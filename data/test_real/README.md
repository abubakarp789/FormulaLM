# Original Realistic Test Set (`test_real_DRAFT.csv`)

- **Author and repository owner:** Abu Bakar (GitHub: `abubakarp789`; Hugging Face and ModelScope: `abubakar56`)
- **Status:** AI-drafted, reviewed and approved by Abu Bakar on 26 November 2026.

`test_real_DRAFT.csv` contains **80 executor-verified realistic requests** (16 per held-out test sheet across all 5 held-out sheets in `data/sheets/manifest.json`). Note: `"DRAFT"` in the filename (`test_real_DRAFT.csv`) and per-row `notes` column is historical and is retained so that saved evaluation results keep their exact dataset paths and file hashes.

## Provenance and scope

- Only uses the **5 held-out test sheets** (`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`) — zero overlap with training schemas.
- Covers natural spreadsheet phrasing, domain synonyms (`revenue`, `payroll`, `headcount`, `vets`), abbreviations (`avg`, `qty`, `amt`, `dept`, `yr`, `dec`, `chars`), and concise queries (`biggest sale?`, `top score in the class`).
- Every reference formula is verified against its `.xlsx` sheet using `src/eval/executor.py` (`uv run python -m src.eval.verify_csv data/test_real/test_real_DRAFT.csv`).
