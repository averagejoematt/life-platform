"""
Evening Nudge Lambda — R54
Fires at 8 PM PT daily (03:00 UTC via EventBridge).
Checks which manual-input data sources are missing for today and sends
a short reminder email if any are incomplete.

Sources checked:
  - Supplements (has any batch been logged today?)
  - Journal (has morning or evening entry been created today?)
  - How We Feel / State of Mind (has a check-in arrived via webhook today?)

Only sends email when at least one source is missing.
No email on days when all three are complete — don't nag unnecessarily.

v1.0.0 — 2026-03-15 (R54)
"""

import json
import os
import logging
import boto3
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]
SENDER     = os.environ["EMAIL_SENDER"]
USER_ID    = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)


def _d2f(obj):
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


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
    som = item.get("state_of_mind_count") or item.get("state_of_mind_check_ins")
    if som and int(float(som)) > 0:
        return True, f"{int(float(som))} How We Feel check-in(s)"
    # Also check the dedicated state_of_mind partition
    som_item = _fetch_date("state_of_mind", date_str)
    if som_item and som_item.get("check_in_count", 0) > 0:
        return True, f"{som_item['check_in_count']} How We Feel check-in(s)"
    return False, "No How We Feel check-in today"


def _build_html(today_str: str, missing: list[dict], complete: list[dict]) -> str:
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
    headline = (
        "One thing left to log"
        if missing_count == 1
        else f"{missing_count} things left to log"
    )

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
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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

        missing  = []
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

        logger.info(f"[nudge] Missing: {[m['name'] for m in missing]} | Complete: {[c['name'] for c in complete]}")

        if not missing:
            logger.info("[nudge] All sources complete — no email needed today")
            return {"statusCode": 200, "body": "All complete — no nudge sent"}

        html    = _build_html(today, missing, complete)
        subject = f"Evening nudge · {len(missing)} thing(s) to log before bed"

        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
            }},
        )
        logger.info(f"[nudge] Sent: {subject}")
        return {"statusCode": 200, "body": f"Nudge sent: {subject}"}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
