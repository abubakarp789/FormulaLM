"""One-command CLI for FormulaLM: generate, verify, and inject Excel formulas locally.

Examples:
    # Generate + execute-verify + inject into a real .xlsx workbook:
    uv run formulalm "Total revenue where Region is North" \
        --file sales.xlsx --cell E2 --out sales_filled.xlsx

    # Generate from a quick schema without a file:
    uv run formulalm "Average price in column C" --schema "A:Product, B:Qty, C:Price (rows 2..50)"

    # Machine-readable JSON output for scripts / pipelines:
    uv run formulalm "Count rows where Status is Shipped" --file orders.xlsx --json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import openpyxl
import pandas as pd
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.build_dataset import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from src.eval.executor import run_formula, validate_formula  # noqa: E402
from src.eval.run_eval import OllamaBackend, extract_formula  # noqa: E402
from src.eval.xlsx_writer import inject_formula_into_xlsx, validate_cell_ref  # noqa: E402

LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEFAULT_MODEL = "formulalm:latest"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MAX_TOKENS = 96
DEFAULT_SEED = 42


def assert_localhost_url(url: str) -> str:
    """Enforce strictly local inference (no external network endpoints)."""
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid host URL scheme in {url!r} (expected http://localhost:11434)")
    host = (parsed.hostname or "").lower()
    if host not in LOCALHOST_HOSTS:
        raise ValueError(
            f"External inference hosts are blocked: {host!r} is not localhost/127.0.0.1/::1."
        )
    return cleaned


def _infer_col_type(series: pd.Series) -> str:
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
    if len(set(sample_strs)) <= max(3, len(sample_strs) // 2) and len(non_null) >= 6:
        return "category"
    return "text"


def extract_schema_from_file(
    file_path: Path,
    *,
    sheet_name: str | None = None,
) -> tuple[str, str, Path, bool]:
    """Read an .xlsx or .csv file and return ``(schema_text, active_sheet, exec_xlsx, is_temp)``."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Spreadsheet not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path)
        chosen_sheet = re.sub(r"[^A-Za-z0-9_]+", "_", file_path.stem).strip("_") or "Sheet1"
        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = chosen_sheet[:31]
        ws.append([str(c) for c in df.columns])
        for row in df.itertuples(index=False, name=None):
            ws.append([None if pd.isna(v) else v for v in row])
        fd, tmp_name = tempfile.mkstemp(prefix="formulalm_cli_", suffix=".xlsx")
        Path(tmp_name).unlink(missing_ok=True)
        import os

        os.close(fd)
        tmp_path = Path(tmp_name)
        wb.save(tmp_path)
        wb.close()
        exec_xlsx = tmp_path
        is_temp = True
    elif suffix == ".xlsx":
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        try:
            if sheet_name:
                if sheet_name not in wb.sheetnames:
                    raise ValueError(
                        f"Sheet {sheet_name!r} not found in {file_path.name} "
                        f"(available: {', '.join(wb.sheetnames)})"
                    )
                chosen_sheet = sheet_name
            else:
                chosen_sheet = wb.sheetnames[0]
        finally:
            wb.close()
        df = pd.read_excel(file_path, sheet_name=chosen_sheet, engine="openpyxl")
        exec_xlsx = file_path
        is_temp = False
    else:
        raise ValueError(f"Unsupported file format {suffix!r}; expected .xlsx or .csv.")

    if df.shape[1] == 0:
        raise ValueError(f"Spreadsheet {file_path.name} has no columns.")
    last_row = max(2, len(df) + 1)
    lines = [f"Sheet: {chosen_sheet} (rows 2..{last_row})", "Columns:"]
    for idx, col in enumerate(df.columns):
        letter = get_column_letter(idx + 1)
        ctype = _infer_col_type(df[col])
        lines.append(f"{letter}: {col} ({ctype})")
    return "\n".join(lines), chosen_sheet, exec_xlsx, is_temp


def normalize_inline_schema(raw_schema: str) -> str:
    """Accept either full FormulaLM schema text or a compact one-liner like 'A:Item, B:Price'."""
    text = raw_schema.strip()
    if not text:
        raise ValueError("Schema text cannot be empty.")
    if text.lower().startswith("sheet:"):
        return text

    rows_match = re.search(r"\(\s*rows?\s+(\d+)\s*(?:\.\.|-)\s*(\d+)\s*\)", text, re.IGNORECASE)
    row_range = (
        f"rows {rows_match.group(1)}..{rows_match.group(2)}"
        if rows_match
        else "rows 2..100"
    )
    cleaned = re.sub(r"\(\s*rows?\s+\d+\s*(?:\.\.|-)\s*\d+\s*\)", "", text, flags=re.IGNORECASE)

    parts = [p.strip() for p in re.split(r"[,;\n]+", cleaned) if p.strip()]
    col_lines: list[str] = []
    for idx, part in enumerate(parts):
        m = re.match(r"^([A-Za-z]{1,2})\s*:\s*(.+)$", part)
        if m:
            letter = m.group(1).upper()
            rest = m.group(2).strip()
        else:
            letter = get_column_letter(idx + 1)
            rest = part
        if not re.search(r"\([A-Za-z_]+\)\s*$", rest):
            rest = f"{rest} (text)"
        col_lines.append(f"{letter}: {rest}")

    return f"Sheet: Sheet1 ({row_range})\nColumns:\n" + "\n".join(col_lines)


