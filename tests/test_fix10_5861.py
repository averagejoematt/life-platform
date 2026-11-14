"""#5861 fix round 10 — the ninth red team's conditions, as OUTCOMES on synthetic athletes, each with a must-fail control in the
same test. Synthetic profiles only (`tests/fixtures/sample_week_stress_profiles_fix10_5861.json` holds the ninth red team's eight,
ported). The load rule's decline athletes live in tests/test_consolidation_5861.py (`test_a_real_decline_steps_down_within_two_exposures`).

  * 2  a pain-flagged lift never steps up (the discomfort "lift" scope held nothing);
  * 3  an unreviewed movement is never a pain route (Banded Row UPS, defaulted all-low joint stress);
  * 4  one joint rule: a flag holds or routes every lift loading its joint at moderate+, the muscle keeps a route;
  * 5  priority muscles are not under the arms and calves, the setting moves the week, the slump trim spares them;
  * 6  one set-credit table (overhead press -> side delts, no hip-thrust quads, no leg-curl calves, rated secondaries);
  * 8  `same_role`: a new untitled session is not ignored for older titled rows; heavy rows never leak into the volume band;
  * 9  pain-skipped time is refilled with reviewed work; consecutive short weeks rotate what is under target;
  * 10 the hard conditioning dose on the freest morning; no template slot over the 3-set cap;
  * the two surviving mutants of the ninth red team: indirect delt credit removed (M3), the second lift at its last load (M5).
"""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "lambdas"), str(REPO / "scripts"), str(REPO / "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import sample_weeks_5861 as sw  # noqa: E402
from training import live_load, live_pain, live_program, live_settings, live_volume  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"
PROFILES = sw.load_profiles()
FIX9 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix9_5861.json")
FIX10 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix10_5861.json")
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


def _lines(w: dict) -> list[str]:
    return [ln for s in w["week"]["sessions"] for ln in list(s["rationale"]) + list(s.get("live_fit") or [])]


def _ups(w: dict) -> list[str]:
    return [ln for ln in _lines(w) if ln.startswith("load (live): ") and " — up: " in ln]


# ── 2. a pain-flagged lift holds its load ────────────────────────────────────────────────────────────────────────────────────
def test_a_pain_flagged_lift_never_steps_up():
    """The ninth red team (n1): bench with 'shoulder a bit achy 2/10' was served 'Heavier: 6 reps reached'. Every lift the pain
    rule keeps holds its load. Control: the hold dropped from the load decision -> the flagged bench steps up again."""
    w = _week(FIX9["n1_one_morning_knee_shoulder"])
    assert any(ln.startswith("load (live): Bench Press (Barbell)") and " — hold: shoulder flag" in ln for ln in _lines(w))
    assert not any("Bench Press (Barbell)" in ln for ln in _ups(w))
    decide = live_load.decide
    off = _week(FIX9["n1_one_morning_knee_shoulder"], {(live_load, "decide"): lambda *a, **k: decide(*a, **(k | {"hold": None}))})
    assert any("Bench Press (Barbell)" in ln for ln in _ups(off))


# ── 3. unreviewed movements never enter a pain route ─────────────────────────────────────────────────────────────────────────
def test_an_unreviewed_movement_is_never_a_pain_route():
    """The ninth red team (n6): 'Banded Row UPS' — custom, unreviewed, joint stress defaulted to all-low — was the sharp-shoulder
    route for the overhead press (owner ruling 16: missing data never masquerades as suitability). Every route the pain rule
    serves is a REVIEWED movement. Control: the review check off -> the defaulted row is served again."""
    w = _week(FIX9["n6_garage_sharp_shoulder"])
    lib, cat = w["world"]["lib"], w["world"]["catalog"]["movements"]
    keys = {x["key"] for s in w["week"]["sessions"] for x in s["lifts"]}
    assert "banded_row_ups" not in keys
    routed = [ln.split(" -> ", 1)[1].split(" — ")[0] for ln in _lines(w) if ln.startswith("swapped (live): ") and " flag on " in ln]
    by_title = {(cat.get(k) or {}).get("title"): k for k in cat}
    assert routed and all(live_pain.reviewed(sw._lib_entry(lib, cat, by_title[t])) for t in routed if t in by_title)
    off = _week(FIX9["n6_garage_sharp_shoulder"], {(live_pain, "reviewed"): lambda entry: True})
    assert "banded_row_ups" in {x["key"] for s in off["week"]["sessions"] for x in s["lifts"]}


# ── 4. one joint rule ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_joint_flag_reaches_every_lift_loading_that_joint_and_the_muscle_keeps_a_route():
    """The ninth red team (r5): hip 4/10 on the split squat removed every squat while the deadlift (hip stress HIGH) stepped up.
    Now no lift loading the flagged joint at moderate or more steps up; one loading it HIGH is routed (a reviewed low-stress
    member), the rest hold; the hamstrings keep a route. Control: the flag scoped to the flagged lift alone -> the deadlift
    steps up again."""
    w = _week(FIX10["r5_garage_hip_knee"])
    lib, cat = w["world"]["lib"], w["world"]["catalog"]["movements"]
    by_title = {(cat.get(k) or {}).get("title"): k for k in cat}
    for ln in _ups(w):
        title = ln[len("load (live): ") :].rsplit(" — ", 1)[0].rsplit(" ", 2)[0]
        assert live_program._stress(sw._lib_entry(lib, cat, by_title.get(title, "")), "hip") < 1, ln
    assert "deadlift_barbell" not in {x["key"] for s in w["week"]["sessions"] for x in s["lifts"]}
    assert w["hard"].get("hamstrings", 0) > 0
    off = _week(FIX10["r5_garage_hip_knee"], {(live_pain, "scope"): lambda flag, light, tid: "lift"})
    assert any("Deadlift (Barbell)" in ln for ln in _ups(off))


def test_the_low_back_is_the_spinal_load_case_of_the_one_joint_rule():
    """No separate spine rule: a flag on the spine routes every lift loading it HIGH (squat, deadlift, RDL, bent-over row) and
    holds the moderate ones, by the same `live_pain.hit` as every joint. Control: a HIGH-stress lift of another pattern under a
    pattern-group-only reach stays unrouted."""
    f = {"movement_id": "x", "joints": ["spinal_load"], "group": "squat", "tier": "avoid", "scope": "joint", "severity": 6.0}
    ctx = {"idx": {"to_lib": {}}}
    deadlift = {"pattern": "hinge", "joint_stress": {"spinal_load": "high"}}
    db_rdl = {"pattern": "hinge", "joint_stress": {"spinal_load": "moderate"}}
    row = {"pattern": "horizontal_pull", "joint_stress": {"spinal_load": "high"}}
    assert live_pain.hit(deadlift, {}, [f], ctx)[0] == "avoid" and live_pain.hit(row, {}, [f], ctx)[0] == "avoid"
    assert live_pain.hit(db_rdl, {}, [f], ctx)[0] == "hold"
    assert live_pain.hit({"pattern": "curl", "joint_stress": {"spinal_load": "low"}}, {}, [f], ctx) is None
    assert live_pain.hit(deadlift, {}, [f | {"scope": "lift"}], ctx) is None  # control: the old pattern-only reach misses it


# ── 5. priority muscles bite ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["a_large_deficit_experienced", "c_equipment_limited"])
def test_priority_muscles_are_not_under_the_arms_and_calves_in_a_served_week(name):
    """The ninth red team: priority chest 9 under biceps 11 (and delts 16). In a served normal week each priority muscle is at or
    over biceps, triceps and calves. Control: the plan's parity off -> a rival over a priority muscle."""
    w = _week(PROFILES[name])
    assert all(w["hard"].get(p, 0) >= w["hard"].get(r, 0) for p in ("chest", "quadriceps") for r in live_volume.PARITY_RIVALS), w["hard"]
    off = _week(PROFILES[name], {(live_volume, "_priority_parity"): lambda *a: []})
    assert any(off["hard"].get(r, 0) > off["hard"].get(p, 0) for p in ("chest", "quadriceps") for r in live_volume.PARITY_RIVALS)


def test_changing_the_priority_setting_changes_the_served_week():
    """The ninth red team: naming back + glutes as the priority changed nothing (73 sets, identical counts). Control: the same
    setting -> the same week."""
    base = _week(PROFILES["a_large_deficit_experienced"])
    other = _week(PROFILES["a_large_deficit_experienced"], settings={"priority_muscles": ["back", "glutes"]})
    assert other["hard"] != base["hard"]
    assert _week(PROFILES["a_large_deficit_experienced"], settings={"priority_muscles": ["chest", "quadriceps"]})["hard"] == base["hard"]


def test_the_slump_trim_takes_non_priority_accessories_first():
    rx = {
        "exposures": [
            {"kind": "accessory", "movement_key": "chest_fly", "sets": [{}] * 3},
            {"kind": "accessory", "movement_key": "curl", "sets": [{}] * 3},
        ]
    }
    live_load.slump_trim(rx, {"chest_fly"})
    assert [len(e["sets"]) for e in rx["exposures"]] == [3, 2]
    rx["exposures"][0]["sets"] = [{}] * 3
    live_load.slump_trim(rx)  # control: no priority keys -> the priority fly is trimmed too
    assert len(rx["exposures"][0]["sets"]) == 2


# ── 6. one set-credit table ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_one_set_credit_table():
    """The ninth red team: the overhead press gave side delts 0 (doc 0.5), hip thrusts credited quadriceps, leg curls calves, the
    leaning split squat no glutes, the cossack no adductors. Kills the red team's M3 (indirect delt credit removed). Control:
    the table's delt credit emptied -> the press credits no side delt and a row no rear delt."""
    lib = sw.load_library() if hasattr(sw, "load_library") else None
    import json

    lib = lib or json.loads((REPO / "config" / "exercise_library.json").read_text())
    mv = lib["movements"]
    c = lambda mid: live_volume.credits(mv[mid])  # noqa: E731
    assert c("overhead_press_barbell").get("side_delts") == 0.5 and "abs" not in c("overhead_press_barbell")
    assert c("seated_row_machine").get("rear_delts") == 0.5 and c("bench_press_barbell").get("front_delts") == 0.5
    assert "quadriceps" not in c("hip_thrust_barbell") and "quadriceps" not in c("glute_bridge")
    assert "calves" not in c("seated_leg_curl") and "calves" not in c("lying_leg_curl_machine")
    assert c("leaning_bulgarian_split_squats").get("glutes") == 0.5 and c("db_cossack_squats").get("glutes") == 0.5
    table = live_settings.HEURISTICS["set_credit"]["value"]
    with patch.dict(live_settings.HEURISTICS["set_credit"], {"value": table | {"delt": {}}}):  # control
        assert not c("overhead_press_barbell").get("side_delts") and not c("seated_row_machine").get("rear_delts")


# ── 8. same_role ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_same_role_prefers_the_newest_rows_and_never_leaks_heavy_rows_into_the_volume_band():
    """The ninth red team: role-less titles on new sessions were ignored for 56 days in favour of older titled rows (progression
    frozen on stale data), and a heavy row at 6 reps sat inside the volume band's 'two under' slack (190 lb held 7 weeks on 8-12).
    Control: the old rule (titled rows only, band floor - 2) -> the stale titled row and the leaked heavy row."""
    row = lambda d, role, reps, kg=100.0: {"date": d, "role": role, "sets": [{"kg": kg, "reps": reps, "rpe": 8.0}]}  # noqa: E731
    rows = [row("2026-11-10", "", 9), row("2026-11-03", "lower_volume", 8), row("2026-10-27", "", 6, 120.0)]
    got = live_load.same_role(rows, "lower_volume", "2026-11-14", 8, 12)
    assert [r["date"] for r in got] == ["2026-11-10", "2026-11-03"]  # the new untitled row first; the heavy 6-rep row out
    heavy = live_load.same_role(rows, "lower_heavy", "2026-11-14", 4, 6)
    assert [r["date"] for r in heavy] == ["2026-10-27"]

    def old(rows, role, target_date, lo, hi):  # control: fix round 9's rule
        same = [r for r in rows if role and r["role"] == role]
        return same or [r for r in rows if not r["role"] and lo - 2 <= r["sets"][0]["reps"] <= max(hi, lo)]

    assert [r["date"] for r in old(rows, "lower_volume", "2026-11-14", 8, 12)] == ["2026-11-03"]
    assert "2026-10-27" in [r["date"] for r in old([rows[0], rows[2]], "", "2026-11-14", 8, 12)]


# ── 9. pain-week time and short-week memory ──────────────────────────────────────────────────────────────────────────────────
def test_pain_skipped_time_is_refilled_with_reviewed_low_stress_work():
    """The ninth red team: pain weeks left 30-40 free minutes beside untrained muscles. A lift the pain rule skips gives its time to
    a reviewed movement LOW on the flagged joint. Control: the refill off -> fewer working sets that week."""
    w = _week(FIX10["r1_knee_and_lowback_5day"])
    refills = [ln for ln in _lines(w) if ln.startswith("refill (live): ")]
    assert refills and all("reviewed and low on the flagged joint" in ln for ln in refills)
    off = _week(FIX10["r1_knee_and_lowback_5day"], {(live_volume, "refill"): lambda *a: []})
    sets = lambda wk: sum(x["working_sets"] for s in wk["week"]["sessions"] for x in s["lifts"])  # noqa: E731
    assert sets(w) > sets(off)


def test_consecutive_short_weeks_rotate_what_is_under_target():
    """The ninth red team: three 1-morning weeks running served the identical session (calves 0, side delts 0, triceps 1.5). The
    rotation names a different muscle each ISO week, and the plan aims it at a slot. Control: no rotation -> identical plans."""
    lib = sw.build_world(FIX9["n8_one_morning_clean"], "approved")
    cat, lib = lib["catalog"]["movements"], lib["lib"]
    mondays = ("2026-11-16", "2026-11-23", "2026-11-30", "2026-12-07")
    plans = [live_volume.week_plan(cat, lib, 1, monday=m)["counts"] for m in mondays]
    assert len({tuple(sorted(p.items())) for p in plans}) == 4
    for m in ("calves", "side_delts", "triceps"):  # each gets its slot in one of the four weeks
        assert max(p.get(m, 0) for p in plans) >= 2, m
    with patch.object(live_volume, "SHORT_ROTATION", ()):
        assert len({tuple(sorted(live_volume.week_plan(cat, lib, 1, monday=m)["counts"].items())) for m in mondays}) == 1


# ── 10. conditioning and the slot cap ────────────────────────────────────────────────────────────────────────────────────────
def test_the_hard_conditioning_dose_sits_on_the_freest_morning_and_no_slot_runs_past_three_sets():
    """The ninth red team: the dose was squeezed to 12-16 min on the one morning without room while another had 20 free minutes,
    and calf slots ran at 4 sets against the engine's own 3-set cap. Control: the morning load ignored -> the template host;
    the cap lifted -> a 4-set slot."""
    prof = PROFILES["a_large_deficit_experienced"]
    w = _week(prof, settings={"session_cap_includes_cardio": True})
    cat, lib = w["world"]["catalog"]["movements"], w["world"]["lib"]
    plan = live_volume.week_plan(cat, lib, 5)
    host = live_volume.conditioning_host(plan)
    loads = {
        r: live_volume._morning_load([x for x in plan["rows"] if x["role"] == r])
        for r in ("shoulders_arms", "upper_volume", "lower_volume")
    }
    assert loads[host] == min(loads.values())
    hard = {s["role"] for s in w["week"]["sessions"] if s["cardio"].get("kind") in live_program.HARD_KINDS}
    assert hard <= {host}
    with patch.object(live_volume, "_morning_load", lambda rows: 0):
        assert live_volume.conditioning_host(plan) == "shoulders_arms"  # control: the tie -> the template host
    assert max(x["working_sets"] for s in w["week"]["sessions"] for x in s["lifts"] if x["tag"].startswith("accessory:")) <= 3
    with patch.dict(live_settings.HEURISTICS["slot_max_sets"], {"value": 9}):
        assert max(r["sets"] for r in live_volume.week_plan(cat, lib, 5)["rows"] if r["kind"] == "accessory") > 3


# ── 7. the notes: no blocking lint problem on any live week ─────────────────────────────────────────────────────────────────
def test_no_live_note_carries_a_blocking_lint_problem():
    """The live note changes (one load rule, the R3 line, the load clauses) never trip the blocking note lint (L1 banned jargon,
    L6/L12 the session line). Control: a load clause written with the load-model jargon ('band') -> L1."""
    w = _week(PROFILES["a_large_deficit_experienced"])
    assert sw.lint_problems(w["week"]) == []
    decide = live_load.decide

    def jargon(*a, **k):
        d = decide(*a, **k)
        return d | {"mode": "down", "clause": "Lighter today: one band lower."} if d else d

    off = _week(PROFILES["a_large_deficit_experienced"], {(live_load, "decide"): jargon})
    assert any(" L1 " in p or p.startswith("L1") or "L1" in p for p in sw.lint_problems(off["week"]))
