"""tests/test_coach_packet_lift_history_5501.py — the session packet carries per-lift history (#5501, option (a)).

The PR #5500 eval read the coach chat calling `get_coach_session_packet` first in every real planning conversation
and `get_exercise_history` in none. Option (a): the packet carries the history for the day's programmed lifts and the
pre-flight contract counts a packet call that carried it. Each test names the mutation that reds it.

Fixtures are wire-shaped (PUBLIC repo — tool names, dates and set numbers only, no journal text, no real note):
  * Hevy rows in the per-workout shape `USER#matthew#SOURCE#hevy` / `DATE#<day>#WORKOUT#<id>` the writer puts and
    `tools_strength._read_hevy_all_phases` returns, read through the REAL `tool_get_exercise_history`;
  * training-notes rows in the `USER#matthew#SOURCE#training_notes#EXERCISE#<tid>` shape, read through the REAL
    `tool_get_exercise_notes` (only the table query and the layer-health read are stubbed);
  * the program session as `draft_custom_session.resolve_program_session` returns it (exposures with template ids).
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import coach_packet_lift_history as clh  # noqa: E402

TARGET = "2026-10-20"
BENCH, ROW, OFF_PROGRAM = "AAAA1111", "BBBB2222", "CCCC3333"
PLACEHOLDER_NOTE = "placeholder note text"


def _ex(tid: str, name: str, sets: list[tuple[float, int]], notes: str = "") -> dict:
    return {
        "name": name,
        "template_id": tid,
        "notes": notes,
        "sets": [{"type": "normal", "weight_kg": kg, "reps": reps, "rpe": None, "duration_sec": None} for kg, reps in sets],
    }


def _workout(day: str, wid: str, exercises: list[dict]) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#{wid}",
        "date": day,
        "title": "Upper",
        "start_time": f"{day}T15:00:00+00:00",
        "end_time": f"{day}T16:00:00+00:00",
        "duration_sec": 3600,
        "phase": "experiment",
        "exercises": exercises,
    }


HEVY_ROWS = [
    _workout("2026-09-29", "w1", [_ex(BENCH, "Bench Press (Barbell)", [(60.0, 8), (60.0, 8)]), _ex(OFF_PROGRAM, "Curl", [(10.0, 12)])]),
    _workout("2026-10-06", "w2", [_ex(BENCH, "Bench Press (Barbell)", [(62.5, 8), (62.5, 7)]), _ex(ROW, "Row (Cable)", [(50.0, 10)])]),
    _workout("2026-10-13", "w3", [_ex(BENCH, "Bench Press (Barbell)", [(65.0, 6), (62.5, 8)], notes=PLACEHOLDER_NOTE)]),
    _workout(
        "2026-10-17",
        "w4",
        [_ex(BENCH, "Bench Press (Barbell)", [(65.0, 8), (65.0, 7), (60.0, 10)]), _ex(OFF_PROGRAM, "Curl", [(12.0, 10)])],
    ),
]

PLANNED = {
    "date": TARGET,
    "source": "session_sequence",
    "session_role": "upper_heavy",
    "position_label": "W3 S1",
    "prescription": {
        "role_label": "Upper — heavy",
        "exposures": [
            {"kind": "anchor", "pattern": "horizontal_press", "intensity": "heavy", "movement_key": "barbell_bench", "template_id": BENCH},
            {"kind": "anchor", "pattern": "horizontal_pull", "intensity": "moderate", "movement_key": "cable_row", "template_id": ROW},
            {"kind": "accessory", "slot": "unmapped_acc", "intensity": "accessory", "movement_key": "unmapped_acc"},
        ],
    },
}

NOTE_ROWS = {
    BENCH: [
        {
            "pk": f"USER#matthew#SOURCE#training_notes#EXERCISE#{BENCH}",
            "sk": "DATE#2026-10-13#WORKOUT#w3#0",
            "date": "2026-10-13",
            "workout_uid": "w3",
            "note_raw": PLACEHOLDER_NOTE,
            "signals": [],
            "pain_flag": False,
            "sentiment": "neutral",
        }
    ]
}


class _Table:
    def query(self, **kw):
        pk_cond = kw["KeyConditionExpression"].get_expression()["values"][0]  # Key("pk").eq(...) & Key("sk").gte(...)
        tid = str(pk_cond.get_expression()["values"][1]).rsplit("#", 1)[-1]
        return {"Items": [dict(r) for r in NOTE_ROWS.get(tid, [])]}


@pytest.fixture
def wire(monkeypatch):
    """Stub only the I/O seams; the history and notes tools run for real."""
    from training import training_notes

    from mcp import draft_custom_session, plan_hevy_windows, tools_strength, tools_training_notes

    reads: list[tuple[str, str]] = []

    def hevy_read(source, start, end):
        reads.append((start, end))
        return [r for r in HEVY_ROWS if start <= r["date"] <= end]

    monkeypatch.setattr(tools_strength, "query_source_cross_phase", hevy_read)
    monkeypatch.setattr(tools_strength, "template_alias_map", lambda: ({}, {"state": "stubbed in test"}))  # no S3 read
    monkeypatch.setattr(plan_hevy_windows, "_block_workouts", lambda d: [])
    monkeypatch.setattr(
        draft_custom_session, "resolve_program_session", lambda d, rows, deload_records=None: json.loads(json.dumps(PLANNED))
    )
    monkeypatch.setattr(clh, "_catalog", lambda: {})
    monkeypatch.setattr(tools_training_notes, "table", _Table())
    monkeypatch.setattr(training_notes, "training_notes_health", lambda table: {"checked": True, "extractor_dark": False, "degraded": 0})
    return reads


def _by_tid(value: dict) -> dict:
    return {r.get("template_id"): r for r in value["lifts"]}


def test_the_packet_carries_history_for_the_programmed_lifts_and_nothing_for_the_rest(wire):
    """Mutation: read history for every lift in the Hevy record instead of the prescription's, or drop a programmed lift."""
    value, status = clh.lift_history(TARGET)
    assert status["state"] == "measured"
    lifts = _by_tid(value)
    assert set(lifts) == {BENCH, ROW, None}  # the unmapped accessory is carried as such, never guessed
    assert OFF_PROGRAM not in json.dumps(value)  # performed in the window, not programmed today -> not on the packet
    bench = lifts[BENCH]["history"]
    assert bench["state"] == "measured" and bench["sessions_in_window"] == 4
    assert [s["date"] for s in bench["sessions"]] == ["2026-10-17", "2026-10-13", "2026-10-06"]  # newest 3
    assert [s["weekday"] for s in bench["sessions"]] == ["Sat", "Tue", "Tue"]
    top = bench["sessions"][0]["top_set"]
    assert top["reps"] == 8 and round(top["weight_lbs"]) == 143  # 65 kg x 8, the heaviest set's own reps
    assert bench["sessions"][0]["working_sets"] == 3
    assert bench["sessions"][1]["note"] == PLACEHOLDER_NOTE
    assert lifts[ROW]["history"]["sessions_in_window"] == 1
    assert lifts[None]["history"] == {"state": "no_template_id"}
    notes = lifts[BENCH]["notes"]
    assert notes["state"] == "measured" and notes["latest"]["date"] == "2026-10-13" and notes["pain_flag_any"] is False
    assert lifts[ROW]["notes"]["state"] == "absent"
    assert value["session"]["session_role"] == "upper_heavy" and value["session"]["weekday"] == "Tue"


