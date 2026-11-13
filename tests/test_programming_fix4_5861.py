"""#5861 fourth red team (graded B-; safety C, programming C+) — the CODE/DATA fixes, gated on the GENERATED weeks.

Every gate here has a MUST-FAIL CONTROL in the same test (the guarded behaviour patched out, or the data put back as it was ->
red). Live mode = an IN-MEMORY approved copy of the library (the committed file stays `proposed`; acceptance e3 holds that).
The stress profiles (g: garage + knee pain 5/10 on the squat + a 4-day week; h: a heavy walker; i: low-back pain 2/10 on the
deadlift) are SYNTHETIC (`tests/fixtures/sample_week_stress_profiles_5861.json`). Owner decisions keep today's defaults; every
alternative is exercised here.

  1. the pain site from the note, knee + hip in the joint model     6. squat before the hinge; the heavy pull's shape setting
  2. mild pain keeps the lift lighter; an in-set stop line          7. the aerobic gap: one optional walk, fewer bolt-on rides
  3. no "+N on later sets" on a held lift or a hold day             8. the stop line: the extended wording, lifting days, the wire
  4. one effort across the session                                  9. the kettlebell slot under strain
  5. the weekly redline, at-MAV donors, the quadriceps slot, drop   10. data: band pull-up, tiers, trunk categories, the deload
     don't shave                                                        RPE cap, the cron's template lookup
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts", REPO / "deploy"):
    sys.path.insert(0, str(_p))

import exercise_library_input_review as ir  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    live_balance as lb,
    live_program as lp,
    live_safety as lsafe,
    live_shape as lshape,
    session_block as sb,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())
PROFILES = sw.load_profiles()
STRESS = sw.load_profiles(REPO / "tests" / "fixtures" / "sample_week_stress_profiles_5861.json")
ALL = PROFILES | STRESS


def _week(name: str, patches: dict | None = None, settings: dict | None = None) -> dict:
    prof = ALL[name]
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
    return {"world": world, "week": week, "m": sw.measure(week, world["lib"], world["catalog"]["movements"], LANDMARKS)}


@pytest.fixture(scope="module")
def weeks() -> dict:
    return {(n, cap): _week(n, settings={"session_cap_includes_cardio": cap}) for n in ALL for cap in (False, True)}


def _lifts(week: dict) -> list[dict]:
    return [x for s in week["sessions"] for x in s["lifts"]]


def _entry(w: dict, key: str) -> dict:
    return sw._lib_entry(w["world"]["lib"], w["world"]["catalog"]["movements"], key)


def _top_rpe(note: str | None) -> float:
    """The highest RPE a lift's note asks of it (its own effort target, else the session band it inherits)."""
    targets = lb.effort_targets(note)
    nums = [float(x) for t in targets for x in re.findall(r"\d+(?:\.\d+)?", t)]
    return max(nums) if nums else 0.0


# ── 1. the pain site, knee + hip ─────────────────────────────────────────────
def test_the_pain_note_names_the_joint():
    assert lsafe.note_site("knee pain 5/10 on the squat") == "knee"
    assert lsafe.note_site("low back pain 2/10 on the deadlift") == "spinal_load"
    assert lsafe.note_site("sharp pain in the front of the shoulder") == "shoulder"
    assert lsafe.note_site("elbow a bit sore 2/10") == "elbow"
    assert lsafe.note_site("hip pinch at the bottom") == "hip"
    assert lsafe.note_site("upper back tight, grip slipped") is None  # no named site -> the movement's worst joint (fallback)
    assert lsafe.flag_joints("felt it 4/10", ["spinal_load"], "squat") == (["spinal_load"], "squat", "inferred")
    assert lsafe.flag_joints("knee 5/10", ["spinal_load"], "hinge") == (["knee"], "squat", "note")  # a knee flag: knee group


