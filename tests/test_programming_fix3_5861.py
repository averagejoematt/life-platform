"""#5861 third red team (2026-11-13, graded B-) — the CODE/DATA fixes, gated on the generated weeks and realistic histories.

Every gate here has a MUST-FAIL CONTROL in the same test (the guarded behaviour patched out, or the data put back as it was ->
red). Live mode = an IN-MEMORY approved copy of the library (the committed file stays `proposed`; acceptance e3 holds that).
The owner's open decisions are settings with today's defaults (`live_balance.SETTINGS_DEFAULTS`, `live_program.SETTINGS_DEFAULTS`);
each alternative is exercised here so it is known to work.

  1. shoulder pain map: abduction / rear-delt / rotation work >= moderate shoulder stress (a class rule), the persistence line
  2. volume by priority (acceptance d1 holds the drafted weeks)
  3. one spine-loading definition, the kettlebell slot's placement (acceptance d2b holds the drafted weeks)
  4. one S per canonical family per objective
  5. outcome gates (acceptance b2, b3, c2c, d3, d5)
  6. one effort target per lift on every generated note
  7. the adherence dip on a realistic history
  8. the conservative steps credit
  9. the garage leg curl from the library pattern
 10. cardio host and machine, the owner settings (KB template, rate band, symptom wording)
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
from collections import Counter
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts", REPO / "deploy"):
    sys.path.insert(0, str(_p))

import exercise_library_input_review as ir  # noqa: E402
import exercise_library_reviews as reviews  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    cardio_model as cm,
    exercise_library as xl,
    kb_entry,
    live_balance as lb,
    live_program as lp,
    live_week as lw,
    program_structure as ps,
    quality_rubric as qr,
    selection_engine as se,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())
PROFILES = sw.load_profiles()


def _week(name: str, patches: dict | None = None, settings: dict | None = None, record=None) -> dict:
    prof = PROFILES[name]
    with patch.dict(sw.SETTINGS, settings or {}):
        world = sw.build_world(prof, "approved")
        if record is not None:
            world = world | {"record": record(world["record"], prof)}
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
    return {(n, cap): _week(n, settings={"session_cap_includes_cardio": cap}) for n in PROFILES for cap in (False, True)}


def _lifts(week: dict) -> list[dict]:
    return [x for s in week["sessions"] for x in s["lifts"]]


# ── 1. the shoulder pain map ─────────────────────────────────────────────────
def shoulder_unrated(lib: dict) -> list[str]:
    """Abduction / rear-delt / rotation rows whose shoulder stress is under moderate (a shoulder flag would not reach them)."""
    return sorted(
        k
        for k, e in xl.movements(lib).items()
        if e.get("pattern") in ir.SHOULDER_PROVOKING["patterns"]
        and (e.get("joint_stress") or {}).get("shoulder") not in ("moderate", "high")
    )


def test_shoulder_provoking_work_reaches_the_pain_rule_and_keeps_its_healthy_joint_cost():
    assert shoulder_unrated(LIB0) == []
    for k in ("lateral_raise_dumbbell", "lateral_raise_machine", "face_pull", "rear_delt_reverse_fly_machine", "upright_row_barbell"):
        assert LIB0["movements"][k]["joint_stress"]["shoulder"] in ("moderate", "high"), k
    # the floor is a PAIN-MAP rating: the rubric's joint-cost term reads the reviewed healthy-joint rating, so no tier moved
    dbl = LIB0["movements"]["lateral_raise_dumbbell"]
    assert dbl["provocation_floor"]["shoulder"]["from"] == "low" and qr.joint_penalty(dbl) == 0
    assert dbl["ratings"]["hypertrophy"]["tier"] == "B"
    assert qr.joint_penalty({k: v for k, v in dbl.items() if k != "provocation_floor"}) == -1  # control: without it, -1
    bad = copy.deepcopy(LIB0)  # control: the data as it was (a lateral raise rated low) -> named
    bad["movements"]["lateral_raise_machine"]["joint_stress"]["shoulder"] = "low"
    assert shoulder_unrated(bad) == ["lateral_raise_machine"]
    # the class rule raises it again (and never lowers a high)
    mv = {"x": {"title": "Lateral Raise (Cable)", "pattern": "lateral_raise", "joint_stress": {"shoulder": "low"}}}
    mv["y"] = {"title": "Dip", "pattern": "lateral_raise", "joint_stress": {"shoulder": "high"}}
    assert ir.apply_class_rules(mv)["shoulder_provoking"] == ["x"] and mv["y"]["joint_stress"]["shoulder"] == "high"


def test_a_pain_flag_carries_the_persistence_line_and_the_setting_turns_it_off(weeks):
    b = weeks[("b_shoulder_flag_low_recovery", False)]["week"]
    line = lb.SETTINGS_DEFAULTS["pain_assess_line"]
    for s in b["sessions"]:
        notes = [x["hevy_note"] or "" for x in s["lifts"]]
        assert sum(n.split("\n").count(line) for n in notes) == 1, s["role"]  # once a session, on a lift
        assert any(ln.startswith("pain (live):") for ln in s["rationale"]), s["role"]
    assert not any(line in (x["hevy_note"] or "") for x in _lifts(weeks[("a_large_deficit_experienced", False)]["week"]))  # no flag
    off = _week("b_shoulder_flag_low_recovery", settings={"pain_assess_line": ""})  # control: the owner turns it off
    assert not any(line in (x["hevy_note"] or "") for x in _lifts(off["week"]))


# ── 2. volume by priority ────────────────────────────────────────────────────
def test_the_week_is_allocated_by_priority_before_any_muscle_sits_over_mav():
    lib = copy.deepcopy(LIB0)
    plan = lb.allocation_plan(CAT0, lib)
    marks = LANDMARKS["muscles"]
    assert plan["before"]["shoulders"] > marks["shoulders"]["MAV"]  # the template's delt spread (the red team's 18)
    assert plan["after"]["shoulders"] <= marks["shoulders"]["MAV"]
    assert all(plan["after"][m] >= marks[m]["MEV"] for m in ("chest", "back", "quadriceps", "hamstrings"))
    assert plan["after"]["chest"] > plan["before"]["chest"]  # the freed sets went to the priority muscle at MEV + 1
    assert all(d < 0 for (r, slot), d in plan["deltas"].items() if slot in ("face_pull", "db_lateral_raise", "reverse_pec_deck"))
    # setting: the owner may make the delts a priority muscle (it is his split) — the freed sets then never go to chest first
    shoulders_first = copy.deepcopy(lib)
    shoulders_first["programming_settings"] = {**(lib.get("programming_settings") or {}), "priority_muscles": ["shoulders"]}
    assert lb.allocation_plan(CAT0, shoulders_first)["after"]["chest"] == plan["before"]["chest"]
    # control: no slot may give (and #5861 FIX4's weekly redline, which may drop a whole slot, off) -> delts stay over MAV
    with patch.dict(lb.ALLOCATION, {"over_mav_floor": {"value": 99}}), patch("training.live_shape.week_ceiling", lambda env, adds: []):
        assert lb.allocation_plan(CAT0, lib)["after"]["shoulders"] > marks["shoulders"]["MAV"]


# ── 3. one spine-loading definition; the kettlebell slot ─────────────────────
def test_the_kettlebell_slot_moves_off_a_stacked_session_by_setting(weeks):
    a = weeks[("a_large_deficit_experienced", False)]["week"]
    where = {s["role"]: {x["key"] for x in s["lifts"]} for s in a["sessions"]}
    assert "kettlebell_deadlift" in where["shoulders_arms"] and "kettlebell_deadlift" not in where["lower_volume"]
    shared = weeks[("a_large_deficit_experienced", True)]["week"]  # the shared cap keeps shoulders+arms for the aerobic block
    where = {s["role"]: {x["key"] for x in s["lifts"]} for s in shared["sessions"]}
    assert "kettlebell_deadlift" in where["upper_volume"]
    drop = _week("a_large_deficit_experienced", settings={"kb_slot_when_stacked": "drop"})["week"]  # the alternative works
    assert "kettlebell_deadlift" not in {x["key"] for x in _lifts(drop)}
    assert any(ln.startswith("dropped (live): Sumo Deadlift") for s in drop["sessions"] for ln in s["rationale"])
    home = _week("a_large_deficit_experienced", settings={"kb_slot_role": "upper_volume"})["week"]  # a placement the owner picks
    assert "kettlebell_deadlift" in {x["key"] for s in home["sessions"] if s["role"] == "upper_volume" for x in s["lifts"]}
    for w in (a, shared, drop, home):  # every alternative keeps lower volume at two spine-loading lifts
        lv = next(s for s in w["sessions"] if s["role"] == "lower_volume")
        lib = LIB0
        assert sum(1 for x in lv["lifts"] if lb.spine_loading(sw._lib_entry(lib, CAT0, x["key"]))) <= 2
    # control: placement off -> the stacking rule must DROP the pinned third hinge (no "kept light" exemption any more)
    off = _week("a_large_deficit_experienced", {(lb, "place_kb"): lambda rx, ctx, workouts: []})["week"]
    lv = next(s for s in off["sessions"] if s["role"] == "lower_volume")
    assert "kettlebell_deadlift" not in {x["key"] for x in lv["lifts"]}
    assert any("the third spine-loading lift" in ln for ln in lv["rationale"])


def test_the_kb_template_setting_writes_the_slot_under_his_custom_template():
    approved = copy.deepcopy(LIB0)
    approved["status"] = "approved"
    base = lambda k: str((CAT0.get(k) or {}).get("hevy_template_id_hint") or k)  # noqa: E731
    assert lb.template_resolver(base, approved) is base  # default (None): today's Sumo Deadlift stand-in, the resolver itself
    custom = copy.deepcopy(approved)
    custom["programming_settings"] = {**(custom.get("programming_settings") or {}), "kb_deadlift_template_id": "C0FFEE01"}
    r = lb.template_resolver(base, custom)
    assert r(kb_entry.ENTRY) == "C0FFEE01" and r("squat_barbell") == base("squat_barbell")
    assert lb.kb_note_line(custom) == "KB deadlift — one kettlebell." and "Sumo" in lb.kb_note_line(approved)
    proposed = copy.deepcopy(custom)
    proposed["status"] = "proposed"
    assert lb.template_resolver(base, proposed) is base  # control: never while the library is proposed (shadow untouched)
    rec = [{"date": "2026-11-12", "exercises": [{"template_id": "C0FFEE01", "sets": [{"reps": 8, "weight_kg": 24}]}]}]
    assert kb_entry.exposures(rec, "2026-11-20") == 0  # the stand-in count alone does not see his custom template
    assert lb.kb_exposures(rec, "2026-11-20", custom) == 1 and lb.kb_exposures(rec, "2026-11-20", approved) == 0


# ── 4. S rarity ──────────────────────────────────────────────────────────────
def quota_violations(lib: dict) -> list[str]:
    """Canonical families with more than one S per objective (per target for hypertrophy) among real variants — an exact
    duplicate (another Hevy template of one movement) shares its canonical's rating."""
    seen: dict[tuple, list[str]] = {}
    for k, e in xl.movements(lib).items():
        if isinstance(e.get("variant"), dict) and "duplicate_of" in e["variant"]:
            continue
        fam = str(e.get("canonical") or k)
        r = e.get("ratings") or {}
        for t, tier in ((r.get("hypertrophy") or {}).get("by_target") or {}).items():
            if tier == "S":
                seen.setdefault(("hypertrophy", fam, t), []).append(k)
        for o in ("strength", "functional", "conditioning", "mobility"):
            if (r.get(o) or {}).get("tier") == "S":
                seen.setdefault((o, fam), []).append(k)
    return sorted(f"{'/'.join(key)}: {v}" for key, v in seen.items() if len(v) > 1)


