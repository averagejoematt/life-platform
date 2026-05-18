"""
compute_metadata.py — Phase 3.3 (2026-05-16): minimal observability for
compute Lambda writes. Tags every output record with `run_id` (UUID4 per
invocation) and `computed_at` (ISO timestamp).

Lighter than full idempotency: doesn't query before write, doesn't enforce
single-write. Just adds metadata so post-hoc analysis can detect double-runs
(e.g., two records with the same (pk, sk) but different run_ids written
within minutes of each other indicate accidental double-trigger).

Also emits a CloudWatch metric `LifePlatform/Compute RecordWritten` per
write so we can graph daily write counts per source. A graph showing 2x
expected count surfaces double-trigger trends.

Why not full idempotency? Compute Lambdas are intentionally re-runnable
(manual invocation for backfill, recovery). Blocking re-writes is wrong.
The OBSERVABILITY value is the win; full enforcement is overkill.

Usage:
    from compute_metadata import tag_record
    record = tag_record(record, source_id="character_sheet")
    table.put_item(Item=record)
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import boto3

# Per-invocation run_id, set lazily on first call.
_RUN_ID: str | None = None

# Per-Lambda CloudWatch client (lazy-init to avoid import-time cost).
_CW = None
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")


def _get_run_id() -> str:
    """One run_id per Lambda warm invocation. Reset to None across cold starts."""
    global _RUN_ID
    if _RUN_ID is None:
        _RUN_ID = str(uuid.uuid4())
    return _RUN_ID


def reset_run_id() -> None:
    """Force a new run_id (useful for testing or if a Lambda explicitly wants
    distinct ids per logical pass within the same invocation)."""
    global _RUN_ID
    _RUN_ID = None


def tag_record(record: dict, source_id: str = "unknown") -> dict:
    """Add run_id + computed_at to a compute output record. Emits metric.

    Mutates and returns the dict (caller can chain). Safe to call multiple
    times on the same record — last call wins.
    """
    record["run_id"] = _get_run_id()
    record["computed_at"] = datetime.now(timezone.utc).isoformat()
    _emit_write_metric(source_id)
    return record


def _emit_write_metric(source_id: str) -> None:
    global _CW
    try:
        if _CW is None:
            _CW = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        _CW.put_metric_data(
            Namespace="LifePlatform/Compute",
            MetricData=[{
                "MetricName": "RecordWritten",
                "Dimensions": [
                    {"Name": "Source", "Value": source_id},
                    {"Name": "LambdaFunction", "Value": _LAMBDA_NAME},
                ],
                "Value": 1.0,
                "Unit": "Count",
            }],
        )
    except Exception:
        pass  # Non-fatal; metric emit failure shouldn't block writes
