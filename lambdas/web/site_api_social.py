"""
lambdas/web/site_api_social.py — subscriber, experiment, challenge, and
nudge interaction handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 4, 2026-05-26).

Endpoints:
  /api/verify_subscriber  — email → 24hr HMAC token
  /api/sub_count          — public subscriber count
  /api/nudge              — track in-page nudge clicks
  /api/submit_finding     — reader-submitted experiment findings (S3)
  /api/experiment_library, /api/experiment_vote, /api/experiment_follow,
  /api/experiment_detail, /api/experiment_suggest
  /api/challenge_catalog, /api/challenges, /api/current_challenge,
  /api/challenge_vote, /api/challenge_follow, /api/challenge_checkin

Also owns the supporting machinery — subscriber-token HMAC (which uses
the Anthropic API key as the signing secret), per-IP rate-limit stores
for nudge/submit_finding, and the rate-limit EMF metric emitter — since
nothing outside this cluster uses them.
"""

import base64 as _b64
import copy
import hashlib
import hmac as _hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from common.client_ip import extract_client_ip  # #1221 — the ONE edge-observed client-IP helper
from content.social_signals import coach_route_of  # #1671 — training/mind coach-route classifier, reused read-side (#1674)
from experiment.phase_filter import with_phase_filter  # ADR-058
from ingestion.source_registry import SOURCE_REGISTRY  # #1679 — inbound channel live/dormant, read from the canonical registry
from privacy import social_provenance  # #1670 membrane — the origin:human predicate for the broadcast feed (#1672)

from web.site_api_common import (
    CORS_HEADERS,
    PT,
    S3_REGION,
    STATUS_CACHE_TTL,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _is_blocked_vice,
    _load_s3_json,
    _ok,
    config_cache_valid,
    logger,
    table,
)

# DynamoDB-backed rate limiting (survives warm-container distribution + cold
# starts). The site_api role already permits UpdateItem on the RATE#* partition
# (no IAM change needed).
#
# #2237: `_RATE_LIMITER_READY` must be read in EXACTLY ONE place — `_rate_check`
# below. Every public write door in this module calls that helper. Before #2237
# each door open-coded `if _RATE_LIMITER_READY:` for itself and five of the seven
# had no working fallback at all: `_handle_challenge_checkin`, `_handle_ritual_log`,
# `_handle_experiment_suggest` and `_handle_cohort_submit` had no `else` branch
# whatsoever, and `_handle_board_question`'s `else` set `allowed = True`
# unconditionally. A bundle missing `common/rate_limiter.py` therefore turned all
# five into unlimited anonymous write doors that still answered 200 — silently.
try:
    from common.rate_limiter import check_rate_limit as _ddb_rate_check

    _RATE_LIMITER_READY = True
except Exception:  # pragma: no cover — import guard
    _RATE_LIMITER_READY = False

# ── Module-owned globals ──────────────────────────────────
# These were originally module-level in site_api_lambda; they're only
# touched by the handlers in this file, so they move with the cluster.
_token_secret_cache = None

_nudge_counts: dict = {}  # ACCT-2: category -> approximate count
# S3 config caches for experiment + challenge endpoints
_challenges_cache = None
_challenges_cache_at = None  # #2019 — TTL stamp; None = pinned (test injection)
_challenge_catalog_cache = None

# R17-04: separate Anthropic key for site-api (distinct from main ai-keys).
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/site-api-ai-key")

# ── ACCT-2 / NEW-1 constants ──────────────────────────────
# Moved with their handlers in P1.1 Phase B step 7 (originally module-level
# in site_api_lambda.py — only _handle_nudge + _handle_submit_finding use them).
NUDGE_CATEGORIES = {"back_on_it", "watching", "take_your_time", "you_got_this"}
NUDGE_LABELS = {
    "back_on_it": "Get back on it 🔥",
    "watching": "We're watching 👀",
    "take_your_time": "Take your time ⏰",
    "you_got_this": "You've got this 💪",
}
FINDING_RATE_LIMIT = 3  # per IP per hour


def handle_current_challenge() -> dict:
    """
    GET /api/current_challenge
    Returns the current weekly challenge from S3 config.
    Manually updated each Monday via:
      aws s3 cp current_challenge.json s3://matthew-life-platform/site/config/current_challenge.json
    Cache: 3600s (1 hr) — changes once/week, no need for shorter TTL.
    """
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    S3_REGION = os.environ.get("S3_REGION", "us-west-2")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/current_challenge.json")
        data = json.loads(resp["Body"].read())
        return _ok({"current_challenge": data}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[site_api] current_challenge S3 fetch failed: {e}")
        # No active challenge → return null so the banner simply doesn't render. The old
        # "Check back soon" placeholder leaked to the UI as a fake day-0-of-7 challenge.
        return _ok({"current_challenge": None}, cache_seconds=60)


_SUBSCRIBER_TOKEN_SECRET_NAME = os.environ.get("SUBSCRIBER_TOKEN_SECRET_NAME", "life-platform/subscriber-token-secret")


def _get_token_secret() -> str:
    """Fetch the dedicated subscriber-token HMAC secret from Secrets Manager.

    #106 (2026-05-30): migrated off `sha256("subscriber-token-v1:" + anthropic_api_key)`
    onto a dedicated 256-bit random key in Secrets Manager. Reasons:
      (1) AI-key rotation no longer invalidates every subscriber token.
      (2) AI-key compromise no longer enables token forgery.

    The pre-#106 fallback (derived from the Anthropic API key) was removed
    2026-06-12 — its 24h migration window expired 2026-05-31, and a loud
    failure beats silently signing with a derivable key.
    """
    global _token_secret_cache
    if _token_secret_cache:
        return _token_secret_cache
    try:
        sm = boto3.client("secretsmanager", region_name="us-west-2")
        _token_secret_cache = sm.get_secret_value(SecretId=_SUBSCRIBER_TOKEN_SECRET_NAME)["SecretString"]
        return _token_secret_cache
    except Exception as e:
        logger.error(f"[token_secret] Signing secret unavailable: {e}")
        raise RuntimeError("Token signing secret unavailable") from e


def _generate_subscriber_token(email: str) -> str:
    """Generate a 24hr HMAC token for a confirmed subscriber."""
    import time as _time

    expires = int(_time.time()) + 86400
    payload = f"{email.lower()}:{expires}"
    secret = _get_token_secret().encode()
    sig = _hmac.new(secret, payload.encode(), digestmod="sha256").hexdigest()[:32]
    return _b64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


# _validate_subscriber_token removed 2026-05-25 (P1.1): the live token validator
# now lives in lambdas/site_api_ai_lambda.py (ADR-036 split). This file's copy
# was only reachable from the dead inline /api/ask block in lambda_handler,
# which CloudFront routes to the AI Lambda instead.


def _is_confirmed_subscriber(email: str) -> bool:
    """Check DDB: USER#matthew#SOURCE#subscribers / EMAIL#{sha256} / status=confirmed"""
    import hashlib as _h

    email_hash = _h.sha256(email.strip().lower().encode()).hexdigest()
    try:
        resp = table.get_item(
            Key={
                "pk": f"USER#{USER_ID}#SOURCE#subscribers",
                "sk": f"EMAIL#{email_hash}",
            }
        )
        item = _decimal_to_float(resp.get("Item") or {})
        return item.get("status") == "confirmed"
    except Exception as e:
        logger.warning(f"[verify_subscriber] DDB lookup failed: {e}")
        return False


# #2239 — per-IP budget for /api/verify_subscriber. Generous against the ONE
# legitimate shape (a reader types their address once and the token then lives 24h
# in sessionStorage), tight against enumeration: 10/hr turns "probe the roster at
# line speed" into ~240 addresses/day/IP instead of unbounded. Sibling capture
# doors in this module sit at 1-5 per IP per window.
VERIFY_SUBSCRIBER_RATE_LIMIT = 10
VERIFY_SUBSCRIBER_RATE_WINDOW = 3600


def _handle_verify_subscriber(event: dict) -> dict:
    """
    GET /api/verify_subscriber?email=...
    Returns a 24hr token if the email is a confirmed subscriber.
    Frontend stores token in sessionStorage and sends as X-Subscriber-Token header
    to unlock 20 questions/hr instead of the default 5.

    #2239 — this door is a MEMBERSHIP ORACLE over the subscriber roster, and that
    is accepted, not overlooked. Recorded here so it is not "fixed" cosmetically
    later:

      * The endpoint's entire purpose is to hand back a credential IF AND ONLY IF
        the caller-supplied address is on the confirmed list. Any response that
        carries the token is therefore a perfect oracle regardless of its status
        code — uniforming 200/404 would only move the signal from `resp.status` to
        `"token" in body`, which the sole client already branches on. That is
        obfuscation, not a fix, and it would leave the leak while retiring the
        test that names it.
      * The only way to actually close it is to stop answering synchronously —
        mail the token to the address instead, so issuance requires proof of
        control. That is a product change (a new email door + a claim flow), out
        of scope here; see the PR for #2239.
      * So the mitigation is COST: the oracle is metered per IP, and both answers
        are metered by the SAME counter, before either reaches DynamoDB. Probing
        the roster is no longer free or unbounded.

    The limiter is deliberately fail-CLOSED: when DynamoDB is unreachable
    `_is_confirmed_subscriber` already returns False and the door answers 404 for
    everyone, so there is no legitimate flow to protect during an outage — only an
    unmetered enumeration window to close.
    """
    params = event.get("queryStringParameters") or {}
    email = (params.get("email") or "").strip().lower()

    if not email or "@" not in email or len(email) > 254:
        # Rejected BEFORE the rate check on purpose: a malformed address costs no
        # DynamoDB operation (not even the limiter's UpdateItem) and can answer no
        # membership question, so metering it would only spend writes on garbage.
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Valid email required"}),
        }

    # Metered through the module chokepoint (#2237) like every other public door.
    # Keyed on the IP alone — NOT on the address — or each new probe address would
    # get its own fresh budget and enumeration would stay free.
    ip_hash = hashlib.sha256(extract_client_ip(event).encode()).hexdigest()[:16]
    allowed, _rem, retry_after = _rate_check(
        "verify_subscriber",
        ip_hash,
        limit=VERIFY_SUBSCRIBER_RATE_LIMIT,
        window_seconds=VERIFY_SUBSCRIBER_RATE_WINDOW,
        fail_open=False,
    )
    if not allowed:
        _emit_rate_limit_metric("verify_subscriber")
        return {
            "statusCode": 429,
            "headers": {
                **CORS_HEADERS,
                "Retry-After": str(retry_after or VERIFY_SUBSCRIBER_RATE_WINDOW),
                "Cache-Control": "no-store",
            },
            "body": json.dumps({"error": "Too many verification attempts. Try again in a little while."}),
        }

    if not _is_confirmed_subscriber(email):
        return {
            "statusCode": 404,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Email not found. Subscribe at /subscribe/ to unlock more questions!"}),
        }

    token = _generate_subscriber_token(email)
    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps(
            {
                "token": token,
                "message": "Verified! You now have 20 questions per hour.",
                "limit": 20,
            }
        ),
    }


def handle_subscriber_count() -> dict:
    """
    GET /api/subscriber_count
    Returns count of confirmed subscribers (read-only query).
    Used by homepage and subscribe page for social proof.
    """
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#subscribers"),
            Select="COUNT",
            FilterExpression="attribute_exists(#s) AND #s = :confirmed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":confirmed": "confirmed"},
        )
        count = resp.get("Count", 0)
    except Exception as e:
        logger.warning(f"[subscriber_count] DDB query failed: {e}")
        count = 0
    return _ok({"count": count}, cache_seconds=600)


# ── #2237: the ONE rate-limit chokepoint for this module ─────────────────────
# Keyed "endpoint|ip_hash" -> newest timestamps inside the window. One store for
# every door, so a new write door cannot ship with its own (or no) fallback.
_FALLBACK_RATE_STORE: dict = {}
_FALLBACK_STORE_MAX_KEYS = 4096  # bounded — see _memory_rate_check's fail-closed branch


