"""#5861 fifth red team (graded B-, "do not approve yet") — the CODE/DATA fixes, gated on the GENERATED weeks.

Every gate here has a MUST-FAIL CONTROL in the same test (the guarded behaviour patched out, or the data put back as it was ->
red). Live mode = an IN-MEMORY approved copy of the library (the committed file stays `proposed`). The stress profiles are the
fifth red team's, SYNTHETIC (`tests/fixtures/sample_week_stress_profiles_rt5_5861.json`: hip, elbow and unnamed pain, a 3-day
week, no barbell, a sedentary week, everything bad in two days, knee discomfort).

  1. short weeks: no crash, every session within the set cap; 3-day and 2-day weeks are full-body (legs and upper 2x)
  2. pain avoidance: above the mild line the flagged pattern is OFF; same-joint isolation at RPE <= 7 with the stop line
  3. the elbow pain map; the new-movement RPE cap reaches isolation
  4. nothing added on a strained / overreached / deload-recommended day
  5. production parity: the cron's sequence serves the generator's week (dip and short weeks)
  6. the kettlebell deadlift as filler
  7. "sore" at the mild line is discomfort (light-and-keep)
  8. the thresholds are read; the deload's isolation effort cap
  9. the self-reported stop lines
  10. the corrected (and the kept) ratings
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts", REPO / "deploy"):
    sys.path.insert(0, str(_p))

import exercise_library_input_review as ir  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    fatigue_model as fm,
    kb_entry,
    live_balance as lb,
    live_program as lp,
    live_rules as lrules,
    live_sequence as lseq,
    live_week as lw,
    program_structure as ps,
    quality_rubric as qr,
    selection_engine as se,
    session_sequence as ss,
)
from training.training_notes_pain import PAIN, pain_class  # noqa: E402

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())
PROFILES = sw.load_profiles()
STRESS4 = sw.load_profiles(REPO / "tests" / "fixtures" / "sample_week_stress_profiles_5861.json")
RT5 = sw.load_profiles(REPO / "tests" / "fixtures" / "sample_week_stress_profiles_rt5_5861.json")
ALL = PROFILES | STRESS4 | RT5
DAYS = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
NODL = {(lrules, "deadlifts"): lambda workouts, ctx: False}


def _week(name: str, patches: dict | None = None, settings: dict | None = None, days: int | None = None, record=None) -> dict:
    prof = copy.deepcopy(ALL[name])
    if days is not None:
        prof |= {"days": DAYS[:days], "roles": list(ps.SPLIT_ROLES)}
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
    return {"world": world, "week": week, "prof": prof}


def _lifts(week: dict) -> list[dict]:
    return [x for s in week["sessions"] for x in s["lifts"]]


def _entry(w: dict, key: str) -> dict:
    return sw._lib_entry(w["world"]["lib"], w["world"]["catalog"]["movements"], key)


def _top_rpe(note: str | None) -> float:
    nums = [float(x) for t in lb.effort_targets(note) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    return max(nums) if nums else 0.0


def _lines(week: dict, prefix: str) -> list[str]:
    return [ln for s in week["sessions"] for ln in s["rationale"] if ln.startswith(prefix)]


# ── 1. short weeks ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(RT5))
def test_every_week_of_one_to_five_mornings_drafts_within_the_session_set_cap(name):
    """The fifth red team's 3-day week crashed (`total_sets 23 > cap 20`). Fuzz: 1-5 mornings x both cap settings x every stress
    profile — no crash, the drafted number of sessions, every session within the week grid's set ceiling."""
    from training import routine_generator as rg
    from training.program_seam import resolve_week_grid

    cap = int(resolve_week_grid(rg._load_json).week["session_set_ceiling"])  # the week grid's ceiling (owner 2026-09-30)
    for shared in (False, True):
        for days in (1, 2, 3, 4, 5):
            w = _week(name, settings={"session_cap_includes_cardio": shared}, days=days)["week"]
            assert len(w["sessions"]) == days or (days == 5 and len(w["sessions"]) == 4), (name, shared, days)
            for s in w["sessions"]:
                assert sum(x["working_sets"] for x in s["lifts"]) <= cap, (name, shared, days, s["role"])
                assert not any("fit failed" in ln for ln in s["rationale"]), (name, shared, days, s["role"])


