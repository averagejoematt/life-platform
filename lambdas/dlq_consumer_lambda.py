"""
dlq_consumer_lambda.py — REL-2: Dead Letter Queue Consumer
Version: 1.0.0

Polls life-platform-ingestion-dlq on a schedule (every 6 hours).
Classifies each failed message, retries transient failures by re-invoking
the original Lambda, and sends an SES alert for permanent failures.

Classification:
  TRANSIENT — timeout, throttle, transient API error → retry once via Lambda invoke
  PERMANENT — auth failure, missing resource, repeated failure → alert + archive to S3

Strategy:
  - Read up to 10 messages per run (SQS batch limit)
  - Inspect message body + metadata to classify
  - Transient: re-invoke original Lambda with same payload, delete from DLQ on success
  - Permanent (or retry failed): write to S3 dead-letter-archive/, send alert email, delete
  - Max retries: if approximateReceiveCount >= 3, treat as permanent regardless

DLQ: life-platform-ingestion-dlq (SQS)
Schedule: every 6 hours (EventBridge: dlq-consumer-schedule)
IAM role: lambda-dlq-consumer-role

Environment variables:
  TABLE_NAME    (default: life-platform)
  S3_BUCKET     (default: matthew-life-platform)
  DLQ_URL       (required — set from deploy script)
  REGION        (default: us-west-2)
"""

import json
import os
import logging
import boto3
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ["S3_BUCKET"]
DLQ_URL    = os.environ.get("DLQ_URL", "")
RECIPIENT  = "awsdev@mattsusername.com"
SENDER     = "awsdev@mattsusername.com"

MAX_MESSAGES_PER_RUN = 10
MAX_RETRY_COUNT      = 3   # treat as permanent if receive count >= this

# ── AWS clients ────────────────────────────────────────────────────────────────
sqs     = boto3.client("sqs",        region_name=REGION)
lam     = boto3.client("lambda",     region_name=REGION)
ses     = boto3.client("sesv2",      region_name=REGION)
s3      = boto3.client("s3",         region_name=REGION)


# ── Classification ─────────────────────────────────────────────────────────────

# Keywords in error messages that indicate transient failures
TRANSIENT_PATTERNS = [
    "timeout", "timed out", "throttl", "rate limit", "503",
    "502", "connection", "socket", "temporary", "try again",
    "retryable", "service unavailable", "task timed out",
    "connection reset", "read timeout", "connect timeout",
]

# Keywords that indicate permanent failures
PERMANENT_PATTERNS = [
    "auth", "unauthorized", "403", "401", "forbidden",
    "invalid token", "expired token", "no such key",
    "nosuchkey", "access denied", "not found", "404",
    "validation", "malformed", "invalid parameter",
]


