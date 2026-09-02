"""tests/test_weekly_correlation_compute.py — unit coverage for the weekly
correlation compute lambda (#1658 coverage ratchet, ADR-105 rigor bar).

Complements the existing narrow-slice suites (test_what_changed.py = SS-08 deltas,
test_cross_domain_edges_1406.py = the two #1406 edges, test_diary_intervention_1843.py
= the diary pair) by exercising the parts none of them touch: the Pearson/interpretation
core against HAND-DERIVED numbers, the n-gates, the BH-FDR plumbing, the daily-series
assembly, the two benchmark computations (centenarian / zone-2), every DynamoDB
store_* encoder, and the handler's four exit paths.

ADR-105 is the reason several of these assertions are exact: a correlation claim must
carry its uncertainty (CI) and its EFFECTIVE n (autocorrelation-corrected), and the
p-value must be computed on n_eff — not on the raw day count. The n_eff = 6.9 and
r = 0.4545 figures below are derived by hand in the comments so a reviewer can check
the arithmetic without running the code.

Fully offline: no AWS, no network, no sleeps. Every DynamoDB/CloudWatch handle is
replaced with a hand-written fake (never MagicMock — a non-terminating mock in a
pagination loop has OOM'd this repo's CI runner before).
"""

import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pacific_clock import freeze_pacific  # noqa: E402 — #2811: the PT clock the module actually calls

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import weekly_correlation_compute_lambda as wc  # noqa: E402
from common import compute_metadata, stats_core  # noqa: E402
from experiment import experiment_gates  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# Hand-written fakes (no MagicMock anywhere — see module docstring)
# ══════════════════════════════════════════════════════════════════════════════


class FakeTable:
    """Minimal DynamoDB Table stand-in that records writes and serves canned reads."""

    def __init__(self, get_items=None, get_raises=False):
        self.puts = []
        self._get_items = dict(get_items or {})  # (pk, sk) -> Item dict
        self._get_raises = get_raises
        self.get_calls = []

    def put_item(self, Item):  # noqa: N803 — boto3's kwarg name
        self.puts.append(Item)
        return {}

    def get_item(self, Key):  # noqa: N803
        self.get_calls.append((Key["pk"], Key["sk"]))
        if self._get_raises:
            raise RuntimeError("simulated DynamoDB read failure")
        item = self._get_items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}


class FakeCloudWatch:
    """compute_metadata._emit_write_metric target — keeps tag_record off the network."""

    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """tag_record() emits a CloudWatch metric on every store_*; keep it local."""
    monkeypatch.setattr(compute_metadata, "_CW", FakeCloudWatch())


def _sk_dates(n, start="2026-05-01"):
    from datetime import timedelta

    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


# The reference series used by several tests below.
#   XS = 1..10                       mean 5.5, Sxx = 82.5
#   YS = 1..9 then 0                 mean 4.5, Syy = 82.5
#   Sxy = 37.5  ->  r = 37.5 / 82.5 = 0.454545... -> rounded 0.4545
_XS = [float(i) for i in range(1, 11)]
_YS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 0.0]


def _paired_series(xs=None, ys=None, a="hrv", b="recovery_score"):
    """A date-keyed series carrying exactly one metric pair."""
    xs = _XS if xs is None else xs
    ys = _YS if ys is None else ys
    dates = _sk_dates(len(xs))
    return {d: {a: xs[i], b: ys[i]} for i, d in enumerate(dates)}


# ══════════════════════════════════════════════════════════════════════════════
# pearson_r — hand-derived values, n-gate, degenerate series
# ══════════════════════════════════════════════════════════════════════════════


class TestPearson:
    def test_hand_derived_r_and_n(self):
        # Sxy/sqrt(Sxx*Syy) = 37.5 / 82.5 = 0.454545... (both sums of squares are 82.5)
        r, n = wc.pearson_r(_XS, _YS)
        assert n == 10
        assert r == 0.4545

    def test_perfect_positive_and_negative(self):
        r_pos, _ = wc.pearson_r(_XS, _XS)
        r_neg, _ = wc.pearson_r(_XS, [-x for x in _XS])
        assert r_pos == 1.0
        assert r_neg == -1.0

    def test_sign_follows_the_relationship(self):
        r_down, _ = wc.pearson_r(_XS, [11.0 - x for x in _XS])
        assert r_down < 0

    def test_insufficient_n_returns_none_but_still_reports_n(self):
        # The registry gate is 10 (experiment_gates.CORRELATION_MIN_N); 9 pairs is a null.
        assert experiment_gates.CORRELATION_MIN_N == 10
        r, n = wc.pearson_r(_XS[:9], _YS[:9])
        assert r is None and n == 9

    def test_exactly_min_n_is_admitted(self):
        r, n = wc.pearson_r(_XS, _YS)
        assert n == experiment_gates.CORRELATION_MIN_N and r is not None

    def test_empty_and_single_sample(self):
        assert wc.pearson_r([], []) == (None, 0)
        assert wc.pearson_r([1.0], [2.0]) == (None, 1)

    def test_flat_series_is_not_a_spurious_correlation(self):
        # A constant y has zero variance — the denominator is 0, so there is no
        # correlation to report. It must be None, never 0.0 dressed up as a result.
        flat = [7.0] * 20
        r, n = wc.pearson_r([float(i) for i in range(20)], flat)
        assert n == 20 and r is None
        r2, _ = wc.pearson_r(flat, flat)
        assert r2 is None

    def test_none_entries_are_dropped_pairwise(self):
        xs = _XS + [None, 99.0]
        ys = _YS + [5.0, None]
        r, n = wc.pearson_r(xs, ys)
        assert n == 10 and r == 0.4545


# ══════════════════════════════════════════════════════════════════════════════
# interpret_r — the n-gated label ladder (thresholds read from the registry)
# ══════════════════════════════════════════════════════════════════════════════


