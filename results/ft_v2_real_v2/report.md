# Evaluation Report: `ft_v2_real_v2`

- **Backend:** `transformers:Qwen/Qwen3-1.7B+abubakar56/formulalm-qwen3-1.7b-lora-v2`
- **Dataset:** `data/test_real_v2/test_real_v2.csv` (50 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 50 |
| Syntax valid rate | 100.0% |
| Execution success rate (no runtime error) | 96.0% |
| **Execution accuracy** | **88.0%** |
| Normalized exact match | 86.0% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 751.6 ms |
| Median / p95 latency | 738.5 ms / 779.4 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 10 | 100.0% | 100.0% | 100.0% | 691.7 ms |
| `conditional_aggregation` | 15 | 100.0% | 80.0% | 73.3% | 695.9 ms |
| `date` | 5 | 100.0% | 80.0% | 80.0% | 969.8 ms |
| `logic` | 5 | 100.0% | 80.0% | 80.0% | 690.4 ms |
| `lookup` | 5 | 100.0% | 100.0% | 100.0% | 707.7 ms |
| `math_and_composition` | 5 | 100.0% | 80.0% | 80.0% | 969.8 ms |
| `text` | 5 | 100.0% | 100.0% | 100.0% | 707.7 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 20 | 100.0% | 100.0% | 95.0% | 697.1 ms |
| 2 | 18 | 100.0% | 88.9% | 88.9% | 768.2 ms |
| 3 | 12 | 100.0% | 66.7% | 66.7% | 817.7 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 2 |
| `wrong_value` | 4 |

## Sample Failures (up to 10)

- **`real_v2_016`** (`hr_employee_roster`, `logic`/D2): Row 21 Annual Salary may be empty: show 0 if blank, otherwise return Annual Salary
  - Reference: `=IF(G21="",0,G21)` → `0`
  - Predicted: `=IF(G21="","0",G21)` → `'0'` (error: `wrong_value`)
- **`real_v2_025`** (`inventory_stock_movements`, `conditional_aggregation`/D3): Average Units Moved for Adjustment records in Zone A
  - Reference: `=AVERAGEIFS(F2:F106,D2:D106,"Adjustment",E2:E106,"Zone A")` → `85.4`
  - Predicted: `=AVERAGEIF(D2:D106,"Adjustment",E2:E106)` → `None` (error: `runtime_error`)
- **`real_v2_029`** (`inventory_stock_movements`, `date`/D3): How many Inbound movements happened before 2025-07-01?
  - Reference: `=COUNTIFS(D2:D106,"Inbound",B2:B106,"<"&DATE(2025,7,1))` → `7`
  - Predicted: `=COUNTIFS(D2:D106,"Inbound",B2:B106,">"&DATE(2025,7,1))` → `15` (error: `wrong_value`)
- **`real_v2_034`** (`grades_course_scores`, `conditional_aggregation`/D2): How many students are NOT in Sec C?
  - Reference: `=COUNTIF(D2:D108,"<>Sec C")` → `72`
  - Predicted: `=COUNTIF(D2:D108,"<>C")` → `107` (error: `wrong_value`)
- **`real_v2_035`** (`grades_course_scores`, `conditional_aggregation`/D3): Average Final Score for Computing students in Sec A
  - Reference: `=AVERAGEIFS(G2:G108,C2:C108,"Computing",D2:D108,"Sec A")` → `66.5`
  - Predicted: `=AVERAGEIF(C2:C108,"Computing",D2:D108)` → `None` (error: `runtime_error`)
- **`real_v2_050`** (`orders_ecommerce`, `math_and_composition`/D3): VLOOKUP Order Total for ORD-1015 rounded to 1 decimal, returning 0 if not found
  - Reference: `=IFERROR(ROUND(VLOOKUP("ORD-1015",A2:H57,7,FALSE),1),0)` → `533.0`
  - Predicted: `=IFERROR(ROUND(VLOOKUP("ORD-1015",A2:H57,6,FALSE),1),0)` → `11.0` (error: `wrong_value`)
