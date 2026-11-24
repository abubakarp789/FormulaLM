"""Train-only v2 phrasing additions and new general templates (informed by v1 error analysis).

Zero-leakage design:
- Original ``src/data/templates.py`` phrasings are kept 100% unchanged so ``val.jsonl``
  and ``test_synthetic.jsonl`` remain bit-for-bit identical to v1 for fair comparison.
- All additions here are used EXCLUSIVELY when generating ``train_v2.jsonl`` on the
  20 training sheets — never on held-out test sheets or test phrasings.

Targeted clusters from v1 error analysis (results/ft_v1_comparison.md):
1. ``wrong_function``      : per-unit / rate wording, target comparison, numeric YEAR vs TEXT, MAX superlatives.
2. ``wrong_column``        : implicit-column requests (naming category values without repeating header names).
3. ``wrong_aggregation``   : unquoted multi-word category literals (preserving full prefixes) & rounded averages/ratios.
"""

from __future__ import annotations

import random
from typing import Any

import pandas as pd

from src.data.templates import (
    FormulaTemplate,
    SheetContext,
    _excel_round,
    _nonnull_indices,
)

# ---------------------------------------------------------------------------
# 1. Extra train-only phrasing patterns keyed by existing template_id
# ---------------------------------------------------------------------------

V2_TRAIN_EXTRA_PHRASINGS: dict[str, tuple[str, ...]] = {
    # --- Cluster 1: wrong_function ---
    "avg_ratio_two_sums": (
        "{m1} per unit of {m2} overall (return 0 on error)",
        "overall {m1} per {m2} ratio (sum {m1} / sum {m2}, 0 if error)",
        "total {m1} divided by total {m2}, returning 0 if division fails",
        "compute overall {m1}-to-{m2} ratio using SUM and IFERROR returning 0",
    ),
    "iferror_safe_division": (
        "{m1} per unit of {m2} on row {row} (return 0 if error)",
        "{m1} per {m2} in row {row}, 0 on error",
        "unit rate ({m1} / {m2}) for row {row} with 0 fallback",
        "row {row} {m1} per {m2} (0 if divide by zero)",
    ),
    "if_sumif_exceeds_target": (
        "say '{yes}' if total {value} {measure} beats {target}, else '{no}'",
        "did {value} hit a {measure} goal of {target}? return '{yes}' or '{no}'",
        "check if total {value} {measure} exceeds {target}: '{yes}' else '{no}'",
        "for {value}, if combined {measure} > {target} output '{yes}' otherwise '{no}'",
    ),
    "year_from_date": (
        "numeric 4-digit calendar year of {date_col} in row {row} using YEAR",
        "extract the 4-digit year integer (not text) from {date_col} row {row}",
        "return the numeric year for {date_col} on row {row}",
    ),
    "max_column": (
        "top {measure} in the sheet",
        "biggest {measure} value",
        "highest recorded {measure}",
        "what is the top value for {measure}?",
    ),
    "min_column": (
        "bottom {measure} value",
        "lowest recorded {measure}",
        "smallest {measure} in the table",
    ),
    # --- Cluster 2: wrong_column (implicit column headers + unquoted values) ---
    "sumif_category_eq": (
        "total {value} {measure}",
        "sum {measure} for {value}",
        "how much {measure} came from {value}?",
        "combined {measure} in {value}",
    ),
    "countif_category_eq": (
        "how many {value} rows are there?",
        "count {value} entries",
        "total count in {value}",
    ),
    "averageif_category_eq": (
        "avg {measure} for {value}",
        "mean {measure} in {value}",
        "average {value} {measure}",
    ),
    "sumifs_two_cats": (
        "total {measure} for {val1} in {val2}",
        "sum {measure} for {val1} entries that are {val2}",
        "how much {measure} for {val1} and {val2}?",
        "total {val1} {measure} in {val2}",
    ),
    "countifs_two_cats": (
        "how many {val1} entries are in {val2}?",
        "count {val1} rows that are {val2}",
        "how many {val1} in {val2}?",
    ),
    "sumifs_cat_and_num": (
        "total {measure} for {value} with {filter_col} > {thresh}",
        "sum {value} {measure} where {filter_col} exceeds {thresh}",
        "total {value} {measure} for rows with {filter_col} over {thresh}",
    ),
    "averageifs_cat_and_num": (
        "avg {measure} for {value} with {filter_col} >= {thresh}",
        "mean {value} {measure} when {filter_col} is at least {thresh}",
        "average {value} {measure} for {filter_col} >= {thresh}",
    ),
    "countifs_cat_and_date_after": (
        "how many {value} rows happened after {iso}?",
        "count {value} entries dated after {iso}",
        "how many {value} records after {iso}?",
    ),
    "sumifs_cat_and_date_after": (
        "total {value} {measure} on or after {iso}",
        "sum {value} {measure} from {iso} onward",
        "total {measure} for {value} starting {iso}",
    ),
    # --- Cluster 3: wrong_aggregation & argument precision ---
    "round_average_column": (
        "round avg {measure} to {digits} dec",
        "mean {measure} rounded to {digits} decimal places",
        "compute the rounded average of {measure} ({digits} decimals)",
    ),
    "concat_two_cells_sep": (
        "combine {col1} and {col2} on row {row} like '{col1}{sep}{col2}' using concat",
        "concatenate {col1} then '{sep}' then {col2} in row {row}",
    ),
    "textjoin_range_delim": (
        "join {col} rows {start_row} to {end_row} only with '{delim}', ignoring blanks",
        "textjoin {col} from row {start_row} through row {end_row} separated by '{delim}'",
    ),
}


