"""Resumable, seeded executable evaluation runner for FormulaLM.

Supports multiple model backends:
- ``ollama``       : local Ollama HTTP server (``/api/chat``, ``think=False``, ``temperature=0``)
- ``llamacpp``     : local llama.cpp HTTP server (``/v1/chat/completions``, ``temperature=0``)
- ``transformers`` : Hugging Face ``transformers`` (+ optional PEFT LoRA adapter) for Colab/Kaggle
- ``mock``         : deterministic offline mock backend for testing

Reads either a JSONL split (``data/processed/test_synthetic.jsonl``) or a real-world CSV
(``data/test_real/test_real_DRAFT.csv``), runs greedy inference (``temperature=0``), extracts
the formula via one documented rule, executes it with ``src.eval.executor.run_formula``,
and writes ``results/<run_name>/{predictions.jsonl, metrics.json, report.md, run_config.json}``.

CLI usage:
    uv run python -m src.eval.run_eval --run-name smoke_mock --backend mock \
        --dataset data/test_real/test_real_DRAFT.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

import requests

from formulalm.config import REPO_ROOT, load_config, save_run_config, set_seed
from formulalm.logging_utils import get_logger
from src.data.build_dataset import (
    SYSTEM_PROMPT,
    build_user_prompt,
    format_schema_text,
)
from src.data.templates import load_sheet_contexts
from src.eval.executor import run_formula
from src.eval.normalize import exact_match, values_equal
from src.eval.prompt_parity import STOP_TOKENS, render_qwen3_non_thinking_prompt

# ---------------------------------------------------------------------------
# Fixed non-test few-shot demonstrations (for base few-shot baseline)
# ---------------------------------------------------------------------------

_FEW_SHOT_SCHEMA = (
    "Sheet: sample_ledger (rows 2..50)\n"
    "Columns:\n"
    "A: Entry ID (text)\n"
    "B: Entry Date (date)\n"
    "C: Branch (category)\n"
    "D: Units (integer)\n"
    "E: Revenue (decimal)"
)

FEW_SHOT_EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        build_user_prompt(_FEW_SHOT_SCHEMA, "Total Revenue across all rows."),
        "=SUM(E2:E50)",
    ),
    (
        build_user_prompt(_FEW_SHOT_SCHEMA, "Sum Revenue where Branch is 'North'."),
        '=SUMIF(C2:C50,"North",E2:E50)',
    ),
    (
        build_user_prompt(_FEW_SHOT_SCHEMA, "In row 5, return 'High' if Units > 20 else 'Low'."),
        '=IF(D5>20,"High","Low")',
    ),
    (
        build_user_prompt(
            _FEW_SHOT_SCHEMA, "Look up Revenue for Entry ID 'ENT-1010' using XLOOKUP."
        ),
        '=XLOOKUP("ENT-1010",A2:A50,E2:E50)',
    ),
    (
        build_user_prompt(
            _FEW_SHOT_SCHEMA,
            "Count rows where Branch is 'South' and Entry Date is after 2025-06-01.",
        ),
        '=COUNTIFS(C2:C50,"South",B2:B50,">"&DATE(2025,6,1))',
    ),
)


# ---------------------------------------------------------------------------
# Documented formula extraction (identical across every evaluated system)
# ---------------------------------------------------------------------------

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```(?:[A-Za-z0-9_+-]*)\n?(.*?)```", re.DOTALL)
_INLINE_BACKTICK_EQ_RE = re.compile(r"`(=[^`\n]+)`")


def extract_formula(raw_text: str) -> str:
    """Extract a single Excel formula string from raw model output.

    Steps (applied identically to every model/system):
    1. Strip any ``<think>...</think>`` reasoning blocks.
    2. If a fenced markdown code block contains a line starting with ``=``, return it.
    3. Otherwise return the first line starting with ``=`` (stripping whitespace,
       enclosing backticks, or leading list markers ``- `` / ``* ``).
    4. Otherwise look for an inline backticked `` `=...` `` formula.
    5. Otherwise return the trimmed text as-is (so non-formula chatter fails honestly).
    """
    if not raw_text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", raw_text).strip()
    if not cleaned:
        return ""

    # 1. Check fenced code blocks first.
    for match in _CODE_FENCE_RE.finditer(cleaned):
        block = match.group(1)
        for line in block.splitlines():
            cand = line.strip().strip("`").strip()
            if cand.startswith("="):
                return cand

    # 2. Scan lines for first line beginning with '='.
    for line in cleaned.splitlines():
        cand = line.strip()
        if cand.startswith(("- ", "* ")):
            cand = cand[2:].strip()
        cand = cand.strip("`").strip()
        if cand.startswith("="):
            return cand

    # 3. Inline backticked formula inside prose (e.g., "Use `=SUM(A2:A5)`.").
    m_inline = _INLINE_BACKTICK_EQ_RE.search(cleaned)
    if m_inline:
        return m_inline.group(1).strip()

    return cleaned


def is_raw_format_clean(raw_text: str) -> bool:
    """True if the model followed instructions strictly (only `=...`, no prose/markdown)."""
    s = raw_text.strip()
    return bool(s) and s.startswith("=") and "\n" not in s and "```" not in s and "<think>" not in s


# ---------------------------------------------------------------------------
# Dataset loading (JSONL or CSV)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalExample:
    """Standardized evaluation record loaded from JSONL or CSV."""

    id: str
    sheet_id: str
    category: str
    difficulty: int
    schema_text: str
    request: str
    reference_formula: str
    expected_value: Any
    expected_type: str


def _parse_expected(raw_val: Any, val_type: str) -> Any:
    if raw_val is None or raw_val == "":
        return None
    if val_type == "empty":
        return None
    if val_type == "boolean":
        if isinstance(raw_val, bool):
            return raw_val
        return str(raw_val).strip().upper() == "TRUE"
    if val_type == "date":
        if isinstance(raw_val, date | datetime):
            return raw_val.date() if isinstance(raw_val, datetime) else raw_val
        return date.fromisoformat(str(raw_val).strip())
    if val_type == "number":
        if isinstance(raw_val, int | float) and not isinstance(raw_val, bool):
            return raw_val
        s = str(raw_val).strip()
        try:
            return int(s)
        except ValueError:
            return float(s)
    return str(raw_val)


def load_eval_examples(
    dataset_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> tuple[list[EvalExample], dict[str, Path]]:
    """Load evaluation examples from a JSONL or CSV dataset plus sheet paths."""
    path = Path(dataset_path)
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    contexts = load_sheet_contexts(manifest_path, split="all")
    schema_by_sheet = {c.sheet_id: format_schema_text(c) for c in contexts}
    xlsx_by_sheet = {c.sheet_id: c.xlsx_path for c in contexts}

    examples: list[EvalExample] = []
    suffix = path.suffix.lower()

    if suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            exp_type = rec.get("expected_type", "text")
            examples.append(
                EvalExample(
                    id=str(rec["id"]),
                    sheet_id=str(rec["sheet_id"]),
                    category=str(rec.get("category", "unknown")),
                    difficulty=int(rec.get("difficulty", 0)),
                    schema_text=rec.get("schema_text") or schema_by_sheet[rec["sheet_id"]],
                    request=str(rec["request"]),
                    reference_formula=str(rec["formula"]),
                    expected_value=_parse_expected(rec.get("expected_value"), exp_type),
                    expected_type=exp_type,
                )
            )
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                sid = row["sheet_id"].strip()
                exp_type = (row.get("expected_type") or "text").strip()
                examples.append(
                    EvalExample(
                        id=(row.get("id") or f"row_{idx:04d}").strip(),
                        sheet_id=sid,
                        category=(row.get("category") or "unknown").strip(),
                        difficulty=int(row.get("difficulty") or 0),
                        schema_text=schema_by_sheet[sid],
                        request=row["request"].strip(),
                        reference_formula=row["reference_formula"].strip(),
                        expected_value=_parse_expected(row.get("expected_value"), exp_type),
                        expected_type=exp_type,
                    )
                )
    else:
        raise ValueError(f"Unsupported dataset format '{suffix}' (expected .jsonl or .csv)")

    return examples, xlsx_by_sheet


def load_few_shot_from_train(
    train_jsonl_path: str | Path,
    k: int,
    *,
    seed: int = 42,
    manifest_path: str | Path | None = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Deterministically sample ``k`` diverse few-shot examples strictly from ``train.jsonl``.

    Samples across distinct categories first and verifies every sampled sheet belongs
    to the training split (never held-out test sheets).
    """
    if k <= 0:
        return [], []

    path = Path(train_jsonl_path)
    if not path.is_file():
        raise FileNotFoundError(f"Few-shot training file not found: {path}")

    mpath = (
        REPO_ROOT / "data" / "sheets" / "manifest.json"
        if manifest_path is None
        else Path(manifest_path)
    )
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    test_sheets = set(manifest["test_sheet_ids"])

    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("sheet_id") in test_sheets:
            raise ValueError(f"Leakage detected: {rec.get('id')} uses held-out test sheet")
        # Prefer clean unaugmented examples for few-shot demonstrations.
        if rec.get("augmentation", "none") == "none":
            by_cat[str(rec.get("category", "unknown"))].append(rec)
        all_rows.append(rec)

    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    chosen_ids: set[str] = set()

    # Preferred diverse category order for 5-shot coverage.
    preferred_cats = [
        "aggregation",
        "conditional_aggregation",
        "logic",
        "lookup",
        "date",
        "text",
        "math_and_composition",
    ]
    cats = [c for c in preferred_cats if c in by_cat] + [
        c for c in sorted(by_cat) if c not in preferred_cats
    ]

    for cat in cats:
        if len(chosen) >= k:
            break
        pool = by_cat[cat]
        if pool:
            pick = rng.choice(pool)
            chosen.append(pick)
            chosen_ids.add(str(pick["id"]))

    if len(chosen) < k:
        rem = [r for r in all_rows if str(r["id"]) not in chosen_ids]
        rng.shuffle(rem)
        chosen.extend(rem[: k - len(chosen)])

    pairs = [
        (build_user_prompt(str(r["schema_text"]), str(r["request"])), str(r["formula"]))
        for r in chosen[:k]
    ]
    ids = [str(r["id"]) for r in chosen[:k]]
    return pairs, ids


