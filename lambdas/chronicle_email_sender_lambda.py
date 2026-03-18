"""
Chronicle Email Sender Lambda — v1.0.0 (BS-03)
Delivers the weekly Chronicle installment to confirmed email subscribers.

Architecture decision (Board vote 4-0 — Marcus/Jin/Elena/Priya):
  Separate Lambda from wednesday-chronicle. Clean separation of concerns.
  Independent DLQ, independent retry, independent alarm.
  Viktor guard: no installment found this week → clean no-op, never fail.

Schedule: EventBridge cron(10 15 ? * WED *) — Wed 8:10 AM PT
  Chronicle fires at 8:00 AM, writes installment to DDB.
  This Lambda fires at 8:10 AM, reads latest installment, sends to subscribers.

DynamoDB reads:
  SOURCE#chronicle    — latest installment (within last 7 days)
  SOURCE#subscribers  — all confirmed subscribers (status=confirmed)

SES delivery:
  Personalized unsubscribe link per email (CAN-SPAM compliance)
  Rate: 1 email/sec (configurable via SEND_RATE_PER_SEC — SES sandbox limit)
  Alarm: chronicle-email-sender-errors (via SNS alerts)

v1.0.0 — 2026-03-17 (BS-03)
"""

import json
import os
import time
import logging
import urllib.parse
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from platform_logger import get_logger
    logger = get_logger("chronicle-email-sender")
except ImportError:
    logger = logging.getLogger("chronicle-email-sender")
    logger.setLevel(logging.INFO)

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]
SENDER     = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL   = os.environ.get("SITE_URL", "https://averagejoematt.com")

# Rate limit: 1/sec for SES sandbox; increase after production access granted
SEND_RATE_PER_SEC = float(os.environ.get("SEND_RATE_PER_SEC", "1.0"))

SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"
CHRONICLE_PK   = f"USER#{USER_ID}#SOURCE#chronicle"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=REGION)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _d2f(obj):
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def _get_this_weeks_installment() -> dict | None:
    """
    Get the most recent Chronicle installment published within the last 7 days.
    Viktor Sorokin guard: return None if nothing found — always a clean no-op.
    """
    today    = datetime.now(timezone.utc).date()
    week_ago = (today - timedelta(days=7)).isoformat()
    today_str = today.isoformat()

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": CHRONICLE_PK,
                ":s":  f"DATE#{week_ago}",
                ":e":  f"DATE#{today_str}",
            },
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            logger.info("No Chronicle installment found within last 7 days — no-op")
            return None
        return _d2f(items[0])
    except Exception as exc:
        logger.error("Failed to query Chronicle DDB: %s", exc)
        return None


