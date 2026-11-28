# External Real-Workbook Benchmark (`SpreadsheetBench Verified 400`, In-Scope Single-Sheet Subset)

- **Source:** `KAKA22/SpreadsheetBench` (`spreadsheetbench_verified_400.tar.gz`, NeurIPS 2024, `CC-BY-SA-4.0`, pinned `ab0b742b`), real MrExcel/ExcelForum human-authored workbooks & questions.
- **Integrity:** Filtered deterministically to single-sheet `Cell-Level Manipulation` formulas using FormulaLM's 36 allowed non-volatile functions (`<= 20` columns, verified gold execution), SHA-256 frozen in `data/external_bench/manifest.sha256` before any inference.
- **Local runtime:** Windows 11 laptop (`Intel Core i5-8365U`, `8 GB RAM`, CPU-only, `Ollama 0.40.18`), `think=False`, `temperature=0`, `seed=42`, `num_ctx=4096`, `num_predict=96`.

| System | N | Correct | **Exec. Accuracy (95% Wilson CI)** | Exact Match | Syntax Valid | Single-Cell | Col-Fill | Avg Latency | Gen tok/s | Peak RAM |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| Base `Qwen3-1.7B` (0-shot, Ollama Q4_K_M) | 56 | 6/56 | **10.7%** `[5.0%, 21.5%]` | 1.8% | 67.9% | 2/11 (18.2%) | 4/45 (8.9%) | 10.89 s | 9.8 | 2986 MB |
| Base `Qwen3-1.7B` (5-shot, Ollama Q4_K_M) | 56 | 6/56 | **10.7%** `[5.0%, 21.5%]` | 3.6% | 64.3% | 1/11 (9.1%) | 5/45 (11.1%) | 11.65 s | 8.8 | 2012 MB |
| **FormulaLM `Q5_K_M` (Shipped 1.7B, 0-shot)** | 56 | 12/56 | **21.4%** `[12.7%, 33.8%]` | 1.8% | 89.3% | 3/11 (27.3%) | 9/45 (20.0%) | 12.16 s | 9.0 | 2006 MB |

## Sample Real-Workbook Wins (FormulaLM Correct, Base 1.7B 0-shot Wrong)

- **`ssb_1563`** (`Sheet1!B2`): FormulaLM `=IF(A2="","",A2)` → `Red` (expected `Red`); Base 1.7B `=IF(ISBLANK(A2), LOOKUP(2, MATCH(ROW(A2)-ROW(A1)+1, ROW(A1: A2)-ROW(A1)+1, 0), A2: A2), A2)` (`unsupported_function`)
- **`ssb_32255`** (`Sheet1!D2`): FormulaLM `=IF(A10<>"",D10,0)` → `0` (expected `0`); Base 1.7B `=D2` (`runtime_error`)
- **`ssb_40959`** (`Sheet1!C2`): FormulaLM `=IF(AND(A2="Sales",B2=""), "Sales", IF(AND(A2="Sales-Marketing",B2=""), "Marketing", IF(AND(A2="Sales",B2="General"), "Marketing", "")))` → `Sales` (expected `Sales`); Base 1.7B `=IF(A2="Sales", "", IF(ISERROR(SEARCH("-",A2,1)), "Sales", "Marketing"))` (`unsupported_function`)
- **`ssb_46167`** (`Sheet1!D2`): FormulaLM `=SUMIF(A2:A12,"111111",B2:B12)` → `270.0` (expected `270`); Base 1.7B `=SUMIFS(D2:D12, A2:A12, "111111", B2:B12, ">=70")` (`runtime_error`)
- **`ssb_47933`** (`master!E2`): FormulaLM `=IF(B2<37.5,D2*2,D2*1.5)` → `27.915` (expected `27.915`); Base 1.7B `=IF(B2<37.5,*D2,1.5*D2)` (`False`)

## Sample Real-Workbook Failures (Honest Error Analysis)

- **`ssb_10747`** (`גיליון1!K6`): Pred `=IF((@$A$3:$A$8=$I3)*(@$B$3:$B$8=$J3),SUM(C3:C8),0)` → `0` (`None`); Ref `=SUMIFS(C3:C8,A3:A8,I3,B3:B8,J3)` → `-10600`
- **`ssb_16511`** (`Sheet1!F2`): Pred `=F2+1` → `None` (`runtime_error`); Ref `=COUNTIF($D$2:D2,D2)` → `1`
- **`ssb_3002`** (`Sheet1!G5`): Pred `=IF(OR(E5="Mat Doc",F5="Doc No"),"Remark",IF(AND(E5="1941546513",F5="90176278"),"Multiple",IF(AND(E5="1941546513",F5="90176279"),"Multiple",IF(AND(E5="1941546514` → `None` (`syntax_error`); Ref `=IF(COUNTIFS($E$5:$E$15,E5,$F$5:$F$15,F5)>1,"Multiple","Single")` → `Multiple`
- **`ssb_31202`** (`NOMINA!J2`): Pred `=IF(G2>0,"+"&G2,"-"&G2)` → `-0` (`None`); Ref `=SUMIFS(H$2:H2,D$2:D2,D2)-SUMIFS(G$2:G2,D$2:D2,D2)` → `0`
- **`ssb_32293`** (`Sheet1!B14`): Pred `=IF(A14="MNQ",B1,B14)=IF(A14="MES",B2,B14)=IF(A14="NQ",B3,B14)=IF(A14="ES",B4,B14)` → `None` (`runtime_error`); Ref `=INDEX($B$1:$B$4,MATCH(A14,$A$1:$A$4,0))` → `0.56`
