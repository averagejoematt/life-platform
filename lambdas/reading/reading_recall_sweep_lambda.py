"""reading_recall_sweep_lambda.py — the daily spaced-retrieval sweep (Phase D, spec §7).

Queries the SPARSE GSI1 for recall prompts due now (`GSI1SK <= now`), writes a
PRIVATE owner-only "recall queue" snapshot, and emits a CloudWatch count. The
answering itself is the owner's act (MCP `manage_reading answer_recall`); this
sweep just makes "a memory check is waiting" visible without opening the tool.

DST-safe: the schedule is fixed-UTC (set in CDK); the sweep reads `now` in UTC and
the GSI1SK comparison is date/iso-string lexical, so there's no local-time boundary
to drift. PRIVATE by construction — the snapshot lives under READING# (never served
by the public site-api; recall is owner-only).

Bundled with lambdas/ (uses reading_store via the shared layer's numeric); no AI.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from reading import reading_keys as rk, reading_store

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
_cw = boto3.client("cloudwatch", region_name=REGION)

# Private owner-only snapshot of what's due (READING# pk → CROSS_PHASE, never public).
NUDGE_PK = "READING#NUDGE"
NUDGE_SK = "RECALL_QUEUE#current"


def _emit(count: int):
    try:
        _cw.put_metric_data(
            Namespace="LifePlatform/Reading",
            MetricData=[{"MetricName": "RecallsDue", "Value": float(count), "Unit": "Count"}],
        )
    except Exception as e:  # noqa: BLE001 — telemetry is best-effort
        logger.info("[recall-sweep] metric emit failed (%s)", type(e).__name__)


def _write_snapshot(due: list, now_iso: str):
    prompts = [
        {"bookId": r.get("bookId"), "promptId": r.get("promptId"), "prompt": r.get("prompt"), "nextDue": r.get("nextDue")} for r in due
    ]
    item = {"pk": NUDGE_PK, "sk": NUDGE_SK, "dueCount": len(due), "prompts": prompts, "generatedAt": now_iso}
    reading_store.table.put_item(Item=item)


def lambda_handler(event, context=None):
    """Daily sweep. Surfaces due recall prompts to the owner-private nudge snapshot."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        due = reading_store.due_recalls(now=now_iso)
        _write_snapshot(due, now_iso)
        _emit(len(due))
        logger.info("[recall-sweep] %d recall prompt(s) due", len(due))
        return {"statusCode": 200, "body": json.dumps({"due_count": len(due), "as_of": now_iso})}
    except Exception as e:  # noqa: BLE001 — never let the scheduled run hard-fail
        logger.exception("[recall-sweep] failed")
        return {"statusCode": 500, "body": json.dumps({"error": type(e).__name__})}


# Keep the rk import meaningful for static-analysis (key constants document intent).
_ = (rk.RECALL_DUE_VALUE, rk.GSI1_NAME)
