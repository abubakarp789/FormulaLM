"""Verify a hand-written real-world CSV against the held-out sheets.

Checks that:
- Every ``sheet_id`` is in ``manifest.json`` ``test_sheet_ids`` (zero train-sheet leakage).
- Every ``reference_formula`` executes without error via ``src.eval.executor.run_formula``.
- ``expected_value`` matches the executed value (or populates ``expected_value`` / ``expected_type``
  when ``--fill-expected`` is passed).

Usage (e.g., to self-verify your fresh held-out test_real_v2.csv locally):
    uv run python -m src.eval.verify_csv data/test_real_v2/test_real_v2.csv --fill-expected
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from formulalm.config import REPO_ROOT
from src.eval.executor import run_formula
from src.eval.normalize import values_equal
from src.eval.run_eval import _parse_expected


def verify_csv(
    csv_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    fill_expected: bool = False,
    timeout: float = 5.0,
) -> dict[str, Any]:
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")

    mpath = (
        REPO_ROOT / "data" / "sheets" / "manifest.json"
        if manifest_path is None
        else Path(manifest_path)
    )
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    heldout_ids = set(manifest["test_sheet_ids"])
    xlsx_by_sheet = {s["sheet_id"]: REPO_ROOT / s["xlsx_path"] for s in manifest["sheets"]}

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    errors: list[str] = []
    seen_reqs: set[tuple[str, str]] = set()
    updated_rows: list[dict[str, str]] = []

    for idx, row in enumerate(rows, start=1):
        rid = (row.get("id") or f"row_{idx:03d}").strip()
        sid = (row.get("sheet_id") or "").strip()
        req = (row.get("request") or "").strip()
        fml = (row.get("reference_formula") or "").strip()

        if sid not in heldout_ids:
            errors.append(f"{rid}: sheet_id '{sid}' is not a held-out test sheet")
            continue
        if not req:
            errors.append(f"{rid}: empty request")
            continue
        req_key = (sid, req.lower())
        if req_key in seen_reqs:
            errors.append(f"{rid}: duplicate request on {sid}")
        seen_reqs.add(req_key)

        res = run_formula(fml, xlsx_by_sheet[sid], timeout=timeout)
        if not res.ok:
            errors.append(f"{rid}: formula failed ({res.error_type}: {res.error_message}) -> {fml}")
            continue

        val = res.value
        val_type = res.value_type or "text"
        if fml.upper().startswith("=DATE(") and isinstance(val, int | float):
            d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(val))
            val_str = d.isoformat()
            val_type = "date"
        elif isinstance(val, bool):
            val_str = "TRUE" if val else "FALSE"
        elif val is None:
            val_str = ""
        else:
            val_str = str(val)

        if fill_expected:
            row["expected_value"] = val_str
            if "expected_type" in fieldnames:
                row["expected_type"] = val_type
        else:
            exp_raw = row.get("expected_value", "")
            exp_type = (row.get("expected_type") or val_type).strip()
            exp_native = _parse_expected(exp_raw, exp_type)
            if not values_equal(res.value, exp_native):
                errors.append(
                    f"{rid}: expected_value={exp_native!r} != executed={res.value!r} ({fml})"
                )
        updated_rows.append(row)

    if fill_expected and not errors and fieldnames:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(updated_rows)

    return {
        "file": str(path),
        "total_rows": len(rows),
        "error_count": len(errors),
        "errors": errors,
        "by_sheet": dict(Counter((r.get("sheet_id") or "").strip() for r in rows)),
        "by_category": dict(Counter((r.get("category") or "unknown").strip() for r in rows)),
        "by_difficulty": dict(Counter((r.get("difficulty") or "0").strip() for r in rows)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to real-world test CSV")
    parser.add_argument(
        "--fill-expected",
        action="store_true",
        help="Populate/refresh expected_value & expected_type from executor",
    )
    args = parser.parse_args(argv)

    report = verify_csv(args.csv_path, fill_expected=args.fill_expected)
    print(json.dumps(report, indent=2))
    return 1 if report["error_count"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
