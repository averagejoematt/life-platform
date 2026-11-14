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

FIX ROUND 9 (consolidation) — tests deleted or rewritten here:
  test_a_pain_flag_carries_the_persistence_line_on_its_own_lift_only -> rewritten: the line is a constant (`PAIN_ASSESS_LINE`,
      its setting deleted); the off-control patches the constant
  test_the_week_is_allocated_by_priority_before_any_muscle_sits_over_mav -> rewritten on the ONE weekly plan (`live_volume`)
  test_the_kettlebell_slot_moves_off_a_stacked_session_by_setting -> deleted: KB slot machinery (rulings #2/#6/#7: no KB hinge
      slot under live; the slot is removed by `live_volume._kb_slot`)
  test_the_kb_template_setting_writes_the_slot_under_his_custom_template -> deleted: ruling #2 (no KB template); the resolver is
      the identity (asserted in the settings test below)
  test_an_adherence_dip_changes_the_week_fewer_shorter_sessions_anchored -> rewritten: ruling 2's dip is ONE 4-morning week
      (`live_sequence.plan_for_days(4, mode="dip")`), never two in a row; the 60-min cap / trim_sets / behind_schedule options
      are deleted dead alternatives
  test_easy_blocks_close_the_weeks_gap_and_never_gut_lifting -> deleted: it held the `cardio_purpose_only=False` / `as_fix5`
      branches the owner ruled out (ruling 4; purposeful cardio is tests/test_owner_rulings_5861.py)
  test_an_equipment_limited_week_keeps_hamstring_knee_flexion_from_the_library -> rewritten: the "nothing fills it" line is a
      debug line now (`live_fit`), not the rationale
  test_the_short_week_under_the_shared_cap_keeps_a_real_aerobic_block -> rewritten: CARDIO_ROOM deleted (ruling 1: no strength
      work cut for cardio); the outcome kept is the short week's conditioning host and the 75-min morning
  test_the_rate_band_and_symptom_wording_settings_work_with_todays_defaults -> deleted: `rate_band_mode` / `body_fat_tier` /
      `symptom_line` settings (owner ruled: advisory only, no symptom line)
  test_every_fix3_constant_is_labelled_and_every_default_is_todays -> rewritten onto `live_settings`
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
    live_balance as lb,
    live_settings as lset,
    live_volume as lvol,
    quality_rubric as qr,
    selection_engine as se,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())
PROFILES = sw.load_profiles()


def _week(name: str, patches: dict | None = None, settings: dict | None = None, record=None, profile: dict | None = None) -> dict:
    prof = profile or PROFILES[name]
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


BENCH_PAIN = {"pain": [{"movement": "barbell_bench_press", "note": "shoulder pain 3/10 at the bottom of the bench"}]}


def _pain_week(patches: dict | None = None, settings: dict | None = None) -> dict:
    """Profile a with a mild (3/10) shoulder pain note on the bench: kept lighter, never swapped."""
    prof = PROFILES["a_large_deficit_experienced"] | BENCH_PAIN
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


def test_a_pain_flag_carries_the_persistence_line_on_its_own_lift_only(weeks):
    """#5861 FIX7 (sixth red team: the bench-elbow 'get it assessed' line printed on the squat and the RDL): the persistence line
    rides the flagged lift (or what stands in for it) and nothing else."""
    line = lb.PAIN_ASSESS_LINE
    on = [x for x in _lifts(_pain_week()) if line in (x["hevy_note"] or "").split("\n")]
    assert on and {x["key"] for x in on} == {"barbell_bench_press"}, [x["key"] for x in on]
    assert not any(line in (x["hevy_note"] or "") for x in _lifts(weeks[("a_large_deficit_experienced", False)]["week"]))  # no flag
    from training import live_pain

    first = {(live_pain, "assess_target"): lambda rx, ctx, pains: rx["exposures"][0]}  # control: the old 'first lift' placement
    assert {x["key"] for x in _lifts(_pain_week(first)) if line in (x["hevy_note"] or "")} - {"barbell_bench_press"}
    off = _pain_week({(lb, "PAIN_ASSESS_LINE"): ""})  # control: no line -> none printed
    assert not any(line in (x["hevy_note"] or "") for x in _lifts(off))


