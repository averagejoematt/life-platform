"""
macrofactor_puller_lambda.py — WS-2 Tier 1 puller for MacroFactor food log.

Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 §3.1.

Architecture:
    EventBridge schedule (daily 14:00 UTC = 07:00 PT)
      → this Lambda
        → read life-platform/macrofactor secret (username, password)
        → MacroFactorClient.sign_in()
        → for each date in [today-LOOKBACK_DAYS, today]:
            entries = client.get_food_log(date)
            for each entry: write NUTRITION#{date}#{meal?}#{entry_uid} to DDB
            persist raw doc to s3://matthew-life-platform/raw/macrofactor_api/{date}.json
        → write health status to DDB: USER#system / INGESTION_STATE#macrofactor_api
        → on ANY failure: record error in status, do NOT crash the platform; the
          digest alert + the manual Dropbox export (Tier 2) take over.

Isolation: hard failure here does not affect anything else. If the
unofficial API breaks tomorrow, the Lambda errors, the digest fires,
and Matthew uses the manual export until the upstream library fix
lands.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3

from macrofactor_client import (
    MacroFactorClient,
    MacroFactorAuthError,
    MacroFactorAPIError,
)

try:
    from platform_logger import get_logger
    logger = get_logger("mf-puller")
except ImportError:
    logger = logging.getLogger("mf-puller")
    logger.setLevel(logging.INFO)

# ── Config ───────────────────────────────────────────────────────────────────
REGION       = os.environ.get("AWS_REGION", "us-west-2")
USER_ID      = os.environ.get("USER_ID", "matthew")
TABLE_NAME   = os.environ.get("TABLE_NAME", "life-platform")
BUCKET       = os.environ.get("S3_BUCKET", "matthew-life-platform")
SECRET_NAME  = os.environ.get("SECRET_NAME", "life-platform/macrofactor")
LOOKBACK_DAYS = int(os.environ.get("MF_LOOKBACK_DAYS", "3"))  # rolling self-heal window

SOURCE = "macrofactor_api"
SCHEMA_VERSION = 1
WORKOUT_SOURCE = "macrofactor_api"   # same source string; we distinguish by SK pattern

# AWS clients (module level for warm-container reuse)
_secrets = boto3.client("secretsmanager", region_name=REGION)
_ddb = boto3.resource("dynamodb", region_name=REGION)
_table = _ddb.Table(TABLE_NAME)
_s3 = boto3.client("s3", region_name=REGION)


# ── DDB write helpers ────────────────────────────────────────────────────────

def _to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _load_credentials() -> tuple[str, str]:
    """Read username/password from Secrets Manager."""
    try:
        from secret_cache import get_secret_json
        sec = get_secret_json(SECRET_NAME, _secrets)
    except ImportError:
        resp = _secrets.get_secret_value(SecretId=SECRET_NAME)
        sec = json.loads(resp["SecretString"])
    username = sec.get("username") or sec.get("email")
    password = sec.get("password")
    if not (username and password):
        raise RuntimeError(f"{SECRET_NAME} missing username/email + password")
    return str(username), str(password)


def _stable_entry_uid(date_str: str, entry_id: str, food_name: str) -> str:
    """Stable hash for cross-tier dedupe.

    Per spec §3.4: same date + entry should produce the same uid regardless
    of which tier (api vs export) fetched it. Both tiers see MacroFactor's
    entry id (epoch-micros, very stable), so we key on that plus a food-name
    fingerprint for safety.
    """
    h = hashlib.sha256(f"{date_str}|{entry_id}|{food_name}".encode("utf-8")).hexdigest()
    return f"mf:{h[:16]}"


def _archive_raw_day(date_str: str, entries: list[dict]) -> str:
    """Archive the day's entries to S3 for re-derivation."""
    key = f"raw/{SOURCE}/{date_str}.json"
    _s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps({"date": date_str, "entries": entries}, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{BUCKET}/{key}"


def _phase_for_date(date_str: str) -> str:
    try:
        from constants import EXPERIMENT_START_DATE, EXPERIMENT_PHASE_CURRENT
        return "pilot" if date_str < EXPERIMENT_START_DATE else EXPERIMENT_PHASE_CURRENT
    except ImportError:
        return "experiment"


def _write_entry(entry: dict) -> None:
    """Idempotent upsert of one food entry under NUTRITION#{date}#{entry_uid}."""
    date_str = entry["date"]
    entry_id = entry["entry_id"]
    name = entry.get("food_name") or ""
    uid = _stable_entry_uid(date_str, entry_id, name)
    item = {
        "pk":              f"USER#{USER_ID}#SOURCE#{SOURCE}",
        "sk":              f"NUTRITION#{date_str}#{uid}",
        "source":          SOURCE,
        "entry_uid":       uid,
        "source_entry_id": entry_id,
        "date":            date_str,
        "food_name":       entry.get("food_name"),
        "brand":           entry.get("brand"),
        "calories":        entry.get("calories"),
        "protein_g":       entry.get("protein_g"),
        "carbs_g":         entry.get("carbs_g"),
        "fat_g":           entry.get("fat_g"),
        "grams":           entry.get("grams"),
        "quantity":        entry.get("quantity"),
        "serving":         entry.get("serving"),
        "unit":            entry.get("unit"),
        "hour":            entry.get("hour"),
        "minute":          entry.get("minute"),
        "raw_field_codes": entry.get("raw_fields"),
        "raw_ref":         f"s3://{BUCKET}/raw/{SOURCE}/{date_str}.json",
        "schema_version":  SCHEMA_VERSION,
        "ingested_at":     datetime.now(timezone.utc).isoformat(),
        "phase":           _phase_for_date(date_str),
    }
    # Strip None values to keep DDB items tidy.
    item = {k: v for k, v in item.items() if v is not None}
    _table.put_item(Item=_to_decimal(item))


def _write_workout(workout: dict) -> None:
    """Idempotent upsert of one MF workout under SOURCE#macrofactor_api.

    SK matches the Hevy convention (DATE#yyyy-mm-dd#WORKOUT#<id>) so the
    MCP tool_get_workouts handler sees a uniform shape across sources.
    The same workout fetched later by the Dropbox export pipeline can
    dedupe against this record by matching workout_uid (= mf:<doc_id>).
    """
    date_str = workout.get("date") or ""
    wid = workout.get("source_workout_id") or ""
    if not (date_str and wid):
        logger.warning("mf-puller: skipping workout with missing date/id: %s", workout)
        return
    item = {
        "pk":              f"USER#{USER_ID}#SOURCE#{WORKOUT_SOURCE}",
        "sk":              f"DATE#{date_str}#WORKOUT#{wid}",
        **workout,
        "raw_ref":         f"s3://{BUCKET}/raw/{WORKOUT_SOURCE}/workouts/{wid}.json",
        "schema_version":  SCHEMA_VERSION,
        "ingested_at":     datetime.now(timezone.utc).isoformat(),
        "phase":           _phase_for_date(date_str),
    }
    # Strip Nones, leave required nested structures alone.
    item = {k: v for k, v in item.items() if v is not None}
    _table.put_item(Item=_to_decimal(item))


def _archive_raw_workout(workout_id: str, raw: dict) -> None:
    """Persist the raw workout doc for re-derivation."""
    key = f"raw/{WORKOUT_SOURCE}/workouts/{workout_id}.json"
    _s3.put_object(
        Bucket=BUCKET, Key=key,
        Body=json.dumps(raw, default=str).encode("utf-8"),
        ContentType="application/json",
    )


def _write_status(success: bool, last_error: str | None, days_with_data: int,
                  entries_total: int, workouts_total: int,
                  consecutive_failures: int) -> None:
    """Status record at USER#system / INGESTION_STATE#macrofactor_api for §3.3."""
    _table.put_item(Item={
        "pk":                   "USER#system",
        "sk":                   "INGESTION_STATE#macrofactor_api",
        "source":               SOURCE,
        "last_success_at":      datetime.now(timezone.utc).isoformat() if success else None,
        "last_run_at":          datetime.now(timezone.utc).isoformat(),
        "last_error":           last_error,
        "days_with_data":       days_with_data,
        "entries_ingested":     entries_total,
        "workouts_ingested":    workouts_total,
        "consecutive_failures": consecutive_failures,
        "healthy":              success,
        "updated_at":           datetime.now(timezone.utc).isoformat(),
    })


def _read_consecutive_failures() -> int:
    try:
        resp = _table.get_item(Key={
            "pk": "USER#system", "sk": "INGESTION_STATE#macrofactor_api",
        })
        item = resp.get("Item") or {}
        return int(item.get("consecutive_failures") or 0)
    except Exception:
        return 0


# ── Handler ──────────────────────────────────────────────────────────────────

def lambda_handler(event: dict, context: Any) -> dict:
    """Scheduled MacroFactor food-log puller (rolling LOOKBACK_DAYS window)."""
    today = date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(LOOKBACK_DAYS + 1)]

    logger.info("mf-puller starting. dates=%s", dates)

    days_with_data = 0
    entries_total = 0
    workouts_total = 0
    failures: list[str] = []

    try:
        username, password = _load_credentials()
        client = MacroFactorClient(username, password)
        client.sign_in()
        logger.info("mf-puller signed in uid=%s", client.uid[:8] + "…")

        # ── Food log: per-day pulls (one Firestore doc per date) ────────────
        for d in dates:
            try:
                entries = client.get_food_log(d)
            except MacroFactorAPIError as e:
                logger.warning("mf-puller food %s: %s", d, e)
                failures.append(f"food {d}: {e}")
                continue
            if not entries:
                continue
            _archive_raw_day(d, entries)
            for ent in entries:
                _write_entry(ent)
                entries_total += 1
            days_with_data += 1
            logger.info("mf-puller food %s: %d entries", d, len(entries))

        # ── Workouts: collection list filtered by date range ────────────────
        # Per spec §3.9, MF workouts come through the SAME login session as
        # nutrition. We pull the workoutHistory collection and filter to the
        # rolling window. Each workout is independently upserted; same uid
        # (mf:<doc_id>) means a future macrofactor_export per-workout writer
        # will dedupe naturally.
        try:
            mf_workouts = client.get_workouts(start_date=start.isoformat(),
                                              end_date=today.isoformat())
        except MacroFactorAPIError as e:
            logger.warning("mf-puller workouts: %s", e)
            failures.append(f"workouts: {e}")
            mf_workouts = []

        for w in mf_workouts:
            try:
                _archive_raw_workout(w["source_workout_id"], w)
                _write_workout(w)
                workouts_total += 1
            except Exception as e:
                logger.warning("mf-puller workout write %s: %s",
                               w.get("source_workout_id"), e)
                failures.append(f"workout {w.get('source_workout_id')}: {e}")
        if mf_workouts:
            logger.info("mf-puller workouts: %d ingested in window", workouts_total)

    except MacroFactorAuthError as e:
        logger.error("mf-puller auth failed: %s", e)
        prev_fail = _read_consecutive_failures()
        _write_status(
            success=False, last_error=f"auth: {e}",
            days_with_data=days_with_data,
            entries_total=entries_total,
            workouts_total=workouts_total,
            consecutive_failures=prev_fail + 1,
        )
        return {
            "statusCode": 200,
            "body": json.dumps({
                "source": SOURCE, "ok": False, "error": f"auth: {e}",
                "advice": "Tier 1 broken. Use the manual Dropbox export (Tier 2) until re-auth.",
            }),
        }
    except Exception as e:
        logger.exception("mf-puller unhandled error: %s", e)
        prev_fail = _read_consecutive_failures()
        _write_status(
            success=False, last_error=f"unhandled: {e}",
            days_with_data=days_with_data,
            entries_total=entries_total,
            workouts_total=workouts_total,
            consecutive_failures=prev_fail + 1,
        )
        return {
            "statusCode": 200,
            "body": json.dumps({"source": SOURCE, "ok": False, "error": str(e)}),
        }

    last_error = "; ".join(failures[:3]) if failures else None
    _write_status(
        success=(len(failures) == 0),
        last_error=last_error,
        days_with_data=days_with_data,
        entries_total=entries_total,
        workouts_total=workouts_total,
        consecutive_failures=(0 if not failures else _read_consecutive_failures() + 1),
    )

    summary = {
        "source":            SOURCE,
        "ok":                len(failures) == 0,
        "lookback_days":     LOOKBACK_DAYS,
        "dates_checked":     len(dates),
        "days_with_data":    days_with_data,
        "entries_ingested":  entries_total,
        "workouts_ingested": workouts_total,
        "per_day_failures":  failures[:5],
    }
    logger.info("mf-puller complete: %s", json.dumps(summary, default=str))
    return {"statusCode": 200, "body": json.dumps(summary, default=str)}
