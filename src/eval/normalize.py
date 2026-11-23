"""Formula normalization (for exact match) and type-aware value comparison."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
from openpyxl.utils import column_index_from_string

EXCEL_EPOCH_DATE = date(1899, 12, 30)
EXCEL_EPOCH_DT = datetime(1899, 12, 30, 0, 0, 0)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Matches optional default sheet prefix ('Sheet1'! or Sheet1!) + cell/col/row range or cell ref.
_SHEET_PREFIX_RE = re.compile(r"(?:'Sheet1'|Sheet1)!", re.IGNORECASE)
_RANGE_CELL_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(\$?[A-Za-z]{1,3}\$?\d+:\$?[A-Za-z]{1,3}\$?\d+"
    r"|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}"
    r"|\$?\d+:\$?\d+"
    r"|\$?[A-Za-z]{1,3}\$?\d+)"
    r"(?![A-Za-z0-9_(])"
)
_CELL_PART_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")
_COL_PART_RE = re.compile(r"^\$?([A-Za-z]{1,3})$")
_ROW_PART_RE = re.compile(r"^\$?(\d+)$")
_FUNC_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_BOOL_LIT_RE = re.compile(r"(?<![A-Za-z0-9_])(true|false)(?![A-Za-z0-9_(])", re.IGNORECASE)


def split_formula_segments(formula: str) -> list[tuple[bool, str]]:
    """Split a formula into ``(is_string_literal, segment)`` chunks.

    Properly handles Excel's doubled-quote escape (``""``) inside double-quoted strings.
    Raises ``ValueError`` if a string literal is unclosed.
    """
    segments: list[tuple[bool, str]] = []
    buf: list[str] = []
    in_str = False
    i = 0
    n = len(formula)

    while i < n:
        ch = formula[i]
        if in_str:
            buf.append(ch)
            if ch == '"':
                if i + 1 < n and formula[i + 1] == '"':
                    buf.append('"')
                    i += 2
                    continue
                segments.append((True, "".join(buf)))
                buf = []
                in_str = False
            i += 1
        else:
            if ch == '"':
                if buf:
                    segments.append((False, "".join(buf)))
                    buf = []
                buf.append(ch)
                in_str = True
            else:
                buf.append(ch)
            i += 1

    if in_str:
        raise ValueError("Unclosed string literal in formula")
    if buf:
        segments.append((False, "".join(buf)))
    return segments


def _canonicalize_ref(token: str) -> str:
    """Canonicalize a cell or range reference: strip $, uppercase, sort endpoints."""
    clean = token.replace("$", "").upper()
    if ":" not in clean:
        m = _CELL_PART_RE.match(clean)
        if m:
            col, row = m.group(1), str(int(m.group(2)))
            return f"{col}{row}"
        return clean

    left, right = clean.split(":", 1)
    m1, m2 = _CELL_PART_RE.match(left), _CELL_PART_RE.match(right)
    if m1 and m2:
        c1, r1 = column_index_from_string(m1.group(1)), int(m1.group(2))
        c2, r2 = column_index_from_string(m2.group(1)), int(m2.group(2))
        col_lo, col_hi = (m1.group(1), m2.group(1)) if c1 <= c2 else (m2.group(1), m1.group(1))
        row_lo, row_hi = min(r1, r2), max(r1, r2)
        return f"{col_lo}{row_lo}:{col_hi}{row_hi}"

    mc1, mc2 = _COL_PART_RE.match(left), _COL_PART_RE.match(right)
    if mc1 and mc2:
        c1, c2 = column_index_from_string(mc1.group(1)), column_index_from_string(mc2.group(1))
        lo, hi = (mc1.group(1), mc2.group(1)) if c1 <= c2 else (mc2.group(1), mc1.group(1))
        return f"{lo}:{hi}"

    mr1, mr2 = _ROW_PART_RE.match(left), _ROW_PART_RE.match(right)
    if mr1 and mr2:
        r1, r2 = int(mr1.group(1)), int(mr2.group(1))
        return f"{min(r1, r2)}:{max(r1, r2)}"

    return clean


def normalize_formula(formula: str) -> str:
    """Normalize an Excel formula for exact-match comparison.

    Rules:
    - Trim outer whitespace.
    - Keep double-quoted string literals intact (case and spaces preserved).
    - Outside strings: remove spaces/tabs, strip default ``Sheet1!`` prefixes,
      uppercase function names and boolean literals, and canonicalize cell/range
      references (strip ``$``, uppercase columns, order range endpoints).
    """
    text = formula.strip()
    if not text:
        return ""

    try:
        segments = split_formula_segments(text)
    except ValueError:
        # Best-effort fallback for malformed formulas (e.g., unclosed quotes).
        return re.sub(r"\s+", "", text)

    out: list[str] = []
    for is_str, seg in segments:
        if is_str:
            out.append(seg)
            continue
        code = re.sub(r"[ \t]+", "", seg)
        code = _SHEET_PREFIX_RE.sub("", code)
        code = _FUNC_CALL_RE.sub(lambda m: f"{m.group(1).upper()}(", code)
        code = _BOOL_LIT_RE.sub(lambda m: m.group(1).upper(), code)
        code = _RANGE_CELL_RE.sub(lambda m: _canonicalize_ref(m.group(1)), code)
        out.append(code)

    return "".join(out)


def exact_match(predicted: str, expected: str) -> bool:
    """Return True if two formulas match after canonical normalization."""
    return normalize_formula(predicted) == normalize_formula(expected)


def date_to_excel_serial(value: date | datetime) -> int | float:
    """Convert a Python ``date`` or ``datetime`` to an Excel 1900 serial number."""
    if isinstance(value, datetime):
        delta = value - EXCEL_EPOCH_DT
        if delta.seconds == 0 and delta.microseconds == 0:
            return delta.days
        return delta.days + (delta.seconds + delta.microseconds / 1_000_000.0) / 86400.0
    return (value - EXCEL_EPOCH_DATE).days


def _unwrap_scalar(val: Any) -> Any:
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return float(val)
    if isinstance(val, np.str_):
        return str(val)
    if isinstance(val, pd.Timestamp):
        return val.to_pydatetime()
    return val


def _is_empty(val: Any) -> bool:
    if val is None or val is pd.NA or val is pd.NaT:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    return False


def _is_number(val: Any) -> bool:
    return isinstance(val, int | float) and not isinstance(val, bool)


def _try_parse_iso_date(val: Any) -> date | None:
    if isinstance(val, str) and _ISO_DATE_RE.match(val.strip()):
        try:
            return date.fromisoformat(val.strip())
        except ValueError:
            return None
    return None


def values_equal(
    actual: Any,
    expected: Any,
    *,
    tol: float = 1e-6,
    case_sensitive: bool = True,
) -> bool:
    """Type-aware comparison for evaluated Excel formula outputs vs expected values.

    - Booleans are strictly distinct from numbers (``True != 1``).
    - Numbers compare within absolute tolerance ``tol`` (default ``1e-6``).
    - Dates compare against ``date``/``datetime``, Excel serial numbers, or ISO date strings
      when at least one side is a ``date``/``datetime``.
    - Strings compare strictly without trimming whitespace (so ``TRIM`` is tested accurately).
    """
    a = _unwrap_scalar(actual)
    b = _unwrap_scalar(expected)

    a_empty = _is_empty(a)
    b_empty = _is_empty(b)
    if a_empty or b_empty:
        return a_empty and b_empty

    # Booleans first (bool subclasses int in Python).
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and (a is b)

    # Date / datetime comparisons (including Excel serial number equivalence).
    if isinstance(a, date | datetime) or isinstance(b, date | datetime):
        a_serial: int | float | None = None
        b_serial: int | float | None = None

        if isinstance(a, date | datetime):
            a_serial = date_to_excel_serial(a)
        elif _is_number(a):
            a_serial = a
        else:
            parsed = _try_parse_iso_date(a)
            if parsed is not None:
                a_serial = date_to_excel_serial(parsed)

        if isinstance(b, date | datetime):
            b_serial = date_to_excel_serial(b)
        elif _is_number(b):
            b_serial = b
        else:
            parsed = _try_parse_iso_date(b)
            if parsed is not None:
                b_serial = date_to_excel_serial(parsed)

        if a_serial is None or b_serial is None:
            return False
        return abs(float(a_serial) - float(b_serial)) <= tol

    # Numeric comparisons (int / float).
    if _is_number(a) and _is_number(b):
        fa, fb = float(a), float(b)
        if math.isnan(fa) or math.isnan(fb) or math.isinf(fa) or math.isinf(fb):
            return False
        if abs(fa - fb) <= tol:
            return True
        # Guard float representation noise on very large magnitudes (> 1e9).
        return max(abs(fa), abs(fb)) > 1e9 and math.isclose(fa, fb, rel_tol=1e-9, abs_tol=tol)

    # Text comparisons.
    if isinstance(a, str) and isinstance(b, str):
        return a == b if case_sensitive else a.lower() == b.lower()

    return False