class TestInterpretR:
    def test_registry_thresholds_are_the_ones_under_test(self):
        assert experiment_gates.CORRELATION_INTERP_N == {"strong": 50, "moderate": 30, "weak": 10}

    def test_no_r_is_insufficient_data(self):
        assert wc.interpret_r(None) == "insufficient_data"
        assert wc.interpret_r(None, 500) == "insufficient_data"

    def test_labels_at_full_sample_size(self):
        assert wc.interpret_r(0.65, 60) == "strong"
        assert wc.interpret_r(-0.65, 60) == "strong"  # magnitude, not sign
        assert wc.interpret_r(0.45, 35) == "moderate"
        assert wc.interpret_r(0.25, 12) == "weak"

    def test_negligible_is_not_n_gated(self):
        # |r| < 0.2 returns before the sample-size ladder — a null is a null at any n.
        assert wc.interpret_r(0.05, 3) == "negligible"
        assert wc.interpret_r(-0.19, 400) == "negligible"

    def test_strong_downgrades_one_level_when_n_below_50(self):
        assert wc.interpret_r(0.8, 40) == "moderate"  # n >= 30
        assert wc.interpret_r(0.8, 20) == "weak"  # n < 30

    def test_moderate_downgrades_and_falls_off_the_bottom(self):
        assert wc.interpret_r(0.45, 20) == "weak"  # n >= 10
        assert wc.interpret_r(0.45, 5) == "insufficient_data"  # n < 10

    def test_weak_below_its_floor_is_insufficient_data(self):
        assert wc.interpret_r(0.25, 9) == "insufficient_data"

    def test_no_n_means_no_gating(self):
        assert wc.interpret_r(0.8, None) == "strong"

    def test_gloss_only_explains_a_real_downgrade(self):
        # r=0.8 on n=20 is served "weak" — two bands below what |r| alone earns.
        assert wc.n_gate_gloss(0.8, 20, wc.interpret_r(0.8, 20)) == "evidence still thin"
        # r=0.65 on n=60 is served at full strength — nothing to explain.
        assert wc.n_gate_gloss(0.65, 60, wc.interpret_r(0.65, 60)) is None


# ══════════════════════════════════════════════════════════════════════════════
# apply_benjamini_hochberg — p on n_eff, FDR adjustment, honest nulls
# ══════════════════════════════════════════════════════════════════════════════


class TestBenjaminiHochberg:
    def test_p_value_is_computed_on_n_eff_not_n_days(self):
        # ADR-105: daily series are autocorrelated, so the p-value must ride the
        # effective n. With n_eff=5 the same r=0.5 is nowhere near significant;
        # on the raw 1000 days it would look overwhelming. Hand check: df=3,
        # t = 0.5*sqrt(3)/sqrt(0.75) = 1.0, z = 1.0*sqrt(3/5) = 0.7746, p ~= 0.439.
        results = {"pair": {"pearson_r": 0.5, "n_days": 1000, "n_eff": 5}}
        out = wc.apply_benjamini_hochberg(results)
        assert 0.43 <= out["pair"]["p_value"] <= 0.45
        assert out["pair"]["p_value"] == stats_core.pearson_p_value(0.5, 5)
        assert out["pair"]["p_value"] != stats_core.pearson_p_value(0.5, 1000)
        assert out["pair"]["fdr_significant"] is False

    def test_falls_back_to_n_days_when_no_n_eff(self):
        results = {"pair": {"pearson_r": 0.5, "n_days": 5}}
        out = wc.apply_benjamini_hochberg(results)
        assert out["pair"]["p_value"] == stats_core.pearson_p_value(0.5, 5)

    def test_null_and_significant_pairs_get_hand_checkable_adjustments(self):
        # r = 0.0  -> t = 0     -> p = 1.0 exactly.
        # r = 0.95 on n_eff=52 -> t ~= 21.5 -> p rounds to 0.0.
        # BH with m=2: sorted p = [0.0, 1.0]; adj = [2/1*0.0, 2/2*1.0] = [0.0, 1.0].
        results = {
            "strong": {"pearson_r": 0.95, "n_eff": 52},
            "null": {"pearson_r": 0.0, "n_eff": 52},
            "nodata": {"pearson_r": None, "n_days": 0},
        }
        out = wc.apply_benjamini_hochberg(results, alpha=0.05)
        assert out["strong"]["p_value"] == 0.0
        assert out["strong"]["p_value_fdr"] == 0.0
        assert out["strong"]["fdr_significant"] is True
        assert out["null"]["p_value"] == 1.0
        assert out["null"]["p_value_fdr"] == 1.0
        assert out["null"]["fdr_significant"] is False

    def test_pair_without_r_carries_no_p_value_and_never_claims_significance(self):
        results = {"nodata": {"pearson_r": None, "n_days": 0}}
        out = wc.apply_benjamini_hochberg(results)
        assert out["nodata"]["p_value"] is None
        assert out["nodata"]["p_value_fdr"] is None
        assert out["nodata"]["fdr_significant"] is False

    def test_perfect_correlation_yields_no_p_value(self):
        # |r| >= 1 has no defined t statistic — stats_core returns None rather than
        # fabricating certainty, and the pair must not be called FDR-significant.
        out = wc.apply_benjamini_hochberg({"perfect": {"pearson_r": 1.0, "n_eff": 40}})
        assert out["perfect"]["p_value"] is None
        assert out["perfect"]["fdr_significant"] is False

    def test_adjustment_never_makes_a_claim_stronger(self):
        results = {f"p{i}": {"pearson_r": 0.3 + 0.05 * i, "n_eff": 45} for i in range(6)}
        out = wc.apply_benjamini_hochberg(results)
        for data in out.values():
            assert data["p_value_fdr"] >= data["p_value"] - 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# compute_correlations — the assembled result dict (ADR-105 payload contract)
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeCorrelations:
    def test_result_carries_r_n_uncertainty_and_effective_n(self):
        out = wc.compute_correlations(_paired_series())
        res = out["hrv_vs_recovery"]
        assert res["pearson_r"] == 0.4545
        assert res["r_squared"] == 0.2066  # 0.4545**2 = 0.20657... -> 0.2066
        assert res["n_days"] == 10
        # ADR-105 hand derivation of the AR(1)/Pyper-Peterman correction:
        #   lag-1 autocorr of 1..10          = 57.75 / 82.5 = 0.7
        #   lag-1 autocorr of 1..9,0         = 21.75 / 82.5 = 0.263636...
        #   rho = 0.7 * 0.263636 = 0.184545
        #   n_eff = 10 * (1 - rho) / (1 + rho) = 6.884... -> 6.9
        assert res["n_eff"] == 6.9
        assert res["n_eff"] < res["n_days"]  # the correction only ever shrinks evidence
        assert res["ci95_low"] is not None and res["ci95_high"] is not None
        assert res["ci95_low"] <= res["pearson_r"] <= res["ci95_high"]
        assert res["direction"] == "positive"
        assert res["correlation_type"] == "cross_sectional"
        assert res["lag_days"] is None
        # n=10 earns "moderate" on magnitude but the n-gate serves "weak" + a gloss.
        assert res["interpretation"] == "weak"
        assert res["gloss"] == "evidence still thin"

    def test_p_value_rides_n_eff_end_to_end(self):
        res = wc.compute_correlations(_paired_series())["hrv_vs_recovery"]
        assert res["p_value"] == stats_core.pearson_p_value(res["pearson_r"], res["n_eff"])
        assert res["p_value"] > stats_core.pearson_p_value(res["pearson_r"], res["n_days"])

    def test_every_pair_in_the_registry_is_computed(self):
        out = wc.compute_correlations(_paired_series())
        assert set(out) == {p[2] for p in wc.CORRELATION_PAIRS}

    def test_pairs_without_data_are_honest_nulls(self):
        out = wc.compute_correlations(_paired_series())
        empty = out["protein_vs_recovery"]  # no macrofactor metrics in this series
        assert empty["pearson_r"] is None
        assert empty["n_days"] == 0
        assert empty["n_eff"] is None
        assert empty["ci95_low"] is None and empty["ci95_high"] is None
        assert empty["r_squared"] is None
        assert empty["direction"] is None
        assert empty["interpretation"] == "insufficient_data"
        assert empty["gloss"] is None
        assert empty["counterintuitive"] is False

    def test_flat_series_produces_no_correlation(self):
        series = _paired_series(xs=[float(i) for i in range(1, 21)], ys=[42.0] * 20)
        res = wc.compute_correlations(series)["hrv_vs_recovery"]
        assert res["n_days"] == 20  # the data is there …
        assert res["pearson_r"] is None  # … and still yields nothing
        assert res["interpretation"] == "insufficient_data"

    def test_counterintuitive_flag_fires_on_a_reversed_prior(self):
        # hrv_vs_recovery is registered "positive"; feed it a negative relationship.
        res = wc.compute_correlations(_paired_series(ys=[-y for y in _YS]))["hrv_vs_recovery"]
        assert res["pearson_r"] == -0.4545
        assert res["direction"] == "negative"
        assert res["expected_direction"] == "positive"
        assert res["counterintuitive"] is True

    def test_counterintuitive_needs_a_meaningful_signal(self):
        # Direction disagrees with the prior but |r| < 0.2 — noise is not a discovery.
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        ys = [5.0, 6.0, 4.0, 7.0, 5.0, 6.0, 4.0, 7.0, 5.0, 5.0]
        res = wc.compute_correlations(_paired_series(xs=xs, ys=ys))["hrv_vs_recovery"]
        assert abs(res["pearson_r"]) < 0.2
        assert res["counterintuitive"] is False

    def test_lagged_pair_pairs_day_d_with_day_d_plus_one(self):
        # load_predicts_next_day_recovery: training_kj[D] vs recovery_score[D+1].
        dates = _sk_dates(11)
        series = {d: {} for d in dates}
        for i, d in enumerate(dates[:-1]):
            series[d]["training_kj"] = float(i)
            series[dates[i + 1]]["recovery_score"] = float(i)  # perfectly lag-1 coupled
        res = wc.compute_correlations(series)["load_predicts_next_day_recovery"]
        assert res["correlation_type"] == "lagged_1d"
        assert res["lag_days"] == 1
        assert res["n_days"] == 10
        assert res["pearson_r"] == 1.0

    def test_lagged_pair_skips_dates_with_no_successor(self):
        # A one-day island contributes no lag-1 pair at all.
        series = {"2026-05-01": {"training_kj": 1.0, "recovery_score": 1.0}}
        res = wc.compute_correlations(series)["load_predicts_next_day_recovery"]
        assert res["n_days"] == 0 and res["pearson_r"] is None

    def test_unparseable_date_key_is_skipped_not_fatal(self):
        series = dict(_paired_series())
        series["not-a-date"] = {"training_kj": 1.0, "recovery_score": 2.0}
        out = wc.compute_correlations(series)  # must not raise
        assert out["hrv_vs_recovery"]["n_days"] == 10

    def test_sdt_sensitive_edge_is_stamped_deterministically(self):
        out = wc.compute_correlations(_paired_series())
        edge = out["values_lived_predicts_next_day_adherence"]
        assert edge["sdt_sensitive"] is True
        assert edge["coach_framing"] == "autonomy_supportive"
        assert "autonomy-supportive" in edge["framing_note"].lower()
        # A non-listed edge carries no framing stamp at all.
        assert "sdt_sensitive" not in out["hrv_vs_recovery"]

    def test_three_tuple_pair_format_is_still_supported(self, monkeypatch):
        monkeypatch.setattr(wc, "CORRELATION_PAIRS", [("hrv", "recovery_score", "legacy_pair")])
        res = wc.compute_correlations(_paired_series())["legacy_pair"]
        assert res["correlation_type"] == "cross_sectional"
        assert res["lag_days"] is None
        assert res["pearson_r"] == 0.4545


