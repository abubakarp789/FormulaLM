# Post-v2 Fresh Held-Out Set (`test_real_v2`)

**Status: READY (50 executor-verified requests across all 5 held-out sheets).**

## Authorship and provenance

- `data/test_real_v2/requests.csv` (50 raw requests, 10 per held-out sheet) and `data/test_real_v2/test_real_v2.csv` (with `reference_formula`, `expected_value`, `expected_type`, `category`, and `difficulty`) were created **after** QLoRA v2 training (`qlora_v2`) had already finished.
- The requests were drafted by an AI assistant with access to the repo, including the v1 error analysis (`results/ft_v1_comparison.md`) and v2's train-only augmentations (`src/data/v2_augmentations.py`); the set is therefore **not fully independent** and is labeled a **fresh held-out set** rather than an independent human-authored benchmark.
- All 50 requests use held-out sheets only (`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`), have zero exact overlap with `data/test_real/test_real_DRAFT.csv`, and pass `src.eval.test_real_v2` in both `--mode raw` and `--mode annotated`.

## Verification commands

```powershell
uv run python -m src.eval.test_real_v2 --mode raw data/test_real_v2/requests.csv
uv run python -m src.eval.test_real_v2 --mode annotated data/test_real_v2/test_real_v2.csv
```
