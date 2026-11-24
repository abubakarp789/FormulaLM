# Evaluation Report: `ft_v1_real_v2`

- **Backend:** `transformers:Qwen/Qwen3-1.7B+abubakar56/formulalm-qwen3-1.7b-lora`
- **Dataset:** `data/test_real_v2/test_real_v2.csv` (50 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 50 |
| Syntax valid rate | 100.0% |
| Execution success rate (no runtime error) | 98.0% |
| **Execution accuracy** | **88.0%** |
| Normalized exact match | 82.0% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 731.2 ms |
| Median / p95 latency | 702.4 ms / 775.5 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 10 | 100.0% | 90.0% | 90.0% | 665.9 ms |
| `conditional_aggregation` | 15 | 100.0% | 86.7% | 80.0% | 679.6 ms |
| `date` | 5 | 100.0% | 60.0% | 40.0% | 943.3 ms |
| `logic` | 5 | 100.0% | 80.0% | 80.0% | 693.5 ms |
| `lookup` | 5 | 100.0% | 100.0% | 100.0% | 680.6 ms |
| `math_and_composition` | 5 | 100.0% | 100.0% | 80.0% | 943.3 ms |
| `text` | 5 | 100.0% | 100.0% | 100.0% | 680.6 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 20 | 100.0% | 90.0% | 85.0% | 678.1 ms |
| 2 | 18 | 100.0% | 88.9% | 83.3% | 738.6 ms |
| 3 | 12 | 100.0% | 83.3% | 75.0% | 808.5 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 1 |
| `wrong_value` | 5 |

## Sample Failures (up to 10)

- **`real_v2_016`** (`hr_employee_roster`, `logic`/D2): Row 21 Annual Salary may be empty: show 0 if blank, otherwise return Annual Salary
  - Reference: `=IF(G21="",0,G21)` → `0`
  - Predicted: `=IF(G21="","0",G21)` → `'0'` (error: `wrong_value`)
- **`real_v2_021`** (`inventory_stock_movements`, `aggregation`/D1): How many stock movements have a numeric Valuation recorded?
  - Reference: `=COUNT(G2:G106)` → `101`
  - Predicted: `=COUNTIF(G2:G106,"<>")` → `4` (error: `wrong_value`)
- **`real_v2_025`** (`inventory_stock_movements`, `conditional_aggregation`/D3): Average Units Moved for Adjustment records in Zone A
  - Reference: `=AVERAGEIFS(F2:F106,D2:D106,"Adjustment",E2:E106,"Zone A")` → `85.4`
  - Predicted: `=AVERAGEIF(E2:E106,"A",F2:F106)` → `None` (error: `runtime_error`)
- **`real_v2_029`** (`inventory_stock_movements`, `date`/D3): How many Inbound movements happened before 2025-07-01?
  - Reference: `=COUNTIFS(D2:D106,"Inbound",B2:B106,"<"&DATE(2025,7,1))` → `7`
  - Predicted: `=COUNTIFS(D2:D106,"Inbound",B2:B106,">"&DATE(2025,7,1))` → `15` (error: `wrong_value`)
- **`real_v2_034`** (`grades_course_scores`, `conditional_aggregation`/D2): How many students are NOT in Sec C?
  - Reference: `=COUNTIF(D2:D108,"<>Sec C")` → `72`
  - Predicted: `=COUNTIF(D2:D108,"<>C")` → `107` (error: `wrong_value`)
- **`real_v2_039`** (`grades_course_scores`, `date`/D1): Calendar year of Exam Date in row 6
  - Reference: `=YEAR(E6)` → `2026`
  - Predicted: `=TEXT(E6,"yyyy")` → `'2026'` (error: `wrong_value`)
