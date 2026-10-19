"""tests/test_deload_owner_gated_5070.py — the deload is the owner's call (#5070).

Owner ruling 2026-10-18: "No scheduled or automatic deload. Fatigue signals become a recommendation; a deload
happens only on the owner's recorded word." Each rule has a fixture and a mutation control.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.pacific_time import shift_day_key  # noqa: E402
from training import deload_word, plan_engine, program_structure, session_sequence  # noqa: E402

START = "2026-09-24"
WORD = {"sk": "DELOAD#2026-11-04", "start_date": "2026-11-04", "days": 7, "sets_pct": -40, "loads": "held", "words": "deload this week"}
FATIGUE = {"triggered": True, "reasons": ["readiness below the floor on 3 consecutive days (>= 2)"], "unknown": []}


def _lift(day: str) -> dict:
    return {
        "date": day,
        "sk": f"DATE#{day}#WORKOUT#{day}",
        "source_workout_id": day,
        "exercises": [
            {"name": "Linear Leg Press", "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]},
            {"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 5}]},
        ],
    }


def _rows(n: int) -> list[dict]:
    return [_lift(shift_day_key(START, i)) for i in range(n)]


def test_signals_without_a_word_recommend_and_cut_nothing():
    rows = _rows(41)
    block = plan_engine.constraint_block(
        date="2026-11-04", block_workouts=rows, fatigue=FATIGUE, readiness_low_streak_days=3, deload_records=[]
    )
    rec = block["deload_recommendation"]
    assert rec["active"] is True and rec["reasons"] == FATIGUE["reasons"]
    assert rec["applied"] is False and rec["applied_on"] is None
    assert rec["proposed_response"] == {"sets_pct": -40, "days": 7, "loads": "held"}
    assert block["session"]["deload"] is False and block["session"]["prescription"]["deload_trim"] is None
    assert block["session"]["deload_recommendation"] == rec
    # control: the same session with no signal is whole too, and says nothing is argued
    calm = plan_engine.constraint_block(date="2026-11-04", block_workouts=rows, deload_records=[])
    assert calm["deload_recommendation"]["active"] is False and calm["deload_recommendation"]["reasons"] == []
    assert calm["session"]["prescription"]["total_sets"] == block["session"]["prescription"]["total_sets"]


def test_the_recorded_word_applies_the_cut_as_written():
    rows = _rows(41)
    block = plan_engine.constraint_block(date="2026-11-04", block_workouts=rows, fatigue=FATIGUE, deload_records=[WORD])
    rec = block["deload_recommendation"]
    assert rec["applied"] is True and rec["applied_on"]["words"] == "deload this week"
    session = block["session"]
    assert session["deload"] is True and session["prescription"]["deload_trim"]["pct"] == -40
    assert session["prescription"]["deload_trim"]["loads"] == "held"
    plain = plan_engine.constraint_block(date="2026-11-04", block_workouts=rows, deload_records=[])
    assert session["prescription"]["total_sets"] < plain["session"]["prescription"]["total_sets"]


def test_week_6_and_the_old_lock_date_fire_nothing_without_a_record():
    for day, n in (("2026-10-29", 35), ("2026-11-04", 41), ("2026-11-05", 42)):
        b = plan_engine.constraint_block(date=day, block_workouts=_rows(n), deload_records=[])
        assert b["session"]["deload"] is False and b["deload_recommendation"]["applied"] is False, day
    # an expired record covers nothing either
    assert deload_word.active_record([WORD], "2026-11-11") is None and deload_word.active_record([WORD], "2026-11-03") is None


def test_pain_note_counts_only_while_the_flag_is_tripped():
    rows = _rows(10)
    tripped = plan_engine.constraint_block(
        date="2026-10-04",
        block_workouts=rows,
        pain_flag_sites=["Squat (Barbell)"],
        pain_layer_status="healthy",
        pain_evidence_scope={"status": "examined"},
        deload_records=[],
    )
    reasons = tripped["deload_recommendation"]["reasons"]
    clear = plan_engine.constraint_block(date="2026-10-04", block_workouts=rows, deload_records=[])
    assert clear["deload_recommendation"]["reasons"] == []
    assert reasons == ["pain/soreness note on a drafted lift: Squat (Barbell)"]


def test_an_unread_record_store_is_stated_not_taken_as_no_word():
    b = plan_engine.constraint_block(
        date="2026-11-04",
        block_workouts=_rows(41),
        deload_records=None,
        input_status={"deload_records": {"state": "read_failed", "error": "X"}},
    )
    assert b["deload_recommendation"]["records_state"] == "read_failed" and b["deload_recommendation"]["records_read"] is False
    assert b["session"]["deload"] is False, "an unreadable store never cuts a session"


def test_the_predraft_session_carries_the_recommendation_key():
    import inspect

    from mcp import nightly_predraft as npd

    assert '"deload_recommendation"' in inspect.getsource(npd.run)
    with (
        patch.object(npd, "_block_record", return_value=_rows(41)),
        patch.object(deload_word, "load_records_failsoft", return_value=[WORD]),
        patch("mcp.plan_helpers._catalog_and_ceiling", return_value=({}, 2)),
    ):
        s = npd.scheduled_session("2026-11-04")
    assert s["deload"] is True and s["deload_recommendation"]["applied"] is True


def test_the_record_shape_validates():
    rec = deload_word.build_deload_record(start_date="2026-11-04", words="  deload this week ", recorded_at="2026-11-04T00:00:00Z")
    assert (rec["sk"], rec["days"], rec["sets_pct"], rec["loads"], rec["words"]) == (
        "DELOAD#2026-11-04",
        7,
        -40,
        "held",
        "deload this week",
    )
    for bad in (
        {"start_date": "2026-11-04", "words": ""},
        {"start_date": "nope", "words": "x"},
        {"start_date": "2026-11-04", "words": "x", "days": 30},
        {"start_date": "2026-11-04", "words": "x", "sets_pct": 10},
    ):
        with pytest.raises(ValueError):
            deload_word.build_deload_record(recorded_at="t", **bad)


def test_the_chat_writer_records_the_word_and_refuses_a_blank_one():
    from mcp import tools_training_notes as tn

    fake = MagicMock()
    with patch.object(tn, "table", fake):
        refused = tn.tool_get_exercise_notes({"action": "deload", "words": ""})
        assert refused["wrote"] is False and "words" in refused["error"] and not fake.put_item.called
        ok = tn.tool_get_exercise_notes({"action": "deload", "start_date": "2026-11-04", "words": "take the week lighter"})
    assert ok["wrote"] is True and ok["sk"] == "DELOAD#2026-11-04"
    item = fake.put_item.call_args.kwargs["Item"]
    assert item["pk"] == deload_word.DELOAD_PK == "USER#matthew#SOURCE#training_constraints"
    assert item["words"] == "take the week lighter" and item["sets_pct"] == -40 and item["days"] == 7
    assert deload_word.DELOAD_SK_PREFIX == "DELOAD#" and not deload_word.DELOAD_SK_PREFIX.startswith("DISMISSAL")


def test_the_policy_reads_the_charter_and_the_schedule_is_gone():
    pol = deload_word.policy()
    assert (pol["scheduled"], pol["automatic"], pol["owner_gated"]) == (False, False, True)
    assert "rpe_drift" in pol["recommendation_triggers"]
    cfg = session_sequence.deload_cfg()
    assert cfg["scheduled"] is False and cfg["sets_pct"] == -40
    assert not hasattr(program_structure, "DELOAD_RULE"), "the scheduled-deload rule text is retired"


def test_the_packet_states_which_charter_triggers_are_wired():
    """Event signals have no producer yet (#5146) — the packet must not imply one is being watched."""
    rec = deload_word.recommendation(day="2026-11-04", records=[])
    assert rec["triggers_wired"] == ["rpe_drift", "recovery"]
    assert rec["triggers_unwired"] == ["event_signals"]
    # control: a caller that wires the extra_reasons hook moves it to wired
    hooked = deload_word.recommendation(day="2026-11-04", records=[], extra_reasons=["sick day on file"])
    assert hooked["triggers_unwired"] == [] and "event_signals" in hooked["triggers_wired"]


def test_the_generator_takes_the_records_as_an_input_not_a_ddb_read():
    from training import routine_generator

    with patch.object(deload_word, "load_records_failsoft", side_effect=AssertionError("must not read when injected")):
        with patch.object(session_sequence, "next_session", return_value=None) as ns:
            routine_generator._schedule_entry_for_date("2026-11-04", {"schedule": {}}, "module", [], [])
    assert ns.call_args[0][2] == []
    # control: not injected -> the one fail-soft read happens here
    with patch.object(deload_word, "load_records_failsoft", return_value=[{"x": 1}]) as rd:
        with patch.object(session_sequence, "next_session", return_value=None) as ns:
            routine_generator._schedule_entry_for_date("2026-11-04", {"schedule": {}}, "module", [])
    assert rd.called and ns.call_args[0][2] == [{"x": 1}]
