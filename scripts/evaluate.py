"""Run executable evaluation against a model backend and dataset."""

from __future__ import annotations

import sys

from src.eval.run_eval import main as run_eval_main

if __name__ == "__main__":
    sys.exit(run_eval_main())
