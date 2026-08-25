"""tests/test_coach_computation_engine.py — the deterministic statistics layer
that every coach brief is built on (#1658 coverage ratchet).

`lambdas/coach/coach_computation_engine.py` is the ADR-105 chokepoint: "ALL math
happens here — the LLM never does math." Everything downstream (trend direction,
the regression-to-mean caveat, the decision-class ceiling a coach is allowed to
claim, the narrative arc) is a pure function of these numbers, so the tests below
assert on ACTUAL VALUES derived by hand, not on shapes:

  * `ewma` — normalized geometric weights, newest heaviest. Checked against
    closed-form expectations (e.g. [10, 20] @ decay 0.5 -> 50/3), plus the
    degenerate inputs: empty, single sample, all-identical, decay 1.0 (zero
    weight mass) and decay 0.0 (last value only).
  * `_extract_metric_series` — date resolution, sort order, and what is dropped.
  * `_compute_trends` — the +/-2% direction threshold and the 9-point floor the
    "EWMA from 7 data points ago" comparison implies.
  * `is_likely_regression_to_mean` / `_detect_regression_to_mean` — the z>1.5
    boundary (strict) and the hand-computed population mean/std/z of a series
    with one outlier.
  * `_compute_seasonality_flags` — alignment logic + the metadata-key guard.
  * `_detect_autocorrelation_warnings` — the 5-consecutive-point rule, including
    the deliberate "equal values don't break the run" skip.
  * `_compute_statistical_guardrails` — every level boundary (6/7/13/14).
  * `_detect_arc_transition` — each edge of the state machine, both DDB writes,
    and the fail-soft paths.
  * the IO seams (`_s3_json`, `_fetch_range`, `_write_results`) — fallback
    behavior when the read fails, which is what actually happens in production
    when a config object or a grant is missing.

Fully offline: DynamoDB is `tests/fakes.FakeDdbTable`, S3 is a local double, and
every test that depends on "today" freezes the clock or passes the date in — no
wall-clock now-math against fixture dates.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pacific_clock import freeze_pacific  # noqa: E402 — #2811: the PT clock the module actually calls

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import coach_computation_engine as engine  # noqa: E402
from fakes import FakeDdbTable, raise_hook  # noqa: E402

# ── deterministic clock ──────────────────────────────────────────────────────
# The module does `from datetime import datetime`, so replacing engine.datetime
# with a real subclass keeps strptime/arithmetic intact while pinning now().

_FROZEN_NOW = datetime(2026, 6, 15, 17, 45, tzinfo=timezone.utc)
_FROZEN_ISO = _FROZEN_NOW.isoformat()
_FROZEN_DATE = "2026-06-15"


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN_NOW


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(engine, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, engine, _FrozenDatetime)
    return _FROZEN_NOW


@pytest.fixture(autouse=True)
def _no_ssm(monkeypatch):
    """experiment_stamp() reads the cycle from SSM on every write and a FAILED
    read is deliberately not cached (#1948) — stub it so no test touches the
    network, while leaving the real stamp path exercised."""
    import coach.coach_checkin as coach_checkin

    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 12)


# ── record builders ──────────────────────────────────────────────────────────


def _records(metric, values, start="2026-06-01"):
    """Chronological DDB-shaped records, one per day, carrying `metric`."""
    d0 = date.fromisoformat(start)
    return [{"pk": "USER#matthew#SOURCE#x", "sk": "DATE#" + (d0 + timedelta(days=i)).isoformat(), metric: v} for i, v in enumerate(values)]


def _trends(up=0, down=0, flat=0, insufficient=0):
    metrics = {}
    for i in range(up):
        metrics[f"u{i}"] = {"direction": "up"}
    for i in range(down):
        metrics[f"d{i}"] = {"direction": "down"}
    for i in range(flat):
        metrics[f"f{i}"] = {"direction": "flat"}
    for i in range(insufficient):
        metrics[f"n{i}"] = {"direction": "insufficient_data"}
    return {"whoop": metrics}


# =============================================================================
# _safe_float
# =============================================================================


class TestSafeFloat:
    def test_reads_decimal_as_float(self):
        out = engine._safe_float({"hrv": Decimal("72.5")}, "hrv")
        assert out == 72.5
        assert isinstance(out, float)

    def test_parses_numeric_string(self):
        assert engine._safe_float({"hrv": "3.5"}, "hrv") == 3.5

    def test_missing_field_returns_default(self):
        assert engine._safe_float({"hrv": 1}, "recovery_score") is None
        assert engine._safe_float({"hrv": 1}, "recovery_score", default=-1.0) == -1.0

    def test_empty_or_none_item_returns_default(self):
        assert engine._safe_float(None, "hrv", default=0.0) == 0.0
        assert engine._safe_float({}, "hrv", default=0.0) == 0.0

    def test_unparseable_value_returns_default_not_raise(self):
        # A present-but-garbage attribute is the real DDB failure mode; the
        # default must come back rather than an exception escaping into a
        # whole-component failure.
        assert engine._safe_float({"hrv": "n/a"}, "hrv", default=-1.0) == -1.0
        assert engine._safe_float({"hrv": None}, "hrv", default=-1.0) == -1.0
        assert engine._safe_float({"hrv": {"nested": 1}}, "hrv") is None


# =============================================================================
# COMPONENT 1a: ewma
# =============================================================================


class TestEwma:
    def test_empty_series_returns_none(self):
        assert engine.ewma([], 0.9) is None

    def test_single_sample_returns_that_sample(self):
        # n=1 -> one weight, normalized to 1.0: the EWMA of one point is the point.
        assert engine.ewma([42.0], 0.9) == 42.0

    def test_all_identical_values_return_that_value(self):
        assert engine.ewma([7.0] * 12, 0.85) == pytest.approx(7.0)

    def test_two_points_matches_closed_form(self):
        # weights (unnormalized, oldest->newest) = [d, 1] = [0.5, 1]
        # (10*0.5 + 20*1) / 1.5 = 25/1.5 = 50/3
        assert engine.ewma([10.0, 20.0], 0.5) == pytest.approx(50.0 / 3.0)

    def test_three_points_matches_closed_form(self):
        # weights = [0.25, 0.5, 1]; (0.25 + 1.0 + 3.0)/1.75 = 4.25/1.75 = 17/7
        assert engine.ewma([1.0, 2.0, 3.0], 0.5) == pytest.approx(17.0 / 7.0)

    def test_weights_the_most_recent_sample_hardest(self):
        # Order matters and the tail dominates: same two samples, reversed.
        rising = engine.ewma([10.0, 20.0], 0.5)
        falling = engine.ewma([20.0, 10.0], 0.5)
        assert rising == pytest.approx(50.0 / 3.0)
        assert falling == pytest.approx(40.0 / 3.0)
        assert rising > 15.0 > falling  # both pulled off the simple mean, opposite ways

    def test_lower_decay_is_more_reactive_than_higher_decay(self):
        series = [100.0] * 8 + [200.0]
        fast = engine.ewma(series, 0.5)
        slow = engine.ewma(series, 0.95)
        assert fast == pytest.approx(150.09784735812133)  # 76700/511
        assert slow < fast  # a longer memory discounts the fresh spike more

    def test_decay_zero_collapses_to_the_last_value(self):
        # weights = [0, 0, 1] -> only the most recent sample survives.
        assert engine.ewma([1.0, 2.0, 3.0], 0.0) == 3.0

    def test_decay_one_has_zero_weight_mass_and_returns_none(self):
        # (1 - decay) == 0 for every weight -> undefined average, not a ZeroDivisionError.
        assert engine.ewma([1.0, 2.0, 3.0], 1.0) is None


# =============================================================================
# COMPONENT 1b: _extract_metric_series
# =============================================================================


class TestExtractMetricSeries:
    def test_sorts_chronologically_regardless_of_record_order(self):
        recs = [
            {"sk": "DATE#2026-06-03", "hrv": 60},
            {"sk": "DATE#2026-06-01", "hrv": 50},
            {"sk": "DATE#2026-06-02", "hrv": 55},
        ]
        assert engine._extract_metric_series(recs, "hrv") == [
            ("2026-06-01", 50.0),
            ("2026-06-02", 55.0),
            ("2026-06-03", 60.0),
        ]

    def test_date_field_wins_over_the_sort_key(self):
        recs = [{"sk": "DATE#2026-06-01", "date": "2026-06-09", "hrv": 61}]
        assert engine._extract_metric_series(recs, "hrv") == [("2026-06-09", 61.0)]

    def test_drops_records_missing_the_metric_or_carrying_junk(self):
        recs = [
            {"sk": "DATE#2026-06-01", "hrv": Decimal("50")},
            {"sk": "DATE#2026-06-02"},  # metric absent
            {"sk": "DATE#2026-06-03", "hrv": "not-a-number"},
            {"sk": "DATE#2026-06-04", "hrv": None},
            {"hrv": 99},  # no date and no sk -> unplaceable in time
        ]
        assert engine._extract_metric_series(recs, "hrv") == [("2026-06-01", 50.0)]

    def test_empty_input_yields_empty_series(self):
        assert engine._extract_metric_series([], "hrv") == []


# =============================================================================
# COMPONENT 1c: _compute_trends
# =============================================================================


class TestComputeTrends:
    def test_rising_series_reports_up_with_hand_computed_ewma_and_slope(self):
        # 9 points @ decay 0.5: current EWMA = 76700/511 = 150.097847...,
        # prior EWMA (values[:2] = [100, 100]) = 100 -> slope = +0.500978.
        data = {"withings": _records("weight_lbs", [100.0] * 8 + [200.0])}
        trends = engine._compute_trends(data, {"nutrition_body_comp": 0.5})

        t = trends["withings"]["weight_lbs"]
        assert t["ewma"] == pytest.approx(150.0978, abs=1e-4)
        assert t["ewma_7d_ago"] == pytest.approx(100.0)
        assert t["slope"] == pytest.approx(0.500978, abs=1e-6)
        assert t["direction"] == "up"
        assert t["n_points"] == 9
        assert t["domain"] == "nutrition_body_comp"

    def test_falling_series_reports_down(self):
        # same shape, mirrored: current EWMA = 38300/511 = 74.951076 -> slope -0.250489
        data = {"withings": _records("weight_lbs", [100.0] * 8 + [50.0])}
        t = engine._compute_trends(data, {"nutrition_body_comp": 0.5})["withings"]["weight_lbs"]
        assert t["ewma"] == pytest.approx(74.9511, abs=1e-4)
        assert t["slope"] == pytest.approx(-0.250489, abs=1e-6)
        assert t["direction"] == "down"

    def test_flat_series_reports_flat_with_zero_slope(self):
        data = {"withings": _records("weight_lbs", [200.0] * 12)}
        t = engine._compute_trends(data, {"nutrition_body_comp": 0.5})["withings"]["weight_lbs"]
        assert t["slope"] == pytest.approx(0.0, abs=1e-9)
        assert t["direction"] == "flat"
        assert t["ewma"] == pytest.approx(200.0)

    def test_sub_two_percent_move_stays_flat(self):
        # +1% on the tail is inside the +/-2% dead band -> deliberately not a trend.
        data = {"withings": _records("weight_lbs", [100.0] * 8 + [101.0])}
        t = engine._compute_trends(data, {"nutrition_body_comp": 0.5})["withings"]["weight_lbs"]
        assert 0.0 < t["slope"] < 0.02
        assert t["direction"] == "flat"

    def test_falls_back_to_default_decay_when_domain_missing_from_params(self):
        # ewma_params.get(domain, 0.90): with 0.90 the same 9-point series gives
        # EWMA 116.3244 and slope +0.163244.
        data = {"withings": _records("weight_lbs", [100.0] * 8 + [200.0])}
        t = engine._compute_trends(data, {})["withings"]["weight_lbs"]
        assert t["ewma"] == pytest.approx(116.3244, abs=1e-4)
        assert t["slope"] == pytest.approx(0.163244, abs=1e-6)

    def test_series_shorter_than_two_points_is_skipped_entirely(self):
        data = {"withings": _records("weight_lbs", [200.0])}
        assert engine._compute_trends(data, {"nutrition_body_comp": 0.5}) == {}

    def test_sources_with_no_records_are_absent_from_the_result(self):
        data = {"withings": _records("weight_lbs", [200.0] * 9), "whoop": []}
        trends = engine._compute_trends(data, {})
        assert set(trends) == {"withings"}

    def test_under_nine_points_yields_no_slope_because_the_prior_window_is_too_short(self):
        # cutoff = max(1, n - 7), and the prior EWMA needs >= 2 points, so a
        # slope only exists at n >= 9. At n == 8 the metric is reported with a
        # null slope and the "flat" default rather than a fabricated direction.
        data = {"withings": _records("weight_lbs", [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0])}
        t = engine._compute_trends(data, {"nutrition_body_comp": 0.5})["withings"]["weight_lbs"]
        assert t["n_points"] == 8
        assert t["ewma_7d_ago"] is None
        assert t["slope"] is None
        # #2179: a metric with too little history to compute the 7-day-ago EWMA was
        # never actually measured as flat -> honest "insufficient_data", not a
        # fabricated "flat" that would silently vote toward a plateau transition.
        assert t["direction"] == "insufficient_data"


# =============================================================================
# COMPONENT 2: regression to mean
# =============================================================================


class TestIsLikelyRegressionToMean:
    def test_extreme_prior_moving_back_toward_the_mean_is_flagged(self):
        # prior z = |70-50|/10 = 2.0 > 1.5, and |55-50| < |70-50|.
        assert engine.is_likely_regression_to_mean(current=55, prior=70, baseline_mean=50, baseline_std=10) is True

    def test_extreme_prior_moving_further_out_is_not_regression(self):
        assert engine.is_likely_regression_to_mean(current=75, prior=70, baseline_mean=50, baseline_std=10) is False

    def test_unremarkable_prior_is_never_flagged(self):
        # z = 1.0: nothing extreme to regress from, even though it moved inward.
        assert engine.is_likely_regression_to_mean(current=51, prior=60, baseline_mean=50, baseline_std=10) is False

    def test_z_threshold_is_strictly_greater_than_1_point_5(self):
        # prior exactly 1.5 sd out -> not flagged; a hair beyond -> flagged.
        assert engine.is_likely_regression_to_mean(current=50, prior=65, baseline_mean=50, baseline_std=10) is False
        assert engine.is_likely_regression_to_mean(current=50, prior=65.1, baseline_mean=50, baseline_std=10) is True

    def test_symmetric_below_the_mean(self):
        assert engine.is_likely_regression_to_mean(current=45, prior=30, baseline_mean=50, baseline_std=10) is True

    def test_zero_or_missing_spread_is_never_regression(self):
        # No variance means no z-score; the guard must return False, not divide by zero.
        assert engine.is_likely_regression_to_mean(current=55, prior=70, baseline_mean=50, baseline_std=0) is False
        assert engine.is_likely_regression_to_mean(current=55, prior=70, baseline_mean=50, baseline_std=None) is False


class TestDetectRegressionToMean:
    # baseline = values[:-1] = [50]*6 + [80]
    #   mean     = 380/7          = 54.285714...
    #   variance = 771.428571/7   = 110.204081...  (population, /n)
    #   std      = 10.497813...
    #   prior z  = 25.714286/10.497813 = sqrt(6) = 2.449490
    _SERIES = [50.0] * 6 + [80.0, 52.0]

    def test_emits_a_warning_with_hand_computed_statistics(self):
        data = {"withings": _records("weight_lbs", self._SERIES)}
        warnings = engine._detect_regression_to_mean(data)

        assert len(warnings) == 1
        w = warnings[0]
        assert w["source"] == "withings"
        assert w["metric"] == "weight_lbs"
        assert w["current"] == 52.0
        assert w["prior"] == 80.0
        assert w["baseline_mean"] == pytest.approx(54.2857, abs=1e-4)
        assert w["baseline_std"] == pytest.approx(10.4978, abs=1e-4)
        assert w["prior_z_score"] == pytest.approx(2.45, abs=1e-2)
        assert "regression to mean" in w["message"]
        assert "z=2.4" in w["message"]

    def test_no_warning_when_the_move_continues_away_from_the_mean(self):
        data = {"withings": _records("weight_lbs", [50.0] * 6 + [80.0, 95.0])}
        assert engine._detect_regression_to_mean(data) == []

    def test_series_shorter_than_seven_points_is_skipped(self):
        # Same spike-then-drop shape, one point short of the n>=7 floor.
        data = {"withings": _records("weight_lbs", [50.0] * 4 + [80.0, 52.0])}
        assert engine._detect_regression_to_mean(data) == []

    def test_zero_variance_baseline_is_skipped(self):
        data = {"withings": _records("weight_lbs", [50.0] * 10)}
        assert engine._detect_regression_to_mean(data) == []

    def test_no_data_yields_no_warnings(self):
        assert engine._detect_regression_to_mean({}) == []
        assert engine._detect_regression_to_mean({"withings": []}) == []


# =============================================================================
# COMPONENT 3: seasonality flags
# =============================================================================


class TestSeasonalityFlags:
    # whoop.sleep_duration_hours: 3 older days at 7h, then 7 recent days at 8h.
    # older_avg = 7.0, recent_avg = 8.0 -> observed_change = +1.0.
    _RISING = [7.0] * 3 + [8.0] * 7

    def test_flags_a_rise_that_matches_a_positive_seasonal_expectation(self):
        data = {"whoop": _records("sleep_duration_hours", self._RISING)}
        flags = engine._compute_seasonality_flags(data, engine.DEFAULT_SEASONAL_ADJUSTMENTS, 6)

        assert len(flags) == 1
        f = flags[0]
        assert f["source"] == "whoop"
        assert f["metric"] == "sleep_duration_hours"
        assert f["month"] == 6
        assert f["expected_seasonal_adjustment"] == 10  # June, from the defaults
        assert f["observed_change"] == pytest.approx(1.0)
        assert "Deseasonalized trend may be flat" in f["message"]

    def test_no_flag_when_the_observed_move_opposes_the_season(self):
        # January expects -15; the data rose. The trend is *more* interesting,
        # not less, so nothing is flagged.
        data = {"whoop": _records("sleep_duration_hours", self._RISING)}
        assert engine._compute_seasonality_flags(data, engine.DEFAULT_SEASONAL_ADJUSTMENTS, 1) == []

    def test_no_flag_for_a_month_with_a_zero_adjustment(self):
        data = {"whoop": _records("sleep_duration_hours", self._RISING)}
        assert engine._compute_seasonality_flags(data, engine.DEFAULT_SEASONAL_ADJUSTMENTS, 4) == []

    def test_month_absent_from_the_table_is_skipped(self):
        adjustments = {"sleep_duration_hours": {"6": 10}}
        data = {"whoop": _records("sleep_duration_hours", self._RISING)}
        assert engine._compute_seasonality_flags(data, adjustments, 7) == []

    def test_metadata_string_keys_do_not_break_the_component(self):
        # The live S3 config mixes _notes/version strings in with the per-metric
        # dicts; a str would blow up .get() and silently lose the whole component.
        adjustments = {
            "_notes": "population-level, reviewed quarterly",
            "version": "2",
            "sleep_duration_hours": {"6": 10},
        }
        data = {"whoop": _records("sleep_duration_hours", self._RISING)}
        flags = engine._compute_seasonality_flags(data, adjustments, 6)
        assert [f["metric"] for f in flags] == ["sleep_duration_hours"]

    def test_needs_more_than_seven_points_to_have_an_older_window(self):
        # Exactly 7 points leaves values[:-7] empty -> nothing to compare against.
        data = {"whoop": _records("sleep_duration_hours", [8.0] * 7)}
        assert engine._compute_seasonality_flags(data, engine.DEFAULT_SEASONAL_ADJUSTMENTS, 6) == []

    def test_no_data_for_the_metric_yields_no_flags(self):
        assert engine._compute_seasonality_flags({}, engine.DEFAULT_SEASONAL_ADJUSTMENTS, 6) == []


# =============================================================================
# COMPONENT 4: autocorrelation warnings
# =============================================================================


class TestAutocorrelationWarnings:
    def test_five_consecutive_moves_clears_the_bar(self):
        # 6 strictly rising points = 5 consecutive same-direction steps.
        data = {"whoop": _records("hrv", [50.0, 51.0, 52.0, 53.0, 54.0, 55.0])}
        assert engine._detect_autocorrelation_warnings(data) == []

    def test_four_consecutive_moves_warns(self):
        data = {"whoop": _records("hrv", [50.0, 51.0, 52.0, 53.0, 54.0])}
        warnings = engine._detect_autocorrelation_warnings(data)
        assert len(warnings) == 1
        w = warnings[0]
        assert w["source"] == "whoop"
        assert w["metric"] == "hrv"
        assert w["consecutive_same_direction"] == 4
        assert w["min_required"] == 5
        assert "Likely autocorrelation" in w["message"]

    def test_a_reversal_immediately_before_the_tail_counts_as_one(self):
        data = {"whoop": _records("hrv", [50.0, 60.0, 70.0, 40.0, 45.0])}
        (w,) = engine._detect_autocorrelation_warnings(data)
        assert w["consecutive_same_direction"] == 1

    def test_equal_neighbours_do_not_break_the_run_but_do_not_extend_it(self):
        # [1, 2, 3, 3, 4, 5]: the 3->3 step is skipped, the run either side is
        # still "up" -> 4 counted steps, one short of the bar.
        data = {"whoop": _records("hrv", [1.0, 2.0, 3.0, 3.0, 4.0, 5.0])}
        (w,) = engine._detect_autocorrelation_warnings(data)
        assert w["consecutive_same_direction"] == 4

    def test_falling_runs_are_counted_the_same_way(self):
        data = {"whoop": _records("hrv", [55.0, 54.0, 53.0, 52.0, 51.0, 50.0])}
        assert engine._detect_autocorrelation_warnings(data) == []

    def test_series_shorter_than_three_points_is_skipped(self):
        data = {"whoop": _records("hrv", [50.0, 51.0])}
        assert engine._detect_autocorrelation_warnings(data) == []

    def test_non_autocorrelated_metrics_are_never_warned_about(self):
        # weight_lbs is not in AUTOCORRELATED_METRICS, so even a 1-step wobble
        # produces nothing.
        data = {"withings": _records("weight_lbs", [200.0, 205.0, 199.0, 204.0])}
        assert engine._detect_autocorrelation_warnings(data) == []
        assert "weight_lbs" not in engine.AUTOCORRELATED_METRICS

    def test_every_autocorrelated_metric_in_the_registry_is_reachable(self):
        # Guard the SET, not the instance: each flagged metric must actually be
        # listed under some source, or its rule can never fire.
        listed = {m for metrics in engine.SOURCE_METRICS.values() for m in metrics}
        assert engine.AUTOCORRELATED_METRICS <= listed


# =============================================================================
# COMPONENT 5: statistical guardrails
# =============================================================================


class TestStatisticalGuardrails:
    @pytest.mark.parametrize(
        "n,level,ceiling",
        [
            (1, "observational_only", "observational"),
            (6, "observational_only", "observational"),
            (7, "preliminary", "directional"),
            (13, "preliminary", "directional"),
            (14, "established", "interventional"),
            (30, "established", "interventional"),
        ],
    )
    def test_level_and_decision_ceiling_at_every_boundary(self, n, level, ceiling):
        data = {"withings": _records("weight_lbs", [200.0] * n)}
        g = engine._compute_statistical_guardrails(data)["withings"]["weight_lbs"]
        assert g["n_points"] == n
        assert g["level"] == level
        assert g["decision_class_ceiling"] == ceiling

    def test_metrics_absent_from_the_records_are_tagged_zero_not_omitted(self):
        # A coach must be able to see "no data" explicitly — silence would read
        # as "not measured this run" rather than "you may not claim anything".
        data = {"whoop": _records("hrv", [50.0] * 20)}
        whoop = engine._compute_statistical_guardrails(data)["whoop"]
        assert whoop["hrv"]["level"] == "established"
        assert whoop["recovery_score"] == {
            "level": "observational_only",
            "decision_class_ceiling": "observational",
            "n_points": 0,
        }

    def test_sources_with_no_records_are_omitted(self):
        data = {"whoop": _records("hrv", [50.0] * 8), "withings": []}
        assert set(engine._compute_statistical_guardrails(data)) == {"whoop"}
        assert engine._compute_statistical_guardrails({}) == {}


# =============================================================================
# IO SEAMS: S3 config load + DDB range fetch
# =============================================================================


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class _FakeS3:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.keys = []

    def get_object(self, Bucket, Key):
        self.keys.append((Bucket, Key))
        if self._error is not None:
            raise self._error
        return {"Body": _Body(json.dumps(self._payload).encode("utf-8"))}


class TestS3Json:
    def test_reads_and_parses_the_object(self, monkeypatch):
        fake = _FakeS3(payload={"sleep": 0.5})
        monkeypatch.setattr(engine, "s3", fake)
        assert engine._s3_json("config/computation/ewma_params.json") == {"sleep": 0.5}
        assert fake.keys == [(engine.S3_BUCKET, "config/computation/ewma_params.json")]

    def test_returns_none_on_read_failure(self, monkeypatch):
        monkeypatch.setattr(engine, "s3", _FakeS3(error=RuntimeError("NoSuchKey")))
        assert engine._s3_json("config/computation/ewma_params.json") is None


class TestConfigLoaders:
    def test_ewma_params_come_from_s3_when_present(self, monkeypatch):
        asked = []

        def _fake(key):
            asked.append(key)
            return {"sleep": 0.5, "hrv_recovery": 0.6}

        monkeypatch.setattr(engine, "_s3_json", _fake)
        assert engine._load_ewma_params() == {"sleep": 0.5, "hrv_recovery": 0.6}
        assert asked == ["config/computation/ewma_params.json"]

    @pytest.mark.parametrize("bad", [None, {}, [], "0.9", 0])
    def test_ewma_params_fall_back_to_defaults_on_any_unusable_read(self, monkeypatch, bad):
        monkeypatch.setattr(engine, "_s3_json", lambda key: bad)
        params = engine._load_ewma_params()
        assert params == engine.DEFAULT_EWMA_PARAMS
        # every domain the metric map can produce must have a decay to fall back on
        assert set(engine.METRIC_DOMAIN.values()) <= set(params)

    def test_seasonal_adjustments_come_from_s3_when_present(self, monkeypatch):
        asked = []

        def _fake(key):
            asked.append(key)
            return {"sleep_duration_hours": {"6": 3}}

        monkeypatch.setattr(engine, "_s3_json", _fake)
        assert engine._load_seasonal_adjustments() == {"sleep_duration_hours": {"6": 3}}
        assert asked == ["config/computation/seasonal_adjustments.json"]

    @pytest.mark.parametrize("bad", [None, {}, ["sleep"]])
    def test_seasonal_adjustments_fall_back_to_defaults(self, monkeypatch, bad):
        monkeypatch.setattr(engine, "_s3_json", lambda key: bad)
        assert engine._load_seasonal_adjustments() == engine.DEFAULT_SEASONAL_ADJUSTMENTS


def _paged_query_hook(pages):
    """Deterministic, terminating pagination double. The last page carries no
    LastEvaluatedKey, so the fetch loop always exits."""
    state = {"i": 0}

    def _hook(table, **kwargs):
        page = pages[min(state["i"], len(pages) - 1)]
        state["i"] += 1
        return page

    return _hook


class TestFetchRange:
    def test_walks_every_page_and_decimalises_to_float(self, monkeypatch):
        pages = [
            {"Items": [{"sk": "DATE#2026-06-01", "hrv": Decimal("50.5")}], "LastEvaluatedKey": {"sk": "DATE#2026-06-01"}},
            {"Items": [{"sk": "DATE#2026-06-02", "hrv": Decimal("51")}]},
        ]
        fake = FakeDdbTable(query_hook=_paged_query_hook(pages))
        monkeypatch.setattr(engine, "table", fake)

        records = engine._fetch_range("whoop", "2026-06-01", "2026-06-02")

        assert [r["hrv"] for r in records] == [50.5, 51.0]
        assert all(isinstance(r["hrv"], float) for r in records)
        assert len(fake.query_calls) == 2
        assert fake.query_calls[1]["ExclusiveStartKey"] == {"sk": "DATE#2026-06-01"}

    def test_applies_the_key_condition_and_the_adr_058_phase_filter(self, monkeypatch):
        fake = FakeDdbTable(query_hook=_paged_query_hook([{"Items": []}]))
        monkeypatch.setattr(engine, "table", fake)

        engine._fetch_range("whoop", "2026-06-01", "2026-06-15")

        (call,) = fake.query_calls
        assert call["ExpressionAttributeValues"][":pk"] == engine.USER_PREFIX + "whoop"
        assert call["ExpressionAttributeValues"][":s"] == "DATE#2026-06-01"
        assert call["ExpressionAttributeValues"][":e"] == "DATE#2026-06-15"
        assert "#phase" in call["ExpressionAttributeNames"]  # pilot rows stay hidden

    def test_a_failed_query_degrades_to_an_empty_series_not_an_exception(self, monkeypatch):
        monkeypatch.setattr(engine, "table", FakeDdbTable(query_hook=raise_hook))
        assert engine._fetch_range("whoop", "2026-06-01", "2026-06-02") == []


class TestFetchAllSourceData:
    def test_returns_one_entry_per_registered_source(self, monkeypatch):
        seen = []

        def _fake_fetch(source, start, end):
            seen.append((source, start, end))
            return _records("hrv", [50.0]) if source == "whoop" else []

        monkeypatch.setattr(engine, "_fetch_range", _fake_fetch)
        data = engine._fetch_all_source_data("2026-06-01", "2026-06-15")

        assert set(data) == set(engine.SOURCE_METRICS)
        assert len(data["whoop"]) == 1
        assert data["withings"] == []
        assert {s for s, _, _ in seen} == set(engine.SOURCE_METRICS)
        assert all((start, end) == ("2026-06-01", "2026-06-15") for _, start, end in seen)


# =============================================================================
# RESULTS WRITER
# =============================================================================


class TestWriteResults:
    _PACKAGE = {
        "trends": {"whoop": {"hrv": {"direction": "up"}}, "withings": {"weight_lbs": {"direction": "down"}}},
        "regression_to_mean_warnings": [{"metric": "hrv"}],
        "seasonality_flags": [{"metric": "sleep_duration_hours"}, {"metric": "som_avg_valence"}],
        "autocorrelation_warnings": [{"metric": "hrv"}, {"metric": "rem_pct"}, {"metric": "deep_pct"}],
        "statistical_guardrails": {"whoop": {"hrv": {"level": "established"}}},
        "prediction_evaluations": [],
    }

    def test_writes_the_package_with_json_subtrees_and_summary_counts(self, monkeypatch, frozen_clock):
        fake = FakeDdbTable()
        monkeypatch.setattr(engine, "table", fake)

        engine._write_results("2026-06-15", self._PACKAGE)

        (item,) = fake.puts
        assert item["pk"] == "COACH#computation"
        assert item["sk"] == "RESULTS#2026-06-15"
        assert item["date"] == "2026-06-15"
        assert item["computed_at"] == _FROZEN_ISO
        assert item["algo_version"] == engine.ALGO_VERSION
        assert json.loads(item["trends"]) == self._PACKAGE["trends"]
        assert json.loads(item["statistical_guardrails"]) == self._PACKAGE["statistical_guardrails"]
        # counts: 2 trends (1 per source), 1 rtm + 3 autocorr warnings, 2 flags, 0 evals
        assert item["trend_count"] == Decimal("2")
        assert item["warning_count"] == Decimal("4")
        assert item["flag_count"] == Decimal("2")
        assert item["prediction_eval_count"] == Decimal("0")
        assert all(isinstance(item[k], Decimal) for k in ("trend_count", "warning_count", "flag_count", "prediction_eval_count"))

    def test_stamps_experiment_provenance_1233(self, monkeypatch, frozen_clock):
        from common.constants import EXPERIMENT_PHASE_CURRENT

        fake = FakeDdbTable()
        monkeypatch.setattr(engine, "table", fake)
        engine._write_results("2026-06-15", self._PACKAGE)

        (item,) = fake.puts
        assert item["phase"] == EXPERIMENT_PHASE_CURRENT
        assert item["cycle"] == 12

    def test_missing_subpackages_serialise_as_empty_containers(self, monkeypatch, frozen_clock):
        fake = FakeDdbTable()
        monkeypatch.setattr(engine, "table", fake)
        engine._write_results("2026-06-15", {})

        (item,) = fake.puts
        assert json.loads(item["trends"]) == {}
        assert json.loads(item["autocorrelation_warnings"]) == []
        assert item["trend_count"] == Decimal("0")

    def test_a_write_failure_propagates_to_the_caller(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", FakeDdbTable(put_item_hook=raise_hook))
        with pytest.raises(RuntimeError):
            engine._write_results("2026-06-15", self._PACKAGE)


# =============================================================================
# COMPONENT 7: narrative arc transitions
# =============================================================================


class TestArcTransition:
    GENESIS = "2026-01-01"

    @pytest.fixture(autouse=True)
    def _pin_genesis(self, monkeypatch):
        # Pin the module's genesis so the staleness guard and days_in_phase are
        # decided by the fixture dates, never by the live EXPERIMENT_START_DATE.
        monkeypatch.setattr(engine, "EXPERIMENT_START", self.GENESIS)

    def _table(self, arc=None, **kw):
        items = []
        if arc is not None:
            items.append({"pk": "NARRATIVE#arc", "sk": "STATE#current", **arc})
        return FakeDdbTable(store_items=items, **kw)

    def test_no_trends_means_no_transition(self, monkeypatch, frozen_clock):
        fake = self._table()
        monkeypatch.setattr(engine, "table", fake)
        assert engine._detect_arc_transition({}, {}, {}, "2026-02-01") is None
        assert fake.puts == []

    def test_early_baseline_graduates_on_fourteen_days_of_majority_positive_trends(self, monkeypatch, frozen_clock):
        fake = self._table()  # no arc row -> defaults to early_baseline @ genesis
        monkeypatch.setattr(engine, "table", fake)

        t = engine._detect_arc_transition(_trends(up=2, flat=1), {}, {}, "2026-01-15")

        assert t["from"] == "early_baseline"
        assert t["to"] == "building_momentum"
        assert t["metrics_context"] == {"up": 2, "down": 0, "flat": 1, "total": 3}
        assert "67% of trends positive" in t["reason"]

    def test_thirteen_days_is_one_short(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table())
        assert engine._detect_arc_transition(_trends(up=2, flat=1), {}, {}, "2026-01-14") is None

    def test_baseline_auto_graduates_at_twenty_eight_days_without_positive_trends(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table())
        t = engine._detect_arc_transition(_trends(up=1, flat=2), {}, {}, "2026-01-29")
        assert t["to"] == "building_momentum"
        assert t["reason"] == "28 days in baseline — auto-transition"

    def test_sixty_percent_declining_drops_to_setback_from_any_phase(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table({"phase": "building_momentum", "entered_date": "2026-01-10"}))
        t = engine._detect_arc_transition(_trends(up=1, down=3), {}, {}, "2026-01-20")
        assert t["from"] == "building_momentum"
        assert t["to"] == "setback"
        assert t["reason"] == "3/4 metrics declining"

    def test_setback_needs_at_least_three_metrics(self, monkeypatch, frozen_clock):
        # 2/2 declining is 100% but n=2 — below the evidence floor, no transition.
        monkeypatch.setattr(engine, "table", self._table({"phase": "building_momentum", "entered_date": "2026-01-10"}))
        assert engine._detect_arc_transition(_trends(down=2), {}, {}, "2026-01-20") is None

    def test_seventy_percent_flat_for_a_week_becomes_plateau(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table({"phase": "building_momentum", "entered_date": "2026-01-10"}))
        t = engine._detect_arc_transition(_trends(up=1, flat=9), {}, {}, "2026-01-20")
        assert t["to"] == "plateau"
        assert t["reason"] == "9/10 metrics flat for 10+ days"

    def test_insufficient_data_metrics_are_excluded_from_the_flat_vote(self, monkeypatch, frozen_clock):
        # #2179: 7 metrics with too little history to have a real direction must not
        # be counted toward the plateau tally at all. 1 up + 2 flat + 7 insufficient:
        # if insufficient_data were still counted as flat (the old bug), flat_pct
        # would be 9/10 = 90% and this would wrongly transition to plateau — with the
        # fix, the vote is only over the 3 metrics that were actually measured
        # (flat_pct = 2/3 = 67%, below the 70% bar), so no transition fires.
        monkeypatch.setattr(engine, "table", self._table({"phase": "building_momentum", "entered_date": "2026-01-10"}))
        assert engine._detect_arc_transition(_trends(up=1, flat=2, insufficient=7), {}, {}, "2026-01-20") is None

    def test_insufficient_data_metrics_can_still_allow_a_genuine_plateau(self, monkeypatch, frozen_clock):
        # Same shape, but the measured metrics really are 70%+ flat once the
        # unmeasured ones are excluded from the denominator.
        monkeypatch.setattr(engine, "table", self._table({"phase": "building_momentum", "entered_date": "2026-01-10"}))
        t = engine._detect_arc_transition(_trends(flat=7, insufficient=5), {}, {}, "2026-01-20")
        assert t["to"] == "plateau"
        assert t["metrics_context"] == {"up": 0, "down": 0, "flat": 7, "total": 7}

    def test_plateau_requires_seven_days_in_phase(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table({"phase": "building_momentum", "entered_date": "2026-01-15"}))
        assert engine._detect_arc_transition(_trends(up=1, flat=9), {}, {}, "2026-01-20") is None

    def test_plateau_is_unreachable_from_early_baseline(self, monkeypatch, frozen_clock):
        # The flat-heavy rule only applies once momentum/adaptation has been claimed.
        monkeypatch.setattr(engine, "table", self._table())
        assert engine._detect_arc_transition(_trends(flat=10), {}, {}, "2026-01-20") is None

    def test_plateau_breaks_out_on_sixty_percent_improving(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table({"phase": "plateau", "entered_date": "2026-01-10"}))
        t = engine._detect_arc_transition(_trends(up=3, flat=2), {}, {}, "2026-01-20")
        assert t["to"] == "breakthrough"
        assert t["reason"] == "3/5 metrics improving"

    def test_breakthrough_needs_at_least_four_metrics(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table({"phase": "plateau", "entered_date": "2026-01-10"}))
        assert engine._detect_arc_transition(_trends(up=3), {}, {}, "2026-01-20") is None

    def test_staying_in_the_same_phase_is_not_a_transition(self, monkeypatch, frozen_clock):
        fake = self._table({"phase": "setback", "entered_date": "2026-01-10"})
        monkeypatch.setattr(engine, "table", fake)
        assert engine._detect_arc_transition(_trends(down=4), {}, {}, "2026-01-20") is None
        assert fake.puts == []

    def test_a_pre_genesis_arc_is_treated_as_absent(self, monkeypatch, frozen_clock):
        # #946: the previous cycle's 'setback' would otherwise fire an absurd
        # day-N breakthrough. The fresh cycle restarts at early_baseline.
        fake = self._table({"phase": "setback", "entered_date": "2025-11-01"})
        monkeypatch.setattr(engine, "table", fake)
        t = engine._detect_arc_transition(_trends(up=4), {}, {}, "2026-01-20")
        assert t["from"] == "early_baseline"
        assert t["to"] == "building_momentum"

    def test_a_tombstoned_arc_is_treated_as_absent(self, monkeypatch, frozen_clock):
        fake = self._table({"phase": "plateau", "entered_date": "2026-01-05", "tombstone": True})
        monkeypatch.setattr(engine, "table", fake)
        t = engine._detect_arc_transition(_trends(up=4), {}, {}, "2026-01-20")
        assert t["from"] == "early_baseline"  # not 'plateau'
        assert t["to"] == "building_momentum"  # not 'breakthrough'

    def test_an_unreadable_arc_row_falls_back_to_early_baseline(self, monkeypatch, frozen_clock):
        fake = FakeDdbTable(get_item_hook=raise_hook)
        monkeypatch.setattr(engine, "table", fake)
        t = engine._detect_arc_transition(_trends(up=3), {}, {}, "2026-01-20")
        assert t["from"] == "early_baseline"

    def test_a_malformed_entered_date_reads_as_zero_days_in_phase(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table({"phase": "early_baseline", "entered_date": "not-a-date"}))
        # 0 days in phase -> neither the 14- nor the 28-day rule can fire.
        assert engine._detect_arc_transition(_trends(up=3), {}, {}, "2026-06-01") is None

    def test_a_transition_writes_state_and_history(self, monkeypatch, frozen_clock):
        fake = self._table({"phase": "plateau", "entered_date": "2026-01-10"})
        monkeypatch.setattr(engine, "table", fake)

        t = engine._detect_arc_transition(_trends(up=4), {}, {}, "2026-01-20")

        state = [p for p in fake.puts if p["sk"] == "STATE#current"]
        history = [p for p in fake.puts if p["sk"] == "HISTORY#2026-01-20"]
        assert len(state) == 1 and len(history) == 1
        assert state[0]["pk"] == "NARRATIVE#arc"
        assert state[0]["phase"] == "breakthrough"  # the ARC phase, not the taxonomy phase
        assert state[0]["previous_phase"] == "plateau"
        assert state[0]["entered_date"] == "2026-01-20"
        assert state[0]["last_updated"] == _FROZEN_ISO
        assert state[0]["cycle"] == 12  # cycle-only stamp (include_phase=False)
        assert history[0]["transition"]["to"] == t["to"]
        assert history[0]["transition"]["metrics_context"]["total"] == 4

    def test_a_failed_write_still_reports_the_transition(self, monkeypatch, frozen_clock):
        # The narrative brief must not lose the transition just because the
        # provenance write failed — the function logs and returns.
        fake = self._table({"phase": "plateau", "entered_date": "2026-01-10"}, put_item_hook=raise_hook)
        monkeypatch.setattr(engine, "table", fake)
        t = engine._detect_arc_transition(_trends(up=4), {}, {}, "2026-01-20")
        assert t["to"] == "breakthrough"

    def test_non_dict_trend_entries_are_ignored_rather_than_crashing(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(engine, "table", self._table())
        trends = {"whoop": "corrupt", "withings": {"weight_lbs": "corrupt", "x": {"direction": "up"}}}
        # Only the one well-formed entry counts -> total 1, up_pct 1.0, 14+ days.
        t = engine._detect_arc_transition(trends, {}, {}, "2026-01-20")
        assert t["metrics_context"] == {"up": 1, "down": 0, "flat": 0, "total": 1}


# =============================================================================
# LAMBDA HANDLER — end-to-end wiring, offline
# =============================================================================


def _install_handler_doubles(monkeypatch, *, genesis, source_data):
    fake = FakeDdbTable()
    monkeypatch.setattr(engine, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, engine, _FrozenDatetime)
    monkeypatch.setattr(engine, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(engine, "table", fake)
    monkeypatch.setattr(engine, "_s3_json", lambda key: None)  # exercise both config fallbacks
    monkeypatch.setattr(engine, "_fetch_range", lambda source, s, e: list(source_data.get(source, [])))
    return fake


class TestLambdaHandler:
    def test_end_to_end_package_and_write(self, monkeypatch):
        # 9 rising hrv points -> one 'up' trend; genesis 2026-06-01 with the clock
        # frozen at 2026-06-15 -> 14 days in baseline -> arc graduates.
        source_data = {"whoop": _records("hrv", [50.0] * 8 + [70.0], start="2026-06-06")}
        fake = _install_handler_doubles(monkeypatch, genesis="2026-06-01", source_data=source_data)

        package = engine.lambda_handler({}, None)

        assert package["date"] == _FROZEN_DATE
        assert package["computed_at"] == _FROZEN_ISO
        assert package["algo_version"] == engine.ALGO_VERSION
        assert package["lookback_start"] == "2026-06-01"  # clamped to genesis, not 30d back
        assert package["lookback_days"] == 14
        assert package["total_records"] == 9
        assert package["trends"]["whoop"]["hrv"]["direction"] == "up"
        assert package["trends"]["whoop"]["hrv"]["n_points"] == 9
        # 9 days of hrv is "preliminary": a coach may speak directionally, not interventionally.
        assert package["statistical_guardrails"]["whoop"]["hrv"]["level"] == "preliminary"
        assert package["statistical_guardrails"]["whoop"]["hrv"]["decision_class_ceiling"] == "directional"
        assert package["prediction_evaluations"] == []  # #813: this engine no longer grades
        assert package["arc_transition"]["to"] == "building_momentum"

        results = [p for p in fake.puts if p["pk"] == "COACH#computation"]
        assert len(results) == 1
        assert results[0]["sk"] == f"RESULTS#{_FROZEN_DATE}"
        assert json.loads(results[0]["trends"]) == package["trends"]

    def test_lookback_is_thirty_days_when_genesis_is_further_back(self, monkeypatch):
        _install_handler_doubles(monkeypatch, genesis="2026-01-01", source_data={})
        package = engine.lambda_handler({}, None)
        assert package["lookback_start"] == "2026-05-16"  # 2026-06-15 minus 30 days
        assert package["lookback_days"] == engine.LOOKBACK_DAYS

    def test_empty_platform_returns_an_honest_empty_package(self, monkeypatch):
        fake = _install_handler_doubles(monkeypatch, genesis="2026-06-01", source_data={})
        package = engine.lambda_handler({}, None)
        assert package["total_records"] == 0
        assert package["trends"] == {}
        assert package["statistical_guardrails"] == {}
        assert package["regression_to_mean_warnings"] == []
        assert package["arc_transition"] is None  # no trends -> nothing to transition on
        assert [p["pk"] for p in fake.puts] == ["COACH#computation"]

    @pytest.mark.parametrize(
        "component,key,empty",
        [
            ("_compute_trends", "trends", {}),
            ("_detect_regression_to_mean", "regression_to_mean_warnings", []),
            ("_compute_seasonality_flags", "seasonality_flags", []),
            ("_detect_autocorrelation_warnings", "autocorrelation_warnings", []),
            ("_compute_statistical_guardrails", "statistical_guardrails", {}),
            ("_detect_arc_transition", "arc_transition", None),
        ],
    )
    def test_one_failing_component_never_blocks_the_others(self, monkeypatch, component, key, empty):
        source_data = {"whoop": _records("hrv", [50.0] * 8 + [70.0], start="2026-06-06")}
        _install_handler_doubles(monkeypatch, genesis="2026-06-01", source_data=source_data)

        def _boom(*args, **kwargs):
            raise RuntimeError(f"{component} exploded")

        monkeypatch.setattr(engine, component, _boom)

        package = engine.lambda_handler({}, None)

        assert package[key] == empty
        assert package["date"] == _FROZEN_DATE
        assert package["total_records"] == 9
        # the surviving components still produced their output
        survivors = [k for k in ("trends", "statistical_guardrails") if k != key]
        assert all(package[s] for s in survivors)

    def test_a_failed_results_write_does_not_fail_the_lambda(self, monkeypatch):
        source_data = {"whoop": _records("hrv", [50.0] * 9, start="2026-06-06")}
        _install_handler_doubles(monkeypatch, genesis="2026-06-01", source_data=source_data)
        monkeypatch.setattr(engine, "_write_results", raise_hook)

        package = engine.lambda_handler({}, None)
        assert package["date"] == _FROZEN_DATE
        assert package["total_records"] == 9