# ── 2. volume by priority ────────────────────────────────────────────────────
def test_the_week_is_planned_by_priority_and_no_non_priority_muscle_grows_over_mav():
    """Round 9's ONE weekly plan: the template's delt spread gives isolation sets first (face pulls toward their 2-set floor), the
    priority muscles sit at or over MEV with the side and rear delt heads at their aims, direct abs at the ruled 4. Setting: the
    owner may name other priority muscles. Control: a slot floor out of reach -> the face pulls keep their template sets."""
    lib = copy.deepcopy(LIB0)
    plan = lvol.week_plan(CAT0, lib, 5)
    marks = LANDMARKS["muscles"]
    c = plan["counts"]
    assert all(c[m] >= marks[m]["MEV"] for m in ("chest", "quadriceps"))  # the ruled priority muscles
    assert c["side_delts"] >= lset.value("delt_heads")["side_delts"] and c["rear_delts"] >= lset.value("delt_heads")["rear_delts"]
    assert c["abs"] == lset.defaults()["abs_direct_sets_per_week"]
    assert sum(r["sets"] for r in plan["rows"] if r["key"] == "face_pull") <= 4  # the template's 3 + 3 gave first
    other = copy.deepcopy(lib)
    other["programming_settings"] = {**(lib.get("programming_settings") or {}), "priority_muscles": ["back"]}
    assert lvol.week_plan(CAT0, other, 5)["targets"]["chest"]["floor"] == marks["chest"]["MV"]  # a setting he owns
    assert c["shoulders"] <= marks["shoulders"]["MAV"]  # ruling 9: total shoulder volume never forced over MAV
    # control (fix round 11): no surplus trim and no donation in the one spend step -> the template's delts sit over MAV
    with (
        patch.object(lvol, "_surplus", lambda rows, tg, prio, lines: (lambda: None)),
        patch.object(
            lvol, "_make_room", lambda rows, tg, lead, role, m, need, room, budget, gave, slot=False: room(role) >= need and not slot
        ),
    ):
        assert lvol.week_plan(CAT0, lib, 5)["counts"]["shoulders"] > marks["shoulders"]["MAV"]


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
    # FIX6 +2: owner ruling 17 (the glute S standard) — the barbell and machine hip thrusts meet every S criterion
    assert s_counts(LIB0) == {"hypertrophy": 30, "strength": 10, "functional": 9, "conditioning": 0, "mobility": 0}  # FIX7: -2 glute S
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
    from training import live_rulings

    def cap_first(rx, ctx):  # fix round 11: the lower-heavy morning's FIRST lift (the squat) capped under the session band
        for e in rx["exposures"]:
            if rx.get("session_role") == "lower_heavy" and e.get("kind") == "anchor" and e.get("pattern") == "squat":
                e["live_effort"] = 7
        return []

    raw = _week("a_large_deficit_experienced", {(lb, "why_effort"): lambda why, ir_: why, (live_rulings, "lead_lift"): cap_first})
    assert contradictory(raw["week"])


# ── 7. the adherence dip, on a realistic history ─────────────────────────────
def _irregular(record: list, prof: dict) -> list:
    """A realistic dip: of the fortnight's ten planned mornings, five done on irregular days (Mon + Thu, then Mon, Tue, Fri) —
    not the synthetic 'last sessions of each week slip' pattern — with the older week untouched (the window is covered)."""
    start = sw._day(prof["as_of"], -14)
    keep = {sw._day(start, d) for d in (0, 3, 7, 8, 11)}
    return [w for w in record if w["date"] < start or w["date"] in keep]


def test_an_adherence_dip_is_one_four_morning_week_no_make_up():
    """Owner ruling 2: after a dip, one 4-morning week (shoulders+arms skipped) to get back into the routine — no make-up sets,
    and never a second dip week for the same gap (the eighth red team: a 12-day layoff gave two). The week is PRODUCTION's plan,
    the one the nightly sequence reads. Control: the full record -> no dip."""
    full = _week("a_large_deficit_experienced")
    dip = _week("a_large_deficit_experienced", record=_irregular)
    w = dip["week"]
    assert len(w["sessions"]) == 4 and "shoulders_arms" not in [s["role"] for s in w["sessions"]]
    from training import live_sequence, session_sequence as ss

    plan = live_sequence.week_plan("2026-11-16", dip["world"]["record"], dip["world"]["lib"])
    assert plan and plan["mode"] == "dip" and plan["skip"] == ("shoulders_arms",) and plan["days"] == 4
    skip = live_sequence.sequence_skip(dip["world"]["record"], dip["world"]["lib"])
    assert ss.next_session("2026-11-16", dip["world"]["record"], [], skip=skip)["session_role"] != "shoulders_arms"
    assert live_sequence.week_plan("2026-11-16", full["world"]["record"], full["world"]["lib"]) is None  # control: no dip
    full_anchor = {s["role"]: [x["key"] for x in s["lifts"] if str(x["tag"]).startswith("anchor:")] for s in full["week"]["sessions"]}
    for s in w["sessions"]:  # every anchor kept, none at one set
        mine = [x for x in s["lifts"] if str(x["tag"]).startswith("anchor:")]
        assert [x["key"] for x in mine] == full_anchor[s["role"]] and all(x["working_sets"] >= 2 for x in mine), s["role"]
    with patch.object(live_sequence, "_dip", lambda workouts, monday: True):  # a dip the week before -> no second dip week
        assert live_sequence.week_plan("2026-11-23", dip["world"]["record"], dip["world"]["lib"]) is None


