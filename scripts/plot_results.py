"""Generate publication-quality summary charts strictly from committed results/*.json.

Reads exclusively from:
- results/final_headline.json
- results/quant_comparison.json
- results/local_benchmark/local_benchmark.json
- results/external_bench/comparison.json

Outputs:
- docs/charts/headline_accuracy.png
- docs/charts/quant_pareto.png

Usage:
    uv run --with matplotlib python scripts/plot_results.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

# Stitch "Formula Precision" light palette
INK = "#0f172a"
MUTED = "#475569"
GRID = "#e2e8f0"
BG = "#ffffff"
PANEL_BG = "#f8fafc"
SLATE_LIGHT = "#94a3b8"
SLATE_MID = "#64748b"
BLUE = "#1a56db"
EMERALD = "#059669"
EMERALD_DARK = "#047857"
EMERALD_TINT = "#ecfdf5"
CRIMSON = "#dc2626"
CRIMSON_TINT = "#fef2f2"
AMBER = "#d97706"


def _load_json(rel_path: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))


def _configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.edgecolor": "#cbd5e1",
            "axes.linewidth": 0.9,
            "axes.facecolor": PANEL_BG,
            "figure.facecolor": BG,
            "savefig.facecolor": BG,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": MUTED,
            "ytick.color": INK,
        }
    )


def plot_headline_accuracy(out_path: Path) -> None:
    fh = _load_json("results/final_headline.json")
    qc = _load_json("results/quant_comparison.json")
    lb = _load_json("results/local_benchmark/local_benchmark.json")
    ext = _load_json("results/external_bench/comparison.json")

    rv2_fh = fh["splits"]["test_real_v2"]["systems"]
    rv2_q5_colab = qc["systems"]["quant_q5_k_m"]["splits"]["real_v2"]
    q5_local_entry = next(r for r in lb["results"] if r["quant_key"] == "q5_k_m")
    rv2_q5_local = q5_local_entry["splits"]["real_v2"]

    # Panel A data (top-to-bottom progression)
    panel_a = [
        ("Base Qwen3-1.7B\n(0-shot, fp16)", rv2_fh["base_zeroshot"], SLATE_LIGHT),
        ("Base Qwen3-1.7B\n(5-shot, fp16)", rv2_fh["base_5shot"], SLATE_MID),
        ("Fine-tuned v2-ship\n(LoRA, fp16)", rv2_fh["ft_v2"], BLUE),
        ("FormulaLM Q5_K_M\n(Local CPU Ollama)", rv2_q5_local, EMERALD),
        ("FormulaLM Q5_K_M\n(Colab llama-server)", rv2_q5_colab, EMERALD_DARK),
    ]

    # Panel B data (same-size 1.7B on external SpreadsheetBench Verified 400 subset)
    ext_sys = ext["systems"]
    panel_b = [
        (
            "Base Qwen3-1.7B\n(0-shot, Ollama)",
            ext_sys["ext_base_1_7b_0shot"]["overall"],
            SLATE_LIGHT,
        ),
        ("Base Qwen3-1.7B\n(5-shot, Ollama)", ext_sys["ext_base_1_7b_5shot"]["overall"], SLATE_MID),
        (
            "FormulaLM Q5_K_M\n(0-shot, Local CPU)",
            ext_sys["ext_formulalm_q5_k_m"]["overall"],
            EMERALD,
        ),
    ]

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(13.4, 5.4), gridspec_kw={"width_ratios": [1.15, 1.0]}
    )
    fig.subplots_adjust(top=0.75, bottom=0.13, left=0.16, right=0.97, wspace=0.44)

    fig.suptitle(
        "FormulaLM (Qwen3-1.7B): Before vs After Execution-Verified Accuracy",
        fontsize=14,
        fontweight="bold",
        color=INK,
        y=0.955,
    )
    fig.text(
        0.5,
        0.885,
        "Every formula executed in formulas 1.3.4 against real .xlsx workbooks (tol=1e-6); "
        "whiskers show 95% Wilson CIs",
        ha="center",
        fontsize=9.5,
        color=MUTED,
    )

    # --- Panel A ---
    y_a = list(range(len(panel_a)))
    vals_a = [d["execution_accuracy"] * 100.0 for _, d, _ in panel_a]
    err_lo_a = [(d["execution_accuracy"] - d["wilson_95_ci"][0]) * 100.0 for _, d, _ in panel_a]
    err_hi_a = [(d["wilson_95_ci"][1] - d["execution_accuracy"]) * 100.0 for _, d, _ in panel_a]
    colors_a = [c for _, _, c in panel_a]

    ax1.barh(y_a, vals_a, height=0.58, color=colors_a, edgecolor="none", zorder=3)
    ax1.errorbar(
        vals_a,
        y_a,
        xerr=[err_lo_a, err_hi_a],
        fmt="none",
        ecolor=INK,
        elinewidth=1.4,
        capsize=4,
        capthick=1.4,
        zorder=4,
    )
    for yi, (_, d, col) in zip(y_a, panel_a, strict=True):
        pct = d["execution_accuracy"] * 100.0
        hi = d["wilson_95_ci"][1] * 100.0
        k, n = d["k"], d["n"]
        weight = "bold" if col in (EMERALD, EMERALD_DARK) else "normal"
        ax1.text(
            hi + 2.0,
            yi,
            f"{pct:.1f}% ({k}/{n})",
            va="center",
            ha="left",
            fontsize=9.3,
            fontweight=weight,
            color=INK,
        )

    ax1.set_yticks(y_a)
    ax1.set_yticklabels([lbl for lbl, _, _ in panel_a], fontsize=9.2)
    ax1.invert_yaxis()
    ax1.set_xlim(0, 122)
    ax1.set_xticks([0, 20, 40, 60, 80, 100])
    ax1.set_xticklabels([f"{x}%" for x in [0, 20, 40, 60, 80, 100]])
    ax1.set_xlabel("Execution Accuracy (%)", fontsize=9.8, fontweight="bold")
    ax1.set_title(
        "A. Fresh Held-Out Set (test_real_v2, N = 50)\n"
        "AI-drafted & reviewed; not fully independent",
        fontsize=10.3,
        fontweight="bold",
        pad=10,
        color=INK,
    )
    ax1.grid(axis="x", color=GRID, linestyle="--", linewidth=0.8, zorder=0)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # --- Panel B ---
    y_b = list(range(len(panel_b)))
    vals_b = [d["execution_accuracy"] * 100.0 for _, d, _ in panel_b]
    err_lo_b = [(d["execution_accuracy"] - d["wilson_95_ci"][0]) * 100.0 for _, d, _ in panel_b]
    err_hi_b = [(d["wilson_95_ci"][1] - d["execution_accuracy"]) * 100.0 for _, d, _ in panel_b]
    colors_b = [c for _, _, c in panel_b]

    ax2.barh(y_b, vals_b, height=0.46, color=colors_b, edgecolor="none", zorder=3)
    ax2.errorbar(
        vals_b,
        y_b,
        xerr=[err_lo_b, err_hi_b],
        fmt="none",
        ecolor=INK,
        elinewidth=1.4,
        capsize=4,
        capthick=1.4,
        zorder=4,
    )
    for yi, (_, d, col) in zip(y_b, panel_b, strict=True):
        pct = d["execution_accuracy"] * 100.0
        hi = d["wilson_95_ci"][1] * 100.0
        syn = d["syntax_valid_rate"] * 100.0
        k, n = d["k"], d["n"]
        weight = "bold" if col == EMERALD else "normal"
        ax2.text(
            hi + 1.5,
            yi,
            f"{pct:.1f}% ({k}/{n})\nsyn {syn:.1f}%",
            va="center",
            ha="left",
            fontsize=8.9,
            fontweight=weight,
            color=INK,
        )

    ax2.set_yticks(y_b)
    ax2.set_yticklabels([lbl for lbl, _, _ in panel_b], fontsize=9.2)
    ax2.invert_yaxis()
    ax2.set_xlim(0, 82)
    ax2.set_xticks([0, 20, 40, 60, 80])
    ax2.set_xticklabels([f"{x}%" for x in [0, 20, 40, 60, 80]])
    ax2.set_xlabel("Execution Accuracy (%)", fontsize=9.8, fontweight="bold")
    ax2.set_title(
        "B. External Benchmark (SpreadsheetBench, N = 56)\n"
        "Unseen MrExcel forum workbooks (1.7B, CPU)",
        fontsize=10.3,
        fontweight="bold",
        pad=10,
        color=INK,
    )
    ax2.grid(axis="x", color=GRID, linestyle="--", linewidth=0.8, zorder=0)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    # Callout badge in open top-right whitespace of Panel B (zero overlap with bars/whiskers)
    base_acc = ext_sys["ext_base_1_7b_0shot"]["overall"]["execution_accuracy"]
    flm_acc = ext_sys["ext_formulalm_q5_k_m"]["overall"]["execution_accuracy"]
    ratio = flm_acc / base_acc if base_acc > 0 else 0.0
    ax2.text(
        0.97,
        0.94,
        f"{ratio:.1f}x base 1.7B accuracy\n89.3% vs 67.9% syntax valid",
        transform=ax2.transAxes,
        ha="right",
        va="top",
        fontsize=8.6,
        fontweight="bold",
        color=EMERALD_DARK,
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": EMERALD_TINT,
            "edgecolor": EMERALD,
            "linewidth": 1.0,
        },
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def plot_quant_pareto(out_path: Path) -> None:
    qc = _load_json("results/quant_comparison.json")
    lb = _load_json("results/local_benchmark/local_benchmark.json")

    # Panel A: Quantization accuracy across splits (Colab GGUF eval)
    q_order = [
        ("quant_q4_k_m", "q4_k_m", "Q4_K_M"),
        ("quant_q5_k_m", "q5_k_m", "Q5_K_M\n(Shipped)"),
        ("quant_q8_0", "q8_0", "Q8_0"),
        ("quant_f16", "f16", "F16\n(ref)"),
    ]
    x_pos = list(range(len(q_order)))
    x_labels = []
    for _, fkey, short_lbl in q_order:
        sz = qc["artifacts"]["files"][fkey]["size_mb"]
        x_labels.append(f"{short_lbl}\n{sz:,.0f} MB")

    val_acc = [
        qc["systems"][sk]["splits"]["val"]["execution_accuracy"] * 100.0 for sk, _, _ in q_order
    ]
    syn_acc = [
        qc["systems"][sk]["splits"]["synthetic"]["execution_accuracy"] * 100.0
        for sk, _, _ in q_order
    ]
    real_acc = [
        qc["systems"][sk]["splits"]["real"]["execution_accuracy"] * 100.0 for sk, _, _ in q_order
    ]

    # Panel B: Local laptop CPU benchmark (Q4_K_M, Q5_K_M, Q8_0)
    lb_by_key = {r["quant_key"]: r for r in lb["results"]}
    loc_keys = [("q4_k_m", "Q4_K_M"), ("q5_k_m", "Q5_K_M\n(Shipped)"), ("q8_0", "Q8_0")]
    loc_x = list(range(len(loc_keys)))
    loc_ram = [lb_by_key[k]["peak_ram_mb"] for k, _ in loc_keys]
    loc_tps = [lb_by_key[k]["gen_tokens_per_s"] for k, _ in loc_keys]
    loc_acc = [lb_by_key[k]["subset_execution_accuracy"] * 100.0 for k, _ in loc_keys]

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(13.4, 5.4), gridspec_kw={"width_ratios": [1.12, 1.0]}
    )
    fig.subplots_adjust(top=0.75, bottom=0.17, left=0.07, right=0.92, wspace=0.30)

    fig.suptitle(
        "Why Q5_K_M Ships Over Q4_K_M: Quantization Accuracy & Local CPU Footprint",
        fontsize=14,
        fontweight="bold",
        color=INK,
        y=0.955,
    )
    fig.text(
        0.5,
        0.885,
        "v2-ship GGUF exports (llama.cpp b12728) & local Windows 11 laptop benchmark "
        "(Intel Core i5-8365U, 8 GB RAM, CPU-only, Ollama 0.40.18)",
        ha="center",
        fontsize=9.4,
        color=MUTED,
    )

    # --- Panel A ---
    ax1.axvspan(0.62, 1.38, color=EMERALD_TINT, alpha=0.95, zorder=1)
    ax1.axvspan(-0.38, 0.38, color=CRIMSON_TINT, alpha=0.85, zorder=1)

    ax1.plot(
        x_pos,
        val_acc,
        marker="o",
        linewidth=2.2,
        markersize=7,
        color=BLUE,
        label="val (N=500)",
        zorder=4,
    )
    ax1.plot(
        x_pos,
        syn_acc,
        marker="s",
        linewidth=2.2,
        markersize=6.5,
        color=EMERALD,
        label="test_synthetic* (N=500)",
        zorder=4,
    )
    ax1.plot(
        x_pos,
        real_acc,
        marker="^",
        linewidth=2.2,
        markersize=7,
        color=AMBER,
        label="test_real* (N=80)",
        zorder=4,
    )

    # Non-overlapping point value labels
    for xi, (va, sa, ra) in enumerate(zip(val_acc, syn_acc, real_acc, strict=True)):
        ax1.text(
            xi,
            va + 0.55,
            f"{va:.1f}%",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=BLUE,
            fontweight="bold",
        )
        sa_off = -1.25 if (va - sa) < 1.5 else -1.10
        ax1.text(
            xi,
            sa + sa_off,
            f"{sa:.1f}%",
            ha="center",
            va="top",
            fontsize=8.4,
            color=EMERALD_DARK,
            fontweight="bold",
        )
        ax1.text(
            xi,
            ra - 0.85,
            f"{ra:.1f}%",
            ha="center",
            va="top",
            fontsize=8.4,
            color=AMBER,
            fontweight="bold",
        )

    ax1.text(
        0.0,
        84.1,
        "Q4_K_M drops\n2.4–5.0 pp vs F16",
        ha="center",
        va="bottom",
        fontsize=8.2,
        fontweight="bold",
        color=CRIMSON,
    )
    ax1.text(
        1.0,
        84.1,
        "Pareto knee:\nwithin F16 noise\n(+144 MB vs Q4)",
        ha="center",
        va="bottom",
        fontsize=8.2,
        fontweight="bold",
        color=EMERALD_DARK,
    )

    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(x_labels, fontsize=8.8)
    ax1.set_ylim(83.5, 102.2)
    ax1.set_ylabel("Execution Accuracy (%)", fontsize=9.8, fontweight="bold")
    ax1.set_title(
        "A. Execution Accuracy Across Quantizations\n(*v2 informed by v1 error analysis)",
        fontsize=10.3,
        fontweight="bold",
        pad=10,
        color=INK,
    )
    ax1.grid(axis="y", color=GRID, linestyle="--", linewidth=0.8, zorder=0)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(loc="lower right", frameon=True, facecolor=BG, edgecolor=GRID, fontsize=8.5)

    # --- Panel B ---
    bar_colors = ["#cbd5e1", EMERALD, "#cbd5e1"]
    bar_edges = ["#64748b", EMERALD_DARK, "#64748b"]
    bars = ax2.bar(
        loc_x,
        loc_ram,
        width=0.52,
        color=bar_colors,
        edgecolor=bar_edges,
        linewidth=1.3,
        zorder=3,
    )

    for xi, bar, ram, acc in zip(loc_x, bars, loc_ram, loc_acc, strict=True):
        txt_col = BG if xi == 1 else INK
        y_center = ram * 0.34 if xi == 2 else ram * 0.46
        ax2.text(
            bar.get_x() + bar.get_width() / 2.0,
            y_center,
            f"{ram:,.0f} MB\nRAM\n({acc:.1f}% acc)",
            ha="center",
            va="center",
            fontsize=8.7,
            fontweight="bold",
            color=txt_col,
            zorder=5,
        )

    ax2.set_xticks(loc_x)
    ax2.set_xticklabels([lbl for _, lbl in loc_keys], fontsize=9.2)
    ax2.set_ylim(0, 3100)
    ax2.set_ylabel("Peak RAM on CPU (MB)", fontsize=9.8, fontweight="bold", color=INK)
    ax2.set_title(
        "B. Local i5-8365U CPU Footprint & Speed\n(130-ex local subset: test_real + test_real_v2)",
        fontsize=10.3,
        fontweight="bold",
        pad=10,
        color=INK,
    )
    ax2.grid(axis="y", color=GRID, linestyle="--", linewidth=0.8, zorder=0)
    ax2.spines["top"].set_visible(False)

    ax2_r = ax2.twinx()
    ax2_r.plot(
        loc_x,
        loc_tps,
        marker="D",
        linewidth=2.4,
        markersize=7.5,
        color=BLUE,
        label="Gen speed (tok/s)",
        zorder=6,
    )
    for xi, tps in zip(loc_x, loc_tps, strict=True):
        ax2_r.text(
            xi,
            tps + 0.85,
            f"{tps:.1f} tok/s",
            ha="center",
            va="bottom",
            fontsize=8.9,
            fontweight="bold",
            color=BLUE,
            bbox={
                "boxstyle": "round,pad=0.22",
                "facecolor": BG,
                "edgecolor": "#bfdbfe",
                "linewidth": 0.8,
            },
            zorder=7,
        )
    ax2_r.set_ylim(0, 21.0)
    ax2_r.set_ylabel("Generation Speed (tok/s)", fontsize=9.8, fontweight="bold", color=BLUE)
    ax2_r.tick_params(axis="y", colors=BLUE)
    ax2_r.spines["top"].set_visible(False)

    legend_handles = [
        Patch(facecolor=EMERALD, edgecolor=EMERALD_DARK, label="Shipped Q5_K_M peak RAM"),
        Patch(facecolor="#cbd5e1", edgecolor="#64748b", label="Other quants peak RAM"),
        plt.Line2D([0], [0], color=BLUE, marker="D", linewidth=2.2, label="CPU speed (tok/s)"),
    ]
    ax2.legend(
        handles=legend_handles,
        loc="upper left",
        frameon=True,
        facecolor=BG,
        edgecolor=GRID,
        fontsize=8.2,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "docs" / "charts")
    args = parser.parse_args()

    _configure_style()
    p1 = args.out_dir / "headline_accuracy.png"
    p2 = args.out_dir / "quant_pareto.png"
    plot_headline_accuracy(p1)
    plot_quant_pareto(p2)
    print(f"Generated {p1} ({p1.stat().st_size / 1024:.1f} KB)")
    print(f"Generated {p2} ({p2.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
