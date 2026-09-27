"""tests/test_coach_session_packet_4082.py — ONE read of the coaching input packet (#4082).

The owner's eight chat sessions (2026-09-14 .. 09-22) each re-verified the same inputs over
10+ calls. `get_coach_session_packet` returns them together. Two properties matter and each
test below names the mutation that reds it:

  * NO SECOND DERIVATION — every number is the owning function's, passed through. The AST
    guard reds if the module imports a counting/estimating primitive, and the pass-through
    tests red if a field is recomputed instead of carried.
  * THREE READ STATES — every field is measured / absent / read_failed, and a broken read is
    never shown as an empty one.

Hevy rows are the #4068 fixture: field-projected copies of live `USER#matthew#SOURCE#hevy`
per-workout rows (the wire, not a hand-built shape).
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.pacific_time import shift_day_key  # noqa: E402

from mcp import tools_coach_packet as pkt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEVY_FIX = Path(__file__).parent / "fixtures" / "shared_quantities_4068" / "hevy_2026-09-08_22.json"
# #4311 — field-projected copies of the live `USER#matthew#SOURCE#hevy` per-workout rows and the
# `USER#matthew#SOURCE#strava` day rows for 2026-09-18..26 (read 2026-09-26): the Flex session, the
# Garmin walk (Strava 20343117320) and the six WHOOP walks recorded inside Hevy sessions 19-25 Sep.
TODAY_FIX = Path(__file__).parent / "fixtures" / "coach_packet_today_4311"
STATES = {"measured", "absent", "read_failed"}
# #4189: a stored morning-note row exactly as the write door puts it (tests/test_e2e_write_paths.py holds the wire).
MORNING_NOTE_ROW = {
    "pk": "USER#matthew#SOURCE#morning_note",
    "sk": "MORNING_NOTE#2026-09-23",
    "date": "2026-09-23",
    "sleep_word": "heavy",
    "body_word": "stiff",
    "mood_word": "steady",
    "felt_recovered": False,
    "written_at": "2026-09-23T12:34:56+00:00",
    "tier": 1,
    "source": "site_api_morning_note",
}


def _hevy_rows() -> list[dict]:
    return json.loads(HEVY_FIX.read_text())


def _today_hevy(day: str) -> list[dict]:
    return [w for w in json.loads((TODAY_FIX / "hevy_2026-09-18_26.json").read_text()) if w["date"] == day]


def _today_strava(day: str) -> list[dict]:
    return [r for r in json.loads((TODAY_FIX / "strava_2026-09-18_26.json").read_text()) if r["date"] == day]


@pytest.fixture
def stub_readers(monkeypatch):
    """Every upstream reader stubbed to a small live-shaped answer; tests override one at a time."""
    from mcp import tools_benchmark, tools_health, tools_nutrition, tools_plan, tools_strength

    muscles = {"Chest": {"total_sets": 6.0, "direct_sets": 6, "sets_per_week": 6.0}}
    monkeypatch.setattr(
        tools_strength,
        "tool_get_muscle_volume",
        lambda a: {
            "muscle_volume": {"Chest": {"total_sets": 20.0, "avg_sets_per_week": 5.0, "volume_landmark_status": "MEV"}},
            "trailing_windows": {"7d": {"start": "x", "muscles": muscles}, "28d": {"start": "y", "muscles": muscles}},
            "method": "m",
            "completeness": {"status": "complete"},
            "unattributed": [],
        },
    )
    monkeypatch.setattr(tools_strength, "_read_hevy_all_phases", lambda s, e: (_hevy_rows(), ["experiment"]))
    import training.routine_title as rt

    monkeypatch.setattr(rt, "_load_routine_index", lambda start: [{"target_date": "2026-09-01", "archetype": "full"}])
    monkeypatch.setattr(
        tools_nutrition,
        "tool_get_nutrition",
        lambda a: {
            "period": {"days_with_data": 2},
            "daily_averages": {"calories_kcal": 2100.0, "protein_g": 190.0},
            "target_comparison": {"protein_g": {"target": 180, "average": 190.0, "n": 2}},
            "daily_breakdown": [{"date": "2026-09-20", "calories_kcal": 2000.0, "protein_g": 200.0}],
        },
    )
    monkeypatch.setattr(tools_plan, "_protein_days_7d", lambda d: (0, 2))
    monkeypatch.setattr(
        tools_plan,
        "_walking_volume_last_7d",
        lambda d: {"total_hr": 10.07, "hr_wk": 10.07, "window": {"start": "a", "end": "b"}, "by_source": {"strava": {"status": "ok"}}},
    )
    monkeypatch.setattr(
        tools_benchmark, "_loss_rate_block", lambda d: {"rate_lb_wk": 2.1, "provisional": False, "window": {"start": "s", "end": "e"}}
    )
    monkeypatch.setattr(tools_plan, "_training_streaks", lambda d: {"active_day_streak": 9, "loaded_lifting_streak": 1})
    monkeypatch.setattr(
        tools_health, "tool_get_readiness_score", lambda a: {"readiness_score": 80.1, "label": "GREEN", "date": "2026-09-22"}
    )
    monkeypatch.setattr(
        tools_plan, "_readiness_low_streak", lambda d: (0, {"state": "measured", "threshold": 50.0, "latest_day": "2026-09-22"})
    )
    # #4189: the morning note reads through coach.morning_note (the one derivation); stub the row read.
    from coach import morning_note as mn

    monkeypatch.setattr(mn, "read_notes", lambda table, today, days=mn.DEFAULT_LOOKBACK_DAYS: [dict(MORNING_NOTE_ROW)])
    from mcp import coach_packet_today

    monkeypatch.setattr(coach_packet_today, "read_hevy_day", _today_hevy)
    monkeypatch.setattr(coach_packet_today, "read_strava_day", _today_strava)
    monkeypatch.setattr(coach_packet_today, "pacific_today", lambda: "2026-09-26")


# ── the contract: one tool, every field, three states ─────────────────────────────────
def test_registered_as_a_read_tool():
    """Mutation: drop the registry entry, or name it with a non-read verb (`coach_session_packet`
    classifies as a WRITE in mcp.audit and would be audited as a mutation)."""
    from mcp.audit import is_write_tool
    from mcp.registry import TOOLS

    assert TOOLS["get_coach_session_packet"]["fn"] is pkt.tool_get_coach_session_packet
    assert TOOLS["get_coach_session_packet"]["schema"]["inputSchema"] == pkt.COACH_PACKET_INPUT
    assert not is_write_tool("get_coach_session_packet")


def test_every_field_present_with_a_state_and_a_source(stub_readers):
    """Mutation: drop a reader from READERS, or return a field without `state`/`source`."""
    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})
    assert set(out["fields"]) == set(pkt.SOURCES) == set(pkt.READERS)
    for name, f in out["fields"].items():
        assert f["state"] in STATES, (name, f)
        assert f["source"] == pkt.SOURCES[name]
    assert out["states"] == {n: "measured" for n in pkt.SOURCES}
    assert out["not_measured"] == []


def test_a_raising_reader_is_read_failed_with_its_error_class_and_the_rest_still_read(stub_readers, monkeypatch):
    """Mutation: let one reader's raise escape (the whole packet 500s), or swallow it into an
    empty `measured`/`absent` field — the 2026-09-15..18 defect class #4072 named."""
    from mcp import tools_plan

    def boom(d):
        raise TimeoutError("hevy query timed out")

    monkeypatch.setattr(tools_plan, "_training_streaks", boom)
    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})
    f = out["fields"]["streaks"]
    assert f["state"] == "read_failed" and f["error"].startswith("TimeoutError") and f["value"] is None
    assert out["not_measured"] == ["streaks"]
    assert out["fields"]["walking_hours_7d"]["state"] == "measured"


