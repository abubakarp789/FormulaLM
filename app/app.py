"""FormulaLM local Gradio demo application.

Features:
- Input via 5 held-out spreadsheets, uploaded small CSV/XLSX (<= 1 MB), or pasted column headers.
- Localhost-only inference via Ollama (default: ``formulalm`` Q5_K_M from ``deploy/Modelfile``),
  ``llama.cpp`` (``llama-server``), or deterministic ``mock`` backend for offline testing.
- Safe formula execution via ``src.eval.executor.run_formula`` with clear error diagnostics.
- Side-by-side comparison against **saved** base ``Qwen3-1.7B`` evaluation runs
  (``results/baseline_*``) — never loads a second model in RAM on 8 GB laptops.
- 8 built-in realistic requests across all 5 held-out sheets, including 1 honestly labeled
  failure case (``real_v2_050``) where ``Q5_K_M`` predicts the wrong ``VLOOKUP`` column index.
- Plain light theme with large fonts optimized for 1080p screen recordings.

CLI usage:
    uv run python app/app.py
    uv run python app/app.py --backend mock
    uv run python app/app.py --backend llamacpp --base-url http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
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
PREVIEW_ROWS = 8
MAX_NEW_TOKENS = 96
DEFAULT_SEED = 42

CUSTOM_SHEET_KEY = "__custom__"
CUSTOM_SHEET_LABEL = "Custom — upload CSV/XLSX or paste headers below"

LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_HEADER_PREFIX_RE = re.compile(r"^\s*(?:[A-Z]{1,2}\s*:\s*)?(.+?)(?:\s*\(\s*([A-Za-z_]+)\s*\))?\s*$")


# ---------------------------------------------------------------------------
# Built-in examples (8 from test_real_v2 across all 5 held-out sheets,
# including 1 honestly labeled failure case)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuiltinExample:
    example_id: str
    label: str
    sheet_id: str
    request: str
    is_honest_failure: bool = False
    note: str = ""


BUILTIN_EXAMPLES: tuple[BuiltinExample, ...] = (
    BuiltinExample(
        example_id="real_v2_005",
        label="1. [Sales — COUNTIFS] Brinport sales with Quantity >= 15",
        sheet_id="sales_retail_store",
        request="How many Brinport sales had Quantity of at least 15?",
    ),
    BuiltinExample(
        example_id="real_v2_006",
        label="2. [Sales — IF + AND] Classify row 10 as 'Bulk High' vs 'Standard'",
        sheet_id="sales_retail_store",
        request=(
            "On row 10, return 'Bulk High' if Quantity >= 20 and Net Amount > 500, "
            "otherwise 'Standard'"
        ),
    ),
    BuiltinExample(
        example_id="real_v2_015",
        label="3. [HR — SUMIFS] Total Annual Salary for Design staff in Stonewick",
        sheet_id="hr_employee_roster",
        request="Total Annual Salary for Design staff based in Stonewick",
    ),
    BuiltinExample(
        example_id="real_v2_017",
        label="4. [HR — INDEX + MATCH] Find Work Hub for employee EMP-1010",
        sheet_id="hr_employee_roster",
        request="Find the Work Hub for employee EMP-1010 using INDEX and MATCH",
    ),
    BuiltinExample(
        example_id="real_v2_027",
        label="5. [Inventory — XLOOKUP] Look up Valuation for movement MOV-1010",
        sheet_id="inventory_stock_movements",
        request="Look up the Valuation for MOV-1010 using XLOOKUP",
    ),
    BuiltinExample(
        example_id="real_v2_040",
        label="6. [Grades — IFERROR + ROUND + SUMIF/SUM] Physics share of Assignments Done",
        sheet_id="grades_course_scores",
        request=(
            "Share of total Assignments Done completed by Physics students, "
            "rounded to 3 decimals (0 on error)"
        ),
    ),
    BuiltinExample(
        example_id="real_v2_045",
        label="7. [Orders — SUMIFS] Shipping Fee for Shipped Marketplace orders",
        sheet_id="orders_ecommerce",
        request="Total Shipping Fee for Marketplace orders that are Shipped",
    ),
    BuiltinExample(
        example_id="real_v2_050",
        label=(
            "8. [HONEST FAILURE — model is WRONG] Orders VLOOKUP Order Total for ORD-1015 "
            "(off-by-one column index)"
        ),
        sheet_id="orders_ecommerce",
        request="VLOOKUP Order Total for ORD-1015 rounded to 1 decimal, returning 0 if not found",
        is_honest_failure=True,
        note=(
            "Honest failure case: Q5_K_M generates syntactically valid Excel, but passes "
            "col_index_num=6 (Discount %, returning 11.0) instead of 7 (Order Total, 533.0). "
            "Executable evaluation catches this semantic error."
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
        # Match known held-out requests so even the honest failure reproduces in mock mode.
        sheet_m = re.search(r"^Sheet:\s*([^\s(]+)", user_msg, flags=re.MULTILINE)
        req_m = re.search(r"\nRequest:\s*(.+)$", user_msg, flags=re.DOTALL)
        if sheet_m and req_m:
            key = (sheet_m.group(1).strip(), req_m.group(1).strip().lower())
            if key in self._saved:
                return self._saved[key]

        # Fallback for custom uploaded CSV/XLSX or pasted headers: sum first numeric column,
        # or count values in column A.
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
    head.insert(0, "Excel Row", [str(r) for r in range(2, 2 + len(head))])
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
        source_note=(
            f"Uploaded `{path.name}` ({size_bytes / 1024:.1f} KB, "
            f"{len(df)} data rows, {df.shape[1]} columns)."
        ),
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

    # Filter optional boilerplate lines if user pasted a full schema block.
    filtered = [
        ln for ln in lines if not ln.lower().startswith("sheet:") and ln.lower() != "columns:"
    ]
    if not filtered:
        raise ValueError("No column definitions found in pasted text.")

    # Case A: Multi-line CSV/TSV with header row + actual data rows.
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
            source_note=f"Pasted CSV data ({len(df)} rows, {df.shape[1]} columns).",
            is_temp=True,
        )

    # Case B: Header-only paste (comma-separated, pipe-separated, tab-separated, or 1-per-line).
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
        source_note=(
            f"Pasted {len(headers)} column header(s) — synthesized 5 sample rows "
            "(rows 2..6) so the formula can be executed immediately."
        ),
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
        source_note=(
            f"Held-out test sheet `{ctx.sheet_id}` ({ctx.domain}, rows 2..{ctx.last_row}, "
            f"{len(ctx.columns)} columns — never seen during training)."
        ),
        is_temp=False,
    )


# ---------------------------------------------------------------------------
# Formatting helpers for UI output cards
# ---------------------------------------------------------------------------


def format_scalar_value(val: Any) -> str:
    if val is None:
        return "None (blank)"
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


def format_execution_markdown(
    formula: str,
    exec_res: ExecutionResult,
    gt: dict[str, Any] | None,
    source_note: str,
) -> str:
    lines: list[str] = []
    if not formula:
        lines.append("### Execution Result\n- **Error:** Model returned an empty response.")
        return "\n".join(lines)

    if exec_res.ok:
        formatted_val = format_scalar_value(exec_res.value)
        lines.append(f"### Executed Value: `{formatted_val}`")
        lines.append(f"- **Value type:** `{exec_res.value_type}` (engine: `{exec_res.engine}`)")
    else:
        lines.append("### Execution Failed")
        lines.append(f"- **Error category:** `{exec_res.error_type}`")
        lines.append(f"- **Details:** {exec_res.error_message}")

    if gt is not None:
        exp_val = gt["expected_value"]
        ref_formula = gt["reference_formula"]
        matched = exec_res.ok and values_equal(exec_res.value, exp_val)
        verdict = (
            "MATCHES GROUND TRUTH" if matched else "DOES NOT MATCH GROUND TRUTH (Honest Failure)"
        )
        badge = "✅" if matched else "❌"
        lines.append(
            f"- **Ground truth (`{gt['split']}` / `{gt['id']}`):** "
            f"`{format_scalar_value(exp_val)}`  →  {badge} **{verdict}**"
        )
        lines.append(f"- **Reference formula:** `{ref_formula}`")
    else:
        lines.append("- **Ground truth:** _Not applicable (custom sheet or custom request)_")

    lines.append(f"- **Active sheet:** {source_note}")
    return "\n".join(lines)


def format_saved_base_markdown(
    sheet_id: str,
    request: str,
    bundle: SavedEvalBundle,
    enabled: bool,
) -> str:
    if not enabled:
        return (
            "_Base-model comparison is turned off. Toggle the checkbox above to view saved "
            "`Qwen3-1.7B` predictions from `results/baseline_*`._"
        )

    key = _norm_key(sheet_id, request)
    b0 = bundle.base_zeroshot.get(key)
    b5 = bundle.base_5shot.get(key)
    if b0 is None and b5 is None:
        return (
            "### Saved evaluation run, base `Qwen3-1.7B`\n"
            "_No saved base-model prediction exists for this request._\n\n"
            "To protect 8 GB laptop RAM (`OLLAMA_MAX_LOADED_MODELS=1`), FormulaLM **never** "
            "runs the unquantized base model live. Saved base predictions are shown only for "
            "held-out requests present in `results/baseline_*` (`test_real_v2` and `test_real`)."
        )

    lines = [
        "### Saved evaluation run, base `Qwen3-1.7B` _(offline — not run live)_",
    ]
    for label, rec in (("Base `Qwen3-1.7B` (0-shot)", b0), ("Base `Qwen3-1.7B` (5-shot)", b5)):
        if rec is None:
            continue
        ext = str(rec.get("extracted_formula") or rec.get("raw_output") or "").strip()
        ok = bool(rec.get("exec_correct"))
        syn = bool(rec.get("syntax_valid"))
        err_t = rec.get("error_type")
        pred_v = rec.get("predicted_value")
        icon = "✅ Correct" if ok else "❌ Wrong"
        if not syn or err_t:
            outcome = f"Failed (`{err_t}`: {rec.get('error_message', 'execution failed')})"
        else:
            outcome = f"Executed value: `{format_scalar_value(pred_v)}`"
        lines.append(f"- **{label}** (`{rec['_source_file']}`): {icon}")
        lines.append(f"  - Formula: `{ext}`")
        lines.append(f"  - Outcome: {outcome}")
    return "\n".join(lines)


def format_status_markdown(
    *,
    backend_kind: str,
    base_url: str,
    model_name: str,
    quant_label: str,
    latency_s: float | None,
    tok_per_s: float | None = None,
    error_note: str | None = None,
) -> str:
    lat_str = f"**{latency_s:.2f} s**" if latency_s is not None else "_ready_"
    if tok_per_s is not None and tok_per_s > 0:
        lat_str += f" ({tok_per_s:.1f} tok/s)"
    endpoint_str = "in-process deterministic mock (offline)" if backend_kind == "mock" else base_url
    lines = [
        "### Runtime Status",
        f"- **Model:** `{model_name}` (`FormulaLM Qwen3-1.7B QLoRA v2-ship`)",
        (
            f"- **Quantization:** `{quant_label}` GGUF "
            "(single model loaded; `OLLAMA_MAX_LOADED_MODELS=1`)"
        ),
        f"- **Backend:** `{backend_kind}` @ `{endpoint_str}` _(localhost only, zero cloud calls)_",
        f"- **Latency:** {lat_str}",
    ]
    if error_note:
        lines.append(f"- **Backend error:** ⚠️ {error_note}")
    return "\n".join(lines)


LIMITS_MARKDOWN = "\n".join(
    [
        "### Limits & Scope",
        (
            "- **Excel dialect only:** outputs a single formula starting with `=` for one active "
            "sheet (no multi-sheet joins or Google Sheets `QUERY` / `ARRAYFORMULA`)."
        ),
        (
            "- **~35 supported functions (36 exact):** `SUM`/`COUNT`/`AVERAGE` (+ `IF`/`IFS`), "
            "`MIN`, `MAX`, `IF`, `IFS`, `AND`, `OR`, `VLOOKUP`, `XLOOKUP`, `INDEX`+`MATCH`, text "
            "(`LEFT`, `RIGHT`, `MID`, `LEN`, `CONCAT`, `TEXTJOIN`, `UPPER`, `LOWER`, `PROPER`, "
            "`TRIM`, `TEXT`), date (`DATE`, `YEAR`, `MONTH`, `DAY`), `ROUND`, `IFERROR`. Excludes "
            "`SUMPRODUCT`, `FILTER`, `LET`, and volatile `TODAY`/`NOW`/`RAND`."
        ),
        (
            "- **Short formulas & synthetic training:** trained on 9,000 synthetic examples "
            "(`max_new_tokens=96`). Reaches **88.0%–90.8%** execution accuracy on held-out "
            "realistic sets (`N=50` blind set) — can still miscount `VLOOKUP` column indices "
            "(see Built-in Example #8). Always verify critical financial formulas."
        ),
    ]
)


# ---------------------------------------------------------------------------
# Core inference + execution controller (pure Python, directly testable)
# ---------------------------------------------------------------------------


@dataclass
class DemoRuntime:
    backend_kind: str
    base_url: str
    model_name: str
    quant_label: str
    backend: Any
    bundle: SavedEvalBundle


def create_runtime(
    *,
    backend_kind: str = "ollama",
    base_url: str | None = None,
    model_name: str | None = None,
) -> DemoRuntime:
    gguf_file, modelfile_quant = detect_modelfile_quant()
    del gguf_file
    bundle = load_saved_eval_bundle()

    kind = backend_kind.strip().lower()
    if kind == "ollama":
        resolved_url = assert_localhost_url(base_url or "http://127.0.0.1:11434")
        resolved_model = (model_name or "formulalm").strip()
        quant = infer_quant_label(resolved_model, modelfile_quant)
        backend: Any = OllamaBackend(model=resolved_model, base_url=resolved_url, timeout=120.0)
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
    elif kind == "mock":
        resolved_url = assert_localhost_url(base_url or "http://127.0.0.1:11434")
        resolved_model = (model_name or "formulalm-mock").strip()
        quant = modelfile_quant
        backend = DemoMockBackend(saved_q5_by_prompt=bundle.local_q5_outputs)
    else:
        raise ValueError(f"Unsupported backend {backend_kind!r} (expected ollama, llamacpp, mock).")

    return DemoRuntime(
        backend_kind=kind,
        base_url=resolved_url,
        model_name=resolved_model,
        quant_label=quant,
        backend=backend,
        bundle=bundle,
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
    """Execute one end-to-end demo request and return UI component values.

    Returns:
        ``(formula_str, execution_md, status_md, base_comparison_md, preview_df, schema_text)``
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
                "Please select a held-out sheet, upload a small CSV/XLSX (<= 1 MB), "
                "or paste column headers."
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
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            err_msg = (
                f"Could not reach local `{runtime.backend_kind}` backend at `{runtime.base_url}` "
                f"for model `{runtime.model_name}`: {exc}"
            )
            status_md = format_status_markdown(
                backend_kind=runtime.backend_kind,
                base_url=runtime.base_url,
                model_name=runtime.model_name,
                quant_label=runtime.quant_label,
                latency_s=elapsed,
                error_note=err_msg,
            )
            base_md = format_saved_base_markdown(
                resolved.sheet_id, req, runtime.bundle, show_base_comparison
            )
            return (
                "",
                f"### Execution Skipped\n- **Backend Error:** {err_msg}",
                status_md,
                base_md,
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

        exec_md = format_execution_markdown(formula, exec_res, gt, resolved.source_note)
        status_md = format_status_markdown(
            backend_kind=runtime.backend_kind,
            base_url=runtime.base_url,
            model_name=runtime.model_name,
            quant_label=runtime.quant_label,
            latency_s=latency_s,
            tok_per_s=float(tok_s) if isinstance(tok_s, int | float) else None,
        )
        base_md = format_saved_base_markdown(
            resolved.sheet_id if not resolved.is_temp else "__custom__",
            req,
            runtime.bundle,
            show_base_comparison,
        )
        return (
            formula,
            exec_md,
            status_md,
            base_md,
            resolved.preview_df,
            resolved.schema_text,
        )
    except ValueError as exc:
        status_md = format_status_markdown(
            backend_kind=runtime.backend_kind,
            base_url=runtime.base_url,
            model_name=runtime.model_name,
            quant_label=runtime.quant_label,
            latency_s=None,
        )
        return (
            "",
            f"### Input Validation Error\n- {exc}",
            status_md,
            format_saved_base_markdown("", req, runtime.bundle, show_base_comparison),
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
# Gradio UI (plain light theme + large fonts for screen recording)
# ---------------------------------------------------------------------------

LIGHT_RECORDING_CSS = """
:root, body, .gradio-container {
    background-color: #ffffff !important;
    color: #0f172a !important;
    font-size: 18px !important;
}
.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
}
.gradio-container h1 {
    font-size: 2.0rem !important;
    font-weight: 700 !important;
    color: #0f172a !important;
}
.gradio-container h2, .gradio-container h3 {
    font-size: 1.25rem !important;
    color: #0f172a !important;
}
.gradio-container p, .gradio-container li, .gradio-container label, .gradio-container span {
    font-size: 1.05rem !important;
    line-height: 1.5 !important;
}
#formula-output textarea, #formula-output input {
    font-family: "IBM Plex Mono", Consolas, monospace !important;
    font-size: 1.35rem !important;
    font-weight: 700 !important;
    color: #0b4f6c !important;
    background-color: #f8fafc !important;
}
#request-input textarea {
    font-size: 1.15rem !important;
    background-color: #ffffff !important;
}
.card-panel {
    background: #f8fafc !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 8px !important;
    padding: 14px 18px !important;
}
"""

FORCE_LIGHT_JS = """
() => {
    document.body.classList.remove('dark');
    document.documentElement.style.colorScheme = 'light';
}
"""


def build_demo_app(runtime: DemoRuntime) -> gr.Blocks:
    """Construct the FormulaLM Gradio Blocks application."""
    sheet_choices: list[tuple[str, str]] = [
        (f"{sid} (held-out test sheet)", sid) for sid in runtime.bundle.heldout_contexts
    ]
    sheet_choices.append((CUSTOM_SHEET_LABEL, CUSTOM_SHEET_KEY))

    example_choices: list[tuple[str, str]] = [(ex.label, ex.example_id) for ex in BUILTIN_EXAMPLES]
    example_by_id = {ex.example_id: ex for ex in BUILTIN_EXAMPLES}

    first_ex = BUILTIN_EXAMPLES[0]
    initial_sheet = resolve_heldout_sheet(first_ex.sheet_id, runtime.bundle)
    initial_status = format_status_markdown(
        backend_kind=runtime.backend_kind,
        base_url=runtime.base_url,
        model_name=runtime.model_name,
        quant_label=runtime.quant_label,
        latency_s=None,
    )
    initial_base_md = format_saved_base_markdown(
        first_ex.sheet_id, first_ex.request, runtime.bundle, True
    )

    with gr.Blocks(
        analytics_enabled=False, title="FormulaLM — Local Excel Formula Generator"
    ) as demo:
        gr.Markdown(
            "# FormulaLM — Local Plain-English to Verified Excel Formula\n"
            "Fine-tuned **`Qwen3-1.7B` (`v2-ship`, `Q5_K_M` GGUF)** running **100% locally on "
            "CPU** and verified by executing every generated formula against spreadsheet rows."
        )

        with gr.Row():
            builtin_dropdown = gr.Dropdown(
                choices=example_choices,
                value=first_ex.example_id,
                label=(
                    "Built-in Held-Out Examples (8 realistic requests, including 1 honest failure)"
                ),
                scale=4,
            )
            compare_toggle = gr.Checkbox(
                value=True,
                label="Show saved Base Qwen3-1.7B comparison (offline — never loads a 2nd model)",
                scale=2,
            )

        example_note_md = gr.Markdown(value="", visible=False, elem_classes=["card-panel"])

        with gr.Row():
            with gr.Column(scale=5):
                sheet_dropdown = gr.Dropdown(
                    choices=sheet_choices,
                    value=first_ex.sheet_id,
                    label="1. Choose a Held-Out Sheet (or select Custom below)",
                )
                with gr.Accordion(
                    "Optional Custom Input: Upload CSV/XLSX (<= 1 MB) or Paste Column Headers",
                    open=False,
                ):
                    upload_input = gr.File(
                        label="Upload small .csv or .xlsx (max 1.0 MB, <= 2,000 rows, <= 26 cols)",
                        file_count="single",
                        file_types=[".csv", ".xlsx"],
                        type="filepath",
                    )
                    pasted_input = gr.Textbox(
                        label="Or paste column headers (comma/pipe-separated) or mini-CSV rows",
                        placeholder="Example: Region, Rep, Units, Net Sales",
                        lines=2,
                    )

                request_box = gr.Textbox(
                    value=first_ex.request,
                    label="2. Plain-English Spreadsheet Request",
                    placeholder="e.g., Total Net Amount for the Mirehaven branch",
                    lines=2,
                    elem_id="request-input",
                )
                run_btn = gr.Button("Generate & Execute Formula", variant="primary", size="lg")

                schema_box = gr.Textbox(
                    value=initial_sheet.schema_text,
                    label="Active Prompt Schema Sent to Model",
                    lines=7,
                    interactive=False,
                )

            with gr.Column(scale=6):
                formula_out = gr.Textbox(
                    value="",
                    label="Generated Excel Formula (click copy icon on right)",
                    lines=2,
                    interactive=False,
                    buttons=["copy"],
                    elem_id="formula-output",
                )
                exec_out_md = gr.Markdown(
                    value=(
                        "_Click **Generate & Execute Formula** to run local inference and "
                        "execute the formula._"
                    ),
                    elem_classes=["card-panel"],
                )
                base_out_md = gr.Markdown(
                    value=initial_base_md,
                    elem_classes=["card-panel"],
                )
                status_out_md = gr.Markdown(
                    value=initial_status,
                    elem_classes=["card-panel"],
                )

        preview_table = gr.Dataframe(
            value=initial_sheet.preview_df,
            label=(
                f"Sample Rows Preview (first {PREVIEW_ROWS} data rows — "
                f"Excel Row 2..{1 + PREVIEW_ROWS})"
            ),
            interactive=False,
            wrap=True,
        )

        gr.Markdown(LIMITS_MARKDOWN, elem_classes=["card-panel"])

        def _on_select_example(example_id: str, show_base: bool):
            ex = example_by_id[example_id]
            resolved = resolve_heldout_sheet(ex.sheet_id, runtime.bundle)
            note_text = f"**Note:** {ex.note}" if ex.note else ""
            base_md = format_saved_base_markdown(ex.sheet_id, ex.request, runtime.bundle, show_base)
            return (
                ex.sheet_id,
                None,
                "",
                ex.request,
                resolved.schema_text,
                resolved.preview_df,
                "",
                "_Click **Generate & Execute Formula** to run local inference._",
                base_md,
                gr.update(value=note_text, visible=bool(ex.note)),
            )

        def _on_change_sheet(sheet_id: str):
            if not sheet_id or sheet_id == CUSTOM_SHEET_KEY:
                return "", pd.DataFrame()
            resolved = resolve_heldout_sheet(sheet_id, runtime.bundle)
            return resolved.schema_text, resolved.preview_df

        def _on_toggle_base(
            show_base: bool, sheet_id: str, req: str, uploaded: str | None, pasted: str
        ):
            effective_sheet = (
                "__custom__" if (uploaded or (pasted or "").strip()) else (sheet_id or "")
            )
            return format_saved_base_markdown(effective_sheet, req or "", runtime.bundle, show_base)

        def _on_run(sheet_id: str, uploaded: str | None, pasted: str, req: str, show_base: bool):
            return run_demo_query(
                runtime,
                sheet_choice=sheet_id,
                uploaded_file=uploaded,
                pasted_headers=pasted,
                request_text=req,
                show_base_comparison=show_base,
            )

        builtin_dropdown.change(
            fn=_on_select_example,
            inputs=[builtin_dropdown, compare_toggle],
            outputs=[
                sheet_dropdown,
                upload_input,
                pasted_input,
                request_box,
                schema_box,
                preview_table,
                formula_out,
                exec_out_md,
                base_out_md,
                example_note_md,
            ],
        )

        sheet_dropdown.change(
            fn=_on_change_sheet,
            inputs=[sheet_dropdown],
            outputs=[schema_box, preview_table],
        )

        compare_toggle.change(
            fn=_on_toggle_base,
            inputs=[compare_toggle, sheet_dropdown, request_box, upload_input, pasted_input],
            outputs=[base_out_md],
        )

        run_btn.click(
            fn=_on_run,
            inputs=[sheet_dropdown, upload_input, pasted_input, request_box, compare_toggle],
            outputs=[
                formula_out,
                exec_out_md,
                status_out_md,
                base_out_md,
                preview_table,
                schema_box,
            ],
        )
        request_box.submit(
            fn=_on_run,
            inputs=[sheet_dropdown, upload_input, pasted_input, request_box, compare_toggle],
            outputs=[
                formula_out,
                exec_out_md,
                status_out_md,
                base_out_md,
                preview_table,
                schema_box,
            ],
        )

    return demo


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
    demo = build_demo_app(runtime)
    theme = gr.themes.Default(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate",
        text_size="lg",
    )
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=False,
        max_file_size="1mb",
        theme=theme,
        css=LIGHT_RECORDING_CSS,
        js=FORCE_LIGHT_JS,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
