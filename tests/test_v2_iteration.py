"""Tests for v2 dataset iteration, frozen val/test parity, v2 config and blind CSV verifier."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from formulalm.config import REPO_ROOT
from scripts.train_qlora import load_train_config
from src.data.build_dataset import build_dataset
from src.data.templates import TEMPLATES, get_template_by_id, load_sheet_contexts
from src.data.v2_augmentations import V2_TRAIN_EXTRA_PHRASINGS, V2_TRAIN_ONLY_TEMPLATES
from src.eval.executor import ALLOWED_FUNCTIONS, run_formula
from src.eval.normalize import values_equal
from src.eval.verify_csv import verify_csv


def test_v2_extra_phrasings_render_cleanly_for_every_template():
    train_sheets = load_sheet_contexts(split="train")
    rng = random.Random(42)
    for tid, extra_patterns in V2_TRAIN_EXTRA_PHRASINGS.items():
        tpl = get_template_by_id(tid)
        matching = [s for s in train_sheets if tpl.matches_sheet(s)]
        assert matching, f"No train sheet matches {tid}"
        built = tpl.instantiate(matching[0], rng)
        for pat in extra_patterns:
            rendered = pat.format(**built.slots)
            assert rendered.strip()
            assert "{" not in rendered and "}" not in rendered


@pytest.mark.parametrize(
    "tpl", V2_TRAIN_ONLY_TEMPLATES, ids=[t.id for t in V2_TRAIN_ONLY_TEMPLATES]
)
def test_v2_new_templates_match_pandas_gt_on_three_train_sheets(tpl):
    train_sheets = [s for s in load_sheet_contexts(split="train") if tpl.matches_sheet(s)]
    assert len(train_sheets) >= 3
    assert set(tpl.functions).issubset(ALLOWED_FUNCTIONS)
    rng = random.Random(101)
    for ctx in rng.sample(train_sheets, k=3):
        built = tpl.instantiate(ctx, rng)
        res = run_formula(built.formula, ctx.xlsx_path)
        assert res.ok, f"{tpl.id} failed on {ctx.sheet_id}: {res.error_message}"
        assert values_equal(res.value, built.expected)


def test_v2_build_preserves_frozen_val_and_test_and_has_zero_leakage(tmp_path: Path):
    s1 = build_dataset(tmp_path / "v1", seed=42, n_train=120, n_val=60, n_test=60, version="v1")
    s2 = build_dataset(tmp_path / "v2", seed=42, n_train=150, n_val=60, n_test=60, version="v2")

    # Val and synthetic test must remain bit-for-bit identical across v1 and v2.
    assert s1["splits"]["val"]["sha256"] == s2["splits"]["val"]["sha256"]
    assert s1["splits"]["test"]["sha256"] == s2["splits"]["test"]["sha256"]
    assert s2["total_dropped"] == 0

    manifest = json.loads((REPO_ROOT / "data" / "sheets" / "manifest.json").read_text("utf-8"))
    train_ids = set(manifest["train_sheet_ids"])

    val_rows = [
        json.loads(line)
        for line in (tmp_path / "v2" / "val.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    test_rows = [
        json.loads(line)
        for line in (tmp_path / "v2" / "test_synthetic.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    train_v2_rows = [
        json.loads(line)
        for line in (tmp_path / "v2" / "train_v2.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]

    val_prompts = {r["messages"][1]["content"].strip().lower() for r in val_rows}
    test_prompts = {r["messages"][1]["content"].strip().lower() for r in test_rows}
    train_prompts = {r["messages"][1]["content"].strip().lower() for r in train_v2_rows}

    assert len(train_prompts) == len(train_v2_rows)
    assert train_prompts.isdisjoint(val_prompts)
    assert train_prompts.isdisjoint(test_prompts)
    assert all(r["sheet_id"] in train_ids for r in train_v2_rows)
    assert any("v2_extra" in r["augmentation"] for r in train_v2_rows)
    assert any(r["template_id"].startswith("v2_") for r in train_v2_rows)

    # Confirm reserved val/test phrasing indices never appear in train_v2.
    reserved = {(r["template_id"], r["phrasing_idx"]) for r in val_rows + test_rows}
    train_pairs = {
        (r["template_id"], r["phrasing_idx"]) for r in train_v2_rows if r["phrasing_idx"] >= 0
    }
    assert train_pairs.isdisjoint(reserved)


def test_committed_v2_stats_match_v1_val_and_test_hashes():
    s1 = json.loads((REPO_ROOT / "data" / "processed" / "stats.json").read_text("utf-8"))
    s2 = json.loads((REPO_ROOT / "data" / "processed" / "stats_v2.json").read_text("utf-8"))
    assert s2["version"] == "v2"
    assert s2["total_dropped"] == 0
    assert s2["splits"]["train"]["count"] == 9000
    assert s2["splits"]["val"]["sha256"] == s1["splits"]["val"]["sha256"]
    assert s2["splits"]["test"]["sha256"] == s1["splits"]["test"]["sha256"]
    assert len(TEMPLATES) == 60


def test_v2_config_notebooks_and_blind_test_placeholder():
    cfg = load_train_config(REPO_ROOT / "config" / "train_qlora_v2.yaml")
    assert cfg["run_name"] == "qlora_v2"
    assert cfg["training"]["num_train_epochs"] == 1
    assert cfg["training"]["learning_rate"] == pytest.approx(1e-4)
    assert cfg["training"]["weight_decay"] == pytest.approx(0.05)
    assert cfg["training"]["eval_steps"] == 50
    assert cfg["data"]["train_file"] == "data/processed/train_v2.jsonl"
    assert cfg["data"]["val_file"] == "data/processed/val.jsonl"

    assert (REPO_ROOT / "data" / "test_real_v2" / "README.md").is_file()
    assert (REPO_ROOT / "data" / "test_real_v2" / "test_real_v2_TEMPLATE.csv").is_file()
    assert (REPO_ROOT / "docs" / "v2_changelog.md").is_file()

    # Verify the CSV verifier works cleanly on test_real_DRAFT.csv.
    rep = verify_csv(REPO_ROOT / "data" / "test_real" / "test_real_DRAFT.csv")
    assert rep["total_rows"] == 80 and rep["error_count"] == 0

    for nb_name in ("train_qlora.ipynb", "03_eval_ft_v2.ipynb"):
        nb = json.loads((REPO_ROOT / "notebooks" / nb_name).read_text("utf-8"))
        assert nb["nbformat"] == 4
