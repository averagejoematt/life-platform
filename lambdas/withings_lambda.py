"""
Withings daily data ingestion Lambda.
Captures weight, body composition measurements from Withings API.
Stores raw JSON to S3 and normalized fields to DynamoDB.
Runs daily via EventBridge.
"""

import json
import os
import logging
import time
import hmac
import hashlib
import urllib.request
import urllib.parse
import boto3
from decimal import Decimal
from datetime import datetime, timezone, timedelta

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("withings")
except ImportError:
    logger = logging.getLogger("withings")
    logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION        = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET     = os.environ["S3_BUCKET"]
DYNAMO_TABLE  = os.environ.get("TABLE_NAME", "life-platform")
USER_ID       = os.environ["USER_ID"]
SECRET_NAME   = os.environ.get("WITHINGS_SECRET_NAME", "life-platform/withings")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))
DYNAMO_PK     = f"USER#{USER_ID}#SOURCE#withings"

WITHINGS_SIG_URL   = "https://wbsapi.withings.net/v2/signature"
WITHINGS_OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_MEAS_URL  = "https://wbsapi.withings.net/measure"

# Withings API measurement type IDs -- see developer.withings.com/api-reference
MEAS_TYPES = {
    1:  "weight_kg",
    5:  "fat_free_mass_kg",
    6:  "fat_ratio_percent",
    8:  "fat_mass_kg",
    11: "heart_pulse_bpm",
    76: "muscle_mass_kg",
    77: "hydration_percent",
    88: "bone_mass_kg",
}

# ── AWS clients ────────────────────────────────────────────────────────────
secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client      = boto3.client("s3",             region_name=REGION)
dynamo         = boto3.resource("dynamodb",      region_name=REGION)
table          = dynamo.Table(DYNAMO_TABLE)

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