def classify_message(message: dict) -> str:
    """
    Returns 'transient' or 'permanent'.
    Bases decision on:
      1. ApproximateReceiveCount (3+ = permanent)
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


# ── Retry logic ────────────────────────────────────────────────────────────────

def extract_function_name(message: dict) -> str | None:
    """
    Extract the original Lambda function name from SQS DLQ metadata.
    SQS DLQs from Lambda async invocations include the source in the
    message attributes or in the event source ARN.
    """
    # Check message attributes first (Lambda sets these)
    msg_attrs = message.get("MessageAttributes", {})
    for attr_name in ["RequestID", "ErrorCode", "ErrorMessage"]:
        if attr_name in msg_attrs:
            # Lambda DLQ messages don't directly include function name in attrs
            break

    # Try to extract from body (some Lambda DLQ payloads include metadata)
    try:
        body = json.loads(message.get("Body", "{}"))
        # Lambda async error records sometimes include the function name
        fn = (body.get("function_name")
              or body.get("FunctionName")
              or body.get("lambda_function"))
        if fn:
            return fn
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def retry_message(message: dict) -> bool:
    """
    Attempt to re-invoke the original Lambda with the same payload.
    Returns True if retry succeeded (Lambda returned 2xx), False otherwise.
    """
    body_str = message.get("Body", "{}")
    fn_name = extract_function_name(message)

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

def archive_to_s3(message: dict, classification: str, retry_attempted: bool) -> str:
    """Write failed message to S3 dead-letter-archive/ for post-mortem analysis."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y/%m/%d")
    msg_id = message.get("MessageId", "unknown")
    s3_key = f"dead-letter-archive/{ts}/{msg_id}.json"

    archive_record = {
        "archived_at":      now.isoformat(),
        "message_id":       msg_id,
        "classification":   classification,
        "retry_attempted":  retry_attempted,
        "receive_count":    message.get("Attributes", {}).get("ApproximateReceiveCount"),
        "sent_timestamp":   message.get("Attributes", {}).get("SentTimestamp"),
        "body":             message.get("Body", ""),
        "attributes":       message.get("Attributes", {}),
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


# ── Alerting ───────────────────────────────────────────────────────────────────

def send_alert(permanent_failures: list[dict]) -> None:
    """Send a single consolidated SES alert for all permanent failures in this run."""
    if not permanent_failures:
        return

    count = len(permanent_failures)
    rows = ""
    for f in permanent_failures:
        msg_id   = f.get("message_id", "?")
        fn_name  = f.get("function_name", "unknown")
        body_pre = str(f.get("body", ""))[:200].replace("<", "&lt;").replace(">", "&gt;")
        s3_key   = f.get("s3_key", "")
        rows += f"""
        <tr>
          <td style="padding:6px 12px;border-bottom:1px solid #333;">{msg_id[:12]}…</td>
          <td style="padding:6px 12px;border-bottom:1px solid #333;">{fn_name}</td>
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
  <h2>⚠️ DLQ — {count} Permanent Failure{'s' if count > 1 else ''}</h2>
  <p style="color:#aaa;">These messages could not be retried and have been archived to S3.</p>
  <table>
    <tr>
      <th>Message ID</th><th>Function</th><th>Body Preview</th><th>S3 Archive</th>
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
                    "Subject": {"Data": f"⚠️ Life Platform: {count} DLQ permanent failure{'s' if count > 1 else ''}"},
                    "Body": {"Html": {"Data": html}},
                }
            },
        )
        logger.info(f"  📧 Alert sent: {count} permanent failures")
    except Exception as e:
        logger.error(f"  Failed to send SES alert: {e}")


# ── Main handler ───────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    if not DLQ_URL:
        logger.error("DLQ_URL env var not set — cannot poll SQS")
        return {"statusCode": 500, "body": "DLQ_URL not configured"}

    logger.info(f"DLQ consumer starting — polling {DLQ_URL}")
    now = datetime.now(timezone.utc).isoformat()

    # ── Poll DLQ ──────────────────────────────────────────────────────────────
    response = sqs.receive_message(
        QueueUrl=DLQ_URL,
        MaxNumberOfMessages=MAX_MESSAGES_PER_RUN,
        AttributeNames=["All"],
        MessageAttributeNames=["All"],
        WaitTimeSeconds=5,  # long poll, up to 5s
    )
    messages = response.get("Messages", [])

    if not messages:
        logger.info("DLQ empty — nothing to process")
        return {
            "statusCode": 200,
            "body": json.dumps({"messages_found": 0, "checked_at": now}),
        }

    logger.info(f"Found {len(messages)} messages in DLQ")

    # ── Process each message ──────────────────────────────────────────────────
    stats = {"transient": 0, "permanent": 0, "retried_ok": 0, "retried_fail": 0}
    permanent_failures = []

    for msg in messages:
        msg_id = msg.get("MessageId", "?")
        receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        fn_name = extract_function_name(msg) or "unknown"
        logger.info(f"Processing message {msg_id} (receive_count={receive_count}, fn={fn_name})")

        classification = classify_message(msg)
        retry_attempted = False
        retry_ok = False

        if classification == "transient":
            stats["transient"] += 1
            retry_attempted = True
            retry_ok = retry_message(msg)
            if retry_ok:
                stats["retried_ok"] += 1
            else:
                stats["retried_fail"] += 1
                # Retry failed — escalate to permanent handling
                classification = "permanent"

        if classification == "permanent":
            stats["permanent"] += 1
            s3_key = archive_to_s3(msg, classification, retry_attempted)
            permanent_failures.append({
                "message_id": msg_id,
                "function_name": fn_name,
                "body": msg.get("Body", ""),
                "s3_key": s3_key,
                "receive_count": receive_count,
            })

        # Always delete from DLQ after processing
        try:
            sqs.delete_message(
                QueueUrl=DLQ_URL,
                ReceiptHandle=msg["ReceiptHandle"],
            )
            logger.info(f"  🗑️  Deleted from DLQ: {msg_id}")
        except Exception as e:
            logger.error(f"  Failed to delete message {msg_id}: {e}")

    # ── Alert on permanent failures ───────────────────────────────────────────
    if permanent_failures:
        send_alert(permanent_failures)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info(
        f"DLQ run complete: "
        f"processed={len(messages)} "
        f"transient={stats['transient']} "
        f"permanent={stats['permanent']} "
        f"retried_ok={stats['retried_ok']} "
        f"retried_fail={stats['retried_fail']}"
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "messages_processed": len(messages),
            "stats": stats,
            "permanent_failures": [f["message_id"] for f in permanent_failures],
            "ran_at": now,
        }),
    }
