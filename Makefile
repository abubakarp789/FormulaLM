# Task runner for Linux/macOS/Colab/Git Bash. On Windows PowerShell use scripts/tasks.ps1.
.PHONY: help setup test lint format data eval reqs

help:
	@echo "setup  - create .venv and install locked deps (uv sync)"
	@echo "test   - run pytest"
	@echo "lint   - ruff check + format check"
	@echo "format - ruff format + autofix"
	@echo "data   - generate synthetic dataset"
	@echo "eval   - run executable evaluation"
	@echo "reqs   - re-export requirements.txt and re-compile requirements-train.txt"

setup:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

data:
	uv run python scripts/generate_data.py $(ARGS)

eval:
	uv run python scripts/evaluate.py $(ARGS)

reqs:
	uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
	uv pip compile requirements-train.in -o requirements-train.txt --python-version 3.12 --python-platform x86_64-manylinux_2_28 --no-header
