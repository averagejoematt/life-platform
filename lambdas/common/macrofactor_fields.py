"""macrofactor_fields — the ONE declaration of the stored MacroFactor day row's macro field names (#4580 B-22).

The writer is ``lambdas/ingestion/macrofactor_lambda.py`` and the authoritative table is
``docs/SCHEMA.md`` § macrofactor: a day row carries ``total_calories_kcal`` and ``total_protein_g``
(plus ``meals_above_30g_protein`` from the ingest's meal grouping). The row may carry the MacroFactor
APP's own target as ``target_calories_kcal`` — that is not the platform's target: the platform's ONE
calorie target is ``health.calorie_target`` (#5095), and the app's is read only as a drift signal.

Why this module exists: ``health/character_engine.py`` read ``calories``/``total_calories`` and
``protein``/``total_protein`` — names the row has never carried under schema v1 — so four Food
components scored ABSENT (0 at full weight) on days that were logged (ADR-104's field-mapping class).
Every reader that needs a day's macros resolves through ``macro_value`` instead of spelling the names.

Resolution is by PRESENCE, not truthiness (#2221): an honestly logged 0 is a value, not an absence.
The legacy short names stay as fallbacks for older rows and hand-built fixtures.
"""

from typing import Any, Optional

# quantity -> stored field names, current schema first, then legacy spellings.
MACRO_FIELDS: dict[str, tuple[str, ...]] = {
    "calories": ("total_calories_kcal", "calories", "total_calories"),
    "protein": ("total_protein_g", "protein_g", "protein", "total_protein"),
}

# The ingest's own count of meals (eating occasions >= 400 kcal) at >= 30 g protein (SCHEMA.md).
MEALS_ABOVE_30G_PROTEIN_FIELD = "meals_above_30g_protein"
MEALS_ABOVE_PROTEIN_THRESHOLD_G = 30


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is absent


# The MacroFactor app's own calorie target as the ingest stores it (SCHEMA.md § macrofactor).
APP_TARGET_CALORIES_FIELD = "target_calories_kcal"


def app_target_kcal(row: Optional[dict]) -> Optional[float]:
    """The MacroFactor app's calorie target stored on the day row, or None. A drift signal against
    health.calorie_target, never a scoring reference (#5095)."""
    return _num((row or {}).get(APP_TARGET_CALORIES_FIELD))


def macro_value(row: Optional[dict], quantity: str) -> Optional[float]:
    """The day's ``quantity`` (``calories`` | ``protein``) from a stored MacroFactor row, or None if absent."""
    if not row:
        return None
    for name in MACRO_FIELDS[quantity]:
        v = _num(row.get(name))
        if v is not None:
            return v
    return None


def meals_above_protein_threshold(row: Optional[dict]) -> Optional[float]:
    """The ingest's stored count of meals at >= 30 g protein, or None if the row does not carry it."""
    if not row:
        return None
    return _num(row.get(MEALS_ABOVE_30G_PROTEIN_FIELD))


def protein_meals_at(row: Optional[dict], threshold_g: float) -> Optional[float]:
    """Meals at >= `threshold_g` protein: from a legacy ``meals`` list when the row carries one, else the
    ingest's stored ``meals_above_30g_protein`` (only when the threshold IS 30 g); None when neither applies."""
    meals = (row or {}).get("meals") or []
    if meals:
        return float(sum(1 for m in meals if (_num((m or {}).get("protein")) or 0) >= threshold_g))
    if float(threshold_g) == MEALS_ABOVE_PROTEIN_THRESHOLD_G:
        return meals_above_protein_threshold(row)
    return None


# ── #5431 box 2: the ONE today-bound for every intake reader ────────────────────────────────────
#
# MacroFactor's export carries projected values (targets, expenditure) for days that have not
# happened; the writer no longer stores them (`_is_future`), but a reader must not depend on that: a
# stored future-dated row reads as intake. Every range read of an intake partition clamps its upper
# bound through ``intake_window`` and every "latest" read rides ``latest_day_condition`` / ``latest_sk_ceiling`` —
# today being the PACIFIC date (the platform timezone), not the UTC one.

#: sources whose DATE# rows are observations of a day that has happened (mcp/core.py reuses the name).
NO_FUTURE_SOURCES = frozenset({"macrofactor"})


def intake_window(source: str, start: str, end: str, today: Optional[str] = None) -> Optional[tuple]:
    """``(start, end)`` with ``end`` clamped to the Pacific today for an intake source, or None when
    the window lies wholly in the future (DynamoDB rejects a BETWEEN whose lower bound exceeds the
    upper). Any other source passes through unchanged."""
    if source not in NO_FUTURE_SOURCES:
        return (start, end)
    from common.pacific_time import pacific_today

    end = min(end, today or pacific_today())
    return None if start > end else (start, end)


def latest_sk_ceiling(source: str, today: Optional[str] = None) -> Optional[str]:
    """The sort-key ceiling day for a newest-first read of ``source``: ``DATE#<pacific today>`` for an intake
    source, None for any other (no bound). The caller closes the END day with ``~`` (#4129: it admits the
    day's ``#``-suffixed rows). ``Limit=1`` reads cannot post-filter, so the bound has to ride the key condition."""
    if source not in NO_FUTURE_SOURCES:
        return None
    from common.pacific_time import pacific_today

    return f"DATE#{today or pacific_today()}"


def latest_day_condition(pk: str, source: str, require_prefix: bool = True, today: Optional[str] = None):
    """A boto3 ``Key`` condition for a newest-first read of one partition: unchanged for every source
    except an intake one, which is bounded at the Pacific today. ``require_prefix`` keeps the
    ``begins_with("DATE#")`` the call site already carried (so a non-day sentinel never reads as latest)."""
    from boto3.dynamodb.conditions import Key

    kce = Key("pk").eq(pk)
    ceiling = latest_sk_ceiling(source, today)
    if ceiling:
        return kce & Key("sk").between("DATE#", f"{ceiling}~")
    return kce & Key("sk").begins_with("DATE#") if require_prefix else kce
