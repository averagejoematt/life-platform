"""
Weather Ingestion Lambda — fetches daily weather from Open-Meteo for Seattle.
Stores in DynamoDB life-platform table under USER#matthew#SOURCE#weather.
Scheduled via EventBridge to run before the Daily Brief.
"""
import json
import os
import logging
import urllib.request
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
LAT, LON = 47.6062, -122.3321  # Seattle

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def fetch_weather(start_date, end_date):
    """Fetch weather from Open-Meteo archive API."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={LAT}&longitude={LON}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
        f"relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max,"
        f"surface_pressure_mean,daylight_duration,uv_index_max,"
        f"sunshine_duration"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&precipitation_unit=mm&timezone=America/Los_Angeles"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def lambda_handler(event, context):
    # Default: fetch yesterday + today (today may have partial data)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Allow override via event
    start_date = event.get("start_date", yesterday)
    end_date = event.get("end_date", today)
    
    print(f"Weather ingestion: {start_date} → {end_date}")
    
    data = fetch_weather(start_date, end_date)
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    
    records_written = 0
    
    for i, date_str in enumerate(dates):
        daylight_secs = daily["daylight_duration"][i] or 0
        sunshine_secs = daily["sunshine_duration"][i] or 0
        
        record = {
            "date": date_str,
            "temp_high_f": daily["temperature_2m_max"][i],
            "temp_low_f": daily["temperature_2m_min"][i],
            "temp_avg_f": daily["temperature_2m_mean"][i],
            "humidity_pct": daily["relative_humidity_2m_mean"][i],
            "precipitation_mm": daily["precipitation_sum"][i],
            "wind_speed_max_mph": daily["wind_speed_10m_max"][i],
            "pressure_hpa": daily["surface_pressure_mean"][i],
            "daylight_hours": round(daylight_secs / 3600, 2),
            "sunshine_hours": round(sunshine_secs / 3600, 2),
            "uv_index_max": daily["uv_index_max"][i],
        }
        
        # Remove None values
        record = {k: v for k, v in record.items() if v is not None}
        
        # DynamoDB
        db_item = {
            "pk": f"USER#{USER_ID}#SOURCE#weather",
            "sk": f"DATE#{date_str}",
            "source": "weather",
            "schema_version": 1,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            **record,
        }
        # DATA-2: Validate before write
        try:
            from ingestion_validator import validate_item as _validate_item
            _vr = _validate_item("weather", floats_to_decimal(db_item), date_str)
            if _vr.should_skip_ddb:
                logger.error(f"[DATA-2] CRITICAL: Skipping weather DDB write for {date_str}: {_vr.errors}")
                _vr.archive_to_s3(s3, bucket=S3_BUCKET, item=db_item)
            else:
                if _vr.warnings:
                    logger.warning(f"[DATA-2] Validation warnings for weather/{date_str}: {_vr.warnings}")
                table.put_item(Item=floats_to_decimal(db_item))
                records_written += 1
                print(f"  {date_str}: temp={record.get('temp_avg_f')}°F, daylight={record.get('daylight_hours')}h, precip={record.get('precipitation_mm')}mm")
        except ImportError:
            table.put_item(Item=floats_to_decimal(db_item))
            records_written += 1
            print(f"  {date_str}: temp={record.get('temp_avg_f')}°F, daylight={record.get('daylight_hours')}h, precip={record.get('precipitation_mm')}mm")
    
    # S3 raw backup
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"raw/weather/{today[:4]}/{today[5:7]}/{today}.json",
        Body=json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "raw": data}, default=str),
        ContentType="application/json",
    )
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "dates_written": records_written,
            "start_date": start_date,
            "end_date": end_date,
        })
    }
