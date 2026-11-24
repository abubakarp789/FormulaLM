"""Compare QLoRA v1 vs v2 across all splits with 95% Wilson CIs and a ship decision rule.

Splits compared (when present under ``--results-dir``):
1. ``val``            (``ft_v1_val`` vs ``ft_v2_val``) — validation selection split
2. ``test_real_v2``   (``ft_v1_real_v2`` vs ``ft_v2_real_v2``) — fresh blind hand-written set
3. ``test_synthetic`` (``ft_v1_synthetic`` vs ``ft_v2_synthetic``) — v2 labeled
   *'informed by v1 error analysis'*
4. ``test_real``      (``ft_v1_real`` vs ``ft_v2_real``) — v2 labeled
   *'informed by v1 error analysis'*

Decision rule (stated verbatim in the generated report):
    Ship v2 only if its execution accuracy is at least as high as v1 on ``val`` AND on
    ``test_real_v2``, and not meaningfully worse on ``test_real``; otherwise ship v1.

CLI usage:
    uv run python -m src.eval.compare_v1_v2 \
        --results-dir results \
        --out results/ft_v2_comparison.md \
        --json-out results/ft_v2_comparison.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WILSON_Z_95 = 1.959963984540054
DECISION_RULE_TEXT = (
    "Ship v2 only if its execution accuracy is at least as high as v1 on `val` "
    "AND on `test_real_v2`, and not meaningfully worse on `test_real`; otherwise ship v1."
)
INFORMED_LABEL = "informed by v1 error analysis"


@dataclass(frozen=True)
class SplitSpec:
    key: str
    title: str
    v1_run: str
    v2_run: str
    informed_by_v1: bool


SPLITS: tuple[SplitSpec, ...] = (
    SplitSpec("val", "`val` (validation)", "ft_v1_val", "ft_v2_val", False),
    SplitSpec(
        "test_real_v2",
        "`test_real_v2` (fresh blind)",
        "ft_v1_real_v2",
        "ft_v2_real_v2",
        False,
    ),
    SplitSpec(
        "test_synthetic",
        "`test_synthetic` (original synthetic)",
        "ft_v1_synthetic",
        "ft_v2_synthetic",
        True,
    ),
    SplitSpec(
        "test_real",
        "`test_real` (original realistic)",
        "ft_v1_real",
        "ft_v2_real",
        True,
    ),
)


def wilson_ci(k: int, n: int, *, z: float = WILSON_Z_95) -> tuple[float, float]:
    """Return the 95% Wilson score confidence interval ``(low, high)`` in ``[0.0, 1.0]``."""
    if n <= 0:
        return (0.0, 0.0)
    k = max(0, min(k, n))
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = (z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)) / denom
    return (max(0.0, round(center - margin, 4)), min(1.0, round(center + margin, 4)))


def _load_run_stats(run_dir: Path) -> dict[str, Any] | None:
    metrics_p = run_dir / "metrics.json"
    if not metrics_p.is_file():
        return None
    metrics = json.loads(metrics_p.read_text(encoding="utf-8"))

    # Recover exact integer correct counts from predictions.jsonl when available.
    preds_p = run_dir / "predictions.jsonl"
    overall_k: int | None = None
    cat_k: dict[str, int] = defaultdict(int)
    cat_n: dict[str, int] = defaultdict(int)
    if preds_p.is_file():
        overall_k = 0
        for line in preds_p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            cat = str(rec.get("category", "unknown"))
            cat_n[cat] += 1
            if rec.get("exec_correct"):
                overall_k += 1
                cat_k[cat] += 1

    ov = metrics["overall"]
    n = int(ov["n"])
    k = overall_k if overall_k is not None else round(float(ov["execution_accuracy"]) * n)
    acc = (k / n) if n > 0 else 0.0
    ci_lo, ci_hi = wilson_ci(k, n)

    by_category: dict[str, dict[str, Any]] = {}
    for cat, st in sorted(metrics.get("by_category", {}).items()):
        cn = int(st["n"])
        ck = (
            cat_k[cat]
            if (preds_p.is_file() and cat_n[cat] == cn)
            else round(float(st["execution_accuracy"]) * cn)
        )
        c_acc = (ck / cn) if cn > 0 else 0.0
        c_lo, c_hi = wilson_ci(ck, cn)
        by_category[cat] = {
            "n": cn,
            "k": ck,
            "execution_accuracy": round(c_acc, 4),
            "wilson_95_ci": [c_lo, c_hi],
            "syntax_valid_rate": float(st["syntax_valid_rate"]),
            "exact_match_rate": float(st["exact_match_rate"]),
        }

    run_cfg_p = run_dir / "run_config.json"
    provenance: dict[str, Any] = {}
    if run_cfg_p.is_file():
        rc = json.loads(run_cfg_p.read_text(encoding="utf-8"))
        cfg_inner = rc.get("config", {})
        provenance = {
            "backend": cfg_inner.get("backend"),
            "base_model_id": cfg_inner.get("base_model_id"),
            "base_revision": cfg_inner.get("base_revision"),
            "model_provenance": cfg_inner.get("model_provenance"),
        }

    return {
        "run_name": metrics.get("run_name", run_dir.name),
        "n": n,
        "k": k,
        "execution_accuracy": round(acc, 4),
        "wilson_95_ci": [ci_lo, ci_hi],
        "syntax_valid_rate": float(ov["syntax_valid_rate"]),
        "exact_match_rate": float(ov["exact_match_rate"]),
        "raw_format_ok_rate": float(ov.get("raw_format_ok_rate", 0.0)),
        "avg_latency_ms": float(ov.get("avg_latency_ms", 0.0)),
        "by_category": by_category,
        "provenance": provenance,
    }


def evaluate_decision_rule(
    split_results: dict[str, dict[str, Any]],
    *,
    real_drop_tolerance: float = 0.025,
) -> dict[str, Any]:
    """Apply the shipping decision rule across ``val``, ``test_real_v2``, and ``test_real``."""
    checks: dict[str, dict[str, Any]] = {}
    missing_required: list[str] = []

    for req_split in ("val", "test_real_v2", "test_real"):
        entry = split_results[req_split]
        v1 = entry["v1"]
        v2 = entry["v2"]
        if v1 is None:
            missing_required.append(f"{req_split}:v1")
        if v2 is None:
            missing_required.append(f"{req_split}:v2")

    # 1. val: v2 >= v1
    val_v1, val_v2 = split_results["val"]["v1"], split_results["val"]["v2"]
    if val_v1 is not None and val_v2 is not None:
        val_delta = round(val_v2["execution_accuracy"] - val_v1["execution_accuracy"], 4)
        checks["val"] = {
            "passed": val_v2["execution_accuracy"] >= val_v1["execution_accuracy"],
            "v1": val_v1["execution_accuracy"],
            "v2": val_v2["execution_accuracy"],
            "delta": val_delta,
            "criterion": "v2 >= v1 on val",
        }
    else:
        checks["val"] = {"passed": None, "criterion": "v2 >= v1 on val (PENDING)"}

    # 2. test_real_v2: v2 >= v1
    r2_v1, r2_v2 = split_results["test_real_v2"]["v1"], split_results["test_real_v2"]["v2"]
    if r2_v1 is not None and r2_v2 is not None:
        r2_delta = round(r2_v2["execution_accuracy"] - r2_v1["execution_accuracy"], 4)
        checks["test_real_v2"] = {
            "passed": r2_v2["execution_accuracy"] >= r2_v1["execution_accuracy"],
            "v1": r2_v1["execution_accuracy"],
            "v2": r2_v2["execution_accuracy"],
            "delta": r2_delta,
            "criterion": "v2 >= v1 on test_real_v2",
        }
    else:
        checks["test_real_v2"] = {
            "passed": None,
            "criterion": "v2 >= v1 on test_real_v2 (PENDING)",
        }

    # 3. test_real: not meaningfully worse (drop <= real_drop_tolerance, default 2.5 pp = 2/80)
    r1_v1, r1_v2 = split_results["test_real"]["v1"], split_results["test_real"]["v2"]
    if r1_v1 is not None and r1_v2 is not None:
        r1_delta = round(r1_v2["execution_accuracy"] - r1_v1["execution_accuracy"], 4)
        ci_overlap = (
            r1_v2["wilson_95_ci"][1] >= r1_v1["wilson_95_ci"][0]
            and r1_v1["wilson_95_ci"][1] >= r1_v2["wilson_95_ci"][0]
        )
        passed = r1_delta >= -real_drop_tolerance - 1e-12
        checks["test_real"] = {
            "passed": passed,
            "v1": r1_v1["execution_accuracy"],
            "v2": r1_v2["execution_accuracy"],
            "delta": r1_delta,
            "tolerance_pp": round(real_drop_tolerance * 100.0, 2),
            "wilson_ci_overlap": ci_overlap,
            "criterion": f"v2 >= v1 - {real_drop_tolerance * 100:.1f} pp on test_real",
        }
    else:
        checks["test_real"] = {
            "passed": None,
            "criterion": f"v2 >= v1 - {real_drop_tolerance * 100:.1f} pp on test_real (PENDING)",
        }

    if missing_required:
        decision = "PENDING"
        rationale = "Waiting for required evaluation runs: " + ", ".join(missing_required)
    elif all(checks[k]["passed"] is True for k in ("val", "test_real_v2", "test_real")):
        decision = "SHIP_V2"
        rationale = (
            "v2 execution accuracy is >= v1 on both val and test_real_v2, "
            "and not meaningfully worse on test_real."
        )
    else:
        failed = [k for k in ("val", "test_real_v2", "test_real") if checks[k]["passed"] is False]
        decision = "SHIP_V1"
        rationale = f"v2 did not satisfy decision rule on: {', '.join(failed)}; keep frozen v1."

    return {
        "rule": DECISION_RULE_TEXT,
        "real_drop_tolerance": real_drop_tolerance,
        "decision": decision,
        "rationale": rationale,
        "missing_required": missing_required,
        "checks": checks,
    }


def build_v1_v2_comparison(
    results_dir: str | Path = "results",
    *,
    real_drop_tolerance: float = 0.025,
) -> dict[str, Any]:
    """Load available v1 and v2 runs under ``results_dir`` and compute CIs + decision."""
    root = Path(results_dir)
    split_results: dict[str, dict[str, Any]] = {}
    for spec in SPLITS:
        v1 = _load_run_stats(root / spec.v1_run)
        v2 = _load_run_stats(root / spec.v2_run)
        delta_pp: float | None = None
        if v1 is not None and v2 is not None:
            delta_pp = round(100.0 * (v2["execution_accuracy"] - v1["execution_accuracy"]), 2)
        split_results[spec.key] = {
            "title": spec.title,
            "informed_by_v1": spec.informed_by_v1,
            "v1_run": spec.v1_run,
            "v2_run": spec.v2_run,
            "v1": v1,
            "v2": v2,
            "delta_exec_pp": delta_pp,
        }

    decision = evaluate_decision_rule(split_results, real_drop_tolerance=real_drop_tolerance)
    return {
        "decision": decision,
        "splits": split_results,
    }


def _pct(v: float) -> str:
    return f"{100.0 * v:.1f}%"


def _fmt_ci(ci: list[float] | tuple[float, float]) -> str:
    return f"[{100.0 * ci[0]:.1f}%, {100.0 * ci[1]:.1f}%]"


def _fmt_delta(after: float, before: float) -> str:
    diff = 100.0 * (after - before)
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f} pp"


def render_v1_v2_markdown(comp: dict[str, Any]) -> str:
    dec = comp["decision"]
    splits = comp["splits"]

    lines = [
        "# QLoRA v1 vs v2 Comparison (with 95% Wilson Confidence Intervals)",
        "",
        "## Decision Rule",
        "",
        f"> **{dec['rule']}**",
        "",
        (
            f"- **Operational tolerance on `test_real` (N=80):** drop of at most "
            f"`{dec['real_drop_tolerance'] * 100:.1f} pp` (2 examples out of 80; "
            "95% Wilson CI half-width is ~6–9 pp on N=80)."
        ),
        f"- **Current verdict:** **`{dec['decision']}`** — {dec['rationale']}",
        "",
        "| Gate | Criterion | v1 | v2 | Δ (v2 − v1) | Status |",
        "|---|---|---:|---:|---:|---|",
    ]

    for gate in ("val", "test_real_v2", "test_real"):
        chk = dec["checks"][gate]
        if chk["passed"] is None:
            lines.append(f"| `{gate}` | {chk['criterion']} | _pending_ | _pending_ | — | PENDING |")
        else:
            status = "PASS" if chk["passed"] else "FAIL"
            lines.append(
                f"| `{gate}` | {chk['criterion']} | {_pct(chk['v1'])} | {_pct(chk['v2'])} | "
                f"{_fmt_delta(chk['v2'], chk['v1'])} | **{status}** |"
            )

    lines.extend(
        [
            "",
            "## Overall Comparison (Every Split)",
            "",
            (
                "Note: Any v2 result on the original test sets (`test_synthetic`, `test_real`) "
                f"is labeled **'{INFORMED_LABEL}'** because v2 data additions were designed "
                "from v1 error analysis on those sets."
            ),
            "",
            (
                "| Split | Model | N | Correct | **Exec. Accuracy** | "
                "95% Wilson CI | Δ vs v1 | Syntax Valid | Exact Match | Avg Latency |"
            ),
            "|---|---|---:|---:|---:|---|---:|---:|---:|---:|",
        ]
    )

    for spec in SPLITS:
        entry = splits[spec.key]
        v1 = entry["v1"]
        v2 = entry["v2"]
        v2_model_label = (
            f"Fine-tuned v2 ({INFORMED_LABEL})" if spec.informed_by_v1 else "Fine-tuned v2"
        )

        if v1 is None:
            lines.append(
                f"| {spec.title} | Fine-tuned v1 (`v1-frozen`) | — | — | "
                "_pending_ | — | — | — | — | — |"
            )
        else:
            lines.append(
                f"| {spec.title} | Fine-tuned v1 (`v1-frozen`) | {v1['n']} | {v1['k']}/{v1['n']} | "
                f"**{_pct(v1['execution_accuracy'])}** | {_fmt_ci(v1['wilson_95_ci'])} | — | "
                f"{_pct(v1['syntax_valid_rate'])} | {_pct(v1['exact_match_rate'])} | "
                f"{v1['avg_latency_ms']:.1f} ms |"
            )

        if v2 is None:
            lines.append(
                f"| {spec.title} | {v2_model_label} | — | — | _pending_ | — | — | — | — | — |"
            )
        else:
            delta_s = (
                _fmt_delta(v2["execution_accuracy"], v1["execution_accuracy"])
                if v1 is not None
                else "—"
            )
            lines.append(
                f"| {spec.title} | **{v2_model_label}** | {v2['n']} | {v2['k']}/{v2['n']} | "
                f"**{_pct(v2['execution_accuracy'])}** | {_fmt_ci(v2['wilson_95_ci'])} | "
                f"{delta_s} | {_pct(v2['syntax_valid_rate'])} | "
                f"{_pct(v2['exact_match_rate'])} | {v2['avg_latency_ms']:.1f} ms |"
            )

    lines.extend(["", "## Per-Category Execution Accuracy (with 95% Wilson CIs)"])
    for spec in SPLITS:
        entry = splits[spec.key]
        v1 = entry["v1"]
        v2 = entry["v2"]
        tag = f" — v2 {INFORMED_LABEL}" if spec.informed_by_v1 else ""
        lines.extend(["", f"### {spec.title}{tag}", ""])
        if v1 is None and v2 is None:
            lines.append("_Pending: neither v1 nor v2 run exists yet._")
            continue

        cats = sorted(
            set((v1 or {}).get("by_category", {})) | set((v2 or {}).get("by_category", {}))
        )
        v2_col = f"v2 ({INFORMED_LABEL})" if spec.informed_by_v1 else "v2"
        lines.append(
            f"| Category | N | v1 Exec. Acc (95% Wilson CI) | "
            f"{v2_col} Exec. Acc (95% Wilson CI) | Δ (v2 − v1) |"
        )
        lines.append("|---|---:|---|---|---:|")
        for cat in cats:
            c1 = (v1 or {}).get("by_category", {}).get(cat)
            c2 = (v2 or {}).get("by_category", {}).get(cat)
            n = c2["n"] if c2 is not None else (c1["n"] if c1 is not None else 0)
            s1 = (
                f"{_pct(c1['execution_accuracy'])} "
                f"({c1['k']}/{c1['n']}, {_fmt_ci(c1['wilson_95_ci'])})"
                if c1 is not None
                else "_pending_"
            )
            s2 = (
                f"{_pct(c2['execution_accuracy'])} "
                f"({c2['k']}/{c2['n']}, {_fmt_ci(c2['wilson_95_ci'])})"
                if c2 is not None
                else "_pending_"
            )
            dlt = (
                _fmt_delta(c2["execution_accuracy"], c1["execution_accuracy"])
                if (c1 is not None and c2 is not None)
                else "—"
            )
            lines.append(f"| `{cat}` | {n} | {s1} | {s2} | {dlt} |")

    return "\n".join(lines) + "\n"


HEADLINE_SPLITS: tuple[tuple[str, str, bool, tuple[tuple[str, str], ...]], ...] = (
    (
        "test_real_v2",
        "`test_real_v2` (post-v2 fresh)",
        False,
        (
            ("base_zeroshot", "baseline_zeroshot_real_v2"),
            ("base_5shot", "baseline_5shot_real_v2"),
            ("ft_v1", "ft_v1_real_v2"),
            ("ft_v2", "ft_v2_real_v2"),
        ),
    ),
    (
        "test_real",
        "`test_real` (original realistic)",
        True,
        (
            ("base_zeroshot", "baseline_zeroshot_real"),
            ("base_5shot", "baseline_5shot_real"),
            ("ft_v1", "ft_v1_real"),
            ("ft_v2", "ft_v2_real"),
        ),
    ),
    (
        "test_synthetic",
        "`test_synthetic` (original synthetic)",
        True,
        (
            ("base_zeroshot", "baseline_zeroshot_synthetic"),
            ("base_5shot", "baseline_5shot_synthetic"),
            ("ft_v1", "ft_v1_synthetic"),
            ("ft_v2", "ft_v2_synthetic"),
        ),
    ),
)

_SYSTEM_DISPLAY: dict[str, str] = {
    "base_zeroshot": "Base `Qwen3-1.7B` (0-shot)",
    "base_5shot": "Base `Qwen3-1.7B` (5-shot, train)",
    "ft_v1": "Fine-tuned v1 (`v1-frozen`)",
    "ft_v2": "Fine-tuned v2 (`v2-ship`)",
}


def build_headline_summary(results_dir: str | Path = "results") -> dict[str, Any]:
    """Collect Base 0-shot, Base 5-shot, v1 and v2 on test_real_v2, test_real, test_synthetic."""
    root = Path(results_dir)
    splits_out: dict[str, dict[str, Any]] = {}
    for split_key, title, v2_informed, run_specs in HEADLINE_SPLITS:
        systems: dict[str, dict[str, Any] | None] = {}
        for sys_key, run_name in run_specs:
            systems[sys_key] = _load_run_stats(root / run_name)
        splits_out[split_key] = {
            "title": title,
            "v2_informed_by_v1": v2_informed,
            "systems": systems,
        }
    return {"splits": splits_out}


def render_headline_markdown(headline: dict[str, Any]) -> str:
    """Render one unified headline table across test_real_v2, test_real and test_synthetic."""
    lines = [
        "# FormulaLM — Final Headline Results (Base vs QLoRA v1 vs QLoRA v2)",
        "",
        (
            "Base model: `Qwen/Qwen3-1.7B` (`70d244cc`, Apache-2.0, fp16, `enable_thinking=False`, "
            "`temperature=0`, `max_tokens=96`, `seed=42`). "
            "95% confidence intervals are exact Wilson score intervals."
        ),
        "",
        (
            f"Note: Fine-tuned v2 results on `test_real` and `test_synthetic` are labeled "
            f"**'{INFORMED_LABEL}'** because v2 data additions targeted v1 error clusters on "
            "those sets."
        ),
        "",
        (
            "| Test Set | System | N | Correct | **Exec. Accuracy** | "
            "95% Wilson CI | Δ vs Base 0-shot | Syntax Valid | Exact Match |"
        ),
        "|---|---|---:|---:|---:|---|---:|---:|---:|",
    ]

    for split_key, title, v2_informed, run_specs in HEADLINE_SPLITS:
        systems = headline["splits"][split_key]["systems"]
        base0 = systems.get("base_zeroshot")
        for sys_key, _ in run_specs:
            st = systems.get(sys_key)
            label = _SYSTEM_DISPLAY[sys_key]
            if sys_key == "ft_v2" and v2_informed:
                label = f"{label} ({INFORMED_LABEL})"
            if st is None:
                lines.append(f"| {title} | {label} | — | — | _pending_ | — | — | — | — |")
                continue
            if sys_key == "base_zeroshot" or base0 is None:
                delta_s = "—"
            else:
                delta_s = _fmt_delta(st["execution_accuracy"], base0["execution_accuracy"])
            bold_label = f"**{label}**" if sys_key == "ft_v2" else label
            lines.append(
                f"| {title} | {bold_label} | {st['n']} | {st['k']}/{st['n']} | "
                f"**{_pct(st['execution_accuracy'])}** | {_fmt_ci(st['wilson_95_ci'])} | "
                f"{delta_s} | {_pct(st['syntax_valid_rate'])} | {_pct(st['exact_match_rate'])} |"
            )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default="results", help="Directory containing run folders")
    parser.add_argument("--out", default="results/ft_v2_comparison.md", help="Output markdown path")
    parser.add_argument(
        "--json-out", default="results/ft_v2_comparison.json", help="Output JSON path"
    )
    parser.add_argument(
        "--headline-out",
        default=None,
        help="Optional path for unified headline markdown (e.g. results/final_headline.md)",
    )
    parser.add_argument(
        "--headline-json",
        default=None,
        help="Optional path for unified headline JSON (e.g. results/final_headline.json)",
    )
    parser.add_argument(
        "--real-drop-tolerance",
        type=float,
        default=0.025,
        help="Max allowed drop on test_real (default 0.025 = 2.5 pp)",
    )
    args = parser.parse_args(argv)

    comp = build_v1_v2_comparison(
        results_dir=args.results_dir,
        real_drop_tolerance=args.real_drop_tolerance,
    )
    md = render_v1_v2_markdown(comp)
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
    if args.json_out:
        jp = Path(args.json_out)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(comp, indent=2) + "\n", encoding="utf-8")
    print(md)

    if args.headline_out or args.headline_json:
        headline = build_headline_summary(results_dir=args.results_dir)
        h_md = render_headline_markdown(headline)
        if args.headline_out:
            hp = Path(args.headline_out)
            hp.parent.mkdir(parents=True, exist_ok=True)
            hp.write_text(h_md, encoding="utf-8")
        if args.headline_json:
            hjp = Path(args.headline_json)
            hjp.parent.mkdir(parents=True, exist_ok=True)
            hjp.write_text(json.dumps(headline, indent=2) + "\n", encoding="utf-8")
        print(h_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
