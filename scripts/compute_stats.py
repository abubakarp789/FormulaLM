"""Compute exact McNemar's test p-values and 95% bootstrap/Wilson CIs from saved results.

Reads exclusively from committed per-item `predictions.jsonl` logs under `results/`
(zero extra inference). Writes:
- results/stats_summary.json
- results/stats_summary.md

Usage:
    uv run python scripts/compute_stats.py
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOOTSTRAP_SAMPLES = 10_000
DEFAULT_SEED = 42


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """95% Wilson score confidence interval for binomial proportion k/n."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * n)) / n)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def bootstrap_ci(
    outcomes: list[int],
    *,
    n_resamples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed: int = DEFAULT_SEED,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for binary accuracy outcomes (0/1)."""
    n = len(outcomes)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_resamples):
        total = 0
        for _ in range(n):
            total += outcomes[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo_idx = int((alpha / 2.0) * n_resamples)
    hi_idx = min(n_resamples - 1, int((1.0 - alpha / 2.0) * n_resamples))
    return (round(means[lo_idx], 4), round(means[hi_idx], 4))


def mcnemar_exact(outcomes_a: list[int], outcomes_b: list[int]) -> dict[str, Any]:
    """Two-sided exact McNemar's test comparing paired binary outcomes A vs B.

    Counts:
      - ``a_only`` (b): A correct (1), B wrong (0)
      - ``b_only`` (c): A wrong (0), B correct (1)
      - ``both_correct``: both 1
      - ``both_wrong``: both 0
    Exact two-sided binomial p-value under H0: P(a_only | discordant) = 0.5.
    """
    if len(outcomes_a) != len(outcomes_b):
        raise ValueError(
            "Paired outcome lists must have identical lengths "
            f"({len(outcomes_a)} vs {len(outcomes_b)})"
        )
    n = len(outcomes_a)
    both_correct = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if a == 1 and b == 1)
    both_wrong = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if a == 0 and b == 0)
    a_only = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if a == 1 and b == 0)
    b_only = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if a == 0 and b == 1)

    n_disc = a_only + b_only
    if n_disc == 0:
        p_val = 1.0
    else:
        k_min = min(a_only, b_only)
        tail = sum(math.comb(n_disc, i) for i in range(k_min + 1)) * (0.5**n_disc)
        p_val = min(1.0, 2.0 * tail)

    acc_a = sum(outcomes_a) / n if n else 0.0
    acc_b = sum(outcomes_b) / n if n else 0.0
    return {
        "n": n,
        "acc_a": round(acc_a, 4),
        "acc_b": round(acc_b, 4),
        "delta_pp": round((acc_a - acc_b) * 100.0, 2),
        "both_correct": both_correct,
        "both_wrong": both_wrong,
        "a_only": a_only,
        "b_only": b_only,
        "discordant": n_disc,
        "p_value": p_val,
        "significant_0_05": p_val < 0.05,
        "significant_0_01": p_val < 0.01,
    }


def _load_predictions(rel_path: str, field: str = "exec_correct") -> dict[str, int]:
    """Load id -> binary field (0/1) mapping from a predictions.jsonl file."""
    path = REPO_ROOT / rel_path
    if not path.is_file():
        raise FileNotFoundError(f"Missing predictions file: {path}")
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        rec_id = str(rec["id"])
        out[rec_id] = 1 if rec.get(field) else 0
    return out


def _align_outcomes(
    preds_map: dict[str, dict[str, int]],
) -> tuple[list[str], dict[str, list[int]]]:
    """Verify identical example IDs across all systems in a split and return sorted alignment."""
    names = list(preds_map.keys())
    base_ids = sorted(preds_map[names[0]].keys())
    base_set = set(base_ids)
    for name in names[1:]:
        other_set = set(preds_map[name].keys())
        if other_set != base_set:
            raise ValueError(
                f"ID mismatch between {names[0]} ({len(base_set)}) and {name} ({len(other_set)})"
            )
    aligned = {name: [preds_map[name][i] for i in base_ids] for name in names}
    return base_ids, aligned


def _format_p(p: float) -> str:
    if p < 1e-4:
        return f"{p:.2e}"
    return f"{p:.4f}"


def compute_all_stats() -> dict[str, Any]:
    """Compute CIs and paired McNemar tests across test_real_v2, test_real, and SpreadsheetBench."""
    summary: dict[str, Any] = {
        "bootstrap_resamples": DEFAULT_BOOTSTRAP_SAMPLES,
        "seed": DEFAULT_SEED,
        "splits": {},
    }

    # --- 1. test_real_v2 (N=50) ---
    rv2_sources: list[tuple[str, str, str]] = [
        (
            "base_1_7b_0shot",
            "Base Qwen3-1.7B (0-shot)",
            "results/baseline_zeroshot_real_v2/predictions.jsonl",
        ),
        (
            "base_1_7b_5shot",
            "Base Qwen3-1.7B (5-shot)",
            "results/baseline_5shot_real_v2/predictions.jsonl",
        ),
        (
            "base_4b_0shot",
            "Base Qwen3-4B (0-shot, CPU)",
            "results/baseline_4b_real_v2/predictions.jsonl",
        ),
        (
            "ft_v2_bf16",
            "Fine-tuned v2-ship (LoRA, BF16)",
            "results/ft_v2_real_v2/predictions.jsonl",
        ),
        (
            "local_q4_k_m",
            "FormulaLM Q4_K_M (Local CPU)",
            "results/local_benchmark/local_q4_k_m_real_v2/predictions.jsonl",
        ),
        (
            "local_q5_k_m",
            "FormulaLM Q5_K_M (Local CPU)",
            "results/local_benchmark/local_q5_k_m_real_v2/predictions.jsonl",
        ),
        (
            "local_q8_0",
            "FormulaLM Q8_0 (Local CPU)",
            "results/local_benchmark/local_q8_0_real_v2/predictions.jsonl",
        ),
        (
            "colab_q5_k_m",
            "FormulaLM Q5_K_M (Colab llama-server)",
            "results/quant_q5_k_m_real_v2/predictions.jsonl",
        ),
    ]
    rv2_preds: dict[str, dict[str, int]] = {}
    rv2_labels: dict[str, str] = {}
    for key, label, rel in rv2_sources:
        if (REPO_ROOT / rel).is_file():
            rv2_preds[key] = _load_predictions(rel)
            rv2_labels[key] = label

    _, rv2_aligned = _align_outcomes(rv2_preds)
    rv2_sys_stats: dict[str, Any] = {}
    for key, outcomes in rv2_aligned.items():
        k = sum(outcomes)
        n = len(outcomes)
        rv2_sys_stats[key] = {
            "label": rv2_labels[key],
            "k": k,
            "n": n,
            "execution_accuracy": round(k / n, 4),
            "wilson_95_ci": list(wilson_ci(k, n)),
            "bootstrap_95_ci": list(bootstrap_ci(outcomes)),
        }

    rv2_pairs_spec = [
        ("local_q5_k_m", "base_1_7b_0shot"),
        ("local_q5_k_m", "base_1_7b_5shot"),
        ("local_q5_k_m", "base_4b_0shot"),
        ("colab_q5_k_m", "base_1_7b_0shot"),
        ("colab_q5_k_m", "base_1_7b_5shot"),
        ("colab_q5_k_m", "base_4b_0shot"),
        ("local_q5_k_m", "local_q4_k_m"),
    ]
    rv2_tests: list[dict[str, Any]] = []
    for a, b in rv2_pairs_spec:
        if a in rv2_aligned and b in rv2_aligned:
            res = mcnemar_exact(rv2_aligned[a], rv2_aligned[b])
            res["system_a"] = a
            res["system_a_label"] = rv2_labels[a]
            res["system_b"] = b
            res["system_b_label"] = rv2_labels[b]
            rv2_tests.append(res)

    summary["splits"]["test_real_v2"] = {
        "n": len(next(iter(rv2_aligned.values()))),
        "systems": rv2_sys_stats,
        "paired_mcnemar": rv2_tests,
    }

    # --- 2. test_real (N=80, Q5_K_M vs Q4_K_M local & Colab quantization check) ---
    tr_sources = [
        (
            "local_q4_k_m",
            "FormulaLM Q4_K_M (Local CPU)",
            "results/local_benchmark/local_q4_k_m_real/predictions.jsonl",
        ),
        (
            "local_q5_k_m",
            "FormulaLM Q5_K_M (Local CPU)",
            "results/local_benchmark/local_q5_k_m_real/predictions.jsonl",
        ),
        (
            "colab_q4_k_m",
            "FormulaLM Q4_K_M (Colab)",
            "results/quant_q4_k_m_real/predictions.jsonl",
        ),
        (
            "colab_q5_k_m",
            "FormulaLM Q5_K_M (Colab)",
            "results/quant_q5_k_m_real/predictions.jsonl",
        ),
    ]
    tr_preds: dict[str, dict[str, int]] = {}
    tr_labels: dict[str, str] = {}
    for key, label, rel in tr_sources:
        if (REPO_ROOT / rel).is_file():
            tr_preds[key] = _load_predictions(rel)
            tr_labels[key] = label
    if tr_preds:
        _, tr_aligned = _align_outcomes(tr_preds)
        tr_sys = {
            key: {
                "label": tr_labels[key],
                "k": sum(outcomes),
                "n": len(outcomes),
                "execution_accuracy": round(sum(outcomes) / len(outcomes), 4),
                "wilson_95_ci": list(wilson_ci(sum(outcomes), len(outcomes))),
                "bootstrap_95_ci": list(bootstrap_ci(outcomes)),
            }
            for key, outcomes in tr_aligned.items()
        }
        tr_tests = []
        for a, b in (("local_q5_k_m", "local_q4_k_m"), ("colab_q5_k_m", "colab_q4_k_m")):
            if a in tr_aligned and b in tr_aligned:
                res = mcnemar_exact(tr_aligned[a], tr_aligned[b])
                res["system_a"] = a
                res["system_a_label"] = tr_labels[a]
                res["system_b"] = b
                res["system_b_label"] = tr_labels[b]
                tr_tests.append(res)
        summary["splits"]["test_real"] = {
            "n": len(next(iter(tr_aligned.values()))),
            "systems": tr_sys,
            "paired_mcnemar": tr_tests,
        }

    # --- 3. External SpreadsheetBench Verified 400 subset (N=56) ---
    ext_sources = [
        (
            "ext_base_1_7b_0shot",
            "Base Qwen3-1.7B (0-shot, CPU)",
            "results/external_bench/ext_base_1_7b_0shot/predictions.jsonl",
        ),
        (
            "ext_base_1_7b_5shot",
            "Base Qwen3-1.7B (5-shot, CPU)",
            "results/external_bench/ext_base_1_7b_5shot/predictions.jsonl",
        ),
        (
            "ext_formulalm_q5_k_m",
            "FormulaLM Q5_K_M (0-shot, CPU)",
            "results/external_bench/ext_formulalm_q5_k_m/predictions.jsonl",
        ),
    ]
    ext_preds = {
        k: _load_predictions(rel)
        for k, _, rel in ext_sources
        if (REPO_ROOT / rel).is_file()
    }
    ext_labels = {k: lbl for k, lbl, _ in ext_sources if k in ext_preds}
    if ext_preds:
        _, ext_aligned = _align_outcomes(ext_preds)
        ext_sys = {
            key: {
                "label": ext_labels[key],
                "k": sum(outcomes),
                "n": len(outcomes),
                "execution_accuracy": round(sum(outcomes) / len(outcomes), 4),
                "wilson_95_ci": list(wilson_ci(sum(outcomes), len(outcomes))),
                "bootstrap_95_ci": list(bootstrap_ci(outcomes)),
            }
            for key, outcomes in ext_aligned.items()
        }
        ext_tests = []
        for a, b in (
            ("ext_formulalm_q5_k_m", "ext_base_1_7b_0shot"),
            ("ext_formulalm_q5_k_m", "ext_base_1_7b_5shot"),
        ):
            if a in ext_aligned and b in ext_aligned:
                res = mcnemar_exact(ext_aligned[a], ext_aligned[b])
                res["system_a"] = a
                res["system_a_label"] = ext_labels[a]
                res["system_b"] = b
                res["system_b_label"] = ext_labels[b]
                ext_tests.append(res)
        summary["splits"]["external_spreadsheetbench"] = {
            "n": len(next(iter(ext_aligned.values()))),
            "systems": ext_sys,
            "paired_mcnemar": ext_tests,
        }

        # Syntax validity paired McNemar on SpreadsheetBench (N=56)
        ext_syn_preds = {
            k: _load_predictions(rel, field="syntax_valid")
            for k, _, rel in ext_sources
            if (REPO_ROOT / rel).is_file()
        }
        _, ext_syn_aligned = _align_outcomes(ext_syn_preds)
        ext_syn_tests = []
        for a, b in (
            ("ext_formulalm_q5_k_m", "ext_base_1_7b_0shot"),
            ("ext_formulalm_q5_k_m", "ext_base_1_7b_5shot"),
        ):
            if a in ext_syn_aligned and b in ext_syn_aligned:
                res = mcnemar_exact(ext_syn_aligned[a], ext_syn_aligned[b])
                res["system_a"] = a
                res["system_a_label"] = ext_labels[a]
                res["system_b"] = b
                res["system_b_label"] = ext_labels[b]
                ext_syn_tests.append(res)
        summary["splits"]["external_spreadsheetbench_syntax"] = {
            "n": len(next(iter(ext_syn_aligned.values()))),
            "systems": {
                k: {
                    "label": ext_labels[k],
                    "k": sum(v),
                    "n": len(v),
                    "execution_accuracy": round(sum(v) / len(v), 4),
                    "wilson_95_ci": list(wilson_ci(sum(v), len(v))),
                    "bootstrap_95_ci": list(bootstrap_ci(v)),
                }
                for k, v in ext_syn_aligned.items()
            },
            "paired_mcnemar": ext_syn_tests,
        }

    # --- 4. Quantization Q5_K_M vs Q4_K_M on val (N=500) & test_synthetic (N=500) ---
    for split_key, q4_rel, q5_rel in (
        (
            "quant_val_500",
            "results/quant_q4_k_m_val/predictions.jsonl",
            "results/quant_q5_k_m_val/predictions.jsonl",
        ),
        (
            "quant_synthetic_500",
            "results/quant_q4_k_m_synthetic/predictions.jsonl",
            "results/quant_q5_k_m_synthetic/predictions.jsonl",
        ),
    ):
        if (REPO_ROOT / q4_rel).is_file() and (REPO_ROOT / q5_rel).is_file():
            q_preds = {
                "colab_q4_k_m": _load_predictions(q4_rel),
                "colab_q5_k_m": _load_predictions(q5_rel),
            }
            q_labels = {
                "colab_q4_k_m": "FormulaLM Q4_K_M (Colab)",
                "colab_q5_k_m": "FormulaLM Q5_K_M (Colab)",
            }
            _, q_aligned = _align_outcomes(q_preds)
            q_res = mcnemar_exact(q_aligned["colab_q5_k_m"], q_aligned["colab_q4_k_m"])
            q_res["system_a"] = "colab_q5_k_m"
            q_res["system_a_label"] = q_labels["colab_q5_k_m"]
            q_res["system_b"] = "colab_q4_k_m"
            q_res["system_b_label"] = q_labels["colab_q4_k_m"]
            summary["splits"][split_key] = {
                "n": len(q_aligned["colab_q5_k_m"]),
                "systems": {
                    k: {
                        "label": q_labels[k],
                        "k": sum(v),
                        "n": len(v),
                        "execution_accuracy": round(sum(v) / len(v), 4),
                        "wilson_95_ci": list(wilson_ci(sum(v), len(v))),
                        "bootstrap_95_ci": list(bootstrap_ci(v)),
                    }
                    for k, v in q_aligned.items()
                },
                "paired_mcnemar": [q_res],
            }

    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Statistical Significance & Confidence Intervals",
        "",
        f"Computed from committed per-item `predictions.jsonl` logs "
        f"(bootstrap resamples = {summary['bootstrap_resamples']:,}, seed = {summary['seed']}, "
        "exact two-sided McNemar's test on paired binary execution accuracy).",
        "",
    ]
    for split_key, split_data in summary["splits"].items():
        lines.append(f"## `{split_key}` (N = {split_data['n']})")
        lines.append("")
        lines.append("| System | Correct | Accuracy | 95% Wilson CI | 95% Bootstrap CI |")
        lines.append("|---|---:|---:|---:|---:|")
        for s in split_data["systems"].values():
            w_lo, w_hi = s["wilson_95_ci"]
            b_lo, b_hi = s["bootstrap_95_ci"]
            lines.append(
                f"| {s['label']} | {s['k']}/{s['n']} | {s['execution_accuracy']*100:.1f}% | "
                f"[{w_lo*100:.1f}%, {w_hi*100:.1f}%] | [{b_lo*100:.1f}%, {b_hi*100:.1f}%] |"
            )
        lines.append("")
        if split_data["paired_mcnemar"]:
            lines.append("### Paired Exact McNemar's Tests")
            lines.append("")
            lines.append(
                "| System A vs System B | Delta | A-only / B-only | Exact p-value "
                "| Significant (p<0.05) |"
            )
            lines.append("|---|---:|---:|---:|---|")
            for t in split_data["paired_mcnemar"]:
                sig = "Yes" if t["significant_0_05"] else "No"
                sign = "+" if t["delta_pp"] >= 0 else ""
                lines.append(
                    f"| {t['system_a_label']} vs {t['system_b_label']} | "
                    f"{sign}{t['delta_pp']:.1f} pp | {t['a_only']} / {t['b_only']} | "
                    f"`p = {_format_p(t['p_value'])}` | {sig} |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    summary = compute_all_stats()
    out_json = REPO_ROOT / "results" / "stats_summary.json"
    out_md = REPO_ROOT / "results" / "stats_summary.md"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(summary), encoding="utf-8")
    print(f"Wrote {out_json.relative_to(REPO_ROOT)} and {out_md.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
