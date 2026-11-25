# Evaluation Report: `quant_q5_k_m_synthetic`

- **Backend:** `llamacpp:formulalm-qwen3-1.7b-v2-q5_k_m.gguf`
- **Dataset:** `data/processed/test_synthetic.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 99.6% |
| Execution success rate (no runtime error) | 99.4% |
| **Execution accuracy** | **98.4%** |
| Normalized exact match | 96.4% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 192.3 ms |
| Median / p95 latency | 159.3 ms / 369.4 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 176.5 ms |
| `conditional_aggregation` | 72 | 100.0% | 97.2% | 97.2% | 232.0 ms |
| `date` | 72 | 100.0% | 100.0% | 100.0% | 171.8 ms |
| `logic` | 71 | 100.0% | 100.0% | 100.0% | 213.5 ms |
| `lookup` | 71 | 100.0% | 97.2% | 84.5% | 227.9 ms |
| `math_and_composition` | 71 | 100.0% | 100.0% | 98.6% | 209.6 ms |
| `text` | 71 | 97.2% | 94.4% | 94.4% | 115.0 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 98.9% | 98.9% | 122.5 ms |
| 2 | 179 | 98.9% | 98.3% | 97.8% | 178.9 ms |
| 3 | 141 | 100.0% | 97.9% | 91.5% | 298.6 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 1 |
| `unsupported_function` | 2 |
| `wrong_value` | 5 |

## Sample Failures (up to 10)

- **`test_syn_00064`** (`hr_employee_roster`, `conditional_aggregation`/D3): averageifs Annual Salary: Department=Finance, Years Service>=8
  - Reference: `=AVERAGEIFS(G2:G144,C2:C144,"Finance",F2:F144,">=8")` → `109144.81875`
  - Predicted: `=AVERAGEIFS(G2:G144,D2:D144,"Work Hub",F2:F144,">=8")` → `None` (error: `runtime_error`)
- **`test_syn_00118`** (`hr_employee_roster`, `conditional_aggregation`/D2): Compute the sum of Annual Salary for 'Crestholm' in Work Hub where Years Service is higher than 4.
  - Reference: `=SUMIFS(G2:G144,D2:D144,"Crestholm",F2:F144,">4")` → `1261327.31`
  - Predicted: `=SUMIFS(G2:G144,C2:C144,"Crestholm",F2:F144,">4")` → `0.0` (error: `wrong_value`)
- **`test_syn_00216`** (`inventory_stock_movements`, `lookup`/D3): Wrap an exact-match VLOOKUP of 'MOV-1047' in Move ID (returning Zone) inside IFERROR so missing keys return 'Missing'.
  - Reference: `=IFERROR(VLOOKUP("MOV-1047",A2:G106,5,FALSE),"Missing")` → `'Zone C'`
  - Predicted: `=IFERROR(VLOOKUP("MOV-1047",A2:G106,4,FALSE),"Missing")` → `'Outbound'` (error: `wrong_value`)
- **`test_syn_00221`** (`inventory_stock_movements`, `text`/D2): mid Zone row 36 start 4 len 3
  - Reference: `=MID(E36,4,3)` → `'e B'`
  - Predicted: `=INDEX(E2:E106,MID(ROW(36),4,3))` → `None` (error: `unsupported_function`)
- **`test_syn_00242`** (`hr_employee_roster`, `text`/D1): proper Department row 140
  - Reference: `=PROPER(C140)` → `'Design'`
  - Predicted: `=INDEX(C2:C144,140)` → `'Finance'` (error: `wrong_value`)
- **`test_syn_00298`** (`grades_course_scores`, `lookup`/D3): Wrap an exact-match VLOOKUP of 'STU-1027' in Student ID (returning Student Name) inside IFERROR so missing keys return 'Missing'.
  - Reference: `=IFERROR(VLOOKUP("STU-1027",A2:G108,2,FALSE),"Missing")` → `'Joren Yorn'`
  - Predicted: `=IFERROR(VLOOKUP("STU-1027",A2:A108,2,FALSE),"Missing")` → `'Missing'` (error: `wrong_value`)
- **`test_syn_00308`** (`orders_ecommerce`, `text`/D1): Transform row 24's Fulfillment to UPPERCASE.
  - Reference: `=UPPER(E24)` → `'PENDING'`
  - Predicted: `=UPPER(D24)` → `'MARKETPLACE'` (error: `wrong_value`)
- **`test_syn_00424`** (`hr_employee_roster`, `text`/D2): mid Work Hub row 25 start 2 len 4
  - Reference: `=MID(D25,2,4)` → `'allo'`
  - Predicted: `=INDEX(D2:D144,MID(ROW(25),2,4))` → `None` (error: `unsupported_function`)
