#!/usr/bin/env python3
"""
backfill_workouts.py — Replay existing HAE payloads to backfill workout data.

Scans raw/health_auto_export/ in S3 for payloads containing workouts,
processes them through the v1.6.0 workout classification logic, and writes
results to S3 (raw/workouts/) and DynamoDB (apple_health partition).

Usage:
  python3 backfill/backfill_workouts.py --dry-run   # Preview
  python3 backfill/backfill_workouts.py              # Execute
"""
import argparse
import json
import boto3
import math
from datetime import datetime, timezone
from decimal import Decimal
from collections import defaultdict

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
TABLE_NAME = "life-platform"
USER_ID = "matthew"
PK = f"USER#{USER_ID}#SOURCE#apple_health"

s3 = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

# ── Recovery workout classification (mirrors Lambda v1.6.0) ──
RECOVERY_WORKOUT_TYPES = {
    "Flexibility": "flexibility", "flexibility": "flexibility",
    "Mind and Body": "breathwork", "mind_and_body": "breathwork",
    "Breathing": "breathwork", "breathing": "breathwork",
    "Yoga": "yoga", "yoga": "yoga",
    "Pilates": "pilates", "pilates": "pilates",
    "Cooldown": "cooldown", "cooldown": "cooldown",
    "Tai Chi": "tai_chi", "tai_chi": "tai_chi",
}


def floats_to_decimal(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def parse_date_str(date_str):
    return date_str[:10] if date_str else None


def list_hae_payloads():
    """List all raw HAE payload keys in S3."""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="raw/health_auto_export/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return sorted(keys)


def process_workouts(workouts):
    """Classify and aggregate workouts (same logic as Lambda v1.6.0)."""
    daily_workouts = defaultdict(list)

    for w in workouts:
        date = parse_date_str(w.get("start", ""))
        if not date:
            continue

        name = w.get("name", "Unknown")
        duration_sec = w.get("duration", 0)
        try:
            duration_sec = float(duration_sec)
        except (ValueError, TypeError):
            duration_sec = 0
        duration_min = round(duration_sec / 60, 1)

        energy_kcal = 0
        aeb = w.get("activeEnergyBurned", {})
        if isinstance(aeb, dict) and aeb.get("qty") is not None:
            try:
                energy_kcal = round(float(aeb["qty"]), 1)
            except (ValueError, TypeError):
                pass
        if not energy_kcal:
            ae_readings = w.get("activeEnergy", [])
            if ae_readings:
                energy_kcal = round(sum(float(r.get("qty", 0)) for r in ae_readings), 1)

        category = RECOVERY_WORKOUT_TYPES.get(name, "other")

        workout_record = {
            "id": w.get("id", ""),
            "name": name,
            "category": category,
            "start": w.get("start", ""),
            "end": w.get("end", ""),
            "duration_min": duration_min,
            "active_energy_kcal": energy_kcal,
            "is_indoor": w.get("isIndoor"),
            "is_recovery_type": category != "other",
        }
        daily_workouts[date].append(workout_record)

    # Aggregate recovery workouts
    daily_agg = {}
    for date, wkts in daily_workouts.items():
        recovery = [w for w in wkts if w["is_recovery_type"]]
        if not recovery:
            continue

        agg = {}
        cat_minutes = defaultdict(float)
        cat_sessions = defaultdict(int)
        for w in recovery:
            cat = w["category"]
            cat_minutes[cat] += w["duration_min"]
            cat_sessions[cat] += 1

        if cat_minutes.get("flexibility"):
            agg["flexibility_minutes"] = round(cat_minutes["flexibility"], 1)
            agg["flexibility_sessions"] = cat_sessions["flexibility"]
        if cat_minutes.get("breathwork"):
            agg["breathwork_minutes"] = round(cat_minutes["breathwork"], 1)
            agg["breathwork_sessions"] = cat_sessions["breathwork"]
        if cat_minutes.get("yoga"):
            agg["yoga_minutes"] = round(cat_minutes["yoga"], 1)
            agg["yoga_sessions"] = cat_sessions["yoga"]
        if cat_minutes.get("pilates"):
            agg["pilates_minutes"] = round(cat_minutes["pilates"], 1)
            agg["pilates_sessions"] = cat_sessions["pilates"]
        if cat_minutes.get("cooldown"):
            agg["cooldown_minutes"] = round(cat_minutes["cooldown"], 1)
        if cat_minutes.get("tai_chi"):
            agg["tai_chi_minutes"] = round(cat_minutes["tai_chi"], 1)

        total_min = sum(cat_minutes.values())
        agg["recovery_workout_minutes"] = round(total_min, 1)
        agg["recovery_workout_sessions"] = len(recovery)
        agg["recovery_workout_types"] = ", ".join(sorted(set(
            w["category"] for w in recovery
        )))
        daily_agg[date] = agg

    return daily_workouts, daily_agg


def save_workouts_to_s3(date_str, workouts_list):
    """Save workout records to S3, merging with existing."""
    s3_key = f"raw/workouts/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    existing = []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3.exceptions.NoSuchKey:
        pass
    except Exception:
        pass

    existing_ids = {w.get("id") for w in existing if w.get("id")}
    new_workouts = [w for w in workouts_list if w.get("id") and w["id"] not in existing_ids]

    if new_workouts:
        merged = existing + new_workouts
        merged.sort(key=lambda w: w.get("start", ""))
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_workouts)
    return 0