def _memory_rate_check(endpoint: str, ip_hash: str, limit: int, window_seconds: int) -> tuple:
    """Per-container sliding-window limiter, used ONLY when `common.rate_limiter`
    failed to import at module load.

    This is the degraded mode CLAUDE.md documents ("an in-memory dict is the
    fail-open fallback only"), previously open-coded at two of the seven doors and
    absent from the other five. Degraded, not absent: the window is per warm
    container rather than per fleet, so the effective ceiling becomes
    `limit x live containers` instead of `limit`. That is bounded and small.
    Skipping the check outright — the shipped behaviour #2237 found — was not
    bounded by anything.

    FAIL CLOSED at capacity. If the store already holds `_FALLBACK_STORE_MAX_KEYS`
    distinct (endpoint, ip) windows after pruning the expired ones, the write is
    REFUSED rather than admitted. The distributed flood is exactly the case an
    unbounded in-memory limiter cannot police, so it ends in 429s here instead of
    an unmetered write path plus an ever-growing dict in a 20-concurrency Lambda.

    Returns the shared limiter's (allowed, remaining, retry_after) triple.
    """
    now = int(time.time())
    key = f"{endpoint}|{ip_hash}"
    recent = [t for t in _FALLBACK_RATE_STORE.get(key, []) if t > now - window_seconds]

    if not recent and len(_FALLBACK_RATE_STORE) >= _FALLBACK_STORE_MAX_KEYS:
        for stale in [k for k, ts in _FALLBACK_RATE_STORE.items() if not any(t > now - window_seconds for t in ts)]:
            _FALLBACK_RATE_STORE.pop(stale, None)
        if len(_FALLBACK_RATE_STORE) >= _FALLBACK_STORE_MAX_KEYS:
            logger.warning(f"[rate_limit] in-memory fallback at capacity — refusing {endpoint} (fail closed)")
            return False, 0, window_seconds

    if len(recent) >= limit:
        _FALLBACK_RATE_STORE[key] = recent[-limit:]
        return False, 0, window_seconds

    recent.append(now)
    _FALLBACK_RATE_STORE[key] = recent[-max(limit, 1) :]
    return True, max(0, limit - len(recent)), window_seconds


def _rate_check(endpoint: str, ip_hash: str, limit: int, window_seconds: int, fail_open: bool = True) -> tuple:
    """The single door every rate-limited write in this module passes through.

    Uses the shared DynamoDB limiter when it is available and the bounded
    in-memory fallback when it is not — but NEVER returns "allowed" without having
    applied a limit. `_RATE_LIMITER_READY` is read here and nowhere else, which is
    what `tests/test_site_api_social_behavior.py` pins: a future write door that
    forgets its fallback is not expressible, because there is only one fallback.
    """
    if _RATE_LIMITER_READY:
        return _ddb_rate_check(table, endpoint=endpoint, ip_hash=ip_hash, limit=limit, window_seconds=window_seconds, fail_open=fail_open)
    return _memory_rate_check(endpoint, ip_hash, limit, window_seconds)


def _emit_rate_limit_metric(endpoint: str) -> None:
    """OBS-03: EMF metric emitted when a rate limit is hit. Zero-config via stdout."""
    import json as _json
    import time as _t

    try:
        emf = {
            "_aws": {
                "Timestamp": int(_t.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "LifePlatform/SiteApi",
                        "Dimensions": [["Endpoint"]],
                        "Metrics": [{"Name": "RateLimitHit", "Unit": "Count"}],
                    }
                ],
            },
            "Endpoint": endpoint,
            "RateLimitHit": 1,
        }
        # sys.stdout.write so CloudWatch EMF parser sees pure JSON without
        # the logger formatter prefix; same reason as site_api_common.py.
        import sys

        sys.stdout.write(_json.dumps(emf) + "\n")
    except Exception:
        pass


def _handle_nudge(event: dict) -> dict:
    """
    POST /api/nudge
    Body: {"category": "back_on_it" | "watching" | "take_your_time" | "you_got_this"}
    Rate limit: 1 nudge per category per IP per hour — DynamoDB-backed (survives
    cold starts / warm-container spread; in-memory fallback only).
    NOTE: the per-category display *counts* are still approximate/in-memory — a
    durable counts schema remains future work, separate from this rate limit.
    """
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    category = (body.get("category") or "").strip().lower()
    if category not in NUDGE_CATEGORIES:
        return _error(400, f"Invalid category. Must be one of: {sorted(NUDGE_CATEGORIES)}")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    # Rate limit: 1 per IP per category per hour. Per-category endpoint key so a
    # nudge in one category doesn't consume another's budget.
    allowed, _rem, _retry = _rate_check(f"nudge:{category}", ip_hash, limit=1, window_seconds=3600)
    if not allowed:
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600", "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Already sent this reaction recently. Come back later.", "category": category}),
        }

    # Increment in-memory count
    _nudge_counts[category] = _nudge_counts.get(category, 0) + 1
    logger.info(f"[nudge] category={category} ip_hash={ip_hash} total_this_session={_nudge_counts[category]}")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps(
            {
                "success": True,
                "category": category,
                "label": NUDGE_LABELS[category],
                "message": "Reaction sent. Matthew will see this in his daily brief.",
            }
        ),
    }


def _handle_submit_finding(event: dict) -> dict:
    """
    POST /api/submit_finding
    Body: {"metric_a": str, "metric_b": str, "finding": str, "email": str (optional)}
    Stores visitor-discovered correlation findings in S3 for Matthew's review.
    Rate limit: 3 per IP per hour.
    """
    source_ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]

    # Rate limit: FINDING_RATE_LIMIT per IP per hour — DynamoDB-backed (survives
    # cold starts; bounded in-memory fallback only, #2237).
    allowed, remaining, _retry = _rate_check("submit_finding", ip_hash, limit=FINDING_RATE_LIMIT, window_seconds=3600)
    if not allowed:
        _emit_rate_limit_metric("submit_finding")
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600"},
            "body": json.dumps({"error": "Rate limit reached. 3 submissions per hour."}),
        }

    # Parse body
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON")

    metric_a = re.sub(r"<[^>]+>", "", (body.get("metric_a") or "").strip())[:100]
    metric_b = re.sub(r"<[^>]+>", "", (body.get("metric_b") or "").strip())[:100]
    finding = re.sub(r"<[^>]+>", "", (body.get("finding") or "").strip())[:500]
    email = re.sub(r"<[^>]+>", "", (body.get("email") or "").strip())[:254]

    if not metric_a or not metric_b:
        return _error(400, "Both metric_a and metric_b are required.")
    if not finding or len(finding) < 10:
        return _error(400, "Finding description must be at least 10 characters.")
    if email and "@" not in email:
        return _error(400, "Invalid email format.")

    # Build finding record
    timestamp = datetime.now(timezone.utc).isoformat()
    # Content-based id (no timestamp): a same-day network retry of the identical
    # submission overwrites the same S3 object instead of creating a duplicate
    # pending finding for Matt to triage.
    finding_id = hashlib.sha256(f"{ip_hash}:{metric_a}:{metric_b}:{finding}".encode()).hexdigest()[:12]
    record = {
        "id": finding_id,
        "metric_a": metric_a,
        "metric_b": metric_b,
        "finding": finding,
        "email": email if email else None,
        "submitted_at": timestamp,
        "ip_hash": ip_hash,
        "status": "pending",
    }

    # Write to S3
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    s3_key = f"generated/findings/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{finding_id}.json"
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(record, indent=2),
            ContentType="application/json",
        )
        logger.info(f"[submit_finding] Stored: {s3_key} metric_a={metric_a} metric_b={metric_b}")
    except Exception as e:
        logger.error(f"[submit_finding] S3 write failed: {e}")
        return _error(503, "Unable to store finding. Try again later.")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps(
            {
                "success": True,
                "finding_id": finding_id,
                "message": "Finding submitted! Matthew will review it and may promote it to a Discovery or seed an Experiment.",
                "remaining": remaining,
            }
        ),
    }


def handle_experiment_library() -> dict:
    """
    GET /api/experiment_library
    Returns the full experiment library from S3 config, merged with:
      - Vote counts from DynamoDB
      - Status from active/completed experiments (matched by library_id or name slug)
    Cache: 900s (15 min).
    """
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"[experiment_library] S3 read failed: {e}")
        return _error(503, "Experiment library not available")

    # ── Load vote counts from DynamoDB ──
    vote_counts = {}
    try:
        vote_pk = "VOTES#experiment_library"
        vote_resp = table.query(
            KeyConditionExpression=Key("pk").eq(vote_pk),
            ProjectionExpression="sk, vote_count",
        )
        for item in _decimal_to_float(vote_resp.get("Items", [])):
            lib_id = item.get("sk", "").replace("LIB#", "")
            vote_counts[lib_id] = int(item.get("vote_count", 0))
    except Exception as e:
        logger.warning(f"[experiment_library] Vote query failed (non-fatal): {e}")

    # ── Load active/completed experiments to merge status ──
    exp_status_map = {}
    try:
        exp_pk = f"{USER_PREFIX}experiments"
        exp_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot experiments
                    "KeyConditionExpression": Key("pk").eq(exp_pk),
                    "ScanIndexForward": False,
                    "Limit": 100,
                }
            )
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            exp_id = item.get("sk", "").replace("EXP#", "")
            # #2240: the live overlay is a second door into this public payload —
            # screen the record's name AND id the same way the challenge routes do
            # before any of it can key or colour a published library entry.
            if _is_blocked_vice(item.get("name", "")) or _is_blocked_vice(exp_id):
                continue
            lib_id = item.get("library_id")
            status = item.get("status", "unknown")
            start = item.get("start_date", "")
            days_in = None
            if status == "active" and start:
                try:
                    days_in = (datetime.now(PT).replace(tzinfo=None) - datetime.strptime(start, "%Y-%m-%d")).days + 1
                except Exception:
                    pass

            entry = {
                "status": status,
                "experiment_id": exp_id,
                "days_in": days_in,
                "start_date": start,
                "outcome": item.get("outcome"),
                "grade": item.get("grade"),
                "hypothesis_confirmed": item.get("hypothesis_confirmed"),
            }
            if lib_id:
                exp_status_map[lib_id] = entry
            name_slug = re.sub(r"[^a-z0-9]+", "-", item.get("name", "").lower()).strip("-")[:40]
            if name_slug:
                exp_status_map.setdefault(name_slug, entry)
    except Exception as e:
        logger.warning(f"[experiment_library] Experiment query failed (non-fatal): {e}")

    # ── Merge votes + experiment status into library entries ──
    # #2240: screen the catalog entries (name AND id — a keyword often lives only in
    # the id while the display name is benign, ER-06) before anything downstream can
    # count, group or publish them. total_experiments/total_votes are computed from
    # the screened list, so a blocked entry is not even visible as a count.
    experiments = [
        e for e in library.get("experiments", []) if not (_is_blocked_vice(e.get("name", "")) or _is_blocked_vice(e.get("id", "")))
    ]
    pillar_map = {}
    pillar_meta = library.get("pillars", {})
    pillar_order = library.get("pillar_order", list(pillar_meta.keys()))

    total_votes = 0
    for exp in experiments:
        lib_id = exp.get("id", "")
        exp["votes"] = vote_counts.get(lib_id, exp.get("votes", 0))
        total_votes += exp["votes"]

        matched = exp_status_map.get(lib_id)
        if matched:
            exp["status"] = matched["status"]
            exp["active_experiment_id"] = matched["experiment_id"]
            exp["days_in"] = matched.get("days_in")

        pillar_id = exp.get("pillar", "other")
        if pillar_id not in pillar_map:
            meta = pillar_meta.get(pillar_id, {})
            pillar_map[pillar_id] = {
                "id": pillar_id,
                "label": meta.get("label", pillar_id.title()),
                "icon": meta.get("icon", "circle"),
                "color": meta.get("color"),
                "experiments": [],
                "stats": {"total": 0, "active": 0, "completed": 0, "backlog": 0},
            }
        group = pillar_map[pillar_id]
        group["experiments"].append(exp)
        group["stats"]["total"] += 1
        s = exp.get("status", "backlog")
        if s == "active":
            group["stats"]["active"] += 1
        elif s in ("completed", "partial", "failed"):
            group["stats"]["completed"] += 1
        else:
            group["stats"]["backlog"] += 1

    pillars = []
    for pid in pillar_order:
        if pid in pillar_map:
            group = pillar_map[pid]
            group["experiments"].sort(key=lambda e: (0 if e.get("status") == "active" else 1, -(e.get("votes") or 0)))
            pillars.append(group)
    for pid, group in pillar_map.items():
        if pid not in pillar_order:
            pillars.append(group)

    return _ok(
        {
            "pillars": pillars,
            "total_experiments": len(experiments),
            "total_votes": total_votes,
            "version": library.get("version", "1.0.0"),
        },
        cache_seconds=900,
    )


_library_ids_cache: tuple = (0.0, frozenset())  # (loaded_at_epoch, ids)


