"""Tests for safe Excel formula execution, normalization and value comparison."""

from __future__ import annotations

import datetime
import time
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from formulalm.config import REPO_ROOT
from src.eval import executor as executor_mod
from src.eval.executor import (
    ALLOWED_FUNCTIONS,
    check_engine_availability,
    run_formula,
)
from src.eval.normalize import (
    date_to_excel_serial,
    exact_match,
    normalize_formula,
    values_equal,
)


@pytest.fixture(scope="module")
def sample_sheets(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Create a deterministic mini workbook in both XLSX and CSV formats."""
    d = tmp_path_factory.mktemp("exec_sheets")
    xlsx_path = d / "mini.xlsx"
    csv_path = d / "mini.csv"

    rows = [
        ["ID", "Region", "Item", "Qty", "Price", "Order Date"],
        ["A1", "North", "  desk lamp  ", 10, 12.5, datetime.date(2025, 3, 15)],
        ["A2", "South", "Mug", 20, 5.0, datetime.date(2025, 7, 20)],
        ["A3", "North", "Lamp", 30, None, datetime.date(2026, 1, 5)],
        ["A4", "East", "Chair", 0, 100.0, datetime.date(2025, 3, 15)],
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for r in rows:
        ws.append(r)
    wb.save(xlsx_path)
    wb.close()

    csv_records = []
    for r in rows[1:]:
        csv_records.append(
            ["" if v is None else (v.isoformat() if isinstance(v, datetime.date) else v) for v in r]
        )
    pd.DataFrame(csv_records, columns=rows[0]).to_csv(csv_path, index=False)
    return xlsx_path, csv_path


# ---------------------------------------------------------------------------
# 1. All 36 in-scope functions: known formula -> expected value pairs (40 cases)
# ---------------------------------------------------------------------------

KNOWN_FORMULA_CASES: list[tuple[str, str, object]] = [
    ("SUM_range", "=SUM(D2:D5)", 60),
    ("SUM_full_col", "=SUM(D:D)", 60),
    ("SUMIF_text", '=SUMIF(B2:B5,"North",D2:D5)', 40),
    ("SUMIF_case_insensitive", '=SUMIF(B2:B5,"north",D2:D5)', 40),
    ("SUMIF_wildcard", '=SUMIF(B2:B5,"Nor*",D2:D5)', 40),
    ("SUMIF_numeric_crit", '=SUMIF(D2:D5,">15")', 50),
    ("SUMIF_blank_in_sum", '=SUMIF(B2:B5,"North",E2:E5)', 12.5),
    ("SUMIFS_two_criteria", '=SUMIFS(D2:D5,B2:B5,"North",D2:D5,">15")', 30),
    ("COUNT_with_blank", "=COUNT(E2:E5)", 3),
    ("COUNT_text_is_zero", "=COUNT(B2:B5)", 0),
    ("COUNTIF_text", '=COUNTIF(B2:B5,"North")', 2),
    ("COUNTIF_date_iso", '=COUNTIF(F2:F5,">2025-06-01")', 2),
    ("COUNTIF_date_fn", '=COUNTIF(F2:F5,">"&DATE(2025,6,1))', 2),
    ("COUNTIFS_multi", '=COUNTIFS(B2:B5,"North",D2:D5,">15")', 1),
    ("AVERAGE_basic", "=AVERAGE(D2:D5)", 15.0),
    ("AVERAGE_skips_blank", "=AVERAGE(E2:E5)", (12.5 + 5.0 + 100.0) / 3.0),
    ("AVERAGEIF_basic", '=AVERAGEIF(B2:B5,"North",D2:D5)', 20.0),
    ("AVERAGEIF_skips_blank", '=AVERAGEIF(B2:B5,"North",E2:E5)', 12.5),
    ("AVERAGEIFS_multi", '=AVERAGEIFS(D2:D5,B2:B5,"North",D2:D5,">5")', 20.0),
    ("MIN_basic", "=MIN(D2:D5)", 0),
    ("MAX_basic", "=MAX(D2:D5)", 30),
    ("IF_true_branch", '=IF(D2>5,"High","Low")', "High"),
    ("IF_false_branch", '=IF(D2>50,"High","Low")', "Low"),
    ("IFS_middle_branch", '=IFS(D2>20,"A",D2>=10,"B",TRUE,"C")', "B"),
    ("AND_true", '=AND(D2=10,B2="North")', True),
    ("AND_false", '=AND(D2=10,B2="South")', False),
    ("OR_true", '=OR(D2=99,B2="North")', True),
    ("OR_false", '=OR(D2=99,B2="West")', False),
    ("VLOOKUP_exact", '=VLOOKUP("A2",A2:E5,4,FALSE)', 20),
    ("XLOOKUP_exact", '=XLOOKUP("A2",A2:A5,D2:D5)', 20),
    ("XLOOKUP_not_found", '=XLOOKUP("ZZZ",A2:A5,D2:D5,"Missing")', "Missing"),
    ("INDEX_MATCH_range", '=INDEX(D2:D5,MATCH("A2",A2:A5,0))', 20),
    ("INDEX_MATCH_full_col", '=INDEX(D:D,MATCH("A2",A:A,0))', 20),
    ("LEFT_basic", "=LEFT(A2,1)", "A"),
    ("RIGHT_basic", "=RIGHT(A2,1)", "1"),
    ("MID_basic", "=MID(B2,2,3)", "ort"),
    ("LEN_basic", "=LEN(B2)", 5),
    ("CONCAT_multi", '=CONCAT(A2,"-",B2)', "A1-North"),
    ("TEXTJOIN_range", '=TEXTJOIN(", ",TRUE,B2:B4)', "North, South, North"),
    ("UPPER_basic", "=UPPER(B2)", "NORTH"),
    ("LOWER_basic", "=LOWER(B2)", "north"),
    ("PROPER_basic", '=PROPER("heLLO wORLD")', "Hello World"),
    ("TRIM_basic", "=TRIM(C2)", "desk lamp"),
    ("TEXT_number", '=TEXT(E2,"0.00")', "12.50"),
    ("TEXT_currency", '=TEXT(E2,"$#,##0.00")', "$12.50"),
    ("TEXT_date", '=TEXT(F2,"yyyy-mm")', "2025-03"),
    ("DATE_serial", "=DATE(2025,3,15)", datetime.date(2025, 3, 15)),
    ("YEAR_basic", "=YEAR(F2)", 2025),
    ("MONTH_basic", "=MONTH(F2)", 3),
    ("DAY_basic", "=DAY(F2)", 15),
    ("ROUND_half_up", "=ROUND(2.5,0)", 3),
    ("ROUND_decimals", "=ROUND(E2,0)", 13),
    ("IFERROR_div0", "=IFERROR(10/D5,0)", 0),
    ("IFERROR_vlookup_na", '=IFERROR(VLOOKUP("ZZZ",A2:E5,4,FALSE),"Not Found")', "Not Found"),
    ("arithmetic_mul", "=D2*E2", 125.0),
    ("ampersand_concat", '=A2&"-"&B2', "A1-North"),
    ("string_containing_fn_name", '=IF(B2="TODAY()",1,0)', 0),
    ("sheet_prefix_allowed", "=SUM(Sheet1!D2:D5)", 60),
    ("if_blank_cell_check", '=IF(E4="","Missing","Present")', "Missing"),
]


@pytest.mark.parametrize(
    ("name", "formula", "expected"),
    KNOWN_FORMULA_CASES,
    ids=[c[0] for c in KNOWN_FORMULA_CASES],
)
def test_known_formulas_xlsx(sample_sheets: tuple[Path, Path], name: str, formula: str, expected):
    xlsx_path, _ = sample_sheets
    res = run_formula(formula, xlsx_path, target_cell="H2")
    assert res.ok, f"{name} failed: {res.error_type}: {res.error_message}"
    assert values_equal(res.value, expected), f"{name}: got {res.value!r}, expected {expected!r}"


def test_csv_and_xlsx_produce_identical_results(sample_sheets: tuple[Path, Path]):
    xlsx_path, csv_path = sample_sheets
    subset = [
        '=SUMIF(B2:B5,"North",D2:D5)',
        "=COUNT(E2:E5)",
        "=AVERAGE(E2:E5)",
        '=COUNTIF(F2:F5,">2025-06-01")',
        '=INDEX(D2:D5,MATCH("A2",A2:A5,0))',
        '=TEXT(F2,"yyyy-mm")',
        "=TRIM(C2)",
    ]
    for fml in subset:
        r_xlsx = run_formula(fml, xlsx_path, target_cell="H2")
        r_csv = run_formula(fml, csv_path, target_cell="H2")
        assert r_xlsx.ok and r_csv.ok
        assert values_equal(r_xlsx.value, r_csv.value), f"{fml}: {r_xlsx.value} vs {r_csv.value}"


def test_real_generated_sheet_matches_pandas():
    xlsx = REPO_ROOT / "data" / "sheets" / "sales_regional_q1.xlsx"
    csv = REPO_ROOT / "data" / "sheets" / "sales_regional_q1.csv"
    df = pd.read_csv(csv)
    last_row = len(df) + 1

    expected_sum = int(df.loc[df["Region"] == "North", "Units Sold"].sum())
    expected_avg = float(df["Unit Price"].mean())
    expected_count = int(df["Unit Price"].notna().sum())

    r1 = run_formula(f'=SUMIF(C2:C{last_row},"North",F2:F{last_row})', xlsx)
    r2 = run_formula(f"=AVERAGE(G2:G{last_row})", xlsx)
    r3 = run_formula(f"=COUNT(G2:G{last_row})", csv)

    assert r1.ok and values_equal(r1.value, expected_sum)
    assert r2.ok and values_equal(r2.value, expected_avg)
    assert r3.ok and values_equal(r3.value, expected_count)
    assert r1.target_cell == "I2"  # 7 columns -> default free cell is I2


# ---------------------------------------------------------------------------
# 2. Broken, disallowed and unsafe formulas (all 4 error classes)
# ---------------------------------------------------------------------------

BROKEN_FORMULA_CASES: list[tuple[str, str, str]] = [
    ("missing_equals", "SUM(D2:D5)", "syntax_error"),
    ("empty_string", "   ", "syntax_error"),
    ("only_equals", "=", "syntax_error"),
    ("unbalanced_open_paren", "=SUM(D2:D5", "syntax_error"),
    ("unbalanced_close_paren", "=SUM(D2:D5))", "syntax_error"),
    ("unclosed_quote", '=IF(B2="North,1,0)', "syntax_error"),
    ("newline_injection", "=SUM(D2:D5)\n+1", "syntax_error"),
    ("external_workbook", "='[other.xlsx]Sheet1'!A1", "syntax_error"),
    ("external_sheet", "=OtherSheet!A1", "syntax_error"),
    ("dde_pipe_injection", "=cmd|' /C calc'!A0", "syntax_error"),
    ("url_outside_string", "=http://example.com/a", "syntax_error"),
    ("volatile_today", "=TODAY()", "unsupported_function"),
    ("volatile_now", "=NOW()", "unsupported_function"),
    ("volatile_rand", "=RAND()", "unsupported_function"),
    ("disallowed_indirect", '=INDIRECT("A1")', "unsupported_function"),
    ("disallowed_webservice", '=WEBSERVICE("http://example.com")', "unsupported_function"),
    ("disallowed_hyperlink", '=HYPERLINK("http://example.com","click")', "unsupported_function"),
    ("typo_function", "=SUMM(D2:D5)", "unsupported_function"),
    ("div_by_zero", "=10/D5", "runtime_error"),
    ("vlookup_na", '=VLOOKUP("MISSING",A2:E5,4,FALSE)', "runtime_error"),
    ("ifs_no_match", '=IFS(D2>999,"A",D2>500,"B")', "runtime_error"),
    ("circular_self_ref", "=H2+1", "runtime_error"),
    ("circular_range_ref", "=SUM(H1:H5)", "runtime_error"),
    ("huge_range_dos", "=SUM(A1:Z50000)", "runtime_error"),
]


@pytest.mark.parametrize(
    ("name", "formula", "expected_error"),
    BROKEN_FORMULA_CASES,
    ids=[c[0] for c in BROKEN_FORMULA_CASES],
)
def test_broken_and_unsafe_formulas(
    sample_sheets: tuple[Path, Path], name: str, formula: str, expected_error: str
):
    xlsx_path, _ = sample_sheets
    res = run_formula(formula, xlsx_path, target_cell="H2")
    assert not res.ok, f"{name} unexpectedly succeeded with {res.value!r}"
    assert res.error_type == expected_error, (
        f"{name}: expected {expected_error}, got {res.error_type} ({res.error_message})"
    )


def test_timeout_error_class(sample_sheets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch):
    xlsx_path, _ = sample_sheets

    class _SlowCompiled:
        inputs: list[str] = []

        def __call__(self, **_kwargs):
            time.sleep(0.3)
            return 1

    class _SlowBuilder:
        def compile(self):
            return _SlowCompiled()

    class _SlowParser:
        def ast(self, _formula: str):
            return (None, _SlowBuilder())

    monkeypatch.setattr(executor_mod.formulas, "Parser", _SlowParser)
    res = run_formula("=SUM(1,2)", xlsx_path, target_cell="H2", timeout=0.05)
    assert not res.ok
    assert res.error_type == "timeout"


def test_missing_sheet_returns_runtime_error(tmp_path: Path):
    res = run_formula("=SUM(A1:A5)", tmp_path / "does_not_exist.xlsx")
    assert not res.ok
    assert res.error_type == "runtime_error"


def test_engine_availability_report():
    info = check_engine_availability()
    assert info["allowed_functions_count"] == len(ALLOWED_FUNCTIONS) == 36
    assert isinstance(info["libreoffice_available"], bool)


# ---------------------------------------------------------------------------
# 3. Formula normalization & type-aware value comparison
# ---------------------------------------------------------------------------


def test_normalize_formula_canonicalizes_and_preserves_strings():
    assert (
        normalize_formula('  = sumif( $b$2:$b$5 , "North East" , Sheet1!d5:d2 ) ')
        == '=SUMIF(B2:B5,"North East",D2:D5)'
    )
    assert exact_match(
        '=sumifs(F2:F10, "Sheet1"!C2:C10, "North", $E$2:$E$10, "Hardware")'.replace(
            '"Sheet1"!', "'Sheet1'!"
        ),
        '=SUMIFS(F2:F10,C2:C10,"North",E2:E10,"Hardware")',
    )
    assert exact_match('=vlookup("A2", $a$2:$e$5, 4, false)', '=VLOOKUP("A2",A2:E5,4,FALSE)')
    # String literal case and inner spaces must NOT be changed.
    assert not exact_match('=COUNTIF(B2:B5,"North")', '=COUNTIF(B2:B5,"north")')
    assert normalize_formula('=CONCAT("a b", "  c")') == '=CONCAT("a b","  c")'
    # Doubled quotes inside string literal preserved.
    assert normalize_formula('=IF(A2="x""y", 1, 0)') == '=IF(A2="x""y",1,0)'


def test_values_equal_type_awareness():
    # Numbers with tolerance 1e-6.
    assert values_equal(12.5000004, 12.5, tol=1e-6)
    assert not values_equal(12.50001, 12.5, tol=1e-6)
    assert not values_equal(1_000_000.0, 1_000_000.5, tol=1e-6)

    # Strict boolean vs integer separation.
    assert values_equal(True, True)
    assert values_equal(False, False)
    assert not values_equal(True, 1)
    assert not values_equal(False, 0)
    assert not values_equal(True, "TRUE")

    # Dates vs Excel serials and ISO strings.
    d = datetime.date(2025, 3, 15)
    assert date_to_excel_serial(d) == 45731
    assert values_equal(45731, d)
    assert values_equal(d, 45731.0)
    assert values_equal(d, "2025-03-15")
    assert not values_equal(45732, d)

    # Text (no silent whitespace stripping).
    assert values_equal("desk lamp", "desk lamp")
    assert not values_equal("  desk lamp  ", "desk lamp")
    assert not values_equal("North", "north", case_sensitive=True)
    assert values_equal("North", "north", case_sensitive=False)

    # Empty / NaN and cross-type mismatch.
    assert values_equal(None, None)
    assert values_equal(None, float("nan"))
    assert not values_equal(None, 0)
    assert not values_equal(12, "12")
