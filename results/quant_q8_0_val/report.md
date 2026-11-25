# Evaluation Report: `quant_q8_0_val`

- **Backend:** `llamacpp:formulalm-qwen3-1.7b-v2-q8_0.gguf`
- **Dataset:** `data/processed/val.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 100.0% |
| Execution success rate (no runtime error) | 99.8% |
| **Execution accuracy** | **99.8%** |
| Normalized exact match | 98.6% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 266.3 ms |
| Median / p95 latency | 185.8 ms / 411.8 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 203.7 ms |
| `conditional_aggregation` | 72 | 100.0% | 100.0% | 100.0% | 263.8 ms |
| `date` | 72 | 100.0% | 100.0% | 94.4% | 201.6 ms |
| `logic` | 71 | 100.0% | 100.0% | 100.0% | 254.2 ms |
| `lookup` | 71 | 100.0% | 98.6% | 97.2% | 268.5 ms |
| `math_and_composition` | 71 | 100.0% | 100.0% | 100.0% | 537.6 ms |
| `text` | 71 | 100.0% | 100.0% | 98.6% | 136.4 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 99.4% | 98.9% | 142.7 ms |
| 2 | 179 | 100.0% | 100.0% | 100.0% | 208.4 ms |
| 3 | 141 | 100.0% | 100.0% | 96.5% | 497.5 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 1 |

## Sample Failures (up to 10)

- **`val_00224`** (`expenses_travel_claims`, `lookup`/D1): Use INDEX to retrieve entry #1 from the Category data column.
  - Reference: `=INDEX(D2:D106,1)` → `'Flight'`
  - Predicted: `=INDEX(D2:D106)` → `None` (error: `runtime_error`)