def test_the_set_cap_guard_is_what_keeps_the_three_day_week_from_crashing():
    _week("l_three_day_week", days=3)  # drafts
    with pytest.raises(AssertionError, match="total_sets"):  # control: the guard off -> the red team's crash returns
        _week("l_three_day_week", {(lrules, "fit_set_cap"): lambda rx, cap: []}, days=3)


def _regions(w: dict) -> list[set[str]]:
    """Per session, the body regions its ANCHOR lifts train (upper / lower)."""
    return [
        {str((_entry(w, x["key"]).get("target") or {}).get("region")) for x in s["lifts"] if str(x["tag"]).startswith("anchor")}
        for s in w["week"]["sessions"]
    ]


def test_three_and_two_day_weeks_train_legs_and_the_upper_body_twice():
    three = _week("a_large_deficit_experienced", days=3)
    regs = _regions(three)
    assert sum("lower" in r for r in regs) >= 2 and sum("upper" in r for r in regs) >= 2, regs
    assert "legs keep 2x" not in three["week"]["short_week"] and "full body" in three["week"]["short_week"]
    two = _week("a_large_deficit_experienced", days=2)
    assert all({"upper", "lower"} <= r for r in _regions(two)), _regions(two)  # two FULL-BODY days, never halves
    halves = _week("a_large_deficit_experienced", {(lrules, "full_body"): lambda rx, ctx: []}, days=2)  # control: no partner
    assert not all({"upper", "lower"} <= r for r in _regions(halves))


# ── 2. pain avoidance ────────────────────────────────────────────────────────
PRESS = ("horizontal_press", "vertical_press", "press", "chest_fly")


def test_above_the_mild_line_the_flagged_pattern_is_off_for_the_session():
    """Profile b: sharp shoulder pain 6/10 on the press. FIX4 substituted a moderate-stress member (a decline machine press at
    RPE 6-7); FIX5 served no pressing at all. #5861 FIX7: no press that loads the shoulder at moderate or more is served — a
    pain-free same-family member (LOW on the shoulder) may stand in at RPE <= 8 with the stop line. Control: every flag read as
    `reduce` -> shoulder-loading pressing is served again."""
    b = _week("b_shoulder_flag_low_recovery")
    presses = [x for x in _lifts(b["week"]) if _entry(b, x["key"]).get("pattern") in PRESS]
    assert all(_entry(b, x["key"])["joint_stress"]["shoulder"] == "low" for x in presses), [x["key"] for x in presses]
    assert all(_top_rpe(x["hevy_note"]) <= 8 and "stop this lift" in x["hevy_note"] for x in presses)
    real = lp.joint_flags
    reduce = lambda ctx, workouts, discomfort: [f | {"tier": "reduce"} for f in real(ctx, workouts, discomfort)]  # noqa: E731
    soft = _week("b_shoulder_flag_low_recovery", {(lp, "joint_flags"): reduce})
    assert [
        x["key"]
        for x in _lifts(soft["week"])
        if _entry(soft, x["key"]).get("pattern") in PRESS and _entry(soft, x["key"])["joint_stress"]["shoulder"] != "low"
    ]


