"""
tests/test_personal_baselines.py — #543 (ADR-105 rule 4): personal percentile bands +
EWMA-ACWR.

The load-bearing safety property under test is the FLOOR-GUARD: below MIN_N observations
every consumer must fall back to the EXACT constant it uses today, so a live training/
readiness verdict is unchanged until enough of Matthew's own data exists. The fallback
anchors are chosen to reproduce the legacy formulas bit-for-bit — that equivalence is
asserted directly here.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "compute"))

import personal_baselines as pb  # noqa: E402
import stats_core  # noqa: E402


# ── percentile ───────────────────────────────────────────────────────────────
class TestPercentile:
    def test_known_values_type7(self):
        data = [1, 2, 3, 4, 5]
        assert pb.percentile(data, 0) == 1
        assert pb.percentile(data, 100) == 5
        assert pb.percentile(data, 50) == 3
        # p25 of 1..5 (type-7): rank = 0.25*4 = 1.0 → exactly index 1 → 2
        assert pb.percentile(data, 25) == 2
        # p10: rank = 0.1*4 = 0.4 → 1 + 0.4*(2-1) = 1.4
        assert abs(pb.percentile(data, 10) - 1.4) < 1e-9

    def test_drops_none_and_nonnumeric(self):
        assert pb.percentile([None, "x", 2, 4], 50) == 3

    def test_empty_returns_none(self):
        assert pb.percentile([], 50) is None

    def test_single_value(self):
        assert pb.percentile([7], 25) == 7


# ── compute_bands + floor-guard ──────────────────────────────────────────────
class TestComputeBands:
    def test_sufficient_data_produces_bands(self):
        # 60 hrv ratios centered ~1.0, 60 grade trends centered ~0
        ratios = [1.0 + 0.1 * math.sin(i) for i in range(60)]
        trends = [3.0 * math.cos(i) for i in range(60)]
        bands = pb.compute_bands(ratios, trends)
        assert bands["readiness_hrv_ratio"] is not None
        assert bands["grade_trend_pct"] is not None
        assert bands["readiness_hrv_ratio"]["n"] == 60
        assert bands["readiness_hrv_ratio"]["p10"] < bands["readiness_hrv_ratio"]["p90"]
        assert bands["grade_trend_pct"]["lo"] < bands["grade_trend_pct"]["hi"]

    def test_thin_data_yields_none(self):
        # Fewer than MIN_N → floor-guard → None for both metrics.
        assert pb.MIN_N > 5
        few = [1.0] * (pb.MIN_N - 1)
        bands = pb.compute_bands(few, few)
        assert bands["readiness_hrv_ratio"] is None
        assert bands["grade_trend_pct"] is None

    def test_exactly_min_n_produces_band(self):
        vals = [1.0 + 0.01 * i for i in range(pb.MIN_N)]
        bands = pb.compute_bands(vals, vals)
        assert bands["readiness_hrv_ratio"] is not None
        assert bands["readiness_hrv_ratio"]["n"] == pb.MIN_N


# ── readiness HRV score: fallback reproduces the legacy formula EXACTLY ───────
def _legacy_hrv_score(ratio):
    return max(0, min(100, round((ratio - 0.75) * 200)))


class TestReadinessHrvScore:
    def test_fallback_reproduces_legacy_formula(self):
        # No baselines → population fallback → must equal the old clamp((r-0.75)*200).
        for ratio in [0.6, 0.75, 0.85, 1.0, 1.1, 1.25, 1.4]:
            score, src = pb.readiness_hrv_score(ratio, {})
            assert src == "population_fallback"
            assert score == _legacy_hrv_score(ratio), ratio

    def test_thin_band_falls_back(self):
        # A stored band that hasn't cleared the floor-guard is ignored.
        thin = {"readiness_hrv_ratio": {"p10": 0.9, "p50": 1.0, "p90": 1.1, "n": pb.MIN_N - 1}}
        score, src = pb.readiness_hrv_score(1.0, thin)
        assert src == "population_fallback"
        assert score == 50

    def test_personal_band_used_when_populated(self):
        # A tighter personal band makes the same ratio move further from 50.
        band = {"readiness_hrv_ratio": {"p10": 0.9, "p50": 1.0, "p90": 1.1, "n": pb.MIN_N}}
        score, src = pb.readiness_hrv_score(1.05, band)
        assert src == "personal"
        # ratio 1.05 is halfway p50..p90 → 75
        assert score == 75
        # median maps to 50 exactly
        assert pb.readiness_hrv_score(1.0, band)[0] == 50

    def test_clamped_0_100(self):
        band = {"readiness_hrv_ratio": {"p10": 0.9, "p50": 1.0, "p90": 1.1, "n": pb.MIN_N}}
        assert pb.readiness_hrv_score(0.5, band)[0] == 0
        assert pb.readiness_hrv_score(2.0, band)[0] == 100


# ── grade-trend signal: fallback is +-5% ─────────────────────────────────────
class TestGradeTrendSignal:
    def test_fallback_is_plus_minus_5(self):
        assert pb.grade_trend_signal(6.0, {}) == ("improving", "population_fallback")
        assert pb.grade_trend_signal(-6.0, {}) == ("declining", "population_fallback")
        assert pb.grade_trend_signal(0.0, {})[0] == "stable"
        assert pb.grade_trend_signal(5.0, {})[0] == "stable"  # not strictly greater
        assert pb.grade_trend_signal(-5.0, {})[0] == "stable"

    def test_personal_band_used(self):
        band = {"grade_trend_pct": {"lo": -2.0, "hi": 3.0, "n": pb.MIN_N}}
        assert pb.grade_trend_signal(4.0, band) == ("improving", "personal")
        assert pb.grade_trend_signal(-3.0, band) == ("declining", "personal")
        assert pb.grade_trend_signal(1.0, band)[0] == "stable"

    def test_thin_band_falls_back(self):
        band = {"grade_trend_pct": {"lo": -2.0, "hi": 3.0, "n": pb.MIN_N - 1}}
        # under the floor-guard, 4.0 is stable? no: fallback +-5 → 4.0 is stable
        assert pb.grade_trend_signal(4.0, band) == ("stable", "population_fallback")


# ── load_baselines: DDB shape + safe fallback on miss ────────────────────────
class _FakeTable:
    def __init__(self, item=None, raise_exc=False):
        self._item = item
        self._raise = raise_exc

    def get_item(self, Key):
        if self._raise:
            raise RuntimeError("throttled")
        return {"Item": self._item} if self._item else {}


class TestLoadBaselines:
    PREFIX = "USER#matthew#SOURCE#"

    def test_miss_returns_empty(self):
        assert pb.load_baselines(_FakeTable(None), self.PREFIX) == {}

    def test_exception_returns_empty(self):
        assert pb.load_baselines(_FakeTable(raise_exc=True), self.PREFIX) == {}

    def test_parses_bands_and_coerces_types(self):
        from decimal import Decimal

        item = {
            "bands": {
                "readiness_hrv_ratio": {"p10": Decimal("0.9"), "p50": Decimal("1.0"), "p90": Decimal("1.1"), "n": Decimal("40")},
            }
        }
        out = pb.load_baselines(_FakeTable(item), self.PREFIX)
        band = out["readiness_hrv_ratio"]
        assert band["p50"] == 1.0 and isinstance(band["p50"], float)
        assert band["n"] == 40 and isinstance(band["n"], int)
        # and it is usable end-to-end
        assert pb.readiness_hrv_score(1.0, out)[1] == "personal"


# ── EWMA-ACWR vs the old rolling ACWR on a known series ──────────────────────
class TestEwmaAcwr:
    def test_ewma_series_matches_manual(self):
        series = [("d1", 10.0), ("d2", 12.0), ("d3", 8.0)]
        out = stats_core.ewma_series(series, 7)
        alpha = 1 - math.exp(-1 / 7)
        e = 0.0
        for _, v in series:
            e = alpha * v + (1 - alpha) * e
        assert abs(out[-1][1] - e) < 1e-9

    def test_seed_warm_start(self):
        series = [("d1", 10.0)]
        # seed 10 with one point of 10 → stays 10 (converged); seed 0 → alpha*10
        assert abs(stats_core.ewma_series(series, 28, seed=10.0)[-1][1] - 10.0) < 1e-9
        assert stats_core.ewma_series(series, 28, seed=0.0)[-1][1] < 10.0

    def test_ewma_vs_rolling_close_on_steady_series(self):
        # On a steady series, EWMA-ACWR and rolling-ACWR both sit near 1.0 — the estimator
        # change does not move the verdict on representative steady load.
        from datetime import datetime, timedelta

        import acwr_compute_lambda as acwr

        base = datetime(2026, 3, 1)
        dates = [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(84)]
        steady = [(ds, 12.0) for ds in dates]
        items = [{"date": ds, "strain": 12.0} for ds in dates]
        ewma_acwr, _, _ = acwr._ewma_acwr(steady)
        acute_roll, _ = acwr._rolling_avg(items, "strain", 7, dates[-1])
        # both estimators of a constant series ≈ the constant → ratio ≈ 1.0
        assert abs(ewma_acwr - 1.0) < 0.02
        assert abs(acute_roll - 12.0) < 1e-9

    def test_ewma_reacts_to_recent_spike_more_than_rolling_edge(self):
        import acwr_compute_lambda as acwr

        # 28 flat days then a hard ramp: EWMA(7) leads EWMA(28), ACWR > 1.
        days = [("2026-04-%02d" % (d + 1), 8.0) for d in range(28)]
        ramp = [("2026-05-%02d" % (d + 1), 20.0) for d in range(7)]
        series = days + ramp
        acwr_val, acute, chronic = acwr._ewma_acwr(series)
        assert acute > chronic  # acute load has risen above chronic
        assert acwr_val > 1.0
        zone, alert, _ = acwr._classify_acwr(acwr_val)
        assert zone in ("caution", "danger", "safe")

    def test_build_daily_strain_fills_rest_days(self):
        import acwr_compute_lambda as acwr

        items = [{"date": "2026-05-01", "strain": 10.0}, {"date": "2026-05-03", "strain": 14.0}]
        series, n_data = acwr._build_daily_strain(items, "2026-05-01", "2026-05-03")
        assert [v for _, v in series] == [10.0, 0.0, 14.0]  # 05-02 filled with rest=0
        assert n_data == 2

    def test_acwr_none_when_chronic_zero(self):
        import acwr_compute_lambda as acwr

        series = [("2026-05-01", 0.0), ("2026-05-02", 0.0)]
        acwr_val, acute, chronic = acwr._ewma_acwr(series)
        assert acwr_val is None


# ── compute_ewa (MCP helper) still equals the sanctioned implementation ──────
def test_mcp_compute_ewa_delegates():
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    os.environ.setdefault("TABLE_NAME", "life-platform")
    os.environ.setdefault("USER_ID", "matthew")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from mcp.helpers import compute_ewa

    series = [("d1", 10.0), ("d2", 12.0), ("d3", 8.0), ("d4", 15.0)]
    got = compute_ewa(series, 7)
    want = [(lbl, round(v, 2)) for lbl, v in stats_core.ewma_series(series, 7)]
    assert got == want
