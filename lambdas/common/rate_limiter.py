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
    from common.rate_limiter import check_rate_limit
    allowed, remaining, retry_after = check_rate_limit(
        table, endpoint="ask", ip_hash=h, limit=5, window_seconds=3600
    )
"""

from __future__ import annotations

import logging
import time
from typing import Tuple

try:
    from common.platform_logger import get_logger

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
    fail_open: bool = True,
    cost: int = 1,
) -> Tuple[bool, int, int]:
    """Atomic per-IP rate check via DynamoDB.

    Returns: (allowed, remaining, retry_after_seconds).
    `cost` is how many tokens THIS request consumes (default 1). It exists because a
    per-REQUEST limit does not bound a per-request FAN-OUT: `/api/board_ask` makes one
    Bedrock call per persona, and the caller chooses the persona list, so a 5/hour limit
    bought one Haiku call per coach — 35/hour against a limit of 5 (#1221 box 5). Charging the fan-out
    makes the limit mean what it says. Every other caller keeps cost=1 and is unaffected.

    On any DDB error, returns (fail_open, …). Fail-open is the default — safer
    for a personal platform than blocking legit traffic on an infrastructure
    hiccup. Cost-bearing endpoints (each /api/board_ask fans out multiple
    Bedrock calls) pass fail_open=False so a DDB outage can't become an
    unmetered AI bill; they return a short retry_after since DDB blips are
    transient. Errors are logged for observability.
    """
    now = int(time.time())
    bucket_start = _bucket_for_window(now, window_seconds)
    bucket_end = bucket_start + window_seconds
    ttl = bucket_end + 3600  # +1h grace before DDB TTL evicts

    pk = f"RATE#{endpoint}#{ip_hash}"
    sk = f"HOUR#{bucket_start}"

    cost = max(1, int(cost))
    # #3419: a request that cannot fit must not CONSUME. The old unconditional
    # ADD meant a doomed fan-out (the 7-persona board click: 1+6=7 vs limit 5)
    # was rejected AND still charged the whole window, locking the reader's
    # working smaller panel out for the rest of the hour. Two guards:
    #   1. cost > limit is structurally impossible in ANY window state — reject
    #      before any write (a fresh window's attribute_not_exists would
    #      otherwise let the charge through and instantly exhaust it).
    #   2. The ADD is conditional on prior count + cost <= limit, so an
    #      over-limit request is a rejection verdict, never a charge.
    if cost > limit:
        return False, 0, max(0, bucket_end - now)

    try:
        resp = table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="ADD #c :inc SET #t = if_not_exists(#t, :ttl)",
            ConditionExpression="attribute_not_exists(#c) OR #c <= :headroom",
            ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
            ExpressionAttributeValues={":inc": cost, ":ttl": ttl, ":headroom": limit - cost},
            ReturnValues="UPDATED_NEW",
        )
    except Exception as e:
        # A conditional failure is the limiter WORKING (over limit, nothing
        # charged) — a verdict, never a DDB error, so it must not reach the
        # fail-open path and turn into an allow.
        err_code = str((getattr(e, "response", None) or {}).get("Error", {}).get("Code", ""))
        if err_code == "ConditionalCheckFailedException":
            return False, 0, max(0, bucket_end - now)
        _logger.warning(
            "rate_limit_ddb_error endpoint=%s err=%s — failing %s",
            endpoint,
            e,
            "open" if fail_open else "closed",
        )
        return (True, limit, 0) if fail_open else (False, 0, 60)

    count = int(resp.get("Attributes", {}).get("count", 1))
    remaining = max(0, limit - count)
    allowed = count <= limit
    retry_after = max(0, bucket_end - now) if not allowed else 0
    return allowed, remaining, retry_after
