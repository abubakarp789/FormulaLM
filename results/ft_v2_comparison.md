# QLoRA v1 vs v2 Comparison (with 95% Wilson Confidence Intervals)

## Decision Rule

> **Ship v2 only if its execution accuracy is at least as high as v1 on `val` AND on `test_real_v2`, and not meaningfully worse on `test_real`; otherwise ship v1.**

- **Operational tolerance on `test_real` (N=80):** drop of at most `2.5 pp` (2 examples out of 80; 95% Wilson CI half-width is ~6–9 pp on N=80).
- **Current verdict:** **`SHIP_V2`** — v2 execution accuracy is >= v1 on both val and test_real_v2, and not meaningfully worse on test_real.

| Gate | Criterion | v1 | v2 | Δ (v2 − v1) | Status |
|---|---|---:|---:|---:|---|
| `val` | v2 >= v1 on val | 99.6% | 99.6% | +0.0 pp | **PASS** |
| `test_real_v2` | v2 >= v1 on test_real_v2 | 88.0% | 88.0% | +0.0 pp | **PASS** |
| `test_real` | v2 >= v1 - 2.5 pp on test_real | 91.2% | 93.8% | +2.5 pp | **PASS** |

## Overall Comparison (Every Split)

Note: Any v2 result on the original test sets (`test_synthetic`, `test_real`) is labeled **'informed by v1 error analysis'** because v2 data additions were designed from v1 error analysis on those sets.

| Split | Model | N | Correct | **Exec. Accuracy** | 95% Wilson CI | Δ vs v1 | Syntax Valid | Exact Match | Avg Latency |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| `val` (validation) | Fine-tuned v1 (`v1-frozen`) | 500 | 498/500 | **99.6%** | [98.6%, 99.9%] | — | 99.8% | 99.4% | 717.2 ms |
| `val` (validation) | **Fine-tuned v2** | 500 | 498/500 | **99.6%** | [98.6%, 99.9%] | +0.0 pp | 100.0% | 98.2% | 700.6 ms |
| `test_real_v2` (fresh blind) | Fine-tuned v1 (`v1-frozen`) | 50 | 44/50 | **88.0%** | [76.2%, 94.4%] | — | 100.0% | 82.0% | 731.2 ms |
| `test_real_v2` (fresh blind) | **Fine-tuned v2** | 50 | 44/50 | **88.0%** | [76.2%, 94.4%] | +0.0 pp | 100.0% | 86.0% | 751.6 ms |
| `test_synthetic` (original synthetic) | Fine-tuned v1 (`v1-frozen`) | 500 | 488/500 | **97.6%** | [95.9%, 98.6%] | — | 99.6% | 97.0% | 794.7 ms |
| `test_synthetic` (original synthetic) | **Fine-tuned v2 (informed by v1 error analysis)** | 500 | 494/500 | **98.8%** | [97.4%, 99.5%] | +1.2 pp | 99.8% | 97.6% | 739.6 ms |
| `test_real` (original realistic) | Fine-tuned v1 (`v1-frozen`) | 80 | 73/80 | **91.2%** | [83.0%, 95.7%] | — | 100.0% | 91.2% | 789.9 ms |
| `test_real` (original realistic) | **Fine-tuned v2 (informed by v1 error analysis)** | 80 | 75/80 | **93.8%** | [86.2%, 97.3%] | +2.5 pp | 100.0% | 93.8% | 720.1 ms |

## Per-Category Execution Accuracy (with 95% Wilson CIs)

### `val` (validation)

| Category | N | v1 Exec. Acc (95% Wilson CI) | v2 Exec. Acc (95% Wilson CI) | Δ (v2 − v1) |
|---|---:|---|---|---:|
| `aggregation` | 72 | 100.0% (72/72, [94.9%, 100.0%]) | 100.0% (72/72, [94.9%, 100.0%]) | +0.0 pp |
| `conditional_aggregation` | 72 | 100.0% (72/72, [94.9%, 100.0%]) | 98.6% (71/72, [92.5%, 99.8%]) | -1.4 pp |
| `date` | 72 | 100.0% (72/72, [94.9%, 100.0%]) | 100.0% (72/72, [94.9%, 100.0%]) | +0.0 pp |
| `logic` | 71 | 100.0% (71/71, [94.9%, 100.0%]) | 100.0% (71/71, [94.9%, 100.0%]) | +0.0 pp |
| `lookup` | 71 | 100.0% (71/71, [94.9%, 100.0%]) | 98.6% (70/71, [92.4%, 99.8%]) | -1.4 pp |
| `math_and_composition` | 71 | 98.6% (70/71, [92.4%, 99.8%]) | 100.0% (71/71, [94.9%, 100.0%]) | +1.4 pp |
| `text` | 71 | 98.6% (70/71, [92.4%, 99.8%]) | 100.0% (71/71, [94.9%, 100.0%]) | +1.4 pp |

