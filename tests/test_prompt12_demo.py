"""Tests for PROMPT 12 Gradio demo app (mock backend, localhost guard, uploads, honest failure)."""

from __future__ import annotations

from pathlib import Path

import gradio as gr
import openpyxl
import pytest

from app.app import (
    BUILTIN_EXAMPLES,
    CUSTOM_SHEET_KEY,
    MAX_UPLOAD_BYTES,
    assert_localhost_url,
    build_demo_app,
    create_runtime,
    run_demo_query,
)


def test_localhost_guard_enforces_local_only_inference() -> None:
    assert assert_localhost_url("http://localhost:11434/") == "http://localhost:11434"
    assert assert_localhost_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert assert_localhost_url("http://[::1]:11434") == "http://[::1]:11434"

    for bad_url in (
        "https://api.openai.com/v1",
        "http://192.168.1.25:11434",
        "http://example.com:8080",
        "ftp://127.0.0.1:11434",
    ):
        with pytest.raises(ValueError):
            assert_localhost_url(bad_url)


def test_builtin_examples_cover_all_heldout_sheets_and_include_honest_failure() -> None:
    runtime = create_runtime(backend_kind="mock")
    assert len(BUILTIN_EXAMPLES) >= 8

    covered_sheets = {ex.sheet_id for ex in BUILTIN_EXAMPLES}
    assert covered_sheets == set(runtime.bundle.heldout_contexts.keys())

    honest_failures = [ex for ex in BUILTIN_EXAMPLES if ex.is_honest_failure]
    assert len(honest_failures) >= 1
    assert "WRONG" in honest_failures[0].label or "FAILURE" in honest_failures[0].label


def test_mock_backend_runs_wins_and_honest_failure_with_saved_base_comparison() -> None:
    runtime = create_runtime(backend_kind="mock")

    # 1. Passing held-out example (real_v2_005)
    win_ex = BUILTIN_EXAMPLES[0]
    formula, exec_md, status_md, base_md, preview_df, schema_text = run_demo_query(
        runtime,
        sheet_choice=win_ex.sheet_id,
        uploaded_file=None,
        pasted_headers="",
        request_text=win_ex.request,
        show_base_comparison=True,
    )
    assert formula.startswith("=COUNTIFS(")
    assert "MATCHES GROUND TRUTH" in exec_md
    assert "Q5_K_M" in status_md
    assert "Latency:" in status_md
    assert "Saved evaluation run, base `Qwen3-1.7B`" in base_md
    assert "0-shot" in base_md and "5-shot" in base_md
    assert not preview_df.empty
    assert "sales_retail_store" in schema_text

    # 2. Honest failure built-in example (real_v2_050)
    fail_ex = [ex for ex in BUILTIN_EXAMPLES if ex.is_honest_failure][0]
    f_fail, exec_fail_md, _, base_fail_md, _, _ = run_demo_query(
        runtime,
        sheet_choice=fail_ex.sheet_id,
        uploaded_file=None,
        pasted_headers="",
        request_text=fail_ex.request,
        show_base_comparison=True,
    )
    assert f_fail.startswith("=")
    assert "DOES NOT MATCH GROUND TRUTH (Honest Failure)" in exec_fail_md
    assert "Saved evaluation run, base `Qwen3-1.7B`" in base_fail_md


def test_pasted_headers_and_csv_xlsx_uploads_and_size_limit(tmp_path: Path) -> None:
    runtime = create_runtime(backend_kind="mock")

    # Pasted column headers (synthesizes 5 rows and executes =SUM on first numeric column)
    formula, exec_md, _, base_md, preview_df, schema_text = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=None,
        pasted_headers="Region, Sales Rep, Units, Net Revenue",
        request_text="Total Units across all rows",
        show_base_comparison=True,
    )
    assert formula == "=SUM(C2:C6)"
    assert "Executed Value:" in exec_md
    assert "No saved base-model prediction exists" in base_md
    assert len(preview_df) == 5
    assert "C: Units (integer)" in schema_text

    # Uploaded CSV
    csv_file = tmp_path / "mini_sales.csv"
    csv_file.write_text("Branch,Amount\nNorth,120.5\nSouth,79.5\n", encoding="utf-8")
    f_csv, exec_csv, _, _, df_csv, _ = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=csv_file,
        pasted_headers="",
        request_text="Total Amount",
        show_base_comparison=False,
    )
    assert f_csv == "=SUM(B2:B3)"
    assert "`200`" in exec_csv
    assert len(df_csv) == 2

    # Uploaded XLSX
    xlsx_file = tmp_path / "mini_orders.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Item", "Qty"])
    ws.append(["Pen", 4])
    ws.append(["Book", 6])
    wb.save(xlsx_file)
    wb.close()
    f_xlsx, exec_xlsx, _, _, _, _ = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=xlsx_file,
        pasted_headers="",
        request_text="Total Qty",
        show_base_comparison=False,
    )
    assert f_xlsx == "=SUM(B2:B3)"
    assert "`10`" in exec_xlsx

    # Oversized upload (> 1.0 MB) rejected cleanly
    big_csv = tmp_path / "too_big.csv"
    big_csv.write_bytes(b"a,b\n" + b"1,2\n" * ((MAX_UPLOAD_BYTES // 4) + 100))
    f_big, exec_big, _, _, _, _ = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=big_csv,
        pasted_headers="",
        request_text="Sum b",
        show_base_comparison=False,
    )
    assert f_big == ""
    assert "Input Validation Error" in exec_big
    assert "1.00 MB limit" in exec_big


def test_execution_failure_surfaces_clear_error_details() -> None:
    runtime = create_runtime(backend_kind="mock")

    class _BadFormulaBackend:
        name = "mock:bad"
        last_timings: dict[str, float] = {}

        def generate(self, messages, *, max_tokens: int, seed: int) -> str:
            del messages, max_tokens, seed
            return "=SUMPRODUCT(E2:E115)"

    runtime.backend = _BadFormulaBackend()
    formula, exec_md, _, _, _, _ = run_demo_query(
        runtime,
        sheet_choice="sales_retail_store",
        uploaded_file=None,
        pasted_headers="",
        request_text="Anything",
        show_base_comparison=False,
    )
    assert formula == "=SUMPRODUCT(E2:E115)"
    assert "Execution Failed" in exec_md
    assert "unsupported_function" in exec_md


def test_gradio_blocks_and_powershell_launcher_config() -> None:
    runtime = create_runtime(backend_kind="mock")
    demo = build_demo_app(runtime)
    assert isinstance(demo, gr.Blocks)

    ps1 = (Path(__file__).resolve().parents[1] / "scripts" / "run_demo.ps1").read_text(
        encoding="utf-8"
    )
    assert "OLLAMA_MAX_LOADED_MODELS = '1'" in ps1
