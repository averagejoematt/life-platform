"""
backfill_cgm_optimal.py — Backfill blood_glucose_time_in_optimal_pct from S3 CGM readings.

Reads each day's CGM readings from S3 (raw/cgm_readings/YYYY/MM/DD.json),
computes the Attia optimal range (70-120 mg/dL) percentage, and updates
the DynamoDB apple_health record with the new field.

Usage: python backfill_cgm_optimal.py [--dry-run]
"""

import json
import sys
import boto3
from decimal import Decimal

S3_BUCKET = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
PK = "USER#matthew#SOURCE#apple_health"
CGM_PREFIX = "raw/cgm_readings/"

s3 = boto3.client("s3", region_name="us-west-2")
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(DYNAMODB_TABLE)

dry_run = "--dry-run" in sys.argv


def list_cgm_files():
    """List all CGM reading files in S3."""
    files = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=CGM_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                files.append(key)
    return sorted(files)


def extract_date_from_key(key):
    """Extract YYYY-MM-DD from raw/cgm_readings/YYYY/MM/DD.json."""
    parts = key.replace(CGM_PREFIX, "").replace(".json", "").split("/")
    if len(parts) == 3:
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return None


def compute_optimal_pct(readings):
    """Compute % of readings in Attia optimal range (70-120 mg/dL)."""
    values = [r["value"] for r in readings if "value" in r]
    if not values:
        return None, 0
    in_optimal = sum(1 for v in values if 70 <= v <= 120)
    return round(in_optimal / len(values) * 100, 1), len(values)


def update_dynamo(date_str, optimal_pct):
    """Update the apple_health record with time_in_optimal_pct."""
    table.update_item(
        Key={"pk": PK, "sk": f"DATE#{date_str}"},
        UpdateExpression="SET #opt = :opt",
        ExpressionAttributeNames={"#opt": "blood_glucose_time_in_optimal_pct"},
        ExpressionAttributeValues={":opt": Decimal(str(optimal_pct))},
    )


def main():
    files = list_cgm_files()
    print(f"Found {len(files)} CGM reading files in S3")

    updated = 0
    skipped = 0

    for key in files:
        date_str = extract_date_from_key(key)
        if not date_str:
            print(f"  ⚠️  Could not parse date from {key}")
            skipped += 1
            continue

        # Read readings from S3
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        readings = json.loads(resp["Body"].read())

        optimal_pct, count = compute_optimal_pct(readings)
        if optimal_pct is None:
            print(f"  ⚠️  {date_str}: no valid readings, skipping")
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY RUN] {date_str}: {optimal_pct}% optimal ({count} readings)")
        else:
            update_dynamo(date_str, optimal_pct)
            updated += 1

            if updated % 20 == 0:
                print(f"  ... {updated} days updated")

    print(f"\n✅ Backfill complete: {updated} days updated, {skipped} skipped")
    if dry_run:
        print("  (dry run — no DynamoDB writes)")


if __name__ == "__main__":
    main()