# ══════════════════════════════════════════════════════════════════════════════
# fetch_range / _to_dec / _deep_dec
# ══════════════════════════════════════════════════════════════════════════════


class TestHelpers:
    def test_fetch_range_delegates_to_the_shared_query(self, monkeypatch):
        seen = {}

        def _fake(table, source, start, end, user_id=None, include_pilot=False):
            seen.update(source=source, start=start, end=end, user_id=user_id, include_pilot=include_pilot)
            return [{"date": "2026-05-01"}]

        monkeypatch.setattr(wc.digest_utils, "query_range_list", _fake)
        assert wc.fetch_range("whoop", "2026-05-01", "2026-05-10") == [{"date": "2026-05-01"}]
        assert seen["source"] == "whoop" and seen["user_id"] == wc.USER_ID
        # #3444: whoop is RAW_TIMESERIES, so fetch_range must derive a cross-phase read.
        assert seen["include_pilot"] is True

    def test_fetch_range_degrades_to_empty_on_a_read_failure(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("DynamoDB unavailable")

        monkeypatch.setattr(wc.digest_utils, "query_range_list", _boom)
        # Fail-soft by contract: one bad source must not abort the whole compute run.
        assert wc.fetch_range("whoop", "2026-05-01", "2026-05-10") == []

    def test_to_dec_rounds_to_six_places_and_rejects_garbage(self):
        assert wc._to_dec(1.23456789) == Decimal("1.234568")
        assert wc._to_dec(3) == Decimal("3")
        assert wc._to_dec(None) is None
        assert wc._to_dec("not a number") is None

    def test_deep_dec_walks_nested_structures_and_preserves_bools(self):
        out = wc._deep_dec({"f": 1.5, "i": 2, "b": True, "s": "x", "n": None, "l": [0.25, {"g": 3.5}]})
        assert out["f"] == Decimal("1.5")
        assert out["i"] == Decimal("2")
        assert out["b"] is True  # bool is a subclass of int — must NOT become Decimal
        assert out["s"] == "x" and out["n"] is None
        assert out["l"][0] == Decimal("0.25") and out["l"][1]["g"] == Decimal("3.5")


# ══════════════════════════════════════════════════════════════════════════════
# assemble_daily_series — the source → metric extraction layer
# ══════════════════════════════════════════════════════════════════════════════


def _fetch_stub(mapping):
    """fetch_range replacement driven by a {source: [records]} dict."""

    def _fetch(source, start, end):
        return list(mapping.get(source, []))

    return _fetch


class TestAssembleDailySeries:
    def test_extracts_each_domain_from_its_source(self, monkeypatch):
        monkeypatch.setattr(
            wc,
            "fetch_range",
            _fetch_stub(
                {
                    "whoop": [
                        {
                            "date": "2026-05-01",
                            "hrv": 62,
                            "recovery_score": 71,
                            "sleep_duration_hours": 7.5,
                            "sleep_quality_score": 88,
                            "resting_heart_rate": 51,
                            "strain": 12.3,
                        }
                    ],
                    "strava": [
                        {
                            "date": "2026-05-01",
                            "activities": [
                                {"kilojoules": 400, "moving_time_seconds": 1800},
                                {"kilojoules": 200, "moving_time_seconds": 900},
                            ],
                        }
                    ],
                    "macrofactor": [
                        {"date": "2026-05-01", "total_calories_kcal": 2400, "total_protein_g": 190, "total_carbs_g": 250, "total_fat_g": 80}
                    ],
                    "apple_health": [{"date": "2026-05-01", "steps": 11000, "blood_glucose_cv": 17.5, "som_avg_valence": 0.4}],
                    "habitify": [{"date": "2026-05-01", "habits": {"a": True, "b": True, "c": False, "d": False}}],
                    "computed_metrics": [
                        {
                            "date": "2026-05-01",
                            "tsb": -8.5,
                            "day_grade_score": 84,
                            "readiness_score": 77,
                            "tier0_streak": 12,
                            "diary_sessions": 2,
                        }
                    ],
                    "flourishing": [{"date": "2026-05-01", "values_lived_count": 3}],
                }
            ),
        )
        series = wc.assemble_daily_series("2026-05-01", "2026-05-01")
        m = series["2026-05-01"]
        assert m["hrv"] == 62.0 and m["recovery_score"] == 71.0
        assert m["sleep_duration"] == 7.5 and m["sleep_score"] == 88.0
        assert m["resting_hr"] == 51.0 and m["strain"] == 12.3
        assert m["training_kj"] == 600.0  # 400 + 200
        assert m["training_mins"] == 45.0  # (1800 + 900) / 60
        assert m["calories"] == 2400.0 and m["protein_g"] == 190.0
        assert m["carbs_g"] == 250.0 and m["fat_g"] == 80.0
        assert m["steps"] == 11000.0
        assert m["tsb"] == -8.5 and m["day_grade"] == 84.0
        assert m["readiness"] == 77.0 and m["tier0_streak"] == 12.0
        assert m["diary_sessions"] == 2.0
        assert m["habit_pct"] == 0.5  # 2 of 4 done
        assert m["glucose_cv"] == 17.5
        assert m["mood_valence"] == 0.4
        assert m["values_lived_count"] == 3.0

    def test_absent_sources_are_none_not_zero(self, monkeypatch):
        # ADR-104 behavioural absence: a day with only whoop must not report
        # training_kj=0 or habit_pct=0 — nothing was measured.
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({"whoop": [{"date": "2026-05-02", "hrv": 60}]}))
        m = wc.assemble_daily_series("2026-05-02", "2026-05-02")["2026-05-02"]
        assert m["training_kj"] is None and m["training_mins"] is None
        assert m["habit_pct"] is None
        assert m["calories"] is None and m["steps"] is None

    def test_habit_pct_with_no_habits_is_none_not_a_division_by_zero(self, monkeypatch):
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({"habitify": [{"date": "2026-05-03", "habits": {}}]}))
        assert wc.assemble_daily_series("2026-05-03", "2026-05-03")["2026-05-03"]["habit_pct"] is None

    def test_sleep_score_falls_back_to_the_legacy_field(self, monkeypatch):
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({"whoop": [{"date": "2026-05-04", "sleep_score": 73}]}))
        assert wc.assemble_daily_series("2026-05-04", "2026-05-04")["2026-05-04"]["sleep_score"] == 73.0

    def test_date_is_recovered_from_the_sort_key(self, monkeypatch):
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({"whoop": [{"sk": "DATE#2026-05-05", "hrv": 55}]}))
        series = wc.assemble_daily_series("2026-05-05", "2026-05-05")
        assert series["2026-05-05"]["hrv"] == 55.0

    def test_records_with_no_resolvable_date_are_dropped(self, monkeypatch):
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({"whoop": [{"hrv": 55}]}))
        assert wc.assemble_daily_series("2026-05-05", "2026-05-05") == {}

    def test_glucose_cv_falls_back_to_mean_and_sd(self, monkeypatch):
        # 100 * 18 / 120 = 15.0 %CV, derived only when >= 2 readings exist.
        monkeypatch.setattr(
            wc,
            "fetch_range",
            _fetch_stub(
                {
                    "apple_health": [
                        {"date": "2026-05-06", "blood_glucose_avg": 120, "blood_glucose_std_dev": 18, "blood_glucose_readings_count": 6}
                    ]
                }
            ),
        )
        assert wc.assemble_daily_series("2026-05-06", "2026-05-06")["2026-05-06"]["glucose_cv"] == 15.0

    def test_single_reading_day_never_fabricates_zero_variability(self, monkeypatch):
        monkeypatch.setattr(
            wc,
            "fetch_range",
            _fetch_stub(
                {
                    "apple_health": [
                        {"date": "2026-05-07", "blood_glucose_avg": 120, "blood_glucose_std_dev": 0, "blood_glucose_readings_count": 1}
                    ]
                }
            ),
        )
        assert wc.assemble_daily_series("2026-05-07", "2026-05-07")["2026-05-07"]["glucose_cv"] is None


