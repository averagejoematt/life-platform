"""
dlq_consumer_lambda.py — REL-2: Dead Letter Queue Consumer
Version: 2.0.0 (REL-02/REL-03, #402 / ADR-115)

Polls life-platform-ingestion-dlq on a schedule (every 6 hours). Classifies
each failed message, retries transient failures by re-invoking the original
Lambda, and ESCALATES permanent / repeatedly-failing messages to the operator.

Why v2 (ADR-115):
  The v1 design re-invoked a transient failure and then *always* deleted the
  message. A failed retry re-lands on the DLQ as a brand-new SQS message with a
  fresh MessageId and ApproximateReceiveCount reset to 1 — so the "this has
  failed N times" counter could never accumulate and the escalation never fired.
  A permanently-broken message could loop invisibly forever.

  v2 tracks retries by a STABLE content-derived identity (sha256 of
  function-name + body) in a DURABLE DynamoDB ledger (`SYSTEM#dlq-ledger`
  partition). The ledger survives the delete→re-invoke→re-land cycle, so
  cumulative failure attempts accumulate across runs. When the cumulative count
  crosses a threshold, the message ESCALATES (pages the operator on the urgent
  SNS topic) instead of being silently retried. A message is deleted from the
  queue only after a *confirmed* re-invoke acceptance — a failed re-invoke is
  left on the queue to redrive, so the count keeps climbing rather than resetting.

Classification:
  TRANSIENT — timeout, throttle, transient API error → retry once via Lambda invoke
  PERMANENT — auth failure, missing resource, unretryable → escalate + archive to S3

Strategy:
  - Drain within a TIME BUDGET per run (loop receive_message until empty or the
    budget is exhausted) instead of a fixed 10-message cap, so a burst cannot
    outgrow the drain rate.
  - For each message: record the failure occurrence in the durable ledger
    (ADD receive_count → cumulative attempts), then decide:
      * permanent OR cumulative attempts >= ESCALATE_THRESHOLD OR unretryable
        → escalate (archive to S3, page on SNS + SES summary), delete.
      * transient below threshold → re-invoke the source Lambda; delete ONLY if
        the invoke was accepted (2xx). If not accepted, leave it on the queue so
        it redrives and the count keeps accumulating.

DLQ: life-platform-ingestion-dlq (SQS)
Schedule: every 6 hours (EventBridge: dlq-consumer-schedule)
IAM role: lambda-dlq-consumer-role

Environment variables:
  TABLE_NAME         (default: life-platform)
  S3_BUCKET          (required)
  DLQ_URL            (required — wired from CDK)
  ALERTS_TOPIC_ARN   (optional — urgent SNS topic for escalation paging)
  ESCALATE_THRESHOLD (default: 3 cumulative attempts)
  DRAIN_BUDGET_SECONDS (default: 90 — wall-clock ceiling per run)
  REGION             (default: us-west-2)
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("dlq-consumer")
except ImportError:
    logger = logging.getLogger("dlq-consumer")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
DLQ_URL = os.environ.get("DLQ_URL", "")
ALERTS_TOPIC_ARN = os.environ.get("ALERTS_TOPIC_ARN", "")
RECIPIENT = "awsdev@mattsusername.com"
SENDER = "awsdev@mattsusername.com"

# Escalate a message once its cumulative failure attempts (durable, across
# re-invoke/re-land cycles) reach this many. Also the receive-count ceiling in
# classify_message so single-message SQS redrive still surfaces on its own.
ESCALATE_THRESHOLD = int(os.environ.get("ESCALATE_THRESHOLD", "3"))
MAX_RETRY_COUNT = ESCALATE_THRESHOLD  # receive_count >= this ⇒ permanent (preserved semantics)

# Drain by time budget instead of a fixed message cap (#402). Leave headroom
# below the Lambda timeout for the final SES/SNS/S3 flush.
DRAIN_BUDGET_SECONDS = int(os.environ.get("DRAIN_BUDGET_SECONDS", "90"))
SAFETY_MARGIN_MS = 15000  # stop pulling new batches with <15s of Lambda time left
RECEIVE_BATCH = 10  # SQS receive_message hard cap
ABSOLUTE_MESSAGE_CAP = 1000  # belt-and-suspenders guard against a runaway loop

# Durable retry ledger (single-table, no GSI — composite key only, ADR-115).
LEDGER_PK = "SYSTEM#dlq-ledger"
LEDGER_TTL_SECONDS = 90 * 24 * 3600  # auto-purge ledger rows 90d after last touch

# ── AWS clients ────────────────────────────────────────────────────────────────
sqs = boto3.client("sqs", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
events = boto3.client("events", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
_ddb = boto3.resource("dynamodb", region_name=REGION)
_table = _ddb.Table(TABLE_NAME)


# ── Classification ─────────────────────────────────────────────────────────────

# Keywords in error messages that indicate transient failures
TRANSIENT_PATTERNS = [
    "timeout",
    "timed out",
    "throttl",
    "rate limit",
    "503",
    "502",
    "connection",
    "socket",
    "temporary",
    "try again",
    "retryable",
    "service unavailable",
    "task timed out",
    "connection reset",
    "read timeout",
    "connect timeout",
]

# Keywords that indicate permanent failures
PERMANENT_PATTERNS = [
    "auth",
    "unauthorized",
    "403",
    "401",
    "forbidden",
    "invalid token",
    "expired token",
    "no such key",
    "nosuchkey",
    "access denied",
    "not found",
    "404",
    "validation",
    "malformed",
    "invalid parameter",
]


def classify_message(message: dict) -> str:
    """
    Returns 'transient' or 'permanent'.
    Bases decision on:
      1. ApproximateReceiveCount (>= MAX_RETRY_COUNT = permanent) — preserves the
         single-message SQS receive-count semantics.
      2. Error patterns in message body
      3. Default: transient (give benefit of doubt on first pass)
    """
    attrs = message.get("Attributes", {})
    receive_count = int(attrs.get("ApproximateReceiveCount", "1"))

    if receive_count >= MAX_RETRY_COUNT:
        logger.info(f"  → PERMANENT (receive_count={receive_count} >= {MAX_RETRY_COUNT})")
        return "permanent"

    # Check body for error indicators
    body_str = message.get("Body", "").lower()
    try:
        body_obj = json.loads(message.get("Body", "{}"))
        error_str = str(body_obj.get("errorMessage", "")).lower()
        body_str = body_str + " " + error_str
    except (json.JSONDecodeError, TypeError):
        pass

    for pattern in PERMANENT_PATTERNS:
        if pattern in body_str:
            logger.info(f"  → PERMANENT (matched pattern: '{pattern}')")
            return "permanent"

    for pattern in TRANSIENT_PATTERNS:
        if pattern in body_str:
            logger.info(f"  → TRANSIENT (matched pattern: '{pattern}')")
            return "transient"

    # Default: transient (retry once, permanent on next receipt)
    logger.info(f"  → TRANSIENT (no pattern matched, receive_count={receive_count}, defaulting to retry)")
    return "transient"


# ── Stable identity + durable ledger (ADR-115) ──────────────────────────────────


def stable_message_id(fn_name: str, body_str: str) -> str:
    """A content-derived identity that is STABLE across the re-invoke → re-land
    cycle.

    The SQS MessageId and ApproximateReceiveCount both reset when a failed
    re-invoke lands a fresh async-DLQ message, so neither can anchor a durable
    "failed N times" count. The message *body* (the original invocation event we
    replay verbatim) is identical across those cycles, so hashing
    function-name + body gives a key that persists in the ledger while SQS churns
    the underlying message."""
    h = hashlib.sha256()
    h.update((fn_name or "unknown").encode("utf-8"))
    h.update(b"\n")
    h.update((body_str or "").encode("utf-8"))
    return h.hexdigest()[:32]


def record_failure(stable_id: str, fn_name: str, receive_count: int, body_str: str) -> int:
    """Atomically add this failure occurrence to the durable ledger and return
    the NEW cumulative attempt count.

    We ADD the SQS-reported receive_count (>= 1) rather than a flat +1 so the
    ledger preserves receive-count semantics: a message that SQS itself redrove
    several times before we saw it contributes all of those attempts. The count
    accumulates across delete→re-invoke→re-land cycles because the key is the
    stable content hash, not the churning MessageId.

    Fail-soft: on any DDB error we return receive_count so the caller still has a
    sane count to decide on (never silently drops the message)."""
    inc = max(1, int(receive_count))
    now = int(time.time())
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        resp = _table.update_item(
            Key={"pk": LEDGER_PK, "sk": f"MSG#{stable_id}"},
            UpdateExpression=(
                "ADD attempts :inc "
                "SET fn_name = :fn, last_seen = :now, last_receive_count = :rc, "
                "body_preview = :bp, #t = :ttl, first_seen = if_not_exists(first_seen, :now)"
            ),
            ExpressionAttributeNames={"#t": "ttl"},
            ExpressionAttributeValues={
                ":inc": Decimal(inc),
                ":fn": fn_name or "unknown",
                ":now": now_iso,
                ":rc": Decimal(int(receive_count)),
                ":bp": (body_str or "")[:500],
                ":ttl": Decimal(now + LEDGER_TTL_SECONDS),
            },
            ReturnValues="UPDATED_NEW",
        )
        return int(resp.get("Attributes", {}).get("attempts", inc))
    except Exception as e:  # noqa: BLE001 — fail-soft, never drop a message on a DDB blip
        logger.error(f"  ledger update failed for {stable_id}: {e}")
        return inc


def mark_escalated(stable_id: str) -> None:
    """Stamp the ledger row as escalated (idempotent, for the audit trail)."""
    try:
        _table.update_item(
            Key={"pk": LEDGER_PK, "sk": f"MSG#{stable_id}"},
            UpdateExpression="SET escalated = :t, escalated_at = :now",
            ExpressionAttributeValues={
                ":t": True,
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"  ledger escalate-mark failed for {stable_id}: {e}")


# ── Retry logic ────────────────────────────────────────────────────────────────

# Cache rule-name → target-function-ARN so we don't re-query EventBridge per
# message within a single run (the same scheduled rule produces many DLQ msgs).
_rule_fn_cache: dict[str, str | None] = {}


def _function_from_eventbridge(body_obj: dict) -> str | None:
    """Resolve the target Lambda for an EventBridge-triggered async failure.

    A Lambda async-DLQ message is the *original invocation event*, not a wrapper
    — so for scheduled ingestion the function name isn't in the payload. But the
    EventBridge event carries the triggering rule ARN in `resources`, and the
    rule has exactly one Lambda target. Look it up dynamically rather than
    hard-coding a rule→function map (which would rot as stacks change)."""
    for arn in body_obj.get("resources") or []:
        if ":rule/" not in arn:
            continue
        rule_name = arn.split(":rule/", 1)[1]
        if rule_name in _rule_fn_cache:
            return _rule_fn_cache[rule_name]
        target = None
        try:
            for t in events.list_targets_by_rule(Rule=rule_name).get("Targets", []):
                if ":function:" in t.get("Arn", ""):
                    target = t["Arn"]
                    break
        except Exception as e:
            logger.warning(f"  list_targets_by_rule failed for {rule_name}: {e}")
        _rule_fn_cache[rule_name] = target
        if target:
            return target
    return None


def extract_function_name(message: dict) -> str | None:
    """
    Extract the original Lambda function name from an SQS DLQ message.

    Lambda async-DLQ messages do NOT include the function name in attributes;
    the body is the original event. We support two shapes:
      1. Payloads that explicitly carry the name (rare).
      2. EventBridge scheduled events → resolve via the triggering rule's target.
    """
    try:
        body = json.loads(message.get("Body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(body, dict):
        return None

    fn = body.get("function_name") or body.get("FunctionName") or body.get("lambda_function")
    if fn:
        return fn

    if body.get("source") == "aws.events" or body.get("resources"):
        return _function_from_eventbridge(body)

    return None


def retry_message(message: dict, fn_name: str | None) -> bool:
    """
    Attempt to re-invoke the original Lambda with the same payload.
    Returns True only if the invoke was CONFIRMED accepted (Lambda returned 2xx).
    A False return means the retry was not accepted — the caller must NOT delete
    the message, so it redrives and the durable count keeps climbing.
    """
    body_str = message.get("Body", "{}")

    if not fn_name:
        logger.warning("  Cannot retry: no function name extractable from message")
        return False

    try:
        logger.info(f"  Retrying Lambda: {fn_name}")
        response = lam.invoke(
            FunctionName=fn_name,
            InvocationType="Event",  # async — don't block
            Payload=body_str.encode("utf-8"),
        )
        status = response.get("StatusCode", 0)
        if 200 <= status < 300:
            logger.info(f"  ✅ Retry invocation accepted (status={status})")
            return True
        else:
            logger.warning(f"  ❌ Retry rejected (status={status})")
            return False
    except Exception as e:
        logger.error(f"  ❌ Retry failed: {e}")
        return False


# ── Archival ───────────────────────────────────────────────────────────────────


def archive_to_s3(message: dict, classification: str, retry_attempted: bool, attempts: int) -> str:
    """Write failed message to S3 dead-letter-archive/ for post-mortem analysis."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y/%m/%d")
    msg_id = message.get("MessageId", "unknown")
    s3_key = f"dead-letter-archive/{ts}/{msg_id}.json"

    archive_record = {
        "archived_at": now.isoformat(),
        "message_id": msg_id,
        "classification": classification,
        "retry_attempted": retry_attempted,
        "cumulative_attempts": attempts,
        "receive_count": message.get("Attributes", {}).get("ApproximateReceiveCount"),
        "sent_timestamp": message.get("Attributes", {}).get("SentTimestamp"),
        "body": message.get("Body", ""),
        "attributes": message.get("Attributes", {}),
        "message_attributes": message.get("MessageAttributes", {}),
    }

    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(archive_record, indent=2),
            ContentType="application/json",
        )
        logger.info(f"  📦 Archived to s3://{S3_BUCKET}/{s3_key}")
        return s3_key
    except Exception as e:
        logger.error(f"  Failed to archive to S3: {e}")
        return ""


