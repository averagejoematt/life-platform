"""
Withings daily data ingestion Lambda.
Captures weight, body composition measurements from Withings API.
Stores raw JSON to S3 and normalized fields to DynamoDB.
Runs daily via EventBridge.
"""

import json
import time
import hmac
import hashlib
import urllib.request
import urllib.parse
import boto3
from decimal import Decimal
from datetime import datetime, timezone, timedelta

# ── Constants ──────────────────────────────────────────────────────────────
SECRET_NAME   = "life-platform/withings"
REGION        = "us-west-2"
S3_BUCKET     = "matthew-life-platform"
DYNAMO_TABLE  = "life-platform"
DYNAMO_PK     = "USER#matthew#SOURCE#withings"

WITHINGS_SIG_URL   = "https://wbsapi.withings.net/v2/signature"
WITHINGS_OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_MEAS_URL  = "https://wbsapi.withings.net/measure"

# Measurement type codes
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
    resp = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])


def save_tokens(secret: dict, access_token: str, refresh_token: str):
    updated = {**secret, "access_token": access_token, "refresh_token": refresh_token}
    secrets_client.put_secret_value(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(updated),
    )
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

    # Sort by date descending, take most recent group
    grps_sorted = sorted(grps, key=lambda g: g["date"], reverse=True)
    latest_grp  = grps_sorted[0]
    latest_ts   = latest_grp["date"]

    result = {
        "measurement_timestamp": latest_ts,
        "measurement_time_utc":  datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat(),
    }

    for meas in latest_grp.get("measures", []):
        mtype = meas["type"]
        if mtype in MEAS_TYPES:
            field_name = MEAS_TYPES[mtype]
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
    key = f"raw/withings/measurements/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
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


def save_to_dynamo(date_str: str, measurements: dict):
    if not measurements:
        print("No measurements to save to DynamoDB.")
        return

    item = {
        "pk":          DYNAMO_PK,
        "sk":          f"DATE#{date_str}",
        "source":      "withings",
        "date":        date_str,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    item.update(float_to_decimal(measurements))

    table.put_item(Item=item)
    print(f"Saved to DynamoDB: pk={DYNAMO_PK}, sk=DATE#{date_str}")


# ── Lambda handler ─────────────────────────────────────────────────────────
def lambda_handler(event, context):
    # Determine target date (default: yesterday UTC)
    if "date" in event:
        target_date = datetime.strptime(event["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        target_date = datetime.now(timezone.utc) - timedelta(days=1)

    date_str = target_date.strftime("%Y-%m-%d")
    print(f"Processing Withings data for {date_str}")

    # Load credentials
    secret = get_secret()

    # Fetch measurements
    raw_body = fetch_measurements(secret, target_date)
    print(f"Raw response: {json.dumps(raw_body)[:500]}")

    # Save raw to S3
    save_to_s3(date_str, raw_body)

    # Parse and save to DynamoDB
    measurements = parse_measurements(raw_body)
    if measurements:
        print(f"Parsed measurements: {measurements}")
        save_to_dynamo(date_str, measurements)
    else:
        print(f"No measurements found for {date_str}")

    return {
        "statusCode": 200,
        "date": date_str,
        "measurements_found": len(measurements) > 0,
        "fields_captured": list(measurements.keys()),
    }
