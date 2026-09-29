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

#4147 (2026-09-24): the program is v0.4 Upper/Lower now, served in order from lower-heavy. The
ramp itself is unchanged (load_ramp is another lane's, #4148); these tests read it through the
v0.4 UPPER-HEAVY session — the fourth in order, so three completed sessions (`_done(3)`) put it
next — whose heavy anchors are the barbell bench and the machine row.
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

from training import load_ramp, owner_redlines, program_structure, rep_scheme, routine_generator  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
MOVEMENTS = CATALOG["movements"]
LB = 0.45359237

# Band-matched anchors, in the wire shape `load_history_indexes` returns: one session each,
# at a bodyweight inside the same 10-lb band as the target-date weigh-in. #4080: the heavy
# day's squat is `squat_barbell` (owner option B exempts the squat family from skill_ceiling
# 2, and it is the squat's first key); `leg_press` stays for §8's non-v0.3 path test.
ANCHOR_LB = {"squat_barbell": 300.0, "leg_press": 400.0, "machine_row": 200.0, "lat_pulldown": 180.0, "barbell_bench_press": 250.0}
ANCHOR_REPS = {"squat_barbell": 5, "leg_press": 8, "machine_row": 10, "lat_pulldown": 10, "barbell_bench_press": 5}
HISTORY = {
    MOVEMENTS[k]["hevy_template_id_hint"]: [
        {"date": "2025-01-10", "top_weight_kg": lb * LB, "sets": [{"weight_kg": lb * LB, "reps": ANCHOR_REPS[k]}]}
    ]
    for k, lb in ANCHOR_LB.items()
}
WEIGHTS = {"2025-01-10": 316.0, "2026-09-23": 315.0, "2026-09-27": 315.0, "2026-11-17": 314.0}
# The v0.4 upper-heavy session's heavy anchors (#4147) — each has a `hevy_template_id_hint`, the
# key `_enforce_load_floors` looks the history up by (the bench's is the live-verified 79D0BB3A).
HEAVY_ANCHORS = ("barbell_bench_press", "machine_row")
BENCH = "barbell_bench_press"
DAY = "2026-09-27"  # week 1, after three completed sessions (lower-heavy, upper-volume, lower-volume)


def _generate(day: str = DAY, history=HISTORY, weights=WEIGHTS, **kw):
    kw.setdefault("block_workouts", _done(3))  # #4147: three done -> upper-heavy is next, still week 1
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, weights, {}, {})):
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=day, **kw))


def _done(n: int) -> list[dict]:
    """`n` completed loaded sessions from the block start, one a day (#4110)."""
    from common.pacific_time import shift_day_key

    return [
        {
            "date": shift_day_key("2026-09-24", i),
            "source_workout_id": f"w{i}",
            # #4312: a lower and an upper set, so each generic session matches the role it takes
            "exercises": [
                {"name": "Leg Press", "sets": [{"weight_kg": 90, "reps": 5}]},
                {"name": "Bench Press", "sets": [{"weight_kg": 60, "reps": 5}]},
            ],
        }
        for i in range(n)
    ]


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
    ideal = _generate()[0]
    assert ideal.inputs_snapshot["calendar"]["week"] == 1 and ideal.inputs_snapshot["calendar"]["session_role"] == "upper_heavy"
    for key in HEAVY_ANCHORS:
        share = _top(ideal, key) / _discounted(key)
        assert 0.60 <= share <= 0.65, (key, share)
    audit = ideal.inputs_snapshot["load_floors"]
    assert audit["load_rule"]["week"] == 1 and audit["movements"][BENCH]["ramp"]["ramp_pct"] == 60
    assert any("entry ramp, week 1 = 60%" in r for r in ideal.rationale)


def test_the_barbell_bench_heavy_anchor_is_loaded_through_its_verified_template_hint():
    """#4080: the exempt bench family resolves to `barbell_bench_press` (first key, tier 3). Its
    catalog entry now carries the live-verified hint 79D0BB3A, so the generator's load path finds
    its history and ramps it like every other heavy anchor; ADR-069's title resolution still runs
    at commit. Mutation control: without the hint the floor reads `no_template_id` and no set is
    loaded, which is exactly the regression this pins."""
    assert MOVEMENTS[BENCH].get("hevy_template_id_hint") == "79D0BB3A"
    ideal = _generate()[0]
    block = next(b for b in ideal.exercises if b.movement_key == BENCH)
    assert block.rationale_tag == "anchor:bench:heavy"
    status = ideal.inputs_snapshot["load_floors"]["movements"][BENCH]["status"]
    assert status != "no_template_id"


def test_back_offs_stay_10_percent_under_the_ramped_top_set_and_the_cue_names_the_ramp():
    ideal = _generate()[0]
    for key in HEAVY_ANCHORS:
        block = next(b for b in ideal.exercises if b.movement_key == key)
        top = block.sets[0].weight_kg
        assert [s.weight_kg for s in block.sets[1:]] == [routine_generator._floor_half_kg(top * 0.9)] * 2
        assert ideal.inputs_snapshot["load_floors"]["movements"][key]["back_off_floor_kg"] == block.sets[1].weight_kg
        assert "Week 1 load" in block.notes and "60% of your band anchor" in block.notes
        assert "never up" in block.notes


def test_moderate_anchors_ride_the_same_ramp():
    ideal = _generate()[0]
    pulldown = next(b for b in ideal.exercises if b.movement_key == "lat_pulldown")
    # #4388: rounded to the NEAREST 5 lb (owner ruling) — within half a step of the exact 60 %
    expect = rep_scheme.load_step_kg(_discounted("lat_pulldown") * 0.60)
    assert all(s.weight_kg == expect for s in pulldown.sets)
    assert abs(expect - _discounted("lat_pulldown") * 0.60) <= 2.5 * LB + 1e-9


