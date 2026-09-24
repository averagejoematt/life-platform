"""tests/test_fullbody_block_calendar_4064.py — v0.3's full-body session (the block calendar retired by #4110).

WHY THIS FILE EXISTS

v0.3 went ACTIVE on 2026-09-21 and block 1 starts Thursday 2026-09-24, but the generator
only knew a WEEKDAY grid (Mon/Wed/Fri full-body, Thursday a walk) and built every "full"
day with the v0.1 muscle-budget selector, the §3 role printed as a label. So the plan for
the first session of the block was a walk, and a heavy day had no top set.

What these tests hold:

  1–2. RETIRED BY #4110. The weekday calendar these pinned is gone: v0.3's sessions are a
     SEQUENCE that advances only on a completed loaded Hevy session. Its pin, the deload
     period's one home and the audible fixtures are tests/test_session_sequence_4110.py.
  3. §3 IS THE SESSION. Each required role trains four anchors; the three roles together
     train every pattern exactly twice; a heavy exposure is one top set + two back-offs
     at 4–6; the numbers match the redline's rep-scheme prose; deload removes ~30 % of
     sets and never a top set.
  4. THE GENERATOR BUILDS IT for 2026-09-24 (not a walk), sets back-offs at −10 % of the
     floored top set, and files it in the "Full Body" folder.
  5. v0.2 / INACTIVE IS UNTOUCHED. With `ACTIVE` False the seam serves the JSON grid and
     2026-09-24 (a Thursday) is whatever that grid says — the sequence is never consulted.
  6. plan_next_session FOR 2026-09-24, THROUGH THE MCP HANDLER, proposes the full-body
     HEAVY session of week 1 — the real program module, the real catalog, readers mocked.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import owner_redlines, program_structure, routine_generator  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())

# ── 1–2. the calendar and the deload period ──────────────────────────────────
# #4110 retired #4064's weekday calendar: the sessions are a SEQUENCE that advances only on a
# completed loaded Hevy session. The pinned sequence, the deload period's one home (with its
# mutation control) and the issue's audible fixtures live in tests/test_session_sequence_4110.py.
H, M, HM = "heavy", "moderate", "heavy_moderate"


# ── 3. §3 is the session ─────────────────────────────────────────────────────
def test_every_anchor_pattern_is_trained_exactly_twice_across_the_three_roles():
    counts: dict[str, int] = {}
    for role in program_structure.SESSION_SEQUENCE["session_roles"]:
        anchors = program_structure.SESSION_TEMPLATES[role]["anchors"]
        assert len(anchors) == 4, role
        for pattern, _ in anchors:
            counts[pattern] = counts.get(pattern, 0) + 1
    assert counts == {p: 2 for p in program_structure.ANCHORS}


def test_squat_and_hinge_are_never_heavy_on_the_same_day():
    for role, tmpl in program_structure.SESSION_TEMPLATES.items():
        heavy = {p for p, i in tmpl["anchors"] if i == "heavy"}
        assert not {"squat", "hinge"} <= heavy, role


def test_heavy_exposure_is_a_top_set_plus_two_back_offs():
    rx = program_structure.session_prescription_for_role("heavy", catalog_movements=CATALOG["movements"])
    squat = next(e for e in rx["exposures"] if e["pattern"] == "squat")
    assert [s["kind"] for s in squat["sets"]] == ["top", "back_off", "back_off"]
    assert squat["sets"][0]["reps"] == [4, 6] and squat["sets"][0]["rpe"] == [7, 8]
    assert all(s["pct_of_top"] == 90 for s in squat["sets"][1:])
    # #4080: `_resolve_movement` takes the FIRST listed key the ceiling admits. The squat's first
    # key is `squat_barbell` (skill_tier 3); the squat family is exempt (owner option B), so its
    # effective ceiling is max(2, 3) = 3 and the barbell squat resolves — not the tier-1 leg press.
    assert program_structure.ANCHORS["squat"]["catalog_keys"][0] == "squat_barbell"
    assert CATALOG["movements"]["squat_barbell"]["skill_tier"] == 3
    assert squat["movement_key"] == "squat_barbell"
    # mutation control: without the exemption the same ceiling of 2 skips tiers 3 (barbell, front
    # squat) and falls through to the first tier <= 2 member, the leg press — the 09-24 main shape
    rx2 = program_structure.session_prescription_for_role("heavy", catalog_movements=CATALOG["movements"], anchor_exempt=False)
    assert next(e for e in rx2["exposures"] if e["pattern"] == "squat")["movement_key"] == "leg_press"


def test_exposure_numbers_match_the_redline_rep_scheme_prose():
    prose = owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]
    e = program_structure.EXPOSURES
    assert f"{e['heavy']['reps'][0]}–{e['heavy']['reps'][1]}" in prose
    assert f"RPE {e['heavy']['top_rpe'][0]}–{e['heavy']['top_rpe'][1]}" in prose
    assert f"−{abs(e['heavy']['back_off_pct'])} %" in prose
    assert f"moderate {e['moderate']['reps'][0]}–{e['moderate']['reps'][1]}" in prose
    assert (
        f"accessories {e['accessory']['reps'][0]}–{e['accessory']['reps'][1]} at RIR {e['accessory']['rir'][0]}–{e['accessory']['rir'][1]}"
        in prose
    )


def test_the_program_summary_carries_the_sequence_and_the_anchor_sets_per_pattern():
    summary = program_structure.summary()
    assert summary["session_sequence"]["block_start"] == "2026-09-24"
    # #4090: vertical pull runs 2 sets per exposure so BACK (row + pulldown) sits inside 6–10;
    # the per-MUSCLE ranges are held in tests/test_v03_load_ramp_4090.py, not per pattern
    assert summary["weekly_anchor_sets"] == {**{p: 6 for p in program_structure.ANCHORS}, "vertical_pull": 4}


def test_sessions_fit_the_ceiling_and_the_week_totals_sit_in_the_redline_band():
    ceiling = program_structure.week_grid()["session_set_ceiling"]
    totals = {r: program_structure.session_prescription_for_role(r)["total_sets"] for r in program_structure.SESSION_TEMPLATES}
    assert all(t <= ceiling for t in totals.values()), totals
    week = sum(totals[r] for r in program_structure.SESSION_SEQUENCE["session_roles"])
    lo, hi = owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"]
    assert lo <= week <= hi, week
    for role in program_structure.SESSION_SEQUENCE["session_roles"]:
        n_acc = len(program_structure.SESSION_TEMPLATES[role]["accessories"])
        assert 2 <= n_acc <= 3, role
        assert set(program_structure.SESSION_TEMPLATES[role]["accessories"]) <= set(program_structure.ACCESSORY_POOL["full"])


def test_deload_cuts_about_30_percent_of_sets_and_keeps_every_top_set_and_anchor():
    for role in program_structure.SESSION_TEMPLATES:
        full = program_structure.session_prescription_for_role(role)
        dl = program_structure.session_prescription_for_role(role, deload=True)
        assert dl["deload_trim"]["sets_after"] == full["total_sets"] - round(full["total_sets"] * 0.30)
        assert [e["pattern"] for e in dl["exposures"]] == [e["pattern"] for e in full["exposures"]]
        for e in dl["exposures"]:
            assert len(e["sets"]) >= 1
            if e["intensity"] == "heavy":
                assert e["sets"][0]["kind"] == "top"


def test_without_the_catalog_anchors_are_patterns_not_guesses():
    rx = program_structure.session_prescription_for_role("heavy")
    anchors = [e for e in rx["exposures"] if e["kind"] == "anchor"]
    assert all(e["movement_key"] is None and "not read" in e["resolution_note"] for e in anchors)


# ── 4. the generator builds it ───────────────────────────────────────────────
def _done(n: int) -> list[dict]:
    """`n` completed loaded sessions from the block start, one a day (#4110's sequence input)."""
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


def test_generator_builds_the_heavy_full_body_session_on_2026_09_24():
    ideal, floor = _generate("2026-09-24")
    assert ideal.archetype == "full" and ideal.variant == "ideal"
    assert ideal.title.startswith("Full Body HEAVY — W1")
    # #4080: squat and bench are core anchor families exempt from skill_ceiling (owner ruling
    # 2026-09-23), so each resolves to its FIRST listed key even at tier 3 — the barbell squat
    # and the barbell bench. Row stays `machine_row`: it is the row's first key (tier 1), the
    # row family has no tier-3 member to reach. Vertical pull is not exempt and is tier 1 anyway.
    assert [b.movement_key for b in ideal.exercises] == [
        "squat_barbell",
        "barbell_bench_press",
        "machine_row",
        "lat_pulldown",
        "leg_curl",
        "cable_tricep_pushdown",
        "db_curl",
    ]
    # #4090: pulldown 2 sets (back 10, not 12); the lateral raise gave way to an arm pair (delts 6, not 8)
    assert [len(b.sets) for b in ideal.exercises] == [3, 3, 3, 2, 2, 2, 2]
    assert ideal.exercises[0].sets[0].rep_range_start == 4 and ideal.exercises[0].sets[0].rep_range_end == 6
    assert ideal.inputs_snapshot["calendar"]["week"] == 1
    assert ideal.inputs_snapshot["session_prescription"]["hevy_folder"] == "Full Body"
    # the Minimum Viable Session: anchors only, top set + one back-off
    assert floor.variant == "floor" and [len(b.sets) for b in floor.exercises] == [2, 2, 2, 2]
    # ...resolved at skill_ceiling 1 with the exemption OFF (anchor_exempt=False): each anchor's
    # first tier-1 key — leg press (squat_barbell/front_squat tier 3, goblet tier 2 skipped),
    # machine chest press (barbell 3, DB 2 skipped), machine row, pulldown. No bar on a tired day.
    assert [b.movement_key for b in floor.exercises] == ["leg_press", "machine_chest_press", "machine_row", "lat_pulldown"]


def test_mutation_control_the_weekday_grid_alone_makes_2026_09_24_a_walk():
    from training import session_sequence

    with patch.object(session_sequence, "next_session", return_value=None):
        routines = _generate("2026-09-24")
    assert routines[0].archetype == "aerobic", "without the sequence, Thursday is the grid's walk — the defect #4064 names"


def test_generator_back_offs_sit_10_percent_under_the_ramped_top_set():
    lb = 0.45359237
    # #4080: the heavy squat is `squat_barbell` now, so the history is keyed by ITS template id
    # (the floor looks the anchor up by `hevy_template_id_hint`, D04AC939), not the leg press's
    tid = CATALOG["movements"]["squat_barbell"]["hevy_template_id_hint"]
    history = {tid: [{"date": "2026-09-20", "top_weight_kg": 200 * lb, "sets": [{"weight_kg": 200 * lb, "reps": 8}]}]}
    weights = {"2026-09-20": 316.0, "2026-09-24": 315.0}
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        ideal = routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date="2026-09-24"))[0]
    squat = ideal.exercises[0]
    assert squat.movement_key == "squat_barbell"
    top = squat.sets[0].weight_kg
    # #4090: week 1 of the v0.3 entry ramp — 60 % of the anchor. #4107: this anchor (09-20)
    # is 4 d before block 1, inside the 28 d detraining age, so it takes NO discount. 316 and
    # 315 lb share band 310–319, so the in-band anchor answers (no fallback). The 85 % e1RM cap
    # (200 x (1 + 8/30) x 0.85 = 215 lb) does not bind.
    assert top == 54.5  # ceil-to-0.5 kg of 200 lb x 0.60 = 54.43 kg
    assert [s.weight_kg for s in squat.sets[1:]] == [routine_generator._floor_half_kg(top * 0.9)] * 2
    assert any("back-offs at 90%" in r for r in ideal.rationale)
    # the note leads with history (ADR-068's one best line), then the §3 prescription
    assert "HEAVY: 1 top set of 4–6 @ RPE 7–8" in squat.notes