def test_knee_and_hip_are_in_the_library_by_class_and_never_in_the_rubric():
    mv = LIB0["movements"]
    assert all({"knee", "hip"} <= set(e["joint_stress"]) for e in mv.values())
    for k in ("squat_barbell", "bulgarian_split_squat_dumbbell", "split_squat_dumbbell", "step_up", "leg_extension_machine"):
        assert mv[k]["joint_stress"]["knee"] == "high", k
    assert mv["box_squat_barbell"]["joint_stress"]["knee"] == "moderate"  # the regression a physio uses
    assert mv["romanian_deadlift_barbell"]["joint_stress"] == mv["romanian_deadlift_barbell"]["joint_stress"] | {
        "knee": "low",
        "hip": "high",
    }
    assert mv["bench_press_barbell"]["joint_stress"]["knee"] == "low"
    from training import quality_rubric as qr

    lunge = mv["bulgarian_split_squat_dumbbell"]
    assert qr.joint_penalty(lunge) == qr.joint_penalty({**lunge, "joint_stress": {**lunge["joint_stress"], "knee": "low"}})
    # control: a knee rating that reached the rubric would move the lunge's joint cost (re-tier the lower body)
    with patch.object(qr, "RUBRIC_JOINTS", qr.RUBRIC_JOINTS + ("knee",)):
        assert qr.joint_penalty(lunge) != qr.joint_penalty({**lunge, "joint_stress": {**lunge["joint_stress"], "knee": "low"}})
    toy = {"x": {"title": "Reverse Lunge (Dumbbell)", "pattern": "squat", "job": "compound", "target": {"region": "lower"}}}
    assert ir.apply_class_rules(toy)["knee_hip"] == ["x"] and toy["x"]["joint_stress"]["knee"] == "high"


def knee_breaches(w: dict) -> list[str]:
    """A knee-pain week's breaches: a high-knee-stress lift served at all, or any knee-loading (moderate+) lift above RPE 7."""
    out = []
    for s in w["week"]["sessions"]:
        for x in s["lifts"]:
            knee = str((_entry(w, x["key"]).get("joint_stress") or {}).get("knee"))
            if knee == "high" or (knee == "moderate" and _top_rpe(x["hevy_note"]) > 7):
                out.append(f"{s['role']}: {x['key']} knee {knee} @ RPE {_top_rpe(x['hevy_note']):g}")
    return out


def test_a_knee_flag_reduces_or_avoids_every_knee_dominant_pattern(weeks):
    """Stress case g (knee pain 5/10 on the squat): no high-knee pattern served, every knee-loading lift at RPE <= 7. Control: the
    note's site ignored (the old worst-joint inference) -> the flag reads 'spinal load' and lunges stay at RPE 8-9."""
    for cap in (False, True):
        g = weeks[("g_knee_pain_garage_short", cap)]
        assert knee_breaches(g) == [], cap
        assert any("(knee, 5/10)" in ln for s in g["week"]["sessions"] for ln in s["rationale"])
    old = _week("g_knee_pain_garage_short", {(lsafe, "note_site"): lambda note: None})
    assert knee_breaches(old)


# ── 2. mild pain keeps the lift lighter; the in-set stop line ────────────────
def test_mild_pain_keeps_the_movement_lighter_with_a_stop_line(weeks):
    """Stress case i (low back 2/10 on the deadlift): PAIN_RULE's mild line keeps the deadlift — 10% lighter, RPE <= 7 — and its
    note says when to stop. Control: the old exclusion (any pain-class note swaps) -> the deadlift is not served."""
    i = weeks[("i_mild_pain_low_back", False)]["week"]
    lh = next(s for s in i["sessions"] if s["role"] == "lower_heavy")
    dl = next(x for x in lh["lifts"] if x["key"] == "deadlift_barbell")
    assert _top_rpe(dl["hevy_note"]) <= 7 and "Pain past 2/10 or sharp → stop this lift." in dl["hevy_note"]
    assert any(ln.startswith("load (live): Deadlift (Barbell)") and "down 10%" in ln for ln in lh["rationale"])
    old = _week("i_mild_pain_low_back", {(lsafe, "blocked_pain_is_mild"): lambda entry, ctx: False})
    assert "deadlift_barbell" not in {x["key"] for x in next(s for s in old["week"]["sessions"] if s["role"] == "lower_heavy")["lifts"]}


