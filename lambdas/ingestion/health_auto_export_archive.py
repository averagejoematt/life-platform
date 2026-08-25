"""
health_auto_export_archive.py — raw-S3 archive writers for the HAE webhook path.

Extracted from `ingestion/health_auto_export_lambda.py` (#3119, the #1400/#1654/
#2604 facade + cohesive-sibling shape — see `ai/ai_transport.py` for the same
split applied to `ai/ai_calls.py`). health_auto_export_lambda.py was baselined
at exactly 1779/1779 on the #1665 module-size ratchet — zero headroom — so the
four DIL-025 replay-safety fixes (a content-hashed raw-archive key, a
monotonic guard on the reading-count fields, a fail-toward-history dedup-map
fix, and the written-up concurrency acceptance) could not land there without
raising a baseline, which the #2610 earned-headroom policy forbids absent an
extraction.

The seam is a real one, not a line-count convenience: everything here is
*archiving individual readings/payloads to raw S3* — always the same
read-merge-dedup-put shape, keyed on the reading's own `time`/`id` (or, for
the whole-payload archive, a content hash of the payload). Nothing here
parses HAE's metric schema, aggregates a day, or touches DynamoDB — that all
stays in health_auto_export_lambda.py.

Each function takes its S3 client + bucket/user explicitly rather than
reading a module global, so the split needs no shared mutable state and this
module is independently unit-testable. health_auto_export_lambda.py keeps
thin wrappers under the ORIGINAL names/signatures that forward its own
`s3_client`/`S3_BUCKET`/`USER_ID` at call time — so `hae.save_cgm_readings_to_s3
(date_str, readings)` and the existing `monkeypatch.setattr(hae, "s3_client",
...)` test pattern are both unchanged (no contract change, per the ratchet's
own docstring).
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights (same
# setup as health_auto_export_lambda.py; duplicated rather than imported so
# this module has no dependency on its sibling).
try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)


def save_cgm_readings_to_s3(s3_client, bucket, user_id, date_str, readings):
    """Save individual CGM readings to S3 for detailed analysis."""
    s3_key = f"raw/{user_id}/cgm_readings/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    # Merge with existing readings for this day (idempotent)
    existing = []
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_cgm_readings %s: %s", s3_key, e)

    # Deduplicate by timestamp
    existing_times = {r["time"] for r in existing}
    new_readings = [r for r in readings if r["time"] not in existing_times]

    if new_readings:
        merged = sorted(existing + new_readings, key=lambda r: r["time"] or "")
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_readings)
    return 0


def save_bp_readings_to_s3(s3_client, bucket, user_id, date_str, readings):
    """Save individual BP readings to S3 for detailed analysis (v1.4.0)."""
    s3_key = f"raw/{user_id}/blood_pressure/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    existing = []
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_bp_readings %s: %s", s3_key, e)

    existing_times = {r["time"] for r in existing}
    new_readings = [r for r in readings if r["time"] not in existing_times]

    if new_readings:
        merged = sorted(existing + new_readings, key=lambda r: r["time"] or "")
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_readings)
    return 0


def save_state_of_mind_to_s3(s3_client, bucket, user_id, date_str, entries):
    """Save individual State of Mind check-ins to S3 (v1.5.0)."""
    s3_key = f"raw/{user_id}/state_of_mind/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    existing = []
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_state_of_mind %s: %s", s3_key, e)

    # Deduplicate by timestamp
    existing_times = {e.get("time") for e in existing}
    new_entries = [e for e in entries if e.get("time") not in existing_times]

    if new_entries:
        merged = sorted(existing + new_entries, key=lambda e: e.get("time") or "")
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_entries)
    return 0


def save_workouts_to_s3(s3_client, bucket, user_id, date_str, workouts_list):
    """Save individual workout records to S3, merging with existing (v1.6.0)."""
    s3_key = f"raw/{user_id}/workouts/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    existing = []
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_workouts %s: %s", s3_key, e)

    # Deduplicate by workout id
    existing_ids = {w.get("id") for w in existing if w.get("id")}
    new_workouts = [w for w in workouts_list if w.get("id") and w["id"] not in existing_ids]

    if new_workouts:
        merged = existing + new_workouts
        merged.sort(key=lambda w: w.get("start", ""))
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_workouts)
    return 0


def save_raw_payload(s3_client, bucket, user_id, payload):
    """Archive the raw webhook payload to S3.

    #3119: the leaf used to be pure wall-clock (unbounded growth on
    delete-protected raw/* — every redelivery minted a new object). It's now a
    content hash of the day's payload: identical bytes the same UTC day
    overwrite the same key; genuinely different payloads still get distinct
    keys. See `lambdas/ingestion/source_registry.py`'s `apple_health` raw_layout
    `filename_legacy` facet for the pre-#3119 `DD_HHMMSS.json` generation this
    replaced (both are resolvable — #3119 is a DIL-028 generation flip, not a
    cutover).
    """
    now = datetime.now(timezone.utc)
    body = json.dumps(payload, default=str, sort_keys=True)
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    s3_key = f"raw/{user_id}/health_auto_export/{now.strftime('%Y/%m/%d')}_{content_hash}.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=body,
        ContentType="application/json",
    )
    return s3_key