def merge_day_to_dynamo(date_str, fields):
    """Merge fields into existing DynamoDB record."""
    if not fields:
        return

    set_parts = []
    names = {}
    values = {}

    for i, (key, val) in enumerate(fields.items()):
        if val is None:
            continue
        attr_name = f"#f{i}"
        attr_val = f":v{i}"
        set_parts.append(f"{attr_name} = {attr_val}")
        names[attr_name] = key
        values[attr_val] = floats_to_decimal(val)

    if not set_parts:
        return

    set_parts.append("#upd = :upd")
    names["#upd"] = "workout_backfill_at"
    values[":upd"] = datetime.now(timezone.utc).isoformat()

    set_parts.append("#src = if_not_exists(#src, :src)")
    names["#src"] = "source"
    values[":src"] = "apple_health"

    set_parts.append("#dt = if_not_exists(#dt, :dt)")
    names["#dt"] = "date"
    values[":dt"] = date_str

    table.update_item(
        Key={"pk": PK, "sk": f"DATE#{date_str}"},
        UpdateExpression="SET " + ", ".join(set_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill workout data from existing HAE payloads")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    print("=" * 60)
    print("Workout Backfill — v1.6.0")
    print("=" * 60)

    # Scan all HAE payloads
    keys = list_hae_payloads()
    print(f"Found {len(keys)} raw HAE payloads in S3")

    total_workouts = 0
    total_recovery = 0
    all_daily_workouts = defaultdict(list)
    all_daily_agg = {}

    for key in keys:
        try:
            resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
            payload = json.loads(resp["Body"].read())
        except Exception as e:
            print(f"  ERROR reading {key}: {e}")
            continue

        data = payload.get("data", payload)
        workouts = data.get("workouts", []) if isinstance(data, dict) else []

        if not workouts:
            continue

        daily_workouts, daily_agg = process_workouts(workouts)

        for date, wkts in daily_workouts.items():
            all_daily_workouts[date].extend(wkts)
            total_workouts += len(wkts)

        for date, agg in daily_agg.items():
            # Merge aggregates (accumulate if multiple payloads per day)
            if date in all_daily_agg:
                for k, v in agg.items():
                    if isinstance(v, (int, float)) and k in all_daily_agg[date]:
                        all_daily_agg[date][k] = all_daily_agg[date].get(k, 0) + v
                    else:
                        all_daily_agg[date][k] = v
            else:
                all_daily_agg[date] = agg
            total_recovery += sum(1 for w in daily_workouts.get(date, []) if w["is_recovery_type"])

        print(f"  {key}: {len(workouts)} workouts")

    print(f"\nTotal: {total_workouts} workouts across {len(all_daily_workouts)} days")
    print(f"Recovery workouts: {total_recovery}")

    if not all_daily_workouts:
        print("\nNo workouts found to backfill.")
        return

    # Show what we found
    print(f"\nBy date:")
    for date in sorted(all_daily_workouts.keys()):
        wkts = all_daily_workouts[date]
        recovery = [w for w in wkts if w["is_recovery_type"]]
        other = [w for w in wkts if not w["is_recovery_type"]]
        parts = []
        for w in wkts:
            parts.append(f"{w['name']}({w['category']})={w['duration_min']}min")
        agg = all_daily_agg.get(date, {})
        print(f"  {date}: {', '.join(parts)}")
        if agg:
            print(f"    → DDB: {agg}")

    if args.dry_run:
        print(f"\n[DRY RUN — no writes]")
        return

    # Write
    s3_written = 0
    ddb_written = 0
    for date in sorted(all_daily_workouts.keys()):
        # S3: all workouts
        n = save_workouts_to_s3(date, all_daily_workouts[date])
        s3_written += n

        # DDB: recovery aggregates only
        if date in all_daily_agg:
            merge_day_to_dynamo(date, all_daily_agg[date])
            ddb_written += 1

    print(f"\n{'=' * 60}")
    print(f"Done. S3: {s3_written} new workouts | DDB: {ddb_written} days updated")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
