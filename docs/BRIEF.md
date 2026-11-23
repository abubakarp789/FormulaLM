# FormulaLM — Project Brief (source of truth)

> Saved verbatim-in-substance from the kickoff brief on Mon 23 Nov 2026. If anything here conflicts with a later instruction from Abubakar, the later instruction wins and this file should be updated.

---

## 1. Role and working rules

The assistant acts as senior ML engineer and pair programmer for Abubakar (solo participant) during a one-week hackathon.

- No code or project files are created until a numbered prompt (PROMPT 1, PROMPT 2, ...) is sent.
- For each task: state a short plan → implement → run the checks that can be run → summarize what changed and what to verify. Make small, meaningful git commits.
- **Never invent** results, metrics, file contents, library APIs or dataset facts. If unsure, say so and verify (read docs, run code). **Every number in the README must come from a real run saved in `results/`.**
- Ask before anything destructive, expensive or paid. Free tools only.
- The assistant cannot run Colab/Kaggle GPU sessions. For training steps, produce a ready-to-run notebook or script plus clear instructions; Abubakar pastes back logs and results.
- Prefer simple, reproducible, well-documented solutions over clever ones. Fix random seeds, pin versions, log configs.
- Secrets (Hugging Face and ModelScope tokens) stay out of the repo. Use environment variables.
- Python tooling: use `uv` exclusively (no pip/poetry/conda/venv).

## 2. The event

- **Name:** Qwen Local Hackathon 2026, organized by Qwen Pakistan. Fully online, free, one week.
- **Mission:** take a small Qwen model, make it better at one thing, make it smaller, and run it on your own machine. No big GPU needed (laptop, Apple Silicon Mac, or free Colab/Kaggle notebook).
- **Requirement:** pick a small open-weight Qwen model and do at least one of:
  - (a) fine-tune it for a specific task with LoRA or QLoRA,
  - (b) quantize it so it fits and runs well on everyday hardware,
  - (c) run it locally with llama.cpp, Ollama, MLX or vLLM.
  
  Then build a small demo that shows it doing something useful. No training from scratch.

### Timeline (PKT = GMT+5)

| Date | Event |
|---|---|
| Fri 20 Nov, 11:59 PM | Registration closed (Abubakar is registered) |
| Mon 23 Nov, 10:30 PM | Live kickoff on Microsoft Teams (moved from 7:00 PM / Google Meet; recorded) |
| Mon 23 – Sat 28 Nov | Build week; help in the Qwen Pakistan WhatsApp community |
| **Sat 28 Nov, 11:59 PM** | **Submissions close** |
| Sun 29 Nov, 8:00 PM | Results announced |

Project start date: Mon 23 Nov 2026.

### Submission must include

1. **The model:** fine-tuned weights or adapter, plus the quantized version if made, published on ModelScope or Hugging Face.
2. **A public GitHub repo** with a README covering base model, data, method, hardware used, and before-and-after results.
3. **A 2–3 minute demo video** of the model running locally.

### Judging criteria

- **Usefulness** — does it solve a real problem?
- **Technical work** — is the fine-tuning or quantization done properly?
- **Measured results** — before-and-after numbers, not just vibes.
- **Runs locally** — how well it performs on modest hardware.
- **Write-up and demo** — could someone else understand and reproduce it?

### Rewards and rules

- Top projects win Qwen API credits and official Qwen swag (exact prizes announced at kickoff). Winners need a free ModelScope account to receive credits.
- Solo or teams up to 3 (Abubakar is solo).
- Use any small open-weight Qwen model and follow its license.
- Build during the hackathon week; older projects don't qualify.
- Only use datasets you are allowed to use; never include private or personal data.
- Judges' decisions are final.

### Suggested tools

- Fine-tuning: Unsloth, LLaMA-Factory, MLX.
- Running locally: llama.cpp, Ollama, MLX.
- Free GPUs: Google Colab, Kaggle.
- Organizer starter repo: <https://github.com/junaiddshaukat/finetune-anywhere> — read it, reuse its approach where helpful, **credit it in the README**.

### Submission mechanics (from the starter repo, read 24 Nov 2026 — confirm against the official event page)

Source: `showcase/qwen-local-hackathon-2026/README.md` in the starter repo.