def s_counts(lib: dict) -> dict[str, int]:
    out = Counter()
    for e in xl.movements(lib).values():
        r = e.get("ratings") or {}
        out["hypertrophy"] += sum(1 for t in ((r.get("hypertrophy") or {}).get("by_target") or {}).values() if t == "S")
        for o in ("strength", "functional", "conditioning", "mobility"):
            out[o] += int((r.get(o) or {}).get("tier") == "S")
    return dict(out)


def test_one_s_per_canonical_family_per_objective():
    assert quota_violations(LIB0) == []
    # before -> after (FIX3): hypertrophy 49 -> 34, strength 10 -> 10, functional 10 -> 9 (exact duplicates share one rating)
    # FIX4 -3: the landmine presses and the trap pulldown read a moderate load ceiling (fourth red team: generous S)
    assert s_counts(LIB0) == {"hypertrophy": 31, "strength": 10, "functional": 9, "conditioning": 0, "mobility": 0}
    pull = LIB0["movements"]["lat_pulldown_close_grip_cable"]
    assert pull["ratings"]["hypertrophy"]["tier"] == "A" and any("S quota" in b for b in pull["ratings"]["hypertrophy"]["basis"])
    assert LIB0["movements"]["lat_pulldown_cable"]["ratings"]["hypertrophy"]["tier"] == "S"  # the family's one S
    # the rating stays the rubric's derivation (a hand-edited tier is a schema error)
    assert qr.rating_problems(pull) == [] and qr.derivation_problems(pull, pull["hypertrophy"][0]) == []
    bad = copy.deepcopy(LIB0)  # control: the quota line removed from one variant -> it derives S again -> two S in a family
    e = bad["movements"]["lat_pulldown_close_grip_cable"]
    e["hypertrophy"] = [qr.finalize_row(e, {k: v for k, v in r.items() if k != "s_quota"}) for r in e["hypertrophy"]]
    e["ratings"] = qr.objective_ratings(e)
    assert quota_violations(bad) and e["ratings"]["hypertrophy"]["tier"] == "S"
    # the builder's pass is idempotent: re-running it over the shipped rows changes nothing
    mv = copy.deepcopy(LIB0["movements"])
    reviews.apply_s_quota(mv)
    for k in ("lat_pulldown_close_grip_cable", "lat_pulldown_cable", "military_press", "kettlebell_suitcase_carry"):
        assert mv[k]["hypertrophy"] == LIB0["movements"][k]["hypertrophy"] and mv[k].get("s_quota") == LIB0["movements"][k].get(
            "s_quota"
        ), k