def test_block_position_raise_is_read_failed_not_a_packet_error(stub_readers, monkeypatch):
    """Mutation: remove `_wrap` — a reader that raises outside `_read` escapes the tool."""
    from training import session_sequence

    def bad(day, workouts):
        raise ValueError("sequence unreadable")

    monkeypatch.setattr(session_sequence, "next_session", bad)
    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-26"})
    assert out["fields"]["block_position"]["state"] == "read_failed"
    assert "ValueError" in out["fields"]["block_position"]["error"]


def test_invalid_target_date_is_an_error_not_a_packet():
    out = pkt.tool_get_coach_session_packet({"target_date": "tomorrow"})
    assert "error" in out and "fields" not in out


# ── absent vs read_failed, per field ──────────────────────────────────────────────────
def test_nutrition_no_data_is_absent_and_a_shape_change_is_read_failed(stub_readers, monkeypatch):
    """Mutation: report the tool's "No MacroFactor data" as read_failed, or a summary that lost
    `daily_breakdown` as absent (a shape change is a failed read — #4072)."""
    from mcp import tools_nutrition

    monkeypatch.setattr(
        tools_nutrition, "tool_get_nutrition", lambda a: {"error": "No MacroFactor data found.", "start_date": "a", "end_date": "b"}
    )
    assert pkt._nutrition("2026-09-23")[1]["state"] == "absent"
    monkeypatch.setattr(tools_nutrition, "tool_get_nutrition", lambda a: {"period": {}, "rows": []})
    value, status = pkt._nutrition("2026-09-23")
    assert status["state"] == "read_failed" and "InputShapeError" in status["error"] and value is None


