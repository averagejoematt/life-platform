"""tests/test_fixed_workload_test_5798.py — the fixed-workload treadmill test in the fitness battery (#5798).

Owner ruling 2026-11-11: the fixed-workload cardio test is the TREADMILL, 20 minutes at a fixed speed and incline, mean heart
rate over minutes 10-20 plus the RPE; the bike test (`bike_20min_rpe6`) stays as it is. Heart rate is a measurement, never an
effort gate. Fixtures are the stored shapes (Hevy workout row with `cardio_hr`, Strava-shaped activities). No clock is read.

Must-fail controls (each run red, then green): `DEDICATED_SPAN_MAX` -> a huge number reds the whole-session-average refusal;
`_series_key` -> a constant reds the cross-regime and cross-setting separation.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from training import (  # noqa: E402
    cardio_hr,
    fitness_tests as ft,
    training_charter as tc,
)

MOVEMENTS = json.loads((_REPO / "config" / "movement_catalog.json").read_text())["movements"]
TID = "treadmill_20min_fixed"
T0 = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _act(start, secs, avg=130, device="Apple Watch"):
    return {
        "start_date": start.isoformat(),
        "elapsed_time_seconds": secs,
        "average_heartrate": avg,
        "max_heartrate": avg + 20,
        "device_name": device,
        "sport_type": "Walk",
    }


# ── the charter ──────────────────────────────────────────────────────────────────────────
def test_the_charter_carries_the_test_beside_the_unchanged_bike_test():
    p = ft.protocol()
    spec = ft.tests_spec()
    row = spec[TID]
    assert (row["unit"], row["better"], row["duration_s"], row["catalog_key"]) == ("bpm", "lower", 1200, "treadmill")
    assert row["regime_bound"] is True
    assert "owner to confirm" in row["setting"]["provenance"] and "platform-proposed" in row["setting"]["provenance"]
    assert str(row["setting"]["speed_mph"]) in row["protocol"] and str(row["setting"]["incline_pct"]) in row["protocol"]
    assert "RPE at the end" in row["protocol"]
    bike = spec["bike_20min_rpe6"]  # the ruling: no second bike test, the existing one as it was
    assert (bike["unit"], bike["better"], bike["duration_s"]) == ("m", "higher", 1200)
    assert p["order"].index(TID) < p["order"].index("bike_20min_rpe6") and p["protocol_version"] == "2"
    assert sorted(p["order"]) == sorted([*spec, "minimum_session"])


def test_the_join_constants_equal_the_charters_window():
    row = ft.tests_spec()[TID]
    assert cardio_hr.FINAL_WINDOW_FROM_S == row["window_from_s"] and cardio_hr.FINAL_WINDOW_BLOCK_S == row["duration_s"]
    assert row["window_to_s"] == row["duration_s"]


# ── the join over minutes 10-20 ──────────────────────────────────────────────────────────
def test_the_final_window_is_joined_from_a_watch_workout_that_is_the_test():
    b0, b1 = T0, T0 + timedelta(seconds=1200)
    got = cardio_hr.final_window(b0, b1, [_act(b0 - timedelta(seconds=60), 1300, avg=131.0)])
    assert got["state"] == "joined" and got["mean_hr"] == 131.0 and got["hr_coverage"] == 1.0
    assert got["window"]["start_utc"] == (b0 + timedelta(seconds=600)).isoformat()


def test_a_whole_session_average_is_refused_never_stored_as_minutes_10_to_20(monkeypatch):
    b0, b1 = T0, T0 + timedelta(seconds=1200)
    session = _act(b0 - timedelta(seconds=3000), 4400, avg=105.0, device="WHOOP")  # the gym session with the treadmill at its tail
    got = cardio_hr.final_window(b0, b1, [session])
    assert got["state"] == "unknown" and got["mean_hr"] is None and "whole-session average" in got["reason"]
    monkeypatch.setattr(cardio_hr, "DEDICATED_SPAN_MAX", 1e9)  # control: without the guard the session average passes as a value
    assert cardio_hr.final_window(b0, b1, [session])["mean_hr"] == 105.0


def test_below_the_coverage_threshold_there_is_no_value():
    b0, b1 = T0, T0 + timedelta(seconds=1200)
    got = cardio_hr.final_window(b0, b1, [_act(b0 + timedelta(seconds=1000), 1200)])  # covers 200 of the 600 s window
    assert got["state"] == "unknown" and got["mean_hr"] is None and got["hr_coverage"] < cardio_hr.HR_COVERAGE_MIN
    assert cardio_hr.final_window(b0, b1, [])["mean_hr"] is None


def _workout(secs, activities, notes="3.2 mph and 3.5 incline. RPE 5"):
    w0 = T0
    ex = {
        "name": "Treadmill",
        "template_id": MOVEMENTS["treadmill"]["hevy_template_id_hint"],
        "sets": [{"type": "normal", "duration_sec": secs}],
        "notes": notes,
    }
    return {
        "date": "2026-11-20",
        "title": ft.BATTERY_TITLE + " — Shoulders+arms",
        "start_time": (w0 - timedelta(seconds=100)).isoformat(),
        "end_time": (w0 + timedelta(seconds=secs)).isoformat(),
        "exercises": [ex],
        "_acts": activities,
    }


def _joined(secs, activities, **kw):
    w = _workout(secs, activities, **kw)
    w["cardio_hr"] = cardio_hr.join_workout(w, w.pop("_acts"))
    return w


def test_only_a_twenty_minute_walking_block_gets_the_final_window():
    ok = _joined(1200, [_act(T0, 1200)])
    assert "final_window" in cardio_hr.block_for(ok, 0)
    assert "final_window" not in cardio_hr.block_for(_joined(2700, [_act(T0, 2700)]), 0)


# ── Hevy reader ──────────────────────────────────────────────────────────────────────────
def test_hevy_reads_hr_setting_and_rpe_and_never_confuses_the_six_minute_walk():
    got = ft.from_hevy([_joined(1200, [_act(T0, 1200, avg=129.0)])], MOVEMENTS)["2026-11-20"]
    assert set(got) == {TID}
    row = got[TID]
    assert row["value"] == 129.0 and row["unit"] == "bpm" and row["rpe"] == 5.0 and row["setting"] == "3.2 mph / 3.5 %"
    assert row["source"] == "hevy" and row.get("state") is None
    six = _joined(360, [])
    six["exercises"][0]["sets"][0]["distance_m"] = 600
    assert set(ft.from_hevy([six], MOVEMENTS)["2026-11-20"]) == {"six_minute_walk"}


def test_a_test_with_no_usable_hr_is_stored_invalid_with_its_reason_never_a_value():
    got = ft.from_hevy([_joined(1200, [])], MOVEMENTS)["2026-11-20"][TID]
    assert got["state"] == ft.INVALID and got["value"] is None and got["reason"]
    tr = ft.trend(ft.batteries([], {"2026-11-20": {TID: got}}))[TID]
    assert tr["state"] == ft.INVALID and "latest" not in tr


def test_the_explicit_record_carries_setting_and_rpe():
    rec = ft.build_battery_record(date="2026-11-20", results={TID: 128}, notes={TID: "felt easy, RPE 4"}, recorded_at="t")
    row = rec["tests"][TID]
    assert (row["value"], row["unit"], row["setting"], row["rpe"], row["source"]) == (128.0, "bpm", "3.2 mph / 3.5 %", 4.0, "explicit")


# ── trend: never across the regime marker, never across a setting ────────────────────────
def _b(date, v, setting="3.2 mph / 3.5 %", rpe=5.0):
    return {"date": date, "tests": {TID: {"value": v, "unit": "bpm", "source": "explicit", "setting": setting, "rpe": rpe}}}


def test_no_result_before_the_regime_marker_is_compared_with_one_after_it():
    t = ft.trend([_b("2026-10-01", 120.0), _b("2026-11-20", 150.0)])[TID]
    assert t["direction"] == "first" and t["previous"] is None and t["delta"] is None
    assert t["compared_within"]["hr_regime_marker"] == "2026-10-10"
    both_after = ft.trend([_b("2026-11-20", 150.0), _b("2027-01-05", 140.0)])[TID]
    assert both_after["direction"] == "better" and both_after["delta"] == -10.0 and both_after["latest"]["rpe"] == 5.0


def test_a_changed_setting_starts_a_new_series():
    t = ft.trend([_b("2026-11-20", 150.0), _b("2027-01-05", 160.0, setting="3.4 mph / 3.5 %")])[TID]
    assert t["direction"] == "first" and t["previous"] is None


def test_the_comparison_guard_is_load_bearing(monkeypatch):
    monkeypatch.setattr(
        ft, "_series_key", lambda row, date, test: (None, None)
    )  # control: with no separation the pre-marker value compares
    t = ft.trend([_b("2026-10-01", 120.0), _b("2026-11-20", 150.0)])[TID]
    assert t["direction"] == "worse" and t["delta"] == 30.0  # the exact lie the guard exists to prevent
