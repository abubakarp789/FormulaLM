"""Deterministically filter & freeze an independent external Excel benchmark.

Source: KAKA22/SpreadsheetBench (`spreadsheetbench_verified_400.tar.gz`,
NeurIPS 2024, CC-BY-SA-4.0, pinned commit ab0b742b0fc95b946f212d80ac7771b5531272e4).

All filter rules are deterministic and model-blind:
1. instruction_type == "Cell-Level Manipulation"
2. answer_position is a single A1 cell or contiguous single-sheet A1:B2 range
   (evaluating the top-left target cell).
3. Target worksheet is the first sheet (sheet_idx == 0) with <= 20 columns.
4. Golden answer cell in `*_golden.xlsx` starts with '=' (formula), has a
   non-null cached value, contains no cross-sheet '!' reference, and uses
   only functions in FormulaLM's 36 ALLOWED_FUNCTIONS.
5. Golden formula passes `src.eval.executor.run_formula` against `*_init.xlsx`
   and matches `*_golden.xlsx`'s cached value (`values_equal`).

Usage:
    uv run python scripts/prepare_external_bench.py \
        --out-dir data/external_bench
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.eval.executor import ALLOWED_FUNCTIONS, run_formula  # noqa: E402
from src.eval.normalize import values_equal  # noqa: E402

HF_DATASET_ID = "KAKA22/SpreadsheetBench"
HF_REVISION = "ab0b742b0fc95b946f212d80ac7771b5531272e4"
ARCHIVE_NAME = "spreadsheetbench_verified_400.tar.gz"
ARCHIVE_URL = (
    f"https://huggingface.co/datasets/{HF_DATASET_ID}/resolve/{HF_REVISION}/{ARCHIVE_NAME}"
)

CELL_RE = re.compile(r"^([A-Z]{1,3}[1-9][0-9]*)(?::([A-Z]{1,3}[1-9][0-9]*))?$")
FUNC_RE = re.compile(r"([A-Z0-9_.]+)\s*\(")
MAX_COLS = 20
MAX_PREVIEW_ROWS = 6
MAX_PREVIEW_CELLS_PER_ROW = 10
MAX_CELL_REPR_LEN = 32


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _infer_col_type(values: list[Any]) -> str:
    non_null = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_null:
        return "text"
    if all(isinstance(v, bool) for v in non_null):
        return "boolean"
    if all(isinstance(v, (date, datetime)) for v in non_null):
        return "date"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "integer"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "decimal"
    return "text"


def _fmt_cell_val(v: Any) -> str:
    if isinstance(v, datetime):
        s = v.strftime("%Y-%m-%d")
    elif isinstance(v, date):
        s = v.isoformat()
    elif isinstance(v, float):
        s = f"{v:g}"
    else:
        s = str(v).replace("\n", " ").replace("\r", " ").strip()
    if len(s) > MAX_CELL_REPR_LEN:
        s = s[: MAX_CELL_REPR_LEN - 3] + "..."
    return s


def format_external_schema(ws: Any, sheet_name: str) -> str:
    """Build a neutral, compact schema + sample-cells block for a real .xlsx worksheet."""
    nrows = int(ws.max_row or 1)
    ncols = min(int(ws.max_column or 1), MAX_COLS)

    # Identify likely header row among rows 1..min(3, nrows)
    best_hdr_row = 1
    best_str_count = -1
    for r in range(1, min(4, nrows + 1)):
        str_cnt = sum(
            1
            for c in range(1, ncols + 1)
            if isinstance(ws.cell(r, c).value, str) and ws.cell(r, c).value.strip()
        )
        if str_cnt > best_str_count:
            best_str_count = str_cnt
            best_hdr_row = r

    data_start = best_hdr_row + 1 if best_str_count >= 2 and nrows > best_hdr_row else 1
    col_lines: list[str] = []
    for c in range(1, ncols + 1):
        letter = get_column_letter(c)
        hdr_val = ws.cell(best_hdr_row, c).value
        sample_vals = [
            ws.cell(r, c).value for r in range(data_start, min(nrows + 1, data_start + 25))
        ]
        if hdr_val is None and all(v is None for v in sample_vals):
            continue
        hdr_str = _fmt_cell_val(hdr_val) if hdr_val is not None else f"Column {letter}"
        col_type = _infer_col_type(sample_vals)
        col_lines.append(f"{letter}: {hdr_str} ({col_type})")

    preview_lines: list[str] = []
    for r in range(1, nrows + 1):
        if len(preview_lines) >= MAX_PREVIEW_ROWS:
            break
        cells = []
        for c in range(1, ncols + 1):
            v = ws.cell(r, c).value
            if v is not None and str(v).strip() != "":
                cells.append(f"{get_column_letter(c)}{r}={_fmt_cell_val(v)}")
                if len(cells) >= MAX_PREVIEW_CELLS_PER_ROW:
                    break
        if cells:
            preview_lines.append(f"Row {r}: " + ", ".join(cells))

    parts = [
        f"Sheet: {sheet_name} (rows {data_start}..{nrows})",
        "Columns:",
        *col_lines,
    ]
    if preview_lines:
        parts.append("Sample cells:")
        parts.extend(preview_lines)
    return "\n".join(parts)


def prepare_benchmark(out_dir: Path, archive_path: Path | None = None) -> dict[str, Any]:
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
    out_dir.mkdir(parents=True, exist_ok=True)
    wb_out_dir = out_dir / "workbooks"
    if wb_out_dir.exists():
        shutil.rmtree(wb_out_dir)
    wb_out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ssb_extract_") as tmp:
        tmp_path = Path(tmp)
        if archive_path is None:
            archive_path = tmp_path / ARCHIVE_NAME
            urllib.request.urlretrieve(ARCHIVE_URL, archive_path)
        archive_sha = sha256_file(archive_path)

        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(tmp_path, filter="data")

        ssb_root = tmp_path / "spreadsheetbench_verified_400"
        raw_items = json.loads((ssb_root / "dataset.json").read_text(encoding="utf-8"))

        rows: list[dict[str, Any]] = []
        skipped_counts: dict[str, int] = {}

        def skip(reason: str) -> None:
            skipped_counts[reason] = skipped_counts.get(reason, 0) + 1

        for d in raw_items:
            if d.get("instruction_type") != "Cell-Level Manipulation":
                skip("sheet_level")
                continue

            pos_raw = str(d.get("answer_position", "")).strip()
            sheet = d.get("answer_sheet")
            if "!" in pos_raw:
                s_part, pos_raw = pos_raw.rsplit("!", 1)
                if not sheet:
                    sheet = s_part.strip().strip("'")
            pos_raw = pos_raw.replace("$", "")
            m = CELL_RE.match(pos_raw)
            if not m:
                skip("non_contiguous_position")
                continue
            first_cell, end_cell = m.group(1), m.group(2)
            task_kind = (
                "single_cell"
                if (end_cell is None or end_cell == first_cell)
                else "col_fill_first_cell"
            )

            tdir = ssb_root / d["spreadsheet_path"]
            gold_files = sorted(tdir.glob("*_golden.xlsx"))
            init_files = sorted(tdir.glob("*_init.xlsx"))
            if not gold_files or not init_files:
                skip("missing_xlsx")
                continue
            gold_path, init_path = gold_files[0], init_files[0]

            try:
                wb_f = openpyxl.load_workbook(gold_path, data_only=False)
                wb_v = openpyxl.load_workbook(gold_path, data_only=True)
                if not sheet:
                    sheet = wb_f.sheetnames[0]
                if sheet not in wb_f.sheetnames:
                    wb_f.close()
                    wb_v.close()
                    skip("missing_sheet")
                    continue
                raw_cell = wb_f[sheet][first_cell].value
                cached_val = wb_v[sheet][first_cell].value
                wb_f.close()
                wb_v.close()
            except Exception:
                skip("xlsx_read_error")
                continue

            if not (isinstance(raw_cell, str) and raw_cell.startswith("=")):
                skip("non_formula_gold")
                continue
            if cached_val is None:
                skip("cached_val_none")
                continue

            clean_f = raw_cell.replace("_xlfn.", "").strip()
            if "!" in clean_f:
                skip("cross_sheet_formula")
                continue
            funcs = {fm.group(1).upper() for fm in FUNC_RE.finditer(clean_f)}
            if not funcs.issubset(ALLOWED_FUNCTIONS):
                skip("out_of_scope_function")
                continue

            wb_i = openpyxl.load_workbook(init_path, data_only=True)
            if sheet not in wb_i.sheetnames or wb_i.sheetnames.index(sheet) != 0:
                wb_i.close()
                skip("non_first_sheet")
                continue
            ws_i = wb_i[sheet]
            nrows, ncols = int(ws_i.max_row or 1), int(ws_i.max_column or 1)
            if ncols > MAX_COLS:
                wb_i.close()
                skip("too_many_cols")
                continue
            schema_text = format_external_schema(ws_i, sheet)
            wb_i.close()

            res = run_formula(clean_f, init_path)
            if not res.ok:
                skip(f"gold_exec_{res.error_type}")
                continue
            if not values_equal(res.value, cached_val):
                skip("gold_value_mismatch")
                continue

            source_id = str(d["id"])
            bench_id = f"ssb_{source_id}"
            dest_wb = wb_out_dir / f"{bench_id}.xlsx"
            shutil.copy2(init_path, dest_wb)

            if isinstance(cached_val, bool):
                exp_type = "bool"
                exp_str = "TRUE" if cached_val else "FALSE"
            elif isinstance(cached_val, (datetime, date)):
                exp_type = "date"
                exp_str = (
                    cached_val.strftime("%Y-%m-%d")
                    if isinstance(cached_val, datetime)
                    else cached_val.isoformat()
                )
            elif isinstance(cached_val, (int, float)):
                exp_type = "number"
                exp_str = (
                    repr(float(cached_val)) if isinstance(cached_val, float) else str(cached_val)
                )
            else:
                exp_type = "string"
                exp_str = str(cached_val)

            instr = " ".join(str(d["instruction"]).split())
            request = f"Write the Excel formula for cell {first_cell}. {instr}"

            rows.append(
                {
                    "id": bench_id,
                    "source_dataset": f"{HF_DATASET_ID}@{HF_REVISION[:8]}",
                    "source_id": source_id,
                    "task_kind": task_kind,
                    "sheet_name": sheet,
                    "target_cell": first_cell,
                    "answer_position": pos_raw,
                    "workbook_path": f"data/external_bench/workbooks/{bench_id}.xlsx",
                    "nrows": nrows,
                    "ncols": ncols,
                    "schema_text": schema_text,
                    "request": request,
                    "reference_formula": clean_f,
                    "expected_value": exp_str,
                    "expected_type": exp_type,
                }
            )

    rows.sort(key=lambda r: r["id"])
    csv_path = out_dir / "external_bench.csv"
    fieldnames = [
        "id",
        "source_dataset",
        "source_id",
        "task_kind",
        "sheet_name",
        "target_cell",
        "answer_position",
        "workbook_path",
        "nrows",
        "ncols",
        "schema_text",
        "request",
        "reference_formula",
        "expected_value",
        "expected_type",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Write deterministic SHA-256 manifest (frozen pre-inference!)
    manifest_lines = [
        f"# Source archive: {ARCHIVE_URL}",
        f"# Source archive SHA-256: {archive_sha}",
        f"{sha256_file(csv_path)}  external_bench.csv",
    ]
    for wb_file in sorted(wb_out_dir.glob("*.xlsx")):
        manifest_lines.append(f"{sha256_file(wb_file)}  workbooks/{wb_file.name}")
    manifest_path = out_dir / "manifest.sha256"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    wb_bytes = sum(p.stat().st_size for p in wb_out_dir.glob("*.xlsx"))
    summary = {
        "source_dataset": HF_DATASET_ID,
        "source_revision": HF_REVISION,
        "archive_name": ARCHIVE_NAME,
        "archive_sha256": archive_sha,
        "total_raw_items": len(raw_items),
        "kept_count": len(rows),
        "single_cell_count": sum(1 for r in rows if r["task_kind"] == "single_cell"),
        "col_fill_count": sum(1 for r in rows if r["task_kind"] == "col_fill_first_cell"),
        "workbooks_total_kb": round(wb_bytes / 1024, 1),
        "csv_sha256": sha256_file(csv_path),
        "manifest_sha256": sha256_file(manifest_path),
        "skipped_counts": dict(sorted(skipped_counts.items())),
    }
    (out_dir / "filter_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("data/external_bench"))
    parser.add_argument("--archive", type=Path, default=None)
    args = parser.parse_args()
    summary = prepare_benchmark(args.out_dir, args.archive)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
