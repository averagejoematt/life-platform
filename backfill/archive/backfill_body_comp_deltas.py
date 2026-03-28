#!/usr/bin/env python3
"""
Backfill lean_mass_delta_14d and fat_mass_delta_14d for all historical
Withings records.

Uses update_item (additive) — never overwrites existing data.

Usage:
    python3 backfill_body_comp_deltas.py              # live write
    python3 backfill_body_comp_deltas.py --dry-run     # preview only
"""

import sys
import boto3
from decimal import Decimal
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key

DYNAMODB_TABLE = "life-platform"
REGION = "us-west-2"
PK = "USER#matthew#SOURCE#withings"


def main():
    dry_run = "--dry-run" in sys.argv

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)

    # Query ALL Withings records
    print("Querying all Withings records...")
    all_items = []
    last_key = None

    while True:
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(PK) & Key("sk").begins_with("DATE#"),
            "ProjectionExpression": "#d, fat_free_mass_lbs, fat_mass_lbs",
            "ExpressionAttributeNames": {"#d": "date"},
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        resp = table.query(**kwargs)
        all_items.extend(resp["Items"])
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    print(f"  Found {len(all_items)} records")
    all_items.sort(key=lambda x: x["date"])

    # Build lookup by date
    by_date = {}
    dates = []
    for item in all_items:
        d = item["date"]
        by_date[d] = item
        dates.append(d)

    # Compute deltas
    updated = 0
    skipped = 0

    for date_str in dates:
        item = by_date[date_str]
        current_lean = item.get("fat_free_mass_lbs")
        current_fat = item.get("fat_mass_lbs")

        if current_lean is None and current_fat is None:
            skipped += 1
            continue

        # Find nearest record 11-17 days ago
        target_dt = datetime.strptime(date_str, "%Y-%m-%d")
        best_match = None
        best_distance = 999

        for d in dates:
            d_dt = datetime.strptime(d, "%Y-%m-%d")
            days_diff = (target_dt - d_dt).days
            if 11 <= days_diff <= 17:
                distance = abs(days_diff - 14)
                if distance < best_distance:
                    best_distance = distance
                    best_match = d

        if best_match is None:
            skipped += 1
            continue

        prev = by_date[best_match]
        expr_parts = []
        expr_values = {}

        if current_lean is not None and prev.get("fat_free_mass_lbs") is not None:
            delta = round(float(current_lean) - float(prev["fat_free_mass_lbs"]), 2)
            expr_parts.append("lean_mass_delta_14d = :lean_delta")
            expr_values[":lean_delta"] = Decimal(str(delta))

        if current_fat is not None and prev.get("fat_mass_lbs") is not None:
            delta = round(float(current_fat) - float(prev["fat_mass_lbs"]), 2)
            expr_parts.append("fat_mass_delta_14d = :fat_delta")
            expr_values[":fat_delta"] = Decimal(str(delta))

        if not expr_parts:
            skipped += 1
            continue

        if dry_run:
            vals = {k.replace(":", ""): float(v) for k, v in expr_values.items()}
            if (updated + 1) % 50 == 0 or updated < 5 or date_str == dates[-1]:
                print(f"  {date_str}: {vals} (vs {best_match})")
        else:
            table.update_item(
                Key={"pk": PK, "sk": f"DATE#{date_str}"},
                UpdateExpression="SET " + ", ".join(expr_parts),
                ExpressionAttributeValues=expr_values,
            )

        updated += 1
        if not dry_run and updated % 100 == 0:
            print(f"  [{updated}] updated through {date_str}")

    if dry_run:
        print(f"\n--dry-run: would update {updated} records, skip {skipped}")
    else:
        print(f"\n✅ Updated {updated} records, skipped {skipped}")

    # Show recent values
    print("\nRecent records:")
    for d in dates[-3:]:
        item = by_date[d]
        lean = item.get("fat_free_mass_lbs", "?")
        fat = item.get("fat_mass_lbs", "?")
        print(f"  {d}: lean={lean} lbs, fat={fat} lbs")


if __name__ == "__main__":
    main()
