"""FormulaLM local Gradio demo application.

Compact, 1080p-ready light UI (fits without scrolling at 100-110% browser zoom):
- Header + hardware/quantization chips, two tabs: "Held-out examples" and "Your own sheet".
- 8 short example buttons across all 5 held-out sheets (including 1 red-outlined honest failure).
- Left (~40%): 5-row horizontally scrollable sheet preview, large request box, primary button.
- Right (~60%): large monospace formula with copy button, green/red/neutral verdict pill,
  one-line meta status (with background startup warm-up and Ollama keep_alive="30m"),
  and optional side-by-side saved Base 0-shot / Base 5-shot cards (never loads a 2nd model).
- Footer: two collapsed accordions ("Limits & scope" and "Show prompt sent to model").
- Localhost-only with system fonts only (zero Google Fonts, zero CDN, zero external assets).

CLI usage:
    uv run python app/app.py
    uv run python app/app.py --backend mock
    uv run python app/app.py --backend llamacpp --base-url http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import gradio as gr
import openpyxl
import pandas as pd
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from src.data.build_dataset import (  # noqa: E402
    SYSTEM_PROMPT,
    build_user_prompt,
    format_schema_text,
)
from src.data.templates import SheetContext, load_sheet_contexts  # noqa: E402
from src.eval.executor import ExecutionResult, run_formula  # noqa: E402
from src.eval.normalize import values_equal  # noqa: E402
from src.eval.run_eval import (  # noqa: E402
    LlamaCppBackend,
    OllamaBackend,
    extract_formula,
    load_eval_examples,
)

# ---------------------------------------------------------------------------
# Constants & safety limits
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 1_048_576  # 1.0 MB upload cap
MAX_UPLOAD_ROWS = 2_000
MAX_UPLOAD_COLS = 26  # Columns A..Z
PREVIEW_ROWS = 5
MAX_NEW_TOKENS = 96
DEFAULT_SEED = 42
DEFAULT_OLLAMA_KEEP_ALIVE = "30m"

CUSTOM_SHEET_KEY = "__custom__"
LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_HEADER_PREFIX_RE = re.compile(r"^\s*(?:[A-Z]{1,2}\s*:\s*)?(.+?)(?:\s*\(\s*([A-Za-z_]+)\s*\))?\s*$")


# ---------------------------------------------------------------------------
# Built-in examples (8 from test_real_v2 across all 5 held-out sheets,
# including 1 honestly labeled failure case)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuiltinExample:
    example_id: str
    short_label: str
    label: str
    sheet_id: str
    request: str
    is_honest_failure: bool = False
    note: str = ""


BUILTIN_EXAMPLES: tuple[BuiltinExample, ...] = (
    BuiltinExample(
        example_id="real_v2_005",
        short_label="COUNTIFS",
        label="1. [Sales — COUNTIFS] Brinport sales with Quantity >= 15",
        sheet_id="sales_retail_store",
        request="How many Brinport sales had Quantity of at least 15?",
    ),
    BuiltinExample(
        example_id="real_v2_006",
        short_label="IF + AND",
        label="2. [Sales — IF + AND] Classify row 10 as 'Bulk High' vs 'Standard'",
        sheet_id="sales_retail_store",
        request=(
            "On row 10, return 'Bulk High' if Quantity >= 20 and Net Amount > 500, "
            "otherwise 'Standard'"
        ),
    ),
    BuiltinExample(
        example_id="real_v2_015",
        short_label="SUMIFS (HR)",
        label="3. [HR — SUMIFS] Total Annual Salary for Design staff in Stonewick",
        sheet_id="hr_employee_roster",
        request="Total Annual Salary for Design staff based in Stonewick",
    ),
    BuiltinExample(
        example_id="real_v2_017",
        short_label="INDEX + MATCH",
        label="4. [HR — INDEX + MATCH] Find Work Hub for employee EMP-1010",
        sheet_id="hr_employee_roster",
        request="Find the Work Hub for employee EMP-1010 using INDEX and MATCH",
    ),
    BuiltinExample(
        example_id="real_v2_027",
        short_label="XLOOKUP",
        label="5. [Inventory — XLOOKUP] Look up Valuation for movement MOV-1010",
        sheet_id="inventory_stock_movements",
        request="Look up the Valuation for MOV-1010 using XLOOKUP",
    ),
    BuiltinExample(
        example_id="real_v2_040",
        short_label="IFERROR + ROUND",
        label="6. [Grades — IFERROR + ROUND + SUMIF/SUM] Physics share of Assignments Done",
        sheet_id="grades_course_scores",
        request=(
            "Share of total Assignments Done completed by Physics students, "
            "rounded to 3 decimals (0 on error)"
        ),
    ),
    BuiltinExample(
        example_id="real_v2_045",
        short_label="SUMIFS (Orders)",
        label="7. [Orders — SUMIFS] Shipping Fee for Shipped Marketplace orders",
        sheet_id="orders_ecommerce",
        request="Total Shipping Fee for Marketplace orders that are Shipped",
    ),
    BuiltinExample(
        example_id="real_v2_050",
        short_label="Honest failure",
        label=(
            "8. [HONEST FAILURE — model is WRONG] Orders VLOOKUP Order Total for ORD-1015 "
            "(off-by-one column index)"
        ),
        sheet_id="orders_ecommerce",
        request="VLOOKUP Order Total for ORD-1015 rounded to 1 decimal, returning 0 if not found",
        is_honest_failure=True,
        note=(
            "Q5_K_M writes valid Excel syntax but picks column 6 (Discount %, 11) instead of "
            "column 7 (Order Total, 533). Execution catches the mistake."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Localhost security guard & Modelfile metadata
# ---------------------------------------------------------------------------


def assert_localhost_url(url: str) -> str:
    """Ensure the inference server URL strictly targets localhost (no external calls)."""
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid backend URL scheme in {url!r} (expected http://localhost:...)")
    host = (parsed.hostname or "").lower()
    if host not in LOCALHOST_HOSTS:
        raise ValueError(
            f"External network calls are disabled at inference time: host {host!r} "
            "must be localhost, 127.0.0.1, or ::1."
        )
    return cleaned


def detect_modelfile_quant(modelfile_path: Path | None = None) -> tuple[str, str]:
    """Read ``deploy/Modelfile`` to report the configured GGUF filename and quantization."""
    path = modelfile_path or (REPO_ROOT / "deploy" / "Modelfile")
    gguf_name = "formulalm-qwen3-1.7b-v2-q5_k_m.gguf"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.upper().startswith("FROM "):
                gguf_name = Path(s[5:].strip().strip('"').strip("'")).name
                break
    upper = gguf_name.upper()
    for q in ("Q5_K_M", "Q8_0", "Q4_K_M", "F16"):
        if q in upper:
            return gguf_name, q
    return gguf_name, "GGUF"


def infer_quant_label(model_name: str, modelfile_quant: str) -> str:
    upper = model_name.upper()
    for q in ("Q5_K_M", "Q8_0", "Q4_K_M", "F16"):
        if q in upper:
            return q
    return modelfile_quant


# ---------------------------------------------------------------------------
# Offline Mock Backend (deterministic, no network)
# ---------------------------------------------------------------------------


class DemoMockBackend:
    """Deterministic offline backend for unit tests and dry runs."""

    def __init__(self, saved_q5_by_prompt: dict[tuple[str, str], str] | None = None) -> None:
        self.name = "mock:formulalm-q5_k_m"
        self.last_timings: dict[str, Any] = {"predicted_per_second": 999.0}
        self._saved = saved_q5_by_prompt or {}

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
    ) -> str:
        del max_tokens, seed
        user_msg = messages[-1]["content"] if messages else ""
        sheet_m = re.search(r"^Sheet:\s*([^\s(]+)", user_msg, flags=re.MULTILINE)
        req_m = re.search(r"\nRequest:\s*(.+)$", user_msg, flags=re.DOTALL)
        if sheet_m and req_m:
            key = (sheet_m.group(1).strip(), req_m.group(1).strip().lower())
            if key in self._saved:
                return self._saved[key]

        rows_m = re.search(r"\(rows\s+2\.\.(\d+)\)", user_msg)
        last_row = int(rows_m.group(1)) if rows_m else 6
        for line in user_msg.splitlines():
            col_m = re.match(r"^([A-Z]):\s*.+\((integer|decimal|number)\)\s*$", line.strip())
            if col_m:
                letter = col_m.group(1)
                return f"=SUM({letter}2:{letter}{last_row})"
        return "=LEN(A2)"


# ---------------------------------------------------------------------------
# Saved evaluation lookup (ground truth + offline Base Qwen3-1.7B comparison)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SavedEvalBundle:
    heldout_contexts: dict[str, SheetContext]
    ground_truth: dict[tuple[str, str], dict[str, Any]]
    base_zeroshot: dict[tuple[str, str], dict[str, Any]]
    base_5shot: dict[tuple[str, str], dict[str, Any]]
    local_q5_outputs: dict[tuple[str, str], str]


def _norm_key(sheet_id: str, request: str) -> tuple[str, str]:
    return (sheet_id.strip(), " ".join(request.strip().lower().split()))


def _load_jsonl_by_key(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        key = _norm_key(str(rec.get("sheet_id", "")), str(rec.get("request", "")))
        rec["_source_file"] = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        out[key] = rec
    return out


def load_saved_eval_bundle() -> SavedEvalBundle:
    """Load held-out sheets, ground truths, and saved base-model predictions once."""
    contexts_list = load_sheet_contexts(split="test")
    heldout_contexts = {c.sheet_id: c for c in contexts_list}

    ground_truth: dict[tuple[str, str], dict[str, Any]] = {}
    for split_name, rel_csv in (
        ("test_real_v2", "data/test_real_v2/test_real_v2.csv"),
        ("test_real", "data/test_real/test_real_DRAFT.csv"),
    ):
        csv_path = REPO_ROOT / rel_csv
        if csv_path.is_file():
            examples, _ = load_eval_examples(csv_path)
            for ex in examples:
                ground_truth[_norm_key(ex.sheet_id, ex.request)] = {
                    "id": ex.id,
                    "split": split_name,
                    "category": ex.category,
                    "difficulty": ex.difficulty,
                    "reference_formula": ex.reference_formula,
                    "expected_value": ex.expected_value,
                    "expected_type": ex.expected_type,
                }

    base_zeroshot: dict[tuple[str, str], dict[str, Any]] = {}
    for rel in (
        "results/baseline_zeroshot_real_v2/predictions.jsonl",
        "results/baseline_zeroshot_real/predictions.jsonl",
    ):
        base_zeroshot.update(_load_jsonl_by_key(REPO_ROOT / rel))

    base_5shot: dict[tuple[str, str], dict[str, Any]] = {}
    for rel in (
        "results/baseline_5shot_real_v2/predictions.jsonl",
        "results/baseline_5shot_real/predictions.jsonl",
    ):
        base_5shot.update(_load_jsonl_by_key(REPO_ROOT / rel))

    local_q5_outputs: dict[tuple[str, str], str] = {}
    for rel in (
        "results/local_benchmark/local_q5_k_m_real_v2/predictions.jsonl",
        "results/local_benchmark/local_q5_k_m_real/predictions.jsonl",
        "results/quant_q5_k_m_real_v2/predictions.jsonl",
        "results/quant_q5_k_m_real/predictions.jsonl",
    ):
        for k, rec in _load_jsonl_by_key(REPO_ROOT / rel).items():
            if k not in local_q5_outputs:
                local_q5_outputs[k] = str(rec.get("extracted_formula") or rec.get("raw_output", ""))

    return SavedEvalBundle(
        heldout_contexts=heldout_contexts,
        ground_truth=ground_truth,
        base_zeroshot=base_zeroshot,
        base_5shot=base_5shot,
        local_q5_outputs=local_q5_outputs,
    )


# ---------------------------------------------------------------------------
# Sheet loading, CSV/XLSX upload validation & pasted-header synthesis
# ---------------------------------------------------------------------------


@dataclass
class ResolvedSheet:
    sheet_id: str
    schema_text: str
    xlsx_path: Path
    preview_df: pd.DataFrame
    source_note: str
    total_rows: int = 5
    is_temp: bool = False


def _infer_series_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "text"
    if pd.api.types.is_bool_dtype(non_null):
        return "boolean"
    if pd.api.types.is_integer_dtype(non_null):
        return "integer"
    if pd.api.types.is_float_dtype(non_null):
        if all(float(v).is_integer() for v in non_null.head(50)):
            return "integer"
        return "decimal"
    if pd.api.types.is_datetime64_any_dtype(non_null):
        return "date"
    sample_strs = [str(v).strip() for v in non_null.head(30) if str(v).strip()]
    if sample_strs and all(re.match(r"^\d{4}-\d{2}-\d{2}$", s) for s in sample_strs):
        return "date"
    try:
        nums = [float(s) for s in sample_strs]
        if sample_strs:
            return "integer" if all(n.is_integer() for n in nums) else "decimal"
    except ValueError:
        pass
    if len(set(sample_strs)) <= max(3, len(sample_strs) // 2) and len(non_null) >= 6:
        return "category"
    return "text"


def _build_preview_df(df: pd.DataFrame, max_rows: int = PREVIEW_ROWS) -> pd.DataFrame:
    head = df.head(max_rows).copy()
    renamed: dict[str, str] = {}
    for idx, col in enumerate(head.columns):
        letter = get_column_letter(idx + 1)
        renamed[col] = f"{letter}: {col}"
    head = head.rename(columns=renamed)
    for col in head.columns:
        head[col] = head[col].map(
            lambda v: (
                ""
                if pd.isna(v)
                else (v.strftime("%Y-%m-%d") if isinstance(v, datetime | date) else str(v))
            )
        )
    head.insert(0, "Row", [str(r) for r in range(2, 2 + len(head))])
    return head


def _write_dataframe_to_temp_xlsx(df: pd.DataFrame) -> Path:
    fd, tmp_name = tempfile.mkstemp(prefix="formulalm_demo_", suffix=".xlsx")
    os.close(fd)
    tmp_path = Path(tmp_name)
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet1"
    ws.append([str(c) for c in df.columns])
    for row in df.itertuples(index=False, name=None):
        cleaned_row: list[Any] = []
        for val in row:
            if pd.isna(val):
                cleaned_row.append(None)
            elif isinstance(val, str) and re.match(r"^[+-]?\d+$", val.strip()):
                cleaned_row.append(int(val.strip()))
            elif isinstance(val, str):
                try:
                    cleaned_row.append(float(val.strip()))
                except ValueError:
                    cleaned_row.append(val)
            else:
                cleaned_row.append(val)
        ws.append(cleaned_row)
    wb.save(tmp_path)
    wb.close()
    return tmp_path


def _format_df_schema(sheet_id: str, df: pd.DataFrame, col_types: list[str] | None = None) -> str:
    last_row = max(2, len(df) + 1)
    lines = [f"Sheet: {sheet_id} (rows 2..{last_row})", "Columns:"]
    for idx, col in enumerate(df.columns):
        letter = get_column_letter(idx + 1)
        ctype = col_types[idx] if col_types else _infer_series_type(df[col])
        lines.append(f"{letter}: {col} ({ctype})")
    return "\n".join(lines)


def resolve_uploaded_file(file_path: str | Path) -> ResolvedSheet:
    """Validate size/shape of an uploaded CSV or XLSX and prepare an executable sheet."""
    path = Path(file_path)
    if not path.is_file():
        raise ValueError("Uploaded file could not be read on disk.")

    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise ValueError("Uploaded file is empty (0 bytes).")
    if size_bytes > MAX_UPLOAD_BYTES:
        mb = size_bytes / (1024 * 1024)
        raise ValueError(
            f"Uploaded file is {mb:.2f} MB, which exceeds the 1.00 MB limit "
            f"({MAX_UPLOAD_BYTES:,} bytes). Please upload a smaller sample sheet."
        )

    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix == ".xlsx":
        df = pd.read_excel(path, engine="openpyxl")
    else:
        raise ValueError(
            f"Unsupported file type '{suffix}'. Please upload a .csv or .xlsx spreadsheet."
        )

    if df.shape[1] == 0:
        raise ValueError("Uploaded file has no columns.")
    if df.shape[1] > MAX_UPLOAD_COLS:
        raise ValueError(
            f"Uploaded sheet has {df.shape[1]} columns (maximum supported in demo is "
            f"{MAX_UPLOAD_COLS}, columns A..Z)."
        )
    if len(df) == 0:
        raise ValueError("Uploaded sheet has headers but 0 data rows. Add at least 1 row.")
    if len(df) > MAX_UPLOAD_ROWS:
        raise ValueError(
            f"Uploaded sheet has {len(df):,} rows, exceeding the {MAX_UPLOAD_ROWS:,}-row cap."
        )

    safe_stem = re.sub(r"[^A-Za-z0-9_]+", "_", path.stem).strip("_") or "uploaded_sheet"
    tmp_xlsx = _write_dataframe_to_temp_xlsx(df)
    schema_text = _format_df_schema(safe_stem, df)
    preview_df = _build_preview_df(df)
    return ResolvedSheet(
        sheet_id=safe_stem,
        schema_text=schema_text,
        xlsx_path=tmp_xlsx,
        preview_df=preview_df,
        source_note=f"{path.name} ({len(df)} rows, {df.shape[1]} cols)",
        total_rows=len(df),
        is_temp=True,
    )


def _infer_header_type_hint(name: str, explicit_type: str | None) -> str:
    if explicit_type:
        low = explicit_type.strip().lower()
        if low in {"int", "integer"}:
            return "integer"
        if low in {"float", "decimal", "number", "numeric", "currency"}:
            return "decimal"
        if low in {"date", "datetime"}:
            return "date"
        if low in {"bool", "boolean"}:
            return "boolean"
        if low in {"category", "cat"}:
            return "category"
        return "text"
    words = set(re.findall(r"[a-z0-9]+", name.lower()))
    if words & {
        "id",
        "code",
        "name",
        "rep",
        "owner",
        "manager",
        "email",
        "customer",
        "employee",
        "item",
        "product",
        "notes",
    }:
        return "text"
    if words & {"date", "month", "year"}:
        return "date"
    if words & {"qty", "quantity", "count", "units", "age", "days", "items", "score"}:
        return "integer"
    if words & {
        "amount",
        "sales",
        "revenue",
        "price",
        "cost",
        "salary",
        "fee",
        "total",
        "valuation",
        "rate",
        "budget",
    }:
        return "decimal"
    if words & {"region", "branch", "dept", "department", "status", "channel", "category", "hub"}:
        return "category"
    return "text"


def _synthesize_sample_rows(
    headers: list[str], col_types: list[str], n_rows: int = 5
) -> pd.DataFrame:
    categories = ["North", "South", "North", "West", "East"]
    dates = ["2025-01-15", "2025-02-20", "2025-03-10", "2025-04-05", "2025-05-18"]
    ints = [12, 25, 8, 30, 15]
    decimals = [150.00, 420.50, 95.25, 610.00, 275.75]
    bools = [True, False, True, True, False]

    data: dict[str, list[Any]] = {}
    for idx, (hdr, ctype) in enumerate(zip(headers, col_types, strict=True)):
        if ctype == "category":
            data[hdr] = categories[:n_rows]
        elif ctype == "date":
            data[hdr] = dates[:n_rows]
        elif ctype == "integer":
            data[hdr] = [v + idx * 2 for v in ints[:n_rows]]
        elif ctype == "decimal":
            data[hdr] = [round(v + idx * 10.0, 2) for v in decimals[:n_rows]]
        elif ctype == "boolean":
            data[hdr] = bools[:n_rows]
        else:
            prefix = re.sub(r"[^A-Z0-9]", "", hdr.upper())[:3] or "ITEM"
            data[hdr] = [f"{prefix}-{1001 + i}" for i in range(n_rows)]
    return pd.DataFrame(data)


def resolve_pasted_headers(raw_text: str) -> ResolvedSheet:
    """Parse pasted headers (or mini-CSV text) and create an executable sample sheet."""
    lines = [ln.strip() for ln in raw_text.strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Pasted headers box is empty.")

    filtered = [
        ln for ln in lines if not ln.lower().startswith("sheet:") and ln.lower() != "columns:"
    ]
    if not filtered:
        raise ValueError("No column definitions found in pasted text.")

    looks_like_schema_list = all(re.match(r"^[A-Z]{1,2}\s*:", ln) for ln in filtered)
    if (
        len(filtered) >= 2
        and not looks_like_schema_list
        and ("," in filtered[0] or "\t" in filtered[0])
    ):
        sep = "\t" if "\t" in filtered[0] else ","
        df = pd.read_csv(io.StringIO("\n".join(filtered)), sep=sep)
        if df.shape[1] == 0 or df.shape[1] > MAX_UPLOAD_COLS:
            raise ValueError(f"Expected 1..{MAX_UPLOAD_COLS} columns in pasted CSV.")
        if len(df) > MAX_UPLOAD_ROWS:
            raise ValueError(f"Pasted CSV exceeds {MAX_UPLOAD_ROWS} rows.")
        tmp_xlsx = _write_dataframe_to_temp_xlsx(df)
        return ResolvedSheet(
            sheet_id="pasted_sheet",
            schema_text=_format_df_schema("pasted_sheet", df),
            xlsx_path=tmp_xlsx,
            preview_df=_build_preview_df(df),
            source_note=f"pasted CSV ({len(df)} rows, {df.shape[1]} cols)",
            total_rows=len(df),
            is_temp=True,
        )

    if len(filtered) == 1:
        line = filtered[0]
        if "|" in line:
            tokens = [t.strip() for t in line.split("|") if t.strip()]
        elif "\t" in line:
            tokens = [t.strip() for t in line.split("\t") if t.strip()]
        else:
            tokens = next(csv.reader([line]))
            tokens = [t.strip() for t in tokens if t.strip()]
    else:
        tokens = filtered

    if not tokens:
        raise ValueError("Could not parse any column names from pasted headers.")
    if len(tokens) > MAX_UPLOAD_COLS:
        raise ValueError(f"Maximum {MAX_UPLOAD_COLS} columns (A..Z) supported.")

    headers: list[str] = []
    col_types: list[str] = []
    seen: set[str] = set()
    for idx, tok in enumerate(tokens, start=1):
        m = _HEADER_PREFIX_RE.match(tok)
        raw_name = (m.group(1) if m else tok).strip() or f"Col_{idx}"
        explicit_type = m.group(2) if m else None
        name = raw_name if raw_name not in seen else f"{raw_name}_{idx}"
        seen.add(name)
        headers.append(name)
        col_types.append(_infer_header_type_hint(name, explicit_type))

    df = _synthesize_sample_rows(headers, col_types, n_rows=5)
    tmp_xlsx = _write_dataframe_to_temp_xlsx(df)
    schema_text = _format_df_schema("custom_headers", df, col_types=col_types)
    return ResolvedSheet(
        sheet_id="custom_headers",
        schema_text=schema_text,
        xlsx_path=tmp_xlsx,
        preview_df=_build_preview_df(df),
        source_note=f"{len(headers)} headers · 5 sample rows (2..6)",
        total_rows=5,
        is_temp=True,
    )


def resolve_heldout_sheet(sheet_id: str, bundle: SavedEvalBundle) -> ResolvedSheet:
    if sheet_id not in bundle.heldout_contexts:
        raise ValueError(f"Unknown held-out sheet: {sheet_id!r}")
    ctx = bundle.heldout_contexts[sheet_id]
    df = pd.read_excel(ctx.xlsx_path, engine="openpyxl")
    return ResolvedSheet(
        sheet_id=ctx.sheet_id,
        schema_text=format_schema_text(ctx),
        xlsx_path=ctx.xlsx_path,
        preview_df=_build_preview_df(df),
        source_note=f"rows 2..{ctx.last_row} · {len(ctx.columns)} cols · held-out",
        total_rows=ctx.last_row - 1,
        is_temp=False,
    )


# ---------------------------------------------------------------------------
# Clean HTML formatting helpers (high-contrast light cards, zero external CSS)
# ---------------------------------------------------------------------------


def format_scalar_value(val: Any) -> str:
    if val is None:
        return "None"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return f"{val:,.6f}".rstrip("0").rstrip(".")
    if isinstance(val, int):
        return f"{val:,}"
    if isinstance(val, datetime | date):
        return val.strftime("%Y-%m-%d")
    return str(val)


def render_sheet_preview_html(
    sheet_name: str,
    subtitle: str,
    preview_df: pd.DataFrame,
) -> str:
    """Render a compact 5-row horizontally scrollable preview card with column letters."""
    safe_name = html.escape(sheet_name)
    safe_sub = html.escape(subtitle)
    if preview_df.empty:
        return (
            '<div class="flm-card flm-sheet-card">'
            '<div class="flm-card-head">'
            f'<span class="flm-sheet-title">{safe_name}</span>'
            f'<span class="flm-sheet-sub">{safe_sub}</span>'
            "</div>"
            '<div class="flm-empty-table">'
            "Paste headers or upload a CSV/XLSX above to preview 5 sample rows."
            "</div></div>"
        )

    ths: list[str] = []
    for col in preview_df.columns:
        col_str = str(col)
        if col_str == "Row":
            ths.append('<th class="flm-row-col">#</th>')
        elif ": " in col_str:
            letter, cname = col_str.split(": ", 1)
            ths.append(
                f'<th><span class="flm-col-letter">{html.escape(letter)}</span> '
                f"{html.escape(cname)}</th>"
            )
        else:
            ths.append(f"<th>{html.escape(col_str)}</th>")

    body_rows: list[str] = []
    for row in preview_df.itertuples(index=False, name=None):
        tds = []
        for idx, cell in enumerate(row):
            cls = ' class="flm-row-col"' if idx == 0 else ""
            tds.append(f"<td{cls}>{html.escape(str(cell))}</td>")
        body_rows.append(f"<tr>{''.join(tds)}</tr>")

    return (
        '<div class="flm-card flm-sheet-card">'
        '<div class="flm-card-head">'
        f'<span class="flm-sheet-title">{safe_name}</span>'
        f'<span class="flm-sheet-sub">{safe_sub}</span>'
        "</div>"
        '<div class="flm-table-wrap">'
        f'<table class="flm-table"><thead><tr>{"".join(ths)}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        "</div></div>"
    )


def format_verdict_html(
    formula: str,
    exec_res: ExecutionResult | None,
    gt: dict[str, Any] | None,
    *,
    error_banner: str | None = None,
    idle_hint: bool = False,
) -> str:
    """Render the verdict pill directly under the formula output."""
    if error_banner:
        return (
            '<div class="flm-verdict-wrap">'
            f'<span class="flm-pill flm-pill-err">❌ {html.escape(error_banner)}</span>'
            "</div>"
        )
    if idle_hint:
        return (
            '<div class="flm-verdict-wrap">'
            '<span class="flm-pill flm-pill-neutral">'
            "Click Generate &amp; verify to run locally</span>"
            "</div>"
        )
    if not formula:
        return (
            '<div class="flm-verdict-wrap">'
            '<span class="flm-pill flm-pill-err">❌ Model returned an empty response</span>'
            "</div>"
        )
    if exec_res is None or not exec_res.ok:
        err_t = exec_res.error_type if exec_res and exec_res.error_type else "runtime_error"
        err_msg = exec_res.error_message if exec_res and exec_res.error_message else ""
        detail_html = (
            f'<div class="flm-verdict-detail">{html.escape(err_msg)}</div>' if err_msg else ""
        )
        return (
            '<div class="flm-verdict-wrap">'
            f'<span class="flm-pill flm-pill-err">❌ Execution failed ({html.escape(err_t)})</span>'
            f"{detail_html}"
            "</div>"
        )

    pred_str = format_scalar_value(exec_res.value)
    if gt is not None:
        exp_val = gt["expected_value"]
        exp_str = format_scalar_value(exp_val)
        matched = values_equal(exec_res.value, exp_val)
        if matched:
            return (
                '<div class="flm-verdict-wrap">'
                f'<span class="flm-pill flm-pill-ok">'
                f"✅ {html.escape(pred_str)} = ground truth</span>"
                "</div>"
            )
        ref_formula = html.escape(str(gt["reference_formula"]))
        return (
            '<div class="flm-verdict-wrap">'
            f'<span class="flm-pill flm-pill-err">'
            f"❌ {html.escape(pred_str)} ≠ {html.escape(exp_str)} (ground truth)</span>"
            f'<div class="flm-verdict-detail">Expected: <code>{ref_formula}</code></div>'
            "</div>"
        )

    return (
        '<div class="flm-verdict-wrap">'
        f'<span class="flm-pill flm-pill-neutral">Executed: {html.escape(pred_str)}</span>'
        "</div>"
    )


def format_meta_line_html(
    *,
    backend_kind: str,
    quant_label: str,
    latency_s: float | None,
    tok_per_s: float | None = None,
    warmup_state: str = "ready",
    error_note: str | None = None,
) -> str:
    """Render one compact meta line: 'Q5_K_M · local Ollama · 3.2 s · 9.2 tok/s'."""
    backend_label = {
        "ollama": "local Ollama",
        "llamacpp": "local llama.cpp",
        "mock": "mock (offline)",
    }.get(backend_kind, backend_kind)

    parts = [html.escape(quant_label), html.escape(backend_label)]
    if error_note:
        parts.append(html.escape(error_note))
    elif latency_s is not None:
        parts.append(f"{latency_s:.1f} s")
        if tok_per_s is not None and tok_per_s > 0 and backend_kind != "mock":
            parts.append(f"{tok_per_s:.1f} tok/s")
    elif warmup_state == "warming":
        parts.append("warming up...")
    elif warmup_state == "error":
        parts.append("server offline")
    else:
        parts.append("ready")

    return f'<div class="flm-meta-line">{" · ".join(parts)}</div>'


def _render_single_base_card(title: str, rec: dict[str, Any] | None) -> str:
    if rec is None:
        return (
            '<div class="flm-base-card">'
            f'<div class="flm-base-head"><span>{html.escape(title)}</span>'
            '<span class="flm-base-tag">saved evaluation run, not live</span></div>'
            '<div class="flm-base-outcome">No saved prediction for this request.</div>'
            "</div>"
        )

    ext = str(rec.get("extracted_formula") or rec.get("raw_output") or "").strip()
    ok = bool(rec.get("exec_correct"))
    syn = bool(rec.get("syntax_valid"))
    err_t = rec.get("error_type")
    pred_v = rec.get("predicted_value")
    icon = "✅" if ok else "❌"
    outcome_cls = "flm-base-ok" if ok else "flm-base-err"

    if not syn or err_t:
        outcome = f"{icon} {err_t or 'execution failed'}"
    else:
        outcome = f"{icon} {format_scalar_value(pred_v)}"

    return (
        '<div class="flm-base-card">'
        f'<div class="flm-base-head"><span>{html.escape(title)}</span>'
        '<span class="flm-base-tag">saved evaluation run, not live</span></div>'
        f'<div class="flm-base-formula"><code>{html.escape(ext)}</code></div>'
        f'<div class="flm-base-outcome {outcome_cls}">{html.escape(outcome)}</div>'
        "</div>"
    )


def format_saved_base_html(
    sheet_id: str,
    request: str,
    bundle: SavedEvalBundle,
    enabled: bool,
) -> str:
    """Render two small side-by-side saved base-model cards when enabled."""
    if not enabled:
        return ""

    key = _norm_key(sheet_id, request)
    b0 = bundle.base_zeroshot.get(key)
    b5 = bundle.base_5shot.get(key)
    if b0 is None and b5 is None:
        return (
            '<div class="flm-base-empty">'
            "No saved base-model prediction exists for this request "
            "(saved evaluation run, not live)."
            "</div>"
        )

    return (
        '<div class="flm-base-grid">'
        f"{_render_single_base_card('Base 0-shot', b0)}"
        f"{_render_single_base_card('Base 5-shot', b5)}"
        "</div>"
    )


LIMITS_HTML = (
    '<div class="flm-limits">'
    "<p><strong>Excel dialect only:</strong> outputs a single formula starting with "
    "<code>=</code> (no Google Sheets <code>QUERY</code> or <code>ARRAYFORMULA</code>).</p>"
    "<p><strong>36 functions:</strong> <code>SUM</code>/<code>COUNT</code>/"
    "<code>AVERAGE</code> (+ <code>IF</code>/<code>IFS</code>), <code>MIN</code>, "
    "<code>MAX</code>, <code>IF</code>, <code>IFS</code>, <code>AND</code>, <code>OR</code>, "
    "<code>VLOOKUP</code>, <code>XLOOKUP</code>, <code>INDEX</code>+<code>MATCH</code>, "
    "text/date helpers, <code>ROUND</code>, and <code>IFERROR</code> (no volatile "
    "<code>TODAY</code>/<code>NOW</code>/<code>RAND</code>, <code>SUMPRODUCT</code>, "
    "<code>FILTER</code>, or <code>LET</code>).</p>"
    "<p><strong>Single sheet:</strong> bounded ranges (<code>2..N</code>) on one active sheet "
    "only.</p>"
    "<p><strong>Short formulas:</strong> up to 96 tokens, trained on synthetic spreadsheet data. "
    "On a 50-request fresh held-out set (small, AI-drafted): "
    "86-90% (Q5_K_M, Colab 45/50, local Ollama 43/50).</p>"
    "<p><strong>Always verify:</strong> check generated formulas before relying on them in "
    "critical sheets.</p>"
    "</div>"
)


# ---------------------------------------------------------------------------
# Core runtime, background warm-up & query controller (pure Python, testable)
# ---------------------------------------------------------------------------


@dataclass
class DemoRuntime:
    backend_kind: str
    base_url: str
    model_name: str
    quant_label: str
    backend: Any
    bundle: SavedEvalBundle
    keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE
    warmup_state: str = "ready"
    _warmup_started: bool = field(default=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start_background_warmup(self) -> None:
        """Send one tiny background request at startup so the first demo click is warm."""
        if self.backend_kind == "mock":
            self.warmup_state = "ready"
            return
        with self._lock:
            if self._warmup_started:
                return
            self._warmup_started = True
            self.warmup_state = "warming"

        def _worker() -> None:
            try:
                self.backend.generate(
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": "hi"},
                    ],
                    max_tokens=1,
                    seed=DEFAULT_SEED,
                )
                self.warmup_state = "ready"
            except Exception:
                self.warmup_state = "error"

        threading.Thread(target=_worker, name="formulalm-warmup", daemon=True).start()


def create_runtime(
    *,
    backend_kind: str = "ollama",
    base_url: str | None = None,
    model_name: str | None = None,
    keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE,
) -> DemoRuntime:
    gguf_file, modelfile_quant = detect_modelfile_quant()
    del gguf_file
    bundle = load_saved_eval_bundle()

    kind = backend_kind.strip().lower()
    if kind == "ollama":
        resolved_url = assert_localhost_url(base_url or "http://127.0.0.1:11434")
        resolved_model = (model_name or "formulalm").strip()
        quant = infer_quant_label(resolved_model, modelfile_quant)
        backend: Any = OllamaBackend(
            model=resolved_model,
            base_url=resolved_url,
            timeout=120.0,
            keep_alive=keep_alive,
        )
        initial_warmup = "idle"
    elif kind == "llamacpp":
        resolved_url = assert_localhost_url(base_url or "http://127.0.0.1:8080")
        resolved_model = (model_name or "formulalm-qwen3-1.7b-v2-q5_k_m.gguf").strip()
        quant = infer_quant_label(resolved_model, modelfile_quant)
        backend = LlamaCppBackend(
            base_url=resolved_url,
            model=resolved_model,
            timeout=120.0,
            use_raw_prompt=True,
            quantization=quant,
        )
        initial_warmup = "idle"
    elif kind == "mock":
        resolved_url = assert_localhost_url(base_url or "http://127.0.0.1:11434")
        resolved_model = (model_name or "formulalm-mock").strip()
        quant = modelfile_quant
        backend = DemoMockBackend(saved_q5_by_prompt=bundle.local_q5_outputs)
        initial_warmup = "ready"
    else:
        raise ValueError(f"Unsupported backend {backend_kind!r} (expected ollama, llamacpp, mock).")

    return DemoRuntime(
        backend_kind=kind,
        base_url=resolved_url,
        model_name=resolved_model,
        quant_label=quant,
        backend=backend,
        bundle=bundle,
        keep_alive=keep_alive,
        warmup_state=initial_warmup,
    )


def run_demo_query(
    runtime: DemoRuntime,
    *,
    sheet_choice: str,
    uploaded_file: str | Path | None,
    pasted_headers: str,
    request_text: str,
    show_base_comparison: bool,
) -> tuple[str, str, str, str, pd.DataFrame, str]:
    """Execute one end-to-end demo request and return UI outputs.

    Returns:
        ``(formula_str, verdict_html, meta_html, base_comparison_html, preview_df, schema_text)``
    """
    req = (request_text or "").strip()
    resolved: ResolvedSheet | None = None
    try:
        if uploaded_file:
            resolved = resolve_uploaded_file(uploaded_file)
        elif (pasted_headers or "").strip():
            resolved = resolve_pasted_headers(pasted_headers)
        elif sheet_choice and sheet_choice != CUSTOM_SHEET_KEY:
            resolved = resolve_heldout_sheet(sheet_choice, runtime.bundle)
        else:
            raise ValueError(
                "Paste column headers or upload a CSV/XLSX (up to 1 MB) before generating."
            )

        if not req:
            raise ValueError("Please enter a plain-English spreadsheet request.")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(resolved.schema_text, req)},
        ]

        t0 = time.perf_counter()
        try:
            raw_output = runtime.backend.generate(
                messages, max_tokens=MAX_NEW_TOKENS, seed=DEFAULT_SEED
            )
            runtime.warmup_state = "ready"
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            err_msg = f"Backend unreachable ({runtime.backend_kind} @ {runtime.base_url}): {exc}"
            meta_html = format_meta_line_html(
                backend_kind=runtime.backend_kind,
                quant_label=runtime.quant_label,
                latency_s=elapsed,
                error_note="backend error",
            )
            base_html = format_saved_base_html(
                resolved.sheet_id, req, runtime.bundle, show_base_comparison
            )
            return (
                "",
                format_verdict_html("", None, None, error_banner=err_msg),
                meta_html,
                base_html,
                resolved.preview_df,
                resolved.schema_text,
            )

        latency_s = time.perf_counter() - t0
        timings = getattr(runtime.backend, "last_timings", {}) or {}
        tok_s = timings.get("predicted_per_second")

        formula = extract_formula(raw_output)
        exec_res = run_formula(formula, resolved.xlsx_path, timeout=15.0)
        gt = (
            None
            if resolved.is_temp
            else runtime.bundle.ground_truth.get(_norm_key(resolved.sheet_id, req))
        )

        verdict_html = format_verdict_html(formula, exec_res, gt)
        meta_html = format_meta_line_html(
            backend_kind=runtime.backend_kind,
            quant_label=runtime.quant_label,
            latency_s=latency_s,
            tok_per_s=float(tok_s) if isinstance(tok_s, int | float) else None,
            warmup_state="ready",
        )
        base_html = format_saved_base_html(
            resolved.sheet_id if not resolved.is_temp else CUSTOM_SHEET_KEY,
            req,
            runtime.bundle,
            show_base_comparison,
        )
        return (
            formula,
            verdict_html,
            meta_html,
            base_html,
            resolved.preview_df,
            resolved.schema_text,
        )
    except ValueError as exc:
        meta_html = format_meta_line_html(
            backend_kind=runtime.backend_kind,
            quant_label=runtime.quant_label,
            latency_s=None,
            warmup_state=runtime.warmup_state,
        )
        return (
            "",
            format_verdict_html("", None, None, error_banner=f"Input validation error: {exc}"),
            meta_html,
            format_saved_base_html("", req, runtime.bundle, show_base_comparison),
            pd.DataFrame(),
            "",
        )
    finally:
        if resolved is not None and resolved.is_temp and resolved.xlsx_path.is_file():
            try:
                resolved.xlsx_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Compact Light 1080p CSS (system fonts only; zero external assets)
# ---------------------------------------------------------------------------

LIGHT_1080P_CSS = """
:root, body, .gradio-container {
    --flm-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    --flm-mono: "Cascadia Code", Consolas, "SFMono-Regular", Menlo, ui-monospace, monospace;
    --flm-accent: #2563eb;
    --flm-accent-hover: #1d4ed8;
    --flm-ink: #0f172a;
    --flm-muted: #475569;
    --flm-border: #cbd5e1;
    --flm-bg: #f8fafc;
    --flm-card: #ffffff;
    background-color: var(--flm-bg) !important;
    color: var(--flm-ink) !important;
    font-family: var(--flm-sans) !important;
    font-size: 18px !important;
}
.gradio-container {
    max-width: 1440px !important;
    margin: 0 auto !important;
    padding: 12px 20px 14px 20px !important;
}
footer { display: none !important; }

