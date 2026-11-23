# Evaluation Report: `baseline_5shot_real`

- **Backend:** `transformers:Qwen/Qwen3-1.7B`
- **Dataset:** `data/test_real/test_real_DRAFT.csv` (80 examples)
- **Settings:** `seed=42`, `temperature=0`, `few_shot=5`, `max_tokens=96`

## Overall Metrics

| Metric | Value |
|---|---:|
| Examples | 80 |
| Syntax valid rate | 85.0% |
| Execution success rate (no runtime error) | 76.2% |
| **Execution accuracy** | **51.2%** |
| Normalized exact match | 41.2% |
| Strict raw format (`=...` only) | 100.0% |
| Avg latency | 1576.2 ms |
| Median / p95 latency | 1548.9 ms / 1976.2 ms |

## By Category

| Category | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| `aggregation` | 12 | 91.7% | 58.3% | 58.3% | 1432.3 ms |
| `conditional_aggregation` | 21 | 95.2% | 38.1% | 38.1% | 1472.5 ms |
| `date` | 9 | 88.9% | 77.8% | 44.4% | 1706.4 ms |
| `logic` | 10 | 70.0% | 60.0% | 40.0% | 1588.0 ms |
| `lookup` | 9 | 55.6% | 33.3% | 11.1% | 1677.4 ms |
| `math_and_composition` | 8 | 75.0% | 25.0% | 12.5% | 1666.6 ms |
| `text` | 11 | 100.0% | 72.7% | 72.7% | 1665.2 ms |

## By Difficulty

| Difficulty | N | Syntax Valid | Exec. Accuracy | Exact Match | Avg Latency |
|---|---:|---:|---:|---:|---:|
| 1 | 29 | 96.5% | 75.9% | 75.9% | 1535.4 ms |
| 2 | 33 | 78.8% | 36.4% | 30.3% | 1591.9 ms |
| 3 | 18 | 77.8% | 38.9% | 5.6% | 1613.0 ms |

## Error Breakdown

| Error Class | Count |
|---|---:|
| `runtime_error` | 7 |
| `syntax_error` | 6 |
| `unsupported_function` | 6 |
| `wrong_value` | 20 |

## Sample Failures (up to 10)

- **`real_001`** (`sales_retail_store`, `aggregation`/D1): total revenue across all receipts
  - Reference: `=SUM(F2:F115)` → `51636.87`
  - Predicted: `=SUMPRODUCT((F2:F115)*1)` → `None` (error: `unsupported_function`)
- **`real_002`** (`sales_retail_store`, `aggregation`/D1): biggest sale?
  - Reference: `=MAX(F2:F115)` → `919.63`
  - Predicted: `=MAX(E2:E115)` → `25` (error: `wrong_value`)
- **`real_005`** (`sales_retail_store`, `conditional_aggregation`/D1): how much did the Suncroft branch make in total?
  - Reference: `=SUMIF(C2:C115,"Suncroft",F2:F115)` → `10004.82`
  - Predicted: `=SUMIF(C2:C115,"Suncroft",E2:E115)` → `346.0` (error: `wrong_value`)
- **`real_007`** (`sales_retail_store`, `conditional_aggregation`/D2): count sales with net amt over 500
  - Reference: `=COUNTIF(F2:F115,">500")` → `50`
  - Predicted: `=SUMIF(F2:F115,">500")` → `34887.950000000004` (error: `wrong_value`)
- **`real_009`** (`sales_retail_store`, `conditional_aggregation`/D3): total net amt at Suncroft for bulk orders (qty >= 15)
  - Reference: `=SUMIFS(F2:F115,C2:C115,"Suncroft",E2:E115,">=15")` → `4361.219999999999`
  - Predicted: `=SUMIF(C2:C115,"Suncroft",E2:E115,">=15",F2:F115)` → `None` (error: `runtime_error`)
- **`real_014`** (`sales_retail_store`, `text`/D2): combine branch and item name on row 3 like 'Branch: Item' using concat
  - Reference: `=CONCAT(C3,": ",D3)` → `'Suncroft: Foldable Stand'`
  - Predicted: `=CONCAT(D3,":",E3)` → `'Foldable Stand:19'` (error: `wrong_value`)
- **`real_018`** (`hr_employee_roster`, `aggregation`/D1): how many employees actually have a salary filled in?
  - Reference: `=COUNT(G2:G144)` → `137`
  - Predicted: `=COUNTIF(G2:G144,"<>")` → `6` (error: `wrong_value`)
- **`real_021`** (`hr_employee_roster`, `conditional_aggregation`/D2): how many folks aren't in Support?
  - Reference: `=COUNTIF(C2:C144,"<>Support")` → `115`
  - Predicted: `=COUNTIF(B2:B144,"<>Support")` → `143` (error: `wrong_value`)
- **`real_022`** (`hr_employee_roster`, `conditional_aggregation`/D2): count people in Finance who work out of Veldor
  - Reference: `=COUNTIFS(C2:C144,"Finance",D2:D144,"Veldor")` → `8`
  - Predicted: `=COUNTIF(C2:C144,"Finance",D2:D144,"Veldor")` → `None` (error: `runtime_error`)
- **`real_023`** (`hr_employee_roster`, `conditional_aggregation`/D3): avg salary in Engineering for vets with 5+ yrs service
  - Reference: `=AVERAGEIFS(G2:G144,C2:C144,"Engineering",F2:F144,">=5")` → `100142.11466666665`
  - Predicted: `= AVERAGEIF(C2:C144,"Engineering",G2:G144,">=5")` → `None` (error: `runtime_error`)
