"""tests/test_program_session_4064_4147.py — the program's session for each role, v0.4 Upper/Lower.

WHY THIS FILE EXISTS

#4064 made the generator build the PROGRAM's session (top set, back-offs, rep ranges, fixed
accessories) instead of a muscle-budget session with a role label on it — then for v0.3
full body. On 2026-09-23 the owner switched to v0.4 Upper/Lower, served in ORDER (#4147;
`DECISION#2026-09-24T03:10:59`). This file (formerly test_fullbody_block_calendar_4064.py)
holds the same guarantees for v0.4; the order itself is tests/test_session_sequence_4110.py.

  1. v0.4 IS DATA, ONE HOME. Four roles, archetypes upper/lower, every anchor pattern
     exactly twice a week, each redline muscle group inside its (moved) band, heavy = top
     4–6 @ RPE 7–8 + two back-offs at −10 %, volume = 8–12, the hinge's trap bar / RDL rule,
     no plyometrics and no max-effort singles, the block lock date, v0.3 kept as history.
  2. THE GENERATOR BUILDS IT: the first v0.4 session is Lower-heavy (the committed routine's
     shape), filed in the Lower folder, back-offs −10 % under the floored top set, the
     Minimum Viable Session machine-only, a deload that holds loads.
  3. v0.2 / INACTIVE IS UNTOUCHED — the sequence is never consulted.
  4. plan_next_session THROUGH THE MCP HANDLER serves the v0.4 session in order.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import owner_redlines, program_structure, program_v03, routine_generator  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
UH, LH, UV, LV = "upper_heavy", "lower_heavy", "upper_volume", "lower_volume"

# The committed first v0.4 session (owner, from chat, 2026-09-23): routine
# b1b9960468f374e30dcdeca8630dd18f / Hevy 4b743f67, target 2026-09-25 — read back read-only from
# its ROUTINE# partition on 2026-09-24 and written out here by hand: squat_barbell 3 x 4–6,
# Romanian Deadlift (Barbell) 3 x 6–8, Linear Leg Press 2 x 8–10, Seated Leg Curl 2 x 10–12,
# Calf Press 2 x 12–15. The catalog's reviewed keys stand in for the three chat-authored
# `tmpl:` machines (leg_press / leg_curl / calf_raise_machine).
COMMITTED_LOWER_HEAVY = [
    ("squat_barbell", 3),
    ("romanian_deadlift_barbell", 3),
    ("leg_press", 2),
    ("leg_curl", 2),
    ("calf_raise_machine", 2),
]


def _rx(role, **kw):
    return program_structure.session_prescription_for_role(role, catalog_movements=CATALOG["movements"], **kw)


# ── 1. v0.4 is data ──────────────────────────────────────────────────────────
def test_the_split_is_upper_lower_in_the_owners_order():
    seq = program_structure.SESSION_SEQUENCE
    assert program_structure.SPLIT == "upper_lower" and program_structure.PROGRAM_VERSION == "0.4"
    assert seq["session_roles"] == [UH, LH, UV, LV] and seq["sessions_per_week"] == 4
    assert {r: program_structure.SESSION_TEMPLATES[r]["archetype"] for r in seq["session_roles"]} == {
        UH: "upper",
        LH: "lower",
        UV: "upper",
        LV: "lower",
    }


def test_every_anchor_pattern_is_trained_exactly_twice_a_week():
    counts: dict[str, int] = {}
    for role in program_structure.SESSION_SEQUENCE["session_roles"]:
        for pattern, _ in program_structure.SESSION_TEMPLATES[role]["anchors"]:
            counts[pattern] = counts.get(pattern, 0) + 1
    assert counts == {p: 2 for p in program_structure.ANCHORS}


def test_heavy_days_are_a_top_set_plus_two_back_offs_and_volume_days_are_8_to_12():
    for role in (UH, LH):
        heavy = [e for e in _rx(role)["exposures"] if e["intensity"] == "heavy"]
        assert heavy, role
        for e in heavy:
            assert [s["kind"] for s in e["sets"]] == ["top", "back_off", "back_off"]
            assert e["sets"][0]["reps"] == [4, 6] and e["sets"][0]["rpe"] == [7, 8]
            assert all(s["pct_of_top"] == 90 for s in e["sets"][1:])
    for role in (UV, LV):
        anchors = [e for e in _rx(role)["exposures"] if e["kind"] == "anchor"]
        assert anchors and all(e["intensity"] == "volume" for e in anchors), role
        assert all(s["reps"] == [8, 12] for e in anchors for s in e["sets"]), role


def test_exposure_numbers_match_the_redline_rep_scheme_prose():
    prose = owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]
    e = program_structure.EXPOSURES
    assert f"{e['heavy']['reps'][0]}–{e['heavy']['reps'][1]}" in prose
    assert f"RPE {e['heavy']['top_rpe'][0]}–{e['heavy']['top_rpe'][1]}" in prose
    assert f"−{abs(e['heavy']['back_off_pct'])} %" in prose
    assert f"moderate {e['moderate']['reps'][0]}–{e['moderate']['reps'][1]}" in prose
    assert f"volume {e['volume']['reps'][0]}–{e['volume']['reps'][1]}" in prose
    assert (
        f"accessories {e['accessory']['reps'][0]}–{e['accessory']['reps'][1]} at RIR {e['accessory']['rir'][0]}–{e['accessory']['rir'][1]}"
        in prose
    )


def test_sets_per_muscle_per_week_sit_in_the_v04_band():
    """Owner 2026-09-23: ~10 hard sets/muscle/wk -> [8, 12] for the big groups (one home,
    owner_redlines); the small groups keep 4–6. The volume_ceiling tripwire is the band's top."""
    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    assert lift["sets_per_muscle_wk"] == [8, 12]
    ceiling = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "volume_ceiling")
    assert ceiling["threshold"]["sets_per_muscle_wk"] == lift["sets_per_muscle_wk"][1]
    got = program_structure.weekly_sets_by_muscle(CATALOG["movements"])
    assert {g: v["sets"] for g, v in got.items()} == {
        "quads": 8,
        "hams_glutes": 10,
        "chest": 8,
        "back": 10,
        "delts": 6,
        "biceps": 4,
        "triceps": 4,
    }
    for group, row in got.items():
        lo, hi = row["range"]
        assert lo <= row["sets"] <= hi, (group, row)


