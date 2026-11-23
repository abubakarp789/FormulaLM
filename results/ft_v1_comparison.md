# Comparison & Error Analysis: Base vs Fine-tuned v1

## 1. Overall Comparison

| Test Set | System | N | Syntax Valid | **Exec. Accuracy** | Δ vs 0-shot | Exact Match | Raw Format | Avg Latency |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `test_synthetic` | Base zero-shot | 500 | 71.8% | **44.6%** | — | 36.6% | 100.0% | 814.0 ms |
| `test_synthetic` | Base 5-shot | 500 | 85.0% | **60.2%** | +15.6 pp | 51.2% | 100.0% | 1728.2 ms |
| `test_synthetic` | **Fine-tuned v1** | 500 | 99.6% | **97.6%** | +53.0 pp | 97.0% | 100.0% | 794.7 ms |
| `test_real` | Base zero-shot | 80 | 81.2% | **50.0%** | — | 42.5% | 100.0% | 651.7 ms |
| `test_real` | Base 5-shot | 80 | 85.0% | **51.2%** | +1.2 pp | 41.2% | 100.0% | 1576.2 ms |
| `test_real` | **Fine-tuned v1** | 80 | 100.0% | **91.2%** | +41.2 pp | 91.2% | 100.0% | 789.9 ms |

## 2A. Execution Accuracy by Category (`test_synthetic`)

| Category | N | Base 0-shot | Base 5-shot | **Fine-tuned v1** | Δ vs 0-shot |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 72 | 65.3% | 65.3% | **95.8%** | +30.6 pp |
| `conditional_aggregation` | 72 | 23.6% | 58.3% | **98.6%** | +75.0 pp |
| `date` | 72 | 56.9% | 79.2% | **95.8%** | +38.9 pp |
| `logic` | 71 | 69.0% | 69.0% | **100.0%** | +31.0 pp |
| `lookup` | 71 | 4.2% | 40.8% | **100.0%** | +95.8 pp |
| `math_and_composition` | 71 | 52.1% | 57.8% | **95.8%** | +43.7 pp |
| `text` | 71 | 40.8% | 50.7% | **97.2%** | +56.3 pp |

## 2B. Execution Accuracy by Category (`test_real`)

| Category | N | Base 0-shot | Base 5-shot | **Fine-tuned v1** | Δ vs 0-shot |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 12 | 83.3% | 58.3% | **100.0%** | +16.7 pp |
| `conditional_aggregation` | 21 | 33.3% | 38.1% | **85.7%** | +52.4 pp |
| `date` | 9 | 55.6% | 77.8% | **88.9%** | +33.3 pp |
| `logic` | 10 | 60.0% | 60.0% | **100.0%** | +40.0 pp |
| `lookup` | 9 | 11.1% | 33.3% | **100.0%** | +88.9 pp |
| `math_and_composition` | 8 | 37.5% | 25.0% | **75.0%** | +37.5 pp |
| `text` | 11 | 72.7% | 72.7% | **90.9%** | +18.2 pp |

## 3A. Execution Accuracy by Difficulty (`test_synthetic`)

| Difficulty | N | Base 0-shot | Base 5-shot | **Fine-tuned v1** | Δ vs 0-shot |
|---|---:|---:|---:|---:|---:|
| Difficulty 1 | 180 | 47.2% | 84.4% | **97.8%** | +50.6 pp |
| Difficulty 2 | 179 | 48.0% | 50.8% | **98.3%** | +50.3 pp |
| Difficulty 3 | 141 | 36.9% | 41.1% | **96.5%** | +59.6 pp |

## 3B. Execution Accuracy by Difficulty (`test_real`)

| Difficulty | N | Base 0-shot | Base 5-shot | **Fine-tuned v1** | Δ vs 0-shot |
|---|---:|---:|---:|---:|---:|
| Difficulty 1 | 29 | 69.0% | 75.9% | **100.0%** | +31.0 pp |
| Difficulty 2 | 33 | 48.5% | 36.4% | **90.9%** | +42.4 pp |
| Difficulty 3 | 18 | 22.2% | 38.9% | **77.8%** | +55.6 pp |

## 4. Error Analysis — Fine-tuned v1 Failures (19 total across both test sets)

