"""Hand-written Excel formula templates with paired pandas ground-truth evaluators.

Each template covers part of the 36-function FormulaLM scope (no volatile functions) and defines:
- ``id``, ``category``, ``difficulty`` (1=easy, 2=medium, 3=hard), ``functions``
- ``required_column_types`` (semantic column counts needed from a sheet)
- ``builder(ctx, rng)`` -> ``(formula, slots, params)`` using real column letters and values
- ``pandas_gt(df, params)`` -> independently computes the expected answer via pandas
- 6 to 10 hand-written natural-language ``phrasings`` (formal, casual, terse, verbose)
- ``excel_quirk``: optional note flagging where Excel and Python ``formulas`` could disagree.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from formulalm.config import REPO_ROOT

Difficulty = Literal[1, 2, 3]


# ---------------------------------------------------------------------------
# Sheet context wrapper (reads manifest metadata + CSV/XLSX DataFrame)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnInfo:
    """Metadata for one column of a synthetic sheet."""

    letter: str
    name: str
    col_type: str
    index: int  # 1-based column index (A=1, B=2, ...)
    nullable: bool
    unique: bool
    null_count: int
    categories: tuple[str, ...] = ()


@dataclass
class SheetContext:
    """Loaded synthetic sheet ready for template instantiation and pandas ground truth."""

    sheet_id: str
    domain: str
    split: str
    num_rows: int
    csv_path: Path
    xlsx_path: Path
    columns: tuple[ColumnInfo, ...]
    df: pd.DataFrame

    @property
    def last_row(self) -> int:
        """Last 1-based Excel row index containing data (row 1 is header)."""
        return self.num_rows + 1

    def col_range(self, col: ColumnInfo, start_row: int = 2, end_row: int | None = None) -> str:
        end = self.last_row if end_row is None else end_row
        return f"{col.letter}{start_row}:{col.letter}{end}"

    def cell_ref(self, col: ColumnInfo, excel_row: int) -> str:
        return f"{col.letter}{excel_row}"

    def cols_of_kind(self, kind: str) -> list[ColumnInfo]:
        if kind == "key":
            return [c for c in self.columns if c.unique and not c.nullable]
        if kind == "numeric":
            return [c for c in self.columns if c.col_type in ("integer", "decimal")]
        if kind == "integer":
            return [c for c in self.columns if c.col_type == "integer"]
        if kind == "decimal":
            return [c for c in self.columns if c.col_type == "decimal"]
        if kind == "category":
            return [c for c in self.columns if c.col_type == "category"]
        if kind == "date":
            return [c for c in self.columns if c.col_type == "date"]
        if kind == "text":
            return [c for c in self.columns if c.col_type == "text"]
        if kind == "text_nonkey":
            return [c for c in self.columns if c.col_type == "text" and not c.unique]
        if kind == "nullable":
            return [c for c in self.columns if c.nullable and c.null_count > 0]
        if kind == "non_key":
            return [c for c in self.columns if not c.unique]
        raise ValueError(f"Unknown column kind: {kind!r}")


def load_sheet_contexts(
    manifest_path: str | Path | None = None,
    *,
    split: Literal["all", "train", "test"] = "all",
) -> list[SheetContext]:
    """Load synthetic sheets from ``data/sheets/manifest.json`` into ``SheetContext`` objects."""
    mpath = (
        REPO_ROOT / "data" / "sheets" / "manifest.json"
        if manifest_path is None
        else Path(manifest_path)
    )
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    contexts: list[SheetContext] = []

    for entry in manifest["sheets"]:
        if split != "all" and entry["split"] != split:
            continue
        csv_path = REPO_ROOT / entry["csv_path"]
        xlsx_path = REPO_ROOT / entry["xlsx_path"]
        df = pd.read_csv(csv_path, keep_default_na=True)
        cols: list[ColumnInfo] = []
        for idx, c in enumerate(entry["columns"], start=1):
            if c["type"] == "date":
                df[c["name"]] = pd.to_datetime(df[c["name"]], format="%Y-%m-%d").dt.date
            cols.append(
                ColumnInfo(
                    letter=c["letter"],
                    name=c["name"],
                    col_type=c["type"],
                    index=idx,
                    nullable=c["nullable"],
                    unique=c["unique"],
                    null_count=c["null_count"],
                    categories=tuple(c.get("categories", ())),
                )
            )
        contexts.append(
            SheetContext(
                sheet_id=entry["sheet_id"],
                domain=entry["domain"],
                split=entry["split"],
                num_rows=entry["num_rows"],
                csv_path=csv_path,
                xlsx_path=xlsx_path,
                columns=tuple(cols),
                df=df,
            )
        )
    return contexts


# ---------------------------------------------------------------------------
# Excel-faithful helpers for pandas ground truth
# ---------------------------------------------------------------------------


def _excel_round(value: float, digits: int = 0) -> float:
    """Round half away from zero (matching Excel's ROUND, unlike Python's banker's round)."""
    dec = Decimal(str(float(value)))
    if digits >= 0:
        quant = Decimal("1") if digits == 0 else Decimal(f"1e-{digits}")
        rounded = dec.quantize(quant, rounding=ROUND_HALF_UP)
        return float(rounded)
    factor = Decimal(10) ** (-digits)
    rounded = (dec / factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * factor
    return float(rounded)


def _excel_proper(text: str) -> str:
    """Capitalize the first letter of each alphabetic run (matching Excel PROPER)."""
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), text)


def _excel_trim(text: str) -> str:
    """Strip leading/trailing spaces and collapse runs of internal spaces (Excel TRIM)."""
    return " ".join(text.split())


def _nonnull_indices(df: pd.DataFrame, *col_names: str) -> list[int]:
    mask = pd.Series(True, index=df.index)
    for name in col_names:
        mask &= df[name].notna()
    return df.index[mask].tolist()


def _pick_threshold(series: pd.Series, rng: random.Random, *, is_int: bool) -> int | float:
    clean = series.dropna()
    q_lo, q_hi = float(clean.quantile(0.25)), float(clean.quantile(0.75))
    raw = rng.uniform(q_lo, q_hi) if q_hi > q_lo else float(clean.median())
    if is_int:
        return int(round(raw))
    return round(raw, 1)


def _pick_two_tiers(series: pd.Series, *, is_int: bool) -> tuple[int | float, int | float]:
    clean = series.dropna()
    q_mid, q_high = float(clean.quantile(0.35)), float(clean.quantile(0.70))
    if is_int:
        t_mid = int(round(q_mid))
        t_high = max(t_mid + 1, int(round(q_high)))
        return t_mid, t_high
    t_mid = round(q_mid, 1)
    t_high = round(max(t_mid + 0.5, q_high), 1)
    return t_mid, t_high


