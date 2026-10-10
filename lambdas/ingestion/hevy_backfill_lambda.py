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
          (a start-time edit RELOCATES the record — the old-date sk is cleaned
          up inside write_normalized, #475)
        → for type=deleted: write a DELETE#WORKOUT#{id} tombstone marker
        → resolve_tombstones() consumes unresolved markers every run (#475):
          the workout record is deleted, the marker stamped resolved (audit)
        → walk pages 1..page_count (capped at MAX_PAGES_PER_RUN)
        → on a COMPLETE, error-free walk, set since = poll-start-time; a
          truncated walk keeps the old since so nothing is silently skipped
          (and, #4643, records a FAILED run so a permanent truncation is visible)
        → an event failing on QUARANTINE_AFTER consecutive runs is quarantined
          (QUARANTINE#WORKOUT#<id>) and stops holding the cursor (#4643)
        → a 401/403 latches the shared auth breaker for 24h (#4643)

Idempotent: same workout id → upsert, no dupe. Page-based pagination
(NOT cursor) because Hevy's API uses that shape.

The `hevy-webhook` Lambda stays deployed for future Hevy webhook support
but currently never receives traffic.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from training import cardio_hr_store
from training.hevy_common import (
    INITIAL_SINCE,
    SOURCE,
    USER_ID,
    HevyAPIError,
    _table,
    archive_raw,
    fetch_events_page,
    load_since,
    normalize_workout,
    resolve_tombstones,
    save_since,
    write_normalized,
)

# #466 (X-1): the ER-01 liveness sentinel. Hevy is pattern-exempt (no
# run_ingestion), so without this the ingest-consecutive-failures-hevy alarm
# watches a metric that never exists. Optional import — ingestion never breaks
# if the layer module is absent.
try:
    from ingestion.ingest_health import classify_error
    from ingestion.ingestion_framework import record_ingest_health

    _INGEST_HEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover — layer-module fallback
    _INGEST_HEALTH_AVAILABLE = False

# #4643: the auth circuit breaker. The registry has declared hevy `oauth: True` ("routes
# through auth_breaker") since #1960, so `ingest-auth-unhealthy-hevy` exists — but nothing
# here ever wrote the marker or emitted IngestAuthHealthy, and a revoked key failed every
# hourly run three times (two async retries) into the dead-letter queue. With the breaker
# the first failure latches the marker and the async retries short-circuit to a 200 skip.
try:
    from common.auth_breaker import check_breaker, clear_failure, mark_failure

    _HAS_AUTH_BREAKER = True
except ImportError:  # pragma: no cover — bundle fallback
    _HAS_AUTH_BREAKER = False

try:
    from common.platform_logger import get_logger

    logger = get_logger("hevy-backfill")
except ImportError:
    logger = logging.getLogger("hevy-backfill")
    logger.setLevel(logging.INFO)


# Safety cap. Each page is at most 10 events × max pages = max events per run.
MAX_PAGES_PER_RUN = int(os.environ.get("HEVY_BACKFILL_MAX_PAGES", "30"))
PAGE_SIZE = int(os.environ.get("HEVY_BACKFILL_PAGE_SIZE", "10"))

#: #4643: HTTP codes that mean the API key is dead (401 revoked/invalid, 403 the account
#: lost API access). Read from HevyAPIError.status, never parsed out of the message.
_AUTH_STATUSES = (401, 403)

#: #4643: one event that fails on this many CONSECUTIVE runs is quarantined — recorded
#: under QUARANTINE#WORKOUT#<id> and no longer allowed to hold the cursor. Before this, one
#: permanently failing event froze `since` forever: every hourly run re-walked the same
#: window, failed the same event, and never advanced, while newer workouts were still
#: ingested (idempotent upserts) so nothing downstream looked wrong.
QUARANTINE_AFTER = int(os.environ.get("HEVY_QUARANTINE_AFTER", "3"))
QUARANTINE_SK_PREFIX = "QUARANTINE#WORKOUT#"


def _is_auth_failure(exc: Exception) -> bool:
    """A Hevy call that failed BECAUSE OF the credential (#4643)."""
    return getattr(exc, "status", None) in _AUTH_STATUSES


def _load_event_failures() -> dict | None:
    """Every QUARANTINE#WORKOUT# record, keyed by workout id — one query per run.

    Returns None when the read fails. None means "cannot count", and the caller then
    treats every event failure as cursor-blocking, exactly as before #4643: quarantine
    is the one path that lets an event be skipped, so it must fail CLOSED.
    """
    try:
        from boto3.dynamodb.conditions import Key

        kwargs: dict = {
            "KeyConditionExpression": Key("pk").eq(f"USER#{USER_ID}#SOURCE#{SOURCE}") & Key("sk").begins_with(QUARANTINE_SK_PREFIX)
        }
        out: dict = {}
        while True:
            resp = _table.query(**kwargs)
            for it in resp.get("Items", []):
                wid = str(it.get("workout_id") or str(it.get("sk", ""))[len(QUARANTINE_SK_PREFIX) :])  # noqa: E203
                out[wid] = it
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                return out
            kwargs["ExclusiveStartKey"] = lek
    except Exception as e:  # noqa: BLE001
        logger.warning("hevy quarantine read failed — every event failure blocks the cursor this run: %s: %s", type(e).__name__, e)
        return None


def _note_event_failure(wid: str, ev_type: str, exc: Exception, prior: dict | None) -> bool:
    """Count one more consecutive failure for `wid`; return True when it is now quarantined.

    The record deliberately carries NO `source_workout_id` and sorts after every DATE# key
    ('Q' > 'D'), the same two properties the DELETE#WORKOUT# markers rely on to stay out of
    every date-range read. A failed write returns False — the event then blocks the cursor,
    never the other way round.
    """
    now = datetime.now(timezone.utc).isoformat()
    prior = prior or {}
    count = int(prior.get("fail_count") or 0) + 1
    quarantined = bool(prior.get("quarantined")) or count >= QUARANTINE_AFTER
    item = {
        "pk": f"USER#{USER_ID}#SOURCE#{SOURCE}",
        "sk": f"{QUARANTINE_SK_PREFIX}{wid}",
        "workout_id": wid,
        "event_type": ev_type,
        "fail_count": count,
        "first_failed_at": prior.get("first_failed_at") or now,
        "last_failed_at": now,
        "last_error": f"{type(exc).__name__}: {exc}"[:500],
        "quarantined": quarantined,
    }
    if quarantined:
        item["quarantined_at"] = prior.get("quarantined_at") or now
    try:
        _table.put_item(Item=item)
    except Exception as e:  # noqa: BLE001
        logger.warning("hevy failure-count write failed for %s (event keeps blocking the cursor): %s", wid, e)
        return False
    if quarantined:
        logger.error(
            "hevy event %s QUARANTINED after %d consecutive failing runs — the cursor may advance past it. "
            "Inspect sk=%s%s; re-ingest by editing the workout in Hevy once fixed. Last error: %s",
            wid,
            count,
            QUARANTINE_SK_PREFIX,
            wid,
            item["last_error"],
        )
    return quarantined


def _clear_event_failure(wid: str) -> None:
    """The event processed cleanly — its failure streak (or quarantine) is over."""
    try:
        _table.delete_item(Key={"pk": f"USER#{USER_ID}#SOURCE#{SOURCE}", "sk": f"{QUARANTINE_SK_PREFIX}{wid}"})
    except Exception as e:  # noqa: BLE001
        logger.warning("hevy failure-count clear failed for %s: %s", wid, e)


def _derive_training_notes(rec: dict) -> None:
    """On-ingest hook (training-notes feedback loop): derive the note-signal projection
    right after the raw workout persists. Fully guarded — a derive failure NEVER breaks
    ingestion (the raw workout is already the source of truth). Skips workouts with no
    non-empty notes ($0, no model call). Pain flags elevate (insight + coach thread)."""
    try:
        exercises = rec.get("exercises") or []
        if not any((e.get("notes") or "").strip() for e in exercises):
            return
        from training import training_notes as tn
        from training.training_notes_llm import make_llm_fn

        llm_fn = make_llm_fn(_table, lane="live")  # #4151: the on-ingest path owns the live lane
        res = tn.write_workout_notes(_table, rec["date"], rec.get("workout_uid", ""), exercises, llm_fn=llm_fn)
        for it in res.get("items", []):
            if it.get("pain_flag"):
                tn.elevate_pain(_table, it)
        logger.info("training-notes derived %s: %d records, %d pain", rec.get("workout_uid"), res["records"], res["pain"])
    except Exception as e:  # noqa: BLE001
        logger.warning("training-notes derive failed (non-fatal) %s: %s", rec.get("workout_uid"), e)


def _attach_adherence(rec: dict, raw_workout: dict) -> None:
    """#412 training-truth: compute programmed-vs-performed adherence and embed it in
    the workout record BEFORE it is written, so it persists in the same idempotent
    put_item and self-heals on every re-ingest. Fully guarded — a derive error must
    NEVER break ingestion (mirrors _derive_training_notes). `raw_workout` is the RAW
    Hevy item (its per-exercise template ids survive; the normalized rec renames them),
    so the Hevy-schema knowledge stays inside adherence_calc, not in this lambda."""
    try:
        from health import adherence_calc

        adh = adherence_calc.derive_adherence(raw_workout)
        if adh:
            rec["adherence"] = adh
            logger.info("hevy adherence %s: status=%s pct=%s", rec.get("workout_uid"), adh.get("status"), adh.get("overall_pct"))
    except Exception as e:  # noqa: BLE001
        logger.warning("adherence attach failed (non-fatal) %s: %s", rec.get("workout_uid"), e)


def _rejoin_cardio_hr() -> dict:
    """#4412: re-derive the cardio-HR join for recent workouts (guarded — never fails the run)."""
    try:
        from common.pacific_time import pacific_now

        return cardio_hr_store.rejoin_recent(_table, USER_ID, pacific_now().date().isoformat())
    except Exception as e:  # noqa: BLE001
        logger.warning("cardio-hr rejoin failed (non-fatal): %s: %s", type(e).__name__, e)
        return {"errors": 1}


def _record_health(*, attempted: bool, succeeded: bool, exc) -> None:
    """Write the ER-01 INGEST_HEALTH sentinel + EMF metric (best-effort).

    `exc` is None (clean run), an exception (fatal API error → classified), or
    an error-class string (per-event transform failures → 'parse')."""
    if not _INGEST_HEALTH_AVAILABLE:
        return
    if exc is None:
        error_class = "none"
    elif isinstance(exc, str):
        error_class = exc
    else:
        error_class = classify_error(exc)
    record_ingest_health(_table, SOURCE, logger, attempted=attempted, succeeded=succeeded, error_class=error_class)


def _tombstone_deleted(workout_id: str) -> None:
    """Durable tombstone for a deleted-event. The marker is the retryable state;
    hevy_common.resolve_tombstones() — called at the end of every run (#475 /
    C-7, the consumer the old 'next audit pass' comment promised) — deletes the
    matching WORKOUT# record(s) and stamps the marker resolved. A failed write
    RAISES so the run counts an error and the cursor does not advance past the
    delete event (retried next poll)."""
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


#: Namespace + metric for the rebuild heartbeat (#3764). Emitted ONLY on a write that
#: actually happened, which is what makes the alarm behind it a dead-man rather than an
#: error alarm — see `_emit_rebuilt` and `HevyTemplateIndexStale` in the ingestion stack.
INDEX_METRIC_NAMESPACE = "LifePlatform/HevyRoutine"
INDEX_REBUILT_METRIC = "TemplateIndexRebuilt"


def _emit_rebuilt(count: int) -> None:
    """Emit the heartbeat for a rebuild that really published a new index.

    Deliberately best-effort: a CloudWatch blip must not turn a successful rebuild into a
    failed run. The cost of a dropped datapoint is one day of a two-day alarm window, and
    the alarm needs both days empty before it fires.
    """
    try:
        import boto3

        boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2")).put_metric_data(
            Namespace=INDEX_METRIC_NAMESPACE,
            MetricData=[{"MetricName": INDEX_REBUILT_METRIC, "Value": 1, "Unit": "Count"}],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("template index heartbeat emit failed: %s: %s", type(e).__name__, e)


def rebuild_template_index() -> dict:
    """Republish config/hevy_template_index.json from the live Hevy catalogue (#3764).

    Emits `TemplateIndexRebuilt` on success and on success only. Every way this job can
    fail ends in the SAME observable state — a `config/hevy_template_index.json` whose
    `_built_at` stops moving — and none of them raises: the rule could stop firing, the
    Hevy walk could 429, or `rebuild()` could refuse a shrink and return `written: False`.
    A Lambda Errors alarm sees none of those three, because this function swallows its own
    failure by design (below). So the thing worth watching is not the error, it is the
    ABSENCE of the success, and that is what the heartbeat carries.
    """
    from training import hevy_template_cache as cache, hevy_template_index as idx, hevy_write_client as wc

    try:
        out = idx.rebuild(wc.list_templates, cache._write_s3_json, cache._read_s3_json)
        logger.info("template index rebuild: %s", out)
        if out.get("written"):
            _emit_rebuilt(int(out.get("count") or 0))
        else:
            # A refused shrink is not an exception, but it IS a day the index did not
            # move. No heartbeat, so the dead-man counts it like any other silent miss.
            logger.warning("template index NOT rebuilt: %s", out.get("reason") or out.get("error"))
        return out
    except Exception as e:  # noqa: BLE001
        # Never fail the function over the index: the resolver's live-walk fallback still
        # answers, it is just slower. A failed rebuild is a log line, not an outage.
        logger.error("template index rebuild failed: %s: %s", type(e).__name__, e)
        return {"written": False, "error": f"{type(e).__name__}: {e}"}


def reextract_training_notes(days: int) -> dict:
    """Re-run the note extractor over already-ingested workouts (#3768).

    The on-ingest hook only fires when a workout ARRIVES. When the extractor itself was
    broken — as it was from the day it shipped until the Bedrock grant landed — every
    note in the window was written with `degraded: true` and deterministic signals only,
    and no future ingest will ever revisit them. This re-reads the raw partition and
    re-derives, which is safe and idempotent: `write_workout_notes` is keyed by
    workout+exercise and the LLM tail is hash-cached, so an unchanged note that already
    extracted cleanly costs nothing and a degraded one is repaired.

    #3816: "idempotent" used to mean "re-puts the same key". It now means NO WRITE at
    all when the extraction is unchanged — this fires on every hevy-backfill invoke, so
    a re-put churned `extracted_at` on records nobody re-derived. When the extraction
    DOES change, the prior is archived first and the new head carries `supersedes`; a
    repair is visible as a repair instead of replacing the past in place.

    Bounded by the same monthly Haiku cap as the live path — a breach degrades exactly
    as before rather than failing the run.
    """
    from boto3.dynamodb.conditions import Key
    from common.pacific_time import pacific_now
    from training import training_notes as tn
    from training.training_notes_llm import make_llm_fn

    # Day arithmetic in the Pacific frame, with no hand-rolled ISO parse (#3609): the
    # window is calendar days, and `pacific_now()` is the one place that frame is defined.
    _end_day = pacific_now().date()
    end = _end_day.isoformat()
    start = (_end_day - timedelta(days=days)).isoformat()
    resp = _table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#{SOURCE}") & Key("sk").between(f"DATE#{start}", f"DATE#{end}~"),
    )
    # #4151: a sweep charges the BULK lane's monthly counter, never the live one — the
    # 2026-09-19 historical pass spent the shared month and every new session degraded.
    llm_fn = make_llm_fn(_table, lane="bulk")
    workouts = 0
    records = 0
    wrote = 0
    skipped = 0
    versioned = 0
    for item in resp.get("Items", []):
        exercises = item.get("exercises") or []
        if not any((e.get("notes") or "").strip() for e in exercises):
            continue
        try:
            res = tn.write_workout_notes(_table, item.get("date"), item.get("workout_uid", ""), exercises, llm_fn=llm_fn)
            workouts += 1
            records += res.get("records", 0)
            wrote += res.get("wrote", 0)
            skipped += res.get("skipped", 0)
            versioned += res.get("versioned", 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("re-extract failed for %s: %s: %s", item.get("workout_uid"), type(e).__name__, e)
    # #3816: `records` is how many notes were CONSIDERED; it was never how many rows
    # moved. The three counters below are the ones that say what this run did to the
    # stored past — `versioned` is the number of records whose signals a re-derivation
    # changed, and every one of them has its prior archived and readable by key.
    out = {
        "reextracted_workouts": workouts,
        "records": records,
        "wrote": wrote,
        "skipped_unchanged": skipped,
        "versioned": versioned,
        "window": f"{start}..{end}",
    }
    logger.info("training-notes re-extract: %s", out)
    return out


def lambda_handler(event: dict, context: Any) -> dict:
    """Scheduled backfill entry point. Polls the events feed since the
    last-known timestamp, ingests new/updated workouts, persists new
    high-water-mark on success."""
    # #3764: the template index has a producer now. Runs on its own daily EventBridge
    # rule with this constant input — the index was built by hand once on 2026-06-01 and
    # had drifted 789 vs 828 live by 2026-09-13, every missing title costing a live walk.
    if event and event.get("rebuild_template_index"):
        return rebuild_template_index()

    # #3768: one-shot repair mode. `{"reextract_days": N}` re-derives the note layer for
    # the last N days instead of polling the events feed — the window the extractor was
    # dark for has already been ingested, so nothing else would ever revisit it.
    if event and event.get("reextract_days"):
        return reextract_training_notes(int(event["reextract_days"]))

    # #4412: re-derive the cardio-HR join for ONE named workout (outside the hourly two-day
    # window) — `{"rejoin_workout": "<hevy id>", "date": "YYYY-MM-DD"}`. Writes only `cardio_hr`,
    # only when the derivation changed; a second invoke writes nothing.
    if event and event.get("rejoin_workout"):
        res = cardio_hr_store.rejoin_one(_table, USER_ID, str(event.get("date") or ""), str(event["rejoin_workout"]))
        logger.info("cardio-hr rejoin_workout: %s", json.dumps(res, default=str))
        return {"statusCode": 200, "body": json.dumps(res, default=str)}

    # #4643: a latched auth breaker short-circuits the poll for 24h. This is also what the
    # two async retries of the run that latched it land on, so they return 200 instead of
    # failing into the dead-letter queue. The skip is a continued FAILURE for liveness —
    # the streak grows with zero data, the running-but-dead case (notion's idiom).
    if _HAS_AUTH_BREAKER:
        marker = check_breaker(_table, source_name=SOURCE, user_id=USER_ID, logger=logger)
        if marker:
            logger.warning(
                "auth_breaker_skip source=hevy marked_at=%s error=%s", marker.get("marked_at"), str(marker.get("error", ""))[:80]
            )
            _record_health(attempted=True, succeeded=False, exc="auth")
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "source": "hevy",
                        "skipped": "auth_failure_circuit_breaker",
                        "marked_at": marker.get("marked_at"),
                        "error": marker.get("error"),
                    },
                    default=str,
                ),
            }

    poll_started_at = datetime.now(timezone.utc).isoformat()
    since = load_since()
    is_initial = since == INITIAL_SINCE
    logger.info("hevy backfill starting. since=%s initial=%s", since, is_initial)

    ingested = 0
    deleted = 0
    errors = 0
    blocking_errors = 0  # #4643: errors that hold the cursor (a quarantined event does not)
    failed_ids: list[str] = []
    quarantined_ids: list[str] = []
    pages_walked = 0
    total_pages_observed = 0
    truncated = False
    event_failures = _load_event_failures()

    try:
        page = 1
        while page <= MAX_PAGES_PER_RUN:
            payload = fetch_events_page(since, page=page, page_size=PAGE_SIZE)
            if page == 1 and _HAS_AUTH_BREAKER:
                # An authenticated page succeeding IS the proof the key works — clear here
                # (emits IngestAuthHealthy=1) so a quiet hour also feeds the alarm's recovery.
                clear_failure(_table, source_name=SOURCE, user_id=USER_ID, logger=logger)
            pages_walked += 1
            total_pages_observed = int(payload.get("page_count", 0))
            events_list = payload.get("events") or []

            if not events_list:
                logger.info("hevy backfill page %d empty; stop", page)
                break

            for ev in events_list:
                ev_type = ev.get("type") or "updated"
                wo = ev.get("workout") or {}
                # Deleted events may carry the id at event level ({type, id,
                # deleted_at}) rather than a full workout object — accept both.
                wid = str(wo.get("id") or ev.get("id") or "")
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
                        _attach_adherence(rec, ev.get("workout") or ev)  # #412 pushed-vs-performed (guarded, pre-write)
                        cardio_hr_store.attach(_table, USER_ID, rec)  # #4412 cardio block ↔ wearable HR (guarded, pre-write)
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
                    if event_failures and wid in event_failures:
                        _clear_event_failure(wid)
                except Exception as e:
                    errors += 1
                    failed_ids.append(wid)
                    logger.exception("hevy backfill event error %s: %s", wid, e)
                    # #4643: count the streak; past QUARANTINE_AFTER the event stops holding
                    # the cursor. A failed count read (None) means every failure blocks.
                    if event_failures is not None and _note_event_failure(wid, ev_type, e, event_failures.get(wid)):
                        quarantined_ids.append(wid)
                    else:
                        blocking_errors += 1
                    # Don't break the page loop on one bad record — continue

            if total_pages_observed and page >= total_pages_observed:
                logger.info("hevy backfill reached page_count=%d, stop", total_pages_observed)
                break
            page += 1
            if page > MAX_PAGES_PER_RUN:
                # #475 / C-7 leg 3: the walk is TRUNCATED — pages remain beyond
                # the cap and the feed is newest-first, so events older than
                # what we walked are still unprocessed. Advancing the cursor
                # here silently skipped them forever.
                truncated = True
                logger.warning(
                    "hevy backfill hit MAX_PAGES_PER_RUN=%d with page_count=%d — truncated walk",
                    MAX_PAGES_PER_RUN,
                    total_pages_observed,
                )
                break

        # Save new high-water mark only on a COMPLETE walk with no cursor-blocking error.
        # On failures or truncation we keep the old since so the next run
        # retries the window (upserts are idempotent — no double-count). A
        # quarantined event (#4643) is the one failure that does not hold it.
        if blocking_errors == 0 and not truncated:
            save_since(poll_started_at)
            logger.info("hevy backfill since advanced to %s (quarantined this run: %s)", poll_started_at, quarantined_ids[:10])
        elif truncated:
            logger.warning(  # #4643: also recorded as a FAILED run below — no longer silent
                "hevy backfill truncated at %d/%d pages; since NOT advanced (#475). "
                "Raise HEVY_BACKFILL_MAX_PAGES for a one-off catch-up if the backlog persists.",
                pages_walked,
                total_pages_observed,
            )
        else:
            logger.warning(
                "hevy backfill had %d cursor-blocking error(s) (%d total); since NOT advanced. Failed ids: %s",
                blocking_errors,
                errors,
                failed_ids[:10],
            )

    except HevyAPIError as e:
        logger.error("hevy backfill fatal API error: %s", e)
        if _is_auth_failure(e):
            # #4643: latch the breaker (24h) before raising — the async retries of THIS
            # event then short-circuit to a 200 skip instead of reaching the DLQ.
            if _HAS_AUTH_BREAKER:
                mark_failure(_table, source_name=SOURCE, user_id=USER_ID, error_msg=e, logger=logger)
            _record_health(attempted=True, succeeded=False, exc="auth")
        else:
            _record_health(attempted=True, succeeded=False, exc=e)
        # Raise (not a 200/500 dict) so the Lambda Errors metric + async retry/DLQ
        # paths engage — a swallowed fatal was how Hevy could die invisibly (#466).
        raise

    # #475 / C-7: consume DELETE#WORKOUT# markers — this run's AND any unresolved
    # backlog (self-healing). Runs after the walk so a delete event and its
    # workout record written in the same run still reconcile. Never raises; a
    # failure leaves the marker unresolved for the next poll and never blocks
    # the cursor (marker state is independent of the events window).
    tombstones = resolve_tombstones()
    # #4412: the wearable usually lands AFTER the Hevy session (WHOOP → Strava → hourly pull), so
    # the join is re-derived every run over the last two Pacific days — written only when it changed.
    cardio_rejoin = _rejoin_cardio_hr()
    # #4643: a truncated walk is a FAILED run. It used to record success whenever no event
    # errored, so a backlog the cap could never clear — `since` frozen, every run walking the
    # same 30 newest pages — read as a healthy source forever. It is not a parse fault; the
    # walk ran out of capacity, which ingest_health files as "transport".
    if errors:
        _record_health(attempted=True, succeeded=False, exc="parse")
    elif truncated:
        _record_health(attempted=True, succeeded=False, exc="transport")
    else:
        _record_health(attempted=True, succeeded=True, exc=None)

    summary = {
        "source": "hevy",
        "initial_run": is_initial,
        "since": since,
        "new_since": poll_started_at if blocking_errors == 0 and not truncated else since,
        "ingested": ingested,
        "deleted": deleted,
        "errors": errors,
        "blocking_errors": blocking_errors,
        "quarantined": quarantined_ids[:10],
        "pages_walked": pages_walked,
        "total_pages": total_pages_observed,
        "truncated": truncated,
        "tombstones": tombstones,
        "cardio_hr_rejoin": cardio_rejoin,
        "failed_ids": failed_ids[:10],
    }
    logger.info("hevy backfill complete: %s", json.dumps(summary, default=str))
    return {"statusCode": 200, "body": json.dumps(summary, default=str)}
