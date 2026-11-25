"""Tests for data/test_real/ DRAFT dataset and src/eval/run_eval.py evaluation runner."""

from __future__ import annotations

import json
from pathlib import Path

from formulalm.config import REPO_ROOT
from src.eval.analyze_errors import analyze_runs, classify_failure, render_summary_md
from src.eval.executor import run_formula
from src.eval.normalize import values_equal
from src.eval.run_eval import (
    MockBackend,
    build_eval_messages,
    evaluate,
    extract_formula,
    is_raw_format_clean,
    load_eval_examples,
    load_few_shot_from_train,
)
from src.eval.run_eval import main as eval_main

TEST_REAL_CSV = REPO_ROOT / "data" / "test_real" / "test_real_DRAFT.csv"


def test_real_draft_csv_valid_heldout_and_executable():
    assert TEST_REAL_CSV.exists()
    manifest = json.loads((REPO_ROOT / "data" / "sheets" / "manifest.json").read_text("utf-8"))
    heldout_ids = set(manifest["test_sheet_ids"])

    examples, xlsx_by_sheet = load_eval_examples(TEST_REAL_CSV)
    assert len(examples) == 80

    seen_reqs: set[tuple[str, str]] = set()
    for ex in examples:
        assert ex.sheet_id in heldout_ids, f"{ex.id} uses non-heldout sheet {ex.sheet_id}"
        key = (ex.sheet_id, ex.request.lower())
        assert key not in seen_reqs, f"duplicate request in {ex.id}"
        seen_reqs.add(key)

        res = run_formula(ex.reference_formula, xlsx_by_sheet[ex.sheet_id], timeout=30.0)
        assert res.ok, f"{ex.id} reference failed: {res.error_type}: {res.error_message}"
        assert values_equal(res.value, ex.expected_value), (
            f"{ex.id}: executor={res.value!r} != expected={ex.expected_value!r}"
        )


def test_extract_formula_handles_clean_fenced_think_and_prose():
    assert extract_formula("=SUM(F2:F10)") == "=SUM(F2:F10)"
    assert is_raw_format_clean("=SUM(F2:F10)")

    fenced = (
        'Sure, here is the formula:\n```excel\n=SUMIF(C2:C10,"North",F2:F10)\n```\nHope this helps.'
    )
    assert extract_formula(fenced) == '=SUMIF(C2:C10,"North",F2:F10)'
    assert not is_raw_format_clean(fenced)

    thinking = "<think>\nNeed column F.\n</think>\n=MAX(F2:F10)"
    assert extract_formula(thinking) == "=MAX(F2:F10)"
    assert not is_raw_format_clean(thinking)

    bullet = "Formula:\n- `=AVERAGE(G2:G10)`"
    assert extract_formula(bullet) == "=AVERAGE(G2:G10)"

    inline = "You can use `=COUNT(G2:G10)` to count numeric cells."
    assert extract_formula(inline) == "=COUNT(G2:G10)"

    chatter = "I am not sure which column to sum."
    assert extract_formula(chatter) == chatter
    assert not is_raw_format_clean(chatter)


def test_evaluate_oracle_and_markdown_oracle_on_real_draft(tmp_path: Path):
    metrics = evaluate(
        MockBackend(mode="oracle"),
        TEST_REAL_CSV,
        run_name="mock_oracle",
        results_root=tmp_path,
        seed=42,
    )
    ov = metrics["overall"]
    assert ov["n"] == 80
    assert ov["syntax_valid_rate"] == 1.0
    assert ov["exec_ok_rate"] == 1.0
    assert ov["execution_accuracy"] == 1.0
    assert ov["exact_match_rate"] == 1.0
    assert ov["raw_format_ok_rate"] == 1.0
    assert metrics["error_breakdown"] == {}
    assert sum(v["n"] for v in metrics["by_category"].values()) == 80
    assert sum(v["n"] for v in metrics["by_difficulty"].values()) == 80

    run_dir = tmp_path / "mock_oracle"
    for fname in ("predictions.jsonl", "metrics.json", "report.md", "run_config.json"):
        assert (run_dir / fname).is_file()

    rc = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert rc["config"]["base_model_id"] == "mock:oracle"
    assert "base_revision" in rc["config"]
    assert rc["config"]["model_provenance"]["base_model_id"] == "mock:oracle"

    # Markdown-wrapped outputs still achieve 100% after extraction, 0% raw_format_ok.
    m_md = evaluate(
        MockBackend(mode="markdown_oracle"),
        TEST_REAL_CSV,
        run_name="mock_md",
        results_root=tmp_path,
        limit=12,
    )
    assert m_md["overall"]["execution_accuracy"] == 1.0
    assert m_md["overall"]["raw_format_ok_rate"] == 0.0


