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
        # 0.80 joined the supported set with the forecast engine (#541); 0.85 stays out.
        try:
            stats_core.fisher_ci(0.5, 40, confidence=0.85)
            assert False, "expected ValueError"
        except ValueError:
            pass
        assert stats_core.fisher_ci(0.5, 40, confidence=0.80) is not None


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


class TestEwmaForecast:
    def _series(self, n=30, seed=7):
        rng = random.Random(seed)
        # AR(1)-ish daily series around 65 — recovery-shaped
        v, x = [], 65.0
        for _ in range(n):
            x = 65.0 + 0.5 * (x - 65.0) + rng.gauss(0, 6)
            v.append(x)
        return v

    def test_deterministic_repeatable(self):
        v = self._series()
        a = stats_core.ewma_forecast(v, horizon=1)
        b = stats_core.ewma_forecast(list(v), horizon=1)
        assert a == b

    def test_shape_and_interval_orders(self):
        v = self._series()
        fc = stats_core.ewma_forecast(v, horizon=1)
        assert fc is not None
        assert fc["lo"] < fc["point"] < fc["hi"]
        assert 0.05 <= fc["alpha"] <= 0.95
        assert fc["n"] == len(v)
        assert fc["confidence"] == 0.80

    def test_interval_widens_with_horizon(self):
        v = self._series()
        h1 = stats_core.ewma_forecast(v, horizon=1)
        h7 = stats_core.ewma_forecast(v, horizon=7)
        assert h1["point"] == h7["point"]  # SES: flat point forecast
        assert (h7["hi"] - h7["lo"]) >= (h1["hi"] - h1["lo"])

    def test_constant_series_returns_none(self):
        # Zero residual variance — an interval would be a lie
        assert stats_core.ewma_forecast([70.0] * 20, horizon=1) is None

    def test_insufficient_history_returns_none(self):
        assert stats_core.ewma_forecast([1, 2, 3], horizon=1) is None
        assert stats_core.ewma_forecast(self._series(8), horizon=1, min_n=10) is None

    def test_none_entries_dropped(self):
        v = self._series()
        with_nones = [v[0], None] + v[1:]
        assert stats_core.ewma_forecast(with_nones, horizon=1) == stats_core.ewma_forecast(v, horizon=1)

    def test_tracks_level_shift(self):
        # Series that steps from 60 to 80 — forecast should sit near the new level
        rng = random.Random(3)
        v = [60 + rng.gauss(0, 1) for _ in range(20)] + [80 + rng.gauss(0, 1) for _ in range(20)]
        fc = stats_core.ewma_forecast(v, horizon=1)
        assert fc["point"] > 74

    def test_unsupported_confidence_raises(self):
        try:
            stats_core.ewma_forecast(self._series(), confidence=0.5)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_bad_horizon_raises(self):
        try:
            stats_core.ewma_forecast(self._series(), horizon=0)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestEwmaFit:
    def test_alpha_grid_deterministic_tie_to_smaller(self):
        v = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
        r1 = stats_core.ewma_fit(v)
        r2 = stats_core.ewma_fit(v)
        assert r1[1] == r2[1]

    def test_short_series_none(self):
        assert stats_core.ewma_fit([1.0, 2.0, 3.0]) is None

    def test_explicit_alpha_respected(self):
        v = [10.0, 12.0, 11.0, 13.0, 12.0]
        level, alpha, residuals = stats_core.ewma_fit(v, alpha=0.5)
        assert alpha == 0.5
        assert len(residuals) == len(v) - 1


# ── Changepoint detection (#542, ADR-105) ────────────────────────────────────
def _step_series(before_mean, after_mean, n_before, n_after, sd, seed):
    """Two constant levels with Gaussian noise — a synthetic regime shift at n_before."""
    rng = random.Random(seed)
    return [before_mean + rng.gauss(0, sd) for _ in range(n_before)] + [after_mean + rng.gauss(0, sd) for _ in range(n_after)]


