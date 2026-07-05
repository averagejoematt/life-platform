"""tests/test_hae_datatype_liveness_468.py — #468 D-4 per-datatype liveness + D-8 alert dedup.

Pure-function tests (no AWS): every HAE datatype lands in the one apple_health partition,
so per-datatype last-seen is derived from which prefixed field last appeared; and the
DI-1.6 degraded alert is gated to one send per episode + a daily reminder.
"""

import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from emails.freshness_checker_lambda import alert_episode_decision, compute_datatype_liveness  # noqa: E402

NOW = datetime(2026, 7, 5, tzinfo=timezone.utc)


def _rec(date, **fields):
    return {"sk": f"DATE#{date}", **fields}


class TestDatatypeLiveness:
    def test_last_seen_is_most_recent_date_with_any_field(self):
        records = [
            _rec("2026-07-04", steps=8000, water_intake_ml=500),  # steps + water fresh
            _rec("2026-07-01", blood_glucose_avg=105),  # CGM 4 days ago
            _rec("2026-05-01", blood_pressure_systolic=118),  # BP months dark
        ]
        by = {d["key"]: d for d in compute_datatype_liveness(records, NOW)}
        assert by["steps"]["last_seen"] == "2026-07-04" and by["steps"]["age_days"] == 1
        assert by["cgm"]["last_seen"] == "2026-07-01" and by["cgm"]["age_days"] == 4
        assert by["blood_pressure"]["last_seen"] == "2026-05-01"

    def test_dark_flag_respects_per_datatype_threshold(self):
        records = [
            _rec("2026-07-04", steps=8000),
            _rec("2026-07-01", blood_glucose_avg=105),  # CGM stale_days=3, age 4 -> dark
            _rec("2026-05-01", blood_pressure_systolic=118),  # BP stale_days=14 -> dark
        ]
        by = {d["key"]: d for d in compute_datatype_liveness(records, NOW)}
        assert by["steps"]["dark"] is False
        assert by["cgm"]["dark"] is True  # 4 > 3
        assert by["blood_pressure"]["dark"] is True

    def test_never_seen_datatype_is_dark_with_none(self):
        by = {d["key"]: d for d in compute_datatype_liveness([_rec("2026-07-04", steps=8000)], NOW)}
        assert by["state_of_mind"]["last_seen"] is None
        assert by["state_of_mind"]["age_days"] is None
        assert by["state_of_mind"]["dark"] is True

    def test_all_datatypes_present_in_output(self):
        out = compute_datatype_liveness([], NOW)
        assert {d["key"] for d in out} == {"cgm", "blood_pressure", "state_of_mind", "workouts", "water", "steps"}


class TestAlertEpisodeDedup:
    def test_first_degraded_run_sends_and_opens_episode(self):
        send, state, kind = alert_episode_decision(None, True, NOW)
        assert send is True and kind == "open"
        assert state["episode_open"] is True and state["send_count"] == 1

    def test_second_run_same_day_holds(self):
        _, state, _ = alert_episode_decision(None, True, NOW)
        send, state2, kind = alert_episode_decision(state, True, NOW.replace(hour=NOW.hour))  # same time
        assert send is False and kind == "hold"
        assert state2["send_count"] == 1  # not incremented

    def test_reminder_fires_after_24h(self):
        _, state, _ = alert_episode_decision(None, True, NOW)
        later = datetime(2026, 7, 6, NOW.hour, tzinfo=timezone.utc)  # +24h
        send, state2, kind = alert_episode_decision(state, True, later)
        assert send is True and kind == "reminder"
        assert state2["send_count"] == 2

    def test_recovery_closes_episode_without_sending(self):
        _, state, _ = alert_episode_decision(None, True, NOW)
        send, state2, kind = alert_episode_decision(state, False, NOW)
        assert send is False and kind == "resolved"
        assert state2["episode_open"] is False and state2.get("resolved_at")

    def test_quiet_when_never_degraded(self):
        send, _, kind = alert_episode_decision(None, False, NOW)
        assert send is False and kind == "quiet"

    def test_thirty_six_invocations_produce_one_send(self):
        # The bug: 36 sends in 72h. With episode dedup, 36 same-day runs -> exactly 1 send.
        state = None
        sends = 0
        for i in range(36):
            send, state, _ = alert_episode_decision(state, True, NOW.replace(minute=i % 60))
            sends += 1 if send else 0
        assert sends == 1
