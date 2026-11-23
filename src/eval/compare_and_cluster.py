"""Compare baseline vs fine-tuned runs and cluster failures for targeted iteration.

Produces:
1. Overall comparison table (zero-shot, 5-shot, fine-tuned v1 on synthetic & real test sets)
2. Per-category execution accuracy comparison tables
3. Per-difficulty execution accuracy comparison tables
4. Six-cluster error analysis (``wrong_column``, ``wrong_function``, ``wrong_argument_order``,
   ``syntax_error``, ``wrong_aggregation``, ``over_generation``) with up to 5 real examples each.

CLI usage:
    uv run python -m src.eval.compare_and_cluster \
        --ft-synthetic results/ft_v1_synthetic \
        --ft-real results/ft_v1_real \
        --out results/ft_v1_comparison.md \
        --json-out results/ft_v1_comparison.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.eval.normalize import normalize_formula

CLUSTERS: tuple[str, ...] = (
    "wrong_column",
    "wrong_function",
    "wrong_argument_order",
    "syntax_error",
    "wrong_aggregation",
    "over_generation",
)

_FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_COL_REF_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{1,3})(?=\d|:)")
_QUOTED_RE = re.compile(r'"([^"]*)"')
_AGG_CATEGORIES = {"aggregation", "conditional_aggregation", "math_and_composition"}
_AGG_FUNCS = {
    "SUM",
    "SUMIF",
    "SUMIFS",
    "COUNT",
    "COUNTIF",
    "COUNTIFS",
    "AVERAGE",
    "AVERAGEIF",
    "AVERAGEIFS",
    "MIN",
    "MAX",
    "ROUND",
}


def _funcs(formula: str) -> list[str]:
    return [m.group(1).upper() for m in _FUNC_RE.finditer(normalize_formula(formula))]


def _cols(formula: str) -> set[str]:
    no_str = _QUOTED_RE.sub("", normalize_formula(formula))
    return set(_COL_REF_RE.findall(no_str))


def cluster_failure(record: dict[str, Any]) -> str:
    """Map an unsuccessful prediction to one of the 6 canonical error-analysis clusters."""
    raw = str(record.get("raw_output") or "")
    pred = str(record.get("extracted_formula") or "")
    ref = str(record.get("reference_formula") or "")
    err_type = record.get("error_type")
    cat = str(record.get("category") or "")

    # 1. Over-generation: model emitted prose, markdown fences, <think>, or multiple lines.
    if record.get("raw_format_ok") is False or (
        raw.strip() and (not raw.strip().startswith("=") or "\n" in raw.strip() or "```" in raw)
    ):
        return "over_generation"

    # 2. Disallowed / wrong function reported by executor.
    if err_type == "unsupported_function":
        return "wrong_function"

    # 3. Syntax error (unbalanced parens/quotes, invalid sheet ref, malformed syntax).
    if err_type == "syntax_error":
        return "syntax_error"

    pred_funcs = _funcs(pred)
    ref_funcs = _funcs(ref)
    pred_cols = _cols(pred)
    ref_cols = _cols(ref)

    # 4. Wrong function chosen (executed or runtime error, but different function set).
    if set(pred_funcs) != set(ref_funcs):
        # Distinguish aggregation function mismatch (e.g. SUM vs AVERAGE, missing ROUND).
        if cat in _AGG_CATEGORIES and (set(pred_funcs) & _AGG_FUNCS or set(ref_funcs) & _AGG_FUNCS):
            if set(pred_funcs) - set(ref_funcs) <= _AGG_FUNCS and (
                set(ref_funcs) - set(pred_funcs) <= _AGG_FUNCS
            ):
                return "wrong_aggregation"
        return "wrong_function"

    # 5. Wrong column reference (same functions, wrong column letters).
    if pred_cols != ref_cols:
        return "wrong_column"

    # 6. Same functions & same columns: distinguish aggregation error vs argument-order/criteria.
    if err_type == "runtime_error":
        if any(
            f in ref_funcs
            for f in (
                "SUMIFS",
                "AVERAGEIFS",
                "COUNTIFS",
                "VLOOKUP",
                "XLOOKUP",
                "INDEX",
                "MATCH",
                "MID",
                "IF",
            )
        ):
            return "wrong_argument_order"
        if cat in _AGG_CATEGORIES:
            return "wrong_aggregation"
        return "wrong_argument_order"

    # Multi-argument order-sensitive functions with same function set & same column set.
    if any(
        f in ref_funcs
        for f in (
            "SUMIF",
            "SUMIFS",
            "AVERAGEIF",
            "AVERAGEIFS",
            "COUNTIF",
            "COUNTIFS",
            "VLOOKUP",
            "XLOOKUP",
            "INDEX",
            "MATCH",
            "MID",
            "IF",
            "IFS",
            "TEXTJOIN",
            "CONCAT",
            "DATE",
        )
    ):
        # Check if criteria/operator or aggregation bounds differed vs argument positions.
        if cat in _AGG_CATEGORIES and _QUOTED_RE.findall(pred) != _QUOTED_RE.findall(ref):
            return "wrong_aggregation"
        return "wrong_argument_order"

    if cat in _AGG_CATEGORIES:
        return "wrong_aggregation"
    return "wrong_argument_order"


def _load_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    preds: list[dict[str, Any]] = []
    pred_p = run_dir / "predictions.jsonl"
    if pred_p.is_file():
        for line in pred_p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                preds.append(json.loads(line))
    return metrics, preds


def build_comparison(
    *,
    base_zero_syn: str | Path,
    base_five_syn: str | Path,
    ft_syn: str | Path,
    base_zero_real: str | Path,
    base_five_real: str | Path,
    ft_real: str | Path,
    ft_label: str = "Fine-tuned v1",
    examples_per_cluster: int = 5,
) -> dict[str, Any]:
    """Compare baseline zero-shot, 5-shot and fine-tuned runs on synthetic and real sets."""
    syn_runs = {
        "base_zeroshot": _load_run(Path(base_zero_syn)),
        "base_5shot": _load_run(Path(base_five_syn)),
        "ft": _load_run(Path(ft_syn)),
    }
    real_runs = {
        "base_zeroshot": _load_run(Path(base_zero_real)),
        "base_5shot": _load_run(Path(base_five_real)),
        "ft": _load_run(Path(ft_real)),
    }

    # Cluster all failures of the fine-tuned model across both test sets.
    cluster_counts: Counter[str] = Counter()
    cluster_by_split: dict[str, Counter[str]] = defaultdict(Counter)
    cluster_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    ft_total_failures = 0
    for split_label, (_m, preds) in (
        ("test_real", real_runs["ft"]),
        ("test_synthetic", syn_runs["ft"]),
    ):
        for rec in preds:
            if rec.get("exec_correct"):
                continue
            ft_total_failures += 1
            cname = cluster_failure(rec)
            cluster_counts[cname] += 1
            cluster_by_split[cname][split_label] += 1
            if len(cluster_examples[cname]) < examples_per_cluster:
                cluster_examples[cname].append(
                    {
                        "split": split_label,
                        "id": rec["id"],
                        "sheet_id": rec["sheet_id"],
                        "category": rec["category"],
                        "difficulty": rec["difficulty"],
                        "request": rec["request"],
                        "reference_formula": rec["reference_formula"],
                        "extracted_formula": rec["extracted_formula"],
                        "raw_output": rec["raw_output"],
                        "expected_value": rec.get("expected_value"),
                        "predicted_value": rec.get("predicted_value"),
                        "error_type": rec.get("error_type") or "wrong_value",
                        "error_message": rec.get("error_message"),
                    }
                )

    ordered_clusters = [
        {
            "cluster": cname,
            "count": cluster_counts[cname],
            "share": round(cluster_counts[cname] / ft_total_failures, 4)
            if ft_total_failures
            else 0.0,
            "test_synthetic_count": cluster_by_split[cname]["test_synthetic"],
            "test_real_count": cluster_by_split[cname]["test_real"],
            "examples": cluster_examples[cname],
        }
        for cname in sorted(CLUSTERS, key=lambda c: (-cluster_counts[c], c))
    ]

    return {
        "ft_label": ft_label,
        "synthetic": {k: m for k, (m, _) in syn_runs.items()},
        "real": {k: m for k, (m, _) in real_runs.items()},
        "ft_total_failures": ft_total_failures,
        "clusters": ordered_clusters,
    }


def _pct(v: float) -> str:
    return f"{100.0 * v:.1f}%"


def _delta_pp(after: float, before: float) -> str:
    diff = 100.0 * (after - before)
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f} pp"


def render_comparison_md(comp: dict[str, Any]) -> str:
    ft_label = comp["ft_label"]
    syn = comp["synthetic"]
    real = comp["real"]

    lines = [
        f"# Comparison & Error Analysis: Base vs {ft_label}",
        "",
        "## 1. Overall Comparison",
        "",
        (
            "| Test Set | System | N | Syntax Valid | **Exec. Accuracy** | "
            "Δ vs 0-shot | Exact Match | Raw Format | Avg Latency |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ds_label, grp in (("`test_synthetic`", syn), ("`test_real`", real)):
        base0_acc = grp["base_zeroshot"]["overall"]["execution_accuracy"]
        for key, sys_name in (
            ("base_zeroshot", "Base zero-shot"),
            ("base_5shot", "Base 5-shot"),
            ("ft", f"**{ft_label}**"),
        ):
            ov = grp[key]["overall"]
            delta = (
                "—" if key == "base_zeroshot" else _delta_pp(ov["execution_accuracy"], base0_acc)
            )
            lines.append(
                f"| {ds_label} | {sys_name} | {ov['n']} | {_pct(ov['syntax_valid_rate'])} | "
                f"**{_pct(ov['execution_accuracy'])}** | {delta} | "
                f"{_pct(ov['exact_match_rate'])} | "
                f"{_pct(ov['raw_format_ok_rate'])} | {ov['avg_latency_ms']:.1f} ms |"
            )

    # 2. Per-category comparison (execution accuracy)
    for title, grp in (
        ("2A. Execution Accuracy by Category (`test_synthetic`)", syn),
        ("2B. Execution Accuracy by Category (`test_real`)", real),
    ):
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                f"| Category | N | Base 0-shot | Base 5-shot | **{ft_label}** | Δ vs 0-shot |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        cats = sorted(grp["ft"]["by_category"])
        for cat in cats:
            n = grp["ft"]["by_category"][cat]["n"]
            b0 = grp["base_zeroshot"]["by_category"].get(cat, {}).get("execution_accuracy", 0.0)
            b5 = grp["base_5shot"]["by_category"].get(cat, {}).get("execution_accuracy", 0.0)
            ft = grp["ft"]["by_category"][cat]["execution_accuracy"]
            lines.append(
                f"| `{cat}` | {n} | {_pct(b0)} | {_pct(b5)} | "
                f"**{_pct(ft)}** | {_delta_pp(ft, b0)} |"
            )

    # 3. Per-difficulty comparison (execution accuracy)
    for title, grp in (
        ("3A. Execution Accuracy by Difficulty (`test_synthetic`)", syn),
        ("3B. Execution Accuracy by Difficulty (`test_real`)", real),
    ):
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                f"| Difficulty | N | Base 0-shot | Base 5-shot | **{ft_label}** | Δ vs 0-shot |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for d in sorted(grp["ft"]["by_difficulty"]):
            n = grp["ft"]["by_difficulty"][d]["n"]
            b0 = grp["base_zeroshot"]["by_difficulty"].get(d, {}).get("execution_accuracy", 0.0)
            b5 = grp["base_5shot"]["by_difficulty"].get(d, {}).get("execution_accuracy", 0.0)
            ft = grp["ft"]["by_difficulty"][d]["execution_accuracy"]
            lines.append(
                f"| Difficulty {d} | {n} | {_pct(b0)} | {_pct(b5)} | "
                f"**{_pct(ft)}** | {_delta_pp(ft, b0)} |"
            )

    # 4. 6-cluster error analysis on fine-tuned model failures
    lines.extend(
        [
            "",
            (
                f"## 4. Error Analysis — {ft_label} Failures "
                f"({comp['ft_total_failures']} total across both test sets)"
            ),
            "",
            "| Cluster | Total | Share | `test_synthetic` | `test_real` |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for cl in comp["clusters"]:
        lines.append(
            f"| `{cl['cluster']}` | {cl['count']} | {_pct(cl['share'])} | "
            f"{cl['test_synthetic_count']} | {cl['test_real_count']} |"
        )

    for cl in comp["clusters"]:
        if cl["count"] == 0:
            continue
        lines.extend(
            [
                "",
                f"### Cluster: `{cl['cluster']}` ({cl['count']} failures — "
                f"{cl['test_synthetic_count']} synthetic, {cl['test_real_count']} real)",
                "",
            ]
        )
        for i, ex in enumerate(cl["examples"], start=1):
            lines.append(
                f"{i}. **`{ex['id']}`** (`{ex['split']}`, `{ex['sheet_id']}`, "
                f"`{ex['category']}`/D{ex['difficulty']}): {ex['request']}"
            )
            lines.append(f"   - Ref: `{ex['reference_formula']}` → `{ex['expected_value']!r}`")
            lines.append(
                f"   - Pred: `{ex['extracted_formula']}` → `{ex['predicted_value']!r}` "
                f"(`{ex['error_type']}`)"
            )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zero-syn", default="results/baseline_zeroshot_synthetic")
    parser.add_argument("--base-five-syn", default="results/baseline_5shot_synthetic")
    parser.add_argument("--ft-synthetic", required=True)
    parser.add_argument("--base-zero-real", default="results/baseline_zeroshot_real")
    parser.add_argument("--base-five-real", default="results/baseline_5shot_real")
    parser.add_argument("--ft-real", required=True)
    parser.add_argument("--ft-label", default="Fine-tuned v1")
    parser.add_argument("--examples-per-cluster", type=int, default=5)
    parser.add_argument("--out", default=None, help="Output markdown path")
    parser.add_argument("--json-out", default=None, help="Output JSON path")
    args = parser.parse_args(argv)

    comp = build_comparison(
        base_zero_syn=args.base_zero_syn,
        base_five_syn=args.base_five_syn,
        ft_syn=args.ft_synthetic,
        base_zero_real=args.base_zero_real,
        base_five_real=args.base_five_real,
        ft_real=args.ft_real,
        ft_label=args.ft_label,
        examples_per_cluster=args.examples_per_cluster,
    )
    md = render_comparison_md(comp)
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
