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

  * ONE WORKOUT — `rejoin_one(table, user, day, workout_id)` re-derives a single named workout
    outside the two-day window (the hevy-backfill `{"rejoin_workout": id, "date": day}` event),
    with the same write-only-on-change rule. It writes nothing but the `cardio_hr` attribute.

The join reads BOTH the Strava day items and the WHOOP workout rows (#4412: WHOOP pushes only
some workouts to Strava). A read failure on one degrades to the other; on both, `unknown` —
never a failed ingest, never 0 bpm.
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
_WHOOP_PK = "USER#{user}#SOURCE#whoop"
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


def _whoop_workouts(table: Any, user: str, day: str) -> Optional[list[dict[str, Any]]]:
    """WHOOP `#WORKOUT#` rows on the WHOOP partitions of `day` and `day + 1`; None when a read failed."""
    from boto3.dynamodb.conditions import Key

    rows: list[dict[str, Any]] = []
    try:
        for d in (day, shift_day_key(day, 1)):
            rows.extend(
                table.query(
                    KeyConditionExpression=Key("pk").eq(_WHOOP_PK.format(user=user)) & Key("sk").begins_with(f"DATE#{d}#WORKOUT#"),
                ).get("Items", [])
            )
    except Exception as e:  # noqa: BLE001 — a failed read is `unknown`, never a failed ingest
        logger.warning("cardio-hr whoop read failed for %s: %s: %s", day, type(e).__name__, e)
        return None
    return rows


def derive(table: Any, user: str, rec: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The `cardio_hr` value for one normalized Hevy record, or None when it has no cardio block."""
    if not any(cardio_hr.cardio_modality(ex) for ex in rec.get("exercises") or []):
        return None
    day = str(rec.get("date") or "")[:10]
    if not parse_day_key(day):
        return cardio_hr.join_workout(rec, None, None)
    return cardio_hr.join_workout(rec, _strava_activities(table, user, day), _whoop_workouts(table, user, day))


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
            _rejoin_item(table, user, item, out)
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1
            logger.warning("cardio-hr rejoin failed for %s: %s: %s", item.get("sk"), type(e).__name__, e)
    return out


def _rejoin_item(table: Any, user: str, item: dict[str, Any], out: dict[str, int]) -> Optional[dict[str, Any]]:
    """Re-derive one stored Hevy row and SET only `cardio_hr`, only when it changed. Returns the derivation."""
    from common.numeric import floats_to_decimal

    joined = derive(table, user, item)
    if joined is None:
        return None
    out["considered"] += 1
    out["joined"] += sum(1 for b in joined["blocks"] if b.get("state") == "joined")
    if _same(joined, item.get("cardio_hr")):
        return joined
    table.update_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        UpdateExpression="SET cardio_hr = :c",
        ConditionExpression="attribute_exists(sk)",  # never resurrect a workout deleted mid-run
        ExpressionAttributeValues={":c": floats_to_decimal(joined)},
    )
    out["updated"] += 1
    return joined


def rejoin_one(table: Any, user: str, day: str, workout_id: str) -> dict[str, Any]:
    """Re-derive `cardio_hr` for ONE named Hevy workout (`DATE#{day}#WORKOUT#{workout_id}`). Idempotent."""
    out: dict[str, Any] = {"considered": 0, "updated": 0, "joined": 0, "errors": 0, "found": False}
    if not parse_day_key(day) or not workout_id or "#" in workout_id:
        out.update(errors=1, reason="date must be YYYY-MM-DD and workout id a bare Hevy id")
        return out
    key = {"pk": _HEVY_PK.format(user=user), "sk": f"DATE#{day}#WORKOUT#{workout_id}"}
    item = table.get_item(Key=key).get("Item")
    if not item:
        out["reason"] = f"no Hevy workout at {key['sk']}"
        return out
    out["found"] = True
    joined = _rejoin_item(table, user, item, out)
    out["blocks"] = [
        {k: b.get(k) for k in ("exercise_index", "name", "state", "hr_coverage", "avg_hr", "max_hr", "hr_source", "reason")}
        for b in (joined or {}).get("blocks", [])
    ]
    return out
