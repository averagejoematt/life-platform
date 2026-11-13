"""tests/test_programming_fix7_5861.py — the sixth red team's findings, as outcome tests with must-fail controls (#5861 FIX7).

Every test drafts through the real path (`scripts/sample_weeks_5861.py`, the library flipped to `approved` IN MEMORY) or, for the
progression, feeds drafted weeks back as the next week's record (`scripts/progression_sim_5861.py`). Each carries a control that
mutates the rule and shows the outcome breaks. Synthetic profiles only (no person's numbers).
"""

from __future__ import annotations

import copy
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "lambdas"), str(REPO / "scripts"), str(REPO / "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import progression_sim_5861 as sim  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    fatigue_model as fm,  # noqa: E402
    live_pain,
    live_rulings as lr,
    live_safety as lsafe,
    live_stimulus,
    live_week,
)

PROFILES = sw.load_profiles()
STRESS = sw.load_profiles(REPO / "tests" / "fixtures" / "sample_week_stress_profiles_5861.json")
FIX7 = sw.load_profiles(REPO / "tests" / "fixtures" / "sample_week_stress_profiles_fix7_5861.json")
KG = 0.45359237


def _week(prof: dict, patches: dict | None = None, settings: dict | None = None) -> dict:
    with patch.dict(sw.SETTINGS, settings or {}):
        world = sw.build_world(prof, "approved")
        ps_ = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
        for p in ps_:
            p.start()
        try:
            week = sw.generate_week(prof, "approved", world)
        finally:
            for p in ps_:
                p.stop()
    return {"world": world, "week": week, "hard": sw.hard_sets_by_muscle(week, world["lib"], world["catalog"]["movements"])}


def _lift(week: dict, role: str, key: str) -> dict | None:
    s = next((s for s in week["sessions"] if s["role"] == role), None)
    return next((x for x in (s or {}).get("lifts") or [] if x["key"] == key), None)


# ── 1. the stall ratchet ─────────────────────────────────────────────────────
def _cascade_week(patches: dict | None = None) -> dict:
    """The sixth red team's reproduction: a deadlift stalled at one load for three weeks, reset 10%, and the reset week then
    performed exactly as prescribed (8 reps at RPE 8) — the next week's lower-heavy draft."""
    prof = PROFILES["a_large_deficit_experienced"] | {"trend_overrides": {"deadlift_barbell": "stalled", "squat_barbell": "stalled"}}
    world = sw.build_world(prof, "approved")
    tid = sw._tid(world["catalog"]["movements"], "deadlift_barbell")
    last = max(w["date"] for w in world["record"] if any(x["template_id"] == tid for x in w["exercises"]))
    for w in world["record"]:
        for x in w["exercises"]:
            if x["template_id"] == tid and w["date"] == last:
                top = max(s["weight_kg"] for s in x["sets"])
                x["sets"] = [{"type": "normal", "weight_kg": round(top * 0.885, 3), "reps": 8, "rpe": 8.0}] * 2
    ps_ = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
    for p in ps_:
        p.start()
    try:
        return sw.generate_week(prof, "approved", world)
    finally:
        for p in ps_:
            p.stop()


def test_a_reset_performed_as_written_is_never_reset_again():
    week = _cascade_week()
    lh = next(s for s in week["sessions"] if s["role"] == "lower_heavy")
    assert not any(ln.startswith("load (live): Deadlift (Barbell)") and "down" in ln for ln in lh["rationale"])
    assert any("rebuilding after a reset" in ln for ln in lh["rationale"])
    old = _cascade_week({(fm, "_reset_start"): lambda pts, deficit, roles=None: (None, False)})  # control: judged vs the pre-reset best
    lh = next(s for s in old["sessions"] if s["role"] == "lower_heavy")
    assert any(ln.startswith("load (live): Deadlift (Barbell)") and "down 10%" in ln for ln in lh["rationale"])


def _first_loads(rows: list[dict], key: str) -> list[float]:
    return [(r["loads"].get(key) or [0.0])[0] for r in rows]


