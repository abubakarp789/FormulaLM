"""Build leakage-free, execution-verified JSONL datasets (train, val, test_synthetic).

Split rules:
- ``test_synthetic`` uses ONLY held-out sheets (manifest ``split == "test"``) AND
  2 reserved phrasing patterns per template that never appear in ``train`` or ``val``.
- ``val`` uses training sheets (manifest ``split == "train"``) AND 1 reserved phrasing
  pattern per template that never appears in ``train`` or ``test_synthetic``.
- ``train`` uses training sheets AND the remaining phrasing patterns, with optional
  hand-written semantic-preserving rewrite rules logged per example in ``augmentation``.
- Every unique ``(sheet_id, formula)`` is executed via ``src.eval.executor.run_formula``
  and verified against its independent pandas ground truth via ``values_equal``.
  Failures are dropped and reported.

CLI usage:
    uv run python -m src.data.build_dataset
    uv run python -m src.data.build_dataset --train 8000 --val 500 --test 500 --workers 4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from formulalm.config import load_config
from formulalm.logging_utils import get_logger
from src.data.templates import (
    TEMPLATES,
    FormulaTemplate,
    SheetContext,
    load_sheet_contexts,
)
from src.eval.executor import run_formula
from src.eval.normalize import values_equal

SYSTEM_PROMPT = (
    "You are FormulaLM. Given a spreadsheet schema and a user request, reply with only "
    "the Excel formula starting with '='. No explanation, no markdown."
)

# ---------------------------------------------------------------------------
# Schema & chat message formatting (shared across dataset, eval and demo)
# ---------------------------------------------------------------------------


def format_schema_text(ctx: SheetContext) -> str:
    """Format a sheet's schema compactly and unambiguously for the model prompt."""
    lines = [
        f"Sheet: {ctx.sheet_id} (rows 2..{ctx.last_row})",
        "Columns:",
    ]
    for col in ctx.columns:
        lines.append(f"{col.letter}: {col.name} ({col.col_type})")
    return "\n".join(lines)


def build_user_prompt(schema_text: str, request: str) -> str:
    return f"{schema_text}\n\nRequest: {request}"


def build_messages(schema_text: str, request: str, formula: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(schema_text, request)},
        {"role": "assistant", "content": formula},
    ]


# ---------------------------------------------------------------------------
# Hand-written paraphrase rewrite rules (train augmentation only, logged)
# ---------------------------------------------------------------------------

_IMPERATIVE_START_RE = re.compile(
    r"^(Calculate|Compute|Find|Count|Sum|Get|Return|Extract|Convert|Round|Join|Combine|"
    r"Average|Total|Add|Show|Fetch|Pull|Look up|Check|Use|Replace|Create|Build|Measure|"
    r"Display|Format|Make|Classify|Label|Assign|Categorize|List|Divide|Compare|Safely)\b"
)


def _lower_first_safe(text: str) -> str:
    """Lowercase the first character unless it begins an uppercase acronym/function name."""
    if len(text) >= 2 and text[0].isupper() and text[1].isupper():
        return text
    return text[0].lower() + text[1:] if text else text


def _swap_word(text: str, a: str, b: str) -> str:
    pattern = re.compile(rf"\b({re.escape(a)}|{re.escape(b)})\b")

    def _rep(m: re.Match[str]) -> str:
        word = m.group(1)
        return b if word == a else a

    return pattern.sub(_rep, text, count=1)


def _rule_prefix_please(req: str) -> str:
    if not _IMPERATIVE_START_RE.match(req):
        return req
    return f"Please {_lower_first_safe(req)}"


def _rule_prefix_excel_formula(req: str) -> str:
    if not _IMPERATIVE_START_RE.match(req):
        return req
    return f"Write an Excel formula to {_lower_first_safe(req)}"


def _rule_prefix_formula_colon(req: str) -> str:
    if req.lower().startswith(("excel formula", "formula:", "give me the excel")):
        return req
    return f"Excel formula: {req}"


def _rule_suffix_formula_only(req: str) -> str:
    base = req.rstrip(".")
    if base.endswith("?"):
        return f"{base} Reply with the Excel formula only."
    return f"{base} (Excel formula only)."


def _rule_swap_records_rows(req: str) -> str:
    return _swap_word(req, "records", "rows")


def _rule_swap_calculate_compute(req: str) -> str:
    out = _swap_word(req, "Calculate", "Compute")
    if out != req:
        return out
    return _swap_word(req, "calculate", "compute")


