"""quality_rubric.py — the exercise library's QUALITY tier, S to D, derived by a written rubric (#5857).

WHY. The library's first tiers (A/B/C, #5769) graded EVIDENCE DIRECTNESS, not exercise quality: A was a direct trial of
this exact movement, B a trial of a close one, C `none_reviewed` — 561 of 582 ratings were C, and the top band of most
muscles had one member or none. Owner, 2026-11-12: "if we are saying there is only one S tier tricep exercise in the
world, that sounds slightly off … there may be a best of the best, but there may be some in that same territory to justify
S-tier." So the tier is now a QUALITY band from the attributes the library already records, and evidence strength is its
own field (`evidence_confidence`), shown beside the tier.

THE RUBRIC v2 (version `RUBRIC_VERSION`; owner ruling 2026-11-12, all eight board recommendations adopted). A movement is
scored against the JOB it does: its `job` (compound | isolation, the builder's rule by movement pattern, never by muscle
name) picks the terms. Per (movement, target muscle), the sum of:

    term                 field                 isolation                              compound (multi-joint pattern)
    stretch              `length_bias`         lengthened 5 · mid 3 · short 1         the same (glutes capped at mid:
                                                                                       `STRETCH_CAPS`, no stretch premium)
    stability            `stability`           high 3 · moderate 2 · low 1            high 2 · moderate 2 · low 1
    resistance profile   `resistance_profile`  fit to the target's curve (0-3,        free weight / any machine / cable 3 ·
                                               `PROFILE_FIT`)                         band / bodyweight / sled 1
    progressability      `skill_complexity`    low 2 · moderate 1 · high 0, +1 for small external load steps (both)
    carryover            `resistance_profile`  —                                      +1 for a free-weight compound
    joint stress         `joint_stress`        -2 per joint rated high, -1 once for any moderate OR unknown; total >= -2

maximum 14 for both jobs. Bands (`BANDS`): S >= 12 · A >= 10 · B >= 8 · C >= 5 · D below. Bands, not a single winner.

EVIDENCE. `evidence_confidence` is rct_direct | rct_characteristic | consensus | none_reviewed. Only a DIRECT trial
(`rct_direct`) may move a row, and only ONE band from its rubric tier (`EVIDENCE_MAX_BANDS`), recorded on the row as
`evidence_adjustment: {bands: +1 | -1, citation, why, basis?, comparator?}`: +1 when the trial found this movement grew the
target MORE than a compared movement or range, -1 when LESS, and +1 for EQUIVALENCE (`basis: equivalence`) when the
comparator it matched sits in a higher tier for the same target (`comparator`, checked library-wide by
`exercise_library.validate`). A move past S or D is capped there. Body mass, heart history and enjoyment are never a term:
they live in gates, cues, N=1 fit and selection.

An `unknown` attribute never helps: a positive term scores 0 and an unknown joint counts as moderate.

Pure: no I/O, no clock. The builder (`deploy/build_exercise_library.py`) writes `rubric_score`, `rubric_tier` and `tier`
from these functions; `exercise_library.validate` and `tests/test_quality_tiers_5857.py` re-derive every row from them, so
a hand-edited tier is a schema error.
"""

from __future__ import annotations

from typing import Any

from training import cardio_model

RUBRIC_VERSION = "3.0.0"  # 3.0.0: #5861 per-objective rubrics + hypertrophy caps (PROPOSED); 2.0.0: owner ruling 2026-11-12
QUALITY_TIERS = ("S", "A", "B", "C", "D")
EVIDENCE_CONFIDENCE = ("rct_direct", "rct_characteristic", "consensus", "none_reviewed")
EVIDENCE_ADJUSTERS = ("rct_direct",)  # the only confidence that may move a row off its rubric tier
EVIDENCE_MAX_BANDS = 1
PROVENANCE = "owner ruling 2026-11-12 on #5857: rubric v2, all eight board recommendations adopted"

STRETCH = {"lengthened": 5, "mid": 3, "shortened": 1}
STABILITY = {"high": 3, "moderate": 2, "low": 1}
SKILL = {"low": 2, "moderate": 1, "high": 0}
LOAD_STEPS = ("free_weight", "cable", "machine_selectorized", "machine_plate_loaded")

