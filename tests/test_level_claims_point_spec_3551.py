"""tests/test_level_claims_point_spec_3551.py — #3551: a numeric LEVEL claim is graded as
the level the coach stated, never as a 14-day slope sign.

THE LIVE DEFECT (2026-09-05, /review full QS-4): 49 PREDICTION# rows whose claims
read "approximately N" / "around N" / "will be N" carried `evaluation.type =
directional`; one — 2026-08-17 'Recovery score tomorrow will be around 50%' — was
CONFIRMED as `recovery_score trend=up (slope=0.0947), predicted=up`: a one-day level
forecast scored as a two-week up-trend, now in the lifetime 8/37. Two feeders:

  (1) `'recover' in DIR_UP_WORDS` substring-matched the metric NAME 'recovery', so
      every recovery_score claim without a down-word was emitted condition='up'
      regardless of content;
  (2) `build_prediction_eval_spec` only knew directional | qualitative, so any
      resolvable direction — including the LLM extractor's — turned a point
      estimate into a slope bet.

Every prove-red test below carries a positive control: the fixture is shown to
reproduce the defect under the OLD rule before the NEW rule is held to it.
"""

import ast
import inspect
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_prediction_evaluator as ev  # noqa: E402
import coach_state_updater as su  # noqa: E402
import pytest  # noqa: E402
from coach import prediction_emission as pe, prediction_windows as pw  # noqa: E402
from experiment import measurable_metrics as mm  # noqa: E402
from fakes import FakeDdbTable, raise_hook  # noqa: E402

LIVE_CLAIM = "Recovery score will be approximately 53.5%"
DECIDED_CLAIM = "Recovery score tomorrow will be around 50%"


# ── feeder 1: the metric name can no longer be read as a direction word ─────────


class TestInferDirectionExcludesTheMetricName:
    def test_the_old_substring_rule_reproduces_the_defect(self):
        """Positive control: under `any(w in claim for w in DIR_UP_WORDS)` the live
        claim reads 'up' — from the word 'recovery' alone."""
        assert any(w in LIVE_CLAIM.lower() for w in mm.DIR_UP_WORDS)
        assert not any(w in LIVE_CLAIM.lower() for w in mm.DIR_DOWN_WORDS)

    @pytest.mark.parametrize("claim", [LIVE_CLAIM, DECIDED_CLAIM, "Recovery score will read 61%"])
    def test_a_recovery_level_claim_cannot_receive_up_from_its_own_name(self, claim):
        assert mm.infer_direction(None, claim, "recovery_score") is None
        # Word-boundary matching alone already refuses 'recover' ~ 'recovery'.
        assert mm.infer_direction(None, claim) is None

    def test_a_real_direction_word_still_resolves_with_the_metric_named(self):
        """Positive control for the exclusion: stripping the metric name must not
        strip the claim's own direction words."""
        assert mm.infer_direction(None, "Recovery score will climb this week", "recovery_score") == "up"
        assert mm.infer_direction(None, "I expect recovery to rebound", "recovery_score") == "up"
        assert mm.infer_direction(None, "weight will drop below the plateau", "weight_lbs") == "down"

    def test_inflections_match_but_different_words_do_not(self):
        assert mm.infer_direction(None, "HRV is improving steadily") == "up"
        assert mm.infer_direction(None, "weight dropped again") == "down"
        assert mm.infer_direction(None, "he is recovering well") == "up"
        assert mm.infer_direction(None, "recovery is the theme") is None  # 'recovery' is not 'recover'

    def test_the_writer_and_the_evaluator_share_the_one_function(self):
        assert su._infer_direction is mm.infer_direction
        assert ev.infer_direction is mm.infer_direction

    def test_the_evaluators_rescue_path_passes_the_metric(self):
        src = inspect.getsource(ev._evaluate_machine)
        assert 'infer_direction(None, pred.get("claim_natural") or "", metric_key)' in src


# ── feeder 2: the claim-shape classifier runs BEFORE direction inference ────────


