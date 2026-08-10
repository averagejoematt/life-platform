"""
Subscriber Onboarding Lambda — Day 2 Bridge Email
Sends curated Chronicle installments to new subscribers who confirmed
1-6 days ago and whose next Wednesday is 3+ days away.

Schedule: EventBridge cron(5 17 * * ? *) — 10:05 AM PT daily (CDK SubscriberOnboarding,
staggered from the daily brief; the old cron(0 16) hand-created rule was an orphan, #1257).

Dry-run posture (#2291): this module is SCHEDULE-triggered, so it is NOT exempt
from the default SES send-suppressor — #2222's "event-driven" exemption for it was
factually wrong (the exemption axis is trigger type, and this function carries an
EventBridge schedule= in cdk/stacks/email_stack.py). It now routes every send
through common.send_guard.guarded_send_email: an operator invoke with
{"dry_run": true} (or the DRY_RUN env var) suppresses every send AND the
onboarding_sent marker write, and reports what would have gone out.
"""

import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone

import boto3
from common.pacific_time import PACIFIC as PT  # #2414: reader-facing days anchor in the Pacific frame
from common.send_guard import guarded_send_email, is_dry_run

try:
    from common.platform_logger import get_logger

    logger = get_logger("subscriber-onboarding")
except ImportError:
    logger = logging.getLogger("subscriber-onboarding")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")

SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

# Fallback pages when no Chronicle posts exist yet. v4 "three doors" routing —
# the legacy /live//chronicle/ paths now 301, which adds a redirect hop to every
# email link, so point straight at the v4 destinations.
FALLBACK_PAGES = [
    {"label": "The Story", "title": "Why I'm doing this — and what I'm tracking", "path": "/story/"},
    {"label": "The Cockpit", "title": "Live daily dashboard — weight, sleep, recovery, habits", "path": "/cockpit/"},
    {"label": "The Chronicle", "title": "Weekly dispatches from inside the experiment", "path": "/story/chronicle/"},
]


def _get_published_posts(max_posts=3):
    """Read posts.json from S3 to get actually-published Chronicle posts.
    Returns list of dicts with label, title, path — or FALLBACK_PAGES if none exist.

    The subscriber-onboarding role has s3:GetObject on generated/journal/posts.json
    (role_policies.subscriber_onboarding, added #352)."""
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")
        data = json.loads(resp["Body"].read())
        posts = data.get("posts", data) if isinstance(data, dict) else data
        # Only include published posts with valid URLs
        published = [p for p in posts if p.get("url") and p.get("status", "published") == "published"]
        if not published:
            return FALLBACK_PAGES
        # Sort by week descending (most recent first), take top N
        published.sort(key=lambda p: p.get("week", 0), reverse=True)
        return [{"label": f"Week {p.get('week', '?')}", "title": p["title"], "path": p["url"]} for p in published[:max_posts]]
    except Exception as e:
        logger.warning(f"Could not load posts.json: {e}")
        return FALLBACK_PAGES


def _days_until_wednesday():
    """Days from today until next Wednesday."""
    today = datetime.now(timezone.utc).weekday()  # Mon=0, Wed=2
    days = (2 - today) % 7
    return days if days > 0 else 7


