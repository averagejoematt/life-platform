"""
Core data access: profile, caching, DynamoDB queries, serialisation.
"""

import concurrent.futures
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from boto3.dynamodb.conditions import Key

# ── Serialisation ──
from digest_utils import d2f as decimal_to_float  # shared bundled helpers (#970)

from mcp.config import (
    _DEFAULT_SOURCE_OF_TRUTH,
    _LEAN_STRIP,
    API_SECRET_NAME,
    CACHE_PK,
    CACHE_TTL_SECS,
    FIELD_ALIASES,
    MEM_CACHE_TTL,
    PROFILE_PK,
    PROFILE_SK,
    USER_ID,
    USER_PREFIX,
    logger,
    secrets,
    table,
)


def get_api_key():
    try:
        return secrets.get_secret_value(SecretId=API_SECRET_NAME)["SecretString"]
    except Exception as e:
        logger.warning(f"Could not retrieve API key: {e}")
        return None


# ── Profile cache ──
_PROFILE_CACHE = None


def get_profile():
    global _PROFILE_CACHE
    if _PROFILE_CACHE is not None:
        return _PROFILE_CACHE
    try:
        resp = table.get_item(Key={"pk": PROFILE_PK, "sk": PROFILE_SK})
        _PROFILE_CACHE = decimal_to_float(resp.get("Item", {}))
    except Exception as e:
        logger.warning(f"Could not load profile: {e}")
        _PROFILE_CACHE = {}
    return _PROFILE_CACHE


def get_sot(domain: str) -> str:
    """Return the source-of-truth source name for a given domain."""
    profile = get_profile()
    sot_overrides = profile.get("source_of_truth", {})
    return sot_overrides.get(domain, _DEFAULT_SOURCE_OF_TRUTH.get(domain, "strava"))


# ── In-memory cache ──
_MEM_CACHE: dict = {}


def mem_cache_get(key: str):
    entry = _MEM_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < MEM_CACHE_TTL:
        logger.info(f"[cache:mem] hit — {key}")
        return entry["data"]
    return None


def mem_cache_set(key: str, data):
    _MEM_CACHE[key] = {"data": data, "ts": time.time()}
    logger.info(f"[cache:mem] stored — {key}")


# ── DynamoDB pre-computed cache ──


def ddb_cache_get(cache_key: str):
    """Read a pre-computed result from DynamoDB. Returns None on miss/expiry."""
    try:
        resp = table.get_item(Key={"pk": CACHE_PK, "sk": f"TOOL#{cache_key}"})
        item = resp.get("Item")
        if not item:
            return None
        ttl = item.get("ttl")
        if ttl and float(ttl) < time.time():
            logger.info(f"[cache:ddb] stale — {cache_key}")
            return None
        payload = item.get("payload")
        if payload:
            logger.info(f"[cache:ddb] hit — {cache_key}")
            return json.loads(payload)
    except Exception as e:
        logger.warning(f"[cache:ddb] read error for {cache_key}: {e}")
    return None


