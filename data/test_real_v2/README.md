# Blind Real-World Evaluation Set (`test_real_v2`)

**Status: PLACEHOLDER — to be authored solely by Abubakar and kept BLIND until QLoRA v2 training is completely finished.**

## Why this set exists

Because QLoRA v2's data and training changes were informed by error analysis on `test_synthetic` and `test_real` (`test_real_DRAFT.csv`), any v2 score on those two original sets is labeled **"informed by v1 error analysis"**.

This folder reserves space for **~50 fresh hand-written realistic requests** (`data/test_real_v2/test_real_v2.csv`) that:
- Are written directly by Abubakar over the 5 held-out test sheets (`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`).
- Are **never shown to the AI assistant or inspected** before QLoRA v2 training finishes.
- Are reported **separately** in `README.md` and `results/` as an unbiased blind generalization check comparing Base, Frozen v1 (`v1-frozen`), and v2.

## How to author and self-verify locally (without showing it to the assistant)

1. Copy `test_real_v2_TEMPLATE.csv` to `test_real_v2.csv`.
2. Fill in ~50 realistic requests (`id`, `sheet_id`, `category`, `difficulty`, `request`, `reference_formula`, optional `notes`), leaving `expected_value` and `expected_type` blank if you want the verifier to compute them.
3. Run the local verifier to check held-out sheet compliance, syntax, and auto-fill `expected_value`:
   ```powershell
   uv run python -m src.eval.verify_csv data/test_real_v2/test_real_v2.csv --fill-expected
   ```
4. Evaluate Base, Frozen v1, and v2 on `data/test_real_v2/test_real_v2.csv` **after** v2 training finishes (using `notebooks/03_eval_ft_v2.ipynb` or `src.eval.run_eval`).