# The target muscle's strength-curve class. ISOLATION: a single-joint upper-body muscle whose resistance should stay high
# into the lengthened range (a cable or selectorized machine does; a dumbbell's torque falls off at one end). LOADED: the
# lower body, the back and the presses, where a free weight or a machine both load the working range.
ISOLATION_MUSCLES = ("chest", "shoulders", "side_delts", "rear_delts", "front_delts", "biceps", "triceps", "forearms")
# The three delt heads (#5857 target audit) sit in the class `shoulders` held: a vocabulary split, not a weight change.
PROFILE_FIT: dict[str, dict[str, int]] = {
    "isolation": {"cable": 3, "machine_selectorized": 3, "machine_plate_loaded": 2, "free_weight": 2, "band": 1, "bodyweight": 1},
    "loaded": {
        "free_weight": 3,
        "machine_plate_loaded": 3,
        "machine_selectorized": 3,
        "cable": 2,
        "band": 1,
        "bodyweight": 1,
        "sled": 1,
    },
}
JOINT_HIGH = -2
JOINT_MODERATE = -1  # once, for any moderate OR unknown joint (missing data never helps)
JOINT_FLOOR = -2  # the joint-stress penalty never exceeds this in total
JOBS = ("compound", "isolation")
COMPOUND_STABILITY = {"high": 2, "moderate": 2, "low": 1}  # stabiliser demand is part of a compound's job, not a defect
COMPOUND_PROFILE = {
    "free_weight": 3,
    "machine_plate_loaded": 3,
    "machine_selectorized": 3,
    "cable": 3,
    "band": 1,
    "bodyweight": 2,  # 3.0.0 (#5861): body mass loads a compound's working range; its weak point is progression, scored there
    "sled": 1,
}
FREE_WEIGHT_CARRYOVER = 1  # a free-weight compound's carryover; the ONLY term where equipment class differs by design
# target -> (the length_bias the stretch term is FIXED at, the citation, why). Owner ruling 2026-11-12 (board rec 6) capped
# it; 3.0.0 (#5861) fixes it both ways: the trial that removed the stretch premium (the shortened hip thrust matched the
# lengthened squat) equally removes the shortened penalty, so any KNOWN glute length scores mid (unknown still scores 0).
STRETCH_CAPS: dict[str, tuple[str, str, str]] = {
    "glutes": (
        "mid",
        "plotkin2023_hip_thrust_vs_squat",
        "no stretch premium and no shortened penalty for the glutes: the hip thrust (shortened) matched the back squat "
        "(lengthened) for glute growth",
    ),
}
BANDS: tuple[tuple[int, str], ...] = ((12, "S"), (10, "A"), (8, "B"), (5, "C"))

# A major muscle whose PROGRAMMABLE pool (S and A, owner ruling 2026-11-12) holds fewer than two selectable movements, and
# why (#5857 acceptance: "at least 2 in the top band where the attributes support it, or the slot names why not").
# `tests/test_quality_tiers_5857.py` holds the list to the shipped library both ways: a short muscle missing here is red,
# and so is a stale entry.
TOP_BAND_SHORTFALL: dict[str, str] = {}
# #5861 resolved both former entries through the framework, not by hand: abs — the ab-wheel rollout is recorded as the
# lengthened, laddered anti-extension movement it is (A beside the cable crunch); rear delts — the cable reverse fly's
# length is reviewed as mid (tension from the crossed start), so it sits at A beside the machine's S.
MAX_SCORE = max(STRETCH.values()) + max(STABILITY.values()) + 3 + max(SKILL.values()) + 1  # isolation
MAX_SCORE_COMPOUND = max(STRETCH.values()) + max(COMPOUND_STABILITY.values()) + 3 + max(SKILL.values()) + 1 + FREE_WEIGHT_CARRYOVER


def curve_class(target: str) -> str:
    """The target muscle's strength-curve class (a sub-target counts: `triceps_long_head` is triceps)."""
    t = str(target or "").lower()
    return "isolation" if any(t == m or t.startswith(m) for m in ISOLATION_MUSCLES) else "loaded"


def job(entry: dict[str, Any]) -> str:
    """The movement's job, as the builder recorded it (`job`: compound | isolation); absent reads as isolation."""
    return "compound" if entry.get("job") == "compound" else "isolation"


def _stretch(entry: dict[str, Any], target: str) -> int:
    points = STRETCH.get(str(entry.get("length_bias")), 0)
    cap = next((c for m, c in STRETCH_CAPS.items() if str(target or "").lower().startswith(m)), None)
    return STRETCH[cap[0]] if cap and points else points