def test_an_athlete_doing_exactly_what_is_prescribed_never_loses_load_week_over_week():
    """Six simulated weeks through the real draft path, each drafted session performed as written (the top of each range at RPE 8)
    and fed back: no anchor's prescribed load ever falls week over week — from a STALLED start (the reset happens once, in week 0,
    and the rebuild climbs). Control: the trend judged against the pre-reset best again -> the deadlift is cut a second time."""
    prof = PROFILES["a_large_deficit_experienced"] | {"trend_overrides": {"deadlift_barbell": "stalled"}, "weekly_loss_pct": 0.0}
    rows = sim.simulate(prof, 6, sim.Athlete(reps="top"))
    for key in ("deadlift_barbell", "barbell_bench_press"):
        loads = _first_loads(rows, key)
        assert all(b >= a for a, b in zip(loads, loads[1:])), (key, loads)
    with patch.object(fm, "_reset_start", lambda pts, deficit, roles=None: (None, False)):
        old = sim.simulate(prof, 3, sim.Athlete(reps="top"))
    loads = _first_loads(old, "deadlift_barbell")
    assert max(loads) <= loads[0], loads  # the ratchet: reset again every week (the cut base now holds it at the reset load)


def test_a_genuinely_stalled_lift_resets_at_most_once_per_three_post_reset_exposures():
    """A plateaued lifter (a fixed e1RM: the reps the load allows, no more), no deficit, eight weeks: the deadlift resets, rebuilds,
    and may reset again only after 3 post-reset exposures. Control: the trend judged against the pre-reset best -> it resets
    every week (the sixth red team's ratchet)."""
    prof = PROFILES["a_large_deficit_experienced"] | {"weekly_loss_pct": 0.0}
    ath = sim.Athlete(capacity={"deadlift_barbell": 225.0})
    rows = sim.simulate(prof, 8, ath)
    got = sim.resets(rows, "deadlift_barbell")
    assert got and all(b - a >= int(fm.THRESHOLDS["post_reset_min_exposures"]["value"]) for a, b in zip(got, got[1:])), got
    with patch.object(fm, "_reset_start", lambda pts, deficit, roles=None: (None, False)):  # control: judged vs the pre-reset best
        old = sim.resets(sim.simulate(prof, 8, ath), "deadlift_barbell")
    assert any(b - a < 3 for a, b in zip(old, old[1:])), (got, old)  # the ratchet: a reset every week


# ── 2. a held e1RM in a deficit is maintained, not stalled ───────────────────
def _pts(loads_reps_rpe: list[tuple[float, int, float]]) -> list[tuple]:
    days = ["2026-10-20", "2026-10-27", "2026-11-03", "2026-11-10"]
    return [(days[i], lb * (1 + r / 30), rpe, lb * KG, r) for i, (lb, r, rpe) in enumerate(loads_reps_rpe)]


def test_a_held_e1rm_at_steady_effort_in_a_deficit_holds_instead_of_resetting():
    flat = _pts([(185, 6, 8.5), (185, 6, 8.5), (185, 6, 8.5)])
    assert fm._trend(flat, deficit=True)["trend"] == "holding"
    assert fm._trend(flat, deficit=False)["trend"] == "stalled"  # outside a deficit the stall rule stands
    assert fm._trend(flat, deficit=None)["trend"] == "stalled"  # unknown is never assumed
    drift = _pts([(185, 6, 8.0), (185, 6, 8.5), (185, 6, 9.5)])
    assert fm._trend(drift, deficit=True)["trend"] == "stalled"  # rep loss / effort drift is a stall even in a deficit
    with patch.dict(fm.THRESHOLDS, {"deficit_hold_pct": {**fm.THRESHOLDS["deficit_hold_pct"], "value": -1.0}}):  # control
        assert fm._trend(flat, deficit=True)["trend"] == "stalled"
    assert fm.in_deficit({f"2026-11-{d:02d}": 250 - 0.3 * d for d in range(1, 29)}) is True
    assert fm.in_deficit({f"2026-11-{d:02d}": 250.0 for d in range(1, 29)}) is False and fm.in_deficit({}) is None
    assert "fatigue_model.THRESHOLDS.deficit_hold_pct" in lr.HEURISTIC_HOOKS


