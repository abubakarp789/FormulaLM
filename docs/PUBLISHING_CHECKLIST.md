# FormulaLM Publishing & Verification Checklist

Do **not** execute uploads until you inspect file sizes (`--dry-run`) and confirm each target.

## 1. Pre-publish secrets & size audit (before making GitHub public)
- [ ] Run full working-tree + git-history secrets scan (no tokens, keys, or `.env` files committed).
- [ ] Run dry-run file-size checks (zero uploads):
  ```powershell
  uv run python scripts/publish_hf.py --target all
  uv run python scripts/publish_modelscope.py --target all
  ```
- [ ] Confirm expected payload sizes (F16 skipped by default):
  - `formulalm-qwen3-1.7b-v2-q5_k_m.gguf`: **1,199.61 MB** *(primary shipping model)*
  - `formulalm-qwen3-1.7b-v2-q8_0.gguf`: **1,749.45 MB** *(optional)*
  - `formulalm-qwen3-1.7b-v2-q4_k_m.gguf`: **1,056.11 MB** *(optional)*
  - `Modelfile` (points to `Q5_K_M`), `Modelfile.Q5_K_M`, `Modelfile.Q8_0`, `Modelfile.Q4_K_M`, `README.md` (<0.02 MB)
  - LoRA adapters (`adapter_v2`, `adapter_v1`): **66.55 MB** (`69,782,384` bytes) each + `README.md`

## 2. Export tokens via environment variables (never commit)
```powershell
$env:HF_TOKEN = "<your_hf_write_token>"
$env:MODELSCOPE_API_TOKEN = "<your_modelscope_token>"
```

## 3. Publish to Hugging Face (`abubakar56`) — confirm each target
- [ ] GGUF repo (`abubakar56/formulalm-qwen3-1.7b-gguf`) — updates `Modelfile` (to `Q5_K_M`), `Modelfile.Q4_K_M`, and `README.md` (use `--cards-only` since `Q5_K_M`/`Q8_0`/`Q4_K_M` are already SHA-256 verified on HF, or omit `--cards-only` to re-upload; optionally add `--prune-f16` if you want F16 removed):
  ```powershell
  uv run python scripts/publish_hf.py --target gguf --cards-only --execute
  ```
- [ ] v2 LoRA adapter (`abubakar56/formulalm-qwen3-1.7b-lora-v2`) — uploads model card + tags `e2dd7e81` as `v2-ship`:
  ```powershell
  uv run python scripts/publish_hf.py --target adapter-v2 --execute
  ```
- [ ] v1 LoRA fallback (`abubakar56/formulalm-qwen3-1.7b-lora`) — uploads fallback model card + tags `d9909249` as `v1-frozen`:
  ```powershell
  uv run python scripts/publish_hf.py --target adapter-v1 --execute
  ```

## 4. Publish to ModelScope (`abubakar56`) — confirm each target
- [ ] GGUF repo (`abubakar56/formulalm-qwen3-1.7b-gguf`, ~4.0 GB total without F16):
  ```powershell
  uv run python scripts/publish_modelscope.py --target gguf --execute
  ```
- [ ] v2 LoRA adapter (`abubakar56/formulalm-qwen3-1.7b-lora-v2`, ~70 MB):
  ```powershell
  uv run python scripts/publish_modelscope.py --target adapter-v2 --execute
  ```
- [ ] v1 LoRA fallback (`abubakar56/formulalm-qwen3-1.7b-lora`, ~70 MB):
  ```powershell
  uv run python scripts/publish_modelscope.py --target adapter-v1 --execute
  ```

## 5. Make repos public & verify visibility and licenses
- [ ] Verify all 3 Hugging Face repos are **public** (`private=False`) with **`Apache-2.0`** license metadata (inherited from `Qwen/Qwen3-1.7B`):
  - `https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf`
  - `https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora-v2`
  - `https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora`
- [ ] Verify all 3 ModelScope repos are **public** with **`Apache-2.0`** license metadata:
  - `https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf`
  - `https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-lora-v2`
  - `https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-lora`
- [ ] Verify GitHub repo has `MIT` code license (`LICENSE`), then make it public (ONLY after confirming the secrets scan is clean):
  ```powershell
  gh repo edit abubakarp789/FormulaLM --visibility public --accept-visibility-change-consequences
  ```

## 6. Clean-folder download & Ollama quick-start verification
*(Close heavy apps so ≥2.5 GB RAM is free before running)*:
```powershell
uv run python scripts/verify_published_download.py --source hf
# Optionally also verify ModelScope:
uv run python scripts/verify_published_download.py --source modelscope
```
Confirm `sha256_ok: true` and `exec_correct: true` before marking publishing complete.
