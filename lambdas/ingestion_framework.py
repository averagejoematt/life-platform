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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

# Truth audit 2026-07-10 (EIGHTSLEEP UTC double-stamp): platform data is keyed by the
# PACIFIC calendar day, but the framework derived "today" in UTC — after 5 PM PT the
# UTC day has already rolled, so refresh_today fetched TOMORROW's PT date and sources
# like Eight Sleep wrote the same night under two DATE# keys. All day-selection here
# goes through pacific_time (the single source of truth for the platform's "today");
# instant TIMESTAMPS (fetched_at/ingested_at) stay UTC ISO on purpose.
from pacific_time import pacific_now, pacific_today

# ADR-058 (2026-05-25): tag every DDB write with phase=pilot|experiment so the
# read-path phase_filter can default-deny pre-genesis data. Without this, every
# ingestion run leaves untagged records that need a periodic
# `restart_phase_tag.py --apply` sweep.
try:
    from constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE
except ImportError:
    EXPERIMENT_START_DATE = "2026-05-25"
    EXPERIMENT_PHASE_CURRENT = "experiment"

# ER-01 (2026-06-09): infra-liveness sentinel. Record per-run outcome to
# USER#system / INGEST_HEALTH#{source} + an EMF metric, so the daily heartbeat can
# tell "the user didn't log" (benign) from "the ingestion Lambda has been erroring
# for weeks" (the 44-day-outage class). Optional import — ingestion never breaks if
# the layer module is absent.
try:
    from ingest_health import SYSTEM_PK as _INGEST_SYSTEM_PK, classify_error, emf_metric_line, ingest_health_sk, update_outcome

    _INGEST_HEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover - layer-module fallback
    _INGEST_HEALTH_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# AUTH-FAILURE CIRCUIT BREAKER (ADR-052)
# ══════════════════════════════════════════════════════════════════════════════
#
# When an OAuth token expires (401) or is revoked (403), the source Lambda
# would otherwise raise on every scheduled run for days until the operator
# notices and rotates the credential — flooding the alarm channel even though
# the failure mode is well-understood and only fixable by a human.
#
# The circuit breaker writes a marker to DDB on the first auth failure. While
# the marker is fresh (<24h), subsequent invocations short-circuit with a
# statusCode 200 + "skipped" body and never reach the source API. The first
# failure still surfaces (so the operator knows to act); the next 23 hours of
# inbox spam are suppressed.
#
# The marker auto-expires after 24h via DDB TTL — so if the operator rotates
# the credential, normal behavior resumes on the next run without manual
# cleanup. A successful invocation also clears the marker immediately.

_AUTH_FAIL_SK = "AUTH_FAILURE"
_AUTH_FAIL_TTL_SECONDS = 24 * 3600  # 24 hours

# #467 (X-13): delegate to auth_breaker (same layer) instead of a private duplicate
# implementation. The behavioral difference matters: auth_breaker emits the
# LifePlatform/OAuth IngestAuthHealthy metric on every mark / short-circuit / clear,
# which the framework's local copy never did — so the fleet-wide `ingest-auth-dead`
# alarm only actually covered notion + dropbox, not the SIMP-2 framework sources
# the monitoring-stack comment claimed. Marker schema (SK, TTL, fields) is identical,
# so delegation is drop-in. Fallback copies keep local tooling importable.
try:
    from auth_breaker import (
        check_breaker as _ab_check_breaker,
        clear_failure as _ab_clear_failure,
        looks_like_auth_failure as _ab_looks_like_auth_failure,
        mark_failure as _ab_mark_failure,
    )

    _HAS_AUTH_BREAKER_MODULE = True
except ImportError:  # pragma: no cover — layer-module fallback
    _HAS_AUTH_BREAKER_MODULE = False

_AUTH_FAIL_HTTP_CODES = ("401", "403")
_AUTH_FAIL_KEYWORDS = (
    "unauthorized",
    "forbidden",
    "invalid token",
    "expired token",
    "token expired",
    "auth failed",
    "authentication failed",
)


