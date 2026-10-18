"""ingestion/whoop_cycle_day.py — #5002: which Whoop cycle a DATE# day row is filed from.

Split out of whoop_lambda.py (module-size ceiling). Two rules, both about FILING, never about
dropping a vendor field:

  1. ``cycle_for_day`` — a day row for D carries the cycle whose ``start`` falls on the UTC day D
     (the whoop ``day_key_frame`` is "utc", #3913; the day comes from ``whoop_lambda._utc_day``, the
     same ``start``-day rule ``workout_files_under`` applies to workouts, #4629 box 3). The vendor's ``start``/``end`` query returns every cycle that
     OVERLAPS the UTC window [D T00:00Z, D+1 T00:00Z), so before #5002 a still-open cycle that began on
     D-1 came back as ``records[0]`` of D's fetch and was written under D too: DATE#2026-10-18 carried
     cycle 1881434574 (started 2026-10-17T06:08Z) field-for-field — strain 10.82, kilojoule 17068.35,
     step_count 17904, max/avg HR 157/62 — beside DATE#2026-10-17 carrying the same cycle. When no
     cycle starts on D yet, the row carries no cycle fields: an honest partial, nothing copied.

  2. ``drop_cycle_filed_elsewhere`` — the cycle-id guard. The row stores the vendor's ``cycle_id``;
     a row for D whose cycle id already sits under a NEIGHBOURING day row (D-1 or D+1) is refused the
     cycle fields, so one cycle id is never on two day rows even if the vendor re-dates a cycle's
     ``start`` across 00:00Z. The neighbour that holds it keeps it until its own trailing refresh
     stops selecting it (its start day moved), after which D's next run files it. Fail-open on a read
     error: rule 1 still holds, and a lost day row is worse than an unverified one.

Everything here is pure except the one bounded neighbour query.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from boto3.dynamodb.conditions import Key

# Every field ``_extract_cycle`` writes onto the day row — the set the guard removes together.
CYCLE_FIELDS = ("strain", "kilojoule", "average_heart_rate", "max_heart_rate", "step_count", "cycle_id", "cycle_start", "cycle_end")


def cycle_for_day(records: list, date_str: str | None, day_of: Callable[[str | None], str | None]) -> dict | None:
    """The cycle record filed under ``date_str``: the first (the vendor sends newest first) whose
    ``start`` is on the day ``date_str``. ``day_of`` is the writer's OWN key derivation
    (``whoop_lambda._utc_day``, the #3913 UTC frame) — passed in, never re-derived here, so the
    cycle, workout and reconciler keys can never disagree. ``date_str=None`` keeps the pre-#5002
    reading (``records[0]``) for callers that hold one cycle payload with no day attached."""
    records = records or []
    if date_str is None:
        return records[0] if records else None
    return next((r for r in records if day_of(r.get("start")) == date_str), None)


def cycle_identity(record: dict) -> dict:
    """The vendor's own cycle identity, stored as sent (capture-all): id, start, end. ``end`` is
    absent while the cycle is still open — that absence is how a reader sees a partial cycle."""
    out: dict = {}
    if type(cid := record.get("id")) is int:
        out["cycle_id"] = cid
    for name, key in (("cycle_start", "start"), ("cycle_end", "end")):
        if record.get(key):
            out[name] = record[key]
    return out


def cycle_id_filed_elsewhere(table, user_id: str, cycle_id, date_str: str) -> str | None:
    """The neighbouring day (D-1 or D+1) whose stored day row already carries ``cycle_id``, else None."""
    if cycle_id is None:
        return None
    d = datetime.strptime(date_str, "%Y-%m-%d")
    lo, hi = ((d + timedelta(days=n)).strftime("%Y-%m-%d") for n in (-1, 1))
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{user_id}#SOURCE#whoop") & Key("sk").between(f"DATE#{lo}", f"DATE#{hi}~"),
        ProjectionExpression="sk, cycle_id",
    )
    for item in resp.get("Items", []):
        sk = str(item.get("sk", ""))
        if "#WORKOUT#" in sk or sk == f"DATE#{date_str}" or item.get("cycle_id") is None:
            continue
        if int(item["cycle_id"]) == int(cycle_id):
            return sk[len("DATE#") :]
    return None


def drop_cycle_filed_elsewhere(table, user_id: str, normalized: dict, date_str: str, logger) -> None:
    """Remove the cycle fields from ``normalized`` (in place) when its cycle id sits under another day."""
    try:
        other = cycle_id_filed_elsewhere(table, user_id, normalized.get("cycle_id"), date_str)
    except Exception as e:
        logger.warning("[CYCLE-ID] whoop/%s neighbour read failed (start-day rule still applied): %s", date_str, e)
        return
    if other:
        logger.warning(
            "[CYCLE-ID] whoop/%s: cycle %s is already filed under %s — not written twice (#5002)", date_str, normalized["cycle_id"], other
        )
        for name in CYCLE_FIELDS:
            normalized.pop(name, None)
