"""QLoRA fine-tuning script for FormulaLM (Qwen3-1.7B, non-thinking mode, Unsloth).

Designed for a free Google Colab or Kaggle T4 GPU (16 GB VRAM).
- Loads Qwen/Qwen3-1.7B in 4-bit QLoRA (rank 16, alpha 32, dropout 0, all 7 linear layers).
- Persists non-thinking chat template and trains loss on assistant formula responses ONLY.
- Supports quick 200-example smoke test (--smoke), automatic checkpoint resume (--resume auto),
  CSV train/val loss logging, saved config/run summary, and optional Hugging Face push.

Usage (Colab / Kaggle GPU):
    python scripts/train_qlora.py --smoke
    python scripts/train_qlora.py --run-name qlora_v1 --resume auto
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

DEFAULT_TRAIN_CONFIG = REPO_ROOT / "config" / "train_qlora.yaml"
NON_THINKING_PREFIX = "{% set enable_thinking = false %}\n"
QWEN3_INSTRUCTION_PART = "<|im_start|>user\n"
QWEN3_RESPONSE_PART = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
_CKPT_RE = re.compile(r"^checkpoint-(\d+)$")


# ---------------------------------------------------------------------------
# CPU-testable helpers (no GPU / unsloth import required)
# ---------------------------------------------------------------------------


def load_train_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the QLoRA training YAML configuration."""
    cfg_path = DEFAULT_TRAIN_CONFIG if path is None else Path(path)
    with cfg_path.open(encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}
    required_top = ("seed", "model", "lora", "training", "data")
    missing = [k for k in required_top if k not in cfg]
    if missing:
        raise ValueError(f"Training config missing required sections: {missing}")
    return cfg


def configure_qwen3_non_thinking(tokenizer: Any) -> Any:
    """Persist ``enable_thinking = false`` in the Qwen3 tokenizer chat template."""
    template = getattr(tokenizer, "chat_template", None)
    if not isinstance(template, str) or "enable_thinking" not in template:
        raise ValueError("Expected Qwen3 tokenizer chat_template with 'enable_thinking' support")
    if not template.startswith(NON_THINKING_PREFIX):
        tokenizer.chat_template = NON_THINKING_PREFIX + template
    return tokenizer


def find_latest_checkpoint(checkpoints_dir: str | Path) -> Path | None:
    """Return the highest-step ``checkpoint-<N>`` folder inside ``checkpoints_dir``, if any."""
    root = Path(checkpoints_dir)
    if not root.is_dir():
        return None
    numbered: list[tuple[int, Path]] = []
    for child in root.iterdir():
        if child.is_dir():
            m = _CKPT_RE.match(child.name)
            if m:
                numbered.append((int(m.group(1)), child))
    if not numbered:
        return None
    numbered.sort(key=lambda pair: pair[0])
    return numbered[-1][1]