# ── 6. one effort target per lift ────────────────────────────────────────────
def contradictory(week: dict) -> list[str]:
    return [
        f"{s['role']}: {x['key']} {lb.effort_targets(x['hevy_note'])}"
        for s in week["sessions"]
        for x in s["lifts"]
        if len(lb.effort_targets(x["hevy_note"])) > 1
    ]


def test_every_generated_note_states_one_effort_target_per_lift(weeks):
    for key, w in weeks.items():
        assert contradictory(w["week"]) == [], key
    assert lb.effort_targets("Upper heavy · RPE 8–9 on big lifts\nLow energy → first 2 lifts + easy cardio.\n\nRPE 6–7") == ["8–9", "6–7"]
    assert lb.effort_targets("RPE 8–9, last set RPE 9–10\nSet 1: 6 reps at RPE 7 or less → +10 lb.") == ["8–9"]  # a rule is no target
    # control: the WHY header left as composed -> the red team's first phone note ("RPE 8–9 on big lifts" ... "RPE 6–7")
    raw = _week("b_shoulder_flag_low_recovery", {(lb, "why_effort"): lambda why, ir_: why})
    assert any("upper_heavy" in c for c in contradictory(raw["week"]))


# ── 7. the adherence dip, on a realistic history ─────────────────────────────
def _irregular(record: list, prof: dict) -> list:
    """A realistic dip: of the fortnight's ten planned mornings, five done on irregular days (Mon + Thu, then Mon, Tue, Fri) —
    not the synthetic 'last sessions of each week slip' pattern — with the older week untouched (the window is covered)."""
    start = sw._day(prof["as_of"], -14)
    keep = {sw._day(start, d) for d in (0, 3, 7, 8, 11)}
    return [w for w in record if w["date"] < start or w["date"] in keep]


