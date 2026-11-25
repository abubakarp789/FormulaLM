"""Compare Base vs v2 Merged F16 vs Q8_0 vs Q5_K_M vs Q4_K_M with Wilson CIs & local stats.

Reads saved runs under ``results/`` (never invents missing numbers):
- Baselines: ``results/baseline_{zeroshot,5shot}_{real_v2,real,synthetic}/``
- Quantized v2-ship evals: ``results/quant_{f16,q8_0,q5_k_m,q4_k_m}_{val,real_v2,real,synthetic}/``
- Artifact sizes: ``results/quant_artifacts.json``
- Local laptop benchmarks: ``results/local_benchmark/local_benchmark.json``

Recommendation rule:
    Recommend the smallest quantization whose execution accuracy is within sampling noise
    of F16 across all 4 splits (95% Wilson CIs overlap F16 AND drop <= 1.5 pp on ``val`` /
    ``test_synthetic`` AND drop <= 2.5 pp on ``test_real_v2`` / ``test_real``) AND fits in
    local laptop RAM when local benchmark data is present. If F16 or quantized results are
    not yet saved, output ``PENDING``.

CLI usage:
    uv run python -m src.eval.compare_quant \
        --results-dir results \
        --out results/quant_comparison.md \
        --json-out results/quant_comparison.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.eval.compare_v1_v2 import INFORMED_LABEL, _fmt_ci, _fmt_delta, _load_run_stats, _pct

QUANT_SYSTEMS: tuple[tuple[str, str, str | None], ...] = (
    ("base_zeroshot", "Base `Qwen3-1.7B` (0-shot, fp16)", None),
    ("base_5shot", "Base `Qwen3-1.7B` (5-shot, fp16)", None),
    ("quant_f16", "v2-ship Merged `F16` GGUF", "f16"),
    ("quant_q8_0", "v2-ship `Q8_0` GGUF", "q8_0"),
    ("quant_q5_k_m", "v2-ship `Q5_K_M` GGUF", "q5_k_m"),
    ("quant_q4_k_m", "v2-ship `Q4_K_M` GGUF", "q4_k_m"),
)

# Smallest -> largest candidate order for shipping selection.
CANDIDATE_ORDER: tuple[str, ...] = ("quant_q4_k_m", "quant_q5_k_m", "quant_q8_0", "quant_f16")

EVAL_SPLITS: tuple[tuple[str, str, float, bool], ...] = (
    ("val", "`val` (500)", 0.015, False),
    ("real_v2", "`test_real_v2` (50)", 0.025, False),
    ("real", "`test_real` (80)*", 0.025, True),
    ("synthetic", "`test_synthetic` (500)*", 0.015, True),
)


def _run_dir_for(sys_key: str, split_key: str) -> str | None:
    if sys_key == "base_zeroshot":
        if split_key == "val":
            return None
        return f"baseline_zeroshot_{split_key}"
    if sys_key == "base_5shot":
        if split_key == "val":
            return None
        return f"baseline_5shot_{split_key}"
    return f"{sys_key}_{split_key}"


def _ci_overlap(a: list[float], b: list[float]) -> bool:
    return a[1] >= b[0] and b[1] >= a[0]


def select_shipping_quant(
    systems: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Recommend the smallest quantization within noise of F16 using measured data only."""
    f16 = systems["quant_f16"]
    f16_missing = [sk for sk, _, _, _ in EVAL_SPLITS if f16["splits"].get(sk) is None]
    if f16_missing:
        return {
            "status": "PENDING",
            "recommended": None,
            "rationale": (
                f"Missing F16 reference runs ({', '.join(f16_missing)}). "
                "Run notebooks/05_merge_quantize.ipynb first."
            ),
            "evaluated_candidates": {},
        }

    evaluated: dict[str, dict[str, Any]] = {}
    for cand_key in CANDIDATE_ORDER:
        if cand_key == "quant_f16":
            continue
        cand = systems[cand_key]
        missing = [sk for sk, _, _, _ in EVAL_SPLITS if cand["splits"].get(sk) is None]
        if missing:
            evaluated[cand_key] = {
                "eligible": False,
                "reason": f"missing runs: {', '.join(missing)}",
            }
            continue

        local = cand.get("local")
        if local is not None and local.get("status") == "skipped_insufficient_ram":
            evaluated[cand_key] = {
                "eligible": False,
                "reason": f"does not fit in local laptop RAM ({local.get('reason', '')})",
            }
            continue

        failed_splits: list[str] = []
        for sk, _, tol, _ in EVAL_SPLITS:
            ref_st = f16["splits"][sk]
            c_st = cand["splits"][sk]
            drop = ref_st["execution_accuracy"] - c_st["execution_accuracy"]
            overlap = _ci_overlap(c_st["wilson_95_ci"], ref_st["wilson_95_ci"])
            if drop > tol + 1e-12 or not overlap:
                failed_splits.append(
                    f"{sk} (drop {100 * drop:+.1f} pp, "
                    f"tol {100 * tol:.1f} pp, ci_overlap={overlap})"
                )

        if failed_splits:
            evaluated[cand_key] = {
                "eligible": False,
                "reason": "degraded vs F16 on " + "; ".join(failed_splits),
            }
        else:
            evaluated[cand_key] = {
                "eligible": True,
                "size_mb": cand.get("size_mb"),
                "reason": "within noise of F16 across all 4 splits",
            }

    if all(
        "missing runs" in evaluated[k]["reason"]
        for k in ("quant_q4_k_m", "quant_q5_k_m", "quant_q8_0")
    ):
        return {
            "status": "PENDING",
            "recommended": None,
            "rationale": "F16 exists, but quantized runs (Q8_0, Q5_K_M, Q4_K_M) are still pending.",
            "evaluated_candidates": evaluated,
        }

    # Sort eligible candidates by measured disk size (smallest first), fallback CANDIDATE_ORDER.
    eligible = [
        k for k in ("quant_q4_k_m", "quant_q5_k_m", "quant_q8_0") if evaluated[k]["eligible"]
    ]
    if eligible:
        eligible.sort(
            key=lambda k: (
                systems[k]["size_mb"]
                if systems[k].get("size_mb") is not None
                else float(CANDIDATE_ORDER.index(k))
            )
        )
        winner = eligible[0]
        local_note = (
            ""
            if systems[winner].get("local")
            else " (pending local laptop RAM/speed confirmation via scripts/benchmark_local.py)"
        )
        return {
            "status": "RECOMMENDED",
            "recommended": winner,
            "recommended_label": systems[winner]["label"],
            "rationale": (
                f"{systems[winner]['label']} is the smallest quantization within sampling noise "
                f"of F16 on all 4 splits{local_note}."
            ),
            "evaluated_candidates": evaluated,
        }

    return {
        "status": "FALLBACK_F16",
        "recommended": "quant_f16",
        "recommended_label": f16["label"],
        "rationale": (
            "No quantized variant stayed within noise of F16 on all 4 splits; "
            "investigate parity/quantization."
        ),
        "evaluated_candidates": evaluated,
    }


