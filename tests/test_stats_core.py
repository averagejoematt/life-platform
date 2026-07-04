"""
tests/test_stats_core.py — unit tests for the sanctioned statistics module (#529, ADR-105).

Fixtures worth naming:
- Anscombe's quartet set I locks pearson_r against a published value (r = 0.81642).
- The AR(1) fixture proves the load-bearing claim of the story: on autocorrelated
  pairs, effective-n-corrected significance is demonstrably WEAKER than the raw-n
  p-value (the anticonservative i.i.d. assumption is what stats_core exists to fix).
- Bootstrap determinism: same data + same seed = identical interval, run to run.
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import stats_core  # noqa: E402

# ── Anscombe's quartet I (published r = 0.81642) ─────────────────────────────
ANSCOMBE_X = [10, 8, 13, 9, 11, 14, 6, 4, 12, 7, 5]
ANSCOMBE_Y = [8.04, 6.95, 7.58, 8.81, 8.33, 9.96, 7.24, 4.26, 10.84, 4.82, 5.68]


def _ar1_series(n, rho, seed, mean=50.0, noise=5.0):
    """Deterministic AR(1) series: x_t = mean + rho*(x_{t-1}-mean) + noise*e_t."""
    rng = random.Random(seed)
    x = mean
    out = []
    for _ in range(n):
        x = mean + rho * (x - mean) + noise * rng.gauss(0, 1)
        out.append(x)
    return out


class TestPearsonR:
    def test_anscombe_fixture(self):
        r = stats_core.pearson_r(ANSCOMBE_X, ANSCOMBE_Y)
        assert abs(r - 0.81642) < 0.0005

    def test_perfect_correlation(self):
        xs = [1, 2, 3, 4, 5]
        assert abs(stats_core.pearson_r(xs, [2 * x + 1 for x in xs]) - 1.0) < 1e-9
        assert abs(stats_core.pearson_r(xs, [-x for x in xs]) + 1.0) < 1e-9

    def test_none_pairs_dropped(self):
        xs = [1, None, 2, 3, 4, 5]
        ys = [3, 9.0, None, 7, 9, 11]
        # Surviving pairs: (1,3),(3,7),(4,9),(5,11) — perfectly linear
        assert abs(stats_core.pearson_r(xs, ys) - 1.0) < 1e-9

    def test_min_n_gate(self):
        assert stats_core.pearson_r([1, 2], [1, 2]) is None
        assert stats_core.pearson_r([1, 2, 3, 4], [2, 4, 6, 8], min_n=5) is None

    def test_zero_variance(self):
        assert stats_core.pearson_r([1, 1, 1, 1], [1, 2, 3, 4]) is None

    def test_nan_dropped(self):
        xs = [1, float("nan"), 2, 3, 4, 5]
        ys = [3, 5, float("nan"), 7, 9, 11]
        assert abs(stats_core.pearson_r(xs, ys) - 1.0) < 1e-9


class TestPValue:
    def test_known_regression_values(self):
        # Locks the erf-based approximation's behavior (ported verbatim from the
        # weekly-correlation copy) so migrations can't silently change published p's.
        assert stats_core.pearson_p_value(0.5, 30) == 0.0032
        assert stats_core.pearson_p_value(0.3, 60) == 0.0166

    def test_monotone_in_r_and_n(self):
        assert stats_core.pearson_p_value(0.9, 20) < stats_core.pearson_p_value(0.3, 20)
        assert stats_core.pearson_p_value(0.4, 60) < stats_core.pearson_p_value(0.4, 15)

    def test_guards(self):
        assert stats_core.pearson_p_value(None, 30) is None
        assert stats_core.pearson_p_value(0.5, 2) is None
        assert stats_core.pearson_p_value(1.0, 30) is None

    def test_accepts_fractional_n(self):
        p = stats_core.pearson_p_value(0.5, 17.4)
        assert p is not None and 0.0 < p < 1.0


class TestAutocorrAndEffectiveN:
    def test_lag1_of_alternating_series_is_negative(self):
        assert stats_core.lag1_autocorr([1, -1, 1, -1, 1, -1, 1, -1]) < -0.5

    def test_lag1_of_white_noise_near_zero(self):
        rng = random.Random(7)
        xs = [rng.gauss(0, 1) for _ in range(500)]
        assert abs(stats_core.lag1_autocorr(xs)) < 0.15

    def test_lag1_guards(self):
        assert stats_core.lag1_autocorr([1, 2]) == 0.0
        assert stats_core.lag1_autocorr([3, 3, 3, 3]) == 0.0

    def test_effective_n_shrinks_on_autocorrelated_series(self):
        xs = _ar1_series(120, rho=0.7, seed=11)
        n_eff = stats_core.effective_sample_size(xs)
        # AR(1) rho=0.7 → theoretical shrink factor (1-.7)/(1+.7) ≈ 0.18
        assert n_eff < 0.5 * len(xs)
        assert n_eff >= 2.0

    def test_effective_n_noop_on_white_noise(self):
        rng = random.Random(23)
        xs = [rng.gauss(0, 1) for _ in range(200)]
        n_eff = stats_core.effective_sample_size(xs)
        assert n_eff > 0.6 * len(xs)

    def test_effective_n_never_exceeds_raw_n(self):
        xs = [1, -1, 1, -1, 1, -1, 1, -1, 1, -1]  # negative autocorr
        assert stats_core.effective_sample_size(xs) <= len(xs)

    def test_significance_shrinks_on_autocorrelated_pairs(self):
        """THE story-#529 acceptance fixture: two series driven by a shared slow
        AR(1) signal correlate strongly, raw-n p looks highly significant, and the
        effective-n-corrected p is demonstrably weaker."""
        driver = _ar1_series(90, rho=0.85, seed=42, noise=3.0)
        rng = random.Random(43)
        xs = [d + rng.gauss(0, 6.0) for d in driver]
        ys = [d + rng.gauss(0, 6.0) for d in driver]
        r = stats_core.pearson_r(xs, ys)
        assert r is not None and r > 0.2
        n_raw = len(xs)
        n_eff = stats_core.effective_sample_size(xs, ys)
        assert n_eff < 0.85 * n_raw
        p_raw = stats_core.pearson_p_value(r, n_raw)
        p_eff = stats_core.pearson_p_value(r, n_eff)
        # Raw n calls it significant at 0.05; the corrected p is >2x weaker.
        assert p_raw < 0.05
        assert p_eff > 1.5 * p_raw


class TestFisherCI:
    def test_contains_r_and_orders(self):
        lo, hi = stats_core.fisher_ci(0.5, 40)
        assert lo < 0.5 < hi
        assert -1.0 < lo and hi < 1.0

    def test_narrows_with_n(self):
        lo1, hi1 = stats_core.fisher_ci(0.5, 20)
        lo2, hi2 = stats_core.fisher_ci(0.5, 200)
        assert (hi2 - lo2) < (hi1 - lo1)

    def test_guards(self):
        assert stats_core.fisher_ci(None, 40) is None
        assert stats_core.fisher_ci(0.5, 3) is None

    def test_unsupported_confidence_raises(self):
        try:
            stats_core.fisher_ci(0.5, 40, confidence=0.80)
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestBlockBootstrap:
    def test_deterministic_same_seed(self):
        xs = _ar1_series(60, rho=0.5, seed=5)
        ys = _ar1_series(60, rho=0.5, seed=6)
        ci1 = stats_core.moving_block_bootstrap_ci(xs, ys)
        ci2 = stats_core.moving_block_bootstrap_ci(xs, ys)
        assert ci1 == ci2

    def test_paired_ci_brackets_point_estimate(self):
        xs = list(range(50))
        rng = random.Random(9)
        ys = [x + rng.gauss(0, 8) for x in xs]
        r = stats_core.pearson_r(xs, ys)
        lo, hi = stats_core.moving_block_bootstrap_ci(xs, ys)
        assert lo <= r <= hi
        assert -1.0 <= lo <= hi <= 1.0

    def test_single_series_mean_ci(self):
        xs = _ar1_series(80, rho=0.4, seed=31, mean=100.0, noise=4.0)
        lo, hi = stats_core.moving_block_bootstrap_ci(xs)
        m = sum(xs) / len(xs)
        assert lo <= m <= hi

    def test_too_few_points_returns_none(self):
        assert stats_core.moving_block_bootstrap_ci([1, 2, 3, 4], [2, 3, 4, 5]) is None

    def test_mean_diff_ci_detects_shift(self):
        base = _ar1_series(40, rho=0.3, seed=13, mean=50.0, noise=2.0)
        shifted = _ar1_series(40, rho=0.3, seed=14, mean=58.0, noise=2.0)
        lo, hi = stats_core.bootstrap_mean_diff_ci(base, shifted)
        assert lo > 0  # entire interval above zero: a real shift
        true_diff = sum(shifted) / len(shifted) - sum(base) / len(base)
        assert lo <= true_diff <= hi

    def test_mean_diff_ci_straddles_zero_on_no_shift(self):
        base = _ar1_series(60, rho=0.3, seed=17, mean=50.0, noise=3.0)
        same = _ar1_series(60, rho=0.3, seed=18, mean=50.0, noise=3.0)
        lo, hi = stats_core.bootstrap_mean_diff_ci(base, same)
        assert lo < 0 < hi

    def test_mean_diff_guard(self):
        assert stats_core.bootstrap_mean_diff_ci([1, 2, 3], [4, 5, 6, 7, 8]) is None


class TestCohensD:
    def test_known_fixture(self):
        a = [2, 4, 7, 3, 7, 35, 8, 9]
        b = [x + 5 for x in a]
        d = stats_core.cohens_d(a, b)
        # Identical variance, mean shift 5, pooled sd = sample sd of a (≈10.72)
        sd = math.sqrt(sum((x - sum(a) / len(a)) ** 2 for x in a) / (len(a) - 1))
        assert abs(d - 5.0 / sd) < 1e-9

    def test_sign_convention_window_minus_baseline(self):
        assert stats_core.cohens_d([1, 2, 3, 4], [11, 12, 13, 14]) > 0
        assert stats_core.cohens_d([11, 12, 13, 14], [1, 2, 3, 4]) < 0

    def test_degenerate(self):
        assert stats_core.cohens_d([1], [1, 2]) is None
        assert stats_core.cohens_d([3, 3, 3], [3, 3, 3]) is None


class TestBHFDR:
    def test_known_fixture(self):
        pvals = [0.005, 0.011, 0.02, 0.04, 0.13]
        adj = stats_core.bh_fdr(pvals)
        expected = [0.025, 0.0275, 0.0333, 0.05, 0.13]
        for a, e in zip(adj, expected):
            assert abs(a - e) < 0.001

    def test_order_preserved_and_none_passthrough(self):
        pvals = [0.04, None, 0.005, 0.13, None]
        adj = stats_core.bh_fdr(pvals)
        assert adj[1] is None and adj[4] is None
        assert adj[2] < adj[0] < adj[3]

    def test_monotone_and_capped(self):
        adj = stats_core.bh_fdr([0.9, 0.8, 0.7])
        assert all(a <= 1.0 for a in adj)
        assert adj == sorted(adj, reverse=True)

    def test_empty_and_all_none(self):
        assert stats_core.bh_fdr([]) == []
        assert stats_core.bh_fdr([None, None]) == [None, None]
