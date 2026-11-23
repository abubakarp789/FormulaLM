"""Tests for formula templates: scope coverage, phrasings and >=3-sheet execution proof."""

from __future__ import annotations

import random
import re

import pytest

from src.data.templates import (
    TEMPLATES,
    FormulaTemplate,
    SheetContext,
    load_sheet_contexts,
    template_summary,
)
from src.eval.executor import ALLOWED_FUNCTIONS, run_formula
from src.eval.normalize import values_equal

VOLATILE_FUNCTIONS = {"TODAY", "NOW", "RAND", "RANDBETWEEN"}
_FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")


@pytest.fixture(scope="module")
def all_sheets() -> list[SheetContext]:
    sheets = load_sheet_contexts(split="all")
    assert len(sheets) >= 20
    return sheets


def test_template_catalog_size_uniqueness_and_full_scope_coverage():
    assert len(TEMPLATES) >= 50
    ids = [t.id for t in TEMPLATES]
    assert len(ids) == len(set(ids)), "duplicate template IDs"

    summary = template_summary()
    covered = set(summary["functions_covered"])
    assert covered.isdisjoint(VOLATILE_FUNCTIONS)
    assert covered == set(ALLOWED_FUNCTIONS), (
        f"Scope mismatch: missing={sorted(ALLOWED_FUNCTIONS - covered)}, "
        f"extra={sorted(covered - ALLOWED_FUNCTIONS)}"
    )

    # All three difficulty tiers present.
    assert summary["by_difficulty"][1] > 0
    assert summary["by_difficulty"][2] > 0
    assert summary["by_difficulty"][3] > 0


def test_every_template_has_six_to_ten_unique_phrasings():
    for tpl in TEMPLATES:
        assert 6 <= len(tpl.phrasings) <= 10, f"{tpl.id} has {len(tpl.phrasings)} phrasings"
        normalized = [p.strip() for p in tpl.phrasings]
        assert all(normalized), f"{tpl.id} has an empty phrasing"
        assert len(set(normalized)) == len(normalized), f"{tpl.id} has duplicate phrasings"
        assert tpl.difficulty in (1, 2, 3)


@pytest.mark.parametrize("tpl", TEMPLATES, ids=[t.id for t in TEMPLATES])
def test_template_matches_pandas_gt_on_at_least_three_sheets(
    tpl: FormulaTemplate, all_sheets: list[SheetContext]
):
    matching = [s for s in all_sheets if tpl.matches_sheet(s)]
    assert len(matching) >= 3, f"{tpl.id} matched only {len(matching)} sheet(s); need at least 3"

    rng = random.Random(42 + abs(hash(tpl.id)) % 10_000)
    # Pick 3 distinct sheets deterministically (spread across the list for variety).
    chosen = rng.sample(matching, k=3)

    for ctx in chosen:
        built = tpl.instantiate(ctx, rng)

        # Verify every phrasing pattern renders cleanly with the built slots.
        for phrasing in tpl.phrasings:
            rendered = phrasing.format(**built.slots)
            assert rendered.strip()
            assert "{" not in rendered and "}" not in rendered

        # Verify formula contains no volatile/disallowed functions.
        used = {m.group(1).upper() for m in _FUNC_RE.finditer(built.formula)}
        assert used.isdisjoint(VOLATILE_FUNCTIONS)
        assert used.issubset(ALLOWED_FUNCTIONS)

        # Execute the formula in our safe spreadsheet engine and compare to pandas ground truth.
        res = run_formula(built.formula, ctx.xlsx_path)
        assert res.ok, (
            f"{tpl.id} on {ctx.sheet_id}: executor failed on {built.formula!r}: "
            f"{res.error_type}: {res.error_message}"
        )
        assert values_equal(res.value, built.expected), (
            f"{tpl.id} on {ctx.sheet_id}: formula={built.formula!r} "
            f"executor={res.value!r} != pandas_gt={built.expected!r}"
        )


def test_template_instantiation_is_deterministic(all_sheets: list[SheetContext]):
    ctx = all_sheets[0]
    tpl = TEMPLATES[0]
    a = tpl.instantiate(ctx, random.Random(123), phrasing_idx=0)
    b = tpl.instantiate(ctx, random.Random(123), phrasing_idx=0)
    assert a == b
