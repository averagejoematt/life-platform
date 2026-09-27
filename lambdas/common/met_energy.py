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

**What is verified, and what is not (#4178, 2026-09-26 — checked against the
published table, not recalled).** The MET VALUES below are the owner's own cited
figures (2026-09-25 review: "treadmill walking ~3.5 METs", "stationary cycling
light/easy 4.0-5.5, pick the light effort code"). The CODE numbers were read on
2026-09-26 from the journal's own supplemental table for Ainsworth et al. 2011 —
Med Sci Sports Exerc 43(8), Supplemental Digital Content 1,
https://cdn-links.lww.com/permalink/mss/a/mss_43_8_2011_06_13_ainsworth_202093_sdc1.pdf
(text-extracted with pdftotext; header "2011 Compendium of Physical Activities",
columns CODE / METS / MAJOR HEADING / SPECIFIC ACTIVITIES):

  * ``17190  3.5  walking  walking, 2.8 to 3.2 mph, level, moderate pace, firm surface``
    — the value matches WALK_MET exactly, so WALK_MET_CODE is pinned to it. The table
    carries NO separate "treadmill walking" row (its only treadmill entries are 02065
    stair-treadmill ergometer 9.0 and 11003 treadmill-desk walking 2.3), so level
    ground at moderate pace is the row a treadmill walk is priced by.
  * Stationary bicycling rows: ``02011 3.5 … 30-50 watts, very light to light effort``,
    ``02017 4.8 … 51-89 watts, light-to-moderate effort``, ``02010 7.0 … general``,
    ``02012 6.8 … 90-100 watts``. **No stationary-bicycling row carries 4.0**: the
    owner's 4.0 sits between 02011 (3.5) and 02017 (4.8). The one 4.0 bicycling row,
    ``01010 bicycling, <10 mph, leisure, to work or for pleasure``, is outdoor leisure
    cycling — a different modality — so CARDIO_LIGHT_MET_CODE stays ``None`` rather
    than borrowing a code whose row does not say what this constant means. The value
    4.0 itself is unchanged: it is the owner's ruling, bracketed by two verified rows,
    and this module does not re-rule it.
"""

from __future__ import annotations

from typing import Any, Optional

MET_SOURCE = "ainsworth_2011_compendium_of_physical_activities"

#: Ainsworth 2011 Compendium row 17190 — description verbatim from the published
#: table (see the module docstring for the source and the 2026-09-26 verification).
WALK_MET = 3.5
WALK_MET_DESCRIPTION = "walking, 2.8 to 3.2 mph, level, moderate pace, firm surface"
WALK_MET_CODE: Optional[str] = "17190"  # verified against the published table 2026-09-26 (#4178)

#: Ainsworth 2011 Compendium — "bicycling, stationary, light/easy effort" — the LOW
#: end of the owner-cited 4.0-5.5 "light effort" band, per the explicit instruction to
#: pick the light-effort code. The published table has no stationary row at 4.0 (it
#: brackets this value: 02011 = 3.5, 02017 = 4.8 — see the module docstring), so the
#: code is deliberately left None rather than guessed (#4178).
CARDIO_LIGHT_MET = 4.0
CARDIO_LIGHT_MET_DESCRIPTION = "bicycling, stationary, light/easy effort"
CARDIO_LIGHT_MET_CODE: Optional[str] = None  # no published row at 4.0; bracketed by 02011/02017 — see docstring

#: 1 MET ~= 1 kcal/(kg*hour) — the existing platform convention (see module docstring;
#: matches how `health.tdee.PROXY_KCAL_PER_KG_HOUR` already documents itself).
WALK_MET_KCAL_PER_KG_HOUR = WALK_MET
CARDIO_LIGHT_MET_KCAL_PER_KG_HOUR = CARDIO_LIGHT_MET

#: Provenance tokens for the two MET bases, as `health.tdee` publishes them in
#: `kcal_by_basis` (#4178) — one spelling for the Hevy side and the Strava side, so a
#: reader can add a walk's energy across devices without knowing which device logged it.
BASIS_MET_WALK = "met:walk"
BASIS_MET_CARDIO_LIGHT = "met:cardio_light"

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