# ── Escalation / Alerting ────────────────────────────────────────────────────────


def page_operator(escalations: list[dict]) -> None:
    """Publish an URGENT escalation to the existing operator paging channel — the
    life-platform-alerts SNS topic (the same real-time page as canary /
    daily-brief / cost-runaway). Reuses the platform's channel; no new one.

    Fail-soft: an SNS hiccup must not crash the run — the SES summary below is
    the redundant record."""
    if not escalations or not ALERTS_TOPIC_ARN:
        if escalations and not ALERTS_TOPIC_ARN:
            logger.warning("  ALERTS_TOPIC_ARN not set — SNS page skipped (SES summary still sent)")
        return

    count = len(escalations)
    lines = [
        f"{count} DLQ message(s) crossed the failure threshold "
        f"(ESCALATE_THRESHOLD={ESCALATE_THRESHOLD} cumulative attempts) and could not recover.",
        "",
    ]
    for e in escalations:
        lines.append(
            f"• fn={e.get('function_name', 'unknown')} "
            f"attempts={e.get('attempts', '?')} "
            f"reason={e.get('classification', '?')} "
            f"msg={str(e.get('message_id', '?'))[:16]} "
            f"archive={e.get('s3_key', '')}"
        )
    lines.append("")
    lines.append("These are permanently-failing or repeatedly-failing messages, archived to S3.")
    lines.append("DLQ: life-platform-ingestion-dlq")
    body = "\n".join(lines)

    try:
        sns.publish(
            TopicArn=ALERTS_TOPIC_ARN,
            Subject=f"[LP URGENT] {count} DLQ failure(s) escalated"[:100],
            Message=body,
        )
        logger.info(f"  🚨 Paged operator via SNS: {count} escalation(s)")
    except Exception as e:
        logger.error(f"  Failed to publish SNS escalation: {e}")