# ── 3. week 9 ────────────────────────────────────────────────────────────────
def test_week_9_is_capped_at_85_percent():
    # #4161: weeks are hybrid (4 sessions AND >= 7 days) — lifting daily, week 9 opens on day 56 (11-19);
    # index 59 (11-22) is upper-heavy (4 a week, from lower-heavy)
    ideal = _generate("2026-11-22", block_workouts=_done(59))[0]
    assert ideal.inputs_snapshot["calendar"]["week"] == 9 and ideal.title.startswith("UPPER-HEAVY")
    for key in HEAVY_ANCHORS:
        top = _top(ideal, key)
        e1rm = load_ramp.band_e1rm_kg(ANCHOR_LB[key] * LB, [ANCHOR_REPS[key]])
        # held at 85 % of the discounted anchor set (novel-again fixture), nearest 5 lb (#4388)
        assert top == min(rep_scheme.load_step_kg(_discounted(key) * 0.85), rep_scheme.load_step_kg(0.85 * e1rm, down=True)), key
        assert abs(top - _discounted(key) * 0.85) <= 2.5 * LB + 1e-9, key
        assert top <= 0.85 * e1rm, key


def test_rounding_never_crosses_the_e1rm_cap():
    """Rounding is to the NEAREST 5 lb (#4388), but the e1RM cap is rounded DOWN and wins: with
    no discount and no reps recorded, e1RM == the anchor, so the cap and the week-9 fraction
    coincide at 85 % (85.255 kg = 187.95 lb). Nearest would read 190 lb, over the cap; the cap's
    round-down reads 185 lb, and the result may not exceed 85 %."""
    floor = {"status": "ok", "best_kg": 100.3, "floor_kg": 100.3, "basis": {"reps": []}}
    with unittest.mock.patch.dict(owner_redlines.REDLINES["load_anchoring"], {"detraining_discount_pct": [0, 0]}):
        r = load_ramp.ramp_floor(floor, 9)
    assert r["floor_kg"] <= 0.85 * 100.3 and r["floor_kg"] == pytest.approx(185 * LB)
    assert r["floor_kg"] < rep_scheme.load_step_kg(0.85 * 100.3), "the cap's round-down must win over nearest (190 lb)"


# ── 4. mutation control ──────────────────────────────────────────────────────
def test_mutation_control_without_the_ramp_week_1_reads_100_percent():
    with patch.object(load_ramp, "ramp_floor", side_effect=lambda f, _w: f):
        ideal = _generate()[0]
    for key in HEAVY_ANCHORS:
        assert _top(ideal, key) == pytest.approx(ANCHOR_LB[key] * LB), key
        assert not 0.60 <= _top(ideal, key) / _discounted(key) <= 0.65, "the ramp-less week 1 must red the week-1 assertion"


def test_no_band_matched_anchor_means_no_ramped_load():
    ideal = _generate(history={})[0]
    assert all(s.weight_kg is None for b in ideal.exercises for s in b.sets)
    # the barbell bench HAS a template id, so its absence is `no_history`, not `no_template_id`
    assert ideal.inputs_snapshot["load_floors"]["movements"][BENCH]["status"] == "no_history"


# ── 5. the commit gate ───────────────────────────────────────────────────────
def test_the_commit_gate_accepts_the_ramped_session_and_refuses_without_the_back_off_floor():
    from mcp.hevy_prescription_gate import prescription_gate

    ideal = _generate()[0]
    assert prescription_gate(ideal)["verdict"] == "clean"
    for m in ideal.inputs_snapshot["load_floors"]["movements"].values():
        m.pop("back_off_floor_kg", None)
    gate = prescription_gate(ideal)
    assert gate["verdict"] == "refuse"
    # exactly the heavy anchors: their back-offs sit 10 % under the top set with no recorded
    # back-off floor.
    assert {v["where"] for v in gate["audit"]["violations"]} == set(HEAVY_ANCHORS)


# ── 6. the week's sets per redline muscle ────────────────────────────────────
def test_weekly_hard_sets_per_muscle_sit_inside_the_redline_ranges():
    week = program_structure.weekly_sets_by_muscle(MOVEMENTS)
    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    assert lift["sets_per_muscle_wk"] == [8, 12] and lift["sets_per_muscle_wk_small"] == [4, 6]  # #4147: v0.4's ~10
    for group, row in week.items():
        lo, hi = row["range"]
        assert lo <= row["sets"] <= hi, (group, row)
    assert week["back"]["sets"] == 10 and week["delts"]["sets"] == 6
    # the summed total still sits in §3's 50–65
    total = sum(
        program_structure.session_prescription_for_role(r)["total_sets"] for r in program_structure.SESSION_SEQUENCE["session_roles"]
    )
    lo, hi = lift["total_hard_sets_wk"]
    assert lo <= total <= hi, total


def test_mutation_control_the_pre_4090_shape_breaks_delts():
    """#4090's two fixes, re-applied to v0.4 (#4147): pulldown at 3 sets on both upper days puts back
    at 12 (the band's top) and a lateral raise on upper-heavy puts delts at 8 — over 4–6."""
    upper_heavy = program_structure.SESSION_TEMPLATES["upper_heavy"]
    upper_volume = program_structure.SESSION_TEMPLATES["upper_volume"]
    with (
        patch.dict(upper_heavy, {"anchor_sets": {}, "accessories": ["cable_tricep_pushdown", "db_lateral_raise"]}),
        patch.dict(upper_volume, {"anchor_sets": {}}),
    ):
        week = program_structure.weekly_sets_by_muscle(MOVEMENTS)
    assert week["back"]["sets"] == 12 and week["delts"]["sets"] == 8 and week["delts"]["sets"] > week["delts"]["range"][1]