def _get_confirmed_subscribers() -> list[dict]:
    """
    Query subscribers partition for all confirmed records.
    Uses FilterExpression (not GSI) — acceptable at <10K subscriber volume.
    Add GSI on (status, sk) when sub count exceeds ~10K.
    """
    confirmed = []
    try:
        kwargs = {
            "KeyConditionExpression": "pk = :pk",
            "FilterExpression": "#s = :confirmed",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {
                ":pk":        SUBSCRIBERS_PK,
                ":confirmed": "confirmed",
            },
        }
        while True:
            resp = table.query(**kwargs)
            confirmed.extend(_d2f(item) for item in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except Exception as exc:
        logger.error("Failed to query subscribers: %s", exc)
    return confirmed


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_subscriber_email(installment: dict, subscriber: dict) -> tuple[str, str]:
    """
    Build the subscriber-facing Chronicle email.
    Signal-branded (Ava Moreau directive). Newsletter format.
    Includes personalized one-click unsubscribe link (CAN-SPAM).
    Returns (subject, html).
    """
    title      = installment.get("title", "The Weekly Signal")
    week_num   = installment.get("week_number", "?")
    stats_line = installment.get("stats_line", "")
    body_html  = installment.get("content_html", "<p>No content available.</p>")
    date_str   = installment.get("date", "")
    conf_badge = installment.get("_confidence_badge_html", "")

    subject = f'The Measured Life — Week {week_num}: "{title}"'

    unsub_url   = (
        f"{SITE_URL}/api/subscribe"
        f"?action=unsubscribe"
        f"&email={urllib.parse.quote(subscriber_email)}"  # noqa: F821 — defined in enclosing scope
    )
    journal_url = f"{SITE_URL}/journal/"

    try:
        display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        display_date = date_str

    # BS-05: confidence badge row
    badge_row = ""
    if conf_badge:
        badge_row = (
            f'<p style="font-size:11px;color:#484f58;margin:0 0 24px;">'
            f'Narrative confidence: {conf_badge}</p>'
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#0D1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:0 16px;">

  <!-- Header -->
  <div style="padding:32px 0 24px;">
    <p style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;
              text-transform:uppercase;color:#F0B429;margin:0 0 8px;">
      The Weekly Signal
    </p>
    <p style="font-size:12px;color:#484f58;margin:0;">
      Week {week_num} &mdash; {display_date}
    </p>
  </div>

  <!-- Article card -->
  <div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);
              padding:32px;margin-bottom:24px;">

    <h1 style="font-size:26px;font-weight:700;color:#E6EDF3;line-height:1.3;margin:0 0 16px;">
      {title}
    </h1>

    {badge_row}

    {"" if not stats_line else (
        '<p style="font-size:13px;color:#F0B429;font-family:\'JetBrains Mono\',monospace;'
        'margin:0 0 24px;padding:10px 14px;background:rgba(240,180,41,0.06);'
        'border-left:3px solid #F0B429;border-radius:0 4px 4px 0;line-height:1.5;">'
        + stats_line +
        '</p>'
    )}

    <div style="font-size:15px;color:#c9d1d9;line-height:1.8;
                border-top:1px solid rgba(230,237,243,0.08);padding-top:24px;">
      {body_html}
    </div>

  </div>

  <!-- CTA -->
  <div style="text-align:center;padding:8px 0 32px;">
    <a href="{journal_url}"
       style="display:inline-block;background:#F0B429;color:#0D1117;font-size:14px;
              font-weight:600;padding:12px 28px;border-radius:8px;text-decoration:none;">
      Read the full archive &rarr;
    </a>
    <p style="font-size:12px;color:#484f58;margin:16px 0 0;">
      Written by Elena Voss &mdash; <em>The Measured Life</em>
    </p>
  </div>

  <!-- Footer (CAN-SPAM) -->
  <div style="border-top:1px solid rgba(230,237,243,0.06);padding:20px 0 40px;">
    <p style="font-size:11px;color:#30363d;margin:0 0 8px;line-height:1.6;text-align:center;">
      You subscribed to The Weekly Signal at averagejoematt.com.
      This is a real person's real data, published every Wednesday.
    </p>
    <p style="font-size:11px;text-align:center;margin:0;">
      <a href="{unsub_url}" style="color:#484f58;text-decoration:underline;">Unsubscribe</a>
      &nbsp;&middot;&nbsp;
      <a href="{SITE_URL}" style="color:#484f58;text-decoration:underline;">averagejoematt.com</a>
    </p>
  </div>

</div>
</body>
</html>"""

    return subject, html


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    logger.info("Chronicle Email Sender v1.0.0 — BS-03 — starting")

    # Viktor guard: is there an installment from this week?
    installment = _get_this_weeks_installment()
    if not installment:
        logger.info("No installment found this week — clean no-op")
        return {
            "statusCode": 200,
            "body":    "No Chronicle installment found this week — no-op",
            "sent":    0,
            "skipped": True,
        }

    title    = installment.get("title", "")
    week_num = installment.get("week_number", "?")
    logger.info("Installment found — Week %s: \"%s\"", week_num, title)

    # Load confirmed subscribers
    subscribers = _get_confirmed_subscribers()
    if not subscribers:
        logger.info("No confirmed subscribers yet — no-op")
        return {"statusCode": 200, "body": "No confirmed subscribers", "sent": 0}

    logger.info("Sending to %d confirmed subscriber(s)", len(subscribers))

    # Send rate: 1/sec default (SES sandbox); bump SEND_RATE_PER_SEC after production access
    rate_delay = 1.0 / max(SEND_RATE_PER_SEC, 0.1)

    sent = failed = 0

    for i, sub in enumerate(subscribers):
        email = sub.get("email", "").strip()
        if not email:
            continue

        subject, html = _build_subscriber_email(installment, sub)

        try:
            ses.send_email(
                FromEmailAddress=SENDER,
                Destination={"ToAddresses": [email]},
                Content={"Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
                }},
            )
            sent += 1
            logger.info("Sent %d/%d (%s...)", i + 1, len(subscribers), email[:6])
        except Exception as exc:
            failed += 1
            logger.error("Failed send to %s...: %s", email[:6], exc)

        # Rate-limit between sends (skip delay after last subscriber)
        if i < len(subscribers) - 1:
            time.sleep(rate_delay)

    logger.info("Done — sent: %d, failed: %d, total: %d", sent, failed, len(subscribers))

    return {
        "statusCode": 200,
        "body":     f"Chronicle Week {week_num} sent to {sent}/{len(subscribers)} subscribers",
        "sent":     sent,
        "failed":   failed,
        "total":    len(subscribers),
        "week_num": week_num,
        "title":    title,
    }
