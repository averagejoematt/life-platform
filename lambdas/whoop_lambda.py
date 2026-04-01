import json
import os
import logging
import boto3
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import statistics

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("whoop")
except ImportError:
    logger = logging.getLogger("whoop")
    logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION         = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET      = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ["USER_ID"]
SECRET_NAME    = os.environ.get("WHOOP_SECRET_NAME", "life-platform/whoop")
LOOKBACK_DAYS  = int(os.environ.get("LOOKBACK_DAYS", "7"))

WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"

# Scopes requested on every token refresh.
WHOOP_SCOPES = (
    "offline read:recovery read:cycles read:workout read:sleep "
    "read:profile read:body_measurement"
)

# Partial lookup table — add entries as you discover unknown sport IDs.
# Unknown IDs are stored as "Sport_<id>" so you can identify them later.
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




# ── Sleep onset consistency helpers ──────────────────────────────────────────

def _sleep_onset_minutes(iso_timestamp):
    """
    Convert an ISO sleep_start timestamp to minutes from midnight (UTC).
    Returns int or None if parsing fails.
    """
    if not iso_timestamp:
        return None
    try:
        # Handle both 'Z' suffix and '+00:00' formats
        ts = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        return dt.hour * 60 + dt.minute
    except (ValueError, AttributeError):
        return None


def _compute_sleep_consistency(table, date_str, current_onset_minutes, log=print):
    """
    Query last 6 Whoop records before date_str, combine with today's onset,
    compute 7-day StdDev of sleep onset times.
    
    Handles midnight wraparound: if range > 720 min, shift values crossing midnight
    so that e.g. 23:30 (1410) and 00:30 (30) are treated as 60 min apart.
    
    Returns StdDev in minutes (float) or None if <3 data points.
    """
    if current_onset_minutes is None:
        return None

    # Query previous 6 days of sleep_onset_minutes
    from boto3.dynamodb.conditions import Key
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#whoop")
            & Key("sk").lt(f"DATE#{date_str}"),
        ProjectionExpression="sleep_onset_minutes",
        ScanIndexForward=False,  # newest first
        Limit=6,
    )

    onsets = [current_onset_minutes]
    for item in resp.get("Items", []):
        val = item.get("sleep_onset_minutes")
        if val is not None:
            onsets.append(int(val))

    if len(onsets) < 3:
        log(f"[INFO] Sleep consistency: only {len(onsets)} data points, need ≥3")
        return None

    # Handle midnight wraparound using circular adjustment
    # If spread is >720 min, some values are on opposite sides of midnight
    min_val = min(onsets)
    max_val = max(onsets)
    if max_val - min_val > 720:
        # Shift values < 720 up by 1440 (treat early morning as "late night")
        onsets = [v + 1440 if v < 720 else v for v in onsets]

    sd = statistics.stdev(onsets)
    log(f"[INFO] Sleep consistency: {len(onsets)} points, StdDev={sd:.1f} min")
    return round(sd, 1)


# ── Lambda entry point ────────────────────────────────────────────────────────

# ── Module-level AWS clients (used by gap detection + handler) ─────────────────
_secretsmanager = boto3.client("secretsmanager", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)
_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE)


# ── Gap detection (v2.0) ──────────────────────────────────────────────────────
def find_missing_dates(lookback_days=LOOKBACK_DAYS):
    """Check DynamoDB for missing Whoop records in the lookback window."""
    from boto3.dynamodb.conditions import Key
    today = datetime.now(timezone.utc).date()
    check_dates = set()
    for i in range(0, lookback_days + 1):  # includes today
        check_dates.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))

    oldest = min(check_dates)
    resp = _table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#whoop")
            & Key("sk").between(f"DATE#{oldest}", f"DATE#{today.strftime('%Y-%m-%d')}"),
        ProjectionExpression="sk",
    )
    # Only count base date records, not WORKOUT sub-items
    existing = set()
    for item in resp.get("Items", []):
        sk = item["sk"]
        if sk.startswith("DATE#") and "#" not in sk[5:]:
            existing.add(sk[5:])

    missing = sorted(check_dates - existing)
    if missing:
        print(f"[GAP-FILL] Found {len(missing)} missing dates in last {lookback_days} days: {missing}")
    else:
        print(f"[GAP-FILL] No gaps in last {lookback_days} days")
    return missing