def _ladder(entry: dict[str, Any]) -> bool:
    """A calisthenics progression ladder (assisted -> bodyweight -> weighted, kneeling -> standing): the load-step bonus."""
    return bool((entry.get("objective_inputs") or {}).get("ladder"))


def joint_penalty(entry: dict[str, Any]) -> int:
    js = [str(v) for v in (entry.get("joint_stress") or {}).values()] or ["unknown"]
    raw = JOINT_HIGH * js.count("high") + (JOINT_MODERATE if ("moderate" in js or "unknown" in js) else 0)
    return max(raw, JOINT_FLOOR)


def components(entry: dict[str, Any], target: str) -> dict[str, int]:
    """Each rubric term for one (movement, target), as points — the job's terms (module docstring)."""
    profile = str(entry.get("resistance_profile") or "unknown")
    compound = job(entry) == "compound"
    stability = (COMPOUND_STABILITY if compound else STABILITY).get(str(entry.get("stability")), 0)
    fit = COMPOUND_PROFILE.get(profile, 0) if compound else PROFILE_FIT[curve_class(target)].get(profile, 0)
    return {
        "stretch": _stretch(entry, target),
        "stability": stability,
        "resistance_profile": fit,
        "progressability": SKILL.get(str(entry.get("skill_complexity")), 0) + (1 if profile in LOAD_STEPS or _ladder(entry) else 0),
        "carryover": FREE_WEIGHT_CARRYOVER if compound and profile == "free_weight" else 0,
        "joint_stress": joint_penalty(entry),
    }


def score(entry: dict[str, Any], target: str) -> int:
    return sum(components(entry, target).values())


def band(points: int) -> str:
    return next((tier for floor, tier in BANDS if points >= floor), "D")


def rubric_tier(entry: dict[str, Any], target: str) -> str:
    return band(score(entry, target))


def shift(tier: str, bands: int) -> str:
    """`tier` moved `bands` toward S (positive) or D (negative), capped at both ends."""
    i = QUALITY_TIERS.index(tier) - int(bands)
    return QUALITY_TIERS[max(0, min(len(QUALITY_TIERS) - 1, i))]


def adjustment_problems(row: dict[str, Any]) -> list[str]:
    """Why a row's recorded evidence adjustment is not allowed (empty when it is, or when there is none)."""
    adj = row.get("evidence_adjustment")
    if adj is None:
        return []
    out = []
    if not isinstance(adj, dict) or adj.get("bands") not in (-EVIDENCE_MAX_BANDS, EVIDENCE_MAX_BANDS):
        return [f"evidence_adjustment.bands must be +/-{EVIDENCE_MAX_BANDS}"]
    if adj.get("basis") == "equivalence" and (adj.get("bands") != EVIDENCE_MAX_BANDS or not adj.get("comparator")):
        out.append("an equivalence adjustment is +1 and names its higher-tier comparator")
    if row.get("evidence_confidence") not in EVIDENCE_ADJUSTERS:
        out.append(f"only a {'/'.join(EVIDENCE_ADJUSTERS)} row may move off its rubric tier")
    if not adj.get("citation") or adj.get("citation") not in (row.get("citations") or []):
        out.append("evidence_adjustment.citation must be one of the row's citations")
    if not adj.get("why"):
        out.append("evidence_adjustment.why is required")
    return out