def unstopped(week: dict) -> list[str]:
    """Lifts the pain rule touched (reduced or swapped in under a flag) whose note carries no in-set stop line."""
    out = []
    for s in week["sessions"]:
        touched = {ln.split("(live): ", 1)[1].split(" — ")[0] for ln in s["rationale"] if ln.startswith("reduced (live): ")}
        touched |= {
            ln.split(" -> ", 1)[1].split(" — ")[0] for ln in s["rationale"] if ln.startswith("swapped (live): ") and " flag on " in ln
        }
        out += [
            f"{s['role']}: {x['key']}" for x in s["lifts"] if x["title"] in touched and "→ stop this lift." not in (x["hevy_note"] or "")
        ]
    return out


def test_every_pain_flagged_lift_carries_an_in_set_stop_line(weeks):
    for key in [k for k in weeks if k[0] in ("b_shoulder_flag_low_recovery", "g_knee_pain_garage_short", "i_mild_pain_low_back")]:
        assert unstopped(weeks[key]["week"]) == [], key
    off = _week("g_knee_pain_garage_short", {(lsafe, "stop_line"): lambda severity: ""})  # control: no stop line
    assert unstopped(off["week"])


# ── 3. no load step on a held lift or a hold day ─────────────────────────────
def _held(s: dict) -> set[str]:
    out = set()
    for ln in s["rationale"]:
        for head in ("load (live): ", "reduced (live): ", "stall (live): ", "one cut a week (live): "):
            if ln.startswith(head):
                out.add(re.split(r" \d[\d.]* lb -> | — ", ln[len(head) :])[0])
        if ln.startswith("swapped (live): ") and " flag on " in ln:
            out.add(ln.split(" -> ", 1)[1].split(" — ")[0])
    return out


def stepping_held(week: dict) -> list[str]:
    """A "+N on later sets" line that reaches a held lift: on its own note, or — on exercise 1 — the session rule not addressed to
    the OTHER lifts; on a hold day (strain, overreach, a recommended deload) any step line at all."""
    out = []
    for s in week["sessions"]:
        fat = s.get("fatigue") or {}
        hold = fat.get("state") in ("strained", "overreached") or fat.get("action") == "deload_recommended"
        held = _held(s)
        for i, x in enumerate(s["lifts"]):
            block, own = sb.split(x["hevy_note"])
            if hold and "on later sets" in (x["hevy_note"] or ""):
                out.append(f"{s['role']}: {x['key']} steps on a hold day")
            elif x["title"] in held and "on later sets" in own:
                out.append(f"{s['role']}: {x['key']} held, own step line")
            elif i == 0 and x["title"] in held and sb.LOAD_RULE_HEAD in block:
                out.append(f"{s['role']}: {x['key']} held under the session's step rule")
            elif i > 0 and x["title"] in held and not hold and x["working_sets"] >= 2 and re.fullmatch(r"\d+(-\d+)?", x["reps"] or ""):
                if lsafe.NO_STEP_LINE not in own:  # the session rule still addresses the lifts: a held one says it stays
                    out.append(f"{s['role']}: {x['key']} held, no '{lsafe.NO_STEP_LINE}'")
    return out


def test_no_held_lift_or_hold_day_carries_an_in_session_load_step(weeks):
    """Fourth red team: the session rule ("Top reps at RPE 7 or less → +10 lb on later sets") headed exercise 1 on deload days,
    stall resets and pain cuts — undoing the cut it sat under. Control: the rule fitted to nothing -> back on the held lifts."""
    for key, w in weeks.items():
        assert stepping_held(w["week"]) == [], key
    f = weeks[("f_high_fatigue_poor_sleep", False)]["week"]
    assert all(lsafe.HOLD_DAY_LINE in s["lifts"][0]["hevy_note"] for s in f["sessions"])
    off = {(lsafe, "no_step"): lambda blocks, rx: [], (lsafe, "block_rule"): lambda block, rx, blocks: block}
    assert stepping_held(_week("f_high_fatigue_poor_sleep", off)["week"])
    assert stepping_held(_week("i_mild_pain_low_back", off)["week"])