def lambda_handler(event, context):
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        import time as _time
        if hasattr(logger, "set_date"): logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1

        # Support date_override from EventBridge event payload
        # 'today' = pull today's data (for recovery refresh after wake)
        # 'YYYY-MM-DD' = pull specific date
        # None/missing = gap-aware lookback
        date_override = event.get('date_override') if isinstance(event, dict) else None

        # ── Auth (shared across all modes) ──
        print("[INFO] Reading credentials from Secrets Manager...")
        credentials = json.loads(
            _secretsmanager.get_secret_value(SecretId=SECRET_NAME)["SecretString"]
        )
        print("[INFO] Refreshing Whoop access token...")
        access_token, new_refresh_token = refresh_access_token(
            credentials["client_id"],
            credentials["client_secret"],
            credentials["refresh_token"],
        )
        print("[INFO] Access token refreshed successfully")
        credentials["access_token"] = access_token
        credentials["refresh_token"] = new_refresh_token
        _secretsmanager.update_secret(
            SecretId=SECRET_NAME,
            SecretString=json.dumps(credentials),
        )
        print("[INFO] Tokens updated in Secrets Manager")

        # ── Mode 1: Explicit date override (recovery refresh or manual) ──
        if date_override:
            if date_override == 'today':
                target_date = datetime.now(timezone.utc).date()
            else:
                target_date = datetime.strptime(date_override, '%Y-%m-%d').date()
            date_str = target_date.strftime("%Y-%m-%d")
            print(f"[INFO] Single-day mode: date={date_str} (override={date_override})")
            summary = ingest_day(date_str, access_token, _s3, _table, verbose=True)
            print(f"[INFO] Completed. summary={summary}")
            return {"statusCode": 200, "body": json.dumps({"date": date_str, **summary})}

        # ── Mode 2: Scheduled run — gap-aware lookback ──
        print(f"[GAP-FILL] Whoop gap-aware lookback ({LOOKBACK_DAYS} days)")
        missing_dates = find_missing_dates()

        if not missing_dates:
            return {"statusCode": 200, "body": json.dumps({"message": "No gaps to fill", "lookback_days": LOOKBACK_DAYS})}

        results = {}
        for i, date_str in enumerate(missing_dates):
            print(f"[GAP-FILL] Ingesting {date_str} ({i+1}/{len(missing_dates)})")
            try:
                summary = ingest_day(date_str, access_token, _s3, _table, verbose=True, call_delay=0.5)
                results[date_str] = summary.get("workout_count", 0) if summary else 0
            except Exception as e:
                print(f"[GAP-FILL] ERROR on {date_str}: {e}")
                results[date_str] = f"error: {e}"
            if i < len(missing_dates) - 1:
                _time.sleep(1)  # Rate limit pacing between days

        filled = sum(1 for v in results.values() if isinstance(v, int))
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
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise


# ── Core per-day ingestion (shared by Lambda and backfill) ────────────────────