def _rule_swap_sheet_table(req: str) -> str:
    return _swap_word(req, "sheet", "table")


def _rule_swap_column_field(req: str) -> str:
    return _swap_word(req, "column", "field")


def _rule_strip_period(req: str) -> str:
    return req[:-1] if req.endswith(".") else req


def _rule_prefix_need_formula(req: str) -> str:
    if not _IMPERATIVE_START_RE.match(req):
        return req
    return f"I need an Excel formula to {_lower_first_safe(req)}"


REWRITE_RULES: tuple[tuple[str, Any], ...] = (
    ("prefix_please", _rule_prefix_please),
    ("prefix_excel_formula", _rule_prefix_excel_formula),
    ("prefix_formula_colon", _rule_prefix_formula_colon),
    ("prefix_need_formula", _rule_prefix_need_formula),
    ("suffix_formula_only", _rule_suffix_formula_only),
    ("swap_records_rows", _rule_swap_records_rows),
    ("swap_calculate_compute", _rule_swap_calculate_compute),
    ("swap_sheet_table", _rule_swap_sheet_table),
    ("swap_column_field", _rule_swap_column_field),
    ("strip_period", _rule_strip_period),
)


def apply_rewrite_rule(request: str, rng: random.Random) -> tuple[str, str]:
    """Try a random hand-written rewrite rule; return ``(new_request, augmentation_tag)``."""
    order = list(REWRITE_RULES)
    rng.shuffle(order)
    for name, fn in order:
        rewritten = fn(request)
        if rewritten != request:
            return rewritten, f"rule:{name}"
    return request, "none"


# ---------------------------------------------------------------------------
# Phrasing-index split & balanced category/difficulty quota planner
# ---------------------------------------------------------------------------


def assign_phrasing_splits(
    templates: tuple[FormulaTemplate, ...] = TEMPLATES,
    *,
    seed: int = 42,
    reserved_test: int = 2,
    reserved_val: int = 1,
) -> dict[str, dict[str, tuple[int, ...]]]:
    """Partition each template's phrasing indices disjointly into train / val / test."""
    rng = random.Random(seed)
    plan: dict[str, dict[str, tuple[int, ...]]] = {}
    for tpl in templates:
        n = len(tpl.phrasings)
        if n < reserved_test + reserved_val + 2:
            raise ValueError(
                f"Template {tpl.id} has only {n} phrasings; need at least "
                f"{reserved_test + reserved_val + 2}"
            )
        indices = list(range(n))
        rng.shuffle(indices)
        test_idx = tuple(sorted(indices[:reserved_test]))
        val_idx = tuple(sorted(indices[reserved_test : reserved_test + reserved_val]))
        train_idx = tuple(sorted(indices[reserved_test + reserved_val :]))
        plan[tpl.id] = {"train": train_idx, "val": val_idx, "test": test_idx}
    return plan


def _distribute_int(total: int, keys: list[Any]) -> dict[Any, int]:
    """Divide ``total`` as evenly as possible across ``keys``."""
    base, rem = divmod(total, len(keys))
    return {k: base + (1 if i < rem else 0) for i, k in enumerate(keys)}


def plan_template_quotas(
    total: int,
    templates: tuple[FormulaTemplate, ...] = TEMPLATES,
) -> dict[str, int]:
    """Compute per-template quotas balanced by category first, then difficulty tier."""
    by_cat: dict[str, list[FormulaTemplate]] = defaultdict(list)
    for tpl in templates:
        by_cat[tpl.category].append(tpl)

    categories = sorted(by_cat)
    cat_quotas = _distribute_int(total, categories)

    quotas: dict[str, int] = {}
    for cat in categories:
        by_diff: dict[int, list[FormulaTemplate]] = defaultdict(list)
        for tpl in by_cat[cat]:
            by_diff[tpl.difficulty].append(tpl)
        diffs = sorted(by_diff)
        diff_quotas = _distribute_int(cat_quotas[cat], diffs)
        for d in diffs:
            tpls = sorted(by_diff[d], key=lambda t: t.id)
            per_tpl = _distribute_int(diff_quotas[d], [t.id for t in tpls])
            quotas.update(per_tpl)
    return quotas


# ---------------------------------------------------------------------------
# Serialization & execution verification (parallelizable over unique formulas)
# ---------------------------------------------------------------------------


