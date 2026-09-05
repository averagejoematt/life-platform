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
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from common import send_ledger  # #3113 / DIL-025: the durable replay guard
from experiment.phase_filter import with_phase_filter  # ADR-058: default-deny pilot data

try:
    from common.platform_logger import get_logger

    logger = get_logger("weekly-signal")
except ImportError:
    logger = logging.getLogger("weekly-signal")
    logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")
SEND_RATE = float(os.environ.get("SEND_RATE_PER_SEC", "1.0"))

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)
cw = boto3.client("cloudwatch", region_name=REGION)

# ── #2820: the delivery dead-man's datapoint (same one-metric pattern as the
# chronicle sender — see chronicle_email_sender_lambda.py for the full note).
# The Sunday Weekly Signal is the other subscriber promise with no delivery
# signal: every non-dry-run invocation emits ONE datapoint here (value = actual
# SES sends; 0 on kill-switch / zero-subscriber / total-failure runs), and
# `weekly-signal-delivery-heartbeat` (email_stack.py) pages when the trailing 7
# daily Sums are all < 1. No sanctioned-pause branch: this sender makes no AI
# calls and degrades sections instead of skipping, so it has no budget-paused
# no-op state — a quiet week is never sanctioned, only delivered or missed.
METRIC_NAMESPACE = "LifePlatform/Email"
SENT_METRIC_NAME = "WeeklySignalSent"


def _emit_sent_metric(value: float, reason: str) -> None:
    """Emit the delivery-heartbeat datapoint. Fail-soft — a metrics outage must
    never fail a send; a persistently failed emit IS a missing datapoint, so the
    dead-man still pages (#2820)."""
    try:
        cw.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{"MetricName": SENT_METRIC_NAME, "Value": float(value), "Unit": "Count"}],
        )
        logger.info("[dead-man] %s=%s (%s)", SENT_METRIC_NAME, value, reason)
    except Exception as exc:
        logger.warning("[dead-man] %s emit failed (non-fatal): %s", SENT_METRIC_NAME, exc)


USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

OBSERVATORY_ROTATION = [
    {"name": "Sleep", "path": "/sleep/", "hook": "How your sleep patterns shape recovery and readiness."},
    {"name": "Glucose", "path": "/glucose/", "hook": "CGM data revealing how food choices affect energy and metabolic health."},
    {"name": "Nutrition", "path": "/nutrition/", "hook": "Macro targets, meal timing, and what the data says about fueling."},
    {"name": "Training", "path": "/training/", "hook": "Strain, recovery balance, and how training load connects to progress."},
    {"name": "Inner Life", "path": "/mind/", "hook": "Journaling, habits, and the behavioral data behind consistency."},
]

BOARD_ROTATION = [
    {"name": "The Chair", "title": "Board Chair"},
    {"name": "Dr. Chen", "title": "Behavioral Science"},
    {"name": "Dr. Okafor", "title": "Longevity Medicine"},
    {"name": "Dr. Park", "title": "Sleep & Circadian"},
    {"name": "Dr. Patrick", "title": "Metabolic Health"},
]


from common.digest_utils import d2f as _d2f  # shared bundled helpers (#970)
from common.pacific_time import pacific_now  # #2811: THE Pacific day helper — DATE# keys are Pacific days, pacific_today
from common.subscriber_cadence import genesis_week_label, genesis_week_number  # #3564 — ONE week numbering
from common.unsubscribe_token import unsub_url_or_fallback  # #3044 — signed unsub link, never plaintext email


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
            ":pk": f"{USER_PREFIX}subscribers",
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
    today = pacific_now().date()
    week_ago = (today - timedelta(days=7)).isoformat()
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": f"{USER_PREFIX}computed_insights",
                        ":s": f"DATE#{week_ago}",
                        ":e": f"DATE#{today.isoformat()}",
                    },
                    "ScanIndexForward": False,
                    "Limit": 5,
                }
            )
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
    return f"""<div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);padding:24px 28px;margin-bottom:16px;">
  <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#3db88a;margin:0 0 16px;">{title}</p>
  {content}
</div>"""