def test_n_lifts_are_one_hevy_read(wire):
    """Mutation: drop the plan_call_scope HEVY_ALL_PHASES memo — every lift re-reads the Hevy partition."""
    clh.lift_history(TARGET)
    assert len(wire) == 1, wire


def test_a_broken_history_reader_is_read_failed_never_an_empty_history(wire, monkeypatch):
    """MUTATION CONTROL: break the history reader; the field must say read_failed by name, never measured or absent."""
    from mcp import tools_strength

    def broken(source, start, end):
        raise RuntimeError("hevy partition unreadable")

    monkeypatch.setattr(tools_strength, "query_source_cross_phase", broken)
    value, status = clh.lift_history(TARGET)
    assert status["state"] == "read_failed"
    for tid in (BENCH, ROW):
        h = _by_tid(value)[tid]["history"]
        assert h["state"] == "read_failed" and "RuntimeError" in h["error"]


def test_a_day_that_is_not_a_program_session_is_absent_with_no_lifts(wire, monkeypatch):
    from mcp import draft_custom_session

    monkeypatch.setattr(draft_custom_session, "resolve_program_session", lambda d, rows, deload_records=None: None)
    value, status = clh.lift_history(TARGET)
    assert status["state"] == "absent" and value["lifts"] == []


def test_an_unreadable_block_record_raises_so_the_packet_says_read_failed(wire, monkeypatch):
    """Mutation: swallow the block-read failure into 'no programmed lift' (absent)."""
    from mcp import plan_hevy_windows, tools_coach_packet as pkt

    def broken(d):
        raise RuntimeError("block read failed")

    monkeypatch.setattr(plan_hevy_windows, "_block_workouts", broken)
    value, status = pkt._wrap(pkt._lift_history)(TARGET)
    assert value is None and status["state"] == "read_failed"


