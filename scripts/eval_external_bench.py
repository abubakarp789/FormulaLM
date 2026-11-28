"""Evaluate local Ollama models (or mock oracle) on the frozen external SpreadsheetBench subset.

Reuses FormulaLM's exact SYSTEM_PROMPT, FEW_SHOT_EXAMPLES, extract_formula,
src.eval.executor.run_formula, exact_match, and values_equal so every model is
scored identically by execution against the real `.xlsx` workbooks.

Usage:
    # Single run
    uv run python scripts/eval_external_bench.py \
        --run-name ext_formulalm_q5_k_m \
        --model formulalm:latest --few-shot 0

    # Generate unified comparison table from completed runs
    uv run python scripts/eval_external_bench.py --summarize
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psutil
import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.data.build_dataset import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from src.eval.executor import run_formula  # noqa: E402
from src.eval.normalize import exact_match, values_equal  # noqa: E402
from src.eval.prompt_parity import STOP_TOKENS, render_qwen3_non_thinking_prompt  # noqa: E402
from src.eval.run_eval import FEW_SHOT_EXAMPLES, extract_formula  # noqa: E402

DEFAULT_DATASET = Path("data/external_bench/external_bench.csv")
DEFAULT_RESULTS_ROOT = Path("results/external_bench")


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / denom
    return round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)


def parse_expected_value(raw: str, expected_type: str) -> Any:
    if expected_type == "bool":
        return raw.strip().upper() == "TRUE"
    if expected_type == "number":
        return float(raw)
    if expected_type == "date":
        return datetime.fromisoformat(raw.strip())
    return raw


def measure_ollama_ram_mb() -> float:
    total = 0
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "ollama" in name or "llama" in name:
                mem = proc.info.get("memory_info")
                if mem is not None:
                    total += int(mem.rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return round(total / (1024 * 1024), 1)


def load_external_rows(csv_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if limit is not None:
        rows = rows[:limit]
    return rows


def build_messages(schema_text: str, request: str, few_shot: int) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if few_shot > 0:
        for user_demo, asst_demo in FEW_SHOT_EXAMPLES[:few_shot]:
            messages.append({"role": "user", "content": user_demo})
            messages.append({"role": "assistant", "content": asst_demo})
    messages.append({"role": "user", "content": build_user_prompt(schema_text, request)})
    return messages


def call_ollama(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    seed: int,
    num_ctx: int,
    timeout: float,
    raw_qwen3_prompt: bool = False,
) -> tuple[str, dict[str, float]]:
    if raw_qwen3_prompt:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": render_qwen3_non_thinking_prompt(messages),
            "raw": True,
            "stream": False,
            "keep_alive": "15m",
            "options": {
                "temperature": 0.0,
                "num_predict": max_tokens,
                "num_ctx": num_ctx,
                "seed": seed,
                "stop": list(STOP_TOKENS),
            },
        }
        resp = requests.post(f"{base_url.rstrip('/')}/api/generate", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = str(data.get("response", ""))
    else:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "15m",
            "options": {
                "temperature": 0.0,
                "num_predict": max_tokens,
                "num_ctx": num_ctx,
                "seed": seed,
            },
        }
        resp = requests.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = str(data.get("message", {}).get("content", ""))

    timings: dict[str, float] = {}
    if data.get("eval_count") and data.get("eval_duration"):
        timings["gen_tok_s"] = float(data["eval_count"]) / (float(data["eval_duration"]) / 1e9)
    if data.get("prompt_eval_count") and data.get("prompt_eval_duration"):
        timings["prompt_tok_s"] = float(data["prompt_eval_count"]) / (
            float(data["prompt_eval_duration"]) / 1e9
        )
    return text, timings


def unload_ollama_model(base_url: str, model: str) -> None:
    try:
        requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=15,
        )
    except Exception:
        pass


def compute_metrics(
    records: list[dict[str, Any]],
    *,
    run_name: str,
    model: str,
    few_shot: int,
    dataset: str,
    seed: int,
    max_tokens: int,
    num_ctx: int,
    peak_ram_mb: float,
) -> dict[str, Any]:
    def _agg(subset: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(subset)
        if n == 0:
            return {"n": 0, "k": 0, "execution_accuracy": 0.0, "wilson_95_ci": [0.0, 0.0]}
        k = sum(1 for r in subset if r["exec_correct"])
        lo, hi = wilson_ci(k, n)
        lat = [float(r["latency_ms"]) for r in subset]
        tps = [float(r["gen_tok_s"]) for r in subset if r.get("gen_tok_s")]
        return {
            "n": n,
            "k": k,
            "execution_accuracy": round(k / n, 4),
            "wilson_95_ci": [lo, hi],
            "syntax_valid_rate": round(sum(1 for r in subset if r["syntax_valid"]) / n, 4),
            "exec_ok_rate": round(sum(1 for r in subset if r["exec_ok"]) / n, 4),
            "exact_match_rate": round(sum(1 for r in subset if r["exact_match"]) / n, 4),
            "raw_format_ok_rate": round(sum(1 for r in subset if r["raw_format_ok"]) / n, 4),
            "avg_latency_ms": round(statistics.mean(lat), 2),
            "median_latency_ms": round(statistics.median(lat), 2),
            "avg_gen_tok_s": round(statistics.mean(tps), 2) if tps else 0.0,
        }

    by_kind: dict[str, Any] = {}
    for kind in sorted({r["task_kind"] for r in records}):
        by_kind[kind] = _agg([r for r in records if r["task_kind"] == kind])

    return {
        "run_name": run_name,
        "model": model,
        "few_shot": few_shot,
        "dataset": dataset,
        "seed": seed,
        "max_tokens": max_tokens,
        "num_ctx": num_ctx,
        "peak_ram_mb": peak_ram_mb,
        "overall": _agg(records),
        "by_task_kind": by_kind,
    }


def run_evaluation(
    *,
    dataset_path: Path,
    run_name: str,
    model: str,
    backend: str,
    few_shot: int,
    out_dir: Path,
    base_url: str,
    seed: int,
    max_tokens: int,
    num_ctx: int,
    timeout: float,
    limit: int | None,
    raw_qwen3_prompt: bool = False,
) -> dict[str, Any]:
    rows = load_external_rows(dataset_path, limit=limit)
    out_dir.mkdir(parents=True, exist_ok=True)
    preds_path = out_dir / "predictions.jsonl"

    done_by_id: dict[str, dict[str, Any]] = {}
    if preds_path.exists():
        for line in preds_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done_by_id[rec["id"]] = rec

    peak_ram_mb = 0.0
    if backend == "ollama":
        peak_ram_mb = max(peak_ram_mb, measure_ollama_ram_mb())

    records: list[dict[str, Any]] = []
    with preds_path.open("a", encoding="utf-8") as pf:
        for idx, row in enumerate(rows, 1):
            ex_id = row["id"]
            if ex_id in done_by_id:
                records.append(done_by_id[ex_id])
                continue

            messages = build_messages(row["schema_text"], row["request"], few_shot=few_shot)
            t0 = time.perf_counter()
            timings: dict[str, float] = {}
            if backend == "mock":
                raw_out = row["reference_formula"]
            else:
                raw_out, timings = call_ollama(
                    base_url,
                    model,
                    messages,
                    max_tokens=max_tokens,
                    seed=seed,
                    num_ctx=num_ctx,
                    timeout=timeout,
                    raw_qwen3_prompt=raw_qwen3_prompt,
                )
                peak_ram_mb = max(peak_ram_mb, measure_ollama_ram_mb())
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

            extracted = extract_formula(raw_out)
            raw_format_ok = raw_out.strip().startswith("=") and "\n" not in raw_out.strip()
            wb_path = _REPO_ROOT / row["workbook_path"]
            exec_res = run_formula(extracted, wb_path, target_cell=row["target_cell"])
            exp_val = parse_expected_value(row["expected_value"], row["expected_type"])
            exec_correct = bool(exec_res.ok and values_equal(exec_res.value, exp_val))
            em = bool(exact_match(extracted, row["reference_formula"]))
            syntax_valid = exec_res.error_type not in ("syntax_error", "unsupported_function")

            pred_val_serializable = (
                exec_res.value.isoformat()
                if isinstance(exec_res.value, (date, datetime))
                else exec_res.value
            )
            rec = {
                "id": ex_id,
                "source_id": row["source_id"],
                "task_kind": row["task_kind"],
                "sheet_name": row["sheet_name"],
                "target_cell": row["target_cell"],
                "reference_formula": row["reference_formula"],
                "expected_value": row["expected_value"],
                "expected_type": row["expected_type"],
                "raw_output": raw_out,
                "extracted_formula": extracted,
                "predicted_value": pred_val_serializable,
                "syntax_valid": syntax_valid,
                "exec_ok": bool(exec_res.ok),
                "exec_correct": exec_correct,
                "exact_match": em,
                "raw_format_ok": raw_format_ok,
                "error_type": exec_res.error_type,
                "error_message": exec_res.error_message,
                "latency_ms": latency_ms,
                "gen_tok_s": round(timings.get("gen_tok_s", 0.0), 2),
            }
            pf.write(json.dumps(rec, default=str) + "\n")
            pf.flush()
            records.append(rec)
            if idx % 10 == 0 or idx == len(rows):
                so_far = sum(1 for r in records if r["exec_correct"])
                print(
                    f"[{run_name}] {idx}/{len(rows)} | exec_acc={so_far}/{len(records)} "
                    f"({100 * so_far / len(records):.1f}%) | peak_ram={peak_ram_mb:.1f} MB",
                    flush=True,
                )

    if backend == "ollama":
        unload_ollama_model(base_url, model)

    metrics = compute_metrics(
        records,
        run_name=run_name,
        model=model,
        few_shot=few_shot,
        dataset=str(dataset_path).replace("\\", "/"),
        seed=seed,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        peak_ram_mb=peak_ram_mb,
    )
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def summarize_results(results_root: Path) -> str:
    order = [
        ("ext_base_1_7b_0shot", "Base `Qwen3-1.7B` (0-shot, Ollama Q4_K_M)"),
        ("ext_base_1_7b_5shot", "Base `Qwen3-1.7B` (5-shot, Ollama Q4_K_M)"),
        ("ext_formulalm_q5_k_m", "**FormulaLM `Q5_K_M` (Shipped 1.7B, 0-shot)**"),
    ]
    loaded: list[tuple[str, str, dict[str, Any]]] = []
    for run_name, label in order:
        mf = results_root / run_name / "metrics.json"
        if mf.exists():
            loaded.append((run_name, label, json.loads(mf.read_text(encoding="utf-8"))))

    lines = [
        "# External Real-Workbook Benchmark"
        " (`SpreadsheetBench Verified 400`, In-Scope Single-Sheet Subset)",
        "",
        "- **Source:** `KAKA22/SpreadsheetBench` (`spreadsheetbench_verified_400.tar.gz`, "
        "NeurIPS 2024, `CC-BY-SA-4.0`, pinned `ab0b742b`), real MrExcel/ExcelForum "
        "human-authored workbooks & questions.",
        "- **Integrity:** Filtered deterministically to single-sheet "
        "`Cell-Level Manipulation` formulas using FormulaLM's 36 allowed non-volatile "
        "functions (`<= 20` columns, verified gold execution), SHA-256 frozen in "
        "`data/external_bench/manifest.sha256` before any inference.",
        "- **Local runtime:** Windows 11 laptop (`Intel Core i5-8365U`, `8 GB RAM`, "
        "CPU-only, `Ollama 0.40.18`), `think=False`, `temperature=0`, `seed=42`, "
        "`num_ctx=4096`, `num_predict=96`.",
        "",
        "| System | N | Correct | **Exec. Accuracy (95% Wilson CI)** | Exact Match "
        "| Syntax Valid | Single-Cell | Col-Fill | Avg Latency | Gen tok/s | Peak RAM |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    comp_json: dict[str, Any] = {"systems": {}}
    for run_name, label, m in loaded:
        ov = m["overall"]
        lo, hi = ov["wilson_95_ci"]
        sc = m["by_task_kind"].get("single_cell", {})
        cf = m["by_task_kind"].get("col_fill_first_cell", {})
        sc_str = (
            f"{sc.get('k', 0)}/{sc.get('n', 0)} ({sc.get('execution_accuracy', 0) * 100:.1f}%)"
            if sc
            else "—"
        )
        cf_str = (
            f"{cf.get('k', 0)}/{cf.get('n', 0)} ({cf.get('execution_accuracy', 0) * 100:.1f}%)"
            if cf
            else "—"
        )
        lines.append(
            f"| {label} | {ov['n']} | {ov['k']}/{ov['n']} | "
            f"**{ov['execution_accuracy'] * 100:.1f}%** `[{lo * 100:.1f}%, {hi * 100:.1f}%]` | "
            f"{ov['exact_match_rate'] * 100:.1f}% | {ov['syntax_valid_rate'] * 100:.1f}% | "
            f"{sc_str} | {cf_str} | {ov['avg_latency_ms'] / 1000:.2f} s | "
            f"{ov['avg_gen_tok_s']:.1f} | {m['peak_ram_mb']:.0f} MB |"
        )
        comp_json["systems"][run_name] = m

    # Add concrete wins & honest failures for FormulaLM if present
    flm_preds_file = results_root / "ext_formulalm_q5_k_m" / "predictions.jsonl"
    base_preds_file = results_root / "ext_base_1_7b_0shot" / "predictions.jsonl"
    if flm_preds_file.exists():
        flm_preds = [
            json.loads(ln)
            for ln in flm_preds_file.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        base_by_id = {}
        if base_preds_file.exists():
            for ln in base_preds_file.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    r = json.loads(ln)
                    base_by_id[r["id"]] = r

        wins = [
            r
            for r in flm_preds
            if r["exec_correct"] and not base_by_id.get(r["id"], {}).get("exec_correct", False)
        ]
        losses = [r for r in flm_preds if not r["exec_correct"]]
        lines.extend(
            ["", "## Sample Real-Workbook Wins (FormulaLM Correct, Base 1.7B 0-shot Wrong)", ""]
        )
        for r in wins[:5]:
            b = base_by_id.get(r["id"], {})
            b_err = b.get("error_type") or b.get("predicted_value")
            lines.append(
                f"- **`{r['id']}`** (`{r['sheet_name']}!{r['target_cell']}`): "
                f"FormulaLM `{r['extracted_formula']}` → `{r['predicted_value']}` "
                f"(expected `{r['expected_value']}`); "
                f"Base 1.7B `{b.get('extracted_formula', '')}` (`{b_err}`)"
            )
        lines.extend(["", "## Sample Real-Workbook Failures (Honest Error Analysis)", ""])
        for r in losses[:5]:
            lines.append(
                f"- **`{r['id']}`** (`{r['sheet_name']}!{r['target_cell']}`): "
                f"Pred `{r['extracted_formula']}` → `{r['predicted_value']}` "
                f"(`{r['error_type']}`); "
                f"Ref `{r['reference_formula']}` → `{r['expected_value']}`"
            )

    md = "\n".join(lines) + "\n"
    (results_root / "comparison.md").write_text(md, encoding="utf-8")
    (results_root / "comparison.json").write_text(
        json.dumps(comp_json, indent=2) + "\n", encoding="utf-8"
    )
    return md


def rescore_run(dataset_path: Path, run_dir: Path) -> dict[str, Any]:
    rows = {r["id"]: r for r in load_external_rows(dataset_path)}
    preds_path = run_dir / "predictions.jsonl"
    old_metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    old_records = [
        json.loads(ln) for ln in preds_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    new_records: list[dict[str, Any]] = []
    for rec in old_records:
        row = rows[rec["id"]]
        extracted = extract_formula(rec["raw_output"])
        wb_path = _REPO_ROOT / row["workbook_path"]
        exec_res = run_formula(extracted, wb_path, target_cell=row["target_cell"])
        exp_val = parse_expected_value(row["expected_value"], row["expected_type"])
        pred_val = (
            exec_res.value.isoformat()
            if isinstance(exec_res.value, (date, datetime))
            else exec_res.value
        )
        updated = dict(rec)
        updated.update(
            {
                "extracted_formula": extracted,
                "predicted_value": pred_val,
                "syntax_valid": exec_res.error_type not in ("syntax_error", "unsupported_function"),
                "exec_ok": bool(exec_res.ok),
                "exec_correct": bool(exec_res.ok and values_equal(exec_res.value, exp_val)),
                "exact_match": bool(exact_match(extracted, row["reference_formula"])),
                "error_type": exec_res.error_type,
                "error_message": exec_res.error_message,
            }
        )
        new_records.append(updated)
    preds_path.write_text(
        "\n".join(json.dumps(r, default=str) for r in new_records) + "\n", encoding="utf-8"
    )
    metrics = compute_metrics(
        new_records,
        run_name=old_metrics["run_name"],
        model=old_metrics["model"],
        few_shot=old_metrics["few_shot"],
        dataset=old_metrics["dataset"],
        seed=old_metrics["seed"],
        max_tokens=old_metrics["max_tokens"],
        num_ctx=old_metrics["num_ctx"],
        peak_ram_mb=old_metrics["peak_ram_mb"],
    )
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--run-name", type=str, default=None)
    parser.add_argument("--model", type=str, default="formulalm:latest")
    parser.add_argument("--backend", choices=["ollama", "mock"], default="ollama")
    parser.add_argument("--few-shot", type=int, default=0)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:11434")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tokens", type=int, default=96)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--raw-qwen3-prompt", action="store_true")
    parser.add_argument("--rescore", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()

    if args.rescore:
        if not args.run_name:
            raise SystemExit("--run-name is required with --rescore")
        m = rescore_run(args.dataset, args.results_root / args.run_name)
        print(json.dumps(m, indent=2))
        return 0
    if args.summarize:
        print(summarize_results(args.results_root))
        return 0
    if not args.run_name:
        raise SystemExit("--run-name is required unless --summarize is passed")

    m = run_evaluation(
        dataset_path=args.dataset,
        run_name=args.run_name,
        model=args.model,
        backend=args.backend,
        few_shot=args.few_shot,
        out_dir=args.results_root / args.run_name,
        base_url=args.base_url,
        seed=args.seed,
        max_tokens=args.max_tokens,
        num_ctx=args.num_ctx,
        timeout=args.timeout,
        limit=args.limit,
        raw_qwen3_prompt=args.raw_qwen3_prompt,
    )
    print(json.dumps(m, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