def _valid_library_ids() -> frozenset:
    """Experiment ids from the S3 library, cached 15 min. Votes are validated
    against this set so arbitrary library_ids can't mint unbounded DDB records."""
    global _library_ids_cache
    import time as _time

    loaded_at, ids = _library_ids_cache
    if ids and _time.time() - loaded_at < 900:
        return ids
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
        resp = s3_client.get_object(Bucket=bucket, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
        # #2240: a screened-out entry is not votable either — the vote allowlist is
        # derived from the same catalog and must not readmit what the read doors drop.
        ids = frozenset(
            (e.get("id") or "").lower()
            for e in library.get("experiments", [])
            if e.get("id") and not (_is_blocked_vice(e.get("name", "")) or _is_blocked_vice(e.get("id", "")))
        )
        _library_ids_cache = (_time.time(), ids)
    except Exception as e:
        logger.warning(f"[experiment_vote] Library allowlist load failed: {e}")
        # Keep serving a stale allowlist if we ever had one; empty set → 503 upstream.
    return _library_ids_cache[1]


def _handle_experiment_vote(event: dict) -> dict:
    """
    POST /api/experiment_vote
    Body: {"library_id": "post-dinner-walk"}
    Rate limit: 1 vote per IP per experiment per 24 hours via DynamoDB TTL.
    library_id must exist in the experiment library (anti-pollution, 2026-06-12).
    """
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    library_id = (body.get("library_id") or "").strip().lower()
    if not library_id or len(library_id) > 80:
        return _error(400, "library_id is required (max 80 chars)")
    valid_ids = _valid_library_ids()
    if not valid_ids:
        return _error(503, "Experiment library unavailable — try again shortly")
    if library_id not in valid_ids:
        return _error(400, "Unknown experiment")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"IP#{ip_hash}#LIB#{library_id}"
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    ttl_24h = now_epoch + 86400

    try:
        table.put_item(
            Item={
                "pk": rate_pk,
                "sk": rate_sk,
                "voted_at": now_epoch,
                "ttl": ttl_24h,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Already voted for this experiment in the last 24 hours"}),
            }
        logger.error(f"[experiment_vote] Rate limit check failed: {e}")
        return _error(500, "Vote rate limit check failed")

    vote_pk = "VOTES#experiment_library"
    vote_sk = f"LIB#{library_id}"
    try:
        result = table.update_item(
            Key={"pk": vote_pk, "sk": vote_sk},
            UpdateExpression="ADD vote_count :one SET library_id = :lid, last_voted = :ts",
            ExpressionAttributeValues={
                ":one": 1,
                ":lid": library_id,
                ":ts": now_epoch,
            },
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(result.get("Attributes", {}).get("vote_count", 1))
    except Exception as e:
        logger.error(f"[experiment_vote] Vote increment failed: {e}")
        return _error(500, "Failed to record vote")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps(
            {
                "library_id": library_id,
                "new_count": new_count,
            }
        ),
    }


def _handle_experiment_follow(event: dict) -> dict:
    """
    POST /api/experiment_follow
    Body: {"email": "user@example.com", "library_id": "post-dinner-walk"}
    Stores interest so we can notify when experiment completes.
    Rate limit: 10 follows per IP per hour.
    """
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    email = (body.get("email") or "").strip().lower()
    library_id = (body.get("library_id") or "").strip().lower()

    if not email or "@" not in email or len(email) > 200:
        return _error(400, "Valid email is required")
    if not library_id or len(library_id) > 80:
        return _error(400, "library_id is required")

    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    # Rate limit: 10 follows per IP per hour
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"FOLLOW#{ip_hash}#{now_epoch // 3600}"
    try:
        result = table.update_item(
            Key={"pk": rate_pk, "sk": rate_sk},
            UpdateExpression="ADD follow_count :one SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":ttl": now_epoch + 7200,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(result.get("Attributes", {}).get("follow_count", 1))
        if count >= 10:
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Too many follow requests. Try again later."}),
            }
    except Exception as e:
        logger.error(f"[experiment_follow] Rate limit check failed: {e}")
        return _error(500, "Follow rate limit check failed")

    # Store the follow interest
    follow_pk = "EXPERIMENT_FOLLOWS"
    follow_sk = f"EMAIL#{email_hash}#EXP#{library_id}"
    try:
        table.put_item(
            Item={
                "pk": follow_pk,
                "sk": follow_sk,
                "email": email,
                "library_id": library_id,
                "followed_at": now_epoch,
                "notified": False,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"already_following": True, "library_id": library_id}),
            }
        logger.error(f"[experiment_follow] DDB put failed: {e}")
        return _error(500, "Failed to save follow")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"followed": True, "library_id": library_id}),
    }


def _handle_experiment_detail(event: dict) -> dict:
    """
    GET /api/experiment_detail?id=post-dinner-walk
    Returns full detail for a single experiment from the library,
    merged with any active/completed DynamoDB experiment data + votes + followers.
    Cache: 900s.
    """
    params = event.get("queryStringParameters") or {}
    lib_id = (params.get("id") or "").strip().lower()
    if not lib_id:
        return _error(400, "id query parameter is required")

    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"[experiment_detail] S3 read failed: {e}")
        return _error(503, "Experiment library not available")

    lib_exp = None
    for exp in library.get("experiments", []):
        if exp.get("id") == lib_id:
            lib_exp = exp
            break
    # #2240: a screened entry is indistinguishable from an absent one — same 404,
    # same message, so the response can't confirm the entry exists.
    if lib_exp and (_is_blocked_vice(lib_exp.get("name", "")) or _is_blocked_vice(lib_exp.get("id", ""))):
        return _error(404, f"Experiment '{lib_id}' not found in library")
    if not lib_exp:
        return _error(404, f"Experiment '{lib_id}' not found in library")

    pillar_meta = library.get("pillars", {}).get(lib_exp.get("pillar", ""), {})
    lib_exp["pillar_label"] = pillar_meta.get("label", lib_exp.get("pillar", "").title())
    lib_exp["pillar_icon"] = pillar_meta.get("icon", "circle")

    # Vote count
    try:
        vote_resp = table.get_item(Key={"pk": "VOTES#experiment_library", "sk": f"LIB#{lib_id}"})
        vote_item = _decimal_to_float(vote_resp.get("Item"))
        lib_exp["votes"] = int(vote_item.get("vote_count", 0)) if vote_item else 0
    except Exception:
        lib_exp["votes"] = 0

    # Follower count
    try:
        follow_resp = table.query(
            KeyConditionExpression=Key("pk").eq("EXPERIMENT_FOLLOWS"),
            FilterExpression="library_id = :lid",
            ExpressionAttributeValues={":lid": lib_id},
            Select="COUNT",
        )
        lib_exp["follower_count"] = follow_resp.get("Count", 0)
    except Exception:
        lib_exp["follower_count"] = 0

    # Past runs from DynamoDB
    runs = []
    try:
        exp_pk = f"{USER_PREFIX}experiments"
        exp_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot experiments
                    "KeyConditionExpression": Key("pk").eq(exp_pk),
                    "ScanIndexForward": False,
                    "Limit": 100,
                }
            )
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            item_lib_id = item.get("library_id", "")
            # #2240: the run overlay is the second door into this payload — screen the
            # live record's name AND its experiment id before it joins `runs`.
            if _is_blocked_vice(item.get("name", "")) or _is_blocked_vice(item.get("sk", "").replace("EXP#", "")):
                continue
            name_slug = re.sub(r"[^a-z0-9]+", "-", item.get("name", "").lower()).strip("-")[:40]
            if item_lib_id == lib_id or name_slug == lib_id:
                start = item.get("start_date", "")
                end = item.get("end_date")
                status = item.get("status", "unknown")
                days = None
                try:
                    end_d = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now(timezone.utc).replace(tzinfo=None)
                    days = max(0, (end_d - datetime.strptime(start, "%Y-%m-%d")).days)
                except Exception:
                    pass
                runs.append(
                    {
                        "experiment_id": item.get("sk", "").replace("EXP#", ""),
                        "status": status,
                        "start_date": start,
                        "end_date": end,
                        "days": days,
                        "hypothesis": item.get("hypothesis"),
                        "outcome": item.get("outcome") or item.get("result_summary"),
                        "primary_metric": item.get("primary_metric"),
                        "baseline_value": item.get("baseline_value"),
                        "result_value": item.get("result_value"),
                        "grade": item.get("grade"),
                        "compliance_pct": item.get("compliance_pct"),
                        "reflection": item.get("reflection"),
                        "mechanism": item.get("mechanism"),
                        "key_finding": item.get("key_finding"),
                        "hypothesis_confirmed": item.get("hypothesis_confirmed"),
                        "iteration": item.get("iteration", 1),
                    }
                )
    except Exception as e:
        logger.warning(f"[experiment_detail] Experiment query failed: {e}")

    lib_exp["runs"] = runs
    lib_exp["total_runs"] = len(runs)
    lib_exp["active_run"] = next((r for r in runs if r["status"] == "active"), None)
    lib_exp["completed_runs_count"] = sum(1 for r in runs if r["status"] == "completed")

    return _ok(lib_exp, cache_seconds=900)


def _public_challenge_ids() -> set | None:
    """Catalog ids a visitor may legitimately vote on — public challenges only
    (excludes public:false vice entries). Returns None when the catalog can't be
    loaded so callers fail *closed* (503) rather than accepting arbitrary ids.
    Shares handle_challenge_catalog's module cache."""
    global _challenge_catalog_cache
    if _challenge_catalog_cache is None:
        _challenge_catalog_cache = _load_s3_json("site/config/challenges_catalog.json", "challenge_catalog")
    cat = _challenge_catalog_cache
    if not cat or not cat.get("challenges"):
        return None
    return {
        (ch.get("id") or "").strip().lower() for ch in cat.get("challenges", []) if ch.get("public", True) is not False and ch.get("id")
    }


def _handle_challenge_vote(event: dict) -> dict:
    """POST /api/challenge_vote — Rate-limited vote for challenge catalog entries.
    Body: {"catalog_id": "cold-shower-finish"}
    Rate limit: 1 vote per IP per challenge per 24 hours via DynamoDB TTL.
    """
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    catalog_id = (body.get("catalog_id") or "").strip().lower()
    if not catalog_id or len(catalog_id) > 80:
        return _error(400, "catalog_id is required (max 80 chars)")

    # Reject votes for ids that aren't real public challenges — without this an
    # attacker can mint arbitrary VOTES#challenges/CH#<anything> rows.
    valid_ids = _public_challenge_ids()
    if valid_ids is None:
        return _error(503, "Challenge catalog unavailable — try again shortly")
    if catalog_id not in valid_ids:
        return _error(404, "Unknown challenge")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"IP#{ip_hash}#CH#{catalog_id}"
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    ttl_24h = now_epoch + 86400

    try:
        table.put_item(
            Item={
                "pk": rate_pk,
                "sk": rate_sk,
                "voted_at": now_epoch,
                "ttl": ttl_24h,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Already voted for this challenge in the last 24 hours"}),
            }
        logger.error(f"[challenge_vote] Rate limit check failed: {e}")
        return _error(500, "Vote rate limit check failed")

    vote_pk = "VOTES#challenges"
    vote_sk = f"CH#{catalog_id}"
    try:
        result = table.update_item(
            Key={"pk": vote_pk, "sk": vote_sk},
            UpdateExpression="ADD vote_count :one SET catalog_id = :cid, last_voted = :ts",
            ExpressionAttributeValues={
                ":one": 1,
                ":cid": catalog_id,
                ":ts": now_epoch,
            },
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(result.get("Attributes", {}).get("vote_count", 1))
    except Exception as e:
        logger.error(f"[challenge_vote] Vote increment failed: {e}")
        return _error(500, "Failed to record vote")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps(
            {
                "catalog_id": catalog_id,
                "new_count": new_count,
            }
        ),
    }


def _handle_challenge_follow(event: dict) -> dict:
    """POST /api/challenge_follow — Email follow for challenge catalog entries.
    Body: {"email": "user@example.com", "catalog_id": "cold-shower-finish"}
    Rate limit: 10 follows per IP per hour.
    """
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    email = (body.get("email") or "").strip().lower()
    catalog_id = (body.get("catalog_id") or "").strip().lower()

    if not email or "@" not in email or len(email) > 200:
        return _error(400, "Valid email is required")
    if not catalog_id or len(catalog_id) > 80:
        return _error(400, "catalog_id is required")

    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    # Rate limit: 10 follows per IP per hour
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"CHFOLLOW#{ip_hash}#{now_epoch // 3600}"
    try:
        result = table.update_item(
            Key={"pk": rate_pk, "sk": rate_sk},
            UpdateExpression="ADD follow_count :one SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":ttl": now_epoch + 7200,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(result.get("Attributes", {}).get("follow_count", 1))
        if count >= 10:
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Too many follow requests. Try again later."}),
            }
    except Exception as e:
        logger.error(f"[challenge_follow] Rate limit check failed: {e}")
        return _error(500, "Follow rate limit check failed")

    # Store the follow interest
    follow_pk = "CHALLENGE_FOLLOWS"
    follow_sk = f"EMAIL#{email_hash}#CH#{catalog_id}"
    try:
        table.put_item(
            Item={
                "pk": follow_pk,
                "sk": follow_sk,
                "email": email,
                "catalog_id": catalog_id,
                "followed_at": now_epoch,
                "notified": False,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"already_following": True, "catalog_id": catalog_id}),
            }
        logger.error(f"[challenge_follow] DDB put failed: {e}")
        return _error(500, "Failed to save follow")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"followed": True, "catalog_id": catalog_id}),
    }


