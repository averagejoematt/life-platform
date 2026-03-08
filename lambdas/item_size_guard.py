"""
item_size_guard.py — REL-3: DynamoDB 400KB item size protection

Shared utility. Imported by at-risk ingestion Lambdas (strava, macrofactor,
apple_health, health_auto_export) before calling table.put_item().

Usage:
    from item_size_guard import safe_put_item

    safe_put_item(table, item, source="strava", date_str="2026-03-08")

Behaviour:
  - Estimates item size by JSON-serialising (approximate but fast)
  - If size < WARN_THRESHOLD (300KB): put_item normally
  - If WARN_THRESHOLD <= size < HARD_LIMIT (380KB): put_item + emit CW warning metric
  - If size >= HARD_LIMIT: truncate largest list field, warn, then put_item
  - Never raises — truncation is lossy but keeps the pipeline running
  - Emits CloudWatch metric: LifePlatform/DynamoDB / ItemSizeBytes (per source)

Thresholds:
  WARN_THRESHOLD  = 307_200  bytes (300 KB) — emit metric, log warning
  HARD_LIMIT      = 389_120  bytes (380 KB) — truncate + emit metric (20KB headroom before DDB 400KB limit)
  DDB_LIMIT       = 409_600  bytes (400 KB) — DynamoDB hard limit (would raise ValidationException)
"""

import json
import os
import logging
import boto3
from decimal import Decimal

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 307_200   # 300 KB
HARD_LIMIT     = 389_120   # 380 KB — truncate before this
DDB_LIMIT      = 409_600   # 400 KB — DynamoDB hard limit

REGION       = os.environ.get("AWS_REGION", "us-west-2")
CW_NAMESPACE = "LifePlatform/DynamoDB"

_cw = None


def _get_cw():
    global _cw
    if _cw is None:
        _cw = boto3.client("cloudwatch", region_name=REGION)
    return _cw


def _estimate_size(item: dict) -> int:
    """
    Estimate DynamoDB item size in bytes.
    Uses JSON serialisation as a fast approximation.
    DynamoDB's actual calculation differs slightly (attribute names + type overhead)
    but JSON size is a reliable conservative upper bound for most items.
    """
    try:
        return len(json.dumps(item, default=str).encode("utf-8"))
    except Exception:
        # Fallback: rough estimate via repr
        return len(repr(item).encode("utf-8"))


def _find_largest_list(item: dict) -> tuple[str | None, int]:
    """Return (field_name, estimated_size) of the largest list field in the item."""
    largest_field = None
    largest_size = 0
    for k, v in item.items():
        if isinstance(v, list) and len(v) > 0:
            size = _estimate_size({k: v})
            if size > largest_size:
                largest_size = size
                largest_field = k
    return largest_field, largest_size


def _truncate_item(item: dict, target_size: int, source: str) -> dict:
    """
    Truncate the largest list field until item size <= target_size.
    Modifies a copy of the item. Logs what was truncated.
    """
    item = dict(item)  # shallow copy — don't mutate original
    for attempt in range(10):
        current_size = _estimate_size(item)
        if current_size <= target_size:
            break
        field, field_size = _find_largest_list(item)
        if not field:
            logger.warning(f"[{source}] Cannot truncate further — no list fields found. Size={current_size}")
            break
        original_len = len(item[field])
        # Remove last 20% of the list
        new_len = max(1, int(original_len * 0.8))
        item[field] = item[field][:new_len]
        logger.warning(
            f"[{source}] Truncated '{field}': {original_len} → {new_len} items "
            f"(attempt {attempt+1}, size was {current_size:,} bytes)"
        )
    return item


def _emit_size_metric(source: str, size_bytes: int) -> None:
    """Emit item size metric to CloudWatch."""
    try:
        _get_cw().put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[{
                "MetricName": "ItemSizeBytes",
                "Dimensions": [{"Name": "Source", "Value": source}],
                "Value": size_bytes,
                "Unit": "Bytes",
            }],
        )
    except Exception as e:
        logger.warning(f"[{source}] CloudWatch size metric emit failed (non-fatal): {e}")


def safe_put_item(table, item: dict, source: str = "unknown", date_str: str = "") -> dict:
    """
    Size-safe wrapper around table.put_item().

    Args:
        table:    boto3 DynamoDB Table resource
        item:     item dict to write (will not be mutated)
        source:   source name for logging/metrics (e.g. "strava", "macrofactor")
        date_str: date string for log context

    Returns:
        The item that was actually written (may be truncated copy if oversized).
    """
    size = _estimate_size(item)
    label = f"[{source}/{date_str}]" if date_str else f"[{source}]"

    if size >= HARD_LIMIT:
        logger.warning(f"{label} Item size {size:,} bytes >= HARD_LIMIT {HARD_LIMIT:,} — TRUNCATING")
        _emit_size_metric(source, size)
        item = _truncate_item(item, target_size=WARN_THRESHOLD, source=source)
        final_size = _estimate_size(item)
        logger.warning(f"{label} After truncation: {final_size:,} bytes")
        _emit_size_metric(f"{source}_truncated", final_size)
        table.put_item(Item=item)
        return item

    elif size >= WARN_THRESHOLD:
        logger.warning(f"{label} Item size {size:,} bytes >= WARN_THRESHOLD {WARN_THRESHOLD:,} — monitoring")
        _emit_size_metric(source, size)
        table.put_item(Item=item)
        return item

    else:
        # Normal path — no overhead beyond the size check itself
        table.put_item(Item=item)
        return item
