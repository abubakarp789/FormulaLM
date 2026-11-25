# FormulaLM

> A small Qwen3 model, fine-tuned with QLoRA and quantized to run on a CPU-only laptop, that turns plain-English spreadsheet requests into Excel formulas — **verified by actually executing them**.

**Status:** work in progress for the Qwen Local Hackathon 2026 (23–28 Nov 2026). Every number in this README will come from a run saved in [`results/`](results/). Sections marked _TBD_ are filled in only after the corresponding run exists.

| | |
|---|---|
| Models | _TBD_ — Hugging Face (`abubakar56`) and ModelScope (`abubakar56`): LoRA adapter, merged weights, GGUF (Q4_K_M, Q8_0) |
| Demo video | _TBD_ |
| License | Code: MIT ([LICENSE](LICENSE)). Model weights: Apache-2.0, inherited from the base model |

## Example

_TBD — a real before/after example from the held-out test set._

```text
Schema:  A: Region (text) | B: Rep (text) | C: Sales (number)
Request: total sales for the North region
Output:  =SUMIF(A:A,"North",C:C)      <- illustrative format only, not a model output
```

## Base model

- [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B), revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, Apache-2.0.
- Used in **non-thinking mode** (`enable_thinking=False`) so the output is only the formula.
- Full base/mirror/adapter provenance: [`docs/MODEL_PROVENANCE.md`](docs/MODEL_PROVENANCE.md).
- Why this size: _TBD_.

## Data

- Fully synthetic, generated from formula templates, random schemas and random values across 25 sample sheets (11 domains: sales, HR, inventory, grades, expenses, orders, project tracking, attendance, subscriptions, support tickets, marketing).
- Request paraphrases: phrasing patterns and semantic-preserving rewrite rules only. No other vendors' model outputs were used to generate training data via API, and no private or personal data is included.
- Scope: 36 Excel functions (`SUM`/`COUNT`/`AVERAGE` families with `IF`/`IFS` variants, `MIN`, `MAX`, `IF`, `IFS`, `AND`, `OR`, `VLOOKUP`, `XLOOKUP`, `INDEX`+`MATCH`, text functions, `DATE`/`YEAR`/`MONTH`/`DAY`, `ROUND`, `IFERROR`). Volatile functions excluded.
- Splits: v1 (`train`: 8,000, `val`: 500, `test_synthetic`: 500 on 5 held-out sheets + 2 reserved phrasings/template); v2 (`train_v2`: 9,000 on the 20 training sheets only, with `val` and `test_synthetic` bit-for-bit frozen). See [`data/DATASET_CARD.md`](data/DATASET_CARD.md) and [`docs/v2_changelog.md`](docs/v2_changelog.md).

### Authorship and evaluation provenance

- The 60 formula templates, their phrasing patterns, the v2 train-only phrasings/templates (`src/data/v2_augmentations.py`), the initial draft of `data/test_real/test_real_DRAFT.csv`, and the 50 post-v2 fresh requests in `data/test_real_v2/` (created after v2 training finished) were drafted with an AI assistant and reviewed/run by Abubakar.
- Because the v2 data additions were informed by v1 error analysis on `test_synthetic` and `test_real`, any v2 metric on those two original test sets is labeled **informed by v1 error analysis**.
- `data/test_real_v2/test_real_v2.csv` (50 executor-verified requests on the 5 held-out sheets, zero overlap with `test_real`) is evaluated identically on both v1 and v2 alongside `val.jsonl` and reported separately (noting transparently that it is AI-drafted post-v2 rather than independently human-authored).

## Method