def test_generator_deload_week_holds_loads_and_cuts_sets():
    # #4110: the deload is program week 6 — the 16th session, after 15 completed ones
    ideal = _generate("2026-10-28", block_workouts=_done(15))[0]
    assert "DELOAD" in ideal.title and ideal.title.startswith("Full Body HEAVY — W6")
    assert sum(len(b.sets) for b in ideal.exercises) == 12
    assert any("deload: sets 17 -> 12" in r for r in ideal.rationale)


def test_red_recovery_drops_accessories_not_anchors():
    ideal = _generate("2026-09-24", recovery_tier="red")[0]
    # the heavy day's four anchors exactly as resolved on green (#4080: barbell squat + bench);
    # only the three accessories go
    assert [b.movement_key for b in ideal.exercises] == ["squat_barbell", "barbell_bench_press", "machine_row", "lat_pulldown"]


def test_hevy_folder_for_full_is_the_program_folder():
    from mcp.hevy_routine_commit_report import folder_title_for

    ideal = _generate("2026-09-24")[0]
    assert folder_title_for(ideal) == program_structure.HEVY_FOLDER == "Full Body"


def test_folder_is_created_if_absent_at_first_commit_never_before():
    """The folder is find-or-create at commit (`ensure_folder`). No live write happens here —
    the write client is mocked — and nothing in the generator or the planner creates one."""
    from mcp import hevy_routine_commit_report as rep

    created: list[str] = []
    with (
        patch("training.hevy_write_client.list_all_folders", return_value=([{"id": 1, "title": "Push"}], False)),
        patch("training.hevy_write_client.create_folder", side_effect=lambda t: created.append(t) or {"routine_folder": {"id": 9}}),
    ):
        fid, miss = rep.ensure_folder("Full Body")
    assert (fid, miss, created) == (9, None, ["Full Body"])
    with (
        patch("training.hevy_write_client.list_all_folders", return_value=([{"id": 7, "title": "Full Body"}], False)),
        patch("training.hevy_write_client.create_folder", side_effect=AssertionError("must not create a duplicate")),
    ):
        assert rep.ensure_folder("Full Body") == (7, None)