def build_eval_messages(
    example: EvalExample,
    *,
    few_shot: int = 0,
    few_shot_pairs: list[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build chat messages (system + optional few-shot turns + target user prompt)."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if few_shot > 0:
        demos = (
            few_shot_pairs[:few_shot]
            if few_shot_pairs is not None
            else FEW_SHOT_EXAMPLES[:few_shot]
        )
        for user_demo, asst_demo in demos:
            messages.append({"role": "user", "content": user_demo})
            messages.append({"role": "assistant", "content": asst_demo})
    messages.append(
        {"role": "user", "content": build_user_prompt(example.schema_text, example.request)}
    )
    return messages


# ---------------------------------------------------------------------------
# Model backends (Ollama HTTP, llama.cpp HTTP, Hugging Face transformers, Mock)
# ---------------------------------------------------------------------------


class ModelBackend(Protocol):
    name: str

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
        example: EvalExample | None = None,
    ) -> str: ...


class OllamaBackend:
    """Calls a local Ollama HTTP server (/api/chat) at temperature 0, non-thinking mode."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.name = f"ollama:{model}"

    def provenance(self) -> dict[str, Any]:
        return {"base_model_id": f"ollama:{self.model}", "base_revision": None, "adapter": None}

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
        example: EvalExample | None = None,
    ) -> str:
        del example
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.0,
                "num_predict": max_tokens,
                "seed": seed,
            },
        }
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("message", {}).get("content", ""))


class LlamaCppBackend:
    """Calls a local ``llama-server`` with exact Qwen3 non-thinking prompt parity.

    By default (``use_raw_prompt=True``), sends the exact Qwen3 non-thinking ChatML prompt
    (``<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n``) to ``/completion`` so prompt
    formatting matches Hugging Face training byte-for-byte regardless of server template
    version. With ``use_raw_prompt=False``, calls ``/v1/chat/completions`` with
    ``chat_template_kwargs={"enable_thinking": False}``.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8080",
        model: str = "local",
        timeout: float = 120.0,
        use_raw_prompt: bool = True,
        base_model_id: str | None = None,
        base_revision: str | None = None,
        quantization: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.use_raw_prompt = use_raw_prompt
        self.base_model_id = base_model_id or f"llamacpp:{model}"
        self.base_revision = base_revision
        self.quantization = quantization
        self.name = f"llamacpp:{model}"
        self.last_timings: dict[str, Any] = {}

    def provenance(self) -> dict[str, Any]:
        return {
            "base_model_id": self.base_model_id,
            "base_revision": self.base_revision,
            "adapter": None,
            "quantization": self.quantization,
            "prompt_mode": "raw_qwen3_non_thinking" if self.use_raw_prompt else "chat_completions",
            "enable_thinking": False,
        }

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
        example: EvalExample | None = None,
    ) -> str:
        del example
        if self.use_raw_prompt:
            prompt = render_qwen3_non_thinking_prompt(messages)
            payload: dict[str, Any] = {
                "prompt": prompt,
                "temperature": 0.0,
                "n_predict": max_tokens,
                "seed": seed,
                "stop": list(STOP_TOKENS),
                "cache_prompt": True,
            }
            resp = requests.post(f"{self.base_url}/completion", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            self.last_timings = dict(data.get("timings") or {})
            return str(data.get("content", "")).strip()

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "seed": seed,
            "stop": list(STOP_TOKENS),
            "chat_template_kwargs": {"enable_thinking": False},
        }
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        self.last_timings = dict(data.get("timings") or {})
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", "")).strip()


