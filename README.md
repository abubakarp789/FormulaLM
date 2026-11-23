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

- Fully synthetic, generated from formula templates, random schemas and random values across ~20–30 sample sheets (sales, HR, inventory, grades, expenses, …).
- Request paraphrases: hand-written patterns and/or Qwen itself. No other vendors' model outputs. No private or personal data.
- Scope: ~30 Excel functions (SUM/COUNT/AVERAGE families with IF/IFS variants, MIN, MAX, IF, IFS, AND, OR, VLOOKUP, XLOOKUP, INDEX+MATCH, text functions, DATE/YEAR/MONTH/DAY, ROUND, IFERROR). Volatile functions excluded.
- Splits, sizes and leakage checks: _TBD_. Dataset card: _TBD_ (`docs/DATASET_CARD.md`).

## Method

- QLoRA with [Unsloth](https://github.com/unslothai/unsloth); loss on assistant responses only.
- Hyperparameters, training time and loss curves: _TBD_ (from `results/`).
- One improvement iteration after error analysis: _TBD_.
- Export to GGUF (Q4_K_M, Q8_0) with llama.cpp; run with Ollama / llama.cpp.

## Evaluation

Executable: each predicted formula is computed in a spreadsheet engine on the test sheet and compared with the expected value computed independently with pandas.

- Metrics: syntax validity rate, execution accuracy, normalized exact match; breakdowns by function category and difficulty.
- Test sets: (a) held-out synthetic set (unseen phrasings, unseen schemas); (b) ~80 hand-written realistic requests.

## Before / after results

_TBD — filled only from `results/`._

| System | Syntax valid | Exec. accuracy (synthetic) | Exec. accuracy (hand-written) | Exact match |
|---|---|---|---|---|
| Base, zero-shot | | | | |
| Base, few-shot | | | | |
| Fine-tuned (16-bit) | | | | |
| Fine-tuned Q8_0 | | | | |
| Fine-tuned Q4_K_M | | | | |

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