# ── 3. the lead lift by state ────────────────────────────────────────────────
def test_a_rebuilding_lift_never_leads_the_heavy_day():
    """The cascade week falls on a hinge-lead ISO week: the rebuilding deadlift cannot lead, so the squat carries RPE 8-9.
    Control: the state read off -> the calendar leads with the rebuilding deadlift and the squat is capped."""
    week = _cascade_week()
    squat = _lift(week, "lower_heavy", "squat_barbell")
    assert sw.lift_effort(squat["hevy_note"]) == 9
    lh = next(s for s in week["sessions"] if s["role"] == "lower_heavy")
    assert any("by state" in ln for ln in lh["rationale"])
    old = _cascade_week({(lr, "lead_blocked"): lambda e, trend: None})
    assert sw.lift_effort(_lift(old, "lower_heavy", "squat_barbell")["hevy_note"]) == 8


# ── 4. the pain rule acts on what provokes it ───────────────────────────────
def test_low_discomfort_touches_only_its_lift_and_the_quadriceps_stay_trained():
    r = _week(FIX7["r_three_day_knee_discomfort"])
    assert r["hard"].get("quadriceps", 0) >= 8, r["hard"]  # 2/10 knee discomfort on the squat: the legs keep their hard sets
    squat = _lift(r["week"], "lower_heavy", "squat_barbell")
    assert squat and sw.lift_effort(squat["hevy_note"]) == 8 and "stop this lift" in squat["hevy_note"]
    broad = _week(FIX7["r_three_day_knee_discomfort"], {(live_pain, "scope"): lambda flag, light, tid: "pattern"})  # control
    assert broad["hard"].get("quadriceps", 0) < r["hard"]["quadriceps"]


def test_a_mild_elbow_note_never_takes_the_chest_down():
    h = _week(STRESS["h_heavy_walker"])
    assert h["hard"].get("chest", 0) >= 8, h["hard"]


def test_a_pain_flag_finds_the_muscle_a_pain_free_route_every_session():
    q = _week(FIX7["q_two_day_shoulder_pain"])
    assert q["hard"].get("chest", 0) > 0 and q["hard"].get("triceps", 0) > 0, q["hard"]
    none = {(live_pain, "variant"): lambda *a: None, (live_pain, "muscle_route"): lambda *a, **k: None}
    lsafe_ = _week(FIX7["q_two_day_shoulder_pain"], none)  # control: no route -> the chest falls
    assert lsafe_["hard"].get("chest", 0) < q["hard"]["chest"]


# ── 5. the press family's joint ratings are consistent ───────────────────────
def test_the_press_family_is_rated_by_implement_and_pain_outcomes_follow():
    import json

    import build_exercise_library as b
    import exercise_library_input_review as targets

    mv = json.loads((REPO / "config" / "exercise_library.json").read_text())["movements"]
    for k, e in mv.items():
        kind = targets.press_implement(e)
        if kind:
            want = targets.PRESS_FAMILY_JOINTS[kind][0]["elbow"]
            assert e["joint_stress"]["elbow"] == want, (k, kind, e["joint_stress"]["elbow"])
    bad = {k: copy.deepcopy(mv[k]) for k in ("incline_bench_press_dumbbell", "bench_press_dumbbell", "bench_press_barbell")}
    bad["incline_bench_press_dumbbell"]["joint_stress"]["elbow"] = "moderate"  # the sixth red team's inconsistency
    b.apply_press_family(bad)
    assert {e["joint_stress"]["elbow"] for k, e in bad.items() if k != "bench_press_barbell"} == {"low"}
    with patch.object(targets, "press_family_joints", lambda e: None):  # control: the rule off -> the inconsistency stands
        bad["incline_bench_press_dumbbell"]["joint_stress"]["elbow"] = "moderate"
        b.apply_press_family(bad)
    assert bad["incline_bench_press_dumbbell"]["joint_stress"]["elbow"] == "moderate"


