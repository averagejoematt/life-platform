"""
alert_digest_lambda.py — ADR-050: daily-batched alarm digest.

Drains the life-platform-alerts-digest-queue SQS (fed by the
life-platform-alerts-digest SNS topic with raw message delivery), groups
by AlarmName, and sends ONE summary SES email at 8 AM PT.

If the queue is empty, sends nothing (no "all clear" emails).

Replaces the previous model where every CloudWatch alarm produced an
immediate email — see DECISIONS.md ADR-050 for rationale.

Environment variables:
  DIGEST_QUEUE_URL   (required)
  EMAIL_RECIPIENT    (default awsdev@mattsusername.com)
  EMAIL_SENDER       (default awsdev@mattsusername.com)
  REGION             (default us-west-2)
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3

try:
    from platform_logger import get_logger
    logger = get_logger("alert-digest")
except ImportError:
    logger = logging.getLogger("alert-digest")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
DIGEST_QUEUE_URL = os.environ["DIGEST_QUEUE_URL"]
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")

# SQS receive-message caps at 10 per call. Loop until empty.
MAX_RECEIVE_BATCH = 10

sqs = boto3.client("sqs", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)


def _parse_alarm_payload(body):
    """SNS raw delivery puts the CloudWatch alarm JSON directly in the SQS body.

    Fall back to parsing the full SNS envelope (Message field) for safety in
    case raw delivery isn't enabled.
    """
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return {"AlarmName": "unparseable", "NewStateReason": body[:200]}
    if isinstance(payload, dict) and "Message" in payload and "AlarmName" not in payload:
        try:
            return json.loads(payload["Message"])
        except (TypeError, ValueError):
            return {"AlarmName": "unparseable", "NewStateReason": str(payload["Message"])[:200]}
    return payload


def _drain_queue():
    """Pull all messages from the digest queue and delete them after parsing."""
    alarms = []
    while True:
        resp = sqs.receive_message(
            QueueUrl=DIGEST_QUEUE_URL,
            MaxNumberOfMessages=MAX_RECEIVE_BATCH,
            WaitTimeSeconds=1,
            VisibilityTimeout=60,
        )
        msgs = resp.get("Messages", [])
        if not msgs:
            break
        for m in msgs:
            alarms.append(_parse_alarm_payload(m.get("Body", "")))
        # Batch delete (SQS allows up to 10 per call, which matches MAX_RECEIVE_BATCH).
        sqs.delete_message_batch(
            QueueUrl=DIGEST_QUEUE_URL,
            Entries=[{"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(msgs)],
        )
    return alarms


def _group_by_alarm(alarms):
    """Dedupe by AlarmName. Count fires, keep first reason + latest state-change time."""
    grouped = defaultdict(lambda: {"count": 0, "reason": "", "last_state_change": "", "last_state": ""})
    for a in alarms:
        name = a.get("AlarmName", "unknown")
        entry = grouped[name]
        entry["count"] += 1
        if not entry["reason"]:
            entry["reason"] = a.get("NewStateReason", "")[:300]
        # Keep latest state-change so the digest reflects current state.
        sc = a.get("StateChangeTime", "")
        if sc > entry["last_state_change"]:
            entry["last_state_change"] = sc
            entry["last_state"] = a.get("NewStateValue", "")
    return dict(grouped)


def _format_email(grouped):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    distinct = len(grouped)
    total = sum(g["count"] for g in grouped.values())
    subject = f"[LP digest {today}] {distinct} alarm(s), {total} fire(s)"

    lines = [
        f"Life Platform alarm digest — {today}",
        f"{distinct} distinct alarm(s), {total} total fire(s) in the last 24h.",
        "",
        "Per-alarm summary (sorted by fire count):",
        "",
    ]
    for name, entry in sorted(grouped.items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"• {name}  ×{entry['count']}  [{entry['last_state'] or 'ALARM'}]")
        if entry["reason"]:
            lines.append(f"    {entry['reason']}")
        if entry["last_state_change"]:
            lines.append(f"    last state change: {entry['last_state_change']}")
        lines.append("")
    lines.append("Urgent alarms (canary, daily-brief, DLQ depth, cost runaway) still")
    lines.append("page in real time on the life-platform-alerts topic.")
    return subject, "\n".join(lines)


def lambda_handler(event: dict, context) -> dict:  # Phase 4.12 type hints
    try:
        alarms = _drain_queue()
        if not alarms:
            logger.info("digest_empty")
            return {"statusCode": 200, "drained": 0, "sent": False}

        grouped = _group_by_alarm(alarms)
        subject, body = _format_email(grouped)

        ses.send_email(
            FromEmailAddress=EMAIL_SENDER,
            Destination={"ToAddresses": [EMAIL_RECIPIENT]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            }},
        )
        logger.info("digest_sent drained=%d distinct=%d", len(alarms), len(grouped))
        return {"statusCode": 200, "drained": len(alarms), "distinct": len(grouped), "sent": True}
    except Exception as e:
        logger.error("alert_digest_failed: %s", e)
        raise