def build_quant_comparison(results_dir: str | Path = "results") -> dict[str, Any]:
    """Assemble base + F16 + quantized accuracy, sizes, local benchmarks, and recommendation."""
    root = Path(results_dir)
    artifacts_p = root / "quant_artifacts.json"
    artifacts = json.loads(artifacts_p.read_text(encoding="utf-8")) if artifacts_p.is_file() else {}
    artifact_files = artifacts.get("files", {})

    local_p = root / "local_benchmark" / "local_benchmark.json"
    local_raw = json.loads(local_p.read_text(encoding="utf-8")) if local_p.is_file() else {}
    local_by_key = {
        r["quant_key"]: r
        for r in local_raw.get("results", [])
        if isinstance(r, dict) and "quant_key" in r
    }

    parity_p = root / "quant_parity" / "parity_report.json"
    parity = json.loads(parity_p.read_text(encoding="utf-8")) if parity_p.is_file() else None

    systems: dict[str, dict[str, Any]] = {}
    for sys_key, label, qkey in QUANT_SYSTEMS:
        split_map: dict[str, dict[str, Any] | None] = {}
        for sk, _, _, _ in EVAL_SPLITS:
            rdir = _run_dir_for(sys_key, sk)
            split_map[sk] = _load_run_stats(root / rdir) if rdir else None

        size_mb = artifact_files.get(qkey, {}).get("size_mb") if qkey else None
        local = local_by_key.get(qkey) if qkey else None
        if size_mb is None and local and local.get("file_size_mb") is not None:
            size_mb = local["file_size_mb"]

        systems[sys_key] = {
            "label": label,
            "quant_key": qkey,
            "size_mb": size_mb,
            "local": local,
            "splits": split_map,
        }

    recommendation = select_shipping_quant(systems)
    return {
        "artifacts": artifacts,
        "parity_f16": parity,
        "local_environment": local_raw.get("environment"),
        "systems": systems,
        "recommendation": recommendation,
    }


def _fmt_cell(st: dict[str, Any] | None) -> str:
    if st is None:
        return "_pending_"
    return f"**{_pct(st['execution_accuracy'])}** {_fmt_ci(st['wilson_95_ci'])}"


