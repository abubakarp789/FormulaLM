"""Publish FormulaLM model cards, GGUFs, Modelfiles, and LoRA adapters to Hugging Face.

Safety guarantees:
- Reads ``HF_TOKEN`` strictly from the environment (never from code or committed files).
- **Dry-run by default:** checks local file sizes and prints the exact upload plan without
  contacting Hugging Face for writes unless ``--execute`` is passed.
- **Skips F16 GGUF by default** (pass ``--include-f16`` only if explicitly requested).
- Prompts for interactive confirmation before each repository upload unless ``--yes`` is set.

Targets:
- ``gguf``       -> ``abubakar56/formulalm-qwen3-1.7b-gguf`` (Q5_K_M primary, Q8_0/Q4_K_M,
  Modelfiles, README.md)
- ``adapter-v2`` -> ``abubakar56/formulalm-qwen3-1.7b-lora-v2`` (README.md + tag ``v2-ship``)
- ``adapter-v1`` -> ``abubakar56/formulalm-qwen3-1.7b-lora`` (README.md + tag ``v1-frozen``)
- ``all``        -> runs all three in order, confirming before each upload.

Usage:
    # 1. Inspect file sizes and upload plan (no network writes):
    uv run python scripts/publish_hf.py --target all

    # 2. Execute upload after confirmation (requires $env:HF_TOKEN):
    uv run python scripts/publish_hf.py --target gguf --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

HF_NAMESPACE = "abubakar56"
GGUF_REPO = f"{HF_NAMESPACE}/formulalm-qwen3-1.7b-gguf"
ADAPTER_V2_REPO = f"{HF_NAMESPACE}/formulalm-qwen3-1.7b-lora-v2"
ADAPTER_V1_REPO = f"{HF_NAMESPACE}/formulalm-qwen3-1.7b-lora"

V2_ADAPTER_REV = "e2dd7e8115406ffcdbbdfa60d6f2f10b4aaf2595"
V1_ADAPTER_REV = "d9909249c496134ecc72e1d77bdc22e6e0461537"

PRIMARY_GGUF = "formulalm-qwen3-1.7b-v2-q5_k_m.gguf"
OPTIONAL_GGUFS = (
    "formulalm-qwen3-1.7b-v2-q8_0.gguf",
    "formulalm-qwen3-1.7b-v2-q4_k_m.gguf",
)
F16_GGUF = "formulalm-qwen3-1.7b-v2-f16.gguf"
MODELFILES = ("Modelfile", "Modelfile.Q5_K_M", "Modelfile.Q8_0", "Modelfile.Q4_K_M")


@dataclass(frozen=True)
class UploadFile:
    local_path: Path
    path_in_repo: str
    required: bool = True

    @property
    def exists(self) -> bool:
        return self.local_path.is_file()

    @property
    def size_bytes(self) -> int:
        return self.local_path.stat().st_size if self.exists else 0

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)


@dataclass(frozen=True)
class UploadPlan:
    target: str
    repo_id: str
    files: tuple[UploadFile, ...]
    tag_name: str | None = None
    tag_revision: str | None = None
    note: str = ""

    @property
    def total_mb(self) -> float:
        return round(sum(f.size_bytes for f in self.files) / (1024 * 1024), 2)

    @property
    def missing_required(self) -> list[UploadFile]:
        return [f for f in self.files if f.required and not f.exists]


def build_hf_plans(
    *,
    models_dir: Path,
    target: str = "all",
    include_f16: bool = False,
    cards_only: bool = False,
) -> list[UploadPlan]:
    """Construct upload plans and check file sizes for requested HF target(s)."""
    plans: list[UploadPlan] = []
    targets = ("gguf", "adapter-v2", "adapter-v1") if target == "all" else (target,)

    for t in targets:
        if t == "gguf":
            files: list[UploadFile] = [
                UploadFile(REPO_ROOT / "deploy" / "model_cards" / "gguf_README.md", "README.md"),
            ]
            for mf in MODELFILES:
                files.append(UploadFile(REPO_ROOT / "deploy" / mf, mf))
            if not cards_only:
                files.append(UploadFile(models_dir / PRIMARY_GGUF, PRIMARY_GGUF, required=True))
                for opt in OPTIONAL_GGUFS:
                    files.append(UploadFile(models_dir / opt, opt, required=False))
                if include_f16:
                    files.append(UploadFile(models_dir / F16_GGUF, F16_GGUF, required=False))
            plans.append(
                UploadPlan(
                    target="gguf",
                    repo_id=GGUF_REPO,
                    files=tuple(files),
                    note=(
                        "Primary Q5_K_M GGUF + optional Q8_0/Q4_K_M + Modelfiles + model card "
                        "(F16 skipped unless --include-f16)."
                    ),
                )
            )
        elif t == "adapter-v2":
            plans.append(
                UploadPlan(
                    target="adapter-v2",
                    repo_id=ADAPTER_V2_REPO,
                    files=(
                        UploadFile(
                            REPO_ROOT / "deploy" / "model_cards" / "adapter_v2_README.md",
                            "README.md",
                        ),
                    ),
                    tag_name="v2-ship",
                    tag_revision=V2_ADAPTER_REV,
                    note=(
                        "Updates model card README.md and tags existing public v2 adapter "
                        "weights as v2-ship."
                    ),
                )
            )
        elif t == "adapter-v1":
            plans.append(
                UploadPlan(
                    target="adapter-v1",
                    repo_id=ADAPTER_V1_REPO,
                    files=(
                        UploadFile(
                            REPO_ROOT / "deploy" / "model_cards" / "adapter_v1_README.md",
                            "README.md",
                        ),
                    ),
                    tag_name="v1-frozen",
                    tag_revision=V1_ADAPTER_REV,
                    note=(
                        "Updates model card README.md and tags existing public frozen v1 "
                        "fallback as v1-frozen."
                    ),
                )
            )
        else:
            raise ValueError(f"Unknown target: {t!r}")
    return plans


def print_plans(plans: list[UploadPlan], *, platform_name: str = "Hugging Face") -> None:
    print(f"=== {platform_name} Upload Plan (File Size Check) ===")
    for plan in plans:
        print(f"\nTarget: {plan.target} -> {plan.repo_id}")
        if plan.note:
            print(f"  Note: {plan.note}")
        if plan.tag_name:
            print(f"  Tag:  {plan.tag_name} -> {plan.tag_revision}")
        for f in plan.files:
            status = (
                f"{f.size_mb:8.2f} MB"
                if f.exists
                else ("MISSING!" if f.required else "skip (not local)")
            )
            print(f"    {f.path_in_repo:<40} {status:>18}  <- {f.local_path}")
        print(f"  Total local payload: {plan.total_mb:.2f} MB")


def execute_hf_plans(
    plans: list[UploadPlan],
    *,
    token: str,
    assume_yes: bool = False,
    prune_f16: bool = False,
) -> dict[str, Any]:
    """Upload planned files to Hugging Face Hub after explicit confirmation per repo."""
    from huggingface_hub import HfApi  # type: ignore[import-not-found]

    api = HfApi(token=token)
    summary: dict[str, Any] = {"uploaded": [], "skipped": []}

    for plan in plans:
        if plan.missing_required:
            missing = ", ".join(str(f.local_path) for f in plan.missing_required)
            raise FileNotFoundError(f"Required file(s) missing for {plan.repo_id}: {missing}")

        if not assume_yes:
            ans = (
                input(
                    f"\nConfirm upload to Hugging Face repo '{plan.repo_id}' "
                    f"({plan.total_mb:.2f} MB)? [y/N]: "
                )
                .strip()
                .lower()
            )
            if ans not in ("y", "yes"):
                print(f"Skipped {plan.repo_id}.")
                summary["skipped"].append(plan.repo_id)
                continue

        api.create_repo(plan.repo_id, repo_type="model", exist_ok=True, private=False)
        api.update_repo_visibility(plan.repo_id, private=False, repo_type="model")
        for f in plan.files:
            if not f.exists:
                continue
            print(
                f"Uploading {f.path_in_repo} ({f.size_mb:.2f} MB) -> {plan.repo_id}...", flush=True
            )
            api.upload_file(
                path_or_fileobj=str(f.local_path),
                path_in_repo=f.path_in_repo,
                repo_id=plan.repo_id,
                repo_type="model",
                commit_message=f"publish: upload {f.path_in_repo} (FormulaLM v2-ship)",
            )
        if plan.target == "gguf" and prune_f16:
            try:
                api.delete_file(
                    path_in_repo=F16_GGUF,
                    repo_id=plan.repo_id,
                    repo_type="model",
                    commit_message="chore: remove unshipped F16 GGUF per shipping policy",
                )
                print(f"Removed {F16_GGUF} from {plan.repo_id}.")
            except Exception as exc:
                print(f"Note: could not delete {F16_GGUF}: {exc}")

        if plan.tag_name and plan.tag_revision:
            api.create_tag(
                plan.repo_id,
                tag=plan.tag_name,
                revision=plan.tag_revision,
                repo_type="model",
                exist_ok=True,
            )
            print(f"Tagged {plan.repo_id}@{plan.tag_revision[:8]} as '{plan.tag_name}'.")

        summary["uploaded"].append(plan.repo_id)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("gguf", "adapter-v2", "adapter-v1", "all"),
        default="all",
    )
    parser.add_argument("--models-dir", default="models/gguf_v2")
    parser.add_argument(
        "--include-f16",
        action="store_true",
        help="Include the 3.29 GB F16 GGUF (skipped by default)",
    )
    parser.add_argument(
        "--cards-only",
        action="store_true",
        help="Upload only README.md and Modelfiles (skip re-uploading GGUF binaries already on HF)",
    )
    parser.add_argument(
        "--prune-f16",
        action="store_true",
        help="Optionally delete formulalm-qwen3-1.7b-v2-f16.gguf from HF GGUF repo",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually upload to Hugging Face (without this flag, dry-run only)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive per-repo confirmation prompt (use only after user confirms)",
    )
    args = parser.parse_args(argv)

    plans = build_hf_plans(
        models_dir=Path(args.models_dir),
        target=args.target,
        include_f16=args.include_f16,
        cards_only=args.cards_only,
    )
    print_plans(plans, platform_name="Hugging Face")

    if not args.execute:
        print("\n[DRY-RUN] No files were uploaded. Re-run with --execute after confirmation.")
        return 0

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        print("ERROR: HF_TOKEN environment variable is not set.", file=sys.stderr)
        return 2

    execute_hf_plans(plans, token=token, assume_yes=args.yes, prune_f16=args.prune_f16)
    return 0


if __name__ == "__main__":
    sys.exit(main())
