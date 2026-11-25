# Evaluation Report: `baseline_5shot_real_v2`

- **Backend:** `transformers:Qwen/Qwen3-1.7B`
- **Dataset:** `data/test_real_v2/test_real_v2.csv` (50 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=5`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 50 |
| Syntax valid rate | 88.0% |
| Execution success rate (no runtime error) | 74.0% |
| **Execution accuracy** | **58.0%** |
| Normalized exact match | 46.0% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 1493.1 ms |
| Median / p95 latency | 1472.2 ms / 1671.3 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 10 | 90.0% | 80.0% | 80.0% | 1432.3 ms |
| `conditional_aggregation` | 15 | 100.0% | 46.7% | 46.7% | 1453.5 ms |
| `date` | 5 | 80.0% | 80.0% | 40.0% | 1651.3 ms |
| `logic` | 5 | 60.0% | 40.0% | 20.0% | 1425.6 ms |
| `lookup` | 5 | 80.0% | 20.0% | 0.0% | 1489.0 ms |
| `math_and_composition` | 5 | 80.0% | 40.0% | 20.0% | 1651.3 ms |
| `text` | 5 | 100.0% | 100.0% | 80.0% | 1489.0 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 20 | 90.0% | 80.0% | 80.0% | 1453.6 ms |
| 2 | 18 | 83.3% | 55.6% | 38.9% | 1505.6 ms |
| 3 | 12 | 91.7% | 25.0% | 0.0% | 1540.4 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 7 |
| `syntax_error` | 4 |
| `unsupported_function` | 2 |
| `wrong_value` | 8 |

## Sample Failures (up to 10)

- **`real_v2_005`** (`sales_retail_store`, `conditional_aggregation`/D3): How many Brinport sales had Quantity of at least 15?
  - Reference: `=COUNTIFS(C2:C115,"Brinport",E2:E115,">=15")` → `16`
  - Predicted: `=COUNTIF(E2:E115,">=15")` → `48` (error: `wrong_value`)
- **`real_v2_006`** (`sales_retail_store`, `logic`/D2): On row 10, return 'Bulk High' if Quantity >= 20 and Net Amount > 500, otherwise 'Standard'
  - Reference: `=IF(AND(E10>=20,F10>500),"Bulk High","Standard")` → `'Bulk High'`
  - Predicted: `=IF(E10>=20 AND F10>500,"Bulk High","Standard")` → `None` (error: `syntax_error`)
- **`real_v2_007`** (`sales_retail_store`, `lookup`/D2): Look up the Item Name for receipt RC-1012 using VLOOKUP
  - Reference: `=VLOOKUP("RC-1012",A2:F115,4,FALSE)` → `'Desk Lamp Pro'`
  - Predicted: `=VLOOKUP(A1012,D2:D115,E1012)` → `None` (error: `runtime_error`)
- **`real_v2_014`** (`hr_employee_roster`, `conditional_aggregation`/D2): How many employees have Annual Salary above 100000?
  - Reference: `=COUNTIF(G2:G144,">100000")` → `57`
  - Predicted: `=SUMIF(G2:G144,">100000")` → `6950773.9799999995` (error: `wrong_value`)
- **`real_v2_015`** (`hr_employee_roster`, `conditional_aggregation`/D3): Total Annual Salary for Design staff based in Stonewick
  - Reference: `=SUMIFS(G2:G144,C2:C144,"Design",D2:D144,"Stonewick")` → `319981.94`
  - Predicted: `=SUMIF(C2:C144,"Design",G2:G144)` → `2398330.77` (error: `wrong_value`)
- **`real_v2_016`** (`hr_employee_roster`, `logic`/D2): Row 21 Annual Salary may be empty: show 0 if blank, otherwise return Annual Salary
  - Reference: `=IF(G21="",0,G21)` → `0`
  - Predicted: `=IF(G21="","0",G21)` → `'0'` (error: `wrong_value`)
- **`real_v2_017`** (`hr_employee_roster`, `lookup`/D2): Find the Work Hub for employee EMP-1010 using INDEX and MATCH
  - Reference: `=INDEX(D2:D144,MATCH("EMP-1010",A2:A144,0))` → `'Stonewick'`
  - Predicted: `=INDEX(D2:D144, MATCH(ADDRESS(2,1,1, "hr_employee_roster",1), ADDRESS(2,1,1, "hr_employee_roster",1),0))` → `None` (error: `unsupported_function`)
- **`real_v2_020`** (`hr_employee_roster`, `math_and_composition`/D3): Check if total Support Annual Salary exceeds 2000000: return 'Over Budget' else 'Within Budget'
  - Reference: `=IF(SUMIF(C2:C144,"Support",G2:G144)>2000000,"Over Budget","Within Budget")` → `'Over Budget'`
  - Predicted: `=IF(SUMIF(D2:D144,"Support",G2:G144)>2000000,"Over Budget","Within Budget")` → `'Within Budget'` (error: `wrong_value`)
- **`real_v2_021`** (`inventory_stock_movements`, `aggregation`/D1): How many stock movements have a numeric Valuation recorded?
  - Reference: `=COUNT(G2:G106)` → `101`
  - Predicted: `=COUNTIF(G2:G106,"<>"&)` → `None` (error: `syntax_error`)
- **`real_v2_025`** (`inventory_stock_movements`, `conditional_aggregation`/D3): Average Units Moved for Adjustment records in Zone A
  - Reference: `=AVERAGEIFS(F2:F106,D2:D106,"Adjustment",E2:E106,"Zone A")` → `85.4`
  - Predicted: `=AVERAGEIF(D2:D106,"Adjustment",E2:E106)` → `None` (error: `runtime_error`)
