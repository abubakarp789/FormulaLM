import json
import random
from pathlib import Path

import pytest

from formulalm.config import REPO_ROOT, load_config, save_run_config, set_seed


def test_default_config_loads_with_expected_keys():
    cfg = load_config()
    assert isinstance(cfg["seed"], int)
    assert cfg["model"]["base_id"] == "Qwen/Qwen3-1.7B"
    assert cfg["model"]["enable_thinking"] is False
    for key in ("train", "valid", "test_synthetic", "test_handwritten"):
        assert cfg["splits"][key] > 0


def test_paths_are_absolute_and_inside_repo():
    cfg = load_config()
    for path in cfg["paths"].values():
        assert isinstance(path, Path) and path.is_absolute()
        assert path.is_relative_to(REPO_ROOT)


def test_overrides_and_experiment_file_merge(tmp_path):
    exp = tmp_path / "exp.yaml"
    exp.write_text("splits:\n  train: 123\n", encoding="utf-8")
    cfg = load_config(exp, overrides={"seed": 7})
    assert cfg["splits"]["train"] == 123
    assert cfg["splits"]["valid"] == load_config()["splits"]["valid"]  # untouched keys kept
    assert cfg["seed"] == 7


def test_non_integer_seed_rejected():
    with pytest.raises(ValueError):
        load_config(overrides={"seed": "42"})


def test_set_seed_is_reproducible():
    set_seed(123)
    a = [random.random() for _ in range(5)]
    set_seed(123)
    b = [random.random() for _ in range(5)]
    assert a == b


def test_save_run_config_writes_serializable_snapshot(tmp_path):
    target = save_run_config(load_config(), tmp_path / "run")
    snap = json.loads(target.read_text(encoding="utf-8"))
    assert snap["config"]["paths"]["results_dir"] == "results"
    assert "python" in snap and "created_utc" in snap
