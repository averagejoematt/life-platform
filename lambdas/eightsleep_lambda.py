"""
eightsleep_lambda.py — Daily Eight Sleep ingestion Lambda.

Fetches one night of sleep data from the Eight Sleep cloud API and writes
a single DynamoDB record and S3 backup for that night.

Night attribution convention: sleep sessions starting on evening of date D
and ending on morning of D+1 are stored under DATE#(D+1) — i.e. the wake
date — matching the convention used by Whoop and Apple Health.

DynamoDB item:
  pk = USER#matthew#SOURCE#eightsleep
  sk = DATE#YYYY-MM-DD   (wake date)

Fields stored (raw):
  sleep_score              – Eight Sleep overall score (0–100)
  sleep_start              – ISO timestamp of sleep onset (UTC)
  sleep_end                – ISO timestamp of wake (UTC)
  sleep_duration_hours     – Total time asleep (hours)
  time_to_sleep_min        – Sleep onset latency (minutes from lying down to first sleep)
  awake_hours              – Total time in bed minus sleep (latency + WASO combined)
  light_hours              – Light NREM sleep (hours)
  deep_hours               – Deep / slow-wave sleep (hours)
  rem_hours                – REM sleep (hours)
  hr_avg                   – Average heart rate during sleep (bpm)
  hrv_avg                  – Average HRV during sleep (ms)
  respiratory_rate         – Breaths per minute (flag >18 sustained)
  toss_turn_count          – Restlessness proxy
  bed_side                 – "left" or "right" (from secret)

Derived clinical fields (computed at ingestion, queryable by all MCP tools):
  time_in_bed_hours        – sleep + awake (total TIB)
  sleep_efficiency_pct     – sleep / TIB × 100  (clinical target ≥85%)
  waso_hours               – Wake After Sleep Onset = awake_hours − latency
  rem_pct                  – REM as % of TST  (norm 20–25%)
  deep_pct                 – Deep as % of TST (norm 15–25%)
  light_pct                – Light as % of TST (norm 40–60%)
  sleep_onset_hour         – Local fractional hour of sleep onset  (e.g. 23.5 = 11:30 pm)
  wake_hour                – Local fractional hour of wake         (e.g. 7.25 = 7:15 am)
  sleep_midpoint_hour      – Midpoint of sleep session in local time (circadian marker;
                             used for Social Jetlag = |weekday − weekend midpoint|)

Clinical reference ranges:
  Sleep efficiency : ≥85% healthy; <80% consistently → CBT-I territory
  REM %            : 20–25% of TST; <15% on most nights → investigate
  Deep %           : 15–25% of TST; naturally declines with age
  Respiratory rate : 12–18 bpm normal; >18 sustained warrants attention
  Social jetlag    : |weekday midpoint − weekend midpoint| >1 h → metabolic risk

IAM requirements (reuses lambda-whoop-ingestion-role):
  - dynamodb:PutItem on life-platform table
  - s3:PutObject on matthew-life-platform bucket
  - secretsmanager:GetSecretValue + UpdateSecret on life-platform/eightsleep
  - CloudWatch Logs

Secret structure (life-platform/eightsleep):
  {
    "email":         "...",
    "password":      "...",
    "user_id":       "...",         # resolved once and cached
    "access_token":  "...",
    "refresh_token": "...",
    "bed_side":      "left",        # or "right"
    "timezone":      "America/Los_Angeles"
  }

Usage (manual trigger):
  aws lambda invoke \\
    --function-name eightsleep-data-ingestion \\
    --payload '{"date": "2024-12-25"}' \\
    --region us-west-2 /tmp/out.json

Default (no payload): ingests yesterday's wake date.
"""

import gzip
import os
import logging
import json
import math
import urllib.request
import urllib.parse
import urllib.error
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("eightsleep")
except ImportError:
    logger = logging.getLogger("eightsleep")
    logger.setLevel(logging.INFO)

# ── Constants ──────────────────────────────────────────────────────────────────
SECRET_NAME    = "life-platform/eightsleep"
# ── Config (env vars with backwards-compatible defaults) ──
REGION         = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET      = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ.get("USER_ID", "matthew")
LOOKBACK_DAYS  = int(os.environ.get("LOOKBACK_DAYS", "7"))