def test_title_type_label_is_full_body():
    from training.routine_title import format_title, format_why_note

    ideal = _generate("2026-09-24")[0]
    assert format_title(ideal, {"phase": "Foundation", "type_count_in_phase": 1, "all_time_count": 5}) == "Foundation - Full Body - 1 - 5"
    assert format_why_note(ideal).startswith("Full-body heavy")


# ── 5. v0.2 / inactive is untouched ──────────────────────────────────────────
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


# ── 6. plan_next_session for 2026-09-24, through the MCP handler ─────────────
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


def test_plan_next_session_2026_09_24_through_the_mcp_handler_proposes_full_body_heavy():
    from mcp import handler as h

    with ExitStack() as st:
        for cm in _stage1_patches():
            st.enter_context(cm)
        st.enter_context(patch.object(h, "_emit_tool_metric"))
        st.enter_context(patch.object(h, "_audit_tool_call"))
        resp = h.handle_tools_call({"name": "plan_next_session", "arguments": {"target_date": "2026-09-24"}})
    out = json.loads(resp["content"][0]["text"])
    assert out["target_date"] == "2026-09-24", out
    session = out["constraint_block"]["session"]
    assert session["source"] == "session_sequence" and session["position_label"] == "week 1 · session 1 of 3 · heavy"
    assert (session["archetype"], session["session_role"], session["week"], session["block"], session["deload"]) == ("full", H, 1, 1, False)
    rx = session["prescription"]
    assert rx["hevy_folder"] == "Full Body"
    assert [(e["pattern"], e["intensity"], e["movement_key"]) for e in rx["exposures"] if e["kind"] == "anchor"] == [
        # #4080: the planner resolves through the same `session_prescription_for_role`, so the
        # exempt squat/bench families serve their first (tier-3 barbell) keys here too
        ("squat", "heavy", "squat_barbell"),
        ("bench", "heavy", "barbell_bench_press"),
        ("row", "heavy", "machine_row"),
        ("vertical_pull", "moderate", "lat_pulldown"),
    ]
    assert rx["total_sets"] == 17
    assert "constraint_block.session" in out["how_to_use"]