def test_same_joint_isolation_is_capped_with_the_stop_line_under_an_elbow_flag():
    """Profile k: elbow pain 5/10 on the bench. The triceps slots went to a pushaway rated LOW for the elbow, at RPE 8-9 (last
    set 9-10). Now a triceps extension is served only LOW on the elbow (#5861 FIX7: a pain-free route) and capped like every curl
    at RPE 7 with the stop line (above the mild line every same-joint isolation is capped). Control: the elbow data as it was AND the isolation cap off -> an elbow isolation above RPE 7.
    """
    k = _week("k_elbow_pain_press")
    tri = [x for x in _lifts(k["week"]) if _entry(k, x["key"]).get("pattern") == "triceps_extension"]
    assert all(_entry(k, x["key"])["joint_stress"]["elbow"] == "low" and _top_rpe(x["hevy_note"]) <= 7 for x in tri)  # FIX7
    curls = [x for x in _lifts(k["week"]) if _entry(k, x["key"]).get("pattern") == "curl"]
    assert curls and all(_top_rpe(x["hevy_note"]) <= 7 and "stop this lift" in x["hevy_note"] for x in curls)
    old = copy.deepcopy(LIB0)
    for e in old["movements"].values():
        if (e.get("provocation_floor") or {}).get("elbow"):
            e["joint_stress"] = {**e["joint_stress"], "elbow": e["provocation_floor"]["elbow"]["from"]}
    prof = RT5["k_elbow_pain_press"]
    world = sw.build_world(prof, "approved")
    world["lib"] = sw.approved_library(old, prof)
    with patch.object(lrules, "isolation_joint_cap", lambda rx, ctx, flags: []):
        was = sw.generate_week(prof, "approved", world)
    w = {"world": world}
    bad = [x for x in _lifts(was) if _entry(w, x["key"]).get("pattern") in ("triceps_extension", "curl") and _top_rpe(x["hevy_note"]) > 7]
    assert bad


# ── 3. the elbow pain map; the new-movement cap reaches isolation ────────────
def test_loaded_elbow_isolation_loads_the_elbow_and_keeps_its_healthy_joint_cost():
    mv = LIB0["movements"]
    assert mv["tricep_pushaway"]["joint_stress"]["elbow"] == "moderate"
    for k, e in mv.items():
        if e.get("pattern") in ir.ELBOW_PROVOKING["patterns"] and not re.search(ir.ELBOW_PROVOKING["not_title"], e["title"], re.I):
            assert e["joint_stress"]["elbow"] in ("moderate", "high"), k
    # the rubric's joint cost reads the healthy-joint rating (a pain-map floor), so no tier moved for it
    assert mv["tricep_pushaway"]["provocation_floor"]["elbow"]["from"] == "low"
    assert qr.joint_penalty(mv["tricep_pushaway"]) == 0
    toy = {"x": {"title": "Tricep Pushaway", "pattern": "triceps_extension", "joint_stress": {"elbow": "low"}}}
    with patch.dict(ir.ELBOW_PROVOKING, {"patterns": ()}):  # control: the class rule off -> the pushaway stays low
        ir.apply_class_rules(toy)
    assert toy["x"]["joint_stress"]["elbow"] == "low"


def test_a_lift_with_no_load_on_file_starts_at_rpe_7_isolation_too():
    weeks = [_week(n)["week"] for n in ("a_large_deficit_experienced", "c_equipment_limited")]
    new = [x for w in weeks for x in _lifts(w) if "find the load" in (x["hevy_note"] or "") and not str(x["tag"]).endswith(":carry")]
    assert new and all(_top_rpe(x["hevy_note"]) <= 7 for x in new)
    raw = _week("c_equipment_limited", {(lp, "_novel_cap"): lambda note, e: note})["week"]  # control: the cap off
    assert any(_top_rpe(x["hevy_note"]) > 7 for x in _lifts(raw) if "find the load" in (x["hevy_note"] or ""))


# ── 4. nothing added on a bad day ────────────────────────────────────────────
def _added_on_bad_days(week: dict) -> list[str]:
    out = []
    for s in week["sessions"]:
        fat = s.get("fatigue") or {}
        if fat.get("state") in ("strained", "overreached") or fat.get("action") == "deload_recommended":
            out += [
                f"{s['role']}: {ln}"
                for ln in s["rationale"]
                if ln.startswith(("added (live)", "trunk floor (live)")) and "short week" not in ln and "weekly carry" not in ln
            ]
    return out


