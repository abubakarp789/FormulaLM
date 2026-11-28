# Evaluation Report: `baseline_4b_real_v2`

- **Backend:** `ollama:qwen3:4b-instruct-2507-q4_K_M`
- **Dataset:** `data/test_real_v2/test_real_v2.csv` (50 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 50 |
| Syntax valid rate | 66.0% |
| Execution success rate (no runtime error) | 62.0% |
| **Execution accuracy** | **56.0%** |
| Normalized exact match | 22.0% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 6352.4 ms |
| Median / p95 latency | 6072.8 ms / 10352.1 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 10 | 60.0% | 50.0% | 30.0% | 5659.2 ms |
| `conditional_aggregation` | 15 | 93.3% | 73.3% | 6.7% | 5720.0 ms |
| `date` | 5 | 60.0% | 60.0% | 20.0% | 5281.9 ms |
| `logic` | 5 | 40.0% | 40.0% | 40.0% | 6988.4 ms |
| `lookup` | 5 | 40.0% | 40.0% | 0.0% | 8699.7 ms |
| `math_and_composition` | 5 | 60.0% | 40.0% | 20.0% | 8256.5 ms |
| `text` | 5 | 60.0% | 60.0% | 60.0% | 5819.4 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 20 | 65.0% | 60.0% | 35.0% | 5228.0 ms |
| 2 | 18 | 55.6% | 50.0% | 16.7% | 6529.9 ms |
| 3 | 12 | 83.3% | 58.3% | 8.3% | 7960.3 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 2 |
| `syntax_error` | 15 |
| `unsupported_function` | 2 |
| `wrong_value` | 3 |

## Sample Failures (up to 10)

- **`real_v2_001`** (`sales_retail_store`, `aggregation`/D1): What is the smallest Net Amount recorded?
  - Reference: `=MIN(F2:F115)` → `29.14`
  - Predicted: `=MIN(sales_retail_store[F])` → `None` (error: `syntax_error`)
- **`real_v2_007`** (`sales_retail_store`, `lookup`/D2): Look up the Item Name for receipt RC-1012 using VLOOKUP
  - Reference: `=VLOOKUP("RC-1012",A2:F115,4,FALSE)` → `'Desk Lamp Pro'`
  - Predicted: `=VLOOKUP("RC-1012", sales_retail_store!A2:F115, 4, FALSE)` → `None` (error: `syntax_error`)
- **`real_v2_011`** (`hr_employee_roster`, `aggregation`/D1): Highest Annual Salary on the roster
  - Reference: `=MAX(G2:G144)` → `144707.81`
  - Predicted: `=MAX(hr_employee_roster[G])` → `None` (error: `syntax_error`)
- **`real_v2_016`** (`hr_employee_roster`, `logic`/D2): Row 21 Annual Salary may be empty: show 0 if blank, otherwise return Annual Salary
  - Reference: `=IF(G21="",0,G21)` → `0`
  - Predicted: `=IF(ISBLANK(G21),0,G21)` → `None` (error: `unsupported_function`)
- **`real_v2_019`** (`hr_employee_roster`, `date`/D1): Month number of Hire Date on row 10
  - Reference: `=MONTH(E10)` → `9`
  - Predicted: `=MONTH([@E])` → `None` (error: `syntax_error`)
- **`real_v2_021`** (`inventory_stock_movements`, `aggregation`/D1): How many stock movements have a numeric Valuation recorded?
  - Reference: `=COUNT(G2:G106)` → `101`
  - Predicted: `=COUNTIF(G:G, ">*")` → `1` (error: `wrong_value`)
- **`real_v2_025`** (`inventory_stock_movements`, `conditional_aggregation`/D3): Average Units Moved for Adjustment records in Zone A
  - Reference: `=AVERAGEIFS(F2:F106,D2:D106,"Adjustment",E2:E106,"Zone A")` → `85.4`
  - Predicted: `=AVERAGEIFS(F:F, D:D, "Adjustment", E:E, "A")` → `None` (error: `runtime_error`)
- **`real_v2_026`** (`inventory_stock_movements`, `logic`/D3): Categorize row 7 Units Moved with IFS: >=150 'Large', >=50 'Medium', else 'Small'
  - Reference: `=IFS(F7>=150,"Large",F7>=50,"Medium",TRUE,"Small")` → `'Large'`
  - Predicted: `=IFS([F7]>=150,"Large",[F7]>=50,"Medium",TRUE,"Small")` → `None` (error: `syntax_error`)
- **`real_v2_027`** (`inventory_stock_movements`, `lookup`/D2): Look up the Valuation for MOV-1010 using XLOOKUP
  - Reference: `=XLOOKUP("MOV-1010",A2:A106,G2:G106)` → `7424.38`
  - Predicted: `=XLOOKUP("MOV-1010", inventory_stock_movements!A2:A106, inventory_stock_movements!G2:G106)` → `None` (error: `syntax_error`)
- **`real_v2_028`** (`inventory_stock_movements`, `text`/D1): Convert Part Name on row 8 to lowercase
  - Reference: `=LOWER(C8)` → `'nylon washer'`
  - Predicted: `=LOWER(INV_STOCK_MOVEMENTS!C8)` → `None` (error: `syntax_error`)
