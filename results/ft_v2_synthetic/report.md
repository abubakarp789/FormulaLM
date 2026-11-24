# Evaluation Report: `ft_v2_synthetic`

- **Backend:** `transformers:Qwen/Qwen3-1.7B+abubakar56/formulalm-qwen3-1.7b-lora-v2`
- **Dataset:** `data/processed/test_synthetic.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 99.8% |
| Execution success rate (no runtime error) | 99.8% |
| **Execution accuracy** | **98.8%** |
| Normalized exact match | 97.6% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 739.6 ms |
| Median / p95 latency | 733.0 ms / 885.2 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 721.7 ms |
| `conditional_aggregation` | 72 | 100.0% | 97.2% | 97.2% | 744.4 ms |
| `date` | 72 | 100.0% | 100.0% | 100.0% | 752.9 ms |
| `logic` | 71 | 100.0% | 100.0% | 98.6% | 743.3 ms |
| `lookup` | 71 | 100.0% | 98.6% | 91.5% | 723.2 ms |
| `math_and_composition` | 71 | 100.0% | 100.0% | 100.0% | 753.6 ms |
| `text` | 71 | 98.6% | 95.8% | 95.8% | 737.8 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 98.9% | 98.9% | 726.2 ms |
| 2 | 179 | 99.4% | 98.9% | 98.9% | 735.7 ms |
| 3 | 141 | 100.0% | 98.6% | 94.3% | 761.5 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `unsupported_function` | 1 |
| `wrong_value` | 5 |

## Sample Failures (up to 10)

- **`test_syn_00118`** (`hr_employee_roster`, `conditional_aggregation`/D2): Compute the sum of Annual Salary for 'Crestholm' in Work Hub where Years Service is higher than 4.
  - Reference: `=SUMIFS(G2:G144,D2:D144,"Crestholm",F2:F144,">4")` → `1261327.31`
  - Predicted: `=SUMIFS(G2:G144,C2:C144,"Crestholm",F2:F144,">4")` → `0.0` (error: `wrong_value`)
- **`test_syn_00179`** (`orders_ecommerce`, `conditional_aggregation`/D3): sum Order Total where Channel=Mobile App & Fulfillment=Delivered
  - Reference: `=SUMIFS(G2:G57,D2:D57,"Mobile App",E2:E57,"Delivered")` → `3902.96`
  - Predicted: `=SUMIFS(G2:G57,D2:D57,"Mobile App",H2:H57,"Delivered")` → `0.0` (error: `wrong_value`)
- **`test_syn_00216`** (`inventory_stock_movements`, `lookup`/D3): Wrap an exact-match VLOOKUP of 'MOV-1047' in Move ID (returning Zone) inside IFERROR so missing keys return 'Missing'.
  - Reference: `=IFERROR(VLOOKUP("MOV-1047",A2:G106,5,FALSE),"Missing")` → `'Zone C'`
  - Predicted: `=IFERROR(VLOOKUP("MOV-1047",A2:G106,4,FALSE),"Missing")` → `'Outbound'` (error: `wrong_value`)
- **`test_syn_00221`** (`inventory_stock_movements`, `text`/D2): mid Zone row 36 start 4 len 3
  - Reference: `=MID(E36,4,3)` → `'e B'`
  - Predicted: `=INDEX(E2:E106,MID(ROW(2:106),36,4))` → `None` (error: `unsupported_function`)
- **`test_syn_00242`** (`hr_employee_roster`, `text`/D1): proper Department row 140
  - Reference: `=PROPER(C140)` → `'Design'`
  - Predicted: `=INDEX(C2:C144,140)` → `'Finance'` (error: `wrong_value`)
- **`test_syn_00308`** (`orders_ecommerce`, `text`/D1): Transform row 24's Fulfillment to UPPERCASE.
  - Reference: `=UPPER(E24)` → `'PENDING'`
  - Predicted: `=UPPER(D24)` → `'MARKETPLACE'` (error: `wrong_value`)
