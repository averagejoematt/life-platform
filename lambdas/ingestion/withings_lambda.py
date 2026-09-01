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
  (the 14-day body-comp delta query was deleted 2026-07-04, #486/B-3, on the
  premise that the scale was weight-only. That premise expired 2026-08-16
  (#3417): the device has two modes — a plain weigh writes weight only, a full
  scan with the handles held writes ~30 composition fields. Composition is a
  behavioral/sparse signal (full-scan days only); the delta stays deleted by
  decision, not for want of inputs — see the ADR-154 amendment (2026-09-01, #3417).)

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
    from common.platform_logger import get_logger

    logger = get_logger("withings")
except ImportError:
    logger = logging.getLogger("withings")
    logger.setLevel(logging.INFO)

from ingestion.ingestion_framework import IngestionConfig, run_ingestion

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
    155: "vascular_age",  # age-class — Tier-2 owner-only (SCHEMA.md), never a public/AI surface
    # ── BodyScan 2 arrivals (#2782, owner-decided ingest-all 2026-08-16) ──────
    130: "afib_result",  # ECG screening: 0 = not detected. Event-class, owner-only.
    168: "extracellular_water_kg",
    169: "intracellular_water_kg",
    170: "visceral_fat_index",  # unitless index
    196: "eda_feet",  # electrodermal activity (nerve health), both feet
    197: "eda_left_foot",
    198: "eda_right_foot",
    226: "bmr_kcal",  # basal metabolic rate — label inferred (BodyScan publishes BMR; kcal-scale value)
    227: "metabolic_age",  # age-class — Tier-2 owner-only, same posture as vascular_age
}

# ── BodyScan 2 segmental body composition (#2782) ─────────────────────────────
# Types 173/174/175 arrive as FIVE measures per reading, one per body segment,
# distinguished by the measure's `position` attribute. The official docs do not
# publish the position→limb mapping; this one is inferred from physiological
# magnitude on the live 2026-08-16 capture (torso carries 48.76 of the 92.08 kg
# fat-free total; legs ≈15.4; arms ≈6.2) and marked as such in SCHEMA.md. If a
# future reading looks anatomically absurd, suspect this mapping first.
# Internal cross-check that pins 173's semantics: the five position values sum
# to exactly the scalar fat_free_mass_kg (type 5).
SEGMENTAL_TYPES = {
    173: "fat_free_mass",
    174: "fat_mass",
    175: "muscle_mass",
}
SEGMENT_POSITIONS = {
    2: "left_arm",
    3: "right_arm",
    10: "left_leg",
    11: "right_leg",
    12: "torso",
}


def requested_meastypes() -> list[int]:
    """Every meastype the transform can parse, as the `getmeas` request asks for it.

    #2994: `_fetch_range` used to build `meastypes` from `MEAS_TYPES` alone, so the
    segmental types added by #2794 were never requested — the transform grew a branch
    for data the fetch could not return, and the wire-shaped fixture in
    `tests/test_ingestion_transforms.py` mirrored the spike's *unfiltered* exploratory
    call rather than the filtered request production issues. Green tests, 15 fields
    permanently absent from every row.

    Derived from the two handler tables so a new type is requested by construction;
    `test_withings_requests_every_type_it_can_parse` guards the equality in both
    directions.
    """
    return sorted(set(MEAS_TYPES) | set(SEGMENTAL_TYPES))


# ── Withings API helpers ───────────────────────────────────────────────────────


def _hmac_sha256(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def _post_form(url: str, params: dict) -> dict:
    """POST form-encoded params, retried via http_retry on transient errors."""
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    from common.http_retry import urlopen_with_retry

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
    from common.http_retry import urlopen_with_retry

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
            value = meas["value"] * (10 ** meas["unit"])
            if mtype in SEGMENTAL_TYPES:
                # #2782: per-limb values share one type id; `position` picks the
                # segment. An unknown position is skipped visibly, never guessed.
                segment = SEGMENT_POSITIONS.get(meas.get("position"))
                if segment is None:
                    logger.warning(f"withings: segmental type {mtype} with unmapped position {meas.get('position')!r} — skipped")
                    continue
                field_name = f"{SEGMENTAL_TYPES[mtype]}_{segment}_kg"
                if field_name not in result:
                    result[field_name] = round(value, 4)
                continue
            if mtype not in MEAS_TYPES:
                continue
            if mtype == 54 and value == 0:
                # ADR-104 (#2782): the BodyScan transmits SpO2 = 0 when the
                # measurement failed to compute. 0% is an absence encoded as a
                # number, not a reading — never store it.
                continue
            field_name = MEAS_TYPES[mtype]
            if field_name in result:
                continue  # keep most-recent only
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
        "meastypes": ",".join(str(k) for k in requested_meastypes()),
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
    deleted 2026-07-04 — at deletion time no record had ever carried its fat/lean
    inputs and it early-returned on every record. The stated premise, "the scale
    is weight-only", stopped being true on 2026-08-16 (#3417): a full scan with
    the handles held DOES write composition fields; a plain weigh still writes
    weight only, so composition is behavioral/sparse — present only on full-scan
    days. The delta stays deleted by recorded decision — see the ADR-154 amendment (2026-09-01, #3417).)"""
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
