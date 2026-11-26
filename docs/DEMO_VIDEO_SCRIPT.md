# FormulaLM — Demo Video Script & Screenshot Capture Guide

- **Target runtime:** **2:30 to 3:00** (planned pacing: **2:45**)
- **Narration length:** **369 words** (strictly under 380 words; first person, plain language, no hype)
- **Fact policy:** Every metric, file size, RAM/speed reading, formula, and execution output below comes directly from `results/` and `README.md`.

---

## 1. Segment Table (0:00–2:45)

| Time | Segment | Narration (spoken verbatim) | Exact On-Screen Text / Visual | Window to Show | Exact Command or Click |
|---|---|---|---|---|---|
| `0:00–0:20` | **Hook** | Most spreadsheet users know the question they want answered, not the exact Excel formula syntax. Cloud LLMs can write formulas, but payroll, invoices, and grades often cannot go to a cloud API. I wanted a small local model that verifies its own formulas by running them. | Title card or README top screen: `FormulaLM — Plain-English to Verified Excel Formula (Local CPU, 1.2 GB)` | Browser showing `README.md` top screen (1080p, zoom 125%) | Pause on top of `README.md` (no scrolling) |
| `0:20–0:40` | **What I built** | I fine-tuned Qwen3-1.7B with QLoRA on synthetic spreadsheet data and shipped a 1.2-gigabyte Q5_K_M GGUF for Ollama. It runs locally on this CPU-only i5-8365U laptop with 8 gigabytes of RAM, using about 1.5 gigabytes peak RAM at roughly 11 tokens per second. Schema and request in; one executed formula out. | Highlight `README.md` top bullets: `Qwen3-1.7B` · `Q5_K_M (1.20 GB)` · `~1.48 GB peak RAM` · `11.3 tok/s` · `i5-8365U, 8 GB RAM, CPU-only` | Browser (`README.md`) → switch to PowerShell terminal | `Alt+Tab` to PowerShell terminal (font 18–20 pt) |
| `0:40–1:00` | **Live Demo 1: Terminal (`ollama`)** | First, in the terminal using `ollama run --think=false formulalm`. I pass the held-out retail schema and ask for total Net Amount for the Mirehaven branch. It outputs `=SUMIF`, and executing that formula against the workbook returns 10,205.82. | Terminal output: `=SUMIF(C2:C115,"Mirehaven",F2:F115)` followed by executor result `10205.82` | PowerShell terminal (light or high-contrast dark, 18–20 pt font) | Run the two pre-pasted commands below (`ollama run --think=false formulalm ...` then `uv run python -c ...`) |
| `1:00–1:20` | **Live Demo 2: Gradio Built-in #1 + Base Comparison** | Next, the local Gradio app launched with `scripts/run_demo.ps1`. On built-in example 1, FormulaLM writes `=COUNTIFS` and executes to 16, matching ground truth. Below it, saved evaluation runs show base Qwen3-1.7B failed both zero-shot and five-shot—without loading a second model into RAM. | Formula: `=COUNTIFS(C2:C115,"Brinport",E2:E115,">=15")`<br>Executed Value: `16` (`✅ MATCHES GROUND TRUTH`)<br>Saved Base: 0-shot `SUMPRODUCT` (unsupported), 5-shot `=COUNTIF(E2:E115,">=15")` → `48` (wrong) | Browser on `http://127.0.0.1:7860` (Gradio app, light theme) | Keep Example #1 (`1. [Sales — COUNTIFS] ...`) selected, keep **Show saved Base Qwen3-1.7B comparison** checked, click **Generate & Execute Formula** |
| `1:20–1:40` | **Live Demo 3: Built-in #8 Honest Failure** | Here is an honest failure: built-in example 8, `real_v2_050`. Asked to `VLOOKUP` Order Total for `ORD-1015`, the model produces valid syntax, but picks column 6 instead of column 7—returning 11 instead of 533. Executing the formula catches that mistake immediately. | Formula: `=IFERROR(ROUND(VLOOKUP("ORD-1015",A2:H57,6,FALSE),1),0)`<br>Executed Value: `11` vs Ground Truth `533` (`❌ DOES NOT MATCH GROUND TRUTH (Honest Failure)`) | Browser on `http://127.0.0.1:7860` | Select `8. [HONEST FAILURE — model is WRONG] ...` in the dropdown, click **Generate & Execute Formula** |
| `1:40–1:55` | **Live Demo 4: Custom Pasted Headers** | It also handles custom schemas. I paste four column headers, ask for total Net Sales for North, and click run. It generates `=SUMIF` and executes on five sample rows to return 305.25. | Pasted: `Region, Sales Rep, Units, Net Sales`<br>Request: `Total Net Sales for North`<br>Formula: `=SUMIF(A2:A6,"North",D2:D6)`<br>Executed Value: `305.25` | Browser on `http://127.0.0.1:7860` | Select `Custom — upload CSV/XLSX or paste headers below`, open **Optional Custom Input**, paste `Region, Sales Rep, Units, Net Sales`, type `Total Net Sales for North`, click **Generate & Execute Formula** |
| `1:55–2:25` | **Results** | On our fresh held-out set `test_real_v2`—50 requests drafted with an AI assistant, so it is small and not fully independent, an indication rather than a precise score—base Qwen3-1.7B gets 23 out of 50 zero-shot (46%) and 29 out of 50 five-shot (58%). Shipped Q5_K_M gets 45 out of 50 on Colab and 43 out of 50 on local Ollama, with 95% intervals roughly 74 to 96%. v1 and v2 are statistically tied, and Q4_K_M loses 2 to 5 points while Q5_K_M stays within noise of F16. | Headline table (`README.md` or `results/final_headline.md`):<br>• Base 0-shot: `23/50` (`46.0%`, `[33.0%, 59.6%]`)<br>• Base 5-shot: `29/50` (`58.0%`, `[44.2%, 70.6%]`)<br>• Q5_K_M Colab: `45/50` (`90.0%`, `[78.6%, 95.7%]`)<br>• Q5_K_M Local Ollama: `43/50` (`86.0%`, `[73.8%, 93.0%]`)<br>• v1 vs v2: tied (`44/50` fp16, `498/500` val)<br>• Q4_K_M drops `2.4–5.0 pp`; Q5_K_M within noise of F16 | Browser showing `README.md` Headline Results tables | `Alt+Tab` back to `README.md` scrolled to **Headline Results** |
| `2:25–2:45` | **Limits & Where to Find It** | Limits: Excel dialect only, 36 functions, single-sheet formulas, synthetic training data, and always check critical sheets. The code is on GitHub at `abubakarp789/FormulaLM`, and the GGUF and LoRA weights are on Hugging Face and ModelScope under `abubakar56`. | Bottom links:<br>• `github.com/abubakarp789/FormulaLM`<br>• `huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf`<br>• `modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf` | Browser scrolled to **Limitations** and **Links** in `README.md` | Scroll smoothly to **Limitations** / top links and stop recording |