/* Header bar + chips */
.flm-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px 16px;
    padding: 4px 2px 10px 2px;
    border-bottom: 1px solid var(--flm-border);
    margin-bottom: 6px;
}
.flm-brand {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 12px;
}
.flm-badge {
    display: inline-block;
    background: var(--flm-ink);
    color: #ffffff;
    font-weight: 700;
    font-size: 1.25rem;
    padding: 4px 12px;
    border-radius: 8px;
    letter-spacing: -0.01em;
}
.flm-subtitle {
    font-size: 1.15rem;
    font-weight: 600;
    color: var(--flm-ink);
}
.flm-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.flm-chip {
    background: #ffffff;
    border: 1px solid var(--flm-border);
    color: #1e293b;
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 0.85rem;
    font-weight: 600;
    white-space: nowrap;
}

/* Tabs */
.tabs > .tab-nav {
    border-bottom: 1px solid var(--flm-border) !important;
    margin-bottom: 10px !important;
    gap: 6px !important;
}
.tabs > .tab-nav button {
    font-size: 0.98rem !important;
    font-weight: 600 !important;
    padding: 7px 16px !important;
    border-radius: 10px 10px 0 0 !important;
    color: var(--flm-muted) !important;
}
.tabs > .tab-nav button.selected {
    color: var(--flm-accent) !important;
    border-bottom: 2px solid var(--flm-accent) !important;
    background: #ffffff !important;
}