def _pick_cutoff_date(series: pd.Series, rng: random.Random) -> date:
    clean = sorted(d for d in series.dropna() if isinstance(d, date))
    lo = max(0, len(clean) // 4)
    hi = max(lo, (3 * len(clean)) // 4)
    return clean[rng.randint(lo, hi)]


def _fmt_num(val: int | float) -> str:
    if isinstance(val, int) or float(val).is_integer():
        return str(int(val))
    return str(val)


# ---------------------------------------------------------------------------
# Template core data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuiltTemplate:
    """One concrete instantiated example from a ``FormulaTemplate`` and ``SheetContext``."""

    template_id: str
    category: str
    difficulty: Difficulty
    functions: tuple[str, ...]
    sheet_id: str
    formula: str
    expected: Any
    request: str
    phrasing_idx: int
    slots: dict[str, Any]
    params: dict[str, Any]


BuilderFn = Callable[[SheetContext, random.Random], tuple[str, dict[str, Any], dict[str, Any]]]
PandasGtFn = Callable[[pd.DataFrame, dict[str, Any]], Any]


@dataclass(frozen=True)
class FormulaTemplate:
    """Reusable Excel formula template with builder, pandas ground truth and NL phrasings."""

    id: str
    category: str
    difficulty: Difficulty
    functions: tuple[str, ...]
    required_column_types: dict[str, int]
    phrasings: tuple[str, ...]
    builder: BuilderFn
    pandas_gt: PandasGtFn
    excel_quirk: str | None = None

    def matches_sheet(self, ctx: SheetContext) -> bool:
        for kind, needed in self.required_column_types.items():
            if len(ctx.cols_of_kind(kind)) < needed:
                return False
        return True

    def instantiate(
        self,
        ctx: SheetContext,
        rng: random.Random,
        *,
        phrasing_idx: int | None = None,
    ) -> BuiltTemplate:
        formula, slots, params = self.builder(ctx, rng)
        expected = self.pandas_gt(ctx.df, params)
        idx = rng.randrange(len(self.phrasings)) if phrasing_idx is None else phrasing_idx
        request = self.phrasings[idx].format(**slots)
        return BuiltTemplate(
            template_id=self.id,
            category=self.category,
            difficulty=self.difficulty,
            functions=self.functions,
            sheet_id=ctx.sheet_id,
            formula=formula,
            expected=expected,
            request=request,
            phrasing_idx=idx,
            slots=slots,
            params=params,
        )


# ---------------------------------------------------------------------------
# Builders & pandas ground-truth functions (60 templates across 7 categories)
# ---------------------------------------------------------------------------

# --- Category 1: aggregation (8 templates) ---


def _build_single_numeric_agg(fn_name: str) -> BuilderFn:
    def _build(ctx: SheetContext, rng: random.Random):
        col = rng.choice(ctx.cols_of_kind("numeric"))
        formula = f"={fn_name}({ctx.col_range(col)})"
        slots = {"measure": col.name}
        params = {"col": col.name}
        return formula, slots, params

    return _build


def _gt_sum(df: pd.DataFrame, p: dict[str, Any]) -> float:
    return float(df[p["col"]].dropna().sum())


def _gt_avg(df: pd.DataFrame, p: dict[str, Any]) -> float:
    return float(df[p["col"]].dropna().mean())


def _gt_min(df: pd.DataFrame, p: dict[str, Any]) -> float:
    return float(df[p["col"]].dropna().min())


def _gt_max(df: pd.DataFrame, p: dict[str, Any]) -> float:
    return float(df[p["col"]].dropna().max())


def _gt_count_num(df: pd.DataFrame, p: dict[str, Any]) -> int:
    return int(df[p["col"]].notna().sum())


def _build_range_spread(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("numeric"))
    r = ctx.col_range(col)
    return f"=MAX({r})-MIN({r})", {"measure": col.name}, {"col": col.name}


def _gt_range_spread(df: pd.DataFrame, p: dict[str, Any]) -> float:
    s = df[p["col"]].dropna()
    return float(s.max() - s.min())


def _build_sum_two_cols(ctx: SheetContext, rng: random.Random):
    c1, c2 = rng.sample(ctx.cols_of_kind("numeric"), 2)
    formula = f"=SUM({ctx.col_range(c1)})+SUM({ctx.col_range(c2)})"
    return formula, {"m1": c1.name, "m2": c2.name}, {"c1": c1.name, "c2": c2.name}


def _gt_sum_two_cols(df: pd.DataFrame, p: dict[str, Any]) -> float:
    return float(df[p["c1"]].dropna().sum() + df[p["c2"]].dropna().sum())


def _build_ratio_two_sums(ctx: SheetContext, rng: random.Random):
    c1, c2 = rng.sample(ctx.cols_of_kind("numeric"), 2)
    formula = f"=IFERROR(SUM({ctx.col_range(c1)})/SUM({ctx.col_range(c2)}),0)"
    return formula, {"m1": c1.name, "m2": c2.name}, {"c1": c1.name, "c2": c2.name}


def _gt_ratio_two_sums(df: pd.DataFrame, p: dict[str, Any]) -> float:
    denom = float(df[p["c2"]].dropna().sum())
    if denom == 0.0:
        return 0.0
    return float(df[p["c1"]].dropna().sum()) / denom


# --- Category 2: conditional_aggregation (12 templates) ---


def _pick_cat_with_nonnull_measure(
    ctx: SheetContext, cat_col: ColumnInfo, num_col: ColumnInfo, rng: random.Random
) -> str:
    valid_cats = [
        val
        for val in cat_col.categories
        if ctx.df.loc[ctx.df[cat_col.name] == val, num_col.name].notna().any()
    ]
    return rng.choice(valid_cats or list(cat_col.categories))


def _build_cat_agg(fn_name: str) -> BuilderFn:
    def _build(ctx: SheetContext, rng: random.Random):
        cat = rng.choice(ctx.cols_of_kind("category"))
        num = rng.choice(ctx.cols_of_kind("numeric"))
        val = _pick_cat_with_nonnull_measure(ctx, cat, num, rng)
        formula = f'={fn_name}({ctx.col_range(cat)},"{val}",{ctx.col_range(num)})'
        return (
            formula,
            {"measure": num.name, "dim": cat.name, "value": val},
            {"cat": cat.name, "val": val, "num": num.name},
        )

    return _build


def _gt_sumif_cat(df: pd.DataFrame, p: dict[str, Any]) -> float:
    mask = df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()
    return float(df.loc[mask, p["num"]].dropna().sum())


def _gt_avgif_cat(df: pd.DataFrame, p: dict[str, Any]) -> float:
    mask = df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()
    return float(df.loc[mask, p["num"]].dropna().mean())


def _build_countif_cat(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    val = rng.choice(cat.categories)
    formula = f'=COUNTIF({ctx.col_range(cat)},"{val}")'
    return formula, {"dim": cat.name, "value": val}, {"cat": cat.name, "val": val}


def _gt_countif_cat(df: pd.DataFrame, p: dict[str, Any]) -> int:
    mask = df[p["cat"]].dropna().astype(str).str.lower() == str(p["val"]).lower()
    return int(mask.sum())


def _build_countif_cat_neq(ctx: SheetContext, rng: random.Random):
    cats = [c for c in ctx.cols_of_kind("category") if c.null_count == 0] or ctx.cols_of_kind(
        "category"
    )
    cat = rng.choice(cats)
    val = rng.choice(cat.categories)
    formula = f'=COUNTIF({ctx.col_range(cat)},"<>{val}")'
    return formula, {"dim": cat.name, "value": val}, {"cat": cat.name, "val": val}


def _gt_countif_cat_neq(df: pd.DataFrame, p: dict[str, Any]) -> int:
    s = df[p["cat"]].dropna().astype(str).str.lower()
    return int((s != str(p["val"]).lower()).sum())


def _build_countif_wildcard(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    val = rng.choice(cat.categories)
    prefix = val[: min(3, max(1, len(val) - 1))]
    formula = f'=COUNTIF({ctx.col_range(cat)},"{prefix}*")'
    return formula, {"dim": cat.name, "prefix": prefix}, {"cat": cat.name, "prefix": prefix}


def _gt_countif_wildcard(df: pd.DataFrame, p: dict[str, Any]) -> int:
    s = df[p["cat"]].dropna().astype(str).str.lower()
    return int(s.str.startswith(str(p["prefix"]).lower()).sum())


def _build_num_cond(fn_name: str, op: str) -> BuilderFn:
    def _build(ctx: SheetContext, rng: random.Random):
        num = rng.choice(ctx.cols_of_kind("numeric"))
        thresh = _pick_threshold(ctx.df[num.name], rng, is_int=(num.col_type == "integer"))
        t_str = _fmt_num(thresh)
        formula = f'={fn_name}({ctx.col_range(num)},"{op}{t_str}")'
        return formula, {"measure": num.name, "thresh": t_str}, {"num": num.name, "thresh": thresh}

    return _build


def _gt_sumif_gt(df: pd.DataFrame, p: dict[str, Any]) -> float:
    s = df[p["num"]].dropna()
    return float(s[s > p["thresh"]].sum())


def _gt_countif_gte(df: pd.DataFrame, p: dict[str, Any]) -> int:
    s = df[p["num"]].dropna()
    return int((s >= p["thresh"]).sum())


def _gt_avgif_gt(df: pd.DataFrame, p: dict[str, Any]) -> float:
    s = df[p["num"]].dropna()
    return float(s[s > p["thresh"]].mean())


def _build_sumifs_cat_num(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    nums = ctx.cols_of_kind("numeric")
    m1 = rng.choice(nums)
    m2 = rng.choice([c for c in nums if c.name != m1.name] or nums)
    val = _pick_cat_with_nonnull_measure(ctx, cat, m1, rng)
    thresh = _pick_threshold(ctx.df[m2.name], rng, is_int=(m2.col_type == "integer"))
    t_str = _fmt_num(thresh)
    formula = (
        f'=SUMIFS({ctx.col_range(m1)},{ctx.col_range(cat)},"{val}",{ctx.col_range(m2)},">{t_str}")'
    )
    return (
        formula,
        {"measure": m1.name, "dim": cat.name, "value": val, "filter_col": m2.name, "thresh": t_str},
        {"m1": m1.name, "cat": cat.name, "val": val, "m2": m2.name, "thresh": thresh},
    )


def _gt_sumifs_cat_num(df: pd.DataFrame, p: dict[str, Any]) -> float:
    mask = (df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()) & (
        df[p["m2"]] > p["thresh"]
    )
    return float(df.loc[mask, p["m1"]].dropna().sum())


def _build_countifs_two_cats(ctx: SheetContext, rng: random.Random):
    c1, c2 = rng.sample(ctx.cols_of_kind("category"), 2)
    row = ctx.df.iloc[rng.randrange(ctx.num_rows)]
    v1, v2 = str(row[c1.name]), str(row[c2.name])
    formula = f'=COUNTIFS({ctx.col_range(c1)},"{v1}",{ctx.col_range(c2)},"{v2}")'
    return (
        formula,
        {"dim1": c1.name, "val1": v1, "dim2": c2.name, "val2": v2},
        {"c1": c1.name, "v1": v1, "c2": c2.name, "v2": v2},
    )


def _gt_countifs_two_cats(df: pd.DataFrame, p: dict[str, Any]) -> int:
    m1 = df[p["c1"]].astype(str).str.lower() == str(p["v1"]).lower()
    m2 = df[p["c2"]].astype(str).str.lower() == str(p["v2"]).lower()
    return int((m1 & m2).sum())


def _build_sumifs_two_cats(ctx: SheetContext, rng: random.Random):
    c1, c2 = rng.sample(ctx.cols_of_kind("category"), 2)
    num = rng.choice(ctx.cols_of_kind("numeric"))
    idxs = _nonnull_indices(ctx.df, c1.name, c2.name, num.name)
    row = ctx.df.iloc[rng.choice(idxs)]
    v1, v2 = str(row[c1.name]), str(row[c2.name])
    formula = f'=SUMIFS({ctx.col_range(num)},{ctx.col_range(c1)},"{v1}",{ctx.col_range(c2)},"{v2}")'
    return (
        formula,
        {"measure": num.name, "dim1": c1.name, "val1": v1, "dim2": c2.name, "val2": v2},
        {"num": num.name, "c1": c1.name, "v1": v1, "c2": c2.name, "v2": v2},
    )


def _gt_sumifs_two_cats(df: pd.DataFrame, p: dict[str, Any]) -> float:
    m1 = df[p["c1"]].astype(str).str.lower() == str(p["v1"]).lower()
    m2 = df[p["c2"]].astype(str).str.lower() == str(p["v2"]).lower()
    return float(df.loc[m1 & m2, p["num"]].dropna().sum())


def _build_averageifs_cat_num(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    nums = ctx.cols_of_kind("numeric")
    m1 = rng.choice(nums)
    m2 = rng.choice([c for c in nums if c.name != m1.name] or nums)
    idxs = _nonnull_indices(ctx.df, cat.name, m1.name, m2.name)
    # Pick a category value and threshold guaranteed to have >=1 matching non-null row.
    anchor = ctx.df.iloc[rng.choice(idxs)]
    val = str(anchor[cat.name])
    sub = ctx.df.loc[(ctx.df[cat.name] == val) & ctx.df[m1.name].notna() & ctx.df[m2.name].notna()]
    thresh = _pick_threshold(sub[m2.name], rng, is_int=(m2.col_type == "integer"))
    if not (sub[m2.name] >= thresh).any():
        thresh = (
            int(sub[m2.name].min())
            if m2.col_type == "integer"
            else round(float(sub[m2.name].min()), 1)
        )
    t_str = _fmt_num(thresh)
    formula = f'=AVERAGEIFS({ctx.col_range(m1)},{ctx.col_range(cat)},"{val}",{ctx.col_range(m2)},">={t_str}")'
    return (
        formula,
        {"measure": m1.name, "dim": cat.name, "value": val, "filter_col": m2.name, "thresh": t_str},
        {"m1": m1.name, "cat": cat.name, "val": val, "m2": m2.name, "thresh": thresh},
    )


def _gt_averageifs_cat_num(df: pd.DataFrame, p: dict[str, Any]) -> float:
    mask = (df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()) & (
        df[p["m2"]] >= p["thresh"]
    )
    return float(df.loc[mask, p["m1"]].dropna().mean())


# --- Category 3: logic (8 templates) ---


def _build_if_num_gt(ctx: SheetContext, rng: random.Random):
    num = rng.choice(ctx.cols_of_kind("numeric"))
    idx = rng.choice(_nonnull_indices(ctx.df, num.name))
    excel_row = idx + 2
    thresh = _pick_threshold(ctx.df[num.name], rng, is_int=(num.col_type == "integer"))
    t_str = _fmt_num(thresh)
    hi, lo = rng.choice([("High", "Low"), ("Above", "Below"), ("Pass", "Review")])
    formula = f'=IF({ctx.cell_ref(num, excel_row)}>{t_str},"{hi}","{lo}")'
    return (
        formula,
        {"measure": num.name, "row": excel_row, "thresh": t_str, "hi": hi, "lo": lo},
        {"num": num.name, "idx": idx, "thresh": thresh, "hi": hi, "lo": lo},
    )


def _gt_if_num_gt(df: pd.DataFrame, p: dict[str, Any]) -> str:
    return p["hi"] if float(df.iloc[p["idx"]][p["num"]]) > p["thresh"] else p["lo"]


def _build_if_cat_eq(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    idx = rng.choice(_nonnull_indices(ctx.df, cat.name))
    excel_row = idx + 2
    val = rng.choice(cat.categories)
    yes, no = rng.choice([("Match", "Other"), ("Yes", "No"), ("Target", "Non-Target")])
    formula = f'=IF({ctx.cell_ref(cat, excel_row)}="{val}","{yes}","{no}")'
    return (
        formula,
        {"dim": cat.name, "row": excel_row, "value": val, "yes": yes, "no": no},
        {"cat": cat.name, "idx": idx, "val": val, "yes": yes, "no": no},
    )


def _gt_if_cat_eq(df: pd.DataFrame, p: dict[str, Any]) -> str:
    actual = str(df.iloc[p["idx"]][p["cat"]]).lower()
    return p["yes"] if actual == str(p["val"]).lower() else p["no"]


def _build_if_blank_fallback(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("nullable"))
    null_idxs = ctx.df.index[ctx.df[col.name].isna()].tolist()
    nonnull_idxs = _nonnull_indices(ctx.df, col.name)
    idx = rng.choice(null_idxs) if (null_idxs and rng.random() < 0.5) else rng.choice(nonnull_idxs)
    excel_row = idx + 2
    fallback = rng.choice(["Missing", "N/A", "Unknown"])
    ref = ctx.cell_ref(col, excel_row)
    formula = f'=IF({ref}="","{fallback}",{ref})'
    return (
        formula,
        {"col": col.name, "row": excel_row, "fallback": fallback},
        {"col": col.name, "idx": idx, "fallback": fallback},
    )


def _gt_if_blank_fallback(df: pd.DataFrame, p: dict[str, Any]) -> Any:
    val = df.iloc[p["idx"]][p["col"]]
    if pd.isna(val) or val == "":
        return p["fallback"]
    return val


def _build_and_two(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    num = rng.choice(ctx.cols_of_kind("numeric"))
    idx = rng.choice(_nonnull_indices(ctx.df, cat.name, num.name))
    excel_row = idx + 2
    val = rng.choice(cat.categories)
    thresh = _pick_threshold(ctx.df[num.name], rng, is_int=(num.col_type == "integer"))
    t_str = _fmt_num(thresh)
    formula = (
        f'=AND({ctx.cell_ref(cat, excel_row)}="{val}",{ctx.cell_ref(num, excel_row)}>={t_str})'
    )
    return (
        formula,
        {"dim": cat.name, "value": val, "measure": num.name, "thresh": t_str, "row": excel_row},
        {"cat": cat.name, "val": val, "num": num.name, "thresh": thresh, "idx": idx},
    )


def _gt_and_two(df: pd.DataFrame, p: dict[str, Any]) -> bool:
    row = df.iloc[p["idx"]]
    return bool(
        str(row[p["cat"]]).lower() == str(p["val"]).lower() and float(row[p["num"]]) >= p["thresh"]
    )


def _build_or_two_cats(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    v1, v2 = rng.sample(list(cat.categories), 2)
    idx = rng.choice(_nonnull_indices(ctx.df, cat.name))
    excel_row = idx + 2
    ref = ctx.cell_ref(cat, excel_row)
    formula = f'=OR({ref}="{v1}",{ref}="{v2}")'
    return (
        formula,
        {"dim": cat.name, "val1": v1, "val2": v2, "row": excel_row},
        {"cat": cat.name, "v1": v1, "v2": v2, "idx": idx},
    )


def _gt_or_two_cats(df: pd.DataFrame, p: dict[str, Any]) -> bool:
    val = str(df.iloc[p["idx"]][p["cat"]]).lower()
    return val in (str(p["v1"]).lower(), str(p["v2"]).lower())


def _build_if_and(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    num = rng.choice(ctx.cols_of_kind("numeric"))
    idx = rng.choice(_nonnull_indices(ctx.df, cat.name, num.name))
    excel_row = idx + 2
    val = rng.choice(cat.categories)
    thresh = _pick_threshold(ctx.df[num.name], rng, is_int=(num.col_type == "integer"))
    t_str = _fmt_num(thresh)
    yes, no = rng.choice([("Priority", "Standard"), ("Qualified", "Not Qualified")])
    formula = (
        f'=IF(AND({ctx.cell_ref(cat, excel_row)}="{val}",'
        f'{ctx.cell_ref(num, excel_row)}>{t_str}),"{yes}","{no}")'
    )
    return (
        formula,
        {
            "dim": cat.name,
            "value": val,
            "measure": num.name,
            "thresh": t_str,
            "row": excel_row,
            "yes": yes,
            "no": no,
        },
        {
            "cat": cat.name,
            "val": val,
            "num": num.name,
            "thresh": thresh,
            "idx": idx,
            "yes": yes,
            "no": no,
        },
    )


def _gt_if_and(df: pd.DataFrame, p: dict[str, Any]) -> str:
    row = df.iloc[p["idx"]]
    cond = (
        str(row[p["cat"]]).lower() == str(p["val"]).lower() and float(row[p["num"]]) > p["thresh"]
    )
    return p["yes"] if cond else p["no"]


def _build_if_or(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    v1, v2 = rng.sample(list(cat.categories), 2)
    idx = rng.choice(_nonnull_indices(ctx.df, cat.name))
    excel_row = idx + 2
    yes, no = rng.choice([("Flagged", "Normal"), ("Selected", "Excluded")])
    ref = ctx.cell_ref(cat, excel_row)
    formula = f'=IF(OR({ref}="{v1}",{ref}="{v2}"),"{yes}","{no}")'
    return (
        formula,
        {"dim": cat.name, "val1": v1, "val2": v2, "row": excel_row, "yes": yes, "no": no},
        {"cat": cat.name, "v1": v1, "v2": v2, "idx": idx, "yes": yes, "no": no},
    )


def _gt_if_or(df: pd.DataFrame, p: dict[str, Any]) -> str:
    val = str(df.iloc[p["idx"]][p["cat"]]).lower()
    return p["yes"] if val in (str(p["v1"]).lower(), str(p["v2"]).lower()) else p["no"]


def _build_ifs_tiers(ctx: SheetContext, rng: random.Random):
    num = rng.choice(ctx.cols_of_kind("numeric"))
    idx = rng.choice(_nonnull_indices(ctx.df, num.name))
    excel_row = idx + 2
    t_mid, t_high = _pick_two_tiers(ctx.df[num.name], is_int=(num.col_type == "integer"))
    tm_s, th_s = _fmt_num(t_mid), _fmt_num(t_high)
    ref = ctx.cell_ref(num, excel_row)
    formula = f'=IFS({ref}>={th_s},"High",{ref}>={tm_s},"Medium",TRUE,"Low")'
    return (
        formula,
        {"measure": num.name, "row": excel_row, "t_high": th_s, "t_mid": tm_s},
        {"num": num.name, "idx": idx, "t_high": t_high, "t_mid": t_mid},
    )


def _gt_ifs_tiers(df: pd.DataFrame, p: dict[str, Any]) -> str:
    val = float(df.iloc[p["idx"]][p["num"]])
    if val >= p["t_high"]:
        return "High"
    if val >= p["t_mid"]:
        return "Medium"
    return "Low"


# --- Category 4: lookup (7 templates) ---


def _pick_lookup_target(
    ctx: SheetContext, rng: random.Random, *, allow_missing: bool = False
) -> tuple[ColumnInfo, ColumnInfo, str, bool]:
    key_col = ctx.cols_of_kind("key")[0]
    ret_candidates = [c for c in ctx.columns if not c.unique and c.col_type != "date"]
    ret_col = rng.choice(ret_candidates)
    if allow_missing and rng.random() < 0.4:
        return key_col, ret_col, "ZZZ-9999", False
    idxs = _nonnull_indices(ctx.df, key_col.name, ret_col.name)
    idx = rng.choice(idxs)
    key_val = str(ctx.df.iloc[idx][key_col.name])
    return key_col, ret_col, key_val, True


def _build_vlookup(ctx: SheetContext, rng: random.Random):
    key_col, ret_col, key_val, _ = _pick_lookup_target(ctx, rng, allow_missing=False)
    last_col = ctx.columns[-1]
    tbl_rng = f"{key_col.letter}2:{last_col.letter}{ctx.last_row}"
    formula = f'=VLOOKUP("{key_val}",{tbl_rng},{ret_col.index},FALSE)'
    return (
        formula,
        {"key_col": key_col.name, "key_val": key_val, "ret_col": ret_col.name},
        {"key_col": key_col.name, "key_val": key_val, "ret_col": ret_col.name},
    )


def _gt_lookup_exact(df: pd.DataFrame, p: dict[str, Any]) -> Any:
    matches = df.loc[df[p["key_col"]].astype(str).str.lower() == str(p["key_val"]).lower()]
    if matches.empty:
        return p.get("fallback")
    return matches.iloc[0][p["ret_col"]]


def _build_xlookup(ctx: SheetContext, rng: random.Random):
    key_col, ret_col, key_val, _ = _pick_lookup_target(ctx, rng, allow_missing=False)
    formula = f'=XLOOKUP("{key_val}",{ctx.col_range(key_col)},{ctx.col_range(ret_col)})'
    return (
        formula,
        {"key_col": key_col.name, "key_val": key_val, "ret_col": ret_col.name},
        {"key_col": key_col.name, "key_val": key_val, "ret_col": ret_col.name},
    )


def _build_xlookup_default(ctx: SheetContext, rng: random.Random):
    key_col, ret_col, key_val, _ = _pick_lookup_target(ctx, rng, allow_missing=True)
    fallback = rng.choice(["Not Found", "Missing", "Unknown"])
    formula = (
        f'=XLOOKUP("{key_val}",{ctx.col_range(key_col)},{ctx.col_range(ret_col)},"{fallback}")'
    )
    return (
        formula,
        {
            "key_col": key_col.name,
            "key_val": key_val,
            "ret_col": ret_col.name,
            "fallback": fallback,
        },
        {
            "key_col": key_col.name,
            "key_val": key_val,
            "ret_col": ret_col.name,
            "fallback": fallback,
        },
    )


def _build_index_match(ctx: SheetContext, rng: random.Random):
    key_col, ret_col, key_val, _ = _pick_lookup_target(ctx, rng, allow_missing=False)
    formula = f'=INDEX({ctx.col_range(ret_col)},MATCH("{key_val}",{ctx.col_range(key_col)},0))'
    return (
        formula,
        {"key_col": key_col.name, "key_val": key_val, "ret_col": ret_col.name},
        {"key_col": key_col.name, "key_val": key_val, "ret_col": ret_col.name},
    )


def _build_match_pos(ctx: SheetContext, rng: random.Random):
    key_col = ctx.cols_of_kind("key")[0]
    idx = rng.randrange(ctx.num_rows)
    key_val = str(ctx.df.iloc[idx][key_col.name])
    formula = f'=MATCH("{key_val}",{ctx.col_range(key_col)},0)'
    return (
        formula,
        {"key_col": key_col.name, "key_val": key_val},
        {"key_col": key_col.name, "key_val": key_val},
    )


def _gt_match_pos(df: pd.DataFrame, p: dict[str, Any]) -> int:
    matches = df.index[df[p["key_col"]].astype(str).str.lower() == str(p["key_val"]).lower()]
    return int(matches[0]) + 1


def _build_index_nth(ctx: SheetContext, rng: random.Random):
    candidates = [c for c in ctx.columns if c.col_type != "date"]
    col = rng.choice(candidates)
    idxs = _nonnull_indices(ctx.df, col.name)
    idx = rng.choice(idxs)
    pos = idx + 1
    formula = f"=INDEX({ctx.col_range(col)},{pos})"
    return formula, {"col": col.name, "pos": pos}, {"col": col.name, "idx": idx}


def _gt_index_nth(df: pd.DataFrame, p: dict[str, Any]) -> Any:
    return df.iloc[p["idx"]][p["col"]]


def _build_iferror_vlookup(ctx: SheetContext, rng: random.Random):
    key_col, ret_col, key_val, _ = _pick_lookup_target(ctx, rng, allow_missing=True)
    last_col = ctx.columns[-1]
    tbl_rng = f"{key_col.letter}2:{last_col.letter}{ctx.last_row}"
    fallback = rng.choice(["Not Found", "Missing"])
    formula = f'=IFERROR(VLOOKUP("{key_val}",{tbl_rng},{ret_col.index},FALSE),"{fallback}")'
    return (
        formula,
        {
            "key_col": key_col.name,
            "key_val": key_val,
            "ret_col": ret_col.name,
            "fallback": fallback,
        },
        {
            "key_col": key_col.name,
            "key_val": key_val,
            "ret_col": ret_col.name,
            "fallback": fallback,
        },
    )


# --- Category 5: text (11 templates) ---


def _pick_string_col(ctx: SheetContext, rng: random.Random) -> ColumnInfo:
    cands = ctx.cols_of_kind("text_nonkey") + ctx.cols_of_kind("category")
    return rng.choice(cands or ctx.cols_of_kind("text"))


def _build_single_text_fn(fn_name: str) -> BuilderFn:
    def _build(ctx: SheetContext, rng: random.Random):
        col = _pick_string_col(ctx, rng)
        idx = rng.choice(_nonnull_indices(ctx.df, col.name))
        excel_row = idx + 2
        formula = f"={fn_name}({ctx.cell_ref(col, excel_row)})"
        return formula, {"col": col.name, "row": excel_row}, {"col": col.name, "idx": idx}

    return _build


def _gt_upper(df: pd.DataFrame, p: dict[str, Any]) -> str:
    return str(df.iloc[p["idx"]][p["col"]]).upper()


def _gt_lower(df: pd.DataFrame, p: dict[str, Any]) -> str:
    return str(df.iloc[p["idx"]][p["col"]]).lower()


def _gt_proper(df: pd.DataFrame, p: dict[str, Any]) -> str:
    return _excel_proper(str(df.iloc[p["idx"]][p["col"]]))


def _gt_trim(df: pd.DataFrame, p: dict[str, Any]) -> str:
    return _excel_trim(str(df.iloc[p["idx"]][p["col"]]))


def _gt_len(df: pd.DataFrame, p: dict[str, Any]) -> int:
    return len(str(df.iloc[p["idx"]][p["col"]]))


def _build_left_right(fn_name: str) -> BuilderFn:
    def _build(ctx: SheetContext, rng: random.Random):
        col = rng.choice(ctx.cols_of_kind("text") + ctx.cols_of_kind("category"))
        idx = rng.choice(_nonnull_indices(ctx.df, col.name))
        excel_row = idx + 2
        text_len = len(str(ctx.df.iloc[idx][col.name]))
        n = rng.randint(2, max(2, min(5, text_len)))
        formula = f"={fn_name}({ctx.cell_ref(col, excel_row)},{n})"
        return (
            formula,
            {"col": col.name, "row": excel_row, "n": n},
            {"col": col.name, "idx": idx, "n": n},
        )

    return _build


def _gt_left(df: pd.DataFrame, p: dict[str, Any]) -> str:
    return str(df.iloc[p["idx"]][p["col"]])[: p["n"]]


def _gt_right(df: pd.DataFrame, p: dict[str, Any]) -> str:
    s = str(df.iloc[p["idx"]][p["col"]])
    return s[-p["n"] :] if p["n"] > 0 else ""


def _build_mid(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("text") + ctx.cols_of_kind("category"))
    idxs = [
        i for i in _nonnull_indices(ctx.df, col.name) if len(str(ctx.df.iloc[i][col.name])) >= 4
    ]
    idx = rng.choice(idxs or _nonnull_indices(ctx.df, col.name))
    excel_row = idx + 2
    s_len = len(str(ctx.df.iloc[idx][col.name]))
    start = rng.randint(2, max(2, min(4, s_len - 1)))
    length = rng.randint(2, max(2, min(4, s_len - start + 1)))
    formula = f"=MID({ctx.cell_ref(col, excel_row)},{start},{length})"
    return (
        formula,
        {"col": col.name, "row": excel_row, "start": start, "length": length},
        {"col": col.name, "idx": idx, "start": start, "length": length},
    )


def _gt_mid(df: pd.DataFrame, p: dict[str, Any]) -> str:
    s = str(df.iloc[p["idx"]][p["col"]])
    return s[p["start"] - 1 : p["start"] - 1 + p["length"]]


def _build_concat_two(ctx: SheetContext, rng: random.Random):
    str_cols = ctx.cols_of_kind("text") + ctx.cols_of_kind("category")
    c1, c2 = rng.sample(str_cols, 2)
    idx = rng.choice(_nonnull_indices(ctx.df, c1.name, c2.name))
    excel_row = idx + 2
    sep = rng.choice([" - ", "-", ": ", " | "])
    formula = f'=CONCAT({ctx.cell_ref(c1, excel_row)},"{sep}",{ctx.cell_ref(c2, excel_row)})'
    return (
        formula,
        {"col1": c1.name, "col2": c2.name, "sep": sep, "row": excel_row},
        {"c1": c1.name, "c2": c2.name, "sep": sep, "idx": idx},
    )


def _gt_concat_two(df: pd.DataFrame, p: dict[str, Any]) -> str:
    row = df.iloc[p["idx"]]
    return f"{row[p['c1']]}{p['sep']}{row[p['c2']]}"


def _build_textjoin_slice(ctx: SheetContext, rng: random.Random):
    col = _pick_string_col(ctx, rng)
    start_row = rng.randint(2, max(2, min(15, ctx.last_row - 4)))
    end_row = start_row + rng.randint(2, 4)
    delim = rng.choice([", ", " | ", "; "])
    formula = f'=TEXTJOIN("{delim}",TRUE,{ctx.col_range(col, start_row, end_row)})'
    return (
        formula,
        {"col": col.name, "start_row": start_row, "end_row": end_row, "delim": delim},
        {"col": col.name, "start_idx": start_row - 2, "end_idx": end_row - 2, "delim": delim},
    )


def _gt_textjoin_slice(df: pd.DataFrame, p: dict[str, Any]) -> str:
    vals = df.iloc[p["start_idx"] : p["end_idx"] + 1][p["col"]].dropna().astype(str).tolist()
    vals = [v for v in vals if v != ""]
    return p["delim"].join(vals)


def _build_text_format_num(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("decimal"))
    idx = rng.choice(_nonnull_indices(ctx.df, col.name))
    excel_row = idx + 2
    formula = f'=TEXT({ctx.cell_ref(col, excel_row)},"0.00")'
    return formula, {"measure": col.name, "row": excel_row}, {"col": col.name, "idx": idx}


def _gt_text_format_num(df: pd.DataFrame, p: dict[str, Any]) -> str:
    val = _excel_round(float(df.iloc[p["idx"]][p["col"]]), 2)
    return f"{val:.2f}"


# --- Category 6: date (8 templates including date-filtered COUNTIFS / SUMIFS) ---


def _build_date_part(fn_name: str) -> BuilderFn:
    def _build(ctx: SheetContext, rng: random.Random):
        col = rng.choice(ctx.cols_of_kind("date"))
        idx = rng.choice(_nonnull_indices(ctx.df, col.name))
        excel_row = idx + 2
        formula = f"={fn_name}({ctx.cell_ref(col, excel_row)})"
        return formula, {"date_col": col.name, "row": excel_row}, {"col": col.name, "idx": idx}

    return _build


def _gt_year(df: pd.DataFrame, p: dict[str, Any]) -> int:
    return int(df.iloc[p["idx"]][p["col"]].year)


def _gt_month(df: pd.DataFrame, p: dict[str, Any]) -> int:
    return int(df.iloc[p["idx"]][p["col"]].month)


def _gt_day(df: pd.DataFrame, p: dict[str, Any]) -> int:
    return int(df.iloc[p["idx"]][p["col"]].day)


def _build_date_construct(_ctx: SheetContext, rng: random.Random):
    year = rng.randint(2023, 2026)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    formula = f"=DATE({year},{month},{day})"
    return (
        formula,
        {"year": year, "month": month, "day": day, "iso": f"{year:04d}-{month:02d}-{day:02d}"},
        {"year": year, "month": month, "day": day},
    )


def _gt_date_construct(_df: pd.DataFrame, p: dict[str, Any]) -> date:
    return date(p["year"], p["month"], p["day"])


def _build_countif_date_after(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("date"))
    cutoff = _pick_cutoff_date(ctx.df[col.name], rng)
    formula = f'=COUNTIF({ctx.col_range(col)},">"&DATE({cutoff.year},{cutoff.month},{cutoff.day}))'
    return (
        formula,
        {"date_col": col.name, "iso": cutoff.isoformat()},
        {"col": col.name, "cutoff": cutoff.isoformat()},
    )


def _gt_countif_date_after(df: pd.DataFrame, p: dict[str, Any]) -> int:
    cutoff = date.fromisoformat(p["cutoff"])
    s = df[p["col"]].dropna()
    return int((s > cutoff).sum())


def _build_text_date_ym(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("date"))
    idx = rng.choice(_nonnull_indices(ctx.df, col.name))
    excel_row = idx + 2
    formula = f'=TEXT({ctx.cell_ref(col, excel_row)},"yyyy-mm")'
    return formula, {"date_col": col.name, "row": excel_row}, {"col": col.name, "idx": idx}


def _gt_text_date_ym(df: pd.DataFrame, p: dict[str, Any]) -> str:
    d: date = df.iloc[p["idx"]][p["col"]]
    return f"{d.year:04d}-{d.month:02d}"


def _build_countifs_cat_date(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    dt = rng.choice(ctx.cols_of_kind("date"))
    val = rng.choice(cat.categories)
    cutoff = _pick_cutoff_date(ctx.df[dt.name], rng)
    formula = (
        f'=COUNTIFS({ctx.col_range(cat)},"{val}",'
        f'{ctx.col_range(dt)},">"&DATE({cutoff.year},{cutoff.month},{cutoff.day}))'
    )
    return (
        formula,
        {"dim": cat.name, "value": val, "date_col": dt.name, "iso": cutoff.isoformat()},
        {"cat": cat.name, "val": val, "dt": dt.name, "cutoff": cutoff.isoformat()},
    )


def _gt_countifs_cat_date(df: pd.DataFrame, p: dict[str, Any]) -> int:
    cutoff = date.fromisoformat(p["cutoff"])
    m1 = df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()
    m2 = df[p["dt"]].apply(lambda d: isinstance(d, date) and d > cutoff)
    return int((m1 & m2).sum())


def _build_sumifs_cat_date(ctx: SheetContext, rng: random.Random):
    num = rng.choice(ctx.cols_of_kind("numeric"))
    cat = rng.choice(ctx.cols_of_kind("category"))
    dt = rng.choice(ctx.cols_of_kind("date"))
    val = _pick_cat_with_nonnull_measure(ctx, cat, num, rng)
    cutoff = _pick_cutoff_date(ctx.df[dt.name], rng)
    formula = (
        f'=SUMIFS({ctx.col_range(num)},{ctx.col_range(cat)},"{val}",'
        f'{ctx.col_range(dt)},">="&DATE({cutoff.year},{cutoff.month},{cutoff.day}))'
    )
    return (
        formula,
        {
            "measure": num.name,
            "dim": cat.name,
            "value": val,
            "date_col": dt.name,
            "iso": cutoff.isoformat(),
        },
        {"num": num.name, "cat": cat.name, "val": val, "dt": dt.name, "cutoff": cutoff.isoformat()},
    )


def _gt_sumifs_cat_date(df: pd.DataFrame, p: dict[str, Any]) -> float:
    cutoff = date.fromisoformat(p["cutoff"])
    m1 = df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()
    m2 = df[p["dt"]].apply(lambda d: isinstance(d, date) and d >= cutoff)
    return float(df.loc[m1 & m2, p["num"]].dropna().sum())


# --- Category 7: math_and_composition (6 templates) ---


def _build_round_cell(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("decimal"))
    idx = rng.choice(_nonnull_indices(ctx.df, col.name))
    excel_row = idx + 2
    digits = rng.choice([0, 1])
    formula = f"=ROUND({ctx.cell_ref(col, excel_row)},{digits})"
    return (
        formula,
        {"measure": col.name, "row": excel_row, "digits": digits},
        {"col": col.name, "idx": idx, "digits": digits},
    )


def _gt_round_cell(df: pd.DataFrame, p: dict[str, Any]) -> float:
    return _excel_round(float(df.iloc[p["idx"]][p["col"]]), p["digits"])


def _build_round_avg(ctx: SheetContext, rng: random.Random):
    col = rng.choice(ctx.cols_of_kind("numeric"))
    digits = rng.choice([1, 2])
    formula = f"=ROUND(AVERAGE({ctx.col_range(col)}),{digits})"
    return formula, {"measure": col.name, "digits": digits}, {"col": col.name, "digits": digits}


def _gt_round_avg(df: pd.DataFrame, p: dict[str, Any]) -> float:
    return _excel_round(float(df[p["col"]].dropna().mean()), p["digits"])


def _build_iferror_div(ctx: SheetContext, rng: random.Random):
    c1, c2 = rng.sample(ctx.cols_of_kind("numeric"), 2)
    idxs = _nonnull_indices(ctx.df, c1.name, c2.name)
    idx = rng.choice(idxs)
    excel_row = idx + 2
    formula = f"=IFERROR({ctx.cell_ref(c1, excel_row)}/{ctx.cell_ref(c2, excel_row)},0)"
    return (
        formula,
        {"m1": c1.name, "m2": c2.name, "row": excel_row},
        {"c1": c1.name, "c2": c2.name, "idx": idx},
    )


def _gt_iferror_div(df: pd.DataFrame, p: dict[str, Any]) -> float:
    v1 = df.iloc[p["idx"]][p["c1"]]
    v2 = df.iloc[p["idx"]][p["c2"]]
    if pd.isna(v1) or pd.isna(v2) or float(v2) == 0.0:
        return 0.0
    return float(v1) / float(v2)


def _build_round_sumif_share(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    num = rng.choice(ctx.cols_of_kind("numeric"))
    val = _pick_cat_with_nonnull_measure(ctx, cat, num, rng)
    formula = (
        f'=IFERROR(ROUND(SUMIF({ctx.col_range(cat)},"{val}",{ctx.col_range(num)})'
        f"/SUM({ctx.col_range(num)}),4),0)"
    )
    return (
        formula,
        {"measure": num.name, "dim": cat.name, "value": val},
        {"cat": cat.name, "val": val, "num": num.name},
    )


def _gt_round_sumif_share(df: pd.DataFrame, p: dict[str, Any]) -> float:
    total = float(df[p["num"]].dropna().sum())
    if total == 0.0:
        return 0.0
    mask = df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()
    part = float(df.loc[mask, p["num"]].dropna().sum())
    return _excel_round(part / total, 4)


def _build_if_sumif_target(ctx: SheetContext, rng: random.Random):
    cat = rng.choice(ctx.cols_of_kind("category"))
    num = rng.choice(ctx.cols_of_kind("numeric"))
    val = _pick_cat_with_nonnull_measure(ctx, cat, num, rng)
    cat_sum = float(ctx.df.loc[ctx.df[cat.name] == val, num.name].dropna().sum())
    factor = rng.choice([0.8, 1.2])
    target = round(cat_sum * factor, 1)
    t_str = _fmt_num(target)
    yes, no = rng.choice([("Met", "Missed"), ("Above Target", "Below Target")])
    formula = (
        f'=IF(SUMIF({ctx.col_range(cat)},"{val}",{ctx.col_range(num)})>{t_str},"{yes}","{no}")'
    )
    return (
        formula,
        {
            "measure": num.name,
            "dim": cat.name,
            "value": val,
            "target": t_str,
            "yes": yes,
            "no": no,
        },
        {
            "cat": cat.name,
            "val": val,
            "num": num.name,
            "target": target,
            "yes": yes,
            "no": no,
        },
    )


def _gt_if_sumif_target(df: pd.DataFrame, p: dict[str, Any]) -> str:
    mask = df[p["cat"]].astype(str).str.lower() == str(p["val"]).lower()
    total = float(df.loc[mask, p["num"]].dropna().sum())
    return p["yes"] if total > p["target"] else p["no"]


def _build_iferror_index_match_round(ctx: SheetContext, rng: random.Random):
    key_col = ctx.cols_of_kind("key")[0]
    dec_col = rng.choice(ctx.cols_of_kind("decimal"))
    digits = rng.choice([0, 1])
    if rng.random() < 0.35:
        key_val = "ZZZ-9999"
    else:
        idx = rng.choice(_nonnull_indices(ctx.df, key_col.name, dec_col.name))
        key_val = str(ctx.df.iloc[idx][key_col.name])
    formula = (
        f"=IFERROR(ROUND(INDEX({ctx.col_range(dec_col)},"
        f'MATCH("{key_val}",{ctx.col_range(key_col)},0)),{digits}),0)'
    )
    return (
        formula,
        {"key_col": key_col.name, "key_val": key_val, "measure": dec_col.name, "digits": digits},
        {"key_col": key_col.name, "key_val": key_val, "dec_col": dec_col.name, "digits": digits},
    )


def _gt_iferror_index_match_round(df: pd.DataFrame, p: dict[str, Any]) -> float:
    matches = df.loc[df[p["key_col"]].astype(str).str.lower() == str(p["key_val"]).lower()]
    if matches.empty or pd.isna(matches.iloc[0][p["dec_col"]]):
        return 0.0
    return _excel_round(float(matches.iloc[0][p["dec_col"]]), p["digits"])


# ---------------------------------------------------------------------------
# All 60 hand-written formula templates (each with 6 to 10 varied phrasings)
# ---------------------------------------------------------------------------

TEMPLATES: tuple[FormulaTemplate, ...] = (
    # ==================== 1. AGGREGATION (8) ====================
    FormulaTemplate(
        id="sum_column",
        category="aggregation",
        difficulty=1,
        functions=("SUM",),
        required_column_types={"numeric": 1},
        builder=_build_single_numeric_agg("SUM"),
        pandas_gt=_gt_sum,
        phrasings=(
            "Calculate the total of the {measure} column.",
            "What is the sum of all values in {measure}?",
            "sum {measure}",
            "Add up every number in the {measure} column across all rows.",
            "Give me the grand total for {measure}.",
            "Total {measure} across the sheet.",
            "Can you sum up the {measure} column for me?",
            "Compute the combined {measure} across every record in the table.",
        ),
    ),
    FormulaTemplate(
        id="average_column",
        category="aggregation",
        difficulty=1,
        functions=("AVERAGE",),
        required_column_types={"numeric": 1},
        builder=_build_single_numeric_agg("AVERAGE"),
        pandas_gt=_gt_avg,
        phrasings=(
            "Calculate the arithmetic mean of the {measure} column.",
            "What's the average {measure}?",
            "avg {measure}",
            "Find the mean value across all populated entries in the {measure} column.",
            "Compute the average for {measure} across the entire table.",
            "Give me the typical mean of {measure}.",
            "What does {measure} average out to across all rows?",
        ),
    ),
    FormulaTemplate(
        id="min_column",
        category="aggregation",
        difficulty=1,
        functions=("MIN",),
        required_column_types={"numeric": 1},
        builder=_build_single_numeric_agg("MIN"),
        pandas_gt=_gt_min,
        phrasings=(
            "Find the minimum value in the {measure} column.",
            "What is the lowest {measure} in the sheet?",
            "min {measure}",
            "Return the smallest number recorded in the {measure} column.",
            "Show me the bottom value for {measure}.",
            "Which number is the smallest across all rows of {measure}?",
            "Get the minimum {measure}.",
        ),
    ),
    FormulaTemplate(
        id="max_column",
        category="aggregation",
        difficulty=1,
        functions=("MAX",),
        required_column_types={"numeric": 1},
        builder=_build_single_numeric_agg("MAX"),
        pandas_gt=_gt_max,
        phrasings=(
            "Find the maximum value in the {measure} column.",
            "What is the highest {measure}?",
            "max {measure}",
            "Return the largest number that appears anywhere in the {measure} column.",
            "Show me the peak {measure} across all records.",
            "Get the top value in {measure}.",
            "What's the biggest {measure} recorded on this sheet?",
        ),
    ),
    FormulaTemplate(
        id="count_numeric",
        category="aggregation",
        difficulty=1,
        functions=("COUNT",),
        required_column_types={"numeric": 1},
        builder=_build_single_numeric_agg("COUNT"),
        pandas_gt=_gt_count_num,
        phrasings=(
            "Count how many numeric entries are present in the {measure} column.",
            "How many non-blank numbers are in {measure}?",
            "count numeric {measure}",
            "Return the total number of cells in {measure} that contain a number.",
            "Count all filled numeric values in the {measure} column.",
            "How many rows have a numeric value recorded for {measure}?",
            "Get the count of numbers in {measure}.",
        ),
    ),
    FormulaTemplate(
        id="range_spread_max_min",
        category="aggregation",
        difficulty=2,
        functions=("MAX", "MIN"),
        required_column_types={"numeric": 1},
        builder=_build_range_spread,
        pandas_gt=_gt_range_spread,
        phrasings=(
            "Calculate the spread between the maximum and minimum {measure}.",
            "What's the difference between the highest and lowest {measure}?",
            "max minus min {measure}",
            "Find the full numeric range of the {measure} column by subtracting the minimum from the maximum.",
            "How wide is the gap between the top and bottom {measure} values?",
            "Compute MAX minus MIN for the {measure} column.",
            "Give me the difference between the largest and smallest {measure}.",
        ),
    ),
    FormulaTemplate(
        id="sum_two_columns",
        category="aggregation",
        difficulty=2,
        functions=("SUM",),
        required_column_types={"numeric": 2},
        builder=_build_sum_two_cols,
        pandas_gt=_gt_sum_two_cols,
        phrasings=(
            "Calculate the combined total of the {m1} and {m2} columns.",
            "Add the sum of {m1} and the sum of {m2} together.",
            "sum({m1}) + sum({m2})",
            "Give me one formula that adds all values in {m1} to all values in {m2}.",
            "What is the grand total when combining {m1} and {m2}?",
            "Total both {m1} and {m2} together.",
            "Find the sum of {m1} plus the sum of {m2}.",
        ),
    ),
    FormulaTemplate(
        id="avg_ratio_two_sums",
        category="aggregation",
        difficulty=3,
        functions=("SUM", "IFERROR"),
        required_column_types={"numeric": 2},
        builder=_build_ratio_two_sums,
        pandas_gt=_gt_ratio_two_sums,
        phrasings=(
            "Compute the ratio of total {m1} to total {m2}, returning 0 if an error occurs.",
            "Divide the sum of {m1} by the sum of {m2}, with 0 as a safe fallback.",
            "iferror(sum {m1} / sum {m2}, 0)",
            "Calculate total {m1} divided by total {m2} across the sheet, and output 0 on division errors.",
            "What is total {m1} per unit of total {m2} (return 0 if division fails)?",
            "Safely divide the total {m1} by the total {m2}, defaulting to 0 on error.",
            "Return the sum of {m1} over the sum of {m2}, wrapped in IFERROR returning 0.",
        ),
    ),
    # ==================== 2. CONDITIONAL AGGREGATION (12) ====================
    FormulaTemplate(
        id="sumif_category_eq",
        category="conditional_aggregation",
        difficulty=1,
        functions=("SUMIF",),
        required_column_types={"numeric": 1, "category": 1},
        builder=_build_cat_agg("SUMIF"),
        pandas_gt=_gt_sumif_cat,
        phrasings=(
            "Calculate the total {measure} for all rows where {dim} is '{value}'.",
            "What is the total {measure} when {dim} equals {value}?",
            "sum {measure} where {dim} = {value}",
            "Add up every value in the {measure} column for records whose {dim} column matches '{value}'.",
            "How much {measure} did we record for {value} in {dim}?",
            "Total {measure} for {dim} '{value}'.",
            "Give me the conditional sum of {measure} restricted to {dim} = '{value}'.",
            "Sum the {measure} column only where {dim} is {value}.",
        ),
    ),
    FormulaTemplate(
        id="countif_category_eq",
        category="conditional_aggregation",
        difficulty=1,
        functions=("COUNTIF",),
        required_column_types={"category": 1},
        builder=_build_countif_cat,
        pandas_gt=_gt_countif_cat,
        phrasings=(
            "Count the number of records where {dim} equals '{value}'.",
            "How many rows have {dim} set to {value}?",
            "count where {dim} = {value}",
            "Return the total count of entries in the {dim} column that match '{value}'.",
            "How often does '{value}' appear in {dim}?",
            "Count all '{value}' rows in the {dim} column.",
            "Tell me how many entries belong to {value} under {dim}.",
        ),
    ),
    FormulaTemplate(
        id="averageif_category_eq",
        category="conditional_aggregation",
        difficulty=1,
        functions=("AVERAGEIF",),
        required_column_types={"numeric": 1, "category": 1},
        builder=_build_cat_agg("AVERAGEIF"),
        pandas_gt=_gt_avgif_cat,
        phrasings=(
            "Calculate the average {measure} for rows where {dim} equals '{value}'.",
            "What is the mean {measure} for {value} in {dim}?",
            "avg {measure} where {dim} = {value}",
            "Compute the arithmetic mean of the {measure} column restricted to records with {dim} = '{value}'.",
            "Find the average {measure} just for {dim} '{value}'.",
            "On average, what is {measure} when {dim} is {value}?",
            "Give me the conditional average of {measure} for {dim} '{value}'.",
        ),
    ),
    FormulaTemplate(
        id="sumif_numeric_gt",
        category="conditional_aggregation",
        difficulty=2,
        functions=("SUMIF",),
        required_column_types={"numeric": 1},
        builder=_build_num_cond("SUMIF", ">"),
        pandas_gt=_gt_sumif_gt,
        phrasings=(
            "Calculate the sum of {measure} values strictly greater than {thresh}.",
            "Add up all {measure} numbers that are above {thresh}.",
            "sum {measure} > {thresh}",
            "Compute the total of the {measure} column counting only cells whose value exceeds {thresh}.",
            "What is the total of {measure} entries larger than {thresh}?",
            "Sum {measure} where the value is over {thresh}.",
            "Give me the sum of every {measure} strictly above {thresh}.",
        ),
    ),
    FormulaTemplate(
        id="countif_numeric_gte",
        category="conditional_aggregation",
        difficulty=2,
        functions=("COUNTIF",),
        required_column_types={"numeric": 1},
        builder=_build_num_cond("COUNTIF", ">="),
        pandas_gt=_gt_countif_gte,
        phrasings=(
            "Count the number of rows where {measure} is at least {thresh}.",
            "How many records have {measure} greater than or equal to {thresh}?",
            "count {measure} >= {thresh}",
            "Return how many cells in the {measure} column hold a value of {thresh} or higher.",
            "How many entries meet or exceed {thresh} in {measure}?",
            "Count rows with {measure} >= {thresh}.",
            "Find the number of {measure} values that are {thresh} or more.",
        ),
    ),
    FormulaTemplate(
        id="averageif_numeric_gt",
        category="conditional_aggregation",
        difficulty=2,
        functions=("AVERAGEIF",),
        required_column_types={"numeric": 1},
        builder=_build_num_cond("AVERAGEIF", ">"),
        pandas_gt=_gt_avgif_gt,
        phrasings=(
            "Calculate the average of {measure} values strictly greater than {thresh}.",
            "What is the mean {measure} among rows above {thresh}?",
            "avg {measure} > {thresh}",
            "Compute the average of all entries in {measure} that exceed {thresh}.",
            "Find the average of {measure} values over {thresh}.",
            "What do {measure} values greater than {thresh} average out to?",
            "Average {measure} only for numbers above {thresh}.",
        ),
    ),
    FormulaTemplate(
        id="countif_category_neq",
        category="conditional_aggregation",
        difficulty=2,
        functions=("COUNTIF",),
        required_column_types={"category": 1},
        builder=_build_countif_cat_neq,
        pandas_gt=_gt_countif_cat_neq,
        excel_quirk=(
            'COUNTIF(range, "<>val") counts blank cells in Excel, whereas pandas dropna() '
            "excludes them; safe on non-null category columns."
        ),
        phrasings=(
            "Count all records where {dim} is not equal to '{value}'.",
            "How many rows have a {dim} other than {value}?",
            "count {dim} != {value}",
            "Return the number of entries in the {dim} column that do not match '{value}'.",
            "Count every row excluding '{value}' in {dim}.",
            "How many entries in {dim} are anything besides {value}?",
            "Find the count of rows where {dim} is not '{value}'.",
        ),
    ),
    FormulaTemplate(
        id="countif_wildcard_prefix",
        category="conditional_aggregation",
        difficulty=2,
        functions=("COUNTIF",),
        required_column_types={"category": 1},
        builder=_build_countif_wildcard,
        pandas_gt=_gt_countif_wildcard,
        excel_quirk=(
            "Wildcard matching in COUNTIF is case-insensitive in Excel and `formulas`; "
            "literal '*', '?' or '~' in prefixes would require escaping."
        ),
        phrasings=(
            "Count all rows where {dim} starts with '{prefix}'.",
            "How many entries in {dim} begin with '{prefix}'?",
            "count {dim} starting with {prefix}",
            "Use a wildcard COUNTIF to count cells in {dim} whose text begins with '{prefix}'.",
            "Find the number of {dim} values having the prefix '{prefix}'.",
            "Count rows where {dim} matches '{prefix}*'.",
            "How many records have a {dim} starting with '{prefix}'?",
        ),
    ),
    FormulaTemplate(
        id="sumifs_cat_and_num",
        category="conditional_aggregation",
        difficulty=2,
        functions=("SUMIFS",),
        required_column_types={"numeric": 2, "category": 1},
        builder=_build_sumifs_cat_num,
        pandas_gt=_gt_sumifs_cat_num,
        phrasings=(
            "Calculate total {measure} where {dim} is '{value}' and {filter_col} exceeds {thresh}.",
            "Sum {measure} for {dim} '{value}' with {filter_col} over {thresh}.",
            "sumifs {measure}: {dim}={value} and {filter_col}>{thresh}",
            "Add up all values in {measure} for rows matching {dim} = '{value}' and {filter_col} strictly greater than {thresh}.",
            "What is the total {measure} when {dim} is {value} and {filter_col} is above {thresh}?",
            "Get total {measure} filtered by {dim} = '{value}' and {filter_col} > {thresh}.",
            "Compute the sum of {measure} for '{value}' in {dim} where {filter_col} is higher than {thresh}.",
        ),
    ),
    FormulaTemplate(
        id="countifs_two_cats",
        category="conditional_aggregation",
        difficulty=2,
        functions=("COUNTIFS",),
        required_column_types={"category": 2},
        builder=_build_countifs_two_cats,
        pandas_gt=_gt_countifs_two_cats,
        phrasings=(
            "Count the records where {dim1} is '{val1}' and {dim2} is '{val2}'.",
            "How many rows have {dim1} = {val1} and {dim2} = {val2}?",
            "countifs {dim1}={val1}, {dim2}={val2}",
            "Return the number of entries that simultaneously have '{val1}' in {dim1} and '{val2}' in {dim2}.",
            "How many records match both {dim1} '{val1}' and {dim2} '{val2}'?",
            "Count rows with {dim1} equal to '{val1}' and {dim2} equal to '{val2}'.",
            "Find the count of rows for {val1} ({dim1}) and {val2} ({dim2}).",
        ),
    ),
    FormulaTemplate(
        id="sumifs_two_cats",
        category="conditional_aggregation",
        difficulty=3,
        functions=("SUMIFS",),
        required_column_types={"numeric": 1, "category": 2},
        builder=_build_sumifs_two_cats,
        pandas_gt=_gt_sumifs_two_cats,
        phrasings=(
            "Calculate the total {measure} where {dim1} is '{val1}' and {dim2} is '{val2}'.",
            "What is the sum of {measure} for {dim1} '{val1}' and {dim2} '{val2}'?",
            "sum {measure} where {dim1}={val1} & {dim2}={val2}",
            "Sum the {measure} column across all rows matching both {dim1} = '{val1}' and {dim2} = '{val2}'.",
            "How much {measure} comes from {val1} in {dim1} combined with {val2} in {dim2}?",
            "Total {measure} filtered to {dim1}='{val1}' and {dim2}='{val2}'.",
            "Give me the conditional sum of {measure} for {dim1} '{val1}' and {dim2} '{val2}'.",
        ),
    ),
    FormulaTemplate(
        id="averageifs_cat_and_num",
        category="conditional_aggregation",
        difficulty=3,
        functions=("AVERAGEIFS",),
        required_column_types={"numeric": 2, "category": 1},
        builder=_build_averageifs_cat_num,
        pandas_gt=_gt_averageifs_cat_num,
        phrasings=(
            "Calculate the average {measure} where {dim} is '{value}' and {filter_col} is at least {thresh}.",
            "What's the mean {measure} for {dim} '{value}' when {filter_col} >= {thresh}?",
            "averageifs {measure}: {dim}={value}, {filter_col}>={thresh}",
            "Compute the arithmetic mean of {measure} restricted to rows where {dim} equals '{value}' and {filter_col} is {thresh} or higher.",
            "Find the average {measure} for '{value}' in {dim} with {filter_col} of at least {thresh}.",
            "Average {measure} filtered by {dim} = '{value}' and {filter_col} >= {thresh}.",
            "Give me the conditional mean of {measure} for {dim} '{value}' and {filter_col} >= {thresh}.",
        ),
    ),
    # ==================== 3. LOGIC (8) ====================
    FormulaTemplate(
        id="if_numeric_gt_label",
        category="logic",
        difficulty=1,
        functions=("IF",),
        required_column_types={"numeric": 1},
        builder=_build_if_num_gt,
        pandas_gt=_gt_if_num_gt,
        phrasings=(
            "For row {row}, return '{hi}' if {measure} is greater than {thresh}, otherwise return '{lo}'.",
            "In row {row}, label {measure} as '{hi}' if it's over {thresh}, else '{lo}'.",
            "row {row}: if {measure} > {thresh} then '{hi}' else '{lo}'",
            "Check the {measure} value in row {row}; output '{hi}' when it strictly exceeds {thresh}, and '{lo}' otherwise.",
            "If row {row}'s {measure} is above {thresh}, show '{hi}', otherwise '{lo}'.",
            "Classify row {row} {measure}: '{hi}' if > {thresh}, else '{lo}'.",
            "Return '{hi}' when {measure} in row {row} is more than {thresh}, or '{lo}' if not.",
        ),
    ),
    FormulaTemplate(
        id="if_category_eq_label",
        category="logic",
        difficulty=1,
        functions=("IF",),
        required_column_types={"category": 1},
        builder=_build_if_cat_eq,
        pandas_gt=_gt_if_cat_eq,
        phrasings=(
            "For row {row}, return '{yes}' if {dim} equals '{value}', otherwise return '{no}'.",
            "In row {row}, if {dim} is {value} output '{yes}', else '{no}'.",
            "row {row}: if {dim}='{value}' -> '{yes}' else '{no}'",
            "Inspect the {dim} cell on row {row} and return '{yes}' when it matches '{value}', or '{no}' otherwise.",
            "Check if row {row} has {dim} set to '{value}'; return '{yes}' if so and '{no}' if not.",
            "Label row {row} as '{yes}' when {dim} is '{value}', otherwise '{no}'.",
            "Output '{yes}' for row {row} if {dim} matches '{value}', else output '{no}'.",
        ),
    ),
    FormulaTemplate(
        id="if_blank_fallback",
        category="logic",
        difficulty=2,
        functions=("IF",),
        required_column_types={"nullable": 1},
        builder=_build_if_blank_fallback,
        pandas_gt=_gt_if_blank_fallback,
        phrasings=(
            "In row {row}, return '{fallback}' if {col} is blank, otherwise return the value of {col}.",
            "For row {row}, show {col} or '{fallback}' if it's empty.",
            "row {row}: if {col} is blank return '{fallback}' else {col}",
            "Check whether the {col} cell in row {row} is empty; if so, display '{fallback}', otherwise keep its existing value.",
            "Replace a blank {col} in row {row} with '{fallback}', keeping non-blank values as-is.",
            "Return the {col} value on row {row}, falling back to '{fallback}' when blank.",
            "If {col} on row {row} is empty, output '{fallback}'; otherwise return {col}.",
        ),
    ),
    FormulaTemplate(
        id="and_two_conditions",
        category="logic",
        difficulty=2,
        functions=("AND",),
        required_column_types={"category": 1, "numeric": 1},
        builder=_build_and_two,
        pandas_gt=_gt_and_two,
        phrasings=(
            "For row {row}, return TRUE if {dim} is '{value}' and {measure} is at least {thresh}, else FALSE.",
            "Check in row {row} whether {dim} equals {value} AND {measure} >= {thresh}.",
            "row {row}: AND({dim}='{value}', {measure}>={thresh})",
            "Evaluate a boolean test on row {row} that is TRUE only when {dim} matches '{value}' and {measure} is {thresh} or higher.",
            "Is row {row} both in {dim} '{value}' and at least {thresh} for {measure}?",
            "Return TRUE/FALSE for row {row}: {dim} is '{value}' and {measure} >= {thresh}.",
            "Test whether both conditions hold on row {row}: {dim} = '{value}' and {measure} >= {thresh}.",
        ),
    ),
    FormulaTemplate(
        id="or_two_categories",
        category="logic",
        difficulty=2,
        functions=("OR",),
        required_column_types={"category": 1},
        builder=_build_or_two_cats,
        pandas_gt=_gt_or_two_cats,
        phrasings=(
            "For row {row}, return TRUE if {dim} is either '{val1}' or '{val2}', otherwise FALSE.",
            "Check in row {row} if {dim} is {val1} or {val2}.",
            "row {row}: OR({dim}='{val1}', {dim}='{val2}')",
            "Evaluate a boolean formula on row {row} returning TRUE when {dim} matches '{val1}' or '{val2}'.",
            "Is {dim} on row {row} equal to '{val1}' or '{val2}'?",
            "Return TRUE/FALSE for row {row} depending on whether {dim} is '{val1}' or '{val2}'.",
            "Test if row {row}'s {dim} is either '{val1}' or '{val2}'.",
        ),
    ),
    FormulaTemplate(
        id="if_and_combined",
        category="logic",
        difficulty=2,
        functions=("IF", "AND"),
        required_column_types={"category": 1, "numeric": 1},
        builder=_build_if_and,
        pandas_gt=_gt_if_and,
        phrasings=(
            "For row {row}, return '{yes}' if {dim} is '{value}' and {measure} exceeds {thresh}, otherwise '{no}'.",
            "In row {row}, mark as '{yes}' when {dim} is {value} and {measure} > {thresh}, else '{no}'.",
            "row {row}: if {dim}='{value}' and {measure}>{thresh} -> '{yes}' else '{no}'",
            "Evaluate both {dim} = '{value}' and {measure} > {thresh} on row {row}; output '{yes}' if both are true and '{no}' otherwise.",
            "Label row {row} '{yes}' only if {dim} equals '{value}' and {measure} is above {thresh}; otherwise '{no}'.",
            "If row {row} has {dim} '{value}' and {measure} strictly over {thresh}, return '{yes}', else '{no}'.",
            "Return '{yes}' on row {row} when {dim} is '{value}' AND {measure} > {thresh}, otherwise '{no}'.",
        ),
    ),
    FormulaTemplate(
        id="if_or_combined",
        category="logic",
        difficulty=2,
        functions=("IF", "OR"),
        required_column_types={"category": 1},
        builder=_build_if_or,
        pandas_gt=_gt_if_or,
        phrasings=(
            "For row {row}, return '{yes}' if {dim} is '{val1}' or '{val2}', otherwise '{no}'.",
            "In row {row}, label as '{yes}' when {dim} is {val1} or {val2}, else '{no}'.",
            "row {row}: if {dim} in ('{val1}','{val2}') -> '{yes}' else '{no}'",
            "Check row {row}'s {dim} cell; if it equals '{val1}' or '{val2}', output '{yes}', otherwise output '{no}'.",
            "Return '{yes}' for row {row} whenever {dim} is either '{val1}' or '{val2}', else '{no}'.",
            "Mark row {row} '{yes}' if {dim} matches '{val1}' or '{val2}', otherwise '{no}'.",
            "If row {row}'s {dim} is '{val1}' OR '{val2}', show '{yes}'; otherwise show '{no}'.",
        ),
    ),
    FormulaTemplate(
        id="ifs_three_tiers",
        category="logic",
        difficulty=3,
        functions=("IFS",),
        required_column_types={"numeric": 1},
        builder=_build_ifs_tiers,
        pandas_gt=_gt_ifs_tiers,
        phrasings=(
            "Using IFS on row {row}, classify {measure} as 'High' if >= {t_high}, 'Medium' if >= {t_mid}, and 'Low' otherwise.",
            "Bucket row {row}'s {measure} into 'High' (>= {t_high}), 'Medium' (>= {t_mid}), or 'Low' using IFS.",
            "row {row} IFS {measure}: >={t_high}->High, >={t_mid}->Medium, else Low",
            "Write an IFS formula for row {row} that returns 'High' when {measure} is at least {t_high}, 'Medium' when at least {t_mid}, and 'Low' for all lower values.",
            "Assign a tier to {measure} in row {row} with IFS: {t_high}+ is 'High', {t_mid}+ is 'Medium', below is 'Low'.",
            "Use IFS on row {row} to map {measure} >= {t_high} to 'High', >= {t_mid} to 'Medium', and everything else to 'Low'.",
            "Categorize {measure} on row {row} via IFS: 'High' (>= {t_high}), 'Medium' (>= {t_mid}), 'Low' (otherwise).",
        ),
    ),
    # ==================== 4. LOOKUP (7) ====================
    FormulaTemplate(
        id="vlookup_exact_by_key",
        category="lookup",
        difficulty=2,
        functions=("VLOOKUP",),
        required_column_types={"key": 1, "non_key": 1},
        builder=_build_vlookup,
        pandas_gt=_gt_lookup_exact,
        excel_quirk=(
            "If the target cell is blank, Excel VLOOKUP returns 0 while `formulas` returns empty; "
            "the builder selects non-null target cells."
        ),
        phrasings=(
            "Use VLOOKUP to find the {ret_col} for {key_col} '{key_val}'.",
            "Look up {ret_col} where {key_col} is {key_val} using VLOOKUP.",
            "vlookup {ret_col} for {key_col}='{key_val}'",
            "Write an exact-match VLOOKUP formula that searches {key_col} for '{key_val}' and returns the corresponding {ret_col}.",
            "Fetch {ret_col} for '{key_val}' in {key_col} via VLOOKUP.",
            "Find the exact {ret_col} matching {key_col} '{key_val}' with VLOOKUP.",
            "Retrieve {ret_col} for record '{key_val}' ({key_col}) using VLOOKUP.",
        ),
    ),
    FormulaTemplate(
        id="xlookup_exact_by_key",
        category="lookup",
        difficulty=2,
        functions=("XLOOKUP",),
        required_column_types={"key": 1, "non_key": 1},
        builder=_build_xlookup,
        pandas_gt=_gt_lookup_exact,
        excel_quirk=(
            "If the target cell is blank, Excel XLOOKUP returns 0 while `formulas` returns empty; "
            "the builder selects non-null target cells."
        ),
        phrasings=(
            "Use XLOOKUP to retrieve {ret_col} for {key_col} '{key_val}'.",
            "Find {ret_col} where {key_col} is {key_val} using XLOOKUP.",
            "xlookup {ret_col} for {key_col}='{key_val}'",
            "Write an XLOOKUP formula that looks up '{key_val}' in {key_col} and returns the matching value from {ret_col}.",
            "Get {ret_col} for '{key_val}' ({key_col}) with XLOOKUP.",
            "Look up {key_col} '{key_val}' via XLOOKUP and return {ret_col}.",
            "Use XLOOKUP to pull {ret_col} for record '{key_val}'.",
        ),
    ),
    FormulaTemplate(
        id="xlookup_with_default",
        category="lookup",
        difficulty=2,
        functions=("XLOOKUP",),
        required_column_types={"key": 1, "non_key": 1},
        builder=_build_xlookup_default,
        pandas_gt=_gt_lookup_exact,
        phrasings=(
            "Use XLOOKUP to find {ret_col} for {key_col} '{key_val}', returning '{fallback}' if not found.",
            "Look up {ret_col} for {key_col} {key_val} with XLOOKUP, or show '{fallback}' when missing.",
            "xlookup {ret_col} where {key_col}='{key_val}' default '{fallback}'",
            "Search {key_col} for '{key_val}' using XLOOKUP to return {ret_col}, and fall back to '{fallback}' if no match exists.",
            "Fetch {ret_col} for '{key_val}' via XLOOKUP with '{fallback}' as the not-found value.",
            "With XLOOKUP, get {ret_col} for {key_col} '{key_val}', defaulting to '{fallback}'.",
            "Return {ret_col} for '{key_val}' ({key_col}) using XLOOKUP, or '{fallback}' if missing.",
        ),
    ),
    FormulaTemplate(
        id="index_match_exact",
        category="lookup",
        difficulty=2,
        functions=("INDEX", "MATCH"),
        required_column_types={"key": 1, "non_key": 1},
        builder=_build_index_match,
        pandas_gt=_gt_lookup_exact,
        excel_quirk=(
            "If the target cell is blank, Excel INDEX/MATCH returns 0 while `formulas` returns empty; "
            "the builder selects non-null target cells."
        ),
        phrasings=(
            "Use INDEX and MATCH to retrieve {ret_col} for {key_col} '{key_val}'.",
            "Look up {ret_col} where {key_col} equals {key_val} using INDEX/MATCH.",
            "index/match {ret_col} for {key_col}='{key_val}'",
            "Combine INDEX and exact-match MATCH to locate '{key_val}' in {key_col} and return the corresponding {ret_col}.",
            "Find {ret_col} for '{key_val}' ({key_col}) via INDEX and MATCH.",
            "With INDEX and MATCH, pull the {ret_col} for record '{key_val}'.",
            "Get {ret_col} matching {key_col} '{key_val}' using INDEX+MATCH.",
        ),
    ),
    FormulaTemplate(
        id="match_row_position",
        category="lookup",
        difficulty=2,
        functions=("MATCH",),
        required_column_types={"key": 1},
        builder=_build_match_pos,
        pandas_gt=_gt_match_pos,
        phrasings=(
            "Find the 1-based position of '{key_val}' within the {key_col} data range using MATCH.",
            "Which position in the {key_col} data rows holds {key_val}?",
            "match '{key_val}' in {key_col}",
            "Return the exact-match index of '{key_val}' inside the {key_col} column (excluding the header row).",
            "Locate the relative row number of '{key_val}' in {key_col} with MATCH.",
            "Use MATCH to get the position of '{key_val}' in the {key_col} data column.",
            "At what 1-based index does '{key_val}' appear in {key_col}?",
        ),
    ),
    FormulaTemplate(
        id="index_nth_row",
        category="lookup",
        difficulty=1,
        functions=("INDEX",),
        required_column_types={"key": 1},
        builder=_build_index_nth,
        pandas_gt=_gt_index_nth,
        phrasings=(
            "Use INDEX to retrieve entry #{pos} from the {col} data column.",
            "What is the {pos}th data value in {col}?",
            "index {col} position {pos}",
            "Return the value located at 1-based position {pos} in the {col} data range (excluding headers).",
            "Get item {pos} of the {col} column using INDEX.",
            "Pull the {pos}th record's {col} using INDEX.",
            "Fetch entry number {pos} from {col} with INDEX.",
        ),
    ),
    FormulaTemplate(
        id="iferror_vlookup_safe",
        category="lookup",
        difficulty=3,
        functions=("IFERROR", "VLOOKUP"),
        required_column_types={"key": 1, "non_key": 1},
        builder=_build_iferror_vlookup,
        pandas_gt=_gt_lookup_exact,
        phrasings=(
            "Use IFERROR and VLOOKUP to fetch {ret_col} for {key_col} '{key_val}', returning '{fallback}' if missing.",
            "Safely VLOOKUP {ret_col} for {key_col} {key_val}, or show '{fallback}' on error.",
            "iferror(vlookup {ret_col} for {key_col}='{key_val}', '{fallback}')",
            "Wrap an exact-match VLOOKUP of '{key_val}' in {key_col} (returning {ret_col}) inside IFERROR so missing keys return '{fallback}'.",
            "Look up {ret_col} for '{key_val}' via VLOOKUP and default to '{fallback}' if not found.",
            "Return {ret_col} for {key_col} '{key_val}' using VLOOKUP, falling back to '{fallback}' on #N/A.",
            "Get {ret_col} for record '{key_val}' with IFERROR + VLOOKUP, returning '{fallback}' when absent.",
        ),
    ),
    # ==================== 5. TEXT (11) ====================
    FormulaTemplate(
        id="upper_cell",
        category="text",
        difficulty=1,
        functions=("UPPER",),
        required_column_types={"text": 1},
        builder=_build_single_text_fn("UPPER"),
        pandas_gt=_gt_upper,
        phrasings=(
            "Convert the {col} value in row {row} to uppercase.",
            "Make {col} on row {row} all caps.",
            "uppercase {col} row {row}",
            "Return an all-uppercase version of the text stored in {col} at row {row}.",
            "Transform row {row}'s {col} to UPPERCASE.",
            "Capitalize every letter in {col} on row {row}.",
            "Get {col} in row {row} in upper case.",
        ),
    ),
    FormulaTemplate(
        id="lower_cell",
        category="text",
        difficulty=1,
        functions=("LOWER",),
        required_column_types={"text": 1},
        builder=_build_single_text_fn("LOWER"),
        pandas_gt=_gt_lower,
        phrasings=(
            "Convert the {col} value in row {row} to lowercase.",
            "Make {col} on row {row} all lowercase.",
            "lowercase {col} row {row}",
            "Return an all-lowercase copy of the text in {col} at row {row}.",
            "Change row {row}'s {col} to small letters.",
            "Lowercase the {col} cell on row {row}.",
            "Get {col} in row {row} in lower case.",
        ),
    ),
    FormulaTemplate(
        id="proper_cell",
        category="text",
        difficulty=1,
        functions=("PROPER",),
        required_column_types={"text": 1},
        builder=_build_single_text_fn("PROPER"),
        pandas_gt=_gt_proper,
        excel_quirk=(
            "Excel PROPER capitalizes letters after any non-letter character (e.g., hyphens or "
            "apostrophes); pandas_gt replicates Excel's regex rule rather than str.title()."
        ),
        phrasings=(
            "Convert the {col} value in row {row} to proper (title) case.",
            "Title-case {col} on row {row}.",
            "proper {col} row {row}",
            "Capitalize the first letter of each word in the {col} cell at row {row} using PROPER.",
            "Format row {row}'s {col} in proper case.",
            "Apply PROPER case to {col} in row {row}.",
            "Return {col} on row {row} with each word capitalized.",
        ),
    ),
    FormulaTemplate(
        id="trim_cell",
        category="text",
        difficulty=1,
        functions=("TRIM",),
        required_column_types={"text": 1},
        builder=_build_single_text_fn("TRIM"),
        pandas_gt=_gt_trim,
        phrasings=(
            "Remove extra leading, trailing, and repeated spaces from {col} in row {row}.",
            "Trim whitespace from {col} on row {row}.",
            "trim {col} row {row}",
            "Clean up extra spaces in the {col} cell at row {row} using TRIM.",
            "Strip surrounding and duplicate spaces from row {row}'s {col}.",
            "Use TRIM on {col} in row {row}.",
            "Return {col} from row {row} with excess spaces removed.",
        ),
    ),
    FormulaTemplate(
        id="len_cell",
        category="text",
        difficulty=1,
        functions=("LEN",),
        required_column_types={"text": 1},
        builder=_build_single_text_fn("LEN"),
        pandas_gt=_gt_len,
        phrasings=(
            "Return the character length of {col} in row {row}.",
            "How many characters are in {col} on row {row}?",
            "len {col} row {row}",
            "Count the total number of characters (including spaces) in the {col} cell at row {row}.",
            "Find the text length of row {row}'s {col}.",
            "Measure how long {col} is in row {row}.",
            "Get the character count of {col} at row {row}.",
        ),
    ),
    FormulaTemplate(
        id="left_n_chars",
        category="text",
        difficulty=1,
        functions=("LEFT",),
        required_column_types={"text": 1},
        builder=_build_left_right("LEFT"),
        pandas_gt=_gt_left,
        phrasings=(
            "Extract the first {n} characters of {col} in row {row}.",
            "Get the leftmost {n} characters from {col} on row {row}.",
            "left {n} chars of {col} row {row}",
            "Return a substring consisting of the first {n} characters from the {col} cell at row {row}.",
            "Take the leading {n} characters of row {row}'s {col}.",
            "Pull the first {n} letters/characters of {col} in row {row}.",
            "Use LEFT to grab {n} characters from {col} at row {row}.",
        ),
    ),
    FormulaTemplate(
        id="right_n_chars",
        category="text",
        difficulty=1,
        functions=("RIGHT",),
        required_column_types={"text": 1},
        builder=_build_left_right("RIGHT"),
        pandas_gt=_gt_right,
        phrasings=(
            "Extract the last {n} characters of {col} in row {row}.",
            "Get the rightmost {n} characters from {col} on row {row}.",
            "right {n} chars of {col} row {row}",
            "Return a substring containing the final {n} characters of the {col} cell at row {row}.",
            "Take the trailing {n} characters of row {row}'s {col}.",
            "Pull the last {n} characters from {col} in row {row}.",
            "Use RIGHT to get the final {n} characters of {col} at row {row}.",
        ),
    ),
    FormulaTemplate(
        id="mid_substring",
        category="text",
        difficulty=2,
        functions=("MID",),
        required_column_types={"text": 1},
        builder=_build_mid,
        pandas_gt=_gt_mid,
        phrasings=(
            "Extract {length} characters from {col} in row {row} starting at position {start}.",
            "Get a substring of {col} on row {row} from character {start} of length {length}.",
            "mid {col} row {row} start {start} len {length}",
            "Use MID to slice {length} characters out of the {col} cell at row {row}, beginning at 1-based character {start}.",
            "Pull {length} characters starting at index {start} from row {row}'s {col}.",
            "Slice {col} at row {row} starting at position {start} for {length} characters.",
            "Return {length} characters of {col} in row {row} beginning at character {start}.",
        ),
    ),
    FormulaTemplate(
        id="concat_two_cells_sep",
        category="text",
        difficulty=2,
        functions=("CONCAT",),
        required_column_types={"text": 1, "category": 1},
        builder=_build_concat_two,
        pandas_gt=_gt_concat_two,
        phrasings=(
            "Concatenate {col1} and {col2} in row {row} separated by '{sep}' using CONCAT.",
            "Join {col1} and {col2} on row {row} with '{sep}' between them.",
            "concat {col1} + '{sep}' + {col2} row {row}",
            "Combine the {col1} and {col2} values from row {row} into a single string with '{sep}' in between using CONCAT.",
            "Merge row {row}'s {col1} and {col2} separated by '{sep}'.",
            "Use CONCAT to combine {col1}, '{sep}', and {col2} on row {row}.",
            "Build one text value from {col1} and {col2} in row {row} joined by '{sep}'.",
        ),
    ),
    FormulaTemplate(
        id="textjoin_range_delim",
        category="text",
        difficulty=2,
        functions=("TEXTJOIN",),
        required_column_types={"text": 1},
        builder=_build_textjoin_slice,
        pandas_gt=_gt_textjoin_slice,
        phrasings=(
            "Join {col} values from rows {start_row} to {end_row} with '{delim}', ignoring blanks.",
            "Combine {col} in rows {start_row} through {end_row} separated by '{delim}' using TEXTJOIN.",
            "textjoin {col} rows {start_row}:{end_row} delim '{delim}' skip blanks",
            "Use TEXTJOIN to concatenate all non-empty entries of {col} from row {start_row} to row {end_row} separated by '{delim}'.",
            "List the {col} entries from row {start_row} to {end_row} joined by '{delim}' (skip empty cells).",
            "With TEXTJOIN, merge {col} rows {start_row}–{end_row} using delimiter '{delim}' and ignoring blanks.",
            "Create a '{delim}'-separated string of non-blank {col} cells from row {start_row} to row {end_row}.",
        ),
    ),
    FormulaTemplate(
        id="text_format_number",
        category="text",
        difficulty=2,
        functions=("TEXT",),
        required_column_types={"decimal": 1},
        builder=_build_text_format_num,
        pandas_gt=_gt_text_format_num,
        excel_quirk=(
            'TEXT(value, "0.00") depends on the decimal separator of Excel\'s UI locale '
            "(dot in en-US, comma in some European locales)."
        ),
        phrasings=(
            "Format {measure} in row {row} as text with exactly two decimal places ('0.00').",
            "Convert row {row}'s {measure} to a 2-decimal text string using TEXT.",
            "text({measure} row {row}, '0.00')",
            "Use the TEXT function to display the {measure} number on row {row} formatted with pattern '0.00'.",
            "Turn {measure} in row {row} into text formatted to 2 decimal places.",
            "Format row {row} {measure} as a string like '0.00' via TEXT.",
            "Return {measure} on row {row} formatted as text using '0.00'.",
        ),
    ),
    # ==================== 6. DATE (8) ====================
    FormulaTemplate(
        id="year_from_date",
        category="date",
        difficulty=1,
        functions=("YEAR",),
        required_column_types={"date": 1},
        builder=_build_date_part("YEAR"),
        pandas_gt=_gt_year,
        phrasings=(
            "Extract the year from {date_col} in row {row}.",
            "What year is {date_col} on row {row}?",
            "year of {date_col} row {row}",
            "Return the 4-digit calendar year of the date stored in {date_col} at row {row}.",
            "Get the year component of row {row}'s {date_col}.",
            "Pull the year from {date_col} in row {row}.",
            "Find the year number for {date_col} on row {row}.",
        ),
    ),
    FormulaTemplate(
        id="month_from_date",
        category="date",
        difficulty=1,
        functions=("MONTH",),
        required_column_types={"date": 1},
        builder=_build_date_part("MONTH"),
        pandas_gt=_gt_month,
        phrasings=(
            "Extract the month number (1–12) from {date_col} in row {row}.",
            "What month is {date_col} on row {row}?",
            "month of {date_col} row {row}",
            "Return the numeric month (1 to 12) of the date recorded in {date_col} at row {row}.",
            "Get the month component of row {row}'s {date_col}.",
            "Pull the month number from {date_col} in row {row}.",
            "Find which month number {date_col} falls in on row {row}.",
        ),
    ),
    FormulaTemplate(
        id="day_from_date",
        category="date",
        difficulty=1,
        functions=("DAY",),
        required_column_types={"date": 1},
        builder=_build_date_part("DAY"),
        pandas_gt=_gt_day,
        phrasings=(
            "Extract the day of the month from {date_col} in row {row}.",
            "What day number is {date_col} on row {row}?",
            "day of {date_col} row {row}",
            "Return the day-of-month integer (1 to 31) from the date in {date_col} at row {row}.",
            "Get the day component of row {row}'s {date_col}.",
            "Pull the calendar day from {date_col} in row {row}.",
            "Find the day of month for {date_col} on row {row}.",
        ),
    ),
    FormulaTemplate(
        id="date_construct",
        category="date",
        difficulty=2,
        functions=("DATE",),
        required_column_types={"date": 1},
        builder=_build_date_construct,
        pandas_gt=_gt_date_construct,
        phrasings=(
            "Construct an Excel date for {iso} using the DATE function.",
            "Build the date for year {year}, month {month}, day {day}.",
            "DATE({year}, {month}, {day})",
            "Create a valid Excel date value representing {iso} with DATE(year, month, day).",
            "Return the Excel date for {year}-{month}-{day} using DATE.",
            "Make a date value for year {year}, month {month}, and day {day}.",
            "Use DATE to produce the date {iso}.",
        ),
    ),
    FormulaTemplate(
        id="countif_date_after",
        category="date",
        difficulty=3,
        functions=("COUNTIF", "DATE"),
        required_column_types={"date": 1},
        builder=_build_countif_date_after,
        pandas_gt=_gt_countif_date_after,
        phrasings=(
            "Count how many rows have a {date_col} strictly after {iso}.",
            "How many records occur after {iso} in {date_col}?",
            "count {date_col} > {iso}",
            "Use COUNTIF with DATE to count all entries whose {date_col} is strictly later than {iso}.",
            "Find the number of rows with {date_col} after {iso}.",
            "Count records dated after {iso} based on {date_col}.",
            "How many {date_col} dates fall past {iso}?",
        ),
    ),
    FormulaTemplate(
        id="text_date_year_month",
        category="date",
        difficulty=3,
        functions=("TEXT",),
        required_column_types={"date": 1},
        builder=_build_text_date_ym,
        pandas_gt=_gt_text_date_ym,
        excel_quirk=(
            'TEXT(date, "yyyy-mm") uses English date format tokens ("y", "m"), which differ '
            "in some non-English localized Excel installations."
        ),
        phrasings=(
            "Format {date_col} in row {row} as 'yyyy-mm' text using TEXT.",
            "Turn row {row}'s {date_col} into a YYYY-MM string.",
            "text({date_col} row {row}, 'yyyy-mm')",
            "Use the TEXT function to extract the year and zero-padded month ('yyyy-mm') from {date_col} at row {row}.",
            "Convert {date_col} on row {row} to 'yyyy-mm' format.",
            "Display row {row}'s {date_col} as a 'yyyy-mm' label via TEXT.",
            "Get the 'yyyy-mm' string for {date_col} in row {row}.",
        ),
    ),
    FormulaTemplate(
        id="countifs_cat_and_date_after",
        category="date",
        difficulty=3,
        functions=("COUNTIFS", "DATE"),
        required_column_types={"category": 1, "date": 1},
        builder=_build_countifs_cat_date,
        pandas_gt=_gt_countifs_cat_date,
        phrasings=(
            "Count rows where {dim} is '{value}' and {date_col} is strictly after {iso}.",
            "How many '{value}' ({dim}) records are dated after {iso} in {date_col}?",
            "countifs {dim}='{value}' and {date_col} > {iso}",
            "Use COUNTIFS with DATE to count all rows matching {dim} = '{value}' whose {date_col} falls after {iso}.",
            "Find the count of records for {dim} '{value}' occurring after {iso} ({date_col}).",
            "Count entries with {dim} equal to '{value}' and {date_col} later than {iso}.",
            "How many rows match {dim} = '{value}' with {date_col} > {iso}?",
        ),
    ),
    FormulaTemplate(
        id="sumifs_cat_and_date_after",
        category="date",
        difficulty=3,
        functions=("SUMIFS", "DATE"),
        required_column_types={"numeric": 1, "category": 1, "date": 1},
        builder=_build_sumifs_cat_date,
        pandas_gt=_gt_sumifs_cat_date,
        phrasings=(
            "Sum {measure} where {dim} is '{value}' and {date_col} is on or after {iso}.",
            "What is total {measure} for {dim} '{value}' starting from {iso} ({date_col})?",
            "sumifs {measure}: {dim}='{value}', {date_col} >= {iso}",
            "Use SUMIFS with DATE to total {measure} across rows matching {dim} = '{value}' whose {date_col} is {iso} or later.",
            "Calculate total {measure} for '{value}' in {dim} on or after {iso}.",
            "Get the sum of {measure} filtered by {dim} = '{value}' and {date_col} >= {iso}.",
            "Total {measure} for {dim} '{value}' with {date_col} from {iso} onward.",
        ),
    ),
    # ==================== 7. MATH & COMPOSITION (6) ====================
    FormulaTemplate(
        id="round_decimal_cell",
        category="math_and_composition",
        difficulty=1,
        functions=("ROUND",),
        required_column_types={"decimal": 1},
        builder=_build_round_cell,
        pandas_gt=_gt_round_cell,
        excel_quirk=(
            "Excel ROUND uses half-away-from-zero (ROUND(2.5,0)=3), unlike Python's built-in "
            "round() which uses half-to-even; pandas_gt uses Decimal ROUND_HALF_UP to match Excel."
        ),
        phrasings=(
            "Round {measure} in row {row} to {digits} decimal place(s).",
            "Round row {row}'s {measure} to {digits} decimal(s).",
            "round {measure} row {row} to {digits}",
            "Return the value of {measure} on row {row} rounded to {digits} decimal place(s) using ROUND.",
            "Give me {measure} at row {row} rounded to {digits} decimal digit(s).",
            "Apply ROUND to {measure} in row {row} with {digits} decimal place(s).",
            "What is {measure} on row {row} rounded to {digits} place(s)?",
        ),
    ),
    FormulaTemplate(
        id="round_average_column",
        category="math_and_composition",
        difficulty=2,
        functions=("ROUND", "AVERAGE"),
        required_column_types={"numeric": 1},
        builder=_build_round_avg,
        pandas_gt=_gt_round_avg,
        excel_quirk=(
            "Uses half-away-from-zero rounding (Excel ROUND); float representation noise near "
            "exact halfways could rarely differ by 1 ULP."
        ),
        phrasings=(
            "Calculate the average of {measure} rounded to {digits} decimal place(s).",
            "What is the mean {measure}, rounded to {digits} decimal(s)?",
            "round(avg({measure}), {digits})",
            "Compute the arithmetic mean of the {measure} column and round the result to {digits} decimal place(s).",
            "Find the average {measure} and round it to {digits} digit(s).",
            "Give me the rounded mean of {measure} ({digits} decimal places).",
            "Average the {measure} column and round to {digits} decimal place(s).",
        ),
    ),
    FormulaTemplate(
        id="iferror_safe_division",
        category="math_and_composition",
        difficulty=2,
        functions=("IFERROR",),
        required_column_types={"numeric": 2},
        builder=_build_iferror_div,
        pandas_gt=_gt_iferror_div,
        phrasings=(
            "In row {row}, divide {m1} by {m2} and return 0 if an error occurs.",
            "Safely divide {m1} by {m2} on row {row}, defaulting to 0 on divide-by-zero.",
            "row {row}: iferror({m1} / {m2}, 0)",
            "Compute {m1} divided by {m2} for row {row}, wrapped in IFERROR so any division error outputs 0.",
            "Return {m1} / {m2} on row {row}, or 0 if division fails.",
            "Calculate the ratio of {m1} to {m2} in row {row} with 0 as an IFERROR fallback.",
            "Divide row {row}'s {m1} by {m2}, returning 0 on error.",
        ),
    ),
    FormulaTemplate(
        id="round_sumif_share_pct",
        category="math_and_composition",
        difficulty=3,
        functions=("IFERROR", "ROUND", "SUMIF", "SUM"),
        required_column_types={"numeric": 1, "category": 1},
        builder=_build_round_sumif_share,
        pandas_gt=_gt_round_sumif_share,
        excel_quirk=(
            "Combines SUMIF/SUM with ROUND(..., 4) and IFERROR; half-away-from-zero rounding used."
        ),
        phrasings=(
            "Calculate {dim} '{value}' share of total {measure}, rounded to 4 decimal places (0 on error).",
            "What fraction of total {measure} comes from {dim} '{value}', rounded to 4 decimals (fallback 0)?",
            "iferror(round(sumif {measure} where {dim}='{value}' / sum {measure}, 4), 0)",
            "Compute the proportion of total {measure} attributed to {dim} = '{value}', rounded to 4 decimal places with IFERROR returning 0.",
            "Divide total {measure} for '{value}' ({dim}) by grand total {measure}, rounded to 4 decimals, or 0 on error.",
            "Find the 4-decimal share of {measure} held by {dim} '{value}', safely returning 0 on division error.",
            "Return '{value}' ({dim}) fraction of overall {measure}, rounded to 4 decimals and wrapped in IFERROR(..., 0).",
        ),
    ),
    FormulaTemplate(
        id="if_sumif_exceeds_target",
        category="math_and_composition",
        difficulty=3,
        functions=("IF", "SUMIF"),
        required_column_types={"numeric": 1, "category": 1},
        builder=_build_if_sumif_target,
        pandas_gt=_gt_if_sumif_target,
        phrasings=(
            "Return '{yes}' if total {measure} for {dim} '{value}' exceeds {target}, otherwise '{no}'.",
            "Check if {dim} '{value}' has total {measure} above {target}: show '{yes}' else '{no}'.",
            "if sum({measure} where {dim}='{value}') > {target} -> '{yes}' else '{no}'",
            "Sum {measure} for all rows with {dim} = '{value}'; if that total is strictly greater than {target}, output '{yes}', otherwise '{no}'.",
            "Did {dim} '{value}' beat a {measure} target of {target}? Return '{yes}' or '{no}'.",
            "Output '{yes}' when the SUMIF of {measure} for {dim} '{value}' is over {target}, else '{no}'.",
            "Compare total {measure} for {dim} '{value}' against {target} and return '{yes}' if greater, otherwise '{no}'.",
        ),
    ),
    FormulaTemplate(
        id="iferror_index_match_round",
        category="math_and_composition",
        difficulty=3,
        functions=("IFERROR", "ROUND", "INDEX", "MATCH"),
        required_column_types={"key": 1, "decimal": 1},
        builder=_build_iferror_index_match_round,
        pandas_gt=_gt_iferror_index_match_round,
        phrasings=(
            "Look up {measure} for {key_col} '{key_val}' using INDEX/MATCH, round to {digits} decimal(s), and return 0 if not found.",
            "Safely INDEX/MATCH {measure} for {key_col} {key_val}, rounded to {digits} place(s) (0 on error).",
            "iferror(round(index/match {measure} for {key_col}='{key_val}', {digits}), 0)",
            "Use INDEX and MATCH to retrieve {measure} for record '{key_val}' in {key_col}, round it to {digits} decimal place(s), and wrap with IFERROR returning 0.",
            "Fetch and round {measure} (to {digits} decimals) for {key_col} '{key_val}' via INDEX+MATCH, defaulting to 0 if missing.",
            "Return the rounded {measure} ({digits} decimals) for '{key_val}' ({key_col}) using IFERROR, ROUND, INDEX, and MATCH.",
            "Find {measure} for '{key_val}' with INDEX/MATCH, round to {digits} decimal(s), or return 0 on error.",
        ),
    ),
)


def get_templates() -> tuple[FormulaTemplate, ...]:
    """Return all registered formula templates."""
    return TEMPLATES


def get_template_by_id(template_id: str) -> FormulaTemplate:
    for tpl in TEMPLATES:
        if tpl.id == template_id:
            return tpl
    raise KeyError(f"Unknown template id: {template_id!r}")


def template_summary() -> dict[str, Any]:
    """Return counts by category and difficulty, covered functions, and flagged quirks."""
    by_cat_diff: dict[str, dict[int, int]] = {}
    diff_totals: Counter[int] = Counter()
    funcs_used: set[str] = set()
    quirks: list[dict[str, str]] = []

    for tpl in TEMPLATES:
        bucket = by_cat_diff.setdefault(tpl.category, {1: 0, 2: 0, 3: 0})
        bucket[tpl.difficulty] += 1
        diff_totals[tpl.difficulty] += 1
        funcs_used.update(tpl.functions)
        if tpl.excel_quirk:
            quirks.append({"id": tpl.id, "category": tpl.category, "quirk": tpl.excel_quirk})

    return {
        "total_templates": len(TEMPLATES),
        "by_category_difficulty": by_cat_diff,
        "by_difficulty": {1: diff_totals[1], 2: diff_totals[2], 3: diff_totals[3]},
        "functions_covered": sorted(funcs_used),
        "quirks": quirks,
    }