# ── 4. one effort across the session ────────────────────────────────────────
def session_conflicts(week: dict) -> list[str]:
    """The session line's band against every big lift's (anchor's) own effort target, across the WHOLE session — the generator's
    own measure (`sample_weeks_5861._session_effort_conflicts`, over `live_safety.big_lift_conflicts`)."""
    return sw._session_effort_conflicts(week)


def test_the_session_line_never_contradicts_a_big_lift(weeks):
    for key, w in weeks.items():
        assert session_conflicts(w["week"]) == [], key
    head = "Lower heavy · RPE 7 on big lifts"
    two = [SimpleNamespace(movement_key="a", notes=f"{head}\n{sb.LOW_ENERGY_LINE}", rationale_tag="anchor:squat:heavy")]
    two.append(SimpleNamespace(movement_key="b", notes="RPE 8–9", rationale_tag="anchor:hinge:heavy"))
    assert lsafe.big_lift_conflicts(two) and lsafe.coherent_head(head, two) == "Lower heavy"  # the red team's own morning
    off = {
        (lsafe, "coherent_effort"): lambda blocks, rx: None,
        (lsafe, "fix_block"): lambda block, rx, blocks: lsafe.block_rule(block, rx, blocks),
    }
    assert session_conflicts(_week("g_knee_pain_garage_short", off)["week"])  # control: the per-lift guard only


# ── 5. volume ────────────────────────────────────────────────────────────────
def over_redline(week: dict) -> int:
    """Working sets over the owner's weekly redline (owner_redlines total_hard_sets_wk); 0 = inside it."""
    return max(0, sum(x["working_sets"] for x in _lifts(week)) - lshape.week_redline())


def test_the_week_never_passes_the_weekly_hard_set_redline(weeks):
    assert lshape.week_redline() == 75
    for key, w in weeks.items():
        assert over_redline(w["week"]) == 0, key
    one_over = copy.deepcopy(weeks[("a_large_deficit_experienced", False)]["week"])  # control 1: 76 must fail
    total = sum(x["working_sets"] for x in _lifts(one_over))
    one_over["sessions"][0]["lifts"][0]["working_sets"] += 76 - total
    assert over_redline(one_over) == 1
    raw = _week("a_large_deficit_experienced", {(lshape, "week_ceiling"): lambda env, adds: []})  # control 2: no ceiling
    assert over_redline(raw["week"]) > 0


def singles(week: dict) -> list[str]:
    return [
        f"{s['role']}: {x['key']}"
        for s in week["sessions"]
        for x in s["lifts"]
        if str(x["tag"]).startswith("accessory:") and not str(x["tag"]).endswith(":carry") and x["working_sets"] == 1
    ]


def test_trims_drop_whole_accessories_never_leaving_one_set(weeks):
    for key, w in weeks.items():
        assert singles(w["week"]) == [], key
    blocks = [SimpleNamespace(movement_key="x", rationale_tag="accessory:x:accessory", sets=[SimpleNamespace(type="normal", reps=10)])]
    assert lshape.no_single_sets(blocks, {}) == ["x"] and blocks == []

    def old_costs(rx, ctx):  # control: the reduce trim may take isolation to ONE set, and nothing sweeps it
        for e in rx.get("exposures") or []:
            e["live_cost"] = lp.fatigue_cost(e, ctx)
            if e["live_cost"] != "low":
                e["live_min_sets"] = 2

    off = _week("b_shoulder_flag_low_recovery", {(lp, "mark_costs"): old_costs, (lshape, "no_single_sets"): lambda b, m: []})
    assert singles(off["week"])