/* 8 short example buttons */
#ex-btn-row {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    margin-bottom: 10px !important;
}
#ex-btn-row > div, #ex-btn-row button.ex-btn {
    min-width: 0 !important;
    flex: 1 1 auto !important;
}
button.ex-btn {
    background: #ffffff !important;
    color: var(--flm-ink) !important;
    border: 1px solid var(--flm-border) !important;
    border-radius: 10px !important;
    font-size: 0.9rem !important;
    font-weight: 600 !important;
    padding: 7px 10px !important;
    min-height: 38px !important;
    box-shadow: none !important;
}
button.ex-btn:hover {
    border-color: var(--flm-accent) !important;
    background: #eff6ff !important;
}
button.ex-btn-active {
    border: 2px solid var(--flm-accent) !important;
    background: #eff6ff !important;
    color: #1e3a8a !important;
}
button.ex-btn-fail {
    border: 2px solid #dc2626 !important;
    color: #991b1b !important;
    background: #fff5f5 !important;
}
button.ex-btn-fail:hover, button.ex-btn-fail.ex-btn-active {
    background: #fee2e2 !important;
    border-color: #b91c1c !important;
}

/* Cards */
.flm-card, .flm-panel {
    background: var(--flm-card) !important;
    border: 1px solid var(--flm-border) !important;
    border-radius: 12px !important;
    padding: 14px 16px !important;
    box-shadow: none !important;
}
.flm-panel > .form, .flm-panel .block {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}
.flm-card-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 8px;
}
.flm-sheet-title {
    font-family: var(--flm-mono);
    font-size: 0.98rem;
    font-weight: 700;
    color: var(--flm-ink);
}
.flm-sheet-sub {
    font-size: 0.82rem;
    color: var(--flm-muted);
    white-space: nowrap;
}

