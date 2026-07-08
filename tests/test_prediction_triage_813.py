"""tests/test_prediction_triage_813.py — #813: the scorecard had never graded once.

The live triage (2026-07-08, 390 phase-current PREDICTION# records) found four
compounding root causes, each pinned here:

  1. A duplicate grader in coach_computation_engine terminalized machine-type
     predictions to 'inconclusive' at the raw stated window — before
     coach-prediction-evaluator's domain-clamped window ever elapsed. All 167
     machine specs carry threshold=None (pre-C-3), so that grader could only
     ever write inconclusive. → Removed; the evaluator reclaims its victims.
  2. Machine specs with threshold=None are structurally ungradable. → The
     evaluator now deterministically re-routes them to the directional (EWMA)
     evaluator when the claim text yields a direction.
  3. SUBDOMAIN_TO_DOMAIN did not contain the subdomain vocabulary the writer
     actually emits (hrv/recovery/sleep/protein/…), so every prediction fell to
     the 'training' 21-day minimum window. → Vocabulary covered.
  4. METRIC_SOURCES mapped sleep_score/deep_pct/rem_pct to whoop, whose records
     never carry those fields (they live on eightsleep) — and the writer could
     emit gradable specs for metrics whose source has no data at all
     (blood_glucose_* with the CGM inactive, body_fat_pct with no DEXA scan).
     → Source mappings fixed + a write-time data-liveness gate.
"""

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import coach_computation_engine as engine  # noqa: E402
import coach_prediction_evaluator as ev  # noqa: E402
import coach_state_updater as updater  # noqa: E402
import measurable_metrics as mm  # noqa: E402
from fakes import FakeDdbTable, raise_hook  # noqa: E402

# ── Root cause 4a: metric → source mappings point at sources that HAVE the field ──


class TestMetricSourceMappings:
    def test_sleep_architecture_metrics_map_to_eightsleep_not_whoop(self):
        # whoop DATE# records carry sleep_quality_score / slow_wave_sleep_hours /
        # rem_sleep_hours — NOT these keys. eightsleep records carry them daily.
        assert mm.METRIC_SOURCES["sleep_score"] == "eightsleep"
        assert mm.METRIC_SOURCES["deep_pct"] == "eightsleep"
        assert mm.METRIC_SOURCES["rem_pct"] == "eightsleep"

    def test_engine_ewma_registry_agrees_no_dead_whoop_fields(self):
        assert "sleep_score" not in engine.SOURCE_METRICS["whoop"]
        assert "deep_pct" not in engine.SOURCE_METRICS["whoop"]
        assert "rem_pct" not in engine.SOURCE_METRICS["whoop"]
        assert set(["sleep_score", "deep_pct", "rem_pct"]) <= set(engine.SOURCE_METRICS["eightsleep"])


# ── Shared direction inference (writer + evaluator use ONE function) ─────────────


class TestSharedDirectionInference:
    def test_writer_uses_the_shared_function(self):
        assert updater._infer_direction is mm.infer_direction

    def test_upward_downward_vocabulary(self):
        # The live corpus phrases claims as "track directionally upward" — the old
        # word lists missed 'upward'/'downward' entirely.
        assert mm.infer_direction(None, "HRV will track directionally upward as composition shifts") == "up"
        assert mm.infer_direction(None, "resting heart rate should drift downward") == "down"
        assert mm.infer_direction(None, "protein trending up this month") == "up"

    def test_ambiguous_stays_none(self):
        assert mm.infer_direction(None, "sleep will stay about the same") is None


# ── Root cause 2: null-threshold machine specs are rescued directionally ─────────


def _legacy_machine_pred(claim, metric="hrv"):
    return (
        {"claim_natural": claim, "coach_id": "sleep_coach", "subdomain": "hrv"},
        {"type": "machine", "metric": metric, "condition": "gt", "threshold": None, "evaluation_window_days": 14},
    )


