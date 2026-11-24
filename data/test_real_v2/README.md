# Fresh Blind Real-World Test Set (`test_real_v2`)

**Status: PLACEHOLDER — awaiting Abubakar's hand-written `requests.csv`.**

## Why this set exists

Because QLoRA v2's data additions were informed by v1 error analysis on `test_synthetic` and `test_real` (`test_real_DRAFT.csv`), any v2 score on those two original sets is labeled **"informed by v1 error analysis"**.

This folder reserves space for ~50 fresh requests authored directly by Abubakar over the 5 held-out test sheets:
`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`.

## Two-step authoring and verification workflow

1. **Author raw requests (`data/test_real_v2/requests.csv`):**
   - Copy `requests_TEMPLATE.csv` to `requests.csv` (columns: `sheet_id,request`; optional `id,notes`).
   - Validate locally (checks held-out sheet IDs, non-empty requests, duplicates, and overlap with v1 `test_real`):
     ```powershell
     uv run python -m src.eval.test_real_v2 --mode raw data/test_real_v2/requests.csv
     ```
2. **Annotate & verify (`data/test_real_v2/test_real_v2.csv`):**
   - Once you hand over `requests.csv`, the assistant adds `reference_formula`, `expected_value`, `expected_type`, `category`, and `difficulty`, verifies every row with the executor, and **reports any ambiguous or unanswerable request instead of guessing**.
   - Re-verify the final annotated CSV at any time:
     ```powershell
     uv run python -m src.eval.test_real_v2 --mode annotated data/test_real_v2/test_real_v2.csv --fill-expected
     ```
3. **Evaluate v1 and v2 side by side** on `data/test_real_v2/test_real_v2.csv` using `notebooks/03_eval_ft_v2.ipynb`, then run `python -m src.eval.compare_v1_v2` to apply the shipping decision rule.