# ── 6. purposeful cardio reads the record ────────────────────────────────────
def test_a_week_short_on_recorded_aerobic_minutes_gets_purposeful_aerobic_work():
    sed = PROFILES["a_large_deficit_experienced"] | {"steps_per_day": 3000}
    w = _week(sed)["week"]
    lines = [ln for s in w["sessions"] for ln in s["rationale"]]
    assert any("purpose: the week's aerobic floor" in ln for ln in lines)
    assert not any("easy aerobic is the walking outside the gym" in ln for ln in lines)
    hard = [s for s in w["sessions"] if s["cardio"].get("kind") in ("tempo", "hills", "intervals")]
    assert len(hard) == 1  # hard_conditioning_doses default 1 (owner decision: no second hard dose by default)
    two = _week(sed, settings={"hard_conditioning_doses": 2})["week"]
    assert len([s for s in two["sessions"] if s["cardio"].get("kind") in ("tempo", "hills", "intervals")]) == 2
    with patch.object(lr, "purposeful_cardio", lambda kind, live, hk: (kind in hk, [])):  # control: the old rule
        old = _week(sed)["week"]
    assert not any(s["cardio"].get("key") and s["cardio"].get("kind") not in ("tempo", "hills", "intervals") for s in old["sessions"])


# ── 7. a fast cut with broad regression is answered with volume ──────────────
def test_a_fast_cut_with_every_lift_regressing_cuts_accessory_volume_and_keeps_loads():
    v = _week(FIX7["v_fast_loss_strength_drop"])
    lines = [ln for s in v["week"]["sessions"] for ln in s["rationale"]]
    assert any(ln.startswith("fast cut (live)") for ln in lines)
    assert not any(ln.startswith("load (live)") and "strength sliding" in ln for ln in lines)
    assert any("FAST_CUT" in ln and ln.startswith("loss rate") for ln in lines)
    off = _week(FIX7["v_fast_loss_strength_drop"], {(live_stimulus, "fast_cut"): lambda rx, sig, inputs: []})  # control
    assert any(ln.startswith("load (live)") and "strength sliding" in ln for s in off["week"]["sessions"] for ln in s["rationale"])


# ── 8. allocation: priority parity, the 3-set slot maximum ───────────────────
def test_a_priority_muscle_never_plans_under_an_isolation_muscle_and_no_slot_passes_three():
    from training import live_balance as lb

    world = sw.build_world(PROFILES["a_large_deficit_experienced"], "approved")
    plan = lb.allocation_plan(world["catalog"]["movements"], world["lib"])
    # the donor keeps MEV + donor_margin (the served week loses sets the plan cannot see): parity moves what it can, never under
    assert plan["after"]["biceps"] <= max(plan["after"]["chest"], 8 + live_stimulus.PARITY["donor_margin"]["value"] + 1)
    with patch.object(live_stimulus, "parity", lambda env, adds: []):  # control: no parity -> biceps well over the chest
        assert lb.allocation_plan(world["catalog"]["movements"], world["lib"])["after"]["biceps"] > plan["after"]["biceps"]
    r = _week(FIX7["r_three_day_knee_discomfort"])  # the 3-day week: its lateral and curl slots took 5 sets before (FIX6)
    big = [
        (x["key"], x["working_sets"])
        for s in r["week"]["sessions"]
        for x in s["lifts"]
        if x["tag"].startswith("accessory") and x["working_sets"] > 3
    ]
    assert not [k for k, n in big if "calf" not in k], big
    with patch.object(lb, "SLOT_MAX", 9):  # control: no slot maximum -> a 4+ set isolation slot
        loose = _week(FIX7["r_three_day_knee_discomfort"])
    assert [
        x
        for s in loose["week"]["sessions"]
        for x in s["lifts"]
        if x["tag"].startswith("accessory") and x["working_sets"] > 3 and "calf" not in x["key"]
    ]