def test_walking_all_sources_unreadable_is_read_failed_and_empty_is_absent(stub_readers, monkeypatch):
    """Mutation: collapse the two None cases — an unreadable week read as 'no walking'."""
    from mcp import tools_plan

    layer = {"total_hr": None, "by_source": {"strava": {"status": "unreadable"}, "hevy": {"status": "unreadable"}}}
    monkeypatch.setattr(tools_plan, "_walking_volume_last_7d", lambda d: layer)
    assert pkt._walking("2026-09-23")[1]["state"] == "read_failed"
    layer2 = {"total_hr": None, "by_source": {"strava": {"status": "ok"}, "hevy": {"status": "ok"}}}
    monkeypatch.setattr(tools_plan, "_walking_volume_last_7d", lambda d: layer2)
    assert pkt._walking("2026-09-23")[1]["state"] == "absent"


def test_loss_rate_block_error_branch_is_read_failed(stub_readers, monkeypatch):
    """Mutation: read `_loss_rate_block`'s except-branch (no `window`) as an absent rate."""
    from mcp import tools_benchmark

    monkeypatch.setattr(
        tools_benchmark, "_loss_rate_block", lambda d: {"rate_lb_wk": None, "provisional": True, "reason": "ClientError: x"}
    )
    assert pkt._loss_rate("2026-09-23")[1] == {"state": "read_failed", "error": "ClientError: x"}
    monkeypatch.setattr(tools_benchmark, "_loss_rate_block", lambda d: {"rate_lb_wk": None, "window": {}, "reason": "1 weigh-in"})
    assert pkt._loss_rate("2026-09-23")[1]["state"] == "absent"


def test_muscle_volume_with_no_working_set_is_absent(stub_readers, monkeypatch):
    from mcp import tools_strength

    zero = {"Chest": {"total_sets": 0.0}}
    monkeypatch.setattr(
        tools_strength,
        "tool_get_muscle_volume",
        lambda a: {"muscle_volume": {}, "trailing_windows": {"7d": {"muscles": zero}, "28d": {"muscles": zero}}},
    )
    assert pkt._muscle_volume("2026-09-23")[1]["state"] == "absent"


def test_readiness_shape_change_is_read_failed(stub_readers, monkeypatch):
    """Mutation: treat a readiness payload carrying none of the known score keys as absent —
    the exact defect that read `unknown` on a GREEN 80.1 day (2026-09-20)."""
    from mcp import tools_health

    monkeypatch.setattr(tools_health, "tool_get_readiness_score", lambda a: {"rs": 80.1})
    assert pkt._readiness("2026-09-23")[1]["state"] == "read_failed"


# ── no second derivation: the packet carries the owner's number ───────────────────────
def test_packet_carries_the_planners_own_numbers(stub_readers):
    """Mutation: recompute any of these instead of passing the owning function's value through."""
    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})["fields"]
    assert out["walking_hours_7d"]["value"]["total_hr"] == 10.07
    assert out["streaks"]["value"] == {"active_day_streak": 9, "loaded_lifting_streak": 1}
    assert out["loss_rate"]["value"]["rate_lb_wk"] == 2.1
    assert out["nutrition_7d"]["value"]["protein_days_below_floor"] == 0
    assert out["nutrition_7d"]["value"]["protein_days_measured"] == 2
    assert out["readiness"]["value"]["recovery_tier"] == "green"
    assert out["muscle_volume"]["value"]["window_7d"]["muscles"]["Chest"]["sets_per_week"] == 6.0


def test_muscle_volume_is_read_over_plan_next_sessions_window(stub_readers, monkeypatch):
    """Mutation: read a different window than the planner (the #4068 disagreement class)."""
    from mcp import tools_strength

    seen = {}
    orig = tools_strength.tool_get_muscle_volume
    monkeypatch.setattr(tools_strength, "tool_get_muscle_volume", lambda a: (seen.update(a), orig(a))[1])
    pkt._muscle_volume("2026-09-23")
    assert seen == {"start_date": "2026-08-26", "end_date": "2026-09-22"}


FORBIDDEN_PRIMITIVES = {
    "working_sets_by_muscle",  # training.muscle_volume — reached only through get_muscle_volume
    "walking_layer",
    "weekly_walking_hours",
    "build",  # walking_volume.build
    "loss_rate_from_rows",
    "_ols_slope",
    "streaks",
    "streak_before",
}


