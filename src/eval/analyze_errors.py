"""Compare evaluation runs and extract the top failure patterns with real examples.

Reads one or more ``results/<run_name>/`` directories produced by ``src.eval.run_eval``,
builds a markdown comparison table, classifies every failure into fine-grained error
patterns, and writes a markdown summary report (and optional JSON).

CLI usage:
    uv run python -m src.eval.analyze_errors \
        --runs results/baseline_zeroshot_synthetic results/baseline_5shot_synthetic \
               results/baseline_zeroshot_real results/baseline_5shot_real \
        --out results/baseline_summary.md
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

_FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_COL_REF_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{1,3})(?=\d|:)")
_ROW_RANGE_RE = re.compile(r"[A-Z]{1,3}(\d+):[A-Z]{1,3}(\d+)")
_QUOTED_RE = re.compile(r'"([^"]*)"')


def _extract_funcs(formula: str) -> list[str]:
    return [m.group(1).upper() for m in _FUNC_RE.finditer(normalize_formula(formula))]


def _extract_cols(formula: str) -> set[str]:
    norm = normalize_formula(formula)
    no_str = _QUOTED_RE.sub("", norm)
    return set(_COL_REF_RE.findall(no_str))


def classify_failure(record: dict[str, Any]) -> str:
    """Assign a single actionable failure pattern label to an unsuccessful prediction."""
    err_type = record.get("error_type")
    err_msg = str(record.get("error_message") or "")
    pred = str(record.get("extracted_formula") or "")
    ref = str(record.get("reference_formula") or "")
    cat = str(record.get("category") or "unknown")

    if err_type == "timeout":
        return "execution_timeout"

    if err_type == "unsupported_function":
        if any(fn in err_msg for fn in ("TODAY", "NOW", "RAND")):
            return "volatile_function_used"
        return f"disallowed_or_unknown_function ({cat})"

    if err_type == "syntax_error":
        if not pred.startswith("="):
            return "no_formula_or_prose_only"
        if "parenthes" in err_msg.lower() or "quote" in err_msg.lower():
            return "unbalanced_parens_or_quotes"
        if "external" in err_msg.lower() or "sheet" in err_msg.lower():
            return "external_or_invalid_sheet_ref"
        return f"syntax_error ({cat})"

    if err_type == "runtime_error":
        if "#DIV/0!" in err_msg:
            return "runtime_div_by_zero"
        if "#N/A" in err_msg:
            return "runtime_lookup_na_missing_iferror"
        if "#VALUE!" in err_msg:
            return "runtime_value_type_error"
        if "#REF!" in err_msg or "Circular" in err_msg:
            return "runtime_bad_or_circular_ref"
        return f"runtime_error ({cat})"

    # Otherwise: executed cleanly, but returned the wrong value.
    pred_funcs = _extract_funcs(pred)
    ref_funcs = _extract_funcs(ref)
    pred_cols = _extract_cols(pred)
    ref_cols = _extract_cols(ref)

    if set(pred_funcs) != set(ref_funcs):
        if "IFERROR" in ref_funcs and "IFERROR" not in pred_funcs:
            return "missing_iferror_wrapper"
        if "DATE" in ref_funcs and "DATE" not in pred_funcs:
            return "wrong_date_criteria_format"
        if "ROUND" in ref_funcs and "ROUND" not in pred_funcs:
            return "missing_round_call"
        return f"wrong_function_choice ({cat})"

    if pred_cols != ref_cols:
        return f"wrong_column_reference ({cat})"

    pred_ranges = _ROW_RANGE_RE.findall(normalize_formula(pred))
    ref_ranges = _ROW_RANGE_RE.findall(normalize_formula(ref))
    if pred_ranges != ref_ranges:
        return f"wrong_row_bounds_or_range ({cat})"

    pred_quotes = _QUOTED_RE.findall(pred)
    ref_quotes = _QUOTED_RE.findall(ref)
    if pred_quotes != ref_quotes:
        return f"wrong_criteria_or_string_literal ({cat})"

    if "VLOOKUP" in ref_funcs or "INDEX" in ref_funcs or "MATCH" in ref_funcs:
        return "wrong_lookup_index_or_arg_order"

    if "SUMIFS" in ref_funcs or "AVERAGEIFS" in ref_funcs or "COUNTIFS" in ref_funcs:
        return "wrong_ifs_argument_order"

    return f"wrong_value_other ({cat})"


def analyze_runs(
    run_dirs: list[str | Path],
    *,
    top_k: int = 15,
) -> dict[str, Any]:
    """Load metrics + predictions from ``run_dirs`` and summarize comparisons + top failures."""
    run_rows: list[dict[str, Any]] = []
    pattern_counts: Counter[str] = Counter()
    pattern_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_failures = 0

    for rd in run_dirs:
        run_path = Path(rd)
        metrics_p = run_path / "metrics.json"
        preds_p = run_path / "predictions.jsonl"
        if not metrics_p.is_file():
            raise FileNotFoundError(f"Missing metrics.json in {run_path}")
        metrics = json.loads(metrics_p.read_text(encoding="utf-8"))
        run_rows.append(metrics)

        if preds_p.is_file():
            for line in preds_p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("exec_correct"):
                    continue
                total_failures += 1
                label = classify_failure(rec)
                pattern_counts[label] += 1
                if len(pattern_examples[label]) < 2:
                    pattern_examples[label].append(
                        {
                            "run": metrics["run_name"],
                            "id": rec["id"],
                            "sheet_id": rec["sheet_id"],
                            "request": rec["request"],
                            "reference_formula": rec["reference_formula"],
                            "extracted_formula": rec["extracted_formula"],
                            "error_type": rec.get("error_type") or "wrong_value",
                        }
                    )

    top_patterns = [
        {
            "rank": rank,
            "pattern": pat,
            "count": cnt,
            "share": round(cnt / total_failures, 4) if total_failures else 0.0,
            "examples": pattern_examples[pat],
        }
        for rank, (pat, cnt) in enumerate(pattern_counts.most_common(top_k), start=1)
    ]

    return {
        "runs": run_rows,
        "total_failures": total_failures,
        "top_patterns": top_patterns,
    }


def render_summary_md(
    analysis: dict[str, Any], *, title: str = "Baseline Evaluation Summary"
) -> str:
    def pct(v: float) -> str:
        return f"{100.0 * v:.1f}%"

    lines = [
        f"# {title}",
        "",
        "## Comparison Table",
        "",
        (
            "| Run | Backend | Dataset | Few-shot | N | Syntax Valid | "
            "Exec. Accuracy | Exact Match | Raw Format | Avg Latency |"
        ),
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for m in analysis["runs"]:
        ov = m["overall"]
        lines.append(
            f"| `{m['run_name']}` | `{m['backend']}` | `{m['dataset']}` | "
            f"{m['few_shot']} | {ov['n']} | {pct(ov['syntax_valid_rate'])} | "
            f"**{pct(ov['execution_accuracy'])}** | {pct(ov['exact_match_rate'])} | "
            f"{pct(ov['raw_format_ok_rate'])} | {ov['avg_latency_ms']:.1f} ms |"
        )

    lines.extend(
        [
            "",
            f"## Top {len(analysis['top_patterns'])} Failure Patterns "
            f"(total failures across runs: {analysis['total_failures']})",
            "",
        ]
    )
    if not analysis["top_patterns"]:
        lines.append("No failures recorded.")
    else:
        lines.append("| # | Failure Pattern | Count | Share | Example |")
        lines.append("|---:|---|---:|---:|---|")
        for item in analysis["top_patterns"]:
            ex = item["examples"][0]
            ex_text = (
                f"`{ex['id']}` ({ex['run']}): ref `{ex['reference_formula']}` vs "
                f"pred `{ex['extracted_formula']}`"
            )
            lines.append(
                f"| {item['rank']} | `{item['pattern']}` | {item['count']} | "
                f"{pct(item['share'])} | {ex_text} |"
            )

        lines.extend(["", "### Detailed Examples by Pattern", ""])
        for item in analysis["top_patterns"]:
            lines.append(
                f"{item['rank']}. **`{item['pattern']}`** ({item['count']} failures, "
                f"{pct(item['share'])})"
            )
            for ex in item["examples"]:
                lines.append(
                    f"   - `{ex['run']}` / `{ex['id']}` (`{ex['sheet_id']}`): {ex['request']}"
                )
                lines.append(
                    f"     - Ref: `{ex['reference_formula']}` | Pred: `{ex['extracted_formula']}` "
                    f"(`{ex['error_type']}`)"
                )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True, help="Paths to results/<run_name> dirs")
    parser.add_argument("--out", default=None, help="Optional path to write markdown summary")
    parser.add_argument("--json-out", default=None, help="Optional path to write JSON summary")
    parser.add_argument("--top-k", type=int, default=15, help="Number of failure patterns to list")
    parser.add_argument("--title", default="Baseline Evaluation Summary")
    args = parser.parse_args(argv)

    analysis = analyze_runs(args.runs, top_k=args.top_k)
    md = render_summary_md(analysis, title=args.title)

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
    if args.json_out:
        jp = Path(args.json_out)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")

    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
