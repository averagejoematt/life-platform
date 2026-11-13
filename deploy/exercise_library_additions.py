# module-size-exception: a hand-authored DATA table (Amendment 15 candidate reconciliation, new canonical movements with
# their metadata, the coverage matrix and the quality-audit findings) — one row per item; the logic is a few small checks.
"""exercise_library_additions.py — epic #5861 lane L2: the comprehensive-library expansion (Amendment 15).

Principle: an exceptionally comprehensive library, an exceptionally selective engine. This module is DATA, consumed by
`deploy/build_exercise_library.py` through its one hook (`library_additions()`, which reads `ADDITIONS`). It holds:

  * RECONCILIATION — every Amendment 15 candidate (§1-§20, `AMENDMENT_15_CANDIDATES`) and every "keep" item the
    amendment names, each with ONE outcome and a priority:
      ADD             a new canonical movement (in `ADDITIONS`, so it lands in config/exercise_library.json)
      VARIANT         a grip / stance / range / tempo / equipment / laterality / level change of an existing (or added)
                      canonical, recorded as variant metadata, never as a second canonical
      ALREADY_COVERED an existing library movement already is this candidate
      DEFER           not added now, with the reason
    Priority: P0 essential functional gap · P1 high value · P2 valuable optional · P3 specialist. Counts are not equalised.
  * ADDITIONS — the new canonicals, in the curation `EXPANSION` shape plus the #5861 fields (`category`, `trunk_function`,
    `functions`, `variants`, `cardio_protocols`, `expansion_profile` with the amendment's 20 metadata fields).
  * COVERAGE — every muscle group and movement function: what covers it now, what this lane adds, what is still open.
  * QUALITY_FINDINGS — misclassifications, near-duplicates, invalid equipment, tier anomalies and missing progression
    paths found while reconciling; each names its owner (this lane fixes only its own data).

The rule that decides ADD vs VARIANT (stated once): a candidate is an ADD only when it fills a muscle or movement FUNCTION
the library does not serve (or serves only with a movement that cannot be loaded or progressed). A candidate that serves
an already-served function with a changed grip, stance, range, tempo, laterality, plane or equipment is a VARIANT of
that canonical — even when Hevy has its own template for it (the template id is kept on the variant row, so it can be
logged and later promoted without a new id). A regression or progression is a VARIANT `level` of its canonical.

Prescribability: an ADD is prescribable only if a Hevy template exists for it — Hevy's built-in catalog or a custom
template already in the account (both read-only from the platform's template index, s3 config/hevy_template_index.json).
Otherwise `hevy_template: null`, `needs_custom_template: true`, and it is NOT prescribable until the owner approves
creating the template (`OWNER_TEMPLATE_APPROVALS`). No Hevy write happens here. The selection engine additionally needs a
movement-catalog entry before it can write any movement (`selection_engine` `not_prescribable`), so nothing added here
reaches a drafted session while the library is `proposed` — or after, until the catalog carries it.

Evidence honesty: no citation is invented. Every rating here is `none_reviewed` with the basis stated as practitioner
consensus — the library reserves `consensus` for a named reviewer's peer-reviewed position with a registered citation.
Tiers are categorical with a stated basis; no point scores. No personal data: fit factors are generic conditions.

    python3 deploy/exercise_library_additions.py --write-doc   # regenerate docs/coaching/EXERCISE_LIBRARY_COVERAGE.md
    python3 deploy/exercise_library_additions.py --check-doc   # exit 1 if the doc drifted from this module
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY_PATH = os.path.join(REPO_ROOT, "config", "exercise_library.json")
CATALOG_PATH = os.path.join(REPO_ROOT, "config", "movement_catalog.json")
DOC_PATH = os.path.join(REPO_ROOT, "docs", "coaching", "EXERCISE_LIBRARY_COVERAGE.md")
ORIGIN = "#5861 amendment 15"  # every ADD's `expansion_origin` starts with this — how a rebuild tells its own rows apart
TEMPLATE_INDEX_SOURCE = "s3://matthew-life-platform/config/hevy_template_index.json (read-only, built 2026-11-12T14:40Z, 822 templates)"

OUTCOMES = ("ADD", "VARIANT", "ALREADY_COVERED", "DEFER")
PRIORITIES = ("P0", "P1", "P2", "P3")
CATEGORIES = ("hypertrophy", "strength", "conditioning", "athletic", "mobility", "rehab_control", "carry")  # the #5861 contract
TRUNK_FUNCTIONS = ("loaded_flexion", "anti_extension", "anti_rotation", "anti_lateral_flexion", "rotation", "loaded_stabilisation")
OBJECTIVES = ("hypertrophy", "strength", "functional", "conditioning", "mobility")
PHASE_SUITABILITY = ("now", "later", "specialist")  # for the present weight-loss phase
PROGRAMMING = ("auto_programmable", "readiness_gated")
READINESS_CONDITIONS = ("bodyweight", "impact", "skill", "identified_need", "joint_tolerance", "equipment_unconfirmed")
INFLUENCE = ("influences_current_program", "available_only")
LATERALITY = ("bilateral", "unilateral", "alternating", "not_applicable")
LEVELS = ("low", "moderate", "high")
VARIANT_AXES = ("grip", "stance", "range", "tempo", "equipment", "laterality", "level", "position", "direction", "load", "plane", "terrain")
HEVY_KINDS = ("builtin", "custom_existing")
CARDIO_PROTOCOLS = (
    "easy_recovery_aerobic",
    "moderate_continuous",
    "tempo_threshold",
    "structured_intervals",
    "progressive_endurance",
    "incline_resistance_progression",
)
# The amendment's 20 metadata fields -> where each lives on the library entry (dotted path).
PROFILE_FIELDS: dict[str, str] = {
    "canonical name": "title",
    "aliases": "expansion_profile.aliases",
    "primary targets": "target.primary",
    "secondary targets": "target.secondary",
    "movement pattern": "expansion_profile.movement_function",
    "objectives served": "expansion_profile.objectives",
    "equipment": "equipment",
    "unilateral/bilateral": "expansion_profile.laterality",
    "skill/technical complexity": "skill_complexity",
    "load + rep progression options": "expansion_profile.progression",
    "stability requirement": "expansion_profile.stability_demand",
    "typical local + systemic fatigue": "expansion_profile.fatigue",
    "joint considerations": "expansion_profile.joint_notes",
    "regressions + progressions": "expansion_profile.levels",
    "alternatives": "expansion_profile.alternatives",
    "evidence confidence": "expansion_profile.evidence_confidence",
    "personal-fit factors": "expansion_profile.personal_fit",
    "type/category": "category",
    "suitability for the present weight-loss phase": "expansion_profile.phase_suitability",
    "auto-programmable vs readiness-gated": "expansion_profile.programming",
}
# Generic fit conditions (never a person's data): what can make a movement a good or poor practical choice.
FIT_FACTORS = (
    "body_mass_load",  # the movement moves (much of) the body's own mass, so a higher body mass raises its effective load
    "floor_transition",  # needs getting down to and up from the floor
    "balance_demand",
    "impact",
    "knee_tolerance",
    "shoulder_tolerance",
    "low_back_tolerance",
    "wrist_tolerance",
    "ankle_tolerance",
    "grip_limited",
    "equipment_unconfirmed",  # the equipment's state at home_gym is not yet known
    "low_recovery_cost",
    "time_efficient",
    "enjoyment_variable",
)

_L, _M, _H = "low", "moderate", "high"


def _js(spinal: str, shear: str, wrist: str, elbow: str, shoulder: str) -> dict[str, str]:
    return {"spinal_load": spinal, "shear": shear, "wrist": wrist, "elbow": elbow, "shoulder": shoulder}


def _r(tier: str | None, basis: str) -> dict[str, Any]:
    """One objective rating in the #5861 contract shape. `None` tier = the objective does not apply (never forced)."""
    return {"tier": tier, "basis": [basis], "evidence_confidence": "none_reviewed"}


def _ratings(**given: tuple[str | None, str]) -> dict[str, dict[str, Any]]:
    return {o: _r(*given[o]) if o in given else _r(None, "not an objective this movement serves") for o in OBJECTIVES}


def _v(name: str, axis: str, value: str, hevy: str | None = None, level: int | None = None) -> dict[str, Any]:
    """A variant row on a canonical: what changes (`axis` -> `value`), and Hevy's own template for it if one exists."""
    out: dict[str, Any] = {"name": name, "axis": axis, "value": value, "hevy_template": hevy}
    if level is not None:
        out["level"] = f"L{level}"  # a string: the public library carries no bare numbers outside its allowed paths
    return out


# Readiness gates the library's own machinery does not already enforce (an unconfirmed equipment state is the
# `equipment_available` gate's job, so it is not repeated here).
_NFY_UNLOCK = {
    "bodyweight": "the movement's body-mass load is within the owner's readiness standard (owner-confirmable)",
    "impact": "the charter's plyometric gate opens and the owner confirms landing readiness",
    "skill": "the owner confirms the technique",
    "identified_need": "a named limitation or purpose is recorded for it (mobility / rehab work is never added by default)",
    "joint_tolerance": "the owner confirms the joint tolerates it (pain-free trial set)",
}


def _not_for_you_now(tid: str | None, gate: str | None) -> dict[str, str] | None:
    """The library's curated exclusion (`selection_engine.not_for_you_now`), so an addition that cannot be written to Hevy, or
    that waits on a readiness condition, is never selected nor offered as another movement's fallback until it unlocks."""
    if tid is None:
        return {
            "reason_code": "needs_custom_hevy_template",
            "unlock_condition": "the owner approves creating the Hevy custom template (#5861 owner approval list), then a catalog entry",
        }
    if gate in _NFY_UNLOCK:
        return {"reason_code": f"readiness_gated_{gate}", "unlock_condition": _NFY_UNLOCK[gate]}
    return None


def _add(
    key: str,
    title: str,
    hevy: tuple[str, str] | None,
    *,
    sec: int,
    pri: str,
    aliases: list[str],
    target: tuple[str, list[str], str],
    function: str,
    category: str,
    attrs: tuple[str, str, str, str, dict[str, str]],
    skill: str,
    equipment: list[str],
    objectives: list[str],
    lat: str,
    progression: tuple[list[str], list[str]],
    demand: str,
    fatigue: tuple[str, str],
    joint_notes: str,
    levels: tuple[list[str], list[str]],
    alts: list[str],
    fit: list[str],
    phase: str,
    gate: str | None,
    influence: tuple[str, str],
    ratings: dict[str, dict[str, Any]],
    trunk: str | None = None,
    gates: list[str] | None = None,
    variants: list[dict[str, Any]] | None = None,
    protocols: list[str] | None = None,
) -> dict[str, Any]:
    """One new canonical movement, in the curation `EXPANSION` shape the builder hook reads, plus the #5861 fields.
    `attrs` = (family, length_bias, resistance_profile, setup stability, joint_stress) — the rubric's inputs."""
    family, length, resist, stab, joints = attrs
    tid, kind = hevy if hevy else (None, None)
    out: dict[str, Any] = {
        "key": key,
        "title": title,
        "template_id": tid,
        "expansion_origin": f"{ORIGIN} §{sec}",
        "target": {"primary": target[0], "secondary": list(target[1]), "region": target[2]},
        "family": family,
        "length_bias": length,
        "resistance_profile": resist,
        "stability": stab,
        "joint_stress": joints,
        "skill_complexity": skill,
        "equipment": list(equipment),
        "gates": list(gates or []),
        "category": category,
        "functions": [function],
        "expansion_profile": {
            "section": f"§{sec}",
            "priority": pri,
            "aliases": list(aliases),
            "movement_function": function,
            "objectives": list(objectives),
            "laterality": lat,
            "progression": {"resistance": list(progression[0]), "reps": list(progression[1])},
            "stability_demand": demand,
            "fatigue": {"local": fatigue[0], "systemic": fatigue[1]},
            "joint_notes": joint_notes,
            "levels": {"regressions": list(levels[0]), "progressions": list(levels[1])},
            "alternatives": list(alts),
            "evidence_confidence": "none_reviewed",
            "evidence_basis": "practitioner consensus; no citation reviewed for this lane",
            "personal_fit": list(fit),
            "phase_suitability": phase,
            "programming": {"mode": "readiness_gated" if gate else "auto_programmable", "gate_reason": gate},
            "influence": {"verdict": influence[0], "why": influence[1]},
            "hevy": {
                "template": tid,
                "kind": kind,
                "needs_custom_template": tid is None,
                "prescribable": tid is not None,
            },
            "ratings_proposed": ratings,
        },
    }
    nfy = _not_for_you_now(tid, gate)
    if nfy:
        out["not_for_you_now"] = nfy
    if tid is None:
        out["template_note"] = (
            "no Hevy template (built-in or custom) exists: needs a custom template, owner-gated (#5861); not prescribable"
        )
    elif kind == "custom_existing":
        out["template_note"] = "a custom template already in the account (read-only template index); never logged"
    if trunk:
        out["trunk_function"] = trunk
    if variants:
        out["variants"] = list(variants)
    if protocols:
        out["cardio_protocols"] = list(protocols)
    return out


_NOW_CLAUSE = "fills a function nothing in the library serves, at low systemic cost"
_AVAIL = "available_only"
_INFL = "influences_current_program"
_ALL_PROTOCOLS = list(CARDIO_PROTOCOLS)
_LOW_IMPACT_PROTOCOLS = ["easy_recovery_aerobic", "moderate_continuous", "tempo_threshold", "structured_intervals", "progressive_endurance"]