def write_loss_csv(log_history: list[dict[str, Any]], csv_path: str | Path) -> Path:
    """Write a tidy CSV of training and validation loss history from Trainer.state.log_history."""
    out = Path(csv_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["step", "epoch", "train_loss", "eval_loss", "learning_rate", "grad_norm"]
    rows: list[dict[str, Any]] = []
    for entry in log_history:
        if "loss" not in entry and "eval_loss" not in entry:
            continue
        rows.append(
            {
                "step": entry.get("step", ""),
                "epoch": round(float(entry["epoch"]), 4) if "epoch" in entry else "",
                "train_loss": round(float(entry["loss"]), 6) if "loss" in entry else "",
                "eval_loss": round(float(entry["eval_loss"]), 6) if "eval_loss" in entry else "",
                "learning_rate": entry.get("learning_rate", ""),
                "grad_norm": round(float(entry["grad_norm"]), 4) if "grad_norm" in entry else "",
            }
        )
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out


def detect_runtime_env() -> str:
    """Detect whether we are running on Kaggle, Google Colab, or a local machine."""
    if os.environ.get("KAGGLE_KERNEL_RUN_TYPE") or Path("/kaggle/working").is_dir():
        return "kaggle"
    if os.environ.get("COLAB_RELEASE_TAG") or Path("/content").is_dir():
        return "colab"
    return "local"


def default_output_dir(run_name: str, env_name: str | None = None) -> Path:
    """Choose a sensible persistent output directory for checkpoints and adapters."""
    env = detect_runtime_env() if env_name is None else env_name
    if env == "kaggle":
        return Path("/kaggle/working/formulalm_outputs") / run_name
    if env == "colab" and Path("/content/drive/MyDrive").is_dir():
        return Path("/content/drive/MyDrive/FormulaLM") / run_name
    return REPO_ROOT / "outputs" / run_name


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_TRAIN_CONFIG), help="QLoRA YAML config")
    parser.add_argument("--run-name", default=None, help="Override run name (default from config)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for checkpoints, adapter and logs (Drive/Kaggle recommended)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a fast 200-example smoke test to verify pipeline before full training",
    )
    parser.add_argument("--epochs", type=float, default=None, help="Override num_train_epochs")
    parser.add_argument("--max-steps", type=int, default=-1, help="Override max optimizer steps")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed")
    parser.add_argument("--train-file", default=None, help="Override train JSONL path")
    parser.add_argument("--val-file", default=None, help="Override val JSONL path")
    parser.add_argument(
        "--resume",
        default="none",
        help="'none', 'auto' (latest checkpoint in output-dir/checkpoints), or a checkpoint path",
    )
    parser.add_argument(
        "--push-to-hub",
        action="store_true",
        help="Push final LoRA adapter to Hugging Face Hub using HF_TOKEN env var",
    )
    parser.add_argument("--hub-repo-id", default=None, help="Override HF Hub repo id")
    parser.add_argument(
        "--save-results-copy",
        action="store_true",
        default=True,
        help="Copy lightweight logs (CSV/JSON) into results/train_<run_name>/",
    )
    return parser


# ---------------------------------------------------------------------------
# GPU training pipeline (Unsloth MUST be imported before TRL / Transformers)
# ---------------------------------------------------------------------------