def test_mutation_control_three_more_pulldown_sets_push_back_over_the_band_top():
    """The band check can fail: the same week with vertical pull at 5 sets on upper-volume puts
    back at 13, over the 8–12 top — the per-group assertion above would red on it."""
    with patch.dict(program_structure.SESSION_TEMPLATES[UV]["anchor_sets"], {"vertical_pull": 5}):
        back = program_structure.weekly_sets_by_muscle(CATALOG["movements"])["back"]
    assert back["sets"] == 13 and back["sets"] > back["range"][1]


def test_sessions_fit_the_ceiling_and_the_week_total_sits_in_the_redline_band():
    ceiling = program_structure.week_grid()["session_set_ceiling"]
    totals = {r: _rx(r)["total_sets"] for r in program_structure.SESSION_TEMPLATES}
    assert totals == {UH: 15, LH: 12, UV: 17, LV: 12}
    assert all(t <= ceiling for t in totals.values()), totals
    lo, hi = owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"]
    assert lo <= sum(totals.values()) <= hi
    for role, tmpl in program_structure.SESSION_TEMPLATES.items():
        assert 2 <= len(tmpl["accessories"]) <= 3, role
        assert set(tmpl["accessories"]) <= set(program_structure.ACCESSORY_POOL[tmpl["archetype"]]), role


def test_the_hinge_is_the_trap_bar_and_the_rdl_only_as_the_moderate_hinge():
    lh = {e["pattern"]: e for e in _rx(LH)["exposures"] if e["kind"] == "anchor"}
    lv = {e["pattern"]: e for e in _rx(LV)["exposures"] if e["kind"] == "anchor"}
    assert (lh["hinge"]["intensity"], lh["hinge"]["movement_key"]) == ("moderate", "romanian_deadlift_barbell")
    assert (lv["hinge"]["intensity"], lv["hinge"]["movement_key"]) == ("volume", "deadlift_trap_bar")
    assert owner_redlines.REDLINES["load_anchoring"]["trap_bar_until_lb"] == 275
    assert program_structure.ANCHORS["hinge"]["catalog_keys"][0] == "deadlift_trap_bar"
    # the RDL is never a non-moderate hinge: it is not in the family's general keys
    assert not any("romanian" in k for k in program_structure.ANCHORS["hinge"]["catalog_keys"])


def test_no_plyometrics_and_no_max_effort_singles():
    excl = program_structure.EXCLUDED_METHODS
    assert set(excl["methods"]) >= {"plyometrics", "max_effort_singles"} and excl["provenance"] == "owner"
    for role in program_structure.SESSION_TEMPLATES:
        for e in _rx(role)["exposures"]:
            assert all(s["reps"][0] >= excl["min_reps_any_exposure"] for s in e["sets"]), (role, e["movement_key"])
            assert not any(w in (e["movement_key"] or "") for w in ("jump", "plyo", "box", "bound")), (role, e["movement_key"])


