# Evaluation Report: `baseline_zeroshot_synthetic`

- **Backend:** `transformers:Qwen/Qwen3-1.7B`
- **Dataset:** `data/processed/test_synthetic.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 71.8% |
| Execution success rate (no runtime error) | 69.0% |
| **Execution accuracy** | **44.6%** |
| Normalized exact match | 36.6% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 814.0 ms |
| Median / p95 latency | 792.9 ms / 1197.7 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 75.0% | 65.3% | 63.9% | 816.1 ms |
| `conditional_aggregation` | 72 | 79.2% | 23.6% | 18.1% | 799.9 ms |
| `date` | 72 | 77.8% | 56.9% | 52.8% | 820.3 ms |
| `logic` | 71 | 91.5% | 69.0% | 40.8% | 854.8 ms |
| `lookup` | 71 | 5.6% | 4.2% | 1.4% | 791.4 ms |
| `math_and_composition` | 71 | 83.1% | 52.1% | 39.4% | 843.2 ms |
| `text` | 71 | 90.1% | 40.8% | 39.4% | 772.1 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 78.3% | 47.2% | 43.3% | 793.4 ms |
| 2 | 179 | 75.4% | 48.0% | 40.8% | 806.0 ms |
| 3 | 141 | 58.9% | 36.9% | 22.7% | 850.2 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 14 |
| `syntax_error` | 92 |
| `unsupported_function` | 49 |
| `wrong_value` | 122 |

## Sample Failures (up to 10)

- **`test_syn_00004`** (`grades_course_scores`, `conditional_aggregation`/D3): Calculate the total Assignments Done where Section is 'Sec B' and Subject is 'Economics'.
  - Reference: `=SUMIFS(F2:F108,D2:D108,"Sec B",C2:C108,"Economics")` → `68.0`
  - Predicted: `=SUMIFS(G2:G108, C2:C108,"Economics", D2:D108,"Sec B")` → `652.1299999999999` (error: `wrong_value`)
- **`test_syn_00005`** (`orders_ecommerce`, `aggregation`/D3): What is total Order Total per unit of total Shipping Fee (return 0 if division fails)?
  - Reference: `=IFERROR(SUM(G2:G57)/SUM(H2:H57),0)` → `34.41518460844978`
  - Predicted: `=SUMPRODUCT((G2:G57)/H2:H57)` → `None` (error: `unsupported_function`)
- **`test_syn_00009`** (`inventory_stock_movements`, `lookup`/D3): Wrap an exact-match VLOOKUP of 'ZZZ-9999' in Move ID (returning Part Name) inside IFERROR so missing keys return 'Missing'.
  - Reference: `=IFERROR(VLOOKUP("ZZZ-9999",A2:G106,3,FALSE),"Missing")` → `'Missing'`
  - Predicted: `=IFERROR(VLOOKUP(A2, inventory_stock_movements, 4, FALSE), "Missing")` → `None` (error: `syntax_error`)
- **`test_syn_00010`** (`hr_employee_roster`, `date`/D3): Count records dated after 2021-12-27 based on Hire Date.
  - Reference: `=COUNTIF(E2:E144,">"&DATE(2021,12,27))` → `84`
  - Predicted: `=COUNTIF(hr_employee_roster!E2:E144, ">2021-12-27")` → `None` (error: `syntax_error`)
- **`test_syn_00012`** (`hr_employee_roster`, `lookup`/D1): index Department position 92
  - Reference: `=INDEX(C2:C144,92)` → `'Operations'`
  - Predicted: `=INDEX(hr_employee_roster!C2:C144,92)` → `None` (error: `syntax_error`)
- **`test_syn_00013`** (`orders_ecommerce`, `math_and_composition`/D2): Compute the arithmetic mean of the Item Count column and round the result to 2 decimal place(s).
  - Reference: `=ROUND(AVERAGE(F2:F57),2)` → `7.59`
  - Predicted: `= AVERAGE(F2:F57)` → `7.589285714285714` (error: `wrong_value`)
- **`test_syn_00014`** (`orders_ecommerce`, `text`/D2): List the Fulfillment entries from row 8 to 10 joined by ' | ' (skip empty cells).
  - Reference: `=TEXTJOIN(" | ",TRUE,E8:E10)` → `'Delivered | Shipped | Shipped'`
  - Predicted: `=TEXTJOIN(" | ", TRUE, H8:H10)` → `'15.02 | 24.85 | 3.26'` (error: `wrong_value`)
- **`test_syn_00015`** (`orders_ecommerce`, `lookup`/D3): iferror(vlookup Channel for Order ID='ORD-1011', 'Not Found')
  - Reference: `=IFERROR(VLOOKUP("ORD-1011",A2:H57,4,FALSE),"Not Found")` → `'Mobile App'`
  - Predicted: `=IFERROR(VLOOKUP(A2, orders_ecommerce, 4, FALSE), "Not Found")` → `None` (error: `syntax_error`)
- **`test_syn_00016`** (`grades_course_scores`, `math_and_composition`/D2): Average the Final Score column and round to 1 decimal place(s).
  - Reference: `=ROUND(AVERAGE(G2:G108),1)` → `67.0`
  - Predicted: `= AVERAGE(G2:G108)` → `66.97514563106796` (error: `wrong_value`)
- **`test_syn_00020`** (`hr_employee_roster`, `lookup`/D2): vlookup Department for Employee ID='EMP-1052'
  - Reference: `=VLOOKUP("EMP-1052",A2:G144,3,FALSE)` → `'Support'`
  - Predicted: `=VLOOKUP(A2, hr_employee_roster, 3, FALSE)` → `None` (error: `syntax_error`)
