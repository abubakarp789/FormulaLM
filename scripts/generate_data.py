"""Generate the synthetic FormulaLM dataset.

Placeholder entry point: the generator is implemented in PROMPT 2. Running it now loads the
config, sets up logging and exits with code 2 so `make data` / `tasks.ps1 data` fail loudly
instead of silently producing nothing.
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
    log = get_logger("formulalm.generate", log_file=cfg["paths"]["logs_dir"] / "generate.log")
    log.info("config loaded (seed=%s)", cfg["seed"])
    log.error("data generation is not implemented yet (planned for PROMPT 2)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
