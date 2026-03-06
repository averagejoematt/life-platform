#!/usr/bin/env python3
"""
Hevy historical backfill script.
Reads exported workout_data.csv and writes one DynamoDB item per day
under source=hevy, mirroring the Strava day-aggregate pattern.

Item structure per day:
  pk:                USER#matthew#SOURCE#hevy
  sk:                DATE#YYYY-MM-DD
  date:              YYYY-MM-DD
  source:            hevy
  workouts_count:    int
  total_sets:        int
  total_volume_lbs:  float  (weight_lbs * reps, summed across all weighted sets)
  unique_exercises:  int
  workouts:          [ { title, start_time, end_time, duration_minutes,
                         exercises: [ { name, sets: [ {set_index, type, weight_lbs, reps} ] } ] } ]

Usage:
  python3 backfill_hevy.py path/to/workout_data.csv
  python3 backfill_hevy.py path/to/workout_data.csv --dry-run
"""

import csv
import sys
import json
import boto3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

DYNAMODB_TABLE = "life-platform"
REGION = "us-west-2"
PK = "USER#matthew#SOURCE#hevy"


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def parse_dt(s):
    """Parse Hevy date format: '8 Nov 2025, 05:20'"""
    return datetime.strptime(s.strip(), "%d %b %Y, %H:%M")


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_day_items(rows):
    """
    Group rows → workouts → exercises → sets, then aggregate by date.
    Returns { 'YYYY-MM-DD': ddb_item }
    """
    # Group rows by (title, start_time, end_time) to identify unique workouts
    workout_rows = defaultdict(list)
    for row in rows:
        key = (row["title"], row["start_time"], row["end_time"])
        workout_rows[key].append(row)

    # Group workouts by local date
    day_workouts = defaultdict(list)
    for (title, start_str, end_str), sets_rows in workout_rows.items():
        start_dt = parse_dt(start_str)
        end_dt   = parse_dt(end_str)
        date_str = start_dt.strftime("%Y-%m-%d")
        duration_minutes = round((end_dt - start_dt).total_seconds() / 60, 1)

        # Group sets by exercise
        exercise_rows = defaultdict(list)
        for row in sets_rows:
            exercise_rows[row["exercise_title"]].append(row)

        exercises = []
        for ex_name, ex_sets in exercise_rows.items():
            parsed_sets = []
            for s in sorted(ex_sets, key=lambda r: int(r.get("set_index") or 0)):
                weight = float(s["weight_lbs"]) if s.get("weight_lbs") else None
                reps   = int(s["reps"]) if s.get("reps") else None
                dist   = float(s["distance_miles"]) if s.get("distance_miles") else None
                dur    = int(s["duration_seconds"]) if s.get("duration_seconds") else None
                rpe    = float(s["rpe"]) if s.get("rpe") else None
                parsed_sets.append({k: v for k, v in {
                    "set_index":        int(s.get("set_index") or 0),
                    "set_type":         s.get("set_type") or "normal",
                    "weight_lbs":       weight,
                    "reps":             reps,
                    "distance_miles":   dist,
                    "duration_seconds": dur,
                    "rpe":              rpe,
                }.items() if v is not None})
            exercises.append({"name": ex_name, "sets": parsed_sets})

        day_workouts[date_str].append({
            "title":            title,
            "start_time":       start_str,
            "end_time":         end_str,
            "duration_minutes": duration_minutes,
            "exercises":        exercises,
        })

    # Build one DynamoDB item per day
    day_items = {}
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for date_str, workouts in day_workouts.items():
        total_sets    = 0
        total_volume  = 0.0
        all_exercises = set()

        for w in workouts:
            for ex in w["exercises"]:
                all_exercises.add(ex["name"])
                for s in ex["sets"]:
                    total_sets += 1
                    weight = s.get("weight_lbs") or 0
                    reps   = s.get("reps") or 0
                    total_volume += weight * reps

        item = {
            "pk":               PK,
            "sk":               f"DATE#{date_str}",
            "date":             date_str,
            "source":           "hevy",
            "ingested_at":      ingested_at,
            "workouts_count":   len(workouts),
            "total_sets":       total_sets,
            "total_volume_lbs": round(total_volume, 1),
            "unique_exercises": len(all_exercises),
            "workouts":         workouts,
        }
        day_items[date_str] = item

    return day_items


def write_to_dynamodb(day_items, dry_run=False):
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table    = dynamodb.Table(DYNAMODB_TABLE)

    dates = sorted(day_items.keys())
    print(f"Writing {len(dates)} day items to DynamoDB ({dates[0]} → {dates[-1]})")

    for i, date_str in enumerate(dates, 1):
        item = floats_to_decimal(day_items[date_str])
        if dry_run:
            print(f"  [DRY RUN] {date_str}: {item['workouts_count']} workouts, "
                  f"{item['total_sets']} sets, {item['total_volume_lbs']} lbs volume")
        else:
            table.put_item(Item=item)
            if i % 20 == 0 or i == len(dates):
                print(f"  [{i}/{len(dates)}] written up to {date_str}")

    print("Done.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 backfill_hevy.py <path_to_workout_data.csv> [--dry-run]")
        sys.exit(1)

    csv_path = sys.argv[1]
    dry_run  = "--dry-run" in sys.argv

    print(f"Loading {csv_path}...")
    rows = load_csv(csv_path)
    print(f"  {len(rows)} rows loaded")

    print("Parsing into day items...")
    day_items = build_day_items(rows)

    total_workouts = sum(i["workouts_count"] for i in day_items.values())
    total_sets     = sum(i["total_sets"]     for i in day_items.values())
    total_volume   = sum(i["total_volume_lbs"] for i in day_items.values())
    print(f"  {len(day_items)} unique days")
    print(f"  {total_workouts} workouts")
    print(f"  {total_sets} sets")
    print(f"  {total_volume:,.0f} lbs total volume")

    write_to_dynamodb(day_items, dry_run=dry_run)


if __name__ == "__main__":
    main()
