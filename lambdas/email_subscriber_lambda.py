"""
Email Subscriber Lambda — v1.0.0 (BS-03)
Handles subscribe / confirm / unsubscribe for averagejoematt.com.

DynamoDB partition: USER#matthew#SOURCE#subscribers
SK pattern: EMAIL#<sha256_of_email>

Record schema:
  pk          USER#matthew#SOURCE#subscribers
  sk          EMAIL#<sha256>
  email       <plaintext email>
  status      pending_confirmation | confirmed | unsubscribed
  created_at  ISO timestamp (first subscribe request)
  confirmed_at ISO timestamp (when double opt-in completed)
  unsubbed_at ISO timestamp (when unsubscribed)
  source      subscribe_page | referral | ...
  ip_hash     SHA256 of source IP (for abuse detection, non-identifying)

Raj directive: NEVER hard-delete subscriber records.
  Unsub writes status=unsubscribed + unsubbed_at. Row is retained for analytics.

Routes (via API Gateway query param ?action=):
  POST ?action=subscribe   — create pending record, send confirmation email
  GET  ?action=confirm     — confirm email, send welcome
  GET  ?action=unsubscribe — mark unsubscribed (non-destructive)

Confirmation token: 32-byte random hex, stored in DDB, expires 48h.
Welcome email: Ava directive — warm, specific, on-brand.

v1.0.0 — 2026-03-16 (BS-03)
"""

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import logging
import boto3
from datetime import datetime, timedelta, timezone

try:
    from platform_logger import get_logger
    logger = get_logger("email-subscriber")
except ImportError:
    logger = logging.getLogger("email-subscriber")
    logger.setLevel(logging.INFO)

# AWS_REGION is set automatically by Lambda to the function's deployment region.
# email-subscriber deploys to us-east-1 (web_stack.py) but DDB is in us-west-2.
# DYNAMODB_REGION env var overrides to ensure cross-region DDB access.
REGION          = os.environ.get("AWS_REGION", "us-east-1")      # Lambda's own region
DYNAMODB_REGION = os.environ.get("DYNAMODB_REGION", "us-west-2") # DDB table region
SES_REGION      = os.environ.get("SES_REGION", "us-west-2")      # SES verified identity region
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID    = os.environ["USER_ID"]
SENDER     = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL   = os.environ.get("SITE_URL", "https://averagejoematt.com")

SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"

