"""Tests for PROMPT 9B: provenance, test_real_v2 validation, Wilson CI & v1-vs-v2 comparison."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from formulalm.config import REPO_ROOT
from src.eval.compare_v1_v2 import (
    DECISION_RULE_TEXT,
    INFORMED_LABEL,
    build_headline_summary,
    build_v1_v2_comparison,
    render_headline_markdown,
    render_v1_v2_markdown,
    wilson_ci,
)
from src.eval.run_eval import evaluate
from src.eval.test_real_v2 import (
    load_annotated_test_real_v2,
    load_raw_requests,
    validate_annotated_test_real_v2,
    validate_raw_requests,
)


class _StubProvenanceBackend:
    """Minimal backend exposing explicit HF model id + revision provenance for testing."""

    name = "transformers:Qwen/Qwen3-1.7B+abubakar56/formulalm-qwen3-1.7b-lora-v2"

    def provenance(self) -> dict[str, Any]:
        return {
            "base_model_id": "Qwen/Qwen3-1.7B",
            "base_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
            "adapter": "abubakar56/formulalm-qwen3-1.7b-lora-v2",
            "adapter_revision": "e2dd7e8115406ffcdbbdfa60d6f2f10b4aaf2595",
        }

    def generate(self, messages, *, max_tokens, seed, example=None) -> str:
        del messages, max_tokens, seed
        return example.reference_formula if example is not None else "=SUM(A2:A5)"


def test_run_eval_writes_base_model_id_and_revision_to_run_config(tmp_path: Path):
    evaluate(
        _StubProvenanceBackend(),
        REPO_ROOT / "data" / "test_real" / "test_real_DRAFT.csv",
        run_name="prov_test",
        results_root=tmp_path,
        limit=2,
        formula_timeout=30.0,
    )
    rc = json.loads((tmp_path / "prov_test" / "run_config.json").read_text(encoding="utf-8"))
    cfg = rc["config"]
    assert cfg["base_model_id"] == "Qwen/Qwen3-1.7B"
    assert cfg["base_revision"] == "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
    assert cfg["model_provenance"]["adapter"] == "abubakar56/formulalm-qwen3-1.7b-lora-v2"


def test_raw_requests_loader_and_validator(tmp_path: Path):
    good = tmp_path / "requests.csv"
    with good.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sheet_id", "request"])
        w.writerow(["sales_retail_store", "Total revenue across all rows"])
        w.writerow(["hr_employee_roster", "Count employees in Engineering"])

    loaded = load_raw_requests(good)
    assert len(loaded) == 2
    assert loaded[0].id == "real_v2_001"
    assert loaded[0].sheet_id == "sales_retail_store"

    rep = validate_raw_requests(good)
    assert rep["error_count"] == 0
    assert rep["total_rows"] == 2
    assert rep["by_sheet"] == {"hr_employee_roster": 1, "sales_retail_store": 1}

    # Reject non-held-out (training) sheet_id and duplicate requests.
    bad = tmp_path / "bad_requests.csv"
    with bad.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sheet_id", "request"])
        w.writerow(["sales_b2b_pipeline", "Total deal value"])  # train sheet -> leakage error
        w.writerow(["sales_retail_store", "Duplicate ask"])
        w.writerow(["sales_retail_store", "duplicate ask"])

    bad_rep = validate_raw_requests(bad)
    assert bad_rep["error_count"] >= 2
    with pytest.raises(ValueError, match="not in held-out"):
        load_raw_requests(bad)


def test_annotated_test_real_v2_flags_ambiguous_and_verifies_valid(tmp_path: Path):
    # Take 2 verified rows from test_real_DRAFT.csv to build a valid annotated fixture.
    src_csv = REPO_ROOT / "data" / "test_real" / "test_real_DRAFT.csv"
    with src_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))[:2]

    valid_csv = tmp_path / "test_real_v2.csv"
    fieldnames = list(rows[0].keys())
    with valid_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    examples, _ = load_annotated_test_real_v2(valid_csv)
    assert len(examples) == 2
    rep = validate_annotated_test_real_v2(valid_csv, timeout=30.0)
    assert rep["error_count"] == 0

    # Flagging a row as AMBIGUOUS must fail validation instead of silently passing.
    rows[1] = dict(rows[1], notes="AMBIGUOUS: unclear which date column")
    ambig_csv = tmp_path / "ambig.csv"
    with ambig_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    ambig_rep = validate_annotated_test_real_v2(ambig_csv, timeout=30.0)
    assert ambig_rep["error_count"] >= 1
    assert len(ambig_rep["flagged_unresolved"]) == 1


def test_wilson_ci_bounds_and_accuracy():
    # Standard known value: 73/80 = 0.9125 -> 95% Wilson CI ≈ [0.8302, 0.9570]
    lo, hi = wilson_ci(73, 80)
    assert 0.825 < lo < 0.835
    assert 0.953 < hi < 0.961
    assert lo < 73 / 80 < hi
    assert wilson_ci(0, 0) == (0.0, 0.0)
    lo_full, hi_full = wilson_ci(50, 50)
    assert hi_full == 1.0 and 0.92 < lo_full < 0.94


def _write_fake_run(root: Path, run_name: str, cats_k_n: dict[str, tuple[int, int]]) -> None:
    run_dir = root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    preds = []
    by_cat = {}
    total_k = 0
    total_n = 0
    idx = 0
    for cat, (k, n) in cats_k_n.items():
        total_k += k
        total_n += n
        by_cat[cat] = {
            "n": n,
            "syntax_valid_rate": 1.0,
            "exec_ok_rate": 1.0,
            "execution_accuracy": round(k / n, 4),
            "exact_match_rate": round(k / n, 4),
            "raw_format_ok_rate": 1.0,
            "avg_latency_ms": 500.0,
        }
        for i in range(n):
            idx += 1
            preds.append({"id": f"ex_{idx}", "category": cat, "exec_correct": i < k})

    (run_dir / "predictions.jsonl").write_text(
        "\n".join(json.dumps(p) for p in preds) + "\n", encoding="utf-8"
    )
    metrics = {
        "run_name": run_name,
        "overall": {
            "n": total_n,
            "syntax_valid_rate": 1.0,
            "exec_ok_rate": 1.0,
            "execution_accuracy": round(total_k / total_n, 4),
            "exact_match_rate": round(total_k / total_n, 4),
            "raw_format_ok_rate": 1.0,
            "avg_latency_ms": 500.0,
        },
        "by_category": by_cat,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def test_v1_v2_comparison_decision_rule_and_labels(tmp_path: Path):
    # Case 1: missing test_real_v2 -> PENDING
    _write_fake_run(tmp_path, "ft_v1_val", {"aggregation": (45, 50), "lookup": (45, 50)})
    _write_fake_run(tmp_path, "ft_v2_val", {"aggregation": (48, 50), "lookup": (46, 50)})
    _write_fake_run(tmp_path, "ft_v1_synthetic", {"aggregation": (48, 50)})
    _write_fake_run(tmp_path, "ft_v2_synthetic", {"aggregation": (49, 50)})
    _write_fake_run(tmp_path, "ft_v1_real", {"aggregation": (73, 80)})
    _write_fake_run(tmp_path, "ft_v2_real", {"aggregation": (74, 80)})

    comp_pending = build_v1_v2_comparison(tmp_path)
    assert comp_pending["decision"]["decision"] == "PENDING"
    md = render_v1_v2_markdown(comp_pending)
    assert DECISION_RULE_TEXT in md
    assert INFORMED_LABEL in md
    assert "95% Wilson CI" in md

    # Case 2: add test_real_v2 where v2 >= v1 -> SHIP_V2
    _write_fake_run(tmp_path, "ft_v1_real_v2", {"aggregation": (22, 25), "lookup": (20, 25)})
    _write_fake_run(tmp_path, "ft_v2_real_v2", {"aggregation": (23, 25), "lookup": (22, 25)})
    comp_ship_v2 = build_v1_v2_comparison(tmp_path)
    assert comp_ship_v2["decision"]["decision"] == "SHIP_V2"

    # Case 3: v2 drops > 2.5 pp on test_real -> SHIP_V1
    _write_fake_run(tmp_path, "ft_v2_real", {"aggregation": (70, 80)})  # 87.5% vs 91.25% (-3.75pp)
    comp_ship_v1 = build_v1_v2_comparison(tmp_path)
    assert comp_ship_v1["decision"]["decision"] == "SHIP_V1"


def test_provenance_doc_authorship_notes_and_eval_notebook():
    prov = (REPO_ROOT / "docs" / "MODEL_PROVENANCE.md").read_text(encoding="utf-8")
    assert "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e" in prov
    assert "unsloth/Qwen3-1.7B-unsloth-bnb-4bit" in prov
    assert "abubakar56/formulalm-qwen3-1.7b-lora-v2" in prov
    assert "UNVERIFIED" in prov

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    card = (REPO_ROOT / "data" / "DATASET_CARD.md").read_text(encoding="utf-8")
    for text in (readme, card):
        assert "AI assistant" in text
        assert "informed by v1 error analysis" in text

    nb = json.loads((REPO_ROOT / "notebooks" / "03_eval_ft_v2.ipynb").read_text(encoding="utf-8"))
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "ft_v2_val" in src and "ft_v1_val" in src
    assert "ft_v2_real_v2" in src and "ft_v1_real_v2" in src
    assert "compare_v1_v2" in src
    assert "EVAL_KWARGS" in src


def test_committed_test_real_v2_raw_and_annotated_verify_cleanly():
    raw_rep = validate_raw_requests(REPO_ROOT / "data" / "test_real_v2" / "requests.csv")
    assert raw_rep["total_rows"] == 50
    assert raw_rep["error_count"] == 0
    assert raw_rep["warnings"] == []
    assert raw_rep["missing_heldout_sheets"] == []

    ann_rep = validate_annotated_test_real_v2(
        REPO_ROOT / "data" / "test_real_v2" / "test_real_v2.csv",
        timeout=30.0,
    )
    assert ann_rep["total_rows"] == 50
    assert ann_rep["error_count"] == 0
    assert ann_rep["flagged_unresolved"] == []


def test_headline_summary_decision_doc_and_base_real_v2_notebook():
    headline = build_headline_summary(REPO_ROOT / "results")
    md = render_headline_markdown(headline)
    assert "95% Wilson CI" in md
    assert INFORMED_LABEL in md
    assert "test_real_v2" in md and "test_real" in md and "test_synthetic" in md

    dec = (REPO_ROOT / "docs" / "DECISION.md").read_text(encoding="utf-8")
    assert "SHIP_V2" in dec
    assert "v1-frozen" in dec
    assert "e2dd7e8115406ffcdbbdfa60d6f2f10b4aaf2595" in dec
    assert "statistically indistinguishable" in dec.lower()

    nb = json.loads(
        (REPO_ROOT / "notebooks" / "04_eval_base_real_v2.ipynb").read_text(encoding="utf-8")
    )
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "baseline_zeroshot_real_v2" in src
    assert "baseline_5shot_real_v2" in src
    assert "data/processed/train.jsonl" in src
    assert "final_headline.md" in src