def test_derivation_guard_no_counting_primitive_is_imported():
    """Mutation: import a counting/estimating primitive into the packet (a second derivation)."""
    tree = ast.parse((ROOT / "mcp" / "tools_coach_packet.py").read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & FORBIDDEN_PRIMITIVES, imported & FORBIDDEN_PRIMITIVES
    assert not modules & {"training.walking_volume", "health.weight_trend", "mcp.shared_quantities"}


# ── last session per type: sets and notes, the type from the platform's own resolver ──
def test_last_session_by_type_is_the_newest_with_sets_and_notes(stub_readers):
    """Mutation: keep the OLDEST session per type, or drop the exercise notes/sets."""
    value = pkt._last_sessions("2026-09-23")
    rows = [r for r in _hevy_rows() if "#WORKOUT#" in r["sk"]]
    newest = max(rows, key=lambda r: (r["date"], r.get("start_time") or ""))
    full = value["by_archetype"]["full"]
    assert full["date"] == newest["date"] and full["title"] == newest["title"]
    assert full["exercises"] and all("sets" in e and "notes" in e for e in full["exercises"])
    assert value["sessions_read"] == len(rows)
    assert value["routine_index"] == {"state": "measured"}
    # 2026-09-08..22 precede the v0.4 block start (2026-09-24): no sequence role is claimed for them
    assert value["by_session_role"] == {}


def _block_rows() -> list[dict]:
    """Two LOADED lifts after the v0.4 block start (live-projected fixture rows, re-dated) and
    one unloaded day between them — the walk/Engine day that must never advance the sequence.
    #4312: the first is the fixture's LEGS session (the sequence's first role is lower-heavy) and
    the second its PULL session (upper-volume) — a lift whose content reaches none of the role's
    anchor muscles is flagged, not credited (`test_session_sequence_4110.py` holds that guard)."""
    pull, legs = _hevy_rows()[0], _hevy_rows()[1]
    lift1 = dict(legs, sk="DATE#2026-09-25#WORKOUT#u1", date="2026-09-25", workout_uid="hevy:u1", source_workout_id="u1")
    walk = dict(pull, sk="DATE#2026-09-26#WORKOUT#w1", date="2026-09-26", workout_uid="hevy:w1", source_workout_id="w1")
    walk["exercises"] = [{"name": "Treadmill", "sets": [{"type": "normal", "duration_sec": 1800}]}]
    lift2 = dict(pull, sk="DATE#2026-09-27#WORKOUT#u2", date="2026-09-27", workout_uid="hevy:u2", source_workout_id="u2")
    return [lift1, walk, lift2]


def test_last_session_by_role_comes_from_the_session_sequence(stub_readers, monkeypatch):
    """Mutation: key the role off a weekday calendar (v0.3's `calendar_entry`) instead of the
    order-based sequence — under v0.4 the role is the position of the LOADED session, whatever the day."""
    from training import session_sequence

    from mcp import tools_strength

    rows = _block_rows()
    monkeypatch.setattr(tools_strength, "_read_hevy_all_phases", lambda s, e: (rows, ["experiment"]))
    value = pkt._last_sessions("2026-09-27")
    done = session_sequence.completed_positions(rows, "2026-09-28")  # #4161: the ledger, one definition
    expect = {c["session_role"]: c["workout_id"] for c in done}
    assert {r: row["workout_uid"].split(":")[1] for r, row in value["by_session_role"].items()} == expect
    assert value["by_session_role"]["lower_heavy"]["workout_uid"] == "hevy:u1"  # first_role
    assert value["by_session_role"]["upper_volume"]["workout_uid"] == "hevy:u2"  # the walk did not advance it
    assert value["session_sequence"]["state"] == "measured"


def test_routine_index_failure_leaves_sessions_read_and_says_why(stub_readers, monkeypatch):
    import training.routine_title as rt

    def boom(start):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(rt, "_load_routine_index", boom)
    value = pkt._last_sessions("2026-09-23")
    assert value["routine_index"]["state"] == "read_failed"
    assert "unresolved" in value["by_archetype"]


def test_no_hevy_session_is_absent(stub_readers, monkeypatch):
    from mcp import tools_strength

    monkeypatch.setattr(tools_strength, "_read_hevy_all_phases", lambda s, e: ([], []))
    assert pkt._last_sessions_field("2026-09-23")[1]["state"] == "absent"


# ── block position: THE session sequence, passed through ───────────────────────────────
def test_block_position_is_next_session_for_the_same_date_and_record(stub_readers, monkeypatch):
    """Mutation: compute the position any other way — v0.3's `calendar_entry` / weekday
    `program_week` again, or a re-derived role — and this equality reds."""
    import training.routine_title as rt
    from training import session_sequence

    from mcp import tools_strength

    rows = _block_rows()
    monkeypatch.setattr(tools_strength, "_read_hevy_all_phases", lambda s, e: ([r for r in rows if s <= r["date"] <= e], ["experiment"]))
    for day in ("2026-09-25", "2026-09-26", "2026-09-28", "2026-10-01"):
        value, status = pkt._block_position(day)
        # #4312: the seam carries each row's routine archetype from the (stubbed) index — the same record, annotated
        block = rt.annotate_routine_archetypes([r for r in rows if r["date"] < day], rt._load_routine_index("2026-06-26"))
        assert status["state"] == "measured"
        assert value["next_session"] == session_sequence.next_session(day, block), day
        assert value["program_week"] == session_sequence.program_week(day, block)
    value, _ = pkt._block_position("2026-09-28")
    nxt = value["next_session"]
    assert nxt["session_role"] == "lower_volume" and nxt["advanced_by"]["date"] == "2026-09-27"
    assert {"position_label", "week", "session_role", "advanced_by"} <= set(nxt)


def test_block_position_never_reads_the_superseded_calendar():
    """Mutation: import program_v03 / call calendar_entry from the packet."""
    src = (ROOT / "mcp" / "tools_coach_packet.py").read_text()
    assert "calendar_entry" not in src and "program_v03" not in src.replace("`training.program_v03`, SUPERSEDED", "")


def test_block_position_before_the_block_start_is_week_0():
    value, status = pkt._block_position("2026-09-23")
    assert status["state"] == "measured"
    assert value["program_week"] == 0 and value["next_session"] is None


# ── the instructions point at it ───────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["docs/coaching/COACH_SESSION.md", ".claude/skills/daily-debrief/SKILL.md"])
def test_chat_instructions_call_the_packet_first(path):
    """Mutation: remove the packet from the doc that tells a chat session what to call."""
    assert "get_coach_session_packet" in (ROOT / path).read_text()


def test_a_hevy_key_scheme_drift_is_read_failed_not_absent(stub_readers, monkeypatch):
    """Mutation: drop the per-workout-row check — a writer-side sk change (hevy_common writes,
    this reads: the #2847 seam) would read as 'no session in the window'."""
    from mcp import tools_strength

    drifted = [dict(r, sk=r["sk"].replace("#WORKOUT#", "#W#")) for r in _hevy_rows()]
    monkeypatch.setattr(tools_strength, "_read_hevy_all_phases", lambda s, e: (drifted, ["experiment"]))
    value, status = pkt._last_sessions_field("2026-09-23")
    assert status["state"] == "read_failed" and "InputShapeError" in status["error"] and value is None


# ── #4312: an off-program Flex complement is refused by the sequence, and the packet says so ──
def test_block_position_passes_not_credited_through_and_the_flex_row_carries_sequence_credit(stub_readers, monkeypatch):
    """The real Flex row (Hevy 80a19118, routine_index archetype=flex) after the two block lifts: `block_position`
    serves lower_volume and names the refused session; `last_session_by_type` shows it under `flex` with
    `sequence_credit.credited: False` and no role. Mutation: credit it (the pre-#4312 rule) and both change."""
    import training.routine_title as rt
    from training import session_sequence

    from mcp import tools_strength
    from tests.test_session_sequence_4110 import FLEX_WID, INDEX_4312, _wire_4312

    flex_row = _wire_4312()[0][2]
    assert flex_row["source_workout_id"] == FLEX_WID and flex_row["date"] == "2026-09-26"
    flex_row = dict(flex_row, sk="DATE#2026-09-28#WORKOUT#" + FLEX_WID, date="2026-09-28", workout_uid="hevy:" + FLEX_WID)
    rows = _block_rows() + [flex_row]
    monkeypatch.setattr(tools_strength, "_read_hevy_all_phases", lambda s, e: ([r for r in rows if s <= r["date"] <= e], ["experiment"]))
    monkeypatch.setattr(rt, "_load_routine_index", lambda start: INDEX_4312)
    value, status = pkt._block_position("2026-09-29")
    nxt = value["next_session"]
    assert status["state"] == "measured" and (nxt["session_role"], nxt["completed_sessions"]) == ("lower_volume", 2)
    assert [(n["workout_id"], n["archetype"], n["credited"]) for n in nxt["not_credited"]] == [(FLEX_WID, "flex", False)]
    assert nxt["credit_rule"]["routine_index_consulted"] is True and nxt["advanced_by"]["workout_id"] == "u2"
    last = pkt._last_sessions("2026-09-29")
    assert last["by_archetype"]["flex"]["session_role"] is None and "sequence_position" not in last["by_archetype"]["flex"]
    assert last["by_archetype"]["flex"]["sequence_credit"]["credited"] is False
    assert last["by_archetype"]["flex"]["sequence_credit"]["reason"].startswith("off-program complement")
    assert set(last["by_session_role"]) == {"lower_heavy", "upper_volume"}
    assert [n["workout_id"] for n in last["session_sequence"]["not_credited"]] == [FLEX_WID]
    with (monkeypatch.context() as m,):
        m.setattr(session_sequence, "off_program_archetype", lambda row: None)
        m.setattr(session_sequence, "content_check", lambda logs, role: {"role": role, "matched": None})
        value, _ = pkt._block_position("2026-09-29")
        last = pkt._last_sessions("2026-09-29")
    assert value["next_session"]["session_role"] == "upper_heavy" and value["next_session"]["advanced_by"]["workout_id"] == FLEX_WID
    assert last["by_archetype"]["flex"]["session_role"] == "lower_volume" and "sequence_credit" not in last["by_archetype"]["flex"]


def test_the_packet_reads_the_routine_index_lookback_from_its_one_home():
    from training import routine_title

    assert pkt.ROUTINE_INDEX_LOOKBACK_DAYS == routine_title.ROUTINE_INDEX_LOOKBACK_DAYS == 90


# ── #4189: the morning note in the packet ────────────────────────────────────────────


def test_morning_note_is_measured_with_the_four_words_the_day_and_the_pt_instant(stub_readers):
    """The field is `coach.morning_note.coach_fact` over the stored row — one derivation with
    /api/morning_note and the coach input. Mutation: read the partition here directly, or
    hand the raw UTC `written_at` through (the #4214 raw-instant check would fire on it)."""
    from coach import morning_note as mn

    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})
    f = out["fields"]["morning_note"]
    assert f["state"] == "measured" and f["source"] == pkt.SOURCES["morning_note"]
    v = f["value"]
    assert (v["sleep_word"], v["body_word"], v["mood_word"], v["felt_recovered"]) == ("heavy", "stiff", "steady", False)
    assert v["date"] == "2026-09-23" and v["day"].startswith("Wednesday, September 23")
    assert v["written_at_pt"].endswith("PT") and "written_at" not in v
    expected = {k: val for k, val in mn.coach_fact(dict(MORNING_NOTE_ROW)).items() if k != "state"}
    assert v == expected, "the packet must carry coach_fact's shape verbatim"
    assert out["packet_version"] == "coach-session-packet@1.3.0"


