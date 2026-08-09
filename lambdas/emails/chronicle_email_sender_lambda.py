"""
Chronicle Email Sender Lambda — v1.0.0 (BS-03)
Delivers the weekly Chronicle installment to confirmed email subscribers.

Architecture decision (Board vote 4-0 — Marcus/Jin/Elena/Priya):
  Separate Lambda from wednesday-chronicle. Clean separation of concerns.
  Independent DLQ, independent retry, independent alarm.
  Viktor guard: no installment found this week → clean no-op, never fail.

Schedule: EventBridge cron(10 15 ? * WED *) — Wed 8:10 AM PT
  Chronicle fires at 8:00 AM, writes a DRAFT installment to DDB (needs approval).
  This Lambda fires at 8:10 AM, reads the latest PUBLISHED installment (within
  the last 7 days), sends to subscribers. On an approval Wednesday the draft is
  usually still unapproved at 8:10, so this trigger is really a catch-up guard
  for whatever installment hasn't been delivered yet — chronicle-approve's own
  post-publish invoke (chronicle_approve_lambda._invoke_email_sender) is the
  trigger that normally delivers a fresh installment. #2112: both triggers used
  to unconditionally send, causing a stale-then-fresh double-send on approval
  Wednesdays — closed via the delivered_at marker (see _get_this_weeks_installment
  / _mark_installment_delivered below); whichever trigger fires first delivers.

DynamoDB reads:
  SOURCE#chronicle    — latest PUBLISHED, not-yet-delivered installment (within last 7 days)
  SOURCE#subscribers  — all confirmed subscribers (status=confirmed)

DynamoDB writes:
  SOURCE#chronicle    — delivered_at / sent_to_count stamped on the installment
                        row after a successful send (#2112)

SES delivery:
  Personalized unsubscribe link per email (CAN-SPAM compliance)
  Rate: 1 email/sec (configurable via SEND_RATE_PER_SEC — SES sandbox limit)
  Alarm: chronicle-email-sender-errors (via SNS alerts)

v1.0.0 — 2026-03-17 (BS-03)
"""

import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
from experiment.phase_filter import with_phase_filter  # ADR-058: default-deny pilot data

try:
    from common.platform_logger import get_logger

    logger = get_logger("chronicle-email-sender")
except ImportError:
    logger = logging.getLogger("chronicle-email-sender")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")

# Rate limit: 1/sec for SES sandbox; increase after production access granted
SEND_RATE_PER_SEC = float(os.environ.get("SEND_RATE_PER_SEC", "1.0"))

SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"
CHRONICLE_PK = f"USER#{USER_ID}#SOURCE#chronicle"

S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────


from common.digest_utils import d2f as _d2f  # shared bundled helpers (#970)


def _fmt_week(week_num) -> str:
    """Render week_number without a trailing '.0'. DDB stores it as a Decimal;
    the shared d2f() round-trip (Decimal -> float) turns a whole number like 0 or
    12 into 0.0 / 12.0, which then prints raw in an f-string (#2112 — the first
    live send rendered "Week 0.0"). Falls back to str() for the "?" placeholder."""
    try:
        return str(int(week_num))
    except (TypeError, ValueError):
        return str(week_num)


def _get_this_weeks_installment() -> dict | None:
    """
    Get the most recent Chronicle installment published within the last 7 days.
    Viktor Sorokin guard: return None if nothing found — always a clean no-op.

    #2112: the Wednesday cron (10:15 UTC) and chronicle-approve's post-publish
    invoke both land on this same installment on an approval Wednesday — the cron
    fires first (drafts land 10 minutes earlier, before Matthew approves) and
    finds LAST week's published row, sends it stale, then approval sends the
    fresh one 10 minutes-to-hours later: two subscriber emails, one wrong. Rather
    than retire either trigger (cron is the fail-safe catch-up for an approval
    that lands hours/days later; the approve-invoke is the "send what was just
    approved" path — both are legitimate), the fix is per-installment delivery
    tracking: `delivered_at`/`sent_to_count` written by the handler after a
    successful send, checked here. Whichever trigger fires first delivers; the
    other one sees the marker and no-ops. The cron is thus demoted in practice to
    a catch-up guard for anything approve hasn't already sent — no code change to
    its schedule needed for that demotion to take effect.
    """
    today = datetime.now(timezone.utc).date()
    week_ago = (today - timedelta(days=7)).isoformat()
    today_str = today.isoformat()

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": CHRONICLE_PK,
                        ":s": f"DATE#{week_ago}",
                        ":e": f"DATE#{today_str}",
                    },
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
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
        # #2112: already delivered by the other trigger (cron or approve-invoke,
        # whichever fired first) — never re-send the same installment.
        if installment.get("delivered_at"):
            logger.info(
                "Most recent Chronicle installment (week %s) already delivered at %s — no-op",
                _fmt_week(installment.get("week_number", "?")),
                installment.get("delivered_at"),
            )
            return None
        return installment
    except Exception as exc:
        logger.error("Failed to query Chronicle DDB: %s", exc)
        return None


