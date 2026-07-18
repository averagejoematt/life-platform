"""
Evening Nudge Lambda — R54
Fires at 8 PM PT daily (03:00 UTC via EventBridge).
Checks which manual-input data sources are missing for today and sends
a short reminder email if any are incomplete.

Sources checked:
  - Supplements (has any batch been logged today?)
  - Journal (has morning or evening entry been created today?)
  - How We Feel / State of Mind (has a check-in arrived via webhook today?)
  - Evening ritual (#769, ADR-124): the C-floor two-scalar micro-ritual —
    connection today (0-4) and mood valence (0-4), delivered as one-tap links
    (see _build_ritual_section). Treated the same as the other three checks
    for whether the email sends at all, so the ritual survives a week where
    everything else is quiet — the whole point of the C floor (ADR-124).

Only sends email when at least one source is missing.
No email on days when all four are complete — don't nag unnecessarily.

v1.0.0 — 2026-03-15 (R54)
v1.1.0 — 2026-07-07 (#769): added the evening-ritual one-tap section.
"""

import logging
import os
from datetime import datetime

import boto3
from pacific_time import pacific_today
from ritual_link import sign_ritual_token
from source_registry import manual_capture_sources

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
RECIPIENT = os.environ["EMAIL_RECIPIENT"]
SENDER = os.environ["EMAIL_SENDER"]
USER_ID = os.environ.get("USER_ID", "matthew")
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")
RITUAL_TOKEN_SECRET_NAME = os.environ.get("RITUAL_TOKEN_SECRET_NAME", "life-platform/ritual-token-secret")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=_REGION)
secretsmanager = boto3.client("secretsmanager", region_name=_REGION)

_ritual_secret_cache: str | None = None

# 0-4 ordinal labels shown next to each tap button — the whole construct is
# "two scalars, no free text" (ADR-124), so the labels are display-only.
RITUAL_LABELS = {
    "connection": ["Not at all", "A little", "Some", "A lot", "Deeply"],
    "mood_valence": ["Rough", "Low", "Okay", "Good", "Great"],
    # #1405: one-tap evening intake count (4 = "4+"). This email is Matthew-private,
    # so the title names it plainly; everywhere else the metric stays oblique
    # (intake_count) and the count lands in the private_intake partition only.
    "intake_count": ["0", "1", "2", "3", "4+"],
}
RITUAL_METRIC_TITLES = {
    "connection": "Felt connected today?",
    "mood_valence": "Mood today?",
    "intake_count": "Drinks this evening?",
}


from digest_utils import d2f as _d2f  # shared bundled helpers (#970)


def _fetch_date(source: str, date_str: str) -> dict | None:
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        item = r.get("Item")
        return _d2f(item) if item else None
    except Exception as e:
        logger.warning(f"[nudge] fetch_date({source}, {date_str}) failed: {e}")
        return None


def _check_supplements(date_str: str) -> tuple[bool, str]:
    """Returns (complete, detail)."""
    item = _fetch_date("supplements", date_str)
    if not item:
        return False, "No supplements logged"
    batches = item.get("batches", [])
    total = item.get("total_supplements_logged", 0) or len(batches)
    if total > 0:
        return True, f"{int(total)} supplement(s) logged"
    return False, "No supplements logged"


def _check_journal(date_str: str) -> tuple[bool, str]:
    """Returns (complete, detail). Complete = at least one entry today."""
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX + "notion",
                ":prefix": f"DATE#{date_str}#journal#",
            },
            Limit=5,
        )
        items = r.get("Items", [])
        if not items:
            return False, "No journal entries"
        templates = [i.get("template", "").lower() for i in items]
        has_evening = "evening" in templates
        has_morning = "morning" in templates
        if has_evening:
            return True, "Evening entry logged"
        if has_morning:
            return True, "Morning entry logged (evening still open)"
        return True, f"{len(items)} entry/entries logged"
    except Exception as e:
        logger.warning(f"[nudge] journal check failed: {e}")
        return False, "Journal check failed"


