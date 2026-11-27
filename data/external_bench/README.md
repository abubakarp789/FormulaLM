# External Real-Workbook Benchmark (`SpreadsheetBench Verified 400` In-Scope Subset)

- **Source dataset:** [`KAKA22/SpreadsheetBench`](https://huggingface.co/datasets/KAKA22/SpreadsheetBench) (`spreadsheetbench_verified_400.tar.gz`, pinned revision `ab0b742b0fc95b946f212d80ac7771b5531272e4`)
- **Paper:** Ma et al., *SpreadsheetBench: Towards Challenging Real World Spreadsheet Manipulation* (NeurIPS 2024, `arXiv:2406.14991`)
- **License & Attribution:** Original `SpreadsheetBench` workbooks and human-authored Excel forum instructions are licensed under **CC-BY-SA-4.0** by the SpreadsheetBench authors. This directory contains a deterministically filtered evaluation-only subset (zero training use, zero AI-drafted prompts).
- **Archive SHA-256:** `10ef893dd29cb13ab97143ea787e68cdc9574a13873ab9a54e50b31dc03fc949`
- **Frozen `external_bench.csv` SHA-256:** `d528d4e8ffc1cc0b788a7292d8e039670b45f3e1a3d0410592d3e59b0849bb61`
- **Pre-inference freeze:** Generated and SHA-256 committed via `scripts/prepare_external_bench.py` **before** running any model inference.

## Deterministic Model-Blind Filter Rules (`400 -> 56` Tasks)

From the 400 verified tasks in `spreadsheetbench_verified_400/dataset.json`, `scripts/prepare_external_bench.py` keeps every task satisfying all 5 rules:

1. `instruction_type == "Cell-Level Manipulation"` (drops `125` sheet-level multi-step tasks).
2. `answer_position` is a contiguous single-sheet cell or range (`^[A-Z]{1,3}[1-9][0-9]*(?::[A-Z]{1,3}[1-9][0-9]*)?$`), evaluating the top-left target cell (`11` single-cell + `45` column-fill first-cell).
3. Target worksheet is the first sheet (`sheet_idx == 0`) with `<= 20` columns (fits inside `num_ctx=4096`).
4. Golden answer cell in `*_golden.xlsx` starts with `=`, has a non-null cached value, has zero cross-sheet `!` references, and uses only FormulaLM's **36 allowed non-volatile Excel functions**.
5. Golden formula passes `src.eval.executor.run_formula` against `*_init.xlsx` and matches the cached golden value (`values_equal`, `tol=1e-6`).

Total workbook footprint: **56 `.xlsx` files (`745.8 KB`)**.

## Regenerate

```powershell
uv run python scripts/prepare_external_bench.py --out-dir data/external_bench
```