/* Compact 5-row horizontally scrollable table */
.flm-table-wrap {
    overflow-x: auto;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    background: #ffffff;
}
.flm-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    line-height: 1.3;
    white-space: nowrap;
}
.flm-table th {
    background: #f1f5f9;
    color: var(--flm-ink);
    font-weight: 600;
    text-align: left;
    padding: 6px 10px;
    border-bottom: 1px solid var(--flm-border);
}
.flm-table td {
    padding: 5px 10px;
    border-bottom: 1px solid #f1f5f9;
    color: #1e293b;
}
.flm-table tr:last-child td { border-bottom: none; }
.flm-col-letter {
    font-family: var(--flm-mono);
    font-weight: 700;
    color: var(--flm-accent);
}
.flm-row-col {
    font-family: var(--flm-mono);
    color: var(--flm-muted) !important;
    background: #f8fafc;
    text-align: right;
    width: 32px;
}
.flm-empty-table {
    padding: 16px 12px;
    color: var(--flm-muted);
    font-size: 0.92rem;
    text-align: center;
    background: #f8fafc;
    border-radius: 8px;
    border: 1px dashed var(--flm-border);
}

/* Request input + primary button */
.flm-request-box textarea {
    font-family: var(--flm-sans) !important;
    font-size: 19px !important;
    line-height: 1.35 !important;
    color: var(--flm-ink) !important;
    background: #ffffff !important;
    border: 1px solid var(--flm-border) !important;
    border-radius: 10px !important;
    padding: 10px 12px !important;
}
.flm-primary-btn {
    background: var(--flm-accent) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 12px !important;
    font-size: 1.08rem !important;
    font-weight: 700 !important;
    padding: 12px 18px !important;
    min-height: 48px !important;
}
.flm-primary-btn:hover {
    background: var(--flm-accent-hover) !important;
}

