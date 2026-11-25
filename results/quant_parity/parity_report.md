# Prompt-Format & Output Parity Report: HF Merged FP16 vs GGUF F16

Evaluated on **20 fixed examples** (`temperature=0`, `seed=42`, `enable_thinking=False`).

| Metric | Count | Rate |
|---|---:|---:|
| Raw output exact match | 20/20 | 100.0% |
| Normalized formula match | 20/20 | 100.0% |
| Executed value agreement | 20/20 | 100.0% |
| HF Merged FP16 execution accuracy | 19/20 | 95.0% |
| GGUF F16 execution accuracy | 19/20 | 95.0% |

**Result:** 100% parity — zero differences across all 20 fixed examples.
