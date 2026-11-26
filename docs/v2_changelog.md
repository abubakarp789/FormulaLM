# FormulaLM v2 Iteration Changelog (Data vs Hyperparameter Changes)

**Frozen fallback:** git tag [`v1-frozen`](https://github.com/abubakarp789/FormulaLM/releases/tag/v1-frozen) (`checkpoint-200`, `config/train_qlora.yaml`, `results/ft_v1_*`).
**Evaluation discipline:** all checkpoint selection and model-selection decisions use `data/processed/val.jsonl` only. Because v2's data additions were motivated by v1's 6-cluster error analysis (`results/ft_v1_comparison.md`), all v2 metrics on `test_synthetic` and `test_real` are explicitly labeled **"informed by v1 error analysis"**, and a 50-example fresh held-out set (`data/test_real_v2/`) created after v2 training is reported separately (AI-drafted with access to the repository including the v1 error analysis, reviewed and approved by Abu Bakar on 26 November 2026; therefore not fully independent, and small, `N = 50`).

---

## 1. Data Changes (v1 → v2, strictly `train_v2.jsonl` on the 20 training sheets)

| Aspect | v1 (`train.jsonl`) | v2 (`train_v2.jsonl`) | Motivation |
|---|---|---|---|
| Train split size | 8,000 | **9,000** (`0` dropped) | Slightly larger coverage for harder multi-function compositions |
| Templates in train | 60 (`src/data/templates.py`) | **62** (+2 train-only templates in `src/data/v2_augmentations.py`) | Added `v2_iferror_round_row_ratio` (`=IFERROR(ROUND(A/B,d),0)`) and `v2_iferror_round_sum_ratio` (`=IFERROR(ROUND(SUM(A)/SUM(B),d),0)`) for Cluster 1 (`wrong_function`) per-unit/ratio failures |
| Train-only phrasing additions | 0 | **58 new train-only phrasings** across 18 templates (`V2_TRAIN_EXTRA_PHRASINGS`) | Targets Cluster 1 (per-unit rates, goal/target `IF+SUMIF`, numeric `YEAR()` vs `TEXT()`, `MAX` superlatives), Cluster 2 (implicit column names like `"total {val1} {measure} in {val2}"`), and Cluster 3 (unquoted multi-word category literals, rounded averages, explicit `TEXTJOIN`/`CONCAT` bounds) |
| Difficulty mix (D1 / D2 / D3) | 35.7% / 35.7% / 28.6% (`2857 / 2857 / 2286`) | **30.2% / 38.9% / 30.9%** (`2722 / 3501 / 2777`) | Shifts weight toward D2/D3 multi-function compositions (where v1's synthetic→real gap was largest) |
| Category mix | Balanced (~14.3% × 7) | Balanced (~14.3% × 7: `1285–1286` each) | Kept balanced across all 7 categories |
| Train SHA-256 (first 16 hex) | `7f3d8e5ebeb4019a` | `0cca0eb9d2748c0f` | Regenerated deterministically (`seed=42`, verified 10,000/10,000) |

## 2. Hyperparameter Changes (`config/train_qlora.yaml` → `config/train_qlora_v2.yaml`)

All hyperparameter changes below were motivated strictly by v1's validation loss curve (`results/train_qlora_v1/loss_log.csv`), which achieved best `eval_loss = 0.004240` at step 200 (`0.40` epoch) and overfit through Epoch 2 (`train_loss = 0.0000`, `eval_loss = 0.0086–0.0095`).

| Hyperparameter | v1 (`train_qlora.yaml`) | v2 (`train_qlora_v2.yaml`) | Why |
|---|---|---|---|
| `num_train_epochs` | `2` (1,000 steps) | **`1`** (563 steps) | Prevents Epoch-2 memorization of synthetic phrasings and halves T4 runtime (~15–18 min) |
| `learning_rate` | `2.0e-4` | **`1.0e-4`** | Gentler adapter updates to reduce overfitting to synthetic templates |
| `weight_decay` | `0.01` | **`0.05`** | Stronger L2 regularization on LoRA weights |
| `warmup_ratio` | `0.05` | **`0.08`** | Slightly smoother early ramp-up over 563 total steps |
| `eval_steps` / `save_steps` | `100` / `100` | **`50` / `50`** | Finer checkpoint resolution on `val.jsonl` (`save_total_limit: 4`, `load_best_model_at_end: true` by `eval_loss`) |
| `hub.hf_repo_id` | `abubakar56/formulalm-qwen3-1.7b-lora` | `abubakar56/formulalm-qwen3-1.7b-lora-v2` | Keeps frozen v1 adapter untouched on HF Hub |

## 3. Unchanged / Frozen Controls

- **Base model & LoRA architecture:** `Qwen/Qwen3-1.7B`, 4-bit QLoRA, `r=16`, `lora_alpha=32`, `lora_dropout=0.0`, all 7 linear projections, `max_seq_length=512`, `batch_size=4 × grad_accum=4 = 16`, `adamw_8bit`, `cosine` schedule, `enable_thinking=false`, `train_on_responses_only=true`, `seed=42`.
- **Validation split (`data/processed/val.jsonl`):** **bit-for-bit identical** to v1 (`SHA-256 = f2cf0d3181baee06`, 500 examples).
- **Synthetic test split (`data/processed/test_synthetic.jsonl`):** **bit-for-bit identical** to v1 (`SHA-256 = ec6348fef4ca3b6a`, 500 examples, 5 held-out sheets, 2 reserved test phrasings/template).
- **Original realistic v1 test split (`data/test_real/test_real_DRAFT.csv`):** untouched (80 requests, filename kept for compatibility with saved results: AI-drafted, reviewed and approved by Abu Bakar on 26 November 2026).
- **Fresh held-out test split (`data/test_real_v2/`):** 50 post-v2 requests across the 5 held-out sheets (AI-drafted with access to the repository including the v1 error analysis, reviewed and approved by Abu Bakar on 26 November 2026; therefore not fully independent, and small, `N = 50`).