# Eight Sleep API bases
CLIENT_API = "https://client-api.8slp.net"
AUTH_API   = "https://auth-api.8slp.net"

# OAuth2 client credentials — loaded from Secrets Manager at first use
_es_client_cache = None


def _get_es_client_creds():
    global _es_client_cache
    if _es_client_cache is not None:
        return _es_client_cache
    try:
        _es_client_cache = json.loads(_cached_secret(secrets_client, "life-platform/eightsleep-client"))
    except Exception as e:
        logger.warning(f"[eightsleep] Failed to load client creds from Secrets Manager: {e}")
        _es_client_cache = {}
    return _es_client_cache

# ── Timezone offset map ────────────────────────────────────────────────────────
# No pytz in Lambda. DST offset is ±1h — acceptable for circadian analysis
# where we care about consistency rather than exact precision.
_TZ_OFFSETS = {
    "America/Los_Angeles": -8,
    "America/Vancouver":   -8,
    "America/Denver":      -7,
    "America/Chicago":     -6,
    "America/New_York":    -5,
    "Europe/London":        0,
    "Europe/Paris":         1,
    "Europe/Berlin":        1,
    "Asia/Tokyo":           9,
    "Australia/Sydney":    10,
}
_DEFAULT_TZ_OFFSET = -8  # PST (Seattle)

# ── AWS clients (module-level — reused across Lambda warm invocations) ─────────
secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client      = boto3.client("s3",             region_name=REGION)
dynamodb       = boto3.resource("dynamodb",      region_name=REGION)
table          = dynamodb.Table(DYNAMODB_TABLE)

# COST-OPT-1: Cache secrets in warm Lambda containers (15-min TTL)
_secret_cache = {}


def _cached_secret(client, secret_id):
    import time as _t
    entry = _secret_cache.get(secret_id)
    if entry and _t.time() - entry[1] < 900:
        return entry[0]
    val = client.get_secret_value(SecretId=secret_id)["SecretString"]
    _secret_cache[secret_id] = (val, _t.time())
    return val


# ── Serialisation ──────────────────────────────────────────────────────────────
# Phase 4.2 (2026-05-16): canonical impl in lambdas/numeric.py.
try:
    from numeric import floats_to_decimal  # noqa: F401
except ImportError:
    def floats_to_decimal(obj):
        if isinstance(obj, bool): return obj
        if isinstance(obj, float): return Decimal(str(obj))
        if isinstance(obj, dict): return {k: floats_to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list): return [floats_to_decimal(v) for v in obj]
        return obj


# ── Secrets ────────────────────────────────────────────────────────────────────
def get_secret():
    return json.loads(_cached_secret(secrets_client, SECRET_NAME))


def save_secret(secret: dict):
    secrets_client.update_secret(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(secret),
    )
    _secret_cache.pop(SECRET_NAME, None)  # Invalidate cache after token refresh


# ── Auth ───────────────────────────────────────────────────────────────────────
def login(email: str, password: str, client_id: str = None, client_secret: str = None, **kwargs) -> dict:
    """OAuth2 password-grant. Returns {access_token, refresh_token, user_id}."""
    payload = json.dumps({
        "client_id":     client_id or _get_es_client_creds().get("client_id", ""),
        "client_secret": client_secret or _get_es_client_creds().get("client_secret", ""),
        "grant_type":    "password",
        "username":      email,
        "password":      password,
    }).encode()

    req = urllib.request.Request(
        f"{AUTH_API}/v1/tokens",
        data=payload,
        headers={
            "Content-Type":    "application/json",
            "Accept":          "application/json",
            "Accept-Encoding": "gzip",
            "user-agent":      "okhttp/4.9.3",
        },
        method="POST",
    )
    # Phase 3.5 (2026-05-16): retry on transient 429/5xx.
    from http_retry import urlopen_with_retry
    with urlopen_with_retry(req, timeout=30) as resp:
        data = json.loads(resp.read())

    return {
        "access_token":  data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "user_id":       data["userId"],
    }


def refresh_token(secret: dict) -> dict:
    """Re-login to get a fresh token (Eight Sleep v1 has no refresh endpoint)."""
    token_data = login(secret["email"], secret["password"])
    secret["access_token"]  = token_data["access_token"]
    secret["refresh_token"] = token_data["refresh_token"]
    return secret


