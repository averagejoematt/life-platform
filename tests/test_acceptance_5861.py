"""#5861 L6 — the A+ ACCEPTANCE SUITE (owner brief §11) over the INTEGRATED engine, run in LIVE mode.

Live mode = an IN-MEMORY copy of `config/exercise_library.json` with `status: approved` (the committed file stays `proposed`;
`test_the_committed_library_stays_proposed` holds that). The weeks are drafted through the real path by
`scripts/sample_weeks_5861.py` over the synthetic profiles in `tests/fixtures/sample_week_profiles_5861.json`: the selection's
live policy, the live session fit, the fatigue model, loads, warm-ups, composed Hevy notes, the cardio menu, the compiler.
Offline and deterministic: no clock, no AWS, no Hevy.

Every gate has a MUST-FAIL CONTROL in the same test: the gate's own check run on a planted defect, or the engine run with
the guarded behaviour patched out, and the check must go red. The five groups:

  A. scientific / ranking consistency — cardio never penalised on hypertrophy; functional movements rated on function;
     evidence confidence separate from the tier; every tier carries its basis; the rankings reproduce.
  B. coverage — every major muscle and pattern in a drafted week; unilateral, carry, trunk-stability and aerobic work
     programmable; missing equipment never prescribed.
  C. individualization — his own response changes a pick; pain and equipment respected on every exposure; a progressing
     movement is held; volume comes down when recovery worsens.
  D. programming quality — weekly sets per muscle inside the volume landmarks; redundant axial fatigue detected; every
     session within 75 minutes by the #5799 model; progression trackable; nothing added to fill a slot; 4-8 exercises.
  E. regression — every pre-epic key and template id resolves; the program's movements resolve; the served drafts in
     shadow are the base tree's (tests/test_no_live_change_5861_l6.py) — this file only checks the switch stays off.
"""

from __future__ import annotations

import copy
import json
import pathlib
import random
import sys
from collections import Counter
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts", REPO / "deploy"):
    sys.path.insert(0, str(_p))

import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    exercise_library as xl,
    fatigue_model as fm,
    live_session as ls,
    program_structure as ps,
    selection_engine as se,
    selection_live as sl,
    variant_rotation as vr,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())
PROFILES = sw.load_profiles()
MAJOR = ("chest", "back", "shoulders", "biceps", "triceps", "quadriceps", "hamstrings", "glutes", "calves")
"""The landmark muscles a full week must place inside [MEV, MRV]. Forearms are optional (rows, deadlifts and carries load
them — the brief: direct forearm work is not assumed necessary); abs are held separately with trunk work credited."""
CAP = 75
EXERCISES_PER_SESSION = (4, 8)  # the owner's principle: the engine picks the 4-8 right exercises, not every good one
ROLE_SETS = {
    r: sum(len(e["sets"]) for e in ps.session_prescription_for_role(r, catalog_movements=CAT0)["exposures"]) for r in ps.SPLIT_ROLES
}


@pytest.fixture(scope="module")
def weeks() -> dict[str, dict]:
    """Every profile's week, drafted live, with its world and measures (computed once)."""
    out = {}
    for name, prof in PROFILES.items():
        world = sw.build_world(prof, "approved")
        week = sw.generate_week(prof, "approved", world)
        out[name] = {"world": world, "week": week, "m": sw.measure(week, world["lib"], world["catalog"]["movements"], LANDMARKS)}
    return out


def _live_lib() -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = "approved"
    return lib


def _lifts(week: dict) -> list[dict]:
    return [x for s in week["sessions"] for x in s["lifts"]]


def _week_of(name: str, patches: dict) -> dict:
    """One profile's week drafted live with `patches` ({(module, attr): replacement}) applied — a must-fail control."""
    prof = PROFILES[name]
    world = sw.build_world(prof, "approved")
    with contextlib_patches(patches):
        week = sw.generate_week(prof, "approved", world)
    return {"world": world, "week": week, "m": sw.measure(week, world["lib"], world["catalog"]["movements"], LANDMARKS)}


class contextlib_patches:  # noqa: N801 — a tiny context manager over several patch.object calls
    def __init__(self, patches: dict):
        self.ps = [patch.object(mod, attr, val) for (mod, attr), val in patches.items()]

    def __enter__(self):
        for p in self.ps:
            p.start()

    def __exit__(self, *exc):
        for p in self.ps:
            p.stop()