def test_the_block_is_owner_locked_for_six_weeks_until_2026_11_04():
    lock = program_structure.BLOCK_LOCK
    assert (lock["weeks"], lock["locked_until"], lock["provenance"]) == (6, "2026-11-04", "owner")
    assert lock["block_start"] == program_structure.SESSION_SEQUENCE["block_start"] == "2026-09-24"
    assert lock["decision_sk"] == program_structure.DECISION_SK
    assert program_structure.SESSION_SEQUENCE["weeks_per_block"] == lock["weeks"]
    from datetime import date

    span = (date.fromisoformat(lock["locked_until"]) - date.fromisoformat(lock["block_start"])).days
    assert 6 * 7 - 1 <= span <= 6 * 7 + 1, span


def test_v03_is_marked_superseded_and_kept_readable():
    sup = program_structure.SUPERSEDED_PROGRAMS["0.3"]
    assert sup is program_v03.SUPERSEDED
    assert (sup["superseded_on"], sup["decision_sk"], sup["superseded_by"]) == ("2026-09-24", "DECISION#2026-09-24T03:10:59", "0.4")
    # the definitions are still there, verbatim
    assert list(program_v03.SESSION_TEMPLATES) == ["heavy", "moderate", "heavy_moderate", "optional_fourth"]
    assert program_v03.HEVY_FOLDER == "Full Body" and program_v03.BLOCK_CALENDAR["steady_weekdays"] == [0, 2, 4]
    assert program_v03.BLOCK_CALENDAR["superseded"] is sup
    # load_ramp still measures the detraining-discount age to this date; it must equal v0.4's start
    assert program_structure.BLOCK_CALENDAR["block_1_start"] == program_structure.SESSION_SEQUENCE["block_start"]


def test_deload_cuts_about_40_percent_of_sets_and_keeps_every_top_set_and_anchor():
    """#4161 (v3.3): −40 % sets, loads held (Coleman 2024) — was −30 %."""
    for role in program_structure.SESSION_TEMPLATES:
        full = program_structure.session_prescription_for_role(role)
        dl = program_structure.session_prescription_for_role(role, deload=True)
        assert dl["deload_trim"]["sets_after"] == full["total_sets"] - round(full["total_sets"] * 0.40)
        assert dl["deload_trim"]["pct"] == -40 and dl["deload_trim"]["loads"] == "held"
        assert [e["pattern"] for e in dl["exposures"]] == [e["pattern"] for e in full["exposures"]]
        for e in dl["exposures"]:
            assert len(e["sets"]) >= 1
            if e["intensity"] == "heavy":
                assert e["sets"][0]["kind"] == "top"


def test_without_the_catalog_anchors_are_patterns_not_guesses():
    rx = program_structure.session_prescription_for_role(LH)
    anchors = [e for e in rx["exposures"] if e["kind"] == "anchor"]
    assert all(e["movement_key"] is None and "not read" in e["resolution_note"] for e in anchors)


# ── 2. the generator builds it ───────────────────────────────────────────────
def _done(n: int) -> list[dict]:
    """`n` completed loaded sessions from the block start, one a day (the sequence's input)."""
    from common.pacific_time import shift_day_key

    return [
        {
            "date": shift_day_key("2026-09-24", i),
            "source_workout_id": f"w{i}",
            "exercises": [{"name": "Linear Leg Press", "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]}],
        }
        for i in range(n)
    ]


def _generate(day: str, **kw):
    kw.setdefault("block_workouts", [])
    with patch.object(routine_generator, "_load_note_indexes", return_value=({}, {}, {}, {})):
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=day, **kw))


def test_generator_builds_the_committed_lower_heavy_as_the_first_v04_session():
    ideal, floor = _generate("2026-09-25")
    assert ideal.archetype == "lower" and ideal.variant == "ideal"
    assert ideal.title.startswith("LOWER-HEAVY — W1")
    assert [(b.movement_key, len(b.sets)) for b in ideal.exercises] == COMMITTED_LOWER_HEAVY
    assert ideal.exercises[0].sets[0].rep_range_start == 4 and ideal.exercises[0].sets[0].rep_range_end == 6
    assert ideal.inputs_snapshot["calendar"]["week"] == 1 and ideal.inputs_snapshot["calendar"]["session_role"] == LH
    assert ideal.inputs_snapshot["session_prescription"]["hevy_folder"] == "Lower"
    # the Minimum Viable Session: anchors only, top set + one back-off, machine-only (no bar on a
    # tired day — the #4080 exemption is OFF at skill_ceiling 1): leg press, hip thrust
    assert floor.variant == "floor" and [(b.movement_key, len(b.sets)) for b in floor.exercises] == [
        ("leg_press", 2),
        ("machine_hip_thrust", 2),
    ]


