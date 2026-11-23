"""Safe executable Excel formula evaluator.

Primary engine: Python ``formulas`` library (compiling the formula AST directly against a
cached sheet grid, which is ~20x faster than rebuilding a full ``ExcelModel`` per call and
handles full-column references cleanly).
Fallback engine: LibreOffice headless (``soffice --headless``), if installed on the machine.

Safety guarantees:
- Never calls Python ``eval``/``exec`` and never invokes a shell (``shell=False``).
- Enforces an explicit function allow-list (the 36 in-scope Excel functions).
- Rejects external workbook/sheet references, URLs/UNC paths, DDE syntax and circular refs.
- Enforces bounded cell allocation and per-formula execution timeouts.
"""

from __future__ import annotations

import csv
import functools
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault("TQDM_DISABLE", "1")
warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"formulas(\.|$)")

import formulas  # noqa: E402
import numpy as np  # noqa: E402
import openpyxl  # noqa: E402
import schedula as sh  # noqa: E402
from formulas.functions import Array  # noqa: E402
from formulas.tokens.operand import XlError  # noqa: E402
from openpyxl.utils import (  # noqa: E402
    column_index_from_string,
    coordinate_to_tuple,
    get_column_letter,
)

from src.eval.normalize import (  # noqa: E402
    date_to_excel_serial,
    exact_match,
    normalize_formula,
    split_formula_segments,
    values_equal,
)

__all__ = [
    "ALLOWED_FUNCTIONS",
    "ErrorType",
    "ExecutionResult",
    "check_engine_availability",
    "exact_match",
    "find_libreoffice",
    "normalize_formula",
    "run_formula",
    "validate_formula",
    "values_equal",
]

ErrorType = Literal["syntax_error", "unsupported_function", "runtime_error", "timeout"]

# Exact 36 in-scope Excel functions from docs/BRIEF.md (volatile functions excluded).
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # Aggregation & conditional aggregation
        "SUM",
        "SUMIF",
        "SUMIFS",
        "COUNT",
        "COUNTIF",
        "COUNTIFS",
        "AVERAGE",
        "AVERAGEIF",
        "AVERAGEIFS",
        "MIN",
        "MAX",
        # Logic
        "IF",
        "IFS",
        "AND",
        "OR",
        # Lookup
        "VLOOKUP",
        "XLOOKUP",
        "INDEX",
        "MATCH",
        # Text
        "LEFT",
        "RIGHT",
        "MID",
        "LEN",
        "CONCAT",
        "TEXTJOIN",
        "UPPER",
        "LOWER",
        "PROPER",
        "TRIM",
        "TEXT",
        # Date
        "DATE",
        "YEAR",
        "MONTH",
        "DAY",
        # Math & error handling
        "ROUND",
        "IFERROR",
    }
)

EXCEL_ERROR_CODES: frozenset[str] = frozenset(
    {
        "#DIV/0!",
        "#N/A",
        "#VALUE!",
        "#REF!",
        "#NAME?",
        "#NUM!",
        "#NULL!",
        "#CALC!",
        "#SPILL!",
    }
)

MAX_FORMULA_LENGTH = 2000
MAX_RANGE_CELLS = 100_000
DEFAULT_TIMEOUT_SECONDS = 5.0

