"""
weekly_signal_lambda.py — PB-06: "The Weekly Signal" subscriber email.

Curated 5-section summary sent to subscribers every Sunday at 9:30 AM PT.
Reads pre-computed data from S3 + DynamoDB — no AI calls.

Schedule: cron(30 16 ? * SUN *)  (9:30 AM PT = 16:30 UTC)
Model: chronicle_email_sender_lambda.py (same subscriber query, SES pattern, rate limiting)

Sections:
  1. The Numbers — weight, sleep, recovery, character
  2. Chronicle Preview — latest Elena Voss headline
  3. What Worked / What Didn't — top weekly insight
  4. The Board Says — rotating board member quote
  5. Observatory Spotlight — rotating page highlight
"""

import json
import os
import time
import logging
import urllib.parse
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal

try:
    from platform_logger import get_logger
    logger = get_logger("weekly-signal")
except ImportError:
    logger = logging.getLogger("weekly-signal")
    logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
SENDER     = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL   = os.environ.get("SITE_URL", "https://averagejoematt.com")
SEND_RATE  = float(os.environ.get("SEND_RATE_PER_SEC", "1.0"))

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
ses      = boto3.client("sesv2", region_name=REGION)

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

OBSERVATORY_ROTATION = [
    {"name": "Sleep",     "path": "/sleep/",     "hook": "How your sleep patterns shape recovery and readiness."},
    {"name": "Glucose",   "path": "/glucose/",   "hook": "CGM data revealing how food choices affect energy and metabolic health."},
    {"name": "Nutrition", "path": "/nutrition/",  "hook": "Macro targets, meal timing, and what the data says about fueling."},
    {"name": "Training",  "path": "/training/",   "hook": "Strain, recovery balance, and how training load connects to progress."},
    {"name": "Inner Life", "path": "/mind/",      "hook": "Journaling, habits, and the behavioral data behind consistency."},
]

BOARD_ROTATION = [
    {"name": "The Chair",    "title": "Board Chair"},
    {"name": "Dr. Chen",     "title": "Behavioral Science"},
    {"name": "Dr. Okafor",   "title": "Longevity Medicine"},
    {"name": "Dr. Park",     "title": "Sleep & Circadian"},
    {"name": "Dr. Patrick",  "title": "Metabolic Health"},
]


def _d2f(obj):
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def _s3_json(key):
    """Read JSON from S3, return None on error."""
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.warning("S3 read failed (%s): %s", key, e)
        return None


def _get_confirmed_subscribers():
    confirmed = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk",
        "FilterExpression": "#s = :confirmed",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {
            ":pk":        f"{USER_PREFIX}subscribers",
            ":confirmed": "confirmed",
        },
    }
    try:
        while True:
            resp = table.query(**kwargs)
            confirmed.extend(_d2f(item) for item in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except Exception as e:
        logger.error("Subscriber query failed: %s", e)
    return confirmed


def _get_weekly_insight():
    """Get the most recent coaching/guidance insight from last 7 days."""
    today = datetime.now(timezone.utc).date()
    week_ago = (today - timedelta(days=7)).isoformat()
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": f"{USER_PREFIX}computed_insights",
                ":s":  f"DATE#{week_ago}",
                ":e":  f"DATE#{today.isoformat()}",
            },
            ScanIndexForward=False,
            Limit=5,
        )
        items = [_d2f(i) for i in resp.get("Items", [])]
        for item in items:
            guidance = item.get("guidance_given") or item.get("top_insight") or item.get("summary")
            if guidance:
                return guidance
    except Exception as e:
        logger.warning("Insight query failed: %s", e)
    return None


# ── Section builders ──────────────────────────────────────────────────────────

def _sec(title, content):
    """Wrap content in a styled section box."""
    return f'''<div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);padding:24px 28px;margin-bottom:16px;">
  <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#3db88a;margin:0 0 16px;">{title}</p>
  {content}
</div>'''


