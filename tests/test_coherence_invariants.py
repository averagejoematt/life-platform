"""
tests/test_coherence_invariants.py — the Coherence Sentinel's invariant cores.

Each invariant is tested by REPLAYING a known past outage: the fixture is the
exact state the platform was in when the bug shipped, and the assertion is "the
sentinel must fire." If these pass, the sentinel would have caught every silent-
incoherence bug of this era. Pure functions — no AWS, no clock.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import coherence_invariants as ci  # noqa: E402


class TestPredictionHealth:
    def test_c3_all_inconclusive_fires_alarm(self):
        # The C-3 outage: 12 predictions, all windows closed, none decided.
        preds = [{"status": "inconclusive", "closed": True, "eval_type": "machine"} for _ in range(12)]
        f = ci.check_prediction_health(preds)
        assert f.is_alarm
        assert "0 decided" in f.detail or "nothing is grading" in f.detail

    def test_healthy_board_is_ok(self):
        preds = [{"status": "confirmed", "closed": True, "eval_type": "directional"} for _ in range(6)]
        preds += [{"status": "refuted", "closed": True, "eval_type": "directional"} for _ in range(3)]
        preds += [{"status": "pending", "closed": False, "eval_type": "directional"} for _ in range(10)]
        f = ci.check_prediction_health(preds)
        assert f.status == ci.OK

    def test_runaway_qualitative_share_warns(self):
        preds = [{"status": "pending", "closed": False, "eval_type": "qualitative"} for _ in range(11)]
        preds += [{"status": "pending", "closed": False, "eval_type": "directional"} for _ in range(1)]
        f = ci.check_prediction_health(preds)
        assert f.status == ci.WARN

    def test_too_few_closed_does_not_false_fire(self):
        # Early days: a couple closed, none decided yet — must NOT alarm.
        preds = [{"status": "inconclusive", "closed": True, "eval_type": "directional"} for _ in range(3)]
        preds += [{"status": "pending", "closed": False, "eval_type": "directional"} for _ in range(20)]
        f = ci.check_prediction_health(preds)
        assert f.status == ci.OK


class TestComputedCoherence:
    def test_drifted_level_fires(self):
        # Character level stored 42 but XP only justifies 38.
        checks = [{"name": "character_level", "stored": 42, "expected": 38, "tol": 0}]
        f = ci.check_computed_coherence(checks)
        assert f.is_alarm
        assert "character_level" in f.detail

    def test_within_tolerance_ok(self):
        checks = [
            {"name": "day_grade_score", "stored": 78.4, "expected": 78.41, "tol": 0.1},
            {"name": "readiness", "stored": 61, "expected": 61, "tol": 0},
        ]
        f = ci.check_computed_coherence(checks)
        assert f.status == ci.OK


class TestFactsAgreement:
    FACTS = {"recovery_pct": 30, "hrv_ms": 25.2, "rhr_bpm": 58, "latest_weight": 300.8}

    def test_30_vs_86_recovery_split_fires(self):
        narratives = [
            "Your recovery sat at 30% today — the system is working hard.",
            "With recovery up at 86, you're primed for a hard session.",  # the contradiction
        ]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status in (ci.WARN, ci.ALARM)
        assert any("recovery" in o for o in f.offenders)

    def test_hrv_in_bpm_unit_error_fires(self):
        narratives = ["HRV climbed to 42 bpm overnight, a strong sign."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.offenders and any("bpm" in o for o in f.offenders)

    def test_consistent_narratives_ok(self):
        narratives = [
            "Recovery was 30% — low. HRV at 25 ms, resting heart rate 58.",
            "At 300.8 lbs the trend is still downward.",
        ]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status == ci.OK

    def test_protein_target_near_weight_does_not_false_positive(self):
        # "190 g protein target" must not be read as a contradiction of 300.8 lb.
        narratives = ["Hit your 190 g protein target; weight is 300.8 lbs and falling."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status == ci.OK

    # ── Precision regressions from the first LIVE run (these WERE false positives) ──
    def test_weight_loss_amount_is_not_a_current_weight_claim(self):
        # "lost 13.8 pounds" is a DELTA, not a contradiction of the 300.8 lb canonical.
        narratives = ["You've lost 13.8 pounds over four weeks — visceral fat down 3.21 pounds."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status == ci.OK

    def test_recovery_over_n_weeks_is_a_duration_not_a_value(self):
        narratives = ["Recovery has been suppressed over 4 weeks now."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status == ci.OK

    def test_hrv_ms_and_rhr_bpm_in_one_sentence_no_unit_error(self):
        # HRV in ms and RHR in bpm coexisting must NOT read as "HRV cited in bpm".
        narratives = ["HRV is 25 ms and your resting heart rate sits at 58 bpm."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status == ci.OK

    def test_real_weight_contradiction_still_fires(self):
        # A plausible-but-wrong current weight (270 vs 300.8) must still fire.
        narratives = ["The scale read 270 lbs this morning.", "Down to 268 pounds."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status in (ci.WARN, ci.ALARM)

    # ── Trend/historical references must NOT false-fire (2026-06-28 precision pass) ──
    def test_trend_citing_the_canonical_is_not_a_contradiction(self):
        # "dipped from 86 to 30" — the tight window captures the historical 86, but
        # the canonical 30 appears in the trend, so the coach is grounded → no flag.
        narratives = ["Recovery dipped from 86 to 30 — still rebuilding this week."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status == ci.OK

    def test_stale_only_value_with_no_grounding_still_fires(self):
        # Cites 86 as the current value and never mentions the canonical 30 → real.
        narratives = ["Recovery sits at 86 right now — push hard today."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert f.status in (ci.WARN, ci.ALARM)

    # ── TSB: derived-value coverage (M-8 / #493 / ADR-109) ──────────────────────
    # TSB is a signed, duration-proxy Banister value covered by this scheduled scan
    # (never the tight grounding_guard). Wide ABSOLUTE tolerance (±12 points).
    def test_tsb_contradiction_fires(self):
        # Record says deep accumulated fatigue (−22); a coach claiming a fresh +8 is the
        # M-8 derived-value contradiction that previously reached the brief ungated.
        facts = {**self.FACTS, "tsb": -22}
        narratives = ["Your TSB is +8 — fresh legs, go hard today."]
        f = ci.check_facts_agreement(narratives, facts)
        assert f.status in (ci.WARN, ci.ALARM)
        assert any("tsb" in o for o in f.offenders)

    def test_tsb_within_wide_tolerance_ok(self):
        # −18 vs canonical −22 is a 4-point miss — well inside the wide ±12 band → OK.
        facts = {**self.FACTS, "tsb": -22}
        narratives = ["TSB is about -18 — still carrying real fatigue."]
        f = ci.check_facts_agreement(narratives, facts)
        assert f.status == ci.OK

    def test_tsb_negative_sign_matters(self):
        # Canonical −22; coach cites −8 (a much fresher value) → real contradiction.
        facts = {**self.FACTS, "tsb": -22}
        narratives = ["Training stress balance at -8 — you're nearly recovered."]
        f = ci.check_facts_agreement(narratives, facts)
        assert f.status in (ci.WARN, ci.ALARM)

    def test_tsb_grounded_trend_not_a_contradiction(self):
        # Cites the canonical −22; the −5 is a historical trend value → grounded, no flag.
        facts = {**self.FACTS, "tsb": -22}
        narratives = ["TSB -22 today, down from -5 last week — fatigue is deepening."]
        f = ci.check_facts_agreement(narratives, facts)
        assert f.status == ci.OK

    def test_tsb_absent_from_facts_never_fires(self):
        # No tsb in the facts dict → the tsb pattern must never manufacture an offender.
        narratives = ["Your TSB is +8, fresh and ready."]
        f = ci.check_facts_agreement(narratives, self.FACTS)
        assert not any("tsb" in o for o in f.offenders)

    def test_tsb_zero_is_a_real_value_not_no_data(self):
        # TSB is signed, so a canonical 0 is a legitimate reading (not "no data"): a coach
        # citing a deep −25 against a balanced 0 must still fire (regression guard for the
        # signed-metric skip logic).
        facts = {**self.FACTS, "tsb": 0}
        narratives = ["Your TSB sits at -25 — badly overreached."]
        f = ci.check_facts_agreement(narratives, facts)
        assert f.status in (ci.WARN, ci.ALARM)
        assert any("tsb" in o for o in f.offenders)


class TestEndpointShape:
    def test_all_zero_predictions_fires(self):
        # handle_predictions bug: 200 OK but everything zeroed.
        payload = {"overall": {"total": 0, "confirmed": 0, "refuted": 0, "pending": 0}, "by_coach": {}, "predictions": []}
        spec = {"required": ["overall.total"], "non_degenerate": ["overall.total", "predictions"]}
        f = ci.check_endpoint_shape("predictions", payload, spec)
        assert f.is_alarm

    def test_healthy_predictions_ok(self):
        payload = {"overall": {"total": 296}, "predictions": [{"text": "x"}]}
        spec = {"required": ["overall.total"], "non_degenerate": ["overall.total", "predictions"]}
        f = ci.check_endpoint_shape("predictions", payload, spec)
        assert f.status == ci.OK

    def test_missing_required_key_fires(self):
        payload = {"by_coach": {}}
        spec = {"required": ["overall.total"], "non_degenerate": []}
        f = ci.check_endpoint_shape("predictions", payload, spec)
        assert f.is_alarm


class TestEndpointShapePostResetGrace:
    """BUG-05 / #379: an experiment reset (ADR-077) deliberately wipes cycle-scoped
    data, so an all-zero/empty payload in the first days of a new cycle is CORRECT,
    not the handle_predictions degenerate-payload outage. `experiment_age_days`
    gates ONLY the non_degenerate assertion during that window."""

    PAYLOAD = {"overall": {"total": 0, "confirmed": 0}, "predictions": []}
    SPEC = {"required": ["overall.total"], "non_degenerate": ["overall.total", "predictions"]}

    def test_day_zero_post_reset_is_ok(self):
        f = ci.check_endpoint_shape("predictions", self.PAYLOAD, self.SPEC, experiment_age_days=0)
        assert f.status == ci.OK
        assert "post-reset" in f.detail

    def test_day_one_to_three_post_reset_is_ok(self):
        for age in (1, 2, 3):
            f = ci.check_endpoint_shape("predictions", self.PAYLOAD, self.SPEC, experiment_age_days=age)
            assert f.status == ci.OK, f"day {age} should be in the grace window"

    def test_grace_window_boundary(self):
        # POST_RESET_GRACE_DAYS=5 → ages 0-4 are grace, 5+ are not.
        f_in = ci.check_endpoint_shape("predictions", self.PAYLOAD, self.SPEC, experiment_age_days=ci.POST_RESET_GRACE_DAYS - 1)
        f_out = ci.check_endpoint_shape("predictions", self.PAYLOAD, self.SPEC, experiment_age_days=ci.POST_RESET_GRACE_DAYS)
        assert f_in.status == ci.OK
        assert f_out.is_alarm

    def test_genuinely_degenerate_payload_still_alarms_outside_grace_window(self):
        # Same broken shape, but the cycle is well past the reset — the C-3-style
        # signature must still trip exactly as before.
        f = ci.check_endpoint_shape("predictions", self.PAYLOAD, self.SPEC, experiment_age_days=30)
        assert f.is_alarm

    def test_missing_required_key_still_fires_inside_grace_window(self):
        # The grace window only forgives the non_degenerate check — a genuinely
        # missing required key is never a "legitimately empty" state.
        payload = {"by_coach": {}}
        spec = {"required": ["overall.total"], "non_degenerate": []}
        f = ci.check_endpoint_shape("predictions", payload, spec, experiment_age_days=1)
        assert f.is_alarm

    def test_no_experiment_age_falls_back_to_ungated_behavior(self):
        # experiment_age_days=None (unknown genesis) → original, ungated behavior.
        f = ci.check_endpoint_shape("predictions", self.PAYLOAD, self.SPEC)
        assert f.is_alarm

    def test_negative_age_does_not_engage_grace(self):
        # A malformed/future genesis producing a negative age must not be treated
        # as "day 0" — it's a clock/config anomaly, not a fresh reset.
        f = ci.check_endpoint_shape("predictions", self.PAYLOAD, self.SPEC, experiment_age_days=-2)
        assert f.is_alarm


class TestCountAgreement:
    def test_arc_7_vs_3_fires(self):
        f = ci.check_count_agreement([{"name": "experiment_arc_weeks", "a": 7, "b": 3}])
        assert f.is_alarm

    def test_agreeing_counts_ok(self):
        f = ci.check_count_agreement([{"name": "experiment_arc_weeks", "a": 3, "b": 3}])
        assert f.status == ci.OK


def test_overall_status_takes_worst():
    findings = [
        ci.Finding("a", ci.OK),
        ci.Finding("b", ci.WARN),
        ci.Finding("c", ci.ALARM),
    ]
    assert ci.overall_status(findings) == ci.ALARM


class TestExperimentContinuity:
    """SS-05: a continuous experiment is fine; a counter that disagrees with genesis
    (the ADR-077 stale-pre-reset leak) is not."""

    GEN = "2026-06-14"

    def test_coherent_continuous_experiment_ok(self):
        # ~2 weeks past genesis; surfaced weeks match → OK (counters grow forever, fine).
        f = ci.check_experiment_continuity(self.GEN, "2026-06-29", [{"name": "arc", "week": 3}])
        assert f.status == ci.OK
        assert f.value == 3.0  # derived week

    def test_stale_pre_reset_high_week_alarms(self):
        # genesis ~2 weeks ago, but a stale week-27 post leaked back into selection.
        f = ci.check_experiment_continuity(self.GEN, "2026-06-29", [{"name": "latest_chronicle_week", "week": 27}])
        assert f.is_alarm
        assert "27" in f.detail

    def test_one_week_boundary_overcount_is_tolerated(self):
        # derived=3, a current-week post one ahead → within tolerance → OK.
        f = ci.check_experiment_continuity(self.GEN, "2026-06-29", [{"name": "arc", "week": 4}])
        assert f.status == ci.OK

    def test_small_overcount_warns_not_alarms(self):
        # derived=3, week=5 (derived+2) → over tolerance but not egregious → WARN.
        f = ci.check_experiment_continuity(self.GEN, "2026-06-29", [{"name": "arc", "week": 5}])
        assert f.status == ci.WARN

    def test_genesis_in_future_alarms(self):
        f = ci.check_experiment_continuity("2026-07-01", "2026-06-29", [])
        assert f.is_alarm
        assert "underflow" in f.detail or "<1" in f.detail

    def test_week_below_one_alarms(self):
        f = ci.check_experiment_continuity(self.GEN, "2026-06-29", [{"name": "arc", "week": 0}])
        assert f.is_alarm

    def test_unparseable_genesis_skips(self):
        f = ci.check_experiment_continuity("not-a-date", "2026-06-29", [{"name": "arc", "week": 3}])
        assert f.status == ci.OK
        assert "skipped" in f.detail
