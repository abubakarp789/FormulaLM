"""Tests for PROMPT 11: model cards, HF/ModelScope dry-run upload plans, and publishing gates."""

from __future__ import annotations

from pathlib import Path

from formulalm.config import REPO_ROOT
from scripts.publish_hf import F16_GGUF, PRIMARY_GGUF, build_hf_plans
from scripts.publish_hf import main as hf_main
from scripts.publish_modelscope import build_modelscope_plans
from scripts.publish_modelscope import main as ms_main


def test_gguf_model_card_contains_all_required_sections_and_measured_facts():
    card = (REPO_ROOT / "deploy" / "model_cards" / "gguf_README.md").read_text(encoding="utf-8")
    required_snippets = (
        "license: apache-2.0",
        "base_model: Qwen/Qwen3-1.7B",
        "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        "formulalm-qwen3-1.7b-v2-q5_k_m.gguf",
        "ollama create formulalm -f Modelfile",
        "llama-server",
        "<think>",
        "</think>",
        "statistically indistinguishable",
        "informed by v1 error analysis",
        "2.4–5.0 pp",
        "i5-8365U",
        "0.40.18",
        "1,476 MB",
        "11.3 tok/s",
        "1–2 examples",
        "Excel dialect only",
        "N=50",
        "v1-frozen",
    )
    for snippet in required_snippets:
        assert snippet in card, f"Missing required content in gguf_README.md: {snippet!r}"


def test_adapter_model_cards_and_checklist_exist():
    for rel in (
        "deploy/model_cards/adapter_v2_README.md",
        "deploy/model_cards/adapter_v1_README.md",
        "docs/PUBLISHING_CHECKLIST.md",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert len(text) > 500
        assert "apache-2.0" in text.lower() or "Apache-2.0" in text


def test_upload_plans_skip_f16_by_default_and_require_env_tokens_on_execute(
    tmp_path: Path, monkeypatch
):
    # Create dummy local GGUFs (no real upload happens).
    for name in (
        PRIMARY_GGUF,
        "formulalm-qwen3-1.7b-v2-q8_0.gguf",
        "formulalm-qwen3-1.7b-v2-q4_k_m.gguf",
        F16_GGUF,
    ):
        (tmp_path / name).write_bytes(b"GGUF")

    hf_plans = build_hf_plans(models_dir=tmp_path, target="all", include_f16=False)
    ms_plans = build_modelscope_plans(models_dir=tmp_path, target="all", include_f16=False)
    assert len(hf_plans) == 3 and len(ms_plans) == 3
    for p in (hf_plans[0], ms_plans[0]):
        names = [f.path_in_repo for f in p.files]
        assert PRIMARY_GGUF in names
        assert "Modelfile" in names
        assert "README.md" in names
        assert F16_GGUF not in names

    # Including F16 explicitly adds it.
    hf_f16 = build_hf_plans(models_dir=tmp_path, target="gguf", include_f16=True)[0]
    assert F16_GGUF in [f.path_in_repo for f in hf_f16.files]

    # Dry-run succeeds without tokens.
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("MODELSCOPE_API_TOKEN", raising=False)
    assert hf_main(["--models-dir", str(tmp_path), "--target", "all"]) == 0
    assert ms_main(["--models-dir", str(tmp_path), "--target", "all"]) == 0

    # --execute without env token MUST fail cleanly with exit code 2.
    assert hf_main(["--models-dir", str(tmp_path), "--target", "gguf", "--execute"]) == 2
    assert ms_main(["--models-dir", str(tmp_path), "--target", "gguf", "--execute"]) == 2
