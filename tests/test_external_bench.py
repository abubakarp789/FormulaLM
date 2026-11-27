"""Integrity, leakage, and consistency tests for the frozen external SpreadsheetBench subset."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from scripts.eval_external_bench import parse_expected_value, wilson_ci
from src.eval.executor import run_formula
from src.eval.normalize import values_equal

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT_DIR = REPO_ROOT / "data" / "external_bench"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_external_bench_manifest_sha256_integrity() -> None:
    manifest = EXT_DIR / "manifest.sha256"
    assert manifest.is_file(), "Missing data/external_bench/manifest.sha256"
    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        expected_hash, rel_name = s.split("  ", 1)
        target = EXT_DIR / rel_name
        assert target.is_file(), f"Missing frozen benchmark file: {rel_name}"
        assert _sha256(target) == expected_hash, f"SHA-256 mismatch for {rel_name}"
        checked += 1
    assert checked >= 57  # external_bench.csv + 56 workbooks


def test_external_bench_zero_overlap_with_formula_sheets_and_requests() -> None:
    csv_path = EXT_DIR / "external_bench.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 56

    manifest = json.loads((REPO_ROOT / "data" / "sheets" / "manifest.json").read_text())
    synth_sheets = {s["sheet_id"].lower() for s in manifest["sheets"]}

    for row in rows:
        assert row["sheet_name"].lower() not in synth_sheets
        assert (REPO_ROOT / row["workbook_path"]).is_file()
        assert row["reference_formula"].startswith("=")
        assert "!" not in row["reference_formula"]


def test_external_bench_sample_gold_formulas_execute_cleanly() -> None:
    csv_path = EXT_DIR / "external_bench.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    # Spot-check 5 diverse rows deterministically so CI stays fast (< 2 s)
    for row in rows[::11]:
        wb_path = REPO_ROOT / row["workbook_path"]
        res = run_formula(row["reference_formula"], wb_path)
        assert res.ok, f"Gold formula failed on {row['id']}: {res.error_message}"
        exp = parse_expected_value(row["expected_value"], row["expected_type"])
        assert values_equal(res.value, exp), f"Mismatch on {row['id']}: {res.value!r} != {exp!r}"


def test_wilson_ci_bounds() -> None:
    lo, hi = wilson_ci(28, 56)
    assert 0.35 < lo < 0.5 < hi < 0.65


def test_external_bench_saved_results_consistency() -> None:
    res_root = REPO_ROOT / "results" / "external_bench"
    comp_md = (res_root / "comparison.md").read_text(encoding="utf-8")
    comp_json = json.loads((res_root / "comparison.json").read_text(encoding="utf-8"))
    for run_name in (
        "ext_base_1_7b_0shot",
        "ext_base_1_7b_5shot",
        "ext_base_4b_0shot",
        "ext_formulalm_q5_k_m",
    ):
        m = json.loads((res_root / run_name / "metrics.json").read_text(encoding="utf-8"))
        assert m["overall"]["n"] == 56
        assert comp_json["systems"][run_name]["overall"]["k"] == m["overall"]["k"]
        assert f"{m['overall']['k']}/56" in comp_md