# ══════════════════════════════════════════════════════════════════════════════
# BS-TR1 — centenarian decathlon progress
# ══════════════════════════════════════════════════════════════════════════════


def _hevy(name, e1rm):
    return {"date": "2026-06-01", "exercises": [{"title": name, "estimated_1rm_lbs": e1rm}]}


class TestCentenarianProgress:
    def _stub(self, monkeypatch, weights, hevy):
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({"withings": weights, "hevy": hevy}))

    def test_status_ladder_and_overall_readiness_are_hand_checkable(self, monkeypatch):
        # bodyweight 200 lb -> targets: DL 400, SQ 350, BP 300, OHP 200.
        self._stub(
            monkeypatch,
            [{"date": "2026-06-29", "weight_lbs": 210}, {"date": "2026-06-30", "weight_lbs": 200}],
            [
                _hevy("Barbell Deadlift", 420),  # 420/400 = 1.05 -> exceeds_target
                _hevy("Back Squat", 315),  # 315/350 = 0.90 -> at_target
                _hevy("Incline Bench Press", 240),  # 240/300 = 0.80 -> approaching
                _hevy("Overhead Press", 110),  # 110/200 = 0.55 -> progressing
            ],
        )
        out = wc._compute_centenarian_progress({}, "2026-06-30")
        assert out["bodyweight_lbs"] == 200.0
        assert out["lifts"]["deadlift"]["status"] == "exceeds_target"
        assert out["lifts"]["deadlift"]["pct_of_target"] == 105.0
        assert out["lifts"]["deadlift"]["gap_lbs"] == 0.0  # never negative
        assert out["lifts"]["squat"]["status"] == "at_target"
        assert out["lifts"]["squat"]["gap_lbs"] == 35.0
        assert out["lifts"]["bench_press"]["status"] == "approaching"
        assert out["lifts"]["overhead_press"]["status"] == "progressing"
        assert out["lifts_scored"] == 4
        # (1.05 + 0.90 + 0.80 + 0.55) / 4 * 100 = 82.5
        assert out["overall_readiness"] == 82.5
        assert out["priority_lift"] == "overhead_press"  # furthest from target

    def test_below_minimum_and_missing_lifts(self, monkeypatch):
        self._stub(monkeypatch, [{"weight_lbs": 200}], [_hevy("Deadlift", 100)])  # 100/400 = 0.25
        out = wc._compute_centenarian_progress({}, "2026-06-30")
        assert out["lifts"]["deadlift"]["status"] == "below_minimum"
        assert out["lifts"]["squat"] == {"status": "no_data", "target_lbs": 350.0}
        assert out["lifts_scored"] == 1
        assert out["overall_readiness"] == 25.0

    def test_uses_the_latest_bodyweight_and_the_max_1rm_per_lift(self, monkeypatch):
        self._stub(
            monkeypatch,
            [{"weight_lbs": 300}, {"weight_lbs": 200}],
            [_hevy("Deadlift", 300), _hevy("Deadlift", 380), _hevy("Deadlift", 250)],
        )
        out = wc._compute_centenarian_progress({}, "2026-06-30")
        assert out["bodyweight_lbs"] == 200.0
        assert out["lifts"]["deadlift"]["current_lbs"] == 380.0

    def test_no_bodyweight_returns_none(self, monkeypatch):
        self._stub(monkeypatch, [], [_hevy("Deadlift", 400)])
        assert wc._compute_centenarian_progress({}, "2026-06-30") is None

    def test_lifts_without_a_1rm_estimate_are_ignored(self, monkeypatch):
        self._stub(monkeypatch, [{"weight_lbs": 200}], [{"exercises": [{"title": "Deadlift"}]}])
        out = wc._compute_centenarian_progress({}, "2026-06-30")
        assert out["lifts_scored"] == 0
        assert out["overall_readiness"] is None
        assert out["priority_lift"] is None

    def test_is_non_fatal_on_a_bad_end_date(self, monkeypatch):
        self._stub(monkeypatch, [{"weight_lbs": 200}], [])
        assert wc._compute_centenarian_progress({}, "not-a-date") is None