def handle_challenge_catalog() -> dict:
    """GET /api/challenge_catalog — Challenge catalog from S3 with vote counts.

    Returns the full catalog of challenges with metadata (icons, evidence,
    board recommenders, protocols) plus merged vote counts from DynamoDB.
    Dynamic status (active/completed/checkins) comes from /api/challenges.
    """
    global _challenge_catalog_cache
    if _challenge_catalog_cache is None:
        _challenge_catalog_cache = _load_s3_json("site/config/challenges_catalog.json", "challenge_catalog")

    # Merge vote counts from DynamoDB
    vote_counts = {}
    try:
        vote_pk = "VOTES#challenges"
        vote_resp = table.query(
            KeyConditionExpression=Key("pk").eq(vote_pk),
            ProjectionExpression="sk, vote_count",
        )
        for item in _decimal_to_float(vote_resp.get("Items", [])):
            cid = item.get("sk", "").replace("CH#", "")
            vote_counts[cid] = int(item.get("vote_count", 0))
    except Exception as e:
        logger.warning(f"[challenge_catalog] Vote query failed (non-fatal): {e}")

    # Inject votes into each challenge (deep copy to avoid mutating the cache)
    result = copy.deepcopy(_challenge_catalog_cache)
    # Filter out private challenges (public: false)
    challenges = [ch for ch in result.get("challenges", []) if ch.get("public", True) is not False]
    total_votes = 0
    for ch in challenges:
        ch["votes"] = vote_counts.get(ch.get("id", ""), 0)
        total_votes += ch["votes"]
    result["challenges"] = challenges
    result["total_votes"] = total_votes

    return _ok(result, cache_seconds=900)


# ── #2238: the check-in `note` screen ────────────────────────────────────────
# `note` is the only reader-supplied FREE TEXT in this module that reaches a
# public payload. It is captured by an anonymous POST (_handle_challenge_checkin),
# stored inside the challenge row's `daily_checkins`, and `handle_challenges`
# publishes that row WHOLE on GET /api/challenges. Until #2238 it was only
# length-capped: no HTML strip (unlike _handle_submit_finding / _handle_board_question,
# which both run the same re.sub) and no blocked-vice screen (unlike this module's
# challenge name/id filters). A stored `<script>` tag and blocked-vice vocabulary
# both came back verbatim to every reader of /protocols.
#
# Screened on BOTH sides deliberately: the write door rejects loudly (400, the
# _handle_board_question precedent) so the submitter is told, and the read door
# re-screens because rows written before this landed are still in the table and
# no backfill touches Matthew's own challenge records.


def _sanitise_note(raw) -> str:
    """HTML-strip + length-cap a reader-supplied check-in note — the identical
    treatment `_handle_submit_finding` and `_handle_board_question` give their
    free-text fields."""
    return re.sub(r"<[^>]+>", "", str(raw or "")).strip()[:500]


def _screened_note(raw) -> str:
    """A stored note, made safe to publish: HTML stripped, and emptied entirely if
    it carries blocked-vice vocabulary. Returns "" for anything withheld."""
    note = _sanitise_note(raw)
    if _is_blocked_vice(note):
        return ""
    return note


def _public_checkins(checkins) -> list:
    """The read-side screen over a challenge's stored `daily_checkins` (#2238).

    Keeps the check-in day itself — that is Matthew's own progress data, and the
    completion arithmetic reads `completed`, never `note` — and withholds only the
    stranger-supplied text when it fails the screen.
    """
    out = []
    for entry in checkins or []:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        note = _screened_note(row.get("note"))
        if note:
            row["note"] = note
        else:
            row.pop("note", None)
        out.append(row)
    return out


def handle_challenges() -> dict:
    """GET /api/challenges — live challenges overlaid on the full catalog.

    Live runs (USER#matthew#SOURCE#challenges, origin='live') are surfaced as
    "taken on / active". The challenge catalog (config/challenges_catalog.json,
    84 challenges) is always overlaid as origin='catalog' so the page shows the
    available + backlog pipeline even right after an experiment reset wipes the
    live partition. Blocked vices (porn/marijuana/…) are filtered server-side.
    """
    import re as _re

    live, live_ids = [], set()
    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot challenges
                    "KeyConditionExpression": Key("pk").eq(challenges_pk) & Key("sk").begins_with("CHALLENGE#"),
                    "ScanIndexForward": False,
                }
            )
        )
        for item in resp.get("Items", []):
            status = item.get("status", "candidate")
            if status not in ("active", "candidate", "completed", "failed"):
                continue
            ch = _decimal_to_float(item)
            ch.pop("pk", None)
            sk_val = ch.pop("sk", "") or ""
            raw_id = sk_val.replace("CHALLENGE#", "")
            ch["challenge_id"] = raw_id
            ch["id"] = _re.sub(r"_\d{4}-\d{2}-\d{2}$", "", raw_id)
            # ER-06: check name AND id — a blocked keyword often lives only in the
            # entry id while the display name is benign; `name or id` missed it.
            if _is_blocked_vice(ch.get("name", "")) or _is_blocked_vice(ch.get("id", "")):
                continue
            # #2238: reader-supplied check-in notes are published with this row —
            # screen them before they leave, including rows stored pre-#2238.
            if "daily_checkins" in ch:
                ch["daily_checkins"] = _public_checkins(ch.get("daily_checkins"))
            ch["origin"] = "live"
            if status == "active":
                checkins = ch.get("daily_checkins", [])
                duration = int(ch.get("duration_days", 7))
                completed_days = sum(1 for c in checkins if c.get("completed"))
                ch["progress"] = {
                    "checkin_days": len(checkins),
                    "completed_days": completed_days,
                    "duration_days": duration,
                    "completion_pct": round(len(checkins) / duration * 100) if duration else 0,
                    "success_rate": round(completed_days / len(checkins) * 100) if checkins else 0,
                }
            live.append(ch)
            live_ids.add(ch["id"])
    except Exception as e:
        logger.warning(f"[challenges] DynamoDB query failed, catalog-only: {e}")

    # Overlay the catalog (always) — available + backlog the live partition lacks.
    catalog = []
    global _challenges_cache, _challenges_cache_at
    if _challenges_cache is None or not config_cache_valid(_challenges_cache_at):
        _challenges_cache = _load_s3_json("config/challenges_catalog.json", "challenges_catalog")
        _challenges_cache_at = time.monotonic()
    for c in (_challenges_cache or {}).get("challenges", []):
        if c.get("id") in live_ids:
            continue
        if _is_blocked_vice(c.get("name", "")) or _is_blocked_vice(c.get("id", "")):  # ER-06: check name AND id
            continue
        shelf = "available" if c.get("status") == "available" else "backlog"
        catalog.append(
            {
                "id": c.get("id"),
                "challenge_id": c.get("id"),
                "name": c.get("name", "Challenge"),
                "status": shelf,
                "origin": "catalog",
                "one_liner": c.get("one_liner", ""),
                "category": c.get("category", ""),
                "duration_days": c.get("duration_days"),
                "difficulty": c.get("difficulty"),
                "evidence_tier": c.get("evidence_tier"),
                "evidence_summary": c.get("evidence_summary", ""),
                "board_recommender": c.get("board_recommender", ""),
                "icon": c.get("icon", ""),
            }
        )
    catalog.sort(key=lambda x: (x["status"] != "available", (x.get("category") or ""), (x.get("name") or "").lower()))

    challenges = live + catalog
    summary = {
        "total": len(challenges),
        "active": sum(1 for c in live if c.get("status") == "active"),
        "available": sum(1 for c in catalog if c["status"] == "available"),
        "backlog": sum(1 for c in catalog if c["status"] == "backlog"),
        "completed": sum(1 for c in live if c.get("status") == "completed"),
    }
    return _ok({"challenges": challenges, "count": len(challenges), "summary": summary, "source": "catalog+live"}, cache_seconds=300)