### Exact PowerShell Commands for Live Demo 1 (`0:40–1:00`)

Run these in a clean PowerShell window from the repo root (copy-paste ready):

```powershell
# 1. Generate formula locally with Ollama (non-thinking mode)
$prompt = @"
Sheet: sales_retail_store (rows 2..115)
Columns:
A: Receipt Code (text)
B: Sale Date (date)
C: Store Branch (category)
D: Item Name (text)
E: Quantity (integer)
F: Net Amount (decimal)

Request: Total Net Amount for the Mirehaven branch
"@
$formula = (ollama run --think=false formulalm $prompt).Trim()
$formula

# 2. Execute the generated formula against the held-out workbook
uv run python -c "from pathlib import Path; from src.eval.executor import run_formula; import sys; r = run_formula(sys.argv[1], Path('data/sheets/sales_retail_store.xlsx')); print(f'ok={r.ok}  value={r.value:.2f}  engine={r.engine}')" $formula
```

Expected output:
- `$formula` → `=SUMIF(C2:C115,"Mirehaven",F2:F115)`
- Executor line → `ok=True  value=10205.82  engine=formulas`

---

## 2. Where to Cut If the Take Runs Over 3:00

If a rehearsal runs over **2:55**, trim in this order (highest savings, lowest impact):

