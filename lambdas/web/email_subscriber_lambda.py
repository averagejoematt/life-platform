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
  source      subscribe_page | referral | ...  (see attribution note below)
  ip_hash     SHA256 of source IP (for abuse detection, non-identifying)

Attribution (#1621): three signals of DIFFERENT confidence are stored as SEPARATE
  attributes, never collapsed into one string, because "the UTM said reddit" and "the
  user typed Reddit" are not the same claim and the 60-day growth gate has to be able
  to tell them apart:
    attr_utm_source/_medium/_campaign  MEASURED — captured site-wide on landing by the
                                       browser attribution module, persisted in
                                       sessionStorage, posted with the form.
    attr_self_reported                 SELF-REPORTED — the free-text "how'd you find
                                       this?" field. A human's recollection.
    attr_referrer_host                 MEASURED, WEAK — HOST ONLY from the HTTP Referer
                                       header. Never the path, never the query string:
                                       a full Referer URL can carry PII and this
                                       partition's retention is unsigned. See
                                       `utm.referrer_host`.
  `source` remains populated for backward compatibility with every existing reader
  (the weekly digest's canary-excluding count, the newsletter send path, historical
  rows) and now carries the highest-confidence signal available, precedence
  UTM > free-text > referrer host > "subscribe_page". Existing rows are untouched.

Retention (#1350): unsub writes status=unsubscribed + unsubbed_at; this Lambda never
  deletes on unsubscribe. Whether/when an unsubscribed row is later purged or
  anonymized is an owner-signed decision — see the "Subscriber emails" row in
  docs/DATA_GOVERNANCE.md. Until that row is signed, rows are retained (today's de
  facto posture, now documented rather than an undocumented in-code directive). Once
  signed, `deploy/subscriber_retention_purge.py` enacts the chosen window/mode. A
  single subscriber can be deleted on request (right-to-be-forgotten, independent of
  the retention window) via `delete_user_data_lambda`'s `{"subscriber_email": "...",
  "confirm": "DELETE"}` event shape.

Routes (via API Gateway query param ?action=):
  POST ?action=subscribe   — create pending record, send confirmation email
  GET  ?action=confirm     — confirm email, send welcome
  GET  ?action=unsubscribe — mark unsubscribed (non-destructive)

Confirmation token: 32-byte random hex, stored in DDB, expires 48h.
Welcome email: Ava directive — warm, specific, on-brand.

v1.0.0 — 2026-03-16 (BS-03)
v1.1.0 — 2026-07-08 (#885): SEC-04 origin-header guard — 403 direct Function-URL
         requests when SITE_API_ORIGIN_SECRET is configured (CloudFront injects
         the X-AMJ-Origin header on the SubscriberLambdaOrigin origin).
"""

import hashlib
import hmac as _hmac
import json
import logging
import os
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import boto3

# #885: the SAME SITE_API_ORIGIN_SECRET constant site_api_lambda / site_api_ai_lambda
# enforce (SEC-04 / #815) — imported, not a second os.environ.get, so the env-var name
# can never drift between the three guarded Function URLs (the convention
# tests/test_function_url_origin_header_validation.py pins). Empty string when the
# env var is unset → guard disabled (fail-open), so Lambda code deployed before the
# CloudFront header / env var can't break subscriptions. Always importable: every
# deploy path ships the full-tree bundle (#781), so web/site_api_common.py is
# guaranteed present alongside this module.
from client_ip import extract_client_ip  # #1221 — the ONE edge-observed client-IP helper
from utm import (
    normalize as _utm_normalize,  # #1621 — shared with the outbound link tagger
    referrer_host as _referrer_host,
)

from web.site_api_common import SITE_API_ORIGIN_SECRET

try:
    from platform_logger import get_logger

    logger = get_logger("email-subscriber")
except ImportError:
    logger = logging.getLogger("email-subscriber")
    logger.setLevel(logging.INFO)

# AWS_REGION is set automatically by Lambda to the function's deployment region.
# email-subscriber deploys to us-east-1 (web_stack.py) but DDB is in us-west-2.
# DYNAMODB_REGION env var overrides to ensure cross-region DDB access.
REGION = os.environ.get("AWS_REGION", "us-east-1")  # Lambda's own region
DYNAMODB_REGION = os.environ.get("DYNAMODB_REGION", "us-west-2")  # DDB table region
SES_REGION = os.environ.get("SES_REGION", "us-west-2")  # SES verified identity region
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")

SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"

# #1621: the utm_* keys accepted off the subscribe POST body. A subset of utm.UTM_KEYS —
# content/term are ad-level detail this platform has no use for and no reason to retain.
UTM_BODY_KEYS = ("utm_source", "utm_medium", "utm_campaign")

dynamodb = boto3.resource("dynamodb", region_name=DYNAMODB_REGION)  # us-west-2
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=SES_REGION)  # us-west-2 (verified identity)


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
        "Access-Control-Allow-Origin": SITE_URL,
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
# RATE LIMIT (replaces WAF SubscribeRateLimit: 60 req / 5min / IP)
# ─────────────────────────────────────────────────────────────────────────────

_RATE_LIMIT_MAX = 60
_RATE_LIMIT_WINDOW_SEC = 300
_RATE_LIMIT_PK = "SUBSCRIBE#rate_limit"


def _check_subscribe_rate_limit(source_ip: str) -> tuple[bool, int]:
    """Per-IP rate-limit via DDB atomic counter on a 5-min time bucket.

    Mirrors the WAF rule it replaces (60 requests / 5min window / source IP).
    Fail-open on DDB errors — we'd rather accept a request than lock out a
    legitimate user on a transient hiccup.

    Returns (allowed, count_in_window).
    """
    if not source_ip or source_ip == "unknown":
        return True, 0

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    bucket = now_epoch // _RATE_LIMIT_WINDOW_SEC
    sk = f"IP#{ip_hash}#BUCKET#{bucket}"
    # TTL one hour past bucket end — long enough for DDB cleanup, short enough
    # to not waste storage. #951: the table's TTL is configured on attribute
    # `ttl` (mirrors rate_limiter.py, whose RATE# buckets ARE reaped) — this
    # wrote `expires_at` for months, so SUBSCRIBE#rate_limit rows accumulated
    # forever. deploy/fix_prologue_cycle_and_subscribe_ttl.py backfills the
    # stranded rows.
    ttl = (bucket * _RATE_LIMIT_WINDOW_SEC) + 3600

    try:
        result = table.update_item(
            Key={"pk": _RATE_LIMIT_PK, "sk": sk},
            UpdateExpression="ADD req_count :one SET #t = if_not_exists(#t, :ttl)",
            ExpressionAttributeNames={"#t": "ttl"},
            ExpressionAttributeValues={":one": 1, ":ttl": ttl},
            ReturnValues="UPDATED_NEW",
        )
        count = int(result.get("Attributes", {}).get("req_count", 1))
    except Exception as e:
        logger.warning(f"Subscribe rate-limit check failed (fail-open): {e}")
        return True, 0

    return (count <= _RATE_LIMIT_MAX), count


# ─────────────────────────────────────────────────────────────────────────────
# SUBSCRIBE
# ─────────────────────────────────────────────────────────────────────────────

_BLOCKED_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "test.org",
    "localhost",
    "invalid",
    "mailinator.com",
    "guerrillamail.com",
    "tempmail.com",
    "throwaway.email",
    "yopmail.com",
    "sharklasers.com",
    "guerrillamailblock.com",
    "grr.la",
    "dispostable.com",
}


def build_attribution(source: str = "", referrer: str = "", utm: dict | None = None) -> dict:
    """Resolve the three attribution signals into the attributes stored on the row.

    Returns a dict of ONLY the non-empty attributes to merge into the DDB item, plus
    the resolved `source` under the "source" key.

    Precedence for the backward-compatible `source` field is
    UTM > free-text > referrer host > "subscribe_page" — measured beats self-reported
    beats weak-measured beats nothing. The separate attr_* fields are always kept
    alongside so the collapse is never lossy.

    CANARY IS A HARD SHORT-CIRCUIT. The canary (`lambdas/operational/canary_lambda.py`)
    POSTs a synthetic subscriber every 4h with source='canary'; every count in the
    platform excludes it by `source <> 'canary'`. If a canary row ever picked up a UTM
    or referrer, `source` would resolve to that instead and the synthetic subscriber
    would silently enter the attribution numerator — corrupting the exact metric this
    story exists to produce. So canary short-circuits: source stays 'canary' and NO
    attribution attributes are written at all.
    """
    if source.strip() == "canary":
        return {"source": "canary"}

    utm = utm or {}
    attrs: dict = {}
    utm_source = _utm_normalize(utm.get("utm_source"))
    utm_medium = _utm_normalize(utm.get("utm_medium"))
    utm_campaign = _utm_normalize(utm.get("utm_campaign"))
    self_reported = source.strip()[:200]
    ref_host = _referrer_host(referrer)

    if utm_source:
        attrs["attr_utm_source"] = utm_source
    if utm_medium:
        attrs["attr_utm_medium"] = utm_medium
    if utm_campaign:
        attrs["attr_utm_campaign"] = utm_campaign
    if self_reported:
        attrs["attr_self_reported"] = self_reported
    if ref_host:
        attrs["attr_referrer_host"] = ref_host

    # The free-text field defaults to the literal 'subscribe-page' whenever the visitor
    # leaves it blank (the form sends `src || 'subscribe-page'`), so it is a real answer
    # only when it differs from that placeholder. Treating the placeholder as a
    # self-report is what made the old referrer fallback dead code.
    self_signal = self_reported if self_reported and self_reported != "subscribe-page" else ""
    attrs["source"] = utm_source or self_signal or ref_host or (self_reported or "subscribe_page")
    return attrs


def handle_subscribe(email: str, source_ip: str = "", referrer: str = "", source: str = "", utm: dict | None = None) -> dict:
    """Create/update pending record and send confirmation email.

    source='canary' skips the confirmation email (the canary POSTs a synthetic
    subscriber every 4h to verify the flow; we don't want SES to send a real
    email to canary+<ts>@mattsusername.com which then bounces and floods inbox).

    `utm` is the measured attribution captured site-wide on landing (#1621) — see
    `build_attribution`. It is optional: a client that doesn't send it (an older
    cached page) still subscribes normally, just with weaker attribution.
    """
    email = email.strip().lower()
    if not email or "@" not in email or len(email) > 254:
        return _json_response(400, {"error": "Invalid email address."})

    # Block fake/disposable domains to prevent SES bounces
    domain = email.rsplit("@", 1)[-1]
    if domain in _BLOCKED_DOMAINS:
        logger.info("subscribe: blocked disposable domain %s", domain)
        # Return success silently — don't reveal we blocked it
        return _json_response(200, {"status": "pending_confirmation", "message": "Check your inbox."})

    is_canary = source == "canary"

    email_hash = _email_hash(email)
    now_iso = datetime.now(timezone.utc).isoformat()

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
    token = secrets.token_hex(32)
    token_exp = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
    confirm_url = f"{SITE_URL}/api/subscribe?action=confirm&token={token}&h={email_hash[:16]}"

    # Write DDB record. `attribution` carries the resolved `source` plus the separate
    # attr_* signals (#1621) — see build_attribution for the precedence and the canary
    # short-circuit. Spread AFTER the literal fields so `source` resolves to the
    # attributed value rather than the old collapsed expression.
    attribution = build_attribution(source=source, referrer=referrer, utm=utm)
    item = {
        "pk": SUBSCRIBERS_PK,
        "sk": f"EMAIL#{email_hash}",
        "email": email,
        "email_hash": email_hash,
        "status": "pending_confirmation",
        "created_at": now_iso,
        "confirm_token": token,
        "token_expires": token_exp,
        "ip_hash": _ip_hash(source_ip),
        "updated_at": now_iso,
        **attribution,
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
    # Skipped for canary synthetic subscribers — see handle_subscribe docstring.
    if is_canary:
        logger.info("subscribe: canary synthetic — skipping confirmation email for %s", email_hash[:8])
    else:
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
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                }
            },
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
                ":t": token,
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
    email = record.get("email", "")

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


def _welcome_email_content(email: str) -> tuple[str, str]:
    """Build the welcome email (subject, plaintext body). Factored out of the
    sender so the copy + links can be verified offline without hitting SES.

    Links are v4 ("three doors": Story / Cockpit / Evidence) and lead with the
    first dispatch so a new subscriber can read the journey from the beginning
    (PG-03's "start from the beginning")."""
    subject = "You're in. Here's what you just signed up for."
    unsub_url = f"{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(email)}"
    body_text = f"""Hey —

You just subscribed to The Measured Life. Every Wednesday, you'll get a dispatch from the experiment: what the data showed, what I tried, what surprised me, and what I'm thinking about next.

This is a real experiment with real data. Not a highlight reel. The weeks the numbers go the wrong direction are in there too.

Right now, the site is brand new and the data is just starting to accumulate. That's on purpose — I wanted you to be able to see the whole journey from the beginning, not just the polished version.

A few things worth looking at while you're here:

-> Start from the beginning — the first dispatch: {SITE_URL}/story/chronicle/
-> The live cockpit (today's score, updated every morning): {SITE_URL}/cockpit/
-> The evidence (every number, every source): {SITE_URL}/data/
-> The Story (why I started): {SITE_URL}/story/

See you Wednesday.

— Matt

averagejoematt.com
Unsubscribe: {unsub_url}"""
    return subject, body_text


def _send_welcome_email(email: str) -> None:
    """Welcome email — direct dispatch from Matthew. Sets honest expectations
    and gives the subscriber one concrete thing to do right now."""
    subject, body_text = _welcome_email_content(email)

    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [email]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info("welcome email sent")
    except Exception as exc:
        logger.error("_send_welcome_email failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# UNSUBSCRIBE
# ─────────────────────────────────────────────────────────────────────────────


def handle_unsubscribe(email: str) -> dict:
    """Mark status=unsubscribed. Never deletes here — see the retention pointer in the
    module docstring (#1350: docs/DATA_GOVERNANCE.md "Subscriber emails" row)."""
    email = email.strip().lower()
    email_hash = _email_hash(email)
    now_iso = datetime.now(timezone.utc).isoformat()

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
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()
        params = event.get("queryStringParameters") or {}
        action = params.get("action", "").lower()

        # CORS preflight
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": _cors_headers(), "body": ""}

        # #885: SEC-04 origin-header guard (mirrors site_api_lambda / site_api_ai_lambda).
        # CloudFront injects X-AMJ-Origin on the SubscriberLambdaOrigin origin
        # (web_stack.py); requests that bypass CloudFront and hit the Function URL
        # directly lack it and are rejected. Fail-open when the secret is unset.
        if SITE_API_ORIGIN_SECRET:
            req_headers = event.get("headers") or {}
            incoming = req_headers.get("x-amj-origin") or req_headers.get("X-AMJ-Origin") or ""
            if not _hmac.compare_digest(incoming, SITE_API_ORIGIN_SECRET):
                return _json_response(403, {"error": "Forbidden"})

        # #1221: key the per-IP subscribe rate limit off the CloudFront edge-appended
        # (last) X-Forwarded-For hop, not the client-controllable leftmost entry — via
        # the ONE shared helper so this can never drift from the site-api handlers.
        source_ip = extract_client_ip(event)

        if action == "confirm":
            token = params.get("token", "")
            email_hash_pfx = params.get("h", "")
            return handle_confirm(token, email_hash_pfx)

        if action == "unsubscribe":
            email = params.get("email", "")
            if not email:
                return _redirect(f"{SITE_URL}/subscribe/confirm/?error=missing_email")
            return handle_unsubscribe(email)

        # Default: subscribe (POST body)
        if method == "POST":
            # Replaces WAF SubscribeRateLimit: 60 requests / 5min / IP.
            allowed, count = _check_subscribe_rate_limit(source_ip)
            if not allowed:
                logger.info(f"Subscribe rate-limit hit ip={source_ip[:8]}... count={count}")
                return _json_response(429, {"error": "Too many requests. Try again in a few minutes."})
            try:
                body = json.loads(event.get("body") or "{}")
                email = body.get("email", "").strip()
                source = body.get("source", "").strip()
                # #1621: measured attribution, captured site-wide on landing. Read
                # permissively — these are optional extra fields, so a client that
                # omits them (or an old cached page) still subscribes normally.
                utm = {k: body.get(k) for k in UTM_BODY_KEYS if isinstance(body.get(k), str)}
            except Exception:
                return _json_response(400, {"error": "Invalid request body."})
            referrer = (event.get("headers") or {}).get("referer", "")
            return handle_subscribe(email, source_ip=source_ip, referrer=referrer, source=source, utm=utm)

        return _json_response(405, {"error": "Method not allowed."})
    except Exception as e:
        logger.error(f"Handler failed: {e}")
        raise
