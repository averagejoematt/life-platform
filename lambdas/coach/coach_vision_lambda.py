"""coach_vision_lambda.py — the Monday coach-vision run over the progress photos (#3759).

Schedule: `coach-vision` in cdk/stacks/compute_stack.py (fixed UTC cron, Mondays). The
protocol captures a set on the week-close day (#3761); this run reads the newest set
within `coach_vision.CURRENT_SET_MAX_AGE_DAYS` of the run and the set before it, asks for
one observation + one visual-estimate band through `coach.coach_vision.observe`, and writes
ONE owner-only row to `USER#matthew#SOURCE#coach_vision` / `DATE#<set date>`.

The handler is glue: every decision lives in `coach_vision` (pure, tested offline). What
this file owns is the I/O order and the three honest no-ops —

  * no set this week          → nothing written, `status: no_set`
  * the set already observed  → nothing written, `status: already_observed` (idempotent on
                                the set date + the photo keys the model saw, so a retake
                                after the run IS re-observed and a redelivery is not)
  * the budget guard paused   → nothing written, `status: paused`

— each of which returns rather than raises, so a quiet week never lands in the DLQ as a
failure. Everything else that stops the record IS a failure and raises after logging: a
DDB read error propagates from boto3 untouched, and `coach_vision.observe` raises
`CoachVisionFailure` when no photo in this week's set is readable (S3), when the inference
call fails (Bedrock — AccessDenied, a throttle, a model-access change), or when the reply
cannot become a record (off-schema, implausible band). Nothing here catches those: this is
a weekly function with ONE trigger, and its only alarm counts Invocations — a run that
swallowed its failures would keep that alarm green while the job was dark for months. The
raise is what makes an Errors datapoint and, after the async retries, a message on the
shared ingestion DLQ (`life-platform-ingestion-dlq-messages` + the DLQ consumer's
escalation, #4731), which are the watched paths (`tests/test_coach_vision_3759.py` pins
both raises end to end).

The S3 keys are the ones the index rows carry; each is checked against the registry's own
prefix facet before it is read (`coach_vision.key_is_under_prefix`). This role holds
`s3:GetObject` on that prefix and nothing else in the raw zone; the site-API roles hold
no `raw/` resource at all (#3757), which is why this is a compute-stack function.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import boto3
from common.numeric import floats_to_decimal
from common.pacific_time import pacific_today, shift_day_key

from coach import coach_vision

try:  # OBS-1: structured logging, like every other handler on the fleet
    from common.platform_logger import get_logger

    logger = get_logger("coach-vision")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("coach-vision")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

_table = None
_s3 = None


def _ddb_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    return _table


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=REGION)
    return _s3


def _query_all(table, pk: str, lo: str = "DATE#", hi: str = "DATE#~") -> list:
    items: list = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
        "ExpressionAttributeValues": {":pk": pk, ":lo": lo, ":hi": hi},
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _existing_record(table, as_of: str) -> dict | None:
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk = :sk",
        ExpressionAttributeValues={":pk": coach_vision.RECORD_PK, ":sk": coach_vision.record_sk(as_of)},
    )
    items = resp.get("Items") or []
    return items[0] if items else None


def _photo_loader(s3, bucket: str, prefix: str):
    def load(key: str) -> bytes:
        if not coach_vision.key_is_under_prefix(key, prefix):
            raise ValueError(f"index row names a key outside the registry prefix: {key!r}")
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()

    return load


def run(*, table, s3, bucket: str, today: str, invoke_fn=None, allow_fn=None, now: datetime | None = None) -> dict:
    """The whole run with every dependency injected — what the tests drive."""
    prefix = coach_vision.photo_prefix()
    rows = _query_all(table, coach_vision.PHOTO_INDEX_PK)
    current, prior = coach_vision.pick_sets(coach_vision.group_sets(rows), today)
    if not current:
        logger.info(
            "[coach_vision] no progress-photo set within %d days of %s — nothing to observe", coach_vision.CURRENT_SET_MAX_AGE_DAYS, today
        )
        return {"status": "no_set", "today": today}

    keys_now = {p: ref["key"] for p, ref in current["poses"].items()}
    prior_rec = _existing_record(table, current["as_of"])
    if prior_rec and dict((prior_rec.get("photo_keys") or {}).get("current") or {}) == keys_now:
        logger.info("[coach_vision] set %s already observed on %s — skipping", current["as_of"], prior_rec.get("created_at"))
        return {"status": "already_observed", "as_of": current["as_of"], "sk": prior_rec.get("sk")}

    dexa_items = _query_all(table, coach_vision.DEXA_PK)
    tape_items = _query_all(
        table, coach_vision.MEASUREMENTS_PK, lo=f"DATE#{shift_day_key(current['as_of'], -coach_vision.TAPE_WINDOW_DAYS)}"
    )
    anchors = {
        "dexa": coach_vision.nearest_dexa(dexa_items, current["as_of"]),
        "tape_trend": coach_vision.tape_trend(tape_items, current["as_of"]),
    }

    result = coach_vision.observe(
        current, prior, anchors, loader=_photo_loader(s3, bucket, prefix), invoke_fn=invoke_fn, allow_fn=allow_fn, now=now
    )
    if result["status"] == "paused":  # the one soft outcome after the set is known; a failure has already raised
        logger.warning("[coach_vision] paused: %s", result.get("reason"))
        return {"status": "paused", "reason": result.get("reason"), "as_of": current["as_of"]}

    created_at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = coach_vision.build_record(current, prior, anchors, result, created_at=created_at)
    table.put_item(Item=floats_to_decimal(record))
    logger.info(
        "[coach_vision] wrote %s/%s model=%s band=%s-%s%% grounded=%s",
        record["pk"],
        record["sk"],
        record["model_id"],
        record["body_fat_estimate"]["low_pct"],
        record["body_fat_estimate"]["high_pct"],
        record["qualitative"] is not None,
    )
    return {"status": "written", "pk": record["pk"], "sk": record["sk"], "model_id": record["model_id"]}


def lambda_handler(event: dict, context: object) -> dict:  # noqa: ARG001 — Lambda signature
    today = str((event or {}).get("today") or pacific_today())
    return run(table=_ddb_table(), s3=_s3_client(), bucket=S3_BUCKET, today=today)