| Cluster | Total | Share | `test_synthetic` | `test_real` |
|---|---:|---:|---:|---:|
| `wrong_function` | 8 | 42.1% | 7 | 1 |
| `wrong_aggregation` | 4 | 21.1% | 2 | 2 |
| `wrong_column` | 4 | 21.1% | 1 | 3 |
| `wrong_argument_order` | 3 | 15.8% | 2 | 1 |
| `over_generation` | 0 | 0.0% | 0 | 0 |
| `syntax_error` | 0 | 0.0% | 0 | 0 |

### Cluster: `wrong_function` (8 failures — 7 synthetic, 1 real)

1. **`real_048`** (`test_real`, `inventory_stock_movements`, `math_and_composition`/D2): valuation per unit on row 2 (return 0 if error)
   - Ref: `=IFERROR(G2/F2,0)` → `20.663299492385786`
   - Pred: `=IFERROR(VLOOKUP(A2,Sheet1!A:E,7,FALSE),0)` → `0` (`wrong_value`)
2. **`test_syn_00006`** (`test_synthetic`, `orders_ecommerce`, `math_and_composition`/D3): Did Channel 'Web' beat a Item Count target of 117.6? Return 'Met' or 'Missed'.
   - Ref: `=IF(SUMIF(D2:D57,"Web",F2:F57)>117.6,"Met","Missed")` → `'Missed'`
   - Pred: `=IF(OR(D2="Web",F2>117.6),"Met","Missed")` → `'Met'` (`wrong_value`)
3. **`test_syn_00037`** (`test_synthetic`, `grades_course_scores`, `math_and_composition`/D3): Did Subject 'Computing' beat a Assignments Done target of 127.2? Return 'Above Target' or 'Below Target'.
   - Ref: `=IF(SUMIF(C2:C108,"Computing",F2:F108)>127.2,"Above Target","Below Target")` → `'Below Target'`
   - Pred: `=IF(OR(SUMIF(C2:C108,"Computing",F2:F108)>127.2,SUMIF(C2:C108,"Computing",F2:F108)<127.2),"Above Target","Below Target")` → `'Above Target'` (`wrong_value`)
4. **`test_syn_00117`** (`test_synthetic`, `orders_ecommerce`, `date`/D1): Return the 4-digit calendar year of the date stored in Order Date at row 30.
   - Ref: `=YEAR(B30)` → `2025`
   - Pred: `=TEXT(B30,"yyyy")` → `'2025'` (`wrong_value`)
5. **`test_syn_00163`** (`test_synthetic`, `sales_retail_store`, `date`/D1): Return the 4-digit calendar year of the date stored in Sale Date at row 29.
   - Ref: `=YEAR(B29)` → `2026`
   - Pred: `=TEXT(B29,"yyyy")` → `'2026'` (`wrong_value`)

### Cluster: `wrong_aggregation` (4 failures — 2 synthetic, 2 real)

1. **`real_038`** (`test_real`, `inventory_stock_movements`, `conditional_aggregation`/D3): total valuation of Outbound movements in Zone A
   - Ref: `=SUMIFS(G2:G106,D2:D106,"Outbound",E2:E106,"Zone A")` → `58629.53`
   - Pred: `=SUMIF(E2:E106,"A",G2:G106)` → `0.0` (`wrong_value`)
2. **`real_054`** (`test_real`, `grades_course_scores`, `conditional_aggregation`/D2): how many Math students are in Sec A?
   - Ref: `=COUNTIFS(C2:C108,"Math",D2:D108,"Sec A")` → `7`
   - Pred: `=COUNTIFS(C2:C108,"Math",D2:D108,"A")` → `0` (`wrong_value`)
3. **`test_syn_00013`** (`test_synthetic`, `orders_ecommerce`, `math_and_composition`/D2): Compute the arithmetic mean of the Item Count column and round the result to 2 decimal place(s).
   - Ref: `=ROUND(AVERAGE(F2:F57),2)` → `7.59`
   - Pred: `=AVERAGE(F2:F57)` → `7.589285714285714` (`wrong_value`)
