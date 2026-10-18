"""protein_floor.py - THE definition of "a day met the protein floor" (#5003).

Two callers answered this question two ways: the MCP `get_nutrition view=macros` graded
`prot >= floor * 0.95` (so 166 g counted as a hit against 170 g) while the plan engine's
`protein_floor_missed` tripwire (`training.redline_rate.protein_days_missed`) counted `g < floor`.
Both now call `met_floor`.

The floor itself is `common.constants.PLAN_DAILY_PROTEIN_MIN_G` (provenance: owner, ruling
2026-10-11 #4540 - ADR-105); `owner_redlines.REDLINES["protein_floor_g"]` re-exports that same value.

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