def test_the_packet_size_is_capped(wire, monkeypatch):
    """Mutation: drop the lift / session / note caps — the worst case blows the stated byte bound."""
    from mcp import draft_custom_session

    long_note = "x" * 5000
    many = [_ex(f"{i:08X}", f"Lift {i}", [(40.0 + j, 8) for j in range(6)], notes=long_note) for i in range(14)]
    rows = [_workout(f"2026-10-{d:02d}", f"m{d}", many) for d in range(1, 19)]
    from mcp import tools_strength

    monkeypatch.setattr(tools_strength, "query_source_cross_phase", lambda s, a, b: [r for r in rows if a <= r["date"] <= b])
    planned = json.loads(json.dumps(PLANNED))
    planned["prescription"]["exposures"] = [
        {"kind": "accessory", "movement_key": f"k{i}", "template_id": f"{i:08X}", "intensity": "accessory"} for i in range(14)
    ]
    monkeypatch.setattr(draft_custom_session, "resolve_program_session", lambda d, r, deload_records=None: planned)
    value, status = clh.lift_history(TARGET)
    assert status["state"] == "measured"
    assert len(value["lifts"]) == clh.LIFT_HISTORY_MAX_LIFTS and value["lifts_dropped_by_cap"] == 4
    assert all(len(r["history"]["sessions"]) == clh.LIFT_HISTORY_SESSIONS_PER_LIFT for r in value["lifts"])
    assert all(len(s["note"]) <= clh.LIFT_HISTORY_NOTE_CHARS for r in value["lifts"] for s in r["history"]["sessions"])
    size = len(json.dumps(value, default=str))
    assert size < clh.LIFT_HISTORY_MAX_BYTES, size


def test_the_packet_field_is_registered_with_its_source():
    from mcp import tools_coach_packet as pkt

    assert "lift_history" in pkt.SOURCES and pkt.READERS["lift_history"] is pkt._lift_history
    assert "lift_history" in pkt.COACH_PACKET_DESCRIPTION


# ── the order contract: a packet call that CARRIED lift_history satisfies the exercise members ──
def test_a_packet_call_carrying_lift_history_satisfies_the_exercise_pre_flight():
    """Mutation: drop PACKET_LIFT_HISTORY from PRE_FLIGHT, or let a bare packet call claim it."""
    from training import coach_context as cc

    plan = {"tool": "plan_next_session"}
    carried = [{"tool": "get_coach_session_packet", "lift_history": "measured"}, plan]
    assert cc.order_violations(carried) == []
    assert cc.order_violations([{"tool": "get_coach_session_packet", "lift_history": "absent"}, plan]) == []
    for not_carried in (
        {"tool": "get_coach_session_packet"},
        "get_coach_session_packet",
        {"tool": "get_coach_session_packet", "lift_history": "read_failed"},
    ):
        v = cc.order_violations([not_carried, plan])
        assert [x["code"] for x in v] == ["plan_before_preflight"] and v[0]["missing"] == ["exercise_history", "exercise_notes"]
    # the dedicated tools still satisfy the members on their own
    assert cc.order_violations(["get_coach_session_packet", "get_exercise_history", "get_exercise_notes", plan]) == []


def test_the_eval_counts_a_packet_call_carrying_history_and_leaves_the_captured_fixtures_unchanged():
    """The eval's definition follows the contract: the real fixtures (captured before #5501, no lift_history record) score
    exactly as on main; the projection (each packet call marked as carrying it) reads no violation in any AFTER row."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "coach_transcript_eval_5071.py"
    spec = importlib.util.spec_from_file_location("coach_transcript_eval_5071", path)
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)

    rows = ev.evaluate_real(ev.load_fixtures(), ev.load_fixtures(ev.AFTER_DIR), projected=True)
    s = ev.summarize(rows)
    assert (s["before"]["with_violations"], s["before"]["context_sources_reached"]) == (3, "0/15")
    assert (s["after"]["with_violations"], s["after"]["context_sources_reached"]) == (4, "13/20")
    assert s["after"]["per_member"]["exercise_history"] == 0 and s["after"]["per_member"]["exercise_notes"] == 1
    p = s[ev.PROJECTED]
    assert (p["conversations"], p["with_violations"], p["context_sources_reached"]) == (4, 0, "20/20")
    assert all(r["phase"] == ev.PROJECTED for r in rows[-4:])
    # to_contract still inserts the dedicated tools, never the pseudo-token
    synth = ev.to_contract(["plan_next_session"])
    assert [c["tool"] for c in synth[:-1]] == ["get_exercise_history", "get_exercise_notes", "get_coach_session_packet"]
