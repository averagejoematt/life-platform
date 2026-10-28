"""protein_floor.py - THE definition of "a day met the protein floor" (#5003).

Two callers answered this question two ways: the MCP `get_nutrition view=macros` graded
`prot >= floor * 0.95` (so 166 g counted as a hit against 170 g) while the plan engine's
`protein_floor_missed` tripwire (`training.redline_rate.protein_days_missed`) counted `g < floor`.
Both now call `met_floor`.

The floor itself is the charter's `nutrition.protein.range_g.low` (#5098), read by
`health.protein_engine.hit` — the engine every hit-decider calls; this predicate is what it
applies. The plan constant `common.constants.PLAN_DAILY_PROTEIN_MIN_G` (provenance: owner,
ruling 2026-10-11 #4540 - ADR-105) is held equal to it by tests/test_protein_engine_5098.py,
so a published surface that passes the constant here grades the same day the same way.

TOLERANCE: `tolerance_g` defaults to 0 and NO caller sets it. Whether any shortfall below the floor
should count as a hit is the owner's ruling (#5003, gate:owner) - his word is a one-line change at
the call sites, and until then the definition is strictly `grams >= floor`.
"""

from __future__ import annotations

from typing import Optional


def met_floor(grams: Optional[float], floor: float, tolerance_g: float = 0.0) -> Optional[bool]:
    """True when `grams >= floor - tolerance_g`; None for an unmeasured day (ADR-104: never a miss)."""
    if grams is None:
        return None
    return float(grams) >= float(floor) - float(tolerance_g)


def floor_gap(floor: float, *averages: Optional[float]) -> Optional[dict]:
    """The distance from an intake average to the floor, as the nutrition context serves it (#5458).

    The 2026-10-28 analyzer run held the nutrition read on "the number 32 appears in the narrative
    but nowhere in the data provided": 32 is the 170 g floor minus the served 138.3 g average,
    rounded. The coach did the subtraction because the context carried both figures and not the gap,
    and the allow-list gate refuses a computed number by design. So the gap travels as a fact.

    `averages` are candidates in order of authority (the served logging record's average first);
    the first measured one wins. None when no average is measured (ADR-104: absence, not a gap of 0).
    """
    avg = next((float(a) for a in averages if a is not None), None)
    if avg is None:
        return None
    delta = round(avg - float(floor), 1)
    return {
        "grams": abs(delta),
        "direction": "below" if delta < 0 else ("above" if delta > 0 else "at"),
        "average_g": avg,
        "floor_g": float(floor),
        "note": (
            "the authoritative average minus the plan's floor. When you cite a gap to the floor, cite THIS figure, never your own "
            'arithmetic, in its own clause: "<grams> g a day below the floor".'
        ),
    }