_FUNC_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_SHEET_REF_RE = re.compile(r"(?:'([^']+)'|([A-Za-z0-9_.\-]+))!")
_EXTERNAL_SCHEME_RE = re.compile(r"(?:https?://|file://|\\\\)", re.IGNORECASE)
_TARGET_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_RE = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of running a single Excel formula against a sheet."""

    ok: bool
    value: Any = None
    value_type: str | None = None
    error_type: ErrorType | None = None
    error_message: str | None = None
    engine: str = "formulas"
    target_cell: str | None = None


def find_libreoffice() -> Path | None:
    """Locate the LibreOffice ``soffice`` executable on this machine, if installed."""
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return Path(found)

    candidates = (
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path("/usr/bin/soffice"),
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def check_engine_availability() -> dict[str, Any]:
    """Report which spreadsheet engines are available on the current machine."""
    lo_path = find_libreoffice()
    return {
        "formulas_version": getattr(formulas, "__version__", "unknown"),
        "libreoffice_available": lo_path is not None,
        "libreoffice_path": str(lo_path) if lo_path is not None else None,
        "allowed_functions_count": len(ALLOWED_FUNCTIONS),
    }


def _check_balanced_parens(code_only: str) -> bool:
    depth = 0
    for ch in code_only:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def validate_formula(
    formula: str,
    *,
    active_sheet: str = "Sheet1",
    allowed_functions: frozenset[str] = ALLOWED_FUNCTIONS,
) -> tuple[ErrorType, str] | None:
    """Run static safety, syntax and allow-list checks before formula execution.

    Returns ``None`` if valid, or ``(error_type, error_message)`` if rejected.
    """
    if not isinstance(formula, str):
        return ("syntax_error", "Formula must be a string")

    text = formula.strip()
    if not text:
        return ("syntax_error", "Formula is empty")
    if len(text) > MAX_FORMULA_LENGTH:
        return ("syntax_error", f"Formula exceeds maximum length ({MAX_FORMULA_LENGTH})")
    if any(ord(ch) < 32 for ch in text):
        return ("syntax_error", "Formula contains control characters or newlines")
    if not text.startswith("="):
        return ("syntax_error", "Formula must start with '='")
    if len(text) == 1:
        return ("syntax_error", "Formula has no expression after '='")

    try:
        segments = split_formula_segments(text)
    except ValueError as exc:
        return ("syntax_error", str(exc))

    code_only = "".join(seg for is_str, seg in segments if not is_str)

    if not _check_balanced_parens(code_only):
        return ("syntax_error", "Unbalanced parentheses in formula")

    # Reject external workbook references, DDE syntax and URLs/UNC paths outside strings.
    if "[" in code_only or "]" in code_only:
        return ("syntax_error", "External workbook or bracket reference is not allowed")
    if "|" in code_only:
        return ("syntax_error", "External DDE pipe syntax is not allowed")
    if _EXTERNAL_SCHEME_RE.search(code_only):
        return ("syntax_error", "External URL or UNC path is not allowed")

    # Allow sheet prefixes only when they point to the active sheet itself.
    for m in _SHEET_REF_RE.finditer(code_only):
        sheet_ref = m.group(1) or m.group(2) or ""
        if sheet_ref.lower() != active_sheet.lower():
            return (
                "syntax_error",
                f"External sheet reference '{sheet_ref}!' is not allowed",
            )
    if "!" in _SHEET_REF_RE.sub("", code_only):
        return ("syntax_error", "Malformed sheet reference '!' in formula")

    # Enforce strict function allow-list.
    used_funcs = {m.group(1).upper() for m in _FUNC_CALL_RE.finditer(code_only)}
    disallowed = sorted(used_funcs - allowed_functions)
    if disallowed:
        return (
            "unsupported_function",
            f"Function(s) not in allow-list: {', '.join(disallowed)}",
        )

    return None


def _to_excel_cell(val: Any) -> Any:
    if val is None:
        return sh.EMPTY
    if isinstance(val, bool):
        return val
    if isinstance(val, date | datetime):
        return date_to_excel_serial(val)
    return val


def _parse_csv_cell(raw: str) -> Any:
    if raw == "":
        return sh.EMPTY
    upper = raw.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    if _ISO_DATE_RE.match(raw):
        try:
            return date_to_excel_serial(date.fromisoformat(raw))
        except ValueError:
            return raw
    if _INT_RE.match(raw):
        return int(raw)
    try:
        num = float(raw)
        if not (math.isnan(num) or math.isinf(num)):
            return num
    except ValueError:
        pass
    return raw


@functools.lru_cache(maxsize=64)
def _load_sheet_cached(
    resolved_path: str, mtime_ns: int, file_size: int
) -> tuple[str, np.ndarray, int, int]:
    """Load an XLSX or CSV sheet into a read-only 2D numpy grid cached by path/mtime/size."""
    del mtime_ns, file_size  # part of the cache key
    path = Path(resolved_path)
    suffix = path.suffix.lower()

    if suffix == ".xlsx":
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            ws = wb.active
            sheet_name = ws.title or "Sheet1"
            rows = [tuple(_to_excel_cell(c) for c in row) for row in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    elif suffix == ".csv":
        sheet_name = "Sheet1"
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = [tuple(_parse_csv_cell(cell) for cell in row) for row in reader]
    else:
        raise ValueError(f"Unsupported sheet format '{suffix}' (expected .xlsx or .csv)")

    max_r = len(rows)
    max_c = max((len(r) for r in rows), default=0)
    grid = np.empty((max_r, max_c), dtype=object)
    grid.fill(sh.EMPTY)
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            grid[r_idx, c_idx] = val
    grid.flags.writeable = False
    return sheet_name, grid, max_r, max_c


def _load_sheet(sheet_path: str | Path) -> tuple[str, np.ndarray, int, int]:
    path = Path(sheet_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Sheet file not found: {path}")
    stat = path.stat()
    return _load_sheet_cached(str(path), stat.st_mtime_ns, stat.st_size)


def _parse_target_cell(target_cell: str | None, max_c: int) -> tuple[str, tuple[int, int]]:
    if target_cell is None:
        col_letter = get_column_letter(max(max_c + 2, 1))
        return f"{col_letter}2", (2, max(max_c + 2, 1))
    m = _TARGET_CELL_RE.match(target_cell.strip())
    if not m:
        raise ValueError(f"Invalid target_cell coordinate: {target_cell!r}")
    col_letter = m.group(1).upper()
    row_num = int(m.group(2))
    if row_num < 1:
        raise ValueError(f"Invalid target_cell row: {target_cell!r}")
    return f"{col_letter}{row_num}", (row_num, column_index_from_string(col_letter))


class _RefRuntimeError(Exception):
    """Raised when a reference fails bounds or circularity checks."""


def _slice_reference(
    ref: str,
    grid: np.ndarray,
    max_r: int,
    max_c: int,
    target_rc: tuple[int, int],
    active_sheet: str,
) -> Any:
    raw = ref.strip()
    if "!" in raw:
        sheet_part, coord_part = raw.rsplit("!", 1)
        clean_sheet = sheet_part.strip().strip("'")
        if clean_sheet.lower() != active_sheet.lower():
            raise _RefRuntimeError(f"External sheet reference '{clean_sheet}!' is not allowed")
    else:
        coord_part = raw

    coord = coord_part.replace("$", "").upper()
    tr, tc = target_rc

    if ":" in coord:
        left, right = coord.split(":", 1)
        if left.isalpha() and right.isalpha():
            c1, c2 = column_index_from_string(left), column_index_from_string(right)
            r1, r2 = 1, max(max_r, 1)
        elif left.isdigit() and right.isdigit():
            r1, r2 = int(left), int(right)
            c1, c2 = 1, max(max_c, 1)
        else:
            r1, c1 = coordinate_to_tuple(left)
            r2, c2 = coordinate_to_tuple(right)

        r1, r2 = min(r1, r2), max(r1, r2)
        c1, c2 = min(c1, c2), max(c1, c2)

        if r1 <= tr <= r2 and c1 <= tc <= c2:
            raise _RefRuntimeError(f"Circular reference includes target cell R{tr}C{tc}")

        n_rows = r2 - r1 + 1
        n_cols = c2 - c1 + 1
        if n_rows * n_cols > MAX_RANGE_CELLS:
            raise _RefRuntimeError(
                f"Reference {ref!r} spans {n_rows * n_cols} cells (limit {MAX_RANGE_CELLS})"
            )

        if 1 <= r1 and r2 <= max_r and 1 <= c1 and c2 <= max_c:
            return grid[r1 - 1 : r2, c1 - 1 : c2].copy().view(Array)

        arr = np.empty((n_rows, n_cols), dtype=object)
        arr.fill(sh.EMPTY)
        ov_r1, ov_r2 = max(r1, 1), min(r2, max_r)
        ov_c1, ov_c2 = max(c1, 1), min(c2, max_c)
        if ov_r1 <= ov_r2 and ov_c1 <= ov_c2:
            arr[ov_r1 - r1 : ov_r2 - r1 + 1, ov_c1 - c1 : ov_c2 - c1 + 1] = grid[
                ov_r1 - 1 : ov_r2, ov_c1 - 1 : ov_c2
            ]
        return arr.view(Array)

    r, c = coordinate_to_tuple(coord)
    if (r, c) == (tr, tc):
        raise _RefRuntimeError(f"Circular self-reference to target cell R{tr}C{tc}")
    if 1 <= r <= max_r and 1 <= c <= max_c:
        return grid[r - 1, c - 1]
    return sh.EMPTY


def _classify_and_unwrap(raw_val: Any, engine: str, target_cell: str) -> ExecutionResult:
    val = raw_val
    # Peel 1x1 arrays returned by `formulas`.
    while isinstance(val, np.ndarray):
        if val.size == 0:
            val = sh.EMPTY
            break
        if val.size > 1:
            return ExecutionResult(
                ok=False,
                error_type="runtime_error",
                error_message=f"Formula returned a multi-cell array of shape {val.shape}",
                engine=engine,
                target_cell=target_cell,
            )
        val = val.flat[0]

    if isinstance(val, XlError):
        return ExecutionResult(
            ok=False,
            error_type="runtime_error",
            error_message=f"Excel error: {val}",
            engine=engine,
            target_cell=target_cell,
        )

    if val is sh.EMPTY or val is None:
        return ExecutionResult(
            ok=True, value=None, value_type="empty", engine=engine, target_cell=target_cell
        )

    if isinstance(val, bool | np.bool_):
        return ExecutionResult(
            ok=True,
            value=bool(val),
            value_type="boolean",
            engine=engine,
            target_cell=target_cell,
        )

    if isinstance(val, int | np.integer):
        return ExecutionResult(
            ok=True,
            value=int(val),
            value_type="number",
            engine=engine,
            target_cell=target_cell,
        )

    if isinstance(val, float | np.floating):
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return ExecutionResult(
                ok=False,
                error_type="runtime_error",
                error_message=f"Formula produced non-finite number: {fval}",
                engine=engine,
                target_cell=target_cell,
            )
        return ExecutionResult(
            ok=True,
            value=fval,
            value_type="number",
            engine=engine,
            target_cell=target_cell,
        )

    if isinstance(val, date | datetime):
        return ExecutionResult(
            ok=True,
            value=val,
            value_type="date",
            engine=engine,
            target_cell=target_cell,
        )

    if isinstance(val, str | np.str_):
        sval = str(val)
        if sval.upper() in EXCEL_ERROR_CODES:
            return ExecutionResult(
                ok=False,
                error_type="runtime_error",
                error_message=f"Excel error: {sval}",
                engine=engine,
                target_cell=target_cell,
            )
        return ExecutionResult(
            ok=True,
            value=sval,
            value_type="text",
            engine=engine,
            target_cell=target_cell,
        )

    return ExecutionResult(
        ok=False,
        error_type="runtime_error",
        error_message=f"Unsupported return type: {type(val).__name__}",
        engine=engine,
        target_cell=target_cell,
    )


def _eval_with_formulas(
    formula: str,
    active_sheet: str,
    grid: np.ndarray,
    max_r: int,
    max_c: int,
    target_cell: str,
    target_rc: tuple[int, int],
    timeout: float,
) -> ExecutionResult:
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            parser = formulas.Parser()
            try:
                ast_tokens, builder = parser.ast(formula)
                del ast_tokens
                compiled = builder.compile()
            except Exception as exc:
                box["result"] = ExecutionResult(
                    ok=False,
                    error_type="syntax_error",
                    error_message=f"{type(exc).__name__}: {exc}",
                    engine="formulas",
                    target_cell=target_cell,
                )
                return

            try:
                kwargs = {
                    inp: _slice_reference(inp, grid, max_r, max_c, target_rc, active_sheet)
                    for inp in compiled.inputs
                }
            except _RefRuntimeError as exc:
                box["result"] = ExecutionResult(
                    ok=False,
                    error_type="runtime_error",
                    error_message=str(exc),
                    engine="formulas",
                    target_cell=target_cell,
                )
                return
            except Exception as exc:
                box["result"] = ExecutionResult(
                    ok=False,
                    error_type="syntax_error",
                    error_message=f"Invalid cell reference: {exc}",
                    engine="formulas",
                    target_cell=target_cell,
                )
                return

            try:
                raw_out = compiled(**kwargs)
            except NotImplementedError as exc:
                box["result"] = ExecutionResult(
                    ok=False,
                    error_type="unsupported_function",
                    error_message=f"Engine does not implement function: {exc}",
                    engine="formulas",
                    target_cell=target_cell,
                )
                return
            except Exception as exc:
                box["result"] = ExecutionResult(
                    ok=False,
                    error_type="runtime_error",
                    error_message=f"{type(exc).__name__}: {exc}",
                    engine="formulas",
                    target_cell=target_cell,
                )
                return

            box["result"] = _classify_and_unwrap(raw_out, "formulas", target_cell)
        except Exception as exc:  # pragma: no cover - defensive catch-all
            box["result"] = ExecutionResult(
                ok=False,
                error_type="runtime_error",
                error_message=f"{type(exc).__name__}: {exc}",
                engine="formulas",
                target_cell=target_cell,
            )

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        return ExecutionResult(
            ok=False,
            error_type="timeout",
            error_message=f"Formula execution exceeded timeout ({timeout:.2f}s)",
            engine="formulas",
            target_cell=target_cell,
        )
    return box["result"]


def _eval_with_libreoffice(
    formula: str,
    sheet_path: Path,
    target_cell: str,
    timeout: float,
    soffice_path: Path,
) -> ExecutionResult:
    """Evaluate a formula using LibreOffice headless without invoking a shell."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        in_xlsx = tmp / "input.xlsx"
        out_dir = tmp / "out"
        out_dir.mkdir()

        if sheet_path.suffix.lower() == ".xlsx":
            wb = openpyxl.load_workbook(sheet_path)
            ws = wb.active
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Sheet1"
            with sheet_path.open("r", encoding="utf-8", newline="") as f:
                for row in csv.reader(f):
                    ws.append([None if c == "" else _parse_csv_cell(c) for c in row])

        ws[target_cell] = formula
        wb.save(in_xlsx)
        wb.close()

        try:
            subprocess.run(
                [
                    str(soffice_path),
                    "--headless",
                    "--norestore",
                    "--convert-to",
                    "xlsx",
                    "--outdir",
                    str(out_dir),
                    str(in_xlsx),
                ],
                shell=False,
                capture_output=True,
                timeout=timeout,
                check=True,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                ok=False,
                error_type="timeout",
                error_message=f"LibreOffice execution exceeded timeout ({timeout:.2f}s)",
                engine="libreoffice",
                target_cell=target_cell,
            )
        except subprocess.SubprocessError as exc:
            return ExecutionResult(
                ok=False,
                error_type="runtime_error",
                error_message=f"LibreOffice error: {exc}",
                engine="libreoffice",
                target_cell=target_cell,
            )

        out_xlsx = out_dir / "input.xlsx"
        if not out_xlsx.is_file():
            return ExecutionResult(
                ok=False,
                error_type="runtime_error",
                error_message="LibreOffice did not produce an evaluated workbook",
                engine="libreoffice",
                target_cell=target_cell,
            )

        wb_out = openpyxl.load_workbook(out_xlsx, data_only=True)
        try:
            raw_val = wb_out.active[target_cell].value
        finally:
            wb_out.close()

    return _classify_and_unwrap(raw_val, "libreoffice", target_cell)


