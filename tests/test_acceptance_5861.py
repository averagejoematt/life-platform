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
    live_program as lp,
    live_session as ls,
    live_week as lw,
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


def single_leg(e: dict) -> bool:
    """FIX-DATA's single-leg tag: a squat / step-down pattern, `unilateral` among its functional qualities, and a functional
    rating of A or better — a real single-leg exposure, not any lower movement done one side at a time."""
    return (
        e.get("pattern") in ("squat", "step_down")
        and "unilateral" in ((e.get("objective_inputs") or {}).get("functional") or [])
        and ((e.get("ratings") or {}).get("functional") or {}).get("tier") in ("S", "A")
    )


def unprogrammed(week: dict, lib: dict, catalog: dict) -> list[str]:
    """Functions the drafted WEEK does not program (red team 2026-11-12: b2 only checked the library): a unilateral lower lift,
    a carry, a trunk-STABILITY drill that is not a carry (anti-extension / anti-rotation / anti-lateral flexion), and an
    aerobic block — a conditioning block, or easy work the steps already cover beside one."""
    served = [sw._lib_entry(lib, catalog, x["key"]) for x in _lifts(week)]
    out = []
    if not any(single_leg(e) for e in served):
        out.append("unilateral")
    if not any(e.get("category") == "carry" and e.get("pattern") == "carry" for e in served):  # FIX-DATA's carry tag
        out.append("carry")
    if not any(e.get("trunk_function") in lp.TRUNK_FUNCTIONS and e.get("pattern") != "carry" for e in served):
        out.append("trunk_stability")
    # second red team: any cardio block of any length passed (a 13-minute week). Now: one block of at least CARDIO_ROOM's
    # minimum, or the steps-dose rationale (cardio_model.aerobic_plan: the week's walking already covers the easy volume)
    long_enough = any((s["cardio"].get("minutes") or 0) >= lw.CARDIO_ROOM["min_block"]["value"] for s in week["sessions"])
    steps_dose = any("no easy block — steps already give" in ln for s in week["sessions"] for ln in s.get("rationale") or [])
    if not (long_enough or steps_dose):
        out.append("aerobic")
    return out