def _check_how_we_feel(date_str: str) -> tuple[bool, str]:
    """Returns (complete, detail). Looks in apple_health for state_of_mind field."""
    item = _fetch_date("apple_health", date_str)
    if not item:
        return False, "No Apple Health data today"
    # HAE writes the SoM check-in count as som_check_in_count on the apple_health
    # record (the older state_of_mind_count/_check_ins names were never produced).
    som = item.get("som_check_in_count") or item.get("state_of_mind_count") or item.get("state_of_mind_check_ins")
    if som and int(float(som)) > 0:
        return True, f"{int(float(som))} How We Feel check-in(s)"
    return False, "No How We Feel check-in today"


def _check_evening_ritual(date_str: str) -> tuple[list[str], str]:
    """Returns (missing_metrics, detail). missing_metrics is a subset of
    ["connection", "mood_valence", "intake_count"] — only the metrics not yet
    logged today, so a partially-completed ritual only re-prompts for what's left.

    #1405: intake_count lives in its own Matthew-private partition (never the
    public-aggregated evening_ritual record), so it gets its own fetch.
    """
    from ritual_link import PRIVATE_INTAKE_SOURCE

    item = _fetch_date("evening_ritual", date_str)
    connection = item.get("connection") if item else None
    mood_valence = item.get("mood_valence") if item else None
    intake_item = _fetch_date(PRIVATE_INTAKE_SOURCE, date_str)
    intake = intake_item.get("intake_count") if intake_item else None
    missing_metrics = []
    if connection is None:
        missing_metrics.append("connection")
    if mood_valence is None:
        missing_metrics.append("mood_valence")
    if intake is None:
        missing_metrics.append("intake_count")
    if not missing_metrics:
        return [], f"Connection {int(connection)}/4 · Mood {int(mood_valence)}/4 · Intake {int(intake)}"
    if len(missing_metrics) < 3:
        return missing_metrics, f"Partially logged — {len(missing_metrics)} tap{'s' if len(missing_metrics) != 1 else ''} left"
    return missing_metrics, "Not logged yet"


def _get_ritual_secret() -> str | None:
    """Fail-soft: a missing/unreadable secret just skips the tap-link section
    for today rather than breaking the whole nudge email."""
    global _ritual_secret_cache
    if _ritual_secret_cache:
        return _ritual_secret_cache
    try:
        _ritual_secret_cache = secretsmanager.get_secret_value(SecretId=RITUAL_TOKEN_SECRET_NAME)["SecretString"]
        return _ritual_secret_cache
    except Exception as e:
        logger.warning(f"[nudge] ritual token secret unavailable (skipping tap links): {e}")
        return None


def _ritual_link(secret: str, date_str: str, metric: str, value: int) -> str:
    token = sign_ritual_token(secret, date_str, metric, value)
    return f"{SITE_URL}/api/ritual_log?date={date_str}&metric={metric}&value={value}&token={token}"


def _ritual_metric_block(secret: str, date_str: str, metric: str) -> str:
    labels = RITUAL_LABELS[metric]
    buttons = "".join(
        f'<a href="{_ritual_link(secret, date_str, metric, v)}" '
        'style="display:inline-block;width:16%;margin:0 1%;padding:8px 0;background:#2d2d44;color:#fff;'
        'text-decoration:none;text-align:center;border-radius:6px;font-size:12px;font-weight:700;">'
        f"{v}</a>"
        for v in range(len(labels))
    )
    caption = " · ".join(f"{i}={label}" for i, label in enumerate(labels))
    return f"""
        <p style="font-size:12px;color:#374151;font-weight:600;margin:10px 0 4px;">{RITUAL_METRIC_TITLES[metric]}</p>
        <div>{buttons}</div>
        <p style="font-size:10px;color:#9ca3af;margin:2px 0 0;">{caption}</p>"""