def _looks_like_auth_failure(exc: Exception) -> bool:
    """Heuristic: does this exception indicate an OAuth/API auth failure?"""
    if _HAS_AUTH_BREAKER_MODULE:
        return _ab_looks_like_auth_failure(exc)
    msg = str(exc).lower()
    if any(code in msg for code in _AUTH_FAIL_HTTP_CODES):
        return True
    if any(kw in msg for kw in _AUTH_FAIL_KEYWORDS):
        return True
    # urllib.error.HTTPError exposes .code
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return True
    return False


def _auth_breaker_pk(source_name: str, user_id: str) -> str:
    return f"USER#{user_id}#SOURCE#{source_name}"


def _check_auth_breaker(table, source_name: str, user_id: str, logger):
    """Return the active marker if one exists and is still fresh, else None."""
    if _HAS_AUTH_BREAKER_MODULE:
        return _ab_check_breaker(table, source_name, user_id, logger)
    try:
        resp = table.get_item(Key={"pk": _auth_breaker_pk(source_name, user_id), "sk": _AUTH_FAIL_SK})
    except Exception as e:
        logger.warning(f"auth_breaker_lookup_failed: {e}")
        return None
    item = resp.get("Item")
    if not item:
        return None
    marked_at_iso = item.get("marked_at")
    if not marked_at_iso:
        return None
    try:
        marked_at = datetime.fromisoformat(marked_at_iso)
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - marked_at).total_seconds()
    if age >= _AUTH_FAIL_TTL_SECONDS:
        return None
    return item


def _mark_auth_failure(table, source_name: str, user_id: str, error_msg, logger):
    """Write the auth-failure marker with a 24h DDB TTL."""
    if _HAS_AUTH_BREAKER_MODULE:
        return _ab_mark_failure(table, source_name, user_id, error_msg, logger)
    now = datetime.now(timezone.utc)
    item = {
        "pk": _auth_breaker_pk(source_name, user_id),
        "sk": _AUTH_FAIL_SK,
        "marked_at": now.isoformat(),
        "error": str(error_msg)[:500],
        "ttl": int(now.timestamp()) + _AUTH_FAIL_TTL_SECONDS,
    }
    try:
        table.put_item(Item=item)
        logger.warning(f"auth_breaker_marked source={source_name} ttl=24h")
    except Exception as e:
        logger.warning(f"auth_breaker_mark_failed: {e}")


def _clear_auth_failure(table, source_name: str, user_id: str, logger):
    """Remove the marker after a successful run."""
    if _HAS_AUTH_BREAKER_MODULE:
        return _ab_clear_failure(table, source_name, user_id, logger)
    try:
        table.delete_item(Key={"pk": _auth_breaker_pk(source_name, user_id), "sk": _AUTH_FAIL_SK})
    except Exception as e:
        logger.warning(f"auth_breaker_clear_failed: {e}")


def record_ingest_health(table, source_name: str, logger, *, attempted: bool, succeeded: bool, error_class: str = "none"):
    """ER-01: read-modify-write a source's INGEST_HEALTH sentinel + emit an EMF metric.

    Best-effort: a failure here must never break ingestion. `attempted` stamps
    last_attempt_ts (the Lambda ran), independent of whether new data came back —
    that decoupling is the whole point (running-but-erroring ≠ unfed-but-healthy).

    Public so pattern-exempt standalone ingesters (hevy, notion, dropbox — #466/#467)
    write the same sentinel the framework sources do; the per-source
    ingest-consecutive-failures alarms only watch metrics this emits.
    """
    if not _INGEST_HEALTH_AVAILABLE:
        return
    try:
        now = datetime.now(timezone.utc)
        sk = ingest_health_sk(source_name)
        key = {"pk": _INGEST_SYSTEM_PK, "sk": sk}
        prev = table.get_item(Key=key).get("Item")
        sentinel = update_outcome(
            prev,
            attempted=attempted,
            succeeded=succeeded,
            error_class=error_class,
            now_iso=now.isoformat(),
            source=source_name,
        )
        table.put_item(Item={**key, **sentinel, "updated_at": now.isoformat()})
        # EMF line — CloudWatch extracts RunSuccess + ConsecutiveFailures.
        print(
            emf_metric_line(
                source=source_name,
                succeeded=succeeded,
                consecutive_failures=int(sentinel.get("consecutive_failures", 0)),
                error_class=sentinel.get("last_error_class", error_class),
                timestamp_ms=int(now.timestamp() * 1000),
            )
        )
    except Exception as e:  # never let health-recording break ingestion
        logger.warning(f"ingest_health_record_failed source={source_name}: {e}")


