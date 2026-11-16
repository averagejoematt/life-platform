"""day_grade_public.py — the Day Grade's PUBLIC method, ``day-grade-public-v1`` (owner ruling 2026-11-05).

"Public Mind, composite, XP, Day grades and overall levels must depend only on public-eligible inputs."

The Day Grade (``scoring_engine.compute_day_grade``) is a weighted mean of component scores, renormalised over the
components that scored. Two of them can read private activity:

* **journal** (``score_journal``) is the journal itself — whether he wrote, morning and/or evening. The public method
  has no journal component: its weight leaves the mean, which renormalises over the rest (``PRIVATE_COMPONENTS``).
* **habits_mvp** before the core-12 set was armed (2026-10-24) was the tier-weighted share of every active habit —
  the Morning and Evening Journal habits among them. The scorer runs over the registry with every non-public habit
  removed (``common.activity_publication.habit_is_public``: the journal habits are private, an unclassified habit
  fails closed), and on a TIER-WEIGHTED day the public method holds the habits component out of the grade
  (``TIER_WEIGHTED_HABITS``): such a day's share cannot be re-scored exactly after the fact. A core-set day is
  unchanged: the core twelve hold no private habit (the evening check-in's PRESENCE is in — the owner put it in the
  core set).

The live compute writes the public variant beside the method-1 fields of the day_grade record, under ``PUBLIC_KEY``
(never over them); every public reader reads ``public_grade`` and gets None when there is none (fail closed). Method
1 stays the owner's: MCP, the daily brief and the coaches read the stored fields as before.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from common import activity_publication

from health import scoring_engine

PUBLIC_KEY = "public"
METHOD_VERSION = "day-grade-public-v1"
METHOD_VERSIONS = (METHOD_VERSION,)
EFFECTIVE_FROM = "2026-09-06"  # the experiment's genesis: every stored day is recomputed under it
DEFINED_ON = "2026-11-05"
PRIVATE_COMPONENTS = {"journal": "notion"}  # component -> the private source it reads
PRIVATE_DATA_KEYS = ("journal_entries",)  # compute inputs the public method never hands a scorer
# A TIER-WEIGHTED habits day (the registry unarmed: before 2026-10-24) scored every active habit, the journal habits
# among them; its stored score cannot be re-scored exactly after the fact (the registry has changed since), so the
# public method holds the habits component OUT of such a day's grade — live and recomputed alike. "replay" would
# re-score it over public habits instead (an owner decision: scripts/backfill_public_variant.py reports both).
TIER_WEIGHTED_HABITS = "hold_out"


def component_is_public(name: str) -> bool:
    src = PRIVATE_COMPONENTS.get(name)
    return src is None or activity_publication.source_is_public(src)


def public_weights(weights: Any) -> dict[str, float]:
    """The day-grade weights with every private component removed (the mean renormalises over the rest)."""
    return {k: float(v) for k, v in (weights or {}).items() if component_is_public(k)}


def public_profile(profile: dict[str, Any], habitify: Any = None) -> dict[str, Any]:
    """The profile the public method scores under: public weights and a habit registry of public habits only —
    classified by identity (the day's stored status for the habit, resolved as the scorer resolves it), never by the
    words in a name."""
    from health.habit_identity import day_name_for

    prof = copy.deepcopy(profile or {})
    prof["day_grade_weights"] = public_weights(prof.get("day_grade_weights"))
    day = habitify if isinstance(habitify, dict) else {}
    habits_map = day.get("habits") or {}
    raw_statuses = day.get("habit_statuses")
    statuses: dict[str, Any] = raw_statuses if isinstance(raw_statuses, dict) else {}
    public = {}
    for name, meta in (prof.get("habit_registry") or {}).items():
        hit = day_name_for(habits_map, statuses, name, meta if isinstance(meta, dict) else None)
        if activity_publication.habit_is_public(name, statuses.get(hit) if hit else None, meta):
            public[name] = meta
    prof["habit_registry"] = public
    return prof


def total_from_components(component_scores: dict[str, Any], weights: Any) -> tuple:
    """(score, letter) exactly as ``compute_day_grade`` combines its components, over the public ones only."""
    w = public_weights(weights)
    active = [(float(s), w[c]) for c, s in (component_scores or {}).items() if s is not None and w.get(c, 0) > 0]
    if not active:
        return None, "—"
    total = scoring_engine.clamp(round(sum(s * wt for s, wt in active) / sum(wt for _, wt in active)))
    return total, scoring_engine.letter_grade(total)


def block(score: Any, letter: str, component_scores: dict[str, Any], weights: Any, *, origin: str, notes: Any = None) -> dict:
    """The stored public variant: score, letter, the public components and weights, the method stamps."""
    out = {
        "total_score": score,
        "letter_grade": letter,
        "component_scores": {c: s for c, s in (component_scores or {}).items() if component_is_public(c) and s is not None},
        "weights": public_weights(weights),
        "public_method_version": METHOD_VERSION,
        "effective_from": EFFECTIVE_FROM,
        "origin": origin,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes:
        out["notes"] = list(notes)
    return out


def compute_live(data: dict[str, Any], profile: dict[str, Any]) -> dict:
    """The day's public variant from the compute's own inputs: the same scorers over the public data (no journal
    entries) and the public profile (``public_profile``)."""
    prof = public_profile(profile, data.get("habitify"))
    pdata = {k: v for k, v in (data or {}).items() if k not in PRIVATE_DATA_KEYS}
    score, letter, comps, details = scoring_engine.compute_day_grade(pdata, prof)
    if TIER_WEIGHTED_HABITS == "hold_out" and (details.get("habits_mvp") or {}).get("composite_method") == "tier_weighted":
        comps = dict(comps, habits_mvp=None)
        score, letter = total_from_components(comps, prof.get("day_grade_weights"))
    return block(score, letter, comps, prof.get("day_grade_weights"), origin="live")


def stored_fields(public_inputs: Any) -> dict[str, Any]:
    """``{PUBLIC_KEY: <the variant, DynamoDB-ready>}`` for the day_grade item, or {} — no inputs, or the public compute
    failed (logged; the method-1 write must never be lost to it, and a public reader then fails closed)."""
    if not public_inputs:
        return {}
    try:
        from common.numeric import floats_to_decimal

        return {PUBLIC_KEY: floats_to_decimal(compute_live(*public_inputs), precision=4)}
    except Exception as e:  # pragma: no cover — defensive; the scorers are pure
        import logging

        logging.getLogger(__name__).error("[day_grade_public] public variant failed (method 1 stored without it): %s", e)
        return {}


def public_grade(record: Any) -> Optional[dict[str, Any]]:
    """The public variant of a stored day_grade record — ``{total_score, letter_grade, component_scores, weights,
    public_method_version, ...}`` — or None when it has none a reader may serve (fail closed, never method 1)."""
    pv = record.get(PUBLIC_KEY) if isinstance(record, dict) else None
    if not isinstance(pv, dict) or pv.get("public_method_version") not in METHOD_VERSIONS:
        return None
    return pv


def public_score(record: Any) -> Optional[float]:
    """The public day-grade score of a stored record, or None (no variant, or no score)."""
    pv = public_grade(record)
    s = (pv or {}).get("total_score")
    try:
        return float(s) if s is not None else None
    except (TypeError, ValueError):
        return None


def public_letter(record: Any) -> Optional[str]:
    """The public letter grade of a stored record, or None (no variant, or no public component scored)."""
    pv = public_grade(record)
    return pv.get("letter_grade") if pv and pv.get("total_score") is not None else None
