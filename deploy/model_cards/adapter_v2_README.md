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

# FormulaLM — Qwen3-1.7B LoRA Adapter (`v2-ship`)

PEFT LoRA adapter (`r=16`, `lora_alpha=32`, `lora_dropout=0.0`, all 7 linear layers) trained with Unsloth QLoRA on `Qwen/Qwen3-1.7B` in **non-thinking mode** to convert spreadsheet schemas + plain-English requests into single executable Excel formulas (`=...`).

- **Recommended local GGUF release (`Q5_K_M`, 1.20 GB):** [`abubakar56/formulalm-qwen3-1.7b-gguf`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf)
- **Frozen fallback adapter (`v1-frozen`):** [`abubakar56/formulalm-qwen3-1.7b-lora`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora)
- **Base model:** [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B) (revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, **Apache-2.0**)
- **Source code:** [`abubakarp789/FormulaLM`](https://github.com/abubakarp789/FormulaLM) (MIT code license)
- **License:** **Apache-2.0**, inherited from [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B). Credit to the Qwen team and [`junaiddshaukat/finetune-anywhere`](https://github.com/junaiddshaukat/finetune-anywhere).

> **Base-model merge note:** Unsloth records `unsloth/Qwen3-1.7B-unsloth-bnb-4bit` (`a972f430...`) in `adapter_config.json` during 4-bit QLoRA training. For 16-bit evaluation and GGUF merging, explicitly load `Qwen/Qwen3-1.7B` at revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` in `float16` before calling `PeftModel.from_pretrained(...)` (verified lossless: 20/20 raw parity between HF merged FP16 and GGUF F16).

## Quick Start (`transformers` + `peft`)

```python
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_ID = "Qwen/Qwen3-1.7B"
BASE_REV = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
ADAPTER_ID = "abubakar56/formulalm-qwen3-1.7b-lora-v2"

tok = AutoTokenizer.from_pretrained(BASE_ID, revision=BASE_REV)
base = AutoModelForCausalLM.from_pretrained(
    BASE_ID, revision=BASE_REV, dtype=torch.float16, device_map="auto"
)
model = PeftModel.from_pretrained(base, ADAPTER_ID).eval()

messages = [
    {
        "role": "system",
        "content": (
            "You are FormulaLM. Given a spreadsheet schema and a user request, reply with only "
            "the Excel formula starting with '='. No explanation, no markdown."
        ),
    },
    {
        "role": "user",
        "content": (
            "Sheet: sales_retail_store (rows 2..115)\n"
            "Columns:\nA: Receipt Code (text)\nB: Sale Date (date)\n"
            "C: Store Branch (category)\nD: Item Name (text)\n"
            "E: Quantity (integer)\nF: Net Amount (decimal)\n\n"
            "Request: Total Net Amount for the Mirehaven branch"
        ),
    },
]
prompt = tok.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
)
inputs = tok(prompt, return_tensors="pt").to(model.device)
out = model.generate(**inputs, max_new_tokens=96, do_sample=False)
print(tok.decode(out[0, inputs["input_ids"].shape[1] :], skip_special_tokens=True).strip())
```

For local CPU inference via Ollama or `llama.cpp`, use the ready-to-run `Q5_K_M` GGUF and `Modelfile` in [`abubakar56/formulalm-qwen3-1.7b-gguf`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf).

## Training Summary & Hyperparameters

- **Data:** 9,000 execution-verified synthetic examples (`train_v2.jsonl`, 0 dropped) on 20 training sheets (11 domains, 36 Excel functions, 0 personal data, 0 third-party LLM outputs); 5 held-out sheets never seen during training. Templates, phrasing patterns, v2 augmentations, draft `test_real`, and post-v2 `test_real_v2` were drafted with an AI assistant and reviewed/run by Abubakar.
- **Hyperparameters (`config/train_qlora_v2.yaml`):** 4-bit QLoRA, `r=16`, `lora_alpha=32`, `lora_dropout=0.0`, target modules `q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj`, `max_seq_length=512`, `train_on_responses_only` (`enable_thinking=False`), `num_train_epochs=1` (563 steps), effective batch 16 (`4 × 4`), `lr=1e-4` cosine, `warmup_ratio=0.08`, `weight_decay=0.05`, `adamw_8bit`, `eval_steps=50`, `seed=42`, best checkpoint `checkpoint-400` (`val_loss=0.003975`).
- **Hardware:** Free Google Colab Tesla T4 (14.56 GB VRAM) — 19.0 min, peak 4.19 GB VRAM.

## Decision Rule & Headline Evaluation (16-bit fp16, 95% Wilson CIs)

> **Pre-registered rule:** Ship v2 only if its execution accuracy is at least as high as v1 on `val` AND on `test_real_v2`, and not meaningfully worse on `test_real` (drop ≤ 2.5 pp); otherwise ship v1.

**Verdict:** **`SHIP_V2`** — v1 and v2 are **statistically indistinguishable** on `val` (both **99.6%**, 498/500) and `test_real_v2` (both **88.0%**, 44/50), and v2's small gains on `test_synthetic` (+1.2 pp) and `test_real` (+2.5 pp) are within sampling noise and informed by v1 error analysis.

| Test Set | System | N | **Exec. Accuracy** | 95% Wilson CI | Syntax Valid | Exact Match |
|---|---|---:|---:|---|---:|---:|
| `test_real_v2` (post-v2 fresh) | Base 0-shot / 5-shot | 50 | **46.0% / 58.0%** | `[33.0%, 59.6%]` / `[44.2%, 70.6%]` | 76.0% / 88.0% | 40.0% / 46.0% |
| `test_real_v2` (post-v2 fresh) | v1 (`v1-frozen`) / **v2 (`v2-ship`)** | 50 | **88.0% / 88.0%** | `[76.2%, 94.4%]` / `[76.2%, 94.4%]` | 100.0% / 100.0% | 82.0% / 86.0% |
| `test_real` (original) | Base 0-shot / 5-shot | 80 | **50.0% / 51.2%** | `[39.3%, 60.7%]` / `[40.5%, 61.9%]` | 81.2% / 85.0% | 42.5% / 41.2% |
| `test_real` (original) | v1 / **v2** *(informed by v1 error analysis)* | 80 | **91.2% / 93.8%** | `[83.0%, 95.7%]` / `[86.2%, 97.3%]` | 100.0% / 100.0% | 91.2% / 93.8% |
| `test_synthetic` (original) | Base 0-shot / 5-shot | 500 | **44.6% / 60.2%** | `[40.3%, 49.0%]` / `[55.9%, 64.4%]` | 71.8% / 85.0% | 36.6% / 51.2% |
| `test_synthetic` (original) | v1 / **v2** *(informed by v1 error analysis)* | 500 | **97.6% / 98.8%** | `[95.9%, 98.6%]` / `[97.4%, 99.5%]` | 99.6% / 99.8% | 97.0% / 97.6% |

### Quantization & Local Laptop Summary (`i5-8365U`, 8 GB RAM, CPU-only, Ollama `0.40.18`)

- `Q4_K_M` (`1,056.1 MB`) loses 2.4–5.0 pp vs merged F16 on Colab (`val` 97.4%, `test_real` 88.8%, `test_synthetic` 95.4%).
- **`Q5_K_M` (`1,199.6 MB`, recommended)** stays within ±0.4 pp of F16 on all 4 splits (`val` 99.6%, `test_real_v2` 90.0%, `test_real` 93.8%, `test_synthetic` 98.4%), uses **1,476 MB RAM** on an 8 GB CPU-only laptop, loads in **2.64 s**, runs at **11.3 tok/s**, and achieves **90.8%** (118/130, `[84.6%, 94.6%]`) locally on Ollama (note: local CPU Ollama/llama.cpp runs can differ by 1–2 examples from Colab T4 CUDA).

## Limitations

Excel dialect only (~35 / 36 exact in-scope functions, no volatile functions), single-sheet bounded ranges (`2..N`), synthetic training data, and small post-v2 evaluation set (`N=50`). Always review generated formulas before relying on them in production spreadsheets.
