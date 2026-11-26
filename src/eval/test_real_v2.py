"""Loader and validator for the fresh held-out set (`data/test_real_v2/`).

Workflow:
1. Raw held-out requests live in ``data/test_real_v2/requests.csv`` with columns
   ``sheet_id`` and ``request`` (optional ``id``, ``notes``) — AI-drafted with access
   to the repository (including v1 error analysis), reviewed and approved by Abu Bakar.
2. Validate the raw file without guessing formulas:
       uv run python -m src.eval.test_real_v2 --mode raw data/test_real_v2/requests.csv
3. Annotate into ``data/test_real_v2/test_real_v2.csv`` with ``reference_formula``,
   ``expected_value``, ``expected_type``, ``category``, ``difficulty`` (flagging any
   ambiguous or unanswerable requests instead of guessing).
4. Verify the annotated file against the held-out sheets and executor:
       uv run python -m src.eval.test_real_v2 --mode annotated \
           data/test_real_v2/test_real_v2.csv --fill-expected
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from formulalm.config import REPO_ROOT
from src.eval.run_eval import EvalExample, load_eval_examples
from src.eval.verify_csv import verify_csv

REQUIRED_RAW_COLUMNS: tuple[str, ...] = ("sheet_id", "request")
REQUIRED_ANNOTATED_COLUMNS: tuple[str, ...] = (
    "id",
    "sheet_id",
    "category",
    "difficulty",
    "request",
    "reference_formula",
    "expected_value",
    "expected_type",
)
UNRESOLVED_MARKERS: tuple[str, ...] = ("AMBIGUOUS", "UNANSWERABLE", "TODO", "TBD")


@dataclass(frozen=True)
class RawRequest:
    """One raw held-out request record from ``data/test_real_v2/requests.csv``."""

    id: str
    sheet_id: str
    request: str
    notes: str = ""


def _load_manifest_heldout(manifest_path: str | Path | None = None) -> set[str]:
    mpath = (
        REPO_ROOT / "data" / "sheets" / "manifest.json"
        if manifest_path is None
        else Path(manifest_path)
    )
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    return set(manifest["test_sheet_ids"])


def load_raw_requests(
    csv_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> list[RawRequest]:
    """Load raw ``(sheet_id, request)`` rows from ``requests.csv`` with strict header checks."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Raw requests CSV not found: {path}")

    heldout_ids = _load_manifest_heldout(manifest_path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing = [c for c in REQUIRED_RAW_COLUMNS if c not in fields]
        if missing:
            raise ValueError(f"Missing required column(s) {missing} in {path}")
        records: list[RawRequest] = []
        for idx, row in enumerate(reader, start=1):
            sid = (row.get("sheet_id") or "").strip()
            req = (row.get("request") or "").strip()
            if not sid and not req:
                continue
            rid = (row.get("id") or f"real_v2_{idx:03d}").strip()
            notes = (row.get("notes") or "").strip()
            if sid not in heldout_ids:
                raise ValueError(
                    f"{rid}: sheet_id '{sid}' is not in held-out test_sheet_ids "
                    f"({sorted(heldout_ids)})"
                )
            if not req:
                raise ValueError(f"{rid}: empty request")
            records.append(RawRequest(id=rid, sheet_id=sid, request=req, notes=notes))
    return records


def validate_raw_requests(
    csv_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    v1_real_csv: str | Path | None = None,
) -> dict[str, Any]:
    """Validate ``requests.csv`` without modifying it or guessing formulas."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Raw requests CSV not found: {path}")

    heldout_ids = _load_manifest_heldout(manifest_path)
    v1_path = (
        REPO_ROOT / "data" / "test_real" / "test_real_DRAFT.csv"
        if v1_real_csv is None
        else Path(v1_real_csv)
    )
    v1_requests: set[tuple[str, str]] = set()
    if v1_path.is_file():
        with v1_path.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                v1_requests.add(
                    ((r.get("sheet_id") or "").strip(), (r.get("request") or "").strip().lower())
                )

    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    seen_reqs: set[tuple[str, str]] = set()
    by_sheet: Counter[str] = Counter()
    total_rows = 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        missing = [c for c in REQUIRED_RAW_COLUMNS if c not in fields]
        if missing:
            errors.append(f"Missing required column(s): {missing}")
            return {
                "mode": "raw",
                "file": str(path),
                "total_rows": 0,
                "error_count": len(errors),
                "errors": errors,
                "warnings": warnings,
                "by_sheet": {},
                "missing_heldout_sheets": sorted(heldout_ids),
            }

        for idx, row in enumerate(reader, start=1):
            sid = (row.get("sheet_id") or "").strip()
            req = (row.get("request") or "").strip()
            if not sid and not req:
                continue
            total_rows += 1
            rid = (row.get("id") or f"real_v2_{idx:03d}").strip()
            if rid in seen_ids:
                errors.append(f"{rid}: duplicate id")
            seen_ids.add(rid)

            if sid not in heldout_ids:
                errors.append(
                    f"{rid}: sheet_id '{sid}' is not a held-out test sheet "
                    f"(allowed: {sorted(heldout_ids)})"
                )
            else:
                by_sheet[sid] += 1

            if not req:
                errors.append(f"{rid}: empty request")
                continue

            key = (sid, req.lower())
            if key in seen_reqs:
                errors.append(f"{rid}: duplicate request on '{sid}': {req!r}")
            seen_reqs.add(key)

            if key in v1_requests:
                warnings.append(f"{rid}: exact match with an existing test_real v1 request")

    if total_rows == 0:
        errors.append("CSV contains 0 request rows")
    missing_sheets = sorted(heldout_ids - set(by_sheet))
    if missing_sheets:
        warnings.append(f"Held-out sheet(s) with 0 requests: {missing_sheets}")

    return {
        "mode": "raw",
        "file": str(path),
        "total_rows": total_rows,
        "error_count": len(errors),
        "errors": errors,
        "warnings": warnings,
        "by_sheet": dict(sorted(by_sheet.items())),
        "missing_heldout_sheets": missing_sheets,
    }


def load_annotated_test_real_v2(
    csv_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> tuple[list[EvalExample], dict[str, Path]]:
    """Load an annotated ``test_real_v2.csv`` and enforce held-out sheet & formula checks."""
    heldout_ids = _load_manifest_heldout(manifest_path)
    examples, xlsx_by_sheet = load_eval_examples(csv_path, manifest_path=manifest_path)
    for ex in examples:
        if ex.sheet_id not in heldout_ids:
            raise ValueError(f"{ex.id}: sheet_id '{ex.sheet_id}' is not a held-out test sheet")
        if not ex.reference_formula.startswith("="):
            raise ValueError(
                f"{ex.id}: reference_formula must start with '=' (got {ex.reference_formula!r})"
            )
    return examples, xlsx_by_sheet


def validate_annotated_test_real_v2(
    csv_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    fill_expected: bool = False,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Validate annotated ``test_real_v2.csv`` (schema, no ambiguous markers, executor check)."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Annotated CSV not found: {path}")

    extra_errors: list[str] = []
    flagged_unresolved: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing = [c for c in REQUIRED_ANNOTATED_COLUMNS if c not in fields]
        if missing:
            extra_errors.append(f"Missing required column(s): {missing}")
        for idx, row in enumerate(reader, start=1):
            rid = (row.get("id") or f"real_v2_{idx:03d}").strip()
            notes_up = (row.get("notes") or "").upper()
            fml_up = (row.get("reference_formula") or "").strip().upper()
            if any(m in notes_up or m in fml_up for m in UNRESOLVED_MARKERS):
                flagged_unresolved.append(
                    f"{rid}: flagged as ambiguous/unanswerable ({row.get('notes') or fml_up})"
                )

    report = verify_csv(
        path, manifest_path=manifest_path, fill_expected=fill_expected, timeout=timeout
    )
    all_errors = extra_errors + flagged_unresolved + list(report["errors"])
    report["mode"] = "annotated"
    report["flagged_unresolved"] = flagged_unresolved
    report["errors"] = all_errors
    report["error_count"] = len(all_errors)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to requests.csv (raw) or test_real_v2.csv (annotated)",
    )
    parser.add_argument(
        "--mode",
        choices=("raw", "annotated"),
        default="raw",
        help="'raw' validates (sheet_id, request); 'annotated' runs full executor verification",
    )
    parser.add_argument(
        "--fill-expected",
        action="store_true",
        help="Annotated mode only: populate expected_value & expected_type from executor",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-formula timeout in seconds for annotated mode (default 5.0)",
    )
    args = parser.parse_args(argv)

    default_path = (
        "data/test_real_v2/requests.csv"
        if args.mode == "raw"
        else "data/test_real_v2/test_real_v2.csv"
    )
    target = args.csv_path or default_path

    if args.mode == "raw":
        report = validate_raw_requests(target)
    else:
        report = validate_annotated_test_real_v2(
            target, fill_expected=args.fill_expected, timeout=args.timeout
        )

    print(json.dumps(report, indent=2))
    return 1 if report["error_count"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
