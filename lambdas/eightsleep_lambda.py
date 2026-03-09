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
USER_ID        = os.environ["USER_ID"]
LOOKBACK_DAYS  = int(os.environ.get("LOOKBACK_DAYS", "7"))

# Eight Sleep API bases
CLIENT_API = "https://client-api.8slp.net"
AUTH_API   = "https://auth-api.8slp.net"

# OAuth2 client credentials (from pyEight open-source library)
KNOWN_CLIENT_ID     = "0894c7f33bb94800a03f1f4df13a4f38"
KNOWN_CLIENT_SECRET = "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86db0c76"

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


# ── Serialisation ──────────────────────────────────────────────────────────────
def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


# ── Secrets ────────────────────────────────────────────────────────────────────
def get_secret():
    resp = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])


def save_secret(secret: dict):
    secrets_client.update_secret(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(secret),
    )


# ── Auth ───────────────────────────────────────────────────────────────────────
def login(email: str, password: str, client_id: str = None, client_secret: str = None, **kwargs) -> dict:
    """OAuth2 password-grant. Returns {access_token, refresh_token, user_id}."""
    payload = json.dumps({
        "client_id":     client_id or KNOWN_CLIENT_ID,
        "client_secret": client_secret or KNOWN_CLIENT_SECRET,
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
    with urllib.request.urlopen(req, timeout=30) as resp:
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
    with urllib.request.urlopen(req, timeout=30) as resp:
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
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

def ingest_day(wake_date: str, secret: dict) -> dict:
    """Fetch sleep data for wake_date, write to S3 + DynamoDB. Returns parsed record."""
    user_id   = secret["user_id"]
    token     = secret["access_token"]
    bed_side  = secret.get("bed_side", "left")
    tz        = secret.get("timezone", "America/Los_Angeles")
    tz_offset = _TZ_OFFSETS.get(tz, _DEFAULT_TZ_OFFSET)

    from_date = (datetime.strptime(wake_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    to_date   = wake_date

    print(f"Fetching trends for user={user_id} side={bed_side} window={from_date}→{to_date}")

    trends = api_get(
        f"/v1/users/{user_id}/trends",
        token,
        params={"from": from_date, "to": to_date, "tz": tz},
    )

    parsed = parse_trends_for_date(trends, wake_date, bed_side, tz_offset=tz_offset)

    if parsed is None:
        print(f"No sleep data found for wake_date={wake_date}")
        return {}

    # ── Fetch temperature data (Feature #6: Sleep Environment) ────────────
    temp_data = fetch_temperature_data(user_id, token, wake_date, tz)

    # ── S3 backup ──────────────────────────────────────────────────────────────
    s3_key = f"raw/eightsleep/{wake_date[:4]}/{wake_date[5:7]}/{wake_date[8:10]}.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps({
            "wake_date":   wake_date,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "raw":         trends,
            "parsed":      parsed,
        }, default=str),
        ContentType="application/json",
    )
    print(f"S3: s3://{S3_BUCKET}/{s3_key}")

    # ── DynamoDB ───────────────────────────────────────────────────────────────
    db_item = {
        "pk":             f"USER#{USER_ID}#SOURCE#eightsleep",
        "sk":             f"DATE#{wake_date}",
        "date":           wake_date,
        "source":         "eightsleep",
        "schema_version": 1,
        "ingested_at":    datetime.now(timezone.utc).isoformat(),
        **parsed,
        **(floats_to_decimal(temp_data) if temp_data else {}),
    }
    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item
        _vr = _validate_item("eightsleep", floats_to_decimal(db_item), wake_date)
        if _vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping eightsleep DDB write for {wake_date}: {_vr.errors}")
            _vr.archive_to_s3(s3_client, bucket=S3_BUCKET, item=db_item)
        else:
            if _vr.warnings:
                logger.warning(f"[DATA-2] Validation warnings for eightsleep/{wake_date}: {_vr.warnings}")
            table.put_item(Item=floats_to_decimal(db_item))
            print(f"DynamoDB: DATE#{wake_date} → {len(parsed)} fields written")
    except ImportError:
        table.put_item(Item=floats_to_decimal(db_item))
        print(f"DynamoDB: DATE#{wake_date} → {len(parsed)} fields written")

    return parsed


# ── Lambda handler ─────────────────────────────────────────────────────────────

# ── Gap detection (v2.0) ──────────────────────────────────────────────────────
def find_missing_dates(lookback_days=LOOKBACK_DAYS):
    """Check DynamoDB for missing Eight Sleep records in the lookback window."""
    from boto3.dynamodb.conditions import Key
    today = datetime.now(timezone.utc).date()
    check_dates = set()
    for i in range(1, lookback_days + 1):
        check_dates.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))

    oldest = min(check_dates)
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#eightsleep")
            & Key("sk").between(f"DATE#{oldest}", f"DATE#{today.strftime('%Y-%m-%d')}"),
        ProjectionExpression="sk",
    )
    existing = {item["sk"][5:] for item in resp.get("Items", [])}
    missing = sorted(check_dates - existing)
    if missing:
        print(f"[GAP-FILL] Found {len(missing)} missing dates in last {lookback_days} days: {missing}")
    else:
        print(f"[GAP-FILL] No gaps in last {lookback_days} days")
    return missing


