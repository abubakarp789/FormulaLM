# Evaluation Report: `ft_v1_synthetic`

- **Backend:** `transformers:Qwen/Qwen3-1.7B+/content/drive/MyDrive/FormulaLM/qlora_v1/adapter`
- **Dataset:** `data/processed/test_synthetic.jsonl` (500 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=0`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 500 |
| Syntax valid rate | 99.6% |
| Execution success rate (no runtime error) | 99.6% |
| **Execution accuracy** | **97.6%** |
| Normalized exact match | 97.0% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 794.7 ms |
| Median / p95 latency | 789.1 ms / 961.4 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 97.2% | 95.8% | 95.8% | 778.6 ms |
| `conditional_aggregation` | 72 | 100.0% | 98.6% | 98.6% | 793.0 ms |
| `date` | 72 | 100.0% | 95.8% | 95.8% | 810.8 ms |
| `logic` | 71 | 100.0% | 100.0% | 100.0% | 791.1 ms |
| `lookup` | 71 | 100.0% | 100.0% | 98.6% | 786.7 ms |
| `math_and_composition` | 71 | 100.0% | 95.8% | 94.4% | 811.7 ms |
| `text` | 71 | 100.0% | 97.2% | 95.8% | 791.1 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 180 | 99.4% | 97.8% | 97.2% | 780.7 ms |
| 2 | 179 | 100.0% | 98.3% | 98.3% | 789.8 ms |
| 3 | 141 | 99.3% | 96.5% | 95.0% | 818.9 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `unsupported_function` | 2 |
| `wrong_value` | 10 |

## Sample Failures (up to 10)

- **`test_syn_00006`** (`orders_ecommerce`, `math_and_composition`/D3): Did Channel 'Web' beat a Item Count target of 117.6? Return 'Met' or 'Missed'.
  - Reference: `=IF(SUMIF(D2:D57,"Web",F2:F57)>117.6,"Met","Missed")` → `'Missed'`
  - Predicted: `=IF(OR(D2="Web",F2>117.6),"Met","Missed")` → `'Met'` (error: `wrong_value`)
- **`test_syn_00013`** (`orders_ecommerce`, `math_and_composition`/D2): Compute the arithmetic mean of the Item Count column and round the result to 2 decimal place(s).
  - Reference: `=ROUND(AVERAGE(F2:F57),2)` → `7.59`
  - Predicted: `=AVERAGE(F2:F57)` → `7.589285714285714` (error: `wrong_value`)
- **`test_syn_00037`** (`grades_course_scores`, `math_and_composition`/D3): Did Subject 'Computing' beat a Assignments Done target of 127.2? Return 'Above Target' or 'Below Target'.
  - Reference: `=IF(SUMIF(C2:C108,"Computing",F2:F108)>127.2,"Above Target","Below Target")` → `'Below Target'`
  - Predicted: `=IF(OR(SUMIF(C2:C108,"Computing",F2:F108)>127.2,SUMIF(C2:C108,"Computing",F2:F108)<127.2),"Above Target","Below Target")` → `'Above Target'` (error: `wrong_value`)
- **`test_syn_00074`** (`grades_course_scores`, `aggregation`/D3): What is total Assignments Done per unit of total Final Score (return 0 if division fails)?
  - Reference: `=IFERROR(SUM(F2:F108)/SUM(G2:G108),0)` → `0.09132499521630978`
  - Predicted: `=IFERROR(SUMIF(G2:G108,"*",$F2:F108)/SUM(G2:G108),0)` → `0.003044166507210326` (error: `wrong_value`)
- **`test_syn_00085`** (`grades_course_scores`, `conditional_aggregation`/D3): sum Final Score where Section=Sec B & Subject=Math
  - Reference: `=SUMIFS(G2:G108,D2:D108,"Sec B",C2:C108,"Math")` → `497.3`
  - Predicted: `=SUMIFS(G2:G108,C2:C108,"Sec B",C2:C108,"Math")` → `0.0` (error: `wrong_value`)
- **`test_syn_00117`** (`orders_ecommerce`, `date`/D1): Return the 4-digit calendar year of the date stored in Order Date at row 30.
  - Reference: `=YEAR(B30)` → `2025`
  - Predicted: `=TEXT(B30,"yyyy")` → `'2025'` (error: `wrong_value`)
- **`test_syn_00163`** (`sales_retail_store`, `date`/D1): Return the 4-digit calendar year of the date stored in Sale Date at row 29.
  - Reference: `=YEAR(B29)` → `2026`
  - Predicted: `=TEXT(B29,"yyyy")` → `'2026'` (error: `wrong_value`)
- **`test_syn_00205`** (`sales_retail_store`, `date`/D1): Return the 4-digit calendar year of the date stored in Sale Date at row 112.
  - Reference: `=YEAR(B112)` → `2025`
  - Predicted: `=TEXT(B112,"yyyy")` → `'2025'` (error: `wrong_value`)
- **`test_syn_00312`** (`orders_ecommerce`, `text`/D2): List the Channel entries from row 2 to 5 joined by '; ' (skip empty cells).
  - Reference: `=TEXTJOIN("; ",TRUE,D2:D5)` → `'Web; Marketplace; Phone; Marketplace'`
  - Predicted: `=TEXTJOIN("; ",TRUE,D2:D57)` → `'Web; Marketplace; Phone; Marketplace; Mobile App; Marketplace; Phone; Marketplace; Marketplace; Web; Mobile App; Web; Web; Marketplace; Web; Marketplace; Marketplace; Mobile App; Web; Phone; Phone; Marketplace; Marketplace; Web; Marketplace; Mobile App; Marketplace; Phone; Phone; Marketplace; Web; Mobile App; Web; Marketplace; Phone; Mobile App; Mobile App; Web; Mobile App; Web; Mobile App; Web; Mobile App; Phone; Phone; Web; Mobile App; Web; Phone; Mobile App; Web; Web; Web; Mobile App; Phone; Mobile App'` (error: `wrong_value`)
- **`test_syn_00366`** (`sales_retail_store`, `aggregation`/D3): What is total Quantity per unit of total Net Amount (return 0 if division fails)?
  - Reference: `=IFERROR(SUM(E2:E115)/SUM(F2:F115),0)` → `0.02930076900478282`
  - Predicted: `=SUMPRODUCT(E2:E115)/SUM(F2:F115)` → `None` (error: `unsupported_function`)
