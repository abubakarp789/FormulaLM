"""FormulaLM local Gradio demo application.

Layout follows the "Formula Precision" Stitch blueprint, rebuilt with Gradio Blocks + local CSS:
- Header (title, subtitle, 4 chips) and two tabs: "Held-out examples" and "Your own sheet".
- Held-out tab: 8 numbered example buttons (#8 = red-outlined honest failure); left column with
  the sheet card (5-row preview with column letters), request card and "Generate & verify";
  right column with the generated-formula card (large monospace + copy), verdict pill, one meta
  line, and the optional "Compare with base model" card (saved evaluation runs, not live).
- Your own sheet tab: paste headers or upload CSV/XLSX (<= 1 MB), request box, same result card.
- Footer: two accordions closed by default ("Limits & scope", "Show prompt sent to model").
- Localhost-only: system fonts, inline SVG icons, zero external scripts/stylesheets/fonts/images.
- Background warm-up request at startup + Ollama ``keep_alive="30m"`` (meta shows "warming up...").

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
        short_label="IF+AND",
        label="2. [Sales — IF + AND] Classify row 10 as 'Bulk High' vs 'Standard'",
        sheet_id="sales_retail_store",
        request=(
            "On row 10, return 'Bulk High' if Quantity >= 20 and Net Amount > 500, "
            "otherwise 'Standard'"
        ),
    ),
    BuiltinExample(
        example_id="real_v2_015",
        short_label="SUMIFS",
        label="3. [HR — SUMIFS] Total Annual Salary for Design staff in Stonewick",
        sheet_id="hr_employee_roster",
        request="Total Annual Salary for Design staff based in Stonewick",
    ),
    BuiltinExample(
        example_id="real_v2_017",
        short_label="INDEX+MATCH",
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
        short_label="IFERROR+ROUND",
        label="6. [Grades — IFERROR + ROUND + SUMIF/SUM] Physics share of Assignments Done",
        sheet_id="grades_course_scores",
        request=(
            "Share of total Assignments Done completed by Physics students, "
            "rounded to 3 decimals (0 on error)"
        ),
    ),
    BuiltinExample(
        example_id="real_v2_045",
        short_label="SUMIFS",
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
            "The model wrote valid Excel but picked column index 6 (Item Count, value 11) "
            "instead of 7 (Order Total, value 533). Executing the formula on the sheet caught "
            "the mismatch against the ground truth."
        ),
    ),
)

_EXAMPLE_BY_ID = {ex.example_id: ex for ex in BUILTIN_EXAMPLES}


def example_button_label(index: int, ex: BuiltinExample) -> str:
    """Numbered short label for the example button row, e.g. ``1 · COUNTIFS``."""
    return f"{index} · {ex.short_label}"


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
    total_cols: int = 0
    is_temp: bool = False
    synthesized: bool = False


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
        source_note=f"uploaded {path.name} ({size_bytes / 1024:.1f} KB)",
        total_rows=len(df),
        total_cols=df.shape[1],
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
            source_note="pasted CSV rows",
            total_rows=len(df),
            total_cols=df.shape[1],
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
        source_note="pasted headers · synthesized sample rows",
        total_rows=5,
        total_cols=len(headers),
        is_temp=True,
        synthesized=True,
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
        source_note="held-out sample",
        total_rows=ctx.last_row - 1,
        total_cols=len(ctx.columns),
        is_temp=False,
    )


# ---------------------------------------------------------------------------
# HTML cards (inline SVG icons only; zero external assets)
# ---------------------------------------------------------------------------

_SVG_ATTRS = (
    'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true"'
)
ICON_TABLE = (
    f'<svg class="flm-ico" {_SVG_ATTRS}><rect x="3" y="4" width="18" height="16" rx="2"/>'
    '<path d="M3 10h18M9 4v16"/></svg>'
)
ICON_CHECK = (
    f'<svg class="flm-ico" {_SVG_ATTRS}><circle cx="12" cy="12" r="9"/>'
    '<path d="m8 12 3 3 5-6"/></svg>'
)
ICON_ALERT = (
    f'<svg class="flm-ico" {_SVG_ATTRS}><path d="M12 3 2 20h20L12 3z"/>'
    '<path d="M12 10v4M12 17h.01"/></svg>'
)


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
    *,
    rows_cols_chip: str = "",
) -> str:
    """Sheet card: icon + name + subtitle + rows/cols chip + 5-row table with column letters."""
    head = (
        '<div class="flm-card-head">'
        f'<div class="flm-card-title">{ICON_TABLE}'
        f'<span class="flm-sheet-name">{html.escape(sheet_name)}</span>'
        f'<span class="flm-sheet-sub">({html.escape(subtitle)})</span></div>'
        + (
            f'<span class="flm-chip-sm">{html.escape(rows_cols_chip)}</span>'
            if rows_cols_chip
            else ""
        )
        + "</div>"
    )
    if preview_df.empty:
        return (
            f'<div class="flm-card flm-sheet-card">{head}'
            '<div class="flm-empty-table">Paste column headers or upload a CSV/XLSX to preview '
            "5 sample rows here.</div></div>"
        )

    ths: list[str] = []
    for col in preview_df.columns:
        col_str = str(col)
        if col_str == "Row":
            ths.append('<th class="flm-rownum">#</th>')
        elif ": " in col_str:
            letter, cname = col_str.split(": ", 1)
            ths.append(
                f'<th><span class="flm-col-letter">{html.escape(letter)}</span>'
                f'<span class="flm-col-name">{html.escape(cname)}</span></th>'
            )
        else:
            ths.append(f"<th>{html.escape(col_str)}</th>")

    body_rows: list[str] = []
    for row in preview_df.itertuples(index=False, name=None):
        tds = []
        for idx, cell in enumerate(row):
            cls = ' class="flm-rownum"' if idx == 0 else ""
            tds.append(f"<td{cls}>{html.escape(str(cell))}</td>")
        body_rows.append(f"<tr>{''.join(tds)}</tr>")

    return (
        f'<div class="flm-card flm-sheet-card">{head}'
        '<div class="flm-table-wrap">'
        f'<table class="flm-table"><thead><tr>{"".join(ths)}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        "</div></div>"
    )


def _sheet_card_for(resolved: ResolvedSheet) -> str:
    return render_sheet_preview_html(
        resolved.sheet_id,
        resolved.source_note,
        resolved.preview_df,
        rows_cols_chip=f"{resolved.total_rows} rows · {resolved.total_cols} cols",
    )


def formula_card_header_html(quant_label: str) -> str:
    return (
        '<div class="flm-card-head flm-formula-head">'
        f'<div class="flm-card-title flm-title-lg">{ICON_CHECK}<span>Generated formula</span>'
        f'<span class="flm-chip-sm">FormulaLM v2 · {html.escape(quant_label)}</span></div>'
        "</div>"
    )


def format_verdict_html(
    formula: str,
    exec_res: ExecutionResult | None,
    gt: dict[str, Any] | None,
    *,
    rows_note: str | None = None,
    error_banner: str | None = None,
    idle_hint: bool = False,
) -> str:
    """Verdict pill (green = matches ground truth, red = wrong/failed, neutral = custom)."""
    if error_banner:
        return (
            '<div class="flm-verdict">'
            f'<span class="flm-pill flm-pill-err">❌ {html.escape(error_banner)}</span></div>'
        )
    if idle_hint:
        return (
            '<div class="flm-verdict"><span class="flm-pill flm-pill-neutral">'
            "Click Generate &amp; verify to run the local model</span></div>"
        )
    if not formula:
        return (
            '<div class="flm-verdict">'
            '<span class="flm-pill flm-pill-err">❌ Model returned an empty response</span></div>'
        )
    if exec_res is None or not exec_res.ok:
        err_t = exec_res.error_type if exec_res and exec_res.error_type else "runtime_error"
        err_msg = exec_res.error_message if exec_res and exec_res.error_message else ""
        detail = f'<span class="flm-verdict-note">{html.escape(err_msg)}</span>' if err_msg else ""
        return (
            '<div class="flm-verdict">'
            f'<span class="flm-pill flm-pill-err">❌ Execution failed ({html.escape(err_t)})</span>'
            f"{detail}</div>"
        )

    pred_str = format_scalar_value(exec_res.value)
    if gt is not None:
        exp_val = gt["expected_value"]
        exp_str = format_scalar_value(exp_val)
        if values_equal(exec_res.value, exp_val):
            return (
                '<div class="flm-verdict">'
                f'<span class="flm-pill flm-pill-ok">✅ {html.escape(pred_str)} '
                "— matches ground truth</span></div>"
            )
        ref_formula = html.escape(str(gt["reference_formula"]))
        ex = _EXAMPLE_BY_ID.get(str(gt.get("id", "")))
        failure_box = ""
        if ex is not None and ex.is_honest_failure and ex.note:
            failure_box = (
                '<div class="flm-failure-box">'
                f"{ICON_ALERT}<div><strong>Honest failure caught by execution</strong>"
                f"<p>{html.escape(ex.note)}</p></div></div>"
            )
        return (
            '<div class="flm-verdict">'
            f'<span class="flm-pill flm-pill-err">❌ {html.escape(pred_str)} ≠ '
            f"{html.escape(exp_str)} (ground truth)</span>"
            f'<span class="flm-verdict-note">Reference: <code>{ref_formula}</code></span>'
            f"</div>{failure_box}"
        )

    suffix = f" on {rows_note}" if rows_note else ""
    return (
        '<div class="flm-verdict">'
        f'<span class="flm-pill flm-pill-neutral">Executed: {html.escape(pred_str)}'
        f"{html.escape(suffix)}</span></div>"
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
    """One compact meta line: 'Q5_K_M · local Ollama · 3.2 s · 9.2 tok/s'."""
    backend_label = {
        "ollama": "local Ollama",
        "llamacpp": "local llama.cpp",
        "mock": "mock backend (offline)",
    }.get(backend_kind, backend_kind)

    parts = [html.escape(quant_label), html.escape(backend_label)]
    dot = "flm-dot-ok"
    if error_note:
        parts.append(html.escape(error_note))
        dot = "flm-dot-err"
    elif latency_s is not None:
        parts.append(f"{latency_s:.1f} s")
        if tok_per_s is not None and tok_per_s > 0 and backend_kind != "mock":
            parts.append(f"{tok_per_s:.1f} tok/s")
    elif warmup_state == "warming":
        parts.append("warming up...")
        dot = "flm-dot-wait"
    elif warmup_state == "error":
        parts.append("server offline")
        dot = "flm-dot-err"
    else:
        parts.append("ready")

    return f'<div class="flm-meta"><span class="flm-dot {dot}"></span>{" · ".join(parts)}</div>'


BASE_CAPTION = "Saved evaluation runs, not live"


def _render_single_base_card(title: str, tag: str, rec: dict[str, Any] | None) -> str:
    head = (
        f'<div class="flm-base-head"><span>{html.escape(title)}</span>'
        f'<span class="flm-chip-sm">{html.escape(tag)}</span></div>'
    )
    if rec is None:
        return (
            f'<div class="flm-base-card">{head}'
            '<div class="flm-base-reason">No saved prediction for this request.</div></div>'
        )

    ext = str(rec.get("extracted_formula") or rec.get("raw_output") or "").strip()
    ok = bool(rec.get("exec_correct"))
    err_t = rec.get("error_type")
    pred_v = rec.get("predicted_value")
    exp_v = rec.get("expected_value")
    err_msg = str(rec.get("error_message") or "").strip()

    if ok:
        chip = (
            '<span class="flm-pill-sm flm-pill-ok">'
            f"✅ {html.escape(format_scalar_value(pred_v))}</span>"
        )
    elif err_t:
        chip = (
            '<span class="flm-pill-sm flm-pill-err">'
            f"❌ {html.escape(str(err_t).replace('_', ' '))}</span>"
        )
    else:
        chip = (
            '<span class="flm-pill-sm flm-pill-err">'
            f"❌ Executed: {html.escape(format_scalar_value(pred_v))} "
            f"(expected {html.escape(format_scalar_value(exp_v))})</span>"
        )

    reason = ""
    if not ok and err_msg:
        short = err_msg if len(err_msg) <= 110 else err_msg[:107] + "..."
        reason = f'<div class="flm-base-reason">{html.escape(short)}</div>'

    return (
        f'<div class="flm-base-card">{head}{chip}'
        f'<div class="flm-base-formula"><code>{html.escape(ext)}</code></div>{reason}</div>'
    )


def format_saved_base_html(
    sheet_id: str,
    request: str,
    bundle: SavedEvalBundle,
    enabled: bool,
) -> str:
    """Two side-by-side saved base-model cards (only when the compare toggle is on)."""
    if not enabled:
        return ""

    key = _norm_key(sheet_id, request)
    b0 = bundle.base_zeroshot.get(key)
    b5 = bundle.base_5shot.get(key)
    caption = f'<div class="flm-base-caption">{BASE_CAPTION} · base Qwen3-1.7B, fp16</div>'
    if b0 is None and b5 is None:
        return (
            f"{caption}"
            '<div class="flm-base-empty">No saved base-model prediction exists for this '
            "request. The base model is never run live (one model in RAM at a time).</div>"
        )

    return (
        f"{caption}"
        '<div class="flm-base-grid">'
        f"{_render_single_base_card('Base 0-shot', 'Qwen3-1.7B · 0-shot', b0)}"
        f"{_render_single_base_card('Base 5-shot', 'Qwen3-1.7B · 5-shot', b5)}"
        "</div>"
    )


LIMITS_HTML = (
    '<div class="flm-limits">'
    "<p><strong>Excel dialect only.</strong> One formula starting with <code>=</code>; "
    "no Google Sheets <code>QUERY</code> or <code>ARRAYFORMULA</code>.</p>"
    "<p><strong>36 functions.</strong> Aggregation, conditional aggregation, lookups, text, "
    "date, <code>ROUND</code> and <code>IFERROR</code>; no <code>SUMPRODUCT</code>, "
    "<code>FILTER</code>, <code>LET</code>, <code>LAMBDA</code> or volatile "
    "<code>TODAY</code>/<code>NOW</code>/<code>RAND</code>.</p>"
    "<p><strong>Single sheet.</strong> One active sheet with bounded ranges; no multi-sheet "
    "joins.</p>"
    "<p><strong>Short formulas.</strong> Single-cell formulas up to 96 tokens.</p>"
    "<p><strong>Synthetic training data.</strong> Trained only on generated spreadsheets "
    "(9,000 synthetic examples on 20 training sheets).</p>"
    "<p><strong>Accuracy.</strong> On a small 50-request fresh held-out set (AI-drafted), "
    "Q5_K_M scored 86-90% (45/50 on Colab, 43/50 on local Ollama).</p>"
    "<p><strong>Always verify critical sheets</strong> before relying on a generated formula.</p>"
    "</div>"
)


# ---------------------------------------------------------------------------
# Runtime, background warm-up & query controller (pure Python, testable)
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
        rows_note = None
        if resolved.is_temp:
            noun = "sample rows" if resolved.synthesized else "rows"
            rows_note = f"{resolved.total_rows} {noun}"

        verdict_html = format_verdict_html(formula, exec_res, gt, rows_note=rows_note)
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
# CSS ("Formula Precision" tokens; system fonts only; zero external assets)
# ---------------------------------------------------------------------------

APP_CSS = """
:root, .dark, body, .gradio-container {
    --flm-sans: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    --flm-mono: "Cascadia Mono", "Cascadia Code", Consolas, "SFMono-Regular", Menlo, monospace;
    --flm-accent: #2563eb;
    --flm-accent-hover: #1d4ed8;
    --flm-ink: #0f172a;
    --flm-ink-2: #334155;
    --flm-muted: #64748b;
    --flm-border: #e3e6eb;
    --flm-canvas: #f7f8fa;
    --flm-tint: #eff4ff;
    --flm-tint-2: #dce9ff;
    --flm-ok: #16a34a;
    --flm-ok-ink: #166534;
    --flm-ok-bg: #f0fdf4;
    --flm-ok-border: #bbf7d0;
    --flm-err: #dc2626;
    --flm-err-ink: #991b1b;
    --flm-err-bg: #fef2f2;
    --flm-err-border: #fecaca;
    --body-background-fill: #f7f8fa;
    --background-fill-primary: #ffffff;
    --background-fill-secondary: #f7f8fa;
    --block-background-fill: #ffffff;
    --body-text-color: #0f172a;
    --body-text-color-subdued: #64748b;
    --input-background-fill: #ffffff;
    --border-color-primary: #e3e6eb;
    --block-border-color: #e3e6eb;
    color-scheme: light;
}
html, body { background: var(--flm-canvas) !important; }
body, .gradio-container {
    font-family: var(--flm-sans) !important;
    font-size: 18px !important;
    color: var(--flm-ink) !important;
}
.gradio-container {
    max-width: 100% !important;
    padding: 0 20px 8px 20px !important;
    background: var(--flm-canvas) !important;
}
footer { display: none !important; }
.gradio-container .column, .gradio-container .row { gap: 12px !important; }

