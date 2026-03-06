"""
Withings historical data backfill.
Fetches all measurements from start_date to yesterday.
Uses date-range batching (90 days at a time) to minimize API calls
— Withings getmeas supports date ranges, unlike Whoop which is day-by-day.
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
import sys

# ── Config ─────────────────────────────────────────────────────────────────
START_DATE   = "2010-01-01"   # Go early — Withings will just return nothing before first weigh-in
REGION       = "us-west-2"
SECRET_NAME  = "life-platform/withings"
S3_BUCKET    = "matthew-life-platform"
DYNAMO_TABLE = "life-platform"
DYNAMO_PK    = "USER#matthew#SOURCE#withings"
BATCH_DAYS   = 90             # Days per API call (Withings supports large ranges)
DELAY_SEC    = 0.5            # Pause between API calls to be respectful

WITHINGS_SIG_URL   = "https://wbsapi.withings.net/v2/signature"
WITHINGS_OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_MEAS_URL  = "https://wbsapi.withings.net/measure"

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


# ── Auth helpers ───────────────────────────────────────────────────────────
def hmac_sha256(key, message):
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()

def post_form(url, params):
    data = urllib.parse.urlencode(params).encode()
    req  = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def get_secret():
    resp = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])

def save_tokens(secret, access_token, refresh_token):
    updated = {**secret, "access_token": access_token, "refresh_token": refresh_token}
    secrets_client.put_secret_value(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(updated),
    )
    return updated

def get_nonce(client_id, client_secret):
    timestamp  = int(time.time())
    sig_string = f"getnonce,{client_id},{timestamp}"
    signature  = hmac_sha256(client_secret, sig_string)
    resp = post_form(WITHINGS_SIG_URL, {
        "action": "getnonce", "client_id": client_id,
        "timestamp": timestamp, "signature": signature,
    })
    if resp.get("status") != 0:
        raise RuntimeError(f"getnonce failed: {resp}")
    return resp["body"]["nonce"]

def refresh_token(secret):
    print("  [auth] Refreshing access token...")
    client_id     = secret["client_id"]
    client_secret = secret["client_secret"]
    nonce         = get_nonce(client_id, client_secret)
    sig_string    = f"requesttoken,{client_id},{nonce}"
    signature     = hmac_sha256(client_secret, sig_string)
    resp = post_form(WITHINGS_OAUTH_URL, {
        "action":        "requesttoken",
        "grant_type":    "refresh_token",
        "client_id":     client_id,
        "refresh_token": secret["refresh_token"],
        "nonce":         nonce,
        "signature":     signature,
    })
    if resp.get("status") != 0:
        raise RuntimeError(f"Token refresh failed: {resp}")
    body = resp["body"]
    return save_tokens(secret, body["access_token"], body["refresh_token"])


# ── API call with auto-refresh ─────────────────────────────────────────────
def withings_post(secret, url, params):
    data    = urllib.parse.urlencode(params).encode()
    headers = {"Authorization": f"Bearer {secret['access_token']}",
               "Content-Type":  "application/x-www-form-urlencoded"}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    if result.get("status") == 401:
        secret = refresh_token(secret)
        req2 = urllib.request.Request(
            url, data=data,
            headers={"Authorization": f"Bearer {secret['access_token']}",
                     "Content-Type":  "application/x-www-form-urlencoded"},
            method="POST"
        )
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            result = json.loads(resp2.read())

    if result.get("status") != 0:
        raise RuntimeError(f"Withings API error {result.get('status')}: {result}")

    return result["body"], secret


# ── Fetch a batch (date range) ─────────────────────────────────────────────
def fetch_batch(secret, start_ts, end_ts):
    params = {
        "action":    "getmeas",
        "meastypes": ",".join(str(k) for k in MEAS_TYPES.keys()),
        "category":  "1",
        "startdate": start_ts,
        "enddate":   end_ts,
    }
    body, secret = withings_post(secret, WITHINGS_MEAS_URL, params)
    return body, secret


# ── Parse: group measurements by calendar date ─────────────────────────────
def parse_by_date(raw_body):
    """
    Returns dict of date_str -> {field: value, ...}
    Takes the most recent measurement group per calendar day.
    """
    grps = raw_body.get("measuregrps", [])
    by_date = {}

    for grp in grps:
        ts       = grp["date"]
        dt_utc   = datetime.fromtimestamp(ts, tz=timezone.utc)
        date_str = dt_utc.strftime("%Y-%m-%d")

        # Keep only the latest group per day
        if date_str in by_date and by_date[date_str]["measurement_timestamp"] >= ts:
            continue

        parsed = {
            "measurement_timestamp": ts,
            "measurement_time_utc":  dt_utc.isoformat(),
        }
        for meas in grp.get("measures", []):
            mtype = meas["type"]
            if mtype in MEAS_TYPES:
                field_name = MEAS_TYPES[mtype]
                value      = meas["value"] * (10 ** meas["unit"])
                parsed[field_name] = round(value, 4)
                if field_name in ("weight_kg", "fat_mass_kg", "fat_free_mass_kg",
                                  "muscle_mass_kg", "bone_mass_kg"):
                    lbs_field = field_name.replace("_kg", "_lbs")
                    parsed[lbs_field] = round(value * 2.20462, 2)

        by_date[date_str] = parsed

    return by_date


# ── Storage ────────────────────────────────────────────────────────────────
def float_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [float_to_decimal(i) for i in obj]
    return obj

def save_day_s3(date_str, raw_grp_data):
    key = f"raw/withings/measurements/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    s3_client.put_object(
        Bucket=S3_BUCKET, Key=key,
        Body=json.dumps(raw_grp_data, indent=2),
        ContentType="application/json",
    )

def save_day_dynamo(date_str, measurements):
    item = {
        "pk":          DYNAMO_PK,
        "sk":          f"DATE#{date_str}",
        "source":      "withings",
        "date":        date_str,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    item.update(float_to_decimal(measurements))
    table.put_item(Item=item)


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    secret    = get_secret()
    start_dt  = datetime.strptime(START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt    = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total_days = (end_dt - start_dt).days

    print(f"Withings backfill: {START_DATE} → {end_dt.strftime('%Y-%m-%d')}")
    print(f"Total window: {total_days} days ({total_days // 365} years)")
    print(f"Batch size: {BATCH_DAYS} days → ~{-(-total_days // BATCH_DAYS)} API calls\n")

    days_with_data = 0
    days_empty     = 0
    batch_num      = 0
    current        = start_dt

    while current < end_dt:
        batch_end = min(current + timedelta(days=BATCH_DAYS), end_dt)
        batch_num += 1

        start_ts = int(current.timestamp())
        end_ts   = int(batch_end.timestamp())
        period   = f"{current.strftime('%Y-%m-%d')} → {batch_end.strftime('%Y-%m-%d')}"

        try:
            raw_body, secret = fetch_batch(secret, start_ts, end_ts)
            by_date          = parse_by_date(raw_body)

            if by_date:
                for date_str, measurements in sorted(by_date.items()):
                    save_day_s3(date_str, measurements)
                    save_day_dynamo(date_str, measurements)
                    days_with_data += 1

                weight_sample = ""
                for d, m in sorted(by_date.items()):
                    if "weight_lbs" in m:
                        weight_sample = f" (e.g. {d}: {m['weight_lbs']} lbs)"
                        break

                print(f"  Batch {batch_num:3d} | {period} | {len(by_date):3d} days with data{weight_sample}")
            else:
                days_empty += BATCH_DAYS
                print(f"  Batch {batch_num:3d} | {period} | no data")

        except Exception as e:
            print(f"  Batch {batch_num:3d} | {period} | ERROR: {e}", file=sys.stderr)

        current = batch_end
        time.sleep(DELAY_SEC)

    print(f"\n{'='*60}")
    print(f"Backfill complete!")
    print(f"  Days with measurements: {days_with_data}")
    print(f"  API calls made:         {batch_num}")
    print(f"  S3 path:  s3://{S3_BUCKET}/raw/withings/measurements/")
    print(f"  DynamoDB: {DYNAMO_TABLE} | pk={DYNAMO_PK}")


if __name__ == "__main__":
    main()