def _mark_installment_delivered(date_str: str, sent_count: int) -> None:
    """#2112: stamp the installment as delivered right after a successful send so
    the OTHER trigger (cron vs. approve-invoke) sees the marker and no-ops instead
    of re-sending. Conditional on delivered_at not already existing — defense in
    depth against a genuine concurrent double-invoke, though the two triggers in
    practice fire minutes-to-hours apart, never truly concurrently. Fail-soft: a
    failed marker write is logged, never raised — it must not fail an otherwise-
    successful send."""
    try:
        table.update_item(
            Key={"pk": CHRONICLE_PK, "sk": f"DATE#{date_str}"},
            UpdateExpression="SET delivered_at = :now, sent_to_count = :n",
            ConditionExpression="attribute_not_exists(delivered_at)",
            ExpressionAttributeValues={
                ":now": datetime.now(timezone.utc).isoformat(),
                ":n": Decimal(int(sent_count)),
            },
        )
        logger.info("DDB: installment %s marked delivered_at (sent_to_count=%d)", date_str, sent_count)
    except Exception as exc:
        # A ConditionalCheckFailedException here means the other trigger already
        # marked it delivered between our read and this write — harmless, we
        # already sent (or are about to), just log it.
        logger.warning("Failed to mark installment %s delivered (non-fatal): %s", date_str, exc)