# ── #5861: hypertrophy is ONE objective; its points are a stimulus profile, capped by categorical criteria ─────────────
# The 14-point sum above is kept as the hypertrophy STIMULUS profile (what the attributes say about loading the target).
# It is not, alone, a quality verdict: three things it cannot see cap the band (`hypertrophy_caps`), and S additionally needs
# every categorical S criterion (`s_criteria`) — no quota, but no S on points alone.
OBJECTIVES = ("hypertrophy", "strength", "functional", "conditioning", "mobility")
CATEGORIES = ("hypertrophy", "strength", "conditioning", "athletic", "mobility", "rehab_control", "carry")
TRUNK_FUNCTIONS = ("loaded_flexion", "anti_extension", "anti_rotation", "anti_lateral_flexion", "rotation", "loaded_stabilisation")
FUNCTIONS = ("hip_flexion", "grip", "wrist_flexion", "wrist_extension", "forearm_rotation")
LEVELS = ("low", "moderate", "high")
LIMITERS = ("target", "balance", "grip", "mobility", "trunk", "other_muscle", "technique", "cardio")
OVERLOAD = ("maximal", "submaximal", "bodyweight", "light")
FUNCTIONAL_QUALITIES = ("unilateral", "balance", "carry", "locomotion", "trunk_stability", "multiplanar", "power")
MOBILITY_TYPES = ("passive", "active", "loaded", "motor_control")
CONDITIONING_KEYS = ("aerobic", "control", "impact", "recovery")
# Each movement's `objective_inputs` (the builder derives them by rule; the reviewed layer overrides): field -> allowed values.
OBJECTIVE_INPUTS: dict[str, tuple[Any, ...]] = {
    "ceiling": LEVELS + ("unknown",),  # can the TARGET be overloaded progressively, in small steps, to failure
    "limiter": LIMITERS,  # what ends the set for the primary target (a secondary row carries its own `limiter`)
    "systemic_fatigue": LEVELS,  # whole-body cost per hard set — the stimulus-to-fatigue side
    "resistance_class": OVERLOAD,  # absolute loading class, for strength
    "strength_lift": (True, False),  # one of the primary strength lifts (squat, hinge, bench, overhead press, row, weighted pull)
    "ladder": (True, False),  # a calisthenics progression ladder: the load-step bonus for a bodyweight movement
    "functional": FUNCTIONAL_QUALITIES,  # a list
    "conditioning": CONDITIONING_KEYS,  # a {key: level} map, or None
    "mobility": MOBILITY_TYPES + (None,),
    "reviewed": (True, False),  # the inputs were checked by hand (#5861 pass), not only derived by title rule
}
NOT_HYPERTROPHY_CATEGORIES = ("conditioning", "mobility", "rehab_control", "carry", "athletic")
NOT_HYPERTROPHY_TARGETS = ("full_body", "cardio", "other", "unknown")
ISOMETRIC_TRUNK = ("anti_rotation", "anti_lateral_flexion", "loaded_stabilisation")
STRENGTH_PATTERNS = ("squat", "hinge", "horizontal_press", "vertical_press", "press", "vertical_pull", "horizontal_pull", "carry")
S_CRITERIA = {
    "ceiling_high": "the target can be overloaded progressively to a high ceiling",
    "target_is_limiter": "the target muscle, not balance, grip, mobility or another muscle, ends the set",
    "stable_to_failure": "stable enough (stability high or moderate) to take the target close to failure",
    "stimulus_to_fatigue": "systemic fatigue is not high for the stimulus",
    "no_high_joint_stress": "no joint is rated high",
}


def _inputs(entry: dict[str, Any]) -> dict[str, Any]:
    return entry.get("objective_inputs") or {}


def _row_limiter(entry: dict[str, Any], row: dict[str, Any]) -> str:
    """The limiter for this row: a secondary row carries its own; the primary reads the movement's (unknown never helps)."""
    return str(row.get("limiter") or _inputs(entry).get("limiter") or "unknown")


def hypertrophy_not_applicable(entry: dict[str, Any], target: str) -> str | None:
    """Why the hypertrophy objective does not apply to this (movement, target) — None when it does. Never forced."""
    cat = entry.get("category")
    if cat in NOT_HYPERTROPHY_CATEGORIES:
        return f"not applicable: category {cat} is rated on its own objective, never on muscle growth"
    if str(target or "unknown") in NOT_HYPERTROPHY_TARGETS:
        return f"not applicable: target {target or 'unknown'} names no single muscle to grow"
    if entry.get("trunk_function") in ISOMETRIC_TRUNK:
        return f"not applicable: {entry.get('trunk_function')} is trunk control, rated on functional"
    return None


def s_criteria(entry: dict[str, Any], row: dict[str, Any]) -> dict[str, bool]:
    """The categorical S criteria (`S_CRITERIA`) for one row: every one must hold for S."""
    inp = _inputs(entry)
    return {
        "ceiling_high": inp.get("ceiling") == "high",
        "target_is_limiter": _row_limiter(entry, row) == "target",
        "stable_to_failure": entry.get("stability") in ("high", "moderate"),
        "stimulus_to_fatigue": inp.get("systemic_fatigue") in ("low", "moderate"),
        "no_high_joint_stress": "high" not in [str(v) for v in (entry.get("joint_stress") or {}).values()],
    }


