#!/usr/bin/env python3
"""
One-time migration: Hevy DynamoDB items → macrofactor_workouts canonical schema.

Reads all items from pk=USER#matthew#SOURCE#hevy, remaps field names to the
MacroFactor canonical schema, and writes them to pk=USER#matthew#SOURCE#macrofactor_workouts.

This preserves full history so exercise progression queries (e.g. bench press
weight over time) work seamlessly across Hevy (historical) and MacroFactor (current).

Field mapping:
  Hevy                          → Canonical (MacroFactor)
  ─────────────────────────────────────────────────────
  workouts[].title              → workouts[].workout_name
  workouts[].duration_minutes   → workouts[].workout_duration_min
  workouts[].exercises[].name   → workouts[].exercises[].exercise_name
  sets[].set_type               → sets[].set_type               (unchanged)
  sets[].weight_lbs             → sets[].weight_lbs             (unchanged)
  sets[].reps                   → sets[].reps                   (unchanged)
  sets[].rpe                    → sets[].rpe                    (kept, different scale from RIR)
  sets[].duration_seconds       → sets[].set_duration_sec       (renamed for consistency)
  sets[].distance_miles         → sets[].distance_miles         (unchanged)
  source = "hevy"               → source = "macrofactor_workouts", original_source = "hevy"

Usage:
  python3 migrate_hevy_to_macrofactor.py
  python3 migrate_hevy_to_macrofactor.py --dry-run
  python3 migrate_hevy_to_macrofactor.py --dry-run --limit 5
"""

import sys
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key

DYNAMODB_TABLE  = "life-platform"
REGION          = "us-west-2"
HEVY_PK         = "USER#matthew#SOURCE#hevy"
TARGET_PK       = "USER#matthew#SOURCE#macrofactor_workouts"


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(i) for i in obj]
    return obj


def decimal_to_native(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_native(i) for i in obj]
    return obj


def remap_set(s):
    """Rename Hevy set fields to canonical names."""
    out = {}
    for k, v in s.items():
        if k == "duration_seconds":
            out["set_duration_sec"] = v   # rename
        else:
            out[k] = v                    # set_index, set_type, weight_lbs, reps, rpe, distance_miles
    return out


def remap_exercise(ex):
    """Rename Hevy exercise fields to canonical names."""
    return {
        "exercise_name": ex.get("name") or ex.get("exercise_name", ""),
        "sets": [remap_set(s) for s in ex.get("sets", [])],
    }


def remap_workout(w):
    """Rename Hevy workout fields to canonical names."""
    out = {
        "workout_name": w.get("title") or w.get("workout_name", "Workout"),
        "exercises":    [remap_exercise(ex) for ex in w.get("exercises", [])],
    }
    # duration: Hevy stores duration_minutes
    dur = w.get("duration_minutes") or w.get("workout_duration_min")
    if dur is not None:
        out["workout_duration_min"] = float(dur)
    # Preserve original timing fields as metadata
    if w.get("start_time"):
        out["start_time"] = w["start_time"]
    return out


def remap_item(item, migrated_at):
    """Remap a full Hevy day item to the macrofactor_workouts canonical schema."""
    native = decimal_to_native(item)
    return {
        "pk":                TARGET_PK,
        "sk":                native["sk"],              # DATE#YYYY-MM-DD unchanged
        "date":              native["date"],
        "source":            "macrofactor_workouts",
        "original_source":   "hevy",                   # audit trail
        "migrated_at":       migrated_at,
        "ingested_at":       native.get("ingested_at", migrated_at),
        "workouts_count":    native.get("workouts_count", 0),
        "total_sets":        native.get("total_sets", 0),
        "total_volume_lbs":  native.get("total_volume_lbs", 0.0),
        "unique_exercises":  native.get("unique_exercises", 0),
        "workouts":          [remap_workout(w) for w in native.get("workouts", [])],
    }


def fetch_hevy_items(table):
    """Fetch all items from the Hevy partition key."""
    items = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(HEVY_PK)
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def main():
    dry_run = "--dry-run" in sys.argv
    limit   = None
    if "--limit" in sys.argv:
        idx   = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    dynamodb     = boto3.resource("dynamodb", region_name=REGION)
    table        = dynamodb.Table(DYNAMODB_TABLE)
    migrated_at  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("Fetching Hevy items from DynamoDB ...")
    hevy_items = fetch_hevy_items(table)
    print(f"  Found {len(hevy_items)} Hevy day items")

    if not hevy_items:
        print("  Nothing to migrate.")
        return

    if limit:
        hevy_items = hevy_items[:limit]
        print(f"  (--limit {limit}: processing first {limit} items only)")

    migrated = [remap_item(item, migrated_at) for item in hevy_items]

    # Summary
    dates = sorted(m["date"] for m in migrated)
    total_w = sum(m["workouts_count"]   for m in migrated)
    total_s = sum(m["total_sets"]       for m in migrated)
    total_v = sum(m["total_volume_lbs"] for m in migrated)
    print(f"\n  Date range:    {dates[0]} → {dates[-1]}")
    print(f"  Days:          {len(migrated)}")
    print(f"  Workouts:      {total_w}")
    print(f"  Sets:          {total_s}")
    print(f"  Volume:        {total_v:,.0f} lbs")
    print(f"  Target pk:     {TARGET_PK}")

    if dry_run:
        print(f"\n  [DRY RUN] Sample remapped item ({dates[0]}):")
        sample = migrated[0]
        print(f"    pk:              {sample['pk']}")
        print(f"    source:          {sample['source']}")
        print(f"    original_source: {sample['original_source']}")
        if sample["workouts"]:
            w = sample["workouts"][0]
            print(f"    workout_name:    {w.get('workout_name')}")
            print(f"    duration_min:    {w.get('workout_duration_min')}")
            if w["exercises"]:
                ex = w["exercises"][0]
                print(f"    exercise_name:   {ex['exercise_name']}")
                if ex["sets"]:
                    print(f"    set[0]:          {ex['sets'][0]}")
        print("\n--dry-run: no changes written. Re-run without --dry-run to migrate.")
        return

    print(f"\nWriting {len(migrated)} items to {TARGET_PK} ...")
    for i, item in enumerate(migrated, 1):
        table.put_item(Item=floats_to_decimal(item))
        if i % 20 == 0 or i == len(migrated):
            print(f"  [{i}/{len(migrated)}] written up to {item['date']}")

    print(f"\n✓ Migration complete. {len(migrated)} Hevy days now available under macrofactor_workouts.")
    print(f"  Original Hevy items left intact at {HEVY_PK} (safe to delete manually if desired).")


if __name__ == "__main__":
    main()