# ── 7. the planner carries the same loads ────────────────────────────────────
def test_plan_next_session_2026_09_24_carries_week_1_ramp_loads():
    from mcp import handler as h
    from tests.test_program_session_4064_4147 import _stage1_patches

    with ExitStack() as st:
        for cm in _stage1_patches():
            st.enter_context(cm)
        st.enter_context(patch("mcp.tools_plan._load_anchor_indexes", return_value=(HISTORY, WEIGHTS)))
        st.enter_context(patch("mcp.tools_plan._block_workouts", return_value=_done(3)))  # #4147: upper-heavy next
        st.enter_context(patch.object(h, "_emit_tool_metric"))
        st.enter_context(patch.object(h, "_audit_tool_call"))
        resp = h.handle_tools_call({"name": "plan_next_session", "arguments": {"target_date": DAY}})
    session = json.loads(resp["content"][0]["text"])["constraint_block"]["session"]
    assert session["session_role"] == "upper_heavy"
    assert session["loads"]["status"] == "applied" and session["loads"]["week"] == 1
    assert session["weekly_sets_by_muscle"]["back"] == {"sets": 10, "range": [8, 12]}
    ideal = _generate()[0]
    assert set(HEAVY_ANCHORS) <= {e["movement_key"] for e in session["prescription"]["exposures"]}
    for e in session["prescription"]["exposures"]:
        if e["movement_key"] in HEAVY_ANCHORS:
            assert e["load"]["top_kg"] == _top(ideal, e["movement_key"]), "planner and draft disagree"
            assert 60.0 <= e["load"]["ramp"]["pct_of_discounted_base"] <= 65.0
            assert e["load"]["back_off_kg"] == routine_generator._floor_half_kg(e["load"]["top_kg"] * 0.9)


def test_plan_next_session_reports_an_unreadable_anchor_by_name():
    from mcp import handler as h
    from tests.test_program_session_4064_4147 import _stage1_patches

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


# ── 9. #4388 — the ramp's percentage is of band e1RM; novel-again keeps the anchor set ─────
# The live 2026-09-28 inputs (ROUTINE# 4300a686…, LOWER-VOLUME W1, read 2026-09-27): squat
# 195 lb x 5 on 09-24 at 313.7 lb (88.45 kg, band e1RM 103.19 kg); trap bar 225 lb x 5 on
# 2025-11-07 in another band (102.06 kg, e1RM 119.07 kg) — the nearest-band fallback, 325 days
# before, discounted 10 %. The engine wrote squat 53.5 kg (60 % of the SET) and trap bar 55.5 kg.
SQUAT_TID = MOVEMENTS["squat_barbell"]["hevy_template_id_hint"]
TRAP_TID = MOVEMENTS["deadlift_trap_bar"]["hevy_template_id_hint"]
SQUAT_KG, TRAP_KG = 88.45061733994974, 102.05840462301894
HISTORY_0928 = {
    SQUAT_TID: [{"date": "2026-09-24", "top_weight_kg": SQUAT_KG, "sets": [{"weight_kg": SQUAT_KG, "reps": 5}]}],
    TRAP_TID: [{"date": "2025-11-07", "top_weight_kg": TRAP_KG, "sets": [{"weight_kg": TRAP_KG, "reps": 5}]}],
}
WEIGHTS_0928 = {"2025-11-07": 332.0, "2026-09-24": 313.7, "2026-09-27": 313.7}


def _floor_0928(tid):
    return load_ramp.v03_floor(tid, HISTORY_0928, WEIGHTS_0928, 313.7, as_of="2026-09-28", week=1)


def test_the_0928_squat_floor_is_60_percent_of_band_e1rm_not_of_the_set():
    """#4388 rulings: `start_pct_of_band_e1rm` means what it says, and the floor rounds to the
    NEAREST 5 lb (owner, 2026-09-28). 60 % x 103.19 kg = 61.92 kg = 136.5 lb -> 135 lb
    (61.235 kg) — not 60 % x 88.45 kg = 53.5 kg (118 lb), the reported defect. The commit gate
    (`recovery_authoring.audit_prescription`, the comparator `hevy_prescription_gate` feeds) takes
    the owner's own hand-written 3 x 135 lb against that floor, and refuses the reported 118 lb."""
    from training.routine_ir import ExerciseBlock, Set

    from mcp import recovery_authoring as ra

    row = _floor_0928(SQUAT_TID)
    r = row["ramp"]
    assert row["status"] == "ok" and row["fallback"] is None and r["discount_pct"] == 0
    assert r["base"] == load_ramp.BASE_BAND_E1RM and r["band_e1rm_kg"] == pytest.approx(103.192, abs=1e-3)
    assert row["floor_kg"] == pytest.approx(61.235, abs=1e-3) == pytest.approx(135 * LB)
    assert row["floor_kg"] == rep_scheme.load_step_kg(103.19 * 0.60)

    def _audit(lb):
        sets = [Set(type="normal", weight_kg=lb * LB, rep_range_start=8, rep_range_end=12) for _ in range(3)]
        block = ExerciseBlock(movement_key="squat_barbell", sets=sets, rest_seconds=120, notes="")
        return ra.audit_prescription([block], floors={"squat_barbell": row})

    assert _audit(135)["ok"] is True, "the owner's own 135 lb must commit"
    refused = _audit(118)
    assert refused["ok"] is False and {v["kind"] for v in refused["violations"]} == {"below_floor"}
    assert "60% of your band e1RM" in load_ramp.render_ramp_cue(row)
    # week 6 on the e1RM base reaches the cap exactly — the ramp and the cap share one number
    w6 = load_ramp.v03_floor(SQUAT_TID, HISTORY_0928, WEIGHTS_0928, 313.7, as_of="2026-09-28", week=6)
    assert w6["floor_kg"] == rep_scheme.load_step_kg(103.192 * 0.85, down=True) and w6["floor_kg"] <= 0.85 * w6["ramp"]["band_e1rm_kg"]


