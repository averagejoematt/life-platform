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
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    CORS_HEADERS,
    PT,
    S3_REGION,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _is_blocked_vice,
    _load_s3_json,
    _ok,
    logger,
    table,
)

# DynamoDB-backed rate limiting (survives warm-container distribution + cold
# starts). The in-memory stores below are now only a fail-open fallback used if
# the shared rate_limiter module is unavailable. The site_api role already
# permits UpdateItem on the RATE#* partition (no IAM change needed).
try:
    from rate_limiter import check_rate_limit as _ddb_rate_check

    _RATE_LIMITER_READY = True
except Exception:  # pragma: no cover — import guard
    _RATE_LIMITER_READY = False

# ── Module-owned globals ──────────────────────────────────
# These were originally module-level in site_api_lambda; they're only
# touched by the handlers in this file, so they move with the cluster.
_token_secret_cache = None
_nudge_rate_store: dict = {}  # ACCT-2: ip_hash+category -> list of timestamps (fallback only)


def _extract_client_ip(event: dict) -> str:
    """Return the original client IP behind CloudFront.

    requestContext.http.sourceIp is the CloudFront edge IP — varies per
    request, useless for IP-based rate-limiting. CloudFront forwards the
    real client in x-forwarded-for; take the first entry. Falls back to
    sourceIp (and "unknown") only if the header is missing.

    Matches the pattern in email_subscriber_lambda.py:lambda_handler;
    same bug, same shape. (Task #108 — burned in 2026-05-29.)
    """
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    xff = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return (
        xff
        or event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )


_nudge_counts: dict = {}  # ACCT-2: category -> approximate count
_finding_rate_store: dict = {}  # NEW-1: ip_hash -> list of timestamps for submit_finding
# S3 config caches for experiment + challenge endpoints
_challenges_cache = None
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


def _handle_verify_subscriber(event: dict) -> dict:
    """
    GET /api/verify_subscriber?email=...
    Returns a 24hr token if the email is a confirmed subscriber.
    Frontend stores token in sessionStorage and sends as X-Subscriber-Token header
    to unlock 20 questions/hr instead of the default 5.
    """
    params = event.get("queryStringParameters") or {}
    email = (params.get("email") or "").strip().lower()

    if not email or "@" not in email or len(email) > 254:
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Valid email required"}),
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
    import time as _time

    source_ip = _extract_client_ip(event)
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
    if _RATE_LIMITER_READY:
        allowed, _rem, _retry = _ddb_rate_check(
            table, endpoint=f"nudge:{category}", ip_hash=ip_hash, limit=1, window_seconds=3600, fail_open=True
        )
    else:
        now = int(_time.time())
        rate_key = f"{ip_hash}:{category}"
        recent = [t for t in _nudge_rate_store.get(rate_key, []) if t > now - 3600]
        allowed = not recent
        if allowed:
            recent.append(now)
            _nudge_rate_store[rate_key] = recent[-10:]
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
    import time as _time

    source_ip = _extract_client_ip(event)
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]

    # Rate limit: FINDING_RATE_LIMIT per IP per hour — DynamoDB-backed (survives
    # cold starts; in-memory fallback only).
    if _RATE_LIMITER_READY:
        allowed, remaining, _retry = _ddb_rate_check(
            table, endpoint="submit_finding", ip_hash=ip_hash, limit=FINDING_RATE_LIMIT, window_seconds=3600, fail_open=True
        )
    else:
        now = int(_time.time())
        recent = [t for t in _finding_rate_store.get(ip_hash, []) if t > now - 3600]
        allowed = len(recent) < FINDING_RATE_LIMIT
        if allowed:
            recent.append(now)
            _finding_rate_store[ip_hash] = recent[-10:]
        remaining = max(0, FINDING_RATE_LIMIT - len(recent))
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
    experiments = library.get("experiments", [])
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
        ids = frozenset((e.get("id") or "").lower() for e in library.get("experiments", []) if e.get("id"))
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
    source_ip = _extract_client_ip(event)
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
    source_ip = _extract_client_ip(event)
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
    source_ip = _extract_client_ip(event)
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
    source_ip = _extract_client_ip(event)
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
    global _challenges_cache
    if _challenges_cache is None:
        _challenges_cache = _load_s3_json("config/challenges_catalog.json", "challenges_catalog")
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
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error(400, "Invalid JSON body")

    challenge_id = (body.get("challenge_id") or "").strip()
    completed = body.get("completed")
    note = (body.get("note") or "").strip()[:500]
    date_str = (body.get("date") or "").strip()

    if not challenge_id:
        return _error(400, "challenge_id required")
    if completed is None:
        return _error(400, "completed (true/false) required")

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


def _handle_experiment_suggest(event: dict) -> dict:
    """POST /api/experiment_suggest — Store reader experiment suggestion."""
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
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps({"status": "received"})}
    except Exception as e:
        logger.error(f"[site_api] experiment_suggest failed: {e}")
        return _error(500, "Failed to submit suggestion")
