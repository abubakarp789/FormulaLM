"""Tests for synthetic dataset builder: schema, chat format, execution and leakage checks."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from formulalm.config import REPO_ROOT
from src.data.build_dataset import (
    SYSTEM_PROMPT,
    assign_phrasing_splits,
    build_dataset,
)
from src.data.templates import TEMPLATES
from src.eval.executor import run_formula
from src.eval.normalize import values_equal

REQUIRED_RECORD_KEYS = {
    "id",
    "template_id",
    "category",
    "difficulty",
    "sheet_id",
    "schema_text",
    "request",
    "formula",
    "expected_value",
    "messages",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _assert_zero_leakage_and_valid_records(
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
    manifest_train_ids: set[str],
    manifest_test_ids: set[str],
) -> None:
    all_splits = {"train": train, "val": val, "test": test}
    seen_ids: set[str] = set()
    prompts_by_split: dict[str, set[str]] = {}
    phrasings_by_split: dict[str, set[tuple[str, int]]] = {}

    for split_name, rows in all_splits.items():
        assert len(rows) > 0, f"{split_name} split is empty"
        prompts: set[str] = set()
        phrasings: set[tuple[str, int]] = set()

        for rec in rows:
            assert REQUIRED_RECORD_KEYS.issubset(rec.keys())
            assert rec["id"] not in seen_ids, f"duplicate record id {rec['id']}"
            seen_ids.add(rec["id"])

            # Check chat messages format.
            msgs = rec["messages"]
            assert len(msgs) == 3
            assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
            assert msgs[0]["content"] == SYSTEM_PROMPT
            assert rec["schema_text"] in msgs[1]["content"]
            assert rec["request"] in msgs[1]["content"]
            assert msgs[2]["content"] == rec["formula"]
            assert rec["formula"].startswith("=")
            assert "```" not in rec["formula"] and "\n" not in rec["formula"]

            # No duplicate user prompts within a split.
            p_key = msgs[1]["content"].strip().lower()
            assert p_key not in prompts, f"duplicate prompt inside {split_name}"
            prompts.add(p_key)

            # Track phrasing pair (template_id, phrasing_idx).
            phrasings.add((rec["template_id"], int(rec["phrasing_idx"])))

            # Check sheet split assignment.
            if split_name == "test":
                assert rec["sheet_id"] in manifest_test_ids
                assert rec["augmentation"] == "none"
            else:
                assert rec["sheet_id"] in manifest_train_ids
                if split_name == "val":
                    assert rec["augmentation"] == "none"

        prompts_by_split[split_name] = prompts
        phrasings_by_split[split_name] = phrasings

    # Zero prompt overlap across splits.
    assert prompts_by_split["train"].isdisjoint(prompts_by_split["val"])
    assert prompts_by_split["train"].isdisjoint(prompts_by_split["test"])
    assert prompts_by_split["val"].isdisjoint(prompts_by_split["test"])

    # Zero shared (template_id, phrasing_idx) across splits.
    assert phrasings_by_split["train"].isdisjoint(phrasings_by_split["val"])
    assert phrasings_by_split["train"].isdisjoint(phrasings_by_split["test"])
    assert phrasings_by_split["val"].isdisjoint(phrasings_by_split["test"])


def test_phrasing_splits_reserve_two_for_test_and_disjoint():
    plan = assign_phrasing_splits(TEMPLATES, seed=42, reserved_test=2, reserved_val=1)
    assert set(plan) == {t.id for t in TEMPLATES}
    for tpl in TEMPLATES:
        tr = set(plan[tpl.id]["train"])
        va = set(plan[tpl.id]["val"])
        te = set(plan[tpl.id]["test"])
        assert len(te) == 2
        assert len(va) == 1
        assert len(tr) >= 2
        assert tr.isdisjoint(va) and tr.isdisjoint(te) and va.isdisjoint(te)
        assert tr | va | te == set(range(len(tpl.phrasings)))


def test_mini_build_end_to_end_leakage_and_determinism(tmp_path: Path):
    manifest = json.loads((REPO_ROOT / "data" / "sheets" / "manifest.json").read_text("utf-8"))
    train_ids = set(manifest["train_sheet_ids"])
    test_ids = set(manifest["test_sheet_ids"])

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    sum_a = build_dataset(out_a, seed=42, n_train=180, n_val=60, n_test=60, workers=1)
    sum_b = build_dataset(out_b, seed=42, n_train=180, n_val=60, n_test=60, workers=1)

    assert sum_a["total_dropped"] == 0
    for key in ("train", "val", "test"):
        assert sum_a["splits"][key]["sha256"] == sum_b["splits"][key]["sha256"]

    train = _read_jsonl(out_a / "train.jsonl")
    val = _read_jsonl(out_a / "val.jsonl")
    test = _read_jsonl(out_a / "test_synthetic.jsonl")

    assert len(train) == 180
    assert len(val) == 60
    assert len(test) == 60
    _assert_zero_leakage_and_valid_records(train, val, test, train_ids, test_ids)

    # Confirm augmentation was actually exercised and logged in train.
    assert any(r["augmentation"].startswith("rule:") for r in train)


def test_processed_dataset_leakage_balance_and_spot_execution():
    proc = REPO_ROOT / "data" / "processed"
    train_p = proc / "train.jsonl"
    val_p = proc / "val.jsonl"
    test_p = proc / "test_synthetic.jsonl"
    stats_p = proc / "stats.json"

    assert stats_p.exists(), "Run `uv run python -m src.data.build_dataset` first"
    if not (train_p.exists() and val_p.exists() and test_p.exists()):
        # Allow fresh clones where large JSONL files are regenerated via `make data`.
        return

    manifest = json.loads((REPO_ROOT / "data" / "sheets" / "manifest.json").read_text("utf-8"))
    train_ids = set(manifest["train_sheet_ids"])
    test_ids = set(manifest["test_sheet_ids"])
    sheet_xlsx = {s["sheet_id"]: REPO_ROOT / s["xlsx_path"] for s in manifest["sheets"]}

    train = _read_jsonl(train_p)
    val = _read_jsonl(val_p)
    test = _read_jsonl(test_p)

    assert 7500 <= len(train) <= 8500
    assert 450 <= len(val) <= 550
    assert 450 <= len(test) <= 550
    _assert_zero_leakage_and_valid_records(train, val, test, train_ids, test_ids)

    # Spot-check 30 random records across all 3 splits directly through the executor.
    rng = random.Random(7)
    sample = rng.sample(train, 10) + rng.sample(val, 10) + rng.sample(test, 10)
    for rec in sample:
        res = run_formula(rec["formula"], sheet_xlsx[rec["sheet_id"]])
        assert res.ok, f"{rec['id']} failed: {res.error_type}: {res.error_message}"
        exp = rec["expected_value"]
        if rec["expected_type"] == "date":
            from datetime import date

            exp = date.fromisoformat(exp)
        assert values_equal(res.value, exp), f"{rec['id']}: {res.value!r} != {exp!r}"
