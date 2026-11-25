"""Publish FormulaLM GGUFs, Modelfiles, model cards, and LoRA adapters to ModelScope.

Safety guarantees:
- Reads ``MODELSCOPE_API_TOKEN`` strictly from the environment (never hardcoded/committed).
- **Dry-run by default:** checks local file sizes and prints the exact upload plan without
  uploading anything unless ``--execute`` is passed.
- **Skips F16 GGUF by default** (pass ``--include-f16`` only if explicitly requested).
- Prompts for interactive confirmation before each repository upload unless ``--yes`` is set.

Targets (under ModelScope namespace ``abubakar56``):
- ``gguf``       -> ``abubakar56/formulalm-qwen3-1.7b-gguf`` (Q5_K_M primary, Q8_0/Q4_K_M,
  Modelfiles, README.md)
- ``adapter-v2`` -> ``abubakar56/formulalm-qwen3-1.7b-lora-v2`` (HF ``e2dd7e81`` + README.md)
- ``adapter-v1`` -> ``abubakar56/formulalm-qwen3-1.7b-lora`` (HF ``d9909249`` + README.md)
- ``all``        -> runs all three in order, confirming before each upload.

Usage:
    # 1. Inspect file sizes and upload plan (no network writes):
    uv run python scripts/publish_modelscope.py --target all

    # 2. Execute upload after confirmation (requires $env:MODELSCOPE_API_TOKEN):
    uv run python scripts/publish_modelscope.py --target gguf --execute
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.publish_hf import (  # noqa: E402
    ADAPTER_V1_REPO,
    ADAPTER_V2_REPO,
    F16_GGUF,
    GGUF_REPO,
    MODELFILES,
    OPTIONAL_GGUFS,
    PRIMARY_GGUF,
    V1_ADAPTER_REV,
    V2_ADAPTER_REV,
    UploadFile,
    UploadPlan,
    print_plans,
)

MS_NAMESPACE = "abubakar56"
MS_GGUF_REPO = f"{MS_NAMESPACE}/formulalm-qwen3-1.7b-gguf"
MS_ADAPTER_V2_REPO = f"{MS_NAMESPACE}/formulalm-qwen3-1.7b-lora-v2"
MS_ADAPTER_V1_REPO = f"{MS_NAMESPACE}/formulalm-qwen3-1.7b-lora"


def build_modelscope_plans(
    *,
    models_dir: Path,
    target: str = "all",
    include_f16: bool = False,
) -> list[UploadPlan]:
    """Construct ModelScope upload plans and check file sizes."""
    plans: list[UploadPlan] = []
    targets = ("gguf", "adapter-v2", "adapter-v1") if target == "all" else (target,)

    for t in targets:
        if t == "gguf":
            files: list[UploadFile] = [
                UploadFile(REPO_ROOT / "deploy" / "model_cards" / "gguf_README.md", "README.md"),
            ]
            for mf in MODELFILES:
                files.append(UploadFile(REPO_ROOT / "deploy" / mf, mf))
            files.append(UploadFile(models_dir / PRIMARY_GGUF, PRIMARY_GGUF, required=True))
            for opt in OPTIONAL_GGUFS:
                files.append(UploadFile(models_dir / opt, opt, required=False))
            if include_f16:
                files.append(UploadFile(models_dir / F16_GGUF, F16_GGUF, required=False))
            plans.append(
                UploadPlan(
                    target="gguf",
                    repo_id=MS_GGUF_REPO,
                    files=tuple(files),
                    note=(
                        "Primary Q5_K_M GGUF + optional Q8_0/Q4_K_M + Modelfiles + README.md "
                        "(F16 skipped unless --include-f16)."
                    ),
                )
            )
        elif t == "adapter-v2":
            plans.append(
                UploadPlan(
                    target="adapter-v2",
                    repo_id=MS_ADAPTER_V2_REPO,
                    files=(
                        UploadFile(
                            REPO_ROOT / "deploy" / "model_cards" / "adapter_v2_README.md",
                            "README.md",
                        ),
                    ),
                    tag_name="v2-ship",
                    tag_revision=V2_ADAPTER_REV,
                    note=(
                        f"Stages ~69.8 MB adapter snapshot from HF {ADAPTER_V2_REPO}@"
                        f"{V2_ADAPTER_REV[:8]} + README.md and uploads to ModelScope."
                    ),
                )
            )
        elif t == "adapter-v1":
            plans.append(
                UploadPlan(
                    target="adapter-v1",
                    repo_id=MS_ADAPTER_V1_REPO,
                    files=(
                        UploadFile(
                            REPO_ROOT / "deploy" / "model_cards" / "adapter_v1_README.md",
                            "README.md",
                        ),
                    ),
                    tag_name="v1-frozen",
                    tag_revision=V1_ADAPTER_REV,
                    note=(
                        f"Stages ~69.8 MB frozen fallback from HF {ADAPTER_V1_REPO}@"
                        f"{V1_ADAPTER_REV[:8]} + README.md and uploads to ModelScope."
                    ),
                )
            )
        else:
            raise ValueError(f"Unknown target: {t!r}")
    return plans


def _ensure_ms_repo(api: Any, repo_id: str, chinese_name: str) -> None:
    try:
        from modelscope.hub.constants import Licenses, ModelVisibility  # type: ignore[import-not-found]

        visibility = ModelVisibility.PUBLIC
        license_val = Licenses.APACHE_V2
    except Exception:
        visibility = 5
        license_val = "Apache License 2.0"

    try:
        api.create_model(
            repo_id,
            visibility=visibility,
            license=license_val,
            chinese_name=chinese_name,
        )
        print(f"Created public ModelScope repo: {repo_id}")
    except Exception as exc:
        # ModelScope raises if repo already exists; continue to upload.
        print(f"ModelScope create_model note ({repo_id}): {exc}")


def execute_modelscope_plans(
    plans: list[UploadPlan],
    *,
    token: str,
    assume_yes: bool = False,
) -> dict[str, Any]:
    """Upload planned files/adapters to ModelScope after per-repo confirmation."""
    from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
    from modelscope.hub.api import HubApi  # type: ignore[import-not-found]

    api = HubApi()
    api.login(token)
    summary: dict[str, Any] = {"uploaded": [], "skipped": []}

    for plan in plans:
        if plan.missing_required:
            missing = ", ".join(str(f.local_path) for f in plan.missing_required)
            raise FileNotFoundError(f"Required file(s) missing for {plan.repo_id}: {missing}")

        if not assume_yes:
            ans = (
                input(
                    f"\nConfirm upload to ModelScope repo '{plan.repo_id}' "
                    f"(local payload {plan.total_mb:.2f} MB; adapters stage ~70 MB)? [y/N]: "
                )
                .strip()
                .lower()
            )
            if ans not in ("y", "yes"):
                print(f"Skipped {plan.repo_id}.")
                summary["skipped"].append(plan.repo_id)
                continue

        _ensure_ms_repo(api, plan.repo_id, f"FormulaLM ({plan.target})")

        if plan.target == "gguf":
            for f in plan.files:
                if not f.exists:
                    continue
                print(
                    f"Uploading {f.path_in_repo} ({f.size_mb:.2f} MB) -> {plan.repo_id}...",
                    flush=True,
                )
                api.upload_file(
                    repo_id=plan.repo_id,
                    path_or_fileobj=str(f.local_path),
                    path_in_repo=f.path_in_repo,
                    commit_message=f"publish: upload {f.path_in_repo} (FormulaLM v2-ship)",
                )
        else:
            hf_src = ADAPTER_V2_REPO if plan.target == "adapter-v2" else ADAPTER_V1_REPO
            hf_rev = V2_ADAPTER_REV if plan.target == "adapter-v2" else V1_ADAPTER_REV
            card_path = plan.files[0].local_path
            with tempfile.TemporaryDirectory(prefix=f"ms_{plan.target}_") as tdir:
                stage = Path(tdir) / "stage"
                print(f"Staging {hf_src}@{hf_rev[:8]} into {stage}...", flush=True)
                snapshot_download(
                    repo_id=hf_src,
                    revision=hf_rev,
                    local_dir=str(stage),
                )
                shutil.copy2(card_path, stage / "README.md")
                total_stage_mb = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) / (
                    1024 * 1024
                )
                print(
                    f"Uploading staged folder ({total_stage_mb:.2f} MB) -> {plan.repo_id}...",
                    flush=True,
                )
                api.upload_folder(
                    repo_id=plan.repo_id,
                    folder_path=str(stage),
                    commit_message=f"publish: FormulaLM {plan.target} ({hf_rev[:8]}) + model card",
                )
        summary["uploaded"].append(plan.repo_id)

    _ = GGUF_REPO
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
        "--execute",
        action="store_true",
        help="Actually upload to ModelScope (without this flag, dry-run only)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive per-repo confirmation prompt (use only after user confirms)",
    )
    args = parser.parse_args(argv)

    plans = build_modelscope_plans(
        models_dir=Path(args.models_dir),
        target=args.target,
        include_f16=args.include_f16,
    )
    print_plans(plans, platform_name="ModelScope")

    if not args.execute:
        print("\n[DRY-RUN] No files were uploaded. Re-run with --execute after confirmation.")
        return 0

    token = os.environ.get("MODELSCOPE_API_TOKEN", "").strip()
    if not token:
        print("ERROR: MODELSCOPE_API_TOKEN environment variable is not set.", file=sys.stderr)
        return 2

    execute_modelscope_plans(plans, token=token, assume_yes=args.yes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
