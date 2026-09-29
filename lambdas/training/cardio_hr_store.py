"""training/cardio_hr_store.py — where the #4412 cardio-HR join is read from and written to.

The join itself is `training.cardio_hr` (pure). This module is its two I/O seams, both run by
the hourly `hevy-backfill` poller (the Hevy ingest path):

  * ON INGEST — `attach(table, rec)` joins the workout against the Strava partitions of its day
    and the next (an evening session crosses UTC midnight) and embeds `cardio_hr` in the record
    BEFORE the idempotent put, exactly as `adherence` is embedded (#412).
  * THE REJOIN — the wearable usually lands AFTER the Hevy session: WHOOP pushes to Strava on
    its own schedule and Strava is pulled hourly, so at ingest the block is commonly `unknown`.
    `rejoin_recent(table, today)` re-derives the last `REJOIN_DAYS` days' workouts every run and
    UpdateItems `cardio_hr` ONLY when the derivation changed (no churn on an unchanged record).

Every read failure degrades to `unknown` (the Strava partition could not be read) — never a
failed ingest, never 0 bpm.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Optional

from common.pacific_time import parse_day_key, shift_day_key
from common.strava_read_seam import strava_read_seam

from training import cardio_hr

logger = logging.getLogger("hevy-backfill")

REJOIN_DAYS = 2  # today + yesterday (Pacific): long enough for the WHOOP → Strava lag, short enough to stay cheap
_STRAVA_PK = "USER#{user}#SOURCE#strava"
_HEVY_PK = "USER#{user}#SOURCE#hevy"  # the rejoin reads ONLY Hevy workouts — never a caller-chosen partition


def _strava_activities(table: Any, user: str, day: str) -> Optional[list[dict[str, Any]]]:
    """Activities on the Strava partitions of `day` and `day + 1`; None when a read failed."""
    acts: list[dict[str, Any]] = []
    try:
        for d in (day, shift_day_key(day, 1)):
            item = table.get_item(Key={"pk": _STRAVA_PK.format(user=user), "sk": f"DATE#{d}"}).get("Item") or {}
            item = strava_read_seam("strava", item) or {}  # #4419: one WHOOP+Garmin session, one activity
            acts.extend(item.get("activities") or [])
    except Exception as e:  # noqa: BLE001 — a failed read is `unknown`, never a failed ingest
        logger.warning("cardio-hr strava read failed for %s: %s: %s", day, type(e).__name__, e)
        return None
    return acts


def derive(table: Any, user: str, rec: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The `cardio_hr` value for one normalized Hevy record, or None when it has no cardio block."""
    if not any(cardio_hr.cardio_modality(ex) for ex in rec.get("exercises") or []):
        return None
    day = str(rec.get("date") or "")[:10]
    return cardio_hr.join_workout(rec, _strava_activities(table, user, day) if parse_day_key(day) else None)


def attach(table: Any, user: str, rec: dict[str, Any]) -> None:
    """Embed `cardio_hr` in `rec` before its write (guarded — a join error never breaks ingest)."""
    try:
        joined = derive(table, user, rec)
        if joined:
            rec["cardio_hr"] = joined
            logger.info(
                "cardio-hr %s: %s", rec.get("workout_uid"), [(b["modality"], b["state"], b.get("hr_coverage")) for b in joined["blocks"]]
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("cardio-hr attach failed (non-fatal) %s: %s", rec.get("workout_uid"), e)


def _plain(v: Any) -> Any:
    """A DDB Decimal as the int/float the join produced, so a stored record compares equal to a re-derivation."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _same(a: Any, b: Any) -> bool:
    return json.dumps(_plain(a), sort_keys=True) == json.dumps(_plain(b), sort_keys=True)


def rejoin_recent(table: Any, user: str, today: str) -> dict[str, int]:
    """Re-derive `cardio_hr` for the last REJOIN_DAYS Pacific days; write only what changed."""
    from boto3.dynamodb.conditions import Key
    from common.numeric import floats_to_decimal

    start = shift_day_key(today, -(REJOIN_DAYS - 1))
    out = {"considered": 0, "updated": 0, "joined": 0, "errors": 0}
    try:
        items = table.query(
            KeyConditionExpression=Key("pk").eq(_HEVY_PK.format(user=user)) & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
        ).get("Items", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("cardio-hr rejoin query failed: %s: %s", type(e).__name__, e)
        out["errors"] += 1
        return out
    for item in items:
        if "#WORKOUT#" not in str(item.get("sk")):
            continue
        try:
            joined = derive(table, user, item)
            if joined is None:
                continue
            out["considered"] += 1
            out["joined"] += sum(1 for b in joined["blocks"] if b.get("state") == "joined")
            if _same(joined, item.get("cardio_hr")):
                continue
            table.update_item(
                Key={"pk": item["pk"], "sk": item["sk"]},
                UpdateExpression="SET cardio_hr = :c",
                ConditionExpression="attribute_exists(sk)",  # never resurrect a workout deleted mid-run
                ExpressionAttributeValues={":c": floats_to_decimal(joined)},
            )
            out["updated"] += 1
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1
            logger.warning("cardio-hr rejoin failed for %s: %s: %s", item.get("sk"), type(e).__name__, e)
    return out
