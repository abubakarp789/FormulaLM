# Evaluation Report: `quant_q4_k_m_val`

- **Backend:** `llamacpp:formulalm-qwen3-1.7b-v2-q4_k_m.gguf`
- **Dataset:** `data/processed/val.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 99.6% |
| Execution success rate (no runtime error) | 98.4% |
| **Execution accuracy** | **97.4%** |
| Normalized exact match | 95.4% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 178.1 ms |
| Median / p95 latency | 152.9 ms / 323.7 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 162.7 ms |
| `conditional_aggregation` | 72 | 100.0% | 94.4% | 94.4% | 205.5 ms |
| `date` | 72 | 97.2% | 91.7% | 83.3% | 163.6 ms |
| `logic` | 71 | 100.0% | 100.0% | 100.0% | 201.0 ms |
| `lookup` | 71 | 100.0% | 95.8% | 94.4% | 213.0 ms |
| `math_and_composition` | 71 | 100.0% | 100.0% | 100.0% | 192.0 ms |
| `text` | 71 | 100.0% | 100.0% | 95.8% | 109.0 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 99.4% | 97.8% | 113.3 ms |
| 2 | 179 | 100.0% | 99.4% | 99.4% | 166.9 ms |
| 3 | 141 | 98.6% | 92.2% | 87.2% | 275.0 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 6 |
| `syntax_error` | 2 |
| `wrong_value` | 5 |

## Sample Failures (up to 10)

- **`val_00033`** (`marketing_campaign_metrics`, `date`/D3): count Launch Date > 2025-11-08
  - Reference: `=COUNTIF(B2:B158,">"&DATE(2025,11,8))` → `68`
  - Predicted: `=COUNTIF(B2:B158,">","2025-11-08")` → `None` (error: `runtime_error`)
- **`val_00158`** (`subscriptions_saas_accounts`, `conditional_aggregation`/D3): Average Monthly Fee filtered by Billing Cycle = 'Annual' and Active Users >= 204.
  - Reference: `=AVERAGEIFS(G2:G87,D2:D87,"Annual",F2:F87,">=204")` → `1711.7514285714283`
  - Predicted: `=AVERAGEIF(D2:D87,"Annual",G2:G87)>=204` → `True` (error: `wrong_value`)
- **`val_00213`** (`projects_sprint_budget`, `lookup`/D2): Write an exact-match VLOOKUP formula that searches Entry ID for 'LOG-1108' and returns the corresponding Budget Used.
  - Reference: `=VLOOKUP("LOG-1108",A2:G174,7,FALSE)` → `6041.5`
  - Predicted: `=VLOOKUP("LOG-1108",A2:G174,6,FALSE)` → `142.58` (error: `wrong_value`)
- **`val_00216`** (`orders_purchase_requests`, `date`/D3): count Request Date > 2025-07-20
  - Reference: `=COUNTIF(B2:B49,">"&DATE(2025,7,20))` → `34`
  - Predicted: `=COUNTIF(B2:B49,">",2025-07-20)` → `None` (error: `syntax_error`)
- **`val_00224`** (`expenses_travel_claims`, `lookup`/D1): Use INDEX to retrieve entry #1 from the Category data column.
  - Reference: `=INDEX(D2:D106,1)` → `'Flight'`
  - Predicted: `=INDEX(D2:D106)` → `None` (error: `runtime_error`)
- **`val_00308`** (`orders_wholesale_shipments`, `date`/D3): count Ship Date > 2025-05-09
  - Reference: `=COUNTIF(B2:B140,">"&DATE(2025,5,9))` → `98`
  - Predicted: `=COUNTIF(B2:B140,">",DATE(2025,5,9))` → `None` (error: `runtime_error`)
- **`val_00412`** (`orders_wholesale_shipments`, `date`/D3): count Ship Date > 2025-08-04
  - Reference: `=COUNTIF(B2:B140,">"&DATE(2025,8,4))` → `80`
  - Predicted: `=COUNTIF(B2:B140,">",DATE(2025,8,4))` → `None` (error: `runtime_error`)
- **`val_00418`** (`hr_payroll_ledger`, `conditional_aggregation`/D3): Average Bonus Amount filtered by Role Band = 'Junior' and Hours Worked >= 172.
  - Reference: `=AVERAGEIFS(G2:G43,D2:D43,"Junior",E2:E43,">=172")` → `523.4499999999999`
  - Predicted: `=AVERAGEIF(D2:D43,"Junior",G2:G43)>=172` → `True` (error: `wrong_value`)
- **`val_00445`** (`grades_lab_assessments`, `lookup`/D3): Look up Status for 'LAB-1030' via VLOOKUP and default to 'Not Found' if not found.
  - Reference: `=IFERROR(VLOOKUP("LAB-1030",A2:G85,7,FALSE),"Not Found")` → `'Failed'`
  - Predicted: `=IFERROR(VLOOKUP("LAB-1030",A2:G85,6,FALSE),"Not Found")` → `18.1` (error: `wrong_value`)
- **`val_00455`** (`attendance_shift_records`, `conditional_aggregation`/D3): Average Overtime Hours filtered by Site = 'Site Beta' and Late Minutes >= 26.
  - Reference: `=AVERAGEIFS(G2:G164,D2:D164,"Site Beta",F2:F164,">=26")` → `2.3153846153846156`
  - Predicted: `=AVERAGEIF(D2:D164,"Site Beta",G2:G164,">=26")` → `None` (error: `runtime_error`)