def test_no_added_work_on_a_strained_overreached_or_deload_day():
    """The quadriceps slot, the trunk floor and a relocated kettlebell slot wait on a bad day (profile f: deload recommended
    all week; b: strained). Control: the rule off (and the trunk floor's bad-day check off) -> the leg extension is added."""
    for name in ("f_high_fatigue_poor_sleep", "b_shoulder_flag_low_recovery"):
        w = _week(name, NODL)["week"]
        assert _added_on_bad_days(w) == [], name
    f = _week("f_high_fatigue_poor_sleep", NODL)["week"]
    assert "leg_extension_machine" not in {x["key"] for x in _lifts(f)}
    off = _week(
        "f_high_fatigue_poor_sleep",
        NODL | {(lrules, "no_added_work"): lambda rx: [], (lrules, "bad_day"): lambda rx: False},
        {"press_sets": 1},  # #5861 FIX6: the round-5 week (the press trade takes the freed sets the slot needs)
    )
    assert "leg_extension_machine" in {x["key"] for x in _lifts(off["week"])}


# ── 5. production parity ─────────────────────────────────────────────────────
def _irregular(record: list, prof: dict) -> list:
    start = sw._day(prof["as_of"], -14)
    keep = {sw._day(start, d) for d in (0, 3, 7, 8, 11)}
    return [w for w in record if w["date"] < start or w["date"] in keep]


def _done(day: str, role: str) -> dict:
    """A performed session of `role` on `day` (its template's movements, loaded), as the Hevy record would hold it."""
    rx = ps.session_prescription_for_role(role, catalog_movements=CAT0)
    ex = [
        {
            "name": CAT0[e["movement_key"]]["title"],
            "template_id": sw._tid(CAT0, e["movement_key"]),
            "sets": [{"type": "normal", "weight_kg": 40, "reps": 8}],
        }
        for e in rx["exposures"]
        if e.get("movement_key") in CAT0 and sw._tid(CAT0, e["movement_key"])
    ]
    return sw._workout(day, role, ex)


def _production_roles(record: list, lib: dict, days: list[str], days_fn=None) -> list[str]:
    rec = list(record)
    skip = lseq.sequence_skip(rec, lib, days_fn)
    served = []
    for d in days:
        role = ss.next_session(d, rec, [], skip=skip)["session_role"]
        served.append(role)
        rec.append(_done(d, role))
    return served


def _rotation_of(a: list[str], b: list[str]) -> bool:
    return len(a) == len(b) and any(a == b[i:] + b[:i] for i in range(len(b)))


def test_the_crons_sequence_serves_the_generators_dip_and_short_weeks():
    """The short-week and dip role choices used to exist only in the sample generator (the fifth red team: the dip test asserted
    the harness). The generator now reads the PRODUCTION plan (`live_sequence.week_roles`), and the nightly sequence
    (`session_sequence.next_session` with `live_sequence.sequence_skip`, what `routine_generator._schedule_entry_for_date`
    passes under live) serves the same week — the same roles in the same cycle, from wherever the sequence stands. Control: the
    sequence without the skip slides into shoulders+arms."""
    dip = _week("a_large_deficit_experienced", record=_irregular)
    gen = [s["role"] for s in dip["week"]["sessions"]]
    assert len(gen) == 4 and "shoulders_arms" not in gen
    prod = _production_roles(dip["world"]["record"], dip["world"]["lib"], DAYS[:4])
    assert _rotation_of(prod, gen), (prod, gen)
    rec = list(dip["world"]["record"])
    slid = []
    for d in DAYS[:5]:
        role = ss.next_session(d, rec, [])["session_role"]
        slid.append(role)
        rec.append(_done(d, role))
    assert "shoulders_arms" in slid  # control: today's sliding sequence
    for days in (2, 3, 4):  # short weeks: the mornings come from `days_fn` in production (the charter's travel windows)
        w = _week("a_large_deficit_experienced", days=days)
        gen = [s["role"] for s in w["week"]["sessions"]]
        prod = _production_roles(w["world"]["record"], w["world"]["lib"], DAYS[:days], days_fn=lambda m, n=days: n)
        assert _rotation_of(prod, gen), (days, prod, gen)


