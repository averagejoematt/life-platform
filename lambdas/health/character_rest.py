"""character_rest.py — the two inputs the final #6293 amendments read (owner ruling 2026-11-26).

* ``planned_rest_days`` — the dates in a window that are a recorded planned pause: a sick-day record (through
  ``sick_day_checker.get_sick_days_range``, which skips a cleared row, #4378) or a travel log — the set
  ``content.engagement_core`` already excuses as a planned pause. Owner-only: never written to the receipt's input rows,
  and the public method restores a planned-rest Movement day without it.
* ``activity_elsewhere`` — whether a source other than Strava (Hevy, Whoop, the Apple Watch) shows a training session
  on a day, by THE session count (``training.session_count``) over rows the caller already fetched.

Both are read-only and fail soft to "no planned rest" / "no activity" (each only ever relaxes a penalty when it holds).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def planned_rest_days(table: Any, user_id: str, start_date: str, end_date: str) -> list[str]:
    """The sorted dates in [start, end] with a sick-day record (not cleared) or a travel log."""
    days: set[str] = set()
    try:
        from health.sick_day_checker import get_sick_days_range

        days |= {str(r.get("date"))[:10] for r in get_sick_days_range(table, user_id, start_date, end_date) if r.get("date")}
    except Exception as e:  # noqa: BLE001 — fail soft: no planned rest found
        logger.warning("[character] planned-rest sick-day read failed (non-fatal): %s", e)
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": f"USER#{user_id}#SOURCE#travel", ":s": "DATE#" + start_date, ":e": "DATE#" + end_date + "~"},
        )
        days |= {str(i.get("sk", "")).replace("DATE#", "")[:10] for i in resp.get("Items", [])}
    except Exception as e:  # noqa: BLE001
        logger.warning("[character] planned-rest travel read failed (non-fatal): %s", e)
    return sorted(d for d in days if start_date <= d <= end_date)


def activity_elsewhere(data: dict[str, Any], day: str) -> bool:
    """Whether Hevy, Whoop or the Apple Watch shows a training session on ``day`` (the 7-day rows on ``data``)."""
    try:
        from training import session_count

        week = session_count.count(
            hevy=data.get("hevy_7d"), whoop=data.get("whoop_7d"), apple=data.get("apple_7d"), start_date=day, end_date=day
        )
        return bool(week.get("sessions"))
    except Exception as e:  # noqa: BLE001 — a count that cannot run is no evidence of activity
        logger.warning("[character] activity_elsewhere(%s) failed (non-fatal): %s", day, e)
        return False
