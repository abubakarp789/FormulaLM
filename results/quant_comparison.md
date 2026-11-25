# FormulaLM — Quantization & Local Benchmark Comparison (`v2-ship`)

## Shipping Recommendation

- **Status:** **`PENDING`**
- **Selected:** `pending measured data`
- **Rationale:** Missing F16 reference runs (val, real_v2, real, synthetic). Run notebooks/05_merge_quantize.ipynb first.
- **Rule:** ship the smallest quantization whose execution accuracy stays within sampling noise of merged `F16` (95% Wilson CIs overlap `F16`, drop ≤ 1.5 pp on `val`/`test_synthetic` and ≤ 2.5 pp on `test_real_v2`/`test_real`) and fits safely in laptop RAM.

## 1. Execution Accuracy Across Splits (with 95% Wilson CIs)

\* _All v2-ship results on `test_real` and `test_synthetic` are **informed by v1 error analysis**._

| System | Size (MB) | `val` (500) | `test_real_v2` (50) | `test_real` (80)* | `test_synthetic` (500)* |
|---|---:|---|---|---|---|
| Base `Qwen3-1.7B` (0-shot, fp16) | — | _n/a_ | **46.0%** [33.0%, 59.6%] | **50.0%** [39.3%, 60.7%] | **44.6%** [40.3%, 49.0%] |
| Base `Qwen3-1.7B` (5-shot, fp16) | — | _n/a_ | **58.0%** [44.2%, 70.6%] | **51.2%** [40.5%, 61.9%] | **60.2%** [55.9%, 64.4%] |
| v2-ship Merged `F16` GGUF | — | _pending_ | _pending_ | _pending_ | _pending_ |
| v2-ship `Q8_0` GGUF | — | _pending_ | _pending_ | _pending_ | _pending_ |
| v2-ship `Q5_K_M` GGUF | — | _pending_ | _pending_ | _pending_ | _pending_ |
| v2-ship `Q4_K_M` GGUF | — | _pending_ | _pending_ | _pending_ | _pending_ |

## 3. Local Laptop Performance (Windows 11, i5-8365U, 8 GB RAM, CPU-only)

| Quantization | Status | Size (MB) | Load (s) | Peak RAM (MB) | Gen tok/s | Local 130-ex Exec. Acc (95% CI) |
|---|---|---:|---:|---:|---:|---|
| v2-ship `Q4_K_M` GGUF | _pending_ | — | — | — | — | _pending_ |
| v2-ship `Q5_K_M` GGUF | _pending_ | — | — | — | — | _pending_ |
| v2-ship `Q8_0` GGUF | _pending_ | — | — | — | — | _pending_ |

## 4. Prompt-Format Parity (HF Merged FP16 vs GGUF F16, 20 fixed examples)

_Pending: run Cell 5 of `notebooks/05_merge_quantize.ipynb`._
