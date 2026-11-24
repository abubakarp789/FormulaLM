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
- Why this size: _TBD_.

## Data

- Fully synthetic, generated from formula templates, random schemas and random values across 25 sample sheets (11 domains: sales, HR, inventory, grades, expenses, orders, project tracking, attendance, subscriptions, support tickets, marketing).
- Request paraphrases: hand-written patterns and semantic-preserving rewrite rules only. No other vendors' model outputs. No private or personal data.
- Scope: 36 Excel functions (`SUM`/`COUNT`/`AVERAGE` families with `IF`/`IFS` variants, `MIN`, `MAX`, `IF`, `IFS`, `AND`, `OR`, `VLOOKUP`, `XLOOKUP`, `INDEX`+`MATCH`, text functions, `DATE`/`YEAR`/`MONTH`/`DAY`, `ROUND`, `IFERROR`). Volatile functions excluded.
- Splits: v1 (`train`: 8,000, `val`: 500, `test_synthetic`: 500 on 5 held-out sheets + 2 reserved phrasings/template); v2 (`train_v2`: 9,000 on the 20 training sheets only, with `val` and `test_synthetic` bit-for-bit frozen). See [`data/DATASET_CARD.md`](data/DATASET_CARD.md) and [`docs/v2_changelog.md`](docs/v2_changelog.md).

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
  - `test_real_v2` (~50 fresh blind hand-written requests authored after v2 training, reported separately)

## Before / after results

All filled numbers come directly from saved runs in [`results/`](results/). v2 results on `test_synthetic` and `test_real` are labeled **informed by v1 error analysis**; the fresh blind set (`test_real_v2`) is reported in its own column.

| System | Syntax valid (`syn` / `real`) | Exec. acc. (`test_synthetic`, 500) | Exec. acc. (`test_real`, 80) | Exact match (`syn` / `real`) | Exec. acc. (`test_real_v2` blind) |
|---|---:|---:|---:|---:|---:|
| Base `Qwen3-1.7B`, zero-shot | 71.8% / 81.2% | 44.6% | 50.0% | 36.6% / 42.5% | _TBD_ |
| Base `Qwen3-1.7B`, 5-shot (from train) | 85.0% / 85.0% | 60.2% | 51.2% | 51.2% / 41.2% | _TBD_ |
| **Fine-tuned v1 (`v1-frozen`, 16-bit)** | **99.6% / 100.0%** | **97.6%** | **91.2%** | **97.0% / 91.2%** | _TBD_ |
| Fine-tuned v2 (16-bit, _informed by v1 error analysis_) | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| Fine-tuned Q8_0 GGUF | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| Fine-tuned Q4_K_M GGUF | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

## Hardware and local performance

- Training: _TBD_ (free Colab/Kaggle T4).
- Local inference: Windows 11 laptop, Intel Core i5-8365U, 8 GB RAM, **no GPU**.

| Model file | Size on disk | Peak RAM | Tokens/s | Measured on |
|---|---|---|---|---|
| _TBD_ | | | | |

## Demo

_TBD_ — Gradio app (`app/`): paste headers or upload a small CSV, type a request, get the formula and see it executed on sample data.

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
