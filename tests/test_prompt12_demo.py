"""Tests for Gradio demo app (mock backend, localhost guard, uploads, honest failure, warm-up)."""

from __future__ import annotations

import re
import time
from pathlib import Path

import gradio as gr
import openpyxl
import pytest

from app.app import (
    BUILTIN_EXAMPLES,
    CUSTOM_SHEET_KEY,
    LIMITS_HTML,
    MAX_UPLOAD_BYTES,
    assert_localhost_url,
    build_demo_app,
    build_offline_theme,
    create_runtime,
    export_custom_xlsx,
    format_meta_line_html,
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
    assert honest_failures[0].short_label == "Honest failure"


def test_mock_backend_runs_wins_and_honest_failure_with_saved_base_comparison() -> None:
    runtime = create_runtime(backend_kind="mock")

    # 1. Passing held-out example (real_v2_005)
    win_ex = BUILTIN_EXAMPLES[0]
    formula, verdict_html, meta_html, base_html, preview_df, schema_text = run_demo_query(
        runtime,
        sheet_choice=win_ex.sheet_id,
        uploaded_file=None,
        pasted_headers="",
        request_text=win_ex.request,
        show_base_comparison=True,
    )
    assert formula.startswith("=COUNTIFS(")
    assert "✅ 16 — matches ground truth" in verdict_html
    assert "Q5_K_M" in meta_html
    assert re.search(r"\d+\.\d s", meta_html)
    assert "Base 0-shot" in base_html and "Base 5-shot" in base_html
    assert "Saved evaluation runs, not live" in base_html
    assert len(preview_df) == 5
    assert "sales_retail_store" in schema_text

    # 2. Honest failure built-in example (real_v2_050)
    fail_ex = [ex for ex in BUILTIN_EXAMPLES if ex.is_honest_failure][0]
    f_fail, verdict_fail_html, _, base_fail_html, _, _ = run_demo_query(
        runtime,
        sheet_choice=fail_ex.sheet_id,
        uploaded_file=None,
        pasted_headers="",
        request_text=fail_ex.request,
        show_base_comparison=True,
    )
    assert f_fail.startswith("=")
    assert "❌ 11 ≠ 533 (ground truth)" in verdict_fail_html
    assert "Saved evaluation runs, not live" in base_fail_html


def test_pasted_headers_and_csv_xlsx_uploads_and_size_limit(tmp_path: Path) -> None:
    runtime = create_runtime(backend_kind="mock")

    # Pasted column headers (synthesizes 5 rows and executes =SUM on first numeric column)
    formula, verdict_html, _, base_html, preview_df, schema_text = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=None,
        pasted_headers="Region, Sales Rep, Units, Net Revenue",
        request_text="Total Units across all rows",
        show_base_comparison=True,
    )
    assert formula == "=SUM(C2:C6)"
    assert "Executed:" in verdict_html and "on 5 sample rows" in verdict_html
    assert "No saved base-model prediction exists" in base_html
    assert len(preview_df) == 5
    assert "C: Units (integer)" in schema_text

    # Uploaded CSV
    csv_file = tmp_path / "mini_sales.csv"
    csv_file.write_text("Branch,Amount\nNorth,120.5\nSouth,79.5\n", encoding="utf-8")
    f_csv, verdict_csv, _, _, df_csv, _ = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=csv_file,
        pasted_headers="",
        request_text="Total Amount",
        show_base_comparison=False,
    )
    assert f_csv == "=SUM(B2:B3)"
    assert "Executed: 200" in verdict_csv
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
    f_xlsx, verdict_xlsx, _, _, _, _ = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=xlsx_file,
        pasted_headers="",
        request_text="Total Qty",
        show_base_comparison=False,
    )
    assert f_xlsx == "=SUM(B2:B3)"
    assert "Executed: 10" in verdict_xlsx

    # Oversized upload (> 1.0 MB) rejected cleanly
    big_csv = tmp_path / "too_big.csv"
    big_csv.write_bytes(b"a,b\n" + b"1,2\n" * ((MAX_UPLOAD_BYTES // 4) + 100))
    f_big, verdict_big, _, _, _, _ = run_demo_query(
        runtime,
        sheet_choice=CUSTOM_SHEET_KEY,
        uploaded_file=big_csv,
        pasted_headers="",
        request_text="Sum b",
        show_base_comparison=False,
    )
    assert f_big == ""
    assert "Input validation error" in verdict_big
    assert "1.00 MB limit" in verdict_big


def test_execution_failure_surfaces_clear_error_details() -> None:
    runtime = create_runtime(backend_kind="mock")

    class _BadFormulaBackend:
        name = "mock:bad"
        last_timings: dict[str, float] = {}

        def generate(self, messages, *, max_tokens: int, seed: int) -> str:
            del messages, max_tokens, seed
            return "=SUMPRODUCT(E2:E115)"

    runtime.backend = _BadFormulaBackend()
    formula, verdict_html, _, _, _, _ = run_demo_query(
        runtime,
        sheet_choice="sales_retail_store",
        uploaded_file=None,
        pasted_headers="",
        request_text="Anything",
        show_base_comparison=False,
    )
    assert formula == "=SUMPRODUCT(E2:E115)"
    assert "Execution failed" in verdict_html
    assert "unsupported_function" in verdict_html


def test_gradio_blocks_and_powershell_launcher_config() -> None:
    runtime = create_runtime(backend_kind="mock")
    demo = build_demo_app(runtime)
    assert isinstance(demo, gr.Blocks)

    # Ollama runtime sets keep_alive="30m" and warms up in background
    rt = create_runtime(backend_kind="ollama")
    assert rt.backend.keep_alive == "30m"

    warming_meta = format_meta_line_html(
        backend_kind="ollama",
        quant_label="Q5_K_M",
        latency_s=None,
        warmup_state="warming",
    )
    assert "warming up..." in warming_meta

    called: list[int] = []

    class _FakeOllama:
        last_timings: dict[str, float] = {}

        def generate(self, messages, *, max_tokens: int, seed: int) -> str:
            del messages, seed
            called.append(max_tokens)
            return "="

    rt.backend = _FakeOllama()
    rt.start_background_warmup()
    for _ in range(30):
        if rt.warmup_state == "ready":
            break
        time.sleep(0.02)
    assert rt.warmup_state == "ready"
    assert called == [1]

    # Offline theme must declare zero external stylesheets (no Google Fonts / CDN)
    theme = build_offline_theme()
    assert theme._stylesheets == []

    # Exact quoted accuracy caveat in Limits & scope
    assert (
        "On a small 50-request fresh held-out set (AI-drafted), "
        "Q5_K_M scored 86-90% (45/50 on Colab, 43/50 on local Ollama)."
    ) in LIMITS_HTML

    ps1 = (Path(__file__).resolve().parents[1] / "scripts" / "run_demo.ps1").read_text(
        encoding="utf-8"
    )
    assert "OLLAMA_MAX_LOADED_MODELS = '1'" in ps1


def test_custom_sheet_export_xlsx_injection_and_validation(tmp_path: Path) -> None:
    # 1. Uploaded CSV -> exported .xlsx with auto summary cell
    csv_file = tmp_path / "mini_sales.csv"
    csv_file.write_text("Branch,Amount\nNorth,120.5\nSouth,79.5\n", encoding="utf-8")
    out_csv, note_csv = export_custom_xlsx(
        uploaded_file=csv_file,
        pasted_headers="",
        formula="=SUM(B2:B3)",
        target_cell="",
        out_dir=tmp_path,
    )
    assert out_csv is not None and out_csv.is_file()
    assert "B5" in note_csv
    wb = openpyxl.load_workbook(out_csv, data_only=False)
    ws = wb.active
    assert ws is not None and ws["B5"].value == "=SUM(B2:B3)"
    wb.close()

    # 2. Pasted headers -> exported .xlsx with explicit target cell
    out_pasted, note_pasted = export_custom_xlsx(
        uploaded_file=None,
        pasted_headers="Region, Units, Net Sales",
        formula="=SUM(C2:C6)",
        target_cell="E2",
        out_dir=tmp_path,
    )
    assert out_pasted is not None and out_pasted.is_file()
    assert "E2" in note_pasted

    # 3. Non-empty cell rejected without overwrite flag
    out_err, note_err = export_custom_xlsx(
        uploaded_file=csv_file,
        pasted_headers="",
        formula="=SUM(B2:B3)",
        target_cell="A1",
        allow_overwrite=False,
        out_dir=tmp_path,
    )
    assert out_err is None
    assert "already contains" in note_err