def hypertrophy_caps(entry: dict[str, Any], row: dict[str, Any]) -> list[tuple[str, str]]:
    """(tier, why) caps below the points band: a low/unknown load ceiling or a limiter that is not the target -> B at best;
    an unmet S criterion -> A at best."""
    caps = []
    ceiling = str(_inputs(entry).get("ceiling") or "unknown")
    if ceiling in ("low", "unknown"):
        caps.append(("B", f"load ceiling {ceiling}: the target cannot be overloaded progressively"))
    limiter = _row_limiter(entry, row)
    if limiter != "target":
        caps.append(("B", f"limiter {limiter}: the target muscle is not what ends the set"))
    unmet = [k for k, ok in s_criteria(entry, row).items() if not ok]
    if unmet:
        caps.append(("A", "S needs " + ", ".join(unmet)))
    return caps


def _worst(*tiers: str) -> str:
    return max(tiers, key=QUALITY_TIERS.index)


def capped_tier(entry: dict[str, Any], row: dict[str, Any]) -> str:
    """The rubric tier: the points band, held under every categorical cap."""
    target = str(row.get("target") or "")
    return _worst(band(score(entry, target)), *[t for t, _ in hypertrophy_caps(entry, row)])


def quality_tier(entry: dict[str, Any], row: dict[str, Any]) -> str | None:
    """The row's tier: its capped rubric tier moved by its recorded evidence adjustment (one band at most) — and never to
    S unless every S criterion holds. None when hypertrophy does not apply."""
    if hypertrophy_not_applicable(entry, str(row.get("target") or "")):
        return None
    base = capped_tier(entry, row)
    adj = row.get("evidence_adjustment")
    moved = shift(base, int(adj["bands"])) if isinstance(adj, dict) and not adjustment_problems(row) else base
    return "A" if moved == "S" and not all(s_criteria(entry, row).values()) else moved


def _hyp_basis(entry: dict[str, Any], row: dict[str, Any]) -> list[str]:
    target = str(row.get("target") or "")
    c = components(entry, target)
    out = [f"points {sum(c.values())}/{MAX_SCORE} -> {band(sum(c.values()))}: " + ", ".join(f"{k} {v}" for k, v in c.items())]
    out += [f"cap {t}: {why}" for t, why in hypertrophy_caps(entry, row)]
    adj = row.get("evidence_adjustment")
    out.append(
        f"evidence {row.get('evidence_confidence') or 'none_reviewed'}" + (f", {adj['bands']:+d} band" if isinstance(adj, dict) else "")
    )
    return out


