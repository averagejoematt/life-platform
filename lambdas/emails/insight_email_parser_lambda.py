"""
Insight Email Parser Lambda — v1.1.0

Triggered by SES inbound email → S3 → Lambda.

When Matthew replies to any Life Platform email (sent to insight@aws.mattsusername.com),
this Lambda:
1. Reads the raw email from S3
2. Extracts the reply text (strips quoted original + signatures)
3. Saves the reply as a coaching insight in DynamoDB
4. Sends a confirmation email back to the sender

DynamoDB record:
  pk: USER#matthew#SOURCE#insights
  sk: INSIGHT#<ISO-timestamp>

Trigger: SES Receipt Rule → S3 → S3 Event Notification → this Lambda

Changes v1.1.0:
  - Subdomain routing: insight@aws.mattsusername.com (avoids SimpleLogin conflict)
  - Dynamic reply-to-sender for confirmation emails
  - ALLOWED_SENDERS from env var for easier config updates
"""

import email
import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from email import policy
from html import escape as html_escape

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("insight-email-parser")
except ImportError:
    logger = logging.getLogger("insight-email-parser")
    logger.setLevel(logging.INFO)

# #1690 (epic #1687): the shared "#N -> archived generation" resolver + the corrections
# ledger writer, for the email-reply feedback channel (the twin of the MCP
# log_coach_correction tool). Both bundle at lambdas/ root (#781). Fail-soft import: a
# missing module must never crash the (unrelated) insight-save path — it only disables
# correction routing.
try:
    import coach_correction_resolver as ccr
    import coach_corrections
except Exception:  # pragma: no cover — bundle-dependent
    ccr = None
    coach_corrections = None


# ── Config (env vars with backwards-compatible defaults) ──
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)

S3_BUCKET = os.environ["S3_BUCKET"]

# Confirmation emails send FROM this address (root domain DKIM already verified)
SENDER = "awsdev@mattsusername.com"

# Allowed sender addresses (security: only process Matthew's emails)
# Loaded from env var (comma-separated) with hardcoded fallback
_env_senders = os.environ.get("ALLOWED_SENDERS", "")
ALLOWED_SENDERS = (
    {s.strip().lower() for s in _env_senders.split(",") if s.strip()}
    if _env_senders
    else {
        "awsdev@mattsusername.com",
        # TODO: Add your personal email address(es) here or set ALLOWED_SENDERS env var
    }
)


def extract_reply_text(email_body):
    """
    Extract just the reply text, removing quoted original, signatures, etc.
    Handles common email client patterns:
      - "On <date>, <sender> wrote:" (Gmail, Apple Mail)
      - "From: <sender>" (Outlook)
      - "-----Original Message-----"
      - ">" quoted lines
      - Signature delimiters ("--", "Sent from my iPhone")
    """
    if not email_body:
        return ""

    lines = email_body.strip().split("\n")
    reply_lines = []

    for line in lines:
        stripped = line.strip()

        # Stop at quoted original markers
        if re.match(r"^On .+ wrote:$", stripped):
            break
        if stripped.startswith("From:") and "@" in stripped:
            break
        if stripped == "-----Original Message-----":
            break
        if stripped.startswith(">"):
            break

        # Stop at signature markers
        if stripped == "--":
            break
        if stripped.startswith("Sent from my"):
            break
        if stripped.startswith("Get Outlook"):
            break

        reply_lines.append(line)

    text = "\n".join(reply_lines).strip()

    # Remove any "track this" / "save this" command prefix (case-insensitive)
    text = re.sub(r"^(track this|save this|insight|note)[:\s]*", "", text, flags=re.IGNORECASE).strip()

    return text


def save_insight(text, source_email_subject=""):
    """Save the insight to DynamoDB insights partition."""
    now = datetime.now(timezone.utc)
    insight_id = now.isoformat()
    date_saved = now.strftime("%Y-%m-%d")

    # Auto-detect tags from subject line
    tags = []
    if "anomaly" in source_email_subject.lower():
        tags.append("anomaly")
    if "daily brief" in source_email_subject.lower():
        tags.append("daily_brief")
    if "weekly" in source_email_subject.lower():
        tags.append("weekly_digest")
    if "monthly" in source_email_subject.lower():
        tags.append("monthly_digest")

    item = {
        "pk": f"USER#{USER_ID}#SOURCE#insights",
        "sk": f"INSIGHT#{insight_id}",
        "insight_id": insight_id,
        "text": text,
        "date_saved": date_saved,
        "source": "email",
        "status": "open",
        "outcome_notes": "",
        "tags": tags,
        "email_subject": source_email_subject[:200] if source_email_subject else "",
    }

    item = json.loads(json.dumps(item), parse_float=Decimal)
    table.put_item(Item=item)

    return insight_id, date_saved