def test_morning_note_no_row_is_absent_and_a_failed_read_is_read_failed(stub_readers, monkeypatch):
    """Absence semantics at birth (ADR-104): no row = no note that morning, stated; a failed
    read is never an empty morning. Mutation: return `absent` for None."""
    from coach import morning_note as mn

    monkeypatch.setattr(mn, "read_notes", lambda table, today, days=2: [])
    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})
    f = out["fields"]["morning_note"]
    assert f["state"] == "absent" and f["value"] is None and "2026-09-23" in f["detail"]
    assert "morning_note" in out["not_measured"]

    monkeypatch.setattr(mn, "read_notes", lambda table, today, days=2: None)
    f = pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})["fields"]["morning_note"]
    assert f["state"] == "read_failed" and f["value"] is None and "ReadError" in f["error"]


def test_morning_note_reads_the_target_morning_with_the_coach_lookback(stub_readers, monkeypatch):
    """The packet asks for the target date's morning or the one before — COACH_LOOKBACK_DAYS,
    never the site's 14-day default — so a stale note cannot pose as this morning's."""
    from coach import morning_note as mn

    seen = {}

    def fake(table, today, days=None):
        seen.update(today=today, days=days)
        return [dict(MORNING_NOTE_ROW)]

    monkeypatch.setattr(mn, "read_notes", fake)
    pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})
    assert seen == {"today": "2026-09-23", "days": mn.COACH_LOOKBACK_DAYS} and mn.COACH_LOOKBACK_DAYS == 2