def test_priority_muscles_take_sets_from_muscles_at_mav_and_the_quadriceps_get_their_isolation(weeks):
    a = weeks[("a_large_deficit_experienced", False)]
    lm = a["m"]["landmarks"]
    assert lm["shoulders"]["sets"] < lm["shoulders"]["MAV"] and lm["biceps"]["sets"] < lm["biceps"]["MAV"]
    lv = next(s for s in a["week"]["sessions"] if s["role"] == "lower_volume")
    assert "leg_extension_machine" in {x["key"] for x in lv["lifts"]}  # his history shows it; the gym has it
    plan = lb.allocation_plan(CAT0, copy.deepcopy(LIB0))
    assert plan["after"]["quadriceps"] > plan["before"]["quadriceps"] and plan["after"]["chest"] > plan["before"]["chest"]
    with patch.dict(lshape.QUAD_SLOT, {"history_min": 10**6}):  # control: no history -> no quadriceps slot
        assert not lb.allocation_plan(CAT0, copy.deepcopy(LIB0))["adds"]
    with patch.dict(lshape.VOLUME, {"at_mav_give": {"value": 0}}), patch.dict(lshape.QUAD_SLOT, {"history_min": 10**6}):
        # control: muscles AT their MAV give nothing -> the old allocation (only over-MAV sets move)
        assert lb.allocation_plan(CAT0, copy.deepcopy(LIB0))["after"]["shoulders"] >= plan["after"]["shoulders"]


# ── 6. order and the heavy pull ──────────────────────────────────────────────
def test_lower_volume_squats_before_the_hinge(weeks):
    for key, w in weeks.items():
        for s in w["week"]["sessions"]:
            if s["role"] != "lower_volume":
                continue
            pats = [_entry(w, x["key"]).get("pattern") for x in s["lifts"] if str(x["tag"]).startswith("anchor:")]
            if "squat" in pats and "hinge" in pats:
                assert pats.index("squat") < pats.index("hinge"), key
    off = _week("a_large_deficit_experienced", {(lshape, "order_lower_volume"): lambda rx: []})  # control: the template order
    lv = next(s for s in off["week"]["sessions"] if s["role"] == "lower_volume")
    assert lv["lifts"][0]["key"] == "romanian_deadlift_barbell"


def test_the_heavy_day_deadlift_shape_is_a_setting(weeks):
    def dl(week):
        lh = next(s for s in week["sessions"] if s["role"] == "lower_heavy")
        return next(x for x in lh["lifts"] if x["key"] == "deadlift_barbell"), {x["key"] for x in lh["lifts"]}

    today, keys = dl(weeks[("a_large_deficit_experienced", False)]["week"])
    assert lshape.SETTINGS_DEFAULTS["heavy_day_deadlift_shape"] == "as_today" and today["working_sets"] == 3
    alt, keys2 = dl(_week("a_large_deficit_experienced", settings={"heavy_day_deadlift_shape": "top_plus_backoff"})["week"])
    assert alt["working_sets"] == 2 and "squat_barbell" in keys2  # top + one back-off; the pairing stays (#5694)


# ── 7. the aerobic gap ───────────────────────────────────────────────────────
def _walks(week: dict) -> list[str]:
    return [s["role"] for s in week["sessions"] if any("Optional today: brisk walk" in (x["hevy_note"] or "") for x in s["lifts"][:1])]


def test_an_uncovered_aerobic_gap_becomes_one_optional_walk_never_silence(weeks):
    """Shared cap, a heavy walker (h): the gap after steps and the one block is closed by ONE optional walk on the conditioning
    host's morning (exercise 1's note), never a lifting cut. Control: the prompt off -> a silent shortfall."""
    h = weeks[("h_heavy_walker", True)]["week"]
    assert _walks(h) == ["shoulders_arms"]
    assert any(ln.startswith("walk (live): optional brisk walk") for s in h["sessions"] for ln in s["rationale"])
    off = _week("h_heavy_walker", {(lshape, "walk_prompt"): lambda live, today_minutes=0: []}, {"session_cap_includes_cardio": True})
    assert _walks(off["week"]) == []