def send_alert(escalations: list[dict]) -> None:
    """Send a single consolidated SES summary for all escalated failures in this run."""
    if not escalations:
        return

    count = len(escalations)
    rows = ""
    for f in escalations:
        msg_id = str(f.get("message_id", "?"))
        fn_name = f.get("function_name", "unknown")
        attempts = f.get("attempts", "?")
        body_pre = str(f.get("body", ""))[:200].replace("<", "&lt;").replace(">", "&gt;")
        s3_key = f.get("s3_key", "")
        rows += f"""
        <tr>
          <td style="padding:6px 12px;border-bottom:1px solid #333;">{msg_id[:12]}…</td>
          <td style="padding:6px 12px;border-bottom:1px solid #333;">{fn_name}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #333;text-align:center;">{attempts}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #333;font-family:monospace;font-size:12px;">{body_pre}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #333;font-size:11px;">{s3_key}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><style>
  body {{ font-family: -apple-system, Arial, sans-serif; background: #1a1a1a; color: #e0e0e0; margin: 0; padding: 20px; }}
  .container {{ max-width: 900px; margin: 0 auto; background: #242424; border-radius: 8px; padding: 24px; }}
  h2 {{ color: #ff6b6b; margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th {{ text-align: left; padding: 8px 12px; background: #333; color: #aaa; font-size: 12px; text-transform: uppercase; }}
  .footer {{ margin-top: 20px; font-size: 12px; color: #666; }}
</style></head>
<body><div class="container">
  <h2>⚠️ DLQ — {count} Escalated Failure{'s' if count > 1 else ''}</h2>
  <p style="color:#aaa;">These messages crossed the failure threshold (≥{ESCALATE_THRESHOLD} cumulative attempts)
  or are permanently unretryable, and have been archived to S3.</p>
  <table>
    <tr>
      <th>Message ID</th><th>Function</th><th>Attempts</th><th>Body Preview</th><th>S3 Archive</th>
    </tr>
    {rows}
  </table>
  <div class="footer">
    DLQ: life-platform-ingestion-dlq |
    <a href="https://us-west-2.console.aws.amazon.com/sqs/v3/home?region=us-west-2#/queues" style="color:#888;">View SQS</a>
  </div>
</div></body></html>"""

    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": f"⚠️ Life Platform: {count} DLQ failure{'s' if count > 1 else ''} escalated"},
                    "Body": {"Html": {"Data": html}},
                }
            },
        )
        logger.info(f"  📧 Escalation summary sent: {count} failure(s)")
    except Exception as e:
        logger.error(f"  Failed to send SES alert: {e}")


