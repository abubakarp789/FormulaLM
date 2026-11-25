# Evaluation Report: `quant_q4_k_m_real`

- **Backend:** `llamacpp:formulalm-qwen3-1.7b-v2-q4_k_m.gguf`
- **Dataset:** `data/test_real/test_real_DRAFT.csv` (80 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 80 |
| Syntax valid rate | 98.8% |
| Execution success rate (no runtime error) | 93.8% |
| **Execution accuracy** | **88.8%** |
| Normalized exact match | 88.8% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 173.8 ms |
| Median / p95 latency | 147.8 ms / 319.2 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 12 | 100.0% | 91.7% | 91.7% | 133.1 ms |
| `conditional_aggregation` | 21 | 100.0% | 76.2% | 76.2% | 202.9 ms |
| `date` | 9 | 88.9% | 88.9% | 88.9% | 183.0 ms |
| `logic` | 10 | 100.0% | 100.0% | 100.0% | 169.1 ms |
| `lookup` | 9 | 100.0% | 88.9% | 88.9% | 222.3 ms |
| `math_and_composition` | 8 | 100.0% | 87.5% | 87.5% | 221.5 ms |
| `text` | 11 | 100.0% | 100.0% | 100.0% | 85.2 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 29 | 96.5% | 86.2% | 86.2% | 109.2 ms |
| 2 | 33 | 100.0% | 97.0% | 97.0% | 169.9 ms |
| 3 | 18 | 100.0% | 77.8% | 77.8% | 285.1 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 4 |
| `unsupported_function` | 1 |
| `wrong_value` | 4 |

## Sample Failures (up to 10)

- **`real_020`** (`hr_employee_roster`, `conditional_aggregation`/D1): headcount in Engineering
  - Reference: `=COUNTIF(C2:C144,"Engineering")` → `34`
  - Predicted: `=SUMIF(C2:C144,"Engineering",1)` → `None` (error: `runtime_error`)
- **`real_023`** (`hr_employee_roster`, `conditional_aggregation`/D3): avg salary in Engineering for vets with 5+ yrs service
  - Reference: `=AVERAGEIFS(G2:G144,C2:C144,"Engineering",F2:F144,">=5")` → `100142.11466666665`
  - Predicted: `=AVERAGEIFS(G2:G144,C2:C144,"Engineering",B2:B144,"Vet",F2:F144,">=5")` → `None` (error: `runtime_error`)
- **`real_030`** (`hr_employee_roster`, `date`/D1): what yr was row 2 hired?
  - Reference: `=YEAR(E2)` → `2021`
  - Predicted: `=EYEAR(E2)` → `None` (error: `unsupported_function`)
- **`real_038`** (`inventory_stock_movements`, `conditional_aggregation`/D3): total valuation of Outbound movements in Zone A
  - Reference: `=SUMIFS(G2:G106,D2:D106,"Outbound",E2:E106,"Zone A")` → `58629.53`
  - Predicted: `=SUMIFS(G2:G106,D2:D106,"Outbound",E2:E106,"A")` → `0.0` (error: `wrong_value`)
- **`real_049`** (`grades_course_scores`, `aggregation`/D1): class average final score
  - Reference: `=AVERAGE(G2:G108)` → `66.97514563106796`
  - Predicted: `=AVERAGEIF(D2:D108,"Class 1",G2:G108)` → `None` (error: `runtime_error`)
- **`real_066`** (`orders_ecommerce`, `conditional_aggregation`/D1): how many orders got cancelled?
  - Reference: `=COUNTIF(E2:E57,"Cancelled")` → `13`
  - Predicted: `=COUNTIF(D2:D57,"Cancelled")` → `0` (error: `wrong_value`)
- **`real_068`** (`orders_ecommerce`, `conditional_aggregation`/D3): total order amount for Web orders that were Delivered
  - Reference: `=SUMIFS(G2:G57,D2:D57,"Web",E2:E57,"Delivered")` → `2416.8399999999997`
  - Predicted: `=SUMIFS(G2:G57,D2:D57,"Web",H2:H57,"Delivered")` → `0.0` (error: `wrong_value`)
- **`real_072`** (`orders_ecommerce`, `lookup`/D2): vlookup fulfillment status for ORD-1004
  - Reference: `=VLOOKUP("ORD-1004",A2:H57,5,FALSE)` → `'Shipped'`
  - Predicted: `=VLOOKUP("ORD-1004",D2:H57,4,FALSE)` → `None` (error: `runtime_error`)
- **`real_079`** (`orders_ecommerce`, `math_and_composition`/D3): say 'Goal Hit' if total Delivered order value beats 5000, else 'Short'
  - Reference: `=IF(SUMIF(E2:E57,"Delivered",G2:G57)>5000,"Goal Hit","Short")` → `'Goal Hit'`
  - Predicted: `=IF(SUMIF(D2:D57,"Delivered",G2:G57)>5000,"Goal Hit","Short")` → `'Short'` (error: `wrong_value`)