def test_under_the_default_cap_a_small_gap_is_the_walks_not_another_ride(weeks):
    def easy(week):
        return sum(1 for s in week["sessions"] if s["cardio"].get("kind") and s["cardio"]["kind"] not in lp.HARD_KINDS)

    h = weeks[("h_heavy_walker", False)]["week"]
    more = _week("h_heavy_walker", {(lshape, "walk_covers"): lambda kind, live: None})["week"]  # control: rides close every gap
    assert easy(h) < easy(more)
    assert lshape.walk_covers("easy", {"settings": {"session_cap_includes_cardio": True}, "aerobic": {"walking_min_per_wk": 140}}) is None
    import inspect

    from training import cardio_model

    assert "HEURISTIC" in inspect.getsource(cardio_model).split("STEPS_CREDIT_SHARE = ", 1)[1][:200]  # the credit stays labelled


# ── 8. the stop line ─────────────────────────────────────────────────────────
def _cardio_wire_notes(week: dict, hard_only: bool = True) -> list[str]:
    """The conditioning notes as COMPILED for Hevy (`hevy_compiler.to_create_body`, the payload the nightly cron and the MCP write
    path send — the generator compiles with the cron's own template lookup); `hard_only`: the hard (conditioning) blocks."""
    out = []
    for s in week["sessions"]:
        if hard_only and s["cardio"].get("kind") not in lp.HARD_KINDS:
            continue
        out += [e.get("notes") or "" for e in s["wire"] if any(st.get("duration_seconds") for st in e.get("sets") or [])]
    return out


def test_the_stop_line_reaches_the_hevy_payload_and_the_extended_wording_works():
    default = lp.SETTINGS_DEFAULTS["symptom_line"]
    assert default == "Chest, breathing, dizzy? Stop, log it."  # the owner's wording, unchanged
    a = _week("a_large_deficit_experienced")["week"]
    hard = _cardio_wire_notes(a)
    assert hard and all(default in n for n in hard)
    ext = _week("a_large_deficit_experienced", settings={"symptom_line": "extended"})["week"]
    notes = _cardio_wire_notes(ext)
    assert any("heart racing or irregular" in n and "Doesn't settle → get medical help." in n for n in notes)
    lifting = _week("a_large_deficit_experienced", settings={"symptom_line_on_lifting_days": True})["week"]
    assert all(default in (s["wire"][0].get("notes") or "") for s in lifting["sessions"])  # exercise 1 of every morning
    off = _week("a_large_deficit_experienced", settings={"symptom_line": ""})["week"]  # control: the line removed
    assert not any(default in n for n in _cardio_wire_notes(off))


# ── 9. the kettlebell slot under strain ──────────────────────────────────────
def test_the_kettlebell_slot_under_strain_is_a_setting(weeks):
    f = weeks[("f_high_fatigue_poor_sleep", False)]["week"]
    assert "kettlebell_deadlift" in {x["key"] for x in _lifts(f)}  # today's default: the slot follows its placement
    drop = _week("f_high_fatigue_poor_sleep", settings={"kb_slot_under_strain": "drop"})["week"]
    assert "kettlebell_deadlift" not in {x["key"] for x in _lifts(drop)}
    assert any("kb_slot_under_strain=drop" in ln for s in drop["sessions"] for ln in s["rationale"])
    a = _week("a_large_deficit_experienced", settings={"kb_slot_under_strain": "drop"})["week"]  # control: a fresh week keeps it
    assert "kettlebell_deadlift" in {x["key"] for x in _lifts(a)}


