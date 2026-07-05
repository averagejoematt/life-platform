"""
withings_lambda.py — Withings ingestion via SIMP-2 framework (P4.1, 2026-05-17).

4th of 8 ingestion Lambdas to migrate. First OAuth-based migration.
HMAC-signed nonce-based refresh; framework writes back the refreshed secret
via enable_secret_writeback=True.

Source-specific concerns preserved:
  - HMAC-SHA256-signed nonce flow for OAuth refresh
  - 401-in-body (not HTTP) → retry-with-refresh on first invocation
  - Multi-measurement-group parsing (scale + BPM produce separate groups)
  - kg→lbs derived fields for weight/composition metrics
  (the 14-day body-comp delta query was deleted 2026-07-04, #486/B-3 — the
  scale is weight-only, so it early-returned on every record)

DDB shape unchanged from pre-migration.
"""

import hashlib
import hmac
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from platform_logger import get_logger

    logger = get_logger("withings")
except ImportError:
    logger = logging.getLogger("withings")
    logger.setLevel(logging.INFO)

from ingestion_framework import IngestionConfig, run_ingestion

REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
SECRET_NAME = os.environ.get("WITHINGS_SECRET_NAME", "life-platform/withings")
DYNAMO_PK = f"USER#{USER_ID}#SOURCE#withings"

WITHINGS_SIG_URL = "https://wbsapi.withings.net/v2/signature"
WITHINGS_OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_MEAS_URL = "https://wbsapi.withings.net/measure"

# Measurement type IDs from Withings API → field names in DDB record.
MEAS_TYPES = {
    1: "weight_kg",
    4: "height_m",
    5: "fat_free_mass_kg",
    6: "fat_ratio_pct",
    8: "fat_mass_kg",
    9: "diastolic_blood_pressure",
    10: "systolic_blood_pressure",
    11: "heart_pulse",
    12: "temperature_c",
    54: "spo2_pct",
    71: "body_temperature_c",
    73: "skin_temperature_c",
    76: "muscle_mass_kg",
    77: "hydration_kg",
    88: "bone_mass_kg",
    91: "pulse_wave_velocity_mps",
    123: "vo2_max",
    135: "qrs_interval_ms",
    136: "pr_interval_ms",
    137: "qt_interval_ms",
    155: "vascular_age",
}

# ── Withings API helpers ───────────────────────────────────────────────────────


