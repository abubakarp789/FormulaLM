"""Unit tests for src/eval/xlsx_writer.py (safe Excel formula injection & export)."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from src.eval.xlsx_writer import inject_formula_into_xlsx, validate_cell_ref


def _make_sample_xlsx(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Orders"
    ws.append(["Region", "Units", "Revenue"])
    ws.append(["North", 10, 250.5])
    ws.append(["South", 20, 400.0])
    wb.save(path)
    wb.close()
    return path


def test_validate_cell_ref_accepts_valid_and_rejects_bad() -> None:
    assert validate_cell_ref("g2") == "G2"
    assert validate_cell_ref("  AA120 ") == "AA120"
    assert validate_cell_ref("XFD1048576") == "XFD1048576"

    for bad in ("", "A0", "1A", "A1:B2", "Sheet1!A1", "=SUM(A1)", "XFE1", "A1048577"):
        with pytest.raises(ValueError):
            validate_cell_ref(bad)


def test_inject_formula_auto_summary_row_into_xlsx(tmp_path: Path) -> None:
    src = _make_sample_xlsx(tmp_path / "orders.xlsx")
    out_path, cell = inject_formula_into_xlsx(
        src,
        sheet_name="Orders",
        formula="=SUM(C2:C3)",
        target_cell=None,
        out_dir=tmp_path,
    )
    assert out_path.is_file()
    assert cell == "B5"  # max_row=3 -> summary row 5

    wb = openpyxl.load_workbook(out_path, data_only=False)
    try:
        ws = wb["Orders"]
        assert ws["A5"].value == "FormulaLM Result"
        assert ws["B5"].value == "=SUM(C2:C3)"
        # Original data preserved untouched
        assert ws["A2"].value == "North"
        assert ws["C3"].value == 400.0
    finally:
        wb.close()


def test_inject_formula_explicit_cell_and_overwrite_guard(tmp_path: Path) -> None:
    src = _make_sample_xlsx(tmp_path / "orders.xlsx")

    # Empty cell succeeds
    out_path, cell = inject_formula_into_xlsx(
        src,
        sheet_name="Orders",
        formula='=SUMIF(A2:A3,"North",C2:C3)',
        target_cell="e2",
        out_dir=tmp_path,
    )
    assert cell == "E2"
    wb = openpyxl.load_workbook(out_path, data_only=False)
    assert wb["Orders"]["E2"].value == '=SUMIF(A2:A3,"North",C2:C3)'
    wb.close()

    # Non-empty cell rejected by default
    with pytest.raises(ValueError, match="already contains"):
        inject_formula_into_xlsx(
            src,
            sheet_name="Orders",
            formula="=SUM(C2:C3)",
            target_cell="A2",
            out_dir=tmp_path,
        )

    # Non-empty cell allowed when explicitly confirmed
    out_ow, cell_ow = inject_formula_into_xlsx(
        src,
        sheet_name="Orders",
        formula="=SUM(C2:C3)",
        target_cell="A2",
        allow_overwrite=True,
        out_dir=tmp_path,
    )
    assert cell_ow == "A2"
    wb2 = openpyxl.load_workbook(out_ow, data_only=False)
    assert wb2["Orders"]["A2"].value == "=SUM(C2:C3)"
    wb2.close()


def test_inject_formula_converts_csv_to_xlsx(tmp_path: Path) -> None:
    csv_file = tmp_path / "sales.csv"
    csv_file.write_text("Branch,Amount\nNorth,120.5\nSouth,79.5\n", encoding="utf-8")

    out_path, cell = inject_formula_into_xlsx(
        csv_file,
        sheet_name=None,
        formula="=SUM(B2:B3)",
        target_cell="D2",
        out_dir=tmp_path,
    )
    assert out_path.suffix == ".xlsx"
    assert cell == "D2"
    wb = openpyxl.load_workbook(out_path, data_only=False)
    ws = wb.active
    assert ws is not None
    assert ws["A1"].value == "Branch"
    assert ws["B2"].value == 120.5
    assert ws["D2"].value == "=SUM(B2:B3)"
    wb.close()


def test_inject_formula_from_bytes_and_rejects_unsafe_or_non_formula(tmp_path: Path) -> None:
    src = _make_sample_xlsx(tmp_path / "orders.xlsx")
    raw_bytes = src.read_bytes()

    out_path, cell = inject_formula_into_xlsx(
        raw_bytes,
        sheet_name="Orders",
        formula="=AVERAGE(B2:B3)",
        target_cell="D4",
        source_suffix=".xlsx",
        out_dir=tmp_path,
    )
    assert cell == "D4"
    wb = openpyxl.load_workbook(out_path, data_only=False)
    assert wb["Orders"]["D4"].value == "=AVERAGE(B2:B3)"
    wb.close()

    for bad_formula in (
        "SUM(B2:B3)",
        "",
        "=SUMPRODUCT(B2:B3)",
        '=HYPERLINK("http://evil.com")',
        "=Sheet2!A1",
    ):
        with pytest.raises(ValueError, match="Refusing to write"):
            inject_formula_into_xlsx(
                src,
                sheet_name="Orders",
                formula=bad_formula,
                target_cell="D4",
                out_dir=tmp_path,
            )
