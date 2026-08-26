"""
Insight Email Parser Lambda — v1.2.0

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

Changes v1.2.0 (#2821 — the watch-surface fix):
  - Every per-record path that catches a failure and continues (rather than
    re-raising) now persists the failing envelope to
    dead-letter-archive/insight-email-parser/ AND emits
    LifePlatform/Email::InsightParseFailure (see _persist_failure_envelope /
    _emit_parse_failure_metric below) — a class the CDK-level Errors alarm
    structurally cannot see (the function still returns 200).
  - CDK side (cdk/stacks/operational_stack.py): dlq=local_dlq +
    alerts_topic=local_digest_topic so a genuine unhandled exception (crash
    class) now mints the shared helper's per-function Errors alarm AND
    preserves the original SES/S3 event in the ingestion DLQ.

Dry-run posture (#2291): this module is EVENT-driven (SES inbound receipt →
S3 → Lambda), never scheduled, so it is exempt from #2222's DEFAULT dry-run
suppression — the declared `SES_EXEMPT_EVENT_DRIVEN` marker below is what the
guard test derives that exemption from, and it also asserts the function has no
EventBridge schedule= in cdk/stacks/. An EXPLICIT `{"dry_run": true}` on the
event is still honored: every send routes through
common.send_guard.guarded_send_email and the insight/correction writes are
suppressed, so replaying a captured S3/SES event with the flag added is safe.
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
from common import send_ledger  # #3113 / DIL-025: the durable replay guard
from common.pacific_time import pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from common.send_guard import guarded_send_email, is_dry_run

# #2291: DECLARED trigger-type exemption from the DEFAULT SES dry-run suppression.
# The exemption axis is TRIGGER TYPE, not recipient consent: this handler runs only
# when SES receives a real inbound email (receipt rule → S3 → Lambda), so a stray
# operator invoke with an empty event sends nothing — there are no Records to mail
# about. tests/test_ses_send_guard_set_2222.py derives the exempt set from this
# marker and fails if this function ever grows an EventBridge schedule=.
SES_EXEMPT_EVENT_DRIVEN = "SES inbound receipt rule -> S3 -> Lambda; sends only in reply to a real inbound email, never on a schedule"

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from common.platform_logger import get_logger

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
    from coach import coach_correction_resolver as ccr, coach_corrections
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
cloudwatch = boto3.client("cloudwatch", region_name=REGION)

#: The `email_log#` partition this sender's completion rows live in (#3113).
LEDGER_NAME = "insight_email_parser"

S3_BUCKET = os.environ["S3_BUCKET"]

# #2821: this Lambda had ZERO watch surface — an SES-async invoke that raises
# retries twice then evaporates with no DLQ, AND several code paths below
# already caught a per-record failure and just `continue`d (the function still
# returns 200, so neither a raised exception nor a Lambda Errors-metric alarm
# would ever see it). The CDK side now wires dlq= + alerts_topic= for the
# crash class; these two helpers close the SILENT-catch class — every place
# this handler decides not to process a record now leaves (1) a durable
# envelope in S3 and (2) an alarmable metric, instead of nothing.
FAILURE_METRIC_NAMESPACE = "LifePlatform/Email"
FAILURE_METRIC_NAME = "InsightParseFailure"
_FAILURE_ARCHIVE_PREFIX = "dead-letter-archive/insight-email-parser"


def _emit_parse_failure_metric(reason: str) -> None:
    """Best-effort EMF-style emit — a metric-service hiccup must never mask the
    failure it is reporting (that would recreate the exact silent-loss bug)."""
    try:
        cloudwatch.put_metric_data(
            Namespace=FAILURE_METRIC_NAMESPACE,
            MetricData=[{"MetricName": FAILURE_METRIC_NAME, "Value": 1.0, "Unit": "Count"}],
        )
    except Exception as e:  # noqa: BLE001 — telemetry is best-effort
        print(f"[WARN] parse-failure metric emit failed ({reason}): {e}")


def _persist_failure_envelope(identifier: str, reason: str, payload: dict) -> str:
    """Durable trace of a record this handler decided not to process, so a
    caught-and-skipped failure is never fully silent. Mirrors the
    dead-letter-archive/ convention dlq_consumer_lambda.py already uses for
    terminal ASYNC failures (#402/ADR-115) — this is the inline twin for a
    failure caught HERE and not re-raised, so the Lambda DLQ never sees it.
    Own subfolder (not the DLQ consumer's dead-letter-archive/ root) so the two
    writers never share a key namespace. Fail-soft on the S3 write (the metric
    above is the primary alarmable signal either way); returns the key written,
    or "" on a write failure."""
    now = datetime.now(timezone.utc)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(identifier) or "unknown")[:180] or "unknown"
    key = f"{_FAILURE_ARCHIVE_PREFIX}/{now.strftime('%Y/%m/%d')}/{now.strftime('%H%M%S')}-{safe_id}.json"
    record = {"failed_at": now.isoformat(), "reason": reason, "identifier": identifier, "payload": payload}
    written = ""
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(record, indent=2, default=str), ContentType="application/json")
        written = key
        print(f"[INFO] failure envelope archived to s3://{S3_BUCKET}/{key}")
    except Exception as e:  # noqa: BLE001 — archival is best-effort
        print(f"[ERROR] failed to archive failure envelope ({reason}): {e}")
    _emit_parse_failure_metric(reason)
    return written


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


def save_insight(text, source_email_subject="", dry_run=False):
    """Save the insight to DynamoDB insights partition.

    Under an explicit dry run (#2291) the write is suppressed — a dry run must
    leave no record claiming the real run happened."""
    now = datetime.now(timezone.utc)
    insight_id = now.isoformat()
    # #2817: the id stays a UTC INSTANT (it is the record's identity and sorts
    # monotonically); the DAY it is filed under is Pacific, like every other
    # `date`-shaped field the site reads.
    date_saved = pacific_today()

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
    if dry_run:
        print(f"[DRY-RUN] insight write suppressed — {len(text)} chars, tags={tags}")
    else:
        table.put_item(Item=item)

    return insight_id, date_saved


def send_confirmation(insight_text, insight_id, recipient_email, dry_run=False):
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

    guarded_send_email(
        ses,
        dry_run,
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


def _send_correction_confirmation(applied, unresolved, recipient_email, subject="", dry_run=False):
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
    guarded_send_email(
        ses,
        dry_run,
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [recipient_email]},
        Content={
            "Simple": {
                "Subject": {"Data": f"Review-pack corrections: {len(applied)} logged, {len(unresolved)} not applied", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            }
        },
    )


def handle_review_pack_reply(reply_text, subject, sender, dry_run=False):
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
                _send_correction_confirmation(
                    [], [f"could not read this week's review pack ({e}) — please retry"], sender, subject, dry_run=dry_run
                )
            except Exception as se:  # pragma: no cover
                print(f"[WARN] correction confirmation email failed: {se}")
            return {"applied": [], "unresolved": ["archive read failed"]}

        for n, text in corrections:
            resolution = ccr.resolve_number(n, numbered=numbered)
            if not resolution.get("ok"):
                unresolved.append(f"#{n}: {resolution.get('error')}")
                continue
            if dry_run:
                # #2291: a dry run resolves and reports but never writes the ledger.
                sk = "dry-run-suppressed"
                print(f"[DRY-RUN] correction write suppressed for #{n}")
            else:
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
        _send_correction_confirmation(applied, unresolved, sender, subject, dry_run=dry_run)
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

        # #2291: this handler is exempt from DEFAULT dry-run suppression (it is
        # SES-receipt-triggered — see SES_EXEMPT_EVENT_DRIVEN), but an EXPLICIT
        # {"dry_run": true} on a replayed event suppresses every send and write.
        dry_run = is_dry_run(event)
        if dry_run:
            print("[DRY-RUN] explicit dry run — sends and writes will be suppressed")

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
                    # #2821: an S3-key-less/messageId-less record is itself a
                    # malformed envelope — persist the whole record so it is
                    # never just a WARN line nobody watches.
                    _persist_failure_envelope("unresolvable-record", "missing_s3_key", record)
                    continue

            print(f"[INFO] Processing: s3://{bucket}/{key}")

            # DIL-025 / #3113 replay guard. This sender is event-driven, so it
            # has no calendar period at all — the identity of the letter is the
            # INBOUND MESSAGE it answers, and the S3 object key is that message's
            # id. A redrive of the S3/SES record replays the same key, so the
            # confirmation reply goes out once per inbound email, not once per
            # delivery of it.
            period_key = f"msg:{key}"
            if send_ledger.should_skip_replay(table, LEDGER_NAME, period_key, dry_run=dry_run, event=event, logger=logger):
                print(f"[DIL-025] already replied to {key} — not answering it twice")
                continue

            # Read raw email from S3
            try:
                obj = s3.get_object(Bucket=bucket, Key=key)
                raw_email = obj["Body"].read().decode("utf-8", errors="replace")
            except Exception as e:
                print(f"[ERROR] Failed to read email from S3: {e}")
                # #2821: can't even read the email — the reply is otherwise gone
                # with only this log line as a trace. Persist what we know.
                _persist_failure_envelope(key, "s3_read_failed", {"bucket": bucket, "key": key, "error": str(e)})
                continue

            # #2821: parsing/extraction wrapped so a malformed MIME payload (an
            # exception nothing below explicitly catches) leaves an envelope +
            # metric HERE, immediately, rather than only via the outer
            # catch-log-reraise → DLQ → 6-hourly dlq-consumer sweep path.
            try:
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
            except Exception as e:
                print(f"[ERROR] Failed to parse email: {e}")
                _persist_failure_envelope(key, "parse_exception", {"bucket": bucket, "key": key, "error": str(e), "raw_email": raw_email})
                continue

            # #1690 (epic #1687): a reply to the weekly AI review-pack email carrying
            # "#N <correction>" lines is a CORRECTION, not a generic insight — route it
            # to the corrections ledger (the same rows the MCP log_coach_correction tool
            # writes). Handled BEFORE the short-length guard so even a terse "#3 wrong"
            # reply is processed (and any malformed/unknown line is reported back).
            if _is_review_pack_reply(subject):
                print(f"[INFO] review-pack reply detected (subject: {subject[:80]!r}) — routing to corrections ledger")
                handle_review_pack_reply(reply_text, subject, sender, dry_run=dry_run)
                if not dry_run:  # DIL-025: one line after the send it just made
                    send_ledger.record_sent(table, LEDGER_NAME, period_key, logger=logger)
                continue

            if not reply_text or len(reply_text) < 5:
                print(f"[WARN] Reply text too short or empty: '{reply_text[:50]}'")
                continue

            print(f"[INFO] Extracted reply ({len(reply_text)} chars): {reply_text[:100]}...")

            # Save as insight — the actual DDB write path #2821 is centrally about.
            try:
                insight_id, date_saved = save_insight(reply_text, source_email_subject=subject, dry_run=dry_run)
            except Exception as e:
                print(f"[ERROR] Failed to save insight: {e}")
                _persist_failure_envelope(
                    key,
                    "insight_write_failed",
                    {"bucket": bucket, "key": key, "sender": sender, "subject": subject, "reply_text": reply_text, "error": str(e)},
                )
                continue
            print(f"[INFO] Insight saved: {insight_id}")

            # Send confirmation back to sender
            try:
                send_confirmation(reply_text, insight_id, recipient_email=sender, dry_run=dry_run)
                if not dry_run:  # DIL-025: one line after the SES call
                    send_ledger.record_sent(table, LEDGER_NAME, period_key, logger=logger)
                print(f"[INFO] Confirmation email sent to {sender}")
            except Exception as e:
                print(f"[WARN] Confirmation email failed: {e}")

        return {"statusCode": 200, "body": json.dumps({"status": "ok", "dry_run": dry_run})}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        # #2821: the last-resort path (anything NOT already caught+persisted
        # per-record above — e.g. a malformed event shape). Persist + emit
        # immediately rather than waiting on the DLQ/dlq-consumer's 6-hourly
        # sweep; the re-raise below is UNCHANGED (still needed so the async
        # invoke's retry + DLQ safety net stays live for this class too).
        _persist_failure_envelope("event", "unhandled_exception", {"event": event, "error": str(e)})
        raise