class TestClaimShapeClassifier:
    @pytest.mark.parametrize(
        "claim,metric,target",
        [
            (LIVE_CLAIM, "recovery_score", 53.5),
            (DECIDED_CLAIM, "recovery_score", 50.0),
            ("HRV will read 48 ms by Friday", "hrv", 48.0),
            ("Weight will sit at 318 lbs", "weight_lbs", 318.0),
            ("sleep will average 7.2 hours this week", "sleep_duration_hours", 7.2),
            ("resting heart rate ~62 bpm", "resting_heart_rate", 62.0),
            ("steps will be around 8000 tomorrow", "steps", 8000.0),
        ],
    )
    def test_level_claims_classify_as_level_with_their_number(self, claim, metric, target):
        shape = pe.classify_claim_shape(claim, metric)
        assert shape["shape"] == "level" and shape["target"] == target

    @pytest.mark.parametrize(
        "claim",
        [
            "HRV will drop by 5 ms",  # a change magnitude
            "HRV should improve in about 3 days",  # a duration
            "weight will be under 320 lbs",  # a threshold — a different spec type, not conflated
            "he'll do about 3 sessions",  # an event count
            "recovery will be about 5 points higher",  # a change, not a level
            "HRV will improve over the next 2 weeks",
        ],
    )
    def test_non_level_claims_stay_on_the_directional_path(self, claim):
        assert pe.classify_claim_shape(claim, "hrv")["shape"] == "other"

    def test_no_metric_is_never_a_level(self):
        assert pe.classify_claim_shape(LIVE_CLAIM, None)["shape"] == "other"

    def test_a_date_word_and_an_iso_date_are_captured(self):
        assert pe.classify_claim_shape(DECIDED_CLAIM, "recovery_score")["window_hint"] == "tomorrow"
        assert pe.classify_claim_shape("weight will sit at 318 by 2026-09-20", "weight_lbs")["target_date"] == "2026-09-20"


# ── the routing: level → point (or observation), never directional ─────────────


def _tol_ok(_metric):
    return (4.0, "±1 SD of the trailing 30-day personal series (n=20 readings, SD=4.0)", 20)


def _tol_none(_metric):
    return None


class TestResolveEvalSpec:
    def test_the_old_builder_reproduces_the_defect(self):
        """Positive control: with a resolvable direction the ONLY builder the writer
        had turns the live claim into a 14-day directional spec."""
        old = pe.build_prediction_eval_spec("recovery_score", "up", 14)
        assert old["type"] == "directional" and old["condition"] == "up"

    def test_a_level_claim_becomes_a_point_spec_even_when_the_extractor_says_up(self):
        spec, window, shape = pe.resolve_eval_spec(
            LIVE_CLAIM, "recovery_score", {"direction": "up", "timeframe_hint": ""}, "2026-09-04", _tol_ok, mm.infer_direction
        )
        assert shape == "level"
        assert spec["type"] == pe.POINT_TYPE and spec["type"] != "directional"
        assert spec["metric"] == "recovery_score" and spec["condition"] == "within"
        assert spec["threshold"] == 53.5 and spec["tolerance"] == 4.0
        assert "SD" in spec["tolerance_rule"] and "n=20" in spec["tolerance_rule"]
        assert window == 14 and spec["target_date"] == "2026-09-18"

    def test_a_level_claim_with_no_derivable_tolerance_is_an_observation_never_directional(self):
        spec, _w, shape = pe.resolve_eval_spec(
            LIVE_CLAIM, "recovery_score", {"direction": "up", "timeframe_hint": ""}, "2026-09-04", _tol_none, mm.infer_direction
        )
        assert shape == "level" and spec["type"] == "qualitative"
        status, gradeable_by = pe.emission_status(spec)
        assert status == pe.OBSERVATION_STATUS and gradeable_by == pe.GRADEABLE_BY_NONE

    def test_tomorrow_is_a_one_day_window_and_target(self):
        spec, window, _ = pe.resolve_eval_spec(
            DECIDED_CLAIM, "recovery_score", {"direction": None, "timeframe_hint": ""}, "2026-08-17", _tol_ok, mm.infer_direction
        )
        assert window == 1 and spec["target_date"] == "2026-08-18"
        assert pe.prediction_window_days("tomorrow") == 1 and pe.prediction_window_days("2 weeks") == 14

    def test_an_iso_date_in_the_claim_sets_the_window(self):
        spec, window, _ = pe.resolve_eval_spec(
            "weight will sit at 318 by 2026-09-20",
            "weight_lbs",
            {"direction": None, "timeframe_hint": ""},
            "2026-09-06",
            _tol_ok,
            mm.infer_direction,
        )
        assert window == 14 and spec["target_date"] == "2026-09-20"

    def test_a_directional_claim_still_routes_exactly_as_before(self):
        spec, window, shape = pe.resolve_eval_spec(
            "HRV should improve over two weeks",
            "hrv",
            {"direction": None, "timeframe_hint": "2 weeks"},
            "2026-09-04",
            _tol_ok,
            mm.infer_direction,
        )
        assert shape == "other" and spec == pe.build_prediction_eval_spec("hrv", "up", 14)
        spec, _, _ = pe.resolve_eval_spec(
            "anything", "hrv", {"direction": "down", "timeframe_hint": ""}, "2026-09-04", _tol_ok, mm.infer_direction
        )
        assert spec["type"] == "directional" and spec["condition"] == "down"  # the extractor still wins for non-level claims

    def test_the_writer_routes_every_claim_through_resolve_eval_spec(self):
        """The extract-the-right-real-source guard (#3046's pattern): the emission
        loop must call the shape-first resolver, not an inline direction lookup."""
        assert su._resolve_eval_spec is pe.resolve_eval_spec
        tree = ast.parse(inspect.getsource(su))
        calls = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert "_resolve_eval_spec" in calls
        assert "_build_prediction_record" in calls  # the #3046 contract builder is still the writer