def run_formula(
    formula: str,
    sheet_path: str | Path,
    target_cell: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    engine: Literal["auto", "formulas", "libreoffice"] = "auto",
) -> ExecutionResult:
    """Safely execute an Excel formula against a spreadsheet and return its result or error.

    Args:
        formula: Excel formula string (must begin with ``=``).
        sheet_path: Path to an ``.xlsx`` or ``.csv`` sheet.
        target_cell: Free cell coordinate where the formula is placed (defaults to two columns
            past the rightmost column on row 2, e.g. ``I2`` for a 7-column sheet).
        timeout: Maximum execution time in seconds.
        engine: ``"auto"`` (try ``formulas``, fall back to LibreOffice if needed and available),
            ``"formulas"``, or ``"libreoffice"``.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    path = Path(sheet_path)
    try:
        active_sheet, grid, max_r, max_c = _load_sheet(path)
    except Exception as exc:
        return ExecutionResult(
            ok=False,
            error_type="runtime_error",
            error_message=f"Failed to load sheet: {exc}",
            engine=engine,
            target_cell=target_cell,
        )

    try:
        resolved_target, target_rc = _parse_target_cell(target_cell, max_c)
    except ValueError as exc:
        return ExecutionResult(
            ok=False,
            error_type="syntax_error",
            error_message=str(exc),
            engine=engine,
            target_cell=target_cell,
        )

    validation_err = validate_formula(formula, active_sheet=active_sheet)
    if validation_err is not None:
        err_type, err_msg = validation_err
        return ExecutionResult(
            ok=False,
            error_type=err_type,
            error_message=err_msg,
            engine="formulas" if engine == "auto" else engine,
            target_cell=resolved_target,
        )

    cleaned = formula.strip()

    if engine == "libreoffice":
        soffice = find_libreoffice()
        if soffice is None:
            return ExecutionResult(
                ok=False,
                error_type="runtime_error",
                error_message="LibreOffice (soffice) is not installed on this machine",
                engine="libreoffice",
                target_cell=resolved_target,
            )
        return _eval_with_libreoffice(cleaned, path, resolved_target, timeout, soffice)

    result = _eval_with_formulas(
        cleaned, active_sheet, grid, max_r, max_c, resolved_target, target_rc, timeout
    )
    if engine == "auto" and not result.ok and result.error_type == "unsupported_function":
        soffice = find_libreoffice()
        if soffice is not None:
            return _eval_with_libreoffice(cleaned, path, resolved_target, timeout, soffice)
    return result