def _build_numbers(stats):
    vitals = stats.get("vitals", {})
    char = stats.get("character", {})
    weight = vitals.get("weight_lbs")
    # #1917: this was reading `weight_delta_30d` and rendering it as "30d" — but the
    # writer (daily_brief write_public_stats) computes it from week_ago_weight, so the
    # email claimed a 30-day window over a 7-day number. Read the honestly-named field
    # and label it from the window the writer declares, never a hardcoded span.
    delta = vitals.get("weight_delta_7d")
    delta_window = vitals.get("weight_delta_window_days")
    sleep = vitals.get("sleep_hours_30d_avg")
    # #3451: the writer computes this over whatever the last 30 calendar days
    # actually held (never genesis-clamped — window_registry.py's EXEMPT ruling)
    # and now ships n beside it. Rendered the same way the #1917 weight row
    # above states its real window, instead of a bare "30d" that could be
    # covering a Whoop outage's handful of nights.
    sleep_n = vitals.get("sleep_hours_30d_n")
    recovery = vitals.get("recovery_pct")
    level = char.get("level", "?")
    tier = char.get("tier", "")

    rows = []
    if weight is not None:
        arrow = "↓" if delta and delta < 0 else "↑" if delta and delta > 0 else ""
        delta_str = f" ({arrow}{abs(delta):.1f} lbs {delta_window}d)" if delta and delta_window else ""
        rows.append(
            f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Weight</td><td style="color:#c9d1d9;font-weight:600;">{weight} lbs{delta_str}</td></tr>'
        )
    if sleep:
        window_str = f" ({sleep_n}n · 30d)" if sleep_n else ""
        rows.append(
            f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Avg Sleep</td><td style="color:#c9d1d9;font-weight:600;">{sleep:.1f} hrs{window_str}</td></tr>'
        )
    if recovery:
        rows.append(
            f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Recovery</td><td style="color:#c9d1d9;font-weight:600;">{recovery:.0f}%</td></tr>'
        )
    rows.append(
        f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Character</td><td style="color:#c9d1d9;font-weight:600;">Level {level} · {tier}</td></tr>'
    )

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
    return _sec(
        "Chronicle Preview",
        f"""<p style="font-size:16px;color:#c9d1d9;font-weight:600;margin:0 0 8px;">{title}</p>
  <p style="font-size:13px;color:#8b949e;line-height:1.6;margin:0 0 12px;">{preview}</p>
  <a href="{SITE_URL}{url}" style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:1px;color:#3db88a;text-decoration:none;">Read more →</a>""",
    )


def _build_worked(insight_text):
    if not insight_text:
        return ""
    return _sec("What Worked This Week", f'<p style="font-size:13px;color:#c9d1d9;line-height:1.7;margin:0;">{insight_text}</p>')


def _build_board_quote(week_num):
    member = BOARD_ROTATION[week_num % len(BOARD_ROTATION)]
    return _sec(
        "The Board Says",
        f'<p style="font-size:13px;color:#c9d1d9;line-height:1.7;margin:0 0 8px;font-style:italic;">"Check the data, not the mirror. Progress at this stage is measured in trends, not snapshots."</p>'
        f'<p style="font-family:\'Courier New\',monospace;font-size:10px;color:#8b949e;margin:0;">— {member["name"]}, {member["title"]}</p>',
    )


def _build_spotlight(week_num):
    obs = OBSERVATORY_ROTATION[week_num % len(OBSERVATORY_ROTATION)]
    return _sec(
        "Observatory Spotlight",
        f'<p style="font-size:14px;color:#c9d1d9;font-weight:600;margin:0 0 8px;">{obs["name"]}</p>'
        f'<p style="font-size:13px;color:#8b949e;line-height:1.6;margin:0 0 12px;">{obs["hook"]}</p>'
        f'<a href="{SITE_URL}{obs["path"]}" style="font-family:\'Courier New\',monospace;font-size:11px;letter-spacing:1px;color:#3db88a;text-decoration:none;">Explore {obs["name"]} →</a>',
    )


def _build_email(stats, posts_data, insight_text, week_num, unsub_url, week_label):
    now = datetime.now(timezone.utc)
    display_date = now.strftime("%B %d, %Y")

    s1 = _build_numbers(stats) if stats else ""
    s2 = _build_chronicle(posts_data) if posts_data else ""
    s3 = _build_worked(insight_text)
    s4 = _build_board_quote(week_num)
    s5 = _build_spotlight(week_num)

    subject = f"{week_label} — The Measured Life"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{week_label} — The Weekly Signal</title></head>
<body style="margin:0;padding:0;background:#0D1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:0 16px;">
  <div style="padding:32px 0 24px;">
    <p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#3db88a;margin:0 0 8px;">The Weekly Signal</p>
    <p style="font-size:12px;color:#484f58;margin:0;">{week_label} — {display_date}</p>
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


#: The `email_log#` partition this sender's completion rows live in (#3113).
#: This sender had no completion row of any kind — only the #2820 CloudWatch
#: delivery datapoint, which is a metric, not a durable per-letter record.
LEDGER_NAME = "weekly_signal"


