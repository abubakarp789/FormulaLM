# Evaluation Report: `local_q5_k_m_real`

- **Backend:** `ollama:formulalm-v2-q5_k_m`
- **Dataset:** `data/test_real/test_real_DRAFT.csv` (80 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 80 |
| Syntax valid rate | 100.0% |
| Execution success rate (no runtime error) | 96.2% |
| **Execution accuracy** | **93.8%** |
| Normalized exact match | 93.8% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 4206.5 ms |
| Median / p95 latency | 3954.8 ms / 5820.2 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 12 | 100.0% | 91.7% | 91.7% | 3656.6 ms |
| `conditional_aggregation` | 21 | 100.0% | 90.5% | 90.5% | 4536.4 ms |
| `date` | 9 | 100.0% | 100.0% | 100.0% | 4303.3 ms |
| `logic` | 10 | 100.0% | 100.0% | 100.0% | 4188.4 ms |
| `lookup` | 9 | 100.0% | 88.9% | 88.9% | 4744.0 ms |
| `math_and_composition` | 8 | 100.0% | 100.0% | 100.0% | 4792.7 ms |
| `text` | 11 | 100.0% | 90.9% | 90.9% | 3247.8 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 29 | 100.0% | 96.5% | 96.5% | 3431.2 ms |
| 2 | 33 | 100.0% | 93.9% | 93.9% | 4218.6 ms |
| 3 | 18 | 100.0% | 88.9% | 88.9% | 5433.6 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 3 |
| `wrong_value` | 2 |

## Sample Failures (up to 10)

- **`real_014`** (`sales_retail_store`, `text`/D2): combine branch and item name on row 3 like 'Branch: Item' using concat
  - Reference: `=CONCAT(C3,": ",D3)` → `'Suncroft: Foldable Stand'`
  - Predicted: `=CONCAT(C3,":",D3)` → `'Suncroft:Foldable Stand'` (error: `wrong_value`)
- **`real_023`** (`hr_employee_roster`, `conditional_aggregation`/D3): avg salary in Engineering for vets with 5+ yrs service
  - Reference: `=AVERAGEIFS(G2:G144,C2:C144,"Engineering",F2:F144,">=5")` → `100142.11466666665`
  - Predicted: `=AVERAGEIFS(G2:G144,C2:C144,"Engineering",B2:B144,"Vet",F2:F144,">=5")` → `None` (error: `runtime_error`)
- **`real_038`** (`inventory_stock_movements`, `conditional_aggregation`/D3): total valuation of Outbound movements in Zone A
  - Reference: `=SUMIFS(G2:G106,D2:D106,"Outbound",E2:E106,"Zone A")` → `58629.53`
  - Predicted: `=SUMIFS(G2:G106,D2:D106,"Outbound",E2:E106,"A")` → `0.0` (error: `wrong_value`)
- **`real_049`** (`grades_course_scores`, `aggregation`/D1): class average final score
  - Reference: `=AVERAGE(G2:G108)` → `66.97514563106796`
  - Predicted: `=AVERAGEIF(D2:D108,"Class",G2:G108)` → `None` (error: `runtime_error`)
- **`real_072`** (`orders_ecommerce`, `lookup`/D2): vlookup fulfillment status for ORD-1004
  - Reference: `=VLOOKUP("ORD-1004",A2:H57,5,FALSE)` → `'Shipped'`
  - Predicted: `=VLOOKUP("ORD-1004",D2:H57,5,FALSE)` → `None` (error: `runtime_error`)
