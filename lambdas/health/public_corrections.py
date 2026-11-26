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

v2 (#6224, owner rulings 2026-11-26): Mind is not scored in public. Both v1 values of a date included Mind — computed
partly from restraint habits — so the v2 ledger serves no per-date rows at all (``build_ledger``), and the v1 item (key
``CORRECTION#character-public-v1``) is no longer read by any route: the served ledger is the CURRENT version's.

Stored as one item, ``USER#<id>#SOURCE#public_corrections`` / ``CORRECTION#<method version>``, written by
``scripts/backfill_public_variant.py --apply``; served by ``/api/character_config`` under ``public_method``.
"""

from __future__ import annotations

from typing import Any, Optional

from health import character_privacy, day_grade_public, habit_pct_public

SOURCE = "public_corrections"
LEDGER_VERSION = "public-correction-ledger-v2"
# #6224 (owner rulings 2026-11-26): the v2 recalculation's reasons. The same sentences stand on every date.
REASON_CATEGORIES = (
    "Mind is not scored in public: its inputs are private. It has no public score, level or XP.",
    "The overall level, the composite and the XP total are worked out from the other areas, without Mind.",
    "The food-delivery adjustment to Nutrition is not applied in public, and restraint habits count in no public figure.",
    "Consistency, levels and XP were worked through again from those daily scores.",
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


def build_ledger(after: dict, recalculated_on: str) -> dict:
    """The v2 ledger item's body (#6224). ``after``: {date: public block} — the recalculated public values.

    It carries NO per-date rows. The v1 ledger's rows paired two public-method values per date, both of which included
    Mind; under v2 the "before" of a date is a value computed WITH Mind — whose inputs the owner ruled private
    (2026-11-26) — so a per-date before/after would publish Mind's contribution as the difference. What is served is the
    range, the count and the reasons, which say the same thing on every date."""
    days = sorted(d for d in after if after[d])
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
        "rows": [],
    }


def served_ledger(item: Any) -> Optional[dict[str, Any]]:
    """The ledger as a public route serves it: the whitelisted keys, or None when no correction is recorded."""
    if not isinstance(item, dict) or item.get("ledger_version") != LEDGER_VERSION:
        return None  # a v1 ledger item (rows carrying Mind levels) is never served under v2
    return {k: item.get(k) for k in SERVED_KEYS}
