# Baseline Evaluation Summary

## Comparison Table

| Run | Backend | Dataset | Few-shot | N | Syntax Valid | Exec. Accuracy | Exact Match | Raw Format | Avg Latency |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline_zeroshot_synthetic` | `transformers:Qwen/Qwen3-1.7B` | `data/processed/test_synthetic.jsonl` | 0 | 500 | 71.8% | **44.6%** | 36.6% | 100.0% | 814.0 ms |
| `baseline_5shot_synthetic` | `transformers:Qwen/Qwen3-1.7B` | `data/processed/test_synthetic.jsonl` | 5 | 500 | 85.0% | **60.2%** | 51.2% | 100.0% | 1728.2 ms |
| `baseline_zeroshot_real` | `transformers:Qwen/Qwen3-1.7B` | `data/test_real/test_real_DRAFT.csv` | 0 | 80 | 81.2% | **50.0%** | 42.5% | 100.0% | 651.7 ms |
| `baseline_5shot_real` | `transformers:Qwen/Qwen3-1.7B` | `data/test_real/test_real_DRAFT.csv` | 5 | 80 | 85.0% | **51.2%** | 41.2% | 100.0% | 1576.2 ms |

## Top 15 Failure Patterns (total failures across runs: 555)

| # | Failure Pattern | Count | Share | Example |
|---:|---|---:|---:|---|
| 1 | `external_or_invalid_sheet_ref` | 69 | 12.4% | `test_syn_00010` (baseline_zeroshot_synthetic): ref `=COUNTIF(E2:E144,">"&DATE(2021,12,27))` vs pred `=COUNTIF(hr_employee_roster!E2:E144, ">2021-12-27")` |
| 2 | `syntax_error (lookup)` | 49 | 8.8% | `test_syn_00009` (baseline_zeroshot_synthetic): ref `=IFERROR(VLOOKUP("ZZZ-9999",A2:G106,3,FALSE),"Missing")` vs pred `=IFERROR(VLOOKUP(A2, inventory_stock_movements, 4, FALSE), "Missing")` |
| 3 | `wrong_column_reference (text)` | 46 | 8.3% | `test_syn_00014` (baseline_zeroshot_synthetic): ref `=TEXTJOIN(" | ",TRUE,E8:E10)` vs pred `=TEXTJOIN(" | ", TRUE, H8:H10)` |
| 4 | `disallowed_or_unknown_function (aggregation)` | 37 | 6.7% | `test_syn_00005` (baseline_zeroshot_synthetic): ref `=IFERROR(SUM(G2:G57)/SUM(H2:H57),0)` vs pred `=SUMPRODUCT((G2:G57)/H2:H57)` |
| 5 | `runtime_value_type_error` | 36 | 6.5% | `test_syn_00024` (baseline_zeroshot_synthetic): ref `=AVERAGEIFS(F2:F115,C2:C115,"Suncroft",E2:E115,">=13")` vs pred `= AVERAGEIF(C2:C115, "Suncroft", E2:E115, 13)` |
| 6 | `wrong_column_reference (conditional_aggregation)` | 35 | 6.3% | `test_syn_00004` (baseline_zeroshot_synthetic): ref `=SUMIFS(F2:F108,D2:D108,"Sec B",C2:C108,"Economics")` vs pred `=SUMIFS(G2:G108, C2:C108,"Economics", D2:D108,"Sec B")` |
| 7 | `missing_round_call` | 27 | 4.9% | `test_syn_00013` (baseline_zeroshot_synthetic): ref `=ROUND(AVERAGE(F2:F57),2)` vs pred `= AVERAGE(F2:F57)` |
| 8 | `wrong_function_choice (text)` | 24 | 4.3% | `test_syn_00097` (baseline_zeroshot_synthetic): ref `=CONCAT(A93,"-",C93)` vs pred `=LEFT(A93,1)& "-"&C93` |
| 9 | `disallowed_or_unknown_function (math_and_composition)` | 16 | 2.9% | `test_syn_00096` (baseline_zeroshot_synthetic): ref `=IFERROR(G29/F29,0)` vs pred `=IF(ISERROR(G29/F29), 0, G29/F29)` |
| 10 | `wrong_function_choice (conditional_aggregation)` | 16 | 2.9% | `test_syn_00112` (baseline_zeroshot_synthetic): ref `=AVERAGEIFS(G2:G144,D2:D144,"Veldor",F2:F144,">=10")` vs pred `= AVERAGEIF(D2:D144, "Veldor", G2:G144)` |
| 11 | `runtime_div_by_zero` | 14 | 2.5% | `test_syn_00075` (baseline_zeroshot_synthetic): ref `=AVERAGEIF(E2:E106,"Zone C",G2:G106)` vs pred `= AVERAGEIF(G2:G106, "Zone C", G2:G106)` |
| 12 | `wrong_column_reference (logic)` | 14 | 2.5% | `test_syn_00113` (baseline_zeroshot_synthetic): ref `=IFS(F48>=11,"High",F48>=4,"Medium",TRUE,"Low")` vs pred `=IFS(G48>=11,"High",G48>=4,"Medium","Low")` |
| 13 | `wrong_function_choice (date)` | 13 | 2.3% | `test_syn_00028` (baseline_zeroshot_synthetic): ref `=MONTH(B10)` vs pred `=TEXT(B10,"mmm")` |
| 14 | `disallowed_or_unknown_function (logic)` | 12 | 2.2% | `test_syn_00159` (baseline_zeroshot_synthetic): ref `=IF(OR(E16="Cold Bay",E16="Zone A"),"Flagged","Normal")` vs pred `=IF(OR(ROW()=16, E16="Cold Bay", E16="Zone A"),"Flagged","Normal")` |
| 15 | `syntax_error (logic)` | 12 | 2.2% | `test_syn_00055` (baseline_5shot_synthetic): ref `=IF(OR(C71="Suncroft",C71="Larkspur"),"Selected","Excluded")` vs pred `=IF(C71="Suncroft" OR C71="Larkspur","Selected","Excluded")` |

### Detailed Examples by Pattern

1. **`external_or_invalid_sheet_ref`** (69 failures, 12.4%)
   - `baseline_zeroshot_synthetic` / `test_syn_00010` (`hr_employee_roster`): Count records dated after 2021-12-27 based on Hire Date.
     - Ref: `=COUNTIF(E2:E144,">"&DATE(2021,12,27))` | Pred: `=COUNTIF(hr_employee_roster!E2:E144, ">2021-12-27")` (`syntax_error`)
   - `baseline_zeroshot_synthetic` / `test_syn_00012` (`hr_employee_roster`): index Department position 92
     - Ref: `=INDEX(C2:C144,92)` | Pred: `=INDEX(hr_employee_roster!C2:C144,92)` (`syntax_error`)
2. **`syntax_error (lookup)`** (49 failures, 8.8%)
   - `baseline_zeroshot_synthetic` / `test_syn_00009` (`inventory_stock_movements`): Wrap an exact-match VLOOKUP of 'ZZZ-9999' in Move ID (returning Part Name) inside IFERROR so missing keys return 'Missing'.
     - Ref: `=IFERROR(VLOOKUP("ZZZ-9999",A2:G106,3,FALSE),"Missing")` | Pred: `=IFERROR(VLOOKUP(A2, inventory_stock_movements, 4, FALSE), "Missing")` (`syntax_error`)
   - `baseline_zeroshot_synthetic` / `test_syn_00015` (`orders_ecommerce`): iferror(vlookup Channel for Order ID='ORD-1011', 'Not Found')
     - Ref: `=IFERROR(VLOOKUP("ORD-1011",A2:H57,4,FALSE),"Not Found")` | Pred: `=IFERROR(VLOOKUP(A2, orders_ecommerce, 4, FALSE), "Not Found")` (`syntax_error`)
3. **`wrong_column_reference (text)`** (46 failures, 8.3%)
   - `baseline_zeroshot_synthetic` / `test_syn_00014` (`orders_ecommerce`): List the Fulfillment entries from row 8 to 10 joined by ' | ' (skip empty cells).
     - Ref: `=TEXTJOIN(" | ",TRUE,E8:E10)` | Pred: `=TEXTJOIN(" | ", TRUE, H8:H10)` (`wrong_value`)
   - `baseline_zeroshot_synthetic` / `test_syn_00033` (`inventory_stock_movements`): List the Movement Type entries from row 2 to 5 joined by ', ' (skip empty cells).
     - Ref: `=TEXTJOIN(", ",TRUE,D2:D5)` | Pred: `=TEXTJOIN(", ", TRUE, B2:B5)` (`wrong_value`)
4. **`disallowed_or_unknown_function (aggregation)`** (37 failures, 6.7%)
   - `baseline_zeroshot_synthetic` / `test_syn_00005` (`orders_ecommerce`): What is total Order Total per unit of total Shipping Fee (return 0 if division fails)?
     - Ref: `=IFERROR(SUM(G2:G57)/SUM(H2:H57),0)` | Pred: `=SUMPRODUCT((G2:G57)/H2:H57)` (`unsupported_function`)
   - `baseline_zeroshot_synthetic` / `test_syn_00052` (`hr_employee_roster`): Return the total number of cells in Years Service that contain a number.
     - Ref: `=COUNT(F2:F144)` | Pred: `=SUMPRODUCT(--ISNUMBER(F2:F144))` (`unsupported_function`)
5. **`runtime_value_type_error`** (36 failures, 6.5%)
   - `baseline_zeroshot_synthetic` / `test_syn_00024` (`sales_retail_store`): Give me the conditional mean of Net Amount for Store Branch 'Suncroft' and Quantity >= 13.
     - Ref: `=AVERAGEIFS(F2:F115,C2:C115,"Suncroft",E2:E115,">=13")` | Pred: `= AVERAGEIF(C2:C115, "Suncroft", E2:E115, 13)` (`runtime_error`)
   - `baseline_zeroshot_synthetic` / `test_syn_00118` (`hr_employee_roster`): Compute the sum of Annual Salary for 'Crestholm' in Work Hub where Years Service is higher than 4.
     - Ref: `=SUMIFS(G2:G144,D2:D144,"Crestholm",F2:F144,">4")` | Pred: `=SUMIFS(G2:G144, C2:C144,"Crestholm", E2:E144>"4")` (`runtime_error`)
6. **`wrong_column_reference (conditional_aggregation)`** (35 failures, 6.3%)
   - `baseline_zeroshot_synthetic` / `test_syn_00004` (`grades_course_scores`): Calculate the total Assignments Done where Section is 'Sec B' and Subject is 'Economics'.
     - Ref: `=SUMIFS(F2:F108,D2:D108,"Sec B",C2:C108,"Economics")` | Pred: `=SUMIFS(G2:G108, C2:C108,"Economics", D2:D108,"Sec B")` (`wrong_value`)
   - `baseline_zeroshot_synthetic` / `test_syn_00026` (`inventory_stock_movements`): Calculate the sum of Units Moved values strictly greater than 108.
     - Ref: `=SUMIF(F2:F106,">108")` | Pred: `=SUMIF(G2:G106,">108")` (`wrong_value`)
7. **`missing_round_call`** (27 failures, 4.9%)
   - `baseline_zeroshot_synthetic` / `test_syn_00013` (`orders_ecommerce`): Compute the arithmetic mean of the Item Count column and round the result to 2 decimal place(s).
     - Ref: `=ROUND(AVERAGE(F2:F57),2)` | Pred: `= AVERAGE(F2:F57)` (`wrong_value`)
   - `baseline_zeroshot_synthetic` / `test_syn_00016` (`grades_course_scores`): Average the Final Score column and round to 1 decimal place(s).
     - Ref: `=ROUND(AVERAGE(G2:G108),1)` | Pred: `= AVERAGE(G2:G108)` (`wrong_value`)
8. **`wrong_function_choice (text)`** (24 failures, 4.3%)
   - `baseline_zeroshot_synthetic` / `test_syn_00097` (`hr_employee_roster`): concat Employee ID + '-' + Department row 93
     - Ref: `=CONCAT(A93,"-",C93)` | Pred: `=LEFT(A93,1)& "-"&C93` (`wrong_value`)
   - `baseline_zeroshot_synthetic` / `test_syn_00132` (`inventory_stock_movements`): mid Zone row 37 start 3 len 2
     - Ref: `=MID(E37,3,2)` | Pred: `=LEFT(B37,3)` (`wrong_value`)
9. **`disallowed_or_unknown_function (math_and_composition)`** (16 failures, 2.9%)
   - `baseline_zeroshot_synthetic` / `test_syn_00096` (`orders_ecommerce`): In row 29, divide Order Total by Item Count and return 0 if an error occurs.
     - Ref: `=IFERROR(G29/F29,0)` | Pred: `=IF(ISERROR(G29/F29), 0, G29/F29)` (`unsupported_function`)
   - `baseline_zeroshot_synthetic` / `test_syn_00107` (`sales_retail_store`): In row 30, divide Quantity by Net Amount and return 0 if an error occurs.
     - Ref: `=IFERROR(E30/F30,0)` | Pred: `=IF(ISERROR(Quantity/Net Amount), 0, Quantity/Net Amount)` (`unsupported_function`)
10. **`wrong_function_choice (conditional_aggregation)`** (16 failures, 2.9%)
   - `baseline_zeroshot_synthetic` / `test_syn_00112` (`hr_employee_roster`): Give me the conditional mean of Annual Salary for Work Hub 'Veldor' and Years Service >= 10.
     - Ref: `=AVERAGEIFS(G2:G144,D2:D144,"Veldor",F2:F144,">=10")` | Pred: `= AVERAGEIF(D2:D144, "Veldor", G2:G144)` (`wrong_value`)
   - `baseline_zeroshot_synthetic` / `test_syn_00208` (`orders_ecommerce`): Give me the conditional mean of Shipping Fee for Channel 'Phone' and Item Count >= 11.
     - Ref: `=AVERAGEIFS(H2:H57,D2:D57,"Phone",F2:F57,">=11")` | Pred: `= AVERAGEIF(D2:D57, "Phone", G2:G57)` (`wrong_value`)
11. **`runtime_div_by_zero`** (14 failures, 2.5%)
   - `baseline_zeroshot_synthetic` / `test_syn_00075` (`inventory_stock_movements`): avg Valuation where Zone = Zone C
     - Ref: `=AVERAGEIF(E2:E106,"Zone C",G2:G106)` | Pred: `= AVERAGEIF(G2:G106, "Zone C", G2:G106)` (`runtime_error`)
   - `baseline_zeroshot_synthetic` / `test_syn_00121` (`sales_retail_store`): Calculate the average of Net Amount values strictly greater than 467.7.
     - Ref: `=AVERAGEIF(F2:F115,">467.7")` | Pred: `= AVERAGEIF(E2:E115, ">467.7")` (`runtime_error`)
12. **`wrong_column_reference (logic)`** (14 failures, 2.5%)
   - `baseline_zeroshot_synthetic` / `test_syn_00113` (`orders_ecommerce`): Categorize Item Count on row 48 via IFS: 'High' (>= 11), 'Medium' (>= 4), 'Low' (otherwise).
     - Ref: `=IFS(F48>=11,"High",F48>=4,"Medium",TRUE,"Low")` | Pred: `=IFS(G48>=11,"High",G48>=4,"Medium","Low")` (`wrong_value`)
   - `baseline_zeroshot_synthetic` / `test_syn_00137` (`orders_ecommerce`): For row 35, return 'Above' if Shipping Fee is greater than 26.2, otherwise return 'Below'.
     - Ref: `=IF(H35>26.2,"Above","Below")` | Pred: `=IF(G35>26.2,"Above","Below")` (`wrong_value`)
13. **`wrong_function_choice (date)`** (13 failures, 2.3%)
   - `baseline_zeroshot_synthetic` / `test_syn_00028` (`orders_ecommerce`): What month is Order Date on row 10?
     - Ref: `=MONTH(B10)` | Pred: `=TEXT(B10,"mmm")` (`wrong_value`)
   - `baseline_zeroshot_synthetic` / `test_syn_00063` (`sales_retail_store`): What month is Sale Date on row 61?
     - Ref: `=MONTH(B61)` | Pred: `=TEXT(B61,"mmm")` (`wrong_value`)
14. **`disallowed_or_unknown_function (logic)`** (12 failures, 2.2%)
   - `baseline_zeroshot_synthetic` / `test_syn_00159` (`inventory_stock_movements`): Check row 16's Zone cell; if it equals 'Cold Bay' or 'Zone A', output 'Flagged', otherwise output 'Normal'.
     - Ref: `=IF(OR(E16="Cold Bay",E16="Zone A"),"Flagged","Normal")` | Pred: `=IF(OR(ROW()=16, E16="Cold Bay", E16="Zone A"),"Flagged","Normal")` (`unsupported_function`)
   - `baseline_zeroshot_synthetic` / `test_syn_00162` (`orders_ecommerce`): For row 44, show Shipping Fee or 'N/A' if it's empty.
     - Ref: `=IF(H44="","N/A",H44)` | Pred: `=IF(ISNUMBER(H44), H44, "N/A")` (`unsupported_function`)
15. **`syntax_error (logic)`** (12 failures, 2.2%)
   - `baseline_5shot_synthetic` / `test_syn_00055` (`sales_retail_store`): Check row 71's Store Branch cell; if it equals 'Suncroft' or 'Larkspur', output 'Selected', otherwise output 'Excluded'.
     - Ref: `=IF(OR(C71="Suncroft",C71="Larkspur"),"Selected","Excluded")` | Pred: `=IF(C71="Suncroft" OR C71="Larkspur","Selected","Excluded")` (`syntax_error`)
   - `baseline_5shot_synthetic` / `test_syn_00159` (`inventory_stock_movements`): Check row 16's Zone cell; if it equals 'Cold Bay' or 'Zone A', output 'Flagged', otherwise output 'Normal'.
     - Ref: `=IF(OR(E16="Cold Bay",E16="Zone A"),"Flagged","Normal")` | Pred: `=IF(E16="Cold Bay" OR E16="Zone A","Flagged","Normal")` (`syntax_error`)
