# Post-v2 Fresh Real-World Test Set (`test_real_v2`)

**Status: READY (50 executor-verified requests across all 5 held-out sheets).**

## Authorship and provenance

- `data/test_real_v2/requests.csv` (50 raw requests, 10 per held-out sheet) and `data/test_real_v2/test_real_v2.csv` (with `reference_formula`, `expected_value`, `expected_type`, `category`, and `difficulty`) were drafted with an AI assistant at Abubakar's request **after** QLoRA v2 training (`qlora_v2`) had already finished.
- Because the same assistant drafted v2's train-only augmentations (`src/data/v2_augmentations.py`) and this post-v2 set, it should be read honestly as a **post-v2 fresh test set (AI-drafted)** rather than an independent human-only blind benchmark.
- All 50 requests use held-out sheets only (`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`), have zero exact overlap with `data/test_real/test_real_DRAFT.csv`, and pass `src.eval.test_real_v2` in both `--mode raw` and `--mode annotated`.

## Verification commands

```powershell
uv run python -m src.eval.test_real_v2 --mode raw data/test_real_v2/requests.csv
uv run python -m src.eval.test_real_v2 --mode annotated data/test_real_v2/test_real_v2.csv
```
