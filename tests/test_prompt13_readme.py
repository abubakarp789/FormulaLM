"""Automated audit of README.md, DECISION.md, and model cards (PROMPT 13 & 13B)."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
CODE_PATH_RE = re.compile(
    r"`((?:notebooks|scripts|src|data|docs|results|deploy|config|app|tests)/[A-Za-z0-9_./\-\*]+|"
    r"LICENSE|README\.md)`"
)
INTENTIONAL_PLACEHOLDERS: set[str] = set()


def test_readme_length_and_first_screen_q5_k_m_headline() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    lines = readme.splitlines()
    assert 120 <= len(lines) <= 250, f"Expected <= 250 lines, got {len(lines)}"

    # First screen (top 25 lines) must state shipped Q5_K_M result plainly + local stats + links.
    first_screen = "\n".join(lines[:25])
    for required_top in (
        "Fresh held-out set",
        "45/50",
        "90.0%",
        "[78.6%, 95.7%]",
        "43/50",
        "86.0%",
        "[73.8%, 93.0%]",
        "23/50",
        "46.0%",
        "[33.0%, 59.6%]",
        "29/50",
        "58.0%",
        "[44.2%, 70.6%]",
        "Q5_K_M",
        "1,199.6 MB",
        "1,476.5 MB",
        "11.3 tok/s",
        "i5-8365U",
        "8 GB RAM",
        "https://github.com/abubakarp789/FormulaLM",
        "https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf",
        "https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf",
        "https://x.com/abubakarp56/status/2126392963379179557",
    ):
        assert required_top in first_screen, f"Missing in first screen of README: {required_top!r}"


def test_readme_numbers_match_saved_results_json() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    fh = json.loads((REPO_ROOT / "results" / "final_headline.json").read_text(encoding="utf-8"))
    qc = json.loads((REPO_ROOT / "results" / "quant_comparison.json").read_text(encoding="utf-8"))
    lb = json.loads(
        (REPO_ROOT / "results" / "local_benchmark" / "local_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    t_v1 = json.loads(
        (REPO_ROOT / "results" / "train_qlora_v1" / "run_summary.json").read_text(encoding="utf-8")
    )
    t_v2 = json.loads(
        (REPO_ROOT / "results" / "train_qlora_v2" / "run_summary.json").read_text(encoding="utf-8")
    )

    rv2 = fh["splits"]["test_real_v2"]["systems"]
    assert f"{rv2['base_zeroshot']['execution_accuracy'] * 100:.1f}%" in readme
    assert f"{rv2['base_5shot']['execution_accuracy'] * 100:.1f}%" in readme
    assert f"{rv2['ft_v2']['execution_accuracy'] * 100:.1f}%" in readme

    for qk in ("q8_0", "q5_k_m", "q4_k_m"):
        sz_mb = qc["artifacts"]["files"][qk]["size_mb"]
        assert f"{sz_mb:,.1f}" in readme

    q5_local = [r for r in lb["results"] if r["quant_key"] == "q5_k_m"][0]
    assert f"{q5_local['load_time_s']:.2f} s" in readme
    assert f"{q5_local['peak_ram_mb']:,.1f} MB" in readme
    assert f"{q5_local['gen_tokens_per_s']:.1f} tok/s" in readme
    assert f"{q5_local['subset_execution_accuracy'] * 100:.1f}%" in readme

    assert f"{t_v1['training_seconds'] / 60:.1f} min" in readme
    assert f"{t_v2['training_seconds'] / 60:.1f} min" in readme
    assert f"{t_v1['peak_vram_gb']:.2f} GB VRAM" in readme
    assert f"{t_v2['peak_vram_gb']:.2f} GB VRAM" in readme


def test_prompt13b_wording_accuracy_across_docs_cards_and_app() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for snippet in (
        "## Quick-Start (5 Steps)",
        "uv run pytest",
        "Abu Bakar",
        "reviewed and approved by Abu Bakar on 26 November 2026",
        "Junaid Shaukat",
        "passed all pre-registered gates",
        "No model-generated paraphrase augmentation or scraped data was used",
        "not fully independent",
        "statistically tied",
        "informed by v1 error analysis",
        "2.4–5.0 pp",
        "1–2 examples",
        "N = 50",
        "100% synthetic",
        "Excel dialect",
        "real_v2_050",
        "Item Count",
        "docs/screenshots/demo_win.png",
        "docs/screenshots/demo_honest_failure.png",
        "docs/screenshots/demo_custom_headers.png",
        "docs/charts/headline_accuracy.png",
        "docs/charts/quant_pareto.png",
        "SpreadsheetBench",
        "12/56",
        "21.4%",
        "src/eval/xlsx_writer.py",
        "https://x.com/abubakarp56/status/2126392963379179557",
        "junaiddshaukat/finetune-anywhere",
        "Apache-2.0",
        "MIT",
    ):
        assert snippet in readme, f"Missing required content in README: {snippet!r}"

    for forbidden in (
        "4 Commands",
        "M Junaid",
        "zero regressions",
        "third-party vendor",
        "unreviewed",
        "spot-checked outputs",
        "Discount %",
        "Pending upload",
        "placeholder until uploaded",
    ):
        assert forbidden not in readme, f"Forbidden wording still in README: {forbidden!r}"

    # Verify 'blind' was replaced with 'fresh held-out set' across docs, results md, cards, and app
    no_blind_files = (
        "README.md",
        "docs/DECISION.md",
        "docs/v2_changelog.md",
        "data/DATASET_CARD.md",
        "data/test_real_v2/README.md",
        "results/ft_v2_comparison.md",
        "results/final_headline.md",
        "results/quant_comparison.md",
        "deploy/model_cards/gguf_README.md",
        "deploy/model_cards/adapter_v2_README.md",
        "deploy/model_cards/adapter_v1_README.md",
        "app/app.py",
    )
    for rel in no_blind_files:
        content = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "blind" not in content.lower(), f"Found 'blind' in {rel}"


def test_all_local_paths_and_notebooks_in_docs_and_cards_exist() -> None:
    target_docs = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "DECISION.md",
        REPO_ROOT / "deploy" / "model_cards" / "gguf_README.md",
        REPO_ROOT / "deploy" / "model_cards" / "adapter_v2_README.md",
        REPO_ROOT / "deploy" / "model_cards" / "adapter_v1_README.md",
    )
    missing: list[tuple[str, str]] = []
    for doc in target_docs:
        text = doc.read_text(encoding="utf-8")
        rel_doc = str(doc.relative_to(REPO_ROOT)).replace("\\", "/")

        for m in MD_LINK_RE.finditer(text):
            target = m.group(1).strip().split("#")[0]
            if not target or target.startswith(("http://", "https://")):
                continue
            if not (doc.parent / target).resolve().exists():
                missing.append((rel_doc, target))

        for m in CODE_PATH_RE.finditer(text):
            p = m.group(1).strip()
            if "*" in p or "{" in p or p in INTENTIONAL_PLACEHOLDERS:
                continue
            if not (REPO_ROOT / p).exists():
                missing.append((rel_doc, p))

    assert not missing, f"Broken local paths/notebooks found: {missing}"
