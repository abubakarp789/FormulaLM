"""Run executable evaluation of a system's formulas against a test set.

Placeholder entry point: the evaluator is implemented in a later prompt. Running it now loads
the config, sets up logging and exits with code 2 so `make eval` / `tasks.ps1 eval` fail loudly.
"""

from __future__ import annotations

import argparse
import sys

from formulalm.config import load_config
from formulalm.logging_utils import get_logger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="YAML merged over config/default.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    log = get_logger("formulalm.evaluate", log_file=cfg["paths"]["logs_dir"] / "evaluate.log")
    log.info("config loaded (seed=%s)", cfg["seed"])
    log.error("evaluation is not implemented yet (planned for a later prompt)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