1. **Cut ~12–15 s from Live Demo 4 (Custom Pasted Headers):** Have `Region, Sales Rep, Units, Net Sales` and `Total Net Sales for North` **pre-typed** in a second Gradio tab or clipboard before switching so you only paste + click once instead of typing on camera.
2. **Cut ~8–10 s from Live Demo 1 (Terminal):** Have `$prompt` already defined in the PowerShell session before hitting Record, and clear the screen (`cls`), so on camera you only press `Up` and `Enter` to run `ollama run --think=false formulalm $prompt` and the executor line.
3. **Cut ~8 s from Results:** Read only the `test_real_v2` headline (`23/50` zero-shot, `29/50` five-shot vs `45/50` Colab and `43/50` local Ollama) plus the one-line v1/v2 tie and `Q4_K_M` vs `Q5_K_M` takeaway, letting the on-screen table show the exact confidence intervals.

---

## 3. Pre-Recording Checklist (8 GB RAM, CPU-Only Windows 11 Laptop)

1. **Pause OneDrive sync:** Click the OneDrive tray icon → Settings (gear) → **Pause syncing → 2 hours** (stops background disk/CPU spikes inside `OneDrive\Desktop\Qwen Hackathon`).
2. **Close all other apps:** Close VS Code, extra browser tabs, Slack/Discord, Teams, Office, and background updaters. Keep only **one** browser window (2 tabs: `README.md` and `http://127.0.0.1:7860`) and **one** PowerShell terminal open.
3. **Check free RAM:** Open Task Manager → Performance → Memory (or run `Get-CimInstance Win32_OperatingSystem | ForEach-Object { [math]::Round($_.FreePhysicalMemory/1024) }`). Confirm at least **2.5–3.0 GB free RAM** before starting Ollama + recorder (`Q5_K_M` peaks around `1.48 GB`).
4. **Hide notifications:** Enable Windows **Do Not Disturb** (Settings → System → Notifications → Do Not Disturb: On) and close desktop popups.
5. **Display & font setup:** Set display resolution to **1920×1080 (1080p)**, browser zoom to **110%–125%**, PowerShell font size to **18–20 pt** (Cascadia Mono / Consolas).
6. **Launch demo & run one warm-up request off-camera:**
   ```powershell
   .\scripts\run_demo.ps1   # enforces OLLAMA_MAX_LOADED_MODELS=1
   ```
   Run **one warm-up query** (click **Generate & Execute Formula** on Example #1 once, or run `ollama run --think=false formulalm "hi"` once) so the 2.6 s cold model load is already in RAM before you hit Record.
7. **Light recorder & 30-second OOM test first:**
   - Use **Windows Game Bar** (`Win + G` → Capture, or `Win + Alt + R` to start/stop) or another lightweight recorder (avoid heavy OBS scenes/filters).
   - Record a **30-second test clip** while running one live Gradio query. Play it back to confirm: (a) audio is clear, (b) fonts are sharp at 1080p, (c) Task Manager Memory stays under ~90% with zero OOM or stutter.

---

## 4. Live-Failure Recovery & Plan B

- **If a live request fails, stalls, or outputs a different formula on camera:** Do **not** panic or restart mid-sentence. Say plainly: *"That one missed live—which is fine and shows why executing the formula matters—let's move on."* Keep going so you stay inside 3:00.
- **Plan B (pre-recorded fallback clip):** Before doing a full narrated run, capture one clean **silent 75-second screen recording** of the 4 live demo steps succeeding cleanly (Terminal Mirehaven → Gradio #1 → Gradio #8 → Custom headers). If live recording + Ollama stutters on 8 GB RAM during narration, play that clean clip full-screen while recording your voiceover, or splice it cleanly in Clipchamp / ffmpeg.

---

## 5. Upload Checklist & Exact `README.md` Lines to Update After Upload

1. **Upload the final MP4 (2:30–3:00, 1080p)** to **YouTube (Unlisted or Public)** — or Loom / Vimeo / Google Drive with public viewer access (YouTube Unlisted is recommended because judges can play it directly in-browser with no sign-in).
2. **Verify playback** in an incognito browser window (confirm audio, 1080p clarity, and zero sign-in wall).
3. **Update these exact two lines in `README.md`** (replace `<VIDEO_URL>` with your uploaded URL):
   - **`README.md` line 7:**
     - **Before:**
       ```markdown
       - **Links:** [GitHub Repo](https://github.com/abubakarp789/FormulaLM) · [Hugging Face GGUF](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf) ([v2 LoRA](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora-v2) · [v1 LoRA fallback](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora)) · [ModelScope GGUF](https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf) ([v2 LoRA](https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-lora-v2) · [v1 LoRA fallback](https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-lora)) · **Demo video:** _TODO: [2–3 min local demo video link — placeholder until uploaded]_
       ```
     - **After:**
       ```markdown
       - **Links:** [GitHub Repo](https://github.com/abubakarp789/FormulaLM) · [Hugging Face GGUF](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-gguf) ([v2 LoRA](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora-v2) · [v1 LoRA fallback](https://huggingface.co/abubakar56/formulalm-qwen3-1.7b-lora)) · [ModelScope GGUF](https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-gguf) ([v2 LoRA](https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-lora-v2) · [v1 LoRA fallback](https://www.modelscope.ai/models/abubakar56/formulalm-qwen3-1.7b-lora)) · [Demo Video (2–3 min)](<VIDEO_URL>)
       ```
   - **`README.md` line 14:**
     - **Before:**
       ```markdown
       | 2–3 minute local demo video | Pending upload | Placeholder above — to be recorded on local `i5-8365U` Gradio + Ollama setup |
       ```
     - **After:**
       ```markdown
       | 2–3 minute local demo video | Done | [Demo Video](<VIDEO_URL>) — recorded locally on `i5-8365U` Gradio + Ollama |
       ```

---

## 6. Screenshot Capture Guide (3 PNGs under `docs/screenshots/`)

Launch the real local demo (`.\scripts\run_demo.ps1`, Ollama backend, `formulalm` Q5_K_M, browser at 1080p, light theme) and save the three captures into `docs/screenshots/`:

1. **`docs/screenshots/demo_win.png`**
   - **Built-in example:** `1. [Sales — COUNTIFS] Brinport sales with Quantity >= 15` (`real_v2_005`)
   - **Settings:** **Show saved Base Qwen3-1.7B comparison** = **Checked (ON)**; Held-out sheet = `sales_retail_store`; Custom Input accordion = **Closed**.
   - **Action & framing:** Click **Generate & Execute Formula**. Capture the full panel showing `=COUNTIFS(C2:C115,"Brinport",E2:E115,">=15")`, Executed Value `16` (`✅ MATCHES GROUND TRUTH`), the saved Base `Qwen3-1.7B` failures (`SUMPRODUCT` error & `48` wrong value), and the Runtime Status card (`formulalm`, `Q5_K_M`, latency + tok/s).

2. **`docs/screenshots/demo_honest_failure.png`**
   - **Built-in example:** `8. [HONEST FAILURE — model is WRONG] Orders VLOOKUP Order Total for ORD-1015 (off-by-one column index)` (`real_v2_050`)
   - **Settings:** **Show saved Base Qwen3-1.7B comparison** = **Checked (ON)**; Held-out sheet = `orders_ecommerce`; Custom Input accordion = **Closed**.
   - **Action & framing:** Click **Generate & Execute Formula**. Capture the yellow/bordered note card, generated formula `=IFERROR(ROUND(VLOOKUP("ORD-1015",A2:H57,6,FALSE),1),0)`, Executed Value `11` vs Ground Truth `533` (`❌ DOES NOT MATCH GROUND TRUTH (Honest Failure)`), and the reference formula with column `7`.

3. **`docs/screenshots/demo_custom_headers.png`**
   - **Built-in example:** None (custom input mode)
   - **Settings:** Sheet dropdown = `Custom — upload CSV/XLSX or paste headers below`; expand **Optional Custom Input** accordion; **Show saved Base Qwen3-1.7B comparison** = **Unchecked (OFF)** (keeps the screenshot clean since custom queries have no saved baseline); paste `Region, Sales Rep, Units, Net Sales` into the **Or paste column headers** box; enter `Total Net Sales for North` in **2. Plain-English Spreadsheet Request**.
   - **Action & framing:** Click **Generate & Execute Formula**. Capture the pasted headers box, active prompt schema (`rows 2..6`), generated formula `=SUMIF(A2:A6,"North",D2:D6)`, Executed Value `305.25`, and the 5 synthesized sample rows preview.

### Exact Commands to Commit the Screenshots After Capture

```powershell
# Verify all 3 files exist and check sizes
Get-ChildItem docs/screenshots/*.png | Format-Table Name, @{n='KB';e={[math]::Round($_.Length/1KB,1)}}

# Stage, commit, and push
git add docs/screenshots/demo_win.png docs/screenshots/demo_honest_failure.png docs/screenshots/demo_custom_headers.png
git commit -m "docs: add 3 local Gradio demo screenshots"
git push origin main
```
