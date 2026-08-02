"""tests/test_hae_datatype_liveness_468.py — #468 D-4 per-datatype liveness + D-8 alert dedup.

Pure-function tests (no AWS): every HAE datatype lands in the one apple_health partition,
so per-datatype last-seen is derived from which prefixed field last appeared; and the
DI-1.6 degraded alert is gated to one send per episode + a daily reminder.

#2001 (TestDeepScanBeyondWindow): the newest-N window cap must never ERASE the
"dark N days" number exactly when the lapse is longest — a datatype unresolved by
the window gets a targeted filtered deep scan back to the lookback horizon, and a
truly-absent datatype carries the honest `age_floor_days` bound (ADR-104), never
a fabricated number. The first test fails on the pre-#2001 tree (single capped
query, no pagination → BP renders dark with no number).
"""

import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from emails.freshness_checker_lambda import (  # noqa: E402
    HAE_LIVENESS_MAX_LOOKBACK_DAYS,
    alert_episode_decision,
    check_apple_health_datatypes,
    compute_datatype_liveness,
)

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


class _FakeHaeTable:
    """Dispatches on the query SHAPE: the cheap window pass uses begins_with (no
    FilterExpression); the #2001 deep scan uses BETWEEN + FilterExpression. Pages
    for the deep scan are supplied as a list of {"Items": [...], "LastEvaluatedKey": ...}.
    """

    def __init__(self, window_items, deep_pages=None):
        self.window_items = window_items
        self.deep_pages = list(deep_pages or [])
        self.deep_calls = 0
        self.deep_filters = []

    def query(self, **kwargs):
        if "FilterExpression" not in kwargs:
            return {"Items": list(self.window_items)}
        self.deep_calls += 1
        self.deep_filters.append(kwargs["FilterExpression"])
        # Key-condition floor must ride the deep scan (bounds the DDB read).
        assert "BETWEEN" in kwargs["KeyConditionExpression"]
        assert kwargs["ExpressionAttributeValues"][":lo"].startswith("DATE#")
        idx = min(self.deep_calls - 1, len(self.deep_pages) - 1) if self.deep_pages else 0
        return self.deep_pages[idx] if self.deep_pages else {"Items": []}


def _window_without_bp():
    """A healthy 45-day-ish window: steps/water present, NO BP/SoM anywhere —
    the exact live shape measured 2026-08-02 (window bottomed out mid-June while
    BP's true last record sat at 2026-04-10)."""
    return [
        _rec("2026-07-04", steps=8000, water_intake_ml=500, blood_glucose_avg=100, recovery_workout_minutes=20, som_avg_valence=0.5)
    ] + [_rec(f"2026-06-{d:02d}", steps=7000) for d in range(30, 15, -1)]


class TestDeepScanBeyondWindow:
    def test_window_lost_bp_recovers_numeric_age_via_deep_scan(self):
        # Regression for #2001: only BP record predates the window → the deep scan
        # must find it and report a NUMERIC age, not dark-with-no-number.
        fake = _FakeHaeTable(_window_without_bp(), deep_pages=[{"Items": [_rec("2026-04-10", blood_pressure_systolic=118)]}])
        by = {d["key"]: d for d in check_apple_health_datatypes(fake, NOW)}
        assert by["blood_pressure"]["last_seen"] == "2026-04-10"
        assert by["blood_pressure"]["age_days"] == (NOW.date() - datetime(2026, 4, 10).date()).days  # 86 — numeric, not None
        assert by["blood_pressure"]["dark"] is True
        assert "age_floor_days" not in by["blood_pressure"]

    def test_deep_scan_runs_only_for_window_unresolved_datatypes(self):
        # Everything except BP resolves in the window (SoM included) → exactly one deep scan.
        window = _window_without_bp()
        fake = _FakeHaeTable(window, deep_pages=[{"Items": [_rec("2026-04-10", blood_pressure_diastolic=76)]}])
        check_apple_health_datatypes(fake, NOW)
        assert fake.deep_calls == 1
        assert "blood_pressure" in fake.deep_filters[0]

    def test_deep_scan_paginates_past_an_empty_filtered_page(self):
        # A filtered query can return an empty page WITH a LastEvaluatedKey — the
        # scan must follow it rather than concluding absence.
        pages = [
            {"Items": [], "LastEvaluatedKey": {"pk": "x", "sk": "DATE#2026-05-01"}},
            {"Items": [_rec("2026-04-10", blood_pressure_systolic=118)]},
        ]
        fake = _FakeHaeTable(_window_without_bp(), deep_pages=pages)
        by = {d["key"]: d for d in check_apple_health_datatypes(fake, NOW)}
        assert by["blood_pressure"]["last_seen"] == "2026-04-10"
        assert fake.deep_calls == 2

    def test_no_record_in_horizon_reports_floor_never_fabricates(self):
        # ADR-104: nothing findable inside the deep horizon → age stays None (no
        # invented number) and the honest ">N days" bound is stamped instead.
        fake = _FakeHaeTable(_window_without_bp(), deep_pages=[{"Items": []}])
        by = {d["key"]: d for d in check_apple_health_datatypes(fake, NOW)}
        assert by["blood_pressure"]["last_seen"] is None
        assert by["blood_pressure"]["age_days"] is None
        assert by["blood_pressure"]["dark"] is True
        assert by["blood_pressure"]["age_floor_days"] == HAE_LIVENESS_MAX_LOOKBACK_DAYS

    def test_null_typed_attribute_is_not_a_sighting(self):
        # attribute_exists() matches DDB NULL types — the Python-side presence
        # re-check must skip a None value and keep looking on the same page.
        page = {"Items": [_rec("2026-06-01", blood_pressure_systolic=None), _rec("2026-04-10", blood_pressure_systolic=118)]}
        fake = _FakeHaeTable(_window_without_bp(), deep_pages=[page])
        by = {d["key"]: d for d in check_apple_health_datatypes(fake, NOW)}
        assert by["blood_pressure"]["last_seen"] == "2026-04-10"


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
