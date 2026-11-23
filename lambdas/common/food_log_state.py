"""common/food_log_state.py — ONE answer to "was this day's food missed, or has its export just not arrived?" (#6240).

MacroFactor reaches the platform by a manual export (``source_registry``: "Manual CSV export via Dropbox
poller, ~24h behind by design"). A day with no food row therefore means one of two different things:

  * PENDING — no export has landed since the day ended, so the platform cannot know what was logged.
    This is data on its way, never a missed log, and nothing may say "not logged" about it.
  * NOT LOGGED — an export HAS landed after the day ended and still carries no intake for it.

The Morning Brief (``content.brief_editorial.nutrition_arrival``, read by the hybrid and compact formats)
and the public day page (``/api/nutrition_overview`` -> ``food_log.pending_days`` ->
``scripts/publish_snapshot_day.py`` -> ``/data/day/<date>/``) both call ``arrival`` below, so the email
and the page it links to cannot disagree about the same day (contract:
``tests/test_brief_compact_6240.py::test_the_brief_and_the_day_page_read_one_determination``).

A confirmed zero is neither state: a row that IS present (a logging-gap stub, a partial export) is
served as what it is by its own flags (``common.nutrition_logging``), never re-labelled here.

No clock. One read, ``read_freshness`` (the newest ``NEWEST_ROWS`` macrofactor rows), shared by both callers so they
also ask the same question of the table; everything else is pure.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from common.pacific_time import pacific_date_of, shift_day_key

# The arrival stamps a macrofactor row can carry: diary rows, daily-summary rows, projections (#5519).
ARRIVAL_FIELDS = ("ingested_at", "summary_ingested_at", "summary_projected_ingested_at")
# The newest rows read to find the latest export (the read `get_freshness_status` makes).
NEWEST_ROWS = 10

ARRIVED = "arrived"
NOT_ARRIVED = "not_arrived"


def freshness_from_rows(rows: Iterable[dict]) -> Optional[dict]:
    """{"last_arrival_day", "last_intake_day"} from the newest macrofactor rows, or None when no row carries
    an arrival stamp. ``last_arrival_day`` is the Pacific day the newest export LANDED."""
    rows = list(rows or [])
    stamps = [str(r[f]) for r in rows for f in ARRIVAL_FIELDS if r.get(f)]
    days = [d for d in (pacific_date_of(s) for s in stamps) if d]
    if not days:
        return None
    intake = [str(r.get("sk", ""))[5:15] for r in rows if r.get("total_calories_kcal") is not None]
    return {"last_arrival_day": max(days), "last_intake_day": max(intake) if intake else None}


def arrival(day: Any, last_arrival_day: Any) -> Optional[str]:
    """'arrived' (an export landed after `day` ended), 'not_arrived', or None (unknown: no day or no stamp)."""
    if not last_arrival_day or not day:
        return None
    return ARRIVED if str(last_arrival_day) > str(day) else NOT_ARRIVED


def pending_days(days: Iterable[str], intake_days: Iterable[str], last_arrival_day: Any) -> list:
    """The days among `days` with no intake whose export has not arrived (sorted). Empty when the arrival is unknown:
    an unknown arrival claims nothing either way."""
    have = set(intake_days or ())
    return sorted(d for d in set(days or ()) if d not in have and arrival(d, last_arrival_day) == NOT_ARRIVED)


def read_freshness(table, user_prefix: str) -> Optional[dict]:
    """``freshness_from_rows`` over the newest macrofactor rows (raises on a failed read; callers are fail-soft)."""
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(user_prefix + "macrofactor") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=NEWEST_ROWS,
    )
    return freshness_from_rows(resp.get("Items") or [])


def served_block(table, user_prefix: str, first: str, last: str, intake_days: Iterable[str], logger=None) -> dict:
    """The additive ``food_log`` block ``/api/nutrition_overview`` serves (#6240): which days in first..last are PENDING
    (no intake, export not arrived). An unreadable or stampless source serves ``arrival_known: False`` and no pending
    day, so a reader keeps its previous wording rather than guessing either way."""
    try:
        fresh = read_freshness(table, user_prefix)
    except Exception as e:  # noqa: BLE001 — fail-soft: the block says it does not know
        if logger:
            logger.warning("food_log freshness read failed (non-fatal): %s", type(e).__name__)
        fresh = None
    last_arrival = (fresh or {}).get("last_arrival_day")
    days: list = []
    d = str(first)
    while first and last and d <= str(last) and len(days) < 400:
        days.append(d)
        d = shift_day_key(d, 1)
    return {"pending_days": pending_days(days, intake_days, last_arrival), "arrival_known": bool(last_arrival)}