/* Result card: monospace formula + verdict pill + meta line */
.flm-formula-box textarea, .flm-formula-box input {
    font-family: var(--flm-mono) !important;
    font-size: 22px !important;
    font-weight: 700 !important;
    line-height: 1.35 !important;
    color: #0f172a !important;
    background: #f8fafc !important;
    border: 1px solid var(--flm-border) !important;
    border-radius: 10px !important;
    padding: 12px 14px !important;
}
.flm-verdict-wrap {
    margin-top: 8px;
}
.flm-pill {
    display: inline-block;
    font-size: 1.02rem;
    font-weight: 700;
    padding: 7px 14px;
    border-radius: 999px;
    border: 1px solid transparent;
}
.flm-pill-ok {
    background: #dcfce7;
    color: #166534;
    border-color: #86efac;
}
.flm-pill-err {
    background: #fee2e2;
    color: #991b1b;
    border-color: #fca5a5;
}
.flm-pill-neutral {
    background: #f1f5f9;
    color: #1e293b;
    border-color: #cbd5e1;
}
.flm-verdict-detail {
    margin-top: 6px;
    font-size: 0.9rem;
    color: #334155;
}
.flm-verdict-detail code {
    font-family: var(--flm-mono);
    background: #f1f5f9;
    padding: 2px 6px;
    border-radius: 6px;
    color: #0f172a;
}
.flm-meta-line {
    margin-top: 8px;
    font-size: 0.88rem;
    color: var(--flm-muted);
    font-weight: 500;
}

