#!/usr/bin/env python3
"""
replay_s3_archive.py — Replay a Health Auto Export S3 archive through the webhook Lambda.

Downloads the archived raw payload from S3 and invokes the health-auto-export-webhook
Lambda directly (bypassing API Gateway + iOS app). This lets us reprocess payloads
that arrived before the Lambda code was updated.

Usage:
    python3 replay_s3_archive.py [S3_KEY]
    
    Default: replays the 289KB full-metric archive from Feb 24.
"""

import json
import sys
import base64
import boto3

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
LAMBDA_NAME = "health-auto-export-webhook"
SECRET_NAME = "life-platform/health-auto-export"

# Default to the big 48-metric payload
DEFAULT_KEY = "raw/health_auto_export/2026/02/24_185348.json"

def main():
    s3_key = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEY
    
    s3 = boto3.client("s3", region_name=REGION)
    secrets = boto3.client("secretsmanager", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)
    
    # Get the API key for auth
    secret_resp = secrets.get_secret_value(SecretId=SECRET_NAME)
    api_key = json.loads(secret_resp["SecretString"])["api_key"]
    
    # Download the archived payload
    print(f"Downloading s3://{S3_BUCKET}/{s3_key} ...")
    resp = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
    payload_body = resp["Body"].read().decode("utf-8")
    payload_data = json.loads(payload_body)
    
    metrics_count = len(payload_data.get("data", payload_data).get("metrics", []))
    workouts_count = len(payload_data.get("data", payload_data).get("workouts", []))
    print(f"Payload: {metrics_count} metrics, {workouts_count} workouts, {len(payload_body)} bytes")
    
    # Construct the API Gateway-style event the Lambda expects
    event = {
        "headers": {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        "body": payload_body,
        "isBase64Encoded": False,
        "requestContext": {
            "http": {"method": "POST", "path": "/ingest"},
        },
    }
    
    # Invoke Lambda directly
    print(f"Invoking {LAMBDA_NAME} ...")
    invoke_resp = lam.invoke(
        FunctionName=LAMBDA_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )
    
    status = invoke_resp["StatusCode"]
    resp_payload = json.loads(invoke_resp["Payload"].read())
    
    print(f"\nLambda status: {status}")
    
    if "body" in resp_payload:
        body = json.loads(resp_payload["body"])
        print(f"HTTP status: {resp_payload.get('statusCode')}")
        print(f"Glucose days updated: {body.get('glucose_days_updated', 0)}")
        print(f"Other metric days: {body.get('other_metric_days', 0)}")
        print(f"Metrics received: {body.get('metrics_received', [])}")
        if body.get("other_metric_days", 0) > 0:
            print("\n✅ Backfill successful!")
        else:
            print("\n⚠️  No metric days written — check Lambda logs")
    else:
        print(f"Response: {json.dumps(resp_payload, indent=2)}")


if __name__ == "__main__":
    main()