### `test_real_v2` (fresh blind)

| Category | N | v1 Exec. Acc (95% Wilson CI) | v2 Exec. Acc (95% Wilson CI) | Δ (v2 − v1) |
|---|---:|---|---|---:|
| `aggregation` | 10 | 90.0% (9/10, [59.6%, 98.2%]) | 100.0% (10/10, [72.2%, 100.0%]) | +10.0 pp |
| `conditional_aggregation` | 15 | 86.7% (13/15, [62.1%, 96.3%]) | 80.0% (12/15, [54.8%, 93.0%]) | -6.7 pp |
| `date` | 5 | 60.0% (3/5, [23.1%, 88.2%]) | 80.0% (4/5, [37.5%, 96.4%]) | +20.0 pp |
| `logic` | 5 | 80.0% (4/5, [37.5%, 96.4%]) | 80.0% (4/5, [37.5%, 96.4%]) | +0.0 pp |
| `lookup` | 5 | 100.0% (5/5, [56.5%, 100.0%]) | 100.0% (5/5, [56.5%, 100.0%]) | +0.0 pp |
| `math_and_composition` | 5 | 100.0% (5/5, [56.5%, 100.0%]) | 80.0% (4/5, [37.5%, 96.4%]) | -20.0 pp |
| `text` | 5 | 100.0% (5/5, [56.5%, 100.0%]) | 100.0% (5/5, [56.5%, 100.0%]) | +0.0 pp |

### `test_synthetic` (original synthetic) — v2 informed by v1 error analysis

| Category | N | v1 Exec. Acc (95% Wilson CI) | v2 (informed by v1 error analysis) Exec. Acc (95% Wilson CI) | Δ (v2 − v1) |
|---|---:|---|---|---:|
| `aggregation` | 72 | 95.8% (69/72, [88.4%, 98.6%]) | 100.0% (72/72, [94.9%, 100.0%]) | +4.2 pp |
| `conditional_aggregation` | 72 | 98.6% (71/72, [92.5%, 99.8%]) | 97.2% (70/72, [90.4%, 99.2%]) | -1.4 pp |
| `date` | 72 | 95.8% (69/72, [88.4%, 98.6%]) | 100.0% (72/72, [94.9%, 100.0%]) | +4.2 pp |
| `logic` | 71 | 100.0% (71/71, [94.9%, 100.0%]) | 100.0% (71/71, [94.9%, 100.0%]) | +0.0 pp |
| `lookup` | 71 | 100.0% (71/71, [94.9%, 100.0%]) | 98.6% (70/71, [92.4%, 99.8%]) | -1.4 pp |
| `math_and_composition` | 71 | 95.8% (68/71, [88.3%, 98.6%]) | 100.0% (71/71, [94.9%, 100.0%]) | +4.2 pp |
| `text` | 71 | 97.2% (69/71, [90.3%, 99.2%]) | 95.8% (68/71, [88.3%, 98.6%]) | -1.4 pp |

### `test_real` (original realistic) — v2 informed by v1 error analysis

| Category | N | v1 Exec. Acc (95% Wilson CI) | v2 (informed by v1 error analysis) Exec. Acc (95% Wilson CI) | Δ (v2 − v1) |
|---|---:|---|---|---:|
| `aggregation` | 12 | 100.0% (12/12, [75.8%, 100.0%]) | 91.7% (11/12, [64.6%, 98.5%]) | -8.3 pp |
| `conditional_aggregation` | 21 | 85.7% (18/21, [65.4%, 95.0%]) | 90.5% (19/21, [71.1%, 97.4%]) | +4.8 pp |
| `date` | 9 | 88.9% (8/9, [56.5%, 98.0%]) | 100.0% (9/9, [70.1%, 100.0%]) | +11.1 pp |
| `logic` | 10 | 100.0% (10/10, [72.2%, 100.0%]) | 100.0% (10/10, [72.2%, 100.0%]) | +0.0 pp |
| `lookup` | 9 | 100.0% (9/9, [70.1%, 100.0%]) | 88.9% (8/9, [56.5%, 98.0%]) | -11.1 pp |
| `math_and_composition` | 8 | 75.0% (6/8, [40.9%, 92.8%]) | 100.0% (8/8, [67.6%, 100.0%]) | +25.0 pp |
| `text` | 11 | 90.9% (10/11, [62.3%, 98.4%]) | 90.9% (10/11, [62.3%, 98.4%]) | +0.0 pp |