def test_the_0928_trap_bar_novel_again_floor_is_unchanged():
    """#4388 acceptance: the novel-again handling is unchanged. The trap bar's anchor is 325 days
    old (the discount applies), so the base stays the anchor SET — 102.06 x 0.90 x 0.60 = 55.11 kg
    = 121.5 lb. Only the owner's rounding ruling moves it: nearest 5 lb = 120 lb (54.43 kg; the
    engine wrote 55.5 kg on the old round-up), and the owner's final 09-28 draft, which held the
    trap bar at 55.5 kg, still commits against it. An e1RM base would have read 140 lb."""
    from training.routine_ir import ExerciseBlock, Set

    from mcp import recovery_authoring as ra

    row = _floor_0928(TRAP_TID)
    r = row["ramp"]
    assert row["fallback"] == load_ramp.FALLBACK_NEAREST_BAND and r["discount_pct"] == 10
    assert r["discount"]["applies"] is True and r["discount"]["anchor_age_days_at_block_1"] == 321
    assert r["base"] == load_ramp.BASE_ANCHOR_SET and r["base_kg"] == pytest.approx(TRAP_KG, abs=1e-3)
    assert row["floor_kg"] == pytest.approx(120 * LB) == rep_scheme.load_step_kg(TRAP_KG * 0.90 * 0.60)
    block = ExerciseBlock(movement_key="deadlift_trap_bar", sets=[Set(type="normal", weight_kg=55.5)] * 2, rest_seconds=120, notes="")
    assert ra.audit_prescription([block], floors={"deadlift_trap_bar": row})["ok"] is True
    assert "60% of your band anchor after the 10% detraining discount" in load_ramp.render_ramp_cue(row)


def test_mutation_control_the_set_weight_base_reproduces_the_reported_118_lb():
    """Force every anchor onto the #4090 set-weight base and the 09-28 squat reads 60 % of the
    88.45 kg set = 117 lb (115 lb on the ruled grid; 118 lb on the old round-up, the number the
    owner reported) — so the e1RM assertion above reds."""
    real = load_ramp.anchor_discount

    def _set_base(date, p=None):
        pct, ruling = real(date, p)
        return pct, {**ruling, "applies": True}

    with patch.object(load_ramp, "anchor_discount", side_effect=_set_base):
        row = _floor_0928(SQUAT_TID)
    assert row["ramp"]["base"] == load_ramp.BASE_ANCHOR_SET and row["floor_kg"] == pytest.approx(115 * LB)
    assert row["floor_kg"] != pytest.approx(135 * LB)


# ── #4408: the ramp is a RE-ENTRY — a this-cycle load at this band is held, never ramped under ──
# The wire: the block-1 Hevy rows as stored (read-only 2026-09-28), indexed by the real
# `exercise_history.load_history_indexes` — bench 205 lb x 5 @ RPE 7.5 on 09-23 at 315.4 lb.
WIRE_WEIGHTS = {"2026-09-23": 315.4, "2026-09-24": 313.7, "2026-09-25": 313.1, "2026-09-28": 313.7}
BENCH_TID = MOVEMENTS[BENCH]["hevy_template_id_hint"]
BENCH_205_KG = 92.98654643430615  # the stored weight_kg of 205 lb


def _wire_history():
    import datetime
    from decimal import Decimal

    from training import exercise_history

    rows = json.loads(
        (REPO / "tests" / "fixtures" / "training_block1_wire_4408_4409" / "hevy_rows.json").read_text(),
        parse_float=Decimal,
        parse_int=Decimal,
    )["items"]

    class _Table:
        def query(self, **_kw):
            return {"Items": rows}

    with patch.object(exercise_history, "_table", return_value=_Table()):
        return exercise_history.load_history_indexes(lookback_days=30, today=datetime.date(2026, 9, 28))[0], rows


HEAVY_SLOT = load_ramp.slot_of([{"reps": [4, 6]}], "heavy")  # the top set: 4–6 @ RPE <= 8, target 5
MODERATE_SLOT = load_ramp.slot_of([{"reps": [6, 10]}], "moderate")  # 6–10, leave 2–3 -> RPE <= 8, target 8
VOLUME_SLOT = load_ramp.slot_of([{"reps": [8, 12]}], "volume")  # 8–12, leave 1–3 -> RPE <= 9, target 10


def _bench_0929(**kw):
    kw.setdefault("slot", HEAVY_SLOT)
    return load_ramp.v03_floor(BENCH_TID, _wire_history()[0], WIRE_WEIGHTS, 313.7, as_of="2026-09-29", week=1, **kw)


def test_4408_the_0929_bench_is_held_at_205_not_ramped_to_60_percent_of_e1rm():
    """The reported draft: 145 lb (60 % of a 239.2 lb band e1RM) six days after 205 x 5 at the same
    band, no discount, no layoff. The top set is now the achieved load, exactly as stored."""
    row = _bench_0929()
    r = row["ramp"]
    assert r["discount_pct"] == 0 and r["base"] == load_ramp.BASE_BAND_E1RM and row["fallback"] is None
    assert r["hold"]["applies"] is True and r["hold"]["layoff"] is False
    assert r["hold"]["ramp_top_kg"] == pytest.approx(145 * LB)  # what the ramp alone wrote on 09-29
    assert row["floor_kg"] == pytest.approx(205 * LB, abs=0.01) and r["top_kg"] == row["floor_kg"]
    a = r["hold"]["achieved"]
    assert (a["weight_kg"], a["reps"], a["rpe"], a["date"], a["bodyweight_lb"]) == (BENCH_205_KG, 5, 8.0, "2026-09-23", 315.4)
    # 205 x 5 @ RPE 8 -> e1RM (5 + 2 RIR) = 252.8 lb -> 5 reps at RPE <= 8 = 205 lb: the achieved load, not above it
    assert r["hold"]["rpe_basis"] == "rpe_adjusted" and r["hold"]["e1rm_rpe_adjusted"] == pytest.approx(
        BENCH_205_KG * (1 + 7 / 30), abs=1e-3
    )
    cue = load_ramp.render_ramp_cue(row)
    assert "205 lb x 5 @ RPE 8 on 2026-09-23" in cue and "RPE <= 8" in cue and "never goes under an achieved load" in cue


