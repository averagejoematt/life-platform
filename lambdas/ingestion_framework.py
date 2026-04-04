"""
ingestion_framework.py — SIMP-2: Common ingestion framework for all data source Lambdas.

Extracts the 80% shared code across 13 ingestion Lambdas into a single reusable
framework. Source-specific logic (API calls, schema mapping) provided as callbacks.

USAGE:
    from ingestion_framework import IngestionConfig, run_ingestion

    config = IngestionConfig(
        source_name="whoop",
        secret_id="life-platform/whoop",
        s3_archive_prefix="raw/whoop",
        enable_gap_detection=True,
    )

    def authenticate(secret_data):
        # Source-specific auth. Return credentials dict.
        access_token = refresh_oauth(secret_data)
        return {"access_token": access_token, **secret_data}

    def fetch_day(creds, date_str):
        # Fetch one day from source API. Return raw response dict (or None to skip).
        return whoop_api_get(f"/v1/recovery?date={date_str}", creds["access_token"])

    def transform(raw, date_str):
        # Map raw API response to platform DDB schema. Return list of DDB items.
        return [{
            "source": "whoop",
            "hrv": raw.get("hrv"),
            "recovery_score": raw.get("recovery"),
            ...
        }]

    def lambda_handler(event, context):
        return run_ingestion(config, authenticate, fetch_day, transform, event, context)

FRAMEWORK HANDLES:
    - AWS client initialization (DynamoDB, S3, Secrets Manager)
    - Secret loading
    - Gap detection (query DDB for last N days, find missing dates)
    - Date override support (EventBridge event payload)
    - DATA-2 validation (ingestion_validator)
    - REL-3 item size guard (safe_put_item)
    - S3 raw data archival
    - Schema version tagging
    - Structured logging (OBS-1 platform_logger)
    - Decimal conversion for DynamoDB
    - Error handling and summary response

SOURCE-SPECIFIC CALLBACKS:
    - authenticate(secret_data) -> credentials dict
    - fetch_day(credentials, date_str) -> raw response dict (or None)
    - transform(raw_response, date_str) -> list of DDB items (without pk/sk/metadata)
    - Optional: post_store(items, date_str) -> called after successful DDB writes (e.g., supplement bridge)

v1.0.0 — SIMP-2 (2026-03-09)
"""

import json
import os
import time
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

class IngestionConfig:
    """Per-source configuration. Passed to run_ingestion()."""

    def __init__(
        self,
        source_name: str,
        secret_id: str = None,
        s3_archive_prefix: str = None,
        schema_version: int = 1,
        enable_gap_detection: bool = False,
        lookback_days: int = None,
        enable_item_size_guard: bool = False,
        enable_secret_writeback: bool = False,
        gap_rate_limit_seconds: float = 1.0,
    ):
        self.source_name = source_name
        self.secret_id = secret_id
        self.s3_archive_prefix = s3_archive_prefix or f"raw/{source_name}"
        self.schema_version = schema_version
        self.enable_gap_detection = enable_gap_detection
        self.lookback_days = lookback_days or int(os.environ.get("LOOKBACK_DAYS", "7"))
        self.enable_item_size_guard = enable_item_size_guard
        self.enable_secret_writeback = enable_secret_writeback
        self.gap_rate_limit_seconds = gap_rate_limit_seconds

        # Environment
        self.region = os.environ.get("AWS_REGION", "us-west-2")
        self.table_name = os.environ.get("TABLE_NAME", "life-platform")
        self.s3_bucket = os.environ["S3_BUCKET"]
        self.user_id = os.environ["USER_ID"]


# ══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _floats_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(i) for i in obj]
    return obj


def _init_logger(source_name):
    """Try to use platform_logger (OBS-1), fall back to print."""
    try:
        from platform_logger import get_logger
        return get_logger(source_name)
    except ImportError:
        import logging
        logger = logging.getLogger(source_name)
        logger.setLevel(logging.INFO)
        # Add set_date no-op for compatibility
        if not hasattr(logger, 'set_date'):
            logger.set_date = lambda d: None
        return logger


