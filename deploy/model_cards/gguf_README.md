---
license: apache-2.0
base_model: Qwen/Qwen3-1.7B
language:
- en
pipeline_tag: text-generation
library_name: gguf
tags:
- qwen3
- excel
- spreadsheet
- formula-generation
- qlora
- gguf
- ollama
- llama.cpp
- qwen-local-hackathon-2026
---

# FormulaLM — Qwen3-1.7B v2 (GGUF)

**FormulaLM** is a 1.7B Qwen3 model fine-tuned with QLoRA and quantized to GGUF to run locally on CPU-only laptops. Given a spreadsheet schema and a plain-English request, it outputs **only a single executable Excel formula starting with `=`** (no prose, no markdown), evaluated by actually executing formulas against independent pandas ground truths.

- **Primary shipping file:** `formulalm-qwen3-1.7b-v2-q5_k_m.gguf` (**1,199.6 MB**, `Q5_K_M`, recommended from measured accuracy/RAM/speed data)
- **Optional files in this repo:** `formulalm-qwen3-1.7b-v2-q8_0.gguf` (`1,749.5 MB`) and `formulalm-qwen3-1.7b-v2-q4_k_m.gguf` (`1,056.1 MB`)
- **Ollama Modelfiles included:** `Modelfile` (primary `Q5_K_M`), `Modelfile.Q5_K_M`, `Modelfile.Q8_0`, `Modelfile.Q4_K_M`
- **Base model:** [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B) (revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, **Apache-2.0**)
- **LoRA adapter (v2-ship):** [`abubakar56/formulalm-qwen3-1.7b-lora-v2`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora-v2) (commit `e2dd7e8115406ffcdbbdfa60d6f2f10b4aaf2595`)
- **Frozen fallback (v1-frozen):** [`abubakar56/formulalm-qwen3-1.7b-lora`](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora) (commit `d9909249c496134ecc72e1d77bdc22e6e0461537`)
- **Source code & evaluation harness:** [`abubakarp789/FormulaLM`](https://github.com/abubakarp789/FormulaLM) (MIT code license)
- **License:** **Apache-2.0**, inherited from [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B). Full credit to the Qwen team for Qwen3 and to [`junaiddshaukat/finetune-anywhere`](https://github.com/junaiddshaukat/finetune-anywhere) (Qwen Pakistan) for the hackathon starter approach.

---

## Quick Start — Run Locally with Ollama (`Q5_K_M`)

Requires [Ollama](https://ollama.com) (tested on **Windows 11, Intel Core i5-8365U, 8 GB RAM, CPU-only, Ollama `0.40.18`** — uses **1,476 MB RAM** and runs at **11.3 tok/s**).

```bash
# 1. Download the primary Q5_K_M GGUF and Modelfile into a clean folder
mkdir formulalm-local && cd formulalm-local
curl -L -o formulalm-qwen3-1.7b-v2-q5_k_m.gguf \
  https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf/resolve/main/formulalm-qwen3-1.7b-v2-q5_k_m.gguf
curl -L -o Modelfile \
  https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf/resolve/main/Modelfile

# 2. Register the model in Ollama (reproduces exact Qwen3 non-thinking training template)
ollama create formulalm -f Modelfile

# 3. Run a test query (--think=false keeps Qwen3 in non-thinking formula-only mode)
ollama run --think=false formulalm "Sheet: sales_retail_store (rows 2..115)
Columns:
A: Receipt Code (text)
B: Sale Date (date)
C: Store Branch (category)
D: Item Name (text)
E: Quantity (integer)
F: Net Amount (decimal)

Request: Total Net Amount for the Mirehaven branch"
# Expected output: =SUMIF(C2:C115,"Mirehaven",F2:F115)
```

*(ModelScope users can download `formulalm-qwen3-1.7b-v2-q5_k_m.gguf` and `Modelfile` from `https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf` and run the exact same `ollama create formulalm -f Modelfile` step.)*

## Quick Start — Run Locally with `llama.cpp`

```bash
# Start llama-server (CPU-only laptop: -ngl 0; GPU: -ngl 99)
llama-server -m formulalm-qwen3-1.7b-v2-q5_k_m.gguf -ngl 0 -c 2048 --port 8080

# Query via /completion using the exact Qwen3 non-thinking prompt format
curl http://127.0.0.1:8080/completion -H "Content-Type: application/json" -d '{
  "prompt": "<|im_start|>system\nYou are FormulaLM. Given a spreadsheet schema and a user request, reply with only the Excel formula starting with '\''='\''. No explanation, no markdown.<|im_end|>\n<|im_start|>user\nSheet: demo (rows 2..50)\nColumns:\nA: Region (category)\nB: Revenue (decimal)\n\nRequest: Total Revenue for North<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
  "temperature": 0.0,
  "n_predict": 96,
  "stop": ["<|im_end|>", "<|endoftext|>"]
}'
```

---

## Exact Prompt Format (Qwen3 Non-Thinking Mode)

The model was trained with `enable_thinking=False` and loss computed on assistant formula tokens only:

- **System message (verbatim):**
  ```text
  You are FormulaLM. Given a spreadsheet schema and a user request, reply with only the Excel formula starting with '='. No explanation, no markdown.
  ```
- **User message:**
  ```text
  Sheet: <sheet_id> (rows 2..<last_row>)
  Columns:
  A: <Header 1> (<type>)
  B: <Header 2> (<type>)
  ...

  Request: <plain-English request>
  ```
- **Rendered ChatML prefix before assistant output:**
  ```text
  <|im_start|>assistant
  <think>

  </think>

  ```
- **Prompt-format parity verification:** Comparing the merged HF FP16 model against the exported GGUF F16 on 20 fixed examples from `test_real_v2` achieved **20/20 (100.0%)** raw string match, normalized formula match, and executed value agreement.

---

## Training Data & Method

- **Synthetic dataset:** 100% synthetic across 25 generated spreadsheets (11 business/academic domains; 20 training sheets, 5 held-out test sheets) covering 36 in-scope Excel functions (volatile functions `TODAY`, `NOW`, `RAND` excluded). Zero real/personal data; zero API outputs from other vendors' models.
  - **v1 (`train.jsonl`):** 8,000 verified examples (60 templates, 422 phrasing patterns + 10 deterministic rewrite rules; 0 dropped).
  - **v2 (`train_v2.jsonl`):** 9,000 verified examples on the 20 training sheets only (adds 58 train-only phrasings + 2 ratio templates targeting v1 error clusters; `val.jsonl` 500 and `test_synthetic.jsonl` 500 stay bit-for-bit frozen; 0 dropped).
  - **Authorship disclosure:** The formula templates, phrasing patterns, v2 augmentations, initial draft of `test_real` (80 requests), and post-v2 `test_real_v2` (50 requests, created after v2 training finished) were drafted with an AI assistant and reviewed/run by Abubakar.
- **QLoRA training (`v2-ship`, Unsloth):** 4-bit QLoRA (`r=16`, `lora_alpha=32`, `lora_dropout=0.0`, all 7 linear layers `q/k/v/o/gate/up/down_proj`), `max_seq_length=512`, `train_on_responses_only`, 1 epoch (563 steps), effective batch 16 (`4 × 4`), `lr=1e-4` cosine, `warmup_ratio=0.08`, `weight_decay=0.05`, `adamw_8bit`, `seed=42`, `eval_steps=50` on `val.jsonl` only. Best checkpoint: `checkpoint-400` (`val` loss `0.003975`).
- **Merge & GGUF export:** LoRA adapter (`e2dd7e81`) merged explicitly into pinned fp16 `Qwen/Qwen3-1.7B@70d244cc` (overriding the 4-bit mirror in `adapter_config.json`), then converted and quantized with `llama.cpp` release `b12728`.
- **Training hardware:** Free Google Colab Tesla T4 (14.56 GB VRAM) — `qlora_v2` took **19.0 min** (peak **4.19 GB VRAM**); `qlora_v1` took **34.5 min** (peak **1.65 GB VRAM**).

---

## Evaluation Results

Every formula is executed in Python `formulas` 1.3.4 on the target `.xlsx` sheet and checked against an independent pandas ground truth (`tol=1e-6`, type-aware). Brackets show exact **95% Wilson confidence intervals**.

### 1. Pre-registered Model Selection Rule & Honest v1-vs-v2 Assessment

> **Decision rule:** Ship v2 only if its execution accuracy is at least as high as v1 on `val` AND on `test_real_v2`, and not meaningfully worse on `test_real` (drop ≤ 2.5 pp); otherwise ship v1.

- **Verdict:** **`SHIP_V2`** (all three gates passed).
- **Honest statistical note:** v1 (`v1-frozen`) and v2 (`v2-ship`) are **statistically indistinguishable** on `val` (both **99.6%**, 498/500, `[98.6%, 99.9%]`) and `test_real_v2` (both **88.0%**, 44/50, `[76.2%, 94.4%]`). v2's gains on `test_synthetic` (+1.2 pp) and `test_real` (+2.5 pp) have overlapping 95% Wilson CIs (within sampling noise) and were informed by earlier v1 error analysis on those sets. Frozen v1 remains publicly available as the tagged fallback (`v1-frozen`).

### 2. Headline Before / After Results (16-bit fp16 on Colab T4)

| Test Set | System | N | Correct | **Exec. Accuracy** | 95% Wilson CI | Δ vs Base 0-shot | Syntax Valid | Exact Match |
|---|---|---:|---:|---:|---|---:|---:|---:|
| `test_real_v2` (post-v2 fresh) | Base `Qwen3-1.7B` (0-shot) | 50 | 23/50 | **46.0%** | `[33.0%, 59.6%]` | — | 76.0% | 40.0% |
| `test_real_v2` (post-v2 fresh) | Base `Qwen3-1.7B` (5-shot, train) | 50 | 29/50 | **58.0%** | `[44.2%, 70.6%]` | +12.0 pp | 88.0% | 46.0% |
| `test_real_v2` (post-v2 fresh) | Fine-tuned v1 (`v1-frozen`) | 50 | 44/50 | **88.0%** | `[76.2%, 94.4%]` | +42.0 pp | 100.0% | 82.0% |
| `test_real_v2` (post-v2 fresh) | **Fine-tuned v2 (`v2-ship`)** | 50 | 44/50 | **88.0%** | `[76.2%, 94.4%]` | +42.0 pp | 100.0% | 86.0% |
| `test_real` (original realistic) | Base `Qwen3-1.7B` (0-shot) | 80 | 40/80 | **50.0%** | `[39.3%, 60.7%]` | — | 81.2% | 42.5% |
| `test_real` (original realistic) | Base `Qwen3-1.7B` (5-shot, train) | 80 | 41/80 | **51.2%** | `[40.5%, 61.9%]` | +1.2 pp | 85.0% | 41.2% |
| `test_real` (original realistic) | Fine-tuned v1 (`v1-frozen`) | 80 | 73/80 | **91.2%** | `[83.0%, 95.7%]` | +41.2 pp | 100.0% | 91.2% |
| `test_real` (original realistic) | **Fine-tuned v2 (`v2-ship`)** *(informed by v1 error analysis)* | 80 | 75/80 | **93.8%** | `[86.2%, 97.3%]` | +43.8 pp | 100.0% | 93.8% |
| `test_synthetic` (original synthetic) | Base `Qwen3-1.7B` (0-shot) | 500 | 223/500 | **44.6%** | `[40.3%, 49.0%]` | — | 71.8% | 36.6% |
| `test_synthetic` (original synthetic) | Base `Qwen3-1.7B` (5-shot, train) | 500 | 301/500 | **60.2%** | `[55.9%, 64.4%]` | +15.6 pp | 85.0% | 51.2% |
| `test_synthetic` (original synthetic) | Fine-tuned v1 (`v1-frozen`) | 500 | 488/500 | **97.6%** | `[95.9%, 98.6%]` | +53.0 pp | 99.6% | 97.0% |
| `test_synthetic` (original synthetic) | **Fine-tuned v2 (`v2-ship`)** *(informed by v1 error analysis)* | 500 | 494/500 | **98.8%** | `[97.4%, 99.5%]` | +54.2 pp | 99.8% | 97.6% |

### 3. Quantization Quality Comparison (Colab T4 `llama-server`, 95% Wilson CIs)

*\*v2-ship results on `test_real` and `test_synthetic` are **informed by v1 error analysis**.*

| System | Size (MB) | `val` (500) | `test_real_v2` (50) | `test_real` (80)\* | `test_synthetic` (500)\* |
|---|---:|---|---|---|---|
| v2-ship Merged `F16` GGUF *(reference, not shipped)* | 3,287.7 | **99.8%** `[98.9%, 100.0%]` | **88.0%** `[76.2%, 94.4%]` | **93.8%** `[86.2%, 97.3%]` | **98.8%** `[97.4%, 99.5%]` |
| v2-ship `Q8_0` GGUF | 1,749.5 | **99.8%** `[98.9%, 100.0%]` | **86.0%** `[73.8%, 93.0%]` | **93.8%** `[86.2%, 97.3%]` | **98.6%** `[97.1%, 99.3%]` |
| **v2-ship `Q5_K_M` GGUF (Primary)** | **1,199.6** | **99.6%** `[98.6%, 99.9%]` | **90.0%** `[78.6%, 95.7%]` | **93.8%** `[86.2%, 97.3%]` | **98.4%** `[96.9%, 99.2%]` |
| v2-ship `Q4_K_M` GGUF | 1,056.1 | **97.4%** `[95.6%, 98.5%]` | **90.0%** `[78.6%, 95.7%]` | **88.8%** `[80.0%, 94.0%]` | **95.4%** `[93.2%, 96.9%]` |

**Key quantization finding:** `Q4_K_M` loses **2.4–5.0 pp** relative to `F16` (`-2.4 pp` on `val`, `-5.0 pp` on `test_real`, `-3.4 pp` on `test_synthetic`), whereas **`Q5_K_M`** adds only **143.5 MB** (`1,199.6 MB`, 36% of F16) and stays **within sampling noise (`±0.4 pp`) of F16** across all 4 splits.

### 4. Local CPU-Only Laptop Benchmarks

Measured locally on **Windows 11 (10.0.26300), Intel Core i5-8365U (4 cores / 8 threads), 8 GB RAM (3,211 MB free at start), no GPU, Ollama `0.40.18`** on the 130-example subset (`test_real_v2` 50 + `test_real` 80):

| File | Quant | Size (MB) | Cold Load | Peak RAM | Gen tok/s | Local 130-ex Exec. Acc (95% CI) |
|---|---|---:|---:|---:|---:|---|
| `formulalm-qwen3-1.7b-v2-q4_k_m.gguf` | `Q4_K_M` | 1,056.1 | 4.60 s | 1,333 MB | **12.7 tok/s** | **89.2%** (116/130, `[82.7%, 93.5%]`) |
| **`formulalm-qwen3-1.7b-v2-q5_k_m.gguf`** | **`Q5_K_M` (Primary)** | **1,199.6** | **2.64 s** | **1,476 MB** | **11.3 tok/s** | **90.8%** (118/130, `[84.6%, 94.6%]`) |
| `formulalm-qwen3-1.7b-v2-q8_0.gguf` | `Q8_0` | 1,749.5 | 5.93 s | 2,026 MB | 7.8 tok/s | **91.5%** (119/130, `[85.5%, 95.2%]`) |

*Runtime variance note:* Local CPU Ollama / `llama.cpp` results can differ by **1–2 examples** from Colab T4 CUDA runs due to CPU vs CUDA quantized matmul kernel rounding (e.g., on `test_real_v2`, `Q5_K_M` scored 45/50 on Colab CUDA `llama-server` vs 43/50 on Windows CPU Ollama, and `Q8_0` scored 43/50 vs 44/50; both scored 75/80 = 93.8% on `test_real` with 100.0% syntax validity).

---

## Intended Use & Limitations

- **Intended use:** Local, offline generation of single-sheet Microsoft Excel formulas from column schemas and plain-English descriptions, ideal for private business spreadsheets where cloud APIs are undesirable or unavailable.
- **Limitations:**
  - **Excel dialect only:** Not trained for Google Sheets-specific functions (`QUERY`, `FILTER`, `ARRAYFORMULA`, `REGEXMATCH`) or VBA/PowerQuery.
  - **~35 in-scope functions (36 exact):** Covers `SUM`, `SUMIF`, `SUMIFS`, `COUNT`, `COUNTIF`, `COUNTIFS`, `AVERAGE`, `AVERAGEIF`, `AVERAGEIFS`, `MIN`, `MAX`, `IF`, `IFS`, `AND`, `OR`, `VLOOKUP`, `XLOOKUP`, `INDEX`, `MATCH`, `LEFT`, `RIGHT`, `MID`, `LEN`, `CONCAT`, `TEXTJOIN`, `UPPER`, `LOWER`, `PROPER`, `TRIM`, `TEXT`, `DATE`, `YEAR`, `MONTH`, `DAY`, `ROUND`, `IFERROR`. Volatile functions (`TODAY`, `NOW`, `RAND`) and pivot/dynamic-array functions are excluded.
  - **Synthetic training data:** Trained on synthetic single-sheet schemas with bounded data ranges (`2..N`). Multi-sheet workbook references, merged cells, or deeply ambiguous business jargon can fail.
  - **Small post-v2 evaluation set (`N=50`):** `test_real_v2` has 50 AI-drafted post-v2 requests (95% Wilson CI width ~±9 pp), and v2 scores on `test_real` (`N=80`) and `test_synthetic` (`N=500`) are informed by v1 error analysis. Always verify generated formulas before using them in financial or compliance-critical spreadsheets.
