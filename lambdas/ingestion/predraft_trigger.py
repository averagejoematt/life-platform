"""predraft_trigger.py — the Hevy poller starts the nightly pre-draft when it writes a loaded session (#5795).

The pre-draft (`mcp/nightly_predraft.py`) runs on a 19:00 PT clock. On 2026-11-11 it ran at 03:00:07Z
and the day's session ended at 03:01:30Z, so it drafted the session just performed. This is the
ingest side of the fix: after a poll that WROTE a loaded workout dated today or yesterday (Pacific —
an after-midnight poll still carries last evening's session), the poller invokes the MCP warmer
asynchronously with `{"job": "nightly_predraft", "trigger": "hevy_ingest", "workout_ids": [...]}`.
The warmer decides whether the sequence CREDITS one of them (`mcp/predraft_ingest.py`) — an
off-program complement (Flex, #4312) drafts nothing — and then runs the unchanged pre-draft.

WHY THE LIVE PATH IS THE POLLER, NOT `hevy_webhook_lambda.py`
  The `hevy-webhook` FunctionURL Lambda was retired 2026-07-06 (#756 — Hevy offers no public webhook
  subscription); the hourly `hevy-backfill` events-feed poller is the only Hevy ingest that runs.

FLAG — `PREDRAFT_ON_INGEST` (env on `hevy-backfill`, cdk/stacks/ingestion_stack.py), default OFF
  The invoke needs `lambda:InvokeFunction` on the warmer, an additive IAM grant the owner approves
  before deploy. Until the env reads `on`, a poll only REPORTS the candidates (`state: "off"`).

Never raises: the poll's outcome and its cursor never depend on this.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

FLAG_ENV = "PREDRAFT_ON_INGEST"
WARMER_FUNCTION_NAME = "life-platform-mcp-warmer"
"""mcp/invoke_gate.WARMER_FUNCTION_NAME — the ONLY function whose privileged job branches run (pinned by test)."""
JOB = "nightly_predraft"
TRIGGER = "hevy_ingest"
"""mcp/nightly_predraft.INGEST_TRIGGER (pinned by test)."""


def enabled() -> bool:
    return os.environ.get(FLAG_ENV, "off").strip().lower() == "on"


def candidates(records: list[dict[str, Any]], today: str) -> list[str]:
    """Workout ids of the LOADED sessions this poll wrote for `today` or the day before (Pacific day keys)."""
    from common.pacific_time import shift_day_key
    from training.training_streaks import is_loaded_session

    recent = {today, shift_day_key(today, -1)}
    return sorted(
        {
            str(r.get("source_workout_id"))
            for r in records
            if r.get("source_workout_id") and str(r.get("date") or "")[:10] in recent and is_loaded_session(r)
        }
    )


def event(workout_ids: list[str]) -> dict[str, Any]:
    return {"job": JOB, "trigger": TRIGGER, "workout_ids": list(workout_ids)}


def _invoke(payload: dict[str, Any]) -> None:
    import boto3

    # Event = async: the 202 acknowledgement carries no payload, and none is read.
    boto3.client("lambda").invoke(FunctionName=WARMER_FUNCTION_NAME, InvocationType="Event", Payload=json.dumps(payload).encode())


def after_poll(
    records: list[dict[str, Any]], today: str | None = None, invoke: Callable[[dict[str, Any]], None] | None = None
) -> dict[str, Any]:
    """Start the pre-draft when this poll wrote a recent loaded session and the flag is on. Never raises."""
    try:
        if today is None:
            from common.pacific_time import pacific_today

            today = pacific_today()
        ids = candidates(records, today)
        if not ids:
            return {"state": "no_candidate"}
        if not enabled():
            return {"state": "off", "candidates": ids}
        (invoke or _invoke)(event(ids))
        return {"state": "invoked", "workout_ids": ids}
    except Exception as e:  # noqa: BLE001 — the 19:00 PT run is the fallback; the failure is named on the summary
        return {"state": "failed", "error": f"{type(e).__name__}: {e}"[:200]}