class TestStoreCentenarianProgress:
    def test_writes_a_decimal_safe_item(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_centenarian_progress(
            "2026-W27",
            {
                "bodyweight_lbs": 200.0,
                "overall_readiness": 82.5,
                "priority_lift": "overhead_press",
                "lifts_scored": 4,
                "lifts": {"deadlift": {"current_lbs": 420.0, "status": "exceeds_target", "target_lbs": None}},
            },
            "2026-06-30",
            "2026-06-30T18:30:00+00:00",
        )
        item = fake.puts[0]
        assert item["pk"] == wc.USER_PREFIX + "centenarian_progress"
        assert item["sk"] == "WEEK#2026-W27"
        assert item["bodyweight_lbs"] == Decimal("200")
        assert item["overall_readiness"] == Decimal("82.5")
        assert item["lifts_scored"] == Decimal("4")
        assert item["lifts"]["deadlift"]["current_lbs"] == Decimal("420")
        assert item["lifts"]["deadlift"]["status"] == "exceeds_target"
        assert "target_lbs" not in item["lifts"]["deadlift"]  # None fields are dropped

    def test_unscorable_and_non_numeric_fields_encode_as_absent(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_centenarian_progress(
            "2026-W27",
            {"bodyweight_lbs": "not a number", "overall_readiness": None, "priority_lift": None, "lifts_scored": 0, "lifts": {}},
            "2026-06-30",
            "ts",
        )
        item = fake.puts[0]
        assert item["overall_readiness"] is None  # no lift scored — no fabricated 0%
        assert item["bodyweight_lbs"] is None  # unparseable input degrades, never raises
        assert "priority_lift" not in item

    def test_no_progress_is_a_no_op(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_centenarian_progress("2026-W27", None, "2026-06-30", "ts")
        assert fake.puts == []


# ══════════════════════════════════════════════════════════════════════════════
# BS-TR2 — zone 2 cardiac efficiency
# ══════════════════════════════════════════════════════════════════════════════

_TEN_MILES_M = 10.0 / 0.000621371  # metres in 10 miles, so speed_mph = distance/hours


def _strava_day(date, avg_hr, *, duration_s=3600, distance_m=_TEN_MILES_M, sport="run"):
    return {
        "date": date,
        "activities": [
            {
                "average_heartrate": avg_hr,
                "moving_time_seconds": duration_s,
                "distance": distance_m,
                "sport_type": sport,
            }
        ],
    }


class TestZone2Efficiency:
    def _stub(self, monkeypatch, records):
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({"strava": records}))

    def test_efficiency_is_speed_over_heart_rate(self, monkeypatch):
        # 10 miles in 1 hour = 10 mph; 10 / 125 bpm = 0.08.
        self._stub(monkeypatch, [_strava_day("2026-06-01", 125)])
        out = wc._compute_zone2_efficiency({}, "2026-06-30")
        assert out["weeks_analyzed"] == 1
        assert out["weekly"][0]["avg_efficiency"] == pytest.approx(0.08, abs=1e-6)
        assert out["weekly"][0]["n_sessions"] == 1
        assert out["trend"] == "insufficient_data"  # fewer than 4 weeks
        assert out["slope_per_week"] is None and out["pct_change_per_week"] is None
        assert out["zone2_hr_range"] == f"{wc.ZONE2_HR_LOW}–{wc.ZONE2_HR_HIGH} bpm"

    def test_improving_trend_over_four_weeks(self, monkeypatch):
        # Same pace at a steadily LOWER heart rate = rising efficiency.
        self._stub(
            monkeypatch,
            [
                _strava_day("2026-06-01", 125),
                _strava_day("2026-06-08", 120),
                _strava_day("2026-06-15", 115),
                _strava_day("2026-06-22", 110),
            ],
        )
        out = wc._compute_zone2_efficiency({}, "2026-06-30")
        assert out["weeks_analyzed"] == 4
        assert out["trend"] == "improving"
        assert out["slope_per_week"] > 0
        assert out["pct_change_per_week"] > 0
        assert out["baseline_efficiency"] == pytest.approx(0.08, abs=1e-6)  # 10/125
        assert out["latest_efficiency"] == pytest.approx(10.0 / 110.0, abs=1e-5)
        assert out["latest_efficiency"] > out["baseline_efficiency"]

    def test_declining_trend(self, monkeypatch):
        self._stub(
            monkeypatch,
            [
                _strava_day("2026-06-01", 110),
                _strava_day("2026-06-08", 115),
                _strava_day("2026-06-15", 120),
                _strava_day("2026-06-22", 125),
            ],
        )
        out = wc._compute_zone2_efficiency({}, "2026-06-30")
        assert out["trend"] == "declining" and out["slope_per_week"] < 0

    def test_identical_weeks_are_stable_not_a_trend(self, monkeypatch):
        self._stub(monkeypatch, [_strava_day(d, 125) for d in ("2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22")])
        out = wc._compute_zone2_efficiency({}, "2026-06-30")
        assert out["trend"] == "stable"
        assert out["slope_per_week"] == 0.0
        assert out["pct_change_per_week"] == 0.0

    def test_sessions_outside_the_zone_or_too_short_are_excluded(self, monkeypatch):
        self._stub(
            monkeypatch,
            [
                _strava_day("2026-06-01", wc.ZONE2_HR_LOW - 1),  # below zone
                _strava_day("2026-06-02", wc.ZONE2_HR_HIGH + 1),  # above zone
                _strava_day("2026-06-03", 125, duration_s=19 * 60),  # too short
                _strava_day("2026-06-04", 125, sport="WeightTraining"),  # not aerobic
                _strava_day("2026-06-05", 125, distance_m=0),  # no distance
                {"date": "2026-06-06", "activities": [{"moving_time_seconds": 3600, "distance": 5000}]},  # no HR
            ],
        )
        assert wc._compute_zone2_efficiency({}, "2026-06-30") is None

    def test_zone_boundaries_are_inclusive(self, monkeypatch):
        self._stub(monkeypatch, [_strava_day("2026-06-01", wc.ZONE2_HR_LOW), _strava_day("2026-06-02", wc.ZONE2_HR_HIGH)])
        out = wc._compute_zone2_efficiency({}, "2026-06-30")
        assert out["weekly"][0]["n_sessions"] == 2  # both land in the same ISO week

    def test_records_with_no_usable_date_are_skipped(self, monkeypatch):
        self._stub(monkeypatch, [{"activities": []}, {"date": "nope", "activities": []}])
        assert wc._compute_zone2_efficiency({}, "2026-06-30") is None

    def test_is_non_fatal_on_a_bad_end_date(self, monkeypatch):
        self._stub(monkeypatch, [])
        assert wc._compute_zone2_efficiency({}, "not-a-date") is None


class TestStoreZone2Efficiency:
    def test_writes_a_decimal_safe_item(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_zone2_efficiency(
            "2026-W27",
            {
                "weeks_analyzed": 2,
                "weekly": [{"week": "2026-W23", "avg_efficiency": 0.08, "n_sessions": 1}],
                "trend": "improving",
                "slope_per_week": 0.001,
                "pct_change_per_week": 1.23,
                "latest_efficiency": 0.081,
                "baseline_efficiency": 0.08,
                "zone2_hr_range": "110–139 bpm",
            },
            "2026-06-30",
            "ts",
        )
        item = fake.puts[0]
        assert item["pk"] == wc.USER_PREFIX + "zone2_efficiency"
        assert item["weeks_analyzed"] == Decimal("2")
        assert item["weekly"][0]["avg_efficiency"] == Decimal("0.08")
        assert item["weekly"][0]["n_sessions"] == Decimal("1")
        assert item["slope_per_week"] == Decimal("0.001")
        assert item["pct_change_per_week"] == Decimal("1.23")

    def test_optional_trend_fields_are_omitted_when_absent(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_zone2_efficiency(
            "2026-W27",
            {
                "weeks_analyzed": 1,
                "weekly": [],
                "trend": "insufficient_data",
                "slope_per_week": None,
                "pct_change_per_week": None,
                "latest_efficiency": 0.08,
                "baseline_efficiency": 0.08,
                "zone2_hr_range": "110–139 bpm",
            },
            "2026-06-30",
            "ts",
        )
        assert "slope_per_week" not in fake.puts[0]
        assert "pct_change_per_week" not in fake.puts[0]

    def test_missing_and_non_numeric_efficiencies_encode_as_absent(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_zone2_efficiency(
            "2026-W27",
            {
                "weeks_analyzed": 0,
                "weekly": [],
                "trend": "insufficient_data",
                "latest_efficiency": None,
                "baseline_efficiency": "n/a",
                "zone2_hr_range": "110–139 bpm",
            },
            "2026-06-30",
            "ts",
        )
        item = fake.puts[0]
        assert item["latest_efficiency"] is None
        assert item["baseline_efficiency"] is None  # unparseable degrades, never raises

    def test_no_efficiency_is_a_no_op(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_zone2_efficiency("2026-W27", None, "2026-06-30", "ts")
        assert fake.puts == []


# ══════════════════════════════════════════════════════════════════════════════
# store_correlations / store_what_changed / the first-seen ledger
# ══════════════════════════════════════════════════════════════════════════════


class TestStoreCorrelations:
    def test_encodes_every_scalar_type_for_dynamodb(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        corr = {
            "hrv_vs_recovery": {
                "pearson_r": 0.4545,
                "n_days": 10,
                "n_eff": 6.9,
                "interpretation": "weak",
                "counterintuitive": False,
                "fdr_significant": True,
                "lag_days": None,
                "gloss": None,
            }
        }
        wc.store_correlations("2026-W27", corr, "2026-04-01", "2026-06-30", "2026-06-30T18:30:00+00:00")
        item = fake.puts[0]
        assert item["pk"] == wc.USER_PREFIX + "weekly_correlations"
        assert item["sk"] == "WEEK#2026-W27"
        assert item["start_date"] == "2026-04-01" and item["end_date"] == "2026-06-30"
        assert item["n_pairs"] == Decimal("1")
        assert item["lookback_days"] == Decimal(str(wc.LOOKBACK_DAYS))
        stored = item["correlations"]["hrv_vs_recovery"]
        assert stored["pearson_r"] == Decimal("0.4545")
        assert stored["n_days"] == Decimal("10")
        assert stored["n_eff"] == Decimal("6.9")
        assert stored["interpretation"] == "weak"
        # bools must stay bools — bool is an int subclass, so order matters here.
        assert stored["counterintuitive"] is False
        assert stored["fdr_significant"] is True
        # None values are dropped rather than written as NULL.
        assert "lag_days" not in stored and "gloss" not in stored

    def test_record_is_provenance_tagged(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_correlations("2026-W27", {}, "2026-04-01", "2026-06-30", "ts")
        assert "run_id" in fake.puts[0] and "phase" in fake.puts[0]


class TestWhatChangedLedger:
    def _corr(self, significant=True):
        return {
            "hrv_vs_recovery": {
                "fdr_significant": significant,
                "metric_a": "hrv",
                "metric_b": "recovery_score",
                "pearson_r": 0.62,
                "n_days": 55,
                "direction": "positive",
                "interpretation": "strong",
                "gloss": None,
            }
        }

    def test_first_significant_run_stamps_and_announces(self):
        fresh, ledger = wc.diff_newly_unlocked(self._corr(), {}, "2026-06-30")
        assert [f["label"] for f in fresh] == ["hrv_vs_recovery"]
        assert fresh[0]["r"] == 0.62 and fresh[0]["n"] == 55
        assert fresh[0]["first_seen"] == "2026-06-30"
        assert ledger == {"hrv_vs_recovery": "2026-06-30"}

    def test_a_pair_is_never_re_announced_after_the_window(self):
        # Stamped 60 days ago; still significant, but outside the 30-day window.
        fresh, ledger = wc.diff_newly_unlocked(self._corr(), {"hrv_vs_recovery": "2026-05-01"}, "2026-06-30")
        assert fresh == []
        assert ledger["hrv_vs_recovery"] == "2026-05-01"  # original stamp preserved

    def test_non_significant_pairs_are_never_stamped(self):
        fresh, ledger = wc.diff_newly_unlocked(self._corr(significant=False), {}, "2026-06-30")
        assert fresh == [] and ledger == {}

    def test_a_corrupt_ledger_date_falls_back_to_the_run_date(self):
        fresh, _ = wc.diff_newly_unlocked(self._corr(), {"hrv_vs_recovery": "garbage"}, "2026-06-30")
        assert len(fresh) == 1  # treated as seen today rather than crashing the run

    def test_legacy_row_without_a_gloss_key_is_glossed_on_read(self):
        corr = self._corr()
        del corr["hrv_vs_recovery"]["gloss"]
        corr["hrv_vs_recovery"]["n_days"] = 12  # r=0.62 on n=12 is an n-gate downgrade
        corr["hrv_vs_recovery"]["interpretation"] = "weak"
        fresh, _ = wc.diff_newly_unlocked(corr, {}, "2026-06-30")
        assert fresh[0]["gloss"] == "evidence still thin"

    def test_empty_inputs_are_a_calm_null(self):
        assert wc.diff_newly_unlocked(None, None, "2026-06-30") == ([], {})


class TestStoreWhatChanged:
    def test_writes_the_snapshot_and_the_ledger(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_what_changed(
            "2026-W27",
            [{"metric": "hrv", "delta": 3.5, "n_this": 20, "n_prior": 18}],
            [{"label": "hrv_vs_recovery", "r": 0.62}],
            {"hrv_vs_recovery": "2026-06-30"},
            "2026-06-30",
            "ts",
        )
        snap, ledger = fake.puts
        assert snap["sk"] == "SNAPSHOT#current"
        assert snap["window_start"] == "2026-06-01" and snap["window_end"] == "2026-06-30"  # end - 29 days
        assert snap["honest_null"] is False
        assert snap["deltas"][0]["delta"] == Decimal("3.5")
        assert snap["newly_unlocked"][0]["r"] == Decimal("0.62")
        assert ledger["sk"] == "STATE#first_seen"
        assert ledger["first_sig"] == {"hrv_vs_recovery": "2026-06-30"}

    def test_nothing_moved_is_an_honest_null(self, monkeypatch):
        fake = FakeTable()
        monkeypatch.setattr(wc, "table", fake)
        wc.store_what_changed("2026-W27", [], [], {}, "2026-06-30", "ts")
        assert fake.puts[0]["honest_null"] is True

    def test_month_deltas_skip_unparseable_dates(self):
        series = {"2026-06-30": {"hrv": 60.0}, "garbage": {"hrv": 999.0}}
        assert wc.compute_month_deltas(series, "2026-06-30") == []  # too few real days either half


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — the four exit paths
# ══════════════════════════════════════════════════════════════════════════════


class _FrozenDatetime(datetime):
    """datetime with a pinned now() — no wall-clock math against fixture dates."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 30, 18, 30, 0, tzinfo=tz)


class TestLambdaHandler:
    def _rich_series(self, days=40):
        dates = _sk_dates(days, start="2026-05-22")
        return {
            d: {
                "hrv": 50.0 + (i % 7),
                "recovery_score": 60.0 + (i % 5),
                "sleep_duration": 7.0 + (i % 3) * 0.25,
                "steps": 8000.0 + 100 * (i % 11),
                "training_kj": 300.0 + 10 * (i % 4),
                "habit_pct": 0.5 + 0.05 * (i % 6),
                "day_grade": 70.0 + (i % 9),
            }
            for i, d in enumerate(dates)
        }

    def _wire(self, monkeypatch, table, series):
        monkeypatch.setattr(wc, "datetime", _FrozenDatetime)
        freeze_pacific(monkeypatch, wc, _FrozenDatetime)
        monkeypatch.setattr(wc, "table", table)
        monkeypatch.setattr(wc, "assemble_daily_series", lambda s, e: series)
        monkeypatch.setattr(wc, "fetch_range", _fetch_stub({}))

    def test_idempotent_skip_when_the_week_is_already_stored(self, monkeypatch):
        key = (wc.USER_PREFIX + "weekly_correlations", "WEEK#2026-W27")
        fake = FakeTable(get_items={key: {"computed_at": "2026-06-30T18:00:00+00:00"}})
        self._wire(monkeypatch, fake, self._rich_series())
        out = wc.lambda_handler({}, None)
        assert out["skipped"] is True
        assert out["week"] == "2026-W27"  # ISO week of the pinned now()
        assert fake.puts == []  # nothing recomputed, nothing rewritten

    def test_a_failed_idempotency_read_does_not_block_the_run(self, monkeypatch):
        fake = FakeTable(get_raises=True)
        self._wire(monkeypatch, fake, self._rich_series())
        out = wc.lambda_handler({}, None)
        # Fail-soft: the read error is logged and the compute proceeds anyway.
        assert out.get("skipped") is None
        assert out["pairs_computed"] == len(wc.CORRELATION_PAIRS)

    def test_insufficient_data_returns_the_honest_count(self, monkeypatch):
        fake = FakeTable()
        self._wire(monkeypatch, fake, self._rich_series(days=experiment_gates.CORRELATION_MIN_N - 1))
        out = wc.lambda_handler({}, None)
        assert out["days_available"] == experiment_gates.CORRELATION_MIN_N - 1
        assert str(experiment_gates.CORRELATION_MIN_N) in out["body"]
        assert "pairs_computed" not in out
        assert fake.puts == []  # never store a result computed on too little data

    def test_full_run_writes_every_partition(self, monkeypatch):
        fake = FakeTable()
        self._wire(monkeypatch, fake, self._rich_series())
        out = wc.lambda_handler({"force": True}, None)
        assert out["statusCode"] == 200
        assert out["week"] == "2026-W27"
        assert out["end_date"] == "2026-06-30"
        assert out["start_date"] == "2026-04-02"  # end - (LOOKBACK_DAYS - 1) = 90-day window
        assert out["days_analyzed"] == 40
        assert out["pairs_computed"] == len(wc.CORRELATION_PAIRS)
        assert out["significant"] >= 0
        sks = [p["sk"] for p in fake.puts]
        assert "WEEK#2026-W27" in sks  # correlations
        assert "SNAPSHOT#current" in sks and "STATE#first_seen" in sks  # SS-08
        assert fake.get_calls  # the SS-08 first-seen ledger was read

    def test_force_skips_the_idempotency_read(self, monkeypatch):
        key = (wc.USER_PREFIX + "weekly_correlations", "WEEK#2026-W27")
        fake = FakeTable(get_items={key: {"computed_at": "already"}})
        self._wire(monkeypatch, fake, self._rich_series())
        out = wc.lambda_handler({"force": True}, None)
        assert out.get("skipped") is None
        assert ("WEEK#2026-W27") in [p["sk"] for p in fake.puts]

    def test_explicit_week_override_is_honoured(self, monkeypatch):
        fake = FakeTable()
        self._wire(monkeypatch, fake, self._rich_series())
        out = wc.lambda_handler({"week": "2026-W10", "force": True}, None)
        assert out["week"] == "2026-W10"
        assert [p["sk"] for p in fake.puts][0] == "WEEK#2026-W10"

    def test_manual_week_round_trips_to_the_scheduled_end_date(self, monkeypatch):
        # #2175: the manual override must derive target_monday the same way
        # the scheduled path does (ISO 8601 weeks via isocalendar()/
        # fromisocalendar()), not via strptime's %W (which is NOT ISO week
        # numbering). Pin "now" to the Sunday that ends ISO week 2026-W01 —
        # under the old %W parse this diverges by a full week (see the sibling
        # test below); under the fix both paths land on the same end_date.
        class _SundayOfWeek1(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 1, 4, 18, 30, 0, tzinfo=tz)

        fake_scheduled = FakeTable()
        self._wire(monkeypatch, fake_scheduled, self._rich_series())
        monkeypatch.setattr(wc, "datetime", _SundayOfWeek1)
        freeze_pacific(monkeypatch, wc, _SundayOfWeek1)
        scheduled_out = wc.lambda_handler({"force": True}, None)
        assert scheduled_out["week"] == "2026-W01"
        assert scheduled_out["end_date"] == "2026-01-04"

        fake_manual = FakeTable()
        self._wire(monkeypatch, fake_manual, self._rich_series())
        monkeypatch.setattr(wc, "datetime", _SundayOfWeek1)
        freeze_pacific(monkeypatch, wc, _SundayOfWeek1)
        manual_out = wc.lambda_handler({"week": "2026-W01", "force": True}, None)
        assert manual_out["week"] == "2026-W01"
        # The load-bearing assertion: a manual re-run of the SAME ISO week the
        # scheduled path would have written must recompute the SAME date
        # window, not a shifted one.
        assert manual_out["end_date"] == scheduled_out["end_date"] == "2026-01-04"

    def test_manual_week_pins_the_W01_divergence_against_regression(self, monkeypatch):
        # #2175: 2026-01-01 is a Thursday, so ISO week 2026-W01 runs
        # 2025-12-29 → 2026-01-04. strptime's "%Y-W%W-%w" instead resolves
        # "2026-W01-1" to 2026-01-05 (the first Monday *numbered* within
        # 2026), a full week later — end_date 2026-01-11 instead of the
        # correct 2026-01-04. Pin this exact divergent week so any future
        # regression back to %W trips this test immediately.
        fake = FakeTable()
        self._wire(monkeypatch, fake, self._rich_series())
        out = wc.lambda_handler({"week": "2026-W01", "force": True}, None)
        assert out["end_date"] == "2026-01-04"
        assert out["start_date"] == (date(2026, 1, 4) - timedelta(days=wc.LOOKBACK_DAYS - 1)).strftime("%Y-%m-%d")

    def test_benchmark_and_month_stages_are_non_fatal(self, monkeypatch):
        fake = FakeTable()
        self._wire(monkeypatch, fake, self._rich_series())

        def _boom(*a, **k):
            raise RuntimeError("stage exploded")

        monkeypatch.setattr(wc, "_compute_centenarian_progress", _boom)
        monkeypatch.setattr(wc, "_compute_zone2_efficiency", _boom)
        monkeypatch.setattr(wc, "compute_month_deltas", _boom)
        out = wc.lambda_handler({"force": True}, None)
        # The correlations — the run's actual product — still land.
        assert out["statusCode"] == 200
        assert [p["sk"] for p in fake.puts] == ["WEEK#2026-W27"]