- QLoRA with [Unsloth](https://github.com/unslothai/unsloth) (`r=16`, `alpha=32`, `dropout=0`, all 7 linear layers, `max_seq_length=512`, non-thinking mode, loss on assistant responses only).
- **Frozen v1 (`v1-frozen`, `checkpoint-200`):** 2 epochs, `lr=2e-4`, peak VRAM 1.65 GB on Colab Tesla T4 (34.5 min), best `val` loss `0.004240` at step 200 (`results/train_qlora_v1/`).
- **Iteration v2 (`config/train_qlora_v2.yaml`):** 1 epoch, `lr=1e-4`, `weight_decay=0.05`, `eval_steps=50` on `val.jsonl`, plus train-only v2 phrasings/ratio templates logged in [`docs/v2_changelog.md`](docs/v2_changelog.md).
- Export to GGUF (`Q4_K_M`, `Q8_0`) with llama.cpp; run locally via Ollama / llama.cpp (_TBD_).

## Evaluation

Executable: each predicted formula is computed in Python `formulas` 1.3.4 on the test sheet and compared with the expected value computed independently with pandas (`tol=1e-6`, type-aware).

- Metrics: syntax validity rate, execution accuracy, normalized exact match; breakdowns by function category and difficulty.
- Test sets:
  - `test_synthetic` (500 examples: 5 unseen held-out sheets + 2 reserved phrasings per template)
  - `test_real` (80 hand-written realistic requests on the 5 held-out sheets)
  - `test_real_v2` (50 post-v2 fresh requests authored with an AI assistant after v2 training finished, reported separately)

## Before / after results

All filled numbers come directly from saved runs in [`results/`](results/). v2 results on `test_synthetic` and `test_real` are labeled **informed by v1 error analysis**; the fresh blind set (`test_real_v2`) is reported in its own column.

| System | Syntax valid (`syn` / `real`) | Exec. acc. (`test_synthetic`, 500) | Exec. acc. (`test_real`, 80) | Exact match (`syn` / `real`) | Exec. acc. (`val`, 500) | Exec. acc. (`test_real_v2`, 50) |
|---|---:|---:|---:|---:|---:|---:|
| Base `Qwen3-1.7B`, zero-shot | 71.8% / 81.2% | 44.6% `[40.3%, 49.0%]` | 50.0% `[39.3%, 60.7%]` | 36.6% / 42.5% | _n/a_ | 46.0% `[33.0%, 59.6%]` |
| Base `Qwen3-1.7B`, 5-shot (from train) | 85.0% / 85.0% | 60.2% `[55.9%, 64.4%]` | 51.2% `[40.5%, 61.9%]` | 51.2% / 41.2% | _n/a_ | 58.0% `[44.2%, 70.6%]` |
| Fine-tuned v1 (`v1-frozen`, 16-bit) | 99.6% / 100.0% | 97.6% `[95.9%, 98.6%]` | 91.2% `[83.0%, 95.7%]` | 97.0% / 91.2% | 99.6% `[98.6%, 99.9%]` | 88.0% `[76.2%, 94.4%]` |
| **Fine-tuned v2 (`v2-ship`, 16-bit adapter)**\* | **99.8% / 100.0%** | **98.8%** `[97.4%, 99.5%]`\* | **93.8%** `[86.2%, 97.3%]`\* | **97.6% / 93.8%**\* | **99.6%** `[98.6%, 99.9%]` | **88.0%** `[76.2%, 94.4%]` |
| Fine-tuned v2 Merged `F16` GGUF\* | 100.0% / 100.0% | 98.8% `[97.4%, 99.5%]`\* | 93.8% `[86.2%, 97.3%]`\* | 97.6% / 93.8%\* | 99.8% `[98.9%, 100.0%]` | 88.0% `[76.2%, 94.4%]` |
| Fine-tuned v2 `Q8_0` GGUF\* | 99.8% / 100.0% | 98.6% `[97.1%, 99.3%]`\* | 93.8% `[86.2%, 97.3%]`\* | 97.4% / 93.8%\* | 99.8% `[98.9%, 100.0%]` | 86.0% `[73.8%, 93.0%]` |
| **Fine-tuned v2 `Q5_K_M` GGUF (Recommended)**\* | **99.6% / 100.0%** | **98.4%** `[96.9%, 99.2%]`\* | **93.8%** `[86.2%, 97.3%]`\* | **96.4% / 93.8%**\* | **99.6%** `[98.6%, 99.9%]` | **90.0%** `[78.6%, 95.7%]` |
| Fine-tuned v2 `Q4_K_M` GGUF\* | 99.4% / 98.8% | 95.4% `[93.2%, 96.9%]`\* | 88.8% `[80.0%, 94.0%]`\* | 91.8% / 88.8%\* | 97.4% `[95.6%, 98.5%]` | 90.0% `[78.6%, 95.7%]` |

\* _Fine-tuned v2 results on `test_synthetic` and `test_real` are **informed by v1 error analysis** (v2 data additions targeted v1 failure clusters). Brackets show 95% Wilson confidence intervals. Full comparisons: [`results/ft_v2_comparison.md`](results/ft_v2_comparison.md) and [`results/quant_comparison.md`](results/quant_comparison.md)._

## Hardware and local performance

- Training: Google Colab Tesla T4 (14.56 GB VRAM) — `qlora_v1`: 34.5 min, peak 1.65 GB VRAM; `qlora_v2`: 19.0 min, peak 4.19 GB VRAM.
- Local inference: Windows 11 laptop, Intel Core i5-8365U (4 cores / 8 threads), 8 GB RAM, **no GPU** (Ollama `0.40.18`).

| Model file | Size on disk | Load time | Peak RAM | Tokens/s | Local 130-ex Exec. Acc (95% CI) | Measured on |
|---|---:|---:|---:|---:|---|---|
| `formulalm-qwen3-1.7b-v2-q4_k_m.gguf` | 1,056.1 MB | 4.60 s | 1,333 MB | 12.7 tok/s | 89.2% (116/130, `[82.7%, 93.5%]`) | i5-8365U CPU, 8 GB RAM (Ollama) |
| **`formulalm-qwen3-1.7b-v2-q5_k_m.gguf` (Recommended)** | **1,199.6 MB** | **2.64 s** | **1,476 MB** | **11.3 tok/s** | **90.8%** (118/130, `[84.6%, 94.6%]`) | i5-8365U CPU, 8 GB RAM (Ollama) |
| `formulalm-qwen3-1.7b-v2-q8_0.gguf` | 1,749.5 MB | 5.93 s | 2,026 MB | 7.8 tok/s | 91.5% (119/130, `[85.5%, 95.2%]`) | i5-8365U CPU, 8 GB RAM (Ollama) |

## Demo

Local Gradio web app ([`app/app.py`](app/app.py)) running 100% on `localhost` with **zero external network calls at inference time**:

- **Inputs:** choose any of the 5 held-out spreadsheets, upload a small `.csv` / `.xlsx` (`<= 1.0 MB`), or paste column headers / mini-CSV rows, plus a plain-English request.
- **Backend (8 GB RAM safe):** connects to local Ollama (`formulalm`, `Q5_K_M` GGUF from [`deploy/Modelfile`](deploy/Modelfile)) or a local `llama-server`, with `OLLAMA_MAX_LOADED_MODELS=1` so two models are never loaded simultaneously.
- **Executable verification:** runs every generated formula on the sheet via `src.eval.executor.run_formula`, displays the computed result alongside sample rows (and ground truth for built-in examples), or surfaces structured syntax/runtime error details.
- **Honest comparison & examples:** includes 8 built-in requests from `test_real_v2` across all 5 held-out sheets — including an honestly labeled failure case (`real_v2_050`, off-by-one `VLOOKUP` column index) — plus a toggle showing **saved** `Qwen3-1.7B` base-model predictions from `results/baseline_*` without loading a second model in RAM.

```powershell
# One-command launch on Windows PowerShell (sets OLLAMA_MAX_LOADED_MODELS=1,
# registers 'formulalm' from deploy/Modelfile if needed, opens http://127.0.0.1:7860):
.\scripts\run_demo.ps1

# Offline smoke mode (no Ollama / llama-server needed):
.\scripts\run_demo.ps1 -Backend mock
```

## Reproduce

```bash
# Local (Windows/macOS/Linux), requires uv: https://docs.astral.sh/uv/
uv sync                 # create .venv from uv.lock
uv run pytest           # unit tests
# Windows PowerShell task runner: .\scripts\tasks.ps1 test | data | eval
# Linux/macOS/Git Bash:            make test | data | eval
```

Data generation, training notebook, evaluation and export steps: _TBD_.

## Limitations

_TBD — written honestly from the error analysis._

## Credits

- Organizer starter repo: [junaiddshaukat/finetune-anywhere](https://github.com/junaiddshaukat/finetune-anywhere) (M Junaid, Qwen Pakistan) — approach and training-environment pins reused where noted.
- [Qwen](https://github.com/QwenLM) for the Qwen3 models; [Unsloth](https://github.com/unslothai/unsloth); [llama.cpp](https://github.com/ggml-org/llama.cpp); [Ollama](https://github.com/ollama/ollama); [formulas](https://github.com/vinci1it2000/formulas); [Gradio](https://github.com/gradio-app/gradio).
- Built for the Qwen Local Hackathon 2026 organized by Qwen Pakistan.