def _handle_challenge_checkin(event: dict) -> dict:
    """POST /api/challenge_checkin — Public check-in for active challenges.

    Body: {"challenge_id": "...", "completed": true/false, "note": "...", "date": "YYYY-MM-DD"}
    Uses localStorage on the client to prevent double-taps.
    Rate-limited: 1 check-in per IP per challenge per day (#358).
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error(400, "Invalid JSON body")

    challenge_id = (body.get("challenge_id") or "").strip()
    completed = body.get("completed")
    # #2238: the note is free text from an anonymous stranger that ends up on the
    # public GET /api/challenges payload. HTML-strip it (sibling capture doors do
    # the same) and refuse blocked-vice vocabulary outright, as _handle_board_question does.
    note = _sanitise_note(body.get("note"))
    date_str = (body.get("date") or "").strip()

    if not challenge_id:
        return _error(400, "challenge_id required")
    if completed is None:
        return _error(400, "completed (true/false) required")
    if _is_blocked_vice(note):
        return _error(400, "That note can't be submitted.")

    # Rate limit: 1 check-in per IP per challenge per day (#358). Applied
    # unconditionally via the module chokepoint (#2237) — never skipped.
    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    allowed, _rem, _retry = _rate_check(f"challenge_checkin:{challenge_id}", ip_hash, limit=1, window_seconds=86400)
    if not allowed:
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "86400", "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Already checked in for this challenge today."}),
        }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not date_str:
        date_str = today

    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    sk = f"CHALLENGE#{challenge_id}"

    # Verify challenge exists and is active
    try:
        item = table.get_item(Key={"pk": challenges_pk, "sk": sk}).get("Item")
    except Exception as e:
        logger.error(f"[challenge_checkin] DDB get failed: {e}")
        return _error(500, "Database error")

    if not item:
        return _error(404, "Challenge not found")
    if item.get("status") != "active":
        return _error(400, f"Challenge is not active (status: {item.get('status')})")

    # Build checkin
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    checkin = {
        "date": date_str,
        "completed": bool(completed),
        "logged_at": now_iso,
        "source": "website",
    }
    if note:
        checkin["note"] = note

    # Idempotent write: replace any existing check-in for the same date instead
    # of blindly appending. A double-tap or a network retry must not create a
    # duplicate day — that would inflate completion_pct / success_rate. (Residual:
    # a truly simultaneous double-tap can still race this read-modify-write; the
    # common retry/double-tap case — writes seconds apart — is fully covered.)
    existing = item.get("daily_checkins", []) or []
    deduped = [c for c in existing if c.get("date") != date_str]
    deduped.append(checkin)
    try:
        table.update_item(
            Key={"pk": challenges_pk, "sk": sk},
            UpdateExpression="SET daily_checkins = :cl",
            ExpressionAttributeValues={":cl": deduped},
        )
    except Exception as e:
        logger.error(f"[challenge_checkin] DDB update failed: {e}")
        return _error(500, "Failed to record check-in")

    total = len(deduped)
    duration = int(item.get("duration_days", 7) if item.get("duration_days") else 7)

    return _ok(
        {
            "checked_in": True,
            "challenge_id": challenge_id,
            "date": date_str,
            "completed": bool(completed),
            "total_checkins": total,
            "duration_days": duration,
            "completion_pct": round(total / duration * 100) if duration else 0,
        },
        cache_seconds=0,
    )


# ── #769 (ADR-124): evening-ritual one-tap write path ──────────────────────────
# The C floor of the fulfillment capture channel — the evening nudge mints two
# tappable links (connection 0-4, mood valence 0-4); tapping one hits this GET
# endpoint directly from the email client, no app-switching, no free text.

_RITUAL_TOKEN_SECRET_NAME = os.environ.get("RITUAL_TOKEN_SECRET_NAME", "life-platform/ritual-token-secret")
_ritual_token_secret_cache = None
RITUAL_LOG_RATE_LIMIT = 20  # per IP per hour — generous (legitimate re-taps happen), still floods-abuse-proof


def _get_ritual_token_secret() -> str:
    """Fetch the dedicated ritual-link HMAC secret from Secrets Manager.

    Same shape as `_get_token_secret` (subscriber tokens): a dedicated random
    key, never derived from another credential, so its compromise/rotation is
    isolated from every other signed surface.
    """
    global _ritual_token_secret_cache
    if _ritual_token_secret_cache:
        return _ritual_token_secret_cache
    try:
        sm = boto3.client("secretsmanager", region_name="us-west-2")
        _ritual_token_secret_cache = sm.get_secret_value(SecretId=_RITUAL_TOKEN_SECRET_NAME)["SecretString"]
        return _ritual_token_secret_cache
    except Exception as e:
        logger.error(f"[ritual_log] Signing secret unavailable: {e}")
        raise RuntimeError("Ritual token signing secret unavailable") from e


def _handle_ritual_log(event: dict) -> dict:
    """GET /api/ritual_log — one-tap write for the evening ritual (#769, ADR-124).

    Query params: date=YYYY-MM-DD, metric=connection|mood_valence, value=0-4, token=<hex32>.
    The token is an HMAC-SHA256 over (date, metric, value) minted by evening_nudge_lambda
    with the dedicated ritual-token secret (lambdas/ritual_link.py) — forging a different
    value for the same link requires the secret, matching the chronicle-approve /
    subscriber-token precedent (signed link, no separate auth scheme).

    Idempotency: last-tap-wins. A second tap (retry, or Matthew changing his mind from the
    same email) overwrites the metric + its logged_at — no read-modify-write, no dedup list,
    just a plain SET on the day's record. Two independent metrics on the same day are two
    independent SETs, so tapping connection doesn't disturb an already-logged mood_valence.

    Rate limit: RITUAL_LOG_RATE_LIMIT per IP per hour (DynamoDB-backed, matches nudge/checkin).
    """
    from content.ritual_link import RITUAL_METRICS, RITUAL_VALUE_MAX, RITUAL_VALUE_MIN, verify_ritual_token

    qs = event.get("queryStringParameters") or {}
    date_str = (qs.get("date") or "").strip()
    metric = (qs.get("metric") or "").strip().lower()
    value_raw = (qs.get("value") or "").strip()
    token = (qs.get("token") or "").strip()

    if metric not in RITUAL_METRICS:
        return _error(400, f"metric must be one of: {sorted(RITUAL_METRICS)}")

    try:
        value = int(value_raw)
    except (TypeError, ValueError):
        return _error(400, "value must be an integer")
    if not (RITUAL_VALUE_MIN <= value <= RITUAL_VALUE_MAX):
        return _error(400, f"value must be between {RITUAL_VALUE_MIN} and {RITUAL_VALUE_MAX}")

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return _error(400, "date must be YYYY-MM-DD")

    # Defense in depth beyond the signature: a link is only ever minted for "today"
    # (Pacific), so bound how stale a tap can be — a week of headroom covers an
    # unread nudge email without leaving the window open indefinitely.
    today_pt = datetime.now(PT).date()
    if date_obj > today_pt or (today_pt - date_obj).days > 7:
        return _error(400, "date outside the allowed window")

    try:
        secret = _get_ritual_token_secret()
    except RuntimeError:
        return _error(503, "Ritual logging temporarily unavailable")

    if not verify_ritual_token(secret, date_str, metric, value, token):
        return _error(403, "Invalid or tampered link")

    # Rate limit: RITUAL_LOG_RATE_LIMIT per IP per hour — DynamoDB-backed (survives
    # cold starts; bounded in-memory fallback only, #2237). Public GET, so it needs
    # the same protection as every other write endpoint in this module.
    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    allowed, _rem, _retry = _rate_check("ritual_log", ip_hash, limit=RITUAL_LOG_RATE_LIMIT, window_seconds=3600)
    if not allowed:
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600", "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Too many taps recently. Try again in a bit."}),
        }

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # #1405: private-class metrics land in their own Matthew-private partition —
    # never the evening_ritual record the public wellbeing aggregate reads. The
    # write path is shared (same signed link, same rate limit); only the
    # destination differs, so the public read surface structurally can't see it.
    from content.ritual_link import PRIVATE_RITUAL_METRICS, TIME_AFFLUENCE_PROBE_METRICS, WEEKLY_PROBE_METRICS

    try:
        table.update_item(
            # ALL destinations INLINE as USER_PREFIX-joined literals — the orphan
            # gate (tests/test_site_partition_orphans.py) resolves web writers only
            # inside the put/update call itself; a hoisted or dynamic pk makes
            # evening_ritual read as writerless (redded e1bcf766's Unit Tests).
            # #1409: weekly felt-reality probe taps land in felt_probe (their own
            # cadence + the calibration engine's read surface), never the daily
            # evening_ritual aggregate.
            # #1408: the weekly Time-Affluence probe (felt_time) lands in its own
            # time_affluence partition — read by the proxy + hypothesis-engine edge.
            Key={
                "pk": (
                    f"{USER_PREFIX}private_intake"
                    if metric in PRIVATE_RITUAL_METRICS
                    else (
                        f"{USER_PREFIX}time_affluence"
                        if metric in TIME_AFFLUENCE_PROBE_METRICS
                        else f"{USER_PREFIX}felt_probe" if metric in WEEKLY_PROBE_METRICS else f"{USER_PREFIX}evening_ritual"
                    )
                ),
                "sk": f"DATE#{date_str}",
            },
            UpdateExpression="SET #m = :v, #ts = :ts, #src = :src",
            ExpressionAttributeNames={
                "#m": metric,
                "#ts": f"{metric}_logged_at",
                "#src": "source",
            },
            ExpressionAttributeValues={
                ":v": Decimal(value),
                ":ts": now_iso,
                ":src": "evening_nudge_link",
            },
        )
    except Exception as e:
        logger.error(f"[ritual_log] DDB update failed: {e}")
        return _error(500, "Failed to record tap")

    logger.info(f"[ritual_log] date={date_str} metric={metric} value={value} ip_hash={ip_hash}")
    return _ok(
        {
            "logged": True,
            "date": date_str,
            "metric": metric,
            "value": value,
        },
        cache_seconds=0,
    )


def _handle_experiment_suggest(event: dict) -> dict:
    """POST /api/experiment_suggest — Store reader experiment suggestion.

    Rate-limited: 3 suggestions per IP per hour (#358). Suggestions are stored
    with status="pending" so they're distinguishable from owner-created experiments
    and can be moderated before surfacing publicly.
    """
    # Rate limit: 3 per IP per hour (#358). Applied unconditionally (#2237).
    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    allowed, _rem, _retry = _rate_check("experiment_suggest", ip_hash, limit=3, window_seconds=3600)
    if not allowed:
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600", "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Too many suggestions. Please try again later."}),
        }
    try:
        body = json.loads(event.get("body", "{}"))
        idea = body.get("idea", "").strip()
        source = body.get("source", "").strip()
        if not idea or len(idea) < 10:
            return _error(400, "Idea must be at least 10 characters")
        table.put_item(
            Item={
                "pk": "USER#matthew#SOURCE#experiment_suggestions",
                "sk": f"SUGGEST#{datetime.now(timezone.utc).isoformat()}",
                "idea": idea,
                "source": source,
                "status": "pending",
                "submitted_by": "reader",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps({"status": "received"})}
    except Exception as e:
        logger.error(f"[site_api] experiment_suggest failed: {e}")
        return _error(500, "Failed to submit suggestion")


# ─────────────────────────────────────────────────────────────────────────────
# Reader engagement loop — "predict the week" + "ask the board".
# Both reuse the existing sanctioned write surface (atomic VOTES# counters with a
# per-IP dedup row; S3 capture for Matthew to moderate). No new AI is called here:
# "ask the board" only CAPTURES a question — the answer reuses the already-gated
# /api/board_ask. The predict-week DDB writes need no IAM change (the site_api role
# already writes the table unconditionally); the board-question S3 write needs
# generated/board_questions/* added to the role (one additive line).
# ─────────────────────────────────────────────────────────────────────────────

_PREDICT_CHOICES = {"up", "down", "flat"}
BOARD_QUESTION_RATE_LIMIT = 3  # per IP per hour


def _current_iso_week() -> str:
    """The reader's current ISO week id (e.g. '2026-W29'), computed in Pacific Time.

    The site renders every user-facing date in PT, so 'this week' — the window the
    predict-the-week widget invites bets on — rolls over on the reader's Monday,
    not UTC's.
    """
    iso = datetime.now(PT).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _predict_subject():
    """The current week's prediction subject from current_challenge.json, or None.

    Returns {"week_id", "metrics": {key: label}, "result": {...}|None} when the
    weekly challenge defines a `predict_metrics` list AND its week_id is the
    current ISO week; None otherwise, so the feature fails *closed* — the widget
    doesn't render and POSTs are rejected when there's no active subject. Read
    fresh (no module cache) so a new Monday challenge is picked up without waiting
    for a cold start.
    """
    try:
        s3 = boto3.client("s3", region_name=S3_REGION)
        bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
        data = json.loads(s3.get_object(Bucket=bucket, Key="site/config/current_challenge.json")["Body"].read())
    except Exception:
        return None
    metrics = data.get("predict_metrics") or []
    week_id = (data.get("week_id") or data.get("id") or "").strip()
    mmap = {}
    for m in metrics:
        k = (m.get("key") or "").strip().lower()
        if k:
            mmap[k] = m.get("label") or k
    if not week_id or not mmap:
        return None
    # #1198 — fail closed on a stale week. current_challenge.json is a MANUAL,
    # per-week S3 artifact (no lambda writes it); if a Monday passes without a
    # re-seed, or a cycle reset leaves the outgoing cycle's frozen week live, its
    # week_id lags the real ISO week. Serving it would solicit predictions on a
    # window that already closed — votes land in a VOTES#predict_week bucket that
    # can never be revealed. Refuse: callers already treat None as "no active
    # subject" (the widget self-hides, POSTs 404).
    current = _current_iso_week()
    if week_id != current:
        logger.warning("[predict_week] stale subject week_id=%r != current ISO week %r; failing closed", week_id, current)
        return None
    return {"week_id": week_id, "metrics": mmap, "result": data.get("result")}


def _predict_tallies(week_id, metric):
    """Aggregate {up,down,flat: count} for one week+metric from VOTES#predict_week."""
    out = {"up": 0, "down": 0, "flat": 0}
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq("VOTES#predict_week") & Key("sk").begins_with(f"WK#{week_id}#M#{metric}#C#"))
        for it in resp.get("Items", []):
            c = it.get("choice")
            if c in out:
                out[c] = int(it.get("vote_count", 0))
    except Exception as e:
        logger.error(f"[predict_week] tally read failed: {e}")
    return out


def _handle_predict_week(event: dict) -> dict:
    """POST /api/predict_week — a reader predicts which way this week's metric moves.

    Body: {"week_id", "metric", "choice"} with choice ∈ {up, down, flat}.
    One prediction per IP per week per metric (DynamoDB dedup row, 8-day TTL).
    Validated against the live current_challenge's predict_metrics (fail-closed).
    """
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    subj = _predict_subject()
    if subj is None:
        return _error(404, "No active prediction this week")

    week_id = (body.get("week_id") or "").strip()
    metric = (body.get("metric") or "").strip().lower()
    choice = (body.get("choice") or "").strip().lower()
    if week_id != subj["week_id"]:
        return _error(409, "That prediction window has closed")
    if metric not in subj["metrics"]:
        return _error(404, "Unknown metric")
    if choice not in _PREDICT_CHOICES:
        return _error(400, "choice must be up, down, or flat")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    try:
        table.put_item(
            Item={
                "pk": "VOTES#rate_limit",
                "sk": f"PRED#{ip_hash}#{week_id}#{metric}",
                "voted_at": now_epoch,
                "ttl": now_epoch + 8 * 86400,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "You already predicted this metric this week"}),
            }
        logger.error(f"[predict_week] dedup check failed: {e}")
        return _error(500, "Prediction rate check failed")

    try:
        table.update_item(
            Key={"pk": "VOTES#predict_week", "sk": f"WK#{week_id}#M#{metric}#C#{choice}"},
            UpdateExpression="ADD vote_count :one SET week_id = :w, metric = :m, choice = :c, last_voted = :ts",
            ExpressionAttributeValues={":one": 1, ":w": week_id, ":m": metric, ":c": choice, ":ts": now_epoch},
        )
    except Exception as e:
        logger.error(f"[predict_week] increment failed: {e}")
        return _error(500, "Failed to record prediction")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"week_id": week_id, "metric": metric, "tallies": _predict_tallies(week_id, metric)}),
    }


