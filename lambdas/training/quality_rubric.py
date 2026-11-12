"""quality_rubric.py — the exercise library's QUALITY tier, S to D, derived by a written rubric (#5857).

WHY. The library's first tiers (A/B/C, #5769) graded EVIDENCE DIRECTNESS, not exercise quality: A was a direct trial of
this exact movement, B a trial of a close one, C `none_reviewed` — 561 of 582 ratings were C, and the top band of most
muscles had one member or none. Owner, 2026-11-12: "if we are saying there is only one S tier tricep exercise in the
world, that sounds slightly off … there may be a best of the best, but there may be some in that same territory to justify
S-tier." So the tier is now a QUALITY band from the attributes the library already records, and evidence strength is its
own field (`evidence_confidence`), shown beside the tier.

THE RUBRIC (version `RUBRIC_VERSION`; PROPOSED WEIGHTS — OWNER TO CONFIRM). Per (movement, target muscle), the sum of:

    stretch             `length_bias`         lengthened 5 · mid 3 · shortened 1 · unknown / not_applicable 0   (highest)
    stability           `stability`           high 3 · moderate 2 · low 1 · unknown 0  (the target muscle is the limiter)
    resistance profile  `resistance_profile`  fit to the target's strength curve, `PROFILE_FIT` (0-3)
    progressability     `skill_complexity` + load steps   low 2 · moderate 1 · high 0, +1 when the resistance loads in small
                                                            external steps (free weight, cable, machine)
    joint stress        `joint_stress`        a PENALTY: -2 per joint rated high, -1 once when any joint is rated moderate

maximum 14. Bands (`BANDS`): S >= 12 · A >= 10 · B >= 8 · C >= 5 · D below. Bands, not a single winner: every movement
that reaches a band shares it.

EVIDENCE. `evidence_confidence` is rct_direct | rct_characteristic | consensus | none_reviewed. Only a DIRECT trial
(`rct_direct`) may move a row, and only ONE band from its rubric tier (`EVIDENCE_MAX_BANDS`), recorded on the row as
`evidence_adjustment: {bands: +1 | -1, citation, why}`: +1 when the trial found this movement grew the target MORE than a
compared movement or range, -1 when LESS; equal or uncompared growth moves nothing. A move past S or D is capped there.

An `unknown` attribute scores 0 — the rubric never guesses a stretch, a stability or a profile the library cannot state.

Pure: no I/O, no clock. The builder (`deploy/build_exercise_library.py`) writes `rubric_score`, `rubric_tier` and `tier`
from these functions; `exercise_library.validate` and `tests/test_quality_tiers_5857.py` re-derive every row from them, so
a hand-edited tier is a schema error.
"""

from __future__ import annotations

from typing import Any

RUBRIC_VERSION = "1.0.0"
QUALITY_TIERS = ("S", "A", "B", "C", "D")
EVIDENCE_CONFIDENCE = ("rct_direct", "rct_characteristic", "consensus", "none_reviewed")
EVIDENCE_ADJUSTERS = ("rct_direct",)  # the only confidence that may move a row off its rubric tier
EVIDENCE_MAX_BANDS = 1
PROVENANCE = "proposed weights (#5857, 2026-11-12) — owner to confirm"

STRETCH = {"lengthened": 5, "mid": 3, "shortened": 1}
STABILITY = {"high": 3, "moderate": 2, "low": 1}
SKILL = {"low": 2, "moderate": 1, "high": 0}
LOAD_STEPS = ("free_weight", "cable", "machine_selectorized", "machine_plate_loaded")

# The target muscle's strength-curve class. ISOLATION: a single-joint upper-body muscle whose resistance should stay high
# into the lengthened range (a cable or selectorized machine does; a dumbbell's torque falls off at one end). LOADED: the
# lower body, the back and the presses, where a free weight or a machine both load the working range.
ISOLATION_MUSCLES = ("chest", "shoulders", "biceps", "triceps", "forearms")
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
JOINT_MODERATE = -1
BANDS: tuple[tuple[int, str], ...] = ((12, "S"), (10, "A"), (8, "B"), (5, "C"))

# A major muscle whose top band (S) holds fewer than two selectable movements, and why (#5857 acceptance: "at least 2 in
# the top band where the attributes support it, or the slot names why not"). `tests/test_quality_tiers_5857.py` holds the
# list to the shipped library both ways: a short muscle missing here is red, and so is a stale entry.
TOP_BAND_SHORTFALL: dict[str, str] = {
    "abs": "the library records no lengthened, externally loaded ab movement: its ab work is bodyweight flexion "
    "(shortened or unknown length bias, bodyweight resistance), so the best rubric score is A (the cable and machine "
    "crunches). A stretched-position loaded ab movement would be an expansion candidate — owner decision.",
}
MAX_SCORE = max(STRETCH.values()) + max(STABILITY.values()) + 3 + max(SKILL.values()) + 1