dynamodb = boto3.resource("dynamodb", region_name=DYNAMODB_REGION)  # us-west-2
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=SES_REGION)             # us-west-2 (verified identity)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _email_hash(email: str) -> str:
    """SHA256 of lowercased email — used as SK and for dedup."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()

def _ip_hash(ip: str) -> str:
    """SHA256 of IP — non-reversible, for abuse detection only."""
    return hashlib.sha256((ip or "").encode()).hexdigest()[:16]

def _get_record(email_hash: str) -> dict | None:
    try:
        resp = table.get_item(Key={"pk": SUBSCRIBERS_PK, "sk": f"EMAIL#{email_hash}"})
        return resp.get("Item")
    except Exception as exc:
        logger.error("_get_record failed: %s", exc)
        return None

def _cors_headers():
    return {
        "Access-Control-Allow-Origin":  SITE_URL,
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

def _json_response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {**_cors_headers(), "Content-Type": "application/json"},
        "body": json.dumps(body),
    }

def _redirect(url: str) -> dict:
    return {
        "statusCode": 302,
        "headers": {"Location": url, **_cors_headers()},
        "body": "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# SUBSCRIBE
# ─────────────────────────────────────────────────────────────────────────────

def handle_subscribe(email: str, source_ip: str = "", referrer: str = "") -> dict:
    """Create/update pending record and send confirmation email."""
    email = email.strip().lower()
    if not email or "@" not in email or len(email) > 254:
        return _json_response(400, {"error": "Invalid email address."})

    email_hash = _email_hash(email)
    now_iso    = datetime.now(timezone.utc).isoformat()

    # Check existing record
    existing = _get_record(email_hash)
    if existing:
        status = existing.get("status", "")
        if status == "confirmed":
            # Already subscribed — return success silently (don't leak status)
            logger.info("subscribe: already confirmed %s", email_hash[:8])
            return _json_response(200, {"status": "pending_confirmation", "message": "Check your inbox."})
        if status == "unsubscribed":
            # Allow re-subscribe — reset to pending
            logger.info("subscribe: resubscribe from unsubscribed %s", email_hash[:8])

    # Generate confirmation token
    token     = secrets.token_hex(32)
    token_exp = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
    confirm_url = f"{SITE_URL}/api/subscribe?action=confirm&token={token}&h={email_hash[:16]}"

    # Write DDB record
    item = {
        "pk":           SUBSCRIBERS_PK,
        "sk":           f"EMAIL#{email_hash}",
        "email":        email,
        "email_hash":   email_hash,
        "status":       "pending_confirmation",
        "created_at":   now_iso,
        "confirm_token": token,
        "token_expires": token_exp,
        "ip_hash":      _ip_hash(source_ip),
        "source":       referrer or "subscribe_page",
        "updated_at":   now_iso,
    }
    if existing:
        # Preserve original created_at and confirmed_at if resubscribing
        item["created_at"] = existing.get("created_at", now_iso)
    try:
        table.put_item(Item=item)
    except Exception as exc:
        logger.error("subscribe: DDB write failed: %s", exc)
        return _json_response(500, {"error": "Database error. Please try again."})

    # Send confirmation email (Ava: warm, specific, on-brand)
    _send_confirmation_email(email, confirm_url)
    logger.info("subscribe: pending confirmation sent to %s", email_hash[:8])
    return _json_response(200, {"status": "pending_confirmation", "message": "Check your inbox."})


def _send_confirmation_email(email: str, confirm_url: str) -> None:
    """Ava Moreau directive: warm, specific, on-brand. Not 'please confirm your email'."""
    subject = "One click to confirm — then the actual numbers every Wednesday"
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0D1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:520px;margin:40px auto;padding:40px 32px;background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);">

  <p style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#F0B429;margin:0 0 24px;">The Weekly Signal</p>

  <h1 style="font-size:22px;font-weight:600;color:#E6EDF3;line-height:1.3;margin:0 0 16px;">
    You're almost in.
  </h1>

  <p style="font-size:15px;color:#8b949e;line-height:1.65;margin:0 0 32px;">
    One click to confirm. Then every Wednesday, the actual numbers &mdash;
    real biometric data from 19 sources, habit performance, what worked, what didn't.
    No filtered highlight reel.
  </p>

  <a href="{confirm_url}"
     style="display:inline-block;background:#F0B429;color:#0D1117;font-size:15px;font-weight:600;
            padding:14px 28px;border-radius:8px;text-decoration:none;">
    Confirm my subscription &rarr;
  </a>

  <p style="font-size:12px;color:#484f58;margin:28px 0 0;line-height:1.6;">
    This link expires in 48 hours. If you didn't request this, you can safely ignore it.
  </p>

</div>
</body>
</html>"""

    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [email]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
            }},
        )
        logger.info("confirmation email sent")
    except Exception as exc:
        logger.error("_send_confirmation_email failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIRM
# ─────────────────────────────────────────────────────────────────────────────

def handle_confirm(token: str, email_hash_prefix: str) -> dict:
    """Validate token, confirm subscription, send welcome email."""
    if not token or len(token) != 64:
        return _redirect(f"{SITE_URL}/subscribe/confirm/?error=invalid_token")

    # Find record by scanning for matching token (DDB has no GSI — acceptable
    # given low subscriber volume at launch; add GSI if >10K subs)
    # For now: email_hash_prefix (first 16 chars) narrows search
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk",
            FilterExpression="confirm_token = :t",
            ExpressionAttributeValues={
                ":pk": SUBSCRIBERS_PK,
                ":t":  token,
            },
        )
        items = resp.get("Items", [])
    except Exception as exc:
        logger.error("confirm: DDB query failed: %s", exc)
        return _redirect(f"{SITE_URL}/subscribe/confirm/?error=server_error")

    if not items:
        logger.warning("confirm: no record for token %s", token[:8])
        return _redirect(f"{SITE_URL}/subscribe/confirm/?error=invalid_token")

    record = items[0]
    email  = record.get("email", "")

    # Check expiry
    expires = record.get("token_expires", "")
    if expires and datetime.now(timezone.utc).isoformat() > expires:
        logger.warning("confirm: expired token for %s", record.get("email_hash", "")[:8])
        return _redirect(f"{SITE_URL}/subscribe/confirm/?error=token_expired")

    # Already confirmed
    if record.get("status") == "confirmed":
        return _redirect(f"{SITE_URL}/subscribe/confirm/?confirmed=already")

    # Confirm
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        table.update_item(
            Key={"pk": SUBSCRIBERS_PK, "sk": record["sk"]},
            UpdateExpression="SET #s = :s, confirmed_at = :c, updated_at = :u REMOVE confirm_token, token_expires",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "confirmed", ":c": now_iso, ":u": now_iso},
        )
    except Exception as exc:
        logger.error("confirm: DDB update failed: %s", exc)
        return _redirect(f"{SITE_URL}/subscribe/confirm/?error=server_error")

    logger.info("confirmed subscriber: %s", record.get("email_hash", "")[:8])
    _send_welcome_email(email)
    return _redirect(f"{SITE_URL}/subscribe/confirm/?confirmed=true")


