"""#5861 FIX-DATA — the library DATA errors an independent red team found, each held by a guard of its CLASS (not the specimen)
beside a must-fail control that was run:

  * a bent-knee (seated) calf raise is never credited to the gastrocnemius;
  * a side bend is lateral flexion, never loaded flexion (the crunch slot's job);
  * every movement's primary target has a hypertrophy row (a Hevy muscle label cannot survive under another primary);
  * one canonical family -> one rating per objective for an exact duplicate, and one cardio rating per machine;
  * no twin movement (same title core, same equipment, same target) sits on two tiers outside a canonical family;
  * S is rare and justified: every S meets every S criterion; a single-leg lever stack is not S; joint-capacity work is never
    functional S; the traps' short ROM is not penalised;
  * the balance limiter never applies to an upper-body pattern; a loaded lunge / split squat / step-up has a glute row;
  * a custom template with no equipment recorded is not bodyweight; cuff rotation is joint capacity, not mobility;
  * the P0/P1 additions publish a pattern a slot job can match (never `other`).

Pure: the committed config, no AWS, no network, no clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "deploy"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import exercise_library_objectives as objectives  # noqa: E402
import exercise_library_targets as targets  # noqa: E402
from training import quality_rubric as qr  # noqa: E402

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
MV = LIB["movements"]


def _tier(e: dict, target: str) -> str | None:
    return next((r["tier"] for r in e["hypertrophy"] if r["target"] == target), None)


# ── a bent-knee calf raise is soleus only ───────────────────────────────────────────────────────────────────────────
def _bent_knee_gastroc(movements: dict) -> list[str]:
    return [
        k
        for k, e in movements.items()
        if re.search(r"seated|bent[- ]knee", str(e.get("title")), re.I)
        and re.search(r"calf", str(e.get("title")), re.I)
        and any(r["target"].startswith("gastroc") for r in e["hypertrophy"])
    ]


def test_a_bent_knee_calf_raise_is_never_credited_to_the_gastrocnemius():
    assert _bent_knee_gastroc(MV) == []
    assert [r["target"] for r in MV["seated_calf_raise"]["hypertrophy"]] == ["soleus"]
    bad = copy.deepcopy(MV)  # control
    bad["seated_calf_raise"]["hypertrophy"].append({"target": "gastrocnemius", "tier": "A"})
    assert _bent_knee_gastroc(bad) == ["seated_calf_raise"]


# ── a side bend is lateral flexion ───────────────────────────────────────────────────────────────────────────────────
def _side_bend_offenders(movements: dict) -> list[str]:
    return [
        k
        for k, e in movements.items()
        if re.search(r"side bends?|side crunch", str(e.get("title")), re.I) and e.get("trunk_function") != "lateral_flexion"
    ]


def test_a_side_bend_is_lateral_flexion_not_loaded_flexion():
    assert "lateral_flexion" in qr.TRUNK_FUNCTIONS
    assert _side_bend_offenders(MV) == []
    assert {k for k, e in MV.items() if e.get("trunk_function") == "lateral_flexion"} >= {"side_bend_dumbbell", "saxon_side_bends"}
    assert MV["side_bend_dumbbell"]["pattern"] == "core_lateral_flexion"
    bad = copy.deepcopy(MV)  # control
    bad["side_bend_dumbbell"]["trunk_function"] = "loaded_flexion"
    assert _side_bend_offenders(bad) == ["side_bend_dumbbell"]


# ── a movement's primary target has a hypertrophy row ────────────────────────────────────────────────────────────────
def _primary_row_offenders(movements: dict) -> list[str]:
    out = []
    for k, e in movements.items():
        p, rows = e["target"]["primary"], e["hypertrophy"]
        if rows and not any(objectives._same_muscle(r["target"], p) for r in rows):
            out.append(f"{k}: primary {p} rows {[r['target'] for r in rows]}")
    return out


def test_every_primary_target_has_its_hypertrophy_row():
    assert _primary_row_offenders(MV) == []
    assert [r["target"] for r in MV["cable_pallof_press"]["hypertrophy"]] == ["abs"]
    bad = copy.deepcopy(MV)  # control: the Pallof row back under `shoulders`
    bad["pallof_press"]["hypertrophy"][0]["target"] = "shoulders"
    assert [o.split(":")[0] for o in _primary_row_offenders(bad)] == ["pallof_press"]


# ── one canonical family -> one rating per objective ─────────────────────────────────────────────────────────────────
OBJ = ("hypertrophy", "strength", "functional", "conditioning", "mobility")


def _duplicate_offenders(movements: dict) -> list[str]:
    out = []
    for k, e in movements.items():
        dup = (e.get("variant") or {}).get("duplicate_of")
        if dup:
            for o in OBJ:
                if e["ratings"][o]["tier"] != movements[dup]["ratings"][o]["tier"]:
                    out.append(f"{k} vs {dup}: {o}")
    return out


def test_an_exact_duplicate_carries_one_rating_per_objective():
    assert _duplicate_offenders(MV) == []
    assert (MV["prone_leg_curl"].get("variant") or {}).get("duplicate_of") == "lying_leg_curl_machine"
    assert (MV["recumbent_bike"].get("variant") or {}).get("duplicate_of") == "cycling"
    assert set(targets.ADDITION_FAMILIES) == {"cycling"} and MV["cycling"]["canonical"] == "cycling"
    bad = copy.deepcopy(MV)  # control
    bad["prone_leg_curl"]["ratings"]["hypertrophy"]["tier"] = "C"
    assert _duplicate_offenders(bad) == ["prone_leg_curl vs lying_leg_curl_machine: hypertrophy"]


def test_one_machine_one_cardio_rating_and_the_cycling_pair_is_one_family():
    assert MV["cycling"]["ratings"]["conditioning"]["tier"] == MV["recumbent_bike"]["ratings"]["conditioning"]["tier"]
    assert MV["recumbent_bike"]["family_sustainability"] == MV["cycling"]["family_sustainability"]
    assert MV["recumbent_bike"]["equipment"] == MV["cycling"]["equipment"], "one machine, one equipment id"
    alone = copy.deepcopy(MV["recumbent_bike"])  # control: without the family stand-in the row's own count rates it apart
    alone.pop("family_sustainability")
    assert qr.objective_ratings(alone)["conditioning"]["tier"] != MV["cycling"]["ratings"]["conditioning"]["tier"]


# ── no twin on two tiers ─────────────────────────────────────────────────────────────────────────────────────────────
_NOISE = re.compile(r"\b(the|a|with|for|time|slow|cadence)\b")


def _core(title: str) -> frozenset:
    t = _NOISE.sub(" ", re.sub(r"[()/\-]", " ", title.lower()))
    return frozenset(w.rstrip("s") for w in t.split())


def _twin_offenders(movements: dict) -> list[str]:
    groups: dict = {}
    for k, e in movements.items():
        tiers = [r["tier"] for r in e["hypertrophy"] if r["tier"]]
        if tiers:
            groups.setdefault((e["target"]["primary"], _core(e["title"]), tuple(sorted(e["equipment"]))), []).append((k, min(tiers)))
    return sorted(
        ",".join(k for k, _ in g)
        for g in groups.values()
        if len(g) > 1 and len({t for _, t in g}) > 1 and len({movements[k]["canonical"] for k, _ in g}) > 1
    )


def test_no_movement_is_listed_twice_with_different_tiers():
    assert _twin_offenders(MV) == []
    bad = copy.deepcopy(MV)  # control: a twin under a different canonical on another tier
    twin = copy.deepcopy(bad["lying_leg_curl_machine"])
    twin["canonical"], twin["title"] = "x_twin", "Lying Leg Curl Machine"
    twin["hypertrophy"][0]["tier"] = "C"
    bad["x_twin"] = twin
    assert _twin_offenders(bad)


# ── S is rare and justified ──────────────────────────────────────────────────────────────────────────────────────────
def _s_without_every_criterion(movements: dict) -> list[str]:
    out = []
    for k, e in movements.items():
        for r in e["hypertrophy"]:
            if r["tier"] == "S" and not all(qr.s_criteria(e, r).values()):
                out.append(f"{k}/{r['target']}")
    return out


def test_every_hypertrophy_s_meets_every_s_criterion_including_reviewed_inputs():
    assert "reviewed_inputs" in qr.S_CRITERIA
    assert _s_without_every_criterion(MV) == []
    bad = copy.deepcopy(MV)  # control: an S row on a movement whose inputs were never reviewed
    bad["hip_thrust_machine"]["objective_inputs"]["reviewed"] = False
    assert qr.s_criteria(bad["hip_thrust_machine"], bad["hip_thrust_machine"]["hypertrophy"][0])["reviewed_inputs"] is False
    assert qr.quality_tier(bad["hip_thrust_machine"], bad["hip_thrust_machine"]["hypertrophy"][0]) == "A"


def test_a_single_leg_lever_stack_is_not_s_the_kickbacks_are_a():
    for k in ("glute_kickback_machine", "glute_machine_kickback", "cable_kickback"):
        assert MV[k]["objective_inputs"]["ceiling"] == "moderate" and _tier(MV[k], "glutes") == "A", k
    e = copy.deepcopy(MV["glute_kickback_machine"])  # control: with a high ceiling it reaches S again
    e["objective_inputs"]["ceiling"] = "high"
    assert qr.quality_tier(e, e["hypertrophy"][0]) == "S"
    assert _tier(MV["hip_thrust_machine"], "glutes") == "S", "the loadable glute lift keeps its S"


def test_joint_capacity_work_is_never_functional_s():
    offenders = [
        k for k, e in MV.items() if "joint_capacity" in e["objective_inputs"]["functional"] and e["ratings"]["functional"]["tier"] == "S"
    ]
    assert offenders == [] and MV["copenhagen_side_plank"]["ratings"]["functional"]["tier"] == "A"
    e = copy.deepcopy(MV["copenhagen_side_plank"])  # control: drop the quality and it is S again
    e["objective_inputs"]["functional"] = [q for q in e["objective_inputs"]["functional"] if q != "joint_capacity"] + ["locomotion"]
    assert qr.functional_rating(e)[0] == "S"


def test_the_traps_short_rom_is_not_penalised_and_a_shrug_is_grip_limited():
    assert "traps" in qr.STRETCH_NOT_ESTABLISHED
    for k in ("shrug_barbell", "shrug_dumbbell", "seated_shrugs"):
        assert qr.components(MV[k], "traps")["stretch"] == qr.STRETCH["mid"], k
        assert _tier(MV[k], "traps") == "B" and MV[k]["objective_inputs"]["limiter"] == "grip", k
    assert qr.components({"length_bias": "unknown"}, "traps")["stretch"] == 0, "an unknown length still never helps"
    e = copy.deepcopy(MV["shrug_barbell"])  # control: the penalty back (shortened scores 1)
    saved = dict(qr.STRETCH_NOT_ESTABLISHED)
    qr.STRETCH_NOT_ESTABLISHED.clear()
    try:
        assert qr.components(e, "traps")["stretch"] == qr.STRETCH["shortened"]
    finally:
        qr.STRETCH_NOT_ESTABLISHED.update(saved)


# ── the balance limiter, the lunge glute row ─────────────────────────────────────────────────────────────────────────
def _balance_on_upper(movements: dict) -> list[str]:
    return [
        k
        for k, e in movements.items()
        if e["objective_inputs"]["limiter"] == "balance"
        and e["pattern"] in objectives._UPPER_PATTERNS
        and not e.get("expansion_origin")  # an authored (L2) limiter is reviewed data: a standing cable press IS balance-limited
    ]


def test_the_balance_limiter_never_applies_to_an_upper_body_pattern():
    assert _balance_on_upper(MV) == []
    assert MV["bent_arm_lateral_raises"]["objective_inputs"]["limiter"] == "target"
    bad = copy.deepcopy(MV)  # control
    bad["bent_arm_lateral_raises"]["objective_inputs"]["limiter"] = "balance"
    assert _balance_on_upper(bad) == ["bent_arm_lateral_raises"]


_LUNGE = re.compile(r"lunge|split squat|step ?ups?|stepup|bulgarian|curtsy", re.I)


def _lunges_without_glutes(movements: dict) -> list[str]:
    return [
        k
        for k, e in movements.items()
        if e["target"]["primary"] == "quadriceps"
        and e["pattern"] == "squat"
        and e["category"] == "hypertrophy"
        and _LUNGE.search(e["title"])
        and not objectives._GLUTE_EXCLUDED_RE.search(e["title"])
        and not any(r["target"] == "glutes" for r in e["hypertrophy"])
    ]


def test_every_loaded_lunge_split_squat_and_step_up_has_a_glute_row():
    assert _lunges_without_glutes(MV) == []
    assert _tier(MV["db_reverse_lunge"], "glutes") == "B" and _tier(MV["walking_lunge_dumbbell"], "glutes") == "B"
    bad = copy.deepcopy(MV)  # control
    bad["db_reverse_lunge"]["hypertrophy"] = [r for r in bad["db_reverse_lunge"]["hypertrophy"] if r["target"] != "glutes"]
    assert _lunges_without_glutes(bad) == ["db_reverse_lunge"]


# ── invalid equipment, joint capacity ────────────────────────────────────────────────────────────────────────────────
_LOADED_PATTERNS = (
    "curl",
    "triceps_extension",
    "leg_curl",
    "lateral_raise",
    "rear_delt",
    "chest_fly",
    "shrug",
    "horizontal_press",
    "vertical_press",
)
_BODY_WORDS = re.compile(
    r"bodyweight|push|dip|inverted|chin|pull|plank|hang|knee|incline push|bench dip|raise|floor bridge|scarecrow", re.I
)


def _bodyweight_loaded_offenders(movements: dict) -> list[str]:
    return [
        k
        for k, e in movements.items()
        if e["source"] == "history"
        and e["resistance_profile"] == "bodyweight"
        and e["pattern"] in _LOADED_PATTERNS
        and not _BODY_WORDS.search(e["title"])
    ]


def test_a_custom_template_with_no_equipment_is_not_bodyweight():
    assert _bodyweight_loaded_offenders(MV) == []
    for k in ("shoulder_press", "tricep_extension", "overhead_tricep_extension", "seated_bicep_curls", "21s", "one_arm_bench_press"):
        assert MV[k]["resistance_profile"] == "unknown" and MV[k]["equipment"] == ["other_unspecified"], k
    bad = copy.deepcopy(MV)  # control
    bad["shoulder_press"]["resistance_profile"] = "bodyweight"
    assert _bodyweight_loaded_offenders(bad) == ["shoulder_press"]


def test_cuff_rotation_is_joint_capacity_not_mobility():
    for k in ("rotator_cuff_external_rotation", "external_rotation", "db_external_rotation"):
        assert MV[k]["ratings"]["mobility"]["tier"] is None and MV[k]["ratings"]["functional"]["tier"] == "B", k


def test_a_supported_curl_is_stable():
    assert MV["spider_curl"]["stability"] == "high" and _tier(MV["spider_curl"], "biceps") == "B"


# ── reachability: a slot job can match a P0/P1 addition's published pattern ──────────────────────────────────────────
P0_P1_ADDITIONS = {
    "tibialis_raise": "ankle_dorsiflexion",
    "cable_serratus_punch": "scapular_protraction",
    "controlled_forward_step_down": "step_down",
    "hip_abduction_machine": "hip_abduction",
    "hip_adduction_machine": "hip_adduction",
    "chest_supported_y_raise_dumbbell": "lateral_raise",
    "copenhagen_side_plank": "hip_adduction",
}


def test_every_p0_p1_addition_publishes_a_real_pattern_never_other():
    assert {k: MV[k]["pattern"] for k in P0_P1_ADDITIONS} == P0_P1_ADDITIONS
    assert set(targets.ADDITION_PATTERNS) <= set(MV), "an addition pattern row for a movement not in the library"
    bad = copy.deepcopy(MV)  # control
    bad["tibialis_raise"]["pattern"] = "other"
    assert {k: bad[k]["pattern"] for k in P0_P1_ADDITIONS} != P0_P1_ADDITIONS
