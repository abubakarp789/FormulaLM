---
license: apache-2.0
base_model: Qwen/Qwen3-1.7B
language:
- en
pipeline_tag: text-generation
library_name: peft
tags:
- qwen3
- excel
- spreadsheet
- formula-generation
- lora
- qlora
- unsloth
- qwen-local-hackathon-2026
---

# FormulaLM — Qwen3-1.7B LoRA Adapter (`v1-frozen` Fallback)

Frozen v1 QLoRA adapter (`checkpoint-200`, `val` loss `0.004240`) retained publicly as the reproducible fallback (`v1-frozen`). For deployment, use the shipping v2 release:

- **Primary local GGUF (`v2-ship Q5_K_M`, 1.20 GB):** [`abubakar56/formulalm-qwen3-1.7b-gguf`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf)
- **Shipping v2 LoRA adapter (`v2-ship`):** [`abubakar56/formulalm-qwen3-1.7b-lora-v2`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora-v2)
- **Base model:** [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B) (revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, **Apache-2.0**)
- **Source code:** [`abubakarp789/FormulaLM`](https://github.com/abubakarp789/FormulaLM) (MIT code license)
- **Author:** Abu Bakar (GitHub: [`abubakarp789`](https://github.com/abubakarp789); Hugging Face and ModelScope: `abubakar56`)
- **License:** **Apache-2.0**, inherited from [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B). Credit to the Qwen team and Junaid Shaukat & Qwen Pakistan ([`junaiddshaukat/finetune-anywhere`](https://github.com/junaiddshaukat/finetune-anywhere)).

## Training Summary (`qlora_v1`)

- **Data:** 8,000 execution-verified synthetic training examples (`train.jsonl`, 0 dropped) across 20 training sheets (60 templates, 36 Excel functions, 0 personal data). No model-generated paraphrase augmentation or scraped data was used.
- **Authorship statement:** Author and repository owner: Abu Bakar (GitHub: `abubakarp789`; Hugging Face and ModelScope: `abubakar56`). Abu Bakar conceived the project and defined the task, scope, evaluation design and all engineering decisions; ran all training, evaluation, quantization and local CPU benchmarks; published the models; and reviewed and approved all code, synthetic data, test sets and results in this repository. An AI coding assistant (Google Antigravity) was used under his direction to help generate code and synthetic data (templates, phrasing patterns, sheets) and to draft test requests; all AI-assisted output was reviewed and approved by Abu Bakar. Code and synthetic data: MIT. Fine-tuned adapters and quantized GGUF weights are Apache-2.0 derivatives of `Qwen/Qwen3-1.7B`.
- **Held-out realistic test sets:** `test_real` (80 requests, file `test_real_DRAFT.csv`, filename kept for compatibility with saved results): AI-drafted, reviewed and approved by Abu Bakar on 26 November 2026. `test_real_v2` (50 requests): AI-drafted with access to the repository including the v1 error analysis, reviewed and approved by Abu Bakar on 26 November 2026; therefore not fully independent, and small (`N=50`).
- **Hyperparameters (`config/train_qlora.yaml`):** 4-bit QLoRA (`r=16`, `lora_alpha=32`, `lora_dropout=0.0`, all 7 linear layers), `max_seq_length=512`, `train_on_responses_only` (`enable_thinking=False`), 2 epochs (1,000 steps), effective batch 16 (`4 × 4`), `lr=2e-4` cosine, `warmup_ratio=0.05`, `weight_decay=0.01`, `adamw_8bit`, `eval_steps=100`, `seed=42`, `load_best_model_at_end=True` → selected `checkpoint-200` (`val_loss=0.004240`).
- **Hardware:** Free Google Colab Tesla T4 (14.56 GB VRAM) — 34.6 min, peak 1.65 GB VRAM.

## Measured Results (`v1-frozen`, 16-bit fp16 on `Qwen/Qwen3-1.7B@70d244cc`)

| Split | N | Base 0-shot | Base 5-shot | **Fine-tuned v1 (`v1-frozen`)** | 95% Wilson CI (v1) |
|---|---:|---:|---:|---:|---|
| `val` | 500 | _n/a_ | _n/a_ | **99.6%** (498/500) | `[98.6%, 99.9%]` |
| `test_real_v2` (fresh held-out set) | 50 | 46.0% | 58.0% | **88.0%** (44/50) | `[76.2%, 94.4%]` |
| `test_real` (original realistic) | 80 | 50.0% | 51.2% | **91.2%** (73/80) | `[83.0%, 95.7%]` |
| `test_synthetic` (original synthetic) | 500 | 44.6% | 60.2% | **97.6%** (488/500) | `[95.9%, 98.6%]` |

*Decision note:* Under our pre-registered rule, v1 and v2 are statistically indistinguishable on `val` (both 99.6%) and `test_real_v2` (both 88.0%); v2 was selected (`SHIP_V2`) because it passed all three gates with lower validation loss (`0.003975` vs `0.004240`). This v1 adapter remains public as the frozen fallback.

## Limitations

Excel dialect only (~35 / 36 exact in-scope functions, volatile functions excluded), synthetic training data, bounded single-sheet ranges (`2..N`), and small fresh held-out set (`N=50`, 95% Wilson CIs about 17-20 pp wide (roughly ±9 pp); AI-drafted with access to the repository including the v1 error analysis, reviewed and approved by Abu Bakar on 26 November 2026; therefore not fully independent).
