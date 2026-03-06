#!/usr/bin/env python3
"""
Migrate Hevy workout data from source=hevy → source=workouts.

WHY:
  Hevy was a one-time historical import. MacroFactor is the go-forward
  workout tracker. Both should live under the unified source=workouts
  partition so strength history queries (e.g. bench press progression)
  work seamlessly across all years without knowing which app logged the data.

FIELD MAPPING (Hevy → unified):
  workouts[].title           → workouts[].workout_name
  workouts[].exercises[].name → workouts[].exercises[].exercise_name
  sets[].set_type             → sets[].set_type        (unchanged)
  sets[].weight_lbs           → sets[].weight_lbs      (unchanged)
  sets[].reps                 → sets[].reps             (unchanged)
  sets[].rpe                  → sets[].rpe              (kept — different from MF's rir)
  source = "hevy"             → source = "workouts", source_app = "hevy"

WHAT IT DOES:
  1. Scans all items under pk=USER#matthew#SOURCE#hevy
  2. Re-writes them under pk=USER#matthew#SOURCE#workouts with source_app=hevy
  3. Deletes the old hevy items

Usage:
  python3 migrate_hevy_to_workouts.py
  python3 migrate_hevy_to_workouts.py --dry-run
"""

import sys
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key

DYNAMODB_TABLE = "life-platform"
REGION         = "us-west-2"
OLD_PK         = "USER#matthew#SOURCE#hevy"
NEW_PK         = "USER#matthew#SOURCE#workouts"


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(i) for i in obj]
    return obj


def decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    return obj


def migrate_workout(w):
    """Rename fields within a single workout dict."""
    migrated = dict(w)
    # title → workout_name
    if "title" in migrated:
        migrated["workout_name"] = migrated.pop("title")
    # exercises[].name → exercises[].exercise_name
    exercises = migrated.get("exercises", [])
    new_exercises = []
    for ex in exercises:
        ex = dict(ex)
        if "name" in ex:
            ex["exercise_name"] = ex.pop("name")
        new_exercises.append(ex)
    migrated["exercises"] = new_exercises
    return migrated


def migrate_item(old_item):
    """Transform a Hevy DynamoDB item into the unified workouts schema."""
    item = decimal_to_float(dict(old_item))

    item["pk"]         = NEW_PK
    item["source"]     = "workouts"
    item["source_app"] = "hevy"
    item["migrated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if "workouts" in item:
        item["workouts"] = [migrate_workout(w) for w in item["workouts"]]

    return item


def main():
    dry_run = "--dry-run" in sys.argv

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table    = dynamodb.Table(DYNAMODB_TABLE)

    print(f"Scanning for Hevy items under pk={OLD_PK} ...")
    response = table.query(KeyConditionExpression=Key("pk").eq(OLD_PK))
    old_items = response["Items"]
    while "LastEvaluatedKey" in response:
        response  = table.query(
            KeyConditionExpression=Key("pk").eq(OLD_PK),
            ExclusiveStartKey=response["LastEvaluatedKey"]
        )
        old_items += response["Items"]

    print(f"Found {len(old_items)} Hevy items to migrate")

    if not old_items:
        print("Nothing to migrate. Exiting.")
        return

    dates = sorted(str(i.get("date", i.get("sk", ""))) for i in old_items)
    print(f"Date range: {dates[0]} → {dates[-1]}")

    for i, old_item in enumerate(sorted(old_items, key=lambda x: str(x.get("sk", ""))), 1):
        new_item = migrate_item(old_item)
        date_str = new_item.get("date", new_item.get("sk"))

        if dry_run:
            wc = new_item.get("workouts_count", "?")
            ts = new_item.get("total_sets", "?")
            tv = new_item.get("total_volume_lbs", "?")
            # Show one exercise name to confirm field rename worked
            first_ex = "—"
            if new_item.get("workouts"):
                exs = new_item["workouts"][0].get("exercises", [])
                if exs:
                    first_ex = exs[0].get("exercise_name", "⚠ name not renamed")
            print(f"  [DRY RUN] {date_str}: {wc} workout(s)  {ts} sets  "
                  f"{tv} lbs  sample_exercise='{first_ex}'")
        else:
            # Write new item
            table.put_item(Item=floats_to_decimal(new_item))
            # Delete old item
            table.delete_item(Key={"pk": OLD_PK, "sk": old_item["sk"]})
            if i % 10 == 0 or i == len(old_items):
                print(f"  [{i}/{len(old_items)}] migrated up to {date_str}")

    if dry_run:
        print(f"\n--dry-run complete.")
        print(f"Re-run without --dry-run to migrate {len(old_items)} items.")
        print("Old items will be deleted from source=hevy after migration.")
    else:
        print(f"\nMigration complete. {len(old_items)} items moved to source=workouts.")
        print("Old hevy partition is now empty.")


if __name__ == "__main__":
    main()
