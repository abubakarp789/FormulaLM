# Evaluation Report: `quant_q4_k_m_synthetic`

- **Backend:** `llamacpp:formulalm-qwen3-1.7b-v2-q4_k_m.gguf`
- **Dataset:** `data/processed/test_synthetic.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 99.4% |
| Execution success rate (no runtime error) | 97.8% |
| **Execution accuracy** | **95.4%** |
| Normalized exact match | 91.8% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 178.6 ms |
| Median / p95 latency | 149.2 ms / 341.3 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 165.1 ms |
| `conditional_aggregation` | 72 | 100.0% | 90.3% | 88.9% | 215.7 ms |
| `date` | 72 | 100.0% | 95.8% | 95.8% | 160.3 ms |
| `logic` | 71 | 100.0% | 97.2% | 85.9% | 199.5 ms |
| `lookup` | 71 | 95.8% | 91.5% | 81.7% | 213.3 ms |
| `math_and_composition` | 71 | 100.0% | 100.0% | 98.6% | 191.1 ms |
| `text` | 71 | 100.0% | 93.0% | 91.5% | 105.2 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 98.3% | 98.3% | 114.6 ms |
| 2 | 179 | 98.3% | 94.4% | 93.3% | 165.9 ms |
| 3 | 141 | 100.0% | 92.9% | 81.6% | 276.5 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 8 |
| `unsupported_function` | 3 |
| `wrong_value` | 12 |

## Sample Failures (up to 10)

- **`test_syn_00014`** (`orders_ecommerce`, `text`/D2): List the Fulfillment entries from row 8 to 10 joined by ' | ' (skip empty cells).
  - Reference: `=TEXTJOIN(" | ",TRUE,E8:E10)` → `'Delivered | Shipped | Shipped'`
  - Predicted: `=TEXTJOIN(" | ",TRUE,D8:D10)` → `'Phone | Marketplace | Marketplace'` (error: `wrong_value`)
- **`test_syn_00035`** (`hr_employee_roster`, `date`/D3): How many Hire Date dates fall past 2021-03-11?
  - Reference: `=COUNTIF(E2:E144,">"&DATE(2021,3,11))` → `107`
  - Predicted: `=COUNTIF(E2:E144,">",DATE(2021,3,11))` → `None` (error: `runtime_error`)
- **`test_syn_00064`** (`hr_employee_roster`, `conditional_aggregation`/D3): averageifs Annual Salary: Department=Finance, Years Service>=8
  - Reference: `=AVERAGEIFS(G2:G144,C2:C144,"Finance",F2:F144,">=8")` → `109144.81875`
  - Predicted: `=AVERAGEIFS(G2:G144,D2:D144,"Finance",F2:F144,">=8")` → `None` (error: `runtime_error`)
- **`test_syn_00094`** (`sales_retail_store`, `logic`/D2): Label row 16 'Priority' only if Store Branch equals 'Ashvale' and Net Amount is above 482.1; otherwise 'Standard'.
  - Reference: `=IF(AND(C16="Ashvale",F16>482.1),"Priority","Standard")` → `'Standard'`
  - Predicted: `=IF(AND(C16="Ashvale"&F16>482.1),"Priority","Standard")` → `'Priority'` (error: `wrong_value`)
- **`test_syn_00108`** (`sales_retail_store`, `lookup`/D2): Return the exact-match index of 'RC-1008' inside the Receipt Code column (excluding the header row).
  - Reference: `=MATCH("RC-1008",A2:A115,0)` → `8`
  - Predicted: `=INDEX(A2:A115,MATCH("RC-1008",A2:A115,0))` → `'RC-1008'` (error: `wrong_value`)
- **`test_syn_00118`** (`hr_employee_roster`, `conditional_aggregation`/D2): Compute the sum of Annual Salary for 'Crestholm' in Work Hub where Years Service is higher than 4.
  - Reference: `=SUMIFS(G2:G144,D2:D144,"Crestholm",F2:F144,">4")` → `1261327.31`
  - Predicted: `=SUMIFS(G2:G144,C2:C144,"Crestholm",F2:F144,">4")` → `0.0` (error: `wrong_value`)
- **`test_syn_00128`** (`hr_employee_roster`, `lookup`/D2): match 'EMP-1068' in Employee ID
  - Reference: `=MATCH("EMP-1068",A2:A144,0)` → `68`
  - Predicted: `=SEARCH("EMP-1068",A2)` → `None` (error: `unsupported_function`)
- **`test_syn_00164`** (`inventory_stock_movements`, `logic`/D2): Label row 91 'Priority' only if Movement Type equals 'Adjustment' and Units Moved is above 103; otherwise 'Standard'.
  - Reference: `=IF(AND(D91="Adjustment",F91>103),"Priority","Standard")` → `'Standard'`
  - Predicted: `=IF(AND(D91="Adjustment")AND(F91>103),"Priority","Standard")` → `None` (error: `runtime_error`)
- **`test_syn_00179`** (`orders_ecommerce`, `conditional_aggregation`/D3): sum Order Total where Channel=Mobile App & Fulfillment=Delivered
  - Reference: `=SUMIFS(G2:G57,D2:D57,"Mobile App",E2:E57,"Delivered")` → `3902.96`
  - Predicted: `=SUMIFS(G2:G57,D2:D57,"Mobile App",H2:H57,"Delivered")` → `0.0` (error: `wrong_value`)
- **`test_syn_00190`** (`inventory_stock_movements`, `date`/D3): How many Move Date dates fall past 2025-08-26?
  - Reference: `=COUNTIF(B2:B106,">"&DATE(2025,8,26))` → `50`
  - Predicted: `=COUNTIF(B2:B106,">",DATE(2025,8,26))` → `None` (error: `runtime_error`)