def test_4408_mutation_control_without_the_hold_the_bench_reads_the_reported_145_lb():
    with patch.object(load_ramp, "achieved_hold", return_value=None):
        row = _bench_0929()
    assert row["floor_kg"] == pytest.approx(145 * LB) and row["ramp"]["hold"]["applies"] is False


def _one_set(lb, reps, rpe, day="2026-09-23"):
    st = {"weight_kg": lb * LB, "reps": reps, "rpe": rpe}
    return {"X": [{"date": day, "top_weight_kg": lb * LB, "sets": [st]}]}


def _held(history, slot):
    return load_ramp.v03_floor("X", history, WIRE_WEIGHTS, 313.7, as_of="2026-09-29", week=1, slot=slot)


def test_4408_review_the_hold_is_rpe_aware_a_breach_set_is_not_re_prescribed():
    """Driver review (the owner's defect 3: RPE ceilings breached as the norm). 205 x 5 @ 8 into the
    4–6 top set @ <= 8 holds 205; 160 x 8 @ RPE 10 into a 6–10 slot @ <= 8 holds 150 — what its
    RPE-adjusted e1RM (160 x (1 + 8/30) = 202.7 lb) allows for 8 reps at RPE 8, rounded DOWN to 5 lb."""
    assert _held(_one_set(205, 5, 8), HEAVY_SLOT)["floor_kg"] == pytest.approx(205 * LB)
    row = _held(_one_set(160, 8, 10), MODERATE_SLOT)
    h = row["ramp"]["hold"]
    assert row["floor_kg"] == pytest.approx(150 * LB) and row["floor_kg"] < 160 * LB
    assert (
        h["applies"] is True
        and h["rpe_basis"] == "rpe_adjusted"
        and h["e1rm_rpe_adjusted"] == pytest.approx(160 * LB * (1 + 8 / 30), abs=1e-3)
    )
    # never ABOVE the achieved load: an easy set (RPE 6) still holds only what he moved
    assert _held(_one_set(160, 8, 6), MODERATE_SLOT)["floor_kg"] == pytest.approx(160 * LB)


def test_4408_review_mutation_control_without_the_rpe_adjustment_the_pulldown_holds_the_breach():
    """Drop the adjustment (the e1RM reads as if every set had room to spare) and the RPE-10
    pulldown holds 160 again — the assertion above reds."""
    with patch.object(load_ramp, "rpe_adjusted_e1rm_kg", side_effect=lambda w, r, rpe: float(w) * 10):
        row = _held(_one_set(160, 8, 10), MODERATE_SLOT)
    assert row["floor_kg"] == pytest.approx(160 * LB)


def test_4408_review_a_set_with_no_logged_rpe_holds_the_load_itself_and_says_absent():
    row = _held(_one_set(160, 8, None), MODERATE_SLOT)
    h = row["ramp"]["hold"]
    assert row["floor_kg"] == pytest.approx(160 * LB) and h["rpe_basis"] == "absent" and h["e1rm_rpe_adjusted"] is None
    assert "no RPE logged" in load_ramp.render_ramp_cue(row)
    # the RPE ceilings are read off program_structure.EXPOSURES, not typed here
    assert [load_ramp.slot_rpe_ceiling(i) for i in ("heavy", "moderate", "volume", "accessory", "unknown")] == [8, 8, 9, 9, None]


def test_4408_the_wire_pulldown_is_held_under_its_rpe_9_10_sets():
    """On the stored record the 09-23 pulldown sets were 160 x 8 @ 9 and @ 10: the 6–10 moderate slot
    (@ <= 8) holds 155 (from the @ 9 set), not the 160 the unadjusted hold wrote."""
    history, _ = _wire_history()
    tid = MOVEMENTS["lat_pulldown"]["hevy_template_id_hint"]
    row = load_ramp.v03_floor(tid, history, WIRE_WEIGHTS, 313.7, as_of="2026-09-29", week=1, slot=MODERATE_SLOT)
    assert row["floor_kg"] == pytest.approx(155 * LB) and row["ramp"]["hold"]["achieved"]["rpe"] == 9.0


def test_4408_the_hold_is_at_the_sets_rep_floor_never_a_heavier_lower_rep_load():
    """205 x 5 does not hold an 8–12 set (205 was never moved for 8): the 09-28 squat 135 lb x 10
    holds an 8–12 squat, not the 195 lb x 5 of 09-24 — the load the owner wrote by hand (#4388)."""
    history, _ = _wire_history()
    squat = MOVEMENTS["squat_barbell"]["hevy_template_id_hint"]
    vol = load_ramp.v03_floor(squat, history, WIRE_WEIGHTS, 313.7, as_of="2026-09-29", week=1, slot=VOLUME_SLOT)
    assert vol["floor_kg"] == pytest.approx(135 * LB, abs=0.01) and vol["floor_kg"] < 195 * LB
    heavy = load_ramp.v03_floor(squat, history, WIRE_WEIGHTS, 313.7, as_of="2026-09-29", week=1, slot=HEAVY_SLOT)
    assert heavy["floor_kg"] == pytest.approx(195 * LB, abs=0.01) and heavy["ramp"]["hold"]["achieved"]["date"] == "2026-09-24"
    # a caller that cannot say the slot gets the ramp alone — the lower number (#4149)
    assert _bench_0929(slot=None)["floor_kg"] == pytest.approx(145 * LB)
    assert _bench_0929(slot=load_ramp.slot_of([{"reps": [4, 6]}], None))["floor_kg"] == pytest.approx(145 * LB)


