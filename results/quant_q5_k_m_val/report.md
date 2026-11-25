# Evaluation Report: `quant_q5_k_m_val`

- **Backend:** `llamacpp:formulalm-qwen3-1.7b-v2-q5_k_m.gguf`
- **Dataset:** `data/processed/val.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 100.0% |
| Execution success rate (no runtime error) | 99.8% |
| **Execution accuracy** | **99.6%** |
| Normalized exact match | 97.2% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 242.7 ms |
| Median / p95 latency | 160.0 ms / 352.9 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 175.8 ms |
| `conditional_aggregation` | 72 | 100.0% | 100.0% | 100.0% | 225.0 ms |
| `date` | 72 | 100.0% | 100.0% | 90.3% | 173.9 ms |
| `logic` | 71 | 100.0% | 100.0% | 100.0% | 217.2 ms |
| `lookup` | 71 | 100.0% | 97.2% | 95.8% | 231.5 ms |
| `math_and_composition` | 71 | 100.0% | 100.0% | 100.0% | 559.0 ms |
| `text` | 71 | 100.0% | 100.0% | 94.4% | 118.8 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 99.4% | 97.2% | 122.7 ms |
| 2 | 179 | 100.0% | 100.0% | 100.0% | 179.6 ms |
| 3 | 141 | 100.0% | 99.3% | 93.6% | 476.2 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 1 |
| `wrong_value` | 1 |

## Sample Failures (up to 10)

- **`val_00224`** (`expenses_travel_claims`, `lookup`/D1): Use INDEX to retrieve entry #1 from the Category data column.
  - Reference: `=INDEX(D2:D106,1)` → `'Flight'`
  - Predicted: `=INDEX(D2:D106)` → `None` (error: `runtime_error`)
- **`val_00445`** (`grades_lab_assessments`, `lookup`/D3): Look up Status for 'LAB-1030' via VLOOKUP and default to 'Not Found' if not found.
  - Reference: `=IFERROR(VLOOKUP("LAB-1030",A2:G85,7,FALSE),"Not Found")` → `'Failed'`
  - Predicted: `=IFERROR(VLOOKUP("LAB-1030",A2:G85,6,FALSE),"Not Found")` → `18.1` (error: `wrong_value`)