class TestNullThresholdRescue:
    def test_directional_claim_confirms_on_matching_trend(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda m, d, t: ("up", 0.05))
        pred, spec = _legacy_machine_pred("HRV will track directionally upward over the window")
        r = ev._evaluate_machine(pred, spec, {}, "2026-07-08")
        assert r["status"] == "confirmed"
        assert "re-routed to directional" in r["reason"]

    def test_directional_claim_refutes_on_opposite_trend(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda m, d, t: ("down", -0.05))
        pred, spec = _legacy_machine_pred("recovery score should improve within two weeks", metric="recovery_score")
        r = ev._evaluate_machine(pred, spec, {}, "2026-07-08")
        assert r["status"] == "refuted"

    def test_no_inferable_direction_is_inconclusive_with_reason(self):
        pred, spec = _legacy_machine_pred("HRV will stabilize inside its normal band")
        r = ev._evaluate_machine(pred, spec, {}, "2026-07-08")
        assert r["status"] == "inconclusive"
        assert "no inferable direction" in r["reason"]

    def test_rescue_does_not_mutate_the_stored_spec(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda m, d, t: ("up", 0.05))
        pred, spec = _legacy_machine_pred("HRV should rise")
        ev._evaluate_machine(pred, spec, {}, "2026-07-08")
        assert spec["condition"] == "gt"  # original record untouched

    def test_thresholded_machine_specs_still_grade_normally(self, monkeypatch):
        monkeypatch.setattr(ev, "_resolve_metric_value", lambda m, d, t: 55.0)
        pred = {"claim_natural": "HRV above 50"}
        spec = {"type": "machine", "metric": "hrv", "condition": "gt", "threshold": 50, "evaluation_window_days": 14}
        r = ev._evaluate_machine(pred, spec, {}, "2026-07-08")
        assert r["status"] == "confirmed"


# ── Root cause 3: the writer's subdomain vocabulary maps to real domains ─────────


class TestSubdomainWindows:
    WRITER_SUBDOMAINS = ["sleep", "hrv", "recovery", "weight", "calories", "protein", "glucose", "training", "mood", "stress", "general"]

    def test_writer_vocabulary_is_covered(self):
        # coach_state_updater derives subdomains from this keyword list (+ 'general'
        # fallback). Every one must be in SUBDOMAIN_TO_DOMAIN or the evaluator
        # silently clamps its window to the 21-day 'training' default.
        for sd in self.WRITER_SUBDOMAINS:
            assert sd in ev.SUBDOMAIN_TO_DOMAIN, f"writer-emitted subdomain {sd!r} missing from SUBDOMAIN_TO_DOMAIN"

    def test_hrv_prediction_window_no_longer_clamped_to_21_days(self):
        # Regression: an hrv-subdomain prediction with a stated 14-day window used
        # to be clamped to 21 (training default) — 50% longer than the coach asked.
        assert ev._get_effective_window({"evaluation_window_days": 14}, "hrv") == 14

    def test_sleep_prediction_keeps_its_stated_window(self):
        assert ev._get_effective_window({"evaluation_window_days": 7}, "sleep") == 7


# ── Root cause 1: the duplicate grader is gone; its victims are reclaimed ────────


class TestDuplicateGraderRemoval:
    def test_engine_no_longer_grades_predictions(self):
        for fn in ("_evaluate_predictions", "_update_prediction_outcome", "_update_bayesian_confidence", "_fetch_predictions"):
            assert not hasattr(engine, fn), f"coach_computation_engine.{fn} should be removed (#813)"

    def test_reclaim_discriminator_matches_engine_signature_only(self):
        # The engine's outcome_notes never carried algo_version; the evaluator's
        # always do. That asymmetry is the deterministic reclaim discriminator.
        engine_notes = json.dumps({"actual_value": None, "beats_null": False, "bayesian_update": None})
        evaluator_notes = json.dumps(
            {"actual_value": None, "reason": "x", "beats_null": False, "bayesian_update": None, "algo_version": "1.0"}
        )
        assert ev._was_terminalized_by_duplicate_grader({"status": "inconclusive", "outcome_notes": engine_notes}) is True
        assert ev._was_terminalized_by_duplicate_grader({"status": "inconclusive", "outcome_notes": evaluator_notes}) is False
        assert ev._was_terminalized_by_duplicate_grader({"status": "pending", "outcome_notes": engine_notes}) is False
        assert ev._was_terminalized_by_duplicate_grader({"status": "confirmed", "outcome_notes": engine_notes}) is False
        assert ev._was_terminalized_by_duplicate_grader({"status": "inconclusive", "outcome_notes": "not json"}) is False


# ── End-to-end: a stranded legacy prediction now actually decides ────────────────