def test_the_short_weeks_input_in_production_is_the_charters_travel_windows():
    assert lseq.days_available("2026-11-16") == len(ps.NOMINAL_LIFTING_DAYS)
    with patch("training.training_charter.charter_value", lambda path, default=None: [{"start": "2026-11-18", "end": "2026-11-30"}]):
        assert lseq.days_available("2026-11-16") == 2  # Mon + Tue only
    with patch("training.training_charter.charter_value", lambda path, default=None: []):  # control: no window -> a full week
        assert lseq.days_available("2026-11-16") == 5


# ── 6. the kettlebell deadlift as filler ─────────────────────────────────────
def test_the_kettlebell_deadlift_is_never_filler_for_a_lifter_who_deadlifts():
    a = _week("a_large_deficit_experienced")["week"]
    assert "kettlebell_deadlift" not in {x["key"] for x in _lifts(a)}
    assert any("filler" in ln for ln in _lines(a, "kettlebell slot (live)"))
    # #5861 FIX8 (owner ruling #6): even with the swing's gate open, the swing never fills the slot — it drops, no makeup
    swing = _week("a_large_deficit_experienced", {(se, "locked_gates"): lambda entry, lib: []})["week"]
    assert kb_entry.TARGET not in {x["key"] for x in _lifts(swing)} and "kettlebell_deadlift" not in {x["key"] for x in _lifts(swing)}
    entry = _week("a_large_deficit_experienced", NODL)["week"]  # control: no barbell deadlift on record -> the entry drill serves
    assert "kettlebell_deadlift" in {x["key"] for x in _lifts(entry)}
    kb = LIB0["movements"]["kettlebell_deadlift"]["hypertrophy"][0]
    assert kb["tier"] == "B" and any("load ceiling low" in b for b in kb["basis"])  # one bell: the rubric's cap, not C


# ── 7. "sore" at the mild line ───────────────────────────────────────────────
def test_a_joint_located_sore_note_at_the_mild_line_is_light_discomfort():
    assert pain_class("elbow a bit sore 2/10") is None  # the note layer's class is unchanged (#5800)
    assert lrules.note_class("elbow a bit sore 2/10") == lrules.LIGHT
    assert lrules.note_class("knee a bit cranky 2/10") == lrules.LIGHT
    assert lrules.note_class("hips achy and tight") == "discomfort"  # the note layer's own discomfort (region + ache) is kept
    assert lrules.note_class("no soreness in the elbow today") is None
    assert lrules.note_class("legs sore after yesterday") is None  # no joint named: muscle soreness, not a joint flag
    assert lrules.note_class("elbow sore 6/10") == PAIN
    h = _week("h_heavy_walker")["week"]  # the profile's note is on a lift the prior phase served
    flagged = [ln for ln in _lines(h, "kept (live)") if "(elbow, 2/10)" in ln]  # FIX7: low discomfort touches this lift only
    assert flagged
    oh = [x for x in _lifts(h) if x["key"] == "overhead_triceps_extension_cable"]
    assert oh and all(_top_rpe(x["hevy_note"]) <= 8 and "stop this lift" in x["hevy_note"] for x in oh)  # light-and-keep: a hard set
    off = _week("h_heavy_walker", {(lrules, "note_class"): lambda note: pain_class(str(note or ""))})["week"]  # control
    assert not [ln for ln in _lines(off, "kept (live)") if "(elbow, 2/10)" in ln]


# ── 8. thresholds read; the deload's isolation effort ────────────────────────
def test_the_readiness_threshold_is_read():
    sig = lambda: fm._systemic("red", None, 7.5, None, {}, None, {})[0]["state"]  # noqa: E731
    assert sig() == "strain"
    with patch.dict(fm.THRESHOLDS, {"readiness_strain": {**fm.THRESHOLDS["readiness_strain"], "value": "never"}}):
        assert sig() == "ok"  # control (the fifth red team's surviving M5): the table's value moves the verdict