def _record_ingest_health(table, config, logger, *, attempted: bool, succeeded: bool, error_class: str = "none"):
    record_ingest_health(table, config.source_name, logger, attempted=attempted, succeeded=succeeded, error_class=error_class)


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
        refresh_today: bool = False,
        refresh_trailing_days: int = 0,
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
        # Phase 4.1 / Habitify (2026-05-17): some sources (Habitify: habits
        # checked throughout the day; Whoop: recovery score updates morning) need
        # today's record overwritten on every run, not just when missing. Setting
        # refresh_today=True adds today to the gap-fill check set unconditionally.
        self.refresh_today = refresh_today
        # Late-arriving data (2026-06-24): gap detection is presence-based — once a
        # date has *any* record it is never re-fetched. But some sources (Strava:
        # activities sync from a watch/phone hours-to-days after they happen, often
        # after their local day has already rolled past "today") gain new entries
        # for a *past* date that the store already considers "present", so those
        # entries are silently dropped (the Jun 2026 afternoon-walk gap that the
        # DI-2 reconciler caught). refresh_trailing_days=N forces the last N days to
        # be re-fetched every run, regardless of presence — transform() rebuilds the
        # whole day from all API activities, so a re-fetch merges in late arrivals.
        self.refresh_trailing_days = refresh_trailing_days

        # Environment
        self.region = os.environ.get("AWS_REGION", "us-west-2")
        self.table_name = os.environ.get("TABLE_NAME", "life-platform")
        self.s3_bucket = os.environ["S3_BUCKET"]
        self.user_id = os.environ.get("USER_ID", "matthew")


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
        if not hasattr(logger, "set_date"):
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
    """Query DDB for last N days, return sorted list of missing date strings.

    Phase 4.1 / Habitify: if config.refresh_today is True, today is always
    included regardless of whether the record exists — sources like Habitify
    update throughout the day and need overwrites on every hourly run.

    Late-arriving data: if config.refresh_trailing_days is N (>0), the last N
    days are likewise always re-fetched regardless of presence, so activities
    that sync to the source after their local day has rolled (Strava walks) are
    picked up instead of being stranded behind an already-present record.
    """
    from boto3.dynamodb.conditions import Key

    pk = f"USER#{config.user_id}#SOURCE#{config.source_name}"
    # Pacific day, not UTC: after 5 PM PT a UTC "today" is tomorrow's DATE# key, and
    # refresh_today then double-stamps the same night under two dates (truth audit
    # 2026-07-10, Eight Sleep — every refresh_today source shared the exposure).
    today = pacific_now().date()
    today_str = today.strftime("%Y-%m-%d")
    check_dates = set()
    for i in range(1, config.lookback_days + 1):
        check_dates.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))
    if config.refresh_today:
        check_dates.add(today_str)

    oldest = min(check_dates)
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(f"DATE#{oldest}", f"DATE#{today_str}"),
        ProjectionExpression="sk",
    )
    existing = {item["sk"][5:] for item in resp.get("Items", [])}
    if config.refresh_today:
        existing.discard(today_str)  # force today to be considered "missing"
    for i in range(1, getattr(config, "refresh_trailing_days", 0) + 1):
        existing.discard((today - timedelta(days=i)).strftime("%Y-%m-%d"))  # force trailing days to re-fetch
    missing = sorted(check_dates - existing)

    if missing:
        logger.info(f"[GAP-FILL] Found {len(missing)} missing dates: {missing}")
    else:
        logger.info(f"[GAP-FILL] No gaps in last {config.lookback_days} days")

    return missing


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATE + STORE (DATA-2 + REL-3)
# ══════════════════════════════════════════════════════════════════════════════