def _hmac_sha256(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def _post_form(url: str, params: dict) -> dict:
    """POST form-encoded params, retried via http_retry on transient errors."""
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    from http_retry import urlopen_with_retry

    with urlopen_with_retry(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_nonce(client_id: str, client_secret: str) -> str:
    sig = _hmac_sha256(client_secret, f"getnonce,{client_id},{int(datetime.now().timestamp())}")
    resp = _post_form(
        WITHINGS_SIG_URL,
        {
            "action": "getnonce",
            "client_id": client_id,
            "timestamp": int(datetime.now().timestamp()),
            "signature": sig,
        },
    )
    if resp.get("status") != 0:
        raise RuntimeError(f"getnonce failed: {resp}")
    return resp["body"]["nonce"]


def _refresh_access_token(secret: dict) -> dict:
    """HMAC-signed refresh flow; mutates + returns the secret with new tokens."""
    logger.info("Refreshing Withings access token...")
    client_id = secret["client_id"]
    client_secret = secret["client_secret"]
    refresh_token = secret["refresh_token"]

    nonce = _get_nonce(client_id, client_secret)
    signature = _hmac_sha256(client_secret, f"requesttoken,{client_id},{nonce}")
    resp = _post_form(
        WITHINGS_OAUTH_URL,
        {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "nonce": nonce,
            "signature": signature,
        },
    )
    if resp.get("status") != 0:
        raise RuntimeError(f"Token refresh failed: {resp}")
    body = resp["body"]
    secret["access_token"] = body["access_token"]
    secret["refresh_token"] = body["refresh_token"]
    return secret


def _withings_get(secret: dict, url: str, params: dict) -> tuple[dict, dict]:
    """Bearer-token POST; refresh on 401-in-body. Returns (body, possibly-updated secret)."""
    params["action"] = params.get("action", "")
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Authorization": f"Bearer {secret['access_token']}"})
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    from http_retry import urlopen_with_retry

    with urlopen_with_retry(req, timeout=30) as resp:
        result = json.loads(resp.read())

    # Withings returns 401 in body (not HTTP status) when token is expired
    if result.get("status") == 401:
        logger.info("Withings access token expired, refreshing...")
        secret = _refresh_access_token(secret)
        req2 = urllib.request.Request(url, data=data, method="POST", headers={"Authorization": f"Bearer {secret['access_token']}"})
        req2.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urlopen_with_retry(req2, timeout=30) as resp2:
            result = json.loads(resp2.read())

    if result.get("status") != 0:
        raise RuntimeError(f"Withings API error: {result}")
    return result["body"], secret


def _parse_measurements(raw_body: dict) -> dict:
    """Withings returns measuregrps — flatten the most-recent value per field."""
    grps = raw_body.get("measuregrps", [])
    if not grps:
        return {}
    grps_sorted = sorted(grps, key=lambda g: g["date"], reverse=True)
    latest_ts = grps_sorted[0]["date"]
    result = {
        "measurement_timestamp": latest_ts,
        "measurement_time_utc": datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat(),
    }
    for grp in grps_sorted:
        for meas in grp.get("measures", []):
            mtype = meas["type"]
            if mtype not in MEAS_TYPES:
                continue
            field_name = MEAS_TYPES[mtype]
            if field_name in result:
                continue  # keep most-recent only
            value = meas["value"] * (10 ** meas["unit"])
            result[field_name] = round(value, 4)
            if field_name in ("weight_kg", "fat_mass_kg", "fat_free_mass_kg", "muscle_mass_kg", "bone_mass_kg"):
                result[field_name.replace("_kg", "_lbs")] = round(value * 2.20462, 2)
    return result


# ── SIMP-2 callbacks ───────────────────────────────────────────────────────────

# Per-invocation: cache the secret dict after auth so fetch_day reuses it
# (matches old behavior where one refresh covered the whole gap-fill loop).
_secret_cache = {"secret": None}

# Per-invocation: one getmeas range call covers the whole lookback window
# (#501/B-9 — the framework calls fetch_day once per missing date, which used
# to mean one getmeas call per date: up to lookback_days+1 calls/run, ~144/day
# during a weigh-in gap on an hourly cron. The API already accepts a date
# range, so the first fetch_day call this invocation fetches the whole window
# and buckets it by UTC date; every subsequent fetch_day call in the same
# gap-fill loop is served from this cache with zero additional API calls).
_range_cache: dict = {"window": None, "by_date": {}}


def authenticate(secret_data: dict) -> dict:
    """Refresh tokens unconditionally on every cold-Lambda invocation.
    Framework writes the returned dict back to Secrets Manager via
    enable_secret_writeback=True so the next invocation reads fresh tokens."""
    refreshed = _refresh_access_token(dict(secret_data))
    _secret_cache["secret"] = refreshed
    _range_cache["window"] = None  # new invocation — force a fresh range fetch
    _range_cache["by_date"] = {}
    return refreshed


def _fetch_range(secret: dict, start_dt: datetime, end_dt: datetime) -> tuple[dict, dict]:
    """One getmeas call spanning [start_dt, end_dt); buckets measuregrps by UTC
    date so each date's bucket has the same shape a per-day fetch used to
    return. Returns (by_date, possibly-updated secret)."""
    params = {
        "action": "getmeas",
        "meastypes": ",".join(str(k) for k in MEAS_TYPES.keys()),
        "category": "1",
        "startdate": int(start_dt.timestamp()),
        "enddate": int(end_dt.timestamp()),
    }
    body, updated_secret = _withings_get(secret, WITHINGS_MEAS_URL, params)
    by_date: dict = {}
    for grp in body.get("measuregrps", []):
        date_str = datetime.fromtimestamp(grp["date"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_date.setdefault(date_str, {"measuregrps": []})["measuregrps"].append(grp)
    return by_date, updated_secret


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Fetch raw measurement groups for the given date. Returns None when the day
    has no weigh-in (framework treats that as 'no_data' — correct behavior; Withings
    silence ≠ error). Backed by the per-invocation range cache — see _fetch_range."""
    secret = _secret_cache["secret"] or credentials
    target_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_start = datetime(target_dt.year, target_dt.month, target_dt.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    window = _range_cache["window"]
    if window is None or not (window[0] <= day_start < window[1]):
        # First fetch_day call this invocation, or a date outside the cached
        # window (e.g. an explicit date_override backfill older than the
        # lookback) — widen the fetch to cover it and cache the result.
        lookback_days = int(os.environ.get("LOOKBACK_DAYS", "7"))
        now = datetime.now(timezone.utc)
        fetch_start = min(day_start, now - timedelta(days=lookback_days))
        fetch_end = max(day_end, now + timedelta(days=1))
        by_date, updated_secret = _fetch_range(secret, fetch_start, fetch_end)
        _secret_cache["secret"] = updated_secret  # keep cache fresh if refresh happened
        _range_cache["by_date"] = by_date
        _range_cache["window"] = (fetch_start, fetch_end)

    body = _range_cache["by_date"].get(date_str)
    return body if body and body.get("measuregrps") else None


def transform(raw: dict, date_str: str) -> list[dict]:
    """Parse measurements. (#486/B-3: the 14-day body-comp delta computation was
    deleted — the scale is weight-only, so its fat/lean inputs never existed and
    the function early-returned on every record since 2021.)"""
    if not raw:
        return []
    measurements = _parse_measurements(raw)
    if not measurements:
        return []
    return [
        {
            "source": "withings",
            "date": date_str,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            **measurements,
        }
    ]


# ── Framework config ───────────────────────────────────────────────────────────

_config = IngestionConfig(
    source_name="withings",
    secret_id=SECRET_NAME,
    s3_archive_prefix=f"raw/{USER_ID}/withings/measurements",
    schema_version=1,
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
    enable_secret_writeback=True,  # OAuth refresh tokens persist back
    enable_item_size_guard=True,
    refresh_today=True,  # users may weigh in any time today
)


def lambda_handler(event: dict, context) -> dict:
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("withings ingestion failed: %s", e, exc_info=True)
        raise
