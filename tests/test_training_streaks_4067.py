"""tests/test_training_streaks_4067.py — the rest-day ask keys on the LOADED streak (#4067).

On 2026-09-22 the joints/tendons critic read `consecutive_training_days = 16` — every day with
ANY Hevy session, v0.3 Engine (treadmill + bike) days included — and asked for a rest day.
Now two streaks are named in the packet; only `loaded_lifting_streak` can produce the ask, and
its thresholds come from his 2024–25 record (`training_streaks.CALIBRATION`, ADR-105).

EACH TEST NAMES THE MUTATION THAT REDS IT.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics as c  # noqa: E402
from training import training_streaks as ts  # noqa: E402

from mcp import tools_plan as tp  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "shared_quantities_4068"
TARGET = "2026-10-20"


def _d(n: int) -> str:
    return (date.fromisoformat(TARGET) - timedelta(days=n)).isoformat()


def _lift(day: str) -> dict:
    return {"date": day, "exercises": [{"name": "Squat (Barbell)", "sets": [{"type": "normal", "weight_kg": 80, "reps": 5}]}]}


def _engine(day: str) -> dict:
    return {
        "date": day,
        "exercises": [
            {"name": "Treadmill", "sets": [{"duration_sec": 3600}]},
            {"name": "Cycling", "sets": [{"duration_sec": 2700}]},
            {"name": "Stretching", "sets": [{"duration_sec": 900}]},
        ],
    }


def _walk(day: str) -> dict:
    return {"date": day, "activities": [{"type": "Walk", "moving_time_seconds": 3600}]}


def _sixteen_active_four_loaded():
    """16 active days before TARGET: the last 4 loaded lifts, then an Engine day, then walks."""
    hevy = [_lift(_d(n)) for n in range(1, 5)] + [_engine(_d(5))] + [_engine(_d(n)) for n in (8, 11)]
    strava = [_walk(_d(n)) for n in range(1, 17)]
    return hevy, strava


def _joints(active, loaded):
    draft = {"exercises": [], "total_sets": 0}
    return c.build_joints_packet(
        draft, pain_by_idx={}, days_since_by_idx={}, active_day_streak=active, loaded_lifting_streak=loaded, pain_layer_status="ok"
    )


# ── acceptance: the fixture ────────────────────────────────────────────────────────
def test_sixteen_active_days_with_a_four_day_lifting_streak_asks_for_no_rest_day():
    """The issue's own fixture. Mutation control: key the ask on `active_day_streak` — 16
    crosses every threshold and the joints verdict becomes a change."""
    hevy, strava = _sixteen_active_four_loaded()
    s = ts.streaks(hevy, strava, TARGET)
    assert s["active_day_streak"] == 16 and s["loaded_lifting_streak"] == 4
    p = _joints(s["active_day_streak"], s["loaded_lifting_streak"])
    assert p["numbers"]["active_day_streak"] == 16 and p["numbers"]["loaded_lifting_streak"] == 4
    assert [f for f in p["flags"] if "streak" in f["metric"]] == []
    (v,) = [
        v
        for v in c.run_critics(_all(p), {"exercises": [], "total_sets": 0}, invoke=None, model_allowed=False)
        if v["critic"] == "joints_tendons"
    ]
    assert v["verdict"] == "approve"


def test_a_model_cannot_manufacture_the_ask_from_the_active_streak():
    """The active streak is never flagged, so a model citing it has no handle (#3851).
    Mutation control: add an info flag on `active_day_streak` — the change is then allowed."""
    p = _joints(16, 4)

    def invoke(_body):
        reply = {
            "verdict": "change",
            "metric": "active_day_streak",
            "value": 16,
            "field": "session.total_sets",
            "to": 10,
            "sentence": "Rest.",
        }
        return {"content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn"}

    (v,) = [
        v
        for v in c.run_critics(_all(p), {"exercises": [], "total_sets": 0}, invoke=invoke, model_allowed=True)
        if v["critic"] == "joints_tendons"
    ]
    assert v["verdict"] == "approve" and "discarded" in (v["discarded"] or "")


def _all(joints_packet):
    empty = {"numbers": {}, "flags": [], "unknown": [], "violations": []}
    return {
        "muscle_defense": {**empty, "critic": "muscle_defense"},
        "joints_tendons": joints_packet,
        "rate_advocate": {**empty, "critic": "rate_advocate"},
        "blueprint_historian": {**empty, "critic": "blueprint_historian"},
    }


# ── the thresholds are his ─────────────────────────────────────────────────────────
def test_no_loaded_streak_length_flags_since_4161():
    """#4161 (owner-approved red team, 2026-09-24): the rest-day ask and the upper-tail line are
    RETIRED — a loaded-day count is not a validated fatigue signal. At every length, including one
    past his 2024–25 record, the streak is carried in `numbers` and flags nothing. Mutation
    control: restore a streak flag in `build_joints_packet` and the 7- and 10-day cases red."""
    assert not hasattr(ts, "loaded_streak_flag") and not hasattr(ts, "REST_ASK_AT_STREAK")
    for loaded in (0, 4, 5, 6, 7, 10):
        p = _joints(30, loaded)
        assert p["numbers"]["loaded_lifting_streak"] == loaded
        assert [f for f in p["flags"] if "streak" in f["metric"]] == [], loaded


def test_the_recorded_calibration_is_internally_consistent():
    lengths = ts.CALIBRATION["loaded_streak_lengths"]
    assert sum(lengths.values()) == ts.CALIBRATION["loaded_streaks_n"] == 59
    assert max(lengths) == ts.CALIBRATION["loaded_streak_max"] == 6
    assert sum(k * v for k, v in lengths.items()) == ts.CALIBRATION["loaded_days"] == 146


def test_unknown_streaks_are_unknown_not_zero():
    p = _joints(None, None)
    assert {"active_day_streak", "loaded_lifting_streak"} <= set(p["unknown"])
    assert ts.streaks(None, [], TARGET)["loaded_lifting_streak"] is None


# ── the predicate ──────────────────────────────────────────────────────────────────
def test_an_engine_day_breaks_the_loaded_streak_and_a_warm_up_is_not_load():
    """Mutation control: drop the cardio-modality skip in `is_loaded_session` — a treadmill
    set carrying a weight would make an Engine day a lift."""
    assert ts.is_loaded_session(_lift("2026-10-01"))
    assert not ts.is_loaded_session(_engine("2026-10-01"))
    assert not ts.is_loaded_session({"exercises": [{"name": "Treadmill", "sets": [{"weight_kg": 10, "duration_sec": 600}]}]})
    assert not ts.is_loaded_session({"exercises": [{"name": "Squat (Barbell)", "sets": [{"type": "warmup", "weight_kg": 40, "reps": 8}]}]})
    assert ts.is_loaded_session(
        {"exercises": [{"name": "Squat (Barbell)", "sets": [{"set_type": "normal", "weight_lbs": 135, "reps": 5}]}]}
    )


def test_the_live_week_replays_sixteen_as_one_loaded_day():
    """The live record (09-08..09-22): the old any-session count for a 09-23 plan was 16 (15 in
    this fixture, which starts on 09-08 — hence the declared floor); the loaded streak is 1,
    because 09-21 was an Engine day."""
    hevy = json.loads((FIX / "hevy_2026-09-08_22.json").read_text())
    strava = json.loads((FIX / "strava_2026-09-08_22.json").read_text())
    any_session = ts.streak_before({h["date"] for h in hevy}, "2026-09-23")
    s = ts.streaks(hevy, strava, "2026-09-23", window_start="2026-09-08")
    assert any_session == 15 and s["active_day_streak"] == 15 and s["active_is_floor"] is True
    assert s["loaded_lifting_streak"] == 1 and s["loaded_is_floor"] is False


def test_the_evidence_gatherer_reads_load_from_the_sanctioned_hevy_path():
    """Mutation control: build the streak from `_workout_dates` (dates only) — the loaded
    streak cannot be computed and reads the any-session count again."""
    hevy, strava = _sixteen_active_four_loaded()
    raw = [{"sk": f"DATE#{h['date']}#WORKOUT#{i}", **h} for i, h in enumerate(hevy)]
    with (
        patch("mcp.tools_strength._read_hevy_all_phases", return_value=(raw, ["experiment"])),
        patch("mcp.core.query_source_range", return_value=strava),
    ):
        out = tp._training_streaks(TARGET)
    assert out["active_day_streak"] == 16 and out["loaded_lifting_streak"] == 4
    assert "no rest-day ask" in out["loaded_streak_role"]  # #4161: context only