# ── Helpers ────────────────────────────────────────────────────────────────
def hmac_sha256(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def post_form(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req  = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_secret() -> dict:
    return json.loads(_cached_secret(secrets_client, SECRET_NAME))


def save_tokens(secret: dict, access_token: str, refresh_token: str):
    updated = {**secret, "access_token": access_token, "refresh_token": refresh_token}
    secrets_client.put_secret_value(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(updated),
    )
    _secret_cache.pop(SECRET_NAME, None)  # Invalidate cache after token refresh
    return updated


# ── OAuth: get nonce ───────────────────────────────────────────────────────
def get_nonce(client_id: str, client_secret: str) -> str:
    timestamp = int(time.time())
    sig_string = f"getnonce,{client_id},{timestamp}"
    signature  = hmac_sha256(client_secret, sig_string)
    params = {
        "action":    "getnonce",
        "client_id": client_id,
        "timestamp": timestamp,
        "signature": signature,
    }
    resp = post_form(WITHINGS_SIG_URL, params)
    if resp.get("status") != 0:
        raise RuntimeError(f"getnonce failed: {resp}")
    return resp["body"]["nonce"]


# ── OAuth: refresh access token ────────────────────────────────────────────
def refresh_access_token(secret: dict) -> dict:
    print("Refreshing Withings access token...")
    client_id     = secret["client_id"]
    client_secret = secret["client_secret"]
    refresh_token = secret["refresh_token"]

    nonce      = get_nonce(client_id, client_secret)
    sig_string = f"requesttoken,{client_id},{nonce}"
    signature  = hmac_sha256(client_secret, sig_string)

    params = {
        "action":        "requesttoken",
        "grant_type":    "refresh_token",
        "client_id":     client_id,
        "refresh_token": refresh_token,
        "nonce":         nonce,
        "signature":     signature,
    }
    resp = post_form(WITHINGS_OAUTH_URL, params)
    if resp.get("status") != 0:
        raise RuntimeError(f"Token refresh failed: {resp}")

    body = resp["body"]
    updated = save_tokens(secret, body["access_token"], body["refresh_token"])
    print("Token refreshed and saved.")
    return updated


# ── API call with auto-refresh ─────────────────────────────────────────────
def withings_get(secret: dict, url: str, params: dict) -> dict:
    """GET/POST with Bearer token; refreshes once on 401."""
    params["action"] = params.get("action", "")
    data = urllib.parse.urlencode(params).encode()
    headers = {"Authorization": f"Bearer {secret['access_token']}"}

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    # Withings returns status 401 in body (not HTTP status)
    if result.get("status") == 401:
        print("Access token expired, refreshing...")
        secret = refresh_access_token(secret)
        # Retry once
        req2 = urllib.request.Request(
            url, data=data,
            headers={"Authorization": f"Bearer {secret['access_token']}"},
            method="POST"
        )
        req2.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            result = json.loads(resp2.read())

    if result.get("status") != 0:
        raise RuntimeError(f"Withings API error: {result}")

    return result["body"]


# ── Fetch measurements ─────────────────────────────────────────────────────
def fetch_measurements(secret: dict, target_date: datetime) -> dict:
    """
    Fetch body measurements for target_date.
    Uses a 24-hour window around midnight of the target date.
    """
    # Window: midnight to midnight UTC of target_date
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    day_end   = day_start + timedelta(days=1)

    params = {
        "action":     "getmeas",
        "meastypes":  ",".join(str(k) for k in MEAS_TYPES.keys()),
        "category":   "1",          # 1 = real measurements (not objectives)
        "startdate":  int(day_start.timestamp()),
        "enddate":    int(day_end.timestamp()),
    }
    body = withings_get(secret, WITHINGS_MEAS_URL, params)
    return body


# ── Parse measurement groups ───────────────────────────────────────────────
def parse_measurements(raw_body: dict) -> dict:
    """
    Withings returns measuregrps — groups of measurements taken together.
    We take the most recent group within the day.
    Returns a flat dict of field_name -> value.
    """
    grps = raw_body.get("measuregrps", [])
    if not grps:
        return {}

    # Process ALL measurement groups for the day (not just the latest)
    # Different devices (scale, BPM) produce separate groups at different times
    grps_sorted = sorted(grps, key=lambda g: g["date"], reverse=True)
    latest_ts   = grps_sorted[0]["date"]

    result = {
        "measurement_timestamp": latest_ts,
        "measurement_time_utc":  datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat(),
    }

    for grp in grps_sorted:
        for meas in grp.get("measures", []):
            mtype = meas["type"]
            if mtype in MEAS_TYPES:
                field_name = MEAS_TYPES[mtype]
                # Only take first (most recent) value per field
                if field_name in result:
                    continue
                # Withings stores values as integer * 10^unit
                value = meas["value"] * (10 ** meas["unit"])
                result[field_name] = round(value, 4)
                # Add lbs alongside kg for weight fields
                if field_name in ("weight_kg", "fat_mass_kg", "fat_free_mass_kg",
                                  "muscle_mass_kg", "bone_mass_kg"):
                    lbs_field = field_name.replace("_kg", "_lbs")
                    result[lbs_field] = round(value * 2.20462, 2)

    return result


# ── S3 storage ─────────────────────────────────────────────────────────────
def save_to_s3(date_str: str, raw_body: dict):
    key = f"raw/{USER_ID}/withings/measurements/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(raw_body, indent=2),
        ContentType="application/json",
    )
    print(f"Saved raw to s3://{S3_BUCKET}/{key}")


# ── DynamoDB storage ───────────────────────────────────────────────────────
def float_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [float_to_decimal(i) for i in obj]
    return obj



# ── Body composition delta helpers (derived metric A2) ─────────────────────

def compute_body_comp_deltas(date_str, measurements):
    """
    Query the Withings record from ~14 days ago and compute lean/fat mass deltas.
    Uses nearest record within a 7-day search window (days 11-17 before today).
    Returns dict with delta fields to merge into measurements.
    """
    from boto3.dynamodb.conditions import Key

    deltas = {}
    current_lean = measurements.get("fat_free_mass_lbs")  # Withings calls lean mass "fat_free_mass"
    current_fat = measurements.get("fat_mass_lbs")

    if current_lean is None and current_fat is None:
        return deltas

    # Search window: 11-17 days ago (centered on 14)
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    search_start = (target_dt - timedelta(days=17)).strftime("%Y-%m-%d")
    search_end = (target_dt - timedelta(days=11)).strftime("%Y-%m-%d")

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(DYNAMO_PK)
            & Key("sk").between(f"DATE#{search_start}", f"DATE#{search_end}"),
        ProjectionExpression="fat_free_mass_lbs, fat_mass_lbs, #d",
        ExpressionAttributeNames={"#d": "date"},
        ScanIndexForward=False,  # newest first (closest to 14 days ago)
        Limit=1,
    )

    items = resp.get("Items", [])
    if not items:
        print(f"  No Withings record found in {search_start} to {search_end} for delta")
        return deltas

    prev = items[0]
    prev_date = prev.get("date", "?")

    if current_lean is not None and prev.get("fat_free_mass_lbs") is not None:
        delta = round(float(current_lean) - float(prev["fat_free_mass_lbs"]), 2)
        deltas["lean_mass_delta_14d"] = delta
        print(f"  lean_mass_delta_14d: {delta:+.2f} lbs (vs {prev_date})")

    if current_fat is not None and prev.get("fat_mass_lbs") is not None:
        delta = round(float(current_fat) - float(prev["fat_mass_lbs"]), 2)
        deltas["fat_mass_delta_14d"] = delta
        print(f"  fat_mass_delta_14d: {delta:+.2f} lbs (vs {prev_date})")

    return deltas