def _record_email_send(sent_count: int) -> None:
    """#2254: write the email_log row the status page reads for "Wednesday chronicle".

    This is the ONLY place a real reader-facing chronicle delivery happens, so it is the
    only honest place to claim one. The generator (wednesday-chronicle) used to write
    this row on its PREVIEW route — where nothing was sent to a reader, only a draft
    stored and an approval email raised — so the status page reported a successful weekly
    send for weeks whose draft was still sitting unapproved. The generator now logs its
    preview to email_log#wednesday_chronicle_preview; this row means mail was delivered.

    Fail-soft: a failed status write must never fail an otherwise-successful send."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        table.put_item(
            Item={
                "pk": f"USER#{USER_ID}#SOURCE#email_log#wednesday_chronicle",
                "sk": f"DATE#{today}",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "sent_to_count": Decimal(int(sent_count)),
                "ttl": int(time.time()) + 86400 * 90,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("[status-tracking] Non-fatal write failure: %s", exc)


def _get_confirmed_subscribers() -> list[dict]:
    """
    Query subscribers partition for all confirmed records.
    Uses FilterExpression (not GSI) — acceptable at <10K subscriber volume.
    Add GSI on (status, sk) when sub count exceeds ~10K.
    """
    confirmed: list[dict[str, Any]] = []
    try:
        kwargs = {
            "KeyConditionExpression": "pk = :pk",
            "FilterExpression": "#s = :confirmed",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {
                ":pk": SUBSCRIBERS_PK,
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

# #2384: the byline map is DERIVED from the persona registry, never hand-typed.
# The previous literal map had forked three ways from the registry: a retired
# key rendered "Dr. Kai Nakamura" to subscribers, "vivek_murthy" rendered a
# phantom "Dr. Daniel Murthy", and "peter_attia" rendered the wrong live coach.
# Rule: a key earns a byline card only if its registry persona is on the cast
# the public site bills \u2014 operational coaches, the lead, and the narrator/meta
# show personas. A retired board twin staged by an old draft falls back to The
# Chair instead of resurrecting a name readers can't find on the team page.
_CHAIR_FALLBACK = {"name": "The Chair", "title": "Board Chair \u2014 Verdict & Priority", "color": "#6366f1", "emoji": "\U0001f3af"}


def _derive_board_members() -> dict:
    try:
        from coach import persona_registry

        live_names = {p.get("name") for p in persona_registry.operational_personas().values()}
        live_names.add((persona_registry.lead_persona() or {}).get("name"))
        members = {}
        for pid, persona in persona_registry.personas().items():
            name = persona.get("name")
            if not name or not (name in live_names or persona.get("type") in ("narrator", "meta")):
                continue
            key = persona.get("board_persona_key") or pid
            members[key] = {
                "name": name,
                "title": persona.get("board_role") or persona.get("title", ""),
                "color": persona.get("color", "#6366f1"),
                "emoji": persona.get("emoji", ""),
            }
        members.setdefault("the_chair", dict(_CHAIR_FALLBACK))
        return members
    except Exception as exc:  # registry unreadable \u2192 every byline degrades to The Chair
        logger.warning("persona registry unavailable, bylines degrade to The Chair: %s", exc)
        return {"the_chair": dict(_CHAIR_FALLBACK)}


BOARD_MEMBERS = _derive_board_members()


# ── #593: engraved coach portraits travel into the email ──────────────────────
# The signed portraits (config/portraits/*.json → scripts/render_portraits.py) are
# committed as ink-on-transparent PNGs under site/assets/portraits/ with a manifest.
# The "Board Speaks" byline shows the portrait when one exists for that coach, else
# falls back to the emoji glyph (also the <img alt>, so image-blocking clients still
# show the emoji). Fail-soft: any S3/parse error → emoji everywhere, exactly as before.
_PORTRAIT_MANIFEST = None  # None = not yet loaded; {} = loaded-but-empty (never retry-storm)


def _load_portrait_manifest() -> dict:
    """Load + index the portrait manifest from S3, once per warm container. Returns a
    dict {name_lower: persona_id}. Empty on any failure (fail-soft to emoji)."""
    global _PORTRAIT_MANIFEST
    if _PORTRAIT_MANIFEST is not None:
        return _PORTRAIT_MANIFEST
    index = {}
    try:
        body = _s3.get_object(Bucket=S3_BUCKET, Key="site/assets/portraits/manifest.json")["Body"].read()
        portraits = json.loads(body).get("portraits", {})
        for pid, rec in portraits.items():
            name = (rec.get("name") or "").strip().lower()
            if name:
                index[name] = pid
    except Exception as exc:
        logger.info("portrait manifest unavailable (emoji fallback): %s", exc)
    _PORTRAIT_MANIFEST = index
    return index


def _coach_portrait_img(member: dict, theme: str = "ondark", px: int = 30) -> str:
    """Return an <img> tag for the coach's engraved portrait, or "" if none exists.
    Matches by display name; alt text carries the emoji for image-blocked clients."""
    pid = _load_portrait_manifest().get((member.get("name") or "").strip().lower())
    if not pid:
        return ""
    emoji = member.get("emoji", "")
    url = f"{SITE_URL}/assets/portraits/{pid}-96-{theme}.png"
    return (
        f'<img src="{url}" width="{px}" height="{px}" alt="{emoji}" ' f'style="vertical-align:middle;border-radius:4px;margin-right:2px;">'
    )


def _extract_chronicle_preview(content_html: str, max_paragraphs: int = 3) -> str:
    """Extract first N paragraphs from Chronicle HTML for email preview."""
    import re

    paragraphs = re.findall(r"<p>(.*?)</p>", content_html, re.DOTALL)
    preview_paras = paragraphs[:max_paragraphs]
    return "\n".join(f"<p>{p}</p>" for p in preview_paras) if preview_paras else "<p>This week's chronicle is available on the site.</p>"


def _build_subscriber_email(installment: dict, subscriber: dict) -> tuple[str, str]:
    """Build the 5-section Weekly Signal email. Returns (subject, html)."""
    title = installment.get("title", "The Weekly Signal")
    week_num = _fmt_week(installment.get("week_number", "?"))
    date_str = installment.get("date", "")
    body_html = installment.get("content_html", "")

    subject = f'The Measured Life \u2014 Week {week_num}: "{title}"'

    sub_email = subscriber.get("email", "")
    unsub_url = f"{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(sub_email)}"

    try:
        display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        display_date = date_str

    # Parse weekly signal data
    signal_data: dict[str, Any] = {}
    try:
        raw = installment.get("weekly_signal_data", "{}")
        signal_data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        pass

    wins_losses: dict[str, Any] = {}
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
            items_html += f'<tr><td style="padding:6px 0;color:#22c55e;font-size:13px;vertical-align:top;width:20px;">\u2713</td><td style="padding:6px 0;font-size:13px;color:#c9d1d9;"><strong style="color:#E6EDF3;">{w.get("headline", "")}</strong><br><span style="color:#8b949e;font-size:12px;">{w.get("detail", "")}</span></td></tr>'
        for d in didnt[:3]:
            items_html += f'<tr><td style="padding:6px 0;color:#f87171;font-size:13px;vertical-align:top;width:20px;">\u2717</td><td style="padding:6px 0;font-size:13px;color:#c9d1d9;"><strong style="color:#E6EDF3;">{d.get("headline", "")}</strong><br><span style="color:#8b949e;font-size:12px;">{d.get("detail", "")}</span></td></tr>'
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
        {_coach_portrait_img(member) or member['emoji']} {member['name']} \u2014 {member['title']}
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
      &nbsp;\u00b7&nbsp;
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
    event = event or {}
    # #2111: {"dry_run": true} runs the full pipeline (installment lookup, subscriber
    # load, render) and returns a preview — but sends nothing and skips the kill-switch
    # gate below, so a diagnostic invoke is safe to run regardless of switch state.
    dry_run = bool(event.get("dry_run"))
    try:
        if not dry_run and os.environ.get("EXTERNAL_EMAILS_ENABLED", "true").lower() != "true":
            logger.info("[kill-switch] EXTERNAL_EMAILS_ENABLED=false — skipping Chronicle subscriber send")
            return {"statusCode": 200, "body": "skipped: external emails disabled", "sent": 0, "skipped": True}

        logger.info("Chronicle Email Sender v1.0.0 — BS-03 — starting")

        # Viktor guard: is there an installment from this week?
        installment = _get_this_weeks_installment()
        if not installment:
            logger.info("No installment found this week — clean no-op")
            return {
                "statusCode": 200,
                "body": "No Chronicle installment found this week — no-op",
                "sent": 0,
                "skipped": True,
            }

        title = installment.get("title", "")
        week_num = _fmt_week(installment.get("week_number", "?"))
        date_str = installment.get("date", "")
        logger.info('Installment found — Week %s: "%s"', week_num, title)

        # Load confirmed subscribers
        subscribers = _get_confirmed_subscribers()

        if dry_run:
            preview_sub = subscribers[0] if subscribers else {"email": "preview@example.com"}
            subject, html = _build_subscriber_email(installment, preview_sub)
            logger.info(
                "[DRY_RUN] Week %s would send to %d subscriber(s) — sending nothing",
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
                "title": title,
            }

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
                    Content={
                        "Simple": {
                            "Subject": {"Data": subject, "Charset": "UTF-8"},
                            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                        }
                    },
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

        # #2112: mark delivered on ANY successful send so the other trigger
        # (cron vs. approve-invoke, whichever fires second) no-ops instead of
        # re-sending. Left unmarked on a total failure (sent == 0) so a future
        # trigger gets a genuine retry rather than a permanently-stuck installment.
        if sent > 0 and date_str:
            _mark_installment_delivered(date_str, sent)
        # #2254: the status-page send record belongs to the delivery, not to the
        # generator's preview. Written on any successful send (dry-run returns earlier).
        if sent > 0:
            _record_email_send(sent)

        return {
            "statusCode": 200,
            "body": f"Chronicle Week {week_num} sent to {sent}/{len(subscribers)} subscribers",
            "sent": sent,
            "failed": failed,
            "total": len(subscribers),
            "week_num": week_num,
            "title": title,
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
