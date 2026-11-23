"""
weekly_signal_lambda.py — PB-06: "The Weekly Signal" subscriber email.

Curated summary sent to subscribers every Sunday at 9:30 AM PT.
Reads pre-computed data from S3 + DynamoDB — no AI calls.

Schedule: cron(30 16 ? * SUN *)  (9:30 AM PT = 16:30 UTC)
Model: chronicle_email_sender_lambda.py (same subscriber query, SES pattern, rate limiting)

Sections:
  1. The Numbers — weight, sleep, recovery, character
  2. The Latest Chapter — the newest PUBLISHED chapter, dated, in its served summary (#6244)
  3. What Worked This Week — the newest computed insight, ONLY when the public narrative gate
     (web.narrative_publication, the Site API's own chokepoint) passes its row; omitted otherwise
  4. Observatory Spotlight — rotating page highlight

#6151: "The Board Says" is gone. It printed one fixed sentence and attributed it to a different
board member each week — words nobody on the board said (ADR-104). Nothing replaces it.
Every send carries a text part, a preheader and List-Unsubscribe (common.reader_email).

#6244 (owner ruling 2026-11-23). Two display defects:
  * "Level 22.0 · None" — the character level is shown as a whole number and the tier only when it is a real word;
    a level that is not a number drops the row.
  * The chapter section ("Chronicle Preview") was undated and read the first post of ``generated/journal/posts.json``,
    re-joining its excerpt at ". " and appending a period (a summary that already ended in one read "flag.."). Two
    weeks after the last chapter it still looked like this week's preview. It now reads ``/api/chapters`` — the route
    that knows a published week from a held, retired or skipped one (those serve ``url: null`` and are never
    shown) — takes the newest PUBLISHED week, dates it ("Week 10 · published November 14, 2026") and shows its
    summary by the site's one-summary rule (www/src/lib/chapter_truth.js): the served later edition's own summary
    (the ``editions`` list, already through every publication gate at serve time), whole. With no served edition
    there is no summary line (the owner-approved header revisions live only in the site build, so the manifest
    excerpt could be the very words a revision replaced) — the title, the date and the link stand alone. A failed
    read omits the section; nothing stale is shown in its place.
"""

import html as _html
import json
import logging
import math
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from common import send_ledger  # #3113 / DIL-025: the durable replay guard
from common.email_identity import SIGNAL_SENDER  # #3568 — ONE sending vocabulary, gated against the SES-verified set
from common.journal_silence import reader_mail  # #5131: the one public-surface guard
from common.reader_email import FOOTER_TEXT, head_meta, preheader_html, simple_content  # #6151 — the ONE reader envelope
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
SENDER = os.environ.get("EMAIL_SENDER", SIGNAL_SENDER)
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")
SEND_RATE = float(os.environ.get("SEND_RATE_PER_SEC", "1.0"))
#: #6244: the public chapters route — the one reader of which weeks are published. "off" skips the read (the unit
#: suite sets it, tests/conftest.py; the section is then omitted, exactly as on a failed read).
CHAPTERS_FETCH = os.environ.get("WEEKLY_SIGNAL_CHAPTERS_FETCH", "on")
CHAPTERS_TIMEOUT_S = 10

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

from common.digest_utils import d2f as _d2f  # shared bundled helpers (#970)
from common.pacific_time import pacific_now  # #2811: THE Pacific day helper — DATE# keys are Pacific days, pacific_today
from common.subscriber_cadence import genesis_week_label, genesis_week_number  # #3564 — ONE week numbering
from common.unsubscribe_token import unsub_url_or_fallback  # #3044 — signed unsub link, never plaintext email
from web import narrative_publication  # #6151: the Site API's public narrative gate — imported, never re-implemented


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


#: The insight fields read, in order. `guidance_given` is stored as a JSON-encoded list (the daily brief's write).
INSIGHT_FIELDS = ("guidance_given", "top_insight", "summary")


def _insight_text(value):
    """One reader sentence from a stored insight field: a string, or the first string of a list (or of a
    JSON-encoded list — `guidance_given` is written as `json.dumps([...])`). Anything else is None."""
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v.strip()), None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _public_insight(item):
    """The insight text of one `computed_insights` row IF the public narrative gate passes the row, else None.

    #6151: this read went straight into reader mail, owner-facing and unescaped. The row now passes the SAME
    decision the Site API applies to every narrative read (`web.narrative_publication.gate_item` — the row's
    provenance record decides, fail-closed; `strict=True` because a mail has no wire half). A withheld row
    comes back with every free-text field emptied, so it can never render."""
    gated = narrative_publication.gate_item(item, f"{USER_PREFIX}computed_insights", strict=True)
    if narrative_publication.is_withheld(gated):
        return None
    for field in INSIGHT_FIELDS:
        text = _insight_text(gated.get(field))
        if text:
            return text
    return None