def test_morning_note_packet_field_never_serves_a_half_note(stub_readers, monkeypatch):
    """A producer drift that dropped a word must surface as read_failed, not as a note with a
    blank in it (public_view raises; the packet's _wrap keeps the error by name)."""
    from coach import morning_note as mn

    broken = {k: v for k, v in MORNING_NOTE_ROW.items() if k != "mood_word"}
    monkeypatch.setattr(mn, "read_notes", lambda table, today, days=2: [broken])
    f = pkt.tool_get_coach_session_packet({"target_date": "2026-09-23"})["fields"]["morning_note"]
    assert f["state"] == "read_failed" and "ValueError" in f["error"]


# ── today (#4311): the day a night-before debrief reviews, across sources, each activity once ──
def _today(target_date: str) -> tuple[dict, dict]:
    f = pkt.tool_get_coach_session_packet({"target_date": target_date})["fields"]["today"]
    return f["value"], {k: v for k, v in f.items() if k != "value"}


def test_today_lists_the_flex_session_and_the_garmin_walk_as_separate_items(stub_readers):
    """The owner's sentence (#4311). Mutation: read Hevy only (the 09-26 defect), or let the Garmin
    walk fold into the Flex session, or extrapolate the part-day to a week."""
    assert "today" in pkt.SOURCES and "today" in pkt.READERS
    value, status = _today("2026-09-27")
    assert status["state"] == "measured" and "PARTIAL" in status["detail"]
    assert value["day"] == "2026-09-26" and value["partial"] is True and "PARTIAL" in value["label"]
    items = value["activities"]
    assert [(i["source"], i["title"]) for i in items] == [("hevy", "Foundation - Flex - 1 - 20"), ("strava", "Afternoon Walk")]
    flex, walk = items
    assert flex["type"] == "full" and flex["start"]["pt"] == "Sep 26, 10:59 AM PT" and flex["moving_time_s"] == 3937
    assert flex["distance_mi"] is None and flex["avg_hr"] is None and flex["zones"] is None  # absence, not a default
    assert walk["id"] == "strava:20343117320" and walk["device"] == "Garmin epix (Gen2)" and walk["type"] == "Walk"
    assert walk["start"] == {"utc": "2026-09-26T20:09:22Z", "pt": "Sep 26, 1:09 PM PT"}
    assert (walk["moving_time_s"], walk["distance_mi"], walk["avg_hr"], walk["max_hr"]) == (6108, 5.16, 116.8, 171)
    assert walk["zones"]["zone2_s"] == 850 and "moving_time_s_counted" not in walk
    # the Hevy->Strava mirror and WHOOP's view of the session are named as duplicates, not dropped
    assert [(d["device"], d["title"]) for d in value["deduplicated"]] == [
        ("Hevy", "Foundation - Flex - 1 - 20"),
        ("WHOOP", "Lunch Weight Training"),
    ]
    assert all(d["inside_hevy_session"] == ["Foundation - Flex - 1 - 20"] for d in value["deduplicated"])
    # walking hours so far — the shared definition over one day, never a week
    assert (
        value["walking_hours_today"] == 1.7
        and value["walking"]["partial"] is True
        and value["walking"]["by_source"]["strava"]["hours"] == 1.7
    )
    assert "walking_layer_for_day" in pkt.SOURCES["today"] and "dedup_strava" in pkt.SOURCES["today"]


