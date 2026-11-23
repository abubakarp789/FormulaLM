"""Unit tests for QLoRA training config, script helpers and training notebook."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from formulalm.config import REPO_ROOT
from scripts.train_qlora import (
    NON_THINKING_PREFIX,
    build_parser,
    configure_qwen3_non_thinking,
    default_output_dir,
    find_latest_checkpoint,
    load_train_config,
    write_loss_csv,
)


def test_train_qlora_config_matches_brief_and_data_stats():
    cfg = load_train_config()
    assert cfg["seed"] == 42
    assert cfg["model"]["base_id"] == "Qwen/Qwen3-1.7B"
    assert cfg["model"]["load_in_4bit"] is True
    assert cfg["model"]["enable_thinking"] is False
    assert cfg["model"]["max_seq_length"] == 512

    assert cfg["lora"]["r"] == 16
    assert cfg["lora"]["lora_alpha"] in (16, 32)
    assert cfg["lora"]["lora_dropout"] == 0.0
    assert set(cfg["lora"]["target_modules"]) == {
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    }

    tcfg = cfg["training"]
    assert 2 <= tcfg["num_train_epochs"] <= 3
    assert tcfg["learning_rate"] == pytest.approx(2e-4)
    assert tcfg["lr_scheduler_type"] == "cosine"
    assert tcfg["warmup_ratio"] > 0
    assert tcfg["eval_steps"] > 0 and tcfg["save_steps"] > 0
    assert cfg["smoke_test"]["train_examples"] == 200


def test_configure_qwen3_non_thinking_is_idempotent_and_validates():
    tok = SimpleNamespace(chat_template="{% if enable_thinking %}...{% endif %}")
    configure_qwen3_non_thinking(tok)
    assert tok.chat_template.startswith(NON_THINKING_PREFIX)
    once = tok.chat_template
    configure_qwen3_non_thinking(tok)
    assert tok.chat_template == once

    bad_tok = SimpleNamespace(chat_template="{{ messages }}")
    with pytest.raises(ValueError):
        configure_qwen3_non_thinking(bad_tok)


def test_find_latest_checkpoint_orders_numerically(tmp_path: Path):
    assert find_latest_checkpoint(tmp_path / "missing") is None
    for name in ("checkpoint-20", "checkpoint-100", "checkpoint-1000", "not-a-ckpt"):
        (tmp_path / name).mkdir()
    latest = find_latest_checkpoint(tmp_path)
    assert latest is not None and latest.name == "checkpoint-1000"


def test_write_loss_csv_outputs_train_and_eval_rows(tmp_path: Path):
    history = [
        {"step": 20, "epoch": 0.04, "loss": 1.234567, "learning_rate": 1e-4, "grad_norm": 0.42},
        {"step": 100, "epoch": 0.2, "eval_loss": 0.54321},
        {"step": 100, "epoch": 0.2, "train_runtime": 12.3},  # summary row without loss -> skipped
    ]
    out = write_loss_csv(history, tmp_path / "loss_log.csv")
    with out.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["step"] == "20" and rows[0]["train_loss"] == "1.234567"
    assert rows[1]["step"] == "100" and rows[1]["eval_loss"] == "0.54321"


def test_cli_parser_and_default_output_dirs():
    args = build_parser().parse_args(["--smoke", "--resume", "auto", "--epochs", "3"])
    assert args.smoke is True
    assert args.resume == "auto"
    assert args.epochs == 3.0
    assert "kaggle" in str(default_output_dir("qlora_v1", env_name="kaggle")).lower()


def test_train_qlora_notebook_is_valid_and_has_required_sections():
    nb_path = REPO_ROOT / "notebooks" / "train_qlora.ipynb"
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    full_text = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "train_qlora.py" in full_text
    assert "--smoke" in full_text
    assert "--resume auto" in full_text
    assert "Kaggle" in full_text
    assert "train_on_responses_only" in full_text
    assert "loss_log.csv" in full_text
