#!/usr/bin/env python3
"""
Backfill sleep_onset_minutes and sleep_onset_consistency_7d for all historical
Whoop records by reading sleep_start from S3 raw files.

Phase 3 (v2.25.0) added sleep_start/sleep_end to the Whoop Lambda, but only
going forward. Historical records have the data in S3 but not in DynamoDB.

This script:
  1. Lists all S3 raw sleep files
  2. Extracts sleep_start from the raw JSON
  3. Computes sleep_onset_minutes and rolling 7-day consistency
  4. Updates DynamoDB records with update_item (additive, no overwrites)

Usage:
    python3 backfill_sleep_consistency.py              # live write
    python3 backfill_sleep_consistency.py --dry-run     # preview only
"""

import json
import sys
import statistics
import boto3
from datetime import datetime
from decimal import Decimal

DYNAMODB_TABLE = "life-platform"
S3_BUCKET = "matthew-life-platform"
REGION = "us-west-2"
PK = "USER#matthew#SOURCE#whoop"


def sleep_onset_minutes(iso_timestamp):
    """Convert ISO sleep_start to minutes from midnight (UTC)."""
    if not iso_timestamp:
        return None
    try:
        ts = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        return dt.hour * 60 + dt.minute
    except (ValueError, AttributeError):
        return None


def compute_consistency(onsets_window):
    """
    Compute StdDev of sleep onset times with midnight wraparound handling.
    Returns float or None if <3 data points.
    """
    values = [v for v in onsets_window if v is not None]
    if len(values) < 3:
        return None

    min_val = min(values)
    max_val = max(values)
    if max_val - min_val > 720:
        values = [v + 1440 if v < 720 else v for v in values]

    return round(statistics.stdev(values), 1)


def extract_sleep_start_from_s3(s3_client, key):
    """Read an S3 raw sleep JSON file and extract the main sleep start time."""
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        print(f"  [WARN] Could not read {key}: {e}")
        return None

    records = data.get("records", [])
    if not records:
        return None

    # Find main sleep (not naps) - take the one with longest duration
    main_sleep = None
    longest = 0
    for r in records:
        if r.get("nap", False):
            continue
        score = r.get("score") or {}
        stage = score.get("stage_summary") or {}
        in_bed = stage.get("total_in_bed_time_milli", 0)
        if in_bed > longest:
            longest = in_bed
            main_sleep = r

    if main_sleep:
        return main_sleep.get("start")
    return None


def main():
    dry_run = "--dry-run" in sys.argv

    s3 = boto3.client("s3", region_name=REGION)
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)

    # Step 1: List all S3 raw sleep files
    print("Step 1: Listing S3 raw sleep files...")
    sleep_files = {}  # date_str -> s3_key
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="raw/whoop/sleep/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Pattern: raw/whoop/sleep/YYYY/MM/DD.json
            parts = key.split("/")
            if len(parts) == 6 and parts[5].endswith(".json"):
                year, month, day_file = parts[3], parts[4], parts[5]
                day = day_file.replace(".json", "")
                date_str = f"{year}-{month}-{day}"
                sleep_files[date_str] = key

    print(f"  Found {len(sleep_files)} sleep files in S3")

    # Step 2: Extract sleep_start from each file
    print("Step 2: Extracting sleep_start from S3 files...")
    onset_by_date = {}
    dates_with_data = 0

    for i, (date_str, s3_key) in enumerate(sorted(sleep_files.items())):
        sleep_start = extract_sleep_start_from_s3(s3, s3_key)
        onset = sleep_onset_minutes(sleep_start)
        onset_by_date[date_str] = {
            "onset_minutes": onset,
            "sleep_start": sleep_start,
        }
        if onset is not None:
            dates_with_data += 1

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(sleep_files)}] processed...")

    print(f"  {dates_with_data}/{len(sleep_files)} files have valid sleep_start")

    # Step 3: Compute rolling consistency and write
    print("Step 3: Computing consistency and writing to DynamoDB...")
    dates = sorted(onset_by_date.keys())
    updated = 0
    skipped = 0

    for i, date_str in enumerate(dates):
        entry = onset_by_date[date_str]
        onset_min = entry["onset_minutes"]
        sleep_start = entry["sleep_start"]

        if onset_min is None:
            skipped += 1
            continue

        # Get last 7 values (including current)
        window_start = max(0, i - 6)
        window = [onset_by_date[dates[j]]["onset_minutes"] for j in range(window_start, i + 1)]
        consistency = compute_consistency(window)

        if dry_run:
            if i < 5 or (i + 1) % 200 == 0 or i == len(dates) - 1:
                c_str = f"{consistency:.1f}" if consistency else "N/A"
                print(f"  {date_str}: onset={onset_min} min, consistency={c_str}")
        else:
            # Build update expression — also backfill sleep_start if not present
            expr_parts = ["sleep_onset_minutes = :onset"]
            expr_values = {":onset": onset_min}

            if sleep_start:
                expr_parts.append("sleep_start = if_not_exists(sleep_start, :ss)")
                expr_values[":ss"] = sleep_start

            if consistency is not None:
                expr_parts.append("sleep_onset_consistency_7d = :consistency")
                expr_values[":consistency"] = Decimal(str(consistency))

            try:
                table.update_item(
                    Key={"pk": PK, "sk": f"DATE#{date_str}"},
                    UpdateExpression="SET " + ", ".join(expr_parts),
                    ExpressionAttributeValues=expr_values,
                )
                updated += 1
            except Exception as e:
                # Record might not exist in DynamoDB (S3 file exists but no DDB record)
                print(f"  [WARN] Could not update {date_str}: {e}")
                skipped += 1
                continue

            if updated % 100 == 0:
                print(f"  [{updated}] updated through {date_str}")

    if dry_run:
        print(f"\n--dry-run: would update {dates_with_data} records, skip {skipped}")
    else:
        print(f"\n✅ Updated {updated} records, skipped {skipped}")

    # Show recent values
    print("\nRecent values:")
    for date_str in dates[-5:]:
        entry = onset_by_date[date_str]
        onset = entry["onset_minutes"]
        if onset is not None:
            idx = dates.index(date_str)
            window_start = max(0, idx - 6)
            window = [onset_by_date[dates[j]]["onset_minutes"] for j in range(window_start, idx + 1)]
            c = compute_consistency(window)
            c_str = f"{c:.1f}" if c else "N/A"
            print(f"  {date_str}: onset={onset} min, consistency={c_str}")


if __name__ == "__main__":
    main()
