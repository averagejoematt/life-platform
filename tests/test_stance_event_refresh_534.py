"""tests/test_stance_event_refresh_534.py — #534 event-driven stance refresh.

Covers:
  * deterministic significant-event detection (coach_prediction_evaluator.py):
    a refuted prediction, a sick-day onset (not a continuation), a vice
    relapse, a weight-milestone crossing — each routes to exactly the
    AFFECTED coach, never a platform-wide broadcast;
  * the platform-wide daily cap (epic #526: <=2/day) — budget-tier gated,
    caps new invokes to the remaining budget, never runs away;
  * the STANCE# writer (coach_history_summarizer.py) joining the ADR-104
    grounded-generation gate — a draft that still fabricates a number after
    one corrective regen is never written over a good prior stance
    (fail-keep-prior), and never written at all with no prior to keep;
  * the event_stance_refresh dispatch mode: budget gate, missing-baseline
    skip, and the happy path wiring into _run_stance with the right trigger.

All offline — `_call_haiku`, DynamoDB, and the Lambda invoke client are
mocked/monkeypatched. No real Bedrock calls.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_history_summarizer as chs  # noqa: E402
import coach_prediction_evaluator as ev  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# Event detection — each class routes to exactly the affected coach
# ══════════════════════════════════════════════════════════════════════════


class TestPredictionMissDetection:
    def test_only_refuted_counts_and_one_per_coach(self):
        evaluations = [
            {"coach_id": "sleep_coach", "status": "confirmed", "metric": "sleep_score"},
            {"coach_id": "training_coach", "status": "refuted", "metric": "training_load", "reason": "missed"},
            {"coach_id": "training_coach", "status": "refuted", "metric": "vo2max", "reason": "also missed"},
            {"coach_id": "nutrition_coach", "status": "refuted", "metric": "protein_intake", "reason": "under target"},
        ]
        events = ev._detect_prediction_miss_events(evaluations)
        assert set(events) == {"training_coach", "nutrition_coach"}
        assert events["training_coach"]["type"] == "prediction_refuted"
        # First refuted prediction for the coach wins — no double-firing on a 2nd miss.
        assert "training_load" in events["training_coach"]["detail"]

    def test_no_refuted_no_events(self):
        assert ev._detect_prediction_miss_events([{"coach_id": "sleep_coach", "status": "confirmed"}]) == {}
        assert ev._detect_prediction_miss_events([]) == {}


class TestSickDayOnset:
    def test_onset_fires(self, monkeypatch):
        monkeypatch.setattr(ev, "check_sick_day", lambda table, uid, d: {"reason": "flu"} if d == "2026-07-05" else None)
        out = ev._detect_sick_day_event("2026-07-05", "2026-07-04")
        assert out == {"type": "sick_day_onset", "detail": "a sick day was logged today (flu)"}

    def test_continuation_does_not_refire(self, monkeypatch):
        monkeypatch.setattr(ev, "check_sick_day", lambda table, uid, d: {"reason": "flu"})
        assert ev._detect_sick_day_event("2026-07-05", "2026-07-04") is None

    def test_not_sick_today_no_event(self, monkeypatch):
        monkeypatch.setattr(ev, "check_sick_day", lambda table, uid, d: None)
        assert ev._detect_sick_day_event("2026-07-05", "2026-07-04") is None


class TestViceRelapse:
    def test_relapse_detected(self, monkeypatch):
        def fake_habit_scores(date_str):
            if date_str == "2026-07-05":
                return {"vice_streaks": {"late_night_screens": 0, "soda": 12}}
            return {"vice_streaks": {"late_night_screens": 9, "soda": 12}}

        monkeypatch.setattr(ev, "_habit_scores_for", fake_habit_scores)
        out = ev._detect_relapse_event("2026-07-05", "2026-07-04")
        assert out["type"] == "vice_relapse"
        assert "late_night_screens" in out["detail"]
        assert "soda" not in out["detail"]  # soda streak held — not a relapse

    def test_no_relapse_when_streak_continues(self, monkeypatch):
        monkeypatch.setattr(ev, "_habit_scores_for", lambda d: {"vice_streaks": {"soda": 13}})
        assert ev._detect_relapse_event("2026-07-05", "2026-07-04") is None

    def test_no_data_no_event(self, monkeypatch):
        monkeypatch.setattr(ev, "_habit_scores_for", lambda d: {})
        assert ev._detect_relapse_event("2026-07-05", "2026-07-04") is None


class TestWeightMilestoneCrossing:
    def test_crossing_detected(self, monkeypatch):
        # 285 ("Sleep Threshold") sits strictly between 286 (yesterday) and 284 (today).
        def fake_resolve(metric, cache, end_date):
            return {"2026-07-05": 284.0, "2026-07-04": 286.0}[end_date]

        monkeypatch.setattr(ev, "_resolve_metric_value", fake_resolve)
        out = ev._detect_milestone_event("2026-07-05", "2026-07-04")
        assert out["type"] == "weight_milestone"
        assert "Sleep Threshold" in out["detail"]

    def test_no_crossing_when_no_milestone_between(self, monkeypatch):
        # Both readings sit above the highest nearby milestone band — no crossing.
        def fake_resolve(metric, cache, end_date):
            return {"2026-07-05": 283.9, "2026-07-04": 283.5}[end_date]

        monkeypatch.setattr(ev, "_resolve_metric_value", fake_resolve)
        assert ev._detect_milestone_event("2026-07-05", "2026-07-04") is None

    def test_regain_is_not_a_milestone(self, monkeypatch):
        # Weight went UP (regain) across 285 — not the positive event the ladder models.
        def fake_resolve(metric, cache, end_date):
            return {"2026-07-05": 286.0, "2026-07-04": 284.0}[end_date]

        monkeypatch.setattr(ev, "_resolve_metric_value", fake_resolve)
        assert ev._detect_milestone_event("2026-07-05", "2026-07-04") is None

    def test_missing_data_is_safe(self, monkeypatch):
        monkeypatch.setattr(ev, "_resolve_metric_value", lambda *a, **k: None)
        assert ev._detect_milestone_event("2026-07-05", "2026-07-04") is None


class TestDetectStanceEventsUnion:
    def test_routes_each_class_to_its_own_coach_only(self, monkeypatch):
        monkeypatch.setattr(ev, "_detect_sick_day_event", lambda t, y: {"type": "sick_day_onset", "detail": "d"})
        monkeypatch.setattr(ev, "_detect_relapse_event", lambda t, y: {"type": "vice_relapse", "detail": "d"})
        monkeypatch.setattr(ev, "_detect_milestone_event", lambda t, y: None)
        evaluations = [{"coach_id": "labs_coach", "status": "refuted", "metric": "cholesterol", "reason": "x"}]
        events = ev._detect_stance_events(evaluations, "2026-07-05", "2026-07-04")
        assert events == {
            "labs_coach": {"type": "prediction_refuted", "detail": "a prediction about cholesterol was just graded refuted (x)"},
            "physical_coach": {"type": "sick_day_onset", "detail": "d"},
            "mind_coach": {"type": "vice_relapse", "detail": "d"},
        }
        # Only these 3 coaches got an event — every other coach is untouched.
        assert "sleep_coach" not in events and "training_coach" not in events

    def test_no_events_when_nothing_detected(self, monkeypatch):
        monkeypatch.setattr(ev, "_detect_sick_day_event", lambda t, y: None)
        monkeypatch.setattr(ev, "_detect_relapse_event", lambda t, y: None)
        monkeypatch.setattr(ev, "_detect_milestone_event", lambda t, y: None)
        assert ev._detect_stance_events([], "2026-07-05", "2026-07-04") == {}


# ══════════════════════════════════════════════════════════════════════════
# The platform-wide daily cap — budget-gated, never runs away
# ══════════════════════════════════════════════════════════════════════════


class TestDailyCapAndBudgetGate:
    def test_cap_is_two_per_epic_526_budget(self):
        assert ev.STANCE_EVENT_REFRESH_DAILY_CAP == 2

    def test_budget_tier_pause_blocks_all_firing(self, monkeypatch):
        monkeypatch.setattr(ev, "_budget_allow", lambda feature: False)
        invoked = []
        monkeypatch.setattr(ev._lambda_client, "invoke", lambda **k: invoked.append(k))
        events = {"sleep_coach": {"type": "prediction_refuted", "detail": "x"}}
        out = ev._fire_event_stance_refreshes(events, "2026-07-05")
        assert out == {"detected": 1, "fired": 0, "skipped": "budget_tier"}
        assert invoked == []

    def test_cap_already_reached_blocks_all_firing(self, monkeypatch):
        monkeypatch.setattr(ev, "_budget_allow", lambda feature: True)
        monkeypatch.setattr(ev, "_event_refresh_count_today", lambda d: 2)
        invoked = []
        monkeypatch.setattr(ev._lambda_client, "invoke", lambda **k: invoked.append(k))
        events = {"sleep_coach": {"type": "prediction_refuted", "detail": "x"}}
        out = ev._fire_event_stance_refreshes(events, "2026-07-05")
        assert out["fired"] == 0 and out["skipped"] == "daily_cap_reached"
        assert invoked == []

    def test_never_fires_more_than_the_remaining_cap(self, monkeypatch):
        # 3 distinct coaches qualify the same run; only 2 (the cap) may fire.
        monkeypatch.setattr(ev, "_budget_allow", lambda feature: True)
        monkeypatch.setattr(ev, "_event_refresh_count_today", lambda d: 0)
        invoked = []
        monkeypatch.setattr(ev._lambda_client, "invoke", lambda **k: invoked.append(k))
        events = {
            "sleep_coach": {"type": "prediction_refuted", "detail": "a"},
            "training_coach": {"type": "prediction_refuted", "detail": "b"},
            "nutrition_coach": {"type": "prediction_refuted", "detail": "c"},
        }
        out = ev._fire_event_stance_refreshes(events, "2026-07-05")
        assert out["fired"] == 2
        assert len(invoked) == 2

    def test_partial_cap_fires_only_the_remainder(self, monkeypatch):
        # 1 already done today, cap 2 -> only 1 more may fire even with 2 candidates.
        monkeypatch.setattr(ev, "_budget_allow", lambda feature: True)
        monkeypatch.setattr(ev, "_event_refresh_count_today", lambda d: 1)
        invoked = []
        monkeypatch.setattr(ev._lambda_client, "invoke", lambda **k: invoked.append(k))
        events = {
            "sleep_coach": {"type": "prediction_refuted", "detail": "a"},
            "training_coach": {"type": "prediction_refuted", "detail": "b"},
        }
        out = ev._fire_event_stance_refreshes(events, "2026-07-05")
        assert out["fired"] == 1
        assert len(invoked) == 1

    def test_invoke_payload_shape(self, monkeypatch):
        monkeypatch.setattr(ev, "_budget_allow", lambda feature: True)
        monkeypatch.setattr(ev, "_event_refresh_count_today", lambda d: 0)
        invoked = []
        monkeypatch.setattr(ev._lambda_client, "invoke", lambda **k: invoked.append(k))
        events = {"sleep_coach": {"type": "prediction_refuted", "detail": "x"}}
        ev._fire_event_stance_refreshes(events, "2026-07-05")
        assert len(invoked) == 1
        call = invoked[0]
        assert call["FunctionName"] == "coach-history-summarizer"
        assert call["InvocationType"] == "Event"  # async, fire-and-forget
        import json as _json

        payload = _json.loads(call["Payload"])
        assert payload == {
            "mode": "event_stance_refresh",
            "coach_id": "sleep_coach",
            "trigger_event": {"type": "prediction_refuted", "detail": "x"},
        }

    def test_no_events_short_circuits_without_reading_the_cap(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("should not check budget/cap with zero events")

        monkeypatch.setattr(ev, "_budget_allow", boom)
        out = ev._fire_event_stance_refreshes({}, "2026-07-05")
        assert out == {"detected": 0, "fired": 0, "skipped": "no_events"}


class TestEventRefreshCountToday:
    def test_counts_only_event_triggered_stances(self, monkeypatch):
        items = {
            "sleep_coach": {"trigger": "event:sick_day_onset"},
            "training_coach": {"trigger": "weekly"},
            "nutrition_coach": {"trigger": "event:vice_relapse"},
        }

        def fake_get_item(Key):
            coach_id = Key["pk"].replace("COACH#", "")
            item = items.get(coach_id)
            return {"Item": item} if item else {}

        monkeypatch.setattr(ev.table, "get_item", fake_get_item)
        assert ev._event_refresh_count_today("2026-07-05") == 2


# ══════════════════════════════════════════════════════════════════════════
# The ADR-104 gate joining the STANCE# writer (#534) — fail-keep-prior
# ══════════════════════════════════════════════════════════════════════════


class TestGroundingGateOnGeneration:
    def test_clean_stance_passes_without_a_regen_call(self, monkeypatch):
        calls = []

        def fake_haiku(**k):
            calls.append(k)
            return {"headline_read": "You're building consistency.", "stage": {"label": "foundation"}}

        monkeypatch.setattr(chs, "_call_haiku", fake_haiku)
        out = chs._generate_stance("sleep_coach", {"corrections_made": []}, {}, None)
        assert out["_adr104_findings"] == []
        assert len(calls) == 1  # no corrective regen needed

    def test_persistent_fabricated_number_flags_findings_and_does_not_infinite_loop(self, monkeypatch):
        # A plausible-but-invented count that survives the one allowed regen —
        # "mock the gate failure case" per the task.
        calls = []

        def fake_haiku(**k):
            calls.append(k)
            return {"headline_read": "You've logged 172 consecutive days of consistency.", "stage": {"label": "x"}}

        monkeypatch.setattr(chs, "_call_haiku", fake_haiku)
        out = chs._generate_stance("sleep_coach", {"corrections_made": []}, {}, None)
        assert out["_adr104_findings"], "a fabricated number with no grounding should survive the gate"
        assert len(calls) == 2  # exactly one corrective regen attempted, never more

    def test_regen_that_fixes_the_number_is_adopted(self, monkeypatch):
        responses = [
            {"headline_read": "You've logged 172 consecutive days.", "stage": {"label": "x"}},
            {"headline_read": "You've been remarkably consistent lately.", "stage": {"label": "x"}},
        ]
        calls = []

        def fake_haiku(**k):
            calls.append(k)
            return responses[len(calls) - 1]

        monkeypatch.setattr(chs, "_call_haiku", fake_haiku)
        out = chs._generate_stance("sleep_coach", {"corrections_made": []}, {}, None)
        assert out["_adr104_findings"] == []
        assert "172" not in out["headline_read"]
        assert len(calls) == 2


class TestRunStanceFailKeepPrior:
    def test_gate_failure_with_prior_keeps_prior_and_never_writes(self, monkeypatch):
        prior = {"headline_read": "old grounded read", "stage": {"label": "consistency"}}
        monkeypatch.setattr(chs, "_gather_learning", lambda cid: [])
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: prior)
        monkeypatch.setattr(
            chs,
            "_generate_stance",
            lambda *a, **k: {
                "coach_id": "sleep_coach",
                "as_of": "2026-07-05",
                "headline_read": "bad draft",
                "stage": {"label": "x"},
                "grounding_flag": False,
                "_adr104_findings": [{"type": "fabricated_number", "claimed": 172.0, "detail": "x"}],
            },
        )
        write_calls = []
        monkeypatch.setattr(chs, "_write_stance", lambda cid, stance: write_calls.append(stance) or True)

        result = chs._run_stance("sleep_coach", {"summary": "x"}, {"confidence_records": []}, trigger="event:sick_day_onset")
        assert result["written"] is False
        assert result["reason"] == "adr104_gate_failed_kept_prior"
        assert write_calls == []  # the prior stance was never overwritten

    def test_gate_failure_with_no_prior_skips_write_entirely(self, monkeypatch):
        monkeypatch.setattr(chs, "_gather_learning", lambda cid: [])
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)  # no prior stance exists yet
        monkeypatch.setattr(
            chs,
            "_generate_stance",
            lambda *a, **k: {
                "coach_id": "sleep_coach",
                "as_of": "2026-07-05",
                "headline_read": "bad draft",
                "stage": {"label": "x"},
                "grounding_flag": False,
                "_adr104_findings": [{"type": "fabricated_number", "claimed": 172.0, "detail": "x"}],
            },
        )
        write_calls = []
        monkeypatch.setattr(chs, "_write_stance", lambda cid, stance: write_calls.append(stance) or True)

        result = chs._run_stance("sleep_coach", {"summary": "x"}, {"confidence_records": []})
        assert result["written"] is False
        assert result["reason"] == "adr104_gate_failed_no_prior"
        assert write_calls == []

    def test_clean_generation_writes_with_trigger_field(self, monkeypatch):
        monkeypatch.setattr(chs, "_gather_learning", lambda cid: [])
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)
        monkeypatch.setattr(
            chs,
            "_generate_stance",
            lambda *a, **k: {
                "coach_id": "sleep_coach",
                "as_of": "2026-07-05",
                "headline_read": "clean read",
                "stage": {"label": "x"},
                "how_my_read_changed": "",
                "grounding_flag": False,
                "_adr104_findings": [],
            },
        )
        write_calls = []
        monkeypatch.setattr(chs, "_write_stance", lambda cid, stance: write_calls.append(stance) or True)

        result = chs._run_stance("sleep_coach", {"summary": "x"}, {"confidence_records": []}, trigger="event:vice_relapse")
        assert result["written"] is True
        assert write_calls[0]["trigger"] == "event:vice_relapse"


# ══════════════════════════════════════════════════════════════════════════
# The event_stance_refresh dispatch mode
# ══════════════════════════════════════════════════════════════════════════


class TestEventStanceRefreshDispatch:
    def test_invalid_coach_id_rejected(self):
        out = chs.lambda_handler({"mode": "event_stance_refresh", "coach_id": "not_a_coach"}, None)
        assert out["statusCode"] == 400

    def test_budget_tier_paused_skips_without_calling_run_stance(self, monkeypatch):
        import budget_guard

        monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
        called = []
        monkeypatch.setattr(chs, "_run_stance", lambda *a, **k: called.append(1))
        out = chs.lambda_handler({"mode": "event_stance_refresh", "coach_id": "sleep_coach"}, None)
        assert out["skipped"] == "budget_tier"
        assert called == []

    def test_missing_compressed_baseline_skips(self, monkeypatch):
        import budget_guard

        monkeypatch.setattr(budget_guard, "allow", lambda feature: True)
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)
        out = chs.lambda_handler({"mode": "event_stance_refresh", "coach_id": "sleep_coach"}, None)
        assert out["skipped"] == "no_compressed_baseline"

    def test_fallback_compressed_baseline_skips(self, monkeypatch):
        import budget_guard

        monkeypatch.setattr(budget_guard, "allow", lambda feature: True)
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: {"_fallback": True})
        out = chs.lambda_handler({"mode": "event_stance_refresh", "coach_id": "sleep_coach"}, None)
        assert out["skipped"] == "no_compressed_baseline"

    def test_happy_path_calls_run_stance_with_event_trigger(self, monkeypatch):
        import budget_guard

        monkeypatch.setattr(budget_guard, "allow", lambda feature: True)
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: {"summary": "compressed history"})
        monkeypatch.setattr(chs, "_query_begins_with", lambda pk, prefix: [])
        captured = {}

        def fake_run_stance(coach_id, compressed, state, trigger="weekly", event_context=None):
            captured["coach_id"] = coach_id
            captured["trigger"] = trigger
            captured["event_context"] = event_context
            return {"written": True}

        monkeypatch.setattr(chs, "_run_stance", fake_run_stance)
        event = {
            "mode": "event_stance_refresh",
            "coach_id": "mind_coach",
            "trigger_event": {"type": "vice_relapse", "detail": "the streak on soda just reset to 0"},
        }
        out = chs.lambda_handler(event, None)
        assert out["statusCode"] == 200
        assert out["result"] == {"written": True}
        assert captured["coach_id"] == "mind_coach"
        assert captured["trigger"] == "event:vice_relapse"
        assert captured["event_context"]["type"] == "vice_relapse"

    def test_weekly_mode_is_unaffected_by_the_new_dispatch(self, monkeypatch):
        # No "mode" key -> falls through to the ordinary weekly path untouched.
        monkeypatch.setattr(chs, "_gather_coach_state", lambda cid: {"outputs": [], "open_threads": [], "active_predictions": []})
        out = chs.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
        assert out["results"]["sleep_coach"]["status"] == "skipped"
        assert out["results"]["sleep_coach"]["reason"] == "no data"