def ensure_user_id(secret: dict) -> dict:
    """Resolve and cache user_id if missing from secret."""
    if secret.get("user_id"):
        return secret
    print("Resolving user_id from /v1/users/me ...")
    req = urllib.request.Request(
        f"{CLIENT_API}/v1/users/me",
        headers={"Authorization": f"Bearer {secret['access_token']}"},
    )
    # Phase 3.5 (2026-05-16): retry on transient 429/5xx.
    from http_retry import urlopen_with_retry
    with urlopen_with_retry(req, timeout=30) as resp:
        data = json.loads(resp.read())
    secret["user_id"] = data["user"]["userId"]
    print(f"Resolved user_id: {secret['user_id']}")
    return secret


def api_get(path: str, access_token: str, params: dict = None) -> dict:
    url = CLIENT_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization":   f"Bearer {access_token}",
            "Content-Type":    "application/json",
            "Accept":          "application/json",
            "Accept-Encoding": "gzip",
            "user-agent":      "okhttp/4.9.3",
        },
    )
    # Phase 3.5 (2026-05-16): retry on transient 429/5xx.
    # Note: http_retry wraps the response and hides .headers — detect gzip via
    # magic bytes (1f 8b) instead of relying on the Content-Encoding header.
    from http_retry import urlopen_with_retry
    with urlopen_with_retry(req, timeout=30) as resp:
        raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw)


# ── Derived field helpers ──────────────────────────────────────────────────────

def _safe_float(val, divisor=1):
    """Convert val to float; return None on failure."""
    try:
        return round(float(val) / divisor, 2) if val is not None else None
    except (TypeError, ValueError):
        return None


def _hour_of_day(iso_ts: str, tz_offset: int = _DEFAULT_TZ_OFFSET) -> float | None:
    """
    Extract local fractional hour (0.0–24.0) from an ISO UTC timestamp.

    Examples:
      "2026-02-20T06:54:00.000Z" with tz_offset=-8 → 22.9 (10:54 pm PST prev evening)
      "2026-02-21T18:06:30.000Z" with tz_offset=-8 →  7.11 (7:06 am PST)

    Returns a float where 23.5 = 11:30 pm and 6.75 = 6:45 am.
    """
    try:
        ts = iso_ts.split(".")[0].rstrip("Z").replace("+00:00", "")
        dt = datetime.fromisoformat(ts)
        local_hour = (dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + tz_offset) % 24
        return round(local_hour, 2)
    except Exception:
        return None


def _sleep_midpoint(onset_hour: float, wake_hour: float) -> float:
    """
    Compute sleep midpoint handling midnight crossing.
    e.g. onset=23.0, wake=7.0 → midpoint=3.0  (not 15.0)
    """
    if wake_hour <= onset_hour:     # session crosses midnight
        wake_hour += 24
    return round(((onset_hour + wake_hour) / 2.0) % 24, 2)