def test_4408_a_missed_week_is_not_a_layoff_the_load_is_still_held():
    """Driver review #2: a layoff is the detraining discount's own line (`DETRAINING_ANCHOR_AGE_DAYS`,
    #4107), not the 7-day re-entry threshold — ten days after the last loaded session (09-28 -> 10-08)
    there is nothing to re-enter from, so the bench is still held, never back to the 60 % ramp."""
    history, _ = _wire_history()
    row = load_ramp.v03_floor(
        BENCH_TID, history, WIRE_WEIGHTS, 313.7, as_of="2026-10-08", week=1, slot=HEAVY_SLOT, days_since_last_workout=10
    )
    ev = row["ramp"]["hold"]["layoff_evidence"]
    assert ev["record_gap_days"] == 10 and ev["threshold_days"] == load_ramp.DETRAINING_ANCHOR_AGE_DAYS
    assert row["ramp"]["hold"]["layoff"] is False and row["floor_kg"] == pytest.approx(205 * LB)


def test_4408_mutation_control_a_7_day_layoff_line_re_prescribes_the_ramp_after_one_missed_week():
    with patch.object(load_ramp, "DETRAINING_ANCHOR_AGE_DAYS", 7):
        history, _ = _wire_history()
        row = load_ramp.v03_floor(BENCH_TID, history, WIRE_WEIGHTS, 313.7, as_of="2026-10-08", week=1, slot=HEAVY_SLOT)
    assert row["ramp"]["hold"]["layoff"] is True and row["floor_kg"] == pytest.approx(145 * LB)


def test_4408_the_ramp_still_fires_after_a_layoff():
    """Past the detraining line — the record's gap, whatever the caller passes (the cron hands the
    generator a constant 2) — there IS something to re-enter from, and the ramp stands."""
    history, _ = _wire_history()
    gap_day = __import__("common.pacific_time", fromlist=["shift_day_key"]).shift_day_key(
        "2026-09-28", load_ramp.DETRAINING_ANCHOR_AGE_DAYS
    )
    row = load_ramp.v03_floor(BENCH_TID, history, WIRE_WEIGHTS, 313.7, as_of=gap_day, week=1, slot=HEAVY_SLOT, days_since_last_workout=2)
    assert row["ramp"]["hold"]["layoff"] is True
    assert row["ramp"]["hold"]["layoff_evidence"]["record_gap_days"] == load_ramp.DETRAINING_ANCHOR_AGE_DAYS
    assert row["floor_kg"] == pytest.approx(145 * LB) and row["ramp"]["hold"]["applies"] is False


def test_4408_the_ramp_still_fires_on_a_novel_again_anchor():
    """An anchor the detraining discount applies to (>= 28 d before block 1) is exactly what the ramp
    re-enters from — in band or not, it holds nothing up. The 09-28 trap bar stays at 120 lb."""
    row = load_ramp.v03_floor(TRAP_TID, HISTORY_0928, WEIGHTS_0928, 313.7, as_of="2026-09-28", week=1, slot=HEAVY_SLOT)
    assert row["floor_kg"] == pytest.approx(120 * LB) and row["ramp"]["hold"]["applies"] is False
    in_band_old = {BENCH_TID: [{"date": "2026-08-01", "top_weight_kg": 100.0, "sets": [{"weight_kg": 100.0, "reps": 5}]}]}
    old = load_ramp.v03_floor(
        BENCH_TID, in_band_old, {"2026-08-01": 314.0, "2026-09-28": 313.7}, 313.7, as_of="2026-09-29", week=1, slot=HEAVY_SLOT
    )
    assert old["ramp"]["discount_pct"] == 10 and old["ramp"]["hold"]["achieved"] is None and old["floor_kg"] < 100.0


def test_4408_generator_planner_and_chat_gate_read_one_held_number():
    """#4149: the generator writes the held load, the planner shows it, and the chat gate derives
    the same floor from the drafted sets — so the generator's own draft commits."""
    import types

    from mcp.hevy_prescription_gate import prescription_gate

    history, rows = _wire_history()
    with patch.object(routine_generator, "_load_note_indexes", return_value=(history, WIRE_WEIGHTS, {}, {})):
        ideal = routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date="2026-09-29", block_workouts=rows))[0]
    assert _top(ideal, BENCH) == pytest.approx(205 * LB)
    rx = program_structure.planned_session("2026-09-29", block_workouts=rows, catalog_movements=MOVEMENTS)["prescription"]
    load_ramp.annotate_prescription(rx, MOVEMENTS, history, WIRE_WEIGHTS, target_date="2026-09-29", week=1)
    planned = {e["movement_key"]: e["load"]["top_kg"] for e in rx["exposures"]}
    assert planned[BENCH] == _top(ideal, BENCH) and planned["db_shoulder_press"] == pytest.approx(52.5 * LB, abs=0.01)
    custom = types.SimpleNamespace(
        variant="ideal", target_date="2026-09-29", notes="", inputs_snapshot={"authored": "custom"}, exercises=ideal.exercises
    )
    with patch("mcp.plan_hevy_windows._block_workouts", return_value=rows):
        gate = prescription_gate(custom, movements=MOVEMENTS, history_index=history, weight_index=WIRE_WEIGHTS)
    assert gate["verdict"] == "clean", gate["audit"]
    assert gate["load_floors"]["movements"][BENCH]["floor_kg"] == _top(ideal, BENCH)
    assert gate["load_floors"]["movements"]["lat_pulldown"]["floor_kg"] == _top(ideal, "lat_pulldown") == pytest.approx(155 * LB)