class TestDetectChangepoints:
    def test_known_single_breakpoint_recovered(self):
        # Level drops 60 -> 50 (a ~3-SD shift) exactly at index 25.
        s = _step_series(60, 50, 25, 25, sd=3, seed=42)
        result = stats_core.detect_changepoints(s)
        assert result["status"] == "ok"
        assert len(result["changepoints"]) >= 1
        cp = result["changepoints"][0]
        # Breakpoint recovered within tolerance of the true index (25).
        assert abs(cp["index"] - 25) <= 3
        # Magnitude and direction are honest.
        assert cp["direction"] == "decrease"
        assert cp["magnitude"] < 0
        assert abs(cp["magnitude"] - (-10)) < 3
        assert cp["confidence"] >= 0.99
        assert cp["n_before"] + cp["n_after"] == len(s)

    def test_known_breakpoint_recovered_across_many_seeds(self):
        # The recovery must not be a lucky seed: every seed lands within tolerance.
        for seed in range(25):
            s = _step_series(60, 50, 30, 30, sd=3, seed=seed)
            idxs = [c["index"] for c in stats_core.detect_changepoints(s)["changepoints"]]
            assert any(abs(i - 30) <= 3 for i in idxs), f"seed {seed} missed the breakpoint: {idxs}"

    def test_flat_series_no_breakpoint(self):
        # Nearly-constant series: no regime shift to find.
        rng = random.Random(1)
        s = [50 + rng.gauss(0, 0.5) for _ in range(50)]
        result = stats_core.detect_changepoints(s)
        assert result["status"] == "ok"
        assert result["changepoints"] == []

    def test_perfectly_constant_series_no_breakpoint(self):
        result = stats_core.detect_changepoints([42.0] * 40)
        assert result["status"] == "ok"
        assert result["changepoints"] == []

    def test_noisy_series_no_false_positive(self):
        # A representative pure-noise series (no true shift) must yield nothing.
        rng = random.Random(3)
        s = [rng.gauss(0, 1) for _ in range(45)]
        assert stats_core.detect_changepoints(s)["changepoints"] == []

    def test_noise_false_positive_rate_is_low(self):
        # Honest conservatism: across many pure-noise draws the spurious-breakpoint
        # rate stays low (the whole point of the Bonferroni + effect gates).
        fp = 0
        trials = 200
        for seed in range(trials):
            rng = random.Random(seed)
            s = [rng.gauss(0, 1) for _ in range(50)]
            if stats_core.detect_changepoints(s)["changepoints"]:
                fp += 1
        assert fp / trials < 0.05, f"noise false-positive rate too high: {fp}/{trials}"

    def test_thin_series_insufficient_data(self):
        result = stats_core.detect_changepoints([1, 2, 3, 4, 5])
        assert result["status"] == "insufficient_data"
        assert result["changepoints"] == []
        assert "reason" in result
        assert result["n"] == 5

    def test_exactly_at_threshold_still_admits_a_split(self):
        # 2*min_segment points is the minimum testable series (one candidate split).
        s = _step_series(10, 40, 7, 7, sd=0.5, seed=5)
        result = stats_core.detect_changepoints(s)
        assert result["status"] == "ok"  # not insufficient

    def test_dates_carry_through_and_align(self):
        s = _step_series(60, 50, 25, 25, sd=3, seed=42)
        dates = [f"2026-06-{d + 1:02d}" if d < 30 else f"2026-07-{d - 29:02d}" for d in range(50)]
        result = stats_core.detect_changepoints(s, dates=dates)
        cp = result["changepoints"][0]
        # The reported date is the one at the recovered index.
        assert cp["date"] == dates[cp["index"]]

    def test_two_breakpoints_recovered(self):
        rng = random.Random(7)
        s = (
            [40 + rng.gauss(0, 2) for _ in range(20)]
            + [55 + rng.gauss(0, 2) for _ in range(20)]
            + [45 + rng.gauss(0, 2) for _ in range(20)]
        )
        idxs = [c["index"] for c in stats_core.detect_changepoints(s)["changepoints"]]
        assert any(abs(i - 20) <= 3 for i in idxs)
        assert any(abs(i - 40) <= 3 for i in idxs)

    def test_max_changepoints_respected(self):
        rng = random.Random(11)
        s = []
        for block, level in enumerate([10, 40, 10, 40, 10]):
            s += [level + rng.gauss(0, 1) for _ in range(15)]
        result = stats_core.detect_changepoints(s, max_changepoints=2)
        assert len(result["changepoints"]) <= 2

    def test_none_and_nan_entries_dropped(self):
        s = _step_series(60, 50, 25, 25, sd=3, seed=42)
        # Inject holes; detection should still recover a breakpoint on the clean data.
        dirty = list(s)
        dirty[3] = None
        dirty[47] = float("nan")
        result = stats_core.detect_changepoints(dirty)
        assert result["status"] == "ok"
        assert result["n"] == len(s) - 2
        assert len(result["changepoints"]) >= 1

    def test_effect_size_gate_suppresses_small_shift(self):
        # A tiny 0.2-unit shift on unit noise is below the default 1.0-SD effect floor.
        s = _step_series(50.0, 50.2, 30, 30, sd=1.0, seed=9)
        assert stats_core.detect_changepoints(s)["changepoints"] == []

    def test_deterministic(self):
        s = _step_series(60, 50, 25, 25, sd=3, seed=42)
        r1 = stats_core.detect_changepoints(s)
        r2 = stats_core.detect_changepoints(s)
        assert r1 == r2