def run_training(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_train_config(args.config)
    seed = int(cfg["seed"] if args.seed is None else args.seed)
    run_name = args.run_name or cfg.get("run_name", "qlora_v1")
    if args.smoke and not run_name.endswith("_smoke"):
        run_name = f"{run_name}_smoke"

    env_name = detect_runtime_env()
    output_dir = (
        Path(args.output_dir) if args.output_dir else default_output_dir(run_name, env_name)
    )
    ckpt_dir = output_dir / "checkpoints"
    adapter_dir = output_dir / "adapter"
    output_dir.mkdir(parents=True, exist_ok=True)

    train_path = Path(args.train_file) if args.train_file else REPO_ROOT / cfg["data"]["train_file"]
    val_path = Path(args.val_file) if args.val_file else REPO_ROOT / cfg["data"]["val_file"]
    if not train_path.is_file() or not val_path.is_file():
        raise FileNotFoundError(
            f"Dataset files not found ({train_path}, {val_path}). "
            "Run `python -m src.data.build_dataset` first."
        )

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "No NVIDIA CUDA GPU detected. Switch your Colab/Kaggle runtime to T4 GPU (not TPU/CPU)."
        )

    # Import Unsloth BEFORE trl/transformers so its kernels and patches register cleanly.
    from unsloth import FastLanguageModel, is_bfloat16_supported
    from unsloth.chat_templates import train_on_responses_only

    started = time.monotonic()
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    mcfg = cfg["model"]
    lcfg = cfg["lora"]
    tcfg = dict(cfg["training"])
    scfg = cfg.get("smoke_test", {})

    if args.smoke:
        train_limit = int(scfg.get("train_examples", 200))
        val_limit = int(scfg.get("val_examples", 50))
        tcfg["num_train_epochs"] = float(scfg.get("num_train_epochs", 1))
        tcfg["logging_steps"] = int(scfg.get("logging_steps", 2))
        tcfg["eval_steps"] = int(scfg.get("eval_steps", 6))
        tcfg["save_steps"] = int(scfg.get("save_steps", 12))
    else:
        train_limit = None
        val_limit = None

    if args.epochs is not None:
        tcfg["num_train_epochs"] = float(args.epochs)

    print(
        f"[FormulaLM] env={env_name} | run={run_name} | smoke={args.smoke} | "
        f"gpu={torch.cuda.get_device_name(0)} | out={output_dir}",
        flush=True,
    )

    # 1. Load base Qwen3-1.7B in 4-bit QLoRA.
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=mcfg["base_id"],
        revision=mcfg.get("base_revision"),
        max_seq_length=int(mcfg["max_seq_length"]),
        dtype=None,  # Auto-selects float16 on T4, bfloat16 on Ampere+
        load_in_4bit=bool(mcfg.get("load_in_4bit", True)),
    )
    configure_qwen3_non_thinking(tokenizer)

    # 2. Attach QLoRA adapters to all 7 linear layers (attention + MLP).
    model = FastLanguageModel.get_peft_model(
        model,
        r=int(lcfg["r"]),
        lora_alpha=int(lcfg["lora_alpha"]),
        lora_dropout=float(lcfg["lora_dropout"]),
        target_modules=list(lcfg["target_modules"]),
        bias=str(lcfg.get("bias", "none")),
        use_gradient_checkpointing=lcfg.get("use_gradient_checkpointing", "unsloth"),
        random_state=seed,
        use_rslora=bool(lcfg.get("use_rslora", False)),
        loftq_config=None,
    )
    model.print_trainable_parameters()

    # 3. Load and render train / val splits in Qwen3 non-thinking chat format.
    train_rows = _read_jsonl(train_path, limit=train_limit)
    val_rows = _read_jsonl(val_path, limit=val_limit)

    def render_chat(example: dict[str, Any]) -> dict[str, str]:
        text = tokenizer.apply_chat_template(
            example["messages"],
            tokenize=False,
            add_generation_prompt=False,
            enable_thinking=False,
        )
        return {"text": text}

    train_ds = Dataset.from_list([{"messages": r["messages"]} for r in train_rows]).map(
        render_chat, remove_columns=["messages"]
    )
    val_ds = Dataset.from_list([{"messages": r["messages"]} for r in val_rows]).map(
        render_chat, remove_columns=["messages"]
    )

    # Verify exact token lengths against max_seq_length (zero silent truncation).
    train_tok_lens = sorted(
        len(tokenizer(t, add_special_tokens=False)["input_ids"]) for t in train_ds["text"]
    )
    val_tok_lens = sorted(
        len(tokenizer(t, add_special_tokens=False)["input_ids"]) for t in val_ds["text"]
    )
    max_seq = int(mcfg["max_seq_length"])
    token_stats = {
        "train_n": len(train_tok_lens),
        "train_p50": train_tok_lens[len(train_tok_lens) // 2],
        "train_p99": train_tok_lens[int(0.99 * (len(train_tok_lens) - 1))],
        "train_max": train_tok_lens[-1],
        "val_n": len(val_tok_lens),
        "val_max": val_tok_lens[-1],
        "max_seq_length": max_seq,
    }
    print(f"[FormulaLM] Token length stats: {token_stats}", flush=True)
    if token_stats["train_max"] > max_seq or token_stats["val_max"] > max_seq:
        raise ValueError(f"Found example longer than max_seq_length={max_seq}: {token_stats}")

    # Verify that the rendered chat text contains the exact response delimiter.
    sample_text = train_ds[0]["text"]
    if QWEN3_RESPONSE_PART not in sample_text:
        raise ValueError(
            f"Expected Qwen3 non-thinking delimiter {QWEN3_RESPONSE_PART!r} in rendered text:\n"
            f"{sample_text}"
        )

    # 4. Configure SFTTrainer and mask loss to assistant responses ONLY.
    use_bf16 = is_bfloat16_supported()
    sft_args = SFTConfig(
        output_dir=str(ckpt_dir),
        dataset_text_field="text",
        max_length=max_seq,
        per_device_train_batch_size=int(tcfg["per_device_train_batch_size"]),
        gradient_accumulation_steps=int(tcfg["gradient_accumulation_steps"]),
        per_device_eval_batch_size=int(tcfg.get("per_device_eval_batch_size", 4)),
        num_train_epochs=float(tcfg["num_train_epochs"]),
        max_steps=int(args.max_steps),
        learning_rate=float(tcfg["learning_rate"]),
        lr_scheduler_type=str(tcfg["lr_scheduler_type"]),
        warmup_ratio=float(tcfg["warmup_ratio"]),
        weight_decay=float(tcfg.get("weight_decay", 0.01)),
        optim=str(tcfg.get("optim", "adamw_8bit")),
        max_grad_norm=float(tcfg.get("max_grad_norm", 1.0)),
        fp16=not use_bf16,
        bf16=use_bf16,
        logging_steps=int(tcfg["logging_steps"]),
        eval_strategy="steps",
        eval_steps=int(tcfg["eval_steps"]),
        save_strategy="steps",
        save_steps=int(tcfg["save_steps"]),
        save_total_limit=int(tcfg.get("save_total_limit", 3)),
        load_best_model_at_end=bool(tcfg.get("load_best_model_at_end", True)),
        metric_for_best_model=str(tcfg.get("metric_for_best_model", "eval_loss")),
        greater_is_better=False,
        seed=seed,
        data_seed=seed,
        report_to="none",
        packing=bool(tcfg.get("packing", False)),
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        args=sft_args,
    )
    trainer = train_on_responses_only(
        trainer,
        instruction_part=QWEN3_INSTRUCTION_PART,
        response_part=QWEN3_RESPONSE_PART,
    )

    # Sanity-check response-only masking on example 0 before starting GPU training.
    first_labels = trainer.train_dataset[0]["labels"]
    unmasked_ids = [tok_id for tok_id in first_labels if tok_id != -100]
    unmasked_text = tokenizer.decode(unmasked_ids, skip_special_tokens=True).strip()
    expected_fml = train_rows[0]["formula"]
    print(
        f"[FormulaLM] Masking check | unmasked={unmasked_text!r} expected={expected_fml!r}",
        flush=True,
    )
    if not unmasked_text.startswith("="):
        raise RuntimeError(
            f"Response-only masking sanity check failed! Decoded unmasked labels: {unmasked_text!r}"
        )

    # 5. Resolve resume checkpoint (for Colab/Kaggle session disconnects).
    resume_ckpt: str | None = None
    if args.resume and args.resume.lower() != "none":
        if args.resume.lower() == "auto":
            latest = find_latest_checkpoint(ckpt_dir)
            if latest is not None:
                resume_ckpt = str(latest)
                print(f"[FormulaLM] Auto-resuming from checkpoint: {resume_ckpt}", flush=True)
            else:
                print(
                    "[FormulaLM] --resume auto: no existing checkpoints, starting fresh.",
                    flush=True,
                )
        else:
            resume_ckpt = args.resume
            print(f"[FormulaLM] Resuming from explicit checkpoint: {resume_ckpt}", flush=True)

    # Save resolved config BEFORE training starts so even interrupted runs are documented.
    resolved_cfg = {
        "run_name": run_name,
        "smoke": args.smoke,
        "seed": seed,
        "env": env_name,
        "model": mcfg,
        "lora": lcfg,
        "training": tcfg,
        "token_stats": token_stats,
        "resume_from_checkpoint": resume_ckpt,
        "git_commit": _git_commit(),
    }
    (output_dir / "train_config.json").write_text(
        json.dumps(resolved_cfg, indent=2) + "\n", encoding="utf-8"
    )

    # 6. Train!
    FastLanguageModel.for_training(model)
    torch.cuda.reset_peak_memory_stats()
    train_start = time.monotonic()
    train_result = trainer.train(resume_from_checkpoint=resume_ckpt)
    train_seconds = time.monotonic() - train_start
    peak_vram_gb = torch.cuda.max_memory_allocated() / (1024**3)

    # 7. Save final (best) adapter + tokenizer + CSV & JSON logs.
    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    log_history = list(trainer.state.log_history)
    loss_csv = write_loss_csv(log_history, output_dir / "loss_log.csv")
    (output_dir / "training_log.json").write_text(
        json.dumps(log_history, indent=2) + "\n", encoding="utf-8"
    )

    pkg_versions: dict[str, str] = {}
    for pkg in (
        "unsloth",
        "unsloth_zoo",
        "torch",
        "transformers",
        "trl",
        "peft",
        "datasets",
        "bitsandbytes",
    ):
        try:
            pkg_versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            pkg_versions[pkg] = "not-installed"

    eval_losses = [e["eval_loss"] for e in log_history if "eval_loss" in e]
    summary = {
        "run_name": run_name,
        "smoke": args.smoke,
        "env": env_name,
        "seed": seed,
        "model_id": mcfg["base_id"],
        "base_revision": mcfg.get("base_revision"),
        "loaded_revision": getattr(model.config, "_commit_hash", None),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "gpu": torch.cuda.get_device_name(0),
        "gpu_total_gb": round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2),
        "peak_vram_gb": round(peak_vram_gb, 2),
        "training_seconds": round(train_seconds, 2),
        "total_seconds": round(time.monotonic() - started, 2),
        "train_metrics": train_result.metrics,
        "best_eval_loss": round(min(eval_losses), 6) if eval_losses else None,
        "best_model_checkpoint": trainer.state.best_model_checkpoint,
        "token_stats": token_stats,
        "data_sha256": {
            "train": _file_sha256(train_path),
            "val": _file_sha256(val_path),
        },
        "package_versions": pkg_versions,
        "adapter_dir": str(adapter_dir),
        "loss_csv": str(loss_csv),
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    # Copy lightweight logs (never weights) into results/train_<run_name>/ for git tracking.
    if args.save_results_copy:
        res_dir = REPO_ROOT / "results" / f"train_{run_name}"
        res_dir.mkdir(parents=True, exist_ok=True)
        for fname in ("loss_log.csv", "training_log.json", "train_config.json", "run_summary.json"):
            shutil.copy2(output_dir / fname, res_dir / fname)

    # 8. Optional Hugging Face Hub push (token from HF_TOKEN env var, never committed).
    if args.push_to_hub:
        hf_token = os.environ.get("HF_TOKEN")
        if not hf_token:
            raise RuntimeError("HF_TOKEN environment variable is required for --push-to-hub")
        repo_id = args.hub_repo_id or cfg.get("hub", {}).get("hf_repo_id")
        if not repo_id:
            raise ValueError("Provide --hub-repo-id or set hub.hf_repo_id in config")
        private = bool(cfg.get("hub", {}).get("private", False))
        print(f"[FormulaLM] Pushing adapter + tokenizer to Hugging Face Hub: {repo_id}", flush=True)
        model.push_to_hub(repo_id, token=hf_token, private=private)
        tokenizer.push_to_hub(repo_id, token=hf_token, private=private)

    print(
        f"[FormulaLM] Done in {train_seconds:.1f}s | peak VRAM={peak_vram_gb:.2f} GB | "
        f"best_eval_loss={summary['best_eval_loss']} | adapter saved to {adapter_dir}",
        flush=True,
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_training(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