/* ---------- Header ---------- */
.flm-header {
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 8px 16px; padding: 12px 0 6px 0;
}
.flm-brand { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.flm-title { font-size: 26px; font-weight: 700; letter-spacing: -0.015em; color: var(--flm-ink); }
.flm-subtitle { font-size: 17px; color: var(--flm-ink-2); }
.flm-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.flm-chip {
    background: var(--flm-tint-2); color: var(--flm-ink-2);
    border-radius: 6px; padding: 3px 10px; font-size: 14px; font-weight: 600;
    font-family: var(--flm-mono); white-space: nowrap;
}

/* ---------- Tabs ---------- */
.flm-tabs { background: transparent !important; border: none !important; }
.flm-tabs [role="tablist"] {
    border-bottom: 1px solid var(--flm-border) !important;
    gap: 6px !important; padding-bottom: 6px !important; margin-bottom: 8px !important;
}
.flm-tabs button[role="tab"] {
    font-size: 16px !important; font-weight: 600 !important;
    padding: 6px 14px !important; border-radius: 6px !important;
    color: var(--flm-ink-2) !important; background: transparent !important;
    border: none !important;
}
.flm-tabs button[role="tab"][aria-selected="true"], .flm-tabs button[role="tab"].selected {
    background: var(--flm-accent) !important; color: #ffffff !important;
}
.flm-tabs button[role="tab"][aria-selected="true"]::after,
.flm-tabs button[role="tab"].selected::after { display: none !important; }
.flm-tabs .tabitem {
    padding: 0 !important; border: none !important; background: transparent !important;
}

/* ---------- Example button row ---------- */
#flm-ex-row { flex-wrap: wrap !important; gap: 6px !important; margin-bottom: 4px !important; }
#flm-ex-row > * { flex: 0 0 auto !important; min-width: 0 !important; width: auto !important; }
button.flm-ex {
    background: #ffffff !important; color: var(--flm-ink-2) !important;
    border: 1px solid var(--flm-border) !important; border-radius: 6px !important;
    font-size: 15px !important; font-weight: 600 !important; letter-spacing: 0.02em;
    padding: 6px 14px !important; min-height: 36px !important; box-shadow: none !important;
    white-space: nowrap !important;
}
button.flm-ex:hover { background: var(--flm-tint) !important; color: var(--flm-ink) !important; }
button.flm-ex-active {
    color: var(--flm-accent) !important; border: 2px solid var(--flm-accent) !important;
    background: #ffffff !important;
}
button.flm-ex-fail {
    color: var(--flm-err) !important; border: 2px solid var(--flm-err) !important;
    background: #ffffff !important;
}
button.flm-ex-fail.flm-ex-active { background: var(--flm-err-bg) !important; }
button.flm-ex-active::before, button.flm-ex-fail::before {
    content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    margin-right: 7px; vertical-align: middle; background: currentColor;
}

/* ---------- Cards ---------- */
.flm-card, .flm-panel {
    background: #ffffff !important; border: 1px solid var(--flm-border) !important;
    border-radius: 12px !important; padding: 14px 16px !important; box-shadow: none !important;
}
.flm-panel { gap: 8px !important; }
.flm-panel > .styler, .flm-panel .block, .flm-panel .form {
    background: transparent !important; border: none !important; box-shadow: none !important;
    padding: 0 !important; overflow: visible !important;
}
.flm-card-head {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    margin-bottom: 10px;
}
.flm-card-title {
    display: flex; align-items: center; gap: 8px; font-size: 17px; font-weight: 600;
    color: var(--flm-ink); flex-wrap: wrap;
}
.flm-title-lg { font-size: 20px; }
.flm-ico { width: 20px; height: 20px; color: var(--flm-accent); flex: 0 0 auto; }
.flm-formula-head .flm-ico { color: var(--flm-ok); }
.flm-sheet-name { font-family: var(--flm-mono); font-weight: 700; }
.flm-sheet-sub { font-size: 14px; color: var(--flm-muted); font-weight: 400; }
.flm-chip-sm {
    background: var(--flm-tint-2); color: var(--flm-ink-2); border-radius: 4px;
    padding: 2px 8px; font-size: 13px; font-weight: 500; font-family: var(--flm-mono);
    white-space: nowrap;
}

/* ---------- Sheet preview table ---------- */
.flm-table-wrap {
    overflow-x: auto; border-radius: 8px; background: var(--flm-tint);
    border: 1px solid var(--flm-border);
}
.flm-table { width: 100%; border-collapse: collapse; font-size: 14px; white-space: nowrap; }
.flm-table th {
    background: var(--flm-tint-2); color: var(--flm-ink-2); font-weight: 600;
    text-align: left; padding: 6px 10px; vertical-align: bottom; line-height: 1.2;
}
.flm-table td {
    padding: 6px 10px; border-top: 1px solid var(--flm-border); color: var(--flm-ink);
    font-family: var(--flm-mono); font-size: 13.5px; background: #ffffff;
}
.flm-col-letter {
    display: block; font-family: var(--flm-mono); font-weight: 700; color: var(--flm-accent);
    font-size: 13px;
}
.flm-col-name { display: block; font-size: 13.5px; }
.flm-table .flm-rownum {
    width: 34px; text-align: center; color: var(--flm-muted) !important;
    background: var(--flm-tint) !important; font-family: var(--flm-mono); font-size: 12px;
}
.flm-empty-table {
    padding: 18px 12px; color: var(--flm-muted); font-size: 15px; text-align: center;
    background: var(--flm-tint); border-radius: 8px; border: 1px dashed #c3c6d7;
}

/* ---------- Inputs ---------- */
.flm-input [data-testid="block-info"], .flm-input label > span:first-child {
    font-size: 16px !important; font-weight: 600 !important; color: var(--flm-ink) !important;
}
.flm-input textarea, .flm-input input[type="text"] {
    font-family: var(--flm-sans) !important; font-size: 18px !important;
    line-height: 1.4 !important; color: var(--flm-ink) !important;
    background: var(--flm-tint) !important;
    border: 1px solid var(--flm-border) !important; border-radius: 8px !important;
    padding: 10px 12px !important; box-shadow: none !important;
}
.flm-input textarea:focus, .flm-input input[type="text"]:focus {
    border-color: var(--flm-accent) !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15) !important;
}
.flm-upload, .flm-upload .block { min-height: 0 !important; }
.flm-upload [data-testid="block-info"] {
    font-size: 16px !important; font-weight: 600 !important; color: var(--flm-ink) !important;
}

