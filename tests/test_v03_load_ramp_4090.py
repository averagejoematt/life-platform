"""tests/test_v03_load_ramp_4090.py — v0.3 §3's entry ramp and the per-muscle set redlines.

WHY THIS FILE EXISTS (#4090)

#4064 made 2026-09-24 the first full-body HEAVY session of block 1, and its loads went
through the #3927 floor — with no layoff, 100 % of the best load at the current bodyweight
band. v0.3 §3, approved 2026-09-21: "Start at 60–65 % of the band-matched historical anchor
after the 10–15 % detraining discount; ramp ~5 %/wk to week 6; ≤ 85 % of band e1RM until
week 8; then hold." And the §3 templates put back at 12 hard sets/wk and delts at 8,
against the 6–10 and 4–6 the owner signed.

What these tests hold:

  1. THE RAMP IS THE REDLINE'S. Every constant is read from `owner_redlines`; the derived
     start sits inside the declared 60–65 %, and moving a redline number moves the ramp.
  2. WEEK 1 — the generator's heavy squat / row top sets for 2026-09-24 land at 60–65 % of
     the band anchor after the discount; back-offs at −10 % of that top set. (#4080: the
     heavy bench is the barbell bench, which carries no `hevy_template_id_hint` by ADR-069
     design, so the generator's load path cannot find its history — stated, not hidden.)
  3. WEEK 9 — capped at 85 % of the discounted anchor, and at or under 85 % of band e1RM.
  4. MUTATION CONTROL — remove the ramp and the week-1 top set reads 100 % of the anchor,
     so assertion 2 reds.
  5. THE COMMIT GATE accepts the ramped session (back-offs judged against their own floor);
     without the recorded back-off floor it refuses, which is the defect the record fixes.
  6. THE WEEK'S SETS per redline muscle sit inside their ranges; restoring the lateral raise
     reds delts.
  7. THE PLANNER, through the MCP handler, carries the same loads on `session.loads`.
  8. THE OTHER PATHS ARE UNCHANGED — without the transform the floor is the band best.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import unittest.mock
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import load_ramp, owner_redlines, program_structure, routine_generator  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
MOVEMENTS = CATALOG["movements"]
LB = 0.45359237

# Band-matched anchors, in the wire shape `load_history_indexes` returns: one session each,
# at a bodyweight inside the same 10-lb band as the target-date weigh-in. #4080: the heavy
# day's squat is `squat_barbell` (owner option B exempts the squat family from skill_ceiling
# 2, and it is the squat's first key); `leg_press` stays for §8's non-v0.3 path test.
ANCHOR_LB = {"squat_barbell": 300.0, "leg_press": 400.0, "machine_row": 200.0, "lat_pulldown": 180.0}
ANCHOR_REPS = {"squat_barbell": 5, "leg_press": 8, "machine_row": 10, "lat_pulldown": 10}
HISTORY = {
    MOVEMENTS[k]["hevy_template_id_hint"]: [
        {"date": "2025-01-10", "top_weight_kg": lb * LB, "sets": [{"weight_kg": lb * LB, "reps": ANCHOR_REPS[k]}]}
    ]
    for k, lb in ANCHOR_LB.items()
}
WEIGHTS = {"2025-01-10": 316.0, "2026-09-23": 315.0, "2026-11-17": 314.0}
# The 09-24 heavy anchors the load path CAN load: each has a `hevy_template_id_hint`, which is
# the key `_enforce_load_floors` looks the history up by. The third heavy anchor,
# `barbell_bench_press`, has none (ADR-069: resolved by exact title at dry_run/commit), so its
# floor is `no_template_id` and its sets carry no load — see the test named for it below.
HEAVY_ANCHORS = ("squat_barbell", "machine_row")
UNLOADABLE_HEAVY = "barbell_bench_press"


def _generate(day: str, history=HISTORY, weights=WEIGHTS, **kw):
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=day, **kw))


def _top(ideal, key):
    return next(b for b in ideal.exercises if b.movement_key == key).sets[0].weight_kg


def _discounted(key):
    return ANCHOR_LB[key] * LB * (100 - load_ramp.params()["discount_pct"]) / 100.0


# ── 1. the ramp is the redline's ─────────────────────────────────────────────
def test_every_ramp_constant_is_read_from_owner_redlines():
    p = load_ramp.params()
    entry = owner_redlines.REDLINES["lifting_sessions_per_wk"]["load_entry"]
    assert p["step_pct_per_wk"] == entry["ramp_pct_per_wk"] == 5
    assert p["cap_pct"] == entry["max_pct_of_band_e1rm_until_week_8"] == 85
    assert p["ramp_to_week"] == entry["ramp_to_week"] == 6
    lo, hi = entry["start_pct_of_band_e1rm"]
    assert lo <= p["start_pct"] <= hi and p["start_pct"] == 60
    # #4107: owner ruling 2026-09-23 — the discount is 10 %, not the deep end of the stated 10–15 %
    assert p["discount_pct"] == max(owner_redlines.REDLINES["load_anchoring"]["detraining_discount_pct"]) == 10
    assert owner_redlines.REDLINES["load_anchoring"]["detraining_discount_provenance"].startswith("owner ruling 2026-09-23")
    assert [load_ramp.ramp_pct(w) for w in range(1, 11)] == [60, 65, 70, 75, 80, 85, 85, 85, 85, 85]


def test_moving_the_redline_moves_the_ramp_and_an_out_of_band_start_refuses():
    entry = owner_redlines.REDLINES["lifting_sessions_per_wk"]["load_entry"]
    with unittest.mock.patch.dict(entry, {"ramp_to_week": 5}):
        assert load_ramp.params()["start_pct"] == 65
        assert load_ramp.ramp_pct(1) == 65
    with unittest.mock.patch.dict(entry, {"ramp_to_week": 8}):
        with pytest.raises(ValueError, match="outside the redline"):
            load_ramp.params()


# ── 2. week 1 ────────────────────────────────────────────────────────────────
def test_week_1_heavy_top_sets_land_at_60_to_65_percent_of_the_discounted_anchor():
    ideal = _generate("2026-09-24")[0]
    assert ideal.inputs_snapshot["calendar"]["week"] == 1
    for key in HEAVY_ANCHORS:
        share = _top(ideal, key) / _discounted(key)
        assert 0.60 <= share <= 0.65, (key, share)
    audit = ideal.inputs_snapshot["load_floors"]
    assert audit["load_rule"]["week"] == 1 and audit["movements"]["squat_barbell"]["ramp"]["ramp_pct"] == 60
    assert any("entry ramp, week 1 = 60%" in r for r in ideal.rationale)


def test_the_barbell_bench_heavy_anchor_is_loaded_through_its_verified_template_hint():
    """#4080: the exempt bench family resolves to `barbell_bench_press` (first key, tier 3). Its
    catalog entry now carries the live-verified hint 79D0BB3A, so the generator's load path finds
    its history and ramps it like every other heavy anchor; ADR-069's title resolution still runs
    at commit. Mutation control: without the hint the floor reads `no_template_id` and no set is
    loaded, which is exactly the regression this pins."""
    assert MOVEMENTS[UNLOADABLE_HEAVY].get("hevy_template_id_hint") == "79D0BB3A"
    ideal = _generate("2026-09-24")[0]
    block = next(b for b in ideal.exercises if b.movement_key == UNLOADABLE_HEAVY)
    assert block.rationale_tag == "anchor:bench:heavy"
    status = ideal.inputs_snapshot["load_floors"]["movements"][UNLOADABLE_HEAVY]["status"]
    assert status != "no_template_id"


def test_back_offs_stay_10_percent_under_the_ramped_top_set_and_the_cue_names_the_ramp():
    ideal = _generate("2026-09-24")[0]
    for key in HEAVY_ANCHORS:
        block = next(b for b in ideal.exercises if b.movement_key == key)
        top = block.sets[0].weight_kg
        assert [s.weight_kg for s in block.sets[1:]] == [routine_generator._floor_half_kg(top * 0.9)] * 2
        assert ideal.inputs_snapshot["load_floors"]["movements"][key]["back_off_floor_kg"] == block.sets[1].weight_kg
        assert "Week 1 load" in block.notes and "60% of your band anchor" in block.notes
        assert "never up" in block.notes


def test_moderate_anchors_ride_the_same_ramp():
    ideal = _generate("2026-09-24")[0]
    pulldown = next(b for b in ideal.exercises if b.movement_key == "lat_pulldown")
    assert all(0.60 <= s.weight_kg / _discounted("lat_pulldown") <= 0.65 for s in pulldown.sets)


# ── 3. week 9 ────────────────────────────────────────────────────────────────
def test_week_9_is_capped_at_85_percent():
    ideal = _generate("2026-11-18")[0]
    assert ideal.inputs_snapshot["calendar"]["week"] == 9 and "HEAVY" in ideal.title
    for key in HEAVY_ANCHORS:
        top = _top(ideal, key)
        share = top / _discounted(key)
        assert 0.85 <= share <= 0.86, (key, share)
        e1rm = load_ramp.band_e1rm_kg(ANCHOR_LB[key] * LB, [ANCHOR_REPS[key]])
        assert top <= 0.85 * e1rm, key


def test_rounding_never_crosses_the_e1rm_cap():
    """Rounding is UP (so week 1 never lands under 60 %), but the e1RM cap is rounded DOWN
    and wins: with no discount and no reps recorded, e1RM == the anchor, so the cap and the
    week-9 fraction coincide at 85 % and the result may not exceed it."""
    floor = {"status": "ok", "best_kg": 100.3, "floor_kg": 100.3, "basis": {"reps": []}}
    with unittest.mock.patch.dict(owner_redlines.REDLINES["load_anchoring"], {"detraining_discount_pct": [0, 0]}):
        r = load_ramp.ramp_floor(floor, 9)
    assert r["floor_kg"] <= 0.85 * 100.3 and r["floor_kg"] == 85.0


# ── 4. mutation control ──────────────────────────────────────────────────────
def test_mutation_control_without_the_ramp_week_1_reads_100_percent():
    with patch.object(load_ramp, "ramp_floor", side_effect=lambda f, _w: f):
        ideal = _generate("2026-09-24")[0]
    for key in HEAVY_ANCHORS:
        assert _top(ideal, key) == pytest.approx(ANCHOR_LB[key] * LB), key
        assert not 0.60 <= _top(ideal, key) / _discounted(key) <= 0.65, "the ramp-less week 1 must red the week-1 assertion"


def test_no_band_matched_anchor_means_no_ramped_load():
    ideal = _generate("2026-09-24", history={})[0]
    assert all(s.weight_kg is None for b in ideal.exercises for s in b.sets)
    # the barbell squat HAS a template id, so its absence is `no_history`, not `no_template_id`
    assert ideal.inputs_snapshot["load_floors"]["movements"]["squat_barbell"]["status"] == "no_history"


# ── 5. the commit gate ───────────────────────────────────────────────────────
def test_the_commit_gate_accepts_the_ramped_session_and_refuses_without_the_back_off_floor():
    from mcp.hevy_prescription_gate import prescription_gate

    ideal = _generate("2026-09-24")[0]
    assert prescription_gate(ideal)["verdict"] == "clean"
    for m in ideal.inputs_snapshot["load_floors"]["movements"].values():
        m.pop("back_off_floor_kg", None)
    gate = prescription_gate(ideal)
    assert gate["verdict"] == "refuse"
    # exactly the LOADED heavy anchors: their back-offs sit 10 % under the top set with no
    # recorded back-off floor. The unloaded barbell bench has no load to be under anything.
    assert {v["where"] for v in gate["audit"]["violations"]} == set(HEAVY_ANCHORS)


# ── 6. the week's sets per redline muscle ────────────────────────────────────
def test_weekly_hard_sets_per_muscle_sit_inside_the_redline_ranges():
    week = program_structure.weekly_sets_by_muscle(MOVEMENTS)
    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    assert lift["sets_per_muscle_wk"] == [6, 10] and lift["sets_per_muscle_wk_small"] == [4, 6]
    for group, row in week.items():
        lo, hi = row["range"]
        assert lo <= row["sets"] <= hi, (group, row)
    assert week["back"]["sets"] == 10 and week["delts"]["sets"] == 6
    # the summed total still sits in §3's 50–65
    total = sum(program_structure.session_prescription_for_role(r)["total_sets"] for r in program_structure.BLOCK_CALENDAR["session_roles"])
    lo, hi = lift["total_hard_sets_wk"]
    assert lo <= total <= hi, total


def test_mutation_control_the_pre_4090_templates_break_back_and_delts():
    heavy = program_structure.SESSION_TEMPLATES["heavy"]
    moderate = program_structure.SESSION_TEMPLATES["moderate"]
    with (
        patch.dict(heavy, {"anchor_sets": {}, "accessories": ["leg_curl", "db_lateral_raise"]}),
        patch.dict(moderate, {"anchor_sets": {}}),
    ):
        week = program_structure.weekly_sets_by_muscle(MOVEMENTS)
    assert week["back"]["sets"] == 12 and week["delts"]["sets"] == 8


# ── 7. the planner carries the same loads ────────────────────────────────────
def test_plan_next_session_2026_09_24_carries_week_1_ramp_loads():
    from mcp import handler as h
    from tests.test_fullbody_block_calendar_4064 import _stage1_patches

    with ExitStack() as st:
        for cm in _stage1_patches():
            st.enter_context(cm)
        st.enter_context(patch("mcp.tools_plan._load_anchor_indexes", return_value=(HISTORY, WEIGHTS)))
        st.enter_context(patch.object(h, "_emit_tool_metric"))
        st.enter_context(patch.object(h, "_audit_tool_call"))
        resp = h.handle_tools_call({"name": "plan_next_session", "arguments": {"target_date": "2026-09-24"}})
    session = json.loads(resp["content"][0]["text"])["constraint_block"]["session"]
    assert session["loads"]["status"] == "applied" and session["loads"]["week"] == 1
    assert session["weekly_sets_by_muscle"]["back"] == {"sets": 10, "range": [6, 10]}
    ideal = _generate("2026-09-24")[0]
    assert set(HEAVY_ANCHORS) <= {e["movement_key"] for e in session["prescription"]["exposures"]}
    for e in session["prescription"]["exposures"]:
        if e["movement_key"] in HEAVY_ANCHORS:
            assert e["load"]["top_kg"] == _top(ideal, e["movement_key"]), "planner and draft disagree"
            assert 60.0 <= e["load"]["ramp"]["pct_of_discounted_anchor"] <= 65.0
            assert e["load"]["back_off_kg"] == routine_generator._floor_half_kg(e["load"]["top_kg"] * 0.9)


def test_plan_next_session_reports_an_unreadable_anchor_by_name():
    from mcp import handler as h
    from tests.test_fullbody_block_calendar_4064 import _stage1_patches

    with ExitStack() as st:
        for cm in _stage1_patches():
            st.enter_context(cm)
        st.enter_context(patch("mcp.tools_plan._load_anchor_indexes", side_effect=RuntimeError("ddb down")))
        st.enter_context(patch.object(h, "_emit_tool_metric"))
        st.enter_context(patch.object(h, "_audit_tool_call"))
        resp = h.handle_tools_call({"name": "plan_next_session", "arguments": {"target_date": "2026-09-24"}})
    loads = json.loads(resp["content"][0]["text"])["constraint_block"]["session"]["loads"]
    assert loads["status"] == "read_failed" and "RuntimeError" in loads["error"]


# ── 8. the other paths are unchanged ─────────────────────────────────────────
def test_without_the_transform_the_floor_is_still_the_band_best():
    from training.routine_ir import ExerciseBlock, Set

    block = ExerciseBlock(
        movement_key="leg_press", sets=[Set(type="normal", rep_range_start=6, rep_range_end=8)], rest_seconds=120, notes=""
    )
    audit = routine_generator._enforce_load_floors(
        [block], CATALOG, HISTORY, WEIGHTS, target_date="2026-09-24", days_since_last_workout=1, layoff_days=7, rationale=[]
    )
    assert block.sets[0].weight_kg == pytest.approx(ANCHOR_LB["leg_press"] * LB)
    assert audit["movements"]["leg_press"]["ramp"] is None