def test_today_flags_the_garmin_walk_over_the_hr_ceiling_read_from_the_redline(stub_readers, monkeypatch):
    """Mutation: hard-code 105, or flag on max HR, or skip the walk because it was de-duplicated."""
    from training import owner_redlines

    ceiling = owner_redlines.REDLINES["walking_floor_hr_wk"]["hr_ceiling_bpm"]
    value, _ = _today("2026-09-27")
    assert value["walking_floor_hr_wk"]["hr_ceiling_bpm"] == ceiling
    assert [(f["id"], f["avg_hr"], f["hr_ceiling_bpm"], f["over_by_bpm"], f["deduplicated"]) for f in value["hr_ceiling_flags"]] == [
        ("strava:20343117320", 116.8, ceiling, round(116.8 - ceiling, 1), False)
    ]
    src = (ROOT / "mcp" / "coach_packet_today.py").read_text()
    assert not any(isinstance(n, ast.Constant) and n.value == ceiling for n in ast.walk(ast.parse(src))), "the ceiling is a literal"
    monkeypatch.setitem(owner_redlines.REDLINES["walking_floor_hr_wk"], "hr_ceiling_bpm", 200)
    value, _ = _today("2026-09-27")
    assert value["hr_ceiling_flags"] == [] and value["walking_floor_hr_wk"]["hr_ceiling_bpm"] == 200


