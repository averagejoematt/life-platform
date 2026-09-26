"""common/met_energy.py — MET-based energy rates for Hevy cardio time the platform
cannot attribute to a measured heart-rate stream (#4158, owner ruling 2026-09-25,
option A).

**Why this exists.** `health.tdee.PROXY_KCAL_PER_KG_HOUR` (6 kcal/kg/hour, ~6 METs —
moderate cycling / running) was being applied to EVERY uncovered Hevy cardio second,
including treadmill walking. A walking pace is not a 6-MET activity; charging it there
inflated the calorie target. The owner's ruling named the preference order:

  1. **HR-based energy, if the platform has it for this time.** Grepped
     `lambdas/health/` and `lambdas/training/` for an existing HR-based KCAL
     derivation to reuse — there is none. `training.training_load.hr_load`/
     `_trimp_weight` compute TRIMP, a UNITLESS TSS-like training-load score, never
     kcal, and no HR-to-calorie conversion exists anywhere else in the tree.
     Structurally, this branch also has no live data to run on: Hevy's stored
     schema carries no per-set or per-workout heart-rate field at all (verified
     against every key `training.hevy_common._normalize_set` / `normalize_workout`
     write), and "an overlapping HR stream exists" is exactly
     `common.activity_overlap`'s discount, already applied — the covered share is
     zeroed on the Hevy side and charged by the OTHER activity's own accounting, so
     there is nothing left to compute for it. Writing a new, unverified HR->kcal
     formula here to fill an unreachable branch would be exactly the kind of
     invented number ADR-104/105 exists to refuse, so none is added.
  2. **Fallback (what actually governs every real day today): a modality MET from
     the Compendium of Physical Activities** (Ainsworth BE, Haskell WL, Herrmann SD,
     et al. 2011 Compendium of Physical Activities: a second update of codes and MET
     values. Med Sci Sports Exerc. 43(8):1575-1581). Population-derived, not measured
     on Matthew (ADR-105 provenance) — MET_SOURCE below names it, `_verified` below
     names PRECISELY what is and is not independently confirmed.

**Unit convention — inherited, not invented.** `health.tdee.PROXY_KCAL_PER_KG_HOUR`'s
own docstring already treats "6 kcal/kg/hour" as "~6 METs" — i.e. this codebase's
existing convention is 1 MET ~= 1 kcal/(kg*hour) (the more exact ~1.05 kcal/(kg*hour)
factor, from 1 MET = 3.5 mL O2/(kg*min) and ~5 kcal per liter O2, rounds to 1:1 the
same way the existing constant already does). This module follows that SAME
convention rather than introducing a second unit rule.

**Stated uncertainty (verify empirically; do not assert — CLAUDE.md).** The MET
VALUES below are the owner's own cited figures (2026-09-25 review: "treadmill walking
~3.5 METs", "stationary cycling light/easy 4.0-5.5, pick the light effort code"),
sourced to the 2011 Compendium. The exact 5-digit Compendium CODE NUMBER for each
entry could NOT be independently verified in this sandboxed session — no network
access to the published table. `CODE` below is left `None` with the activity
description carried instead of a guessed number, specifically so a wrong code is
never silently shipped as if checked. A human should confirm the code number
against the published Compendium table before this constant is treated as
code-cited rather than description-cited.
"""

from __future__ import annotations

from typing import Any, Optional

MET_SOURCE = "ainsworth_2011_compendium_of_physical_activities"

#: Ainsworth 2011 Compendium — "walking, treadmill or level ground, moderate pace
#: (~3.5 METs)" per the owner's own citation. Code number NOT independently verified
#: here (no network access) — see the module docstring.
WALK_MET = 3.5
WALK_MET_DESCRIPTION = "walking, treadmill or level ground, moderate pace"
WALK_MET_CODE: Optional[str] = None  # unverified in this session; see docstring

#: Ainsworth 2011 Compendium — "bicycling, stationary, light/easy effort" — the LOW
#: end of the owner-cited 4.0-5.5 "light effort" band, per the explicit instruction to
#: pick the light-effort code. Code number NOT independently verified here.
CARDIO_LIGHT_MET = 4.0
CARDIO_LIGHT_MET_DESCRIPTION = "bicycling, stationary, light/easy effort"
CARDIO_LIGHT_MET_CODE: Optional[str] = None  # unverified in this session; see docstring

#: 1 MET ~= 1 kcal/(kg*hour) — the existing platform convention (see module docstring;
#: matches how `health.tdee.PROXY_KCAL_PER_KG_HOUR` already documents itself).
WALK_MET_KCAL_PER_KG_HOUR = WALK_MET
CARDIO_LIGHT_MET_KCAL_PER_KG_HOUR = CARDIO_LIGHT_MET

#: Hevy exercise-name fragments that mark walking-type locomotion — the SAME set
#: `training.training_load._cardio_rate` uses for its own (TSS-point) modality split,
#: moved here so both the calorie side and the TSB-load side classify a cardio block
#: identically (ONE derivation, #4158 review item 2).
WALK_NAME_FRAGMENTS = ("walk", "treadmill", "hike", "stair")
#: A logged cardio block at or below this average speed is walking pace (7.2 km/h).
WALK_PACE_MAX_MS = 2.0


def is_walk_pace(name: Any, secs: float, distance_m: float) -> bool:
    """True when a Hevy cardio block's exercise name AND pace both read as walking.

    Identical predicate to `training.training_load._cardio_rate`'s own walk check —
    moved here so the calorie side and the TSB-load side can never classify the SAME
    block differently.
    """
    n = str(name or "").lower()
    speed = (distance_m / secs) if secs > 0 else 0.0
    return any(k in n for k in WALK_NAME_FRAGMENTS) and speed <= WALK_PACE_MAX_MS
