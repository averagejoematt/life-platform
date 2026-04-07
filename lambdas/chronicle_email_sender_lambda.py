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
USER_ID    = os.environ.get("USER_ID", "matthew")
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
        installment = _d2f(items[0])
        # FEAT-12: Skip drafts — only send published installments to subscribers.
        if installment.get("status") == "draft":
            logger.info("Most recent Chronicle installment is still a draft — no-op (awaiting approval)")
            return None
        return installment
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

BOARD_MEMBERS = {
    "sarah_chen":       {"name": "Dr. Sarah Chen",       "title": "Sports Scientist",                 "color": "#0ea5e9", "emoji": "\U0001F3CB\uFE0F"},
    "marcus_webb":      {"name": "Dr. Marcus Webb",      "title": "Nutritionist",                     "color": "#22c55e", "emoji": "\U0001F957"},
    "lisa_park":        {"name": "Dr. Lisa Park",        "title": "Sleep & Circadian Specialist",      "color": "#8b5cf6", "emoji": "\U0001F634"},
    "james_okafor":     {"name": "Dr. James Okafor",     "title": "Longevity & Preventive Medicine",   "color": "#f59e0b", "emoji": "\U0001FA7A"},
    "maya_rodriguez":   {"name": "Coach Maya Rodriguez",  "title": "Behavioural Performance Coach",    "color": "#ec4899", "emoji": "\U0001F9E0"},
    "the_chair":        {"name": "The Chair",             "title": "Board Chair \u2014 Verdict & Priority", "color": "#6366f1", "emoji": "\U0001F3AF"},
    "layne_norton":     {"name": "Dr. Marcus Webb",       "title": "Macros, Protein & Adherence",      "color": "#10b981", "emoji": "\U0001F4AA"},
    "rhonda_patrick":   {"name": "Dr. Amara Patel",      "title": "Micronutrients & Longevity",       "color": "#8b5cf6", "emoji": "\U0001F9EC"},
    "peter_attia":      {"name": "Dr. James Okafor",     "title": "Metabolic Health & Longevity",     "color": "#f59e0b", "emoji": "\U0001F4CA"},
    "andrew_huberman":  {"name": "Dr. Kai Nakamura",     "title": "Neuroscience & Protocols",         "color": "#06b6d4", "emoji": "\U0001F52C"},
    "elena_voss":       {"name": "Elena Voss",            "title": "Embedded Journalist",              "color": "#94a3b8", "emoji": "\u270D\uFE0F"},
    "paul_conti":       {"name": "Dr. Nathan Reeves",     "title": "Psychiatrist \u2014 Self-Structure",    "color": "#7c3aed", "emoji": "\U0001F9E0"},
    "margaret_calloway":{"name": "Margaret Calloway",     "title": "Senior Editor \u2014 Longform",         "color": "#b45309", "emoji": "\u270F\uFE0F"},
    "vivek_murthy":     {"name": "Dr. Daniel Murthy",     "title": "Social Connection & Loneliness",   "color": "#0891b2", "emoji": "\U0001F91D"},
}


def _extract_chronicle_preview(content_html: str, max_paragraphs: int = 3) -> str:
    """Extract first N paragraphs from Chronicle HTML for email preview."""
    import re
    paragraphs = re.findall(r'<p>(.*?)</p>', content_html, re.DOTALL)
    preview_paras = paragraphs[:max_paragraphs]
    return "\n".join(f"<p>{p}</p>" for p in preview_paras) if preview_paras else "<p>This week's chronicle is available on the site.</p>"


