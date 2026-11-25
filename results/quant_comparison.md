# FormulaLM — Quantization & Local Benchmark Comparison (`v2-ship`)

## Shipping Recommendation

- **Status:** **`RECOMMENDED`**
- **Selected:** `v2-ship `Q5_K_M` GGUF`
- **Rationale:** v2-ship `Q5_K_M` GGUF is the smallest quantization within sampling noise of F16 on all 4 splits.
- **Rule:** ship the smallest quantization whose execution accuracy stays within sampling noise of merged `F16` (95% Wilson CIs overlap `F16`, drop ≤ 1.5 pp on `val`/`test_synthetic` and ≤ 2.5 pp on `test_real_v2`/`test_real`) and fits safely in laptop RAM.

## 1. Execution Accuracy Across Splits (with 95% Wilson CIs)

\* _All v2-ship results on `test_real` and `test_synthetic` are **informed by v1 error analysis**._

| System | Size (MB) | `val` (500) | `test_real_v2` (50) | `test_real` (80)* | `test_synthetic` (500)* |
|---|---:|---|---|---|---|
| Base `Qwen3-1.7B` (0-shot, fp16) | — | _n/a_ | **46.0%** [33.0%, 59.6%] | **50.0%** [39.3%, 60.7%] | **44.6%** [40.3%, 49.0%] |
| Base `Qwen3-1.7B` (5-shot, fp16) | — | _n/a_ | **58.0%** [44.2%, 70.6%] | **51.2%** [40.5%, 61.9%] | **60.2%** [55.9%, 64.4%] |
| v2-ship Merged `F16` GGUF | 3287.7 | **99.8%** [98.9%, 100.0%] | **88.0%** [76.2%, 94.4%] | **93.8%** [86.2%, 97.3%] | **98.8%** [97.4%, 99.5%] |
| v2-ship `Q8_0` GGUF | 1749.5 | **99.8%** [98.9%, 100.0%] | **86.0%** [73.8%, 93.0%] | **93.8%** [86.2%, 97.3%] | **98.6%** [97.1%, 99.3%] |
| v2-ship `Q5_K_M` GGUF | 1199.6 | **99.6%** [98.6%, 99.9%] | **90.0%** [78.6%, 95.7%] | **93.8%** [86.2%, 97.3%] | **98.4%** [96.9%, 99.2%] |
| v2-ship `Q4_K_M` GGUF | 1056.1 | **97.4%** [95.6%, 98.5%] | **90.0%** [78.6%, 95.7%] | **88.8%** [80.0%, 94.0%] | **95.4%** [93.2%, 96.9%] |

## 2. Delta vs Merged F16 Reference

| Quantization | Size vs F16 | Δ `val` | Δ `test_real_v2` | Δ `test_real`* | Δ `test_synthetic`* |
|---|---:|---:|---:|---:|---:|
| v2-ship `Q8_0` GGUF | 53% | +0.0 pp | -2.0 pp | +0.0 pp | -0.2 pp |
| v2-ship `Q5_K_M` GGUF | 36% | -0.2 pp | +2.0 pp | +0.0 pp | -0.4 pp |
| v2-ship `Q4_K_M` GGUF | 32% | -2.4 pp | +2.0 pp | -5.0 pp | -3.4 pp |

## 3. Local Laptop Performance (Windows 11, i5-8365U, 8 GB RAM, CPU-only)

| Quantization | Status | Size (MB) | Load (s) | Peak RAM (MB) | Gen tok/s | Local 130-ex Exec. Acc (95% CI) |
|---|---|---:|---:|---:|---:|---|
| v2-ship `Q4_K_M` GGUF | ok (ollama) | 1056.1 | 4.60 | 1333 | 12.7 | **89.2%** (116/130, [82.7%, 93.5%]) |
| v2-ship `Q5_K_M` GGUF | ok (ollama) | 1199.6 | 2.64 | 1476 | 11.3 | **90.8%** (118/130, [84.6%, 94.6%]) |
| v2-ship `Q8_0` GGUF | ok (ollama) | 1749.5 | 5.93 | 2026 | 7.8 | **91.5%** (119/130, [85.5%, 95.2%]) |

## 4. Prompt-Format Parity (HF Merged FP16 vs GGUF F16, 20 fixed examples)

- Raw exact match: **20/20** (100.0%)
- Normalized formula match: **20/20** (100.0%)
- Executed value agreement: **20/20** (100.0%)
- Full diff log: `results/quant_parity/parity_report.md`
