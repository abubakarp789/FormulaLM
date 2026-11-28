# SpreadsheetBench Verified 400 Subset (N = 56): Error & Pattern Taxonomy

All 56 frozen tasks use functions within the 36-function Excel allow-list. Overall headline accuracy remains **12/56 (21.4%)** for FormulaLM `Q5_K_M` vs **6/56 (10.7%)** for Base `Qwen3-1.7B` (0-shot and 5-shot). The tables below decompose *every* prediction and *every* task without filtering.

## 1. Mutually Exclusive Outcome & Failure Breakdown (All 56 Tasks)

| Outcome / Failure Mode | Base 1.7B (0-shot) | Base 1.7B (5-shot) | FormulaLM Q5_K_M |
|---|---:|---:|---:|
| Correct (execution match) | 6 (10.7%) | 6 (10.7%) | 12 (21.4%) |
| Valid execution, wrong range/logic | 15 (26.8%) | 16 (28.6%) | 22 (39.3%) |
| Circular reference to target cell | 15 (26.8%) | 13 (23.2%) | 13 (23.2%) |
| Syntax / parse error | 6 (10.7%) | 7 (12.5%) | 4 (7.1%) |
| Unsupported / out-of-allowlist function | 12 (21.4%) | 13 (23.2%) | 2 (3.6%) |
| Runtime Excel error (#N/A, #VALUE!) | 2 (3.6%) | 1 (1.8%) | 3 (5.4%) |
| Non-formula output | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| **Total** | **56** | **56** | **56** |

Key takeaways:
- **Unsupported/hallucinated functions dropped 6x:** 12 (0-shot) / 13 (5-shot) -> **2** with FormulaLM.
- **Syntax errors fell** from 6 / 7 -> **4** (`89.3%` overall syntax validity).
- **Circular target-cell references** (`13/56`) remain the largest structural failure on multi-row `col_fill_first_cell` sheets.

## 2. Structural Pattern Breakdown (Trained Grammar vs Untrained Excel Idioms)

| Task Structural Pattern | N | Base 1.7B (0-shot) | Base 1.7B (5-shot) | FormulaLM Q5_K_M |
|---|---:|---:|---:|---:|
| Standard single-formula patterns (trained grammar) | 37 | 6/37 (16.2%) | 5/37 (13.5%) | 11/37 (29.7%) |
| Drag-down running anchored window ($D$2:D2) | 6 | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) |
| 2D matrix lookup (INDEX + dual MATCH) | 5 | 0/5 (0.0%) | 0/5 (0.0%) | 0/5 (0.0%) |
| Dynamic wildcard criteria ("*"&cell&"*") | 4 | 0/4 (0.0%) | 1/4 (25.0%) | 1/4 (25.0%) |
| Boolean array multiplication ((A=x)*(B=y)) | 2 | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Deep nested IF chains (3+ nested IFs) | 2 | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |

### Scope Summary

- **Trained single-formula grammar (`N = 37`):** Base 0-shot `6/37` (`16.2%`), Base 5-shot `5/37` (`13.5%`), **FormulaLM `Q5_K_M` `11/37` (`29.7%`)**.
- **Untrained structural idioms (`N = 19` — 2D matrix INDEX/MATCH/MATCH, drag-down running anchors, CSE boolean arrays, dynamic wildcards, 3+ nested IFs):** Base 0-shot `0/19` (`0.0%`), Base 5-shot `1/19` (`5.3%`), FormulaLM `Q5_K_M` `1/19` (`5.3%`).