def _build_subscriber_email(installment: dict, subscriber: dict) -> tuple[str, str]:
    """Build the 5-section Weekly Signal email. Returns (subject, html)."""
    title      = installment.get("title", "The Weekly Signal")
    week_num   = installment.get("week_number", "?")
    date_str   = installment.get("date", "")
    body_html  = installment.get("content_html", "")

    subject = f'The Measured Life \u2014 Week {week_num}: "{title}"'

    sub_email = subscriber.get("email", "")
    unsub_url = f"{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(sub_email)}"

    try:
        display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        display_date = date_str

    # Parse weekly signal data
    signal_data = {}
    try:
        raw = installment.get("weekly_signal_data", "{}")
        signal_data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        pass

    wins_losses = {}
    try:
        raw = installment.get("weekly_signal_wins_losses", "{}")
        wins_losses = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        pass

    board_quote = installment.get("weekly_signal_board_quote", "")
    featured_member_id = signal_data.get("featured_member_id", "the_chair")
    featured_obs = signal_data.get("featured_observatory", {})
    member = BOARD_MEMBERS.get(featured_member_id, BOARD_MEMBERS["the_chair"])

    # Chronicle preview
    preview_html = _extract_chronicle_preview(body_html)
    chronicle_url = f"{SITE_URL}/chronicle/"

    # ── Section 1: Week in Numbers ──
    def _num(val, suffix=""):
        return f"{val}{suffix}" if val else "\u2014"

    s1 = ""
    if signal_data:
        s1 = f"""
  <div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);padding:24px 28px;margin-bottom:16px;">
    <p style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#F0B429;margin:0 0 16px;">The Week in Numbers</p>
    <table style="width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:13px;color:#c9d1d9;">
      <tr>
        <td style="padding:6px 0;color:#8b949e;">Weight</td>
        <td style="padding:6px 0;text-align:right;"><a href="{SITE_URL}/live/" style="color:#E6EDF3;text-decoration:none;">{_num(signal_data.get('weight_lbs'), ' lbs')}</a></td>
      </tr>
      <tr>
        <td style="padding:6px 0;color:#8b949e;">Sleep avg</td>
        <td style="padding:6px 0;text-align:right;"><a href="{SITE_URL}/sleep/" style="color:#E6EDF3;text-decoration:none;">{_num(signal_data.get('avg_sleep_hours'), 'h')}</a></td>
      </tr>
      <tr>
        <td style="padding:6px 0;color:#8b949e;">Recovery</td>
        <td style="padding:6px 0;text-align:right;"><a href="{SITE_URL}/training/" style="color:#E6EDF3;text-decoration:none;">{_num(signal_data.get('avg_recovery_pct'), '%')}</a></td>
      </tr>
      <tr>
        <td style="padding:6px 0;color:#8b949e;">HRV</td>
        <td style="padding:6px 0;text-align:right;">{_num(signal_data.get('avg_hrv_ms'), ' ms')}</td>
      </tr>
      <tr>
        <td style="padding:6px 0;color:#8b949e;">Training</td>
        <td style="padding:6px 0;text-align:right;"><a href="{SITE_URL}/training/" style="color:#E6EDF3;text-decoration:none;">{_num(signal_data.get('training_sessions'))} sessions</a></td>
      </tr>
      <tr>
        <td style="padding:6px 0;color:#8b949e;">Habits</td>
        <td style="padding:6px 0;text-align:right;"><a href="{SITE_URL}/habits/" style="color:#E6EDF3;text-decoration:none;">{_num(signal_data.get('habit_pct'), '%')}</a></td>
      </tr>
      <tr style="border-top:1px solid rgba(230,237,243,0.08);">
        <td style="padding:8px 0 0;color:#F0B429;font-size:11px;">Day {signal_data.get('journey_days', '?')}</td>
        <td style="padding:8px 0 0;text-align:right;color:#F0B429;font-size:11px;">{_num(signal_data.get('weight_delta_journey_lbs'), ' lbs lost')}</td>
      </tr>
    </table>
  </div>"""

    # ── Section 2: Chronicle Preview ──
    s2 = f"""
  <div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);padding:28px;margin-bottom:16px;">
    <h2 style="font-size:20px;font-weight:700;color:#E6EDF3;line-height:1.3;margin:0 0 16px;">{title}</h2>
    <div style="font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#c9d1d9;line-height:1.8;">
      {preview_html}
    </div>
    <p style="margin:20px 0 0;">
      <a href="{chronicle_url}" style="color:#F0B429;font-size:14px;font-weight:600;text-decoration:none;">Continue reading \u2192</a>
    </p>
  </div>"""

    # ── Section 3: What Worked / What Didn't ──
    s3 = ""
    worked = wins_losses.get("worked", [])
    didnt = wins_losses.get("didnt_work", [])
    if worked or didnt:
        items_html = ""
        for w in worked[:3]:
            items_html += f'<tr><td style="padding:6px 0;color:#22c55e;font-size:13px;vertical-align:top;width:20px;">\u2713</td><td style="padding:6px 0;font-size:13px;color:#c9d1d9;"><strong style="color:#E6EDF3;">{w.get("headline","")}</strong><br><span style="color:#8b949e;font-size:12px;">{w.get("detail","")}</span></td></tr>'
        for d in didnt[:3]:
            items_html += f'<tr><td style="padding:6px 0;color:#f87171;font-size:13px;vertical-align:top;width:20px;">\u2717</td><td style="padding:6px 0;font-size:13px;color:#c9d1d9;"><strong style="color:#E6EDF3;">{d.get("headline","")}</strong><br><span style="color:#8b949e;font-size:12px;">{d.get("detail","")}</span></td></tr>'
        s3 = f"""
  <div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);padding:24px 28px;margin-bottom:16px;">
    <p style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#F0B429;margin:0 0 16px;">What Worked / What Didn't</p>
    <table style="width:100%;border-collapse:collapse;">{items_html}</table>
  </div>"""

    # ── Section 4: The Board Speaks ──
    s4 = ""
    if board_quote:
        s4 = f"""
  <div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);padding:24px 28px;margin-bottom:16px;">
    <p style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#F0B429;margin:0 0 16px;">The Board Speaks</p>
    <div style="border-left:3px solid {member['color']};padding-left:16px;">
      <p style="font-family:Georgia,'Times New Roman',serif;font-size:14px;font-style:italic;color:#c9d1d9;line-height:1.7;margin:0 0 12px;">
        "{board_quote}"
      </p>
      <p style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#8b949e;margin:0;">
        {member['emoji']} {member['name']} \u2014 {member['title']}
      </p>
    </div>
  </div>"""

    # ── Section 5: Explore the Observatory ──
    s5 = ""
    if featured_obs:
        obs_slug = featured_obs.get("slug", "sleep")
        obs_url = f"{SITE_URL}/{obs_slug}/"
        s5 = f"""
  <div style="background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);padding:24px 28px;margin-bottom:16px;">
    <p style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#F0B429;margin:0 0 12px;">Explore the Observatory</p>
    <p style="font-size:15px;color:#E6EDF3;font-weight:600;margin:0 0 8px;">{featured_obs.get('name', '')}</p>
    <p style="font-size:13px;color:#8b949e;line-height:1.6;margin:0 0 16px;">{featured_obs.get('hook', '')}</p>
    <a href="{obs_url}" style="color:#F0B429;font-size:13px;font-weight:600;text-decoration:none;">Explore the data \u2192</a>
  </div>"""

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
    <p style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#F0B429;margin:0 0 8px;">The Weekly Signal</p>
    <p style="font-size:12px;color:#484f58;margin:0;">Week {week_num} \u2014 {display_date}</p>
  </div>

  {s1}
  {s2}
  {s3}
  {s4}
  {s5}

  <!-- Footer (CAN-SPAM) -->
  <div style="border-top:1px solid rgba(230,237,243,0.06);padding:20px 0 40px;">
    <p style="font-size:11px;color:#30363d;margin:0 0 8px;line-height:1.6;text-align:center;">
      You subscribed to The Weekly Signal at averagejoematt.com.<br>
      This is a real person's real data, published every Wednesday.
    </p>
    <p style="font-size:11px;text-align:center;margin:0;">
      <a href="{unsub_url}" style="color:#484f58;text-decoration:underline;">Unsubscribe</a>
      &nbsp;\u00B7&nbsp;
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
    try:
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
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
