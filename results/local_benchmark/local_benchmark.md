# FormulaLM Local Laptop Benchmark

- **OS:** Windows 11 (10.0.26300)
- **CPU:** Intel64 Family 6 Model 142 Stepping 12, GenuineIntel (8 threads)
- **RAM at start:** 3211 MB free / 7998 MB total
- **Free disk:** 44.2 GB

| Quant | Status | Engine | Size (MB) | Load (s) | Peak RAM (MB) | Gen tok/s | Local Subset Exec. Acc (95% CI) |
|---|---|---|---:|---:|---:|---:|---|
| `Q4_K_M` | ok | ollama | 1056.1 | 4.60 | 1333 | 12.7 | **89.2%** (116/130, [82.7%, 93.5%]) |
| `Q5_K_M` | ok | ollama | 1199.6 | 2.64 | 1476 | 11.3 | **90.8%** (118/130, [84.6%, 94.6%]) |
| `Q8_0` | ok | ollama | 1749.5 | 5.93 | 2026 | 7.8 | **91.5%** (119/130, [85.5%, 95.2%]) |