# ══ A. scientific / ranking consistency ══════════════════════════════════════
def cardio_penalised(lib: dict) -> list[str]:
    """Conditioning movements carrying a hypertrophy TIER (a growth verdict on cardio), or with no conditioning rating."""
    out = []
    for k, e in xl.movements(lib).items():
        if e.get("category") != "conditioning":
            continue
        r = e.get("ratings") or {}
        if (r.get("hypertrophy") or {}).get("tier") is not None or not (r.get("conditioning") or {}).get("tier"):
            out.append(k)
    return out


def test_a1_cardio_is_never_rated_on_hypertrophy_and_never_a_hypertrophy_candidate():
    assert cardio_penalised(LIB0) == []
    treadmill = LIB0["movements"]["treadmill"]
    assert sl.objective_tier(treadmill, "hypertrophy", "quadriceps") is None  # live: never a hypertrophy candidate
    assert sl.objective_tier(treadmill, "conditioning", None) in ("S", "A")
    bad = copy.deepcopy(LIB0)  # control: a growth tier planted on a cardio row
    bad["movements"]["treadmill"]["ratings"]["hypertrophy"]["tier"] = "D"
    assert cardio_penalised(bad) == ["treadmill"]


def functional_unrated(lib: dict) -> list[str]:
    """A movement with a functional quality but no functional tier — judged only by its direct stimulus. A conditioning
    modality is rated on conditioning instead (the rubric's own rule), never left unrated."""
    return sorted(
        k
        for k, e in xl.movements(lib).items()
        if (e.get("objective_inputs") or {}).get("functional")
        and not ((e.get("ratings") or {}).get("functional") or {}).get("tier")
        and not (e.get("category") == "conditioning" and ((e.get("ratings") or {}).get("conditioning") or {}).get("tier"))
    )


def test_a2_functional_movements_are_rated_on_function_not_only_direct_stimulus():
    assert functional_unrated(LIB0) == []
    # the anomalies the owner named: low/no growth tier, a high functional tier
    for k in ("farmers_walk", "walking_lunge_dumbbell", "sled_push", "suitcase_carry"):
        r = LIB0["movements"][k]["ratings"]
        assert r["functional"]["tier"] in ("S", "A"), k
        assert r["hypertrophy"]["tier"] in (None, "B", "C", "D"), k
    bad = copy.deepcopy(LIB0)  # control: a carry with its functional rating dropped
    bad["movements"]["farmers_walk"]["ratings"]["functional"]["tier"] = None
    assert "farmers_walk" in functional_unrated(bad)


def evidence_conflated(lib: dict) -> list[str]:
    """Ratings with no separate evidence field, plus a check that evidence does not decide the tier."""
    out = []
    pairs: dict[str, set] = {}
    for k, e in xl.movements(lib).items():
        for obj, r in (e.get("ratings") or {}).items():
            if (r or {}).get("tier") is None:
                continue
            if "evidence_confidence" not in r:
                out.append(f"{k}.{obj}")
            pairs.setdefault(r["tier"], set()).add(r.get("evidence_confidence"))
    if len(pairs.get("S", set()) | pairs.get("A", set())) < 2:
        out.append("every top-band rating shares one evidence level: evidence and recommendation look like one field")
    return out


def test_a3_evidence_confidence_is_distinguishable_from_the_recommendation():
    assert evidence_conflated(LIB0) == []
    bad = copy.deepcopy(LIB0)  # control: a rating with its evidence field removed
    del bad["movements"]["hip_thrust_machine"]["ratings"]["hypertrophy"]["evidence_confidence"]
    assert evidence_conflated(bad) == ["hip_thrust_machine.hypertrophy"]


def unexplained(lib: dict) -> list[str]:
    return sorted(
        f"{k}.{o}"
        for k, e in xl.movements(lib).items()
        for o, r in (e.get("ratings") or {}).items()
        if r and r.get("tier") and not r.get("basis")
    )


def test_a4_every_tier_carries_its_basis():
    assert unexplained(LIB0) == []
    bad = copy.deepcopy(LIB0)
    bad["movements"]["squat_barbell"]["ratings"]["strength"]["basis"] = []
    assert unexplained(bad) == ["squat_barbell.strength"]


