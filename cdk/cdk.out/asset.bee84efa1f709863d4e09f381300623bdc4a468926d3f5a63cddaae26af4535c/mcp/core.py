"""
Core data access: profile, caching, DynamoDB queries, serialisation.
"""
import json
import time
import concurrent.futures
import logging
from decimal import Decimal
from datetime import datetime
from boto3.dynamodb.conditions import Key

from mcp.config import (
    table, secrets, logger, USER_PREFIX, PROFILE_PK, PROFILE_SK,
    CACHE_PK, CACHE_TTL_SECS, MEM_CACHE_TTL, API_SECRET_NAME,
    _DEFAULT_SOURCE_OF_TRUTH, _LEAN_STRIP, FIELD_ALIASES,
)

# ── Serialisation ──

def decimal_to_float(obj):
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    if isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


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
        table.put_item(Item={
            "pk":           CACHE_PK,
            "sk":           f"TOOL#{cache_key}",
            "payload":      json.dumps(data, default=str),
            "ttl":          Decimal(str(ttl_epoch)),
            "computed_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        logger.info(f"[cache:ddb] stored — {cache_key}")
    except Exception as e:
        logger.warning(f"[cache:ddb] write error for {cache_key}: {e}")


# ── DynamoDB queries ──

def query_source(source, start_date, end_date, lean=False):
    """Query DynamoDB by source + date range with full pagination."""
    pk = f"{USER_PREFIX}{source}"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}~"
        )
    }
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


def parallel_query_sources(sources, start_date, end_date, lean=False):
    """Query multiple DynamoDB sources concurrently."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sources), 5)) as pool:
        future_to_src = {
            pool.submit(query_source, src, start_date, end_date, lean): src
            for src in sources
        }
        for future in concurrent.futures.as_completed(future_to_src):
            src = future_to_src[future]
            try:
                results[src] = future.result()
            except Exception as e:
                logger.warning(f"parallel_query_sources failed for {src}: {e}")
                results[src] = []
    return results


def query_source_range(source, start_date, end_date):
    """Alias for query_source used by some tools."""
    return query_source(source, start_date, end_date)


def date_diff_days(start, end):
    try:
        return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    except Exception:
        return 0


def resolve_field(source, field):
    aliases = FIELD_ALIASES.get(source, {})
    return aliases.get(field, field)