def finalize_row(entry: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """The row with its derived fields written: `tier`, `rubric_tier`, `rubric_score`, `points_tier`, `basis` (and
    `applicable: false` with every tier field None when hypertrophy does not apply). The evidence fields are kept."""
    target = str(row.get("target") or "")
    na = hypertrophy_not_applicable(entry, target)
    if na:
        out: dict[str, Any] = {"target": target, "tier": None, "rubric_tier": None, "rubric_score": None, "points_tier": None}
        out |= {"applicable": False, "basis": [na]}
    else:
        out = {"target": target, "tier": quality_tier(entry, row), "rubric_tier": capped_tier(entry, row)}
        out |= {"rubric_score": score(entry, target), "points_tier": band(score(entry, target)), "basis": _hyp_basis(entry, row)}
    out.update({k: v for k, v in row.items() if k not in out and k != "applicable"})
    return out


def derivation_problems(entry: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """Why a row's stored tier fields are not what the rubric (plus its recorded adjustment) derives."""
    want = finalize_row(entry, row)
    keys = ("rubric_score", "rubric_tier", "tier", "points_tier", "basis", "applicable")
    return [f"{k} {row.get(k)!r} != derived {want.get(k)!r}" for k in keys if row.get(k) != want.get(k)] + adjustment_problems(row)


# ── the other four objectives: small categorical rubrics, each over the movement's `objective_inputs` ────────────────
def _confidence(entry: dict[str, Any], tier: str | None) -> str | None:
    """Practitioner-consensus heuristics, no trial behind any single rating: `consensus` once the inputs were reviewed."""
    return None if tier is None else ("consensus" if _inputs(entry).get("reviewed") else "none_reviewed")


def strength_rating(entry: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Progressive loading potential, specificity, transfer. S = a primary strength lift, maximal overload, free-weight
    (self-stabilised) transfer, bilateral. Fatigue is reported, never a demotion: the fatigue model weighs it."""
    cat, inp = entry.get("category"), _inputs(entry)
    if cat not in ("strength", "hypertrophy", "carry"):
        return None, [f"not applicable: category {cat}"]
    if entry.get("job") != "compound" and cat != "carry":
        return None, ["not applicable: a single-joint movement is rated on hypertrophy"]
    if entry.get("pattern") not in STRENGTH_PATTERNS:
        return None, [f"not applicable: pattern {entry.get('pattern')} is not a loaded strength pattern"]
    ov, lift = str(inp.get("resistance_class") or "light"), bool(inp.get("strength_lift"))
    transfer = entry.get("resistance_profile") in ("free_weight", "bodyweight")
    bilateral = "unilateral" not in (inp.get("functional") or [])
    if lift and ov == "maximal" and transfer and bilateral:
        tier = "S"
    elif ov == "maximal" or (ov == "bodyweight" and inp.get("ladder") and inp.get("ceiling") == "moderate"):
        tier = "A"
    else:
        tier = {"submaximal": "B", "bodyweight": "C"}.get(ov, "D")
    basis = [
        f"overload {ov}",
        f"primary strength lift: {'yes' if lift else 'no'}",
        f"transfer: {'self-stabilised' if transfer else 'guided'}",
    ]
    basis += [f"{'bilateral' if bilateral else 'unilateral'}", f"systemic fatigue {inp.get('systemic_fatigue')} (weighed by selection)"]
    return tier, basis + [
        "rule: S = primary lift + maximal overload + self-stabilised + bilateral; A = maximal, or a bodyweight pull/dip ladder"
    ]


def functional_rating(entry: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Unilateral control, balance, carries, loaded locomotion, trunk stability, multiplanar control, power. S = three or
    more qualities, loadable, not high-skill, no high joint, AND a carry or single-leg work under travel or trunk load."""
    inp = _inputs(entry)
    q = [x for x in FUNCTIONAL_QUALITIES if x in (inp.get("functional") or [])]
    if entry.get("category") == "conditioning" or not q:
        return None, ["not applicable: no functional quality (" + ", ".join(FUNCTIONAL_QUALITIES) + ")"]
    loadable = inp.get("ceiling") in ("moderate", "high")
    core = "carry" in q or ("unilateral" in q and bool({"locomotion", "trunk_stability"} & set(q)))
    safe = entry.get("skill_complexity") != "high" and "high" not in [str(v) for v in (entry.get("joint_stress") or {}).values()]
    if len(q) >= 3 and loadable and safe and core:
        tier = "S"
    elif (len(q) >= 2 and loadable) or len(q) >= 3:
        tier = "A"
    else:
        tier = "B" if len(q) >= 2 or loadable else "C"
    basis = ["qualities: " + ", ".join(q), f"loadable: {'yes' if loadable else 'no'}"]
    return tier, basis + ["rule: S = 3+ qualities, loadable, safe, a carry or single-leg under travel/trunk load; A = 2+ loadable"]


def _cardio(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Lane L4's cardio model rating for this movement (it owns cardio), keyed by the canonical id; None = not a modality
    it models."""
    return cardio_model.conditioning_rating(entry, str(entry.get("canonical") or "") or None)


def conditioning_rating(entry: dict[str, Any]) -> tuple[str | None, list[str]]:
    """ONE conditioning rule per movement. A modality the cardio model knows (`training.cardio_model`, lane L4: every
    cardio machine, walking, running, jump rope, sleds, the KB swing) is rated by it alone. Only a movement it does not
    model (a carry, an athletic drill, a bodyweight circuit) falls back to this table: aerobic stimulus, intensity
    control, impact, recovery demand; S = high aerobic, high control, low impact, low recovery demand. Never penalised for
    lacking hypertrophy traits."""
    cm = _cardio(entry)
    if cm is not None:
        return cm["tier"], [f"cardio_model ({cardio_model.CARDIO_MODEL_VERSION}) modality {cm['modality']}"] + list(cm["basis"])
    c = _inputs(entry).get("conditioning")
    if not isinstance(c, dict):
        return None, ["not applicable: not a conditioning modality"]
    a, ctl, imp, rec = (str(c.get(k)) for k in CONDITIONING_KEYS)
    if a == "high" and ctl == "high" and imp == "low" and rec == "low":
        tier = "S"
    elif (a == "high" and imp == "low") or (a == "moderate" and imp == "low" and rec == "low"):
        tier = "A"
    elif a == "high" or (a == "moderate" and imp != "high"):
        tier = "B"
    else:
        tier = "C" if a in ("moderate", "low") else "D"
    basis = [f"aerobic {a}", f"intensity control {ctl}", f"impact {imp}", f"recovery demand {rec}"]
    return tier, basis + ["rule: S = aerobic high + control high + impact low + recovery low; A = aerobic high + low impact"]


MOBILITY_TIER = {"loaded": "A", "active": "B", "motor_control": "B", "passive": "C"}


def mobility_rating(entry: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Mobility / joint function: active ROM, strength through range, control. Loaded A, active or motor control B,
    passive C. S needs specificity to a RECORDED limitation (owner-private, N=1): the public library never awards it."""
    t = _inputs(entry).get("mobility")
    if t not in MOBILITY_TIER:
        return None, ["not applicable: not a mobility or joint-function movement"]
    return MOBILITY_TIER[t], [f"type {t}", "S needs a recorded limitation this movement targets (N=1) — none in the public library"]


_RATERS = {"strength": strength_rating, "functional": functional_rating, "conditioning": conditioning_rating, "mobility": mobility_rating}


def objective_ratings(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every objective's rating for the movement: {tier: S-D | None, basis: [...], evidence_confidence}. Hypertrophy is
    its primary target's row (and `by_target` per row); None = not applicable, never forced. Pure."""
    rows = [finalize_row(entry, r) for r in entry.get("hypertrophy") or []]
    primary = str((entry.get("target") or {}).get("primary") or "")
    row = next((r for r in rows if r["target"] == primary), rows[0] if rows else {"tier": None, "basis": ["no row"]})
    out = {
        "hypertrophy": {
            "tier": row.get("tier"),
            "target": row.get("target"),
            "by_target": {r["target"]: r["tier"] for r in rows},
            "basis": row.get("basis"),
            "evidence_confidence": row.get("evidence_confidence") if row.get("tier") else None,
        }
    }
    for obj, rate in _RATERS.items():
        tier, basis = rate(entry)
        cm = _cardio(entry) if obj == "conditioning" else None
        conf = cm["evidence_confidence"] if cm is not None else _confidence(entry, tier)
        out[obj] = {"tier": tier, "basis": basis, "evidence_confidence": conf}
    return out


def objective_tier(entry: dict[str, Any], objective: str, target: str | None = None) -> str | None:
    """THE shared accessor (#5861): the movement's tier for `objective`, or None when the objective does not apply.
    Hypertrophy with a `target` is the best tier among that muscle's rows (a sub-target counts: triceps_long_head is
    triceps). Reads the stored `ratings`, deriving them when absent."""
    if objective not in OBJECTIVES:
        raise ValueError(f"objective {objective!r} not in {OBJECTIVES}")
    if objective == "hypertrophy" and target:
        t = str(target).lower()
        tiers = [
            r.get("tier")
            for r in (entry.get("hypertrophy") or [])
            if r.get("tier") and (str(r.get("target")).lower().startswith(t) or t.startswith(str(r.get("target")).lower()))
        ]
        return min(tiers, key=QUALITY_TIERS.index) if tiers else None
    return ((entry.get("ratings") or objective_ratings(entry)).get(objective) or {}).get("tier")


def rating_problems(entry: dict[str, Any]) -> list[str]:
    """Why the stored `ratings` are not what the objective rubrics derive (a hand-edited rating is a schema error)."""
    want = objective_ratings(entry)
    have = entry.get("ratings") or {}
    return [f"ratings.{o} {have.get(o)!r} != derived {want[o]!r}" for o in OBJECTIVES if have.get(o) != want[o]]


def s_census(movements: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """S per objective per muscle (the primary target; a hypertrophy row counts under its own target): the movement keys
    and the number of distinct canonical families among them. A report, not a quota: each S already met every S criterion."""
    out: dict[str, dict[str, dict[str, Any]]] = {o: {} for o in OBJECTIVES}
    for key, e in sorted(movements.items()):
        r = e.get("ratings") or objective_ratings(e)
        hits = [(str(t), "hypertrophy") for t, tier in (r["hypertrophy"].get("by_target") or {}).items() if tier == "S"]
        hits += [(str((e.get("target") or {}).get("primary")), o) for o in _RATERS if objective_tier(e, o) == "S"]
        for muscle, obj in hits:
            cell = out[obj].setdefault(muscle, {"movements": [], "families": []})
            cell["movements"].append(key)
            fam = str(e.get("canonical") or key)
            if fam not in cell["families"]:
                cell["families"].append(fam)
    return {
        o: {m: {"s": len(c["movements"]), "families": len(c["families"]), "movements": c["movements"]} for m, c in sorted(v.items())}
        for o, v in out.items()
    }


def rubric_doc() -> dict[str, Any]:
    """The rubric as data — the library's `quality_rubric` header block (versioned, public)."""
    return {
        "version": RUBRIC_VERSION,
        "provenance": PROVENANCE,
        "job": {
            "field": "job",
            "values": list(JOBS),
            "rule": "by movement pattern (deploy/build_exercise_library.py `_job`), never by muscle",
        },
        "terms": {
            "stretch": {
                "field": "length_bias",
                "points": STRETCH,
                "fixed": {m: {"at": c[0], "citation": c[1], "why": c[2]} for m, c in STRETCH_CAPS.items()},
            },
            "stability": {"field": "stability", "isolation": STABILITY, "compound": COMPOUND_STABILITY},
            "resistance_profile": {
                "field": "resistance_profile",
                "isolation": {"isolation_muscles": list(ISOLATION_MUSCLES), "points": PROFILE_FIT},
                "compound": COMPOUND_PROFILE,
            },
            "progressability": {"field": "skill_complexity", "points": SKILL, "load_steps_bonus": 1, "load_steps": list(LOAD_STEPS)},
            "carryover": {"compound_free_weight": FREE_WEIGHT_CARRYOVER},
            "joint_stress": {
                "field": "joint_stress",
                "per_high": JOINT_HIGH,
                "any_moderate_or_unknown": JOINT_MODERATE,
                "floor": JOINT_FLOOR,
            },
        },
        "unknown": "an unknown attribute never helps: a positive term scores 0, an unknown joint counts as moderate",
        "max_score": {"isolation": MAX_SCORE, "compound": MAX_SCORE_COMPOUND},
        "bands": {tier: floor for floor, tier in BANDS} | {"D": "below C"},
        "evidence": {
            "confidence": list(EVIDENCE_CONFIDENCE),
            "may_adjust": list(EVIDENCE_ADJUSTERS),
            "max_bands": EVIDENCE_MAX_BANDS,
            "rule": "+1 when a direct trial found this movement grew the target more than a compared movement or range, -1 when "
            "less, +1 for equivalence with a higher-tier comparator; otherwise nothing; recorded with its citation; capped at S and D",
        },
        "hypertrophy_caps": {
            "points": "the sum above is the hypertrophy STIMULUS profile; its band is then held under every cap",
            "cap_B": ["ceiling low or unknown", "limiter is not the target muscle"],
            "cap_A": "any unmet S criterion",
            "s_criteria": S_CRITERIA,
            "evidence": "a direct trial moves the capped tier one band, never to S unless every S criterion holds",
            "not_applicable": {"categories": list(NOT_HYPERTROPHY_CATEGORIES), "targets": list(NOT_HYPERTROPHY_TARGETS)}
            | {"trunk_functions": list(ISOMETRIC_TRUNK)},
        },
        "objectives": {
            "list": list(OBJECTIVES),
            "inputs": {k: list(v) for k, v in OBJECTIVE_INPUTS.items()},
            "strength": (strength_rating.__doc__ or "").split(".")[0] + ". S = primary lift + maximal overload + self-stabilised"
            " + bilateral; A = maximal overload or a bodyweight ladder; B submaximal; C bodyweight; D light.",
            "functional": "S = 3+ qualities, loadable, not high-skill, no high joint, and a carry or single-leg work under "
            "travel or trunk load; A = 2+ qualities loadable (or 3+); B = 2 qualities or 1 loadable; C = 1.",
            "conditioning": "S = aerobic high + control high + impact low + recovery low; A = aerobic high + impact low, or "
            "aerobic moderate + impact low + recovery low; B = aerobic high, or moderate without high impact; C otherwise.",
            "mobility": "loaded A, active or motor_control B, passive C; S only against a recorded (N=1) limitation.",
            "evidence_confidence": "practitioner-consensus heuristics: `consensus` when the inputs were reviewed, else "
            "`none_reviewed`; no trial is claimed behind any single non-hypertrophy rating",
            "categories": list(CATEGORIES),
            "trunk_functions": list(TRUNK_FUNCTIONS),
            "functions": list(FUNCTIONS),
        },
        "doc": "docs/coaching/EXERCISE_LIBRARY.md (Quality tiers; Objectives)",
    }
