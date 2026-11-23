# Real-World Hand-Written Test Set (`DRAFT`)

**Status: DRAFT — awaiting Abubakar's review and edits.**

`test_real_DRAFT.csv` contains **80 realistic hand-written requests** (16 per held-out test sheet across all 5 held-out sheets in `data/sheets/manifest.json`).

## Guidelines used while drafting

- Only uses the **5 held-out test sheets** (`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`) — zero overlap with training schemas.
- Written in natural user styles: casual phrasing, domain jargon (`revenue`, `payroll`, `headcount`, `vets`), abbreviations (`avg`, `qty`, `amt`, `dept`, `yr`, `dec`, `chars`), and a few slightly underspecified-but-answerable queries (`biggest sale?`, `top score in the class`).
- Every reference formula is verified against its `.xlsx` sheet using `src/eval/executor.py` (`run_formula`).

## How to review and finalize

1. Open `data/test_real/test_real_DRAFT.csv` in Microsoft Excel or VS Code.
2. Edit any phrasing, formula, or notes to match how you'd naturally ask for formulas (feel free to spot-check any formula directly in Office 365 Excel against the matching sheet in `data/sheets/`).
3. After editing, run `.\scripts\tasks.ps1 test` — `tests/test_eval_runner.py` re-executes every reference formula in the CSV and verifies `expected_value` still matches.
4. Once satisfied, you can either keep editing `test_real_DRAFT.csv` or rename/copy it to `test_real.csv` as the final benchmark.