def test_b2_unilateral_carry_trunk_and_aerobic_work_are_programmable(weeks):
    assert unprogrammable(LIB0, CAT0) == []
    bad = copy.deepcopy(LIB0)  # control 1: every carry closed in the library
    for e in xl.movements(bad).values():
        if e.get("category") == "carry":
            e["not_for_you_now"] = {"reason_code": "control", "unlock_condition": "never"}
    assert unprogrammable(bad, CAT0) == ["carry"]
    # the WEEK programs every function (full weeks, nothing trimmed for recovery)
    for name in ("a_large_deficit_experienced", "c_equipment_limited", "d_stalled_anchor_adherence_dip"):
        w = weeks[name]
        assert unprogrammed(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"]) == [], name
    # control 2: the trunk floor off -> the week's only trunk work is the crunch and the carry
    off = _week_of("a_large_deficit_experienced", {(lp, "trunk_floor"): lambda rx, ctx, state=None: []})
    assert unprogrammed(off["week"], off["world"]["lib"], off["world"]["catalog"]["movements"]) == ["trunk_stability"]
    # control 3: a week with its unilateral lift and its carry taken out
    bad_week = copy.deepcopy(weeks["a_large_deficit_experienced"]["week"])
    lib, cat = weeks["a_large_deficit_experienced"]["world"]["lib"], weeks["a_large_deficit_experienced"]["world"]["catalog"]["movements"]
    for s in bad_week["sessions"]:
        s["lifts"] = [
            x
            for x in s["lifts"]
            if not (single_leg(sw._lib_entry(lib, cat, x["key"])) or PATTERNS["carry"](sw._lib_entry(lib, cat, x["key"])))
        ]
    assert unprogrammed(bad_week, lib, cat) == ["unilateral", "carry"]
    # control 4: a week whose only structured cardio is a 13-minute stub and no steps-dose line (the red team's shared-cap week)
    stub = copy.deepcopy(weeks["a_large_deficit_experienced"]["week"])
    for s in stub["sessions"]:
        s["rationale"] = [ln for ln in s["rationale"] if "steps already give" not in ln]
        s["cardio"] = {"key": "cycling", "kind": "tempo", "minutes": 13} if s["role"] == "shoulders_arms" else {}
    assert unprogrammed(stub, lib, cat) == ["aerobic"]


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
    off = _week_of(  # control: the per-exposure fit and the joint rule both off
        "b_shoulder_flag_low_recovery",
        {(ls, "fit_exposures"): lambda rx, rot, ctx: [], (lp, "apply_joint_rule"): lambda rx, ctx, rot, flags: []},
    )
    assert "machine_shoulder_press" in {x["key"] for x in _lifts(off["week"])}


def joint_unprotected(week: dict, lib: dict, catalog: dict, joint: str, group: str) -> list[str]:
    """Served lifts that load `joint` at moderate or more with no protection: a same-group movement (the flagged pattern) still
    served, or another joint-loading lift served with no RPE cap at 7 or less on its note (the pain-monitoring rule)."""
    out = []
    for x in _lifts(week):
        e = sw._lib_entry(lib, catalog, x["key"])
        if not e or x["tag"].endswith(":carry") or lp._stress(e, joint) < 1:
            continue
        if lp._group(e.get("pattern")) == group:
            out.append(f"{x['key']}: same pattern")
        elif not any(ln.strip() in ("RPE 7", "RPE 6–7") for ln in (x["hevy_note"] or "").splitlines()):
            out.append(f"{x['key']}: no cap")
    return out


def test_c2c_a_pain_flag_reaches_every_movement_loading_that_joint_all_week(weeks):
    """Red team (PT): the shoulder pain flag (6/10, sharp) on the machine press removed the press and left the barbell bench,
    incline press, flies and overhead extensions at RPE 8-10. Now every pressing movement that loads the shoulder is avoided
    (swapped for a lower-shoulder-stress member or skipped) and every other shoulder-loading lift is capped at RPE 7 with a
    lighter load, every session of the week. The rule's line (PAIN_RULE mild_max) is a labelled heuristic."""
    b = weeks["b_shoulder_flag_low_recovery"]
    lib, cat = b["world"]["lib"], b["world"]["catalog"]["movements"]
    assert joint_unprotected(b["week"], lib, cat, "shoulder", "press") == []
    assert {x["key"] for x in _lifts(b["week"])}.isdisjoint({"barbell_bench_press", "incline_db_press", "cable_chest_fly"})
    assert any(ln.startswith("reduced (live)") for s in b["week"]["sessions"] for ln in s["rationale"])
    off = _week_of("b_shoulder_flag_low_recovery", {(lp, "apply_joint_rule"): lambda rx, ctx, rot, flags: []})  # control
    assert joint_unprotected(off["week"], lib, cat, "shoulder", "press")
    # the monitoring rule itself: a mild stated score reduces, a higher or 'sharp' one avoids
    flags = lambda note: lp.joint_flags(  # noqa: E731
        {"lib": lib, "overlay": b["world"]["overlay"], "idx": se.key_index(lib, cat)},
        [{"date": "2026-11-10", "exercises": [{"template_id": sw._tid(cat, "machine_shoulder_press"), "notes": note}]}],
        set(),
    )
    assert {f["tier"] for f in flags("shoulder pain 2/10 on the press")} == {"reduce"}
    assert {f["tier"] for f in flags("shoulder pain 6/10 on the press")} == {"avoid"}
    assert {f["tier"] for f in flags("sharp shoulder pain 2/10")} == {"avoid"}


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


def _rotations(week: dict, deferred: bool = False) -> list[str]:
    """The stall rotations a week's selection made — with `deferred`, also the ones the novelty budget held a week
    (`selection_live.enforce_novelty`: "(stall waits)")."""
    return [ln for s in week["sessions"] for ln in s["selection"] if "rotate: stall" in ln or (deferred and "(stall waits)" in ln)]


def test_c3b_a_systemic_slump_holds_the_movements_and_cuts_volume_instead(weeks):
    """Every lift regressing in an overreached week is fatigue, not a reason to churn every accessory: the movements hold
    (`systemic_regression`), the fatigue model takes sets off. Control: the systemic read off — every accessory rotates."""
    f = weeks["f_high_fatigue_poor_sleep"]["week"]
    assert _rotations(f) == [] and any("systemic fatigue" in ln for s in f["sessions"] for ln in s["selection"])
    real = sl.build_policy
    off = _week_of("f_high_fatigue_poor_sleep", {(sl, "build_policy"): lambda *a, **k: real(*a, **k) | {"systemic_regression": False}})
    assert len(_rotations(off["week"], deferred=True)) >= 10  # the churn the slump read stops (some held a week by the budget)
    d = weeks["d_stalled_anchor_adherence_dip"]["week"]  # one stalled lift among progressing ones still rotates (a real stall)
    assert _rotations(d)


def test_c3c_novelty_is_budgeted_and_upgrades_wait_for_a_block_start():
    """Stress cases for novelty churn: (1) a third new movement in a week yields to the best familiar candidate; (2) a better
    band opening mid-block holds the working lift (`upgrade_waits`) and rotates only at a block's first phase. Controls: the
    budget raised; the phase rule read as phase 1."""
    cand = lambda k, novel, tier="S": {"catalog_key": k, "title": k, "novel": novel, "tier": tier, "canonical": k}  # noqa: E731
    ranked = [cand("new_a", True), cand("familiar_b", False, "A")]
    pick, rep = sl._novelty_cap(ranked[0], ranked, {"novel_count": 2, "week_counts": Counter()}, None, None)
    assert pick["catalog_key"] == "familiar_b" and rep["code"] == "novelty_budget"
    with patch.object(sl, "MAX_NEW_PER_WEEK", 99):
        assert sl._novelty_cap(ranked[0], ranked, {"novel_count": 2, "week_counts": Counter()}, None, None)[0]["catalog_key"] == "new_a"

    held = cand("held_b", False, "B") | {"trend": "progressing", "discomfort": False, "movement_id": "held_b", "n1": {"components": {}}}
    better = cand("better_s", False, "S") | {"movement_id": "better_s"}
    ctx = lambda phase: {
        "policy": {"position": {"phase": phase, "step": 3}, "week_counts": Counter(), "rows": []},
        "slot_id": "x",
    }  # noqa: E731
    assert sl._trigger("held_b", [held, better], [], ("S", "A"), ctx(2))[0] is None  # mid-block: the upgrade waits
    assert sl._trigger("held_b", [held, better], [], ("S", "A"), ctx(2))[2] == "upgrade_waits"
    assert sl._trigger("held_b", [held, better], [], ("S", "A"), ctx(1))[0] == "pool_change"  # control: a block start rotates


def _working_sets(week: dict) -> int:
    return sum(x["working_sets"] for x in _lifts(week))


def _anchor_sets(week: dict) -> Counter:
    return Counter({x["key"]: x["working_sets"] for x in _lifts(week) if str(x["tag"]).startswith("anchor:")})


def rising_loads(w: dict) -> list[str]:
    """Lifts whose prescribed top WORKING load (as compiled for Hevy) is above his last performed top set — a load step UP."""
    world = w["world"]
    cat = world["catalog"]["movements"]
    hidx = sw.history_index(world["record"], cat, world["profile"]["as_of"])
    out = []
    for s in w["week"]["sessions"]:
        for x, wire in zip(s["lifts"], [e for e in s["wire"] if e.get("sets")]):
            tid = sw._tid(cat, x["key"])
            last = (hidx.get(tid) or [{}])[0].get("top_weight_kg")
            work = [float(st["weight_kg"]) for st in wire["sets"] if st.get("type") != "warmup" and st.get("weight_kg")]
            if last and work and max(work) > float(last) + 0.3:
                out.append(f"{s['role']}:{x['key']}")
    return out


def _lift_sets(week: dict, cost: str, lib: dict, catalog: dict) -> int:
    return sum(x["working_sets"] for x in _lifts(week) if lp.fatigue_cost({"movement_key": x["key"]}, _ctx(lib, catalog)) == cost)


def _ctx(lib: dict, catalog: dict) -> dict:
    return {"lib": lib, "idx": se.key_index(lib, catalog)}


def test_c4_volume_comes_down_when_recovery_worsens_compounds_first_and_loads_never_rise(weeks):
    """Red team (strength, recovery): under overreach the engine loaded every compound HEAVIER (a regressing squat +20 lb),
    kept the intervals, and cut only isolation. Now, on the high-fatigue profile: no load steps up anywhere, the heavy
    compounds lose the most (to 2 sets, RPE 7), isolation is kept, no hard cardio — a deload stays RECOMMENDED (his word)."""
    ws = {k: weeks[k] for k in ("a_large_deficit_experienced", "b_shoulder_flag_low_recovery", "f_high_fatigue_poor_sleep")}
    a, b, f = (w["week"] for w in ws.values())
    lib, cat = ws["f_high_fatigue_poor_sleep"]["world"]["lib"], ws["f_high_fatigue_poor_sleep"]["world"]["catalog"]["movements"]
    assert _working_sets(f) < _working_sets(b) < _working_sets(a)
    assert all(s["fatigue"]["action"] == "deload_recommended" for s in f["sessions"])  # recommended — applied only on his word
    assert rising_loads(ws["f_high_fatigue_poor_sleep"]) == [] and rising_loads(ws["b_shoulder_flag_low_recovery"]) == []
    assert not any("Heavier" in (x["hevy_note"] or "") for x in _lifts(f))
    assert all(n <= 2 for n in _anchor_sets(f).values())  # compounds cut first
    hi_cut = _lift_sets(f, "high", lib, cat) / _lift_sets(a, "high", lib, cat)
    lo_kept = _lift_sets(f, "low", lib, cat) / _lift_sets(a, "low", lib, cat)
    assert hi_cut < lo_kept, (hi_cut, lo_kept)
    assert not [s["cardio"].get("kind") for s in f["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS]
    # control 1: the load guard off -> the regressing compounds step UP again (the red team's squat)
    off = _week_of("f_high_fatigue_poor_sleep", {(lp, "guard_loads"): lambda *a, **k: []})
    assert rising_loads(off)
    # control 2: the deload shape replaced by the old accessory trim -> anchors keep 3 sets, isolation is what goes
    old = _week_of("f_high_fatigue_poor_sleep", {(lp, "deload_shape"): lambda ex: fm.trim_accessory_sets(ex, 6)})
    assert any(n > 2 for n in _anchor_sets(old["week"]).values())
    # control 3: the cardio fit off -> the hard block stays on a deload-recommended week
    hard = _week_of("f_high_fatigue_poor_sleep", {(lp, "cardio_fit"): lambda menu, live: (menu, [])})
    assert [s["cardio"].get("kind") for s in hard["week"]["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS]


def test_c4b_the_load_guard_holds_and_steps_down_by_rule():
    """The guard's decisions on synthetic exposures: regression steps 10% down, an anchor's RPE overshoot 5% down, a grind at
    the bottom of the range or a strained day holds, a progressing lift on a good day is the engine's own call (None)."""
    anchor, acc = {"kind": "anchor"}, {"kind": "accessory"}
    prev = {"lb": 155.0, "reps": 4, "rpe": 9.0}
    assert lp.load_decision(anchor, "regressing", prev, "normal", 4)["pct"] == 10
    assert lp.load_decision(anchor, "progressing", prev | {"rpe": 9.5}, "normal", 4)["pct"] == 5
    assert lp.load_decision(acc, "progressing", prev, "normal", 4)["mode"] == "hold"  # 4 reps at RPE 9, bottom of 4-6
    assert lp.load_decision(acc, "progressing", prev | {"rpe": 8.0, "reps": 6}, "strained", 4)["mode"] == "hold"
    assert lp.load_decision(acc, "progressing", prev | {"rpe": 8.0, "reps": 6}, "normal", 4) is None
    with patch.dict(lp.LOAD_POLICY, {"regress_down_pct": {"value": 0}}):  # control: the rule's step zeroed -> no down-step
        assert lp.load_decision(anchor, "regressing", prev | {"rpe": 8.0, "reps": 6}, "normal", 4) is None


def test_c5_a_stalled_anchor_changes_its_scheme(weeks):
    """Red team: the stalled bench stayed 3x4-6 'Heavier'. A stalled anchor now moves its rep range (and its load with it) —
    the stall machinery's 'adjust the loading' answer, never more volume in a deficit."""
    d = weeks["d_stalled_anchor_adherence_dip"]["week"]
    bench = next(x for s in d["sessions"] for x in s["lifts"] if x["key"] == "barbell_bench_press")
    assert bench["reps"] == "6-8" and "Now aiming 6–8" in bench["hevy_note"]
    off = _week_of("d_stalled_anchor_adherence_dip", {(lp, "stall_scheme"): lambda rx, ctx, trends: []})  # control
    assert next(x for s in off["week"]["sessions"] for x in s["lifts"] if x["key"] == "barbell_bench_press")["reps"] == "4-6"


# ══ D. programming quality ═══════════════════════════════════════════════════
LEGS = ("quadriceps", "hamstrings", "glutes", "calves")


def landmark_problems(m: dict, muscles: tuple = MAJOR, with_abs: bool = True) -> list[str]:
    """Muscles below MEV or over MRV. Abs count DIRECT ab sets only (the library's target): a carry is trunk work, but two
    farmer's-walk sets are not ab volume (red team 2026-11-12: abs passed only by counting them)."""
    out = [f"{mu} {m['landmarks'][mu]['verdict']}" for mu in muscles if m["landmarks"][mu]["verdict"] in ("below MEV", "over MRV")]
    abs_ = m["landmarks"]["abs"]
    if with_abs and abs_["sets"] < abs_["MEV"]:
        out.append(f"abs {abs_['sets']} < MEV {abs_['MEV']}")
    return out


def misallocated(m: dict, muscles: tuple = MAJOR) -> list[str]:
    """Second red team (2026-11-13): d1 tested bounds, not ALLOCATION — delts at 18 (over MAV) beside chest at its MEV passed.
    A week that leaves a major muscle under its MEV while another sits over its MAV put sets in the wrong place: they could
    have moved."""
    lm = m["landmarks"]
    over = [mu for mu in muscles if lm[mu]["sets"] > lm[mu]["MAV"]]
    under = [mu for mu in muscles if lm[mu]["sets"] < lm[mu]["MEV"]]
    return [f"{o} over MAV while {u} is under MEV" for o in over for u in under]


def test_d1_weekly_sets_per_muscle_sit_inside_the_volume_landmarks(weeks):
    for name in ("a_large_deficit_experienced", "c_equipment_limited"):  # full weeks, nothing trimmed for recovery
        assert landmark_problems(weeks[name]["m"]) == [], name
    for name, w in weeks.items():  # the DISTRIBUTION: no muscle over MAV while another is under MEV, in any profile
        assert misallocated(w["m"]) == [], name
    lop = copy.deepcopy(weeks["a_large_deficit_experienced"]["m"])  # control: delts at 20 beside chest at 6
    lop["landmarks"]["shoulders"]["sets"], lop["landmarks"]["chest"]["sets"] = 20, 6
    assert misallocated(lop) == ["shoulders over MAV while chest is under MEV"]
    # control: no trunk fallback -> the equipment-limited week's crunch slot stays empty and abs fall under MEV
    bare = _week_of("c_equipment_limited", {(lp, "trunk_fallback"): lambda e, ctx, taken: None})
    assert any(p.startswith("abs ") for p in landmark_problems(bare["m"]))
    # the SHORT week (4 mornings): legs keep 2x and every leg muscle stays at or over MEV (L5's rule, live default); chest and
    # back too. Delts and arms may sit at their floor for that week — the rule's stated cost, named here, not hidden
    e = weeks["e_short_week"]
    assert e["week"].get("short_week", "").startswith("short week (live, skip_shoulders_arms)")
    assert landmark_problems(e["m"], LEGS + ("chest", "back"), with_abs=False) == []
    slide = copy.deepcopy(e["world"]["lib"])  # control: the sequence slides (today) -> legs fall under MEV
    slide["programming_settings"] = {"short_week_rule": "slide"}
    week = sw.generate_week(PROFILES["e_short_week"], "approved", e["world"] | {"lib": slide})
    assert landmark_problems(sw.measure(week, slide, e["world"]["catalog"]["movements"], LANDMARKS), LEGS, with_abs=False)
    # control: abs counted the old way (carry sets credited) would pass a week with no direct trunk drill
    no_floor = _week_of("a_large_deficit_experienced", {(lp, "trunk_floor"): lambda rx, ctx, state=None: []})
    assert "abs 2.0 < MEV 4" in landmark_problems(no_floor["m"])
    # a trimmed week takes sets from the muscle furthest above its MEV first (the delts), never past MRV anywhere
    full = weeks["a_large_deficit_experienced"]["m"]["landmarks"]
    for name in ("b_shoulder_flag_low_recovery", "d_stalled_anchor_adherence_dip", "f_high_fatigue_poor_sleep"):
        lm = weeks[name]["m"]["landmarks"]
        assert lm["shoulders"]["sets"] < full["shoulders"]["sets"] and not [m for m, v in lm.items() if v["verdict"] == "over MRV"], name
    bad = copy.deepcopy(weeks["a_large_deficit_experienced"]["m"])  # control: a week with the lateral raises tripled
    bad["landmarks"]["shoulders"] = dict(bad["landmarks"]["shoulders"], sets=40, verdict="over MRV")
    assert landmark_problems(bad) == ["shoulders over MRV"]


def test_d1b_a_recovery_trim_takes_sets_where_the_week_has_most_surplus():
    """Upper volume, 2 sets off: the face pull's delts (the week's largest surplus over MEV) give them first, the chest fly
    (chest at its MEV) keeps its sets. Control: the default trim order (last-listed first) takes the arms and leaves the delts."""
    rx = ps.session_prescription_for_role("upper_volume", catalog_movements=CAT0)

    def trimmed(order):
        ex = copy.deepcopy(rx["exposures"])
        fm.trim_accessory_sets(ex, 2, order(ex) if order else None)
        return {e["slot"]: len(e["sets"]) for e in ex if e["kind"] == "accessory"}

    before = {e["slot"]: len(e["sets"]) for e in rx["exposures"] if e["kind"] == "accessory"}
    after = trimmed(ls.surplus_first(CAT0))
    assert after["face_pull"] < before["face_pull"] and after["cable_chest_fly"] == before["cable_chest_fly"]
    default = trimmed(None)
    assert default["db_curl"] < before["db_curl"] and default["face_pull"] == before["face_pull"]


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


def _light(s: dict, x: dict) -> bool:
    """The owner-pinned slot kept as a technique dose (STACK_RULE pinned_light_rpe): said in the rationale AND capped on its note."""
    said = any(ln.startswith(f"kept light (live): {x['title']} ") for ln in s["rationale"])
    return said and (x["hevy_note"] or "").startswith(f"RPE {lp.STACK_RULE['pinned_light_rpe']['value']}")


def stacked_sessions(week: dict, lib: dict, catalog: dict) -> list[str]:
    """Sessions serving more than STACK_RULE axial_per_session LOADED spinal-loading squat/hinge compounds (library joint
    stress) — a pinned slot kept light (`_light`) is a technique dose, not a loaded third lift."""
    out = []
    for s in week["sessions"]:
        ax = [x["key"] for x in s["lifts"] if lp._axial(sw._lib_entry(lib, catalog, x["key"])) and not _light(s, x)]
        if len(ax) > lp.STACK_RULE["axial_per_session"]["value"]:
            out.append(f"{s['role']}: {', '.join(ax)}")
    return out


def lower_without(week: dict, lib: dict, catalog: dict) -> list[str]:
    """Lower sessions that lost their only squat-pattern or only hinge-pattern compound (second red team: the stacking rule
    swapped the session's only bilateral squat to protect a pinned third hinge)."""
    out = []
    for s in week["sessions"]:
        if not s["role"].startswith("lower"):
            continue
        ents = [sw._lib_entry(lib, catalog, x["key"]) for x in s["lifts"]]
        # a hip thrust (a discomfort swap's low-spinal-load stand-in for the deadlift) is the hinge group's; a leg curl is not
        pats = {lp._group(e.get("pattern")) for e in ents if e.get("job") == "compound" or e.get("pattern") == "hip_extension"}
        out += [f"{s['role']}: no {p}" for p in ("squat", "hinge") if p not in pats]
        if not any(x["key"] in ("squat_barbell", "front_squat_barbell") or "squat" in x["key"] for x in s["lifts"]):
            out.append(f"{s['role']}: no squat movement")
    return out


def test_d2b_redundant_axial_fatigue_is_avoided_in_the_drafted_week(weeks):
    """Red team: every generated week stacked squat + deadlift + lunge and RDL + squat + KB deadlift; d2 only tested the
    detector. Now no drafted session carries a third LOADED spinal-loading squat/hinge compound (an unpinned one is swapped for
    a low-spinal-load member — a unilateral slot stays unilateral — or dropped). Second red team (2026-11-13): the old rule kept
    the owner-pinned kettlebell hinge by swapping the session's ONLY squat; now the pin stays as a technique dose (RPE <= 7,
    load held) and every lower session keeps a squat and a hinge."""
    for name, w in weeks.items():
        lib, cat = w["world"]["lib"], w["world"]["catalog"]["movements"]
        assert stacked_sessions(w["week"], lib, cat) == [], name
        assert lower_without(w["week"], lib, cat) == [], name
    a = weeks["a_large_deficit_experienced"]
    lower_volume = next(s for s in a["week"]["sessions"] if s["role"] == "lower_volume")
    assert "kettlebell_deadlift" in {x["key"] for x in lower_volume["lifts"]}  # the pin stands
    assert "squat_barbell" in {x["key"] for x in lower_volume["lifts"]}  # and so does the squat
    off = _week_of("a_large_deficit_experienced", {(lp, "avoid_stacking"): lambda rx, ctx, rot, pinned: []})  # control 1
    assert stacked_sessions(off["week"], off["world"]["lib"], off["world"]["catalog"]["movements"])
    # control 2: the old precedence (the pin untouched, the only squat may go) -> the squat is swapped out of lower volume
    old = _week_of("a_large_deficit_experienced", {(lp, "_lighten"): lambda e, ctx: None, (lp, "_sole"): lambda e, axial, ctx: False})
    lv = next(s for s in old["week"]["sessions"] if s["role"] == "lower_volume")
    assert "squat_barbell" not in {x["key"] for x in lv["lifts"]}


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


def morning_over_cap(week: dict) -> list[tuple[str, float]]:
    """Sessions whose lifting + cardio minutes exceed the cap — the whole morning, the red team's ~105 minutes."""
    return [
        (s["role"], (s["lifting_minutes"] or 0) + (s["cardio"].get("minutes") or 0))
        for s in week["sessions"]
        if (s["lifting_minutes"] or 0) + (s["cardio"].get("minutes") or 0) > CAP
    ]


def test_d3b_with_the_shared_cap_the_whole_morning_fits_and_conditioning_sits_on_shoulders_arms():
    """`session_cap_includes_cardio` (library setting, owner's choice; default False = today's lifting cap + a separate block):
    True makes the 75 minutes cover lifting AND cardio — every session of every profile fits, and hard conditioning lands only
    on shoulders+arms. Default: lifting still fits (d3), and an easy block the steps already cover is not added."""
    with patch.dict(sw.SETTINGS, {"session_cap_includes_cardio": True}):
        for name, prof in PROFILES.items():
            world = sw.build_world(prof, "approved")
            week = sw.generate_week(prof, "approved", world)
            assert morning_over_cap(week) == [], name
            assert {s["role"] for s in week["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS} <= {"shoulders_arms"}, name
            if name in ("a_large_deficit_experienced", "c_equipment_limited", "d_stalled_anchor_adherence_dip"):
                # second red team: lifting gives over-MAV sets (after the charter's antagonist supersets) so the week keeps a
                # real aerobic block — not the 13-minute stub the shared cap used to leave
                assert max(s["cardio"].get("minutes") or 0 for s in week["sessions"]) >= lw.CARDIO_ROOM["min_block"]["value"], name
        # control: the cap's minute fit removed -> the 30-minute block overruns a long lifting day
        with patch.object(lp, "MIN_CARDIO_MINUTES", -(10**6)), patch.object(lp, "cardio_fit", lambda m, live: (m, [])):
            prof = PROFILES["a_large_deficit_experienced"]
            assert morning_over_cap(sw.generate_week(prof, "approved", sw.build_world(prof, "approved")))
        # control: no cardio room -> lifting keeps every set and the block is cut under the minimum (the red team's 13 min)
        with patch.object(lw, "make_cardio_room", lambda blocks, rx, mv, cap, shape: shape):
            prof = PROFILES["a_large_deficit_experienced"]
            week = sw.generate_week(prof, "approved", sw.build_world(prof, "approved"))
            assert max(s["cardio"].get("minutes") or 0 for s in week["sessions"]) < lw.CARDIO_ROOM["min_block"]["value"]


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


def filled(week: dict, lib: dict, catalog: dict) -> list[str]:
    """Training added to fill a slot, judged against an INDEPENDENT expectation (red team: comparing with the template's own
    counts could never fail): (1) every session serves exactly its template's exposures minus what the live fit says it
    skipped, dropped or trimmed for time, plus only what it says it ADDED; (2) every addition targets a muscle the week leaves
    under its MEV landmark without it (config/training_landmarks.json) — a purpose, not a slot; (3) no muscle over MRV."""
    out = []
    m = sw.measure(week, lib, catalog, LANDMARKS)
    for s in week["sessions"]:
        tmpl = ps.SESSION_TEMPLATES[s["role"]]
        expected = len(tmpl["anchors"]) + len(tmpl["accessories"])
        rat = s["rationale"]
        expected -= sum(1 for ln in rat if ln.startswith(("skipped (live)", "dropped (live)")))
        added_titles = {ln[len("added (live): ") :].split(" — ")[0].rsplit(" ", 3)[0] for ln in rat if ln.startswith("added (live): ")}
        timed = [
            t
            for ln in rat
            if ln.startswith("time (live)") and "dropped " in ln
            for t in ln.split("dropped ", 1)[1].split(" -> ")[0].split(", ")
        ]  # second red team: the time fit takes surplus SETS first and says so; only "dropped …" names a whole exercise
        expected -= sum(1 for t in timed if t not in added_titles)  # an added drill the time fit dropped was never a template slot
        moved = [x for x in s["lifts"] if any(ln.startswith(f"added (live): {x['title']} — short week") for ln in rat)]
        added = [x for x in s["lifts"] if any(ln.startswith(f"added (live): {x['title']} ") for ln in rat) and x not in moved]
        if len(s["lifts"]) != expected + len(added) + len(moved):
            out.append(f"{s['role']}: {len(s['lifts'])} exercises, expected {expected} + {len(added)} added + {len(moved)} moved")
        for x in added:  # a MOVED exposure (the short week's carry) is the skipped day's own, not new training
            t = (sw._lib_entry(lib, catalog, x["key"]).get("target") or {}).get("primary")
            mu = sw.LANDMARK_OF.get(str(t), str(t))
            lm = m["landmarks"].get(mu)
            if not lm or lm["sets"] - x["working_sets"] >= lm["MEV"]:
                out.append(f"{s['role']}: {x['key']} added for {mu}, already at MEV without it")
    out += [f"{mu} over MRV" for mu, v in m["landmarks"].items() if v["verdict"] == "over MRV"]
    return out


def test_d5_no_training_is_added_to_fill_slots(weeks):
    for name, w in weeks.items():
        assert filled(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"]) == [], name
    w = weeks["c_equipment_limited"]
    lib, cat = w["world"]["lib"], w["world"]["catalog"]["movements"]
    bad = copy.deepcopy(w["week"])  # control 1: a skipped slot "refilled" with an extra movement and no line saying why
    bad["sessions"][1]["lifts"] += [dict(bad["sessions"][1]["lifts"][-1], key="extra")]
    assert filled(bad, lib, cat)
    bad = copy.deepcopy(weeks["a_large_deficit_experienced"]["week"])  # control 2: an "addition" for a muscle already over MEV
    s = bad["sessions"][0]
    lr = next(x for x in s["lifts"] if "lateral" in x["key"])
    s["lifts"].append(dict(lr))
    s["rationale"].append(f"added (live): {lr['title']} 2 x 8-12 — a filler")
    assert any("already at MEV" in p for p in filled(bad, weeks["a_large_deficit_experienced"]["world"]["lib"], cat))


def exercise_count_problems(week: dict) -> list[str]:
    lo, hi = EXERCISES_PER_SESSION
    return [f"{s['role']}: {len(s['lifts'])}" for s in week["sessions"] if not lo <= len(s["lifts"]) <= hi]


def test_d6_each_session_has_a_sensible_number_of_exercises(weeks):
    for name, w in weeks.items():
        assert exercise_count_problems(w["week"]) == [], name
    # control: today's red-day rule (every accessory dropped) leaves the aesthetic day one exercise long
    strip = _week_of("b_shoulder_flag_low_recovery", {(ls, "drop_accessories"): lambda autoreg, rx, rat, at: autoreg <= at})
    assert exercise_count_problems(strip["week"])


def test_d7_a_trunk_slot_keeps_its_function_even_when_his_fit_favours_another():
    """Stress case — the top-ranked movement is the wrong practical choice: his N=1 fit favours the torso-rotation machine,
    but the crunch slot's job is loaded flexion (L1's trunk_function); the slot serves a crunch. Control: the rule off and
    the rotation machine serves the crunch slot."""
    slot = "lower_volume.machine_crunch"
    tid = str(LIB0["movements"]["torso_rotation"]["template_id"]).upper()
    ov = {
        "pain_source": xl.PAIN_SOURCE_ID,
        "per_template": {
            tid: {
                "best_set_by_band": {"8-12": {"date": "2026-11-10", "weight_kg": 40, "reps": 12}},
                "note_signals": {"sentiment_positive": 3},
            }
        },
    }
    pick = next(s for s in _select_live(overlay=ov)["slots"] if s["slot_id"] == slot)["pick"]
    assert pick["movement_id"] != "torso_rotation" and LIB0["movements"][pick["movement_id"]]["trunk_function"] == "loaded_flexion"
    with patch.object(sl, "same_trunk_job", lambda entry, ctx: True):
        off = next(s for s in _select_live(overlay=ov)["slots"] if s["slot_id"] == slot)["pick"]
    assert off["movement_id"] == "torso_rotation"


def test_d8_the_rationale_names_what_serves_when_the_ledger_already_decided_the_phase():
    rot = {
        "selection": {
            "mode": "live",
            "slots": [{"slot_id": "upper_heavy.db_lateral_raise", "pick": {"catalog_key": "lateral_raise_machine"}}],
        },
        "source": "selection",
        "slots": [{"slot_id": "upper_heavy.db_lateral_raise", "source": "ledger", "variant": "db_lateral_raise"}],
        "rationale": ["selection: Lateral Raise (Machine) [tier A] for upper_heavy.db_lateral_raise — hold: progressing"],
    }
    assert "THIS phase serves db_lateral_raise" in ls.rotation_lines(rot)[0]
    shadow = rot | {"selection": rot["selection"] | {"mode": "shadow"}}  # control: shadow lines are never rewritten
    assert ls.rotation_lines(shadow) == rot["rationale"]


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