def compute_derived_fields(record: dict, tz_offset: int = _DEFAULT_TZ_OFFSET) -> dict:
    """
    Compute all derived clinical fields from a parsed record dict.
    Safe to call on freshly-parsed records AND existing DynamoDB items
    (the backfill script uses this function directly).
    Returns a dict of NEW fields only — caller merges into existing record.
    """
    derived = {}

    sleep_h     = record.get("sleep_duration_hours")
    awake_h     = record.get("awake_hours")
    latency_min = record.get("time_to_sleep_min")
    rem_h       = record.get("rem_hours")
    deep_h      = record.get("deep_hours")
    light_h     = record.get("light_hours")
    sleep_start = record.get("sleep_start")
    sleep_end   = record.get("sleep_end")

    # ── Time in bed & sleep efficiency ────────────────────────────────────────
    if sleep_h is not None and awake_h is not None:
        tib = round(float(sleep_h) + float(awake_h), 2)
        derived["time_in_bed_hours"] = tib
        if tib > 0:
            derived["sleep_efficiency_pct"] = round(float(sleep_h) / tib * 100, 1)

    # ── WASO — true Wake After Sleep Onset ────────────────────────────────────
    # awake_hours from API = presenceDuration − sleepDuration
    # = latency + WASO combined.  Separating them:
    if awake_h is not None and latency_min is not None:
        latency_h = float(latency_min) / 60.0
        waso = max(round(float(awake_h) - latency_h, 2), 0.0)
        derived["waso_hours"] = waso

    # ── Stage percentages ─────────────────────────────────────────────────────
    if sleep_h and float(sleep_h) > 0:
        sh = float(sleep_h)
        if rem_h   is not None: derived["rem_pct"]   = round(float(rem_h)   / sh * 100, 1)
        if deep_h  is not None: derived["deep_pct"]  = round(float(deep_h)  / sh * 100, 1)
        if light_h is not None: derived["light_pct"] = round(float(light_h) / sh * 100, 1)

    # ── Circadian timing ──────────────────────────────────────────────────────
    onset_h = _hour_of_day(sleep_start, tz_offset) if sleep_start else None
    wake_h  = _hour_of_day(sleep_end,   tz_offset) if sleep_end   else None

    if onset_h is not None:
        derived["sleep_onset_hour"] = onset_h
    if wake_h is not None:
        derived["wake_hour"] = wake_h
    if onset_h is not None and wake_h is not None:
        derived["sleep_midpoint_hour"] = _sleep_midpoint(onset_h, wake_h)

    return derived


# ── Sleep data parsing ─────────────────────────────────────────────────────────



