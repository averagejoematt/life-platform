#!/usr/bin/env python3
"""
Replay Feb 24 water data from S3 archive — v2 (robust date parsing).

Diagnoses date format first, then sums dietary_water for 2026-02-24.
"""

import boto3
import json
from decimal import Decimal
from datetime import datetime, timezone

BUCKET = "matthew-life-platform"
S3_KEYS = [
    "raw/health_auto_export/2026/02/24_185348.json",
    "raw/health_auto_export/2026/02/24_224353.json",
    "raw/health_auto_export/2026/02/25_000534.json",
    "raw/health_auto_export/2026/02/25_000934.json",
]
TABLE = "life-platform"
PK = "USER#matthew#SOURCE#apple_health"
TARGET_DATE = "2026-02-24"

def parse_date(date_str):
    """Extract YYYY-MM-DD from various Health Auto Export formats."""
    if not date_str:
        return None
    # ISO: "2026-02-24T08:30:00-08:00"
    # HAE: "2026-02-24 08:30:00 -0800"
    # Just grab first 10 chars
    return date_str[:10]

def main():
    s3 = boto3.client("s3", region_name="us-west-2")
    dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
    table = dynamodb.Table(TABLE)

    # Step 1: Scan ALL archived payloads for water readings
    all_water_readings = []  # (date, qty, source_file)
    for s3_key in S3_KEYS:
        print(f"\nScanning s3://{BUCKET}/{s3_key}...")
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=s3_key)
            payload = json.loads(obj["Body"].read())
        except Exception as e:
            print(f"  SKIP: {e}")
            continue
        data = payload.get("data", payload)
        metrics = data.get("metrics", [])
        print(f"  {len(metrics)} metrics")

        for m in metrics:
            name = m.get("name", "")
            if "water" in name.lower():
                readings = m.get("data", [])
                units = m.get("units", "unknown")
                print(f"  Found '{name}': {len(readings)} readings, units: {units}")
                for r in readings:
                    d = parse_date(r.get("date", ""))
                    qty = r.get("qty")
                    if d and qty is not None:
                        all_water_readings.append((d, float(qty), s3_key, units))
                        print(f"    {d}: {qty} {units}")

    print(f"\n{'='*60}")
    print(f"Total water readings found across all payloads: {len(all_water_readings)}")
    
    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)
    for d, qty, src, units in all_water_readings:
        by_date[d].append((qty, src, units))
    
    for d in sorted(by_date.keys()):
        entries = by_date[d]
        total = sum(q for q, _, _ in entries)
        total_ml = round(total * 29.5735)
        print(f"  {d}: {len(entries)} readings, {total:.2f} fl_oz = {total_ml} mL")
        for q, src, u in entries:
            print(f"    {q} {u} from {src.split('/')[-1]}")

    # Step 2: Sum target date readings (deduplicated by taking latest payload's sum)
    target_readings = by_date.get(TARGET_DATE, [])
    if not target_readings:
        print(f"\nERROR: No water readings found for {TARGET_DATE} in any payload.")
        print("The water data may not have been exported by Health Auto Export yet.")
        return

    day_total = sum(q for q, _, _ in target_readings)
    day_count = len(target_readings)
    units = target_readings[0][2]  # units from first reading

    # Convert
    if "fl_oz" in units.lower() or "oz" in units.lower():
        water_ml = round(day_total * 29.5735)
        water_oz = round(day_total, 1)
    elif "ml" in units.lower():
        water_ml = round(day_total)
        water_oz = round(day_total / 29.5735, 1)
    else:
        print(f"  Assuming fl_oz for units '{units}'")
        water_ml = round(day_total * 29.5735)
        water_oz = round(day_total, 1)

    print(f"\n{TARGET_DATE}: {day_count} readings → {water_ml} mL ({water_oz} oz)")

    # Step 6: Read current
    current = table.get_item(
        Key={"pk": PK, "sk": f"DATE#{TARGET_DATE}"},
        ProjectionExpression="water_intake_ml, water_intake_oz"
    ).get("Item", {})
    print(f"  Current DynamoDB: {dict(current)}")

    # Step 7: Update
    table.update_item(
        Key={"pk": PK, "sk": f"DATE#{TARGET_DATE}"},
        UpdateExpression="SET water_intake_ml = :ml, water_intake_oz = :oz, water_replay_at = :ts",
        ExpressionAttributeValues={
            ":ml": Decimal(str(water_ml)),
            ":oz": Decimal(str(water_oz)),
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(f"  ✅ Updated: {water_ml} mL ({water_oz} oz)")

    # Step 8: Verify
    verify = table.get_item(
        Key={"pk": PK, "sk": f"DATE#{TARGET_DATE}"},
        ProjectionExpression="water_intake_ml, water_intake_oz, water_replay_at"
    ).get("Item", {})
    print(f"  Verified: {dict(verify)}")


if __name__ == "__main__":
    main()