# ── Per-message processing ───────────────────────────────────────────────────────


def process_message(msg: dict, stats: dict, escalations: list[dict]) -> None:
    """Handle one DLQ message: ledger the failure, retry-or-escalate, delete only
    on a confirmed outcome. Mutates `stats` and appends escalations in place."""
    msg_id = msg.get("MessageId", "?")
    receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    body_str = msg.get("Body", "")
    fn_name = extract_function_name(msg)
    retryable = fn_name is not None
    fn_label = fn_name or "unknown"

    stable_id = stable_message_id(fn_label, body_str)
    attempts = record_failure(stable_id, fn_label, receive_count, body_str)
    classification = classify_message(msg)

    logger.info(
        f"Processing {msg_id} (fn={fn_label}, receive_count={receive_count}, "
        f"cumulative_attempts={attempts}, class={classification}, retryable={retryable})"
    )

    # Escalate on: an explicitly-permanent classification, an unretryable message
    # (we can't ever re-invoke it), or a cumulative attempt count that crossed the
    # durable threshold. This is the count that v1 could never accumulate.
    escalate = classification == "permanent" or not retryable or attempts >= ESCALATE_THRESHOLD

    if not escalate:
        # Transient, below threshold → attempt one re-invoke.
        stats["transient"] += 1
        retry_ok = retry_message(msg, fn_name)
        if retry_ok:
            stats["retried_ok"] += 1
            _delete(msg, msg_id)  # confirmed accepted — safe to delete; count persists in the ledger
        else:
            # NOT confirmed. Leave on the queue: it redrives, ApproximateReceiveCount
            # climbs, and record_failure accumulates until it escalates. This is the
            # "delete only after a confirmed re-invoke outcome" rule.
            stats["retried_fail"] += 1
            stats["left_on_queue"] += 1
            logger.warning(f"  ⏳ Retry not confirmed — leaving {msg_id} on queue to redrive")
        return

    # Escalation path.
    reason = classification if classification == "permanent" else ("unretryable" if not retryable else "threshold")
    stats["escalated"] += 1
    s3_key = archive_to_s3(msg, reason, retry_attempted=False, attempts=attempts)
    mark_escalated(stable_id)
    escalations.append(
        {
            "message_id": msg_id,
            "function_name": fn_label,
            "attempts": attempts,
            "classification": reason,
            "body": body_str,
            "s3_key": s3_key,
        }
    )
    _delete(msg, msg_id)