def test_an_adherence_dip_changes_the_week_fewer_shorter_sessions_anchored():
    full = _week("a_large_deficit_experienced")
    dip = _week("a_large_deficit_experienced", record=_irregular)
    w = dip["week"]
    assert w["short_week"].startswith("adherence dip (live, adherence_response=short_week)") and len(w["sessions"]) == 4
    cap = lb.ADHERENCE_DIP["session_minutes"]["value"]
    assert all((s["lifting_minutes"] or 0) <= cap for s in w["sessions"])
    full_anchor = {
        s["role"]: [x["working_sets"] for x in s["lifts"] if str(x["tag"]).startswith("anchor:")] for s in full["week"]["sessions"]
    }
    for s in w["sessions"]:
        assert [x["working_sets"] for x in s["lifts"] if str(x["tag"]).startswith("anchor:")] == full_anchor[s["role"]], s["role"]
        acc = [x for x in s["lifts"] if str(x["tag"]).startswith("accessory:") and not str(x["tag"]).endswith(":carry")]
        assert all(x["working_sets"] <= lb.ADHERENCE_DIP["accessory_sets"]["value"] for x in acc), s["role"]
    sets = lambda wk: sum(x["working_sets"] for x in _lifts(wk))  # noqa: E731
    assert sets(w) <= 0.75 * sets(full["week"])  # meaningfully less, not two sets off
    # control: today's answer (two sets off, five full sessions) through the setting
    trim = _week("a_large_deficit_experienced", settings={"adherence_response": "trim_sets"}, record=_irregular)["week"]
    assert len(trim["sessions"]) == 5 and sets(trim) > sets(w)
    # the stricter keep-the-anchors week stays behind its own setting (~45 min, one accessory per major muscle)
    behind = _week("a_large_deficit_experienced", settings={"behind_schedule_week": True}, record=_irregular)["week"]
    assert behind["short_week"].startswith("behind schedule") and all(
        (s["lifting_minutes"] or 0) <= lw.BEHIND_SCHEDULE["session_minutes"]["value"] for s in behind["sessions"]
    )