- Submit by opening **one PR to `junaiddshaukat/finetune-anywhere`** containing only an entry folder `showcase/qwen-local-hackathon-2026/<your-slug>/` (template: `showcase/_template/README.md` + `model.yaml`).
- **Eligibility uses the PR creation time; PRs at or after 19:00:00 UTC Sat 28 Nov (= 00:00 PKT Sun) are late** and not judged.
- Public model link and demo video are both required. Do not commit model weights or files over 5 MB in the PR.
- Judging weights listed there: Usefulness 25%, Proof the fine-tune helped (held-out base vs tuned) 25%, Runs locally and efficiently (quantized, normal laptop, hardware stated) 25%, Demo and write-up 25%.
- Starter defaults confirmed: Qwen3 0.6B / 1.7B / 4B text models, Apache-2.0, `enable_thinking: false`; Qwen3-1.7B revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`.

## 3. About Abubakar

CS graduate focused on AI/ML and full-stack development. Comfortable with Python, FastAPI, Docker, Git/GitHub, pytest and agentic IDEs. **New to hands-on LoRA fine-tuning and quantization** — explain choices briefly and flag pitfalls. Works solo in PKT with limited time each day.

### Setup

| Item | Value |
|---|---|
| OS | Windows 11 |
| CPU and RAM | Intel(R) Core(TM) i5-8365U CPU @ 1.60GHz with 8GB RAM |
| GPU or Apple Silicon | NO |
| Colab/Kaggle access | Yes |
| GitHub repo URL | https://github.com/abubakarp789/FormulaLM.git |
| Hugging Face username | abubakar56 |
| ModelScope username | abubakar56 |

### Answers and decisions (Tue 24 Nov 2026)

- **Kickoff:** attended. No rule changes. Prizes: Qwen API credits.
- **Local tools:** LibreOffice can be installed locally (evaluator fallback). Microsoft Excel is available on the laptop for manual spot-checks.
- **Publishing:** both Hugging Face and ModelScope (username `abubakar56` on both).
- **Time budget:** 3–4 hours per day.
- **Repo:** `abubakarp789/FormulaLM` on GitHub, private for now; made public once the model and project are complete (must be public before the submission deadline). Code license: MIT.

### Hardware implications

- Local machine is **CPU-only, 8 GB RAM** (i5-8365U, 4 cores). All training and full-precision (HF transformers) evaluation of base and fine-tuned models runs on Colab/Kaggle.
- Local machine is used for: data generation, evaluator, unit tests, GGUF inference via Ollama/llama.cpp, the Gradio demo, and size / RAM / tokens-per-second benchmarks.
- Keep the local model small (Qwen3-1.7B Q4_K_M / Q8_0 GGUF) and keep prompts short (compact schema, few-shot only for baselines). Large-batch GGUF evaluation may also be run on Colab/Kaggle CPU/GPU if local runs are too slow; local runs then cover a representative subset plus the speed/RAM benchmarks.

## 4. The project

**Working title:** FormulaLM (name may change).

**Pitch:** a small Qwen model, fine-tuned with QLoRA and quantized to run locally, that turns plain-English spreadsheet requests into correct Excel formulas, **verified by actually executing them**.

**Why it matters:** many people know what they want from a spreadsheet but not the formula syntax, and cloud AI is not always available or acceptable for private business data, so a small local model is useful.

### Core design decisions

1. **Input and output.** Each prompt contains the sheet schema (column letters, header names, column types) plus the natural-language request. Output is **only the formula string starting with `=`** — no explanations, no markdown.

2. **Scope.** Excel dialect first, ~25–30 functions:
   `SUM, SUMIF, SUMIFS, COUNT, COUNTIF, COUNTIFS, AVERAGE, AVERAGEIF, AVERAGEIFS, MIN, MAX, IF, IFS, AND, OR, VLOOKUP, XLOOKUP, INDEX+MATCH, LEFT, RIGHT, MID, LEN, CONCAT, TEXTJOIN, UPPER, LOWER, PROPER, TRIM, TEXT, DATE, YEAR, MONTH, DAY, ROUND, IFERROR`.
   Exclude volatile functions (TODAY, NOW, RAND) from tests. Google Sheets support is a stretch goal only if time remains. **No further scope creep.**

3. **Data.** Fully synthetic, generated this week from formula templates, random schemas and random values across 20–30 sample sheets (sales, HR, inventory, student grades, expenses, etc.). Request paraphrases come from hand-written patterns and/or the Qwen model itself — **never from other vendors' model outputs**. No private or personal data. Document everything in a dataset card.

4. **Base model.** Qwen3 small models (0.6B, 1.7B, 4B). **Default: Qwen3-1.7B** on a free Colab/Kaggle T4. Verify the license on the model card. Use **non-thinking mode** so output is just the formula. Abubakar will say if the kickoff recommends something different.

5. **Method.** QLoRA with Unsloth, rank 16 as a starting point, ~5k–10k training examples, 2–3 epochs, loss on assistant responses only, then **one improvement iteration** after error analysis.

6. **Evaluation (the heart of the project) is executable.**
   - For each test example: compute the expected value from the sheet with pandas, run the model's formula in a spreadsheet engine (Python `formulas` library or LibreOffice headless), compare.
   - **Metrics:** syntax validity rate, execution accuracy, normalized exact match, breakdowns by function category and difficulty.
   - **Test sets:** (a) held-out synthetic set with unseen phrasings and unseen schemas; (b) ~80 hand-written realistic requests.
   - **Systems compared:** base zero-shot, base few-shot, fine-tuned, quantized (Q4_K_M and Q8_0).
   - **Also measure:** model size, RAM use and tokens/second on Abubakar's machine.

7. **Local running.** Export GGUF and run via Ollama and/or llama.cpp.

8. **Demo.** Small Gradio app: user pastes column headers (or uploads a small CSV), types a request, gets the formula, and sees it executed on sample data with the result. Optional side-by-side with the base model.

9. **Deliverables.**
   - Models on Hugging Face and/or ModelScope (adapter, merged, GGUF) with model cards.
   - Public GitHub repo with README: base model, data, method, hardware, before/after table, limitations, reproduction steps.
   - 2–3 minute demo video.

### Planned repo layout

```
README.md
docs/          # brief, dataset card, design notes
config/        # training / eval / generation configs
data/          # schemas/, templates/, generated/
src/           # data generation, evaluation, inference
app/           # Gradio demo
notebooks/     # training (Colab/Kaggle)
results/       # all raw evaluation outputs (JSON/CSV)
tests/         # pytest: data generation + evaluator
scripts/       # CLI entry points
```

Keep the commit history active from now until submission. Nothing from older projects.

### Quality bar

- Reproducible with fixed seeds.
- Unit tests for data generation and the evaluator.
- No train/test leakage (check templates, schemas and exact duplicates).
- Honest reporting, including failures and limitations.
