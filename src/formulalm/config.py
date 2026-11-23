"""Configuration loading, seeding and run-config snapshots.

Usage:
    cfg = load_config()                       # config/default.yaml
    cfg = load_config("config/exp.yaml", overrides={"seed": 7})
    set_seed(cfg["seed"])
    save_run_config(cfg, cfg["paths"]["results_dir"] / "my_run")
"""

from __future__ import annotations

import copy
import json
import os
import platform
import random
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "default.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(
    path: str | Path | None = None, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Load a YAML config, apply optional overrides and resolve ``paths`` to absolute Paths.

    If ``path`` is not the default config, it is merged on top of ``config/default.yaml``
    so experiment configs only need to list what they change.
    """
    with DEFAULT_CONFIG.open(encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    if path is not None and Path(path).resolve() != DEFAULT_CONFIG:
        with Path(path).open(encoding="utf-8") as f:
            cfg = _deep_merge(cfg, yaml.safe_load(f) or {})
    if overrides:
        cfg = _deep_merge(cfg, overrides)

    if not isinstance(cfg.get("seed"), int):
        raise ValueError("config 'seed' must be an integer")
    cfg["paths"] = {k: (REPO_ROOT / v).resolve() for k, v in cfg.get("paths", {}).items()}
    return cfg


def set_seed(seed: int) -> None:
    """Seed Python's and NumPy's RNGs (and torch if it is installed)."""
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:  # pragma: no cover - numpy is a pandas dependency
        pass
    try:
        import torch  # type: ignore[import-not-found]

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def to_serializable(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON/YAML-safe copy (Paths become repo-relative POSIX strings)."""

    def conv(v: Any) -> Any:
        if isinstance(v, Path):
            try:
                return v.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                return v.as_posix()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [conv(x) for x in v]
        return v

    return conv(cfg)


def save_run_config(cfg: dict[str, Any], out_dir: str | Path) -> Path:
    """Write ``run_config.json`` (config + git commit + environment) into ``out_dir``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "config": to_serializable(cfg),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    target = out / "run_config.json"
    target.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return target
