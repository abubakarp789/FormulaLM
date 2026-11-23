# Evaluation Report: `baseline_5shot_synthetic`

- **Backend:** `transformers:Qwen/Qwen3-1.7B`
- **Dataset:** `data/processed/test_synthetic.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=5`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 85.0% |
| Execution success rate (no runtime error) | 78.2% |
| **Execution accuracy** | **60.2%** |
| Normalized exact match | 51.2% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 1728.2 ms |
| Median / p95 latency | 1720.8 ms / 1998.9 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 76.4% | 65.3% | 50.0% | 1728.3 ms |
| `conditional_aggregation` | 72 | 97.2% | 58.3% | 55.6% | 1731.9 ms |
| `date` | 72 | 95.8% | 79.2% | 68.1% | 1720.4 ms |
| `logic` | 71 | 80.3% | 69.0% | 53.5% | 1734.4 ms |
| `lookup` | 71 | 59.2% | 40.8% | 36.6% | 1709.1 ms |
| `math_and_composition` | 71 | 90.1% | 57.8% | 47.9% | 1737.1 ms |
| `text` | 71 | 95.8% | 50.7% | 46.5% | 1736.1 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 99.4% | 84.4% | 83.3% | 1710.3 ms |
| 2 | 179 | 82.1% | 50.8% | 43.6% | 1721.5 ms |
| 3 | 141 | 70.2% | 41.1% | 19.9% | 1759.5 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 34 |
| `syntax_error` | 43 |
| `unsupported_function` | 32 |
| `wrong_value` | 90 |

## Sample Failures (up to 10)

- **`test_syn_00004`** (`grades_course_scores`, `conditional_aggregation`/D3): Calculate the total Assignments Done where Section is 'Sec B' and Subject is 'Economics'.
  - Reference: `=SUMIFS(F2:F108,D2:D108,"Sec B",C2:C108,"Economics")` → `68.0`
  - Predicted: `=SUMIF(D2:D108,"Sec B",F2:F108,"Economics")` → `None` (error: `runtime_error`)
- **`test_syn_00005`** (`orders_ecommerce`, `aggregation`/D3): What is total Order Total per unit of total Shipping Fee (return 0 if division fails)?
  - Reference: `=IFERROR(SUM(G2:G57)/SUM(H2:H57),0)` → `34.41518460844978`
  - Predicted: `=SUMPRODUCT((G2:G57)/H2:H57)` → `None` (error: `unsupported_function`)
- **`test_syn_00008`** (`grades_course_scores`, `conditional_aggregation`/D3): Calculate the total Final Score where Subject is 'Economics' and Section is 'Sec B'.
  - Reference: `=SUMIFS(G2:G108,C2:C108,"Economics",D2:D108,"Sec B")` → `652.1299999999999`
  - Predicted: `=SUMIF(C2:C108,"Economics",G2:G108,"Sec B")` → `None` (error: `runtime_error`)
- **`test_syn_00009`** (`inventory_stock_movements`, `lookup`/D3): Wrap an exact-match VLOOKUP of 'ZZZ-9999' in Move ID (returning Part Name) inside IFERROR so missing keys return 'Missing'.
  - Reference: `=IFERROR(VLOOKUP("ZZZ-9999",A2:G106,3,FALSE),"Missing")` → `'Missing'`
  - Predicted: `=IFERROR(VLOOKUP(A2,inventory_stock_movements,5,F2),"Missing")` → `None` (error: `syntax_error`)
- **`test_syn_00010`** (`hr_employee_roster`, `date`/D3): Count records dated after 2021-12-27 based on Hire Date.
  - Reference: `=COUNTIF(E2:E144,">"&DATE(2021,12,27))` → `84`
  - Predicted: `=COUNTIF(E2:E144,">=2021-12-27")` → `85` (error: `wrong_value`)
- **`test_syn_00013`** (`orders_ecommerce`, `math_and_composition`/D2): Compute the arithmetic mean of the Item Count column and round the result to 2 decimal place(s).
  - Reference: `=ROUND(AVERAGE(F2:F57),2)` → `7.59`
  - Predicted: `=AVERAGEIF(F2:F57,F2,F2:F57)` → `12.0` (error: `wrong_value`)
- **`test_syn_00014`** (`orders_ecommerce`, `text`/D2): List the Fulfillment entries from row 8 to 10 joined by ' | ' (skip empty cells).
  - Reference: `=TEXTJOIN(" | ",TRUE,E8:E10)` → `'Delivered | Shipped | Shipped'`
  - Predicted: `=TEXTJOIN(" | ",TRUE,INDEX(E8:E10,0))` → `'Delivered'` (error: `wrong_value`)
- **`test_syn_00015`** (`orders_ecommerce`, `lookup`/D3): iferror(vlookup Channel for Order ID='ORD-1011', 'Not Found')
  - Reference: `=IFERROR(VLOOKUP("ORD-1011",A2:H57,4,FALSE),"Not Found")` → `'Mobile App'`
  - Predicted: `=IFERROR(VLOOKUP(A2,"orders_ecommerce"!,3,FALSE),"Not Found")` → `None` (error: `syntax_error`)
- **`test_syn_00016`** (`grades_course_scores`, `math_and_composition`/D2): Average the Final Score column and round to 1 decimal place(s).
  - Reference: `=ROUND(AVERAGE(G2:G108),1)` → `67.0`
  - Predicted: `=AVERAGE(G2:G108)` → `66.97514563106796` (error: `wrong_value`)
- **`test_syn_00019`** (`grades_course_scores`, `math_and_composition`/D2): Average the Assignments Done column and round to 1 decimal place(s).
  - Reference: `=ROUND(AVERAGE(F2:F108),1)` → `5.9`
  - Predicted: `=AVERAGEIF(F2:F108,F2,F2)` → `None` (error: `runtime_error`)
