# Evaluation Report: `ft_v2_val`

- **Backend:** `transformers:Qwen/Qwen3-1.7B+abubakar56/formulalm-qwen3-1.7b-lora-v2`
- **Dataset:** `data/processed/val.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 100.0% |
| Execution success rate (no runtime error) | 99.6% |
| **Execution accuracy** | **99.6%** |
| Normalized exact match | 98.2% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 700.6 ms |
| Median / p95 latency | 697.7 ms / 855.7 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 100.0% | 100.0% | 100.0% | 693.8 ms |
| `conditional_aggregation` | 72 | 100.0% | 98.6% | 98.6% | 699.6 ms |
| `date` | 72 | 100.0% | 100.0% | 94.4% | 709.0 ms |
| `logic` | 71 | 100.0% | 100.0% | 100.0% | 702.7 ms |
| `lookup` | 71 | 100.0% | 98.6% | 97.2% | 707.3 ms |
| `math_and_composition` | 71 | 100.0% | 100.0% | 100.0% | 707.6 ms |
| `text` | 71 | 100.0% | 100.0% | 97.2% | 684.2 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 100.0% | 99.4% | 98.3% | 693.0 ms |
| 2 | 179 | 100.0% | 99.4% | 99.4% | 677.1 ms |
| 3 | 141 | 100.0% | 100.0% | 96.5% | 740.2 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 2 |

## Sample Failures (up to 10)

- **`val_00214`** (`hr_performance_reviews`, `conditional_aggregation`/D2): Find the average of Goals Met values over 6.
  - Reference: `=AVERAGEIF(E2:E80,">6")` → `8.35`
  - Predicted: `=AVERAGEIF(F2:F80,">6")` → `None` (error: `runtime_error`)
- **`val_00224`** (`expenses_travel_claims`, `lookup`/D1): Use INDEX to retrieve entry #1 from the Category data column.
  - Reference: `=INDEX(D2:D106,1)` → `'Flight'`
  - Predicted: `=INDEX(D2:D106)` → `None` (error: `runtime_error`)