/* ---------- Primary button ---------- */
button.flm-primary {
    background: var(--flm-accent) !important; color: #ffffff !important; border: none !important;
    border-radius: 8px !important; font-size: 18px !important; font-weight: 700 !important;
    min-height: 48px !important; box-shadow: none !important;
}
button.flm-primary:hover { background: var(--flm-accent-hover) !important; }

/* ---------- Formula box ---------- */
.flm-formula textarea, .flm-formula input[type="text"] {
    font-family: var(--flm-mono) !important; font-size: 23px !important;
    font-weight: 600 !important; line-height: 1.35 !important;
    color: #003ea8 !important; background: var(--flm-tint) !important;
    border: 1px solid var(--flm-border) !important; border-radius: 8px !important;
    padding: 14px 16px !important; box-shadow: none !important;
}

/* ---------- Verdict + meta ---------- */
.flm-verdict { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 2px; }
.flm-pill {
    display: inline-flex; align-items: center; gap: 6px; font-size: 17px; font-weight: 700;
    padding: 6px 14px; border-radius: 6px; border: 1px solid transparent;
}
.flm-pill-sm {
    display: inline-flex; align-items: center; font-size: 14px; font-weight: 600;
    padding: 3px 10px; border-radius: 4px; border: 1px solid transparent; margin-bottom: 8px;
}
.flm-pill-ok {
    background: var(--flm-ok-bg); color: var(--flm-ok-ink); border-color: var(--flm-ok-border);
}
.flm-pill-err {
    background: var(--flm-err-bg); color: var(--flm-err-ink); border-color: var(--flm-err-border);
}
.flm-pill-neutral { background: #f1f5f9; color: var(--flm-ink-2); border-color: #e2e8f0; }
.flm-verdict-note { font-size: 14px; color: var(--flm-ink-2); }
.flm-verdict-note code, .flm-limits code {
    font-family: var(--flm-mono); font-size: 13.5px; background: var(--flm-tint);
    padding: 1px 6px; border-radius: 4px; color: var(--flm-ink);
}
.flm-failure-box {
    display: flex; gap: 10px; margin-top: 10px; padding: 10px 14px; border-radius: 8px;
    background: var(--flm-err-bg); border: 1px solid var(--flm-err-border);
}
.flm-failure-box .flm-ico { color: var(--flm-err); margin-top: 2px; }
.flm-failure-box strong { color: var(--flm-err-ink); font-size: 16px; }
.flm-failure-box p {
    margin: 4px 0 0 0; font-size: 15.5px; line-height: 1.45; color: var(--flm-ink);
}
.flm-meta {
    display: flex; align-items: center; gap: 8px; font-family: var(--flm-mono);
    font-size: 14px; color: var(--flm-muted); margin-top: 2px;
}
.flm-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.flm-dot-ok { background: var(--flm-ok); }
.flm-dot-wait { background: #f59e0b; }
.flm-dot-err { background: var(--flm-err); }

/* ---------- Compare toggle (checkbox styled as a switch) ---------- */
.flm-toggle { padding: 0 !important; }
.flm-toggle label {
    display: flex !important; align-items: center !important; gap: 10px !important;
}
.flm-toggle label > span {
    font-size: 17px !important; font-weight: 600 !important; color: var(--flm-ink) !important;
}
.flm-toggle input[type="checkbox"] {
    appearance: none !important; -webkit-appearance: none !important;
    width: 40px !important; height: 22px !important; border-radius: 999px !important;
    background: #cbd5e1 !important; border: none !important; position: relative !important;
    cursor: pointer !important; transition: background 0.15s ease; flex: 0 0 auto !important;
    background-image: none !important;
}
.flm-toggle input[type="checkbox"]::before {
    content: ""; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px;
    border-radius: 50%; background: #ffffff; transition: left 0.15s ease;
}
.flm-toggle input[type="checkbox"]:checked { background: var(--flm-accent) !important; }
.flm-toggle input[type="checkbox"]:checked::before { left: 21px; }

/* ---------- Base cards ---------- */
.flm-base-caption {
    font-size: 14px; font-style: italic; color: var(--flm-muted); margin: 2px 0 8px 0;
}
.flm-base-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.flm-base-card {
    background: var(--flm-tint); border: 1px solid var(--flm-border); border-radius: 8px;
    padding: 12px 14px; min-width: 0;
}
.flm-base-head {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    font-size: 16px; font-weight: 600; color: var(--flm-ink); margin-bottom: 8px;
}
.flm-base-formula {
    background: #ffffff; border: 1px solid var(--flm-border); border-radius: 4px;
    padding: 6px 8px; overflow-x: auto;
}
.flm-base-formula code {
    font-family: var(--flm-mono); font-size: 13.5px; color: var(--flm-ink); white-space: nowrap;
}
.flm-base-reason { margin-top: 6px; font-size: 13.5px; color: var(--flm-muted); line-height: 1.35; }
.flm-base-empty {
    font-size: 15px; color: var(--flm-muted); background: var(--flm-tint);
    border: 1px solid var(--flm-border); border-radius: 8px; padding: 10px 14px;
}

/* ---------- Footer accordions ---------- */
#flm-footer { margin-top: 8px !important; }
.flm-acc {
    background: var(--flm-tint) !important; border: 1px solid var(--flm-border) !important;
    border-radius: 8px !important; box-shadow: none !important;
}
.flm-acc > button, .flm-acc button.label-wrap {
    font-size: 16px !important; font-weight: 600 !important; color: var(--flm-ink-2) !important;
}
.flm-limits p { margin: 4px 0; font-size: 15.5px; line-height: 1.45; color: var(--flm-ink); }
.flm-schema textarea {
    font-family: var(--flm-mono) !important; font-size: 14px !important;
    background: #ffffff !important; color: var(--flm-ink) !important;
}
.flm-credit-line {
    text-align: center; font-size: 13px; color: var(--flm-muted);
    padding: 4px 0 2px 0;
}
"""

FORCE_LIGHT_JS = """
() => {
    const force = () => {
        document.body.classList.remove('dark');
        document.documentElement.classList.remove('dark');
        document.documentElement.style.colorScheme = 'light';
    };
    force();
    new MutationObserver(force).observe(
        document.body, { attributes: true, attributeFilter: ['class'] }
    );
}
"""


def _header_html(quant_label: str) -> str:
    size_chip = f"{quant_label} · 1.2 GB" if quant_label == "Q5_K_M" else quant_label
    chips = ("Qwen3-1.7B", size_chip, "CPU only", "Offline")
    return (
        '<div class="flm-header">'
        '<div class="flm-brand"><span class="flm-title">FormulaLM</span>'
        '<span class="flm-subtitle">Plain-English to verified Excel formula</span></div>'
        '<div class="flm-chips">'
        + "".join(f'<span class="flm-chip">{html.escape(c)}</span>' for c in chips)
        + "</div></div>"
    )


def _button_classes(ex: BuiltinExample, active_id: str) -> list[str]:
    classes = ["flm-ex"]
    if ex.is_honest_failure:
        classes.append("flm-ex-fail")
    if ex.example_id == active_id:
        classes.append("flm-ex-active")
    return classes


def build_demo_app(runtime: DemoRuntime) -> gr.Blocks:
    """Construct the FormulaLM Gradio Blocks application (Stitch "Formula Precision" layout)."""
    first_ex = BUILTIN_EXAMPLES[0]
    initial_sheet = resolve_heldout_sheet(first_ex.sheet_id, runtime.bundle)

    def _meta_now() -> str:
        return format_meta_line_html(
            backend_kind=runtime.backend_kind,
            quant_label=runtime.quant_label,
            latency_s=None,
            warmup_state=runtime.warmup_state,
        )

    idle_verdict = format_verdict_html("", None, None, idle_hint=True)
    empty_custom_card = render_sheet_preview_html(
        "Your sheet", "paste headers or upload", pd.DataFrame()
    )

    with gr.Blocks(
        analytics_enabled=False, title="FormulaLM — Plain-English to verified Excel formula"
    ) as demo:
        gr.HTML(_header_html(runtime.quant_label))

        active_sheet_state = gr.State(value=first_ex.sheet_id)
        held_ran_state = gr.State(value=False)
        custom_ran_state = gr.State(value=False)

        with gr.Tabs(elem_classes=["flm-tabs"]):
            # ---------------------------------------------------------------
            # Tab 1: Held-out examples
            # ---------------------------------------------------------------
            with gr.Tab("Held-out examples"):
                ex_buttons: list[gr.Button] = []
                with gr.Row(elem_id="flm-ex-row"):
                    for i, ex in enumerate(BUILTIN_EXAMPLES, start=1):
                        ex_buttons.append(
                            gr.Button(
                                example_button_label(i, ex),
                                size="sm",
                                elem_classes=_button_classes(ex, first_ex.example_id),
                            )
                        )

                with gr.Row(equal_height=False):
                    with gr.Column(scale=2, min_width=420):
                        sheet_card = gr.HTML(_sheet_card_for(initial_sheet))
                        with gr.Group(elem_classes=["flm-panel"]):
                            request_box = gr.Textbox(
                                value=first_ex.request,
                                label="Plain-English request",
                                lines=2,
                                max_lines=3,
                                elem_classes=["flm-input"],
                            )
                            run_btn = gr.Button(
                                "Generate & verify",
                                variant="primary",
                                elem_classes=["flm-primary"],
                            )

                    with gr.Column(scale=3, min_width=560):
                        with gr.Group(elem_classes=["flm-panel"]):
                            gr.HTML(formula_card_header_html(runtime.quant_label))
                            formula_out = gr.Textbox(
                                value="",
                                show_label=False,
                                lines=1,
                                max_lines=3,
                                interactive=False,
                                buttons=["copy"],
                                placeholder="=…",
                                elem_classes=["flm-formula"],
                            )
                            verdict_out = gr.HTML(idle_verdict)
                            meta_out = gr.HTML(_meta_now())

                        with gr.Group(elem_classes=["flm-panel"]):
                            compare_toggle = gr.Checkbox(
                                value=True,
                                label="Compare with base model",
                                elem_classes=["flm-toggle"],
                            )
                            base_out = gr.HTML(
                                format_saved_base_html(
                                    first_ex.sheet_id, first_ex.request, runtime.bundle, True
                                )
                            )

            # ---------------------------------------------------------------
            # Tab 2: Your own sheet
            # ---------------------------------------------------------------
            with gr.Tab("Your own sheet"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2, min_width=420):
                        with gr.Group(elem_classes=["flm-panel"]):
                            with gr.Row(equal_height=True):
                                pasted_input = gr.Textbox(
                                    label="Paste column headers",
                                    placeholder="Region, Sales Rep, Units, Net Sales",
                                    lines=2,
                                    scale=3,
                                    elem_classes=["flm-input"],
                                )
                                upload_input = gr.File(
                                    label="or upload CSV / XLSX (max 1 MB)",
                                    file_count="single",
                                    file_types=[".csv", ".xlsx"],
                                    type="filepath",
                                    height=96,
                                    scale=2,
                                    elem_classes=["flm-upload"],
                                )
                        custom_sheet_card = gr.HTML(empty_custom_card)
                        with gr.Group(elem_classes=["flm-panel"]):
                            custom_request_box = gr.Textbox(
                                value="",
                                label="Plain-English request",
                                placeholder="e.g., Total Net Sales for North",
                                lines=2,
                                max_lines=3,
                                elem_classes=["flm-input"],
                            )
                            custom_run_btn = gr.Button(
                                "Generate & verify",
                                variant="primary",
                                elem_classes=["flm-primary"],
                            )

                    with gr.Column(scale=3, min_width=560):
                        with gr.Group(elem_classes=["flm-panel"]):
                            gr.HTML(formula_card_header_html(runtime.quant_label))
                            custom_formula_out = gr.Textbox(
                                value="",
                                show_label=False,
                                lines=1,
                                max_lines=3,
                                interactive=False,
                                buttons=["copy"],
                                placeholder="=…",
                                elem_classes=["flm-formula"],
                            )
                            custom_verdict_out = gr.HTML(idle_verdict)
                            custom_meta_out = gr.HTML(_meta_now())

        # -------------------------------------------------------------------
        # Footer: two accordions, closed by default
        # -------------------------------------------------------------------
        with gr.Row(elem_id="flm-footer"):
            with gr.Accordion("Limits & scope", open=False, elem_classes=["flm-acc"]):
                gr.HTML(LIMITS_HTML)
            with gr.Accordion("Show prompt sent to model", open=False, elem_classes=["flm-acc"]):
                schema_box = gr.Textbox(
                    value=initial_sheet.schema_text,
                    show_label=False,
                    lines=8,
                    interactive=False,
                    elem_classes=["flm-schema"],
                )
        gr.HTML(
            '<div class="flm-credit-line">'
            "Built by Abu Bakar · MIT code · Apache-2.0 weights (Qwen3-1.7B)"
            "</div>"
        )

        # Poll the background warm-up so the meta line flips from "warming up..." to "ready".
        warmup_timer = gr.Timer(value=1.0, active=runtime.warmup_state in ("warming", "idle"))

        def _poll_warmup(held_ran: bool, custom_ran: bool):
            still = runtime.warmup_state in ("warming", "idle")
            meta = _meta_now()
            return (
                gr.update() if held_ran else meta,
                gr.update() if custom_ran else meta,
                gr.Timer(active=still),
            )

        warmup_timer.tick(
            fn=_poll_warmup,
            inputs=[held_ran_state, custom_ran_state],
            outputs=[meta_out, custom_meta_out, warmup_timer],
        )

        # ---- Held-out tab events ----
        def _select_example(ex_id: str, show_base: bool):
            ex = _EXAMPLE_BY_ID[ex_id]
            resolved = resolve_heldout_sheet(ex.sheet_id, runtime.bundle)
            btn_updates = [
                gr.update(elem_classes=_button_classes(item, ex.example_id))
                for item in BUILTIN_EXAMPLES
            ]
            return (
                ex.sheet_id,
                _sheet_card_for(resolved),
                ex.request,
                "",
                idle_verdict,
                format_saved_base_html(ex.sheet_id, ex.request, runtime.bundle, show_base),
                resolved.schema_text,
                *btn_updates,
            )

        for ex, btn in zip(BUILTIN_EXAMPLES, ex_buttons, strict=True):
            btn.click(
                fn=lambda show_b, _eid=ex.example_id: _select_example(_eid, show_b),
                inputs=[compare_toggle],
                outputs=[
                    active_sheet_state,
                    sheet_card,
                    request_box,
                    formula_out,
                    verdict_out,
                    base_out,
                    schema_box,
                    *ex_buttons,
                ],
            )

        compare_toggle.change(
            fn=lambda show_b, sid, req: format_saved_base_html(
                sid or "", req or "", runtime.bundle, show_b
            ),
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
            return formula, verdict, meta, base_html, schema_txt or gr.update(), True

        for trigger in (run_btn.click, request_box.submit):
            trigger(
                fn=_on_run_heldout,
                inputs=[active_sheet_state, request_box, compare_toggle],
                outputs=[formula_out, verdict_out, meta_out, base_out, schema_box, held_ran_state],
            )

        # ---- Your own sheet tab events ----
        def _preview_custom(pasted: str, uploaded: str | None):
            resolved: ResolvedSheet | None = None
            try:
                if uploaded:
                    resolved = resolve_uploaded_file(uploaded)
                elif (pasted or "").strip():
                    resolved = resolve_pasted_headers(pasted)
                else:
                    return empty_custom_card, gr.update()
                return _sheet_card_for(resolved), resolved.schema_text
            except ValueError as exc:
                err = (
                    '<div class="flm-card flm-sheet-card"><div class="flm-empty-table">'
                    f"❌ {html.escape(str(exc))}</div></div>"
                )
                return err, gr.update()
            finally:
                if resolved is not None and resolved.is_temp and resolved.xlsx_path.is_file():
                    try:
                        resolved.xlsx_path.unlink()
                    except OSError:
                        pass

        for change_evt in (pasted_input.change, upload_input.change):
            change_evt(
                fn=_preview_custom,
                inputs=[pasted_input, upload_input],
                outputs=[custom_sheet_card, schema_box],
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
            if not preview_df.empty and not uploaded:
                ncols = max(0, len(preview_df.columns) - 1)
                card = render_sheet_preview_html(
                    "custom_headers",
                    "pasted headers · synthesized sample rows",
                    preview_df,
                    rows_cols_chip=f"{len(preview_df)} rows · {ncols} cols",
                )
            else:
                card = gr.update()
            return formula, verdict, meta, card, schema_txt or gr.update(), True

        for trigger in (custom_run_btn.click, custom_request_box.submit):
            trigger(
                fn=_on_run_custom,
                inputs=[pasted_input, upload_input, custom_request_box],
                outputs=[
                    custom_formula_out,
                    custom_verdict_out,
                    custom_meta_out,
                    custom_sheet_card,
                    schema_box,
                    custom_ran_state,
                ],
            )

    return demo


def build_offline_theme() -> gr.themes.Base:
    """System-font light theme with zero Google Fonts or external CDN requests."""
    return gr.themes.Base(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
        radius_size="md",
        font=["system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
        font_mono=["Cascadia Mono", "Consolas", "SFMono-Regular", "ui-monospace", "monospace"],
    ).set(
        body_background_fill="#f7f8fa",
        body_background_fill_dark="#f7f8fa",
        body_text_color="#0f172a",
        body_text_color_dark="#0f172a",
        block_background_fill="#ffffff",
        block_background_fill_dark="#ffffff",
        block_border_color="#e3e6eb",
        block_border_color_dark="#e3e6eb",
        input_background_fill="#ffffff",
        input_background_fill_dark="#ffffff",
        button_primary_background_fill="#2563eb",
        button_primary_background_fill_dark="#2563eb",
        button_primary_background_fill_hover="#1d4ed8",
        button_primary_background_fill_hover_dark="#1d4ed8",
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
        css=APP_CSS,
        js=FORCE_LIGHT_JS,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
