# FormulaLM — Final Headline Results (Base vs QLoRA v1 vs QLoRA v2)

Base model: `Qwen/Qwen3-1.7B` (`70d244cc`, Apache-2.0, fp16, `enable_thinking=False`, `temperature=0`, `max_tokens=96`, `seed=42`). 95% confidence intervals are exact Wilson score intervals.

Note: Fine-tuned v2 results on `test_real` and `test_synthetic` are labeled **'informed by v1 error analysis'** because v2 data additions targeted v1 error clusters on those sets.

| Test Set | System | N | Correct | **Exec. Accuracy** | 95% Wilson CI | Δ vs Base 0-shot | Syntax Valid | Exact Match |
|---|---|---:|---:|---:|---|---:|---:|---:|
| `test_real_v2` (post-v2 fresh) | Base `Qwen3-1.7B` (0-shot) | 50 | 23/50 | **46.0%** | [33.0%, 59.6%] | — | 76.0% | 40.0% |
| `test_real_v2` (post-v2 fresh) | Base `Qwen3-1.7B` (5-shot, train) | 50 | 29/50 | **58.0%** | [44.2%, 70.6%] | +12.0 pp | 88.0% | 46.0% |
| `test_real_v2` (post-v2 fresh) | Fine-tuned v1 (`v1-frozen`) | 50 | 44/50 | **88.0%** | [76.2%, 94.4%] | +42.0 pp | 100.0% | 82.0% |
| `test_real_v2` (post-v2 fresh) | **Fine-tuned v2 (`v2-ship`)** | 50 | 44/50 | **88.0%** | [76.2%, 94.4%] | +42.0 pp | 100.0% | 86.0% |
| `test_real` (original realistic) | Base `Qwen3-1.7B` (0-shot) | 80 | 40/80 | **50.0%** | [39.3%, 60.7%] | — | 81.2% | 42.5% |
| `test_real` (original realistic) | Base `Qwen3-1.7B` (5-shot, train) | 80 | 41/80 | **51.2%** | [40.5%, 61.9%] | +1.2 pp | 85.0% | 41.2% |
| `test_real` (original realistic) | Fine-tuned v1 (`v1-frozen`) | 80 | 73/80 | **91.2%** | [83.0%, 95.7%] | +41.2 pp | 100.0% | 91.2% |
| `test_real` (original realistic) | **Fine-tuned v2 (`v2-ship`) (informed by v1 error analysis)** | 80 | 75/80 | **93.8%** | [86.2%, 97.3%] | +43.8 pp | 100.0% | 93.8% |
| `test_synthetic` (original synthetic) | Base `Qwen3-1.7B` (0-shot) | 500 | 223/500 | **44.6%** | [40.3%, 49.0%] | — | 71.8% | 36.6% |
| `test_synthetic` (original synthetic) | Base `Qwen3-1.7B` (5-shot, train) | 500 | 301/500 | **60.2%** | [55.9%, 64.4%] | +15.6 pp | 85.0% | 51.2% |
| `test_synthetic` (original synthetic) | Fine-tuned v1 (`v1-frozen`) | 500 | 488/500 | **97.6%** | [95.9%, 98.6%] | +53.0 pp | 99.6% | 97.0% |
| `test_synthetic` (original synthetic) | **Fine-tuned v2 (`v2-ship`) (informed by v1 error analysis)** | 500 | 494/500 | **98.8%** | [97.4%, 99.5%] | +54.2 pp | 99.8% | 97.6% |
