"""
hevy_backfill_lambda.py — Hourly Hevy workout ingestion via events feed.

Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 §2.2-B, repurposed 2026-05-25:
Hevy does NOT currently offer webhook subscriptions in the public API (the
OpenAPI spec at api.hevyapp.com/docs/ lists no /v1/webhook* endpoints), so
this Lambda is the *primary* ingestion path, not just a safety net.

Architecture (verified against live API + OpenAPI 2026-05-25):
    EventBridge schedule (hourly during waking hours)
      → this Lambda
        → load `since` ISO timestamp from DDB USER#system / INGESTION_STATE#hevy
          (first run: INITIAL_SINCE = 2023-01-01 → pulls all history)
        → GET /v1/workouts/events?since=<iso>&page=N&pageSize=10
        → events come back as {type, workout: {...full workout...}}
          type ∈ {"updated", "deleted"}
        → for type=updated: normalize + idempotent upsert + raw S3 archive
        → for type=deleted: write a tombstone DDB record (if we can locate the date)
        → walk pages 1..page_count
        → on full success, set since = poll-start-time (next run picks up here)

Idempotent: same workout id → upsert, no dupe. Page-based pagination
(NOT cursor) because Hevy's API uses that shape.

The `hevy-webhook` Lambda stays deployed for future Hevy webhook support
but currently never receives traffic.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from hevy_common import (
    INITIAL_SINCE,
    SOURCE,
    USER_ID,
    HevyAPIError,
    _table,
    archive_raw,
    fetch_events_page,
    load_since,
    normalize_workout,
    save_since,
    write_normalized,
)

try:
    from platform_logger import get_logger

    logger = get_logger("hevy-backfill")
except ImportError:
    logger = logging.getLogger("hevy-backfill")
    logger.setLevel(logging.INFO)


# Safety cap. Each page is at most 10 events × max pages = max events per run.
MAX_PAGES_PER_RUN = int(os.environ.get("HEVY_BACKFILL_MAX_PAGES", "30"))
PAGE_SIZE = int(os.environ.get("HEVY_BACKFILL_PAGE_SIZE", "10"))


def _derive_training_notes(rec: dict) -> None:
    """On-ingest hook (training-notes feedback loop): derive the note-signal projection
    right after the raw workout persists. Fully guarded — a derive failure NEVER breaks
    ingestion (the raw workout is already the source of truth). Skips workouts with no
    non-empty notes ($0, no model call). Pain flags elevate (insight + coach thread)."""
    try:
        exercises = rec.get("exercises") or []
        if not any((e.get("notes") or "").strip() for e in exercises):
            return
        import training_notes as tn
        from training_notes_llm import make_llm_fn

        llm_fn = make_llm_fn(_table)
        res = tn.write_workout_notes(_table, rec["date"], rec.get("workout_uid", ""), exercises, llm_fn=llm_fn)
        for it in res.get("items", []):
            if it.get("pain_flag"):
                tn.elevate_pain(_table, it)
        logger.info("training-notes derived %s: %d records, %d pain", rec.get("workout_uid"), res["records"], res["pain"])
    except Exception as e:  # noqa: BLE001
        logger.warning("training-notes derive failed (non-fatal) %s: %s", rec.get("workout_uid"), e)


def _tombstone_deleted(workout_id: str) -> None:
    """Best-effort tombstone for a deleted-event. We don't have the date
    without the full record, so this records a delete marker that the next
    audit pass can reconcile."""
    try:
        _table.put_item(
            Item={
                "pk": f"USER#{USER_ID}#SOURCE#{SOURCE}",
                "sk": f"DELETE#WORKOUT#{workout_id}",
                "tombstone": True,
                "tombstoned_at": datetime.now(timezone.utc).isoformat(),
                "tombstoned_reason": "hevy_event_delete",
            }
        )
        logger.info("hevy delete marker written for %s", workout_id)
    except Exception as e:
        logger.warning("hevy delete-marker write failed for %s: %s", workout_id, e)


def lambda_handler(event: dict, context: Any) -> dict:
    """Scheduled backfill entry point. Polls the events feed since the
    last-known timestamp, ingests new/updated workouts, persists new
    high-water-mark on success."""
    poll_started_at = datetime.now(timezone.utc).isoformat()
    since = load_since()
    is_initial = since == INITIAL_SINCE
    logger.info("hevy backfill starting. since=%s initial=%s", since, is_initial)

    ingested = 0
    deleted = 0
    errors = 0
    failed_ids: list[str] = []
    pages_walked = 0
    total_pages_observed = 0

    try:
        page = 1
        while page <= MAX_PAGES_PER_RUN:
            payload = fetch_events_page(since, page=page, page_size=PAGE_SIZE)
            pages_walked += 1
            total_pages_observed = int(payload.get("page_count", 0))
            events_list = payload.get("events") or []

            if not events_list:
                logger.info("hevy backfill page %d empty; stop", page)
                break

            for ev in events_list:
                ev_type = ev.get("type") or "updated"
                wo = ev.get("workout") or {}
                wid = str(wo.get("id") or "")
                if not wid:
                    logger.warning("hevy event missing workout id: %s", ev)
                    continue

                try:
                    if ev_type == "deleted":
                        _tombstone_deleted(wid)
                        deleted += 1
                    else:
                        # 'updated' covers both newly-created and edited workouts.
                        # The full payload is INLINE in the events feed — no need
                        # to GET /v1/workouts/{id} separately (per OpenAPI shape).
                        archive_raw(wid, ev)
                        rec = normalize_workout(ev)  # accepts {workout:{...}} wrapper
                        write_normalized(rec)
                        _derive_training_notes(rec)  # on-ingest note-signal projection (guarded)
                        ingested += 1
                        logger.info(
                            "hevy backfill ingest %s date=%s phase=%s sets=%d volume=%.2fkg",
                            wid,
                            rec["date"],
                            rec.get("phase", "?"),
                            rec["set_count"],
                            rec["total_volume_kg"],
                        )
                except Exception as e:
                    errors += 1
                    failed_ids.append(wid)
                    logger.exception("hevy backfill event error %s: %s", wid, e)
                    # Don't break the page loop on one bad record — continue

            if total_pages_observed and page >= total_pages_observed:
                logger.info("hevy backfill reached page_count=%d, stop", total_pages_observed)
                break
            page += 1

        # Save new high-water mark only if everything succeeded.
        # On failures we keep the old since so next run retries the failed window.
        if errors == 0:
            save_since(poll_started_at)
            logger.info("hevy backfill since advanced to %s", poll_started_at)
        else:
            logger.warning(
                "hevy backfill had %d error(s); since NOT advanced. Failed ids: %s",
                errors,
                failed_ids[:10],
            )

    except HevyAPIError as e:
        logger.error("hevy backfill fatal API error: %s", e)
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "source": "hevy",
                    "error": str(e),
                    "ingested": ingested,
                    "deleted": deleted,
                    "errors": errors,
                    "pages_walked": pages_walked,
                }
            ),
        }

    summary = {
        "source": "hevy",
        "initial_run": is_initial,
        "since": since,
        "new_since": poll_started_at if errors == 0 else since,
        "ingested": ingested,
        "deleted": deleted,
        "errors": errors,
        "pages_walked": pages_walked,
        "total_pages": total_pages_observed,
        "failed_ids": failed_ids[:10],
    }
    logger.info("hevy backfill complete: %s", json.dumps(summary, default=str))
    return {"statusCode": 200, "body": json.dumps(summary, default=str)}