def _serialize_expected(val: Any) -> tuple[Any, str]:
    if val is None:
        return None, "empty"
    if isinstance(val, bool | np.bool_):
        return bool(val), "boolean"
    if isinstance(val, date | datetime):
        d = val.date() if isinstance(val, datetime) else val
        return d.isoformat(), "date"
    if isinstance(val, int | np.integer):
        return int(val), "number"
    if isinstance(val, float | np.floating):
        return float(val), "number"
    return str(val), "text"


def _deserialize_expected(val: Any, val_type: str) -> Any:
    if val_type == "date" and isinstance(val, str):
        return date.fromisoformat(val)
    return val


def _verify_batch(
    batch: list[tuple[str, str, str, Any, str]],
) -> dict[tuple[str, str], tuple[bool, str | None]]:
    """Worker function: execute each unique ``(sheet_id, formula)`` and compare to expected."""
    results: dict[tuple[str, str], tuple[bool, str | None]] = {}
    for sheet_id, xlsx_path, formula, expected_json, expected_type in batch:
        res = run_formula(formula, xlsx_path)
        if not res.ok:
            results[(sheet_id, formula)] = (False, f"{res.error_type}: {res.error_message}")
            continue
        expected_native = _deserialize_expected(expected_json, expected_type)
        if not values_equal(res.value, expected_native):
            results[(sheet_id, formula)] = (
                False,
                f"mismatch: executor={res.value!r} != expected={expected_native!r}",
            )
            continue
        results[(sheet_id, formula)] = (True, None)
    return results


