"""public_corrections.py — the PUBLIC correction ledger of the scoring methods (owner rulings 2026-11-05/06).

"Preserve the public correction ledger and version the scoring methodology." The private ledger (per-value method-1
values with their timestamps) stays private. This is what a reader may see, and its one design rule is that it CANNOT
identify private activity:

* A per-date "before" taken from method 1 would leak: the delta on a date would move with the journal, and a reason
  stamped on one date ("journal component removed") would name a journal day. So no method-1 value appears here.
* The before/after it serves are BOTH public-method values: ``before`` is the public method as if the habit results had
  stayed unavailable (the old compute order), ``after`` is the corrected public value. Both derive from public inputs
  only, so every row is byte-identical whatever the journal did, and the delta explains the timing correction, which
  is the part that moved the numbers up.
* The reason categories are ONE list for the whole correction, never per date. The same sentences stand on every date.

Stored as one item, ``USER#<id>#SOURCE#public_corrections`` / ``CORRECTION#<method version>``, written by
``scripts/backfill_public_variant.py --apply``; served by ``/api/character_config`` under ``public_method``.
"""

from __future__ import annotations

from typing import Any, Optional

from health import character_privacy, day_grade_public, habit_pct_public

SOURCE = "public_corrections"
LEDGER_VERSION = "public-correction-ledger-v1"
REASON_CATEGORIES = (
    "Private inputs were removed from the public scores (the same rule on every date).",
    "Habit results that used to arrive after the score was worked out are now counted.",
    "A day with no public measurement is shown as unavailable, not as a zero.",
    "Consistency, levels and XP were worked through again from those corrected daily scores.",
    "The day grade and habit completion use public-eligible inputs only.",
)
SERVED_KEYS = (
    "ledger_version",
    "method_versions",
    "effective_from",
    "recalculated_on",
    "date_from",
    "date_to",
    "dates_recalculated",
    "reason_categories",
    "notice",
    "rows",
)


def correction_sk(version: str = character_privacy.PUBLIC_METHOD_VERSION) -> str:
    return f"CORRECTION#{version}"


def _pillar(block: dict, name: str) -> dict:
    return block.get(f"pillar_{name}") or {}


def _row(day: str, before: dict, after: dict) -> dict:
    def mind(b: dict) -> Optional[float]:
        p = _pillar(b, "mind")
        return None if p.get("not_instrumented") else p.get("level")

    return {
        "date": day,
        "overall_level": [before.get("character_level"), after.get("character_level")],
        "mind_level": [mind(before), mind(after)],
        "character_xp": [before.get("character_xp"), after.get("character_xp")],
    }


def build_ledger(before: dict, after: dict, recalculated_on: str) -> dict:
    """The ledger item's body. ``before`` / ``after``: {date: public block} — the public method without and with the
    habit results. Neither reads a method-1 value, so nothing here can move with a private input."""
    days = sorted(d for d in after if after[d] and before.get(d))
    return {
        "ledger_version": LEDGER_VERSION,
        "method_versions": {
            "character": character_privacy.PUBLIC_METHOD_VERSION,
            "day_grade": day_grade_public.METHOD_VERSION,
            "habit_pct": habit_pct_public.METHOD_VERSION,
        },
        "effective_from": character_privacy.PUBLIC_METHOD_EFFECTIVE_FROM,
        "recalculated_on": recalculated_on,
        "date_from": days[0] if days else None,
        "date_to": days[-1] if days else None,
        "dates_recalculated": len(days),
        "reason_categories": list(REASON_CATEGORIES),
        "notice": character_privacy.PUBLIC_CORRECTION_NOTICE,
        "rows": [_row(d, before[d], after[d]) for d in days],
    }


def served_ledger(item: Any) -> Optional[dict[str, Any]]:
    """The ledger as a public route serves it: the whitelisted keys, or None when no correction is recorded."""
    if not isinstance(item, dict) or item.get("ledger_version") != LEDGER_VERSION:
        return None
    return {k: item.get(k) for k in SERVED_KEYS}
