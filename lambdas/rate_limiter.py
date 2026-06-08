"""
rate_limiter.py — Phase 2.1 (ADR-052 follow-up): DynamoDB-backed rate limiter.

Replaces the in-memory `_ask_rate_store` / `_board_rate_store` dicts that
fail under warm-container distribution: per-IP limits enforced only within
a single Lambda container, not globally. With 20 reserved concurrency
across multiple warm containers, a user could blow past documented limits.

Pattern:
  pk = "RATE#{endpoint}#{ip_hash}"
  sk = "HOUR#{utc_hour_bucket}"
  attributes: count (Number), ttl (Number, epoch seconds, ~2h)

Atomic increment via UpdateItem ADD; race-tolerant (slight over-count
under burst is acceptable for a personal platform).

DDB TTL on the `ttl` attribute (must be enabled on the table) auto-purges
buckets after they're irrelevant. We set ttl = bucket_end + 1h grace.

Usage:
    from rate_limiter import check_rate_limit
    allowed, remaining, retry_after = check_rate_limit(
        table, endpoint="ask", ip_hash=h, limit=5, window_seconds=3600
    )
"""

from __future__ import annotations

import logging
import time
from typing import Tuple

try:
    from platform_logger import get_logger

    _logger = get_logger("rate-limiter")
except ImportError:
    _logger = logging.getLogger("rate-limiter")
    _logger.setLevel(logging.INFO)


def _bucket_for_window(now: int, window_seconds: int) -> int:
    """Truncate the current epoch second to the start of the rate-limit window."""
    return now - (now % window_seconds)


def check_rate_limit(
    table,
    endpoint: str,
    ip_hash: str,
    limit: int,
    window_seconds: int = 3600,
) -> Tuple[bool, int, int]:
    """Atomic per-IP rate check via DynamoDB.

    Returns: (allowed, remaining, retry_after_seconds).
    On any DDB error, returns (True, limit, 0) — fail-open is safer for a
    personal platform than blocking legit traffic on infrastructure hiccup.
    Errors are logged for observability.
    """
    now = int(time.time())
    bucket_start = _bucket_for_window(now, window_seconds)
    bucket_end = bucket_start + window_seconds
    ttl = bucket_end + 3600  # +1h grace before DDB TTL evicts

    pk = f"RATE#{endpoint}#{ip_hash}"
    sk = f"HOUR#{bucket_start}"

    try:
        resp = table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="ADD #c :inc SET #t = if_not_exists(#t, :ttl)",
            ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
            ExpressionAttributeValues={":inc": 1, ":ttl": ttl},
            ReturnValues="UPDATED_NEW",
        )
    except Exception as e:
        _logger.warning("rate_limit_ddb_error endpoint=%s err=%s — failing open", endpoint, e)
        return True, limit, 0

    count = int(resp.get("Attributes", {}).get("count", 1))
    remaining = max(0, limit - count)
    allowed = count <= limit
    retry_after = max(0, bucket_end - now) if not allowed else 0
    return allowed, remaining, retry_after