def verify_candidates(
    candidates: list[dict[str, Any]],
    sheet_paths: dict[str, str],
    *,
    workers: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute and verify every candidate's formula against its pandas ground truth."""
    unique_jobs: dict[tuple[str, str], tuple[str, str, str, Any, str]] = {}
    for rec in candidates:
        key = (rec["sheet_id"], rec["formula"])
        if key not in unique_jobs:
            unique_jobs[key] = (
                rec["sheet_id"],
                sheet_paths[rec["sheet_id"]],
                rec["formula"],
                rec["expected_value"],
                rec["expected_type"],
            )

    job_list = list(unique_jobs.values())
    verdicts: dict[tuple[str, str], tuple[bool, str | None]] = {}

    if workers > 1 and len(job_list) >= 64:
        chunk_size = max(16, (len(job_list) + workers * 4 - 1) // (workers * 4))
        chunks = [job_list[i : i + chunk_size] for i in range(0, len(job_list), chunk_size)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for part in pool.map(_verify_batch, chunks):
                verdicts.update(part)
    else:
        verdicts = _verify_batch(job_list)

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for rec in candidates:
        ok, err = verdicts[(rec["sheet_id"], rec["formula"])]
        if ok:
            kept.append(rec)
        else:
            dropped.append(
                {
                    "template_id": rec["template_id"],
                    "sheet_id": rec["sheet_id"],
                    "formula": rec["formula"],
                    "error": err,
                }
            )
    return kept, dropped


# ---------------------------------------------------------------------------
# Split generation & full dataset pipeline
# ---------------------------------------------------------------------------


def _generate_split_candidates(
    split_name: str,
    target_count: int,
    sheets: list[SheetContext],
    phrasing_plan: dict[str, dict[str, tuple[int, ...]]],
    *,
    seed: int,
    allow_augmentation: bool,
    augment_prob: float,
    global_seen_prompts: set[str],
    templates: tuple[FormulaTemplate, ...] = TEMPLATES,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    quotas = plan_template_quotas(target_count, templates)
    schema_cache = {s.sheet_id: format_schema_text(s) for s in sheets}

    records: list[dict[str, Any]] = []
    shortfall = 0

    def _try_emit(tpl: FormulaTemplate, count: int) -> int:
        matching = [s for s in sheets if tpl.matches_sheet(s)]
        if not matching or count <= 0:
            return 0
        allowed_idxs = phrasing_plan[tpl.id][split_name]
        emitted = 0
        max_attempts = max(count * 25, 250)
        attempts = 0

        while emitted < count and attempts < max_attempts:
            attempts += 1
            ctx = rng.choice(matching)
            p_idx = rng.choice(allowed_idxs)
            built = tpl.instantiate(ctx, rng, phrasing_idx=p_idx)

            request = built.request
            aug_tag = "none"
            use_aug = allow_augmentation and (rng.random() < augment_prob or attempts > count * 4)
            if use_aug:
                request, aug_tag = apply_rewrite_rule(request, rng)

            schema_text = schema_cache[ctx.sheet_id]
            user_prompt = build_user_prompt(schema_text, request)
            prompt_key = user_prompt.strip().lower()
            if prompt_key in global_seen_prompts:
                continue

            global_seen_prompts.add(prompt_key)
            exp_val, exp_type = _serialize_expected(built.expected)
            records.append(
                {
                    "id": "",  # assigned after verification & shuffle
                    "template_id": tpl.id,
                    "category": tpl.category,
                    "difficulty": tpl.difficulty,
                    "sheet_id": ctx.sheet_id,
                    "phrasing_idx": p_idx,
                    "augmentation": aug_tag,
                    "schema_text": schema_text,
                    "request": request,
                    "formula": built.formula,
                    "expected_value": exp_val,
                    "expected_type": exp_type,
                    "messages": build_messages(schema_text, request, built.formula),
                }
            )
            emitted += 1
        return emitted

    for tpl in templates:
        wanted = quotas[tpl.id]
        got = _try_emit(tpl, wanted)
        if got < wanted:
            shortfall += wanted - got

    # Top up any tiny shortfall across templates in the same split so target counts are met.
    if shortfall > 0:
        pool = list(templates)
        rng.shuffle(pool)
        for tpl in pool:
            if shortfall <= 0:
                break
            extra = _try_emit(tpl, min(shortfall, 25))
            shortfall -= extra

    rng.shuffle(records)
    return records


def _split_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat = Counter(r["category"] for r in records)
    by_diff = Counter(r["difficulty"] for r in records)
    by_aug = Counter(r["augmentation"] for r in records)
    by_sheet = Counter(r["sheet_id"] for r in records)
    return {
        "count": len(records),
        "unique_sheets": len(by_sheet),
        "unique_templates": len({r["template_id"] for r in records}),
        "by_category": dict(sorted(by_cat.items())),
        "by_difficulty": {str(k): by_diff[k] for k in (1, 2, 3)},
        "augmented_count": sum(v for k, v in by_aug.items() if k != "none"),
        "by_augmentation": dict(sorted(by_aug.items())),
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> str:
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataset(
    out_dir: str | Path,
    *,
    manifest_path: str | Path | None = None,
    seed: int = 42,
    n_train: int = 8000,
    n_val: int = 500,
    n_test: int = 500,
    reserved_test_phrasings: int = 2,
    reserved_val_phrasings: int = 1,
    augment_prob: float = 0.25,
    workers: int = 1,
) -> dict[str, Any]:
    """Generate, verify and write ``train.jsonl``, ``val.jsonl``, ``test_synthetic.jsonl``."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    train_sheets = load_sheet_contexts(manifest_path, split="train")
    test_sheets = load_sheet_contexts(manifest_path, split="test")
    sheet_paths = {s.sheet_id: str(s.xlsx_path) for s in (*train_sheets, *test_sheets)}

    phrasing_plan = assign_phrasing_splits(
        TEMPLATES,
        seed=seed,
        reserved_test=reserved_test_phrasings,
        reserved_val=reserved_val_phrasings,
    )

    # Generate test -> val -> train so global_seen_prompts blocks any cross-split collision.
    global_seen_prompts: set[str] = set()
    raw_splits = {
        "test": _generate_split_candidates(
            "test",
            n_test,
            test_sheets,
            phrasing_plan,
            seed=seed + 300,
            allow_augmentation=False,
            augment_prob=0.0,
            global_seen_prompts=global_seen_prompts,
        ),
        "val": _generate_split_candidates(
            "val",
            n_val,
            train_sheets,
            phrasing_plan,
            seed=seed + 200,
            allow_augmentation=False,
            augment_prob=0.0,
            global_seen_prompts=global_seen_prompts,
        ),
        "train": _generate_split_candidates(
            "train",
            n_train,
            train_sheets,
            phrasing_plan,
            seed=seed + 100,
            allow_augmentation=True,
            augment_prob=augment_prob,
            global_seen_prompts=global_seen_prompts,
        ),
    }

    filenames = {
        "train": "train.jsonl",
        "val": "val.jsonl",
        "test": "test_synthetic.jsonl",
    }

    split_stats: dict[str, Any] = {}
    total_dropped = 0
    total_checked = 0

    for split_key in ("train", "val", "test"):
        cands = raw_splits[split_key]
        kept, dropped = verify_candidates(cands, sheet_paths, workers=workers)
        total_checked += len(cands)
        total_dropped += len(dropped)

        prefix = "test_syn" if split_key == "test" else split_key
        for idx, rec in enumerate(kept, start=1):
            rec["id"] = f"{prefix}_{idx:05d}"

        file_path = out_path / filenames[split_key]
        sha = _write_jsonl(file_path, kept)
        dist = _split_distribution(kept)
        dist["candidates_checked"] = len(cands)
        dist["dropped_count"] = len(dropped)
        dist["dropped_samples"] = dropped[:10]
        dist["file"] = filenames[split_key]
        dist["sha256"] = sha
        dist["size_bytes"] = file_path.stat().st_size
        split_stats[split_key] = dist

    summary = {
        "seed": seed,
        "system_prompt": SYSTEM_PROMPT,
        "reserved_test_phrasings": reserved_test_phrasings,
        "reserved_val_phrasings": reserved_val_phrasings,
        "train_augment_prob": augment_prob,
        "total_checked": total_checked,
        "total_verified": total_checked - total_dropped,
        "total_dropped": total_dropped,
        "phrasing_splits": {
            tid: {k: list(v) for k, v in d.items()} for tid, d in phrasing_plan.items()
        },
        "splits": split_stats,
    }
    stats_path = out_path / "stats.json"
    stats_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def format_distribution_report(summary: dict[str, Any]) -> str:
    """Format a human-readable table of split sizes, categories, difficulties and drops."""
    lines = [
        f"Dataset built (seed={summary['seed']}) | "
        f"verified={summary['total_verified']}/{summary['total_checked']} "
        f"| dropped={summary['total_dropped']}",
        "",
        "Split sizes:",
    ]
    for name in ("train", "val", "test"):
        s = summary["splits"][name]
        lines.append(
            f"  {name:5s}: {s['count']:5d} examples "
            f"({s['unique_sheets']} sheets, {s['unique_templates']} templates, "
            f"augmented={s['augmented_count']}, dropped={s['dropped_count']}, "
            f"{s['size_bytes'] / 1024:.1f} KB)"
        )

    lines.append("\nCategory distribution (train / val / test):")
    cats = sorted(summary["splits"]["train"]["by_category"])
    for cat in cats:
        t = summary["splits"]["train"]["by_category"].get(cat, 0)
        v = summary["splits"]["val"]["by_category"].get(cat, 0)
        e = summary["splits"]["test"]["by_category"].get(cat, 0)
        lines.append(f"  {cat:24s}: {t:5d} / {v:4d} / {e:4d}")

    lines.append("\nDifficulty distribution (train / val / test):")
    for d in ("1", "2", "3"):
        t = summary["splits"]["train"]["by_difficulty"].get(d, 0)
        v = summary["splits"]["val"]["by_difficulty"].get(d, 0)
        e = summary["splits"]["test"]["by_difficulty"].get(d, 0)
        lines.append(f"  difficulty {d}            : {t:5d} / {v:4d} / {e:4d}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="YAML merged over config/default.yaml")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed")
    parser.add_argument("--out-dir", default=None, help="Override output directory")
    parser.add_argument("--train", type=int, default=None, help="Train split target size")
    parser.add_argument("--val", type=int, default=None, help="Validation split target size")
    parser.add_argument("--test", type=int, default=None, help="Synthetic test target size")
    parser.add_argument("--workers", type=int, default=4, help="Parallel verification workers")
    args = parser.parse_args()

    cfg = load_config(args.config)
    seed = cfg["seed"] if args.seed is None else args.seed
    out_dir = cfg["paths"]["processed_dir"] if args.out_dir is None else Path(args.out_dir)
    n_train = cfg["splits"]["train"] if args.train is None else args.train
    n_val = cfg["splits"]["valid"] if args.val is None else args.val
    n_test = cfg["splits"]["test_synthetic"] if args.test is None else args.test
    res_test = cfg["splits"].get("reserved_test_phrasings", 2)
    res_val = cfg["splits"].get("reserved_val_phrasings", 1)

    log = get_logger("formulalm.dataset", log_file=cfg["paths"]["logs_dir"] / "build_dataset.log")
    log.info(
        "Building dataset into %s (seed=%d, targets=%d/%d/%d, workers=%d)",
        out_dir,
        seed,
        n_train,
        n_val,
        n_test,
        args.workers,
    )
    summary = build_dataset(
        out_dir=out_dir,
        manifest_path=cfg["paths"]["sheets_dir"] / "manifest.json",
        seed=seed,
        n_train=n_train,
        n_val=n_val,
        n_test=n_test,
        reserved_test_phrasings=res_test,
        reserved_val_phrasings=res_val,
        workers=args.workers,
    )
    report = format_distribution_report(summary)
    log.info("\n%s", report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