def test_generator_builds_each_role_in_order():
    got = [_generate("2026-10-10", block_workouts=_done(n))[0] for n in range(4)]
    assert [(r.archetype, r.inputs_snapshot["calendar"]["session_role"]) for r in got] == [
        ("lower", LH),
        ("upper", UV),
        ("lower", LV),
        ("upper", UH),
    ]
    assert [b.movement_key for b in got[3].exercises][:4] == [
        "barbell_bench_press",
        "machine_row",
        "machine_shoulder_press",
        "lat_pulldown",
    ]


def test_mutation_control_without_the_sequence_the_nominal_grid_answers():
    from training import session_sequence

    with patch.object(session_sequence, "next_session", return_value=None):
        routines = _generate("2026-09-25")  # a Friday: the nominal grid's lower-volume
    assert routines[0].inputs_snapshot["calendar"]["session_role"] == LV, "the weekday answers only when the sequence does not"


def test_generator_back_offs_sit_10_percent_under_the_ramped_top_set():
    lb = 0.45359237
    tid = CATALOG["movements"]["squat_barbell"]["hevy_template_id_hint"]
    history = {tid: [{"date": "2026-09-20", "top_weight_kg": 200 * lb, "sets": [{"weight_kg": 200 * lb, "reps": 8}]}]}
    weights = {"2026-09-20": 316.0, "2026-09-25": 315.0}
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        ideal = routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date="2026-09-25", block_workouts=[]))[0]
    squat = ideal.exercises[0]
    assert squat.movement_key == "squat_barbell"
    top = squat.sets[0].weight_kg
    # week 1 of the entry ramp (load_ramp, unchanged by #4147) — 60 % of the in-band anchor, no
    # discount (09-20 is inside the 28 d detraining age)
    assert top == 54.5  # ceil-to-0.5 kg of 200 lb x 0.60 = 54.43 kg
    assert [s.weight_kg for s in squat.sets[1:]] == [routine_generator._floor_half_kg(top * 0.9)] * 2
    assert any("back-offs at 90%" in r for r in ideal.rationale)
    assert "HEAVY: 1 top set of 4–6 @ RPE 7–8" in squat.notes


def test_generator_deload_week_holds_loads_and_cuts_sets():
    # #4161: lifting daily, hybrid week 6 opens 10-29 — before the block lock — so the deload opens on
    # the lock date 11-04 and runs 7 days; index 44 (11-07, week 7) is lower-heavy inside it
    ideal = _generate("2026-11-07", block_workouts=_done(44))[0]
    assert "DELOAD" in ideal.title and ideal.title.startswith("LOWER-HEAVY — W7")
    assert any("deload: sets 12 -> 7" in r for r in ideal.rationale)
    assert sum(len(b.sets) for b in ideal.exercises) == 7


def test_red_recovery_drops_accessories_not_anchors():
    ideal = _generate("2026-09-25", recovery_tier="red")[0]
    assert [b.movement_key for b in ideal.exercises] == ["squat_barbell", "romanian_deadlift_barbell"]


@pytest.mark.parametrize("archetype, folder", [("upper", "Upper"), ("lower", "Lower")])
def test_hevy_folders_are_upper_and_lower(archetype, folder):
    from mcp.hevy_routine_commit_report import FOLDER_BY_ARCHETYPE, folder_title_for

    assert FOLDER_BY_ARCHETYPE[archetype] == program_structure.HEVY_FOLDERS[archetype] == folder
    n = 0 if archetype == "lower" else 1  # the sequence starts at lower-heavy; one done -> upper-volume
    ideal = _generate("2026-09-26", block_workouts=_done(n))[0]
    assert ideal.archetype == archetype and folder_title_for(ideal) == folder
    # v0.3 history still files where it always did
    assert FOLDER_BY_ARCHETYPE["full"] == program_v03.HEVY_FOLDER == "Full Body"