def handle_predict_week_tally(event: dict) -> dict:
    """GET /api/predict_week — read-only reader-consensus tallies for the week.

    Returns {"active": False} when there's no prediction subject (the widget then
    hides). Otherwise returns the metrics, per-metric tallies, and the actual
    outcome (`result`) once Matthew sets it on the challenge — so the front-end can
    show "readers said UP 64% · it actually went DOWN."
    """
    subj = _predict_subject()
    if subj is None:
        return _ok({"active": False}, cache_seconds=120)
    qs = (event.get("queryStringParameters") or {}) or {}
    metric = (qs.get("metric") or "").strip().lower()
    if metric and metric not in subj["metrics"]:
        return _error(404, "Unknown metric")
    metrics = [metric] if metric else list(subj["metrics"].keys())
    tallies = {m: _predict_tallies(subj["week_id"], m) for m in metrics}
    return _ok(
        {
            "active": True,
            "week_id": subj["week_id"],
            "metrics": subj["metrics"],
            "result": subj.get("result"),
            "tallies": tallies,
        },
        cache_seconds=60,
    )


def _handle_board_question(event: dict) -> dict:
    """POST /api/board_question — capture a reader question for the AI board.

    A near-clone of _handle_submit_finding: rate-limited per IP, HTML-stripped and
    length-capped, vice-filtered, written to S3 with status=pending for Matthew to
    moderate. NO AI is invoked here — the answer is produced later via the already
    budget/rate-gated /api/board_ask and published as a dispatch. The optional email
    is stored privately for a reply and is never echoed back or published.
    """
    source_ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]

    # #2237: this door's old `else` branch set `allowed = True` unconditionally —
    # an unmetered S3 write path whenever the shared limiter was unavailable. It
    # now shares the module chokepoint with every other door.
    allowed, remaining, _retry = _rate_check("board_question", ip_hash, limit=BOARD_QUESTION_RATE_LIMIT, window_seconds=3600)
    if not allowed:
        _emit_rate_limit_metric("board_question")
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600"},
            "body": json.dumps({"error": "Rate limit reached. 3 questions per hour."}),
        }

    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON")

    question = re.sub(r"<[^>]+>", "", (body.get("question") or "").strip())[:500]
    email = re.sub(r"<[^>]+>", "", (body.get("email") or "").strip())[:254]
    if not question or len(question) < 10:
        return _error(400, "Question must be at least 10 characters.")
    if email and "@" not in email:
        return _error(400, "Invalid email format.")
    # Fail-closed on blocked-vice terms (privacy). Capture is moderated by Matthew
    # before any answer is published, but reject the obvious cases at the door.
    if _is_blocked_vice(question):
        return _error(400, "That question can't be submitted.")

    timestamp = datetime.now(timezone.utc).isoformat()
    # Content-based id so a same-month retry overwrites rather than duplicating.
    qid = hashlib.sha256(f"{ip_hash}:{question}".encode()).hexdigest()[:12]
    record = {
        "id": qid,
        "question": question,
        "email": email if email else None,
        "submitted_at": timestamp,
        "ip_hash": ip_hash,
        "status": "pending",
    }

    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    s3_key = f"generated/board_questions/{month}_{qid}.json"
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=json.dumps(record, indent=2), ContentType="application/json")
        logger.info(f"[board_question] Stored: {s3_key}")
    except Exception as e:
        logger.error(f"[board_question] S3 write failed: {e}")
        return _error(503, "Unable to store question. Try again later.")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps(
            {
                "success": True,
                "id": qid,
                "message": "Question received — Matthew reviews these and the board answers a selection.",
                "remaining": remaining,
            }
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# The Social Membrane — the Broadcast feed (#1672, epic #1668, story S4)
# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/broadcast — the read-only source for /story/broadcast/, the site's
# canonical home for Matthew's own public voice. Reverse-chron facade cards
# (thumbnail + caption + link-out) of the ingested social posts (#1669/#1670),
# filtered to the CLEARED, human-origin set. Modeled on handle_journey_timeline:
# read-only, aggregate-only, fail-soft, one _ok() envelope.

# The ingested-post partitions (#1669, extended #1676). All three are dormant until the
# owner provisions their respective identity (channel id / handle / instance+handle); as
# more inbound channels land they append here and the feed picks them up with no other
# change. pk = USER#matthew#SOURCE#<source>, sk = DATE#<date>#<post_id>, one row per post
# (youtube_lambda / bluesky_lambda / mastodon_lambda .transform — same shape).
_BROADCAST_SOURCES = ("youtube", "bluesky", "mastodon")
_BROADCAST_LIMIT = 60  # newest N cleared posts; the feed is a voice highlight, not an archive

# ── S5 sensitivity gate seam — RECONCILED to #1673 (PR #1701) ────────────────────
# #1672 ships the origin:human feed; #1673 lands the FAIL-CLOSED auto-publish
# sensitivity gate. This is the ONE place the seam composes. Reconciled to #1673's
# ACTUAL contract (its `gate` module): the row attribute is `sensitivity_status`
# (== gate.STATUS_ATTR) and the publishable verdict is the literal "cleared"
# (NOT "clear") — i.e. gate.is_cleared(post). FAIL CLOSED — a missing / "pending" /
# "flagged" / any non-"cleared" status is WITHHELD, so a flagged post is absent from
# the rendered feed (AC) and the feed is honestly empty until #1673 stamps posts.
#
# #1673's `gate` module isn't in this branch yet (unmerged sibling PR #1701), so we
# MIRROR its contract rather than import it. On merge, collapse to the single source
# of truth: `from <gate_module> import is_cleared` and make _is_sensitivity_cleared a
# one-line delegate to it (its helpers: is_cleared / filter_cleared / STATUS_ATTR /
# cleared_filter_expression). The literals below match #1673 exactly.
SENSITIVITY_STATUS_ATTR = "sensitivity_status"  # == #1673 gate.STATUS_ATTR
SENSITIVITY_CLEARED = "cleared"  # == #1673's publishable verdict (gate.is_cleared)


def _is_sensitivity_cleared(post: dict) -> bool:
    """FAIL-CLOSED mirror of #1673 gate.is_cleared: only sensitivity_status == "cleared" publishes."""
    return (post or {}).get(SENSITIVITY_STATUS_ATTR) == SENSITIVITY_CLEARED


def _is_broadcast_visible(post: dict) -> bool:
    """The ONE membrane predicate for the broadcast feed — kept in a single place so
    #1673's real gate reconciles trivially:

      S2 (#1670) origin:human  AND  S5 (#1673) sensitivity-clear (fail-closed).

    origin:human treats an UNSTAMPED row as human (membrane default, #1670); the
    sensitivity gate is the opposite posture — unstamped is NOT cleared — because a
    post no gate has vetted must never auto-publish.
    """
    return social_provenance.is_displayable_voice(post) and _is_sensitivity_cleared(post)


def _broadcast_card(post: dict) -> dict:
    """Reduce an ingested-post DDB row to a facade card (thumbnail + caption + link).

    A FACADE by design (#1672): a link-out to where the post lives, never a
    third-party iframe — so the feed needs zero CSP change (img-src already allows
    any HTTPS thumbnail). Native players are a later story (S10)."""
    pid = str(post.get("post_id") or post.get("sk", "").split("#")[-1] or "")
    return {
        "id": pid,
        "date": post.get("date") or str(post.get("sk", "")).replace("DATE#", "").split("#")[0],
        "channel": post.get("channel", ""),
        "caption": post.get("title", ""),
        "excerpt": post.get("description", ""),
        "thumbnail_url": post.get("thumbnail_url", ""),
        "link_out": post.get("url", ""),  # where the post actually lives (facade target)
        "permalink": f"/story/broadcast/#{pid}" if pid else "/story/broadcast/",
    }


def _membrane_source_rows() -> list:
    """Every ingested-post row (#1669), UNGATED — the raw read behind the membrane.

    Split out of _membrane_visible_rows (#1679) because the membrane dashboard has to
    report on what the gate REJECTED (how many platform-origin echoes it kept out),
    which is unanswerable from the post-gate set. Everything reader-facing still goes
    through _membrane_visible_rows below; this function is the shared QUERY, never a
    second gate. Fail-soft per source (a query error on one channel never breaks a
    feed). Newest-first within each source; callers merging sources re-sort."""
    rows: list = []
    for source in _BROADCAST_SOURCES:
        pk = f"{USER_PREFIX}{source}"
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
                ScanIndexForward=False,  # newest-first
            )
            rows.extend(_decimal_to_float(resp.get("Items", [])))
        except Exception as e:  # noqa: BLE001 — one bad channel must not break the feed
            logger.warning("[site_api] social membrane: source %s query failed (non-fatal): %s", source, e)
    return rows


def _membrane_visible_rows() -> list:
    """The ingested-post rows that pass the ONE membrane predicate (origin:human +
    sensitivity-clear, fail-closed). Shared by /api/broadcast (#1672),
    /api/social_context (#1674) and /api/membrane (#1679) so there's exactly one
    query + one gate, never copies drifting apart."""
    return [r for r in _membrane_source_rows() if _is_broadcast_visible(r)]


