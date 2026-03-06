#!/bin/bash
# deploy_weather_lambda.sh — Create weather ingestion Lambda + EventBridge schedule
# Fetches Seattle weather from Open-Meteo (free, no auth) → DynamoDB
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Weather Ingestion Lambda + EventBridge Schedule"
echo "  Runs daily before Daily Brief, populates weather partition"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

# ── Step 1: Create Lambda source ────────────────────────────────────────────
cat > lambdas/weather_lambda.py << 'LAMBDA_CODE'
"""
Weather Ingestion Lambda — fetches daily weather from Open-Meteo for Seattle.
Stores in DynamoDB life-platform table under USER#matthew#SOURCE#weather.
Scheduled via EventBridge to run before the Daily Brief.
"""
import json
import urllib.request
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

TABLE_NAME = "life-platform"
S3_BUCKET = "matthew-life-platform"
LAT, LON = 47.6062, -122.3321  # Seattle

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name="us-west-2")


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
            "pk": "USER#matthew#SOURCE#weather",
            "sk": f"DATE#{date_str}",
            "source": "weather",
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            **record,
        }
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
LAMBDA_CODE

echo "✅ Lambda source created"

# ── Step 2: Package ─────────────────────────────────────────────────────────
cd lambdas
rm -f weather_lambda.zip
zip weather_lambda.zip weather_lambda.py
cd ..
echo "✅ Lambda packaged"

# ── Step 3: Create IAM role ─────────────────────────────────────────────────
ROLE_NAME="lambda-weather-role"

# Check if role exists
if aws iam get-role --role-name $ROLE_NAME --region us-west-2 2>/dev/null; then
    echo "✅ IAM role already exists: $ROLE_NAME"
else
    echo "Creating IAM role: $ROLE_NAME"
    
    # Trust policy
    cat > /tmp/weather-trust-policy.json << 'TRUST'
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
}
TRUST
    
    aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document file:///tmp/weather-trust-policy.json \
        --region us-west-2
    
    # Inline policy: DynamoDB write + S3 write + CloudWatch logs
    cat > /tmp/weather-policy.json << 'POLICY'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["dynamodb:PutItem", "dynamodb:GetItem"],
            "Resource": "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
        },
        {
            "Effect": "Allow",
            "Action": ["s3:PutObject"],
            "Resource": "arn:aws:s3:::matthew-life-platform/raw/weather/*"
        },
        {
            "Effect": "Allow",
            "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            "Resource": "arn:aws:logs:us-west-2:205930651321:*"
        }
    ]
}
POLICY
    
    aws iam put-role-policy \
        --role-name $ROLE_NAME \
        --policy-name weather-lambda-policy \
        --policy-document file:///tmp/weather-policy.json \
        --region us-west-2
    
    echo "✅ IAM role created. Waiting 10s for propagation..."
    sleep 10
fi

ROLE_ARN="arn:aws:iam::205930651321:role/$ROLE_NAME"

# ── Step 4: Create or update Lambda ─────────────────────────────────────────
FUNC_NAME="weather-data-ingestion"

if aws lambda get-function --function-name $FUNC_NAME --region us-west-2 2>/dev/null; then
    echo "Updating existing Lambda: $FUNC_NAME"
    aws lambda update-function-code \
        --function-name $FUNC_NAME \
        --zip-file fileb://lambdas/weather_lambda.zip \
        --region us-west-2
else
    echo "Creating Lambda: $FUNC_NAME"
    aws lambda create-function \
        --function-name $FUNC_NAME \
        --runtime python3.12 \
        --handler weather_lambda.lambda_handler \
        --role $ROLE_ARN \
        --zip-file fileb://lambdas/weather_lambda.zip \
        --timeout 30 \
        --memory-size 128 \
        --description "Weather ingestion — Open-Meteo → DynamoDB (life-platform)" \
        --region us-west-2
fi

echo "✅ Lambda deployed: $FUNC_NAME"

# ── Step 5: EventBridge rule (5:45 AM PT = 13:45 UTC) ──────────────────────
RULE_NAME="weather-daily-ingestion"

aws events put-rule \
    --name $RULE_NAME \
    --schedule-expression "cron(45 13 * * ? *)" \
    --state ENABLED \
    --description "Daily weather fetch from Open-Meteo (5:45 AM PT, before Daily Brief)" \
    --region us-west-2

LAMBDA_ARN=$(aws lambda get-function --function-name $FUNC_NAME --region us-west-2 --query 'Configuration.FunctionArn' --output text)

# Add permission for EventBridge to invoke Lambda
aws lambda add-permission \
    --function-name $FUNC_NAME \
    --statement-id weather-daily-trigger \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:us-west-2:205930651321:rule/$RULE_NAME" \
    --region us-west-2 2>/dev/null || true

aws events put-targets \
    --rule $RULE_NAME \
    --targets "Id=weather-lambda,Arn=$LAMBDA_ARN" \
    --region us-west-2

echo "✅ EventBridge rule: $RULE_NAME (cron 13:45 UTC = 5:45 AM PT)"

# ── Step 6: DLQ ─────────────────────────────────────────────────────────────
aws lambda update-function-configuration \
    --function-name $FUNC_NAME \
    --dead-letter-config TargetArn=arn:aws:sqs:us-west-2:205930651321:life-platform-ingestion-dlq \
    --region us-west-2 2>/dev/null || echo "⚠️  DLQ attach skipped (may need SQS permissions on role)"

# ── Step 7: Smoke test ──────────────────────────────────────────────────────
echo ""
echo "Running smoke test (fetching yesterday's weather)..."
aws lambda invoke \
    --function-name $FUNC_NAME \
    --payload '{}' \
    --region us-west-2 \
    /tmp/weather_test_output.json 2>/dev/null

cat /tmp/weather_test_output.json 2>/dev/null || echo "(output file not found locally — check CloudWatch)"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Weather Lambda deployed!"
echo "  Lambda: $FUNC_NAME"
echo "  Schedule: 5:45 AM PT daily (before Daily Brief)"
echo "  IAM: $ROLE_NAME"
echo "  Data: Open-Meteo → DynamoDB (USER#matthew#SOURCE#weather)"
echo "═══════════════════════════════════════════════════════════════"
