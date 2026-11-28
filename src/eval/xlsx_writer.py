"""Safe Excel (.xlsx) formula injection helper for FormulaLM.

Takes an uploaded `.xlsx` workbook (or `.csv` file, converted cleanly to `.xlsx`),
validates both the Excel formula (using `src.eval.executor.validate_formula`) and
target cell reference, writes the formula into either an auto-selected summary row
or the user's chosen cell (refusing to overwrite non-empty cells unless explicitly
allowed), saves to a temporary `.xlsx` file, and verifies round-trip integrity via
`openpyxl`.
"""

from __future__ import annotations

import io
import re
import tempfile
import uuid
from pathlib import Path

import openpyxl
import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import column_index_from_string

from src.eval.executor import validate_formula

CELL_REF_RE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
MAX_EXCEL_COL = 16_384  # XFD
MAX_EXCEL_ROW = 1_048_576
_AUTO_LABELS = frozenset({"", "auto", "auto (summary row)"})


def validate_cell_ref(cell_ref: str) -> str:
    """Validate and normalize a single A1 cell coordinate (e.g. ``'g2' -> 'G2'``)."""
    cleaned = (cell_ref or "").strip().upper()
    m = CELL_REF_RE.match(cleaned)
    if not m:
        raise ValueError(
            f"Invalid target cell {cell_ref!r}. Expected a single cell like 'G2' or 'B10' "
            "(or leave blank for automatic summary row)."
        )
    col_letters, row_str = m.group(1), m.group(2)
    col_idx = column_index_from_string(col_letters)
    row_idx = int(row_str)
    if col_idx > MAX_EXCEL_COL or row_idx > MAX_EXCEL_ROW:
        raise ValueError(f"Target cell {cleaned!r} is outside Excel bounds (XFD1048576).")
    return cleaned


def _workbook_from_csv(csv_source: Path | bytes, sheet_title: str = "Sheet1") -> openpyxl.Workbook:
    if isinstance(csv_source, bytes):
        df = pd.read_csv(io.BytesIO(csv_source))
    else:
        df = pd.read_csv(csv_source)
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    safe_title = re.sub(r"[\\/*?:\[\]]+", "_", sheet_title).strip()[:31] or "Sheet1"
    ws.title = safe_title
    ws.append([str(c) for c in df.columns])
    for row in df.itertuples(index=False, name=None):
        cleaned_row = [None if pd.isna(v) else v for v in row]
        ws.append(cleaned_row)
    return wb


def inject_formula_into_xlsx(
    src_bytes_or_path: bytes | str | Path,
    sheet_name: str | None,
    formula: str,
    target_cell: str | None = None,
    *,
    allow_overwrite: bool = False,
    source_suffix: str | None = None,
    out_dir: Path | None = None,
) -> tuple[Path, str]:
    """Inject a validated Excel formula into an `.xlsx` (or `.csv` -> `.xlsx`) workbook.

    Returns ``(output_xlsx_path, chosen_cell_ref)`` after verifying via re-read that
    ``ws[chosen_cell_ref].value == formula``.
    """
    formula_clean = (formula or "").strip()
    if not formula_clean.startswith("="):
        raise ValueError("Refusing to write formula: must start with '='.")
    err = validate_formula(formula_clean)
    if err is not None:
        err_type, err_msg = err
        raise ValueError(f"Refusing to write unsafe/invalid formula ({err_type}): {err_msg}")

    # Load source workbook or convert CSV -> XLSX
    stem = "formulalm_sheet"
    if isinstance(src_bytes_or_path, (str, Path)):
        src_path = Path(src_bytes_or_path)
        if not src_path.is_file():
            raise ValueError(f"Source spreadsheet not found: {src_path}")
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", src_path.stem).strip("_") or stem
        suffix = (source_suffix or src_path.suffix).lower()
        if suffix == ".csv":
            wb = _workbook_from_csv(src_path, sheet_title=stem)
        elif suffix == ".xlsx":
            wb = openpyxl.load_workbook(src_path)
        else:
            raise ValueError(f"Unsupported spreadsheet format {suffix!r}; expected .xlsx or .csv.")
    elif isinstance(src_bytes_or_path, (bytes, bytearray)):
        raw = bytes(src_bytes_or_path)
        suffix = (source_suffix or ".xlsx").lower()
        if suffix == ".csv":
            wb = _workbook_from_csv(raw, sheet_title=sheet_name or "Sheet1")
        elif suffix == ".xlsx":
            wb = openpyxl.load_workbook(io.BytesIO(raw))
        else:
            raise ValueError(f"Unsupported spreadsheet format {suffix!r}; expected .xlsx or .csv.")
    else:
        raise TypeError("src_bytes_or_path must be bytes, str, or Path.")

    try:
        if sheet_name and sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            ws = wb.active
            if ws is None:
                raise ValueError("Workbook has no active worksheet.")
        chosen_sheet = ws.title

        raw_target = (target_cell or "").strip()
        if raw_target.lower() in _AUTO_LABELS:
            summary_row = (ws.max_row or 1) + 2
            label_cell = f"A{summary_row}"
            chosen_cell = f"B{summary_row}"
            ws[label_cell] = "FormulaLM Result"
            ws[label_cell].font = Font(bold=True)
            ws[chosen_cell] = formula_clean
        else:
            chosen_cell = validate_cell_ref(raw_target)
            existing = ws[chosen_cell].value
            if existing is not None and str(existing).strip() != "" and not allow_overwrite:
                raise ValueError(
                    f"Cell {chosen_cell} already contains {existing!r}. "
                    "Choose an empty cell or check 'Allow overwrite'."
                )
            ws[chosen_cell] = formula_clean

        dest_dir = Path(out_dir) if out_dir is not None else Path(tempfile.gettempdir())
        dest_dir.mkdir(parents=True, exist_ok=True)
        out_path = dest_dir / f"{stem}_formulalm_{uuid.uuid4().hex[:8]}.xlsx"
        wb.save(out_path)
    finally:
        wb.close()

    # Verify round-trip formula preservation via openpyxl
    verify_wb = openpyxl.load_workbook(out_path, data_only=False)
    try:
        actual = verify_wb[chosen_sheet][chosen_cell].value
        if actual != formula_clean:
            raise RuntimeError(
                f"Round-trip verification failed at {chosen_sheet}!{chosen_cell}: "
                f"got {actual!r}, expected {formula_clean!r}."
            )
    finally:
        verify_wb.close()

    return out_path, chosen_cell
