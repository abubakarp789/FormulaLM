# QLoRA v1 vs v2 Comparison (with 95% Wilson Confidence Intervals)

## Decision Rule

> **Ship v2 only if its execution accuracy is at least as high as v1 on `val` AND on `test_real_v2`, and not meaningfully worse on `test_real`; otherwise ship v1.**

- **Operational tolerance on `test_real` (N=80):** drop of at most `2.5 pp` (2 examples out of 80; 95% Wilson CI half-width is ~6–9 pp on N=80).
- **Current verdict:** **`PENDING`** — Waiting for required evaluation runs: val:v1, val:v2, test_real_v2:v1, test_real_v2:v2, test_real:v2

| Gate | Criterion | v1 | v2 | Δ (v2 − v1) | Status |
|---|---|---:|---:|---:|---|
| `val` | v2 >= v1 on val (PENDING) | _pending_ | _pending_ | — | PENDING |
| `test_real_v2` | v2 >= v1 on test_real_v2 (PENDING) | _pending_ | _pending_ | — | PENDING |
| `test_real` | v2 >= v1 - 2.5 pp on test_real (PENDING) | _pending_ | _pending_ | — | PENDING |

## Overall Comparison (Every Split)

Note: Any v2 result on the original test sets (`test_synthetic`, `test_real`) is labeled **'informed by v1 error analysis'** because v2 data additions were designed from v1 error analysis on those sets.

| Split | Model | N | Correct | **Exec. Accuracy** | 95% Wilson CI | Δ vs v1 | Syntax Valid | Exact Match | Avg Latency |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| `val` (validation) | Fine-tuned v1 (`v1-frozen`) | — | — | _pending_ | — | — | — | — | — |
| `val` (validation) | Fine-tuned v2 | — | — | _pending_ | — | — | — | — | — |
| `test_real_v2` (fresh blind) | Fine-tuned v1 (`v1-frozen`) | — | — | _pending_ | — | — | — | — | — |
| `test_real_v2` (fresh blind) | Fine-tuned v2 | — | — | _pending_ | — | — | — | — | — |
| `test_synthetic` (original synthetic) | Fine-tuned v1 (`v1-frozen`) | 500 | 488/500 | **97.6%** | [95.9%, 98.6%] | — | 99.6% | 97.0% | 794.7 ms |
| `test_synthetic` (original synthetic) | Fine-tuned v2 (informed by v1 error analysis) | — | — | _pending_ | — | — | — | — | — |
| `test_real` (original realistic) | Fine-tuned v1 (`v1-frozen`) | 80 | 73/80 | **91.2%** | [83.0%, 95.7%] | — | 100.0% | 91.2% | 789.9 ms |
| `test_real` (original realistic) | Fine-tuned v2 (informed by v1 error analysis) | — | — | _pending_ | — | — | — | — | — |

## Per-Category Execution Accuracy (with 95% Wilson CIs)

### `val` (validation)

_Pending: neither v1 nor v2 run exists yet._

### `test_real_v2` (fresh blind)

_Pending: neither v1 nor v2 run exists yet._

### `test_synthetic` (original synthetic) — v2 informed by v1 error analysis

| Category | N | v1 Exec. Acc (95% Wilson CI) | v2 (informed by v1 error analysis) Exec. Acc (95% Wilson CI) | Δ (v2 − v1) |
|---|---:|---|---|---:|
| `aggregation` | 72 | 95.8% (69/72, [88.4%, 98.6%]) | _pending_ | — |
| `conditional_aggregation` | 72 | 98.6% (71/72, [92.5%, 99.8%]) | _pending_ | — |
| `date` | 72 | 95.8% (69/72, [88.4%, 98.6%]) | _pending_ | — |
| `logic` | 71 | 100.0% (71/71, [94.9%, 100.0%]) | _pending_ | — |
| `lookup` | 71 | 100.0% (71/71, [94.9%, 100.0%]) | _pending_ | — |
| `math_and_composition` | 71 | 95.8% (68/71, [88.3%, 98.6%]) | _pending_ | — |
| `text` | 71 | 97.2% (69/71, [90.3%, 99.2%]) | _pending_ | — |

### `test_real` (original realistic) — v2 informed by v1 error analysis

| Category | N | v1 Exec. Acc (95% Wilson CI) | v2 (informed by v1 error analysis) Exec. Acc (95% Wilson CI) | Δ (v2 − v1) |
|---|---:|---|---|---:|
| `aggregation` | 12 | 100.0% (12/12, [75.8%, 100.0%]) | _pending_ | — |
| `conditional_aggregation` | 21 | 85.7% (18/21, [65.4%, 95.0%]) | _pending_ | — |
| `date` | 9 | 88.9% (8/9, [56.5%, 98.0%]) | _pending_ | — |
| `logic` | 10 | 100.0% (10/10, [72.2%, 100.0%]) | _pending_ | — |
| `lookup` | 9 | 100.0% (9/9, [70.1%, 100.0%]) | _pending_ | — |
| `math_and_composition` | 8 | 75.0% (6/8, [40.9%, 92.8%]) | _pending_ | — |
| `text` | 11 | 90.9% (10/11, [62.3%, 98.4%]) | _pending_ | — |
