# FormulaLM Synthetic Dataset Card

## Overview

The FormulaLM dataset pairs a spreadsheet schema and a plain-English request with a single executable Excel formula (`=...`) and its independently verified expected value. It is **100% synthetic**, generated from scratch during the Qwen Local Hackathon 2026 (`seed = 42`), with **no private or personal data** and **no outputs from third-party/other-vendor LLMs**.

## Sources and Generation Method

1. **Synthetic spreadsheets ([`src/data/sheets.py`](../src/data/sheets.py), documented in [`docs/sheets.md`](../docs/sheets.md)):**
   - 25 spreadsheets across 11 domains (`sales`, `hr_employees`, `inventory`, `student_grades`, `expenses`, `orders`, `project_tracking`, `attendance`, `subscriptions`, `support_tickets`, `marketing`).
   - 5–8 typed columns (`text`, `integer`, `decimal`, `date`, `category`), 42–193 rows (`rows_per_sheet` in `[30, 200]`), realistic headers including spaces, and ~4% blank cells in designated nullable columns.
   - All person names, organizations, cities, product names and numbers are sampled from purely invented vocabularies.
2. **Hand-written formula templates ([`src/data/templates.py`](../src/data/templates.py)):**
   - 60 templates spanning 7 categories and 3 difficulty levels (22 easy, 26 medium, 12 hard), covering all **36 / 36** in-scope Excel functions (`SUM`, `SUMIF`, `SUMIFS`, `COUNT`, `COUNTIF`, `COUNTIFS`, `AVERAGE`, `AVERAGEIF`, `AVERAGEIFS`, `MIN`, `MAX`, `IF`, `IFS`, `AND`, `OR`, `VLOOKUP`, `XLOOKUP`, `INDEX`, `MATCH`, `LEFT`, `RIGHT`, `MID`, `LEN`, `CONCAT`, `TEXTJOIN`, `UPPER`, `LOWER`, `PROPER`, `TRIM`, `TEXT`, `DATE`, `YEAR`, `MONTH`, `DAY`, `ROUND`, `IFERROR`). Volatile functions (`TODAY`, `NOW`, `RAND`) are excluded.
   - Each template has 7–8 hand-written phrasing patterns (422 total) across formal, casual, terse and verbose styles, paired with an independent pandas ground-truth function (`pandas_gt`).
3. **Optional paraphrase augmentation (`train` only):**
   - 10 hand-written semantic-preserving rewrite rules (e.g., polite/imperative prefixes, `records`↔`rows`, `Calculate`↔`Compute`, `sheet`↔`table`, `column`↔`field`, trailing period removal), logged per example in the `augmentation` field (`"none"` or `"rule:<name>"`).
   - Never applied to `val` or `test_synthetic`.
4. **Executable verification ([`src/eval/executor.py`](../src/eval/executor.py)):**
   - Every generated example's formula is executed on its target `.xlsx` sheet using Python `formulas` 1.3.4 and compared against its pandas ground truth (`values_equal`, numeric tolerance `1e-6`).
   - Build run (`seed = 42`): **9,000 / 9,000 verified (0 dropped)**.

## Splits and Leakage Guarantees

| Split | File | Examples | Sheets | Templates | Augmented | Dropped | Size | SHA-256 (first 16 hex) |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `train` (v1, frozen) | `data/processed/train.jsonl` | **8,000** | 20 (train) | 60 | 2,168 | 0 | 9,422.8 KB | `7f3d8e5ebeb4019a` |
| `train_v2` (v2) | `data/processed/train_v2.jsonl` | **9,000** | 20 (train) | 62 | 3,420 | 0 | 10,625.3 KB | `0cca0eb9d2748c0f` |
| `val` (frozen) | `data/processed/val.jsonl` | **500** | 20 (train) | 60 | 0 | 0 | 577.4 KB | `f2cf0d3181baee06` |
| `test_synthetic` (frozen) | `data/processed/test_synthetic.jsonl` | **500** | 5 (held-out) | 60 | 0 | 0 | 588.2 KB | `ec6348fef4ca3b6a` |