def _init_aws(config):
    """Initialize AWS clients."""
    dynamodb = boto3.resource("dynamodb", region_name=config.region)
    table = dynamodb.Table(config.table_name)
    s3 = boto3.client("s3", region_name=config.region)
    secrets = None
    if config.secret_id:
        secrets = boto3.client("secretsmanager", region_name=config.region)
    return table, s3, secrets


# ══════════════════════════════════════════════════════════════════════════════
# GAP DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _find_missing_dates(table, config, logger):
    """Query DDB for last N days, return sorted list of missing date strings."""
    from boto3.dynamodb.conditions import Key

    pk = f"USER#{config.user_id}#SOURCE#{config.source_name}"
    today = datetime.now(timezone.utc).date()
    check_dates = set()
    for i in range(1, config.lookback_days + 1):
        check_dates.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))

    oldest = min(check_dates)
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) &
            Key("sk").between(f"DATE#{oldest}", f"DATE#{today.strftime('%Y-%m-%d')}"),
        ProjectionExpression="sk",
    )
    existing = {item["sk"][5:] for item in resp.get("Items", [])}
    missing = sorted(check_dates - existing)

    if missing:
        logger.info(f"[GAP-FILL] Found {len(missing)} missing dates: {missing}")
    else:
        logger.info(f"[GAP-FILL] No gaps in last {config.lookback_days} days")

    return missing


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATE + STORE (DATA-2 + REL-3)
# ══════════════════════════════════════════════════════════════════════════════

def _store_item(table, s3, config, item, date_str, logger):
    """Validate (DATA-2), size-guard (REL-3), and store a single DDB item.

    Returns True if stored successfully, False if skipped.
    """
    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item
        vr = _validate_item(config.source_name, item, date_str)
        if vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping {config.source_name} DDB write "
                         f"for {date_str}: {vr.errors}")
            vr.archive_to_s3(s3, bucket=config.s3_bucket, item=item)
            return False
        if vr.warnings:
            logger.warning(f"[DATA-2] Validation warnings for "
                           f"{config.source_name}/{date_str}: {vr.warnings}")
    except ImportError:
        pass  # Validator not available — proceed without

    # REL-3: Item size guard (optional, for large-item sources)
    if config.enable_item_size_guard:
        try:
            from item_size_guard import safe_put_item
            safe_put_item(table, item, source=config.source_name, date_str=date_str)
            return True
        except ImportError:
            logger.warning("[WARN] item_size_guard not available — falling back to direct put_item")

    table.put_item(Item=item)
    return True


