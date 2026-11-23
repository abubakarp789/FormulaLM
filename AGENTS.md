# Agent rules — FormulaLM (Qwen Local Hackathon 2026)

Full source of truth: `docs/BRIEF.md`. Read it at the start of every session.

- Project: fine-tune (QLoRA, Unsloth) + quantize (GGUF, Ollama/llama.cpp) a small Qwen3 model (default Qwen3-1.7B, non-thinking mode) to turn schema + plain-English request into a single Excel formula (`=...` only), evaluated by executing formulas.
- Deadline: **Sat 28 Nov 2026, 11:59 PM PKT**. Deliverables: models on HF/ModelScope, public GitHub repo with README, 2–3 min demo video. Submission = one PR to `junaiddshaukat/finetune-anywhere` adding `showcase/qwen-local-hackathon-2026/<slug>/` before 19:00 UTC (see BRIEF).
- Only act on numbered prompts (PROMPT N). Plan → implement → check → summarize → small git commit.
- Never invent results, metrics, APIs or dataset facts. Every README number must come from a run saved in `results/`.
- Ask before destructive/expensive/paid actions. Free tools only. Secrets via env vars, never committed.
- Training runs happen on the user's Colab/Kaggle: deliver ready-to-run notebooks/scripts + instructions.
- Python tooling: `uv` only. Fixed seeds, pinned versions, logged configs. No train/test leakage. No scope creep beyond the ~30 listed Excel functions.
- Local machine: Windows 11, i5-8365U, 8 GB RAM, **no GPU** — local = data gen, evaluator, tests, GGUF inference, demo, benchmarks. Publish to both HF and ModelScope (`abubakar56`). Repo `abubakarp789/FormulaLM` (private until done; MIT). User has 3–4 h/day.
- Data: synthetic only; paraphrases from hand-written patterns or Qwen itself, never other vendors' models.