def curve_class(target: str) -> str:
    """The target muscle's strength-curve class (a sub-target counts: `triceps_long_head` is triceps)."""
    t = str(target or "").lower()
    return "isolation" if any(t == m or t.startswith(m) for m in ISOLATION_MUSCLES) else "loaded"


def components(entry: dict[str, Any], target: str) -> dict[str, int]:
    """Each rubric term for one (movement, target), as points."""
    profile = str(entry.get("resistance_profile") or "unknown")
    js = [str(v) for v in (entry.get("joint_stress") or {}).values()]
    return {
        "stretch": STRETCH.get(str(entry.get("length_bias")), 0),
        "stability": STABILITY.get(str(entry.get("stability")), 0),
        "resistance_profile": PROFILE_FIT[curve_class(target)].get(profile, 0),
        "progressability": SKILL.get(str(entry.get("skill_complexity")), 0) + (1 if profile in LOAD_STEPS else 0),
        "joint_stress": JOINT_HIGH * js.count("high") + (JOINT_MODERATE if "moderate" in js else 0),
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
    if row.get("evidence_confidence") not in EVIDENCE_ADJUSTERS:
        out.append(f"only a {'/'.join(EVIDENCE_ADJUSTERS)} row may move off its rubric tier")
    if not adj.get("citation") or adj.get("citation") not in (row.get("citations") or []):
        out.append("evidence_adjustment.citation must be one of the row's citations")
    if not adj.get("why"):
        out.append("evidence_adjustment.why is required")
    return out


def quality_tier(entry: dict[str, Any], row: dict[str, Any]) -> str:
    """The row's tier: its rubric tier, moved by its recorded evidence adjustment (one band at most)."""
    base = rubric_tier(entry, str(row.get("target") or ""))
    adj = row.get("evidence_adjustment")
    return shift(base, int(adj["bands"])) if isinstance(adj, dict) and not adjustment_problems(row) else base


def finalize_row(entry: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """The row with its derived fields written: `rubric_score`, `rubric_tier`, `tier`. The evidence fields are kept."""
    target = str(row.get("target") or "")
    out = {"target": target, "tier": quality_tier(entry, row), "rubric_tier": rubric_tier(entry, target)}
    out["rubric_score"] = score(entry, target)
    out.update({k: v for k, v in row.items() if k not in out})
    return out


def derivation_problems(entry: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """Why a row's stored tier fields are not what the rubric (plus its recorded adjustment) derives."""
    target = str(row.get("target") or "")
    want = {"rubric_score": score(entry, target), "rubric_tier": rubric_tier(entry, target), "tier": quality_tier(entry, row)}
    return [f"{k} {row.get(k)!r} != derived {v!r}" for k, v in want.items() if row.get(k) != v] + adjustment_problems(row)


def rubric_doc() -> dict[str, Any]:
    """The rubric as data — the library's `quality_rubric` header block (versioned, public)."""
    return {
        "version": RUBRIC_VERSION,
        "provenance": PROVENANCE,
        "terms": {
            "stretch": {"field": "length_bias", "points": STRETCH},
            "stability": {"field": "stability", "points": STABILITY},
            "resistance_profile": {"field": "resistance_profile", "isolation_muscles": list(ISOLATION_MUSCLES), "points": PROFILE_FIT},
            "progressability": {"field": "skill_complexity", "points": SKILL, "load_steps_bonus": 1, "load_steps": list(LOAD_STEPS)},
            "joint_stress": {"field": "joint_stress", "per_high": JOINT_HIGH, "any_moderate": JOINT_MODERATE},
        },
        "unknown": "an unknown attribute scores 0",
        "max_score": MAX_SCORE,
        "bands": {tier: floor for floor, tier in BANDS} | {"D": "below C"},
        "evidence": {
            "confidence": list(EVIDENCE_CONFIDENCE),
            "may_adjust": list(EVIDENCE_ADJUSTERS),
            "max_bands": EVIDENCE_MAX_BANDS,
            "rule": "+1 when a direct trial found this movement grew the target more than a compared movement or range, -1 when "
            "less; equal or uncompared growth moves nothing; recorded with its citation; capped at S and D",
        },
        "doc": "docs/coaching/EXERCISE_LIBRARY.md (Quality tiers)",
    }
