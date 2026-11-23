"""Small logging helper: consistent console format plus an optional log file.

Usage:
    from formulalm.logging_utils import get_logger
    log = get_logger(__name__, log_file="logs/generate.log")
    log.info("generated %d examples", n)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def get_logger(
    name: str = "formulalm", level: int | str = logging.INFO, log_file: str | Path | None = None
) -> logging.Logger:
    """Return a configured logger. Safe to call repeatedly (no duplicate handlers)."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    if not any(getattr(h, "_formulalm_console", False) for h in logger.handlers):
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console._formulalm_console = True  # type: ignore[attr-defined]
        logger.addHandler(console)

    if log_file is not None:
        path = Path(log_file).resolve()
        already = any(
            isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path
            for h in logger.handlers
        )
        if not already:
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(path, encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
    return logger