# ── 10. data and test fidelity ───────────────────────────────────────────────
def test_the_band_pull_up_is_a_built_in_vertical_pull():
    assert CAT0["pull_up_band"]["hevy_template_id_hint"] == "56808FD2" and CAT0["pull_up_band"]["is_custom"] is False
    assert CAT0["pull_up_band"]["anchor_family"] == "vertical_pull"
    e = LIB0["movements"]["pull_up_band"]
    assert e["template_id"] == "56808FD2" and e["gates"] == [] and e["objective_inputs"]["reviewed"]


def test_the_generous_tiers_and_the_trunk_categories_are_corrected_at_their_inputs():
    mv = LIB0["movements"]
    tier = lambda k, o: (mv[k]["ratings"][o] or {}).get("tier")  # noqa: E731
    assert tier("landmine_press", "hypertrophy") == "A" and tier("landmine_press_single_arm", "hypertrophy") == "A"
    assert tier("trap_pulldown", "hypertrophy") == "A"
    assert tier("sled_push", "strength") == "B" and tier("sled_drag", "strength") == "B"
    assert tier("walking", "conditioning") == "C" and tier("treadmill", "conditioning") == "A"  # rechecked: incline is the difference
    assert mv["pallof_press"]["category"] == "rehab_control" and mv["pallof_press"]["trunk_function"] == "anti_rotation"
    assert mv["ab_wheel"]["category"] == "hypertrophy" and mv["ab_wheel"]["trunk_function"] == "anti_extension"


def test_the_deload_caps_every_compound_at_rpe_7(weeks):
    """The third red team's M3 survivor: DELOAD_SHAPE compound_rpe 7 -> 9 passed every test. Control: the cap moved -> red."""

    def over(week):
        return [
            f"{s['role']}: {x['key']}"
            for s in week["sessions"]
            for x in s["lifts"]
            if str(x["tag"]).startswith("anchor:") and _top_rpe(x["hevy_note"]) > lp.DELOAD_SHAPE["compound_rpe"]["value"]
        ]

    f = weeks[("f_high_fatigue_poor_sleep", False)]["week"]
    assert all(s["fatigue"]["action"] == "deload_recommended" for s in f["sessions"]) and over(f) == []
    assert lp.DELOAD_SHAPE["compound_rpe"]["value"] == 7
    with patch.dict(lp.DELOAD_SHAPE, {"compound_rpe": {"value": 9, "label": "heuristic", "basis": "mutated"}}):
        moved = _week("f_high_fatigue_poor_sleep")["week"]
    assert over(moved)  # control: the mutated cap lets a compound past RPE 7


def test_the_sample_wire_uses_the_nightly_jobs_template_lookup(weeks):
    """The generator compiles with the cron's lookup (`hevy_template_cache.resolve_movement` behind the KB template setting), so
    no catalog KEY reaches the wire as a template id. Control: the base harness's simplified lookup -> 'reverse_pec_deck' does."""
    ids = {e.get("exercise_template_id") for w in weeks.values() for s in w["week"]["sessions"] for e in s["wire"]}
    assert ids and not ids & set(CAT0)
    sw.RESOLVER["mode"] = "legacy"
    try:
        old = _week("a_large_deficit_experienced")["week"]
    finally:
        sw.RESOLVER["mode"] = "cron"
    assert {e.get("exercise_template_id") for s in old["sessions"] for e in s["wire"]} & set(CAT0)


def test_every_fix4_constant_is_labelled_and_every_default_is_todays():
    for table in (lshape.VOLUME, lshape.WALK_PROMPT):
        assert all(v["label"] == "heuristic" and v["basis"] for v in table.values())
    assert lshape.QUAD_SLOT["label"] == "heuristic" and lsafe.STOP_LINE["label"] == "heuristic"
    assert lsafe.SETTINGS_DEFAULTS == {"symptom_line_on_lifting_days": False}
    assert lshape.SETTINGS_DEFAULTS == {"heavy_day_deadlift_shape": "as_today", "kb_slot_under_strain": "as_today"}
    assert LIB0["status"] == "proposed"