- **v2 train split (`train_v2.jsonl`, `stats_v2.json`):** generated strictly on the 20 training sheets using `src/data/v2_augmentations.py` (58 train-only phrasings + 2 ratio templates; difficulty rebalanced to 30.2% D1 / 38.9% D2 / 30.9% D3; 10,000/10,000 verified, 0 dropped). Both `val.jsonl` and `test_synthetic.jsonl` remain **bit-for-bit identical** to v1. See [`docs/v2_changelog.md`](../docs/v2_changelog.md).
- **Blind fresh real-world set (`data/test_real_v2/`):** placeholder reserved for ~50 new hand-written requests authored independently by Abubakar and evaluated only after v2 training finishes.

- **Zero schema leakage:** `test_synthetic` uses only the 5 held-out test sheets (`sales_retail_store`, `hr_employee_roster`, `inventory_stock_movements`, `grades_course_scores`, `orders_ecommerce`), which never appear in `train` or `val`.
- **Zero phrasing leakage:** for every template, phrasing pattern indices are partitioned disjointly across splits: **2 reserved for `test_synthetic`**, **1 reserved for `val`**, and the remaining **4–5 for `train`**.
- **Zero duplicate prompts:** enforced globally across all 9,000 examples and verified by automated pytest leakage tests (`tests/test_dataset.py`).

### Category Distribution

| Category | Train | Val | Test (synthetic) |
|---|---:|---:|---:|
| `aggregation` | 1,143 | 72 | 72 |
| `conditional_aggregation` | 1,143 | 72 | 72 |
| `date` | 1,143 | 72 | 72 |
| `logic` | 1,143 | 71 | 71 |
| `lookup` | 1,143 | 71 | 71 |
| `math_and_composition` | 1,143 | 71 | 71 |
| `text` | 1,142 | 71 | 71 |
| **Total** | **8,000** | **500** | **500** |

### Difficulty Distribution

| Difficulty | Train | Val | Test (synthetic) |
|---|---:|---:|---:|
| 1 (Easy) | 2,857 (35.7%) | 180 (36.0%) | 180 (36.0%) |
| 2 (Medium) | 2,857 (35.7%) | 179 (35.8%) | 179 (35.8%) |
| 3 (Hard) | 2,286 (28.6%) | 141 (28.2%) | 141 (28.2%) |

### Train Augmentation Breakdown

| Augmentation tag | Count |
|---|---:|
| `none` | 5,832 |
| `rule:prefix_formula_colon` | 589 |
| `rule:suffix_formula_only` | 561 |
| `rule:strip_period` | 325 |
| `rule:prefix_excel_formula` | 219 |
| `rule:prefix_please` | 206 |
| `rule:prefix_need_formula` | 191 |
| `rule:swap_records_rows` | 32 |
| `rule:swap_calculate_compute` | 24 |
| `rule:swap_column_field` | 11 |
| `rule:swap_sheet_table` | 10 |

## Record Schema

Each JSONL line contains:

- `id`, `template_id`, `category`, `difficulty`, `sheet_id`, `phrasing_idx`, `augmentation`
- `schema_text`: sheet name, data row range (`rows 2..N`), column letters, header names and types
- `request`: natural-language request
- `formula`: target Excel formula starting with `=`
- `expected_value` & `expected_type`: pandas ground-truth answer verified by execution (`number`, `text`, `boolean`, `date`, `empty`)
- `messages`: 3-turn chat list (`system`, `user`, `assistant`) ready for Qwen3 non-thinking chat-template formatting

## Reproduction

The `.jsonl` files are git-ignored as regenerable build artifacts (`data/processed/stats.json` records exact counts and SHA-256 hashes). Regenerate identically with:

```powershell
# Windows PowerShell
.\scripts\tasks.ps1 data -- --workers 4
```

```bash
# Linux / macOS / Git Bash
make data ARGS="--workers 4"
```

## Privacy, Licensing and Limitations

- **Privacy:** 100% synthetic; contains zero real people, companies, emails, or personal records.
- **License:** MIT (matching the repository code license).
- **Limitations:** Synthetic prompts follow structured template patterns and bounded ranges (`2..N`). To measure real-world generalization beyond templates, FormulaLM is also evaluated on a separate hand-written realistic test set (`data/handwritten/`).