def phase_for_date(date_str: str) -> str:
    """Return phase tag ('pilot' or 'experiment') for a given DATE# value.

    Records written for dates before EXPERIMENT_START_DATE are pilot data;
    records for the genesis date or later are live experiment data. The
    read-path phase_filter (lambdas/phase_filter.py) excludes pilot by default.

    PUBLIC since #482/X-6: every standalone (non-framework) DDB writer stamps
    phase through this one helper, so an untagged backfill can never surface
    pre-genesis data as current (phase_filter passes attribute_not_exists).
    """
    if date_str and date_str < EXPERIMENT_START_DATE:
        return "pilot"
    return EXPERIMENT_PHASE_CURRENT


# Backward-compat alias (hevy_common and older callers import the private name).
_phase_for_date = phase_for_date


def _store_item(table, s3, config, item, date_str, logger):
    """Validate (DATA-2), size-guard (REL-3), and store a single DDB item.

    Returns True if stored successfully, False if skipped.
    """
    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item

        vr = _validate_item(config.source_name, item, date_str)
        if vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping {config.source_name} DDB write " f"for {date_str}: {vr.errors}")
            vr.archive_to_s3(s3, bucket=config.s3_bucket, item=item)
            return False
        if vr.warnings:
            logger.warning(f"[DATA-2] Validation warnings for " f"{config.source_name}/{date_str}: {vr.warnings}")
    except ImportError:
        pass  # Validator not available — proceed without

    # ADR-058: stamp phase=pilot|experiment so the default-deny read filter works.
    # Don't overwrite an explicitly-set phase (e.g., admin backfill scripts).
    if "phase" not in item:
        item["phase"] = _phase_for_date(date_str)

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
            Body=json.dumps(
                {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "raw": raw_data,
                },
                default=str,
            ),
            ContentType="application/json",
        )
    except Exception as e:
        # S3 archive is non-fatal but losing audit trail is concerning — log as ERROR
        print(f"[ERROR] S3 archive failed for {config.source_name}/{date_str} — audit trail lost: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ══════════════════════════════════════════════════════════════════════════════


def run_ingestion(config, authenticate_fn, fetch_day_fn, transform_fn, event, context, post_store_fn=None):
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

    today = pacific_today()  # DATE# keys are Pacific calendar days (truth audit 2026-07-10)
    logger.set_date(today)

    logger.info(f"Ingestion starting: source={config.source_name}")

    # ── Auth-failure circuit breaker (ADR-052) ──
    # If a prior run hit 401/403 in the last 24h, skip the API call entirely.
    # The first failure already produced its alert; further alarms are noise
    # until the operator rotates the credential. Marker auto-expires after 24h.
    _active_breaker = _check_auth_breaker(table, config.source_name, config.user_id, logger)
    if _active_breaker:
        msg = (
            f"auth_breaker_active source={config.source_name} "
            f"marked_at={_active_breaker.get('marked_at')} "
            f"error={_active_breaker.get('error', '')[:120]}"
        )
        logger.info(msg)
        # ER-01: the Lambda ran, but the upstream fetch is being suppressed by an
        # unresolved auth failure — record it as a continued failure so the streak
        # grows even with zero new data (this IS the running-but-dead case).
        _record_ingest_health(table, config, logger, attempted=True, succeeded=False, error_class="auth")
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "skipped": "auth_failure_circuit_breaker",
                    "source": config.source_name,
                    "marker": {k: str(v) for k, v in _active_breaker.items() if k != "ttl"},
                }
            ),
        }

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
            _record_ingest_health(table, config, logger, attempted=True, succeeded=False, error_class="transport")
            return {"statusCode": 500, "body": json.dumps({"error": f"Secret load failed: {e}"})}

        # ADR-052: trip the circuit breaker on auth failures so the next 24h
        # of runs skip the API instead of re-alerting on the same root cause.
        try:
            credentials = authenticate_fn(secret_data)
        except Exception as auth_exc:
            if _looks_like_auth_failure(auth_exc):
                _mark_auth_failure(table, config.source_name, config.user_id, auth_exc, logger)
            _err_class = classify_error(auth_exc) if _INGEST_HEALTH_AVAILABLE else "auth"
            _record_ingest_health(table, config, logger, attempted=True, succeeded=False, error_class=_err_class)
            raise

        # Write back updated credentials (OAuth token refresh).
        # #481/A-9: for rotating-token sources (Whoop rotates the single-use
        # refresh_token every run) this writeback is the ONLY persist path — a
        # lost write strands the rotated token: next run 400s → breaker →
        # manual re-auth. So: retry once, and a double failure is an ERROR
        # ('re-auth likely needed'), never a shrugged-off warning.
        if config.enable_secret_writeback and credentials:
            for _wb_attempt in (1, 2):
                try:
                    secrets_client.update_secret(
                        SecretId=config.secret_id,
                        SecretString=json.dumps(credentials),
                    )
                    logger.info("Credentials updated in Secrets Manager")
                    break
                except Exception as e:
                    if _wb_attempt == 1:
                        logger.warning(f"Secret writeback failed (attempt 1/2, retrying): {e}")
                        time.sleep(1)
                    else:
                        logger.error(
                            f"Secret writeback FAILED twice for {config.secret_id} — the rotated "
                            f"token may be stranded; re-auth likely needed on the next run: {e}"
                        )
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
            # ER-01: gap detection ran and found nothing missing — the source is
            # up to date. A healthy run (Lambda ran, no error), so it counts as a
            # success for liveness even though no API call was needed.
            _record_ingest_health(table, config, logger, attempted=True, succeeded=True)
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "No gaps to fill",
                        "source": config.source_name,
                        "lookback_days": config.lookback_days,
                    }
                ),
            }
    else:
        # Mode 3: Default — yesterday + today (Pacific calendar days, like the DATE# keys)
        yesterday = (pacific_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        dates_to_ingest = [yesterday, today]

    # ── Ingest each date ──
    results = {}
    records_written = 0
    errors = 0
    last_error_class = "none"  # ER-01: classify the most recent per-date failure

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

                db_item = _floats_to_decimal(
                    {
                        "pk": pk,
                        "sk": sk,
                        "source": source,
                        "schema_version": config.schema_version,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                        **record,
                    }
                )

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
            if _INGEST_HEALTH_AVAILABLE:
                last_error_class = classify_error(e)
            # ADR-052: trip the breaker if the per-date error looks like 401/403.
            if _looks_like_auth_failure(e):
                _mark_auth_failure(table, config.source_name, config.user_id, e, logger)
                # No point retrying remaining dates with the same bad credential.
                break

        # Rate limit between gap-fill days
        if i < len(dates_to_ingest) - 1 and config.enable_gap_detection:
            time.sleep(config.gap_rate_limit_seconds)

    # ── Clear circuit breaker on a clean run (ADR-052) ──
    # If we wrote at least one record successfully and had no errors at all,
    # the credential is healthy — drop any lingering marker so the next run
    # behaves normally even before the 24h TTL expires.
    if errors == 0 and records_written > 0:
        _clear_auth_failure(table, config.source_name, config.user_id, logger)

    # ── ER-01 infra-liveness sentinel ──
    # The Lambda ran and completed its fetch loop. succeeded iff no per-date errors
    # (a date that simply had no data is NOT an error → still a healthy run). This
    # is what distinguishes "user didn't log" (succeeded) from "ingestion erroring"
    # (errors > 0 → streak grows → heartbeat alerts).
    _record_ingest_health(
        table,
        config,
        logger,
        attempted=True,
        succeeded=(errors == 0),
        error_class="none" if errors == 0 else last_error_class,
    )

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