def send_confirmation(insight_text, insight_id, recipient_email):
    """Send a brief confirmation email back to the sender."""
    preview = insight_text[:80] + ("..." if len(insight_text) > 80 else "")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:480px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:#1a1a2e;padding:16px 24px;">
      <p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Life Platform</p>
      <h1 style="color:#fff;font-size:15px;font-weight:700;margin:0;">Insight Saved</h1>
    </div>
    <div style="padding:16px 24px;">
      <p style="font-size:13px;color:#374151;line-height:1.6;margin:0;background:#f8f8fc;padding:12px 14px;border-radius:8px;border-left:3px solid #10b981;">
        {preview}
      </p>
      <p style="font-size:11px;color:#9ca3af;margin:12px 0 0;">
        Status: open | Review via Claude Desktop: get_insights
      </p>
    </div>
  </div>
</body>
</html>"""

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [recipient_email]},
        Content={
            "Simple": {
                "Subject": {"Data": f"Insight saved: {preview[:50]}", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
            }
        },
    )


# ── #1690: weekly-review-pack correction reply channel ──────────────────────


def _is_review_pack_reply(subject):
    """A reply to the weekly AI review-pack email (subject '🗂️ Weekly AI Review Pack …',
    a reply prefixes 'Re: '). Gated on the subject so a normal insight reply that happens
    to contain a '#3' is never hijacked into the corrections ledger."""
    return "review pack" in (subject or "").lower()


def _send_correction_confirmation(applied, unresolved, recipient_email, subject=""):
    """Echo back what landed and what didn't (AC3: unresolved is never silently dropped)."""
    applied_rows = "".join(
        f'<li style="margin:2px 0;">#{a["n"]} — {html_escape(str(a.get("surface") or ""))}'
        f'{(" · " + html_escape(str(a.get("coach")))) if a.get("coach") else ""} '
        f'<span style="color:#9ca3af;">→ logged</span></li>'
        for a in applied
    )
    unresolved_rows = "".join(f'<li style="margin:2px 0;color:#fca5a5;">{html_escape(str(u))}</li>' for u in unresolved)
    applied_block = (
        f'<p style="font-size:12px;color:#374151;margin:8px 0 2px;font-weight:700;">Logged ({len(applied)}):</p>'
        f'<ul style="margin:0 0 8px;padding-left:18px;font-size:13px;color:#374151;">{applied_rows}</ul>'
        if applied
        else ""
    )
    unresolved_block = (
        f'<p style="font-size:12px;color:#b91c1c;margin:8px 0 2px;font-weight:700;">Not applied ({len(unresolved)}):</p>'
        f'<ul style="margin:0 0 8px;padding-left:18px;font-size:13px;">{unresolved_rows}</ul>'
        if unresolved
        else ""
    )
    accent = "#10b981" if applied and not unresolved else ("#f59e0b" if applied else "#ef4444")
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:480px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:#1a1a2e;padding:16px 24px;">
      <p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Life Platform · Review Pack</p>
      <h1 style="color:#fff;font-size:15px;font-weight:700;margin:0;">Corrections received</h1>
    </div>
    <div style="padding:16px 24px;border-left:3px solid {accent};">
      {applied_block}
      {unresolved_block}
      <p style="font-size:11px;color:#9ca3af;margin:8px 0 0;">
        Corrections join the ledger (epic #1687) tagged 'other'. Set a class via the log_coach_correction tool.
      </p>
    </div>
  </div>
</body>
</html>"""
    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [recipient_email]},
        Content={
            "Simple": {
                "Subject": {"Data": f"Review-pack corrections: {len(applied)} logged, {len(unresolved)} not applied", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            }
        },
    )


def handle_review_pack_reply(reply_text, subject, sender):
    """Land '#N <correction>' reply lines in the corrections ledger (#1690).

    Each #N resolves — via the shared coach_correction_resolver, the SAME numbering the
    MCP channel uses — to the archived generation the pack numbered, then writes one
    ledger row via coach_corrections.write_correction (default class 'other'; the email
    channel carries no class override). Malformed lines and unknown numbers are collected
    and echoed back to the sender, never silently dropped (AC3). Returns a summary dict.
    """
    if ccr is None or coach_corrections is None:
        print("[ERROR] review-pack correction modules unavailable — cannot process reply")
        return {"applied": [], "unresolved": ["correction subsystem unavailable"]}

    parsed = ccr.parse_correction_reply(reply_text)
    corrections, malformed = parsed["corrections"], parsed["malformed"]

    applied = []
    unresolved = [f"could not parse as '#N <correction>': {m}" for m in malformed]

    if not corrections and not malformed:
        unresolved.append("no '#N <correction>' lines found — reply with e.g. '#3 the weight baseline is stale'")

    if corrections:
        # ONE archive read for the whole reply — resolve every #N against the same week.
        try:
            numbered = ccr.numbered_for_week()
        except Exception as e:  # noqa: BLE001 — a broken read is reported, not swallowed
            print(f"[ERROR] could not assemble review-pack week: {e}")
            try:
                _send_correction_confirmation([], [f"could not read this week's review pack ({e}) — please retry"], sender, subject)
            except Exception as se:  # pragma: no cover
                print(f"[WARN] correction confirmation email failed: {se}")
            return {"applied": [], "unresolved": ["archive read failed"]}

        for n, text in corrections:
            resolution = ccr.resolve_number(n, numbered=numbered)
            if not resolution.get("ok"):
                unresolved.append(f"#{n}: {resolution.get('error')}")
                continue
            try:
                sk = coach_corrections.write_correction(table, resolution["item_ref"], text, "other")
            except Exception as e:  # noqa: BLE001 — a lost correction must be loud
                print(f"[ERROR] correction write failed for #{n}: {e}")
                unresolved.append(f"#{n}: could not be saved ({e})")
                continue
            entry = resolution["entry"]
            applied.append({"n": resolution["n"], "surface": entry.get("surface"), "coach": entry.get("variant"), "sk": sk})
            print(f"[INFO] correction logged for #{resolution['n']} -> {sk}")

    print(f"[INFO] review-pack reply: {len(applied)} applied, {len(unresolved)} unresolved")
    try:
        _send_correction_confirmation(applied, unresolved, sender, subject)
    except Exception as e:  # pragma: no cover — confirmation is best-effort
        print(f"[WARN] correction confirmation email failed: {e}")
    return {"applied": applied, "unresolved": unresolved}


def lambda_handler(event, context):
    try:
        """
        Triggered by S3 event when SES deposits a raw email.

        Event can come from:
        1. S3 Event Notification (has 'Records' with s3 info)
        2. SES direct invocation (has 'Records' with ses info)
        """
        print("[INFO] Insight Email Parser v1.1.0 triggered")

        for record in event.get("Records", []):
            # Handle S3 trigger
            s3_info = record.get("s3", {})
            bucket = s3_info.get("bucket", {}).get("name", S3_BUCKET)
            key = s3_info.get("object", {}).get("key", "")

            if not key:
                # Handle SES direct invocation
                ses_info = record.get("ses", {})
                mail = ses_info.get("mail", {})
                message_id = mail.get("messageId", "")
                if message_id:
                    key = f"raw/inbound_email/{message_id}"
                else:
                    print("[WARN] No S3 key or SES messageId found, skipping")
                    continue

            print(f"[INFO] Processing: s3://{bucket}/{key}")

            # Read raw email from S3
            try:
                obj = s3.get_object(Bucket=bucket, Key=key)
                raw_email = obj["Body"].read().decode("utf-8", errors="replace")
            except Exception as e:
                print(f"[ERROR] Failed to read email from S3: {e}")
                continue

            # Parse email
            msg = email.message_from_string(raw_email, policy=policy.default)

            # Security: check sender
            from_addr = msg.get("From", "")
            sender_email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", from_addr)
            sender = sender_email.group(0).lower() if sender_email else ""

            if sender not in ALLOWED_SENDERS:
                print(f"[WARN] Unauthorized sender: {sender}. Allowed: {ALLOWED_SENDERS}. Ignoring.")
                continue

            subject = msg.get("Subject", "")
            print(f"[INFO] From: {sender}, Subject: {subject}")

            # Extract text body
            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body_text = part.get_content()
                        break
                # Fallback to HTML if no plain text
                if not body_text:
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            html_content = part.get_content()
                            # Basic HTML stripping
                            body_text = re.sub(r"<[^>]+>", "", html_content)
                            break
            else:
                body_text = msg.get_content()

            # Extract reply text
            reply_text = extract_reply_text(body_text)

            # #1690 (epic #1687): a reply to the weekly AI review-pack email carrying
            # "#N <correction>" lines is a CORRECTION, not a generic insight — route it
            # to the corrections ledger (the same rows the MCP log_coach_correction tool
            # writes). Handled BEFORE the short-length guard so even a terse "#3 wrong"
            # reply is processed (and any malformed/unknown line is reported back).
            if _is_review_pack_reply(subject):
                print(f"[INFO] review-pack reply detected (subject: {subject[:80]!r}) — routing to corrections ledger")
                handle_review_pack_reply(reply_text, subject, sender)
                continue

            if not reply_text or len(reply_text) < 5:
                print(f"[WARN] Reply text too short or empty: '{reply_text[:50]}'")
                continue

            print(f"[INFO] Extracted reply ({len(reply_text)} chars): {reply_text[:100]}...")

            # Save as insight
            insight_id, date_saved = save_insight(reply_text, source_email_subject=subject)
            print(f"[INFO] Insight saved: {insight_id}")

            # Send confirmation back to sender
            try:
                send_confirmation(reply_text, insight_id, recipient_email=sender)
                print(f"[INFO] Confirmation email sent to {sender}")
            except Exception as e:
                print(f"[WARN] Confirmation email failed: {e}")

        return {"statusCode": 200, "body": json.dumps({"status": "ok"})}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