def _archive_raw(s3, config, date_str, raw_data):
    """Archive raw API response to S3."""
    try:
        year = date_str[:4]
        month = date_str[5:7]
        key = f"{config.s3_archive_prefix}/{year}/{month}/{date_str}.json"
        s3.put_object(
            Bucket=config.s3_bucket,
            Key=key,
            Body=json.dumps({
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "raw": raw_data,
            }, default=str),
            ContentType="application/json",
        )
    except Exception as e:
        # S3 archive is non-fatal but losing audit trail is concerning — log as ERROR
        print(f"[ERROR] S3 archive failed for {config.source_name}/{date_str} — audit trail lost: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_ingestion(config, authenticate_fn, fetch_day_fn, transform_fn,
                  event, context, post_store_fn=None):
    """Execute the full ingestion pipeline.

    Args:
        config:          IngestionConfig instance
        authenticate_fn: (secret_data: dict) -> credentials dict
                         Called once. If config.secret_id is None, receives empty dict.
                         If config.enable_secret_writeback, returned dict is saved back.
        fetch_day_fn:    (credentials: dict, date_str: str) -> raw response dict | None
                         Called per date. Return None to skip a date.
        transform_fn:    (raw: dict, date_str: str) -> list[dict]
                         Map raw response to list of DDB record dicts (without pk/sk/metadata).
                         Each dict must have a "source" key. Optional "sk_suffix" for sub-records.
        event:           Lambda event dict
        context:         Lambda context
        post_store_fn:   Optional (items: list[dict], date_str: str) -> None
                         Called after successful DDB writes for a date (e.g., supplement bridge).

    Returns:
        Lambda response dict with statusCode and body.
    """
    logger = _init_logger(config.source_name)
    table, s3, secrets_client = _init_aws(config)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.set_date(today)

    logger.info(f"Ingestion starting: source={config.source_name}")

    # ── Load secrets + authenticate ──
    credentials = {}
    if config.secret_id and secrets_client:
        try:
            try:
                from secret_cache import get_secret_json
                secret_data = get_secret_json(config.secret_id, secrets_client)
            except ImportError:
                raw_secret = secrets_client.get_secret_value(SecretId=config.secret_id)["SecretString"]
                secret_data = json.loads(raw_secret)
        except Exception as e:
            logger.error(f"Failed to load secret {config.secret_id}: {e}")
            return {"statusCode": 500, "body": json.dumps({"error": f"Secret load failed: {e}"})}

        credentials = authenticate_fn(secret_data)

        # Write back updated credentials (OAuth token refresh)
        if config.enable_secret_writeback and credentials:
            try:
                secrets_client.update_secret(
                    SecretId=config.secret_id,
                    SecretString=json.dumps(credentials),
                )
                logger.info("Credentials updated in Secrets Manager")
            except Exception as e:
                logger.warning(f"Secret writeback failed (non-fatal): {e}")
    else:
        credentials = authenticate_fn({})

    # ── Determine dates to ingest ──
    date_override = event.get("date_override") if isinstance(event, dict) else None

    if date_override:
        # Mode 1: Explicit date
        if date_override == "today":
            dates_to_ingest = [today]
        else:
            dates_to_ingest = [date_override]
        logger.info(f"Single-day mode: {dates_to_ingest[0]}")

    elif config.enable_gap_detection:
        # Mode 2: Gap-aware lookback
        dates_to_ingest = _find_missing_dates(table, config, logger)
        if not dates_to_ingest:
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "No gaps to fill",
                    "source": config.source_name,
                    "lookback_days": config.lookback_days,
                }),
            }
    else:
        # Mode 3: Default — yesterday + today
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        dates_to_ingest = [yesterday, today]

    # ── Ingest each date ──
    results = {}
    records_written = 0
    errors = 0

    for i, date_str in enumerate(dates_to_ingest):
        try:
            # Fetch
            raw = fetch_day_fn(credentials, date_str)
            if raw is None:
                logger.info(f"  {date_str}: no data (fetch returned None)")
                results[date_str] = "no_data"
                continue

            # Transform
            items = transform_fn(raw, date_str)
            if not items:
                logger.info(f"  {date_str}: no records after transform")
                results[date_str] = "no_records"
                continue

            # Store each item
            stored_items = []
            for record in items:
                source = record.pop("source", config.source_name)
                sk_suffix = record.pop("sk_suffix", "")

                pk = f"USER#{config.user_id}#SOURCE#{source}"
                sk = f"DATE#{date_str}{sk_suffix}"

                db_item = _floats_to_decimal({
                    "pk": pk,
                    "sk": sk,
                    "source": source,
                    "schema_version": config.schema_version,
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                    **record,
                })

                if _store_item(table, s3, config, db_item, date_str, logger):
                    records_written += 1
                    stored_items.append(db_item)

            # Post-store hook (e.g., supplement bridge)
            if post_store_fn and stored_items:
                try:
                    post_store_fn(stored_items, date_str)
                except Exception as e:
                    logger.warning(f"post_store_fn failed for {date_str}: {e}")

            # Archive raw to S3
            _archive_raw(s3, config, date_str, raw)

            results[date_str] = len(stored_items)
            logger.info(f"  {date_str}: {len(stored_items)} record(s) stored")

        except Exception as e:
            logger.error(f"  {date_str}: ERROR — {e}")
            results[date_str] = f"error: {e}"
            errors += 1

        # Rate limit between gap-fill days
        if i < len(dates_to_ingest) - 1 and config.enable_gap_detection:
            time.sleep(config.gap_rate_limit_seconds)

    # ── Summary ──
    summary = {
        "source": config.source_name,
        "dates_processed": len(dates_to_ingest),
        "records_written": records_written,
        "errors": errors,
        "results": results,
    }
    if config.enable_gap_detection:
        summary["mode"] = "gap_fill"
        summary["lookback_days"] = config.lookback_days

    logger.info(f"Ingestion complete: {records_written} records, {errors} errors")

    return {
        "statusCode": 200 if errors == 0 else 207,
        "body": json.dumps(summary, default=str),
    }