# ── #4397: the ramp's cap is rep-aware — a volume day never carries his 5-rep weight ─────────────
# On the #4417 wire rows (squat 195 lb x 5 on 09-24 -> band e1RM 227.5 lb; 135 lb x 10 on 09-28),
# week 6's 85 % of band e1RM is 193.4 lb -> 190 lb: roughly his 5-rep weight, prescribed for 8–12.
SQUAT_WIRE_TID = MOVEMENTS["squat_barbell"]["hevy_template_id_hint"]


def _squat_wire(week, slot, as_of="2026-09-29"):
    history, _ = _wire_history()
    return load_ramp.v03_floor(SQUAT_WIRE_TID, history, WIRE_WEIGHTS, 313.7, as_of=as_of, week=week, slot=slot)


def test_4397_the_rep_table_is_inverse_epley_on_reps_plus_rir():
    """The table (population-derived, ADR-105): 5 reps 85.7 %, 8 = 78.9 %, 10 = 75 %, 12 = 71.4 % at RIR 0;
    the program's slots at their RPE ceilings: volume 73.2, moderate 75.0, accessory 71.4, heavy 81.1."""
    assert [round(load_ramp.rep_ceiling_pct(n, 10), 1) for n in (1, 5, 8, 10, 12)] == [96.8, 85.7, 78.9, 75.0, 71.4]
    slots = {i: load_ramp.slot_of([{"reps": program_structure.EXPOSURES[i]["reps"]}], i) for i in program_structure.EXPOSURES}
    got = {i: round(load_ramp.rep_ceiling_pct(s["target_reps"], s["rpe_ceiling"]), 1) for i, s in slots.items()}
    assert got == {"heavy": 81.1, "moderate": 75.0, "volume": 73.2, "accessory": 71.4}
    # the inverse of the hold's own e1RM: a load moved for (reps, RPE) is exactly its own ceiling at those reps/RPE
    assert load_ramp.rpe_adjusted_e1rm_kg(100.0, 8, 8) * load_ramp.rep_ceiling_pct(8, 8) / 100 == pytest.approx(100.0)
    assert "population-derived" in load_ramp.REP_TABLE_SOURCE and load_ramp.lowest_program_rpe_ceiling() == 8


def test_4397_volume_squat_week_1_and_week_6_sit_under_the_rep_table():
    """Week 1: 60 % of 227.5 lb = 135 lb (the ramp; 73.2 % does not bind). Week 6: the ramp's 85 % (190 lb)
    is capped at 73.2 % — 10 reps at RPE <= 9 — = 166.5 lb -> 165 lb, rounded DOWN."""
    w1, w6 = _squat_wire(1, VOLUME_SLOT), _squat_wire(6, VOLUME_SLOT)
    assert w1["floor_kg"] == pytest.approx(135 * LB, abs=0.01) and w1["ramp"]["rep_cap"]["binds"] is False
    rc = w6["ramp"]["rep_cap"]
    e1rm = w6["ramp"]["band_e1rm_kg"]
    assert rc["applies"] is True and rc["binds"] is True and rc["governed_by"] == "rep_cap"
    assert (rc["target_reps"], rc["rpe_ceiling"], rc["rir"], rc["pct_of_band_e1rm"]) == (10, 9, 1, 73.2)
    assert rc["ramp_top_kg"] == pytest.approx(190 * LB, abs=0.01)
    assert w6["floor_kg"] == pytest.approx(165 * LB, abs=0.01) == rc["cap_kg"] and w6["floor_kg"] <= e1rm * 0.732
    assert w6["ramp"]["top_kg"] == w6["floor_kg"] and w6["ramp"]["pct_of_band_e1rm"] < 73.2
    assert "capped at 73.2% of your band e1RM" in load_ramp.render_ramp_cue(w6) and "10 reps at RPE <= 9" in load_ramp.render_ramp_cue(w6)
    # the ramp binds at week 3 (70 %), the rep table from week 4 (75 % > 73.2 %)
    assert (
        _squat_wire(3, VOLUME_SLOT)["ramp"]["rep_cap"]["binds"] is False and _squat_wire(4, VOLUME_SLOT)["ramp"]["rep_cap"]["binds"] is True
    )


def test_4397_mutation_control_without_the_rep_cap_week_6_volume_is_his_5_rep_weight():
    with patch.object(load_ramp, "_apply_rep_cap", lambda *_a: None):
        w6 = _squat_wire(6, VOLUME_SLOT)
    assert w6["floor_kg"] == pytest.approx(190 * LB, abs=0.01) and "rep_cap" not in w6["ramp"]


def test_4397_a_5_rep_anchor_on_the_ramp_week_1_and_week_6():
    """After a layoff (no hold — the ramp re-enters) the 4–6 top set: week 1 = 60 % of the 239.2 lb bench
    e1RM = 145 lb; week 6 = the ramp's 85 % (203 lb -> 205) capped at 81.1 % (5 reps @ RPE <= 8) -> 190 lb."""
    from common.pacific_time import shift_day_key

    history, _ = _wire_history()
    after = shift_day_key("2026-09-28", load_ramp.DETRAINING_ANCHOR_AGE_DAYS)
    w1, w6 = (load_ramp.v03_floor(BENCH_TID, history, WIRE_WEIGHTS, 313.7, as_of=after, week=w, slot=HEAVY_SLOT) for w in (1, 6))
    assert w1["ramp"]["hold"]["layoff"] is True and w1["floor_kg"] == pytest.approx(145 * LB)
    assert w6["floor_kg"] == pytest.approx(190 * LB) and w6["ramp"]["rep_cap"]["pct_of_band_e1rm"] == 81.1
    assert w6["ramp"]["rep_cap"]["governed_by"] == "rep_cap"