def lambda_handler(event, context):
    event = event or {}
    # #2111: {"dry_run": true} runs the full pipeline (data load, subscriber load,
    # render) and returns a preview — but sends nothing and skips the kill-switch
    # gate below, so a diagnostic invoke is safe to run regardless of switch state.
    dry_run = bool(event.get("dry_run"))
    try:
        # DIL-025 / #3113 replay guard, ahead of every S3 read and the whole
        # fan-out. Keyed on the ISO week the letter IS — deliberately NOT `week_num`
        # below, which is the genesis-anchored EXPERIMENT week (#3564) and is not a
        # calendar fact at all: it repeats across cycles after a restart, so reusing it
        # as a replay key would make cycle 17 week 3 collide with cycle 16 week 3.
        # #2811: the letter's week is a PACIFIC calendar fact (a Sunday-evening PT send
        # must not key next week's ISO week just because UTC rolled) — pacific_today().
        period_key = f"week:{send_ledger.iso_week_key(pacific_now().date())}"
        if send_ledger.should_skip_replay(table, LEDGER_NAME, period_key, dry_run=dry_run, event=event, user_id=USER_ID, logger=logger):
            logger.warning("[DIL-025] Weekly Signal for %s already sent — refusing to mail the list twice", period_key)
            return {"statusCode": 200, "body": f"Weekly Signal for {period_key} already sent — skipped (replay guard)", "sent": 0}

        if not dry_run and os.environ.get("EXTERNAL_EMAILS_ENABLED", "true").lower() != "true":
            logger.info("[kill-switch] EXTERNAL_EMAILS_ENABLED=false — skipping Weekly Signal subscriber send")
            # #2820: an unfulfilled promise emits 0 — the #1951 kill-switch alarm
            # names the cause, this dead-man tracks the outcome.
            _emit_sent_metric(0, "kill-switch skip")
            return {"statusCode": 200, "body": "skipped: external emails disabled", "sent": 0, "skipped": True}

        logger.info("Weekly Signal v1.0.0 — PB-06 — starting")

        # Load data (graceful degradation: missing data = skip section, not crash)
        stats = _s3_json("generated/public_stats.json")
        posts_data = _s3_json("generated/journal/posts.json")
        insight_text = _get_weekly_insight()

        # #3564: ONE week numbering across the subscriber-facing senders. `%W` is the
        # Gregorian CALENDAR week — a subscriber received "Week 34" from this letter and
        # "Week 2" from the chronicle about the same seven days. Both now read the
        # genesis-anchored number, and a pre-genesis send says "Prologue" rather than
        # inventing a week that has not started. The int stays the rotation index.
        _week_day = pacific_now().date()
        week_num = genesis_week_number(_week_day)
        week_label = genesis_week_label(_week_day)

        # Load subscribers
        subscribers = _get_confirmed_subscribers()

        if dry_run:
            preview_email = (subscribers[0].get("email") if subscribers else "") or "preview@example.com"
            unsub_url = unsub_url_or_fallback(preview_email, SITE_URL)  # #3044
            subject, html = _build_email(stats, posts_data, insight_text, week_num, unsub_url, week_label)
            logger.info(
                "[DRY_RUN] Weekly Signal week %d would send to %d subscriber(s) — sending nothing",
                week_num,
                len(subscribers),
            )
            return {
                "statusCode": 200,
                "dry_run": True,
                "subject": subject,
                "recipient_count": len(subscribers),
                "html_bytes": len(html),
                "week_num": week_num,
            }

        if not subscribers:
            logger.info("No confirmed subscribers — no-op")
            # #2820: deliberately 0, never sanctioned — the subscriber query
            # fail-softs to [] on a DDB error, and a sanctioned datapoint there
            # would let a broken read mask a missed delivery.
            _emit_sent_metric(0, "no confirmed subscribers")
            return {"statusCode": 200, "body": "No confirmed subscribers", "sent": 0}

        logger.info("Sending Weekly Signal (week %d) to %d subscribers", week_num, len(subscribers))

        sent = failed = 0
        rate_delay = 1.0 / max(SEND_RATE, 0.1)

        for i, sub in enumerate(subscribers):
            email = sub.get("email", "").strip()
            if not email:
                continue

            unsub_url = unsub_url_or_fallback(email, SITE_URL)  # #3044
            subject, html = _build_email(stats, posts_data, insight_text, week_num, unsub_url, week_label)

            try:
                ses.send_email(
                    FromEmailAddress=SENDER,
                    Destination={"ToAddresses": [email]},
                    Content={
                        "Simple": {
                            "Subject": {"Data": subject, "Charset": "UTF-8"},
                            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                        }
                    },
                )
                sent += 1
                if sent == 1:
                    # DIL-025: mail is on the wire NOW — record before the rest
                    # of the fan-out, not after it.
                    send_ledger.record_sent(table, LEDGER_NAME, period_key, user_id=USER_ID, logger=logger)
                logger.info("Sent %d/%d (%s...)", i + 1, len(subscribers), email[:6])
            except Exception as exc:
                failed += 1
                logger.error("Failed send to %s...: %s", email[:6], exc)

            if i < len(subscribers) - 1:
                time.sleep(rate_delay)

        logger.info("Weekly Signal complete: sent=%d, failed=%d, total=%d", sent, failed, len(subscribers))

        # #2820: the delivery datapoint — actual send count, honestly 0 on a
        # total failure so the dead-man can page within the week.
        _emit_sent_metric(sent, f"SES sends completed ({sent}/{len(subscribers)})")

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
