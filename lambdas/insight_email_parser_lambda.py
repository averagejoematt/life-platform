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

import json
import logging
import email
import os
import re
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from email import policy

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ── Config (env vars with backwards-compatible defaults) ──
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
ses      = boto3.client("sesv2", region_name=REGION)

S3_BUCKET  = os.environ["S3_BUCKET"]

# Confirmation emails send FROM this address (root domain DKIM already verified)
SENDER = "awsdev@mattsusername.com"

# Allowed sender addresses (security: only process Matthew's emails)
# Loaded from env var (comma-separated) with hardcoded fallback
_env_senders = os.environ.get("ALLOWED_SENDERS", "")
ALLOWED_SENDERS = {s.strip().lower() for s in _env_senders.split(",") if s.strip()} if _env_senders else {
    "awsdev@mattsusername.com",
    # TODO: Add your personal email address(es) here or set ALLOWED_SENDERS env var
}


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
        if re.match(r'^On .+ wrote:$', stripped):
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
    text = re.sub(r'^(track this|save this|insight|note)[:\s]*', '', text, flags=re.IGNORECASE).strip()

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
        Content={"Simple": {
            "Subject": {"Data": f"Insight saved: {preview[:50]}", "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )


def lambda_handler(event, context):
    """
    Triggered by S3 event when SES deposits a raw email.
    
    Event can come from:
    1. S3 Event Notification (has 'Records' with s3 info)
    2. SES direct invocation (has 'Records' with ses info)
    """
    print(f"[INFO] Insight Email Parser v1.1.0 triggered")

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
        sender_email = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', from_addr)
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
                        body_text = re.sub(r'<[^>]+>', '', html_content)
                        break
        else:
            body_text = msg.get_content()

        # Extract reply text
        reply_text = extract_reply_text(body_text)

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
