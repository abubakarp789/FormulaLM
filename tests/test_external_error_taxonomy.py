"""Unit tests for the SpreadsheetBench error & structural-pattern taxonomy."""

from __future__ import annotations

from scripts.analyze_external_errors import (
    analyze_taxonomy,
    classify_gold_pattern,
    classify_prediction_outcome,
)


def test_taxonomy_counts_sum_to_56_for_all_models() -> None:
    data = analyze_taxonomy()
    n = data["total_tasks"]
    assert n == 56

    for sys_key, counts in data["outcome_breakdown"].items():
        assert sum(counts.values()) == n, f"Mismatch for {sys_key}"

    assert data["outcome_breakdown"]["ext_formulalm_q5_k_m"]["correct"] == 12
    assert data["outcome_breakdown"]["ext_base_1_7b_0shot"]["correct"] == 6
    assert data["outcome_breakdown"]["ext_base_1_7b_5shot"]["correct"] == 6

    pattern_total = sum(row["n"] for row in data["pattern_buckets"].values())
    assert pattern_total == n
    tr_n = data["scope_summary"]["trained_grammar"]["n"]
    un_n = data["scope_summary"]["untrained_structural_idioms"]["n"]
    assert tr_n + un_n == n


def test_pattern_and_outcome_classifiers() -> None:
    assert (
        classify_gold_pattern("=INDEX($C$6:$I$19,MATCH($L6,$B$6:$B$19,0),MATCH(M$5,$C$5:$I$5,0))")
        == "2D_matrix_INDEX_MATCH_MATCH"
    )
    assert (
        classify_gold_pattern("=IF(MAX(IF(($A$2:$A$41=A2)*($J$2:$J$41=J2),$I$2:$I$41))=I2,1,0)")
        == "boolean_array_multiplication"
    )
    assert classify_gold_pattern("=COUNTIF($D$2:D2,D2)") == "running_anchored_window"
    assert (
        classify_gold_pattern('=SUMIF($A$2:$A$10,D2&"*",$B$2:$B$10)')
        == "wildcard_string_criteria"
    )
    assert classify_gold_pattern('=SUMIF(A2:A12,"111111",B2:B12)') == "standard_in_scope_pattern"

    assert (
        classify_prediction_outcome(
            {
                "exec_correct": False,
                "extracted_formula": "=F2+1",
                "error_type": "runtime_error",
                "error_message": "Circular self-reference to target cell R2C6",
            }
        )
        == "circular_reference"
    )
