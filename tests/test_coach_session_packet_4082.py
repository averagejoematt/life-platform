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

from mcp import tools_coach_packet as pkt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEVY_FIX = Path(__file__).parent / "fixtures" / "shared_quantities_4068" / "hevy_2026-09-08_22.json"
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
    assert out["packet_version"] == "coach-session-packet@1.2.0"


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
