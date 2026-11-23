"""Tests for synthetic spreadsheet generation (src/data/sheets.py)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pandas as pd

from formulalm.config import REPO_ROOT
from src.data.sheets import (
    assign_splits,
    build_sheet_specs,
    generate_all_sheets,
)

REQUIRED_DOMAINS = {
    "sales",
    "hr_employees",
    "inventory",
    "student_grades",
    "expenses",
    "orders",
    "project_tracking",
    "attendance",
}

VALID_TYPES = {"text", "integer", "decimal", "date", "category"}


def test_sheet_specs_cover_domains_and_constraints():
    specs = build_sheet_specs()
    assert 20 <= len(specs) <= 30

    domains = {s.domain for s in specs}
    assert REQUIRED_DOMAINS.issubset(domains)

    ids = [s.sheet_id for s in specs]
    assert len(ids) == len(set(ids)), "duplicate sheet_id found"

    has_spaced_header = False
    types_seen: set[str] = set()
    for spec in specs:
        assert 5 <= len(spec.columns) <= 8, f"{spec.sheet_id} col count out of range"
        col_names = [c.name for c in spec.columns]
        assert len(col_names) == len(set(col_names)), f"duplicate header in {spec.sheet_id}"
        assert spec.columns[spec.key_column_index].unique is True
        assert spec.columns[spec.key_column_index].nullable is False
        for col in spec.columns:
            assert col.col_type in VALID_TYPES
            types_seen.add(col.col_type)
            if " " in col.name:
                has_spaced_header = True

    assert has_spaced_header
    assert types_seen == VALID_TYPES


def test_assign_splits_holds_out_about_twenty_percent_disjointly():
    specs = build_sheet_specs()
    splits = assign_splits(specs, heldout_fraction=0.2, seed=42)
    assert set(splits) == {s.sheet_id for s in specs}

    test_ids = {sid for sid, sp in splits.items() if sp == "test"}
    train_ids = {sid for sid, sp in splits.items() if sp == "train"}
    assert train_ids.isdisjoint(test_ids)
    assert len(test_ids) == round(len(specs) * 0.2)

    # Test sheets should come from distinct domains for stronger schema generalization checks.
    spec_by_id = {s.sheet_id: s for s in specs}
    test_domains = [spec_by_id[sid].domain for sid in test_ids]
    assert len(test_domains) == len(set(test_domains))


def test_generate_all_sheets_csv_xlsx_parity_and_blanks(tmp_path):
    manifest = generate_all_sheets(tmp_path, seed=42, min_rows=30, max_rows=200)
    assert 20 <= manifest["num_sheets"] <= 30
    assert manifest["train_sheets"] + manifest["test_sheets"] == manifest["num_sheets"]
    assert set(manifest["train_sheet_ids"]).isdisjoint(manifest["test_sheet_ids"])

    for entry in manifest["sheets"]:
        sid = entry["sheet_id"]
        assert 30 <= entry["num_rows"] <= 200
        assert 5 <= entry["num_cols"] <= 8
        assert entry["blank_cells"] >= 2, f"{sid} expected blank cells"

        csv_path = tmp_path / f"{sid}.csv"
        xlsx_path = tmp_path / f"{sid}.xlsx"
        assert csv_path.exists()
        assert xlsx_path.exists()

        df = pd.read_csv(csv_path, keep_default_na=True)
        assert len(df) == entry["num_rows"]
        assert list(df.columns) == [c["name"] for c in entry["columns"]]

        expected_letters = [chr(ord("A") + i) for i in range(entry["num_cols"])]
        assert [c["letter"] for c in entry["columns"]] == expected_letters

        # Key column has no blanks and all unique values.
        key_col_name = entry["columns"][0]["name"]
        assert df[key_col_name].isna().sum() == 0
        assert df[key_col_name].nunique() == entry["num_rows"]

        # Verify XLSX matches CSV headers, row count, types and blanks.
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        assert ws.title == "Sheet1"
        assert ws.max_row == entry["num_rows"] + 1
        assert ws.max_column == entry["num_cols"]

        xlsx_headers = [ws.cell(1, c).value for c in range(1, entry["num_cols"] + 1)]
        assert xlsx_headers == list(df.columns)

        xlsx_blanks = 0
        for r_idx in range(entry["num_rows"]):
            for c_idx, col_meta in enumerate(entry["columns"]):
                xl_val = ws.cell(r_idx + 2, c_idx + 1).value
                csv_val = df.iloc[r_idx, c_idx]
                if xl_val is None:
                    xlsx_blanks += 1
                    assert pd.isna(csv_val), f"{sid} R{r_idx + 2}C{c_idx + 1} blank mismatch"
                else:
                    assert not pd.isna(csv_val), (
                        f"{sid} R{r_idx + 2}C{c_idx + 1} non-blank mismatch"
                    )
                    if col_meta["type"] == "date":
                        assert isinstance(xl_val, date | datetime)
                        xl_iso = (
                            xl_val.date().isoformat()
                            if isinstance(xl_val, datetime)
                            else xl_val.isoformat()
                        )
                        assert xl_iso == str(csv_val)
                    elif col_meta["type"] == "integer":
                        assert int(xl_val) == int(csv_val)
                    elif col_meta["type"] == "decimal":
                        assert abs(float(xl_val) - float(csv_val)) < 1e-6
                    else:
                        assert str(xl_val) == str(csv_val)

        assert xlsx_blanks == entry["blank_cells"]
        assert int(df.isna().sum().sum()) == entry["blank_cells"]
        wb.close()


def test_generation_is_deterministic_for_fixed_seed(tmp_path):
    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"
    dir_c = tmp_path / "run_c"

    man_a = generate_all_sheets(dir_a, seed=42)
    man_b = generate_all_sheets(dir_b, seed=42)
    man_c = generate_all_sheets(dir_c, seed=99)

    hashes_a = {s["sheet_id"]: s["csv_sha256"] for s in man_a["sheets"]}
    hashes_b = {s["sheet_id"]: s["csv_sha256"] for s in man_b["sheets"]}
    hashes_c = {s["sheet_id"]: s["csv_sha256"] for s in man_c["sheets"]}

    assert hashes_a == hashes_b
    assert man_a["test_sheet_ids"] == man_b["test_sheet_ids"]
    assert hashes_a != hashes_c


def test_committed_data_sheets_manifest_is_valid():
    manifest_path = REPO_ROOT / "data" / "sheets" / "manifest.json"
    assert manifest_path.exists(), "Run `uv run python -m src.data.sheets` to generate sheets"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["seed"] == 42
    assert manifest["num_sheets"] == 25
    assert manifest["train_sheets"] == 20
    assert manifest["test_sheets"] == 5
    for entry in manifest["sheets"]:
        assert Path(REPO_ROOT / entry["csv_path"]).exists()
        assert Path(REPO_ROOT / entry["xlsx_path"]).exists()