# ── 8. the steps credit (#5861 FIX6, owner ruling 12: REMOVED — steps are reported, never credited) ──────────────────────
def test_steps_earn_no_credit_and_cadence_minutes_count_first():
    days = sw.steps_by_day(PROFILES["a_large_deficit_experienced"])  # a 14k-step walker
    after = cm._walking_dose(days)
    assert after["moderate_min_per_wk"] == 0 and after["source"] == "intensity_unknown" and after["steps_per_day"] == 14000
    assert not hasattr(cm, "STEPS_CREDIT_SHARE")  # the rejected 25 %-over-5k formula is gone, not parked
    cad = cm._walking_dose(days, cadence_minutes_by_day={d: 12 for d in days})  # minutes AT a qualifying cadence, where read
    assert cad["moderate_min_per_wk"] == 84 and cad["source"] == "cadence_minutes"
    assert not cm.aerobic_plan({d: 30000 for d in days})["volume_covered"]  # no step count 'covers' the week by itself


# ── 9. the garage leg curl ───────────────────────────────────────────────────
def test_an_equipment_limited_week_keeps_hamstring_knee_flexion_from_the_library(weeks):
    c = weeks[("c_equipment_limited", False)]
    lh = next(s for s in c["week"]["sessions"] if s["role"] == "lower_heavy")
    curls = [x for x in lh["lifts"] if sw._lib_entry(c["world"]["lib"], CAT0, x["key"]).get("pattern") == "leg_curl"]
    assert curls and all(not se.availability(sw._lib_entry(c["world"]["lib"], CAT0, x["key"]), c["world"]["lib"], None) for x in curls)
    off = _week("c_equipment_limited", {(lb, "library_fallbacks"): lambda e, ctx: []})  # control: slot fallbacks only
    lh = next(s for s in off["week"]["sessions"] if s["role"] == "lower_heavy")
    assert not [x for x in lh["lifts"] if sw._lib_entry(off["world"]["lib"], CAT0, x["key"]).get("pattern") == "leg_curl"]
    assert any("Leg Curl" in ln and "nothing fills it" in ln for ln in lh["live_fit"] or [])


# ── 10. cardio and the owner's settings ──────────────────────────────────────
def test_the_short_week_hosts_its_conditioning_on_a_morning_it_drafts():
    """The third red team's short week had no conditioning at all under the shared cap. The host moves off a skipped
    shoulders+arms to the morning after the heavy lower day; ruling 1 (round 9): the block takes only what lifting leaves, so
    every morning fits 75 minutes. Control: a week that keeps shoulders+arms hosts it there."""
    assert lb.conditioning_host(("shoulders_arms",)) == "upper_volume"
    assert lb.conditioning_host(None) == "shoulders_arms"  # control
    e = _week("e_short_week", settings={"session_cap_includes_cardio": True})["week"]
    for s in e["sessions"]:
        assert (s["lifting_minutes"] or 0) + (s["cardio"].get("minutes") or 0) <= 75.05, s["role"]


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


def test_the_one_settings_table_holds_the_rulings_and_nothing_dead():
    s = lset.settings(LIB0)
    # the owner's rulings of 2026-11-13 — the shared cap ON (ruling 1), press 3 (ruling 6), chest + quadriceps (ruling 9)
    assert s["session_cap_includes_cardio"] is True and s["press_sets"] == 3 and s["priority_muscles"] == ["chest", "quadriceps"]
    dead = {"behind_schedule_week", "symptom_line", "kb_deadlift_template_id", "kb_slot_role", "body_fat_tier", "rate_band_mode"}
    assert not dead & set(s)
    base = lambda k: k  # noqa: E731
    assert lb.template_resolver(base) is base  # ruling #2: no KB template — the resolver is the identity
    assert cm.STEPS_PER_MODERATE_MIN == cm.CADENCE_MODERATE_SPM == 100  # a population heuristic, labelled (ruling 12)