class LlamaCppPythonBackend:
    """In-process ``llama-cpp-python`` backend using exact Qwen3 non-thinking prompts."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        n_ctx: int = 2048,
        n_gpu_layers: int = -1,
        n_threads: int | None = None,
        quantization: str | None = None,
        base_model_id: str | None = None,
        base_revision: str | None = None,
    ) -> None:
        from llama_cpp import Llama  # type: ignore[import-not-found]

        self.model_path = Path(model_path)
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.quantization = quantization
        self.base_model_id = base_model_id or f"gguf:{self.model_path.name}"
        self.base_revision = base_revision
        self.name = f"llama_cpp_python:{self.model_path.name}"

        kwargs: dict[str, Any] = {
            "model_path": str(self.model_path),
            "n_ctx": n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "verbose": False,
        }
        if n_threads is not None:
            kwargs["n_threads"] = n_threads
        self.llm = Llama(**kwargs)

    def provenance(self) -> dict[str, Any]:
        return {
            "base_model_id": self.base_model_id,
            "base_revision": self.base_revision,
            "adapter": None,
            "gguf_file": self.model_path.name,
            "gguf_size_bytes": self.model_path.stat().st_size
            if self.model_path.is_file()
            else None,
            "quantization": self.quantization,
            "n_ctx": self.n_ctx,
            "n_gpu_layers": self.n_gpu_layers,
            "prompt_mode": "raw_qwen3_non_thinking",
            "enable_thinking": False,
        }

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
        example: EvalExample | None = None,
    ) -> str:
        del example
        prompt = render_qwen3_non_thinking_prompt(messages)
        out = self.llm.create_completion(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.0,
            seed=seed,
            stop=list(STOP_TOKENS),
        )
        choices = out.get("choices") or []
        if not choices:
            return ""
        return str(choices[0].get("text", "")).strip()


class TransformersBackend:
    """Runs Hugging Face ``transformers`` (+ optional PEFT LoRA adapter) with greedy decoding."""

    def __init__(
        self,
        model_id: str,
        *,
        adapter_path: str | None = None,
        revision: str | None = None,
        adapter_revision: str | None = None,
        load_in_4bit: bool = False,
        enable_thinking: bool = False,
    ) -> None:
        import torch  # type: ignore[import-not-found]
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore[import-not-found]

        self.torch = torch
        self.enable_thinking = enable_thinking
        self.model_id = model_id
        self.revision = revision
        self.adapter_path = adapter_path
        self.adapter_revision = adapter_revision
        self.load_in_4bit = load_in_4bit
        self.name = f"transformers:{model_id}" + (f"+{adapter_path}" if adapter_path else "")

        tok_source = adapter_path if adapter_path else model_id
        tok_kwargs: dict[str, Any] = {}
        if adapter_path and adapter_revision:
            tok_kwargs["revision"] = adapter_revision
        elif revision and not adapter_path:
            tok_kwargs["revision"] = revision
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(tok_source, **tok_kwargs)
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_id, **({"revision": revision} if revision else {})
            )
        self.tokenizer.padding_side = "left"
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token_id = self.tokenizer.eos_token_id

        model_kwargs: dict[str, Any] = {"device_map": "auto"}
        if revision:
            model_kwargs["revision"] = revision
        if load_in_4bit:
            model_kwargs["load_in_4bit"] = True
        else:
            model_kwargs["torch_dtype"] = "auto"

        model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
        self.adapter_base_model: str | None = None
        if adapter_path:
            from peft import PeftModel  # type: ignore[import-not-found]

            peft_kwargs: dict[str, Any] = {}
            if adapter_revision:
                peft_kwargs["revision"] = adapter_revision
            model = PeftModel.from_pretrained(model, adapter_path, **peft_kwargs)
            try:
                self.adapter_base_model = str(model.peft_config["default"].base_model_name_or_path)
            except Exception:
                self.adapter_base_model = None
        model.eval()
        self.model = model
        self.dtype = str(getattr(model, "dtype", "unknown"))

    def provenance(self) -> dict[str, Any]:
        """Model identity written into ``run_config.json`` (base id/revision, adapter source)."""
        adapter_commit: str | None = self.adapter_revision
        if self.adapter_path and not Path(self.adapter_path).is_dir():
            try:
                from huggingface_hub import HfApi  # type: ignore[import-not-found]

                info = HfApi().model_info(self.adapter_path, revision=self.adapter_revision)
                adapter_commit = str(info.sha)
            except Exception:
                pass
        return {
            "base_model_id": self.model_id,
            "base_revision": self.revision,
            "adapter": self.adapter_path,
            "adapter_revision": adapter_commit,
            "adapter_config_base_model": self.adapter_base_model,
            "load_in_4bit": self.load_in_4bit,
            "dtype": self.dtype,
            "enable_thinking": self.enable_thinking,
        }

    def _render_prompt(self, messages: list[dict[str, str]]) -> str:
        return str(
            self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=self.enable_thinking,
            )
        )

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
        example: EvalExample | None = None,
    ) -> str:
        del example
        return self.generate_batch([messages], max_tokens=max_tokens, seed=seed)[0]

    def generate_batch(
        self,
        batch_messages: list[list[dict[str, str]]],
        *,
        max_tokens: int,
        seed: int,
    ) -> list[str]:
        self.torch.manual_seed(seed)
        prompts = [self._render_prompt(msgs) for msgs in batch_messages]
        inputs = self.tokenizer(
            prompts, return_tensors="pt", padding=True, add_special_tokens=False
        ).to(self.model.device)
        prompt_len = inputs["input_ids"].shape[1]
        with self.torch.inference_mode():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        results: list[str] = []
        for row_idx in range(len(prompts)):
            gen_ids = out[row_idx, prompt_len:]
            results.append(str(self.tokenizer.decode(gen_ids, skip_special_tokens=True)).strip())
        return results


class MockBackend:
    """Deterministic offline backend for testing the full evaluation pipeline."""

    def __init__(
        self,
        *,
        mode: str = "oracle",
        custom_fn: Callable[[EvalExample], str] | None = None,
    ) -> None:
        self.mode = mode
        self.custom_fn = custom_fn
        self.name = f"mock:{mode}"
        self.call_count = 0

    def provenance(self) -> dict[str, Any]:
        return {"base_model_id": f"mock:{self.mode}", "base_revision": None, "adapter": None}

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
        example: EvalExample | None = None,
    ) -> str:
        del messages, max_tokens, seed
        self.call_count += 1
        if self.custom_fn is not None and example is not None:
            return self.custom_fn(example)
        if example is None:
            return "=SUM(A2:A5)"
        if self.mode == "oracle":
            return example.reference_formula
        if self.mode == "markdown_oracle":
            return f"Here is the formula:\n```excel\n{example.reference_formula}\n```"
        if self.mode == "mixed":
            # Deterministic mix of correct, wrapped, wrong-value and broken outputs for tests.
            idx = sum(ord(ch) for ch in example.id) % 4
            if idx == 0:
                return example.reference_formula
            if idx == 1:
                return f"<think>Let me check.</think>\n```excel\n{example.reference_formula}\n```"
            if idx == 2:
                return "=SUM(1,2,3)"  # syntactically valid but wrong value
            return "=TODAY()"  # unsupported volatile function
        if self.mode == "broken":
            return "=SUM(A2:A5"
        return ""


# ---------------------------------------------------------------------------
# Metrics aggregation and markdown reporting
# ---------------------------------------------------------------------------


def _serialize_value(val: Any) -> Any:
    if isinstance(val, date | datetime):
        return (val.date() if isinstance(val, datetime) else val).isoformat()
    return val


def _summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "syntax_valid_rate": 0.0,
            "exec_ok_rate": 0.0,
            "execution_accuracy": 0.0,
            "exact_match_rate": 0.0,
            "raw_format_ok_rate": 0.0,
            "avg_latency_ms": 0.0,
        }
    latencies = sorted(float(r["latency_ms"]) for r in rows)
    p95_idx = min(n - 1, max(0, math.ceil(0.95 * n) - 1))
    return {
        "n": n,
        "syntax_valid_rate": round(sum(1 for r in rows if r["syntax_valid"]) / n, 4),
        "exec_ok_rate": round(sum(1 for r in rows if r["exec_ok"]) / n, 4),
        "execution_accuracy": round(sum(1 for r in rows if r["exec_correct"]) / n, 4),
        "exact_match_rate": round(sum(1 for r in rows if r["exact_match"]) / n, 4),
        "raw_format_ok_rate": round(sum(1 for r in rows if r["raw_format_ok"]) / n, 4),
        "avg_latency_ms": round(statistics.mean(latencies), 2),
        "p50_latency_ms": round(statistics.median(latencies), 2),
        "p95_latency_ms": round(latencies[p95_idx], 2),
    }


def compute_metrics(
    predictions: list[dict[str, Any]],
    *,
    run_name: str,
    backend_name: str,
    dataset_path: str,
    seed: int,
    few_shot: int,
    max_tokens: int,
    few_shot_ids: list[str] | None = None,
) -> dict[str, Any]:
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_diff: dict[str, list[dict[str, Any]]] = defaultdict(list)
    err_counts: Counter[str] = Counter()

    for row in predictions:
        by_cat[str(row["category"])].append(row)
        by_diff[str(row["difficulty"])].append(row)
        if not row["exec_correct"]:
            err_counts[row["error_type"] or "wrong_value"] += 1

    return {
        "run_name": run_name,
        "backend": backend_name,
        "dataset": dataset_path,
        "seed": seed,
        "few_shot": few_shot,
        "few_shot_ids": few_shot_ids or [],
        "max_tokens": max_tokens,
        "overall": _summarize_group(predictions),
        "by_category": {k: _summarize_group(by_cat[k]) for k in sorted(by_cat)},
        "by_difficulty": {k: _summarize_group(by_diff[k]) for k in sorted(by_diff)},
        "error_breakdown": dict(sorted(err_counts.items())),
    }


def render_report_md(metrics: dict[str, Any], predictions: list[dict[str, Any]]) -> str:
    ov = metrics["overall"]

    def pct(v: float) -> str:
        return f"{100.0 * v:.1f}%"

    lines = [
        f"# Evaluation Report: `{metrics['run_name']}`",
        "",
        f"- **Backend:** `{metrics['backend']}`",
        f"- **Dataset:** `{metrics['dataset']}` ({ov['n']} examples)",
        f"- **Settings:** `seed={metrics['seed']}`, `temperature=0`, "
        f"`few_shot={metrics['few_shot']}`, `max_tokens={metrics['max_tokens']}`",
        "",
        "## Overall Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Examples | {ov['n']} |",
        f"| Syntax valid rate | {pct(ov['syntax_valid_rate'])} |",
        f"| Execution success rate (no runtime error) | {pct(ov['exec_ok_rate'])} |",
        f"| **Execution accuracy** | **{pct(ov['execution_accuracy'])}** |",
        f"| Normalized exact match | {pct(ov['exact_match_rate'])} |",
        f"| Strict raw format (`=...` only) | {pct(ov['raw_format_ok_rate'])} |",
        f"| Avg latency | {ov['avg_latency_ms']:.1f} ms |",
        f"| Median / p95 latency | {ov.get('p50_latency_ms', 0.0):.1f} ms / "
        f"{ov.get('p95_latency_ms', 0.0):.1f} ms |",
        "",
        "## By Category",
        "",
        "| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cat, st in metrics["by_category"].items():
        lines.append(
            f"| `{cat}` | {st['n']} | {pct(st['syntax_valid_rate'])} | "
            f"{pct(st['execution_accuracy'])} | {pct(st['exact_match_rate'])} | "
            f"{st['avg_latency_ms']:.1f} ms |"
        )

    lines.extend(
        [
            "",
            "## By Difficulty",
            "",
            "| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for diff, st in metrics["by_difficulty"].items():
        lines.append(
            f"| {diff} | {st['n']} | {pct(st['syntax_valid_rate'])} | "
            f"{pct(st['execution_accuracy'])} | {pct(st['exact_match_rate'])} | "
            f"{st['avg_latency_ms']:.1f} ms |"
        )

    lines.extend(["", "## Error Breakdown", ""])
    if metrics["error_breakdown"]:
        lines.append("| Error Class | Count |")
        lines.append("|---|---:|")
        for err, cnt in metrics["error_breakdown"].items():
            lines.append(f"| `{err}` | {cnt} |")
    else:
        lines.append("No errors (100% execution accuracy).")

    failures = [p for p in predictions if not p["exec_correct"]][:10]
    if failures:
        lines.extend(["", "## Sample Failures (up to 10)", ""])
        for f in failures:
            lines.append(
                f"- **`{f['id']}`** (`{f['sheet_id']}`, `{f['category']}`/D{f['difficulty']}): "
                f"{f['request']}"
            )
            lines.append(f"  - Reference: `{f['reference_formula']}` → `{f['expected_value']!r}`")
            lines.append(
                f"  - Predicted: `{f['extracted_formula']}` → `{f['predicted_value']!r}` "
                f"(error: `{f['error_type'] or 'wrong_value'}`)"
            )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main evaluation loop (resumable, seeded)
# ---------------------------------------------------------------------------


def evaluate(
    backend: ModelBackend,
    dataset_path: str | Path,
    *,
    run_name: str,
    results_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
    seed: int = 42,
    max_tokens: int = 96,
    few_shot: int = 0,
    few_shot_source: str | Path | None = None,
    batch_size: int = 1,
    limit: int | None = None,
    resume: bool = True,
    overwrite: bool = False,
    formula_timeout: float = 5.0,
) -> dict[str, Any]:
    """Run resumable evaluation and write predictions.jsonl, metrics.json and report.md."""
    set_seed(seed)
    cfg = load_config()
    out_root = cfg["paths"]["results_dir"] if results_root is None else Path(results_root)
    run_dir = out_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    pred_path = run_dir / "predictions.jsonl"
    if overwrite and pred_path.exists():
        pred_path.unlink()

    examples, xlsx_by_sheet = load_eval_examples(dataset_path, manifest_path=manifest_path)
    if limit is not None:
        examples = examples[:limit]

    few_shot_pairs: list[tuple[str, str]] | None = None
    few_shot_ids: list[str] = []
    if few_shot > 0:
        default_train = cfg["paths"]["processed_dir"] / "train.jsonl"
        fs_path = Path(few_shot_source) if few_shot_source is not None else default_train
        if fs_path.is_file():
            few_shot_pairs, few_shot_ids = load_few_shot_from_train(
                fs_path, few_shot, seed=seed, manifest_path=manifest_path
            )
        elif few_shot_source is not None:
            raise FileNotFoundError(f"Few-shot source not found: {fs_path}")

    existing_by_id: dict[str, dict[str, Any]] = {}
    if resume and pred_path.exists():
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                existing_by_id[str(rec["id"])] = rec

    prov_fn = getattr(backend, "provenance", None)
    provenance: dict[str, Any] = prov_fn() if callable(prov_fn) else {}
    save_run_config(
        {
            "run_name": run_name,
            "backend": backend.name,
            "base_model_id": provenance.get("base_model_id"),
            "base_revision": provenance.get("base_revision"),
            "model_provenance": provenance,
            "dataset": str(dataset_path),
            "seed": seed,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "few_shot": few_shot,
            "few_shot_source": str(few_shot_source) if few_shot_source else None,
            "few_shot_ids": few_shot_ids,
            "batch_size": batch_size,
            "limit": limit,
            "resume": resume,
        },
        run_dir,
    )

    pending = [ex for ex in examples if ex.id not in existing_by_id]
    eff_batch = max(1, batch_size) if hasattr(backend, "generate_batch") else 1

    with pred_path.open("a", encoding="utf-8") as pred_f:
        for start in range(0, len(pending), eff_batch):
            chunk = pending[start : start + eff_batch]
            chunk_msgs = [
                build_eval_messages(ex, few_shot=few_shot, few_shot_pairs=few_shot_pairs)
                for ex in chunk
            ]

            t0 = time.perf_counter()
            if eff_batch > 1 and hasattr(backend, "generate_batch"):
                try:
                    raw_outputs = backend.generate_batch(
                        chunk_msgs, max_tokens=max_tokens, seed=seed
                    )
                    gen_errs: list[str | None] = [None] * len(chunk)
                except Exception as exc:
                    raw_outputs = [""] * len(chunk)
                    gen_errs = [f"{type(exc).__name__}: {exc}"] * len(chunk)
                per_item_ms = ((time.perf_counter() - t0) * 1000.0) / len(chunk)
                latencies = [per_item_ms] * len(chunk)
            else:
                raw_outputs = []
                gen_errs = []
                latencies = []
                for ex, msgs in zip(chunk, chunk_msgs, strict=True):
                    t_item = time.perf_counter()
                    try:
                        out_txt = backend.generate(
                            msgs, max_tokens=max_tokens, seed=seed, example=ex
                        )
                        g_err = None
                    except Exception as exc:
                        out_txt = ""
                        g_err = f"{type(exc).__name__}: {exc}"
                    raw_outputs.append(out_txt)
                    gen_errs.append(g_err)
                    latencies.append((time.perf_counter() - t_item) * 1000.0)

            for ex, raw_output, gen_err, latency_ms in zip(
                chunk, raw_outputs, gen_errs, latencies, strict=True
            ):
                extracted = extract_formula(raw_output)
                raw_fmt_ok = is_raw_format_clean(raw_output)

                if gen_err is not None:
                    res_ok = False
                    pred_val = None
                    err_type = "runtime_error"
                    err_msg = f"Backend error: {gen_err}"
                    syntax_valid = False
                else:
                    exec_res = run_formula(
                        extracted, xlsx_by_sheet[ex.sheet_id], timeout=formula_timeout
                    )
                    res_ok = exec_res.ok
                    pred_val = exec_res.value
                    err_type = exec_res.error_type
                    err_msg = exec_res.error_message
                    syntax_valid = exec_res.error_type not in (
                        "syntax_error",
                        "unsupported_function",
                    )

                exec_correct = res_ok and values_equal(pred_val, ex.expected_value)
                em = exact_match(extracted, ex.reference_formula)

                record = {
                    "id": ex.id,
                    "sheet_id": ex.sheet_id,
                    "category": ex.category,
                    "difficulty": ex.difficulty,
                    "request": ex.request,
                    "reference_formula": ex.reference_formula,
                    "expected_value": _serialize_value(ex.expected_value),
                    "expected_type": ex.expected_type,
                    "raw_output": raw_output,
                    "extracted_formula": extracted,
                    "predicted_value": _serialize_value(pred_val),
                    "syntax_valid": syntax_valid,
                    "exec_ok": res_ok,
                    "exec_correct": exec_correct,
                    "exact_match": em,
                    "raw_format_ok": raw_fmt_ok,
                    "error_type": err_type if not exec_correct else None,
                    "error_message": err_msg if not exec_correct else None,
                    "latency_ms": round(latency_ms, 2),
                }
                pred_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                pred_f.flush()
                existing_by_id[ex.id] = record

    ordered_preds = [existing_by_id[ex.id] for ex in examples if ex.id in existing_by_id]
    try:
        ds_display = Path(dataset_path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        ds_display = str(dataset_path)

    metrics = compute_metrics(
        ordered_preds,
        run_name=run_name,
        backend_name=backend.name,
        dataset_path=ds_display,
        seed=seed,
        few_shot=few_shot,
        max_tokens=max_tokens,
        few_shot_ids=few_shot_ids,
    )
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text(render_report_md(metrics, ordered_preds), encoding="utf-8")
    return metrics


def _make_backend(args: argparse.Namespace) -> ModelBackend:
    if args.backend == "ollama":
        if not args.model:
            raise ValueError("--model is required for backend=ollama")
        return OllamaBackend(args.model, base_url=args.base_url, timeout=args.timeout)
    if args.backend == "llamacpp":
        return LlamaCppBackend(
            base_url=args.base_url,
            model=args.model or "local",
            timeout=args.timeout,
            base_revision=args.revision,
        )
    if args.backend == "llama_cpp_python":
        if not args.model:
            raise ValueError("--model (path to .gguf) is required for backend=llama_cpp_python")
        return LlamaCppPythonBackend(
            args.model,
            n_gpu_layers=args.n_gpu_layers,
            base_revision=args.revision,
        )
    if args.backend == "transformers":
        if not args.model:
            raise ValueError("--model is required for backend=transformers")
        return TransformersBackend(
            args.model,
            adapter_path=args.adapter,
            revision=args.revision,
            adapter_revision=args.adapter_revision,
            load_in_4bit=args.load_in_4bit,
            enable_thinking=False,
        )
    if args.backend == "mock":
        return MockBackend(mode=args.mock_mode)
    raise ValueError(f"Unknown backend: {args.backend!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True, help="Output folder name under results/")
    parser.add_argument(
        "--backend",
        choices=("ollama", "llamacpp", "llama_cpp_python", "transformers", "mock"),
        required=True,
    )
    parser.add_argument("--dataset", required=True, help="Path to JSONL or CSV dataset")
    parser.add_argument("--model", default=None, help="Model name/id for ollama/transformers")
    parser.add_argument("--revision", default=None, help="Optional HF revision commit hash")
    parser.add_argument("--adapter", default=None, help="Optional PEFT adapter path")
    parser.add_argument(
        "--adapter-revision", default=None, help="Optional HF commit hash for a Hub adapter"
    )
    parser.add_argument("--load-in-4bit", action="store_true", help="4-bit load for transformers")
    parser.add_argument(
        "--n-gpu-layers",
        type=int,
        default=-1,
        help="GPU offload layers for llama_cpp_python (-1 = all, 0 = CPU only)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Server URL (default http://localhost:11434 for ollama, :8080 for llamacpp)",
    )
    parser.add_argument(
        "--mock-mode", default="oracle", choices=("oracle", "markdown_oracle", "mixed", "broken")
    )
    parser.add_argument("--max-tokens", type=int, default=96, help="Max new tokens")
    parser.add_argument(
        "--few-shot", type=int, default=0, help="Number of few-shot examples (0..5)"
    )
    parser.add_argument(
        "--few-shot-source",
        default=None,
        help="Train JSONL to draw few-shot demos from (default: data/processed/train.jsonl)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Batch size for transformers backend (e.g. 8 on T4 GPU)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only first N examples")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed")
    parser.add_argument("--timeout", type=float, default=120.0, help="Backend request timeout (s)")
    parser.add_argument("--results-dir", default=None, help="Override results root directory")
    parser.add_argument("--overwrite", action="store_true", help="Discard existing predictions")
    args = parser.parse_args(argv)

    cfg = load_config()
    seed = cfg["seed"] if args.seed is None else args.seed
    if args.base_url is None:
        args.base_url = (
            "http://localhost:8080" if args.backend == "llamacpp" else "http://localhost:11434"
        )

    log = get_logger("formulalm.eval", log_file=cfg["paths"]["logs_dir"] / f"{args.run_name}.log")
    backend = _make_backend(args)
    log.info(
        "Starting eval run=%s backend=%s dataset=%s seed=%d few_shot=%d max_tokens=%d batch=%d",
        args.run_name,
        backend.name,
        args.dataset,
        seed,
        args.few_shot,
        args.max_tokens,
        args.batch_size,
    )
    metrics = evaluate(
        backend=backend,
        dataset_path=args.dataset,
        run_name=args.run_name,
        results_root=args.results_dir,
        seed=seed,
        max_tokens=args.max_tokens,
        few_shot=args.few_shot,
        few_shot_source=args.few_shot_source,
        batch_size=args.batch_size,
        limit=args.limit,
        resume=not args.overwrite,
        overwrite=args.overwrite,
    )
    ov = metrics["overall"]
    log.info(
        "Done run=%s | n=%d | syntax=%.1f%% | exec_acc=%.1f%% | exact=%.1f%% | avg_lat=%.1fms",
        args.run_name,
        ov["n"],
        100 * ov["syntax_valid_rate"],
        100 * ov["execution_accuracy"],
        100 * ov["exact_match_rate"],
        ov["avg_latency_ms"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