def ingest_day(date_str, access_token, s3_client, table, verbose=True, call_delay=0.0):
    """
    Fetch and store all Whoop data for one calendar day (UTC).

    Writes to S3:
      raw/whoop/recovery/{Y}/{M}/{D}.json
      raw/whoop/sleep/{Y}/{M}/{D}.json
      raw/whoop/cycle/{Y}/{M}/{D}.json
      raw/whoop/workout/{Y}/{M}/{D}/{workout_id}.json  (one per workout)

    Writes to DynamoDB:
      pk=USER#matthew#SOURCE#whoop  sk=DATE#{date_str}
          → recovery + sleep + cycle fields merged into one item
      pk=USER#matthew#SOURCE#whoop  sk=DATE#{date_str}#WORKOUT#{id}
          → one item per workout

    call_delay: seconds to sleep between the 4 API calls (use >0 during backfill
                to stay well under the Whoop rate limit).

    Returns a summary dict with all 20 daily fields + workout_count.
    """
    import time as _time

    def log(msg):
        if verbose:
            print(msg)

    year, month, day = date_str.split("-")
    next_day = (
        datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    start_dt = f"{date_str}T00:00:00.000Z"
    end_dt = f"{next_day}T00:00:00.000Z"

    # ── Fetch (with optional inter-call pacing) ────────────────────────────────
    log(f"[INFO] Fetching recovery ({date_str})...")
    recovery_data = fetch_whoop_endpoint(access_token, "recovery", start_dt, end_dt)
    log(f"[INFO] recovery records: {len(recovery_data.get('records', []))}")
    if call_delay: _time.sleep(call_delay)

    log(f"[INFO] Fetching sleep ({date_str})...")
    sleep_data = fetch_whoop_endpoint(access_token, "activity/sleep", start_dt, end_dt)
    log(f"[INFO] sleep records: {len(sleep_data.get('records', []))}")
    if call_delay: _time.sleep(call_delay)

    log(f"[INFO] Fetching cycle ({date_str})...")
    cycle_data = fetch_whoop_endpoint(access_token, "cycle", start_dt, end_dt)
    log(f"[INFO] cycle records: {len(cycle_data.get('records', []))}")
    if call_delay: _time.sleep(call_delay)

    log(f"[INFO] Fetching workouts ({date_str})...")
    workout_data = fetch_whoop_endpoint(access_token, "activity/workout", start_dt, end_dt)
    workout_records = workout_data.get("records", [])
    log(f"[INFO] workout records: {len(workout_records)}")

    # ── Raw → S3 ──────────────────────────────────────────────────────────────
    _s3_put(s3_client, f"raw/{USER_ID}/whoop/recovery/{year}/{month}/{day}.json", recovery_data, log)
    _s3_put(s3_client, f"raw/{USER_ID}/whoop/sleep/{year}/{month}/{day}.json", sleep_data, log)
    _s3_put(s3_client, f"raw/{USER_ID}/whoop/cycle/{year}/{month}/{day}.json", cycle_data, log)
    for workout in workout_records:
        wid = workout["id"]
        _s3_put(s3_client, f"raw/{USER_ID}/whoop/workout/{year}/{month}/{day}/{wid}.json", workout, log)

    # ── Normalize ─────────────────────────────────────────────────────────────
    normalized = {}
    normalized.update(extract_recovery_fields(recovery_data, log))
    normalized.update(extract_sleep_fields(sleep_data, log))
    normalized.update(extract_cycle_fields(cycle_data, log))

    # ── Field presence validation (F2.5) ──────────────────────────────────────
    CRITICAL_FIELDS = ["recovery_score", "hrv", "resting_heart_rate",
                       "sleep_duration_hours", "strain"]
    EXPECTED_FIELDS = ["rem_sleep_hours", "slow_wave_sleep_hours",
                       "sleep_efficiency_percentage", "respiratory_rate",
                       "kilojoule", "average_heart_rate"]
    missing_critical = [f for f in CRITICAL_FIELDS if f not in normalized]
    missing_expected = [f for f in EXPECTED_FIELDS if f not in normalized]
    if missing_critical:
        log(f"[VALIDATION] ⚠️ CRITICAL fields missing for {date_str}: {missing_critical}")
    if missing_expected:
        log(f"[VALIDATION] Expected fields missing for {date_str}: {missing_expected}")


    # ── Sleep onset consistency (derived metric A1) ────────────────────────────
    sleep_start_val = normalized.get("sleep_start")
    if sleep_start_val:
        onset_min = _sleep_onset_minutes(sleep_start_val)
        if onset_min is not None:
            normalized["sleep_onset_minutes"] = onset_min
            log(f"[INFO] sleep_onset_minutes: {onset_min}")
            consistency = _compute_sleep_consistency(table, date_str, onset_min, log)
            if consistency is not None:
                normalized["sleep_onset_consistency_7d"] = Decimal(str(consistency))
                log(f"[INFO] sleep_onset_consistency_7d: {consistency}")


    # ── DynamoDB: daily item ───────────────────────────────────────────────────
    if normalized:
        _whoop_item = {
            "pk": f"USER#{USER_ID}#SOURCE#whoop",
            "sk": f"DATE#{date_str}",
            "date": date_str,
            "schema_version": 1,
            **normalized,
        }
        # DATA-2: Validate before write
        try:
            from ingestion_validator import validate_item as _validate_item
            _vr = _validate_item("whoop", _whoop_item, date_str)
            if _vr.should_skip_ddb:
                log(f"[DATA-2] CRITICAL: Skipping whoop DDB write for {date_str}: {_vr.errors}")
                _vr.archive_to_s3(s3_client, bucket=S3_BUCKET, item=_whoop_item)
            else:
                if _vr.warnings:
                    log(f"[DATA-2] Validation warnings for whoop/{date_str}: {_vr.warnings}")
                table.put_item(Item=_whoop_item)
                log(f"[INFO] DynamoDB daily item written ({len(normalized)} fields)")
        except ImportError:
            table.put_item(Item=_whoop_item)
            log(f"[INFO] DynamoDB daily item written ({len(normalized)} fields)")

    # ── DynamoDB: workout items ────────────────────────────────────────────────
    for workout in workout_records:
        wid = workout["id"]
        wfields = extract_workout_fields(workout, log)
        try:
            table.put_item(Item={
                "pk": f"USER#{USER_ID}#SOURCE#whoop",
                "sk": f"DATE#{date_str}#WORKOUT#{wid}",
                "date": date_str,
                "workout_id": wid,
                **wfields,
            })
            log(f"[INFO] DynamoDB workout item written: {wid}")
        except Exception as _we:
            log(f"[ERROR] Failed to write workout {wid}: {_we}")
            # Continue with other workouts — partial write is better than no write

    # Return all normalized fields as plain Python scalars (float/int/None)
    # so callers (Lambda handler, backfill script) can log or serialize them.
    ALL_DAILY_FIELDS = [
        # recovery
        "recovery_score", "hrv", "resting_heart_rate",
        "spo2_percentage", "skin_temp_celsius",
        # sleep
        "sleep_duration_hours", "rem_sleep_hours", "slow_wave_sleep_hours",
        "light_sleep_hours", "time_awake_hours", "disturbance_count",
        "respiratory_rate", "sleep_efficiency_percentage",
        "sleep_consistency_percentage", "sleep_performance_percentage",
        "sleep_quality_score",
        # sleep timing + naps (Phase 3)
        "nap_count", "nap_duration_hours",
        # cycle
        "strain", "kilojoule", "average_heart_rate", "max_heart_rate",
        # derived metrics
        "sleep_onset_minutes", "sleep_onset_consistency_7d",
    ]
    summary = {}
    for key in ALL_DAILY_FIELDS:
        val = normalized.get(key)
        if val is None:
            summary[key] = None
        elif isinstance(val, int):
            summary[key] = val
        elif isinstance(val, str):
            summary[key] = val
        else:
            summary[key] = float(val)
    # String fields not in ALL_DAILY_FIELDS
    for str_key in ("sleep_start", "sleep_end"):
        if str_key in normalized:
            summary[str_key] = normalized[str_key]
    summary["workout_count"] = len(workout_records)
    return summary


# ── Field extractors ──────────────────────────────────────────────────────────

def extract_recovery_fields(recovery_data, log=print):
    """
    Recovery fields written:
      recovery_score, hrv, resting_heart_rate,
      spo2_percentage, skin_temp_celsius
    """
    fields = {}
    records = recovery_data.get("records", [])
    if not records:
        log("[WARN] No recovery records")
        return fields

    record = records[0]
    score_state = record.get("score_state", "UNKNOWN")
    score = record.get("score")

    if score_state != "SCORED" or not score:
        log(f"[WARN] Recovery score_state={score_state}, skipping")
        return fields

    _set_dec(fields, "recovery_score", score.get("recovery_score"), log)
    _set_dec(fields, "resting_heart_rate", score.get("resting_heart_rate"), log)
    hrv = score.get("hrv_rmssd_milli")
    if hrv is not None:
        _set_dec(fields, "hrv", round(hrv, 2), log)
    _set_dec(fields, "spo2_percentage", _round(score.get("spo2_percentage"), 2), log)
    _set_dec(fields, "skin_temp_celsius", _round(score.get("skin_temp_celsius"), 2), log)

    return fields


def extract_sleep_fields(sleep_data, log=print):
    """
    Sleep fields written:
      sleep_duration_hours, sleep_quality_score (alias for sleep_performance_percentage),
      rem_sleep_hours, slow_wave_sleep_hours, light_sleep_hours, time_awake_hours,
      disturbance_count, respiratory_rate, sleep_efficiency_percentage,
      sleep_consistency_percentage, sleep_performance_percentage,
      sleep_start, sleep_end (ISO timestamps, Phase 3),
      nap_count, nap_duration_hours (from nap=True records, Phase 3)
    """
    fields = {}
    records = sleep_data.get("records", [])
    main_sleep = next((r for r in records if not r.get("nap", False)), None)

    if not main_sleep:
        log("[WARN] No main sleep record (nap=False)")
        return fields

    score_state = main_sleep.get("score_state", "UNKNOWN")
    score = main_sleep.get("score")

    if score_state != "SCORED" or not score:
        log(f"[WARN] Sleep score_state={score_state}, skipping")
        return fields

    stage = score.get("stage_summary", {})

    def ms_to_h(ms):
        return round((ms or 0) / 3_600_000, 2)

    in_bed_ms = stage.get("total_in_bed_time_milli", 0)
    awake_ms = stage.get("total_awake_time_milli", 0)
    rem_ms = stage.get("total_rem_sleep_time_milli", 0)
    sws_ms = stage.get("total_slow_wave_sleep_time_milli", 0)
    light_ms = stage.get("total_light_sleep_time_milli", 0)

    sleep_ms = in_bed_ms - awake_ms
    if sleep_ms > 0:
        _set_dec(fields, "sleep_duration_hours", ms_to_h(sleep_ms), log)
    if rem_ms > 0:
        _set_dec(fields, "rem_sleep_hours", ms_to_h(rem_ms), log)
    if sws_ms > 0:
        _set_dec(fields, "slow_wave_sleep_hours", ms_to_h(sws_ms), log)
    if light_ms > 0:
        _set_dec(fields, "light_sleep_hours", ms_to_h(light_ms), log)
    if awake_ms > 0:
        _set_dec(fields, "time_awake_hours", ms_to_h(awake_ms), log)

    disturbances = stage.get("disturbance_count")
    if disturbances is not None:
        fields["disturbance_count"] = int(disturbances)
        log(f"[INFO] disturbance_count: {disturbances}")

    _set_dec(fields, "respiratory_rate", _round(score.get("respiratory_rate"), 2), log)
    _set_dec(fields, "sleep_efficiency_percentage",
             _round(score.get("sleep_efficiency_percentage"), 2), log)
    _set_dec(fields, "sleep_consistency_percentage",
             _round(score.get("sleep_consistency_percentage"), 2), log)

    perf = score.get("sleep_performance_percentage")
    if perf is not None:
        _set_dec(fields, "sleep_performance_percentage", perf, log)
        _set_dec(fields, "sleep_quality_score", perf, log)  # backward-compat alias

    # ── Sleep timing (Phase 3 — previously missing) ──
    sleep_start = main_sleep.get("start")
    sleep_end = main_sleep.get("end")
    if sleep_start:
        fields["sleep_start"] = sleep_start
        log(f"[INFO] sleep_start: {sleep_start}")
    if sleep_end:
        fields["sleep_end"] = sleep_end
        log(f"[INFO] sleep_end: {sleep_end}")

    # ── Nap data (Phase 3 — previously filtered out) ──
    naps = [r for r in records if r.get("nap", False)]
    if naps:
        fields["nap_count"] = len(naps)
        log(f"[INFO] nap_count: {len(naps)}")
        total_nap_ms = 0
        for nap in naps:
            nap_score = nap.get("score") or {}
            nap_stage = nap_score.get("stage_summary") or {}
            in_bed = nap_stage.get("total_in_bed_time_milli", 0)
            awake = nap_stage.get("total_awake_time_milli", 0)
            total_nap_ms += (in_bed - awake)
        if total_nap_ms > 0:
            nap_hours = round(total_nap_ms / 3_600_000, 2)
            _set_dec(fields, "nap_duration_hours", nap_hours, log)

    return fields


def extract_cycle_fields(cycle_data, log=print):
    """
    Cycle fields written:
      strain, kilojoule, average_heart_rate, max_heart_rate
    """
    fields = {}
    records = cycle_data.get("records", [])
    if not records:
        log("[WARN] No cycle records")
        return fields

    record = records[0]
    score_state = record.get("score_state", "UNKNOWN")
    score = record.get("score")

    if score_state != "SCORED" or not score:
        log(f"[WARN] Cycle score_state={score_state}, skipping")
        return fields

    _set_dec(fields, "strain", _round(score.get("strain"), 2), log)
    _set_dec(fields, "kilojoule", _round(score.get("kilojoule"), 2), log)
    _set_dec(fields, "average_heart_rate", score.get("average_heart_rate"), log)
    _set_dec(fields, "max_heart_rate", score.get("max_heart_rate"), log)

    return fields


def extract_workout_fields(workout_record, log=print):
    """
    Workout fields written:
      sport_id, sport_name, start_time, end_time,
      strain, average_heart_rate, max_heart_rate, kilojoule, distance_meter,
      zone_0_minutes … zone_5_minutes
    """
    fields = {}

    sport_id = workout_record.get("sport_id")
    if sport_id is not None:
        fields["sport_id"] = int(sport_id)
        fields["sport_name"] = WHOOP_SPORT_NAMES.get(sport_id, f"Sport_{sport_id}")
        log(f"[INFO] sport: {fields['sport_name']} (id={sport_id})")

    for key in ("start", "end"):
        val = workout_record.get(key)
        if val:
            fields[f"{key}_time"] = val

    score_state = workout_record.get("score_state", "UNKNOWN")
    score = workout_record.get("score")

    if score_state != "SCORED" or not score:
        log(f"[WARN] Workout score_state={score_state}, no scored data")
        return fields

    _set_dec(fields, "strain", _round(score.get("strain"), 2), log)
    _set_dec(fields, "average_heart_rate", score.get("average_heart_rate"), log)
    _set_dec(fields, "max_heart_rate", score.get("max_heart_rate"), log)
    _set_dec(fields, "kilojoule", _round(score.get("kilojoule"), 2), log)
    _set_dec(fields, "distance_meter", _round(score.get("distance_meter"), 1), log)

    zone_dur = score.get("zone_duration", {})
    for i, word in enumerate(_ZONE_WORD):
        ms = zone_dur.get(f"zone_{word}_milli") or 0
        fields[f"zone_{i}_minutes"] = Decimal(str(round(ms / 60_000, 2)))

    return fields


# ── Whoop API helpers ─────────────────────────────────────────────────────────

def refresh_access_token(client_id, client_secret, refresh_token):
    """Exchange a refresh token for a new access_token + refresh_token pair."""
    payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": WHOOP_SCOPES,
    }).encode("utf-8")

    req = urllib.request.Request(
        WHOOP_TOKEN_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "WhoopIngestion/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
            return token_data["access_token"], token_data["refresh_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"[ERROR] Token refresh failed — HTTP {e.code}: {body}")
        raise
    except urllib.error.URLError as e:
        print(f"[ERROR] Token refresh network error: {e.reason}")
        raise


def fetch_whoop_endpoint(access_token, endpoint, start_datetime, end_datetime):
    """GET a Whoop API v2 collection. Raises urllib.error.HTTPError on failure."""
    params = urllib.parse.urlencode({
        "start": start_datetime,
        "end": end_datetime,
        "limit": 25,
    })
    url = f"{WHOOP_API_BASE}/{endpoint}?{params}"

    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "WhoopIngestion/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"[ERROR] Whoop /{endpoint} — HTTP {e.code}: {body}")
        raise
    except urllib.error.URLError as e:
        print(f"[ERROR] Whoop /{endpoint} network error: {e.reason}")
        raise


# ── Private helpers ───────────────────────────────────────────────────────────

def _s3_put(s3_client, key, data, log=print):
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(data, indent=2),
        ContentType="application/json",
    )
    log(f"[INFO] S3 ← s3://{S3_BUCKET}/{key}")


def _set_dec(fields, name, value, log=print):
    """Store value as Decimal in fields if not None; log it."""
    if value is None:
        return
    fields[name] = Decimal(str(value))
    log(f"[INFO] {name}: {value}")


def _round(value, decimals):
    """Round value if not None, else return None."""
    return round(value, decimals) if value is not None else None
