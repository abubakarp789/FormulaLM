"""Tests for Base-vs-FT comparison tables and 6-cluster error analysis."""

from __future__ import annotations

import json
from pathlib import Path

from formulalm.config import REPO_ROOT
from src.eval.compare_and_cluster import (
    CLUSTERS,
    build_comparison,
    cluster_failure,
    render_comparison_md,
)
from src.eval.run_eval import MockBackend, evaluate

TEST_REAL_CSV = REPO_ROOT / "data" / "test_real" / "test_real_DRAFT.csv"


def test_cluster_failure_covers_all_six_clusters():
    assert (
        cluster_failure(
            {
                "raw_format_ok": False,
                "raw_output": "Here is the formula:\n=SUM(A2:A5)",
                "extracted_formula": "=SUM(A2:A5)",
                "reference_formula": "=SUM(B2:B5)",
                "category": "aggregation",
            }
        )
        == "over_generation"
    )
    assert (
        cluster_failure(
            {
                "raw_format_ok": True,
                "raw_output": "=SUM(A2:A5",
                "extracted_formula": "=SUM(A2:A5",
                "reference_formula": "=SUM(A2:A5)",
                "error_type": "syntax_error",
                "category": "aggregation",
            }
        )
        == "syntax_error"
    )
    assert (
        cluster_failure(
            {
                "raw_format_ok": True,
                "raw_output": "=SUM(E2:E10)",
                "extracted_formula": "=SUM(E2:E10)",
                "reference_formula": "=SUM(F2:F10)",
                "error_type": None,
                "category": "aggregation",
            }
        )
        == "wrong_column"
    )
    assert (
        cluster_failure(
            {
                "raw_format_ok": True,
                "raw_output": "=LEFT(A2,3)",
                "extracted_formula": "=LEFT(A2,3)",
                "reference_formula": "=RIGHT(A2,3)",
                "error_type": None,
                "category": "text",
            }
        )
        == "wrong_function"
    )
    assert (
        cluster_failure(
            {
                "raw_format_ok": True,
                "raw_output": "=AVERAGE(F2:F10)",
                "extracted_formula": "=AVERAGE(F2:F10)",
                "reference_formula": "=ROUND(AVERAGE(F2:F10),2)",
                "error_type": None,
                "category": "math_and_composition",
            }
        )
        == "wrong_aggregation"
    )
    assert (
        cluster_failure(
            {
                "raw_format_ok": True,
                "raw_output": '=SUMIFS(C2:C10,F2:F10,"North",E2:E10,">5")',
                "extracted_formula": '=SUMIFS(C2:C10,F2:F10,"North",E2:E10,">5")',
                "reference_formula": '=SUMIFS(F2:F10,C2:C10,"North",E2:E10,">5")',
                "error_type": None,
                "category": "conditional_aggregation",
            }
        )
        == "wrong_argument_order"
    )


def test_build_comparison_and_render_md(tmp_path: Path):
    for name, mode in (
        ("b0_syn", "broken"),
        ("b5_syn", "mixed"),
        ("ft_syn", "mixed"),
        ("b0_real", "broken"),
        ("b5_real", "mixed"),
        ("ft_real", "mixed"),
    ):
        evaluate(
            MockBackend(mode=mode),
            TEST_REAL_CSV,
            run_name=name,
            results_root=tmp_path,
            limit=12,
        )

    comp = build_comparison(
        base_zero_syn=tmp_path / "b0_syn",
        base_five_syn=tmp_path / "b5_syn",
        ft_syn=tmp_path / "ft_syn",
        base_zero_real=tmp_path / "b0_real",
        base_five_real=tmp_path / "b5_real",
        ft_real=tmp_path / "ft_real",
    )
    assert {c["cluster"] for c in comp["clusters"]} == set(CLUSTERS)
    md = render_comparison_md(comp)
    assert "## 1. Overall Comparison" in md
    assert "## 2A. Execution Accuracy by Category" in md
    assert "## 3A. Execution Accuracy by Difficulty" in md
    assert "## 4. Error Analysis" in md

    nb = json.loads((REPO_ROOT / "notebooks" / "02_eval_ft_v1.ipynb").read_text("utf-8"))
    assert nb["nbformat"] == 4
    assert any("compare_and_cluster" in "".join(c["source"]) for c in nb["cells"])
