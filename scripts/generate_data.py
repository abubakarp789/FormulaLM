"""Generate the full synthetic FormulaLM dataset (sheets + verified JSONL splits)."""

from __future__ import annotations

import sys

from src.data.build_dataset import main as build_dataset_main

if __name__ == "__main__":
    sys.exit(build_dataset_main())
