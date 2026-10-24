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
    """#5146: all three charter triggers have a producer — `triggers_unwired` is empty. A copy built without the
    event reads (the session-sequence copy) says so on `event_signals.read`, never implying they were watched."""
    rec = deload_word.recommendation(day="2026-11-04", records=[])
    assert rec["triggers_wired"] == ["rpe_drift", "recovery", "event_signals"]
    assert rec["triggers_unwired"] == []
    assert rec["event_signals"]["read"] is False
    # control: the stage-1 builder reads them, and the block says it did
    block = plan_engine.constraint_block(date="2026-11-04", block_workouts=_rows(41), deload_records=[])
    assert block["deload_recommendation"]["event_signals"]["read"] is True
    assert block["deload_recommendation"]["triggers_unwired"] == []


# ── #5146: the event signals (the issue's Set: sick-day store, deficit tool recommendation, charter travel window) ──
# Real shapes: a SOURCE#sick_days row as `manage_sick_days action=list` returns it (d2f'd; the live 2026-10-10 row's
# keys, with a neutral reason), and `get_deficit_sustainability`'s return keys (period, degraded_count, channels,
# severity, recommendation — the WARNING line verbatim from mcp/tools_nutrition.py).
SICK_ROW = {
    "pk": "USER#matthew#SOURCE#sick_days",
    "sk": "DATE#2026-11-02",
    "date": "2026-11-02",
    "logged_at": "2026-11-03T02:22:35.496774+00:00",
    "schema_version": 1.0,
    "reason": "head cold — clinical detail stays off the packet",
}
_CHANNELS = [
    {"name": n, "status": st, "direction": "declining" if st == "degraded" else "stable"}
    for n, st in (
        ("HRV", "degraded"),
        ("Sleep Quality", "degraded"),
        ("Recovery", "degraded"),
        ("Habit Completion", "stable"),
        ("Training Output", "stable"),
    )
]
WARNING = {
    "period": {"start_date": "2026-10-20", "end_date": "2026-11-02", "days": 14, "days_with_data": 14},
    "deficit": {"in_deficit": True, "avg_intake_kcal": 1690, "estimated_tdee": 2840, "deficit_kcal": 1150},
    "channels": _CHANNELS,
    "degraded_count": 3,
    "severity": "WARNING",
    "recommendation": "3 channels degrading under 1150 kcal/day deficit. Consider adding 200 kcal/day for 3-5 days and scheduling a deload.",
}
MEASURED = {"state": "measured"}


def _events(**kw):
    base = {"sick_days": [], "deficit": None, "status": {"sick_days": MEASURED, "deficit": {"state": "absent"}}}
    base.update(kw)
    return base


def test_a_sick_day_in_the_window_is_a_reason_and_cuts_nothing():
    rows = _rows(41)
    block = plan_engine.constraint_block(
        date="2026-11-04", block_workouts=rows, deload_records=[], event_inputs=_events(sick_days=[SICK_ROW])
    )
    rec = block["deload_recommendation"]
    assert rec["active"] is True and rec["applied"] is False and rec["applied_on"] is None
    assert rec["reasons"] == ["sick day logged 2026-11-02 — inside the 7 days through 2026-11-04 (manage_sick_days)"]
    assert "head cold" not in str(rec), "the row's free-text reason is never echoed onto the packet"
    assert rec["event_signals"]["sources"]["sick_days"]["dates"] == ["2026-11-02"]
    # never a cut: the session is whole, the same size as with no signal at all
    calm = plan_engine.constraint_block(date="2026-11-04", block_workouts=rows, deload_records=[], event_inputs=_events())
    assert calm["deload_recommendation"]["active"] is False and calm["deload_recommendation"]["reasons"] == []
    assert block["session"]["deload"] is False and block["session"]["prescription"]["deload_trim"] is None
    assert block["session"]["prescription"]["total_sets"] == calm["session"]["prescription"]["total_sets"]
    assert block["session"]["deload_recommendation"] == rec


def test_a_sick_day_outside_the_window_or_cleared_is_no_reason():
    """MUTATION CONTROLS — the lookback edge (day - 7 counts, day - 8 does not) and a #4378 tombstone."""
    edge = {**SICK_ROW, "sk": "DATE#2026-10-28", "date": "2026-10-28"}
    old = {**SICK_ROW, "sk": "DATE#2026-10-27", "date": "2026-10-27"}
    cleared = {**SICK_ROW, "cleared_at": "2026-11-03T05:00:00+00:00", "cleared_reason": "logged_in_error"}
    assert deload_word.event_signals("2026-11-04", sick_days=[edge])["reasons"]
    assert deload_word.event_signals("2026-11-04", sick_days=[old])["reasons"] == []
    assert deload_word.event_signals("2026-11-04", sick_days=[cleared])["reasons"] == []
    two = deload_word.event_signals("2026-11-04", sick_days=[SICK_ROW, edge])
    assert two["reasons"] == ["sick days logged 2026-10-28, 2026-11-02 — inside the 7 days through 2026-11-04 (manage_sick_days)"]