/* Base comparison toggle & side-by-side cards */
.flm-base-toggle {
    margin-top: 4px !important;
    padding: 0 2px !important;
}
.flm-base-toggle label, .flm-base-toggle span {
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    color: var(--flm-ink) !important;
}
.flm-base-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 4px;
}
.flm-base-card {
    background: #ffffff;
    border: 1px solid var(--flm-border);
    border-radius: 12px;
    padding: 12px 14px;
}
.flm-base-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
    font-size: 0.9rem;
    font-weight: 700;
    color: var(--flm-ink);
    margin-bottom: 6px;
}
.flm-base-tag {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--flm-muted);
}
.flm-base-formula {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 6px 8px;
    overflow-x: auto;
    margin-bottom: 6px;
}
.flm-base-formula code {
    font-family: var(--flm-mono);
    font-size: 0.85rem;
    color: #0f172a;
    white-space: nowrap;
}
.flm-base-outcome {
    font-size: 0.9rem;
    font-weight: 700;
}
.flm-base-ok { color: #166534; }
.flm-base-err { color: #991b1b; }
.flm-base-empty {
    font-size: 0.9rem;
    color: var(--flm-muted);
    background: #ffffff;
    border: 1px solid var(--flm-border);
    border-radius: 12px;
    padding: 10px 14px;
}

/* Custom upload compact height */
.flm-upload-box .upload-container, .flm-upload-box .file-preview {
    min-height: 64px !important;
    padding: 6px 10px !important;
}

/* Footer collapsed accordions */
.flm-footer-row {
    margin-top: 10px !important;
    gap: 12px !important;
}
.flm-footer-acc {
    background: #ffffff !important;
    border: 1px solid var(--flm-border) !important;
    border-radius: 12px !important;
}
.flm-footer-acc > button {
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    color: var(--flm-muted) !important;
    padding: 8px 14px !important;
}
.flm-limits p {
    margin: 4px 0;
    font-size: 0.9rem;
    line-height: 1.4;
    color: #1e293b;
}
.flm-limits code {
    font-family: var(--flm-mono);
    font-size: 0.84rem;
    background: #f1f5f9;
    padding: 1px 5px;
    border-radius: 4px;
}
.flm-schema-box textarea {
    font-family: var(--flm-mono) !important;
    font-size: 0.86rem !important;
    background: #f8fafc !important;
}
"""

FORCE_LIGHT_JS = """
() => {
    document.body.classList.remove('dark');
    document.documentElement.style.colorScheme = 'light';
}
"""


def _header_html(quant_label: str) -> str:
    size_chip = f"{quant_label} 1.2 GB" if quant_label == "Q5_K_M" else quant_label
    return (
        '<div class="flm-header">'
        '<div class="flm-brand">'
        '<span class="flm-badge">FormulaLM</span>'
        '<span class="flm-subtitle">Plain-English to verified Excel formula</span>'
        "</div>"
        '<div class="flm-chips">'
        '<span class="flm-chip">Qwen3-1.7B</span>'
        f'<span class="flm-chip">{html.escape(size_chip)}</span>'
        '<span class="flm-chip">CPU only</span>'
        '<span class="flm-chip">offline</span>'
        "</div>"
        "</div>"
    )


def _button_classes(ex: BuiltinExample, active_id: str) -> list[str]:
    classes = ["ex-btn"]
    if ex.is_honest_failure:
        classes.append("ex-btn-fail")
    if ex.example_id == active_id:
        classes.append("ex-btn-active")
    return classes


def build_demo_app(runtime: DemoRuntime) -> gr.Blocks:
    """Construct the compact, 1080p-ready FormulaLM Gradio Blocks application."""
    example_by_id = {ex.example_id: ex for ex in BUILTIN_EXAMPLES}
    first_ex = BUILTIN_EXAMPLES[0]
    initial_sheet = resolve_heldout_sheet(first_ex.sheet_id, runtime.bundle)

    initial_meta = format_meta_line_html(
        backend_kind=runtime.backend_kind,
        quant_label=runtime.quant_label,
        latency_s=None,
        warmup_state=runtime.warmup_state,
    )
    initial_verdict = format_verdict_html("", None, None, idle_hint=True)
    initial_base = format_saved_base_html(first_ex.sheet_id, first_ex.request, runtime.bundle, True)
    initial_preview = render_sheet_preview_html(
        initial_sheet.sheet_id, initial_sheet.source_note, initial_sheet.preview_df
    )
    empty_custom_preview = render_sheet_preview_html(
        "Your sheet", "paste headers or upload CSV/XLSX", pd.DataFrame()
    )

    with gr.Blocks(
        analytics_enabled=False, title="FormulaLM — Plain-English to Verified Excel Formula"
    ) as demo:
        gr.HTML(_header_html(runtime.quant_label))

        active_sheet_state = gr.State(value=first_ex.sheet_id)
        active_ex_state = gr.State(value=first_ex.example_id)
        last_latency_state = gr.State(value=None)
        custom_latency_state = gr.State(value=None)

        with gr.Tabs():
            # ---------------------------------------------------------------
            # Tab 1: Held-out examples
            # ---------------------------------------------------------------
            with gr.Tab("Held-out examples"):
                ex_buttons: list[gr.Button] = []
                with gr.Row(elem_id="ex-btn-row"):
                    for ex in BUILTIN_EXAMPLES:
                        btn = gr.Button(
                            ex.short_label,
                            size="sm",
                            elem_classes=_button_classes(ex, first_ex.example_id),
                        )
                        ex_buttons.append(btn)

                with gr.Row(equal_height=False):
                    # LEFT (~40%): Sheet preview card + Request card + Primary button
                    with gr.Column(scale=4, min_width=360):
                        sheet_preview_html = gr.HTML(initial_preview)
                        with gr.Group(elem_classes=["flm-panel"]):
                            request_box = gr.Textbox(
                                value=first_ex.request,
                                label="Request",
                                placeholder="e.g., Total Net Amount for the Mirehaven branch",
                                lines=2,
                                elem_classes=["flm-request-box"],
                            )
                        run_btn = gr.Button(
                            "Generate & verify",
                            variant="primary",
                            size="lg",
                            elem_classes=["flm-primary-btn"],
                        )

                    # RIGHT (~60%): Formula + Verdict pill + Meta line + Base toggle/cards
                    with gr.Column(scale=6, min_width=440):
                        with gr.Group(elem_classes=["flm-panel"]):
                            formula_out = gr.Textbox(
                                value="",
                                label="Excel Formula",
                                lines=2,
                                interactive=False,
                                buttons=["copy"],
                                elem_classes=["flm-formula-box"],
                            )
                            verdict_out = gr.HTML(initial_verdict)
                            meta_out = gr.HTML(initial_meta)

                        compare_toggle = gr.Checkbox(
                            value=True,
                            label="Compare with base model",
                            elem_classes=["flm-base-toggle"],
                        )
                        base_out = gr.HTML(initial_base)

            # ---------------------------------------------------------------
            # Tab 2: Your own sheet (clean two-field form, no accordion)
            # ---------------------------------------------------------------
            with gr.Tab("Your own sheet"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=4, min_width=360):
                        with gr.Group(elem_classes=["flm-panel"]):
                            pasted_input = gr.Textbox(
                                label="Paste column headers or mini-CSV",
                                placeholder="Region, Sales Rep, Units, Net Sales",
                                lines=2,
                                elem_classes=["flm-request-box"],
                            )
                            upload_input = gr.File(
                                label="Or upload CSV / XLSX (up to 1 MB)",
                                file_count="single",
                                file_types=[".csv", ".xlsx"],
                                type="filepath",
                                elem_classes=["flm-upload-box"],
                            )
                        custom_preview_html = gr.HTML(empty_custom_preview)
                        with gr.Group(elem_classes=["flm-panel"]):
                            custom_request_box = gr.Textbox(
                                value="",
                                label="Request",
                                placeholder="e.g., Total Net Sales for North",
                                lines=2,
                                elem_classes=["flm-request-box"],
                            )
                        custom_run_btn = gr.Button(
                            "Generate & verify",
                            variant="primary",
                            size="lg",
                            elem_classes=["flm-primary-btn"],
                        )

                    with gr.Column(scale=6, min_width=440):
                        with gr.Group(elem_classes=["flm-panel"]):
                            custom_formula_out = gr.Textbox(
                                value="",
                                label="Excel Formula",
                                lines=2,
                                interactive=False,
                                buttons=["copy"],
                                elem_classes=["flm-formula-box"],
                            )
                            custom_verdict_out = gr.HTML(initial_verdict)
                            custom_meta_out = gr.HTML(initial_meta)

        # -------------------------------------------------------------------
        # Footer: two collapsed accordions (both closed by default)
        # -------------------------------------------------------------------
        with gr.Row(elem_classes=["flm-footer-row"]):
            with gr.Accordion("Limits & scope", open=False, elem_classes=["flm-footer-acc"]):
                gr.HTML(LIMITS_HTML)
            with gr.Accordion(
                "Show prompt sent to model", open=False, elem_classes=["flm-footer-acc"]
            ):
                schema_box = gr.Textbox(
                    value=initial_sheet.schema_text,
                    show_label=False,
                    lines=7,
                    interactive=False,
                    elem_classes=["flm-schema-box"],
                )

        # Lightweight timer to update "warming up..." -> "ready" once startup warm-up completes.
        warmup_timer = gr.Timer(
            value=1.5, active=(runtime.backend_kind != "mock" and runtime.warmup_state != "ready")
        )

        def _poll_warmup(held_lat: float | None, cust_lat: float | None):
            still_warming = runtime.warmup_state == "warming"
            held_update = (
                gr.update()
                if held_lat is not None
                else format_meta_line_html(
                    backend_kind=runtime.backend_kind,
                    quant_label=runtime.quant_label,
                    latency_s=None,
                    warmup_state=runtime.warmup_state,
                )
            )
            cust_update = (
                gr.update()
                if cust_lat is not None
                else format_meta_line_html(
                    backend_kind=runtime.backend_kind,
                    quant_label=runtime.quant_label,
                    latency_s=None,
                    warmup_state=runtime.warmup_state,
                )
            )
            return held_update, cust_update, gr.Timer(active=still_warming)

        warmup_timer.tick(
            fn=_poll_warmup,
            inputs=[last_latency_state, custom_latency_state],
            outputs=[meta_out, custom_meta_out, warmup_timer],
        )

        # Event handlers — Held-out examples tab
        def _select_example(ex_id: str, show_base: bool):
            ex = example_by_id[ex_id]
            resolved = resolve_heldout_sheet(ex.sheet_id, runtime.bundle)
            preview = render_sheet_preview_html(
                resolved.sheet_id, resolved.source_note, resolved.preview_df
            )
            base_html = format_saved_base_html(ex.sheet_id, ex.request, runtime.bundle, show_base)
            btn_updates = [
                gr.update(elem_classes=_button_classes(item, ex.example_id))
                for item in BUILTIN_EXAMPLES
            ]
            return (
                ex.sheet_id,
                ex.example_id,
                preview,
                ex.request,
                "",
                format_verdict_html("", None, None, idle_hint=True),
                base_html,
                resolved.schema_text,
                *btn_updates,
            )

        for ex, btn in zip(BUILTIN_EXAMPLES, ex_buttons, strict=True):
            btn.click(
                fn=lambda show_b, _eid=ex.example_id: _select_example(_eid, show_b),
                inputs=[compare_toggle],
                outputs=[
                    active_sheet_state,
                    active_ex_state,
                    sheet_preview_html,
                    request_box,
                    formula_out,
                    verdict_out,
                    base_out,
                    schema_box,
                    *ex_buttons,
                ],
            )

        def _on_toggle_base(show_base: bool, sheet_id: str, req: str):
            return format_saved_base_html(sheet_id or "", req or "", runtime.bundle, show_base)

        compare_toggle.change(
            fn=_on_toggle_base,
            inputs=[compare_toggle, active_sheet_state, request_box],
            outputs=[base_out],
        )

        def _on_run_heldout(sheet_id: str, req: str, show_base: bool):
            formula, verdict, meta, base_html, _, schema_txt = run_demo_query(
                runtime,
                sheet_choice=sheet_id,
                uploaded_file=None,
                pasted_headers="",
                request_text=req,
                show_base_comparison=show_base,
            )
            return formula, verdict, meta, base_html, schema_txt, 1.0

        for trigger in (run_btn.click, request_box.submit):
            trigger(
                fn=_on_run_heldout,
                inputs=[active_sheet_state, request_box, compare_toggle],
                outputs=[
                    formula_out,
                    verdict_out,
                    meta_out,
                    base_out,
                    schema_box,
                    last_latency_state,
                ],
            )

        # Event handlers — Your own sheet tab
        def _preview_custom(pasted: str, uploaded: str | None):
            resolved: ResolvedSheet | None = None
            try:
                if uploaded:
                    resolved = resolve_uploaded_file(uploaded)
                elif (pasted or "").strip():
                    resolved = resolve_pasted_headers(pasted)
                else:
                    return empty_custom_preview, gr.update()
                html_tbl = render_sheet_preview_html(
                    resolved.sheet_id, resolved.source_note, resolved.preview_df
                )
                return html_tbl, resolved.schema_text
            except ValueError as exc:
                err_tbl = (
                    '<div class="flm-card flm-sheet-card">'
                    f'<div class="flm-empty-table">❌ {html.escape(str(exc))}</div></div>'
                )
                return err_tbl, gr.update()
            finally:
                if resolved is not None and resolved.is_temp and resolved.xlsx_path.is_file():
                    try:
                        resolved.xlsx_path.unlink()
                    except OSError:
                        pass

        pasted_input.change(
            fn=_preview_custom,
            inputs=[pasted_input, upload_input],
            outputs=[custom_preview_html, schema_box],
        )
        upload_input.change(
            fn=_preview_custom,
            inputs=[pasted_input, upload_input],
            outputs=[custom_preview_html, schema_box],
        )

        def _on_run_custom(pasted: str, uploaded: str | None, req: str):
            formula, verdict, meta, _, preview_df, schema_txt = run_demo_query(
                runtime,
                sheet_choice=CUSTOM_SHEET_KEY,
                uploaded_file=uploaded,
                pasted_headers=pasted,
                request_text=req,
                show_base_comparison=False,
            )
            if not preview_df.empty:
                title = Path(uploaded).stem if uploaded else "custom_headers"
                sub = f"first {len(preview_df)} rows"
                prev_html = render_sheet_preview_html(title, sub, preview_df)
            else:
                prev_html = empty_custom_preview
            return formula, verdict, meta, prev_html, schema_txt or gr.update(), 1.0

        for trigger in (custom_run_btn.click, custom_request_box.submit):
            trigger(
                fn=_on_run_custom,
                inputs=[pasted_input, upload_input, custom_request_box],
                outputs=[
                    custom_formula_out,
                    custom_verdict_out,
                    custom_meta_out,
                    custom_preview_html,
                    schema_box,
                    custom_latency_state,
                ],
            )

    return demo


def build_offline_theme() -> gr.themes.Base:
    """System-font light theme with zero Google Fonts or external CDN requests."""
    return gr.themes.Base(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
        font=["system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
        font_mono=["Cascadia Code", "Consolas", "SFMono-Regular", "ui-monospace", "monospace"],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the local FormulaLM Gradio demo.")
    parser.add_argument(
        "--backend",
        choices=("ollama", "llamacpp", "mock"),
        default=os.environ.get("FORMULALM_BACKEND", "ollama"),
        help="Local inference backend (default: ollama).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("FORMULALM_BASE_URL") or None,
        help=(
            "Localhost backend URL (default: http://127.0.0.1:11434 for ollama, "
            ":8080 for llamacpp)."
        ),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("FORMULALM_MODEL", "formulalm"),
        help="Model tag/name on the local backend (default: formulalm from deploy/Modelfile).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("FORMULALM_DEMO_HOST", "127.0.0.1"),
        help="Gradio bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("FORMULALM_DEMO_PORT", "7860")),
        help="Gradio bind port (default: 7860).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    assert_localhost_url(f"http://{args.host}:{args.port}")
    runtime = create_runtime(
        backend_kind=args.backend,
        base_url=args.base_url,
        model_name=args.model,
    )
    runtime.start_background_warmup()
    demo = build_demo_app(runtime)
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=False,
        max_file_size="1mb",
        theme=build_offline_theme(),
        css=LIGHT_1080P_CSS,
        js=FORCE_LIGHT_JS,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