def _get_weekly_insight():
    """The most recent PUBLISHABLE insight from the last 7 days (None when no row passes the public gate)."""
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
        for item in (_d2f(i) for i in resp.get("Items", [])):
            text = _public_insight(item)
            if text:
                return text
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
    character = character_words(char)
    rows = []
    if weight is not None:
        arrow = "↓" if delta and delta < 0 else "↑" if delta and delta > 0 else ""
        delta_str = f" ({arrow}{abs(delta):.1f} lbs {delta_window}d)" if delta and delta_window else ""
        weight_n = _finite(weight)
        if weight_n is not None:
            rows.append(
                f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Weight</td><td style="color:#c9d1d9;font-weight:600;">{weight_n:.1f} lbs{delta_str}</td></tr>'
            )
    if sleep:
        sleep_n_int = _finite(sleep_n)
        window_str = f" ({int(sleep_n_int)}n · 30d)" if sleep_n_int else ""
        rows.append(
            f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Avg Sleep</td><td style="color:#c9d1d9;font-weight:600;">{sleep:.1f} hrs{window_str}</td></tr>'
        )
    if recovery:
        rows.append(
            f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Recovery</td><td style="color:#c9d1d9;font-weight:600;">{recovery:.0f}%</td></tr>'
        )
    if character:
        rows.append(
            f'<tr><td style="color:#8b949e;padding:4px 12px 4px 0;">Character</td><td style="color:#c9d1d9;font-weight:600;">{_html.escape(character)}</td></tr>'
        )

    return _sec("The Numbers", f'<table style="font-size:14px;line-height:1.8;">{"".join(rows)}</table>')


def _finite(value):
    """A finite float from a wire value (Decimal, int, float, numeric string); None otherwise (bools included)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError, ArithmeticError):
        return None
    return f if math.isfinite(f) else None


#: Words that are not a tier name — a serialized null or an empty marker never reaches a reader.
_NOT_A_WORD = {"", "none", "null", "nan", "undefined", "?"}


def character_words(char):
    """#6244: "Level 26 · Momentum" — the level as a whole number, the tier only when it is a real word; None when the
    level is not a number (the row is then omitted, never "Level ?")."""
    if not isinstance(char, dict):
        return None
    level = _finite(char.get("level"))
    if level is None or level < 0:
        return None
    tier = str(char.get("tier") or "").strip()
    words = f"Level {int(round(level))}"
    return f"{words} · {tier}" if tier.lower() not in _NOT_A_WORD else words


_CHAPTER_ID_RE = re.compile(r"/week-(\d+)/?$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _chapter_id(url):
    """The chapter id of a journal permalink ("/journal/posts/week-12/" -> "week-12") — the derivation the snapshot
    producer uses (scripts/publish_snapshot_chapters.week_id); None when the url names no week page."""
    m = _CHAPTER_ID_RE.search(str(url or ""))
    return f"week-{int(m.group(1)):02d}" if m else None


def _day_words(day):
    try:
        d = datetime.strptime(str(day or "")[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def latest_published_chapter(doc):
    """#6244: the newest PUBLISHED chapter of an ``/api/chapters`` document, ready to render — pure.

    ``{"label", "title", "url", "published_on", "summary"}`` or None. Only a week served as ``published`` with a title
    and a url is a candidate: a held, retired, skipped or pending week (``url: null``) never is. ``summary`` follows the
    one-summary rule: the served edition's own summary for that chapter, else None — never a manifest excerpt."""
    if not isinstance(doc, dict):
        return None
    weeks = [
        w
        for w in (doc.get("weeks") or [])
        if isinstance(w, dict) and w.get("status") == "published" and w.get("url") and w.get("title") and isinstance(w.get("week"), int)
    ]
    if not weeks:
        return None
    w = max(weeks, key=lambda x: x["week"])
    cid = _chapter_id(w["url"])
    if cid is None:
        return None
    summary = None
    for e in doc.get("editions") or []:
        if isinstance(e, dict) and e.get("chapter_id") == cid and str(e.get("title") or "") == str(w["title"]):
            text = " ".join(str(e.get("summary") or "").split())
            summary = text or None
            break
    published = str(w.get("published_at") or "")[:10]
    on = _day_words(published) if _DAY_RE.match(published) else None
    return {
        "label": str(w.get("label") or f"Week {w['week']}"),
        "title": str(w["title"]),
        "url": f"/story/{cid}/",
        "published_on": on,
        "summary": summary,
    }


def _fetch_chapters():
    """GET {SITE_URL}/api/chapters (the public route; no AWS read). None when off, unreachable or not JSON."""
    if str(CHAPTERS_FETCH).strip().lower() != "on":
        return None
    try:
        req = urllib.request.Request(f"{SITE_URL}/api/chapters", headers={"User-Agent": "weekly-signal"})
        with urllib.request.urlopen(req, timeout=CHAPTERS_TIMEOUT_S) as resp:  # noqa: S310 — our own https site
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 — a failed read omits the section
        logger.warning("chapters read failed (%s) — the chapter section is omitted", type(e).__name__)
        return None