def test_the_deload_shape_caps_isolation_effort():
    f = _week("f_high_fatigue_poor_sleep")
    iso = [x for x in _lifts(f["week"]) if _entry(f, x["key"]).get("job") == "isolation" and not str(x["tag"]).endswith(":carry")]
    cap = lp.DELOAD_SHAPE["isolation_rpe"]["value"]
    assert iso and all(_top_rpe(x["hevy_note"]) <= cap for x in iso)
    with patch.dict(lp.DELOAD_SHAPE, {"isolation_rpe": {**lp.DELOAD_SHAPE["isolation_rpe"], "value": 10}}):  # control (M10)
        raw = _week("f_high_fatigue_poor_sleep")
    assert any(_top_rpe(x["hevy_note"]) > cap for x in _lifts(raw["week"]) if _entry(raw, x["key"]).get("job") == "isolation")


# ── 9. the self-reported stop lines ──────────────────────────────────────────
def _with_note(note: str):
    def mod(record: list, prof: dict) -> list:
        rec = copy.deepcopy(record)
        last = max(rec, key=lambda w: w["date"])
        last["exercises"][-1]["notes"] = note
        return rec

    return mod


def test_a_logged_palpitation_or_faint_trips_the_symptom_gate():
    trip = lw.symptom_gate(None, [{"date": "2026-11-12", "exercises": [{"notes": "heart racing on the bike, stopped"}]}], "2026-11-16")
    assert trip and trip["lines"] == ["palpitations"]
    assert lw.symptom_gate(None, [{"date": "2026-11-12", "exercises": [{"notes": "felt dizzy after the intervals"}]}], "2026-11-16")[
        "lines"
    ] == ["syncope"]
    assert lw.symptom_gate(None, [{"date": "2026-11-12", "exercises": [{"notes": "no palpitations, no dizziness"}]}], "2026-11-16") is None
    assert lw.symptom_gate(None, [{"date": "2026-10-01", "exercises": [{"notes": "heart racing"}]}], "2026-11-16") is None  # old
    w = _week("a_large_deficit_experienced", record=_with_note("heart racing on the bike, stopped"))["week"]
    assert all(s["cardio"].get("kind") not in lp.HARD_KINDS for s in w["sessions"])
    assert _lines(w, "review (live)") or any("review (live)" in ln for s in w["sessions"] for ln in s["rationale"])
    calm = _week("a_large_deficit_experienced")["week"]  # control: no such note -> hard conditioning is served
    assert any(s["cardio"].get("kind") in lp.HARD_KINDS for s in calm["sessions"])


# ── 10. the ratings the fifth red team called wrong ──────────────────────────
def test_the_disputed_ratings_follow_the_rubric_inputs():
    mv = LIB0["movements"]
    tier = lambda k, t=None: next(r["tier"] for r in mv[k]["hypertrophy"] if t is None or r["target"] == t)  # noqa: E731
    # corrected: the preacher curl is one movement on three implements -> one S (the machine), the dumbbell a variant at A
    assert mv["preacher_curl_dumbbell"]["canonical"] == "preacher_curl_machine" and tier("preacher_curl_dumbbell") == "A"
    s_families = {
        mv[k].get("canonical") or k for k in mv for r in mv[k].get("hypertrophy") or [] if r["target"] == "biceps" and r["tier"] == "S"
    }
    assert len(s_families) == 4, s_families
    # kept, each with its reason (EXERCISE_LIBRARY.md / the PR): the inputs are right
    assert tier("overhead_triceps_extension_cable", "triceps_lateral_medial") == "S"  # deep elbow flexion; Maeo 2023 whole-triceps
    assert tier("lateral_raise_dumbbell") == "B"  # the load peaks at the top (shortened) — the cable lateral is the S/A pick
    assert mv["walking"]["ratings"]["conditioning"]["tier"] == "C"  # outdoor pace is the only dose control; N=1 fit is `n1`