# ---------------------------------------------------------------------------
# 2. Two new general train-only templates (rounded row ratio & rounded sum ratio)
# ---------------------------------------------------------------------------


def _build_iferror_round_row_ratio(ctx: SheetContext, rng: random.Random):
    c1, c2 = rng.sample(ctx.cols_of_kind("numeric"), 2)
    idx = rng.choice(_nonnull_indices(ctx.df, c1.name, c2.name))
    excel_row = idx + 2
    digits = rng.choice([1, 2])
    formula = (
        f"=IFERROR(ROUND({ctx.cell_ref(c1, excel_row)}/{ctx.cell_ref(c2, excel_row)},{digits}),0)"
    )
    return (
        formula,
        {"m1": c1.name, "m2": c2.name, "row": excel_row, "digits": digits},
        {"c1": c1.name, "c2": c2.name, "idx": idx, "digits": digits},
    )


def _gt_iferror_round_row_ratio(df: pd.DataFrame, p: dict[str, Any]) -> float:
    v1 = df.iloc[p["idx"]][p["c1"]]
    v2 = df.iloc[p["idx"]][p["c2"]]
    if pd.isna(v1) or pd.isna(v2) or float(v2) == 0.0:
        return 0.0
    return _excel_round(float(v1) / float(v2), p["digits"])


def _build_iferror_round_sum_ratio(ctx: SheetContext, rng: random.Random):
    c1, c2 = rng.sample(ctx.cols_of_kind("numeric"), 2)
    digits = rng.choice([2, 4])
    formula = f"=IFERROR(ROUND(SUM({ctx.col_range(c1)})/SUM({ctx.col_range(c2)}),{digits}),0)"
    return (
        formula,
        {"m1": c1.name, "m2": c2.name, "digits": digits},
        {"c1": c1.name, "c2": c2.name, "digits": digits},
    )


def _gt_iferror_round_sum_ratio(df: pd.DataFrame, p: dict[str, Any]) -> float:
    denom = float(df[p["c2"]].dropna().sum())
    if denom == 0.0:
        return 0.0
    return _excel_round(float(df[p["c1"]].dropna().sum()) / denom, p["digits"])


V2_TRAIN_ONLY_TEMPLATES: tuple[FormulaTemplate, ...] = (
    FormulaTemplate(
        id="v2_iferror_round_row_ratio",
        category="math_and_composition",
        difficulty=2,
        functions=("IFERROR", "ROUND"),
        required_column_types={"numeric": 2},
        builder=_build_iferror_round_row_ratio,
        pandas_gt=_gt_iferror_round_row_ratio,
        phrasings=(
            "{m1} per unit of {m2} on row {row}, rounded to {digits} dec (0 on error)",
            "In row {row}, divide {m1} by {m2}, round to {digits} decimal place(s), and return 0 on error.",
            "row {row}: iferror(round({m1} / {m2}, {digits}), 0)",
            "Compute row {row}'s {m1} per {m2} rounded to {digits} decimal(s), defaulting to 0 if division fails.",
            "What is {m1} per {m2} on row {row} rounded to {digits} decimal(s) (0 if error)?",
            "Safely calculate rounded {m1} / {m2} ({digits} decimals) on row {row}, returning 0 on error.",
        ),
    ),
    FormulaTemplate(
        id="v2_iferror_round_sum_ratio",
        category="math_and_composition",
        difficulty=3,
        functions=("IFERROR", "ROUND", "SUM"),
        required_column_types={"numeric": 2},
        builder=_build_iferror_round_sum_ratio,
        pandas_gt=_gt_iferror_round_sum_ratio,
        phrasings=(
            "overall {m1} per unit of {m2}, rounded to {digits} dec (0 on error)",
            "Compute total {m1} divided by total {m2}, rounded to {digits} decimal place(s), returning 0 on error.",
            "iferror(round(sum {m1} / sum {m2}, {digits}), 0)",
            "What is the overall ratio of sum {m1} to sum {m2}, rounded to {digits} decimal(s) (fallback 0)?",
            "Divide grand total {m1} by grand total {m2}, round to {digits} decimal(s), wrapped in IFERROR(..., 0).",
            "Safely compute total {m1} per total {m2} rounded to {digits} decimal place(s), or 0 if error.",
        ),
    ),
)
