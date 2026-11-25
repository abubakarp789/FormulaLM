# Model Selection Decision Record (`v1` vs `v2`)

**Date:** 25 Nov 2026  
**Verdict:** **`SHIP_V2`** (git tag `v2-ship`; frozen fallback remains at git tag `v1-frozen`)

---

## 1. Pre-registered decision rule

Committed in `src/eval/compare_v1_v2.py` (`6973916`) **before** any v2 evaluation was executed:

> **Ship v2 only if its execution accuracy is at least as high as v1 on `val` AND on `test_real_v2`, and not meaningfully worse on `test_real`; otherwise ship v1.**

Operational tolerance on `test_real` ($N = 80$): a drop of at most `2.5 pp` (2 examples out of 80; 95% Wilson CI half-width is ~6–9 pp on $N = 80$).

---

## 2. Measured results (16-bit fp16 on pinned `Qwen/Qwen3-1.7B@70d244cc`)

All v1 and v2 runs below come directly from saved files under `results/` (see [`results/ft_v2_comparison.md`](../results/ft_v2_comparison.md) and [`results/final_headline.md`](../results/final_headline.md)). Both adapters were evaluated with identical settings (`enable_thinking=False`, `temperature=0`, `max_tokens=96`, `seed=42`, `few_shot=0`, `batch_size=8`).

| Split | Model | N | Correct | Exec. Accuracy | 95% Wilson CI | Δ (v2 − v1) | Syntax Valid | Exact Match |
|---|---|---:|---:|---:|---|---:|---:|---:|
| `val` (validation) | Fine-tuned v1 (`v1-frozen`) | 500 | 498/500 | **99.6%** | `[98.6%, 99.9%]` | — | 99.8% | 99.4% |
| `val` (validation) | **Fine-tuned v2 (`v2-ship`)** | 500 | 498/500 | **99.6%** | `[98.6%, 99.9%]` | +0.0 pp | **100.0%** | 98.2% |
| `test_real_v2` (fresh held-out set) | Fine-tuned v1 (`v1-frozen`) | 50 | 44/50 | **88.0%** | `[76.2%, 94.4%]` | — | 100.0% | 82.0% |
| `test_real_v2` (fresh held-out set) | **Fine-tuned v2 (`v2-ship`)** | 50 | 44/50 | **88.0%** | `[76.2%, 94.4%]` | +0.0 pp | 100.0% | **86.0%** |
| `test_synthetic` | Fine-tuned v1 (`v1-frozen`) | 500 | 488/500 | **97.6%** | `[95.9%, 98.6%]` | — | 99.6% | 97.0% |
| `test_synthetic` | **Fine-tuned v2** *(informed by v1 error analysis)* | 500 | 494/500 | **98.8%** | `[97.4%, 99.5%]` | +1.2 pp | **99.8%** | **97.6%** |
| `test_real` | Fine-tuned v1 (`v1-frozen`) | 80 | 73/80 | **91.2%** | `[83.0%, 95.7%]` | — | 100.0% | 91.2% |
| `test_real` | **Fine-tuned v2** *(informed by v1 error analysis)* | 80 | 75/80 | **93.8%** | `[86.2%, 97.3%]` | +2.5 pp | **100.0%** | **93.8%** |

### Gate check

| Gate | Criterion | v1 | v2 | Δ (v2 − v1) | Status |
|---|---|---:|---:|---:|---|
| `val` | `v2 >= v1` | 99.6% | 99.6% | +0.0 pp | **PASS** |
| `test_real_v2` | `v2 >= v1` | 88.0% | 88.0% | +0.0 pp | **PASS** |
| `test_real` | `v2 >= v1 − 2.5 pp` | 91.2% | 93.8% | +2.5 pp | **PASS** |

---

## 3. Honest statistical assessment

- **Statistically indistinguishable on unbiased splits:** On `val` (498/500 vs 498/500) and `test_real_v2` (44/50 vs 44/50), v1 and v2 tie exactly on execution accuracy with identical 95% Wilson CIs (`[98.6%, 99.9%]` and `[76.2%, 94.4%]`). v2 holds small secondary advantages (lower validation loss `0.003975` vs `0.004240`, `100.0%` vs `99.8%` syntax validity on `val`, and `86.0%` vs `82.0%` normalized exact match on `test_real_v2`).
- **Original test-set gains are within noise and analysis-informed:** v2's gains on `test_synthetic` (`+1.2 pp`, `[95.9%, 98.6%]` vs `[97.4%, 99.5%]`) and `test_real` (`+2.5 pp`, `[83.0%, 95.7%]` vs `[86.2%, 97.3%]`) have overlapping 95% Wilson CIs and were produced after v2's train-only data additions targeted v1's failure clusters on those sets (*informed by v1 error analysis*). They should not be overstated as statistically significant breakthroughs over v1.
- **Authorship caveat on `test_real_v2`:** For the fresh held-out set `data/test_real_v2/test_real_v2.csv` (50 requests, created after `qlora_v2` training finished), the requests were drafted by an AI assistant with access to the repo, including the v1 error analysis; the set is therefore not fully independent. This is disclosed in `README.md`, `data/DATASET_CARD.md`, and `data/test_real_v2/README.md`.
- **Why `SHIP_V2` stands:** `v2` passed all pre-registered gates cleanly, showed cleaner 1-epoch training dynamics (no Epoch-2 validation overfitting), and achieved lower validation loss.

---

## 4. Shipping candidate (`v2-ship`) and fallback (`v1-frozen`)

### Candidate to merge and quantize in PROMPT 10 (`v2-ship`)
- **Base model (merge target):** `Qwen/Qwen3-1.7B`
- **Base revision:** `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` (`apache-2.0`)
- **Adapter Hugging Face repo:** [`abubakar56/formulalm-qwen3-1.7b-lora-v2`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora-v2)
- **Adapter Hugging Face commit:** `e2dd7e8115406ffcdbbdfa60d6f2f10b4aaf2595`
- **Adapter weights LFS SHA-256:** `9c085a87fa60d28896599b2dba6ba425ee3bc5656596763175a1bd75ae7e422f` (`69,782,384` bytes, `r=16`, `lora_alpha=32`, inferred `checkpoint-400`)
- **Merge note:** Explicitly load `Qwen/Qwen3-1.7B@70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` (fp16) before loading the adapter, overriding the `unsloth/Qwen3-1.7B-unsloth-bnb-4bit` path stored in `adapter_config.json` (see [`docs/MODEL_PROVENANCE.md`](MODEL_PROVENANCE.md)).

### Frozen fallback (`v1-frozen`)
- **Git tag:** `v1-frozen` (commit `c7e0971`)
- **Adapter Hugging Face repo:** [`abubakar56/formulalm-qwen3-1.7b-lora`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora)
- **Adapter Hugging Face commit:** `d9909249c496134ecc72e1d77bdc22e6e0461537` (`checkpoint-200` inferred)
- Frozen `results/ft_v1_synthetic` and `results/ft_v1_real` remain untouched.
