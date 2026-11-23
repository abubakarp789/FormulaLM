# Evaluation Report: `ft_v1_real`

- **Backend:** `transformers:Qwen/Qwen3-1.7B+/content/drive/MyDrive/FormulaLM/qlora_v1/adapter`
- **Dataset:** `data/test_real/test_real_DRAFT.csv` (80 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 80 |
| Syntax valid rate | 100.0% |
| Execution success rate (no runtime error) | 100.0% |
| **Execution accuracy** | **91.2%** |
| Normalized exact match | 91.2% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 789.9 ms |
| Median / p95 latency | 810.5 ms / 994.6 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 12 | 100.0% | 100.0% | 100.0% | 768.2 ms |
| `conditional_aggregation` | 21 | 100.0% | 85.7% | 85.7% | 727.5 ms |
| `date` | 9 | 100.0% | 88.9% | 88.9% | 854.8 ms |
| `logic` | 10 | 100.0% | 100.0% | 100.0% | 724.4 ms |
| `lookup` | 9 | 100.0% | 100.0% | 100.0% | 834.1 ms |
| `math_and_composition` | 8 | 100.0% | 75.0% | 75.0% | 845.5 ms |
| `text` | 11 | 100.0% | 90.9% | 90.9% | 862.2 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 29 | 100.0% | 100.0% | 100.0% | 801.9 ms |
| 2 | 33 | 100.0% | 90.9% | 90.9% | 779.0 ms |
| 3 | 18 | 100.0% | 77.8% | 77.8% | 790.2 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `wrong_value` | 7 |

## Sample Failures (up to 10)

- **`real_014`** (`sales_retail_store`, `text`/D2): combine branch and item name on row 3 like 'Branch: Item' using concat
  - Reference: `=CONCAT(C3,": ",D3)` → `'Suncroft: Foldable Stand'`
  - Predicted: `=CONCAT("Branch:",D3,"-",C3)` → `'Branch:Foldable Stand-Suncroft'` (error: `wrong_value`)
- **`real_038`** (`inventory_stock_movements`, `conditional_aggregation`/D3): total valuation of Outbound movements in Zone A
  - Reference: `=SUMIFS(G2:G106,D2:D106,"Outbound",E2:E106,"Zone A")` → `58629.53`
  - Predicted: `=SUMIF(E2:E106,"A",G2:G106)` → `0.0` (error: `wrong_value`)
- **`real_047`** (`inventory_stock_movements`, `date`/D3): total Outbound units moved on or after 2025-10-01
  - Reference: `=SUMIFS(F2:F106,D2:D106,"Outbound",B2:B106,">="&DATE(2025,10,1))` → `1062.0`
  - Predicted: `=SUMIFS(F2:F106,B2:B106,"Outbound",B2:B106,">="&DATE(2025,10,1))` → `0.0` (error: `wrong_value`)
- **`real_048`** (`inventory_stock_movements`, `math_and_composition`/D2): valuation per unit on row 2 (return 0 if error)
  - Reference: `=IFERROR(G2/F2,0)` → `20.663299492385786`
  - Predicted: `=IFERROR(VLOOKUP(A2,Sheet1!A:E,7,FALSE),0)` → `0` (error: `wrong_value`)
- **`real_054`** (`grades_course_scores`, `conditional_aggregation`/D2): how many Math students are in Sec A?
  - Reference: `=COUNTIFS(C2:C108,"Math",D2:D108,"Sec A")` → `7`
  - Predicted: `=COUNTIFS(C2:C108,"Math",D2:D108,"A")` → `0` (error: `wrong_value`)
- **`real_068`** (`orders_ecommerce`, `conditional_aggregation`/D3): total order amount for Web orders that were Delivered
  - Reference: `=SUMIFS(G2:G57,D2:D57,"Web",E2:E57,"Delivered")` → `2416.8399999999997`
  - Predicted: `=SUMIFS(G2:G57,E2:E57,"Web",H2:H57,"Delivered")` → `0.0` (error: `wrong_value`)
- **`real_079`** (`orders_ecommerce`, `math_and_composition`/D3): say 'Goal Hit' if total Delivered order value beats 5000, else 'Short'
  - Reference: `=IF(SUMIF(E2:E57,"Delivered",G2:G57)>5000,"Goal Hit","Short")` → `'Goal Hit'`
  - Predicted: `=IF(SUMIF(D2:D57,"Delivered",G2:G57)>5000,"Goal Hit","Short")` → `'Short'` (error: `wrong_value`)
