# Evaluation Report: `baseline_zeroshot_real`

- **Backend:** `transformers:Qwen/Qwen3-1.7B`
- **Dataset:** `data/test_real/test_real_DRAFT.csv` (80 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 80 |
| Syntax valid rate | 81.2% |
| Execution success rate (no runtime error) | 78.8% |
| **Execution accuracy** | **50.0%** |
| Normalized exact match | 42.5% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 651.7 ms |
| Median / p95 latency | 637.6 ms / 892.9 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 12 | 91.7% | 83.3% | 83.3% | 595.9 ms |
| `conditional_aggregation` | 21 | 90.5% | 33.3% | 28.6% | 618.9 ms |
| `date` | 9 | 77.8% | 55.6% | 44.4% | 703.3 ms |
| `logic` | 10 | 90.0% | 60.0% | 40.0% | 611.2 ms |
| `lookup` | 9 | 33.3% | 11.1% | 0.0% | 730.5 ms |
| `math_and_composition` | 8 | 62.5% | 37.5% | 37.5% | 699.3 ms |
| `text` | 11 | 100.0% | 72.7% | 63.6% | 671.0 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 29 | 93.1% | 69.0% | 69.0% | 624.2 ms |
| 2 | 33 | 78.8% | 48.5% | 39.4% | 636.7 ms |
| 3 | 18 | 66.7% | 22.2% | 5.6% | 723.7 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 2 |
| `syntax_error` | 7 |
| `unsupported_function` | 8 |
| `wrong_value` | 23 |

## Sample Failures (up to 10)

- **`real_005`** (`sales_retail_store`, `conditional_aggregation`/D1): how much did the Suncroft branch make in total?
  - Reference: `=SUMIF(C2:C115,"Suncroft",F2:F115)` → `10004.82`
  - Predicted: `=SUMIFS(E:E, C:C,"Suncroft")` → `346.0` (error: `wrong_value`)
- **`real_009`** (`sales_retail_store`, `conditional_aggregation`/D3): total net amt at Suncroft for bulk orders (qty >= 15)
  - Reference: `=SUMIFS(F2:F115,C2:C115,"Suncroft",E2:E115,">=15")` → `4361.219999999999`
  - Predicted: `=SUMIFS(E:E, C:C,"Suncroft", E:E,">=15")` → `232.0` (error: `wrong_value`)
- **`real_011`** (`sales_retail_store`, `logic`/D2): row 24 item name might be empty - show 'Unknown Item' if blank otherwise keep it
  - Reference: `=IF(D24="","Unknown Item",D24)` → `'Unknown Item'`
  - Predicted: `=IF(B24="","Unknown Item",D24)` → `0` (error: `wrong_value`)
- **`real_012`** (`sales_retail_store`, `lookup`/D2): grab the net amount for receipt RC-1005 using xlookup
  - Reference: `=XLOOKUP("RC-1005",A2:A115,F2:F115)` → `597.17`
  - Predicted: `=SUMIFS(E:E, A:A, "RC-1005", C:C, "Store Branch")` → `0.0` (error: `wrong_value`)
- **`real_013`** (`sales_retail_store`, `text`/D1): how many chars in row 2's item name?
  - Reference: `=LEN(D2)` → `12`
  - Predicted: `=LEN(A2)` → `7` (error: `wrong_value`)
- **`real_014`** (`sales_retail_store`, `text`/D2): combine branch and item name on row 3 like 'Branch: Item' using concat
  - Reference: `=CONCAT(C3,": ",D3)` → `'Suncroft: Foldable Stand'`
  - Predicted: `=CONCAT(C2, ":", D2)` → `'Larkspur:Pocket Scale'` (error: `wrong_value`)
- **`real_016`** (`sales_retail_store`, `math_and_composition`/D3): what share of total net amount is from Suncroft? round to 4 dec, 0 on error
  - Reference: `=IFERROR(ROUND(SUMIF(C2:C115,"Suncroft",F2:F115)/SUM(F2:F115),4),0)` → `0.1938`
  - Predicted: `=ROUND(SUMIF(C2:C115,"Suncroft",E2:E115)/SUM(E2:E115),4)` → `0.2287` (error: `wrong_value`)
- **`real_018`** (`hr_employee_roster`, `aggregation`/D1): how many employees actually have a salary filled in?
  - Reference: `=COUNT(G2:G144)` → `137`
  - Predicted: `=COUNTIF(G2:G144,"<>")` → `6` (error: `wrong_value`)
- **`real_020`** (`hr_employee_roster`, `conditional_aggregation`/D1): headcount in Engineering
  - Reference: `=COUNTIF(C2:C144,"Engineering")` → `34`
  - Predicted: `=SUMPRODUCT((C2:C144="Engineering")*(1+IF(E2:E144<=TODAY(),F2:F144,0)))` → `None` (error: `unsupported_function`)
- **`real_021`** (`hr_employee_roster`, `conditional_aggregation`/D2): how many folks aren't in Support?
  - Reference: `=COUNTIF(C2:C144,"<>Support")` → `115`
  - Predicted: `=COUNTIF(D2:D144,"<>Support")` → `143` (error: `wrong_value`)