def _send_welcome_email(email: str) -> None:
    """Ava directive: the first experience a subscriber has with your voice.
    Warm, specific, on-brand. Not 'thanks for subscribing'."""
    subject = "You're in. First signal arrives Wednesday."
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0D1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:520px;margin:40px auto;padding:40px 32px;background:#161b22;border-radius:8px;border:1px solid rgba(230,237,243,0.08);">

  <p style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#F0B429;margin:0 0 24px;">The Weekly Signal</p>

  <h1 style="font-size:22px;font-weight:600;color:#E6EDF3;line-height:1.3;margin:0 0 16px;">
    You're confirmed.
  </h1>

  <p style="font-size:15px;color:#8b949e;line-height:1.65;margin:0 0 20px;">
    Every Wednesday you'll get one email &mdash; the actual data from the past week.
    Whoop recovery. Weight trend. Habit performance. What worked, what didn't.
    Written by an AI journalist with unfettered access to everything.
  </p>

  <p style="font-size:14px;color:#8b949e;line-height:1.65;margin:0 0 12px;border-left:3px solid #F0B429;padding-left:12px;">
    Each Wednesday: the week's real data, what worked, what didn't, and one honest verdict from the Board of Directors.
  </p>

  <p style="font-size:15px;color:#8b949e;line-height:1.65;margin:0 0 32px;">
    No filters. No "good news only." The bad weeks are in there too.
  </p>

  <a href="{SITE_URL}/story/"
     style="display:inline-block;background:#F0B429;color:#0D1117;font-size:15px;font-weight:600;
            padding:14px 28px;border-radius:8px;text-decoration:none;">
    Read the story &rarr;
  </a>

  <p style="font-size:13px;color:#484f58;margin:16px 0 0;">
    <a href="{SITE_URL}/chronicle/" style="color:#8b949e;text-decoration:none;">Browse the Chronicle archive &rarr;</a>
  </p>

  <p style="font-size:12px;color:#484f58;margin:28px 0 0;line-height:1.6;">
    Changed your mind?
    <a href="{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(email)}"
       style="color:#484f58;">Unsubscribe here.</a>
  </p>

</div>
</body>
</html>"""

    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [email]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
            }},
        )
        logger.info("welcome email sent")
    except Exception as exc:
        logger.error("_send_welcome_email failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# UNSUBSCRIBE
# ─────────────────────────────────────────────────────────────────────────────

def handle_unsubscribe(email: str) -> dict:
    """Mark status=unsubscribed. Raj directive: NEVER hard-delete. Row retained for analytics."""
    email      = email.strip().lower()
    email_hash = _email_hash(email)
    now_iso    = datetime.now(timezone.utc).isoformat()

    existing = _get_record(email_hash)
    if not existing:
        # Not found — return success silently (don't leak subscription status)
        return _redirect(f"{SITE_URL}/subscribe/confirm/?unsubscribed=true")

    if existing.get("status") == "unsubscribed":
        return _redirect(f"{SITE_URL}/subscribe/confirm/?unsubscribed=already")

    try:
        table.update_item(
            Key={"pk": SUBSCRIBERS_PK, "sk": f"EMAIL#{email_hash}"},
            UpdateExpression="SET #s = :s, unsubbed_at = :u, updated_at = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "unsubscribed", ":u": now_iso},
        )
    except Exception as exc:
        logger.error("unsubscribe: DDB update failed: %s", exc)
        return _redirect(f"{SITE_URL}/subscribe/confirm/?error=server_error")

    logger.info("unsubscribed: %s", email_hash[:8])
    return _redirect(f"{SITE_URL}/subscribe/confirm/?unsubscribed=true")


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()
    params = event.get("queryStringParameters") or {}
    action = params.get("action", "").lower()

    # CORS preflight
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": _cors_headers(), "body": ""}

    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp", "")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp", "")
    )

    if action == "confirm":
        token          = params.get("token", "")
        email_hash_pfx = params.get("h", "")
        return handle_confirm(token, email_hash_pfx)

    if action == "unsubscribe":
        email = params.get("email", "")
        if not email:
            return _redirect(f"{SITE_URL}/subscribe/confirm/?error=missing_email")
        return handle_unsubscribe(email)

    # Default: subscribe (POST body)
    if method == "POST":
        try:
            body  = json.loads(event.get("body") or "{}")
            email = body.get("email", "").strip()
        except Exception:
            return _json_response(400, {"error": "Invalid request body."})
        referrer = (event.get("headers") or {}).get("referer", "")
        return handle_subscribe(email, source_ip=source_ip, referrer=referrer)

    return _json_response(405, {"error": "Method not allowed."})
