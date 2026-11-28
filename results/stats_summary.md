# Statistical Significance & Confidence Intervals

Computed from committed per-item `predictions.jsonl` logs (bootstrap resamples = 10,000, seed = 42, exact two-sided McNemar's test on paired binary execution accuracy).

## `test_real_v2` (N = 50)

| System | Correct | Accuracy | 95% Wilson CI | 95% Bootstrap CI |
|---|---:|---:|---:|---:|
| Base Qwen3-1.7B (0-shot) | 23/50 | 46.0% | [33.0%, 59.6%] | [32.0%, 60.0%] |
| Base Qwen3-1.7B (5-shot) | 29/50 | 58.0% | [44.2%, 70.6%] | [44.0%, 72.0%] |
| Base Qwen3-4B (0-shot, CPU) | 28/50 | 56.0% | [42.3%, 68.8%] | [42.0%, 70.0%] |
| Fine-tuned v2-ship (LoRA, BF16) | 44/50 | 88.0% | [76.2%, 94.4%] | [78.0%, 96.0%] |
| FormulaLM Q4_K_M (Local CPU) | 44/50 | 88.0% | [76.2%, 94.4%] | [78.0%, 96.0%] |
| FormulaLM Q5_K_M (Local CPU) | 43/50 | 86.0% | [73.8%, 93.0%] | [76.0%, 94.0%] |
| FormulaLM Q8_0 (Local CPU) | 44/50 | 88.0% | [76.2%, 94.4%] | [78.0%, 96.0%] |
| FormulaLM Q5_K_M (Colab llama-server) | 45/50 | 90.0% | [78.6%, 95.7%] | [80.0%, 98.0%] |

### Paired Exact McNemar's Tests

| System A vs System B | Delta | A-only / B-only | Exact p-value | Significant (p<0.05) |
|---|---:|---:|---:|---|
| FormulaLM Q5_K_M (Local CPU) vs Base Qwen3-1.7B (0-shot) | +40.0 pp | 21 / 1 | `p = 1.10e-05` | Yes |
| FormulaLM Q5_K_M (Local CPU) vs Base Qwen3-1.7B (5-shot) | +28.0 pp | 16 / 2 | `p = 0.0013` | Yes |
| FormulaLM Q5_K_M (Local CPU) vs Base Qwen3-4B (0-shot, CPU) | +30.0 pp | 17 / 2 | `p = 0.0007` | Yes |
| FormulaLM Q5_K_M (Colab llama-server) vs Base Qwen3-1.7B (0-shot) | +44.0 pp | 22 / 0 | `p = 4.77e-07` | Yes |
| FormulaLM Q5_K_M (Colab llama-server) vs Base Qwen3-1.7B (5-shot) | +32.0 pp | 16 / 0 | `p = 3.05e-05` | Yes |
| FormulaLM Q5_K_M (Colab llama-server) vs Base Qwen3-4B (0-shot, CPU) | +34.0 pp | 17 / 0 | `p = 1.53e-05` | Yes |
| FormulaLM Q5_K_M (Local CPU) vs FormulaLM Q4_K_M (Local CPU) | -2.0 pp | 0 / 1 | `p = 1.0000` | No |

## `test_real` (N = 80)

| System | Correct | Accuracy | 95% Wilson CI | 95% Bootstrap CI |
|---|---:|---:|---:|---:|
| FormulaLM Q4_K_M (Local CPU) | 72/80 | 90.0% | [81.5%, 94.8%] | [82.5%, 96.2%] |
| FormulaLM Q5_K_M (Local CPU) | 75/80 | 93.8% | [86.2%, 97.3%] | [87.5%, 98.8%] |
| FormulaLM Q4_K_M (Colab) | 71/80 | 88.8% | [80.0%, 94.0%] | [81.2%, 95.0%] |
| FormulaLM Q5_K_M (Colab) | 75/80 | 93.8% | [86.2%, 97.3%] | [87.5%, 98.8%] |

### Paired Exact McNemar's Tests

| System A vs System B | Delta | A-only / B-only | Exact p-value | Significant (p<0.05) |
|---|---:|---:|---:|---|
| FormulaLM Q5_K_M (Local CPU) vs FormulaLM Q4_K_M (Local CPU) | +3.8 pp | 4 / 1 | `p = 0.3750` | No |
| FormulaLM Q5_K_M (Colab) vs FormulaLM Q4_K_M (Colab) | +5.0 pp | 5 / 1 | `p = 0.2188` | No |

## `external_spreadsheetbench` (N = 56)

| System | Correct | Accuracy | 95% Wilson CI | 95% Bootstrap CI |
|---|---:|---:|---:|---:|
| Base Qwen3-1.7B (0-shot, CPU) | 6/56 | 10.7% | [5.0%, 21.5%] | [3.6%, 19.6%] |
| Base Qwen3-1.7B (5-shot, CPU) | 6/56 | 10.7% | [5.0%, 21.5%] | [3.6%, 19.6%] |
| FormulaLM Q5_K_M (0-shot, CPU) | 12/56 | 21.4% | [12.7%, 33.8%] | [10.7%, 32.1%] |

### Paired Exact McNemar's Tests

| System A vs System B | Delta | A-only / B-only | Exact p-value | Significant (p<0.05) |
|---|---:|---:|---:|---|
| FormulaLM Q5_K_M (0-shot, CPU) vs Base Qwen3-1.7B (0-shot, CPU) | +10.7 pp | 9 / 3 | `p = 0.1460` | No |
| FormulaLM Q5_K_M (0-shot, CPU) vs Base Qwen3-1.7B (5-shot, CPU) | +10.7 pp | 9 / 3 | `p = 0.1460` | No |

## `external_spreadsheetbench_syntax` (N = 56)

| System | Correct | Accuracy | 95% Wilson CI | 95% Bootstrap CI |
|---|---:|---:|---:|---:|
| Base Qwen3-1.7B (0-shot, CPU) | 38/56 | 67.9% | [54.8%, 78.6%] | [55.4%, 80.4%] |
| Base Qwen3-1.7B (5-shot, CPU) | 36/56 | 64.3% | [51.2%, 75.5%] | [51.8%, 76.8%] |
| FormulaLM Q5_K_M (0-shot, CPU) | 50/56 | 89.3% | [78.5%, 95.0%] | [80.4%, 96.4%] |

### Paired Exact McNemar's Tests

| System A vs System B | Delta | A-only / B-only | Exact p-value | Significant (p<0.05) |
|---|---:|---:|---:|---|
| FormulaLM Q5_K_M (0-shot, CPU) vs Base Qwen3-1.7B (0-shot, CPU) | +21.4 pp | 15 / 3 | `p = 0.0075` | Yes |
| FormulaLM Q5_K_M (0-shot, CPU) vs Base Qwen3-1.7B (5-shot, CPU) | +25.0 pp | 16 / 2 | `p = 0.0013` | Yes |

## `quant_val_500` (N = 500)

| System | Correct | Accuracy | 95% Wilson CI | 95% Bootstrap CI |
|---|---:|---:|---:|---:|
| FormulaLM Q4_K_M (Colab) | 487/500 | 97.4% | [95.6%, 98.5%] | [96.0%, 98.6%] |
| FormulaLM Q5_K_M (Colab) | 498/500 | 99.6% | [98.6%, 99.9%] | [99.0%, 100.0%] |

### Paired Exact McNemar's Tests

| System A vs System B | Delta | A-only / B-only | Exact p-value | Significant (p<0.05) |
|---|---:|---:|---:|---|
| FormulaLM Q5_K_M (Colab) vs FormulaLM Q4_K_M (Colab) | +2.2 pp | 11 / 0 | `p = 0.0010` | Yes |

## `quant_synthetic_500` (N = 500)

| System | Correct | Accuracy | 95% Wilson CI | 95% Bootstrap CI |
|---|---:|---:|---:|---:|
| FormulaLM Q4_K_M (Colab) | 477/500 | 95.4% | [93.2%, 96.9%] | [93.4%, 97.2%] |
| FormulaLM Q5_K_M (Colab) | 492/500 | 98.4% | [96.9%, 99.2%] | [97.2%, 99.4%] |

### Paired Exact McNemar's Tests

| System A vs System B | Delta | A-only / B-only | Exact p-value | Significant (p<0.05) |
|---|---:|---:|---:|---|
| FormulaLM Q5_K_M (Colab) vs FormulaLM Q4_K_M (Colab) | +3.0 pp | 18 / 3 | `p = 0.0015` | Yes |