def _select_live(lib: dict | None = None, overlay: dict | None = None, rows: list | None = None) -> dict:
    lib = lib or _live_lib()
    pos = vr.position({"week": 10, "block": 2})
    policy = sl.build_policy(lib, position=pos, rows=rows or [], block_workouts=None, as_of="2026-11-16", gate_eval=None)
    return se.select_week(pos, copy.deepcopy(CAT0), lib, overlay, rows=rows or [], missing=[], policy=policy)


def _picks(sel: dict) -> dict[str, str | None]:
    return {s["slot_id"]: (s.get("pick") or {}).get("catalog_key") for s in sel["slots"]}


def test_a5_rankings_reproduce(weeks):
    assert _picks(_select_live()) == _picks(_select_live())
    again = sw.generate_week(PROFILES["a_large_deficit_experienced"], "approved", weeks["a_large_deficit_experienced"]["world"])
    assert again["sessions"] == weeks["a_large_deficit_experienced"]["week"]["sessions"]
    real = sl.rank_key  # control: a random term in the live rank — two runs must disagree somewhere

    def noisy(*a, **k):
        return (random.random(),) + real(*a, **k)

    random.seed(5861)
    with patch.object(sl, "rank_key", noisy):
        runs = [_picks(_select_live()) for _ in range(3)]
    assert any(r != runs[0] for r in runs[1:])


# ══ B. coverage ══════════════════════════════════════════════════════════════
PATTERNS = {
    "horizontal_press": lambda e: e.get("pattern") == "horizontal_press",
    "vertical_press": lambda e: e.get("pattern") == "vertical_press",
    "horizontal_pull": lambda e: e.get("pattern") == "horizontal_pull",
    "vertical_pull": lambda e: e.get("pattern") == "vertical_pull",
    "squat": lambda e: e.get("pattern") == "squat",
    "hinge": lambda e: e.get("pattern") == "hinge",
    "unilateral_lower": lambda e: "unilateral" in ((e.get("objective_inputs") or {}).get("functional") or [])
    and (e.get("target") or {}).get("region") == "lower",
    "carry": lambda e: e.get("category") == "carry",
    "trunk": lambda e: bool(e.get("trunk_function")),
}


def week_gaps(week: dict, lib: dict, catalog: dict) -> list[str]:
    """Major muscles under MEV, patterns with no exposure, and a week with fewer conditioning blocks than the charter's two."""
    m = sw.measure(week, lib, catalog, LANDMARKS)
    out = [f"{mu} below MEV ({m['landmarks'][mu]['sets']})" for mu in MAJOR if m["landmarks"][mu]["verdict"] == "below MEV"]
    served = [sw._lib_entry(lib, catalog, x["key"]) for x in _lifts(week)]
    out += [f"no {p}" for p, f in PATTERNS.items() if not any(f(e) for e in served)]
    hard = [s["cardio"].get("kind") for s in week["sessions"] if s["cardio"].get("kind") in ("tempo", "hills", "intervals")]
    out += [] if len(hard) >= 2 else [f"{len(hard)} conditioning blocks (charter: 2)"]
    return out