def test_4397_the_hold_and_the_cap_never_disagree_the_final_load_is_under_the_one_table():
    """The hold governs when it applies (it runs after the cap and only raises) — the same `rep_ceiling_kg`
    on the RPE-adjusted e1RM of a set moved this cycle at this band. So at every week and every slot, the
    final load <= the table's % of the larger of the two e1RMs, and a held load is never above its own."""
    history, _ = _wire_history()
    seen = set()
    for tid in sorted(history):
        for slot in (HEAVY_SLOT, MODERATE_SLOT, VOLUME_SLOT):
            for week in range(1, 10):
                row = load_ramp.v03_floor(tid, history, WIRE_WEIGHTS, 313.7, as_of="2026-09-29", week=week, slot=slot)
                r = row.get("ramp")
                if not r:
                    continue
                pct = load_ramp.rep_ceiling_pct(slot["target_reps"], slot["rpe_ceiling"]) / 100
                a = r["hold"].get("achieved") or {}
                hold_e1 = a.get("e1rm_rpe_adjusted") or (
                    load_ramp.rpe_adjusted_e1rm_kg(a["weight_kg"], a["reps"], slot["rpe_ceiling"]) if a else 0.0
                )
                # 0.01 kg: the recorded e1RMs are rounded to 3 dp; a real breach is a 5-lb step (2.27 kg)
                assert row["floor_kg"] <= max(r["band_e1rm_kg"], hold_e1) * pct + 0.01, (tid, slot, week, row["floor_kg"])
                if a:
                    assert a["held_kg"] <= hold_e1 * pct + 0.01
                seen.add(r["rep_cap"]["governed_by"])
    assert seen == {"ramp", "rep_cap", "hold"}, seen


def test_4397_an_absent_rpe_set_below_the_target_reps_is_read_at_the_ceiling():
    """160 x 6 with no RPE into a 6–10 slot (target 8, RPE <= 8): read at RPE 8 -> e1RM 160 x (1 + 8/30) = 202.7 lb
    -> 8 reps @ 8 = 152 lb -> 150 lb, not the 160 he moved for 6. At or past the target it is the load itself."""
    row = _held(_one_set(160, 6, None), MODERATE_SLOT)
    assert row["ramp"]["hold"]["rpe_basis"] == "absent" and row["floor_kg"] == pytest.approx(150 * LB)
    assert _held(_one_set(160, 8, None), MODERATE_SLOT)["floor_kg"] == pytest.approx(160 * LB)


def test_4397_generator_planner_and_chat_gate_read_one_rep_capped_number_at_week_6():
    """#4149: at week 6 the generator writes the rep-capped loads, the planner shows them, and the chat gate
    derives the same floors — and a hand draft with no rationale tag (intensity unknown -> the lowest program
    ceiling) floors at or under them, so the generator's draft still commits."""
    import types

    from mcp.hevy_prescription_gate import prescription_gate

    real = load_ramp.ramp_floor
    history, rows = _wire_history()
    with ExitStack() as st:
        st.enter_context(patch.object(load_ramp, "ramp_floor", side_effect=lambda f, _w: real(f, 6)))
        st.enter_context(patch.object(routine_generator, "_load_note_indexes", return_value=(history, WIRE_WEIGHTS, {}, {})))
        ideal = routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date="2026-09-29", block_workouts=rows))[0]
        floors = ideal.inputs_snapshot["load_floors"]["movements"]
        capped = {k: m["ramp"]["rep_cap"] for k, m in floors.items() if (m.get("ramp") or {}).get("rep_cap", {}).get("binds")}
        assert capped, "week 6 must bind the rep table on at least one movement of the 09-29 session"
        rx = program_structure.planned_session("2026-09-29", block_workouts=rows, catalog_movements=MOVEMENTS)["prescription"]
        load_ramp.annotate_prescription(rx, MOVEMENTS, history, WIRE_WEIGHTS, target_date="2026-09-29", week=6)
        planned = {e["movement_key"]: e["load"]["top_kg"] for e in rx["exposures"]}
        for key in capped:
            assert planned[key] == _top(ideal, key) == floors[key]["floor_kg"], key
        custom = types.SimpleNamespace(
            variant="ideal", target_date="2026-09-29", notes="", inputs_snapshot={"authored": "custom"}, exercises=ideal.exercises
        )
        st.enter_context(patch("mcp.plan_hevy_windows._block_workouts", return_value=rows))
        gate = prescription_gate(custom, movements=MOVEMENTS, history_index=history, weight_index=WIRE_WEIGHTS)
        assert gate["verdict"] == "clean", gate["audit"]
        gate_rows = gate["load_floors"]["movements"]
        for key in capped:
            if gate_rows[key]["status"] == "no_template_id":
                # pre-existing, not #4397: the chat gate resolves a template only from the catalog hint, so the
                # #4409 in-block variant the generator carries on the exposure has NO gate floor (permissive)
                assert key == "db_shoulder_press" and gate_rows[key]["floor_kg"] is None
                continue
            assert gate_rows[key]["floor_kg"] == floors[key]["floor_kg"], key
        assert {"lat_pulldown"} <= set(capped) - {"db_shoulder_press"}, capped  # 6–10 @ <= 8: 75 % < the ramp's 85 %
        import copy

        untagged = copy.deepcopy(ideal.exercises)
        for ex in untagged:
            ex.rationale_tag = None
        bare = types.SimpleNamespace(**{**vars(custom), "exercises": untagged})
        gate2 = prescription_gate(bare, movements=MOVEMENTS, history_index=history, weight_index=WIRE_WEIGHTS)
        assert gate2["verdict"] == "clean", gate2["audit"]