def _build_ritual_section(date_str: str, missing_metrics: list[str]) -> str:
    """One-tap section HTML, or "" if nothing's missing or the secret's unavailable
    (fail-soft — see _get_ritual_secret)."""
    if not missing_metrics:
        return ""
    secret = _get_ritual_secret()
    if not secret:
        return ""
    blocks = "".join(_ritual_metric_block(secret, date_str, m) for m in missing_metrics)
    return f"""
    <div style="padding:4px 24px 16px;">
      <div style="background:#eef2ff;border-radius:8px;padding:12px 14px;">
        <p style="font-size:12px;color:#4338ca;font-weight:700;margin:0 0 4px;">🌙 Evening ritual — one tap each, no typing</p>
        {blocks}
      </div>
    </div>"""


# ── #746: gentle "gone quiet" mentions for manual capture sources ─────────────
# When a hand-filled source (the evening journal, or a manual Apple-Health stream
# like CGM/BP/State of Mind/water) has been dark past its registry threshold, the
# nudge mentions it gently — never a nag, never a device outage the nudge can't
# fix. Scoped to the 'notion' + 'hae' channels: the journal + manual health streams
# that fit a "before bed" capture ritual. MCP-logged one-offs (tape measurements,
# food-delivery orders) are surfaced on the public board's degraded stamp instead —
# a gap there isn't a nightly capture lapse. ADDITIVE ONLY: this section rides along
# when the nudge is already sending; it never force-sends on its own, so a long-dark
# source can't turn the nudge into a daily nag (#746).
NUDGE_QUIET_CHANNELS = frozenset({"notion", "hae"})
_HAE_LIVENESS_SK = "DATATYPE_LIVENESS"  # apple_health per-datatype liveness sentinel (freshness_checker writes it)


def _quiet_detail(days: int) -> str:
    """Kind, non-numeric-alarm phrasing for a gone-quiet source."""
    if days >= 14:
        weeks = days // 7
        return f"Quiet {days} days (~{weeks} week{'s' if weeks != 1 else ''}) — no rush"
    return f"Quiet {days} days — whenever you're ready"