def fetch_temperature_data(user_id: str, access_token: str, wake_date: str, tz: str) -> dict:
    """
    Fetch bed temperature data from Eight Sleep intervals endpoint.
    Returns dict of temperature fields, or empty dict if unavailable.
    Always safe — never raises exceptions that would block normal ingestion.
    """
    from_date = (datetime.strptime(wake_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        data = api_get(
            f"/v2/users/{user_id}/intervals",
            access_token,
            params={"from": from_date, "to": wake_date, "tz": tz},
        )

        intervals = data.get("intervals") or data.get("data") or []
        if not intervals:
            print(f"No intervals data returned for {wake_date}")
            return {}

        target = None
        for interval in intervals:
            int_date = interval.get("day") or interval.get("date") or ""
            if int_date == wake_date:
                target = interval
                break
        if target is None and len(intervals) == 1:
            target = intervals[0]
        if target is None:
            print(f"No interval matching {wake_date}")
            return {}

        result = {}

        # Method 1: Top-level temperature fields
        if target.get("tempBedC") is not None:
            result["bed_temp_c"] = round(float(target["tempBedC"]), 1)
            result["bed_temp_f"] = round(float(target["tempBedC"]) * 9/5 + 32, 1)
        if target.get("tempRoomC") is not None:
            result["room_temp_c"] = round(float(target["tempRoomC"]), 1)
            result["room_temp_f"] = round(float(target["tempRoomC"]) * 9/5 + 32, 1)

        # Method 2: Timeseries temperature data
        ts = target.get("timeseries") or {}
        bed_temps = ts.get("tempBedC") or ts.get("tempBed") or []
        room_temps = ts.get("tempRoomC") or ts.get("tempRoom") or []

        if bed_temps and not result.get("bed_temp_c"):
            vals = []
            for point in bed_temps:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    try: vals.append(float(point[1]))
                    except (ValueError, TypeError): pass
                elif isinstance(point, (int, float)):
                    vals.append(float(point))
            if vals:
                result["bed_temp_c"] = round(sum(vals) / len(vals), 1)
                result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
                result["bed_temp_min_c"] = round(min(vals), 1)
                result["bed_temp_max_c"] = round(max(vals), 1)

        if room_temps and not result.get("room_temp_c"):
            vals = []
            for point in room_temps:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    try: vals.append(float(point[1]))
                    except (ValueError, TypeError): pass
                elif isinstance(point, (int, float)):
                    vals.append(float(point))
            if vals:
                result["room_temp_c"] = round(sum(vals) / len(vals), 1)
                result["room_temp_f"] = round(result["room_temp_c"] * 9/5 + 32, 1)

        # Method 3: Per-stage temperature settings (heating/cooling level)
        stages = target.get("stages") or []
        temp_levels = []
        for stage in stages:
            temp_info = stage.get("temp") or stage.get("temperature") or {}
            level = temp_info.get("level")
            if level is not None:
                try: temp_levels.append(float(level))
                except (ValueError, TypeError): pass
            stage_bed = temp_info.get("bedC") or temp_info.get("bed_temp_c")
            if stage_bed is not None and "bed_temp_c" not in result:
                try:
                    result["bed_temp_c"] = round(float(stage_bed), 1)
                    result["bed_temp_f"] = round(float(stage_bed) * 9/5 + 32, 1)
                except (ValueError, TypeError):
                    pass

        if temp_levels:
            result["temp_level_avg"] = round(sum(temp_levels) / len(temp_levels), 1)
            result["temp_level_min"] = round(min(temp_levels), 1)
            result["temp_level_max"] = round(max(temp_levels), 1)

        # Method 4: sleepQualityScore temperature hint
        sq = target.get("sleepQualityScore") or {}
        for key in ["temperature", "tempBedC", "bedTemp"]:
            val = sq.get(key)
            if isinstance(val, dict) and val.get("current") is not None and "bed_temp_c" not in result:
                try:
                    result["bed_temp_c"] = round(float(val["current"]), 1)
                    result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
                except (ValueError, TypeError):
                    pass

        if result:
            print(f"Temperature data found: {list(result.keys())}")
        else:
            print(f"No temperature data found in intervals response")
            print(f"  Interval keys: {list(target.keys())[:15]}")

        return result

    except urllib.error.HTTPError as e:
        print(f"Intervals endpoint error: HTTP {e.code}")
        return {}
    except Exception as e:
        print(f"Temperature fetch exception: {e}")
        return {}


def parse_trends_for_date(
    trends_data: dict,
    wake_date:   str,
    bed_side:    str,
    tz_offset:   int = _DEFAULT_TZ_OFFSET,
) -> dict | None:
    """
    Extract one night matching wake_date from the Eight Sleep trends API response.

    API response shape:
      {
        "days": [
          {
            "day":             "YYYY-MM-DD",   # local wake date
            "score":           76,
            "sleepDuration":   30870,          # seconds asleep
            "remDuration":     9180,
            "lightDuration":   16770,
            "deepDuration":    4920,
            "presenceDuration":49410,          # time in bed
            "sleepStart":      "<ISO UTC>",
            "sleepEnd":        "<ISO UTC>",
            "tnt":             36,
            "sleepQualityScore": {
              "hrv":             {"current": 36.2},
              "heartRate":       {"current": 56},
              "respiratoryRate": {"current": 12.8},
            },
            "sleepRoutineScore": {
              "latencyAsleepSeconds": {"current": 8040},
            },
          }, ...
        ]
      }
    """
    days = trends_data.get("days") or []
    if not days:
        print("No days found in trends response.")
        return None

    target = next((d for d in days if d.get("day") == wake_date), None)
    if target is None and len(days) == 1:
        target = days[0]
    if target is None:
        print(f"No day matching {wake_date}. Available: {[d.get('day','?') for d in days]}")
        return None

    def secs_to_hours(s):
        return round(s / 3600.0, 2) if s else None

    sleep_s    = target.get("sleepDuration") or 0
    presence_s = target.get("presenceDuration") or 0
    awake_s    = max(presence_s - sleep_s, 0)

    sq  = target.get("sleepQualityScore") or {}
    sr  = target.get("sleepRoutineScore") or {}

    hr_avg    = _safe_float((sq.get("heartRate")       or {}).get("current"))
    hrv_avg   = _safe_float((sq.get("hrv")             or {}).get("current"))
    resp_rate = _safe_float((sq.get("respiratoryRate") or {}).get("current"))

    latency_s   = (sr.get("latencyAsleepSeconds") or {}).get("current")
    latency_min = round(float(latency_s) / 60.0, 1) if latency_s else None

    sleep_start = target.get("sleepStart")
    sleep_end   = target.get("sleepEnd")

    record = {
        "sleep_score":          _safe_float(target.get("score")),
        "sleep_start":          sleep_start,
        "sleep_end":            sleep_end,
        "sleep_duration_hours": secs_to_hours(sleep_s),
        "time_to_sleep_min":    latency_min,
        "awake_hours":          secs_to_hours(awake_s),
        "light_hours":          secs_to_hours(target.get("lightDuration")),
        "deep_hours":           secs_to_hours(target.get("deepDuration")),
        "rem_hours":            secs_to_hours(target.get("remDuration")),
        "hr_avg":               hr_avg,
        "hrv_avg":              hrv_avg,
        "respiratory_rate":     resp_rate,
        "toss_turn_count":      _safe_float(target.get("tnt")),
        "bed_side":             bed_side,
    }
    # Strip None values before computing derived fields
    record = {k: v for k, v in record.items() if v is not None}

    # ── Field presence validation (F2.5) ──────────────────────────────────────
    ES_CRITICAL = ["sleep_score", "sleep_duration_hours", "sleep_start", "sleep_end"]
    ES_EXPECTED = ["deep_hours", "rem_hours", "light_hours", "hr_avg",
                   "hrv_avg", "respiratory_rate", "time_to_sleep_min"]
    missing_crit = [f for f in ES_CRITICAL if f not in record]
    missing_exp = [f for f in ES_EXPECTED if f not in record]
    if missing_crit:
        print(f"[VALIDATION] ⚠️ CRITICAL fields missing for {wake_date}: {missing_crit}")
    if missing_exp:
        print(f"[VALIDATION] Expected fields missing for {wake_date}: {missing_exp}")

    # Compute and merge all derived clinical fields
    record.update(compute_derived_fields(record, tz_offset))

    return record


# ── Core ingestion ─────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# P4.1 SIMP-2 framework migration (2026-05-17)
# ══════════════════════════════════════════════════════════════════════════════

from ingestion_framework import IngestionConfig, run_ingestion

_secret_cache_simp2 = {"secret": None}


def authenticate(secret_data: dict) -> dict:
    """Reuse cached access_token; full re-login only if missing. Eight Sleep v1
    has no refresh-token endpoint — refresh = re-login with email/password, so
    we avoid proactive refresh to minimize token churn. fetch_day handles
    on-demand 401 → re-login."""
    secret = dict(secret_data)
    if not secret.get("access_token"):
        secret = refresh_token(secret)
    secret = ensure_user_id(secret)
    _secret_cache_simp2["secret"] = secret
    return secret


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Fetch trends for one wake_date. Returns raw + temperature data."""
    secret = _secret_cache_simp2["secret"] or credentials
    user_id_es = secret["user_id"]
    token = secret["access_token"]
    bed_side = secret.get("bed_side", "left")
    tz = secret.get("timezone", "America/Los_Angeles")
    from_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        trends = api_get(f"/v1/users/{user_id_es}/trends", token,
                         params={"from": from_date, "to": date_str, "tz": tz})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            logger.info("Eight Sleep 401 — re-logging in and retrying...")
            secret = refresh_token(secret)
            _secret_cache_simp2["secret"] = secret
            trends = api_get(f"/v1/users/{user_id_es}/trends", secret["access_token"],
                             params={"from": from_date, "to": date_str, "tz": tz})
        else:
            raise
    temp = fetch_temperature_data(user_id_es, secret["access_token"], date_str, tz)
    return {"trends": trends, "temp": temp, "bed_side": bed_side, "tz": tz}


def transform(raw: dict, date_str: str) -> list[dict]:
    """Parse sleep + merge environment temperature."""
    if not raw:
        return []
    tz_offset = _TZ_OFFSETS.get(raw["tz"], _DEFAULT_TZ_OFFSET)
    parsed = parse_trends_for_date(raw["trends"], date_str, raw["bed_side"], tz_offset=tz_offset)
    if not parsed:
        return []
    return [{
        "source": "eightsleep",
        "date":   date_str,
        **parsed,
        **(raw["temp"] or {}),
    }]


_config = IngestionConfig(
    source_name="eightsleep",
    secret_id=SECRET_NAME,
    s3_archive_prefix=f"raw/{USER_ID}/eightsleep",
    schema_version=1,
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
    enable_secret_writeback=True,
    enable_item_size_guard=True,
    refresh_today=True,
)


def lambda_handler(event: dict, context) -> dict:
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("eightsleep ingestion failed: %s", e, exc_info=True)
        raise


