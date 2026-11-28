"""Unit tests for statistical significance helpers (McNemar exact test & bootstrap CI)."""

from __future__ import annotations

import math

import pytest

from scripts.compute_stats import bootstrap_ci, mcnemar_exact, wilson_ci


def test_mcnemar_exact_known_binomial_case() -> None:
    # 10 A-only, 0 B-only -> two-sided exact p = 2 * 0.5^10 = 1/512
    a = [1] * 10 + [1] * 5 + [0] * 5
    b = [0] * 10 + [1] * 5 + [0] * 5
    res = mcnemar_exact(a, b)
    assert res["a_only"] == 10
    assert res["b_only"] == 0
    assert res["both_correct"] == 5
    assert res["both_wrong"] == 5
    assert math.isclose(res["p_value"], 2.0 * (0.5**10), rel_tol=1e-9)
    assert res["significant_0_01"] is True


def test_mcnemar_exact_zero_discordant_returns_one() -> None:
    res = mcnemar_exact([1, 0, 1, 0], [1, 0, 1, 0])
    assert res["discordant"] == 0
    assert res["p_value"] == 1.0
    assert res["significant_0_05"] is False


def test_mcnemar_exact_symmetric_discordant_capped_at_one() -> None:
    res = mcnemar_exact([1, 0, 1, 0], [0, 1, 0, 1])
    assert res["a_only"] == 2
    assert res["b_only"] == 2
    assert res["p_value"] == 1.0


def test_mcnemar_exact_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="identical lengths"):
        mcnemar_exact([1, 0], [1])


def test_bootstrap_and_wilson_ci_bounds() -> None:
    outcomes = [1] * 43 + [0] * 7
    w_lo, w_hi = wilson_ci(43, 50)
    b_lo, b_hi = bootstrap_ci(outcomes, n_resamples=2000, seed=42)
    assert 0.0 < w_lo < 0.86 < w_hi < 1.0
    assert 0.0 < b_lo < 0.86 < b_hi < 1.0
    # Deterministic with fixed seed
    assert bootstrap_ci(outcomes, n_resamples=2000, seed=42) == (b_lo, b_hi)