def _build_onboarding_email(email: str) -> tuple[str, str]:
    """Build the Day 2 bridge email with curated installments."""
    subject = "Welcome to The Weekly Signal \u2014 here's what you're following"

    unsub_url = f"{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(email)}"

    # Dynamically load published content — adapts as new posts are approved
    featured_pages = _get_published_posts(max_posts=3)

    cards_html = ""
    for page in featured_pages:
        cards_html += f"""
    <div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);
                padding:20px 24px;margin-bottom:12px;">
      <p style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;
                text-transform:uppercase;color:#F0B429;margin:0 0 8px;">{page['label']}</p>
      <p style="font-size:16px;font-weight:600;color:#E6EDF3;margin:0 0 8px;">{page['title']}</p>
      <a href="{SITE_URL}{page['path']}" style="color:#F0B429;font-size:13px;font-weight:600;text-decoration:none;">
        Explore \u2192
      </a>
    </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0D1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:520px;margin:40px auto;padding:0 16px;">

  <p style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;
            text-transform:uppercase;color:#F0B429;margin:0 0 24px;">The Weekly Signal</p>

  <h1 style="font-size:20px;font-weight:600;color:#E6EDF3;line-height:1.3;margin:0 0 16px;">
    Your first Signal arrives Wednesday.
  </h1>

  <p style="font-size:15px;color:#8b949e;line-height:1.65;margin:0 0 24px;">
    While you wait, here's what this experiment is about \u2014 the data,
    the honesty, and why accountability needs an audience.
  </p>

  {cards_html}

  <div style="border-top:1px solid rgba(230,237,243,0.06);padding:20px 0 40px;margin-top:24px;">
    <p style="font-size:11px;color:#30363d;margin:0 0 8px;line-height:1.6;text-align:center;">
      You subscribed to The Weekly Signal at averagejoematt.com.
    </p>
    <p style="font-size:11px;text-align:center;margin:0;">
      <a href="{unsub_url}" style="color:#484f58;text-decoration:underline;">Unsubscribe</a>
      &nbsp;\u00b7&nbsp;
      <a href="{SITE_URL}" style="color:#484f58;text-decoration:underline;">averagejoematt.com</a>
    </p>
  </div>

</div>
</body>
</html>"""

    return subject, html


def lambda_handler(event, context):
    """Query new subscribers and send Day 2 bridge email.

    #2291: `{"dry_run": true}` (or DRY_RUN env) suppresses every send and the
    `onboarding_sent` marker write — the run reports what it would have sent.
    """
    if hasattr(logger, "set_date"):
        logger.set_date(datetime.now(PT).strftime("%Y-%m-%d"))

    dry_run = is_dry_run(event)
    if dry_run:
        logger.info("dry run — sends and onboarding_sent markers will be suppressed")

    now = datetime.now(timezone.utc)
    days_to_wed = _days_until_wednesday()

    # Only send if next Wednesday is 3+ days away
    if days_to_wed < 3:
        logger.info(f"Wednesday is {days_to_wed} days away — skipping onboarding emails")
        return {"statusCode": 200, "body": "Too close to Wednesday — skipping"}

    # Query all confirmed subscribers
    try:
        resp = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(SUBSCRIBERS_PK),
            FilterExpression="attribute_exists(confirmed_at) AND attribute_not_exists(onboarding_sent)",
        )
        subscribers = resp.get("Items", [])
    except Exception as e:
        logger.error(f"Failed to query subscribers: {e}")
        return {"statusCode": 500, "body": "Internal server error"}

    sent_count = 0
    would_send_count = 0
    for sub in subscribers:
        confirmed_at = sub.get("confirmed_at", "")
        if not confirmed_at:
            continue

        try:
            conf_dt = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
            days_since = (now - conf_dt).days
        except Exception:
            continue

        # Only send to subscribers confirmed 1-6 days ago
        if days_since < 1 or days_since > 6:
            continue

        email = sub.get("email") or sub.get("sk", "").replace("SUB#", "")
        if not email or "@" not in email:
            continue

        try:
            subject, html = _build_onboarding_email(email)
            guarded_send_email(
                ses,
                dry_run,
                FromEmailAddress=SENDER,
                Destination={"ToAddresses": [email]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                    }
                },
            )

            if dry_run:
                # #2291: a dry run must leave no record claiming the real run
                # happened — an onboarding_sent marker with no mail behind it
                # would silently starve the subscriber of their bridge email.
                would_send_count += 1
                continue

            # Mark as sent
            table.update_item(
                Key={"pk": sub["pk"], "sk": sub["sk"]},
                UpdateExpression="SET onboarding_sent = :t, onboarding_sent_at = :now",
                ExpressionAttributeValues={
                    ":t": True,
                    ":now": now.isoformat(),
                },
            )
            sent_count += 1
            # PII discipline (#2369): never the full address in CloudWatch — truncate
            # per the sibling send-loop convention (email[:6]…).
            logger.info("Onboarding email sent (%s...)", email[:6])
        except Exception as e:
            logger.error("Failed to send onboarding to %s...: %s", email[:6], e)

    body = {"sent": sent_count, "checked": len(subscribers)}
    if dry_run:
        body["dry_run"] = True
        body["would_send"] = would_send_count
    return {"statusCode": 200, "body": json.dumps(body)}
