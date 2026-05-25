"""
hevy_backfill_lambda.py — Scheduled Hevy workout backfill via events cursor.

Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 §2.2-B:
    EventBridge schedule (daily 13:00 UTC = 06:00 PT)
      → this Lambda
        → GET /v1/workouts/events?since={cursor} (cursor from DDB)
        → for each event in feed: fetch the workout, normalize, idempotent upsert
        → persist new cursor on success

This is the self-healing safety net for webhook drops — directly relevant to
the "absence" principle in the spec: if a webhook fires into the void while
Matthew is off-grid, the next backfill reconstructs the gap. Idempotent
because workout ids are stable.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from hevy_common import (
    HevyAPIError,
    fetch_events_since,
    fetch_workout,
    archive_raw,
    normalize_workout,
    write_normalized,
    load_cursor,
    save_cursor,
)

try:
    from platform_logger import get_logger
    logger = get_logger("hevy-backfill")
except ImportError:
    logger = logging.getLogger("hevy-backfill")
    logger.setLevel(logging.INFO)


# Safety cap: never process more than this many events per invocation. Keeps
# Lambda runtime + Hevy API usage bounded if the cursor is far behind.
MAX_EVENTS_PER_RUN = int(os.environ.get("HEVY_BACKFILL_MAX_EVENTS", "100"))


def _extract_event_workout_id(event_obj: dict) -> str | None:
    """Pull workout id from a single events-feed entry. Liberal parser."""
    if not isinstance(event_obj, dict):
        return None
    for k in ("workoutId", "workout_id", "id"):
        if k in event_obj and event_obj[k]:
            return str(event_obj[k])
    sub = event_obj.get("workout")
    if isinstance(sub, dict):
        for k in ("id", "workoutId", "workout_id"):
            if k in sub and sub[k]:
                return str(sub[k])
    return None


def _events_from_payload(payload: dict) -> list[dict]:
    """Hevy may name the events list `events`, `data`, or `items`. Be liberal."""
    if not isinstance(payload, dict):
        return []
    for k in ("events", "data", "items"):
        if isinstance(payload.get(k), list):
            return payload[k]
    return []


def _next_cursor_from_payload(payload: dict) -> str | None:
    """Pull next-page cursor from response. None if no more pages."""
    if not isinstance(payload, dict):
        return None
    for k in ("next_cursor", "nextCursor", "cursor", "next"):
        v = payload.get(k)
        if v:
            return str(v)
    return None


def lambda_handler(event: dict, context: Any) -> dict:
    """Scheduled backfill entry point."""
    cursor = load_cursor()
    logger.info("hevy backfill starting. cursor=%s", cursor)

    processed = 0
    errors = 0
    failed_ids: list[str] = []
    new_cursor = cursor
    pages = 0
    last_event_id: str | None = None

    try:
        while processed < MAX_EVENTS_PER_RUN:
            payload = fetch_events_since(new_cursor)
            pages += 1
            events_list = _events_from_payload(payload)
            if not events_list:
                logger.info("hevy backfill — no events on page %d, done", pages)
                break

            for ev in events_list:
                if processed >= MAX_EVENTS_PER_RUN:
                    break
                wid = _extract_event_workout_id(ev)
                if not wid:
                    continue
                event_type = ev.get("type") or ev.get("event") or "updated"
                # Deletion handling: if Hevy ever emits a delete event, we
                # tombstone rather than re-fetch. For now: treat all events
                # as upserts (fetch + write).
                try:
                    if event_type in ("deleted", "delete"):
                        # Tombstone in place; no S3 archive needed
                        from hevy_common import _table  # type: ignore[attr-defined]
                        from datetime import datetime, timezone
                        # We don't know the date from a delete event alone; mark with the workout
                        # id and rely on a manual cleanup later if needed.
                        _table.update_item(
                            Key={
                                "pk": f"USER#matthew#SOURCE#hevy",
                                # SK requires date — skip deletion handling for v1; log only
                                "sk": f"DELETE#WORKOUT#{wid}",
                            },
                            UpdateExpression=(
                                "SET tombstone=:t, tombstoned_at=:ts, "
                                "tombstoned_reason=:r"
                            ),
                            ExpressionAttributeValues={
                                ":t": True,
                                ":ts": datetime.now(timezone.utc).isoformat(),
                                ":r": "hevy_event_delete",
                            },
                        )
                        logger.info("hevy backfill — marked tombstone for %s", wid)
                    else:
                        raw = fetch_workout(wid)
                        archive_raw(wid, raw)
                        rec = normalize_workout(raw)
                        write_normalized(rec)
                        logger.info(
                            "hevy backfill ingest %s date=%s sets=%d",
                            wid, rec["date"], rec["set_count"],
                        )
                    processed += 1
                    last_event_id = wid
                except HevyAPIError as e:
                    errors += 1
                    failed_ids.append(wid)
                    logger.warning("hevy backfill HevyAPIError %s: %s", wid, e)
                    # Don't advance cursor over a failure — let the next run retry
                    break
                except Exception as e:
                    errors += 1
                    failed_ids.append(wid)
                    logger.exception("hevy backfill error %s: %s", wid, e)
                    break

            # Move cursor to end of this page if everything succeeded
            new_cursor = _next_cursor_from_payload(payload) or new_cursor
            if not new_cursor or new_cursor == cursor:
                # No further pages
                break
            if errors > 0:
                # Stop advancing on error — retry from the failure point next run
                break

        if last_event_id and errors == 0 and new_cursor:
            save_cursor(new_cursor)
            logger.info("hevy backfill cursor advanced to %s", new_cursor)
    except HevyAPIError as e:
        logger.error("hevy backfill fatal API error: %s", e)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "source": "hevy",
                "error": str(e),
                "processed": processed,
                "errors": errors,
            }),
        }

    summary = {
        "source": "hevy",
        "processed": processed,
        "errors": errors,
        "pages": pages,
        "old_cursor": cursor,
        "new_cursor": new_cursor,
        "failed_ids": failed_ids[:10],
    }
    logger.info("hevy backfill complete: %s", json.dumps(summary, default=str))
    return {"statusCode": 200, "body": json.dumps(summary, default=str)}