4. **`test_syn_00074`** (`test_synthetic`, `grades_course_scores`, `aggregation`/D3): What is total Assignments Done per unit of total Final Score (return 0 if division fails)?
   - Ref: `=IFERROR(SUM(F2:F108)/SUM(G2:G108),0)` → `0.09132499521630978`
   - Pred: `=IFERROR(SUMIF(G2:G108,"*",$F2:F108)/SUM(G2:G108),0)` → `0.003044166507210326` (`wrong_value`)

### Cluster: `wrong_column` (4 failures — 1 synthetic, 3 real)

1. **`real_047`** (`test_real`, `inventory_stock_movements`, `date`/D3): total Outbound units moved on or after 2025-10-01
   - Ref: `=SUMIFS(F2:F106,D2:D106,"Outbound",B2:B106,">="&DATE(2025,10,1))` → `1062.0`
   - Pred: `=SUMIFS(F2:F106,B2:B106,"Outbound",B2:B106,">="&DATE(2025,10,1))` → `0.0` (`wrong_value`)
2. **`real_068`** (`test_real`, `orders_ecommerce`, `conditional_aggregation`/D3): total order amount for Web orders that were Delivered
   - Ref: `=SUMIFS(G2:G57,D2:D57,"Web",E2:E57,"Delivered")` → `2416.8399999999997`
   - Pred: `=SUMIFS(G2:G57,E2:E57,"Web",H2:H57,"Delivered")` → `0.0` (`wrong_value`)
3. **`real_079`** (`test_real`, `orders_ecommerce`, `math_and_composition`/D3): say 'Goal Hit' if total Delivered order value beats 5000, else 'Short'
   - Ref: `=IF(SUMIF(E2:E57,"Delivered",G2:G57)>5000,"Goal Hit","Short")` → `'Goal Hit'`
   - Pred: `=IF(SUMIF(D2:D57,"Delivered",G2:G57)>5000,"Goal Hit","Short")` → `'Short'` (`wrong_value`)
4. **`test_syn_00085`** (`test_synthetic`, `grades_course_scores`, `conditional_aggregation`/D3): sum Final Score where Section=Sec B & Subject=Math
   - Ref: `=SUMIFS(G2:G108,D2:D108,"Sec B",C2:C108,"Math")` → `497.3`
   - Pred: `=SUMIFS(G2:G108,C2:C108,"Sec B",C2:C108,"Math")` → `0.0` (`wrong_value`)

### Cluster: `wrong_argument_order` (3 failures — 2 synthetic, 1 real)

1. **`real_014`** (`test_real`, `sales_retail_store`, `text`/D2): combine branch and item name on row 3 like 'Branch: Item' using concat
   - Ref: `=CONCAT(C3,": ",D3)` → `'Suncroft: Foldable Stand'`
   - Pred: `=CONCAT("Branch:",D3,"-",C3)` → `'Branch:Foldable Stand-Suncroft'` (`wrong_value`)
2. **`test_syn_00312`** (`test_synthetic`, `orders_ecommerce`, `text`/D2): List the Channel entries from row 2 to 5 joined by '; ' (skip empty cells).
   - Ref: `=TEXTJOIN("; ",TRUE,D2:D5)` → `'Web; Marketplace; Phone; Marketplace'`
   - Pred: `=TEXTJOIN("; ",TRUE,D2:D57)` → `'Web; Marketplace; Phone; Marketplace; Mobile App; Marketplace; Phone; Marketplace; Marketplace; Web; Mobile App; Web; Web; Marketplace; Web; Marketplace; Marketplace; Mobile App; Web; Phone; Phone; Marketplace; Marketplace; Web; Marketplace; Mobile App; Marketplace; Phone; Phone; Marketplace; Web; Mobile App; Web; Marketplace; Phone; Mobile App; Mobile App; Web; Mobile App; Web; Mobile App; Web; Mobile App; Phone; Phone; Web; Mobile App; Web; Phone; Mobile App; Web; Web; Web; Mobile App; Phone; Mobile App'` (`wrong_value`)
3. **`test_syn_00411`** (`test_synthetic`, `sales_retail_store`, `text`/D2): Build one text value from Item Name and Store Branch in row 38 joined by ': '.
   - Ref: `=CONCAT(D38,": ",C38)` → `'Monitor Riser: Ashvale'`
   - Pred: `=CONCAT(D38," :",C38)` → `'Monitor Riser :Ashvale'` (`wrong_value`)
