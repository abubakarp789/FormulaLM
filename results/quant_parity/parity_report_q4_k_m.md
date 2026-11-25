# Prompt-Format & Output Parity Report: HF Merged FP16 vs GGUF Q4_K_M

Evaluated on **20 fixed examples** (`temperature=0`, `seed=42`, `enable_thinking=False`).

| Metric | Count | Rate |
|---|---:|---:|
| Raw output exact match | 19/20 | 95.0% |
| Normalized formula match | 19/20 | 95.0% |
| Executed value agreement | 20/20 | 100.0% |
| HF Merged FP16 execution accuracy | 19/20 | 95.0% |
| GGUF Q4_K_M execution accuracy | 19/20 | 95.0% |

## Differences (1 example(s))

- **`real_v2_009`** (`sales_retail_store`): Sum Net Amount for sales on or after 2026-01-01
  - Ground truth: `=SUMIF(B2:B115,">="&DATE(2026,1,1),F2:F115)`
  - HF Merged FP16: `=SUMIF(B2:B115,">="&DATE(2026,1,1),F2:F115)` (exec_correct=True)
  - GGUF Q4_K_M: `=SUMIF(B2:B115,">=2026-01-01",F2:F115)` (exec_correct=True)