def _delete(msg: dict, msg_id: str) -> None:
    try:
        sqs.delete_message(QueueUrl=DLQ_URL, ReceiptHandle=msg["ReceiptHandle"])
        logger.info(f"  🗑️  Deleted from DLQ: {msg_id}")
    except Exception as e:
        logger.error(f"  Failed to delete message {msg_id}: {e}")


# ── Main handler ───────────────────────────────────────────────────────────────


def _time_left_ms(context, started: float) -> int:
    """Milliseconds of run budget remaining — the lesser of the Lambda's own
    remaining time and our wall-clock DRAIN_BUDGET_SECONDS."""
    wall_left = int((DRAIN_BUDGET_SECONDS - (time.time() - started)) * 1000)
    try:
        lambda_left = int(context.get_remaining_time_in_millis()) - SAFETY_MARGIN_MS
    except Exception:
        lambda_left = wall_left
    return min(wall_left, lambda_left)


def lambda_handler(event, context):
    try:
        if not DLQ_URL:
            logger.error("DLQ_URL env var not set — cannot poll SQS")
            return {"statusCode": 500, "body": "DLQ_URL not configured"}

        logger.info(f"DLQ consumer starting — polling {DLQ_URL} (budget={DRAIN_BUDGET_SECONDS}s)")
        now = datetime.now(timezone.utc).isoformat()
        started = time.time()

        stats = {
            "transient": 0,
            "escalated": 0,
            "retried_ok": 0,
            "retried_fail": 0,
            "left_on_queue": 0,
        }
        escalations: list[dict] = []
        processed = 0

        # ── Drain by time budget (not a fixed 10-message cap) ──────────────────────
        while processed < ABSOLUTE_MESSAGE_CAP and _time_left_ms(context, started) > 0:
            response = sqs.receive_message(
                QueueUrl=DLQ_URL,
                MaxNumberOfMessages=RECEIVE_BATCH,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
                WaitTimeSeconds=2,  # short long-poll; loop handles the draining
            )
            messages = response.get("Messages", [])
            if not messages:
                break
            for msg in messages:
                process_message(msg, stats, escalations)
                processed += 1

        if processed == 0:
            logger.info("DLQ empty — nothing to process")
            return {"statusCode": 200, "body": json.dumps({"messages_found": 0, "checked_at": now})}

        # ── Escalate (page + summary) ──────────────────────────────────────────────
        if escalations:
            page_operator(escalations)
            send_alert(escalations)

        logger.info(
            f"DLQ run complete: processed={processed} "
            f"transient={stats['transient']} escalated={stats['escalated']} "
            f"retried_ok={stats['retried_ok']} retried_fail={stats['retried_fail']} "
            f"left_on_queue={stats['left_on_queue']}"
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "messages_processed": processed,
                    "stats": stats,
                    "escalated": [e["message_id"] for e in escalations],
                    "ran_at": now,
                }
            ),
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