# ── the emission contract holds for the new type ────────────────────────────────


class TestPointEmissionContract:
    def test_a_point_spec_is_pending_and_deterministic(self):
        spec = pe.build_point_eval_spec("recovery_score", 53.5, 4.0, "±1 SD", 14, "2026-09-04")
        assert pe.emission_status(spec) == ("pending", pe.GRADEABLE_BY_DETERMINISTIC)
        assert pw.is_gradeable(spec)
        rec = pe.build_prediction_record("explorer_coach", "2026-09-04", LIVE_CLAIM, spec, 0.6, "observational")
        assert rec["status"] == "pending" and rec["evaluation"]["type"] == pe.POINT_TYPE

    def test_the_evaluator_dispatches_point_specs(self):
        src = inspect.getsource(ev._evaluate_all)
        assert 'in ("directional", "point")' in src and "_evaluate_point" in src
        # The evaluator's name is the grader module's function with the evaluator's own data path injected.
        from coach import prediction_point_grader as ppg

        assert "return evaluate_point(" in inspect.getsource(ev._evaluate_point) and ev.evaluate_point is ppg.evaluate_point
        assert ev.POINT_LOOKBACK_DAYS == ppg.POINT_LOOKBACK_DAYS

    def test_the_coherence_sentinel_counts_point_as_gradable(self):
        from operational import coherence_sentinel_lambda as cs

        src = inspect.getsource(cs._gather_predictions)
        assert '("directional", "point")' in src


# ── the tolerance: personal variance, or say why not ───────────────────────────


class TestPointTolerance:
    def test_one_sd_of_the_trailing_series_with_n_in_the_rule(self):
        tol, rule, n = pe.point_tolerance_from_series([50, 55, 60, 45, 52, 58])
        assert n == 6 and tol == 5.5015
        assert "n=6" in rule and "SD=5.5015" in rule and "30-day" in rule

    def test_below_the_floor_or_constant_derives_nothing(self):
        assert pe.point_tolerance_from_series([50, 55, 60, 45]) is None  # n < 5
        assert pe.point_tolerance_from_series([50] * 8) is None  # SD 0 would be an exact-match lottery
        assert pe.point_tolerance_from_series(["x", None, 50, 51, 52]) is None  # 3 clean readings

    def test_the_writer_derives_it_from_the_metrics_own_partition(self, monkeypatch):
        rows = [{"sk": f"DATE#2026-08-{i + 1:02d}", "recovery_score": 40 + (i % 5) * 3} for i in range(12)]
        monkeypatch.setattr(su, "table", FakeDdbTable(rows=rows))
        cache = {}
        tol = su._metric_point_tolerance("recovery_score", cache)
        assert tol is not None and tol[2] == 12 and tol[0] > 0
        assert su._metric_point_tolerance("recovery_score", cache) is tol  # cached per run
        assert su._metric_point_tolerance("recovery_score_7day_avg", {}) is not None  # aggregate reads the base

    def test_a_read_error_derives_nothing_it_does_not_fail_open(self, monkeypatch):
        """Liveness fails open (a dead read must not stall emission); a TOLERANCE
        never does — an invented tolerance would grade a claim nobody priced."""
        monkeypatch.setattr(su, "table", FakeDdbTable(query_hook=raise_hook))
        assert su._metric_point_tolerance("recovery_score", {}) is None