def render_quant_comparison_md(comp: dict[str, Any]) -> str:
    systems = comp["systems"]
    rec = comp["recommendation"]
    parity = comp.get("parity_f16")

    lines = [
        "# FormulaLM — Quantization & Local Benchmark Comparison (`v2-ship`)",
        "",
        "## Shipping Recommendation",
        "",
        f"- **Status:** **`{rec['status']}`**",
        f"- **Selected:** `{rec.get('recommended_label') or 'pending measured data'}`",
        f"- **Rationale:** {rec['rationale']}",
        (
            "- **Rule:** ship the smallest quantization whose execution accuracy stays within "
            "sampling noise of merged `F16` (95% Wilson CIs overlap `F16`, drop ≤ 1.5 pp on "
            "`val`/`test_synthetic` and ≤ 2.5 pp on `test_real_v2`/`test_real`) and fits safely "
            "in laptop RAM."
        ),
        "",
        "## 1. Execution Accuracy Across Splits (with 95% Wilson CIs)",
        "",
        (
            f"\\* _All v2-ship results on `test_real` and `test_synthetic` are "
            f"**{INFORMED_LABEL}**._"
        ),
        "",
        (
            "| System | Size (MB) | `val` (500) | `test_real_v2` (50) | "
            "`test_real` (80)* | `test_synthetic` (500)* |"
        ),
        "|---|---:|---|---|---|---|",
    ]

    for sys_key, _, _ in QUANT_SYSTEMS:
        s = systems[sys_key]
        sz = f"{s['size_mb']:.1f}" if s.get("size_mb") is not None else "—"
        val_cell = "_n/a_" if sys_key.startswith("base_") else _fmt_cell(s["splits"]["val"])
        lines.append(
            f"| {s['label']} | {sz} | {val_cell} | "
            f"{_fmt_cell(s['splits']['real_v2'])} | "
            f"{_fmt_cell(s['splits']['real'])} | "
            f"{_fmt_cell(s['splits']['synthetic'])} |"
        )

    # Delta vs F16 table when F16 exists
    f16 = systems["quant_f16"]
    if any(f16["splits"][sk] is not None for sk, _, _, _ in EVAL_SPLITS):
        lines.extend(
            [
                "",
                "## 2. Delta vs Merged F16 Reference",
                "",
                (
                    "| Quantization | Size vs F16 | Δ `val` | Δ `test_real_v2` | "
                    "Δ `test_real`* | Δ `test_synthetic`* |"
                ),
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for sys_key in ("quant_q8_0", "quant_q5_k_m", "quant_q4_k_m"):
            s = systems[sys_key]
            sz_ratio = (
                f"{100.0 * s['size_mb'] / f16['size_mb']:.0f}%"
                if (s.get("size_mb") and f16.get("size_mb"))
                else "—"
            )
            deltas = []
            for sk, _, _, _ in EVAL_SPLITS:
                a = s["splits"][sk]
                b = f16["splits"][sk]
                deltas.append(
                    _fmt_delta(a["execution_accuracy"], b["execution_accuracy"])
                    if (a is not None and b is not None)
                    else "_pending_"
                )
            lines.append(f"| {s['label']} | {sz_ratio} | {' | '.join(deltas)} |")

    lines.extend(
        [
            "",
            "## 3. Local Laptop Performance (Windows 11, i5-8365U, 8 GB RAM, CPU-only)",
            "",
            (
                "| Quantization | Status | Size (MB) | Load (s) | Peak RAM (MB) | "
                "Gen tok/s | Local 130-ex Exec. Acc (95% CI) |"
            ),
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for sys_key in ("quant_q4_k_m", "quant_q5_k_m", "quant_q8_0"):
        s = systems[sys_key]
        loc = s.get("local")
        if loc is None:
            lines.append(f"| {s['label']} | _pending_ | — | — | — | — | _pending_ |")
        elif loc.get("status") != "ok":
            sz = f"{loc['file_size_mb']:.1f}" if loc.get("file_size_mb") else "—"
            lines.append(
                f"| {s['label']} | `{loc['status']}` | {sz} | — | — | — | {loc.get('reason', '')} |"
            )
        else:
            tps = f"{loc['gen_tokens_per_s']:.1f}" if loc.get("gen_tokens_per_s") else "—"
            ci = loc["subset_wilson_95_ci"]
            lines.append(
                f"| {s['label']} | ok ({loc['engine']}) | {loc['file_size_mb']:.1f} | "
                f"{loc['load_time_s']:.2f} | {loc['peak_ram_mb']:.0f} | {tps} | "
                f"**{_pct(loc['subset_execution_accuracy'])}** "
                f"({loc['subset_k']}/{loc['subset_n']}, {_fmt_ci(ci)}) |"
            )

    lines.extend(
        ["", "## 4. Prompt-Format Parity (HF Merged FP16 vs GGUF F16, 20 fixed examples)", ""]
    )
    if parity is None:
        lines.append("_Pending: run Cell 5 of `notebooks/05_merge_quantize.ipynb`._")
    else:
        n = parity["n"]
        raw_pct = _pct(parity["raw_match_rate"])
        lines.append(f"- Raw exact match: **{parity['raw_match_count']}/{n}** ({raw_pct})")
        lines.append(
            f"- Normalized formula match: **{parity['formula_match_count']}/{n}** "
            f"({_pct(parity['formula_match_rate'])})"
        )
        lines.append(
            f"- Executed value agreement: **{parity['value_match_count']}/{n}** "
            f"({_pct(parity['value_match_rate'])})"
        )
        lines.append("- Full diff log: `results/quant_parity/parity_report.md`")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--out", default="results/quant_comparison.md")
    parser.add_argument("--json-out", default="results/quant_comparison.json")
    args = parser.parse_args(argv)

    comp = build_quant_comparison(args.results_dir)
    md = render_quant_comparison_md(comp)
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
    if args.json_out:
        jp = Path(args.json_out)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(comp, indent=2) + "\n", encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