def _build_chronicle(chapter):
    """The latest published chapter (``latest_published_chapter``), dated; "" when there is none."""
    if not isinstance(chapter, dict) or not chapter.get("title") or not chapter.get("url"):
        return ""
    label = _html.escape(chapter.get("label") or "")
    dated = f" · published {_html.escape(chapter['published_on'])}" if chapter.get("published_on") else ""
    summary = (
        f'<p style="font-size:13px;color:#8b949e;line-height:1.6;margin:0 0 12px;">{_html.escape(chapter["summary"])}</p>'
        if chapter.get("summary")
        else ""
    )
    return _sec(
        "The Latest Chapter",
        f"""<p style="font-size:11px;color:#8b949e;margin:0 0 6px;">{label}{dated}</p>
  <p style="font-size:16px;color:#c9d1d9;font-weight:600;margin:0 0 8px;">{_html.escape(chapter["title"])}</p>
  {summary}<a href="{SITE_URL}{chapter["url"]}" style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:1px;color:#3db88a;text-decoration:none;">Read the chapter →</a>""",
    )


def _build_worked(insight_text):
    """Render the gated insight. Escaped: stored text is data, never markup (#6151)."""
    if not insight_text:
        return ""
    body = _html.escape(str(insight_text))
    return _sec("What Worked This Week", f'<p style="font-size:13px;color:#c9d1d9;line-height:1.7;margin:0;">{body}</p>')


def _build_spotlight(week_num):
    obs = OBSERVATORY_ROTATION[week_num % len(OBSERVATORY_ROTATION)]
    return _sec(
        "Observatory Spotlight",
        f'<p style="font-size:14px;color:#c9d1d9;font-weight:600;margin:0 0 8px;">{obs["name"]}</p>'
        f'<p style="font-size:13px;color:#8b949e;line-height:1.6;margin:0 0 12px;">{obs["hook"]}</p>'
        f'<a href="{SITE_URL}{obs["path"]}" style="font-family:\'Courier New\',monospace;font-size:11px;letter-spacing:1px;color:#3db88a;text-decoration:none;">Explore {obs["name"]} →</a>',
    )


def _build_email(stats, chapter, insight_text, week_num, unsub_url, week_label):
    now = datetime.now(timezone.utc)
    display_date = now.strftime("%B %d, %Y")

    s1 = _build_numbers(stats) if stats else ""
    s2 = _build_chronicle(chapter) if chapter else ""
    s3 = _build_worked(insight_text)
    s4 = _build_spotlight(week_num)

    subject = f"{week_label} — The Measured Life"
    preheader = preheader_html(f"{week_label}: the week's numbers, the latest chapter and one page to explore.")

    html = f"""<!DOCTYPE html>
<html><head>{head_meta()}
<title>{week_label} — The Weekly Signal</title></head>
<body style="margin:0;padding:0;background:#0D1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
{preheader}
<div style="max-width:600px;margin:0 auto;padding:0 16px;">
  <div style="padding:32px 0 24px;">
    <p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#3db88a;margin:0 0 8px;">The Weekly Signal</p>
    <p style="font-size:12px;color:#484f58;margin:0;">{week_label} — {display_date}</p>
  </div>
  {s1}{s2}{s3}{s4}
  <div style="border-top:1px solid rgba(230,237,243,0.06);padding:20px 0 40px;">
    <p style="font-size:11px;color:{FOOTER_TEXT};margin:0 0 8px;line-height:1.6;text-align:center;">
      You subscribed to The Weekly Signal at averagejoematt.com.<br>
      One person's real data, published without filters.
    </p>
    <p style="font-size:11px;text-align:center;margin:0;">
      <a href="{unsub_url}" style="color:{FOOTER_TEXT};text-decoration:underline;">Unsubscribe</a>
      &nbsp;&middot;&nbsp;
      <a href="{SITE_URL}" style="color:{FOOTER_TEXT};text-decoration:underline;">averagejoematt.com</a>
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
        chapter = latest_published_chapter(_fetch_chapters())  # #6244: the newest PUBLISHED week, never a held/retired one
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
            subject, html = _build_email(stats, chapter, insight_text, week_num, unsub_url, week_label)
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
            subject, html = _build_email(stats, chapter, insight_text, week_num, unsub_url, week_label)

            try:
                ses.send_email(
                    FromEmailAddress=SENDER,
                    Destination={"ToAddresses": [email]},
                    # #6151: text part derived from the scrubbed HTML + List-Unsubscribe headers
                    Content=simple_content(reader_mail(subject), html=reader_mail(html), unsub_url=unsub_url),
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