# ── 9. familiar equipment swaps work at target ───────────────────────────────
def test_a_like_for_like_swap_for_an_experienced_lifter_is_not_capped_as_new():
    u = _week(FIX7["u_travel_dumbbells_only"])
    assert u["hard"].get("back", 0) >= 10, u["hard"]  # the DB row works at target: back keeps its hard sets
    off = _week(FIX7["u_travel_dumbbells_only"], {(live_week, "familiar_swap"): lambda e, ctx, w: False})  # control
    assert off["hard"].get("back", 0) < u["hard"]["back"]


# ── 10. hard-set floors, the deload's top set, the notes ─────────────────────
FLOOR_MUSCLES = ("chest", "back", "quadriceps", "hamstrings", "glutes", "calves", "shoulders", "biceps", "triceps")
"""The abs are the trunk floor's (`live_program.TRUNK_FLOOR`, a purpose-driven drill), not the week floor's."""


@pytest.mark.parametrize("name", ["a_large_deficit_experienced", "e_short_week"])
def test_every_muscle_reaches_mev_in_hard_sets_or_the_week_names_why(name):
    """A normal week: every muscle with an MEV reaches it in HARD sets (RPE >= 8), or the week's rationale names it (the floor's
    printed line); the priority muscles reach it outright. Kills the HARD_RPE 8 -> 10 mutation (the sixth red team's survivor)."""
    w = _week(PROFILES[name])
    from training import routine_generator as rg

    marks = sw.measure(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"], rg._load_json("training_landmarks.json"))[
        "landmarks"
    ]
    lines = " ".join(ln for s in w["week"]["sessions"] for ln in s["rationale"])
    for m in ("chest", "quadriceps"):
        assert w["hard"].get(m, 0) >= marks[m]["MEV"], (m, w["hard"])
    for m in FLOOR_MUSCLES:
        assert w["hard"].get(m, 0) >= marks[m]["MEV"] or f"{m} " in lines and "WEEK_FLOOR" in lines, (m, w["hard"])
    with patch.object(sw, "HARD_RPE", 10):  # control: the threshold moved -> the floors fail
        assert sw.hard_sets_by_muscle(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"]).get("chest", 0) < 8


def test_an_unconfirmed_deload_keeps_a_top_set_at_rpe_8_and_no_carry_step():
    f = _week(PROFILES["f_high_fatigue_poor_sleep"])["week"]
    anchors = [x for s in f["sessions"] for x in s["lifts"] if x["tag"].startswith("anchor:")]
    assert anchors and max(sw.lift_effort(x["hevy_note"]) for x in anchors) == live_stimulus.DELOAD_TOP_SET["rpe"]["value"]
    carries = [x for s in f["sessions"] for x in s["lifts"] if x["tag"].endswith(":carry")]
    assert carries and not any("lb per hand." in x["hevy_note"] and "+" in x["hevy_note"] for x in carries)
    with patch.object(lsafe, "_LATER_SETS", __import__("re").compile(r"on later sets")):  # control: the old step regex
        old = _week(PROFILES["f_high_fatigue_poor_sleep"])["week"]
    assert any("+10 lb per hand" in x["hevy_note"] for s in old["sessions"] for x in s["lifts"] if x["tag"].endswith(":carry"))


def test_the_live_weeks_pass_the_blocking_note_lint():
    for name in PROFILES:
        assert sw.lint_problems(_week(PROFILES[name])["week"]) == [], name
    with patch.object(
        lsafe, "coherent_head", lambda head, blocks: head.split(" · ", 1)[0] if lsafe.big_lift_conflicts(blocks, head) else head
    ):
        old = _week(PROFILES["a_large_deficit_experienced"])["week"]
    assert sw.lint_problems(old), "control: the day-only head fails L6 / L12"
    for s in _week(PROFILES["a_large_deficit_experienced"])["week"]["sessions"]:
        assert not any("block fits" in ln for ln in s["rationale"])  # never "a 20+ min block fits" above a shorter block