def _build_numbers(stats):
    vitals = stats.get("vitals", {})
    char = stats.get("character", {})
    weight = vitals.get("weight_lbs")
    delta = vitals.get("weight_delta_30d")
    sleep = vitals.get("sleep_hours_30d_avg")
    recovery = vitals.get("recovery_pct")
    level = char.get("level", "?")
    tier = char.get("tier", "")

    rows = []
    if weight is not None:
        arrow = "↓" if delta and delta < 0 else "↑" if delta and delta > 0 else ""
        delta_str = f" ({arrow}{abs(delta):.1f} lbs 30d)" if delta else ""
        rows.append(f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Weight</td><td style="color:#c9d1d9;font-weight:600;">{weight} lbs{delta_str}</td></tr>')
    if sleep:
        rows.append(f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Avg Sleep</td><td style="color:#c9d1d9;font-weight:600;">{sleep:.1f} hrs</td></tr>')
    if recovery:
        rows.append(f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Recovery</td><td style="color:#c9d1d9;font-weight:600;">{recovery:.0f}%</td></tr>')
    rows.append(f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Character</td><td style="color:#c9d1d9;font-weight:600;">Level {level} · {tier}</td></tr>')

    return _sec("The Numbers", f'<table style="font-size:14px;line-height:1.8;">{"".join(rows)}</table>')


def _build_chronicle(posts_data):
    posts = posts_data.get("posts", []) if isinstance(posts_data, dict) else posts_data
    if not posts:
        return ""
    latest = posts[0]
    title = latest.get("title", "")
    excerpt = latest.get("excerpt", "")
    url = latest.get("url", "/chronicle/")
    # Truncate excerpt to ~2 sentences
    sentences = excerpt.split(". ")
    preview = ". ".join(sentences[:2]) + ("." if len(sentences) > 1 else "")
    return _sec("Chronicle Preview", f'''<p style="font-size:16px;color:#c9d1d9;font-weight:600;margin:0 0 8px;">{title}</p>
  <p style="font-size:13px;color:#8b949e;line-height:1.6;margin:0 0 12px;">{preview}</p>
  <a href="{SITE_URL}{url}" style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:1px;color:#3db88a;text-decoration:none;">Read more →</a>''')


def _build_worked(insight_text):
    if not insight_text:
        return ""
    return _sec("What Worked This Week",
                f'<p style="font-size:13px;color:#c9d1d9;line-height:1.7;margin:0;">{insight_text}</p>')


def _build_board_quote(week_num):
    member = BOARD_ROTATION[week_num % len(BOARD_ROTATION)]
    return _sec("The Board Says",
                f'<p style="font-size:13px;color:#c9d1d9;line-height:1.7;margin:0 0 8px;font-style:italic;">"Check the data, not the mirror. Progress at this stage is measured in trends, not snapshots."</p>'
                f'<p style="font-family:\'Courier New\',monospace;font-size:10px;color:#8b949e;margin:0;">— {member["name"]}, {member["title"]}</p>')


def _build_spotlight(week_num):
    obs = OBSERVATORY_ROTATION[week_num % len(OBSERVATORY_ROTATION)]
    return _sec("Observatory Spotlight",
                f'<p style="font-size:14px;color:#c9d1d9;font-weight:600;margin:0 0 8px;">{obs["name"]}</p>'
                f'<p style="font-size:13px;color:#8b949e;line-height:1.6;margin:0 0 12px;">{obs["hook"]}</p>'
                f'<a href="{SITE_URL}{obs["path"]}" style="font-family:\'Courier New\',monospace;font-size:11px;letter-spacing:1px;color:#3db88a;text-decoration:none;">Explore {obs["name"]} →</a>')


def _build_email(stats, posts_data, insight_text, week_num, unsub_url):
    now = datetime.now(timezone.utc)
    display_date = now.strftime("%B %d, %Y")

    s1 = _build_numbers(stats) if stats else ""
    s2 = _build_chronicle(posts_data) if posts_data else ""
    s3 = _build_worked(insight_text)
    s4 = _build_board_quote(week_num)
    s5 = _build_spotlight(week_num)

    subject = f"Week {week_num} — The Measured Life"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Week {week_num} — The Weekly Signal</title></head>
<body style="margin:0;padding:0;background:#0D1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:0 16px;">
  <div style="padding:32px 0 24px;">
    <p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#3db88a;margin:0 0 8px;">The Weekly Signal</p>
    <p style="font-size:12px;color:#484f58;margin:0;">Week {week_num} — {display_date}</p>
  </div>
  {s1}{s2}{s3}{s4}{s5}
  <div style="border-top:1px solid rgba(230,237,243,0.06);padding:20px 0 40px;">
    <p style="font-size:11px;color:#30363d;margin:0 0 8px;line-height:1.6;text-align:center;">
      You subscribed to The Weekly Signal at averagejoematt.com.<br>
      One person's real data, published without filters.
    </p>
    <p style="font-size:11px;text-align:center;margin:0;">
      <a href="{unsub_url}" style="color:#484f58;text-decoration:underline;">Unsubscribe</a>
      &nbsp;&middot;&nbsp;
      <a href="{SITE_URL}" style="color:#484f58;text-decoration:underline;">averagejoematt.com</a>
    </p>
  </div>
</div></body></html>"""
    return subject, html


# ── Handler ───────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    try:
        logger.info("Weekly Signal v1.0.0 — PB-06 — starting")

        # Load data (graceful degradation: missing data = skip section, not crash)
        stats = _s3_json("generated/public_stats.json")
        posts_data = _s3_json("generated/journal/posts.json")
        insight_text = _get_weekly_insight()

        now = datetime.now(timezone.utc)
        week_num = int(now.strftime("%W"))

        # Load subscribers
        subscribers = _get_confirmed_subscribers()
        if not subscribers:
            logger.info("No confirmed subscribers — no-op")
            return {"statusCode": 200, "body": "No confirmed subscribers", "sent": 0}

        logger.info("Sending Weekly Signal (week %d) to %d subscribers", week_num, len(subscribers))

        sent = failed = 0
        rate_delay = 1.0 / max(SEND_RATE, 0.1)

        for i, sub in enumerate(subscribers):
            email = sub.get("email", "").strip()
            if not email:
                continue

            unsub_url = f"{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(email)}"
            subject, html = _build_email(stats, posts_data, insight_text, week_num, unsub_url)

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

            if i < len(subscribers) - 1:
                time.sleep(rate_delay)

        logger.info("Weekly Signal complete: sent=%d, failed=%d, total=%d", sent, failed, len(subscribers))

        return {
            "statusCode": 200,
            "body": f"Weekly Signal week {week_num} sent to {sent}/{len(subscribers)} subscribers",
            "sent": sent,
            "failed": failed,
            "total": len(subscribers),
            "week_num": week_num,
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