def handle_broadcast() -> dict:
    """GET /api/broadcast — reverse-chron cleared, human-origin posts for /story/broadcast/.

    Read-only; queries the ingested-post partitions, applies the ONE membrane
    predicate (_is_broadcast_visible), and returns facade cards newest-first.
    Fail-soft per source (a query error on one channel never breaks the feed).
    Cache 900s — the feed is refreshed by hourly-ish ingestion, not per-request."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    visible = _membrane_visible_rows()
    # Reverse-chron across all sources (the per-source query is already newest-first;
    # this re-sorts the merged set). sk carries the post id after the date, so sort on it.
    visible.sort(key=lambda r: str(r.get("date", "")) + str(r.get("sk", "")), reverse=True)
    cards = [_broadcast_card(r) for r in visible[:_BROADCAST_LIMIT]]

    return _ok(
        {
            "as_of_date": today,
            "items": cards,
            "total": len(cards),
        },
        cache_seconds=900,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Contextual social embeds (#1674, epic #1668, story S6)
# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/social_context?route=training|mind — the SAME cleared, human-origin
# membrane as /api/broadcast (_membrane_visible_rows), narrowed to the posts whose
# ENRICHED content (#1671 social_signals.coach_route_of — the same router the
# training/Mind coach surfaces already read, ai_context._social_posts_by_route)
# routes to the requested surface. A training-flavoured post (exercise_context, or
# a concrete training keyword in its themes/behaviors/entities) surfaces on
# /data/training/; a reflective post surfaces on the Mind pillar (/data/mind/).
#
# Facade cards only — reuses _broadcast_card, so this is a pure narrowing of the
# broadcast feed, never a second card shape. Zero CSP change: no third-party
# iframe, same as #1672. #1678 (native embeds via a scoped frame-src/media-src
# amendment) is a separate, owner-gated security decision — this endpoint stays a
# facade regardless of how that lands.
#
# Only ACTUALLY-ENRICHED posts (enriched_at present) are eligible: an unenriched
# post has no content signal to route on, so classify_coach_route's "mind" default
# would silently misroute a training post that just hasn't been enriched yet. It
# stays in the general /story/broadcast/ feed until enrichment stamps a route.
_CONTEXT_ROUTES = frozenset({"training", "mind"})
_CONTEXT_LIMIT = 6  # a contextual sidebar highlight, not the full archive — see /story/broadcast/ for that


def _handle_social_context(event: dict) -> dict:
    """GET /api/social_context?route=training|mind — contextual embeds for #1674."""
    params = event.get("queryStringParameters") or {}
    route = (params.get("route") or "").strip().lower()
    if route not in _CONTEXT_ROUTES:
        return _error(400, f"route query parameter is required and must be one of: {sorted(_CONTEXT_ROUTES)}")

    enriched = [r for r in _membrane_visible_rows() if r.get("enriched_at")]
    matched = [r for r in enriched if coach_route_of(r) == route]
    matched.sort(key=lambda r: str(r.get("date", "")) + str(r.get("sk", "")), reverse=True)
    cards = [_broadcast_card(r) for r in matched[:_CONTEXT_LIMIT]]

    return _ok(
        {
            "route": route,
            "items": cards,
            "total": len(cards),
        },
        cache_seconds=900,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# The bidirectional membrane dashboard (#1679, epic #1668, story S11)
# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/membrane — "what I said, where it went, what came back" in one payload.
# The loop the epic describes has three stages and this endpoint reports each one
# from ITS OWN system of record, never from a derived summary:
#
#   said / went  ← the BROADCAST_ORIGIN# ledger (#1670). One row per post the
#                  platform's outbound syndication path created, keyed by
#                  (channel, post_id). That ledger IS "where it went".
#   came back    ← the SAME _membrane_visible_rows() the Broadcast feed reads.
#                  Not a second query and not a second predicate — the dashboard
#                  cannot disagree with /story/broadcast/ about what is human.
#   the membrane ← the count of ingested rows the origin gate classified as
#                  platform echoes. This is the join the epic asks to be visible:
#                  an echo is displayed as an echo and never counted as inbound.
#
# NO vanity metrics (#1402's no-gloss ethos): no followers, no likes, no reach, no
# impressions. Nothing here is an engagement number — every figure is a count of
# records the platform itself wrote, which is the only thing it can honestly claim.
#
# HONEST ABSENCE (ADR-104). Today every partition below is empty, and "empty" has
# two different meanings that must not be flattened into one 0:
#   * a channel that is not wired yet is `dormant` — the absence of a pipe, not the
#     absence of posting. Derived from the source registry's own `active_api` facet,
#     never hand-stated here (the #2003 drift class).
#   * a channel that IS wired and has no rows is `empty` — a real zero.
# The payload carries the state, and the page renders the two differently.
#
# PRIVACY. Everything published here is already public by construction: outbound
# rows describe posts the platform made in public, and inbound items are exactly the
# membrane-cleared set /story/broadcast/ already serves. The sensitivity gate's HELD
# set is deliberately NOT published — not the content and not the count. Publishing
# "3 held" would disclose that flagged material exists, which is the one thing a
# fail-closed gate is supposed to keep quiet. That is also why no raw ingested total
# is returned: with a total, held would be derivable by subtraction.

# The outbound channels whose ledger partition is queried. Mirrors _BROADCAST_SOURCES
# above: adding a channel appends here and the dashboard picks it up with no other
# change. Kept in sync by hand with the posting surface's own platform list
# (scripts/post_social.py --platform), which is a local operator script the Lambda
# cannot import.
_OUTBOUND_CHANNELS = ("bluesky", "x")
_MEMBRANE_LIMIT = 20  # newest N per side — a legible loop, not an archive


def _outbound_ledger_rows(channel: str) -> list:
    """The BROADCAST_ORIGIN# ledger rows for one channel (#1670). Fail-soft: a query
    error on one channel returns [] rather than breaking the whole dashboard."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"BROADCAST_ORIGIN#{channel}") & Key("sk").begins_with("POST#"),
            ScanIndexForward=False,
        )
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # noqa: BLE001 — one bad channel must not break the dashboard
        logger.warning("[site_api] membrane: outbound ledger %s query failed (non-fatal): %s", channel, e)
        return []


def _inbound_channel_live(source: str) -> bool:
    """Is an inbound channel actually pulling yet? Read from the source registry's own
    `active_api` facet — the canonical place a source's live/dormant state is recorded
    (CLAUDE.md: read the registry, don't hand-state it). A source absent from the
    registry is treated as not live."""
    try:
        return bool((SOURCE_REGISTRY.get(source) or {}).get("active_api"))
    except Exception:  # noqa: BLE001 — a registry read must never break the dashboard
        return False


def _outbound_record(row: dict) -> dict:
    """Reduce a ledger row to the public outbound record. Provenance fields only —
    what was posted, to which channel, when it was recorded, and where it lives."""
    return {
        "id": str(row.get("post_id") or str(row.get("sk", "")).replace("POST#", "")),
        "channel": row.get("channel", ""),
        "url": row.get("url", ""),
        "recorded_at": row.get("recorded_at", ""),
    }


def handle_membrane() -> dict:
    """GET /api/membrane — the bidirectional membrane dashboard (#1679).

    Read-only, aggregate + provenance only, fail-soft on every read. Returns the
    three stages of the loop with an explicit state per side so the page can render
    "not wired yet" differently from "wired and quiet"."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── what I said → where it went (the outbound ledger) ──────────────────────
    outbound_channels, outbound_rows = [], []
    for channel in _OUTBOUND_CHANNELS:
        rows = _outbound_ledger_rows(channel)
        outbound_rows.extend(rows)
        outbound_channels.append({"channel": channel, "recorded": len(rows)})
    outbound_rows.sort(key=lambda r: str(r.get("recorded_at", "")), reverse=True)

    # ── what came back (the SAME gate the Broadcast feed uses) ─────────────────
    source_rows = _membrane_source_rows()
    visible = [r for r in source_rows if _is_broadcast_visible(r)]
    # The membrane join: rows the ORIGIN half of the predicate rejected. Counted from
    # social_provenance's own predicate — the same one _is_broadcast_visible composes —
    # so an echo can never be tallied as inbound. (Rows the SENSITIVITY half held are
    # deliberately not counted or reported; see the privacy note above.)
    echoes = sum(1 for r in source_rows if not social_provenance.is_displayable_voice(r))
    visible.sort(key=lambda r: str(r.get("date", "")) + str(r.get("sk", "")), reverse=True)

    inbound_channels = []
    for source in _BROADCAST_SOURCES:
        live = _inbound_channel_live(source)
        inbound_channels.append(
            {
                "channel": source,
                "live": live,
                "state": "live" if live else "dormant",
                # VISIBLE (cleared, human-origin) rows only — never the raw partition
                # count, which would make the held set derivable by subtraction.
                "visible": sum(1 for r in visible if r.get("channel") == source),
            }
        )

    return _ok(
        {
            "as_of_date": today,
            "outbound": {
                "state": "recording" if outbound_rows else "empty",
                "total": len(outbound_rows),
                "channels": outbound_channels,
                "posts": [_outbound_record(r) for r in outbound_rows[:_MEMBRANE_LIMIT]],
            },
            "inbound": {
                # "dormant" while NO inbound channel is wired — the absence of a pipe,
                # which is not the same claim as "nothing came back" (ADR-104).
                "state": "live" if any(c["live"] for c in inbound_channels) else "dormant",
                "visible": len(visible),
                "channels": inbound_channels,
                "items": [_broadcast_card(r) for r in visible[:_MEMBRANE_LIMIT]],
            },
            "membrane": {
                "echoes_excluded": echoes,
                "predicate": "origin:human AND sensitivity-cleared (fail-closed)",
            },
        },
        cache_seconds=900,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# The Engagement Ladder (#1393, epic #1366) — Reader → Subscriber → Predictor →
# Replicator → Contributor.
# ═══════════════════════════════════════════════════════════════════════════════
# Participation made legible as rungs. The reader's OWN rung is computed CLIENT-side
# from the EXISTING subscriber HMAC token + localStorage (engagement_ladder.js) — no
# auth system is built, no new identity, no PII stored server-side. This module
# publishes only the PUBLIC, aggregate rung COUNTS, each DERIVED FROM DATA already in
# the system and stamped with a `.provenance` block (never a hand-maintained number).
# Two endpoints:
#   GET  /api/ladder_counts     — read-only public counts + provenance (the only thing
#                                 rendered on the site).
#   POST /api/replicate_certify — a reader self-certifies a completed Replication Kit
#                                 run; a per-source-deduped aggregate counter, no PII.
# SDT note (the design warning the story carries): the streak/participation surface is
# INFORMATION ONLY — never loss-framed, gaps neutral, skippable. That copy lives in
# engagement_ladder.js; the server only reports counts.

# The self-cert Replicator aggregate lives under a VOTES#* pk, so it is already covered
# by the site_api role's LeadingKeys (VOTES#*) — no IAM change. The per-IP dedup rows
# ride the shared VOTES#rate_limit partition, REPL# prefixed.
#
# UNLIKE predict-week's PRED#{ip_hash}#{week}#{metric} rows, REPL# rows carry NO ttl
# (#1825). Predict-week's dedup is intentionally a per-week RATE LIMIT (the TTL window
# is disclosed in its own provenance: "the active window only"); the Replicator rung's
# published provenance instead promises a ONE-TIME EVER cert — "deduped per source", no
# window qualifier. An 8-day TTL row previously made that dedup reset every 8 days, so
# the same source could keep re-certifying and inflating the monotonic cert_count
# counter forever (VOTES# is SYSTEM_STATE — no reset ever corrects it either). Dropping
# the ttl makes the dedup row (and therefore the count) actually match what's published.
_LADDER_REPLICATOR_PK = "VOTES#ladder_replicator"
# The Contributor rung wires to the EXISTING findings moderation path: when Matthew
# verifies + publishes a reader-submitted finding, that path appends it to this single
# index object ({id, credit_opt_in, credit_name} — never an email/identity). The
# site-api has GetObject on generated/* (NOT ListBucket), so it reads this ONE known key
# rather than enumerating the findings queue. Absent/empty ⇒ an honest 0.
_PUBLISHED_FINDINGS_INDEX_KEY = "generated/findings/_published_index.json"


def _ladder_subscriber_count() -> int:
    """Confirmed-subscriber count — the same COUNT query behind /api/sub_count."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#subscribers"),
            Select="COUNT",
            FilterExpression="attribute_exists(#s) AND #s = :confirmed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":confirmed": "confirmed"},
        )
        return int(resp.get("Count", 0))
    except Exception as e:
        logger.warning(f"[ladder] subscriber count failed: {e}")
        return 0


def _ladder_predictor_count() -> int:
    """Distinct predict-the-week participants in the active window.

    Counts DISTINCT ip_hash across the predict dedup rows (pk VOTES#rate_limit,
    sk PRED#{ip_hash}#{week}#{metric}). Those rows carry an 8-day TTL, so this is
    honestly 'participants in the current prediction window', not an all-time total —
    the provenance says exactly that. No new partition, no PII (ip_hash only, already
    the site's dedup primitive)."""
    seen: set = set()
    try:
        kwargs: dict = {"KeyConditionExpression": Key("pk").eq("VOTES#rate_limit") & Key("sk").begins_with("PRED#")}
        for _ in range(50):  # page cap — bounded by the 8-day TTL window, personal scale
            resp = table.query(**kwargs)
            for it in resp.get("Items", []):
                parts = str(it.get("sk", "")).split("#")
                if len(parts) >= 2 and parts[1]:
                    seen.add(parts[1])
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except Exception as e:
        logger.warning(f"[ladder] predictor count failed: {e}")
    return len(seen)


def _ladder_replicator_count() -> int:
    """Self-certified Replication Kit completions — the aggregate counter row."""
    try:
        resp = table.get_item(Key={"pk": _LADDER_REPLICATOR_PK, "sk": "COUNT"})
        item = _decimal_to_float(resp.get("Item") or {})
        return int(item.get("cert_count", 0) or 0)
    except Exception as e:
        logger.warning(f"[ladder] replicator count failed: {e}")
        return 0


def _ladder_contributors() -> tuple:
    """(count, credited_names) of verified+published reader findings.

    Reads the single published-findings index the moderation path maintains. Only
    opt-in display names are surfaced — never an email or reader identity. Fail-soft to
    (0, []) when nothing has been published yet."""
    idx = _load_s3_json(_PUBLISHED_FINDINGS_INDEX_KEY, "published_findings_index")
    entries = idx.get("published") if isinstance(idx, dict) else None
    if not isinstance(entries, list):
        return 0, []
    credited: list = []
    for e in entries:
        if isinstance(e, dict) and e.get("credit_opt_in") and isinstance(e.get("credit_name"), str):
            nm = e["credit_name"].strip()[:60]
            if nm:
                credited.append(nm)
    return len(entries), credited


def handle_ladder_counts() -> dict:
    """GET /api/ladder_counts — public engagement-ladder rung counts + provenance.

    Read-only. Every published count is DERIVED FROM DATA (never hand-maintained) and
    carries a .provenance block naming its source + method. The Reader rung is the
    anonymous base — deliberately uncounted (no identity is tracked), which the
    provenance states rather than fabricating a number."""
    subscribers = _ladder_subscriber_count()
    predictors = _ladder_predictor_count()
    replicators = _ladder_replicator_count()
    contributors, credited = _ladder_contributors()
    rungs = {
        "reader": {
            "label": "Reader",
            "count": None,
            "countable": False,
            "provenance": {
                "source": "none",
                "method": "not counted — anonymous, no identity or PII is stored",
                "note": "everyone who reads; the base rung has no number by design",
            },
        },
        "subscriber": {
            "label": "Subscriber",
            "count": subscribers,
            "countable": True,
            "provenance": {
                "source": "ddb:USER#matthew#SOURCE#subscribers",
                "method": "COUNT of confirmed (double-opt-in) subscriber records",
                "note": "the same query behind /api/sub_count",
            },
        },
        "predictor": {
            "label": "Predictor",
            "count": predictors,
            "countable": True,
            "provenance": {
                "source": "ddb:VOTES#rate_limit (PRED# dedup rows)",
                "method": "distinct participants who cast a predict-the-week call",
                "note": "the active window only — dedup rows carry an 8-day TTL",
            },
        },
        "replicator": {
            "label": "Replicator",
            "count": replicators,
            "countable": True,
            "provenance": {
                "source": "ddb:VOTES#ladder_replicator",
                "method": "self-certified Replication Kit completions, deduped per source",
                "note": "self-reported; no proof required or stored",
            },
        },
        "contributor": {
            "label": "Contributor",
            "count": contributors,
            "countable": True,
            "credited": credited,
            "provenance": {
                "source": "s3:generated/findings/_published_index.json",
                "method": "reader findings verified + published via the existing moderation path",
                "note": "named credit is opt-in only; no emails or identities are exposed",
            },
        },
    }
    return _ok(
        {
            "order": ["reader", "subscriber", "predictor", "replicator", "contributor"],
            "rungs": rungs,
        },
        cache_seconds=300,
    )


def _handle_replicate_certify(event: dict) -> dict:
    """POST /api/replicate_certify — a reader self-certifies a completed Replication
    Kit run, bumping the public Replicator rung count.

    SELF-CERTIFIED by design (#1393): no proof is required and none is stored — the
    reader asserts they ran a kit. Deduped per source, PERMANENTLY (one cert per IP,
    ever — a no-ttl row on the shared VOTES#rate_limit partition, #1825) so a
    double-tap / retry / return-visit-after-the-old-8-day-window can't inflate the
    count; the published provenance says "deduped per source" with no window
    qualifier, so the dedup itself must not expire. No PII: only an ip_hash (already
    the site's dedup primitive) and an aggregate counter. ZERO moderation load —
    nothing lands in a review queue."""
    source_ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    try:
        table.put_item(
            Item={
                "pk": "VOTES#rate_limit",
                "sk": f"REPL#{ip_hash}",
                "voted_at": now_epoch,
                # No ttl (#1825) — unlike the rate-limit-style dedup rows elsewhere in
                # this module, this one must never expire: the published provenance
                # promises a one-time-ever cert, not a rolling window.
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            # Idempotent: already counted this source. Report success so the reader's
            # own rung still resolves, but do NOT double-count.
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"certified": True, "counted": False, "message": "Already counted — thanks for replicating."}),
            }
        logger.error(f"[replicate_certify] dedup write failed: {e}")
        return _error(500, "Could not record certification")
    try:
        table.update_item(
            Key={"pk": _LADDER_REPLICATOR_PK, "sk": "COUNT"},
            UpdateExpression="ADD cert_count :one SET last_certified = :ts",
            ExpressionAttributeValues={":one": 1, ":ts": now_epoch},
        )
    except Exception as e:
        logger.error(f"[replicate_certify] counter increment failed: {e}")
        return _error(500, "Could not record certification")
    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"certified": True, "counted": True, "message": "Logged — you're on the Replicator rung."}),
    }


# ── #1394 (epic #1366): The Cohort Strip — "where do I sit this week?" ──────────
# A weekly ANONYMOUS distribution of participant-reported single numbers (one
# metric per week) with Matthew's dot marked. One-tap submission reuses this
# module's check-in write class verbatim — the same DynamoDB `table` and the same
# DDB-backed `_ddb_rate_check` that _handle_challenge_checkin uses (no fork, no new
# rate limiter). There is NO free-text field, so there is zero moderation surface.
#
# Structural isolation (the load-bearing privacy invariant): cohort submissions
# live in their OWN partition family, `COHORT#<metric>#<week>` — deliberately NOT a
# `USER#matthew#SOURCE#…` partition. Matthew's stats/calibration pipelines only ever
# query his own `USER#…#SOURCE#…` partitions, so they can never read pooled cohort
# numbers. tests/test_cohort_strip_isolation_1394.py asserts this both directions.
# Matthew's dot on the strip is his own metric value, supplied by the weekly config
# (not read back out of the cohort partition), keeping the two data sets disjoint.
COHORT_PK_PREFIX = "COHORT#"  # the cohort partition family — NEVER a USER#…#SOURCE# key
COHORT_K_FLOOR = 5  # k-anonymity: the strip stays hidden until n ≥ this (a HARD gate, not copy)
COHORT_SUBMIT_WINDOW = 604800  # 1 submission per IP per week (7 days), DDB-backed
COHORT_HIST_BINS = 12  # inline-SVG histogram resolution across the metric's axis
_cohort_config_cache: dict = {}
_cohort_config_cache_ts = 0.0


def _cohort_partition(metric_id: str, week: str) -> str:
    """The one place a cohort pk is minted — `COHORT#<metric>#<week>`.

    Kept literal-prefixed with COHORT_PK_PREFIX so the isolation test can prove no
    stats/calibration module references this family and both handlers only ever
    touch it (never a USER#…#SOURCE# partition).
    """
    return f"{COHORT_PK_PREFIX}{metric_id}#{week}"


def _load_cohort_config() -> dict | None:
    """Load the active weekly cohort metric from S3 config (module-cached).

    Shape (site/config/cohort_week.json):
      {"metric_id": "resting_heart_rate", "label": "Resting heart rate",
       "unit": "bpm", "week": "2026-W30", "matthew_value": 52,
       "axis_min": 40, "axis_max": 90, "lower_is_better": true}

    Absent/malformed → None, which both handlers treat as "no active cohort week"
    (the strip self-hides; submissions 404) — never a fabricated metric.

    Cached for STATUS_CACHE_TTL seconds (matches handle_status's pattern), and
    ONLY once a load actually returns a config — a miss/error is never cached
    (#1821: the prior "cache forever, including the miss" pattern held a warm
    container on `{"active": false}` until recycle, and at week rollover let
    different containers disagree for their whole remaining lifetime about
    which week's partition to write/read, splitting submissions across a dead
    week and a live one).
    """
    global _cohort_config_cache, _cohort_config_cache_ts
    import time as _time

    now_ts = _time.time()
    if not _cohort_config_cache or now_ts - _cohort_config_cache_ts >= STATUS_CACHE_TTL:
        _cohort_config_cache = _load_s3_json("site/config/cohort_week.json", "cohort_week") or {}
        _cohort_config_cache_ts = now_ts
    cfg = _cohort_config_cache
    if not cfg or not cfg.get("metric_id") or not cfg.get("week"):
        return None
    try:
        amin = float(cfg["axis_min"])
        amax = float(cfg["axis_max"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (amax > amin):
        return None
    return cfg


def _handle_cohort_submit(event: dict) -> dict:
    """POST /api/cohort_submit — one-tap weekly single-number submission (#1394).

    Body: {"value": <number>}. NO free text — a single number is the entire payload,
    so there is nothing to moderate. Reuses the check-in write class: same DynamoDB
    `table`, same DDB-backed `_ddb_rate_check` (1 submission / IP / week), same
    idempotent read-free write discipline as _handle_challenge_checkin.

    The write lands in the cohort partition `COHORT#<metric>#<week>` at sk
    `SUBMIT#<ip_hash>` — a re-tap from the same IP overwrites its own row (last-tap
    wins), so a double-tap can never inflate n. The individual value is never read
    back out for display; only the aggregate strip is ever served.
    """
    cfg = _load_cohort_config()
    if not cfg:
        return _error(404, "No cohort metric active this week")

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error(400, "Invalid JSON body")

    raw = body.get("value")
    if isinstance(raw, bool) or raw is None:
        return _error(400, "value (number) required")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _error(400, "value must be a number")
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf guard
        return _error(400, "value must be a finite number")

    amin, amax = float(cfg["axis_min"]), float(cfg["axis_max"])
    if not (amin <= value <= amax):
        return _error(400, f"value must be between {amin:g} and {amax:g} {cfg.get('unit', '')}".strip())

    metric_id = str(cfg["metric_id"])
    week = str(cfg["week"])

    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

    # Rate limit: 1 submission per IP per week — DDB-backed (the SAME limiter the
    # challenge check-in uses), survives warm-container distribution. Applied
    # unconditionally via the module chokepoint (#2237).
    allowed, _rem, _retry = _rate_check(f"cohort_submit:{week}", ip_hash, limit=1, window_seconds=COHORT_SUBMIT_WINDOW)
    if not allowed:
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": str(COHORT_SUBMIT_WINDOW), "Cache-Control": "no-store"},
            "body": json.dumps({"error": "You've already added your number this week."}),
        }

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        # pk INLINE via _cohort_partition — the cohort family, never a USER#…#SOURCE#
        # partition. sk keyed by ip_hash makes the write idempotent per participant.
        table.put_item(
            Item={
                "pk": _cohort_partition(metric_id, week),
                "sk": f"SUBMIT#{ip_hash}",
                "value": Decimal(str(value)),
                "week": week,
                "metric_id": metric_id,
                "logged_at": now_iso,
                "source": "website",
            }
        )
    except Exception as e:
        logger.error(f"[cohort_submit] DDB put failed: {e}")
        return _error(500, "Failed to record your number")

    logger.info(f"[cohort_submit] metric={metric_id} week={week} ip_hash={ip_hash}")
    # Never echo n or any other participant's number — the client refreshes the
    # aggregate strip through /api/cohort_strip, which enforces the k-anonymity floor.
    return _ok({"submitted": True, "metric_id": metric_id, "week": week}, cache_seconds=0)


def handle_cohort_strip() -> dict:
    """GET /api/cohort_strip — the anonymous weekly distribution strip (#1394).

    Enforces the k-anonymity floor (n ≥ COHORT_K_FLOOR) as a HARD gate: below it the
    payload carries `visible: false` and NO distribution at all (a dignified
    "waiting for n≥5" state on the client, never a fabricated chart or band —
    ADR-105 confidence grammar). At or above the floor it returns AGGREGATES ONLY —
    a histogram + quartiles + Matthew's percentile. Individual submissions are never
    returned. Matthew's dot value comes from the weekly config, not the cohort
    partition, so his stats stay disjoint from the pool.
    """
    cfg = _load_cohort_config()
    if not cfg:
        return _ok({"active": False}, cache_seconds=300)

    metric_id = str(cfg["metric_id"])
    week = str(cfg["week"])
    label = str(cfg.get("label", metric_id))
    unit = str(cfg.get("unit", ""))
    amin, amax = float(cfg["axis_min"]), float(cfg["axis_max"])
    matthew_value = cfg.get("matthew_value")
    try:
        matthew_value = float(matthew_value) if matthew_value is not None else None
    except (TypeError, ValueError):
        matthew_value = None

    base = {
        "active": True,
        "week": week,
        "metric_id": metric_id,
        "label": label,
        "unit": unit,
        "axis_min": amin,
        "axis_max": amax,
        "matthew_value": matthew_value,
        "floor": COHORT_K_FLOOR,
        "lower_is_better": bool(cfg.get("lower_is_better", False)),
    }

    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(_cohort_partition(metric_id, week)))
        items = resp.get("Items", []) or []
    except Exception as e:
        logger.error(f"[cohort_strip] DDB query failed: {e}")
        return _error(500, "Database error")

    values = []
    for it in items:
        v = _decimal_to_float(it.get("value"))
        if isinstance(v, (int, float)) and amin <= v <= amax:
            values.append(float(v))
    n = len(values)

    # HARD k-anonymity gate — below the floor, no distribution is emitted at all.
    if n < COHORT_K_FLOOR:
        return _ok({**base, "visible": False, "n": n}, cache_seconds=60)

    values.sort()
    span = amax - amin
    bins = [0] * COHORT_HIST_BINS
    for v in values:
        idx = int((v - amin) / span * COHORT_HIST_BINS)
        idx = min(COHORT_HIST_BINS - 1, max(0, idx))
        bins[idx] += 1

    def _pctile(p: float) -> float:
        if n == 1:
            return values[0]
        k = (n - 1) * p
        lo = int(k)
        hi = min(lo + 1, n - 1)
        return values[lo] + (values[hi] - values[lo]) * (k - lo)

    # Matthew's rank among the pool — a percentile, never his row exposed to others.
    m_pctile = None
    if matthew_value is not None:
        below = sum(1 for v in values if v < matthew_value)
        m_pctile = round(below / n * 100)

    return _ok(
        {
            **base,
            "visible": True,
            "n": n,
            "bins": bins,
            "bin_count": COHORT_HIST_BINS,
            "min": round(values[0], 2),
            "p25": round(_pctile(0.25), 2),
            "median": round(_pctile(0.5), 2),
            "p75": round(_pctile(0.75), 2),
            "max": round(values[-1], 2),
            "matthew_percentile": m_pctile,
        },
        cache_seconds=120,
    )