def test_today_keeps_the_six_whoop_in_hevy_walks_de_duplicated(stub_readers, monkeypatch):
    """19-25 Sep: WHOOP auto-detected the treadmill block inside six Hevy sessions and posted each
    to Strava as its own Walk. Each is listed ONCE — as a named duplicate of its session, never as
    a second activity. Mutation control: neuter `walking_volume.dedup_strava` — every WHOOP walk
    appears beside its Hevy session and the predicate below catches it."""
    from training import walking_volume

    def whoop_walks(value: dict, key: str) -> list[tuple[str, str]]:
        return [(i["title"], i["start"]["pt"]) for i in value[key] if i.get("device") == "WHOOP" and i.get("modality") == "walking"]

    days = [f"2026-09-{d}" for d in range(19, 26)]
    listed_twice, deduplicated = [], []
    for day in days:
        value, status = _today(shift_day_key(day, 1))
        assert status["state"] == "measured" and value["day"] == day
        assert [i["source"] for i in value["activities"]] == ["hevy"], (day, value["activities"])
        listed_twice += whoop_walks(value, "activities")
        for d in [d for d in value["deduplicated"] if d["device"] == "WHOOP" and d["modality"] == "walking"]:
            assert d["inside_hevy_session"] and d["inside_hevy_session"][0].startswith("Foundation - ")
            deduplicated.append((d["title"], d["start"]["pt"]))
    assert listed_twice == [] and len(deduplicated) == 6 and len(set(deduplicated)) == 6
    assert [d[1][:6] for d in deduplicated] == [
        "Sep 19",
        "Sep 20",
        "Sep 21",
        "Sep 23",
        "Sep 24",
        "Sep 25",
    ]  # 09-22 had a Hevy Walking block, no WHOOP walk
    # the control: without the #4068 rule the same predicate reds
    monkeypatch.setattr(
        walking_volume,
        "dedup_strava",
        lambda strava, intervals: (list(strava), {"rule": "none", "removed": [], "hours_removed": 0.0, "untimed": 0}),
    )
    value, _ = _today("2026-09-20")
    assert whoop_walks(value, "activities") == [("Lunch Walk", "Sep 19, 11:01 AM PT")] and value["deduplicated"] == []


def test_today_is_read_failed_when_neither_source_reads_and_a_floor_when_one_does(stub_readers, monkeypatch):
    """Mutation: swallow a source failure into an empty day (the #4072 class), or let it escape the packet."""
    from mcp import coach_packet_today

    def boom(day):
        raise TimeoutError("hevy query timed out")

    monkeypatch.setattr(coach_packet_today, "read_hevy_day", boom)
    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-27"})
    f = out["fields"]["today"]
    assert f["state"] == "measured" and "FLOOR — hevy read failed" in f["detail"]
    assert f["value"]["sources"]["hevy"] == {"status": "read_failed", "rows": None, "error": "TimeoutError: hevy query timed out"}
    assert [i["id"] for i in f["value"]["activities"]] == [
        "strava:20341744941",
        "strava:20343117320",
    ]  # the mirror stands in for the session
    assert any("hevy could not be read" in h for h in f["value"]["honesty"])
    assert out["fields"]["walking_hours_7d"]["state"] == "measured" and out["not_measured"] == []

    def boom2(day):
        raise RuntimeError("strava partition unreadable")

    monkeypatch.setattr(coach_packet_today, "read_strava_day", boom2)
    out = pkt.tool_get_coach_session_packet({"target_date": "2026-09-27"})
    f = out["fields"]["today"]
    assert (
        f["state"] == "read_failed"
        and f["error"].startswith("SourceReadError: hevy: TimeoutError")
        and "strava: RuntimeError" in f["error"]
    )
    assert out["not_measured"] == ["today"] and out["fields"]["last_session_by_type"]["state"] == "measured"


def test_today_is_absent_for_a_day_not_started_and_for_an_empty_day(stub_readers, monkeypatch):
    """Mutation: read a day that has not happened as an empty measured day, or an empty day as read_failed."""
    from mcp import coach_packet_today

    value, status = _today("2026-09-28")  # today is pinned to 09-26: the 27th has not started
    assert status["state"] == "absent" and "has not started" in status["detail"] and value is None
    monkeypatch.setattr(coach_packet_today, "read_hevy_day", lambda day: [])
    monkeypatch.setattr(coach_packet_today, "read_strava_day", lambda day: [])
    value, status = _today("2026-09-27")
    assert status["state"] == "absent" and "so far" in status["detail"]
    assert value["activities"] == [] and value["walking_hours_today"] is None and value["sources"]["hevy"]["status"] == "no_records"


def test_today_walking_hours_are_the_shared_definitions_and_the_ceiling_is_carried_not_counted(stub_readers, monkeypatch):
    """Mutation: sum the day's walks in `coach_packet_today` instead of reading the shared layer."""
    from mcp import shared_quantities

    seen = {}
    orig = shared_quantities.walking_layer_for_day

    def spy(day, **kw):
        seen["day"] = day
        layer = orig(day, **kw)
        layer["total_hr"] = 99.9
        return layer

    monkeypatch.setattr(shared_quantities, "walking_layer_for_day", spy)
    value, _ = _today("2026-09-27")
    assert seen == {"day": "2026-09-26"} and value["walking_hours_today"] == 99.9
    tree = ast.parse((ROOT / "mcp" / "coach_packet_today.py").read_text())
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "walking_layer_for_day" in calls and "build" not in calls and "walking_layer" not in calls
