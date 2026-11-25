# Evaluation Report: `baseline_zeroshot_real_v2`

- **Backend:** `transformers:Qwen/Qwen3-1.7B`
- **Dataset:** `data/test_real_v2/test_real_v2.csv` (50 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 50 |
| Syntax valid rate | 76.0% |
| Execution success rate (no runtime error) | 74.0% |
| **Execution accuracy** | **46.0%** |
| Normalized exact match | 40.0% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 645.6 ms |
| Median / p95 latency | 634.1 ms / 724.4 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 10 | 100.0% | 70.0% | 60.0% | 612.6 ms |
| `conditional_aggregation` | 15 | 80.0% | 26.7% | 20.0% | 631.1 ms |
| `date` | 5 | 80.0% | 80.0% | 60.0% | 718.4 ms |
| `logic` | 5 | 60.0% | 40.0% | 40.0% | 629.8 ms |
| `lookup` | 5 | 20.0% | 20.0% | 20.0% | 635.6 ms |
| `math_and_composition` | 5 | 80.0% | 40.0% | 40.0% | 718.4 ms |
| `text` | 5 | 80.0% | 60.0% | 60.0% | 635.6 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 20 | 100.0% | 65.0% | 55.0% | 627.5 ms |
| 2 | 18 | 61.1% | 44.4% | 38.9% | 646.6 ms |
| 3 | 12 | 58.3% | 16.7% | 16.7% | 674.5 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 1 |
| `syntax_error` | 7 |
| `unsupported_function` | 5 |
| `wrong_value` | 14 |

## Sample Failures (up to 10)

- **`real_v2_001`** (`sales_retail_store`, `aggregation`/D1): What is the smallest Net Amount recorded?
  - Reference: `=MIN(F2:F115)` → `29.14`
  - Predicted: `=MIN(E2:E115)` → `1` (error: `wrong_value`)
- **`real_v2_003`** (`sales_retail_store`, `conditional_aggregation`/D1): Total Net Amount for the Mirehaven branch
  - Reference: `=SUMIF(C2:C115,"Mirehaven",F2:F115)` → `10205.819999999998`
  - Predicted: `=SUMIFS(E:E, C:C, "Mirehaven")` → `294.0` (error: `wrong_value`)
- **`real_v2_005`** (`sales_retail_store`, `conditional_aggregation`/D3): How many Brinport sales had Quantity of at least 15?
  - Reference: `=COUNTIFS(C2:C115,"Brinport",E2:E115,">=15")` → `16`
  - Predicted: `=SUMPRODUCT((E2:E115>=15)*(C2:C115="Brinport"))` → `None` (error: `unsupported_function`)
- **`real_v2_006`** (`sales_retail_store`, `logic`/D2): On row 10, return 'Bulk High' if Quantity >= 20 and Net Amount > 500, otherwise 'Standard'
  - Reference: `=IF(AND(E10>=20,F10>500),"Bulk High","Standard")` → `'Bulk High'`
  - Predicted: `=IF(E10>=20 AND F10>500, "Bulk High", "Standard")` → `None` (error: `syntax_error`)
- **`real_v2_007`** (`sales_retail_store`, `lookup`/D2): Look up the Item Name for receipt RC-1012 using VLOOKUP
  - Reference: `=VLOOKUP("RC-1012",A2:F115,4,FALSE)` → `'Desk Lamp Pro'`
  - Predicted: `=VLOOKUP(A2, sales_retail_store, 4, FALSE)` → `None` (error: `syntax_error`)
- **`real_v2_010`** (`sales_retail_store`, `math_and_composition`/D3): Average Net Amount per unit on row 10 (Net Amount / Quantity), rounded to 2 decimals, 0 on error
  - Reference: `=IFERROR(ROUND(F10/E10,2),0)` → `33.91`
  - Predicted: `=ROUND(AVERAGE(E10/F10), 2)` → `0.03` (error: `wrong_value`)
- **`real_v2_015`** (`hr_employee_roster`, `conditional_aggregation`/D3): Total Annual Salary for Design staff based in Stonewick
  - Reference: `=SUMIFS(G2:G144,C2:C144,"Design",D2:D144,"Stonewick")` → `319981.94`
  - Predicted: `=SUMPRODUCT((C2:C144="Design")*(D2:D144="Stonewick")*G2:G144)` → `None` (error: `unsupported_function`)
- **`real_v2_016`** (`hr_employee_roster`, `logic`/D2): Row 21 Annual Salary may be empty: show 0 if blank, otherwise return Annual Salary
  - Reference: `=IF(G21="",0,G21)` → `0`
  - Predicted: `=IF(ISBLANK(G21), 0, G21)` → `None` (error: `unsupported_function`)
- **`real_v2_017`** (`hr_employee_roster`, `lookup`/D2): Find the Work Hub for employee EMP-1010 using INDEX and MATCH
  - Reference: `=INDEX(D2:D144,MATCH("EMP-1010",A2:A144,0))` → `'Stonewick'`
  - Predicted: `=INDEX(hr_employee_roster[D], MATCH(EMP-1010, hr_employee_roster[A], 0))` → `None` (error: `syntax_error`)
- **`real_v2_023`** (`inventory_stock_movements`, `conditional_aggregation`/D1): How many movements took place in Cold Bay?
  - Reference: `=COUNTIF(E2:E106,"Cold Bay")` → `24`
  - Predicted: `=COUNTIF(G2:G106, "Cold Bay")` → `0` (error: `wrong_value`)