# ── 8. the steps credit ──────────────────────────────────────────────────────
def test_the_steps_credit_is_conservative_and_cadence_minutes_count_first():
    days = sw.steps_by_day(PROFILES["a_large_deficit_experienced"])  # a 14k-step walker
    after = cm._walking_dose(days)
    assert after["moderate_min_per_wk"] == 158 and after["source"] == "steps_heuristic" and "heuristic" in after["basis"][0]
    with patch.object(cm, "STEPS_CREDIT_SHARE", 1.0):  # control: the old credit — every step over 5,000 at 100 a minute
        assert cm._walking_dose(days)["moderate_min_per_wk"] == 630
    cad = cm._walking_dose(days, cadence_minutes_by_day={d: 12 for d in days})  # minutes AT a qualifying cadence, where read
    assert cad["moderate_min_per_wk"] == 84 and cad["source"] == "cadence_minutes"
    assert not cm.aerobic_plan({d: 10000 for d in days})["volume_covered"]  # 10k a day no longer 'covers' the week by itself


def _walker_week(steps: int, settings: dict | None = None, patches: dict | None = None) -> dict:
    """Profile (a) with a different daily step count — a 10k walker's steps no longer cover the weekly floor."""
    prof = PROFILES["a_large_deficit_experienced"] | {"steps_per_day": steps}
    with patch.dict(sw.SETTINGS, settings or {}):
        world = sw.build_world(prof, "approved")
        ps_ = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
        for p in ps_:
            p.start()
        try:
            return sw.generate_week(prof, "approved", world)
        finally:
            for p in ps_:
                p.stop()


