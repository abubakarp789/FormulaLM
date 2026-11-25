"""Automated audit of README.md against saved files in results/ (PROMPT 13)."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_readme_length_and_structure() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    lines = readme.splitlines()
    assert 120 <= len(lines) <= 250, f"Expected <= 250 lines, got {len(lines)}"

    # First screen (top 25 lines) must contain pitch, blind-set headline, local Q5_K_M stats, links.
    first_screen = "\n".join(lines[:25])
    for required_top in (
        "46.0%",
        "58.0%",
        "88.0%",
        "[33.0%, 59.6%]",
        "[44.2%, 70.6%]",
        "[76.2%, 94.4%]",
        "Q5_K_M",
        "1,199.6 MB",
        "1,476.5 MB",
        "11.3 tok/s",
        "i5-8365U",
        "8 GB RAM",
        "https://github.com/abubakarp789/FormulaLM",
        "https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf",
        "https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf",
        "placeholder until uploaded",
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

    # Verify key headline accuracies from final_headline.json
    rv2 = fh["splits"]["test_real_v2"]["systems"]
    assert f"{rv2['base_zeroshot']['execution_accuracy'] * 100:.1f}%" in readme
    assert f"{rv2['base_5shot']['execution_accuracy'] * 100:.1f}%" in readme
    assert f"{rv2['ft_v2']['execution_accuracy'] * 100:.1f}%" in readme

    # Verify quant file sizes and accuracies from quant_comparison.json
    for qk in ("q8_0", "q5_k_m", "q4_k_m"):
        sz_mb = qc["artifacts"]["files"][qk]["size_mb"]
        assert f"{sz_mb:,.1f}" in readme

    # Verify local benchmark numbers from local_benchmark.json
    q5_local = [r for r in lb["results"] if r["quant_key"] == "q5_k_m"][0]
    assert f"{q5_local['load_time_s']:.2f} s" in readme
    assert f"{q5_local['peak_ram_mb']:,.1f} MB" in readme
    assert f"{q5_local['gen_tokens_per_s']:.1f} tok/s" in readme
    assert f"{q5_local['subset_execution_accuracy'] * 100:.1f}%" in readme

    # Verify training times and VRAM from run_summary.json
    assert f"{t_v1['training_seconds'] / 60:.1f} min" in readme
    assert f"{t_v2['training_seconds'] / 60:.1f} min" in readme
    assert f"{t_v1['peak_vram_gb']:.2f} GB VRAM" in readme
    assert f"{t_v2['peak_vram_gb']:.2f} GB VRAM" in readme


def test_readme_honesty_disclosures_and_placeholders() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for snippet in (
        "statistically tied",
        "informed by v1 error analysis",
        "2.4–5.0 pp",
        "1–2 examples",
        "N = 50",
        "100% synthetic",
        "Excel dialect",
        "real_v2_050",
        "docs/screenshots/demo_win.png",
        "docs/screenshots/demo_honest_failure.png",
        "docs/screenshots/demo_custom_headers.png",
        "Pending upload",
        "unreviewed AI-assisted draft",
        "junaiddshaukat/finetune-anywhere",
        "Apache-2.0",
        "MIT",
    ):
        assert snippet in readme, f"Missing required disclosure/placeholder in README: {snippet!r}"

    # Must NOT falsely claim Abubakar manually reviewed test_real
    assert "reviewed by Abubakar" not in readme
    assert "reviewed/run by Abubakar" not in readme
