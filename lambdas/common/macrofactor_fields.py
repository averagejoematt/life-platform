"""macrofactor_fields — the ONE declaration of the stored MacroFactor day row's macro field names (#4580 B-22).

The writer is ``lambdas/ingestion/macrofactor_lambda.py`` and the authoritative table is
``docs/SCHEMA.md`` § macrofactor: a day row carries ``total_calories_kcal`` and ``total_protein_g``
(plus ``meals_above_30g_protein`` from the ingest's meal grouping). It carries NO calorie target —
the target is the plan's (``common.constants.PLAN_DAILY_CALORIES_TARGET``).

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
