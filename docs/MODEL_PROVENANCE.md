# Model Provenance

Facts below were checked on **24 Nov 2026** against the Hugging Face Hub API and the files committed in this repo. Anything that cannot be proven from a file or API response is marked **UNVERIFIED**.

## 1. Base model

| Field | Value | Evidence |
|---|---|---|
| Model | `Qwen/Qwen3-1.7B` | `config/train_qlora*.yaml`, `results/train_qlora_v*/run_summary.json` (`model_id`) |
| Pinned revision | `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` | HF API `GET /api/models/Qwen/Qwen3-1.7B/revision/70d244c…` returns this `sha` |
| License | Apache-2.0 | HF API `cardData.license = apache-2.0` at that revision |
| Mode | Non-thinking (`enable_thinking=False`) | `src/eval/run_eval.py`, `scripts/train_qlora.py` |

## 2. Unsloth 4-bit mirror used during training

Unsloth swaps `Qwen/Qwen3-1.7B` for its pre-quantized 4-bit mirror when `load_in_4bit=True`.

| Field | Value | Evidence |
|---|---|---|
| Mirror repo | `unsloth/Qwen3-1.7B-unsloth-bnb-4bit` | `base_model_name_or_path` in both adapters' `adapter_config.json` on the Hub |
| Mirror revision loaded | `a972f4304f86a0a705d35b378d7a7675d58063a7` | `loaded_revision` in `results/train_qlora_v1/run_summary.json` and `results/train_qlora_v2/run_summary.json`; HF API confirms this `sha` exists in the mirror repo |
| Mirror license / declared base | Apache-2.0 / `Qwen/Qwen3-1.7B` | HF API `cardData` of the mirror |
| Mirror weights identical to `Qwen/Qwen3-1.7B@70d244c` before quantization | **UNVERIFIED** | Not checked byte-for-byte |

**Consequence for evaluation and merging:** our 16-bit evaluations load `Qwen/Qwen3-1.7B@70d244c` (fp16) and apply the LoRA adapter on top, not the 4-bit mirror. The adapter was trained against 4-bit (NF4) base weights, so a small train/inference precision mismatch exists. This is standard QLoRA practice. Merges for GGUF export must target `Qwen/Qwen3-1.7B@70d244c` explicitly, overriding the `adapter_config.json` base path.

## 3. LoRA adapters

Both adapters: `r=16`, `lora_alpha=32`, `lora_dropout=0.0`, targets `q,k,v,o,gate,up,down_proj`, `peft_version=0.21.2`, `task_type=CAUSAL_LM` (from the Hub `adapter_config.json`).

| | v1 (frozen fallback, git tag `v1-frozen`) | v2 |
|---|---|---|
| Hugging Face repo | [`abubakar56/formulalm-qwen3-1.7b-lora`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora) (public) | [`abubakar56/formulalm-qwen3-1.7b-lora-v2`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora-v2) (public) |
| Hub commit at audit | `d9909249c496134ecc72e1d77bdc22e6e0461537` | `e2dd7e8115406ffcdbbdfa60d6f2f10b4aaf2595` |
| `adapter_model.safetensors` | 69,782,384 bytes, LFS sha256 `3301483e8e925196efc78d57fdeab3e7cf1b71f4c1347d99d7c4c86ab8f8615c` | 69,782,384 bytes, LFS sha256 `9c085a87fa60d28896599b2dba6ba425ee3bc5656596763175a1bd75ae7e422f` |
| Hub repo created | 2026-11-23T22:50:56Z | 2026-11-24T11:11:33Z |
| Training run | `qlora_v1`, commit `b9e32c7`, `config/train_qlora.yaml` | `qlora_v2`, commit `da2ad22`, `config/train_qlora_v2.yaml` |
| Best checkpoint (val `eval_loss`) | `checkpoint-200` (0.004240) | `checkpoint-400` (0.003975) |
| Drive copy | Colab account A: `/content/drive/MyDrive/FormulaLM/qlora_v1/adapter` | Colab account B: `/content/drive/MyDrive/FormulaLM/qlora_v2/adapter` |

### Which checkpoint each Hub adapter corresponds to

- **Inferred: v1 Hub adapter = `checkpoint-200`, v2 Hub adapter = `checkpoint-400`.**
  - Training ran with `load_best_model_at_end: true` and `metric_for_best_model: eval_loss` (`results/train_qlora_v*/train_config.json`).
  - `scripts/train_qlora.py` saves `model` (L444) and pushes the same object (L518) after training, i.e. after the best checkpoint was reloaded.
  - Each Hub repo was created about 20 s before the commit that saved that run's logs (`caae8f1` at 22:51:12Z; `341be71` at 11:11:53Z), which fits a push at the end of the same run.
- **UNVERIFIED:** byte-level identity between each Hub `adapter_model.safetensors` and the corresponding Drive `checkpoint-*/adapter_model.safetensors`. The Drive folders can't be reached from this machine. To verify, run `sha256sum` on the Drive files and compare with the hashes above.
- **UNVERIFIED:** that the frozen `results/ft_v1_*` runs used weights identical to the v1 Hub adapter. Those runs loaded the Drive copy (`run_config.json` → `backend: transformers:Qwen/Qwen3-1.7B+/content/drive/MyDrive/FormulaLM/qlora_v1/adapter`).
- **UNVERIFIED:** the base revision used by the frozen baseline and `ft_v1_*` runs. The notebooks passed `REVISION = '70d244c…'`, but `run_config.json` did not record it before PROMPT 9B. From PROMPT 9B on, `run_eval` writes `base_model_id`, `base_revision` and `model_provenance` (adapter source, resolved Hub commit, adapter-config base, dtype) into every `run_config.json`.

## 4. Evaluation from now on

`notebooks/03_eval_ft_v2.ipynb` loads **both** adapters from the Hub, pinned to the commits above, on the same `Qwen/Qwen3-1.7B@70d244c` fp16 base with identical decoding settings. The v1-vs-v2 comparison therefore does not depend on which Colab account's Drive is mounted.

## 5. Merged 16-bit & Quantized GGUF Release (`v2-ship`)

Exported in `notebooks/05_merge_quantize.ipynb` using `Qwen/Qwen3-1.7B@70d244cc` (fp16) + `abubakar56/formulalm-qwen3-1.7b-lora-v2@e2dd7e81` and `llama.cpp` release `b12728` (`244640b7f26e2a7301b27a24edc4f7feaf97d52f`).

- **Hugging Face GGUF repo:** [`abubakar56/formulalm-qwen3-1.7b-gguf`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf) (public, commit `cbfb673ce04394d5d1cefabaf484b752cf5bf009`)
- **HF Merged FP16 vs GGUF F16 parity (20 fixed examples):** `20/20` (100.0%) raw exact match, formula match, and executed value agreement (`results/quant_parity/parity_report.md`).

| File | Quant | Size (MB) | LFS SHA-256 (first 16 hex) |
|---|---|---:|---|
| `formulalm-qwen3-1.7b-v2-f16.gguf` | `F16` | 3,287.65 | `af920c6319798df4` |
| `formulalm-qwen3-1.7b-v2-q8_0.gguf` | `Q8_0` | 1,749.45 | `56dee17960b60da3` |
| `formulalm-qwen3-1.7b-v2-q5_k_m.gguf` | `Q5_K_M` | 1,199.61 | `ca91c683279434a8` |
| `formulalm-qwen3-1.7b-v2-q4_k_m.gguf` | `Q4_K_M` | 1,056.11 | `aebb66e3b210d251` |