def test_b1_a_full_week_covers_every_major_muscle_and_pattern(weeks):
    w = weeks["a_large_deficit_experienced"]
    assert week_gaps(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"]) == []
    bad = copy.deepcopy(w["week"])  # control: the squats gone from the week
    for s in bad["sessions"]:
        s["lifts"] = [x for x in s["lifts"] if x["key"] != "squat_barbell"]
    assert "quadriceps below MEV" in " ".join(week_gaps(bad, w["world"]["lib"], w["world"]["catalog"]["movements"]))


def unprogrammable(lib: dict, catalog: dict) -> list[str]:
    """Functions with no movement the engine can SERVE today (catalog-writable, available, no locked gate, not
    not_for_you_now): unilateral lower work, carries, trunk stability, aerobic work."""
    idx = se.key_index(lib, catalog)
    servable = [
        e
        for k, e in xl.movements(lib).items()
        if k in idx["to_cat"] and not se.availability(e, lib, None) and not se.locked_gates(e, lib) and not se.not_for_you_now(e)
    ]
    need = {
        "unilateral": PATTERNS["unilateral_lower"],
        "carry": PATTERNS["carry"],
        "trunk_stability": lambda e: str(e.get("trunk_function") or "").startswith("anti_")
        or e.get("trunk_function") == "loaded_stabilisation",
        "aerobic": lambda e: e.get("category") == "conditioning"
        and ((e.get("ratings") or {}).get("conditioning") or {}).get("tier") in "SAB",
    }
    return [n for n, f in need.items() if not any(f(e) for e in servable)]


def test_b2_unilateral_carry_trunk_and_aerobic_work_are_programmable():
    assert unprogrammable(LIB0, CAT0) == []
    bad = copy.deepcopy(LIB0)  # control: every carry closed
    for e in xl.movements(bad).values():
        if e.get("category") == "carry":
            e["not_for_you_now"] = {"reason_code": "control", "unlock_condition": "never"}
    assert unprogrammable(bad, CAT0) == ["carry"]


def impossible(week: dict, lib: dict, catalog: dict, overlay: dict | None = None) -> list[str]:
    """Every served lift the gym can't serve (home_gym availability under the profile's inventory) or his pain note names."""
    out = []
    for x in _lifts(week):
        e = sw._lib_entry(lib, catalog, x["key"])
        if e and (se.availability(e, lib, overlay) or se.pain_exclusion(e, overlay)):
            out.append(x["key"])
    return out


def test_b3_missing_equipment_never_yields_an_impossible_prescription(weeks):
    w = weeks["c_equipment_limited"]
    assert impossible(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"]) == []
    # control 1: today's (shadow) path over the same world prescribes the machines the gym lacks
    shadow = sw.generate_week(PROFILES["c_equipment_limited"], "proposed", sw.build_world(PROFILES["c_equipment_limited"], "proposed"))
    assert impossible(shadow, w["world"]["lib"], w["world"]["catalog"]["movements"])
    # control 2: the live session fit switched off
    off = _week_of("c_equipment_limited", {(ls, "fit_exposures"): lambda rx, rot, ctx: []})
    assert impossible(off["week"], off["world"]["lib"], off["world"]["catalog"]["movements"])


# ══ C. individualization ═════════════════════════════════════════════════════
def test_c1_his_own_response_changes_a_pick():
    """An overlay that says the slot's top pick regressed for him and he dislikes it moves the slot to another movement."""
    slot = "upper_heavy.db_curl"
    top = next(s for s in _select_live()["slots"] if s["slot_id"] == slot)["pick"]
    tid = str(LIB0["movements"][top["movement_id"]]["template_id"]).upper()
    ov = {
        "pain_source": xl.PAIN_SOURCE_ID,
        "per_template": {
            tid: {
                "best_set_by_band": {
                    "8-12": {"date": "2026-10-01", "weight_kg": 30, "reps": 12},
                    "4-7": {"date": "2026-11-10", "weight_kg": 20, "reps": 5},
                },
                "note_signals": {"sentiment_negative": 3},
            }
        },
    }
    moved = next(s for s in _select_live(overlay=ov)["slots"] if s["slot_id"] == slot)["pick"]
    assert moved["movement_id"] != top["movement_id"] and moved["n1"]["score"] >= 0
    real = sl.rank_key  # control: the N=1 term dropped from the live rank — the overlay no longer moves the pick

    def blind(c, recent, slot_last, pool):
        return real(c | {"n1": {"score": 0}}, recent, slot_last, pool)

    with patch.object(sl, "rank_key", blind):
        same = next(s for s in _select_live(overlay=ov)["slots"] if s["slot_id"] == slot)["pick"]
    assert same["movement_id"] == top["movement_id"]


def test_c2_pain_and_equipment_are_respected_on_every_exposure(weeks):
    b = weeks["b_shoulder_flag_low_recovery"]
    assert impossible(b["week"], b["world"]["lib"], b["world"]["catalog"]["movements"], b["world"]["overlay"]) == []
    assert "machine_shoulder_press" not in {x["key"] for x in _lifts(b["week"])}
    off = _week_of("b_shoulder_flag_low_recovery", {(ls, "fit_exposures"): lambda rx, rot, ctx: []})  # control
    assert "machine_shoulder_press" in {x["key"] for x in _lifts(off["week"])}


def test_c2b_repeated_discomfort_on_a_weekly_anchor_moves_it_to_a_lower_joint_load(weeks):
    """Two discomfort-class notes on the weekly conventional deadlift (7 and 14 days back on its own weekday): the heavy hinge
    goes to the role's listed hinge that loads the lower back less; nothing is skipped for discomfort alone."""
    f = weeks["f_high_fatigue_poor_sleep"]["week"]
    lower = next(s for s in f["sessions"] if s["role"] == "lower_heavy")
    assert any(ln.startswith("swapped (live): Deadlift (Barbell) -> Hip Thrust (Machine) — discomfort") for ln in lower["rationale"])
    assert "deadlift_barbell" not in {x["key"] for x in lower["lifts"]}
    rec = [
        {
            "date": d,
            "exercises": [
                {"template_id": "C6272009", "notes": "lower back achy", "sets": [{"type": "normal", "weight_kg": 100, "reps": 5}]}
            ],
        }
        for d in ("2026-11-03", "2026-11-10")
    ]
    assert fm.movement_signals(rec, as_of="2026-11-17")["C6272009"]["discomfort_sessions"] == 2  # the inclusive fortnight
    assert fm.movement_signals(rec, as_of="2026-11-18")["C6272009"]["discomfort_sessions"] == 1  # control: a day later, one


def rotated_while_progressing(week: dict, world: dict) -> list[str]:
    """Slots whose previous variant was progressing in his record yet the live selection rotated it."""
    out = []
    for s in week["sessions"]:
        for ln in s["selection"]:
            if "rotate: stall" in ln or "rotate: pool_change" in ln:
                out.append(ln.split(" for ")[1].split(" ")[0])
    sig = fm.movement_signals(world["record"], as_of=world["profile"]["as_of"])
    prog = {tid for tid, v in sig.items() if v.get("trend") == "progressing"}
    return [slot for slot in out if sw._tid(world["catalog"]["movements"], vr._ledger_variant(world["rows"], 2, slot, 1) or "") in prog]


def test_c3_a_progressing_movement_is_held_not_rotated(weeks):
    a = weeks["a_large_deficit_experienced"]
    holds = [ln for s in a["week"]["sessions"] for ln in s["selection"] if "hold: progressing" in ln]
    assert len(holds) >= 10 and rotated_while_progressing(a["week"], a["world"]) == []

    def strict(pts, e1):  # control: the pre-L6 trend (latest strictly beats every earlier exposure)
        return e1[-1] > max(e1[:-1])

    off = _week_of("a_large_deficit_experienced", {(fm, "_recent_best"): strict})
    stalls = [ln for s in off["week"]["sessions"] for ln in s["selection"] if "rotate: stall" in ln]
    assert stalls, "the strict trend reads a twice-a-week progressing movement as a stall"


def _working_sets(week: dict) -> int:
    return sum(x["working_sets"] for x in _lifts(week))


def _anchor_sets(week: dict) -> Counter:
    return Counter({x["key"]: x["working_sets"] for x in _lifts(week) if str(x["tag"]).startswith("anchor:")})


def test_c4_volume_comes_down_when_recovery_worsens_and_strength_work_is_held(weeks):
    a, b, f = (weeks[k]["week"] for k in ("a_large_deficit_experienced", "b_shoulder_flag_low_recovery", "f_high_fatigue_poor_sleep"))
    assert _working_sets(f) < _working_sets(b) < _working_sets(a)
    assert all(s["fatigue"]["action"] == "deload_recommended" for s in f["sessions"])  # recommended — applied only on his word
    shared = set(_anchor_sets(a)) & set(_anchor_sets(f))
    assert shared and all(_anchor_sets(f)[k] == _anchor_sets(a)[k] for k in shared)  # anchors held
    off = _week_of("f_high_fatigue_poor_sleep", {(fm, "trim_accessory_sets"): lambda ex, n: 0})  # control: the reduction off
    assert _working_sets(off["week"]) > _working_sets(f)


# ══ D. programming quality ═══════════════════════════════════════════════════
def landmark_problems(m: dict) -> list[str]:
    out = [f"{mu} {m['landmarks'][mu]['verdict']}" for mu in MAJOR if m["landmarks"][mu]["verdict"] in ("below MEV", "over MRV")]
    abs_ = m["landmarks"]["abs"]
    if abs_["sets"] + m.get("trunk_sets", 0) < abs_["MEV"]:
        out.append(f"abs + trunk work {abs_['sets'] + m.get('trunk_sets', 0)} < MEV {abs_['MEV']}")
    return out


def test_d1_weekly_sets_per_muscle_sit_inside_the_volume_landmarks(weeks):
    for name in ("a_large_deficit_experienced", "c_equipment_limited", "d_stalled_anchor_adherence_dip"):
        assert landmark_problems(weeks[name]["m"]) == [], name
    bad = copy.deepcopy(weeks["a_large_deficit_experienced"]["m"])  # control: a week with the lateral raises tripled
    bad["landmarks"]["shoulders"] = dict(bad["landmarks"]["shoulders"], sets=40, verdict="over MRV")
    assert landmark_problems(bad) == ["shoulders over MRV"]


def test_d2_redundant_axial_fatigue_is_detected():
    lib = _live_lib()
    idx = fm.library_index(lib)
    ex = lambda tid: {"template_id": tid, "sets": [{"type": "normal", "weight_kg": 100, "reps": 5, "rpe": 8}] * 3}  # noqa: E731
    rec = [
        {"date": "2026-11-14", "exercises": [ex("D04AC939")]},  # squat
        {"date": "2026-11-15", "exercises": [ex("C6272009")]},  # conventional deadlift
        {"date": "2026-11-16", "exercises": [ex("2B4B7310")]},  # RDL
    ]
    found = {f["finding"] for f in fm.axial_stacking(rec, idx, as_of="2026-11-16")}
    assert found == {"axial_stacking", "hinge_stacking"}
    policy = sl.build_policy(lib, position=None, rows=[], block_workouts=rec, as_of="2026-11-16", gate_eval=None)
    assert policy["stacking"] and sl.fatigue_cost(lib["movements"]["squat_barbell"], True) > sl.fatigue_cost(
        lib["movements"]["squat_barbell"], False
    )
    with patch.object(fm, "AXIAL_PATTERNS", ()):  # control: the detector blind to squat/hinge
        assert fm.axial_stacking(rec, idx, as_of="2026-11-16") == []


def over_cap(week: dict) -> list[tuple[str, float]]:
    return [(s["role"], s["lifting_minutes"]) for s in week["sessions"] if (s["lifting_minutes"] or 0) > CAP]


def test_d3_every_session_fits_75_minutes_by_the_5799_model(weeks):
    assert {n: over_cap(w["week"]) for n, w in weeks.items() if over_cap(w["week"])} == {}
    # stress: no load on file for anything (a first week back): every lift gets its "find the load" warm-up set as written,
    # the time the prescription's estimate does not see — the routine is still fitted to the ceiling, accessories first
    real = sw.history_index
    cold = {(sw, "history_index"): lambda record, catalog=None, as_of=None: {}}
    stressed = _week_of("a_large_deficit_experienced", cold)
    assert over_cap(stressed["week"]) == [] and any("time (live)" in ln for s in stressed["week"]["sessions"] for ln in s["rationale"])
    off = _week_of("a_large_deficit_experienced", cold | {(ls, "fit_routine"): lambda blocks, rx, cap, mv, rat, shape: shape})
    assert over_cap(off["week"]), "control: without the routine fit the warm-ups as written run past the ceiling"
    assert sw.history_index is real


def untrackable(week: dict, catalog: dict) -> list[str]:
    """A lift that can't be tracked session to session: no Hevy template id, no rep target, or no effort line on its note."""
    out = []
    for x in _lifts(week):
        if str(x["tag"]).endswith(":carry"):
            continue  # a carry is distance-dosed: steps in the yards box (#5373)
        tid = (catalog.get(x["key"]) or {}).get("hevy_template_id_hint") or sw._tid(catalog, x["key"])
        if not tid or not x["reps"] or "RPE" not in (x["hevy_note"] or ""):
            out.append(x["key"])
    return out


def test_d4_progression_is_trackable(weeks):
    for name, w in weeks.items():
        assert untrackable(w["week"], w["world"]["catalog"]["movements"]) == [], name
    bad = copy.deepcopy(weeks["a_large_deficit_experienced"]["week"])  # control: a lift with no rep target
    bad["sessions"][0]["lifts"][0]["reps"] = ""
    assert untrackable(bad, weeks["a_large_deficit_experienced"]["world"]["catalog"]["movements"])


def filled(week: dict) -> list[str]:
    """A session with more working sets or more exercises than its role's template: training added to fill slots."""
    out = []
    for s in week["sessions"]:
        tmpl = ps.SESSION_TEMPLATES[s["role"]]
        n_ex = len(tmpl["anchors"]) + len(tmpl["accessories"])
        sets = sum(x["working_sets"] for x in s["lifts"])
        if sets > ROLE_SETS[s["role"]] or len(s["lifts"]) > n_ex:
            out.append(f"{s['role']}: {sets} sets / {len(s['lifts'])} exercises")
    return out


def test_d5_no_training_is_added_to_fill_slots(weeks):
    for name, w in weeks.items():
        assert filled(w["week"]) == [], name
    bad = copy.deepcopy(weeks["c_equipment_limited"]["week"])  # control: a skipped slot "refilled" with an extra movement
    bad["sessions"][1]["lifts"] += [dict(bad["sessions"][1]["lifts"][-1], key="extra")] * 2
    assert filled(bad)


def exercise_count_problems(week: dict) -> list[str]:
    lo, hi = EXERCISES_PER_SESSION
    return [f"{s['role']}: {len(s['lifts'])}" for s in week["sessions"] if not lo <= len(s["lifts"]) <= hi]


def test_d6_each_session_has_a_sensible_number_of_exercises(weeks):
    for name, w in weeks.items():
        assert exercise_count_problems(w["week"]) == [], name
    # control: today's red-day rule (every accessory dropped) leaves the aesthetic day one exercise long
    strip = _week_of("b_shoulder_flag_low_recovery", {(ls, "drop_accessories"): lambda autoreg, rx, rat, at: autoreg <= at})
    assert exercise_count_problems(strip["week"])


# ══ E. regression / compatibility ════════════════════════════════════════════
def unresolved(lib: dict, pre: dict[str, str]) -> list[str]:
    return sorted(k for k, tid in pre.items() if xl.canonical_of(lib, k) is None or (tid and xl.canonical_of(lib, tid) is None))


def test_e1_every_pre_epic_key_and_template_id_still_resolves():
    pre = json.loads((REPO / "tests" / "fixtures" / "exercise_library_keys_pre_5861.json").read_text())["keys"]
    assert len(pre) >= 578 and unresolved(LIB0, pre) == []
    bad = copy.deepcopy(LIB0)  # control: one pre-epic movement removed
    del bad["movements"]["squat_barbell"]
    assert "squat_barbell" in unresolved(bad, pre)


def program_keys() -> set[str]:
    keys = {k for a in ps.ANCHORS.values() for k in list(a["catalog_keys"]) + list(a.get("moderate_catalog_keys") or [])}
    keys |= {k for t in ps.SESSION_TEMPLATES.values() for k in t["accessories"]}
    keys |= {k for t in ps.SESSION_TEMPLATES.values() for ks in (t.get("anchor_keys") or {}).values() for k in ks}
    keys |= {k for p in vr.VETTED_POOLS.values() for k in p.get("candidates") or []}
    return keys


def test_e2_every_movement_the_program_names_is_in_the_catalog_and_coach_additions_never_rename_one():
    import build_movement_catalog as bmc

    assert sorted(program_keys() - set(CAT0)) == []
    cur = {"movements": {"squat_barbell": {"title": "kept as written"}}}
    merged = bmc.with_coach_additions(cur, {"squat_barbell": {"title": "a stub"}, "new_key": {"title": "added"}})
    assert merged["movements"]["squat_barbell"]["title"] == "kept as written" and "new_key" in merged["movements"]
    assert sorted(program_keys() - (set(CAT0) - {"machine_row"})) == ["machine_row"]  # control: a missing key is seen


def test_e3_the_committed_library_stays_proposed_so_nothing_here_is_live():
    assert LIB0["status"] == "proposed" and se.mode(LIB0) == se.MODE_SHADOW
    assert se.mode(_live_lib()) == se.MODE_LIVE  # the suite's switch flips a COPY only