def save_to_dynamo(date_str: str, measurements: dict):
    if not measurements:
        print("No measurements to save to DynamoDB.")
        return

    item = {
        "pk":             DYNAMO_PK,
        "sk":             f"DATE#{date_str}",
        "source":         "withings",
        "date":           date_str,
        "schema_version": 1,
        "captured_at":    datetime.now(timezone.utc).isoformat(),
    }
    item.update(float_to_decimal(measurements))

    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item
        _vr = _validate_item("withings", item, date_str)
        if _vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping withings DDB write for {date_str}: {_vr.errors}")
            _vr.archive_to_s3(s3_client, bucket=S3_BUCKET, item=item)
        else:
            if _vr.warnings:
                logger.warning(f"[DATA-2] Validation warnings for withings/{date_str}: {_vr.warnings}")
            table.put_item(Item=item)
            print(f"Saved to DynamoDB: pk={DYNAMO_PK}, sk=DATE#{date_str}")
    except ImportError:
        table.put_item(Item=item)
        print(f"Saved to DynamoDB: pk={DYNAMO_PK}, sk=DATE#{date_str}")



# ── Gap detection (v2.0) ──────────────────────────────────────────────────────
def find_missing_dates(lookback_days=LOOKBACK_DAYS):
    """Check DynamoDB for missing Withings records in the lookback window.
    
    Note: Withings only has data on days with a weigh-in. Missing dates may
    simply be no-weigh days — the API call for those dates returns empty safely.
    """
    from boto3.dynamodb.conditions import Key
    today = datetime.now(timezone.utc).date()
    check_dates = set()
    for i in range(0, lookback_days + 1):  # includes today
        check_dates.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))

    oldest = min(check_dates)
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(DYNAMO_PK)
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


def _ingest_single_day(date_str, secret):
    """Fetch, parse, and save Withings data for a single date. Returns measurements dict."""
    target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    raw_body = fetch_measurements(secret, target_date)
    save_to_s3(date_str, raw_body)

    measurements = parse_measurements(raw_body)
    if measurements:
        print(f"  Parsed measurements for {date_str}: {list(measurements.keys())}")
        deltas = compute_body_comp_deltas(date_str, measurements)
        measurements.update(deltas)
        save_to_dynamo(date_str, measurements)
    else:
        print(f"  No measurements for {date_str}")
    return measurements


# ── Lambda handler ─────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        import time as _time
        if hasattr(logger, "set_date"): logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1

        # ── Mode 1: Explicit date (manual invoke / backfill) ──
        if "date" in event:
            date_str = event["date"]
            print(f"Withings ingestion — explicit date={date_str}")
            secret = get_secret()
            measurements = _ingest_single_day(date_str, secret)
            return {
                "statusCode": 200,
                "date": date_str,
                "measurements_found": len(measurements) > 0,
                "fields_captured": list(measurements.keys()),
            }

        # ── Mode 2: Scheduled run — gap-aware lookback ──
        print(f"[GAP-FILL] Withings gap-aware lookback ({LOOKBACK_DAYS} days)")
        missing_dates = find_missing_dates()

        if not missing_dates:
            return {"statusCode": 200, "body": json.dumps({"message": "No gaps to fill", "lookback_days": LOOKBACK_DAYS})}

        secret = get_secret()
        results = {}

        for i, date_str in enumerate(missing_dates):
            print(f"[GAP-FILL] Checking {date_str} ({i+1}/{len(missing_dates)})")
            try:
                # Re-read secret each iteration — token refresh invalidates the old
                # refresh_token, so we must always use the latest from Secrets Manager
                secret = get_secret()
                measurements = _ingest_single_day(date_str, secret)
                results[date_str] = list(measurements.keys()) if measurements else "no data"
            except Exception as e:
                print(f"[GAP-FILL] ERROR on {date_str}: {e}")
                results[date_str] = f"error: {e}"
            if i < len(missing_dates) - 1:
                _time.sleep(0.5)  # Gentle pacing

        filled = sum(1 for v in results.values() if isinstance(v, list))
        print(f"[GAP-FILL] Complete: {filled}/{len(missing_dates)} days had measurements")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "mode": "gap_fill",
                "lookback_days": LOOKBACK_DAYS,
                "gaps_checked": len(missing_dates),
                "gaps_with_data": filled,
                "details": results,
            }, default=str),
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise

