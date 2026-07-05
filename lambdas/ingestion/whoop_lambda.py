"""
whoop_lambda.py — Whoop ingestion via SIMP-2 framework (P4.1, 2026-05-17).

7th of 8 ingestion Lambdas to migrate. Most complex pre-Garmin: multi-endpoint
(recovery + sleep + cycle + workout), per-workout sub-records via the
framework's sk_suffix mechanism, cross-day sleep-consistency query.

Source-specific concerns preserved:
  - OAuth refresh with refresh_token rotation (enable_secret_writeback=True)
  - Per-workout DDB items at DATE#{date}#WORKOUT#{id} (framework sk_suffix)
  - Sleep onset 7-day rolling consistency (cross-day query)
  - Nap aggregation (separate from main sleep)
  - Field-presence validation logging (F2.5)
  - Auth-failure circuit breaker (now framework-native via enable_gap_detection)

DDB shape unchanged from pre-migration.

Note: ADR-036 race risk — Whoop runs every hour. Reserved concurrency=1 must
remain set on this function until proven safe under concurrent invocations.
"""

import json
import logging
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

try:
    from platform_logger import get_logger

    logger = get_logger("whoop")
except ImportError:
    logger = logging.getLogger("whoop")
    logger.setLevel(logging.INFO)

try:
    from http_retry import urlopen_with_retry
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    urlopen_with_retry = urllib.request.urlopen

from ingestion_framework import IngestionConfig, run_ingestion

REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
SECRET_NAME = os.environ.get("WHOOP_SECRET_NAME", "life-platform/whoop")
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")

WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"
WHOOP_SCOPES = "offline read:recovery read:cycles read:workout read:sleep " "read:profile read:body_measurement"

WHOOP_SPORT_NAMES = {
    -1: "Activity",
    0: "Running",
    1: "Cycling",
    16: "Basketball",
    17: "Baseball",
    18: "Football",
    19: "Soccer",
    25: "Swimming",
    27: "Tennis",
    44: "Weightlifting",
    45: "Cross Training",
    46: "Functional Fitness",
    48: "Yoga",
    49: "Pilates",
    50: "HIIT",
    51: "Spin",
    57: "Rowing",
    63: "Hiking",
    71: "Triathlon",
    72: "Golf",
    73: "Skiing / Snowboarding",
    74: "Skateboarding",
    85: "Lacrosse",
    91: "Walking",
}
_ZONE_WORD = ["zero", "one", "two", "three", "four", "five"]

# Module-level DDB resource — needed by transform() for sleep-consistency
# cross-day query (framework doesn't pass its table to callbacks).
_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE)


