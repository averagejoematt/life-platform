"""predraft_ingest.py — the nightly pre-draft, started by the Hevy ingest of a credited session (#5795).

WHY THIS EXISTS
  On 2026-11-11 the 19:00 PT pre-draft ran at 03:00:07Z; the day's session ended at 03:01:30Z and
  reached the store on a later Hevy poll. The run read the completed-session record before that
  session was in it, so it drafted the session he had just performed — the same sequence slot. A
  clock-only run races every evening session that crosses 19:00 PT.

WHAT AN INGEST-TRIGGERED RUN DOES
  The Hevy poller (`ingestion/predraft_trigger.py`, behind `PREDRAFT_ON_INGEST`, default off) invokes
  the warmer asynchronously with `{"job": "nightly_predraft", "trigger": "hevy_ingest", "workout_ids":
  [...]}` for the LOADED workouts it just wrote for today / yesterday (Pacific). Here:
    1. the record the sequence reads (`nightly_predraft._block_record`, stage 1's own read) decides
       whether any of those workouts is CREDITED (`session_sequence.classify_sessions` — an off-program
       complement such as Flex, #4312, or a content mismatch is not). None credited → `not_credited`,
       nothing swept, nothing drafted.
    2. credited → `nightly_predraft.run(tomorrow)`, unchanged: the same sweep (whose `sequence_done`
       reason archives a pre-draft of the slot just performed), the same idempotency and ownership
       rules (`exists`, resume, `skipped_owner_routine`), the same never-commit contract.
  It emits NO `PredraftOutcome` datapoint and runs none of the scheduled run's legs (tracker, battery,
  calibration, titration): the 19:00 PT schedule stays, as the fallback and as the run the
  `nightly-predraft-missing` dead-man watches — an ingest run must never mask that run's absence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("nightly_predraft")

NOT_CREDITED = "not_credited"
SEQUENCE_UNREADABLE = "sequence_unreadable"


def credited_ids(workout_ids: list[str], rows: list[dict[str, Any]], before_day: str) -> list[str]:
    """The ids in `workout_ids` the sequence CREDITS as a program session in [block start, `before_day`).

    A day's program logs are one session (`classify_sessions`), so a log is credited when its day carries
    a credited session and the log itself was not refused (an off-program complement on the same day is)."""
    from training import session_sequence, training_streaks

    credited, refused = session_sequence.classify_sessions(rows, before_day)
    days = {c["date"] for c in credited}
    refused_ids = {str(r.get("workout_id")) for r in refused if r.get("workout_id")}
    day_of = {
        str(w.get("source_workout_id") or w.get("workout_id")): training_streaks._day(w)
        for w in rows
        if not w.get("tombstone") and (w.get("source_workout_id") or w.get("workout_id"))
    }
    return [w for w in workout_ids if day_of.get(w) in days and w not in refused_ids]


def _gate_and_run(ids: list[str], target: str) -> dict[str, Any]:
    from mcp import nightly_predraft as npd

    rows = npd._block_record(target)
    if rows is None:
        return {"outcome": SEQUENCE_UNREADABLE, "reason": "the Hevy record since the block start was not read — nothing drafted"}
    hit = credited_ids(ids, rows, target)
    if not hit:
        return {
            "outcome": NOT_CREDITED,
            "reason": "no ingested workout is credited as a program session (off-program, content mismatch, or not yet readable)",
        }
    return {**npd.run(target), "credited_workout_ids": hit}


def lambda_entry(event: dict[str, Any]) -> dict[str, Any]:
    """The ingest-triggered entry (dispatched by `nightly_predraft.lambda_entry`). Never raises; never emits the dead-man."""
    from common.pacific_time import pacific_today, shift_day_key

    from mcp import nightly_predraft as npd

    ids = [str(i) for i in (event or {}).get("workout_ids") or [] if i]
    target = shift_day_key(pacific_today(), npd.JOB["target_offset_days"])
    try:
        result = _gate_and_run(ids, target)
    except Exception as e:  # noqa: BLE001 — named on the log line; the 19:00 PT run is the fallback
        logger.exception("ingest-triggered pre-draft failed")
        result = {"outcome": npd.FAILED, "error": f"{type(e).__name__}: {e}"[:300]}
    result = {**result, "job": npd.JOB["name"], "trigger": npd.INGEST_TRIGGER, "target_date": target, "workout_ids": ids}
    logger.info("NIGHTLY_PREDRAFT_INGEST %s", json.dumps(result, default=str)[:4000])
    return {"statusCode": 200, "body": json.dumps(result, default=str), "headers": {"Content-Type": "application/json"}}