ADDITIONS: list[dict[str, Any]] = [
    # §1 chest — one ADD: a standing (no-bench) press whose single-arm form adds anti-rotation; the rest are VARIANTs.
    _add(
        "standing_cable_chest_press",
        "Standing Cable Chest Press",
        None,
        sec=1,
        pri="P3",
        aliases=["standing cable press", "cable chest press (standing)"],
        target=("chest", ["front_delts", "triceps", "abs"], "upper"),
        function="horizontal_press_standing",
        category="hypertrophy",
        attrs=("hypertrophy", "mid", "cable", _L, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["cable_stack"],
        objectives=["hypertrophy", "functional"],
        lat="bilateral",
        progression=(["stack load", "staggered-to-parallel stance"], ["8-15", "slow eccentric"]),
        demand=_M,
        fatigue=(_L, _L),
        joint_notes="shoulder-friendly free path; load is capped by stance stability, not by the chest",
        levels=(["half-kneeling cable press"], ["single-arm standing cable press (anti-rotation)"]),
        alts=["chest_press_machine", "bench_press_dumbbell"],
        fit=["time_efficient", "low_recovery_cost"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "chest pressing is already served by stable, more loadable presses"),
        ratings=_ratings(
            hypertrophy=("C", "standing stability limits the load the chest can be taken near failure with"),
            functional=("B", "standing press with trunk bracing; anti-rotation when single-arm"),
        ),
        variants=[
            _v("single-arm standing cable chest press", "laterality", "unilateral, adds an anti-rotation demand"),
            _v("chest-focused isometric cable press", "tempo", "isometric hold at mid-range"),
        ],
    ),
    # §3 traps / scapular — upper trap is served by four shrugs; lower-trap upward rotation had no movement.
    _add(
        "chest_supported_y_raise_dumbbell",
        "Chest Supported Y Raise (Dumbbell)",
        ("F21D5693", "builtin"),
        sec=3,
        pri="P1",
        aliases=["prone incline Y raise", "lower-trap Y raise", "incline-bench lower-trap raise"],
        target=("traps", ["rear_delts", "side_delts"], "upper"),
        function="scapular_upward_rotation_lower_trap",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "free_weight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["dumbbell", "bench_adjustable"],
        objectives=["functional", "hypertrophy"],
        lat="bilateral",
        progression=(["small dumbbell steps"], ["10-15", "1 s pause at the top"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="thumbs up, arms in a Y in line with the lower-trap fibres; pain-free overhead range only",
        levels=(["unloaded Y on the incline"], ["trap-3 raise (single-arm)", "cable Y raise"]),
        alts=["prone_w_raise", "face_pull"],
        fit=["low_recovery_cost", "time_efficient"],
        phase="now",
        gate=None,
        influence=(_INFL, "the only lower-trap upward-rotation movement; low-fatigue scapular work beside heavy pressing"),
        ratings=_ratings(
            functional=("A", "lower-trap upward rotation and scapular control for overhead work"),
            hypertrophy=("C", "light loads; the lower trap is a small target"),
        ),
        variants=[
            _v("trap-3 raise", "laterality", "single-arm, bent-over"),
            _v("standing cable Y raise", "equipment", "cable, standing", hevy="28927A36"),
        ],
    ),
    # §4 shoulders — the serratus and the internal rotators were the unserved functions.
    _add(
        "cable_serratus_punch",
        "Cable Serratus Punch",
        None,
        sec=4,
        pri="P1",
        aliases=["serratus cable punch", "cable protraction punch"],
        target=("serratus", ["front_delts", "chest"], "upper"),
        function="scapular_protraction",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "cable", _M, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["cable_stack"],
        objectives=["functional", "mobility"],
        lat="unilateral",
        progression=(["stack load"], ["10-15", "pause at full protraction"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="elbow locked, motion at the shoulder blade only; no shoulder end-range load",
        levels=(["supine dumbbell punch"], ["incline push-up plus", "push-up plus (floor, bodyweight-gated)"]),
        alts=["incline_push_up"],
        fit=["low_recovery_cost", "time_efficient"],
        phase="now",
        gate=None,
        influence=(_INFL, "the only loadable protraction movement; a low-fatigue shoulder-health accessory beside heavy pressing"),
        ratings=_ratings(
            functional=("A", "trains scapular protraction/upward rotation the presses barely load"),
            hypertrophy=("D", "serratus growth is not its aim"),
        ),
        variants=[_v("supine dumbbell serratus punch", "position", "supine, dumbbell", level=0)],
    ),
    _add(
        "cable_internal_rotation",
        "Cable Internal Rotation",
        None,
        sec=4,
        pri="P3",
        aliases=["cable IR", "shoulder internal rotation (cable)"],
        target=("rotator_cuff", ["chest"], "upper"),
        function="shoulder_internal_rotation",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "cable", _M, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["cable_stack"],
        objectives=["functional"],
        lat="unilateral",
        progression=(["stack load", "at 90 degrees abduction"], ["12-20"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="towel under the elbow at the side; pain-free range only",
        levels=(["band internal rotation"], ["internal rotation at 90 degrees abduction"]),
        alts=["rotator_cuff_external_rotation"],
        fit=["low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "internal-rotation strength is rarely limiting; use on an identified need"),
        ratings=_ratings(functional=("C", "rotator-cuff balance work, only with a reason")),
    ),
    # §7 forearms / grip / wrist — extension, rotation, deviation, pinch, crush and finger extension were unserved.
    _add(
        "wrist_extension_dumbbell",
        "Reverse Wrist Curl (Dumbbell)",
        ("D8460FA6", "builtin"),
        sec=7,
        pri="P2",
        aliases=["seated dumbbell wrist extension", "dumbbell wrist extension"],
        target=("forearms", [], "upper"),
        function="wrist_extension",
        category="hypertrophy",
        attrs=("hypertrophy", "mid", "free_weight", _H, _js(_L, _L, _M, _L, _L)),
        skill=_L,
        equipment=["dumbbell", "bench_flat"],
        objectives=["hypertrophy", "functional"],
        lat="unilateral",
        progression=(["small dumbbell steps"], ["12-20", "3-4 s eccentric"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="forearm supported on the bench; the eccentric-only form is the lateral-elbow-friendly option",
        levels=(["unloaded wrist extension"], ["barbell reverse wrist curl"]),
        alts=["db_wrist_curl", "forearm_curl"],
        fit=["grip_limited", "low_recovery_cost"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "rows, deadlifts and carries already load the forearm; direct extensor work is optional"),
        ratings=_ratings(hypertrophy=("B", "isolated wrist extensors"), functional=("B", "balances flexor-dominant grip work")),
        variants=[
            _v("barbell reverse wrist curl", "equipment", "barbell, seated", hevy="9202CC23"),
            _v("wrist extensor eccentric lowering", "tempo", "eccentric-only, assisted up"),
        ],
    ),
    _add(
        "wrist_roller",
        "Wrist Roller",
        ("0E4523F4", "builtin"),
        sec=7,
        pri="P3",
        aliases=["forearm roller"],
        target=("forearms", ["front_delts"], "upper"),
        function="wrist_flexion_extension_endurance",
        category="hypertrophy",
        attrs=("hypertrophy", "not_applicable", "free_weight", _M, _js(_L, _L, _M, _L, _M)),
        skill=_L,
        equipment=["wrist_roller", "weight_plate"],
        objectives=["hypertrophy", "functional"],
        lat="bilateral",
        progression=(["plate load"], ["up-and-down passes"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="arms held forward load the front delts; shorter holds if the shoulders tire first",
        levels=(["light plate, arms supported on a rack"], ["heavier plate, overhand and underhand passes"]),
        alts=["db_wrist_curl", "wrist_extension_dumbbell"],
        fit=["equipment_unconfirmed", "grip_limited"],
        phase="now",
        gate="equipment_unconfirmed",
        influence=(_AVAIL, "optional forearm endurance work; the equipment is unconfirmed"),
        ratings=_ratings(hypertrophy=("C", "forearm pump work, hard to load precisely"), functional=("B", "flexor and extensor endurance")),
    ),
    _add(
        "forearm_rotation_dumbbell",
        "Dumbbell Pronation and Supination",
        None,
        sec=7,
        pri="P3",
        aliases=["dumbbell pronation", "dumbbell supination", "forearm rotation with a lever"],
        target=("forearms", ["biceps"], "upper"),
        function="forearm_rotation",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "free_weight", _H, _js(_L, _L, _M, _M, _L)),
        skill=_L,
        equipment=["dumbbell", "bench_flat"],
        objectives=["functional"],
        lat="unilateral",
        progression=(["grip further from the loaded end (longer lever)"], ["12-20"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="forearm supported; the lever length sets the load, start short",
        levels=(["unloaded rotation"], ["hammer or sledge lever"]),
        alts=["reverse_curl_dumbbell", "hammer_curl_dumbbell"],
        fit=["low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "rotation strength is rarely the limiter; use for an elbow/forearm need"),
        ratings=_ratings(functional=("C", "pronator/supinator strength, specialist")),
        variants=[
            _v("dumbbell supination", "direction", "supination"),
            _v("hammer-lever pronation/supination", "equipment", "sledgehammer or lever bar"),
        ],
    ),
    _add(
        "wrist_deviation_dumbbell",
        "Dumbbell Radial and Ulnar Deviation",
        None,
        sec=7,
        pri="P3",
        aliases=["radial deviation", "ulnar deviation", "wrist deviation"],
        target=("forearms", [], "upper"),
        function="wrist_deviation",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "free_weight", _H, _js(_L, _L, _M, _L, _L)),
        skill=_L,
        equipment=["dumbbell"],
        objectives=["functional"],
        lat="unilateral",
        progression=(["lever length"], ["12-20"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="small range; stop short of wrist pain",
        levels=(["unloaded deviation"], ["longer lever"]),
        alts=["forearm_rotation_dumbbell"],
        fit=["low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "specialist wrist work with no current need"),
        ratings=_ratings(functional=("D", "narrow, specialist function")),
        variants=[_v("dumbbell ulnar deviation", "direction", "ulnar")],
    ),
    _add(
        "plate_pinch_hold",
        "Plate Pinch Hold",
        None,
        sec=7,
        pri="P2",
        aliases=["plate pinch", "pinch grip hold"],
        target=("forearms", [], "upper"),
        function="pinch_grip",
        category="strength",
        attrs=("carry_conditioning", "not_applicable", "free_weight", _H, _js(_L, _L, _M, _L, _L)),
        skill=_L,
        equipment=["weight_plate"],
        objectives=["strength", "functional"],
        lat="unilateral",
        progression=(["plate size / two plates smooth-side out"], ["timed holds"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="thumb load; hold beside the body",
        levels=(["two light plates"], ["heavier or wider plates", "pinch farmer's walk"]),
        alts=["farmers_walk", "dead_hang"],
        fit=["grip_limited", "low_recovery_cost"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "pinch is the one grip mode no current movement trains; optional"),
        ratings=_ratings(strength=("B", "direct thumb/pinch strength"), functional=("B", "pinch is a distinct grip mode")),
    ),
    _add(
        "hand_gripper_squeeze",
        "Hand Gripper Squeeze",
        None,
        sec=7,
        pri="P3",
        aliases=["heavy gripper", "crush grip squeeze"],
        target=("forearms", [], "upper"),
        function="crush_grip",
        category="strength",
        attrs=("hypertrophy", "not_applicable", "unknown", _H, _js(_L, _L, _M, _L, _L)),
        skill=_L,
        equipment=["hand_gripper"],
        objectives=["strength"],
        lat="unilateral",
        progression=(["gripper strength rating"], ["singles / timed closes"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="high finger-flexor tendon load; build volume slowly",
        levels=(["lighter gripper"], ["heavier gripper", "negatives"]),
        alts=["plate_pinch_hold", "farmers_walk"],
        fit=["equipment_unconfirmed", "grip_limited"],
        phase="specialist",
        gate="equipment_unconfirmed",
        influence=(_AVAIL, "crush grip is already trained by heavy pulling and carries"),
        ratings=_ratings(strength=("C", "crush grip only")),
    ),
    _add(
        "band_finger_extension",
        "Band Finger Extension",
        None,
        sec=7,
        pri="P3",
        aliases=["finger extensor band", "rubber-band finger opening"],
        target=("forearms", [], "upper"),
        function="finger_extension",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "band", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["resistance_band"],
        objectives=["functional"],
        lat="unilateral",
        progression=(["band thickness"], ["15-30"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="none",
        levels=([], ["thicker band"]),
        alts=["wrist_extension_dumbbell"],
        fit=["low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "balancing work only with a grip-related need"),
        ratings=_ratings(functional=("D", "rehab balance for heavy gripping")),
    ),
    # §8 quadriceps — eccentric single-leg knee control and knee-dominant isometrics were unserved.
    _add(
        "controlled_forward_step_down",
        "Controlled Forward Step-Down",
        None,
        sec=8,
        pri="P1",
        aliases=["forward step-down", "eccentric step-down"],
        target=("quadriceps", ["glutes", "hip_abductors"], "lower"),
        function="single_leg_eccentric_knee_control",
        category="rehab_control",
        attrs=("hypertrophy", "mid", "bodyweight", _L, _js(_L, _M, _L, _L, _L)),
        skill=_M,
        equipment=["plyo_box"],
        objectives=["functional", "strength"],
        lat="unilateral",
        progression=(["box height", "light dumbbells"], ["6-12 per side", "3-5 s lowering"]),
        demand=_H,
        fatigue=(_M, _L),
        joint_notes="knee tracks over the second toe; start from a low step and a hand on a rack",
        levels=(["low step with hand support"], ["higher box", "held dumbbells", "lateral step-down"]),
        alts=["db_step_up", "split_squat_dumbbell"],
        fit=["knee_tolerance", "balance_demand", "body_mass_load"],
        phase="now",
        gate=None,
        influence=(_INFL, "the only eccentric single-leg knee-control movement; low load, regressed by step height"),
        ratings=_ratings(
            functional=("A", "stairs/descents: eccentric single-leg control and frontal-plane knee control"),
            strength=("C", "low absolute load"),
            hypertrophy=("C", "bodyweight, limited overload"),
        ),
        variants=[
            _v("controlled lateral step-down", "direction", "lateral (frontal plane)"),
            _v("step-down with hand support", "level", "rack-assisted", level=0),
        ],
    ),
    _add(
        "spanish_squat",
        "Spanish Squat",
        None,
        sec=8,
        pri="P2",
        aliases=["band-supported knee-dominant squat"],
        target=("quadriceps", ["glutes"], "lower"),
        function="knee_dominant_isometric",
        category="rehab_control",
        attrs=("hypertrophy", "mid", "band", _M, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["resistance_band", "squat_rack"],
        objectives=["functional", "strength"],
        lat="bilateral",
        progression=(["held dumbbell", "deeper angle"], ["30-45 s isometrics", "slow reps"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="vertical shin, knee-dominant with low shear; a common patellar-tendon-friendly option",
        levels=(["shallow hold"], ["deeper hold", "loaded hold", "slow reps"]),
        alts=["wall_sit", "leg_extension_machine"],
        fit=["knee_tolerance", "low_recovery_cost"],
        phase="now",
        gate="identified_need",
        influence=(_AVAIL, "a knee-tolerance tool, programmed when the knee asks for it"),
        ratings=_ratings(functional=("B", "knee-dominant isometric strength with low shear"), strength=("C", "isometric, low load")),
        variants=[_v("split-squat isometric hold", "tempo", "isometric, split stance")],
    ),
    _add(
        "sissy_squat",
        "Sissy Squat",
        ("F5DEF1EB", "builtin"),
        sec=8,
        pri="P3",
        aliases=["assisted sissy squat", "sissy squat (weighted)"],
        target=("quadriceps", [], "lower"),
        function="closed_chain_knee_extension",
        category="hypertrophy",
        attrs=("hypertrophy", "lengthened", "bodyweight", _M, _js(_L, _H, _L, _L, _L)),
        skill=_M,
        equipment=["bodyweight", "squat_rack"],
        objectives=["hypertrophy"],
        lat="bilateral",
        progression=(["assisted -> bodyweight -> held plate"], ["8-15", "range"]),
        demand=_M,
        fatigue=(_H, _L),
        joint_notes="deep loaded knee flexion with the hips extended: high patellar load",
        levels=(["rack-assisted, partial range"], ["full range", "held plate"]),
        alts=["leg_extension_machine", "hack_squat_machine"],
        fit=["knee_tolerance", "body_mass_load"],
        phase="later",
        gate="joint_tolerance",
        influence=(_AVAIL, "the leg extension already trains the same lengthened rectus femoris with less knee stress"),
        ratings=_ratings(hypertrophy=("B", "lengthened rectus femoris, hard to load")),
        variants=[_v("assisted sissy squat", "level", "rack-assisted", level=0)],
    ),
    _add(
        "band_assisted_reverse_nordic",
        "Band-Assisted Reverse Nordic",
        None,
        sec=8,
        pri="P3",
        aliases=["reverse nordic", "reverse nordic curl"],
        target=("quadriceps", ["hip_flexors"], "lower"),
        function="knee_extension_lengthened_eccentric",
        category="rehab_control",
        attrs=("hypertrophy", "lengthened", "band", _M, _js(_L, _M, _L, _L, _L)),
        skill=_M,
        equipment=["resistance_band"],
        objectives=["functional", "hypertrophy", "mobility"],
        lat="bilateral",
        progression=(["lighter assistance band", "range"], ["6-10", "slow eccentric"]),
        demand=_M,
        fatigue=(_M, _L),
        joint_notes="kneeling: needs knee-kneeling tolerance and a pad",
        levels=(["partial range with heavy band"], ["light band", "unassisted reverse nordic"]),
        alts=["leg_extension_machine", "sissy_squat"],
        fit=["knee_tolerance", "floor_transition", "body_mass_load"],
        phase="later",
        gate="joint_tolerance",
        influence=(_AVAIL, "knee-resilience work best added once kneeling and body mass allow it"),
        ratings=_ratings(
            functional=("B", "lengthened eccentric quad strength"),
            hypertrophy=("C", "bodyweight, limited load"),
            mobility=("C", "rectus femoris length under load"),
        ),
    ),
    # §10 glutes — hip abduction (glute med/min) had no loadable movement; hip-rotation control and band work missing.
    _add(
        "hip_abduction_machine",
        "Hip Abduction (Machine)",
        ("F4B4C6EE", "builtin"),
        sec=10,
        pri="P0",
        aliases=["seated hip abduction", "abductor machine"],
        target=("hip_abductors", ["glutes"], "lower"),
        function="hip_abduction",
        category="hypertrophy",
        attrs=("hypertrophy", "mid", "machine_selectorized", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["hip_abduction_machine"],
        objectives=["hypertrophy", "functional"],
        lat="bilateral",
        progression=(["stack load", "torso lean forward"], ["10-20", "pause at the open position"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="no spinal or knee load",
        levels=(["lighter stack"], ["forward-lean (more glute max)", "standing cable abduction"]),
        alts=["banded_clam_shells", "lateral_band_walks"],
        fit=["low_recovery_cost", "time_efficient", "equipment_unconfirmed"],
        phase="now",
        gate=None,
        influence=(_INFL, "the one loadable glute med/min movement — lateral hip strength for walking and single-leg work"),
        ratings=_ratings(
            hypertrophy=("A", "stable, loadable to near failure for the glute med/min"),
            functional=("B", "lateral hip strength; open-chain"),
        ),
        variants=[
            _v("standing cable hip abduction", "equipment", "cable, standing (adds stance-leg control)", hevy="C469EA70"),
            _v("side-lying weighted hip abduction", "position", "side-lying, ankle weight or plate", hevy="DC59D143"),
            _v("forward-lean machine abduction", "position", "torso forward (more glute max)"),
        ],
    ),
    _add(
        "lateral_band_walks",
        "Lateral Band Walks",
        ("EC02979E", "builtin"),
        sec=10,
        pri="P3",
        aliases=["lateral band walk", "band side steps"],
        target=("hip_abductors", ["glutes"], "lower"),
        function="hip_abduction_closed_chain",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "band", _M, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["resistance_band"],
        objectives=["functional"],
        lat="alternating",
        progression=(["band at knees -> ankles -> feet"], ["10-20 steps each way"]),
        demand=_M,
        fatigue=(_L, _L),
        joint_notes="none",
        levels=(["band above the knees"], ["band at the feet", "monster walk"]),
        alts=["hip_abduction_machine", "banded_clam_shells"],
        fit=["low_recovery_cost"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "warm-up activation; the machine carries the loadable work"),
        ratings=_ratings(
            functional=("C", "closed-chain abduction, low load"), hypertrophy=("D", "too light to train near failure usefully")
        ),
        variants=[_v("monster walk", "direction", "diagonal forward/back")],
    ),
    _add(
        "hip_airplane",
        "Hip Airplane",
        None,
        sec=10,
        pri="P2",
        aliases=["single-leg hip airplane"],
        target=("hip_abductors", ["glutes", "hamstrings"], "lower"),
        function="hip_rotation_control",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "bodyweight", _L, _js(_L, _L, _L, _L, _L)),
        skill=_M,
        equipment=["bodyweight", "squat_rack"],
        objectives=["functional", "mobility"],
        lat="unilateral",
        progression=(["less hand support", "range of pelvic rotation"], ["5-8 slow reps per side"]),
        demand=_H,
        fatigue=(_L, _L),
        joint_notes="hand on a rack as needed; slow, controlled",
        levels=(["rack-supported, small range"], ["unsupported", "held light dumbbell"]),
        alts=["single_leg_static_balance_with_eyes_closed", "single_leg_rdl_dumbbell"],
        fit=["balance_demand", "low_recovery_cost"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "hip rotation control is useful, not urgent"),
        ratings=_ratings(functional=("B", "single-leg hip rotation and balance control"), mobility=("C", "active hip rotation range")),
    ),
    # §11 adductors — no adduction movement existed beyond one slide; the machine is the loadable core, Copenhagen the resilience line.
    _add(
        "hip_adduction_machine",
        "Hip Adduction (Machine)",
        ("8BEBFED6", "builtin"),
        sec=11,
        pri="P0",
        aliases=["seated hip adduction", "adductor machine"],
        target=("adductors", [], "lower"),
        function="hip_adduction",
        category="hypertrophy",
        attrs=("hypertrophy", "mid", "machine_selectorized", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["hip_adduction_machine"],
        objectives=["hypertrophy", "functional"],
        lat="bilateral",
        progression=(["stack load", "wider start (more range)"], ["10-20"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="start range within comfort; no spinal or knee load",
        levels=(["lighter stack, reduced range"], ["full range", "standing cable adduction"]),
        alts=["db_adductor_slides", "copenhagen_side_plank"],
        fit=["low_recovery_cost", "time_efficient", "equipment_unconfirmed"],
        phase="now",
        gate=None,
        influence=(_INFL, "the one loadable adductor movement; adductors are large and nearly unserved"),
        ratings=_ratings(
            hypertrophy=("A", "stable, loadable to near failure for the adductors"),
            functional=("B", "adduction strength for lateral stability"),
        ),
        variants=[
            _v("standing cable hip adduction", "equipment", "cable, standing", hevy="22578A94"),
            _v("side-lying adduction raise", "position", "side-lying, bottom leg", level=0),
        ],
    ),
    _add(
        "copenhagen_side_plank",
        "Copenhagen Side Plank",
        None,
        sec=11,
        pri="P1",
        aliases=["copenhagen plank", "copenhagen adduction"],
        target=("adductors", ["abs"], "lower"),
        function="hip_adduction_isometric",
        category="rehab_control",
        attrs=("core_anti_movement", "not_applicable", "bodyweight", _M, _js(_L, _L, _L, _L, _M)),
        skill=_L,
        equipment=["bench_flat"],
        objectives=["functional", "strength"],
        lat="unilateral",
        progression=(["lever length (knee -> ankle on the bench)", "dynamic reps"], ["10-30 s holds", "slow reps"]),
        demand=_M,
        fatigue=(_M, _L),
        joint_notes="elbow and shoulder bear the upper body; short lever first",
        levels=(["supine adductor ball squeeze", "short lever (knee on bench)"], ["long lever", "dynamic Copenhagen adduction"]),
        alts=["hip_adduction_machine", "side_plank"],
        fit=["body_mass_load", "floor_transition"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "adductor resilience line; the machine carries the current adductor work"),
        ratings=_ratings(
            functional=("A", "adductor strength with anti-lateral-flexion; groin resilience"),
            strength=("C", "bodyweight isometric"),
        ),
        trunk="anti_lateral_flexion",
        variants=[
            _v("supine adductor ball squeeze", "level", "isometric squeeze, supine", level=0),
            _v("short-lever Copenhagen", "level", "knee on the bench", level=1),
            _v("long-lever Copenhagen", "level", "ankle on the bench", level=2),
            _v("dynamic Copenhagen adduction", "level", "bottom leg raises and lowers", level=3),
        ],
    ),
    # §12 lower leg / ankle / foot — the charter's lower-leg prep names tibialis work and no movement served it.
    _add(
        "tibialis_raise",
        "Tibialis Raise",
        None,
        sec=12,
        pri="P0",
        aliases=["wall tibialis raise", "tib raise", "toe raise"],
        target=("tibialis", [], "lower"),
        function="ankle_dorsiflexion_strength",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["functional", "hypertrophy"],
        lat="bilateral",
        progression=(["feet further from the wall", "single leg", "loaded machine/band"], ["15-25"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="back against a wall, heels down; none",
        levels=(["feet close to the wall"], ["feet further out", "single-leg", "tibialis machine"]),
        alts=["leg_swings"],
        fit=["low_recovery_cost", "time_efficient", "ankle_tolerance"],
        phase="now",
        gate=None,
        influence=(_INFL, "serves the charter's lower-leg prep, which prescribes tibialis work with no movement behind it"),
        ratings=_ratings(
            functional=("A", "dorsiflexor strength for walking volume and the shin"), hypertrophy=("C", "bodyweight, small muscle")
        ),
        variants=[
            _v("tibialis machine raise", "equipment", "tibialis machine or banded"),
            _v("single-leg tibialis raise", "laterality", "unilateral"),
        ],
    ),
    _add(
        "banded_ankle_inversion_eversion",
        "Banded Ankle Inversion and Eversion",
        None,
        sec=12,
        pri="P3",
        aliases=["resisted inversion", "resisted eversion"],
        target=("ankle_stabilisers", [], "lower"),
        function="ankle_inversion_eversion",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "band", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["resistance_band"],
        objectives=["functional"],
        lat="unilateral",
        progression=(["band tension"], ["15-25"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="none",
        levels=([], ["standing balance with ankle control"]),
        alts=["single_leg_static_balance_with_eyes_closed"],
        fit=["ankle_tolerance", "low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "ankle rehab work, only with an ankle need"),
        ratings=_ratings(functional=("C", "ankle stabiliser strength")),
        variants=[_v("resisted eversion", "direction", "eversion")],
    ),
    _add(
        "short_foot",
        "Short-Foot Exercise",
        None,
        sec=12,
        pri="P3",
        aliases=["short foot", "arch doming"],
        target=("foot_intrinsics", [], "lower"),
        function="intrinsic_foot_control",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["functional"],
        lat="unilateral",
        progression=(["seated -> standing -> single-leg"], ["5-10 s holds"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="none",
        levels=(["seated"], ["standing", "single-leg stance"]),
        alts=["single_leg_static_balance_with_eyes_closed"],
        fit=["low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "foot-control drill without a current need"),
        ratings=_ratings(functional=("C", "intrinsic foot control")),
        variants=[_v("toe yoga", "level", "independent big-toe / lesser-toe control")],
    ),
    # §13 abs / deep core — every trunk function already had a movement; the ADDs are distinct tools, not gap fills.
    _add(
        "reverse_crunch",
        "Reverse Crunch",
        ("7952B5CD", "builtin"),
        sec=13,
        pri="P2",
        aliases=["bench reverse crunch"],
        target=("abs", ["hip_flexors"], "core"),
        function="loaded_spinal_flexion_from_pelvis",
        category="hypertrophy",
        attrs=("hypertrophy", "shortened", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bench_flat"],
        objectives=["hypertrophy"],
        lat="bilateral",
        progression=(["incline bench angle", "ankle weight"], ["10-20", "slow lowering"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="posterior pelvic tilt drives it, not a leg swing",
        levels=(["flat, bent knees"], ["incline bench", "hanging knee raise"]),
        alts=["cable_crunch", "hanging_knee_raise"],
        fit=["floor_transition"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "loaded spinal flexion is already served by the cable and machine crunch"),
        ratings=_ratings(hypertrophy=("C", "bodyweight flexion, progressable by bench angle")),
        trunk="loaded_flexion",
    ),
    _add(
        "bear_crawl",
        "Bear Crawl",
        ("B3B1D947", "builtin"),
        sec=13,
        pri="P2",
        aliases=["quadruped crawl"],
        target=("abs", ["front_delts", "quadriceps"], "core"),
        function="quadruped_locomotion",
        category="athletic",
        attrs=("core_anti_movement", "not_applicable", "bodyweight", _L, _js(_L, _L, _M, _L, _M)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["functional", "conditioning"],
        lat="alternating",
        progression=(["distance", "direction changes", "weighted vest (later)"], ["timed sets"]),
        demand=_M,
        fatigue=(_L, _M),
        joint_notes="wrists and shoulders carry the upper body",
        levels=(["bear plank (static, knees hovering)"], ["longer crawls", "lateral crawl"]),
        alts=["plank", "dead_bug"],
        fit=["body_mass_load", "wrist_tolerance", "floor_transition"],
        phase="later",
        gate="bodyweight",
        influence=(_AVAIL, "anti-rotation and locomotion are served lower-cost by the Pallof press and carries"),
        ratings=_ratings(functional=("B", "contralateral coordination under anti-rotation"), conditioning=("C", "short, intense bouts")),
        trunk="anti_rotation",
        variants=[_v("bear plank", "level", "static, knees hovering", level=0)],
    ),
    _add(
        "suitcase_deadlift",
        "Suitcase Deadlift",
        None,
        sec=13,
        pri="P2",
        aliases=["single-side deadlift", "offset deadlift"],
        target=("abs", ["glutes", "hamstrings", "quadriceps", "forearms"], "core"),
        function="anti_lateral_flexion_hinge",
        category="strength",
        attrs=("core_anti_movement", "not_applicable", "free_weight", _M, _js(_M, _L, _L, _L, _L)),
        skill=_L,
        equipment=["dumbbell", "kettlebell"],
        objectives=["functional", "strength"],
        lat="unilateral",
        progression=(["load"], ["5-10 per side"]),
        demand=_M,
        fatigue=(_M, _M),
        joint_notes="adds hinge and spinal load; never on the same day as heavy deadlift / RDL work",
        levels=(["light kettlebell from a raised block"], ["heavier load", "trap-bar single-side"]),
        alts=["suitcase_carry", "side_plank"],
        fit=["low_back_tolerance", "grip_limited"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "anti-lateral flexion is already served by the suitcase carry without the extra hinge"),
        ratings=_ratings(functional=("A", "anti-lateral flexion under a real hinge load"), strength=("C", "load is grip/side-limited")),
        trunk="anti_lateral_flexion",
    ),
    _add(
        "stability_ball_stir_the_pot",
        "Stability Ball Stir The Pot",
        ("eb5e90db-f4f0-47ea-9d9b-fcade21f4efc", "custom_existing"),
        sec=13,
        pri="P2",
        aliases=["stir the pot"],
        target=("abs", ["front_delts"], "core"),
        function="anti_extension_dynamic",
        category="rehab_control",
        attrs=("core_anti_movement", "not_applicable", "bodyweight", _L, _js(_L, _L, _L, _M, _M)),
        skill=_M,
        equipment=["stability_ball"],
        objectives=["functional"],
        lat="bilateral",
        progression=(["circle size", "feet narrower"], ["timed sets, 6-10 circles each way"]),
        demand=_H,
        fatigue=(_M, _L),
        joint_notes="forearms on the ball load the shoulders and elbows",
        levels=(["static ball plank, knees down"], ["larger circles", "feet together"]),
        alts=["ab_wheel", "plank"],
        fit=["body_mass_load", "shoulder_tolerance", "equipment_unconfirmed"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "anti-extension is already served by the ab wheel and plank"),
        ratings=_ratings(functional=("B", "anti-extension against a moving base")),
        trunk="anti_extension",
    ),
    _add(
        "mcgill_curl_up",
        "McGill Curl-Up",
        None,
        sec=13,
        pri="P3",
        aliases=["curl-up", "modified curl-up"],
        target=("abs", [], "core"),
        function="trunk_flexor_endurance",
        category="rehab_control",
        attrs=("core_anti_movement", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["functional"],
        lat="bilateral",
        progression=(["elbows lifted", "longer holds"], ["8-10 s holds, descending pyramid"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="neutral lumbar spine; minimal flexion",
        levels=([], ["elbows off the floor", "pre-bracing"]),
        alts=["dead_bug", "plank"],
        fit=["floor_transition", "low_back_tolerance"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "a back-sensitive trunk-endurance option; the dead bug serves the general case"),
        ratings=_ratings(functional=("C", "low-load trunk-flexor endurance")),
        trunk="anti_extension",
    ),
    # §15 hip flexors — the dedicated category had no loadable standing movement.
    _add(
        "standing_cable_knee_drive",
        "Standing Cable Knee Drive",
        None,
        sec=15,
        pri="P2",
        aliases=["cable hip flexion", "standing cable hip flexor raise"],
        target=("hip_flexors", ["abs"], "lower"),
        function="hip_flexion",
        category="hypertrophy",
        attrs=("hypertrophy", "shortened", "cable", _M, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["cable_stack"],
        objectives=["functional", "hypertrophy"],
        lat="unilateral",
        progression=(["stack load", "isometric hold at the top"], ["10-15"]),
        demand=_M,
        fatigue=(_L, _L),
        joint_notes="tall posture; no lumbar flexion to finish the rep",
        levels=(["banded march"], ["isometric hold above 90 degrees", "heavier stack"]),
        alts=["hanging_knee_raise", "long_leg_marches"],
        fit=["balance_demand", "low_recovery_cost"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "hip-flexor work is generally optional; walking and knee raises already load it"),
        ratings=_ratings(
            functional=("B", "standing hip-flexion strength for gait and stairs"), hypertrophy=("C", "small, optional target")
        ),
        variants=[
            _v("banded hip-flexion march", "equipment", "band around the feet, alternating"),
            _v("seated resisted hip-flexion raise", "position", "seated, end-range above 90 degrees"),
            _v("hip-flexor isometric hold", "tempo", "isometric at the top"),
        ],
    ),
    # §16 carries — anterior (front-rack) loading was the one carry mode missing.
    _add(
        "front_rack_carry_kettlebell",
        "Front Rack Carry (Kettlebell)",
        None,
        sec=16,
        pri="P2",
        aliases=["double kettlebell front-rack carry", "rack walk"],
        target=("abs", ["traps", "back", "quadriceps"], "core"),
        function="loaded_carry_anterior",
        category="carry",
        attrs=("carry_conditioning", "not_applicable", "free_weight", _L, _js(_M, _L, _M, _L, _L)),
        skill=_M,
        equipment=["kettlebell"],
        objectives=["functional", "conditioning", "strength"],
        lat="bilateral",
        progression=(["load", "distance"], ["timed or measured walks"]),
        demand=_M,
        fatigue=(_M, _M),
        joint_notes="rack position needs wrist and shoulder comfort; breathe behind the brace",
        levels=(["single kettlebell in the rack"], ["double kettlebell", "mixed rack + suitcase", "front-rack march in place"]),
        alts=["farmers_walk", "db_gun_carries"],
        fit=["wrist_tolerance", "time_efficient"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "the farmer's and suitcase carries already cover loaded carrying"),
        ratings=_ratings(
            functional=("A", "anterior load: anti-extension and upright posture under load"),
            conditioning=("C", "carry conditioning"),
            strength=("C", "load limited by the rack position"),
        ),
        trunk="loaded_stabilisation",
        variants=[
            _v("single kettlebell front-rack carry", "laterality", "one bell (adds anti-lateral flexion)"),
            _v("mixed front-rack + suitcase carry", "load", "one bell racked, one at the side"),
            _v("heavy front-rack march", "range", "march in place"),
        ],
    ),
    # §17 cardio modalities — protocols are data on the modality (`cardio_protocols`); L4 owns the protocol logic.
    _add(
        "stair_machine",
        "Stair Machine (Steps)",
        ("4377A52C", "builtin"),
        sec=17,
        pri="P1",
        aliases=["stepmill", "stair climber"],
        target=("cardio", ["quadriceps", "glutes", "calves"], "cardio"),
        function="aerobic_stair_climbing",
        category="conditioning",
        attrs=("carry_conditioning", "not_applicable", "cardio_machine", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["stair_climber"],
        objectives=["conditioning"],
        lat="alternating",
        progression=(["step rate", "duration"], ["intervals of steps/min"]),
        demand=_M,
        fatigue=(_M, _M),
        joint_notes="no impact; light handrail touch only for balance",
        levels=(["slow step rate, short bouts"], ["longer bouts", "higher step rate"]),
        alts=["treadmill", "elliptical_trainer"],
        fit=["knee_tolerance", "equipment_unconfirmed", "time_efficient"],
        phase="now",
        gate="equipment_unconfirmed",
        influence=(_AVAIL, "a strong low-impact option, but the home_gym stair machine is unconfirmed"),
        ratings=_ratings(conditioning=("A", "high aerobic stimulus with no impact"), functional=("B", "stair capacity")),
        variants=[_v("stair machine (floors)", "equipment", "floors counter", hevy="4377A52B")],
        protocols=_ALL_PROTOCOLS,
    ),
    _add(
        "recumbent_bike",
        "Recumbent Bike",
        ("35e53528-d898-4721-9a36-65bc003eb0cb", "custom_existing"),
        sec=17,
        pri="P1",
        aliases=["recumbent cycle"],
        target=("cardio", ["quadriceps"], "cardio"),
        function="aerobic_cycling_seated_supported",
        category="conditioning",
        attrs=("carry_conditioning", "not_applicable", "cardio_machine", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["recumbent_bike"],
        objectives=["conditioning"],
        lat="alternating",
        progression=(["resistance level", "duration", "cadence"], ["continuous or interval blocks"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="back-supported, no impact, low balance demand",
        levels=(["short easy bouts"], ["longer bouts", "intervals"]),
        alts=["cycling", "elliptical_trainer"],
        fit=["knee_tolerance", "low_back_tolerance", "low_recovery_cost", "equipment_unconfirmed"],
        phase="now",
        gate="equipment_unconfirmed",
        influence=(
            _AVAIL,
            "named in the brief's modality list; equipment state unconfirmed, so it informs the cardio model only once confirmed",
        ),
        ratings=_ratings(conditioning=("A", "lowest-impact, lowest-balance aerobic option; easy to dose")),
        protocols=_ALL_PROTOCOLS,
    ),
    _add(
        "ski_erg",
        "Ski Erg",
        ("5D99A2FA", "builtin"),
        sec=17,
        pri="P2",
        aliases=["skierg", "nordic ski erg"],
        target=("cardio", ["back", "triceps", "abs"], "cardio"),
        function="aerobic_upper_body_dominant",
        category="conditioning",
        attrs=("carry_conditioning", "not_applicable", "cardio_machine", _M, _js(_L, _L, _L, _L, _M)),
        skill=_L,
        equipment=["ski_erg"],
        objectives=["conditioning"],
        lat="bilateral",
        progression=(["damper", "duration", "pace"], ["continuous or intervals"]),
        demand=_M,
        fatigue=(_M, _M),
        joint_notes="hip hinge plus shoulder extension; light damper first",
        levels=(["short easy bouts"], ["intervals"]),
        alts=["rowing_machine", "air_bike"],
        fit=["equipment_unconfirmed", "knee_tolerance"],
        phase="now",
        gate="equipment_unconfirmed",
        influence=(_AVAIL, "rowing and the air bike already serve upper-body-inclusive conditioning"),
        ratings=_ratings(conditioning=("B", "upper-body-inclusive aerobic work, no impact")),
        protocols=_LOW_IMPACT_PROTOCOLS,
    ),
    _add(
        "swimming",
        "Swimming",
        ("B60A678F", "builtin"),
        sec=17,
        pri="P2",
        aliases=["lap swimming"],
        target=("cardio", ["back", "front_delts"], "cardio"),
        function="aerobic_non_weight_bearing",
        category="conditioning",
        attrs=("carry_conditioning", "not_applicable", "not_applicable", _M, _js(_L, _L, _L, _L, _M)),
        skill=_M,
        equipment=["swimming_pool"],
        objectives=["conditioning"],
        lat="alternating",
        progression=(["duration", "intervals of lengths"], ["continuous or intervals"]),
        demand=_L,
        fatigue=(_M, _M),
        joint_notes="non-weight-bearing; stroke choice sets the shoulder load",
        levels=(["short easy sets with rests"], ["continuous swims", "intervals"]),
        alts=["recumbent_bike", "elliptical_trainer"],
        fit=["equipment_unconfirmed", "knee_tolerance", "enjoyment_variable"],
        phase="now",
        gate="equipment_unconfirmed",
        influence=(_AVAIL, "pool access is not part of home_gym"),
        ratings=_ratings(conditioning=("B", "non-weight-bearing aerobic work; skill sets the dose")),
        variants=[_v("deep-water running", "equipment", "flotation belt, deep end")],
        protocols=_LOW_IMPACT_PROTOCOLS,
    ),
    _add(
        "rucking",
        "Rucking (Loaded Walk)",
        None,
        sec=17,
        pri="P2",
        aliases=["loaded hiking", "ruck walk", "weighted vest walk"],
        target=("cardio", ["quadriceps", "glutes", "traps"], "cardio"),
        function="aerobic_loaded_walking",
        category="conditioning",
        attrs=("carry_conditioning", "not_applicable", "free_weight", _M, _js(_M, _L, _L, _L, _L)),
        skill=_L,
        equipment=["ruck_vest"],
        objectives=["conditioning", "functional"],
        lat="alternating",
        progression=(["load", "distance", "grade"], ["continuous"]),
        demand=_M,
        fatigue=(_M, _M),
        joint_notes="adds load to every step on top of a high daily walking volume; feet, knees and back take it",
        levels=(["light load, flat route"], ["heavier load", "hills", "loaded hiking"]),
        alts=["walking", "treadmill"],
        fit=["body_mass_load", "knee_tolerance", "low_back_tolerance", "equipment_unconfirmed"],
        phase="later",
        gate="joint_tolerance",
        influence=(_AVAIL, "while body mass is high, the body itself is the load; incline walking progresses walking first"),
        ratings=_ratings(conditioning=("B", "raises walking intensity without running"), functional=("B", "loaded locomotion")),
        variants=[_v("weighted-vest walking", "equipment", "vest instead of a pack")],
        protocols=["easy_recovery_aerobic", "moderate_continuous", "progressive_endurance", "incline_resistance_progression"],
    ),
    _add(
        "step_aerobics_low_impact",
        "Low-Impact Step Aerobics",
        ("5E0DDACE", "builtin"),
        sec=17,
        pri="P3",
        aliases=["step aerobics", "aerobics"],
        target=("cardio", ["quadriceps", "calves"], "cardio"),
        function="aerobic_stepping",
        category="conditioning",
        attrs=("carry_conditioning", "not_applicable", "bodyweight", _M, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["plyo_box"],
        objectives=["conditioning"],
        lat="alternating",
        progression=(["step height", "duration"], ["continuous"]),
        demand=_M,
        fatigue=(_L, _M),
        joint_notes="no jumping; low step",
        levels=(["floor marching"], ["low step", "higher step"]),
        alts=["walking", "stair_machine"],
        fit=["enjoyment_variable", "balance_demand"],
        phase="now",
        gate=None,
        influence=(_AVAIL, "walking already covers this stimulus"),
        ratings=_ratings(conditioning=("C", "low-impact aerobic work; adherence-dependent")),
        protocols=["easy_recovery_aerobic", "moderate_continuous", "structured_intervals"],
    ),
    _add(
        "arm_ergometer",
        "Arm Ergometer",
        None,
        sec=17,
        pri="P3",
        aliases=["upper-body ergometer", "UBE", "arm bike"],
        target=("cardio", ["front_delts", "back"], "cardio"),
        function="aerobic_upper_body_only",
        category="conditioning",
        attrs=("carry_conditioning", "not_applicable", "cardio_machine", _H, _js(_L, _L, _L, _L, _M)),
        skill=_L,
        equipment=["arm_ergometer"],
        objectives=["conditioning"],
        lat="alternating",
        progression=(["resistance", "duration"], ["continuous or intervals"]),
        demand=_L,
        fatigue=(_M, _L),
        joint_notes="seated; the conditioning option when the legs must rest",
        levels=(["short easy bouts"], ["longer bouts", "intervals"]),
        alts=["ski_erg", "air_bike"],
        fit=["equipment_unconfirmed"],
        phase="specialist",
        gate="equipment_unconfirmed",
        influence=(_AVAIL, "a lower-limb-injury fallback; small aerobic stimulus otherwise"),
        ratings=_ratings(conditioning=("C", "small muscle mass limits the aerobic stimulus")),
        protocols=["easy_recovery_aerobic", "moderate_continuous", "structured_intervals"],
    ),
    # §18 mobility — never in a muscle-growth ranking; programmed only for an identified limitation or purpose.
    _add(
        "knee_to_wall_dorsiflexion",
        "Knee-to-Wall Ankle Dorsiflexion",
        None,
        sec=18,
        pri="P2",
        aliases=["knee to wall", "ankle dorsiflexion mobilisation"],
        target=("mobility", ["calves"], "lower"),
        function="mobility_ankle_dorsiflexion",
        category="mobility",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["mobility"],
        lat="unilateral",
        progression=(["distance from the wall"], ["10-15 slow reps"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="heel stays down; active mobility",
        levels=([], ["loaded half-kneeling dorsiflexion"]),
        alts=["leg_swings"],
        fit=["ankle_tolerance", "low_recovery_cost"],
        phase="now",
        gate="identified_need",
        influence=(_AVAIL, "used when squat or step-down depth is ankle-limited"),
        ratings=_ratings(mobility=("A", "active dorsiflexion range; also a simple measure")),
        variants=[_v("bent-knee loaded dorsiflexion", "load", "half-kneeling, dumbbell on the knee (soleus)")],
    ),
    _add(
        "hip_cars",
        "Hip CARs",
        None,
        sec=18,
        pri="P2",
        aliases=["hip controlled articular rotations"],
        target=("mobility", ["hip_flexors", "glutes"], "lower"),
        function="mobility_hip_active",
        category="mobility",
        attrs=("corrective", "not_applicable", "bodyweight", _M, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["mobility"],
        lat="unilateral",
        progression=(["range", "slower tempo"], ["3-5 slow circles"]),
        demand=_M,
        fatigue=(_L, _L),
        joint_notes="standing with support or quadruped",
        levels=(["quadruped"], ["standing unsupported"]),
        alts=["walking_hip_circles", "90_90_hip_stretch"],
        fit=["low_recovery_cost", "balance_demand"],
        phase="now",
        gate="identified_need",
        influence=(_AVAIL, "warm-up or limitation tool; walking_hip_circles already exists"),
        ratings=_ratings(mobility=("B", "active hip range under control")),
    ),
    _add(
        "shoulder_cars",
        "Shoulder CARs",
        None,
        sec=18,
        pri="P2",
        aliases=["shoulder controlled articular rotations"],
        target=("mobility", ["rotator_cuff"], "upper"),
        function="mobility_shoulder_active",
        category="mobility",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["mobility"],
        lat="unilateral",
        progression=(["range", "slower tempo"], ["3-5 slow circles"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="pain-free range only",
        levels=([], ["slower, larger circles"]),
        alts=["er_wall_slides", "angels_and_devils"],
        fit=["shoulder_tolerance", "low_recovery_cost"],
        phase="now",
        gate="identified_need",
        influence=(_AVAIL, "warm-up or limitation tool"),
        ratings=_ratings(mobility=("B", "active shoulder range under control")),
        variants=[_v("scapular CARs", "range", "scapula only")],
    ),
    _add(
        "adductor_rock_back",
        "Adductor Rock-Back",
        None,
        sec=18,
        pri="P2",
        aliases=["quadruped adductor rock back"],
        target=("mobility", ["adductors"], "lower"),
        function="mobility_hip_abduction_flexion",
        category="mobility",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["mobility"],
        lat="unilateral",
        progression=(["range"], ["8-12 slow reps"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="quadruped: kneeling tolerance needed",
        levels=([], ["deeper rock-back"]),
        alts=["90_90_hip_stretch"],
        fit=["floor_transition", "knee_tolerance"],
        phase="now",
        gate="identified_need",
        influence=(_AVAIL, "used when squat depth is adductor/hip limited"),
        ratings=_ratings(mobility=("B", "adductor length with hip flexion")),
    ),
    _add(
        "half_kneeling_hip_flexor_stretch",
        "Half-Kneeling Hip Flexor Stretch",
        ("f623b185-7e9e-46c7-bc6e-b587efd0d64d", "custom_existing"),
        sec=18,
        pri="P2",
        aliases=["hip flexor stretch", "half-kneeling hip flexor mobilisation"],
        target=("mobility", ["hip_flexors"], "lower"),
        function="mobility_hip_extension",
        category="mobility",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["mobility"],
        lat="unilateral",
        progression=(["posterior pelvic tilt", "overhead reach"], ["30-60 s or slow reps"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="kneeling: pad under the knee",
        levels=([], ["couch stretch (rectus femoris)"]),
        alts=["90_90_hip_stretch"],
        fit=["knee_tolerance", "floor_transition"],
        phase="now",
        gate="identified_need",
        influence=(_AVAIL, "used for an identified hip-extension limitation"),
        ratings=_ratings(mobility=("B", "hip-extension range with a glute contraction")),
        variants=[_v("couch stretch", "position", "back knee against the wall (rectus femoris)")],
    ),
    _add(
        "wrist_extension_mobilization",
        "Wrist Extension Mobilization",
        None,
        sec=18,
        pri="P3",
        aliases=["wrist extension mobilisation", "quadruped wrist rocks"],
        target=("mobility", ["forearms"], "upper"),
        function="mobility_wrist_extension",
        category="mobility",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _M, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["mobility"],
        lat="bilateral",
        progression=(["range", "load through the hands"], ["10-15 rocks"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="gentle; stop short of pain",
        levels=(["against a wall"], ["quadruped", "front-rack position holds"]),
        alts=["wrist_extension_dumbbell"],
        fit=["wrist_tolerance"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "only for a front-rack or push-up wrist limitation"),
        ratings=_ratings(mobility=("C", "wrist-extension range")),
    ),
    # §19 power / athletic — optional; never auto-programmed in the current phase; skill + impact gates apply.
    _add(
        "medicine_ball_chest_pass",
        "Medicine Ball Chest Pass",
        None,
        sec=19,
        pri="P2",
        aliases=["med-ball chest pass", "med-ball chest throw"],
        target=("full_body", ["chest", "triceps", "front_delts"], "upper"),
        function="power_horizontal_push",
        category="athletic",
        attrs=("skill_athletic", "not_applicable", "free_weight", _M, _js(_L, _L, _M, _M, _M)),
        skill=_M,
        equipment=["medicine_ball"],
        objectives=["strength", "functional"],
        lat="bilateral",
        progression=(["ball mass", "distance / intent"], ["3-6 crisp reps, full rest"]),
        demand=_M,
        fatigue=(_L, _L),
        joint_notes="throw into a wall; no catching heavy balls",
        levels=(["seated explosive med-ball press"], ["standing", "split-stance, then rotational"]),
        alts=["medicine_ball_slams", "bench_press_dumbbell"],
        fit=["shoulder_tolerance", "low_recovery_cost"],
        phase="later",
        gate="skill",
        influence=(_AVAIL, "power work is not auto-programmed in the current phase"),
        ratings=_ratings(strength=("C", "rate of force, not load"), functional=("B", "upper-body power with low impact")),
        variants=[_v("seated explosive med-ball press", "level", "seated, back supported", level=0)],
    ),
    _add(
        "medicine_ball_scoop_toss",
        "Medicine Ball Scoop Toss",
        None,
        sec=19,
        pri="P2",
        aliases=["scoop toss", "underhand med-ball throw"],
        target=("full_body", ["glutes", "hamstrings"], "full_body"),
        function="power_hip_extension",
        category="athletic",
        attrs=("skill_athletic", "not_applicable", "free_weight", _M, _js(_M, _L, _L, _L, _L)),
        skill=_M,
        equipment=["medicine_ball"],
        objectives=["functional", "strength"],
        lat="bilateral",
        progression=(["ball mass", "intent"], ["3-6 crisp reps, full rest"]),
        demand=_M,
        fatigue=(_L, _L),
        joint_notes="hinge pattern; no landing, low impact",
        levels=(["light ball, short toss"], ["heavier ball", "backward overhead throw"]),
        alts=["kettlebell_swing", "medicine_ball_slams"],
        fit=["low_back_tolerance"],
        phase="later",
        gate="skill",
        influence=(_AVAIL, "power work is not auto-programmed in the current phase"),
        ratings=_ratings(functional=("B", "hip-extension power with no landing"), strength=("C", "rate of force, not load")),
        variants=[_v("medicine ball overhead throw", "direction", "backward overhead")],
    ),
    _add(
        "low_box_step_off_landing",
        "Low-Box Step-Off Landing",
        None,
        sec=19,
        pri="P2",
        aliases=["step-off landing", "drop landing (low)"],
        target=("full_body", ["quadriceps", "glutes", "calves"], "lower"),
        function="landing_mechanics",
        category="athletic",
        attrs=("skill_athletic", "not_applicable", "bodyweight", _L, _js(_L, _M, _L, _L, _L)),
        skill=_M,
        equipment=["plyo_box"],
        objectives=["functional"],
        lat="bilateral",
        progression=(["box height", "single-leg", "lateral"], ["3-5 landings, stick 2 s"]),
        demand=_H,
        fatigue=(_L, _L),
        joint_notes="landing loads the knees and ankles at a multiple of body mass",
        levels=(["squat snap-down landing"], ["low-amplitude jump-and-stick", "controlled lateral bound-and-stick"]),
        alts=["controlled_forward_step_down"],
        fit=["impact", "body_mass_load", "knee_tolerance", "ankle_tolerance"],
        phase="later",
        gate="impact",
        influence=(_AVAIL, "the first rung of landing work, behind the charter's plyometric gate"),
        ratings=_ratings(functional=("B", "deceleration and landing control")),
        gates=["charter_plyometric"],
        variants=[
            _v("squat snap-down landing", "level", "no box: fast drop into a stuck landing", level=0),
            _v("low-amplitude jump-and-stick", "level", "small jump, stuck landing", level=2),
            _v("controlled lateral bound-and-stick", "level", "frontal-plane bound, stuck landing", level=3),
        ],
    ),
    # §20 neck — optional specialist, symptom-aware, no aggressive loading.
    _add(
        "supine_deep_neck_flexor_nod",
        "Supine Deep Neck Flexor Nod",
        None,
        sec=20,
        pri="P3",
        aliases=["chin nod", "supine chin tuck"],
        target=("neck", [], "upper"),
        function="neck_deep_flexor_control",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["functional"],
        lat="not_applicable",
        progression=(["hold time"], ["5-10 s holds"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="gentle; symptom-aware",
        levels=([], ["head-lift hold", "lying neck curl (loaded, later)"]),
        alts=["neck_isometric_holds"],
        fit=["low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "optional, symptom-led"),
        ratings=_ratings(functional=("C", "deep neck-flexor control")),
        variants=[_v("lying neck curl", "level", "loaded neck flexion", hevy="22FEDCA4", level=2)],
    ),
    _add(
        "neck_isometric_holds",
        "Neck Isometric Holds",
        None,
        sec=20,
        pri="P3",
        aliases=["neck isometrics", "4-way neck isometrics"],
        target=("neck", ["traps"], "upper"),
        function="neck_isometric_strength",
        category="rehab_control",
        attrs=("corrective", "not_applicable", "bodyweight", _H, _js(_L, _L, _L, _L, _L)),
        skill=_L,
        equipment=["bodyweight"],
        objectives=["functional"],
        lat="not_applicable",
        progression=(["hand pressure", "hold time"], ["5-10 s holds each direction"]),
        demand=_L,
        fatigue=(_L, _L),
        joint_notes="submaximal hand pressure; no aggressive loading",
        levels=([], ["longer holds"]),
        alts=["supine_deep_neck_flexor_nod"],
        fit=["low_recovery_cost"],
        phase="specialist",
        gate="identified_need",
        influence=(_AVAIL, "optional, symptom-led"),
        ratings=_ratings(functional=("C", "neck isometric strength")),
        variants=[_v("controlled neck rotation mobility", "range", "slow active rotation, mobility")],
    ),
]


def _row(sec: int, cand: str, outcome: str, pri: str, ref: str | None, note: str, **extra: Any) -> dict[str, Any]:
    return {"section": sec, "candidate": cand, "outcome": outcome, "priority": pri, "ref": ref, "note": note, **extra}


def A(sec: int, cand: str, key: str, note: str = "", kind: str = "candidate") -> dict[str, Any]:
    """ADD: `key` is the new canonical in ADDITIONS (its priority is the addition's own)."""
    pri = next(a["expansion_profile"]["priority"] for a in ADDITIONS if a["key"] == key)
    return _row(sec, cand, "ADD", pri, key, note, kind=kind)


def V(sec: int, cand: str, pri: str, of: str, axis: str, value: str, hevy: str | None = None, note: str = "") -> dict[str, Any]:
    """VARIANT of canonical `of` (existing or added): what changes, and Hevy's template for it when one exists."""
    return _row(sec, cand, "VARIANT", pri, of, note, variant={"axis": axis, "value": value, "hevy_template": hevy})


def C(sec: int, cand: str, pri: str, by: str, note: str = "", kind: str = "candidate") -> dict[str, Any]:
    """ALREADY_COVERED by library movement `by`."""
    return _row(sec, cand, "ALREADY_COVERED", pri, by, note, kind=kind)


def D(sec: int, cand: str, pri: str, why: str) -> dict[str, Any]:
    return _row(sec, cand, "DEFER", pri, None, why)


# The amendment's candidates, verbatim and in order: the accounting test holds RECONCILIATION to exactly these.
AMENDMENT_15_CANDIDATES: dict[int, tuple[str, ...]] = {
    1: (
        "single-arm standing cable chest press",
        "bilateral standing cable chest press",
        "flat Smith bench",
        "incline Smith bench",
        "feet-elevated push-up",
        "deficit push-up on handles",
        "suspension-trainer push-up",
        "single-arm machine chest press",
        "converging plate-loaded chest press",
        "chest-focused isometric cable press",
    ),
    2: (
        "single-arm high-to-low cable pulldown",
        "half-kneeling single-arm cable pulldown",
        "iso-lateral plate-loaded pulldown",
        "barbell seal row",
        "incline-bench-supported barbell row",
        "unilateral chest-supported machine row",
        "plate-loaded iso-lateral high row",
        "single-arm machine high row",
        "chest-supported scapular retraction",
        "prone incline scapular row",
        "cable row with deliberate scapular retraction",
        "sternum chin-up",
    ),
    3: (
        "trap-bar shrug",
        "cable shrug",
        "prone incline DB shrug",
        "lower-trap prone Y raise",
        "trap-3 raise",
        "cable Y raise",
        "overhead scapular-elevation drill",
        "incline-bench lower-trap raise",
    ),
    4: (
        "bilateral cable lateral raise",
        "lean-away cable lateral",
        "cable scaption",
        "DB scaption",
        "single-arm cable rear-delt row",
        "incline cable rear-delt fly",
        "side-lying cable lateral",
        "cable ER at side",
        "cable ER at 90° abduction",
        "side-lying DB ER",
        "cable IR",
        "serratus cable punch",
        "serratus wall slide with lift-off",
        "push-up plus",
        "bottoms-up KB hold",
    ),
    5: (
        "cable rope hammer curl",
        "reverse-grip cable curl",
        "reverse EZ curl",
        "cable preacher curl",
        "incline cable curl",
        "Zottman curl",
        "single-arm supported cable curl",
        "cross-body cable hammer curl",
    ),
    6: (
        "single-arm cross-body cable extension",
        "reverse-grip pushdown",
        "single-arm neutral pushdown",
        "cable katana extension",
        "plate-loaded dip machine",
        "single-arm overhead cable extension",
    ),
    7: (
        "seated DB wrist extension",
        "barbell reverse wrist curl",
        "wrist roller",
        "DB pronation",
        "DB supination",
        "hammer-lever pronation/supination",
        "DB radial deviation",
        "DB ulnar deviation",
        "plate pinch hold",
        "heavy gripper squeeze",
        "band finger extension",
        "towel-grip hold",
        "thick-grip hold",
        "wrist extensor eccentric lowering",
    ),
    8: (
        "front-foot-elevated split squat",
        "heel-elevated DB squat",
        "heel-elevated Smith squat",
        "cyclist squat",
        "assisted sissy squat",
        "reverse Nordic",
        "Spanish squat",
        "controlled forward step-down",
        "controlled lateral step-down",
        "backward sled drag",
        "split-squat isometric hold",
        "step-up with controlled eccentric",
    ),
    9: (
        "standing single-leg curl machine",
        "standing cable hamstring curl",
        "assisted eccentric Nordic",
        "bilateral sliding curl",
        "B-stance RDL",
        "long-lever bridge isometric",
        "bridge walkout",
        "single-leg bridge isometric",
        "hinge-biased 45° back extension",
    ),
    10: (
        "seated hip abduction machine",
        "standing cable hip abduction",
        "side-lying weighted abduction",
        "single-leg hip thrust",
        "B-stance hip thrust",
        "hip airplane",
        "lateral band walk",
        "monster walk",
        "glute-biased FFE split squat",
        "high step-up glute emphasis",
        "standing cable hip extension with supported torso",
    ),
    11: (
        "seated adduction machine",
        "standing cable adduction",
        "short-lever Copenhagen",
        "long-lever Copenhagen progression",
        "dynamic Copenhagen adduction",
        "supine ball squeeze",
        "side-lying adduction raise",
        "adductor-biased lateral sliding squat",
    ),
    12: (
        "single-leg seated calf raise",
        "bent-knee calf raise on leg press",
        "loaded donkey calf raise machine",
        "wall tibialis raise",
        "tibialis raise machine",
        "resisted inversion",
        "resisted eversion",
        "single-leg balance with ankle control",
        "short-foot",
        "toe yoga",
    ),
    13: (
        "reverse crunch",
        "hollow hold",
        "bear plank",
        "bear crawl",
        "stir-the-pot",
        "body-saw plank",
        "McGill curl-up",
        "dead bug with band pulldown",
        "half-kneeling cable lift",
        "cable anti-rotation walkout",
        "suitcase deadlift",
        "weighted dead bug",
        "tall-kneeling cable anti-extension pulldown",
        "single-arm loaded standing march",
        "side plank with hip abduction",
    ),
    14: (
        "Sorensen hold",
        "bird-dog row",
        "quadruped contralateral raise with hold",
        "hip-hinge isometric hold",
        "suitcase deadlift",
        "offset-load RDL",
        "back-extension isometric hold",
    ),
    15: (
        "standing cable knee drive",
        "banded hip-flexion march",
        "seated resisted hip-flexion raise",
        "supine loaded straight-leg raise",
        "standing psoas march",
        "hip-flexor isometric hold",
    ),
    16: (
        "single KB front-rack carry",
        "double KB front-rack carry",
        "waiter's carry",
        "mixed front-rack + suitcase",
        "offset farmer's",
        "bear-hug sandbag carry",
        "heavy front-rack march",
        "weighted-vest walking",
        "heavy sled drag variations",
    ),
    17: (
        "stair-climber/stepmill",
        "SkiErg",
        "swimming",
        "deep-water running",
        "outdoor hill walking",
        "hiking",
        "loaded hiking/rucking",
        "low-impact step aerobics",
        "arm ergometer",
        "backward treadmill walking",
    ),
    18: (
        "knee-to-wall dorsiflexion",
        "bent-knee dorsiflexion",
        "active 90/90 switches",
        "hip CARs",
        "shoulder CARs",
        "adductor rock-back",
        "couch stretch",
        "half-kneeling hip-flexor mobilization",
        "deep squat pry",
        "loaded deep squat hold",
        "serratus wall slide with lift-off",
        "scapular CARs",
        "wrist extension mobilization",
        "active straight-leg raise",
        "thoracic open-book",
    ),
    19: (
        "med-ball chest pass",
        "scoop toss",
        "overhead throw",
        "low-box step-off landing",
        "squat snap-down landing",
        "low-amplitude jump-and-stick",
        "controlled lateral bound-and-stick",
        "low-impact sled acceleration",
        "seated explosive med-ball press",
    ),
    20: (
        "supine deep-neck-flexor nod",
        "gentle isometric flexion/extension/lateral flexion",
        "controlled rotation mobility",
    ),
}

# The items the amendment says to KEEP (and, for the trunk list, reclassify by purpose): reconciled the same way.
AMENDMENT_15_KEEP: dict[int, tuple[str, ...]] = {
    13: ("ab wheel", "Pallof", "side plank", "bird dog", "cable crunch", "hanging knee raise"),
    16: ("farmer's", "suitcase", "overhead", "sandbag"),
    17: ("walking", "treadmill", "cycling", "recumbent", "elliptical", "rowing", "air bike"),
    19: ("jumps", "pogos", "KB swings", "slams", "sprint drills", "Olympic variations"),
}

_RF = "reclassify by trunk_function for L1's category contract"
RECONCILIATION: list[dict[str, Any]] = [
    # §1 chest (horizontal press, incline press, chest adduction and bodyweight pressing are all served)
    V(1, "single-arm standing cable chest press", "P3", "standing_cable_chest_press", "laterality", "unilateral (anti-rotation)"),
    A(1, "bilateral standing cable chest press", "standing_cable_chest_press", "the no-bench, standing horizontal press"),
    V(
        1,
        "flat Smith bench",
        "P2",
        "bench_press_barbell",
        "equipment",
        "Smith machine (fixed path)",
        "0FBF7195",
        "a stable near-failure press",
    ),
    V(1, "incline Smith bench", "P2", "incline_bench_press_barbell", "equipment", "Smith machine (fixed path)", "3A6FA3D1"),
    V(1, "feet-elevated push-up", "P3", "push_up", "level", "feet elevated (harder)", "C43825EA", "same bodyweight gate as the push-up"),
    V(1, "deficit push-up on handles", "P3", "push_up", "range", "deficit on handles (longer range)"),
    V(1, "suspension-trainer push-up", "P3", "push_up", "equipment", "suspension trainer; body angle sets the load", "AEA56BDC"),
    V(1, "single-arm machine chest press", "P3", "chest_press_machine", "laterality", "unilateral (iso-lateral machine)", "24706DCD"),
    V(
        1,
        "converging plate-loaded chest press",
        "P2",
        "chest_press_machine",
        "equipment",
        "converging plate-loaded (iso-lateral)",
        "24706DCD",
    ),
    V(1, "chest-focused isometric cable press", "P3", "standing_cable_chest_press", "tempo", "isometric hold"),
    # §2 lats / upper back / rhomboids
    V(2, "single-arm high-to-low cable pulldown", "P2", "lat_pulldown_cable", "laterality", "single-arm, high-to-low", "2EE45F81"),
    V(2, "half-kneeling single-arm cable pulldown", "P3", "lat_pulldown_cable", "position", "half-kneeling, single-arm"),
    V(2, "iso-lateral plate-loaded pulldown", "P3", "lat_pulldown_machine", "equipment", "iso-lateral plate-loaded", "72880C57"),
    V(2, "barbell seal row", "P2", "db_chest_supported_rows", "equipment", "barbell, prone on a raised flat bench", "DF3BDB9C"),
    V(2, "incline-bench-supported barbell row", "P3", "db_chest_supported_rows", "equipment", "barbell, incline bench"),
    V(2, "unilateral chest-supported machine row", "P2", "seated_row_machine", "laterality", "iso-lateral, one arm", "AA1EB7D8"),
    V(2, "plate-loaded iso-lateral high row", "P2", "high_cable_row", "equipment", "plate-loaded iso-lateral high row", "BC3492DA"),
    V(2, "single-arm machine high row", "P3", "1_arm_high_cable_row", "equipment", "machine, single-arm", "BC3492DA"),
    V(2, "chest-supported scapular retraction", "P3", "dead_arm_scap_rows", "position", "chest-supported, straight-arm retraction"),
    V(2, "prone incline scapular row", "P3", "db_chest_supported_rows", "tempo", "pause in full retraction"),
    V(2, "cable row with deliberate scapular retraction", "P3", "seated_cable_row", "tempo", "pause in full retraction"),
    V(
        2,
        "sternum chin-up",
        "P3",
        "chin_up",
        "range",
        "to the sternum, leaning back (advanced)",
        "EE2938D1",
        "behind the chin-up's bodyweight gate",
    ),
    # §3 traps / scapular (upper trap served by shrugs; the lower/mid trap Y-raise line is new)
    V(3, "trap-bar shrug", "P3", "shrug_barbell", "equipment", "trap bar, neutral grip"),
    V(3, "cable shrug", "P3", "shrug_dumbbell", "equipment", "cable", "FFABC123"),
    V(3, "prone incline DB shrug", "P3", "shrug_dumbbell", "position", "prone on an incline (mid-trap bias)"),
    A(3, "lower-trap prone Y raise", "chest_supported_y_raise_dumbbell", "lower-trap upward rotation was unserved"),
    V(
        3,
        "trap-3 raise",
        "P2",
        "chest_supported_y_raise_dumbbell",
        "laterality",
        "single-arm, bent-over, arm in line with the lower-trap fibres",
    ),
    V(3, "cable Y raise", "P2", "chest_supported_y_raise_dumbbell", "equipment", "cable, standing", "28927A36"),
    D(3, "overhead scapular-elevation drill", "P3", "no identified upward-rotation limitation; the Y raise and overhead hold cover it"),
    C(3, "incline-bench lower-trap raise", "P2", "chest_supported_y_raise_dumbbell", "the same movement on an incline bench"),
    # §4 shoulders, cuff, scapular stabilisers, serratus
    V(4, "bilateral cable lateral raise", "P3", "lateral_raise_cable_single_arm", "laterality", "both arms", "BE289E45"),
    V(4, "lean-away cable lateral", "P2", "lateral_raise_cable_single_arm", "position", "lean-away (longer range)"),
    V(4, "cable scaption", "P3", "front_raise_dumbbell", "plane", "scapular plane, cable", "DBB91A3C"),
    V(4, "DB scaption", "P2", "front_raise_dumbbell", "plane", "scapular plane, thumbs up"),
    V(4, "single-arm cable rear-delt row", "P2", "db_rear_delt_rows", "equipment", "cable, single-arm, high elbow"),
    V(4, "incline cable rear-delt fly", "P3", "rear_delt_reverse_fly_cable", "position", "chest-supported on an incline bench"),
    V(4, "side-lying cable lateral", "P3", "lateral_raise_cable_single_arm", "position", "side-lying (lengthened-range peak)"),
    C(4, "cable ER at side", "P2", "rotator_cuff_external_rotation", "its equipment/pattern labels are wrong — see QUALITY_FINDINGS"),
    V(4, "cable ER at 90° abduction", "P3", "rotator_cuff_external_rotation", "position", "90/90 (abducted)"),
    C(4, "side-lying DB ER", "P3", "db_external_rotation"),
    A(4, "cable IR", "cable_internal_rotation", "internal rotation had no movement"),
    A(4, "serratus cable punch", "cable_serratus_punch", "serratus had no movement"),
    V(4, "serratus wall slide with lift-off", "P2", "er_wall_slides", "range", "forearms on the wall, slide up and lift off (serratus)"),
    V(4, "push-up plus", "P2", "incline_push_up", "range", "+ full protraction at the top (serratus)"),
    V(4, "bottoms-up KB hold", "P3", "overhead_hold", "grip", "kettlebell bottoms-up (reflexive cuff demand)"),
    # §5 biceps / brachialis / brachioradialis (elbow-flexor emphasis is grip orientation, never a new canonical)
    V(5, "cable rope hammer curl", "P2", "hammer_curl_dumbbell", "equipment", "cable rope", "36E8F14E"),
    V(5, "reverse-grip cable curl", "P3", "reverse_curl_dumbbell", "equipment", "cable", "9F48F858"),
    V(5, "reverse EZ curl", "P3", "reverse_curl_dumbbell", "equipment", "EZ bar", "112FC6B7"),
    V(5, "cable preacher curl", "P3", "preacher_curl_dumbbell", "equipment", "cable"),
    C(5, "incline cable curl", "P3", "behind_the_back_curl_cable", "the same arm-behind-torso lengthened position"),
    V(5, "Zottman curl", "P3", "bicep_curl_dumbbell", "grip", "supinated up, pronated down", "123EE239"),
    V(5, "single-arm supported cable curl", "P3", "bicep_curl_cable", "laterality", "single-arm, arm supported", "B33B526E"),
    V(5, "cross-body cable hammer curl", "P3", "cross_body_hammer_curls", "equipment", "cable"),
    # §6 triceps (overhead, pushdown, pressing and dip patterns are all served)
    V(6, "single-arm cross-body cable extension", "P3", "triceps_extension_cable", "laterality", "single-arm, cross-body line of pull"),
    V(6, "reverse-grip pushdown", "P3", "triceps_pushdown", "grip", "supinated", "8B5BED30"),
    V(6, "single-arm neutral pushdown", "P3", "triceps_pushdown", "laterality", "single-arm, neutral grip", "552AB030"),
    C(6, "cable katana extension", "P3", "overhead_triceps_extension_cable", "an influencer name for its single-arm cross-body variant"),
    V(6, "plate-loaded dip machine", "P2", "triceps_dip_assisted", "equipment", "seated plate-loaded dip machine", "5122E7D9"),
    V(6, "single-arm overhead cable extension", "P2", "overhead_triceps_extension_cable", "laterality", "single-arm"),
    # §7 forearms / grip / wrist
    A(7, "seated DB wrist extension", "wrist_extension_dumbbell", "wrist extension had no movement"),
    V(7, "barbell reverse wrist curl", "P3", "wrist_extension_dumbbell", "equipment", "barbell", "9202CC23"),
    A(7, "wrist roller", "wrist_roller"),
    A(7, "DB pronation", "forearm_rotation_dumbbell", "forearm rotation had no movement"),
    V(7, "DB supination", "P3", "forearm_rotation_dumbbell", "direction", "supination"),
    V(7, "hammer-lever pronation/supination", "P3", "forearm_rotation_dumbbell", "equipment", "sledgehammer / lever bar"),
    A(7, "DB radial deviation", "wrist_deviation_dumbbell"),
    V(7, "DB ulnar deviation", "P3", "wrist_deviation_dumbbell", "direction", "ulnar"),
    A(7, "plate pinch hold", "plate_pinch_hold", "pinch grip had no movement"),
    A(7, "heavy gripper squeeze", "hand_gripper_squeeze"),
    A(7, "band finger extension", "band_finger_extension"),
    V(7, "towel-grip hold", "P3", "dead_hang", "grip", "towel over the bar"),
    V(7, "thick-grip hold", "P3", "farmers_walk", "grip", "thick handles / fat grips (static hold option)"),
    V(7, "wrist extensor eccentric lowering", "P3", "wrist_extension_dumbbell", "tempo", "eccentric-only"),
    # §8 quadriceps (bilateral squat, unilateral squat and knee extension served; eccentric control + isometrics added)
    V(8, "front-foot-elevated split squat", "P2", "split_squat_dumbbell", "range", "front foot elevated (deeper)"),
    V(8, "heel-elevated DB squat", "P2", "goblet_squat", "stance", "heels elevated (quad bias)"),
    V(8, "heel-elevated Smith squat", "P2", "squat_barbell", "equipment", "Smith machine, heels elevated", "DDCC3821"),
    C(8, "cyclist squat", "P3", "goblet_squat", "its narrow-stance heel-elevated variant; an influencer-name duplicate"),
    A(8, "assisted sissy squat", "sissy_squat", "the assisted form is its level 0"),
    A(8, "reverse Nordic", "band_assisted_reverse_nordic", "the band-assisted form is the canonical; unassisted is a progression"),
    A(8, "Spanish squat", "spanish_squat", "knee-dominant isometric had no movement"),
    A(8, "controlled forward step-down", "controlled_forward_step_down", "eccentric single-leg knee control had no movement"),
    V(8, "controlled lateral step-down", "P2", "controlled_forward_step_down", "direction", "lateral"),
    V(8, "backward sled drag", "P2", "sled_drag", "direction", "backward (knee-dominant)", "7D1BD41D"),
    V(8, "split-squat isometric hold", "P3", "spanish_squat", "tempo", "isometric, split stance"),
    V(8, "step-up with controlled eccentric", "P2", "db_step_up", "tempo", "3-4 s lowering"),
    # §9 hamstrings (hip extension and knee flexion both served; regressions as levels)
    V(9, "standing single-leg curl machine", "P3", "lying_leg_curl_machine", "equipment", "standing single-leg machine", "6120CAAB"),
    V(9, "standing cable hamstring curl", "P3", "lying_leg_curl_machine", "equipment", "cable + ankle strap, standing"),
    V(9, "assisted eccentric Nordic", "P2", "nordic_hamstring_curl", "level", "band-assisted eccentric (on-ramp)"),
    V(
        9,
        "bilateral sliding curl",
        "P2",
        "single_leg_slick_floor_bridge_curl",
        "laterality",
        "both legs (regression)",
        "7993e821-f649-4871-be32-a86005857cdb",
    ),
    V(9, "B-stance RDL", "P2", "romanian_deadlift_dumbbell", "stance", "B-stance / kickstand"),
    V(9, "long-lever bridge isometric", "P3", "glute_bridge", "level", "long lever, isometric (hamstring bias)"),
    V(9, "bridge walkout", "P3", "glute_bridge", "level", "heel walkouts from the bridge"),
    V(9, "single-leg bridge isometric", "P3", "single_leg_glute_bridge", "tempo", "isometric hold"),
    C(9, "hinge-biased 45° back extension", "P2", "back_extension_45", "the hinge-biased execution is its default"),
    # §10 glutes max / med / min
    A(10, "seated hip abduction machine", "hip_abduction_machine", "glute med/min had no loadable movement"),
    V(10, "standing cable hip abduction", "P1", "hip_abduction_machine", "equipment", "cable, standing", "C469EA70"),
    V(10, "side-lying weighted abduction", "P2", "hip_abduction_machine", "position", "side-lying, ankle weight", "DC59D143"),
    V(10, "single-leg hip thrust", "P2", "db_hip_thrust", "laterality", "single-leg", "D1CD146F"),
    V(10, "B-stance hip thrust", "P2", "hip_thrust_barbell", "stance", "B-stance"),
    A(10, "hip airplane", "hip_airplane", "hip rotation control had no movement"),
    A(10, "lateral band walk", "lateral_band_walks"),
    V(10, "monster walk", "P3", "lateral_band_walks", "direction", "diagonal"),
    V(10, "glute-biased FFE split squat", "P3", "split_squat_dumbbell", "position", "front foot elevated + forward torso lean"),
    V(10, "high step-up glute emphasis", "P2", "db_step_up", "range", "high box (glute bias)"),
    C(10, "standing cable hip extension with supported torso", "P2", "cable_kickback"),
    # §11 adductors
    A(11, "seated adduction machine", "hip_adduction_machine", "adductors had no loadable movement"),
    V(11, "standing cable adduction", "P1", "hip_adduction_machine", "equipment", "cable, standing", "22578A94"),
    A(11, "short-lever Copenhagen", "copenhagen_side_plank", "the short lever is its default level"),
    V(11, "long-lever Copenhagen progression", "P2", "copenhagen_side_plank", "level", "long lever"),
    V(11, "dynamic Copenhagen adduction", "P3", "copenhagen_side_plank", "level", "dynamic"),
    V(11, "supine ball squeeze", "P2", "copenhagen_side_plank", "level", "isometric squeeze (level 0)"),
    V(11, "side-lying adduction raise", "P3", "hip_adduction_machine", "position", "side-lying, bodyweight / ankle weight"),
    C(11, "adductor-biased lateral sliding squat", "P2", "db_adductor_slides"),
    # §12 calves / soleus / tibialis / ankle / foot
    V(12, "single-leg seated calf raise", "P3", "seated_calf_raise", "laterality", "single-leg"),
    V(12, "bent-knee calf raise on leg press", "P3", "seated_calf_raise", "equipment", "leg press, knees bent (soleus)"),
    V(12, "loaded donkey calf raise machine", "P3", "standing_calf_raise_machine", "position", "hips flexed (donkey machine)"),
    A(12, "wall tibialis raise", "tibialis_raise", "the charter's lower-leg prep prescribes tibialis work with no movement"),
    V(12, "tibialis raise machine", "P2", "tibialis_raise", "equipment", "tibialis machine"),
    A(12, "resisted inversion", "banded_ankle_inversion_eversion"),
    V(12, "resisted eversion", "P3", "banded_ankle_inversion_eversion", "direction", "eversion"),
    V(12, "single-leg balance with ankle control", "P3", "single_leg_static_balance_with_eyes_closed", "level", "eyes open (regression)"),
    A(12, "short-foot", "short_foot"),
    V(12, "toe yoga", "P3", "short_foot", "level", "toe isolation"),
    # §13 abs / obliques / deep core (every trunk function is served; ADDs are distinct tools)
    A(13, "reverse crunch", "reverse_crunch"),
    V(13, "hollow hold", "P3", "dead_bug", "level", "both limbs extended, static (dead-bug end level)", "970ADF87"),
    V(13, "bear plank", "P2", "bear_crawl", "level", "static, knees hovering"),
    A(13, "bear crawl", "bear_crawl"),
    A(13, "stir-the-pot", "stability_ball_stir_the_pot", "a custom template already exists in the account"),
    V(13, "body-saw plank", "P3", "plank", "level", "rocking forward/back (longer lever)"),
    A(13, "McGill curl-up", "mcgill_curl_up"),
    V(13, "dead bug with band pulldown", "P2", "dead_bug", "load", "band/cable pulldown held overhead"),
    V(13, "half-kneeling cable lift", "P2", "cable_twist_up_to_down", "direction", "low-to-high lift, half-kneeling", "92D858EA"),
    V(13, "cable anti-rotation walkout", "P3", "cable_pallof_press", "level", "walkout away from the stack"),
    A(13, "suitcase deadlift", "suitcase_deadlift", "anti-lateral flexion under a hinge"),
    V(13, "weighted dead bug", "P3", "dead_bug", "load", "dumbbell / ankle weights"),
    V(
        13,
        "tall-kneeling cable anti-extension pulldown",
        "P3",
        "kneeling_straight_arm_pulldown",
        "position",
        "tall-kneeling, ribs-down anti-extension cue",
    ),
    V(13, "single-arm loaded standing march", "P2", "suitcase_carry", "range", "march in place, single load"),
    V(13, "side plank with hip abduction", "P2", "side_plank", "level", "top-leg abduction"),
    # §14 erectors / trunk endurance (loaded erector work is already heavy via squat/DL/RDL; added spinal load is avoided)
    V(14, "Sorensen hold", "P2", "back_extension_45", "tempo", "isometric hold, horizontal"),
    V(14, "bird-dog row", "P3", "bird_dog", "load", "contralateral dumbbell row"),
    C(14, "quadruped contralateral raise with hold", "P3", "bird_dog"),
    V(14, "hip-hinge isometric hold", "P3", "romanian_deadlift_dumbbell", "tempo", "isometric at mid-shin"),
    C(14, "suitcase deadlift", "P2", "suitcase_deadlift", "added in §13"),
    V(14, "offset-load RDL", "P3", "romanian_deadlift_dumbbell", "load", "single offset dumbbell (anti-rotation)"),
    C(14, "back-extension isometric hold", "P3", "back_extension_45", "its Sorensen-hold variant"),
    # §15 hip flexors (dedicated; generally optional)
    A(15, "standing cable knee drive", "standing_cable_knee_drive", "no loadable standing hip-flexion movement"),
    V(15, "banded hip-flexion march", "P3", "standing_cable_knee_drive", "equipment", "band, alternating march"),
    V(15, "seated resisted hip-flexion raise", "P3", "standing_cable_knee_drive", "position", "seated, end range"),
    V(15, "supine loaded straight-leg raise", "P3", "long_leg_marches", "load", "ankle weight"),
    C(15, "standing psoas march", "P3", "standing_cable_knee_drive", "its banded-march variant"),
    V(15, "hip-flexor isometric hold", "P3", "standing_cable_knee_drive", "tempo", "isometric at the top"),
    # §16 carries (grip endurance, trunk stability, loaded locomotion and conditioning)
    V(16, "single KB front-rack carry", "P2", "front_rack_carry_kettlebell", "laterality", "one bell"),
    A(16, "double KB front-rack carry", "front_rack_carry_kettlebell", "anterior-loaded carrying was unserved"),
    V(16, "waiter's carry", "P2", "db_overhead_farmers_carry", "laterality", "single-arm overhead"),
    V(16, "mixed front-rack + suitcase", "P3", "front_rack_carry_kettlebell", "load", "one racked, one at the side"),
    V(16, "offset farmer's", "P3", "farmers_walk", "load", "uneven loads"),
    C(16, "bear-hug sandbag carry", "P2", "sandbag_carry"),
    V(16, "heavy front-rack march", "P3", "front_rack_carry_kettlebell", "range", "march in place"),
    V(16, "weighted-vest walking", "P2", "rucking", "equipment", "vest"),
    C(16, "heavy sled drag variations", "P2", "sled_drag", "logs under Hevy's Sled Pull; direction variants are in §8"),
    # §17 cardio modalities (protocols are data on the modality; L4 owns the protocol logic)
    A(17, "stair-climber/stepmill", "stair_machine", "stair climbing is a named modality with no entry"),
    A(17, "SkiErg", "ski_erg"),
    A(17, "swimming", "swimming"),
    D(17, "deep-water running", "P3", "pool access is not part of home_gym and swimming covers the pool slot; kept as a swimming variant"),
    V(17, "outdoor hill walking", "P1", "walking", "terrain", "outdoor hills (incline progression)"),
    V(17, "hiking", "P2", "walking", "terrain", "trail", "1C34A172"),
    A(17, "loaded hiking/rucking", "rucking"),
    A(17, "low-impact step aerobics", "step_aerobics_low_impact"),
    A(17, "arm ergometer", "arm_ergometer"),
    V(17, "backward treadmill walking", "P3", "treadmill", "direction", "backward (quad bias, knee-friendly)"),
    # §18 mobility (passive flexibility, active mobility, loaded mobility, motor control — never a growth ranking)
    A(18, "knee-to-wall dorsiflexion", "knee_to_wall_dorsiflexion", "ankle mobility had no movement"),
    V(18, "bent-knee dorsiflexion", "P3", "knee_to_wall_dorsiflexion", "load", "half-kneeling, loaded (soleus)"),
    V(18, "active 90/90 switches", "P2", "90_90_hip_stretch", "tempo", "active switches (no hands)"),
    A(18, "hip CARs", "hip_cars"),
    A(18, "shoulder CARs", "shoulder_cars"),
    A(18, "adductor rock-back", "adductor_rock_back"),
    V(18, "couch stretch", "P2", "half_kneeling_hip_flexor_stretch", "position", "back knee against the wall"),
    A(18, "half-kneeling hip-flexor mobilization", "half_kneeling_hip_flexor_stretch", "a custom template already exists in the account"),
    V(18, "deep squat pry", "P2", "bottomed_out_squat_reaches", "load", "goblet-loaded pry"),
    V(18, "loaded deep squat hold", "P3", "bottomed_out_squat_reaches", "load", "goblet-loaded static hold"),
    C(18, "serratus wall slide with lift-off", "P2", "er_wall_slides", "its lift-off variant (§4)"),
    V(18, "scapular CARs", "P3", "shoulder_cars", "range", "scapula only"),
    A(18, "wrist extension mobilization", "wrist_extension_mobilization"),
    V(18, "active straight-leg raise", "P3", "long_leg_marches", "range", "one leg, end-range hold (active hamstring range)"),
    C(18, "thoracic open-book", "P3", "t_spine_rotations"),
    # §19 power / athletic (optional; readiness-gated; never auto-programmed in the current phase)
    A(19, "med-ball chest pass", "medicine_ball_chest_pass"),
    A(19, "scoop toss", "medicine_ball_scoop_toss"),
    V(19, "overhead throw", "P3", "medicine_ball_scoop_toss", "direction", "backward overhead"),
    A(19, "low-box step-off landing", "low_box_step_off_landing", "landing mechanics had no movement"),
    V(19, "squat snap-down landing", "P3", "low_box_step_off_landing", "level", "no box (level 0)"),
    V(19, "low-amplitude jump-and-stick", "P3", "low_box_step_off_landing", "level", "small jump"),
    V(19, "controlled lateral bound-and-stick", "P3", "low_box_step_off_landing", "level", "lateral bound"),
    V(19, "low-impact sled acceleration", "P2", "sled_push", "tempo", "short acceleration pushes"),
    V(19, "seated explosive med-ball press", "P3", "medicine_ball_chest_pass", "level", "seated (level 0)"),
    # §20 neck (optional specialist)
    A(20, "supine deep-neck-flexor nod", "supine_deep_neck_flexor_nod"),
    A(20, "gentle isometric flexion/extension/lateral flexion", "neck_isometric_holds"),
    V(20, "controlled rotation mobility", "P3", "neck_isometric_holds", "range", "slow active rotation"),
    # ── keep-list items ──
    C(13, "ab wheel", "P1", "ab_wheel", f"trunk_function anti_extension; {_RF}", kind="keep"),
    C(13, "Pallof", "P1", "cable_pallof_press", f"trunk_function anti_rotation; {_RF}", kind="keep"),
    C(13, "side plank", "P1", "side_plank", f"trunk_function anti_lateral_flexion; {_RF}", kind="keep"),
    C(13, "bird dog", "P2", "bird_dog", f"trunk_function anti_rotation (low-load control); {_RF}", kind="keep"),
    C(13, "cable crunch", "P1", "cable_crunch", f"trunk_function loaded_flexion; {_RF}", kind="keep"),
    C(13, "hanging knee raise", "P2", "hanging_knee_raise", f"trunk_function loaded_flexion (hip-flexor heavy); {_RF}", kind="keep"),
    C(16, "farmer's", "P1", "farmers_walk", "grip endurance + loaded locomotion", kind="keep"),
    C(16, "suitcase", "P1", "suitcase_carry", "anti-lateral flexion under load", kind="keep"),
    C(16, "overhead", "P2", "db_overhead_farmers_carry", "shoulder stability under load", kind="keep"),
    C(16, "sandbag", "P2", "sandbag_carry", "bear-hug / awkward-object carrying", kind="keep"),
    C(17, "walking", "P0", "walking", "the base aerobic modality", kind="keep"),
    C(17, "treadmill", "P1", "treadmill", "incline walking is the first progression", kind="keep"),
    C(17, "cycling", "P1", "cycling", kind="keep"),
    A(17, "recumbent", "recumbent_bike", "not in the library; a custom template already exists in the account", kind="keep"),
    C(17, "elliptical", "P1", "elliptical_trainer", kind="keep"),
    C(17, "rowing", "P2", "rowing_machine", kind="keep"),
    C(17, "air bike", "P2", "air_bike", kind="keep"),
    C(19, "jumps", "P3", "box_jump", "behind the charter's plyometric gate", kind="keep"),
    C(19, "pogos", "P3", "low_pogos", "behind the charter's plyometric gate", kind="keep"),
    C(19, "KB swings", "P2", "kettlebell_swing", "behind its kettlebell-deadlift chain", kind="keep"),
    C(19, "slams", "P3", "medicine_ball_slams", kind="keep"),
    C(19, "sprint drills", "P3", "sprints", "behind the charter's running gate", kind="keep"),
    C(19, "Olympic variations", "P3", "hang_power_clean", "behind the clean chain and owner confirmation", kind="keep"),
]
for _row_ in RECONCILIATION:
    _row_.setdefault("kind", "candidate")

# Data L4 (cardio model) reads: the protocols each EXISTING modality supports (the ADDs carry their own `cardio_protocols`).
CARDIO_PROTOCOLS_BY_MODALITY: dict[str, list[str]] = {
    "walking": ["easy_recovery_aerobic", "moderate_continuous", "progressive_endurance", "incline_resistance_progression"],
    "treadmill": list(CARDIO_PROTOCOLS),
    "cycling": list(CARDIO_PROTOCOLS),
    "elliptical_trainer": list(CARDIO_PROTOCOLS),
    "rowing_machine": _LOW_IMPACT_PROTOCOLS,
    "air_bike": _LOW_IMPACT_PROTOCOLS,
}

# Additions whose Hevy template does not exist: the owner approves creating each before it is prescribable.
OWNER_TEMPLATE_APPROVALS: list[str] = sorted(a["key"] for a in ADDITIONS if a["template_id"] is None)

# ── coverage: every muscle group and movement function × now / added / still open ─────────────────────────────────
# (area, function, existing library keys that serve it, keys added here, improvement still open)
COVERAGE: list[tuple[str, str, list[str], list[str], str]] = [
    (
        "chest",
        "horizontal press",
        ["bench_press_barbell", "bench_press_dumbbell", "chest_press_machine"],
        ["standing_cable_chest_press"],
        "Smith and converging-machine presses are variants",
    ),
    ("chest", "incline press", ["incline_bench_press_dumbbell", "incline_chest_press_machine"], [], "none"),
    (
        "chest",
        "chest adduction (fly)",
        ["butterfly_pec_deck", "cable_fly_crossovers", "chest_fly_dumbbell"],
        [],
        "6 near-duplicate crossovers at S (L1)",
    ),
    (
        "chest",
        "bodyweight pressing",
        ["push_up", "incline_push_up", "push_up_weighted"],
        [],
        "push-up levels are variants; weighted push-up typed bodyweight (L1)",
    ),
    (
        "back",
        "vertical pull (lat-biased)",
        ["lat_pulldown_cable", "pull_up", "chin_up", "pullover_machine"],
        [],
        "11 pulldown near-duplicates at S (L1)",
    ),
    (
        "back",
        "horizontal row (upper-back)",
        ["db_chest_supported_rows", "chest_supported_t_bar_row", "seated_row_machine"],
        [],
        "seal row / iso-lateral rows are variants",
    ),
    ("back", "scapular retraction control", ["dead_arm_scap_rows", "banded_retractions", "scap_pulldowns"], [], "none"),
    (
        "traps",
        "upper trap (elevation)",
        ["shrug_barbell", "shrug_dumbbell", "shrug_machine"],
        [],
        "all shrugs C/D on the hypertrophy rubric (L1)",
    ),
    ("traps", "lower/mid trap (upward rotation)", ["prone_w_raise"], ["chest_supported_y_raise_dumbbell"], "none"),
    (
        "shoulders",
        "front delt",
        ["landmine_press", "shoulder_press_dumbbell", "front_raise_dumbbell"],
        [],
        "scaption is a front-raise variant",
    ),
    (
        "shoulders",
        "side delt",
        ["lateral_raise_cable_single_arm", "lateral_raise_machine", "lateral_raise_dumbbell"],
        [],
        "DB lateral raise tier (L1)",
    ),
    (
        "shoulders",
        "rear delt",
        ["rear_delt_reverse_fly_machine", "face_pull", "rear_delt_reverse_fly_cable"],
        [],
        "1 S / 0 A, length labels inconsistent (L1)",
    ),
    (
        "shoulders",
        "rotator cuff ER",
        ["rotator_cuff_external_rotation", "db_external_rotation"],
        [],
        "ER rows mislabelled core_flexion / machine (L1)",
    ),
    ("shoulders", "rotator cuff IR", [], ["cable_internal_rotation"], "none"),
    ("shoulders", "serratus (protraction)", [], ["cable_serratus_punch"], "push-up plus is an incline push-up variant"),
    ("arms", "elbow flexion (biceps)", ["preacher_curl_dumbbell", "seated_incline_curl_dumbbell", "bicep_curl_machine"], [], "none"),
    ("arms", "brachialis / brachioradialis", ["hammer_curl_dumbbell", "reverse_curl_dumbbell", "cross_body_hammer_curls"], [], "none"),
    (
        "arms",
        "elbow extension (overhead / pushdown / press / dip)",
        ["overhead_triceps_extension_cable", "triceps_pushdown", "bench_press_close_grip_barbell", "triceps_dip_assisted"],
        [],
        "pushdown / pushaway near-duplicates (L1)",
    ),
    ("forearms", "wrist flexion", ["db_wrist_curl", "forearm_curl"], [], "none"),
    ("forearms", "wrist extension", [], ["wrist_extension_dumbbell"], "none"),
    ("forearms", "forearm rotation", [], ["forearm_rotation_dumbbell"], "none"),
    ("forearms", "wrist deviation", [], ["wrist_deviation_dumbbell"], "none"),
    ("forearms", "support grip / hang", ["dead_hang", "farmers_walk"], [], "none"),
    ("forearms", "pinch grip", [], ["plate_pinch_hold"], "none"),
    ("forearms", "crush grip", [], ["hand_gripper_squeeze"], "equipment unconfirmed"),
    ("forearms", "finger extension", [], ["band_finger_extension"], "none"),
    ("forearms", "grip endurance", ["farmers_walk"], ["wrist_roller"], "none"),
    ("quadriceps", "bilateral squat", ["squat_barbell", "hack_squat_machine", "leg_press_machine", "goblet_squat"], [], "none"),
    (
        "quadriceps",
        "unilateral squat / lunge",
        ["split_squat_dumbbell", "bulgarian_split_squat_dumbbell", "db_step_up"],
        [],
        "27 quad S inflated by DB lunge variants (L1)",
    ),
    (
        "quadriceps",
        "knee extension (open chain)",
        ["leg_extension_machine", "single_leg_extension"],
        ["sissy_squat", "band_assisted_reverse_nordic"],
        "none",
    ),
    ("quadriceps", "knee-dominant isometric", ["wall_sit"], ["spanish_squat"], "none"),
    ("quadriceps", "eccentric single-leg knee control", [], ["controlled_forward_step_down"], "none"),
    ("quadriceps", "sled (knee-dominant)", ["sled_push", "sled_drag"], [], "sled availability unknown"),
    ("hamstrings", "knee flexion", ["seated_leg_curl", "lying_leg_curl_machine", "nordic_hamstring_curl"], [], "none"),
    ("hamstrings", "hip extension (hinge)", ["romanian_deadlift_barbell", "romanian_deadlift_dumbbell", "back_extension_45"], [], "none"),
    (
        "glutes",
        "glute max (hip extension)",
        ["hip_thrust_machine", "hip_thrust_barbell", "glute_kickback_machine", "cable_kickback"],
        [],
        "no S glute by the glute stretch cap (L1)",
    ),
    ("glutes", "hip abduction (glute med/min)", ["banded_clam_shells"], ["hip_abduction_machine", "lateral_band_walks"], "none"),
    ("glutes", "hip rotation control", [], ["hip_airplane"], "none"),
    (
        "adductors",
        "hip adduction",
        ["db_adductor_slides"],
        ["hip_adduction_machine", "copenhagen_side_plank"],
        "adductor share of cossack / lateral lunge / squat unrated (L1)",
    ),
    ("calves", "gastrocnemius (straight knee)", ["standing_calf_raise_machine", "calf_press_machine"], [], "none"),
    ("calves", "soleus (bent knee)", ["seated_calf_raise"], [], "none"),
    ("lower leg", "tibialis (dorsiflexion)", [], ["tibialis_raise"], "none"),
    ("lower leg", "ankle inversion / eversion", [], ["banded_ankle_inversion_eversion"], "none"),
    ("lower leg", "balance / ankle control", ["single_leg_static_balance_with_eyes_closed"], [], "none"),
    ("foot", "intrinsic foot", [], ["short_foot"], "none"),
    (
        "trunk",
        "loaded flexion",
        ["cable_crunch", "machine_crunch", "hanging_knee_raise"],
        ["reverse_crunch"],
        "trunk_function not yet on existing rows (L1)",
    ),
    (
        "trunk",
        "anti-extension",
        ["ab_wheel", "plank", "dead_bug"],
        ["stability_ball_stir_the_pot", "mcgill_curl_up"],
        "ab wheel D on the hypertrophy rubric (L1)",
    ),
    (
        "trunk",
        "anti-rotation",
        ["cable_pallof_press", "pallof_press", "bird_dog"],
        ["bear_crawl"],
        "Pallof targets inconsistent: shoulders vs abs (L1)",
    ),
    ("trunk", "anti-lateral flexion", ["side_plank", "suitcase_carry"], ["suitcase_deadlift", "copenhagen_side_plank"], "none"),
    (
        "trunk",
        "dynamic rotation",
        ["cable_twist_up_to_down", "landmine_rotation", "torso_rotation"],
        [],
        "torso_rotation pattern core_flexion (L1)",
    ),
    ("trunk", "loaded stabilisation", ["farmers_walk", "suitcase_carry"], ["front_rack_carry_kettlebell"], "none"),
    ("trunk", "erector endurance", ["back_extension_45", "bird_dog", "superman"], [], "Sorensen hold is a back-extension variant"),
    (
        "hip flexors",
        "hip flexion",
        ["hanging_knee_raise", "long_leg_marches"],
        ["standing_cable_knee_drive"],
        "static_knee_drives filed under hamstrings (L1)",
    ),
    ("neck", "neck flexor control / isometrics", [], ["supine_deep_neck_flexor_nod", "neck_isometric_holds"], "optional specialist"),
    ("carries", "grip + loaded locomotion", ["farmers_walk", "sandbag_carry"], [], "farmers_walk duplicate scored C vs D (L1)"),
    ("carries", "overhead / shoulder stability", ["db_overhead_farmers_carry", "overhead_hold"], [], "none"),
    (
        "carries",
        "anterior (front-rack)",
        [],
        ["front_rack_carry_kettlebell"],
        "db_gun_carries may already be a front-rack DB carry (owner to confirm)",
    ),
    ("cardio", "walking / incline walking", ["walking", "treadmill"], [], "hill and trail are walking variants"),
    ("cardio", "cycling (upright / recumbent)", ["cycling"], ["recumbent_bike"], "none"),
    ("cardio", "elliptical", ["elliptical_trainer"], [], "none"),
    ("cardio", "rowing / ski", ["rowing_machine"], ["ski_erg"], "none"),
    ("cardio", "stair climbing", [], ["stair_machine"], "home_gym equipment unconfirmed"),
    ("cardio", "non-weight-bearing (pool)", [], ["swimming"], "pool not at home_gym"),
    ("cardio", "loaded walking", [], ["rucking"], "later phase"),
    ("cardio", "upper-body only", ["air_bike"], ["arm_ergometer"], "none"),
    ("cardio", "intervals (bike / sprint)", ["air_bike", "sprints"], [], "protocols are data on the modality (L4)"),
    ("mobility", "ankle dorsiflexion", [], ["knee_to_wall_dorsiflexion"], "none"),
    (
        "mobility",
        "hip (active / passive)",
        ["90_90_hip_stretch", "walking_hip_circles", "leg_swings", "long_leg_marches"],
        ["hip_cars", "adductor_rock_back", "half_kneeling_hip_flexor_stretch"],
        "none",
    ),
    ("mobility", "thoracic spine", ["t_spine_rotations", "thoracic_extension"], [], "none"),
    ("mobility", "shoulder / scapula", ["er_wall_slides", "angels_and_devils"], ["shoulder_cars"], "none"),
    ("mobility", "wrist", [], ["wrist_extension_mobilization"], "none"),
    ("mobility", "loaded mobility (deep squat)", ["bottomed_out_squat_reaches"], [], "deep-squat pry is a variant"),
    (
        "power",
        "lower-body jump / landing",
        ["box_jump", "low_pogos"],
        ["low_box_step_off_landing"],
        "readiness-gated; not auto-programmed now",
    ),
    ("power", "hip-extension power (no landing)", ["kettlebell_swing"], ["medicine_ball_scoop_toss"], "readiness-gated"),
    ("power", "upper-body power", ["medicine_ball_slams", "db_shot_put"], ["medicine_ball_chest_pass"], "readiness-gated"),
    ("power", "Olympic lifts", ["hang_power_clean", "power_clean"], [], "behind the clean chain"),
]

# ── quality audit (found while reconciling; this lane fixes only its own data) ─────────────────────────────────────
# (finding kind, library keys, what is wrong, owner)
QUALITY_FINDINGS: list[tuple[str, list[str], str, str]] = [
    (
        "misclassified_pattern",
        ["rotator_cuff_external_rotation", "external_rotation", "db_external_rotation", "torso_rotation"],
        "pattern core_flexion; should be shoulder external rotation / trunk rotation",
        "L1",
    ),
    (
        "invalid_equipment",
        ["rotator_cuff_external_rotation", "external_rotation"],
        "equipment machine_unspecified; cuff ER is a cable or band movement",
        "L1",
    ),
    ("misclassified_family", ["walking_lunge_dumbbell"], "family carry_conditioning from the 'walking' regex", "L1"),
    ("misclassified_pattern", ["crossover_stepup"], "pattern chest_fly ('crossover'), scored as a cable quad movement", "L1"),
    ("misclassified_target", ["static_knee_drives"], "a hip-flexion drill filed under hamstrings", "L1"),
    (
        "misclassified_target",
        ["db_cossack_squats", "db_alt_side_lunges", "side_lunge"],
        "adductor-heavy frontal-plane squats rated only for quadriceps; adductors unrated",
        "L1",
    ),
    (
        "misclassified_target",
        ["pallof_press", "cable_pallof_press", "pallof_press_cc55119b"],
        "same movement, two targets (shoulders vs abs)",
        "L1",
    ),
    (
        "misclassified_target",
        ["slick_floor_bridge_hammer_curls"],
        "a hamstring bridge curl whose custom title reads as an arm curl",
        "owner",
    ),
    ("invalid_equipment", ["bent_over_lateral_raise", "rear_delt_fly"], "dumbbell rear-delt moves typed bodyweight", "L1"),
    ("invalid_equipment", ["push_up_weighted"], "external load typed bodyweight", "L1"),
    ("invalid_equipment", ["sandbag_carry", "swing", "double_swings"], "equipment bodyweight for a sandbag / kettlebell movement", "L1"),
    ("near_duplicate", ["farmers_walk", "farmers_walk_8d414b80"], "same movement, tiers C vs D", "L1"),
    ("near_duplicate", ["triceps_pushdown", "tricep_pushdown"], "same movement, two templates", "L1"),
    ("near_duplicate", ["tricep_pushaway", "tricep_pushaways"], "same movement, two templates", "L1"),
    ("near_duplicate", ["glute_kickback_machine", "glute_machine_kickback"], "same movement, two templates", "L1"),
    ("near_duplicate", ["db_reverse_lunge", "reverse_lunge_dumbbell"], "same movement, two templates", "L1"),
    ("near_duplicate", ["db_power_incline_bombs", "db_incline_power_bombs"], "same movement, two templates", "L1"),
    ("near_duplicate", ["high_knee_flying_20s", "high_knee_flying_20s_2476151f"], "same movement, two templates", "L1"),
    (
        "near_duplicate",
        ["cross_body_hammer_curls"],
        "custom template duplicates Hevy's built-in Cross Body Hammer Curl (32C4D4A2)",
        "owner",
    ),
    ("near_duplicate", ["external_rotation", "rotator_cuff_external_rotation"], "two custom templates for one movement", "L1"),
    ("nonsensical_tier", ["pull_up_assisted", "chin_up_assisted"], "assisted machines S above the unassisted lift (B)", "L1"),
    ("nonsensical_tier", ["walking", "treadmill", "cycling", "elliptical_trainer"], "every cardio row D on the hypertrophy rubric", "L1"),
    (
        "nonsensical_tier",
        ["db_cossack_squats", "offset_lunges", "drop_step_lunges"],
        "unusual lunges S for quads above the barbell squat (A)",
        "L1",
    ),
    (
        "missing_progression_path",
        ["push_up"],
        "no recorded levels between incline push-up and weighted push-up (variants added here as metadata)",
        "L2 (this PR, as reconciliation variants)",
    ),
    (
        "missing_progression_path",
        ["nordic_hamstring_curl"],
        "no assisted-eccentric on-ramp level (variant added here as metadata)",
        "L2 (this PR, as reconciliation variants)",
    ),
    (
        "missing_progression_path",
        ["db_adductor_slides"],
        "the only adductor movement had no progression line (the Copenhagen levels added here)",
        "L2",
    ),
    (
        "missing_movement",
        ["sled_drag"],
        "the audit's 'no Sled Pull' is stale: sled_drag already logs under Hevy's Sled Pull (7D1BD41D)",
        "none",
    ),
    (
        "misclassified_pattern",
        ["band_assisted_reverse_nordic", "cable_internal_rotation", "mcgill_curl_up", "lateral_band_walks"],
        "the title-regex pattern table reads 'reverse nordic' as leg_curl, 'internal rotation' as core_flexion, 'curl-up' as curl and 'band walks' as cardio; exercise_library.movement_pattern needs those phrases",
        "L1",
    ),
    (
        "ambiguous_title",
        ["db_gun_carries", "hip_band_ladder", "underhand_barbell_wiring_out"],
        "custom titles whose movement cannot be read from the name",
        "owner",
    ),
]


# ── checks (the build fails on a duplicate; the tests hold the rest) ─────────────────────────────────────────────


def norm_title(title: str) -> str:
    """Case-, punctuation- and spacing-insensitive title key ('Hip Abduction (Machine)' == 'hip abduction machine')."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(title).lower()).split())


def _existing_titles_and_ids(library: dict[str, Any] | None, catalog: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, str]]:
    """Normalized title -> key and TEMPLATE ID -> key for every movement this module does NOT own (its own rows in a
    previously built library are excluded by `expansion_origin`), plus every catalog movement and curated candidate."""
    titles: dict[str, str] = {}
    ids: dict[str, str] = {}
    for k, e in ((library or {}).get("movements") or {}).items():
        if str(e.get("expansion_origin") or "").startswith(ORIGIN):
            continue
        titles.setdefault(norm_title(e.get("title") or ""), k)
        if e.get("template_id"):
            ids.setdefault(str(e["template_id"]).upper(), k)
    for k, v in ((catalog or {}).get("movements") or {}).items():
        titles.setdefault(norm_title(v.get("title") or ""), f"catalog:{k}")
        if v.get("hevy_template_id_hint"):
            ids.setdefault(str(v["hevy_template_id_hint"]).upper(), f"catalog:{k}")
    return titles, ids


def duplicate_problems(additions: list[dict[str, Any]], library: dict[str, Any] | None, catalog: dict[str, Any] | None) -> list[str]:
    """Every way an ADD duplicates something already in the library, the catalog or another ADD: its title or any alias
    matches an existing title (case-insensitive), its Hevy template is already a movement's, or two ADDs collide."""
    titles, ids = _existing_titles_and_ids(library, catalog)
    out: list[str] = []
    seen_names: dict[str, str] = {}
    for a in additions:
        if a["key"] in ((library or {}).get("movements") or {}) and not str(
            (library or {})["movements"][a["key"]].get("expansion_origin") or ""
        ).startswith(ORIGIN):
            out.append(f"{a['key']}: key already a library movement")
        for name in [a["title"], *a["expansion_profile"]["aliases"]]:
            n = norm_title(name)
            if n in titles:
                out.append(f"{a['key']}: {name!r} duplicates existing {titles[n]}")
            if n in seen_names and seen_names[n] != a["key"]:
                out.append(f"{a['key']}: {name!r} duplicates addition {seen_names[n]}")
            seen_names.setdefault(n, a["key"])
        tid = str(a.get("template_id") or "").upper()
        if tid and tid in ids:
            out.append(f"{a['key']}: Hevy template {a['template_id']} is already {ids[tid]}")
    return out


def _get(entry: dict[str, Any], path: str) -> Any:
    cur: Any = entry
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def metadata_problems(additions: list[dict[str, Any]]) -> list[str]:
    """Every ADD carries all 20 amendment fields with values from the declared vocabularies."""
    out: list[str] = []
    for a in additions:
        k, p = a["key"], a["expansion_profile"]
        for name, path in PROFILE_FIELDS.items():
            v = _get(a, path)
            if v is None or v == "" or (isinstance(v, (list, dict)) and not v and name not in ("aliases", "secondary targets")):
                out.append(f"{k}: missing {name} ({path})")
        lv = p["levels"]
        if not (lv["regressions"] or lv["progressions"]):
            out.append(f"{k}: no regression or progression path")
        checks = (
            (a.get("category"), CATEGORIES, "category"),
            (p.get("priority"), PRIORITIES, "priority"),
            (p.get("phase_suitability"), PHASE_SUITABILITY, "phase_suitability"),
            (_get(a, "expansion_profile.programming.mode"), PROGRAMMING, "programming"),
            (_get(a, "expansion_profile.influence.verdict"), INFLUENCE, "influence"),
            (p.get("laterality"), LATERALITY, "laterality"),
            (p.get("stability_demand"), LEVELS, "stability_demand"),
            (_get(a, "expansion_profile.fatigue.local"), LEVELS, "fatigue.local"),
            (_get(a, "expansion_profile.fatigue.systemic"), LEVELS, "fatigue.systemic"),
        )
        out += [f"{k}: {what} {v!r} not in {vocab}" for v, vocab, what in checks if v not in vocab]
        out += [f"{k}: objective {o!r}" for o in p["objectives"] if o not in OBJECTIVES]
        out += [f"{k}: fit factor {f!r}" for f in p["personal_fit"] if f not in FIT_FACTORS]
        gr = p["programming"]["gate_reason"]
        if (p["programming"]["mode"] == "readiness_gated") != (gr in READINESS_CONDITIONS):
            out.append(f"{k}: a readiness-gated movement names a gate reason (and only it does)")
        if a.get("trunk_function") is not None and a["trunk_function"] not in TRUNK_FUNCTIONS:
            out.append(f"{k}: trunk_function {a['trunk_function']!r}")
        if set(p["ratings_proposed"]) != set(OBJECTIVES) or all(r["tier"] is None for r in p["ratings_proposed"].values()):
            out.append(f"{k}: ratings_proposed must rate every objective (None = not applicable) and at least one")
        if any(x not in CARDIO_PROTOCOLS for x in a.get("cardio_protocols") or []):
            out.append(f"{k}: unknown cardio protocol")
        h = p["hevy"]
        if h["prescribable"] != (a["template_id"] is not None) or h["needs_custom_template"] == h["prescribable"]:
            out.append(f"{k}: a movement with no Hevy template is never prescribable")
        if p["influence"]["verdict"] == "influences_current_program" and (
            p["priority"] not in ("P0", "P1") or p["phase_suitability"] != "now"
        ):
            out.append(f"{k}: only a P0/P1 movement suitable now may influence the current program")
    return out


def reconciliation_problems(rows: list[dict[str, Any]], additions: list[dict[str, Any]], library_keys: set[str]) -> list[str]:
    """Candidates in == rows out (each amendment candidate and keep item exactly once), every row's outcome and priority
    is from the vocabulary, every ref resolves, every ADD row names an addition and every addition is some row's ADD."""
    out: list[str] = []
    add_keys = {a["key"] for a in additions}
    want = Counter((s, c, "candidate") for s, cs in AMENDMENT_15_CANDIDATES.items() for c in cs)
    want += Counter((s, c, "keep") for s, cs in AMENDMENT_15_KEEP.items() for c in cs)
    have = Counter((r["section"], r["candidate"], r["kind"]) for r in rows)
    if have != want:
        out.append(f"rows != candidates: missing {sorted((want - have).elements())}, extra {sorted((have - want).elements())}")
    for r in rows:
        tag = f"§{r['section']} {r['candidate']!r}"
        if r["outcome"] not in OUTCOMES or r["priority"] not in PRIORITIES:
            out.append(f"{tag}: outcome/priority {r['outcome']}/{r['priority']}")
        if r["outcome"] == "ADD" and r["ref"] not in add_keys:
            out.append(f"{tag}: ADD names no addition")
        if r["outcome"] in ("VARIANT", "ALREADY_COVERED") and r["ref"] not in library_keys | add_keys:
            out.append(f"{tag}: {r['ref']!r} is not a library movement")
        if r["outcome"] == "VARIANT" and r["variant"]["axis"] not in VARIANT_AXES:
            out.append(f"{tag}: variant axis {r['variant']['axis']!r}")
        if r["outcome"] == "DEFER" and not r["note"]:
            out.append(f"{tag}: a DEFER states why")
    unrowed = add_keys - {r["ref"] for r in rows if r["outcome"] == "ADD"}
    if unrowed:
        out.append(f"additions with no reconciliation row: {sorted(unrowed)}")
    return out


def _load(path: str) -> dict[str, Any] | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def checked_additions() -> list[dict[str, Any]]:
    """ADDITIONS after the duplicate check against the committed library + catalog (a duplicate stops the build)."""
    dup = duplicate_problems(ADDITIONS, _load(LIBRARY_PATH), _load(CATALOG_PATH))
    if dup:
        raise SystemExit("library additions duplicate existing movements:\n  " + "\n  ".join(dup))
    return ADDITIONS


# ── the public coverage doc (generated from this module) ────────────────────────────────────────────────────────


def _md_keys(keys: list[str]) -> str:
    return ", ".join(f"`{k}`" for k in keys) if keys else "—"


def _summary_lines() -> list[str]:
    cand = [r for r in RECONCILIATION if r["kind"] == "candidate"]
    by_outcome = Counter(r["outcome"] for r in cand)
    by_pri = Counter((r["outcome"], r["priority"]) for r in cand)
    lines = [
        f"**{len(cand)} candidates** (Amendment 15 §1-§20) + **{len(RECONCILIATION) - len(cand)} keep-list items**, "
        f"one outcome each. **{len(ADDITIONS)} new canonical movements** in the library.",
        "",
        "| Outcome | Candidates | P0 | P1 | P2 | P3 |",
        "|---|---|---|---|---|---|",
    ]
    for o in OUTCOMES:
        lines.append(f"| {o} | {by_outcome.get(o, 0)} | " + " | ".join(str(by_pri.get((o, p), 0)) for p in PRIORITIES) + " |")
    return lines


def render_doc() -> str:
    """docs/coaching/EXERCISE_LIBRARY_COVERAGE.md, from the data above — never hand-edited."""
    adds = {a["key"]: a for a in ADDITIONS}
    out = [
        "# Exercise library coverage and the Amendment 15 reconciliation",
        "",
        "<!-- GENERATED by deploy/exercise_library_additions.py --write-doc — do not hand-edit (epic #5861, lane L2). -->",
        "",
        "Comprehensive library, selective engine: this page lists what the library covers, what lane L2 added, and the "
        "outcome for every candidate. A movement in the library is **available**, not prescribed: the selection engine "
        "picks 4-8 per session, and only while the library is approved.",
        "",
        "**ADD vs VARIANT rule.** A candidate becomes an ADD only when it serves a muscle or movement function nothing "
        "in the library serves (or serves only with something that cannot be loaded or progressed). A grip, stance, "
        "range, tempo, laterality, plane or equipment change of a served function is a VARIANT of that canonical, even "
        "when Hevy has its own template for it; regressions and progressions are VARIANT levels. IDs and history are "
        "never touched.",
        "",
        "**Prescribable.** An ADD with a Hevy template (built-in, or a custom template already in the account) can be "
        "logged; one without needs a custom template the owner approves first. Either way the selection engine also "
        "needs a movement-catalog entry before it can write the movement.",
        "",
        "**Evidence.** No citation is invented: every rating below is a categorical, practitioner-consensus judgement "
        "with its basis stated (`evidence_confidence: none_reviewed`).",
        "",
        "## Summary",
        "",
        *_summary_lines(),
        "",
        "## Coverage matrix",
        "",
        "| Area | Function | Covered now by | Added (L2) | Still open / improvement |",
        "|---|---|---|---|---|",
    ]
    out += [f"| {a} | {f} | {_md_keys(n)} | {_md_keys(d)} | {o} |" for a, f, n, d, o in COVERAGE]
    out += [
        "",
        "## New canonical movements",
        "",
        "| Key | Title | § | Priority | Category | Function | Hevy template | Phase | Programming | Influence (why) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k, a in adds.items():
        p = a["expansion_profile"]
        h = p["hevy"]
        tmpl = f"`{h['template']}` ({h['kind']})" if h["template"] else "none: custom template needed"
        prog = p["programming"]["mode"] + (f" ({p['programming']['gate_reason']})" if p["programming"]["gate_reason"] else "")
        out.append(
            f"| `{k}` | {a['title']} | {p['section'].lstrip('§')} | {p['priority']} | {a['category']} | {p['movement_function']} | {tmpl} | "
            f"{p['phase_suitability']} | {prog} | {p['influence']['verdict']}: {p['influence']['why']} |"
        )
    out += ["", "## Owner approval list: custom Hevy templates needed", ""]
    out += [f"- `{k}` — {adds[k]['title']} ({adds[k]['expansion_profile']['priority']})" for k in OWNER_TEMPLATE_APPROVALS]
    out += [
        "",
        "## Candidate reconciliation",
        "",
        "| § | Candidate | Kind | Outcome | Priority | Ref | Variant / note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in RECONCILIATION:
        v = r.get("variant")
        detail = f"{v['axis']}: {v['value']}" + (f" (Hevy `{v['hevy_template']}`)" if v["hevy_template"] else "") if v else ""
        detail = "; ".join(x for x in (detail, r["note"]) if x)
        out.append(
            f"| {r['section']} | {r['candidate']} | {r['kind']} | {r['outcome']} | {r['priority']} | {_md_keys([r['ref']] if r['ref'] else [])} | {detail} |"
        )
    out += ["", "## Cardio protocols by existing modality (data for the cardio model)", ""]
    out += [f"- `{k}`: {', '.join(v)}" for k, v in CARDIO_PROTOCOLS_BY_MODALITY.items()]
    out += ["", "## Quality audit findings", "", "| Kind | Movements | Finding | Owner |", "|---|---|---|---|"]
    out += [f"| {kind} | {_md_keys(keys)} | {what} | {owner} |" for kind, keys, what, owner in QUALITY_FINDINGS]
    return "\n".join(out) + "\n"


# The builder hook imports this module and reads ADDITIONS, so the duplicate check runs at that import: a duplicate
# stops the build before any entry is merged.
checked_additions()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-doc", action="store_true")
    ap.add_argument("--check-doc", action="store_true")
    args = ap.parse_args(argv)
    lib = _load(LIBRARY_PATH) or {}
    problems = metadata_problems(ADDITIONS) + reconciliation_problems(RECONCILIATION, ADDITIONS, set(lib.get("movements") or {}))
    problems += duplicate_problems(ADDITIONS, lib, _load(CATALOG_PATH))
    for p in problems:
        print(p)
    doc = render_doc()
    if args.write_doc:
        with open(DOC_PATH, "w", encoding="utf-8") as f:
            f.write(doc)
        print(f"wrote {os.path.relpath(DOC_PATH, REPO_ROOT)}")
    if args.check_doc:
        with open(DOC_PATH, encoding="utf-8") as f:
            if f.read() != doc:
                print("docs/coaching/EXERCISE_LIBRARY_COVERAGE.md drifted: run --write-doc")
                return 1
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