def test_the_deficit_warning_and_critical_bands_are_reasons_with_the_tools_own_line():
    warn = deload_word.event_signals("2026-11-04", deficit=WARNING, status={"deficit": MEASURED})
    assert warn["reasons"] == [
        "deficit sustainability WARNING (3 of 5 channels degrading, 2026-10-20..2026-11-02): "
        + WARNING["recommendation"]
        + " (get_deficit_sustainability)"
    ]
    critical = {
        **WARNING,
        "severity": "CRITICAL",
        "degraded_count": 4,
        "recommendation": "4+ channels degrading under 1150 kcal/day deficit.",
    }
    assert deload_word.event_signals("2026-11-04", deficit=critical)["reasons"][0].startswith("deficit sustainability CRITICAL (4 of 5")
    # MUTATION CONTROL: the bands below WARNING recommend nothing to the training load
    for sev in ("WATCH", "SUSTAINABLE", "NOT_IN_DEFICIT"):
        assert deload_word.event_signals("2026-11-04", deficit={**WARNING, "severity": sev})["reasons"] == [], sev
    block = plan_engine.constraint_block(
        date="2026-11-04", block_workouts=_rows(41), deload_records=[], event_inputs=_events(deficit=WARNING)
    )
    assert block["deload_recommendation"]["active"] is True and block["session"]["deload"] is False


def test_a_dated_travel_window_is_a_reason_and_a_pending_one_is_listed_only():
    win = [{"label": "late December 2026", "start": "2026-12-22", "end": "2026-12-30", "templates": "#5088"}]
    near = deload_word.event_signals("2026-12-20", travel_windows=win)  # inside the charter's 3-day travel lead
    assert near["reasons"] == ["travel window late December 2026 (2026-12-22..2026-12-30) — the charter travel window (#5088)"]
    assert deload_word.event_signals("2026-12-18", travel_windows=win)["reasons"] == []  # MUTATION CONTROL: outside the lead
    assert deload_word.event_signals("2026-12-31", travel_windows=win)["reasons"] == []  # after the window
    pending = deload_word.event_signals("2026-12-24", travel_windows=[{"label": "late December 2026", "start": None, "end": None}])
    assert pending["reasons"] == [] and pending["sources"]["travel"]["pending_windows"] == ["late December 2026: dates pending the owner"]


def test_an_unread_event_source_is_named_never_read_as_no_event():
    failed = {"state": "read_failed", "error": "ClientError: throttled"}
    ev = deload_word.event_signals("2026-11-04", sick_days=None, deficit=None, status={"sick_days": failed})
    assert ev["reasons"] == [] and ev["unread"] == ["sick_days", "deficit"]
    assert ev["sources"]["sick_days"]["error"] == "ClientError: throttled" and ev["sources"]["deficit"]["state"] == "not_read"


def test_the_stage_1_reads_feed_the_engine(monkeypatch):
    """`mcp.plan_event_reads.read` through `tools_plan._read`: the list tool's rows and the deficit tool's return reach
    `event_inputs`; the tool's own <7-day refusal is ABSENT, not read_failed; the deficit tool is called once."""
    from mcp import plan_event_reads, tools_plan

    with (
        patch("mcp.tools_sick_days._get_sick_days", return_value={"sick_days": [SICK_ROW], "count": 1, "dates": ["2026-11-02"]}) as sick,
        patch("mcp.tools_nutrition.tool_get_deficit_sustainability", return_value=WARNING) as tool,
    ):
        inputs, raw = plan_event_reads.read("2026-11-04", tools_plan._read)
    assert sick.call_args[0][0] == {"start_date": "2026-10-28", "end_date": "2026-11-04"}
    assert tool.call_count == 1 and tool.call_args[0][0] == {"critics_model": False} and raw is WARNING
    assert inputs["sick_days"] == [SICK_ROW] and inputs["deficit"] is WARNING
    assert {k: v["state"] for k, v in inputs["status"].items()} == {"sick_days": "measured", "deficit": "measured"}
    assert len(deload_word.event_signals("2026-11-04", **inputs)["reasons"]) == 2
    refusal = {"error": "Need ≥7 days of MacroFactor data. Found 4."}
    with (
        patch("mcp.tools_sick_days._get_sick_days", return_value={"error": "throttled"}),
        patch("mcp.tools_nutrition.tool_get_deficit_sustainability", return_value=refusal),
    ):
        inputs, raw = plan_event_reads.read("2026-11-04", tools_plan._read)
    assert inputs["status"]["deficit"]["state"] == "absent" and raw is refusal
    assert inputs["status"]["sick_days"]["state"] == "read_failed" and inputs["sick_days"] is None


def test_stage_1_carries_the_event_reasons_and_calls_the_deficit_tool_once(monkeypatch):
    """End to end through `plan_next_session` stage 1 (the #4072 harness's live-shape reader stubs): a sick day and the
    deficit WARNING land in `constraint_block.deload_recommendation.reasons`; nothing is applied; the deficit tool's one
    return is the one `nutrition_critics` is built from."""
    from tests import test_plan_input_read_state_4072 as h

    monkeypatch.setattr(h.tp, "pacific_today", lambda: h.TODAY)
    h._wire(monkeypatch, [])
    row = {**SICK_ROW, "sk": "DATE#2026-09-21", "date": "2026-09-21"}
    listed = {"sick_days": [row], "count": 1, "dates": ["2026-09-21"]}
    critics = MagicMock(return_value={"verdicts": []})
    with patch("mcp.tools_nutrition.tool_get_deficit_sustainability", return_value=WARNING) as tool:
        out = h._stage1(
            **{"mcp.tools_sick_days._get_sick_days": {"return_value": listed}, "mcp.tools_plan._nutrition_critics_block": {"new": critics}}
        )
    rec = out["constraint_block"]["deload_recommendation"]
    assert rec["triggers_unwired"] == [] and rec["applied"] is False
    assert "sick day logged 2026-09-21 — inside the 7 days through 2026-09-22 (manage_sick_days)" in rec["reasons"]
    assert any(r.startswith("deficit sustainability WARNING") for r in rec["reasons"])
    assert out["constraint_block"]["session"].get("deload") in (False, None)
    assert tool.call_count == 1 and critics.call_args[0][0] is WARNING


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