# ── the grader: |actual − target| <= tolerance on the target date ──────────────


def _cache(values, start_day=1):
    recs = [{"date": f"2026-08-{start_day + i:02d}", "recovery_score": v} for i, v in enumerate(values)]
    return {f"{ev.METRIC_SOURCES['recovery_score']}:{ev.POINT_LOOKBACK_DAYS}": recs}


def _spec(target, tol, target_date):
    return {
        "type": "point",
        "metric": "recovery_score",
        "condition": "within",
        "threshold": target,
        "tolerance": tol,
        "tolerance_rule": "±1 SD of the trailing 30-day personal series (n=20 readings, SD=4.0)",
        "target_date": target_date,
    }


class TestEvaluatePoint:
    def test_the_cache_reaches_the_grader(self):
        """Control: a broken cache key would return inconclusive and let the verdict
        tests below pass vacuously."""
        r = ev._evaluate_point({}, _spec(54.0, 4.0, "2026-08-15"), _cache([40 + i for i in range(20)]), "2026-08-30")
        assert r["status"] != "inconclusive", r

    def test_within_tolerance_is_confirmed_and_the_reason_is_reproducible(self):
        r = ev._evaluate_point({}, _spec(53.5, 4.0, "2026-08-15"), _cache([40 + i for i in range(20)]), "2026-08-30")
        assert r["status"] == "confirmed" and r["beats_null"] is True and r["actual_value"] == 54.0
        assert "recovery_score=54.00 on 2026-08-15" in r["reason"] and "|Δ|=0.50" in r["reason"] and "n=20" in r["reason"]

    def test_outside_tolerance_is_refuted(self):
        r = ev._evaluate_point({}, _spec(53.5, 0.2, "2026-08-15"), _cache([40 + i for i in range(20)]), "2026-08-30")
        assert r["status"] == "refuted" and r["beats_null"] is False and "outside tolerance" in r["reason"]

    def test_the_decided_row_regraded_as_a_level_is_not_an_up_trend_verdict(self):
        """The 2026-08-17 row: 'around 50%' tomorrow. Grade it as the level it was:
        a next-day reading of 44 against 50 ±4 is REFUTED — the confirmed 'up
        trend' verdict it carries was never a grade of this claim."""
        series = [60, 58, 55, 52, 50, 48, 46, 44]  # falling, yet the last-week EWMA 'trend' could read up
        r = ev._evaluate_point({}, _spec(50.0, 4.0, "2026-08-08"), _cache(series), "2026-08-30")
        assert r["status"] == "refuted"

    def test_a_reading_within_the_grace_window_counts_a_later_one_never_does(self):
        cache = _cache([50.0] * 10)  # readings 08-01..08-10
        near = ev._evaluate_point({}, _spec(50.0, 1.0, "2026-08-12"), cache, "2026-08-30")
        assert near["status"] == "confirmed" and "on 2026-08-10" in near["reason"]
        far = ev._evaluate_point({}, _spec(50.0, 1.0, "2026-08-20"), cache, "2026-08-30")
        assert far["status"] == "inconclusive"
        # A reading AFTER the target date is not the target date's reading.
        before = ev._evaluate_point({}, _spec(50.0, 1.0, "2026-07-30"), cache, "2026-08-30")
        assert before["status"] == "inconclusive"

    def test_a_missing_target_date_derives_from_created_plus_window(self):
        spec = _spec(54.0, 4.0, None)
        spec["evaluation_window_days"] = 1
        r = ev._evaluate_point({"created_date": "2026-08-14"}, spec, _cache([40 + i for i in range(20)]), "2026-08-30")
        assert r["status"] == "confirmed" and "on 2026-08-15" in r["reason"]

    def test_an_aggregate_metric_is_the_mean_of_the_last_n_readings_on_or_before_the_target(self):
        spec = dict(_spec(46.0, 0.01, "2026-08-10"), metric="recovery_score_7day_avg")
        r = ev._evaluate_point({}, spec, _cache([40 + i for i in range(20)]), "2026-08-30")
        assert r["status"] == "confirmed" and r["actual_value"] == 46.0  # mean(43..49) — readings on/before 08-10 only

    def test_a_malformed_spec_is_skipped_not_graded(self):
        assert ev._evaluate_point({}, {"type": "point", "metric": "recovery_score"}, _cache([50] * 10), "2026-08-30") is None