def test_evaluate_mixed_and_broken_error_reporting(tmp_path: Path):
    m_mix = evaluate(
        MockBackend(mode="mixed"),
        TEST_REAL_CSV,
        run_name="mock_mixed",
        results_root=tmp_path,
        limit=16,
    )
    assert m_mix["overall"]["n"] == 16
    assert 0.0 < m_mix["overall"]["execution_accuracy"] < 1.0
    assert m_mix["error_breakdown"].get("unsupported_function", 0) > 0
    assert m_mix["error_breakdown"].get("wrong_value", 0) > 0
    report_text = (tmp_path / "mock_mixed" / "report.md").read_text(encoding="utf-8")
    assert "## Sample Failures" in report_text

    m_bad = evaluate(
        MockBackend(mode="broken"),
        TEST_REAL_CSV,
        run_name="mock_broken",
        results_root=tmp_path,
        limit=5,
    )
    assert m_bad["overall"]["syntax_valid_rate"] == 0.0
    assert m_bad["overall"]["execution_accuracy"] == 0.0
    assert m_bad["error_breakdown"] == {"syntax_error": 5}


def test_evaluate_is_resumable(tmp_path: Path):
    b1 = MockBackend(mode="oracle")
    m1 = evaluate(
        b1,
        TEST_REAL_CSV,
        run_name="resumable_run",
        results_root=tmp_path,
        limit=10,
        resume=True,
    )
    assert b1.call_count == 10
    assert m1["overall"]["n"] == 10

    b2 = MockBackend(mode="oracle")
    m2 = evaluate(
        b2,
        TEST_REAL_CSV,
        run_name="resumable_run",
        results_root=tmp_path,
        limit=25,
        resume=True,
    )
    assert b2.call_count == 15  # skipped the 10 already recorded
    assert m2["overall"]["n"] == 25
    pred_lines = (
        (tmp_path / "resumable_run" / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(pred_lines) == 25
    assert len({json.loads(line)["id"] for line in pred_lines}) == 25


def test_few_shot_messages_and_jsonl_cli(tmp_path: Path):
    examples, _ = load_eval_examples(TEST_REAL_CSV)
    msgs0 = build_eval_messages(examples[0], few_shot=0)
    msgs3 = build_eval_messages(examples[0], few_shot=3)
    assert len(msgs0) == 2
    assert len(msgs3) == 2 + 6

    # Create a tiny JSONL fixture and run CLI end-to-end.
    mini_jsonl = tmp_path / "mini.jsonl"
    ex = examples[0]
    rec = {
        "id": ex.id,
        "sheet_id": ex.sheet_id,
        "category": ex.category,
        "difficulty": ex.difficulty,
        "schema_text": ex.schema_text,
        "request": ex.request,
        "formula": ex.reference_formula,
        "expected_value": ex.expected_value,
        "expected_type": ex.expected_type,
    }
    mini_jsonl.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    rc = eval_main(
        [
            "--run-name",
            "cli_smoke",
            "--backend",
            "mock",
            "--mock-mode",
            "oracle",
            "--dataset",
            str(mini_jsonl),
            "--few-shot",
            "2",
            "--results-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    metrics = json.loads((tmp_path / "cli_smoke" / "metrics.json").read_text("utf-8"))
    assert metrics["overall"]["n"] == 1
    assert metrics["overall"]["execution_accuracy"] == 1.0
    assert metrics["few_shot"] == 2


def test_few_shot_drawn_from_train_only_and_error_analyzer(tmp_path: Path):
    train_jsonl = REPO_ROOT / "data" / "processed" / "train.jsonl"
    if train_jsonl.is_file():
        pairs, ids = load_few_shot_from_train(train_jsonl, 5, seed=42)
        assert len(pairs) == 5 and len(ids) == 5
        assert all(i.startswith("train_") for i in ids)
        assert all(fml.startswith("=") for _, fml in pairs)

    # Test analyze_errors across two mock runs and failure classifier categories.
    evaluate(
        MockBackend(mode="mixed"),
        TEST_REAL_CSV,
        run_name="baseline_mock_a",
        results_root=tmp_path,
        limit=20,
    )
    evaluate(
        MockBackend(mode="broken"),
        TEST_REAL_CSV,
        run_name="baseline_mock_b",
        results_root=tmp_path,
        limit=10,
    )
    analysis = analyze_runs([tmp_path / "baseline_mock_a", tmp_path / "baseline_mock_b"], top_k=15)
    assert len(analysis["runs"]) == 2
    assert analysis["total_failures"] > 0
    assert len(analysis["top_patterns"]) >= 2

    md = render_summary_md(analysis)
    assert "## Comparison Table" in md
    assert "## Top " in md

    assert (
        classify_failure(
            {
                "error_type": None,
                "category": "aggregation",
                "reference_formula": "=SUM(F2:F10)",
                "extracted_formula": "=SUM(E2:E10)",
            }
        )
        == "wrong_column_reference (aggregation)"
    )
    assert (
        classify_failure(
            {
                "error_type": "unsupported_function",
                "error_message": "Function(s) not in allow-list: TODAY",
                "category": "date",
                "reference_formula": "=DATE(2025,1,1)",
                "extracted_formula": "=TODAY()",
            }
        )
        == "volatile_function_used"
    )

    # Verify the baseline Colab notebook is valid JSON with code cells.
    nb = json.loads((REPO_ROOT / "notebooks" / "01_baseline_eval.ipynb").read_text("utf-8"))
    assert nb["nbformat"] == 4
    assert any(c["cell_type"] == "code" for c in nb["cells"])