def _json_safe(val: Any) -> Any:
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return val


def run_cli_request(
    request_text: str,
    *,
    file_path: Path | None = None,
    sheet_name: str | None = None,
    schema_text: str | None = None,
    target_cell: str | None = None,
    out_path: Path | None = None,
    allow_overwrite: bool = False,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    verify: bool = True,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    seed: int = DEFAULT_SEED,
    backend: Any | None = None,
) -> dict[str, Any]:
    """Execute one end-to-end FormulaLM CLI request and return a structured result dict."""
    if not file_path and not schema_text:
        raise ValueError("Provide either --file <path.xlsx|.csv> or --schema <columns>.")

    chosen_sheet: str | None = sheet_name
    exec_xlsx: Path | None = None
    is_temp = False

    if file_path is not None:
        resolved_schema, chosen_sheet, exec_xlsx, is_temp = extract_schema_from_file(
            file_path, sheet_name=sheet_name
        )
    else:
        assert schema_text is not None
        resolved_schema = normalize_inline_schema(schema_text)

    normalized_cell: str | None = None
    if target_cell:
        normalized_cell = validate_cell_ref(target_cell)

    try:
        if backend is None:
            safe_host = assert_localhost_url(host)
            backend = OllamaBackend(model=model, base_url=safe_host)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(resolved_schema, request_text.strip())},
        ]
        t0 = time.perf_counter()
        raw_output = backend.generate(messages, max_tokens=max_tokens, seed=seed)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        formula = extract_formula(raw_output)
        result: dict[str, Any] = {
            "ok": False,
            "formula": formula,
            "raw_output": raw_output,
            "syntax_valid": False,
            "verified": False,
            "value": None,
            "sheet": chosen_sheet,
            "target_cell": normalized_cell,
            "out_file": None,
            "model": model,
            "latency_ms": latency_ms,
            "error": None,
        }

        if not formula.startswith("="):
            result["error"] = f"Model did not return an Excel formula (got {raw_output!r})."
            return result

        val_err = validate_formula(formula)
        if val_err is not None:
            result["error"] = f"{val_err[0]}: {val_err[1]}"
            return result
        result["syntax_valid"] = True

        if verify and exec_xlsx is not None:
            exec_res = run_formula(
                formula,
                exec_xlsx,
                target_cell=normalized_cell,
            )
            if not exec_res.ok:
                result["error"] = f"{exec_res.error_type}: {exec_res.error_message}"
                return result
            result["verified"] = True
            result["value"] = _json_safe(exec_res.value)

        if out_path is not None:
            if file_path is None:
                raise ValueError("--out requires --file <path.xlsx|.csv>.")
            tmp_out, written_cell = inject_formula_into_xlsx(
                file_path,
                chosen_sheet,
                formula,
                target_cell=normalized_cell,
                allow_overwrite=allow_overwrite,
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_out), str(out_path))
            result["out_file"] = str(out_path)
            result["target_cell"] = written_cell

        result["ok"] = True
        return result
    finally:
        if is_temp and exec_xlsx is not None:
            exec_xlsx.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="formulalm",
        description="Generate, execution-verify, and inject Excel formulas locally with FormulaLM.",
    )
    p.add_argument("request", help="Plain-English spreadsheet formula request.")
    p.add_argument(
        "-f",
        "--file",
        type=Path,
        default=None,
        help="Input .xlsx or .csv workbook to inspect and execution-verify against.",
    )
    p.add_argument("--sheet", default=None, help="Worksheet name inside --file (default: first).")
    p.add_argument(
        "--schema",
        default=None,
        help=(
            "Inline schema when not passing --file "
            '(e.g. "A:Product, B:Qty, C:Price (rows 2..50)").'
        ),
    )
    p.add_argument(
        "--cell",
        default=None,
        help=(
            "Target cell for circular-ref check & --out injection "
            "(e.g. E2; omit for auto summary row)."
        ),
    )
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Save a formula-injected copy of --file to this .xlsx path.",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting a non-empty --cell when writing --out.",
    )
    p.add_argument(
        "-m",
        "--model",
        default=DEFAULT_MODEL,
        help=f"Local Ollama model name (default: {DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Localhost Ollama URL (default: {DEFAULT_HOST}).",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip local formula execution check (syntax validation still runs).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON to stdout.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        res = run_cli_request(
            args.request,
            file_path=args.file,
            sheet_name=args.sheet,
            schema_text=args.schema,
            target_cell=args.cell,
            out_path=args.out,
            allow_overwrite=args.overwrite,
            model=args.model,
            host=args.host,
            verify=not args.no_verify,
        )
    except Exception as exc:
        if args.as_json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    if not res["ok"]:
        print(f"Formula: {res['formula']}", file=sys.stderr)
        print(f"Error:   {res['error']}", file=sys.stderr)
        return 1

    print(res["formula"])
    meta_parts: list[str] = []
    if res["verified"]:
        meta_parts.append(f"verified value={res['value']!r}")
    else:
        meta_parts.append("syntax valid")
    if res["out_file"]:
        meta_parts.append(f"wrote {res['target_cell']} -> {res['out_file']}")
    meta_parts.append(f"{res['latency_ms']:.0f} ms")
    print(f"# {', '.join(meta_parts)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