def ddb_cache_set(cache_key: str, data):
    """Write a pre-computed result to DynamoDB cache with a TTL."""
    try:
        ttl_epoch = int(time.time()) + CACHE_TTL_SECS
        table.put_item(
            Item={
                "pk": CACHE_PK,
                "sk": f"TOOL#{cache_key}",
                "payload": json.dumps(data, default=str),
                "ttl": Decimal(str(ttl_epoch)),
                "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        logger.info(f"[cache:ddb] stored — {cache_key}")
    except Exception as e:
        logger.warning(f"[cache:ddb] write error for {cache_key}: {e}")


# ── OAuth authorization-code store (SEC-01 / #779) ──
# The remote MCP auth flow must not mint a bearer for an unbound request. /authorize
# issues a single-use, short-lived code bound to the client's PKCE challenge and
# redirect_uri; /token may only exchange a code this server actually issued. Codes
# live in the single table under a dedicated partition with a DDB TTL, and are
# consumed atomically (delete-if-exists) so a code can never be replayed.
_OAUTH_PK = f"OAUTH#{USER_ID}"
OAUTH_CODE_TTL_SECS = 600  # 10 min — an auth code is exchanged immediately in practice


def oauth_code_store(code: str, code_challenge: str, code_challenge_method: str, redirect_uri: str) -> bool:
    """Persist a server-issued authorization code with its PKCE binding. Returns True on success."""
    try:
        ttl_epoch = int(time.time()) + OAUTH_CODE_TTL_SECS
        table.put_item(
            Item={
                "pk": _OAUTH_PK,
                "sk": f"CODE#{code}",
                "code_challenge": code_challenge or "",
                "code_challenge_method": (code_challenge_method or "").upper(),
                "redirect_uri": redirect_uri or "",
                "ttl": Decimal(str(ttl_epoch)),
                "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        return True
    except Exception as e:
        logger.warning(f"[oauth] code store failed: {e}")
        return False


def oauth_code_consume(code: str):
    """Atomically consume a one-time authorization code. Returns the stored binding
    dict if the code existed, was unexpired, and had not already been consumed; else
    None. A conditional UpdateItem (set consumed=true only if the code exists and is
    unconsumed) is the atomic single-use gate — a forged or replayed code fails the
    condition. UpdateItem is used rather than DeleteItem because the MCP role's
    DeleteItem is deliberately scoped to the meal-prune partition only (see
    role_policies.mcp_server); the item is left to expire via its TTL."""
    if not code:
        return None
    try:
        # `consumed` is a DynamoDB reserved word — alias it via ExpressionAttributeNames.
        resp = table.update_item(
            Key={"pk": _OAUTH_PK, "sk": f"CODE#{code}"},
            UpdateExpression="SET #consumed = :t",
            ConditionExpression="attribute_exists(sk) AND attribute_not_exists(#consumed)",
            ExpressionAttributeNames={"#consumed": "consumed"},
            ExpressionAttributeValues={":t": True},
            ReturnValues="ALL_NEW",
        )
    except Exception as e:
        # ConditionalCheckFailedException (unknown/replayed code) lands here too — all
        # failure modes collapse to "invalid code", which is the correct client signal.
        logger.warning(f"[oauth] code consume rejected: {type(e).__name__}")
        return None
    item = resp.get("Attributes") or {}
    ttl = item.get("ttl")
    if ttl and float(ttl) < time.time():
        # DDB TTL deletion can lag; enforce expiry ourselves.
        return None
    return {
        "code_challenge": item.get("code_challenge", ""),
        "code_challenge_method": (item.get("code_challenge_method") or "").upper(),
        "redirect_uri": item.get("redirect_uri", ""),
    }


# ── Remote-session bearer store (SEC / #893) ──
# #779 hardened the /token *code exchange* (single-use, PKCE-bound, redirect-checked),
# but /token still handed back the permanent, key-derived Desktop bearer — so anyone
# who completes the (auto-approving) OAuth flow received a credential that never
# expires. Address possession thus implied a permanent bearer. Fix: /token now mints a
# random, short-lived, individually-revocable session bearer stored here. The static
# Desktop bearer path (hmac of the API key) is UNCHANGED — this is purely additive, so
# Claude Desktop keeps working while the remote (claude.ai) path gets expiring,
# revocable tokens that silently re-authorize on expiry.
SESSION_TOKEN_TTL_SECS = 86400  # 24h — matches the historical expires_in the client already expects
SESSION_TOKEN_PREFIX = "lps_"  # noqa: S105 — token *prefix* label, not a secret value; distinct from the static "lp_" Desktop bearer


def session_token_issue():
    """Mint + persist a random, short-lived session bearer. Returns the token string,
    or None if the store write failed. 256 bits of uuid4 (os.urandom-backed) entropy,
    mirroring the opaque-code idiom in _handle_authorize."""
    token = SESSION_TOKEN_PREFIX + uuid.uuid4().hex + uuid.uuid4().hex
    try:
        ttl_epoch = int(time.time()) + SESSION_TOKEN_TTL_SECS
        table.put_item(
            Item={
                "pk": _OAUTH_PK,
                "sk": f"SESSION#{token}",
                "ttl": Decimal(str(ttl_epoch)),
                "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        return token
    except Exception as e:
        logger.warning(f"[oauth] session token store failed: {e}")
        return None


def session_token_valid(token: str) -> bool:
    """True iff `token` is a known, unexpired, unrevoked session bearer. Expiry is
    enforced in-process because DDB TTL deletion can lag by up to ~48h; an explicit
    `revoked` flag allows immediate revocation ahead of TTL."""
    if not token or not token.startswith(SESSION_TOKEN_PREFIX):
        return False
    try:
        resp = table.get_item(Key={"pk": _OAUTH_PK, "sk": f"SESSION#{token}"})
    except Exception as e:
        logger.warning(f"[oauth] session token lookup error: {type(e).__name__}")
        return False
    item = resp.get("Item")
    if not item or item.get("revoked"):
        return False
    ttl = item.get("ttl")
    if ttl and float(ttl) < time.time():
        return False
    return True


def session_token_revoke(token: str) -> bool:
    """Revoke a session bearer immediately (sets revoked=true; the row still TTL-expires).
    Operational kill-switch for a leaked token. Uses a conditional UpdateItem because the
    MCP role's DeleteItem is scoped to the meal-prune partition only (role_policies.mcp_server)."""
    if not token or not token.startswith(SESSION_TOKEN_PREFIX):
        return False
    try:
        table.update_item(
            Key={"pk": _OAUTH_PK, "sk": f"SESSION#{token}"},
            UpdateExpression="SET #revoked = :t",
            ConditionExpression="attribute_exists(sk)",
            ExpressionAttributeNames={"#revoked": "revoked"},
            ExpressionAttributeValues={":t": True},
        )
        return True
    except Exception as e:
        logger.warning(f"[oauth] session token revoke rejected: {type(e).__name__}")
        return False


# ── DynamoDB queries ──

import re

_SAFE_SOURCE = re.compile(r"^[a-zA-Z0-9_]+$")

# ADR-058: phase filter — hides phase=pilot records by default. Records without
# a phase attribute (genome, profile, config, board) pass through.
_PHASE_FILTER_EXPRESSION = "(#phase = :phase_experiment OR attribute_not_exists(#phase))"
_PHASE_FILTER_NAMES = {"#phase": "phase"}
_PHASE_FILTER_VALUES = {":phase_experiment": "experiment"}


def _apply_phase_filter(kwargs: dict, include_pilot: bool = False) -> dict:
    if include_pilot:
        return kwargs
    out = dict(kwargs)
    existing = out.get("FilterExpression")
    out["FilterExpression"] = f"({existing}) AND {_PHASE_FILTER_EXPRESSION}" if existing else _PHASE_FILTER_EXPRESSION
    names = dict(out.get("ExpressionAttributeNames") or {})
    names.update(_PHASE_FILTER_NAMES)
    out["ExpressionAttributeNames"] = names
    values = dict(out.get("ExpressionAttributeValues") or {})
    values.update(_PHASE_FILTER_VALUES)
    out["ExpressionAttributeValues"] = values
    return out


def query_source(source, start_date, end_date, lean=False, include_pilot=False):
    """Query DynamoDB by source + date range with full pagination. ADR-058: phase=pilot hidden by default."""
    if not source or not _SAFE_SOURCE.match(source):
        logger.warning(f"query_source: rejected invalid source name: {source!r}")
        return []
    pk = f"{USER_PREFIX}{source}"
    kwargs = _apply_phase_filter(
        {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}~")},
        include_pilot=include_pilot,
    )
    items = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
        logger.info(f"query_source paginating {source}: {len(items)} items so far")
    raw = decimal_to_float(items)
    if lean:
        return [{k: v for k, v in item.items() if k not in _LEAN_STRIP} for item in raw]
    return raw


def parallel_query_sources(sources, start_date, end_date, lean=False, include_pilot=False):
    """Query multiple DynamoDB sources concurrently."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sources), 5)) as pool:
        future_to_src = {pool.submit(query_source, src, start_date, end_date, lean, include_pilot): src for src in sources}
        for future in concurrent.futures.as_completed(future_to_src):
            src = future_to_src[future]
            try:
                results[src] = future.result()
            except Exception as e:
                logger.warning(f"parallel_query_sources failed for {src}: {e}")
                results[src] = []
    return results


def query_source_range(source, start_date, end_date, include_pilot=False):
    """Alias for query_source used by some tools."""
    return query_source(source, start_date, end_date, include_pilot=include_pilot)


def date_diff_days(start, end):
    try:
        return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    except Exception:
        return 0


def pacific_today():
    """Today's date (YYYY-MM-DD) in Pacific time — the calendar day the data is keyed by.

    Data is keyed by the Pacific day a behavior occurred; deriving "today" from a raw
    UTC ``now`` selects tomorrow's (empty) PT day for any caller in the UTC-evening
    window. MCP single source of truth; mirrors ``lambdas/pacific_time.pacific_today``
    (the MCP bundle resolves shared modules from the layer, not lambdas/). See
    ``docs/reviews/PLATFORM_AUDIT_2026-06-30.md`` BUG-03.
    """
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def resolve_field(source, field):
    aliases = FIELD_ALIASES.get(source, {})
    return aliases.get(field, field)