def select_quiet_manual_sources(manual_sources, latest_by_source, hae_liveness, today, nudge_channels=NUDGE_QUIET_CHANNELS):
    """Pure: which manual capture sources are gently worth mentioning tonight.

    manual_sources: source_registry.manual_capture_sources() — {key:{label,channel,stale_hours}}.
    latest_by_source: {key: 'YYYY-MM-DD'|None} newest partition record per source.
    hae_liveness: the stored apple_health per-datatype liveness list (or None) —
        each {label, age_days, dark, manual}.
    today: 'YYYY-MM-DD'.

    Returns [{name, channel, days, detail}] sorted longest-dark first. A source with
    NO history is skipped (no invented nag). Device streams (manual=False) and any
    channel outside `nudge_channels` are excluded — a dead pipe is never a nudge."""
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return []
    out = []
    for key, meta in manual_sources.items():
        ch = meta.get("channel")
        # 'hae' is handled below via per-stream liveness — the apple_health partition
        # itself stays fresh on steps/water and would never look dark at partition level.
        if ch not in nudge_channels or ch == "hae":
            continue
        last = latest_by_source.get(key)
        if not last:
            continue
        try:
            days = (today_d - datetime.strptime(str(last)[:10], "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            continue
        if days > meta["stale_hours"] / 24.0:
            out.append({"name": meta["label"], "channel": ch, "days": days, "detail": _quiet_detail(days)})
    if "hae" in nudge_channels:
        for d in hae_liveness or []:
            if d.get("manual") and d.get("dark") and d.get("age_days") is not None:
                days = int(d["age_days"])
                out.append({"name": d.get("label", "Apple Health"), "channel": "hae", "days": days, "detail": _quiet_detail(days)})
    out.sort(key=lambda e: e["days"], reverse=True)
    return out


def _latest_date_for(source: str) -> str | None:
    """Newest YYYY-MM-DD among a source's DATE# records, or None. Fail-soft."""
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": USER_PREFIX + source, ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="sk",
        )
        items = r.get("Items", [])
        return str(items[0]["sk"]).replace("DATE#", "")[:10] if items else None
    except Exception as e:
        logger.warning(f"[nudge] latest_date_for({source}) failed: {e}")
        return None


def _hae_liveness() -> list | None:
    """The stored apple_health per-datatype liveness list (or None). Fail-soft."""
    try:
        rec = table.get_item(Key={"pk": USER_PREFIX + "apple_health", "sk": _HAE_LIVENESS_SK}).get("Item")
        return _d2f(rec).get("datatypes") if rec else None
    except Exception as e:
        logger.warning(f"[nudge] hae_liveness read failed: {e}")
        return None


def _build_quiet_section(quiet: list) -> str:
    """Gentle 'gone quiet' HTML, or "" when nothing qualifies."""
    if not quiet:
        return ""
    rows = "".join(
        f'<p style="font-size:12px;color:#6b7280;margin:4px 0;">' f'<strong style="color:#4b5563;">{q["name"]}</strong> — {q["detail"]}</p>'
        for q in quiet
    )
    return f"""
    <div style="padding:4px 24px 16px;">
      <div style="background:#f0f9ff;border-radius:8px;padding:12px 14px;">
        <p style="font-size:12px;color:#0369a1;font-weight:700;margin:0 0 4px;">🕰️ Gone quiet — no pressure</p>
        {rows}
      </div>
    </div>"""


def _build_html(today_str: str, missing: list[dict], complete: list[dict], ritual_html: str = "", quiet_html: str = "") -> str:
    missing_rows = ""
    for m in missing:
        missing_rows += f"""
        <tr>
          <td style="padding:10px 0;font-size:14px;color:#1a1a2e;font-weight:600;">
            {m['icon']} {m['name']}
          </td>
          <td style="padding:10px 0;font-size:13px;color:#6b7280;text-align:right;">
            {m['detail']}
          </td>
        </tr>"""

    complete_rows = ""
    for c in complete:
        complete_rows += f"""
        <tr>
          <td style="padding:6px 0;font-size:13px;color:#6b7280;">✅ {c['name']}</td>
          <td style="padding:6px 0;font-size:12px;color:#9ca3af;text-align:right;">{c['detail']}</td>
        </tr>"""

    try:
        today_fmt = datetime.strptime(today_str, "%Y-%m-%d").strftime("%A, %B %-d")
    except Exception:
        today_fmt = today_str

    missing_count = len(missing)
    headline = "One thing left to log" if missing_count == 1 else f"{missing_count} things left to log"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:480px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.07);">
    <div style="background:#1a1a2e;padding:18px 24px 14px;">
      <p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Evening Nudge</p>
      <h1 style="color:#fff;font-size:16px;font-weight:700;margin:0;">{today_fmt}</h1>
    </div>

    <div style="background:#f59e0b;padding:12px 24px;">
      <p style="color:#fff;font-size:14px;font-weight:700;margin:0;">⏰ {headline}</p>
      <p style="color:#fef3c7;font-size:12px;margin:3px 0 0;">Quick log before bed — your morning brief will be better for it.</p>
    </div>

    <div style="padding:20px 24px 4px;">
      <table style="width:100%;border-collapse:collapse;">
        {missing_rows}
      </table>
    </div>

    {ritual_html}

    {quiet_html}

    {'<div style="padding:4px 24px 16px;"><table style="width:100%;border-collapse:collapse;border-top:1px solid #f3f4f6;">' + complete_rows + '</table></div>' if complete_rows else ''}

    <div style="padding:0 24px 20px;">
      <div style="background:#f8f8fc;border-radius:8px;padding:12px 14px;">
        <p style="font-size:12px;color:#6b7280;line-height:1.6;margin:0;">
          <strong>Supplements:</strong> use the Life Platform MCP tool or Hevy/Habitify &nbsp;·&nbsp;
          <strong>Journal:</strong> open Notion and write your evening entry &nbsp;·&nbsp;
          <strong>How We Feel:</strong> open Apple Health and log a check-in
        </p>
      </div>
    </div>

    <div style="background:#f8f8fc;padding:10px 24px;border-top:1px solid #e8e8f0;">
      <p style="color:#9ca3af;font-size:10px;margin:0;text-align:center;">Life Platform · Evening Data Nudge · {today_str}</p>
    </div>
  </div>