def test_easy_blocks_close_the_weeks_gap_and_never_gut_lifting():
    """Steps first, then only the structured minutes that close the gap to the weekly floor (cardio_model.WEEKLY_MODERATE_MIN):
    a 10k walker (~88 credited min) gets easy blocks until the week's blocks close the gap — not one every morning — and under
    the shared cap only the conditioning host buys room (an easy block takes what lifting leaves, else none)."""
    week = _walker_week(10000)
    kinds = [s["cardio"].get("kind") for s in week["sessions"]]
    easy = [k for k in kinds if k and k not in lp.HARD_KINDS]
    total = sum(int(s["cardio"].get("minutes") or 0) for s in week["sessions"])
    assert easy and len(easy) < len([s for s in week["sessions"] if s["cardio"].get("kind") not in lp.HARD_KINDS])
    assert total + week["steps_credit"]["moderate_min_per_wk"] >= cm.WEEKLY_MODERATE_MIN[0]
    from training import live_shape

    # control: no gap rule (FIX4: nor the walk prompt's "a small gap is the walk's")
    every = _walker_week(
        10000, patches={(lb, "easy_gap"): lambda kind, live: (True, []), (live_shape, "walk_covers"): lambda kind, live: None}
    )
    assert sum(1 for s in every["sessions"] if s["cardio"].get("kind") and s["cardio"]["kind"] not in lp.HARD_KINDS) > len(easy)
    shared = _walker_week(10000, {"session_cap_includes_cardio": True})
    full = {s["role"]: s["lifting_minutes"] for s in week["sessions"]}
    for s in shared["sessions"]:
        if s["role"] != "shoulders_arms":  # only the host trims lifting for its block
            assert s["lifting_minutes"] >= full[s["role"]] - 0.05, s["role"]
        assert (
            not s["cardio"].get("minutes")
            or s["cardio"]["minutes"] >= lw.CARDIO_ROOM["min_block"]["value"]
            or s["cardio"]["kind"] in lp.HARD_KINDS
        )


# ── 9. the garage leg curl ───────────────────────────────────────────────────
def test_an_equipment_limited_week_keeps_hamstring_knee_flexion_from_the_library(weeks):
    c = weeks[("c_equipment_limited", False)]
    lh = next(s for s in c["week"]["sessions"] if s["role"] == "lower_heavy")
    curls = [x for x in lh["lifts"] if sw._lib_entry(c["world"]["lib"], CAT0, x["key"]).get("pattern") == "leg_curl"]
    assert curls and all(not se.availability(sw._lib_entry(c["world"]["lib"], CAT0, x["key"]), c["world"]["lib"], None) for x in curls)
    off = _week("c_equipment_limited", {(lb, "library_fallbacks"): lambda e, ctx: []})  # control: slot fallbacks only
    lh = next(s for s in off["week"]["sessions"] if s["role"] == "lower_heavy")
    assert not [x for x in lh["lifts"] if sw._lib_entry(off["world"]["lib"], CAT0, x["key"]).get("pattern") == "leg_curl"]
    assert any("Leg Curl" in ln and "nothing fills it" in ln for ln in lh["rationale"])