# ── Lambda handler ─────────────────────────────────────────────────────────────

def _ensure_auth(secret):
    """Ensure valid access token, refreshing if needed. Returns updated secret."""
    if not secret.get("access_token"):
        print("No access token — performing full login...")
        secret.update(login(secret["email"], secret["password"]))
        save_secret(secret)
    return secret


def _ingest_with_retry(wake_date, secret):
    """Ingest a single day with 401 retry. Returns (result, updated_secret)."""
    try:
        return ingest_day(wake_date, secret), secret
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("401 — refreshing token and retrying...")
            secret = refresh_token(secret)
            save_secret(secret)
            return ingest_day(wake_date, secret), secret
        raise


def lambda_handler(event, context):
    import time as _time
    logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1

    # ── Mode 1: Explicit date (manual invoke / backfill) ──
    if event.get("date"):
        wake_date = event["date"]
        print(f"Eight Sleep ingestion — explicit date={wake_date}")
        secret = get_secret()
        secret = _ensure_auth(secret)
        result, _ = _ingest_with_retry(wake_date, secret)
        if not result:
            return {"statusCode": 204, "body": json.dumps({"message": f"No sleep data for {wake_date}"})}
        return {
            "statusCode": 200,
            "body": json.dumps({
                "wake_date": wake_date,
                "sleep_score": result.get("sleep_score"),
                "sleep_duration_hours": result.get("sleep_duration_hours"),
            }, default=str),
        }

    # ── Mode 2: Scheduled run — gap-aware lookback ──
    print(f"[GAP-FILL] Eight Sleep gap-aware lookback ({LOOKBACK_DAYS} days)")
    missing_dates = find_missing_dates()

    if not missing_dates:
        return {"statusCode": 200, "body": json.dumps({"message": "No gaps to fill", "lookback_days": LOOKBACK_DAYS})}

    secret = get_secret()
    secret = _ensure_auth(secret)
    results = {}

    for i, wake_date in enumerate(missing_dates):
        print(f"[GAP-FILL] Ingesting {wake_date} ({i+1}/{len(missing_dates)})")
        try:
            result, secret = _ingest_with_retry(wake_date, secret)
            results[wake_date] = result.get("sleep_score") if result else "no data"
        except Exception as e:
            print(f"[GAP-FILL] ERROR on {wake_date}: {e}")
            results[wake_date] = f"error: {e}"
        if i < len(missing_dates) - 1:
            _time.sleep(1)  # Rate limit pacing

    filled = sum(1 for v in results.values() if v not in ("no data",) and not str(v).startswith("error"))
    print(f"[GAP-FILL] Complete: {filled}/{len(missing_dates)} days filled")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "mode": "gap_fill",
            "lookback_days": LOOKBACK_DAYS,
            "gaps_found": len(missing_dates),
            "gaps_filled": filled,
            "details": results,
        }, default=str),
    }
