# Post-v2 Fresh Held-Out Set (`test_real_v2`)

- **Author and repository owner:** Abu Bakar (GitHub: `abubakarp789`; Hugging Face and ModelScope: `abubakar56`)
- **Status:** AI-drafted with access to the repository including the v1 error analysis, reviewed and approved by Abu Bakar on 26 November 2026; therefore not fully independent, and small (`N = 50`).

## Authorship and provenance

- `data/test_real_v2/requests.csv` (50 raw requests, 10 per held-out sheet) and `data/test_real_v2/test_real_v2.csv` (with `reference_formula`, `expected_value`, `expected_type`, `category`, and `difficulty`) were created **after** QLoRA v2 training (`qlora_v2`) had already finished.
- AI-drafted with access to the repository including the v1 error analysis (`results/ft_v1_comparison.md`) and v2's train-only augmentations (`src/data/v2_augmentations.py`), reviewed and approved by Abu Bakar on 26 November 2026; therefore **not fully independent**, and small (`N = 50`, 95% Wilson CIs about 17-20 pp wide (roughly ±9 pp)).
- All 50 requests use held-out sheets only (`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`), have zero exact overlap with `data/test_real/test_real_DRAFT.csv`, and pass `src.eval.test_real_v2` in both `--mode raw` and `--mode annotated`.

## Verification commands

```powershell
uv run python -m src.eval.test_real_v2 --mode raw data/test_real_v2/requests.csv
uv run python -m src.eval.test_real_v2 --mode annotated data/test_real_v2/test_real_v2.csv
```