</body>
</html>"""


def lambda_handler(event, context):
    try:
        # Pacific day, not UTC: this lambda runs on an 8 PM PT cron (03:00 UTC), where
        # a UTC "today" is tomorrow in PT — so every manual source reads "not logged".
        # See AUDIT BUG-02.
        today = pacific_today()
        logger.info(f"[nudge] Checking data completeness for {today}")

        checks = [
            {
                "name": "Supplements",
                "icon": "💊",
                "fn": _check_supplements,
            },
            {
                "name": "Journal",
                "icon": "📓",
                "fn": _check_journal,
            },
            {
                "name": "How We Feel",
                "icon": "💭",
                "fn": _check_how_we_feel,
            },
        ]

        missing = []
        complete = []

        for check in checks:
            try:
                done, detail = check["fn"](today)
                entry = {"name": check["name"], "icon": check.get("icon", ""), "detail": detail}
                if done:
                    complete.append(entry)
                else:
                    missing.append(entry)
            except Exception as e:
                logger.warning(f"[nudge] Check '{check['name']}' failed: {e}")
                missing.append({"name": check["name"], "icon": check.get("icon", ""), "detail": "Check failed"})

        # #769 (ADR-124): the evening-ritual C floor — checked and (if incomplete)
        # rendered as its own tap-button section, not a generic text row. Folded
        # into `missing`/`complete` too so it participates in the same "send if
        # anything's incomplete" gate as the other three checks — the ritual
        # must survive a quiet week, which means it has to keep showing up.
        ritual_missing, ritual_detail = _check_evening_ritual(today)
        ritual_entry = {"name": "Evening Ritual", "icon": "🌙", "detail": ritual_detail}
        if ritual_missing:
            missing.append(ritual_entry)
        else:
            complete.append(ritual_entry)
        ritual_html = _build_ritual_section(today, ritual_missing)

        # #746: gentle staleness mentions for manual capture sources (journal +
        # manual HAE streams) gone dark past their registry threshold. ADDITIVE —
        # computed for the email body, but NOT part of the send gate below, so a
        # long-dark source can't turn the nudge into a nightly nag (kind, not naggy).
        quiet = []
        try:
            manual = manual_capture_sources()
            latest_by_source = {
                k: _latest_date_for(k) for k, m in manual.items() if m["channel"] in NUDGE_QUIET_CHANNELS and m["channel"] != "hae"
            }
            quiet = select_quiet_manual_sources(manual, latest_by_source, _hae_liveness(), today)
        except Exception as e:
            logger.warning(f"[nudge] quiet-source scan failed (non-fatal): {e}")
        quiet_html = _build_quiet_section(quiet)

        logger.info(
            f"[nudge] Missing: {[m['name'] for m in missing]} | Complete: {[c['name'] for c in complete]} "
            f"| Quiet: {[q['name'] for q in quiet]}"
        )

        if not missing:
            logger.info("[nudge] All sources complete — no email needed today")
            return {"statusCode": 200, "body": "All complete — no nudge sent"}

        html = _build_html(today, missing, complete, ritual_html, quiet_html)
        subject = f"Evening nudge · {len(missing)} thing(s) to log before bed"

        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info(f"[nudge] Sent: {subject}")
        return {"statusCode": 200, "body": f"Nudge sent: {subject}"}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