# ── Whoop API ─────────────────────────────────────────────────────────────────


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> tuple:
    payload = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": WHOOP_SCOPES,
        }
    ).encode()
    req = urllib.request.Request(
        WHOOP_TOKEN_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "WhoopIngestion/1.0"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["access_token"], data["refresh_token"]


def _fetch_endpoint(access_token: str, endpoint: str, start_dt: str, end_dt: str) -> dict:
    """GET on the shared retry policy (#501/X-11 — converged onto http_retry;
    3-attempt 2s/8s backoff on 429/5xx and network errors). Auth failures
    (401/403) still bubble immediately — the auth_breaker pattern handles those."""
    params = urllib.parse.urlencode({"start": start_dt, "end": end_dt, "limit": 25})
    url = f"{WHOOP_API_BASE}/{endpoint}?{params}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "WhoopIngestion/1.0"},
    )
    with urlopen_with_retry(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── Field extractors (DDB-shape preserved from pre-migration) ────────────────


def _set_dec(fields: dict, name: str, value) -> None:
    if value is None:
        return
    fields[name] = Decimal(str(value))


def _round(value, decimals):
    return round(value, decimals) if value is not None else None


def _extract_recovery(recovery: dict) -> dict:
    fields = {}
    records = recovery.get("records", [])
    if not records:
        return fields
    record = records[0]
    if record.get("score_state") != "SCORED":
        return fields
    score = record.get("score") or {}
    _set_dec(fields, "recovery_score", score.get("recovery_score"))
    _set_dec(fields, "resting_heart_rate", score.get("resting_heart_rate"))
    hrv = score.get("hrv_rmssd_milli")
    if hrv is not None:
        _set_dec(fields, "hrv", round(hrv, 2))
    _set_dec(fields, "spo2_percentage", _round(score.get("spo2_percentage"), 2))
    _set_dec(fields, "skin_temp_celsius", _round(score.get("skin_temp_celsius"), 2))
    return fields


def _extract_sleep(sleep: dict) -> dict:
    fields = {}
    records = sleep.get("records", [])
    main = next((r for r in records if not r.get("nap", False)), None)
    if not main or main.get("score_state") != "SCORED":
        return fields
    score = main.get("score") or {}
    stage = score.get("stage_summary", {}) or {}

    def ms_to_h(ms):
        return round((ms or 0) / 3_600_000, 2)

    in_bed_ms = stage.get("total_in_bed_time_milli", 0)
    awake_ms = stage.get("total_awake_time_milli", 0)
    rem_ms = stage.get("total_rem_sleep_time_milli", 0)
    sws_ms = stage.get("total_slow_wave_sleep_time_milli", 0)
    light_ms = stage.get("total_light_sleep_time_milli", 0)
    sleep_ms = in_bed_ms - awake_ms

    if sleep_ms > 0:
        _set_dec(fields, "sleep_duration_hours", ms_to_h(sleep_ms))
    if rem_ms > 0:
        _set_dec(fields, "rem_sleep_hours", ms_to_h(rem_ms))
    if sws_ms > 0:
        _set_dec(fields, "slow_wave_sleep_hours", ms_to_h(sws_ms))
    if light_ms > 0:
        _set_dec(fields, "light_sleep_hours", ms_to_h(light_ms))
    if awake_ms > 0:
        _set_dec(fields, "time_awake_hours", ms_to_h(awake_ms))

    if stage.get("disturbance_count") is not None:
        fields["disturbance_count"] = int(stage["disturbance_count"])

    _set_dec(fields, "respiratory_rate", _round(score.get("respiratory_rate"), 2))
    _set_dec(fields, "sleep_efficiency_percentage", _round(score.get("sleep_efficiency_percentage"), 2))
    _set_dec(fields, "sleep_consistency_percentage", _round(score.get("sleep_consistency_percentage"), 2))

    perf = score.get("sleep_performance_percentage")
    if perf is not None:
        _set_dec(fields, "sleep_performance_percentage", perf)
        _set_dec(fields, "sleep_quality_score", perf)  # backward-compat alias

    if main.get("start"):
        fields["sleep_start"] = main["start"]
    if main.get("end"):
        fields["sleep_end"] = main["end"]

    naps = [r for r in records if r.get("nap", False)]
    if naps:
        fields["nap_count"] = len(naps)
        total_nap_ms = 0
        for nap in naps:
            ns = (nap.get("score") or {}).get("stage_summary") or {}
            total_nap_ms += ns.get("total_in_bed_time_milli", 0) - ns.get("total_awake_time_milli", 0)
        if total_nap_ms > 0:
            _set_dec(fields, "nap_duration_hours", round(total_nap_ms / 3_600_000, 2))
    return fields


def _extract_cycle(cycle: dict) -> dict:
    fields = {}
    records = cycle.get("records", [])
    if not records or records[0].get("score_state") != "SCORED":
        return fields
    score = records[0].get("score") or {}
    _set_dec(fields, "strain", _round(score.get("strain"), 2))
    _set_dec(fields, "kilojoule", _round(score.get("kilojoule"), 2))
    _set_dec(fields, "average_heart_rate", score.get("average_heart_rate"))
    _set_dec(fields, "max_heart_rate", score.get("max_heart_rate"))
    return fields


def _extract_workout(workout: dict) -> dict:
    fields = {}
    sport_id = workout.get("sport_id")
    if sport_id is not None:
        fields["sport_id"] = int(sport_id)
        fields["sport_name"] = WHOOP_SPORT_NAMES.get(sport_id, f"Sport_{sport_id}")
    for key in ("start", "end"):
        if workout.get(key):
            fields[f"{key}_time"] = workout[key]
    if workout.get("score_state") != "SCORED":
        return fields
    score = workout.get("score") or {}
    _set_dec(fields, "strain", _round(score.get("strain"), 2))
    _set_dec(fields, "average_heart_rate", score.get("average_heart_rate"))
    _set_dec(fields, "max_heart_rate", score.get("max_heart_rate"))
    _set_dec(fields, "kilojoule", _round(score.get("kilojoule"), 2))
    _set_dec(fields, "distance_meter", _round(score.get("distance_meter"), 1))
    zone_dur = score.get("zone_duration", {}) or {}
    for i, word in enumerate(_ZONE_WORD):
        ms = zone_dur.get(f"zone_{word}_milli") or 0
        fields[f"zone_{i}_minutes"] = Decimal(str(round(ms / 60_000, 2)))
    return fields


# ── Sleep-onset consistency (cross-day) ───────────────────────────────────────


def _sleep_onset_minutes(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.hour * 60 + dt.minute
    except (ValueError, AttributeError):
        return None


def _compute_sleep_consistency(date_str: str, current_onset: int) -> float | None:
    """Query the prior 6 nights; compute 7-day StdDev of onset times (midnight-aware).

    The whoop partition interleaves DATE#{d}#WORKOUT#{id} sub-records with the
    date-only night records, so a bare Limit=6 descending page can be mostly
    workouts on training-heavy weeks (#488/A-6). Bound the key range to the
    actual 7-day window and skip the workout sub-records.
    """
    window_start = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    resp = _table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#whoop") & Key("sk").between(f"DATE#{window_start}", f"DATE#{date_str}"),
        ProjectionExpression="sk, sleep_onset_minutes",
        ScanIndexForward=False,
    )
    onsets = [current_onset]
    for item in resp.get("Items", []):
        sk = item.get("sk", "")
        if "#WORKOUT#" in sk or sk == f"DATE#{date_str}":
            continue
        val = item.get("sleep_onset_minutes")
        if val is not None:
            onsets.append(int(val))
    if len(onsets) < 3:
        return None
    if max(onsets) - min(onsets) > 720:
        onsets = [v + 1440 if v < 720 else v for v in onsets]
    return round(statistics.stdev(onsets), 1)


# ── SIMP-2 callbacks ──────────────────────────────────────────────────────────

_secret_cache = {"access_token": None}


def authenticate(secret_data: dict) -> dict:
    """Refresh on every cold invocation. Whoop refresh rotates refresh_token,
    so framework's enable_secret_writeback=True persists both back.

    Concurrency-safe (2026-06-08): EventBridge at-least-once delivery occasionally
    fires two invocations seconds apart. The first rotates the single-use refresh
    token; the second then gets HTTP 400. On a 400 we re-read the secret fresh
    (briefly retrying to cover the winner's secret-writeback window) — if a
    concurrent invocation already rotated it, we adopt the winner's tokens rather
    than fail (a raise here DLQs a benign race + false-fires the error alarm).
    A 400 with an *unchanged* refresh_token is a genuine auth failure and raises.
    """
    secret = dict(secret_data)
    try:
        access_token, new_refresh = _refresh_access_token(
            secret["client_id"],
            secret["client_secret"],
            secret["refresh_token"],
        )
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        for _ in range(2):
            time.sleep(1.5)  # let a concurrent invocation persist its rotated token
            fresh = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_NAME)["SecretString"])
            if fresh.get("refresh_token") and fresh["refresh_token"] != secret["refresh_token"]:
                logger.warning("Whoop refresh 400 — a concurrent invocation already rotated the token; adopting it.")
                secret["access_token"] = fresh["access_token"]
                secret["refresh_token"] = fresh["refresh_token"]
                _secret_cache["access_token"] = fresh["access_token"]
                return secret
        logger.error("Whoop refresh 400 with unchanged refresh_token — genuine auth failure.")
        raise
    secret["access_token"] = access_token
    secret["refresh_token"] = new_refresh
    _secret_cache["access_token"] = access_token
    return secret


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Fetch all 4 Whoop endpoints for one calendar day (UTC)."""
    token = _secret_cache["access_token"] or credentials["access_token"]
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    start_dt = f"{date_str}T00:00:00.000Z"
    end_dt = f"{next_day}T00:00:00.000Z"
    return {
        "recovery": _fetch_endpoint(token, "recovery", start_dt, end_dt),
        "sleep": _fetch_endpoint(token, "activity/sleep", start_dt, end_dt),
        "cycle": _fetch_endpoint(token, "cycle", start_dt, end_dt),
        "workouts": _fetch_endpoint(token, "activity/workout", start_dt, end_dt),
    }


def transform(raw: dict, date_str: str) -> list[dict]:
    """Build the daily aggregate item + one item per workout."""
    if not raw:
        return []
    normalized = {}
    normalized.update(_extract_recovery(raw["recovery"]))
    normalized.update(_extract_sleep(raw["sleep"]))
    normalized.update(_extract_cycle(raw["cycle"]))

    # Field-presence validation logging (F2.5)
    critical = ["recovery_score", "hrv", "resting_heart_rate", "sleep_duration_hours", "strain"]
    missing = [f for f in critical if f not in normalized]
    if missing:
        logger.warning("[VALIDATION] whoop/%s missing CRITICAL fields: %s", date_str, missing)

    # Sleep onset + 7-day consistency
    onset_min = _sleep_onset_minutes(normalized.get("sleep_start"))
    if onset_min is not None:
        normalized["sleep_onset_minutes"] = onset_min
        consistency = _compute_sleep_consistency(date_str, onset_min)
        if consistency is not None:
            normalized["sleep_onset_consistency_7d"] = Decimal(str(consistency))

    items = []
    if normalized:
        items.append({"source": "whoop", "date": date_str, **normalized})

    for workout in raw["workouts"].get("records", []):
        wid = workout["id"]
        items.append(
            {
                "source": "whoop",
                "date": date_str,
                "workout_id": wid,
                "sk_suffix": f"#WORKOUT#{wid}",
                **_extract_workout(workout),
            }
        )
    return items


# ── Framework config ──────────────────────────────────────────────────────────

_config = IngestionConfig(
    source_name="whoop",
    secret_id=SECRET_NAME,
    s3_archive_prefix=f"raw/{USER_ID}/whoop",
    schema_version=1,
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
    enable_secret_writeback=True,
    enable_item_size_guard=True,
    refresh_today=True,  # Whoop recovery score finalizes mid-morning
    # Late-arriving workouts (2026-06-24): Whoop stores per-workout sub-records at
    # DATE#{date}#WORKOUT#{id}, but gap detection keys off the DATE#{date} recovery
    # record — so a workout that syncs from the band AFTER that day's recovery was
    # stored lands on an already-"present" date and is silently dropped, exactly the
    # Strava afternoon-walk class. Whoop runs hourly and has no rate-limit breaker, so
    # re-fetching a short trailing window is safe and cheap; it re-emits the per-workout
    # sub-records (keyed by id, idempotent) and picks up the late arrival. 2 days covers
    # the band's continuous-sync latency with buffer.
    refresh_trailing_days=2,
)


def lambda_handler(event: dict, context) -> dict:
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("whoop ingestion failed: %s", e, exc_info=True)
        raise
