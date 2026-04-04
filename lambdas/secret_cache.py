"""
secret_cache.py — In-memory secret caching for Lambda warm containers.

Lambda warm containers persist between invocations (5-45 minutes typically).
This module caches Secrets Manager responses to avoid redundant API calls,
reducing Secrets Manager costs by ~90%.

Cache TTL: 15 minutes (secrets rarely change mid-execution).

Usage:
    from secret_cache import get_secret
    value = get_secret("life-platform/whoop", secretsmanager_client)
    # Returns cached SecretString on warm invocations

v1.0.0 — 2026-04-03 (COST-OPT-1)
"""

import time
import json
import logging

logger = logging.getLogger(__name__)

_cache = {}
_TTL_SECONDS = 900  # 15 minutes


def get_secret(secret_id, client):
    """Get a secret value with in-memory caching.

    Args:
        secret_id: Secrets Manager secret name/ARN
        client: boto3 secretsmanager client

    Returns:
        SecretString (raw string, caller should json.loads if needed)
    """
    now = time.time()
    entry = _cache.get(secret_id)
    if entry and (now - entry["ts"]) < _TTL_SECONDS:
        return entry["value"]

    value = client.get_secret_value(SecretId=secret_id)["SecretString"]
    _cache[secret_id] = {"value": value, "ts": now}
    logger.debug("Secret %s fetched (cache miss)", secret_id)
    return value


def get_secret_json(secret_id, client):
    """Get a secret value as parsed JSON dict with caching."""
    return json.loads(get_secret(secret_id, client))


def invalidate(secret_id=None):
    """Clear cache for a specific secret or all secrets."""
    if secret_id:
        _cache.pop(secret_id, None)
    else:
        _cache.clear()