class TestEvaluateAllEndToEnd:
    def _run(self, monkeypatch, trend, claim, days_ago=15):
        today = datetime(2026, 7, 8)
        created = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        pred = {
            "pk": "COACH#sleep_coach",
            "sk": "PREDICTION#pred_x",
            "prediction_id": "pred_x",
            "coach_id": "sleep_coach",
            "subdomain": "hrv",
            "status": "pending",
            "created_date": created,
            "claim_natural": claim,
            "evaluation": {"type": "machine", "metric": "hrv", "condition": "gt", "threshold": None, "evaluation_window_days": 14},
        }
        writes = []
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda m, d, t: trend)
        monkeypatch.setattr(ev, "_update_prediction_status", lambda p, e: writes.append(("status", e["status"])))
        monkeypatch.setattr(ev, "_update_bayesian_confidence", lambda c, s, u: writes.append(("bayes", u)))
        monkeypatch.setattr(ev, "_write_learning_record", lambda c, t, e: writes.append(("learning", e["status"])))
        evaluations, stats = ev._evaluate_all([pred], "2026-07-08")
        return evaluations, stats, writes

    def test_legacy_machine_prediction_confirms_end_to_end(self, monkeypatch):
        # Pre-fix this exact record was UNGRADEABLE twice over: the 14-day window
        # was clamped to 21 ('hrv' unmapped → training), and once elapsed the
        # null threshold could only produce inconclusive.
        evaluations, stats, writes = self._run(monkeypatch, ("up", 0.05), "HRV will track directionally upward")
        assert stats["confirmed"] == 1
        assert ("bayes", "success") in writes
        assert evaluations[0]["status"] == "confirmed"

    def test_legacy_machine_prediction_refutes_end_to_end(self, monkeypatch):
        evaluations, stats, writes = self._run(monkeypatch, ("down", -0.04), "HRV will track directionally upward")
        assert stats["refuted"] == 1
        assert ("bayes", "failure") in writes

    def test_window_not_elapsed_still_skips(self, monkeypatch):
        _, stats, writes = self._run(monkeypatch, ("up", 0.05), "HRV will rise", days_ago=3)
        assert stats["skipped_window"] == 1
        assert writes == []


# ── Root cause 4b: write-time data-liveness gate ─────────────────────────────────


def _StubTable(items):
    return FakeDdbTable(rows=items)


class TestWriteTimeLivenessGate:
    def test_metric_with_enough_recent_data_passes(self, monkeypatch):
        items = [{"hrv": 40 + i} for i in range(6)]
        monkeypatch.setattr(updater, "table", _StubTable(items))
        assert updater._metric_has_recent_data("hrv", {}) is True

    def test_dead_source_metric_is_rejected(self, monkeypatch):
        monkeypatch.setattr(updater, "table", _StubTable([]))
        assert updater._metric_has_recent_data("body_fat_pct", {}) is False

    def test_below_minimum_points_is_rejected(self, monkeypatch):
        items = [{"blood_glucose_avg": 100}, {"blood_glucose_avg": 104}]  # < 5 points
        monkeypatch.setattr(updater, "table", _StubTable(items))
        assert updater._metric_has_recent_data("blood_glucose_avg", {}) is False

    def test_aggregate_suffix_checks_the_base_metric(self, monkeypatch):
        items = [{"hrv": 40 + i} for i in range(6)]
        monkeypatch.setattr(updater, "table", _StubTable(items))
        cache = {}
        assert updater._metric_has_recent_data("hrv_7day_avg", cache) is True
        assert cache == {"hrv": True}

    def test_unmapped_metric_is_rejected(self, monkeypatch):
        monkeypatch.setattr(updater, "table", _StubTable([]))
        assert updater._metric_has_recent_data("not_a_metric", {}) is False

    def test_read_error_fails_open(self, monkeypatch):
        monkeypatch.setattr(updater, "table", FakeDdbTable(query_hook=raise_hook))
        assert updater._metric_has_recent_data("hrv", {}) is True

    def test_result_is_cached_per_base_metric(self, monkeypatch):
        table = FakeDdbTable(rows=[{"hrv": 40 + i} for i in range(6)])
        monkeypatch.setattr(updater, "table", table)
        cache = {}
        assert updater._metric_has_recent_data("hrv", cache) is True
        assert updater._metric_has_recent_data("hrv", cache) is True
        assert len(table.query_calls) == 1


# ── The extraction prompt's allowlist is derived, not a drifting copy ────────────


class TestPromptAllowlistDerived:
    def test_every_measurable_metric_is_in_the_prompt(self):
        for key in mm.MEASURABLE_METRICS:
            assert key in updater.EXTRACTION_SYSTEM_PROMPT, f"{key} missing from extraction prompt"

    def test_prompt_uses_the_derived_join(self):
        assert updater._METRIC_ALLOWLIST_PROMPT == ", ".join(sorted(mm.MEASURABLE_METRICS))
        assert updater._METRIC_ALLOWLIST_PROMPT in updater.EXTRACTION_SYSTEM_PROMPT
