# Evaluation Report: `ft_v1_val`

- **Backend:** `transformers:Qwen/Qwen3-1.7B+abubakar56/formulalm-qwen3-1.7b-lora`
- **Dataset:** `data/processed/val.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 99.8% |
| Execution success rate (no runtime error) | 99.8% |
| **Execution accuracy** | **99.6%** |
| Normalized exact match | 99.4% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 717.2 ms |
| Median / p95 latency | 718.4 ms / 879.6 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 712.0 ms |
| `conditional_aggregation` | 72 | 100.0% | 100.0% | 100.0% | 714.2 ms |
| `date` | 72 | 100.0% | 100.0% | 100.0% | 729.9 ms |
| `logic` | 71 | 100.0% | 100.0% | 100.0% | 716.2 ms |
| `lookup` | 71 | 100.0% | 100.0% | 98.6% | 726.4 ms |
| `math_and_composition` | 71 | 98.6% | 98.6% | 98.6% | 724.8 ms |
| `text` | 71 | 100.0% | 98.6% | 98.6% | 696.8 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 100.0% | 100.0% | 705.0 ms |
| 2 | 179 | 100.0% | 99.4% | 99.4% | 697.7 ms |
| 3 | 141 | 99.3% | 99.3% | 98.6% | 757.4 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `unsupported_function` | 1 |
| `wrong_value` | 1 |

## Sample Failures (up to 10)

- **`val_00429`** (`orders_purchase_requests`, `text`/D2): Merge row 35's PO Number and Category separated by ': '.
  - Reference: `=CONCAT(A35,": ",D35)` → `'PO-1034: Software'`
  - Predicted: `=CONCAT(A35," :",D35)` → `'PO-1034 :Software'` (error: `wrong_value`)
- **`val_00493`** (`sales_regional_q1`, `math_and_composition`/D3): Compare total Unit Price for Region 'Central' against 6831.4 and return 'Above Target' if greater, otherwise 'Below Target'.
  - Reference: `=IF(SUMIF(C2:C194,"Central",G2:G194)>6831.4,"Above Target","Below Target")` → `'Above Target'`
  - Predicted: `=IF(GVERAGE(C2:C194,"Central")>6831.4,"Above Target","Below Target")` → `None` (error: `unsupported_function`)