# ── 10. cardio and the owner's settings ──────────────────────────────────────
def test_the_short_week_under_the_shared_cap_keeps_a_real_aerobic_block(weeks):
    e = weeks[("e_short_week", True)]["week"]
    assert max(s["cardio"].get("minutes") or 0 for s in e["sessions"]) >= lw.CARDIO_ROOM["min_block"]["value"]
    assert lb.conditioning_host("shoulders_arms") == "upper_volume" and lb.conditioning_host(None) == "shoulders_arms"
    stuck = _week("e_short_week", {(lb, "conditioning_host"): lambda skipped: "shoulders_arms"}, {"session_cap_includes_cardio": True})
    assert max(s["cardio"].get("minutes") or 0 for s in stuck["week"]["sessions"]) == 0  # control: the skipped day as host


def test_a_cardio_machine_the_gym_lacks_is_swapped_and_the_bike_is_named_for_what_is_there():
    lib = copy.deepcopy(LIB0)
    lib["movements"]["cycling"]["availability"] = {"home_gym": {"state": "unavailable", "source": "control"}}
    menu, lines = lb.cardio_machine({"kind": "tempo", "machine": "cycling"}, lib)
    assert menu["machine"] != "cycling" and lines
    assert lb.cardio_machine({"kind": "tempo", "machine": "cycling"}, LIB0) == ({"kind": "tempo", "machine": "cycling"}, [])
    note = "RPE _\nRecumbent · your level · RPE 6–7"
    assert lb.machine_label(note, LIB0) == note  # his gym: the recumbent stands
    garage = copy.deepcopy(LIB0)
    garage["gym_inventory"]["items"]["recumbent_bike"] = {"home_gym": {"state": "unavailable", "source": "control"}}
    assert lb.machine_label(note, garage) == "RPE _\nBike · your level · RPE 6–7"


def test_the_rate_band_and_symptom_wording_settings_work_with_todays_defaults():
    lib = copy.deepcopy(LIB0)
    band = lb.rate_band(None, 7.5, lib)
    assert band["mode"] == "advisory" and band["body_fat_tier"] == "unknown"
    set_ = copy.deepcopy(lib)
    from health import rate_policy

    tier = sorted(rate_policy.START_RUNG_BY_TIER)[0]
    set_["programming_settings"] = {**(lib.get("programming_settings") or {}), "body_fat_tier": tier, "rate_band_mode": "structured"}
    got = lb.rate_band(None, 7.5, set_)
    assert got["mode"] == "structured" and got["body_fat_tier"] == tier
    assert got["band_pct_bw_per_wk"] == rate_policy.propose_band(body_fat_tier=tier)["band_pct_bw_per_wk"]
    wording = "Chest, breathing, dizzy, heart racing or irregular? Stop, log it."
    w = _week("a_large_deficit_experienced", settings={"symptom_line": wording})["week"]
    hard = [s["cardio"]["note"] for s in w["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS]
    assert hard and all(n.split("\n")[-1] == wording for n in hard)


def test_every_fix3_constant_is_labelled_and_every_default_is_todays():
    for table in (lb.ALLOCATION, lb.ADHERENCE_DIP):
        for name, row in table.items():
            assert row["label"] == "heuristic" and row["basis"], name
    s = lp.settings(LIB0)
    assert s["session_cap_includes_cardio"] is False and s["behind_schedule_week"] is False
    assert s["symptom_line"] == "Chest, breathing, dizzy? Stop, log it." and s["kb_deadlift_template_id"] is None
    assert s["kb_slot_role"] == "lower_volume" == lb.KB_HOME and s["body_fat_tier"] is None and s["rate_band_mode"] == "advisory"
    assert ps.SESSION_TEMPLATES["lower_volume"]["accessories"].count(lb.KB_SLOT_KEY) == 1  # the template placement is today's
    assert isinstance(cm.STEPS_CREDIT_SHARE, float) and 0 < cm.STEPS_CREDIT_SHARE < 1