def test_folder_is_created_if_absent_at_first_commit_never_before():
    """The folder is find-or-create at commit (`ensure_folder`). No live write happens here —
    the write client is mocked — and nothing in the generator or the planner creates one."""
    from mcp import hevy_routine_commit_report as rep

    created: list[str] = []
    with (
        patch("training.hevy_write_client.list_all_folders", return_value=([{"id": 1, "title": "Legs"}], False)),
        patch("training.hevy_write_client.create_folder", side_effect=lambda t: created.append(t) or {"routine_folder": {"id": 9}}),
    ):
        fid, miss = rep.ensure_folder("Lower")
    assert (fid, miss, created) == (9, None, ["Lower"])
    with (
        patch("training.hevy_write_client.list_all_folders", return_value=([{"id": 7, "title": "Lower"}], False)),
        patch("training.hevy_write_client.create_folder", side_effect=AssertionError("must not create a duplicate")),
    ):
        assert rep.ensure_folder("Lower") == (7, None)


def test_title_type_label_and_why_note():
    from training.routine_title import format_title, format_why_note

    ideal = _generate("2026-09-25")[0]
    assert format_title(ideal, {"phase": "Foundation", "type_count_in_phase": 1, "all_time_count": 5}) == "Foundation - Lower - 1 - 5"
    assert format_why_note(ideal).startswith("Lower heavy")


# ── 3. v0.2 / inactive is untouched ──────────────────────────────────────────
def test_inactive_program_never_consults_the_sequence():
    from training import session_sequence

    live = json.loads((REPO / "config" / "training_week.json").read_text())
    thursday = live["schedule"]["3"]["archetype"]
    with (
        patch.object(program_structure, "ACTIVE", False),
        patch.object(session_sequence, "next_session", side_effect=AssertionError("sequence read under an inactive program")),
    ):
        routines = _generate("2026-09-24")
    assert routines[0].archetype == thursday
    assert all("session_role" not in r for r in routines[0].rationale)


def test_inactive_program_plan_session_says_the_json_grid_decides():
    from training import plan_engine

    with patch.object(program_structure, "ACTIVE", False):
        block = plan_engine.constraint_block(date="2026-09-24")
    assert block["session"]["source"] == "json" and block["session"]["archetype"] is None


# ── 4. plan_next_session through the MCP handler ─────────────────────────────
def _stage1_patches():
    return [
        patch("mcp.tools_benchmark.tool_get_benchmark", return_value={"applicable": False, "reason": "offline"}),
        patch("mcp.tools_health.tool_get_readiness_score", return_value={"score": 60}),
        patch("mcp.tools_training.tool_get_acwr_status", return_value={"zone": "safe"}),
        patch("mcp.tools_strength.tool_get_muscle_volume", return_value={"muscle_volume": {}}),
        patch("mcp.tools_plan._walking_volume_last_7d", return_value=None),
        patch("mcp.tools_plan._protein_days_7d", return_value=(None, None)),
        patch("mcp.tools_plan._gather_performed_evidence", return_value=None),
        patch("mcp.tools_plan._rotation_window", return_value=None),
        patch("mcp.tools_plan._block_workouts", return_value=[]),  # #4110: no session completed yet
        patch("mcp.tools_plan._pain_dismissals", return_value=[]),
        patch("mcp.tools_plan._nutrition_critics_block", return_value={"verdicts": []}),
        patch("mcp.tools_plan._load_anchor_indexes", return_value=({}, {})),
        patch("training.training_notes.training_notes_health", side_effect=RuntimeError("offline")),
        patch("ai.bedrock_client.invoke", side_effect=AssertionError("no model in stage 1")),
    ]


def test_plan_next_session_through_the_mcp_handler_serves_lower_heavy_first():
    from mcp import handler as h

    with ExitStack() as st:
        for cm in _stage1_patches():
            st.enter_context(cm)
        st.enter_context(patch.object(h, "_emit_tool_metric"))
        st.enter_context(patch.object(h, "_audit_tool_call"))
        resp = h.handle_tools_call({"name": "plan_next_session", "arguments": {"target_date": "2026-09-25"}})
    out = json.loads(resp["content"][0]["text"])
    assert out["target_date"] == "2026-09-25", out
    session = out["constraint_block"]["session"]
    assert session["source"] == "session_sequence" and session["position_label"] == "week 1 · session 1 of 4 · lower-heavy"
    assert (session["archetype"], session["session_role"], session["week"], session["block"], session["deload"]) == (
        "lower",
        LH,
        1,
        1,
        False,
    )
    assert session["program_version"] == "0.4"
    rx = session["prescription"]
    assert rx["hevy_folder"] == "Lower"
    assert [(e["pattern"], e["intensity"], e["movement_key"]) for e in rx["exposures"] if e["kind"] == "anchor"] == [
        ("squat", "heavy", "squat_barbell"),
        ("hinge", "moderate", "romanian_deadlift_barbell"),
    ]
    assert rx["total_sets"] == 12
    assert out["constraint_block"]["program"]["program_version"] == "0.4"
