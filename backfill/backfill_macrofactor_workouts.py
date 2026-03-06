#!/usr/bin/env python3
"""
MacroFactor workout backfill — Granular Workout Export format.

HOW TO EXPORT FROM MACROFACTOR:
  More → Data Management → Data Export → Granular Export tab
  → select "Workouts" → choose "All time" → Export

Confirmed schema (from MacroFactor-20260222093726.csv):
  Date, Workout Duration, Workout, Exercise, Exercise Base Weight (lbs),
  Set Type, Weight (lbs), Reps, RIR, Duration, Distance short (Yd), Distance long (Mi)

One row per set. This script groups rows → exercises → workouts → days,
then writes one DynamoDB item per day under:
  pk: USER#matthew#SOURCE#macrofactor_workouts
  sk: DATE#YYYY-MM-DD

Usage:
  python3 backfill_macrofactor_workouts.py path/to/MacroFactor-*.csv
  python3 backfill_macrofactor_workouts.py path/to/MacroFactor-*.csv --dry-run
"""

import csv
import sys
import boto3
from collections import defaultdict, OrderedDict
from datetime import datetime, timezone
from decimal import Decimal

DYNAMODB_TABLE = "life-platform"
REGION         = "us-west-2"
S3_BUCKET      = "matthew-life-platform"
PK             = "USER#matthew#SOURCE#macrofactor_workouts"


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(i) for i in obj]
    return obj


def safe_float(val):
    if val is None: return None
    s = str(val).strip()
    if s in ("", "-", "N/A"): return None
    try: return float(s.replace(",", ""))
    except ValueError: return None


def safe_int(val):
    v = safe_float(val)
    return int(v) if v is not None else None


def parse_duration_min(val):
    """
    Parse MacroFactor workout duration string → float minutes.
    Handles: '1h 23m', '45m', '1h', '90', '1:30:00', '45:00'
    """
    if not val or not str(val).strip():
        return None
    s = str(val).strip()

    # 'Xh Ym' or 'Xh' or 'Ym'
    if 'h' in s or 'm' in s:
        hours = minutes = 0
        if 'h' in s:
            h_part = s.split('h')[0].strip()
            hours = float(h_part) if h_part else 0
            s = s.split('h')[1]
        if 'm' in s:
            m_part = s.replace('m', '').strip()
            minutes = float(m_part) if m_part else 0
        return round(hours * 60 + minutes, 1)

    # 'H:MM:SS' or 'MM:SS'
    if ':' in s:
        parts = s.split(':')
        if len(parts) == 3:
            return round(int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60, 1)
        if len(parts) == 2:
            return round(int(parts[0]) + int(parts[1]) / 60, 1)

    # Plain number → assume minutes
    try:
        return round(float(s), 1)
    except ValueError:
        return None


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_day_items(rows):
    """
    Group set-level rows → exercises → workouts → days.
    """
    # Skip entirely blank rows
    rows = [r for r in rows if r.get("Date", "").strip() and r.get("Exercise", "").strip()]

    if not rows:
        return {}

    # Group by (date, workout_name, workout_duration) to identify unique workouts
    workout_sets = defaultdict(list)
    for row in rows:
        date_str = row["Date"].strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                date_str = datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        key = (date_str, row.get("Workout", "").strip(), row.get("Workout Duration", "").strip())
        workout_sets[key].append(row)

    # Group workouts by date
    day_workouts = defaultdict(list)
    for (date_str, workout_name, duration_raw), set_rows in workout_sets.items():
        # Group set rows by exercise
        exercise_sets = defaultdict(list)
        for row in set_rows:
            exercise_sets[row.get("Exercise", "").strip()].append(row)

        exercises = []
        for ex_name, ex_rows in exercise_sets.items():
            base_weight = safe_float(ex_rows[0].get("Exercise Base Weight (lbs)"))
            sets = []
            for i, row in enumerate(ex_rows, 1):
                s = {k: v for k, v in {
                    "set_index":          i,
                    "set_type":           row.get("Set Type", "").strip() or "normal",
                    "weight_lbs":         safe_float(row.get("Weight (lbs)")),
                    "reps":               safe_int(row.get("Reps")),
                    "rir":                safe_int(row.get("RIR")),
                    "set_duration_sec":   safe_int(row.get("Duration")),
                    "distance_yards":     safe_float(row.get("Distance short (Yd)")),
                    "distance_miles":     safe_float(row.get("Distance long (Mi)")),
                }.items() if v is not None}
                sets.append(s)

            ex_entry = {"exercise_name": ex_name, "sets": sets}
            if base_weight is not None:
                ex_entry["base_weight_lbs"] = base_weight
            exercises.append(ex_entry)

        workout = {
            "workout_name":        workout_name or "Workout",
            "workout_duration_min": parse_duration_min(duration_raw),
            "exercises":           exercises,
        }
        # Remove None duration
        workout = {k: v for k, v in workout.items() if v is not None}
        day_workouts[date_str].append(workout)

    # Build DynamoDB items
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_items = {}

    for date_str, workouts in day_workouts.items():
        total_sets   = 0
        total_volume = 0.0
        all_exercises = set()

        for w in workouts:
            for ex in w["exercises"]:
                all_exercises.add(ex["exercise_name"])
                for s in ex["sets"]:
                    total_sets += 1
                    total_volume += (s.get("weight_lbs") or 0) * (s.get("reps") or 0)

        day_items[date_str] = {
            "pk":               PK,
            "sk":               f"DATE#{date_str}",
            "date":             date_str,
            "source":           "macrofactor_workouts",
            "ingested_at":      ingested_at,
            "workouts_count":   len(workouts),
            "total_sets":       total_sets,
            "total_volume_lbs": round(total_volume, 1),
            "unique_exercises": len(all_exercises),
            "workouts":         workouts,
        }

    return day_items


def write_to_dynamodb(day_items, dry_run=False):
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table    = dynamodb.Table(DYNAMODB_TABLE)

    dates = sorted(day_items.keys())
    print(f"\nWriting {len(dates)} day items  ({dates[0]} → {dates[-1]})")

    for i, date_str in enumerate(dates, 1):
        item = floats_to_decimal(day_items[date_str])
        if dry_run:
            w = day_items[date_str]
            print(f"  [DRY RUN] {date_str}: {w['workouts_count']} workout(s), "
                  f"{w['total_sets']} sets, {w['total_volume_lbs']:,.0f} lbs volume")
        else:
            table.put_item(Item=item)
            if i % 20 == 0 or i == len(dates):
                print(f"  [{i}/{len(dates)}] written up to {date_str}")

    if not dry_run:
        print("Done.")


def archive_to_s3(csv_path, dry_run=False):
    if dry_run:
        return
    import os
    s3  = boto3.client("s3", region_name=REGION)
    now = datetime.now(timezone.utc)
    key = f"raw/macrofactor/workouts/{now.strftime('%Y/%m')}/{os.path.basename(csv_path)}"
    with open(csv_path, "rb") as f:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=f.read(), ContentType="text/csv")
    print(f"✓ Archived → s3://{S3_BUCKET}/{key}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 backfill_macrofactor_workouts.py <MacroFactor-*.csv> [--dry-run]")
        sys.exit(1)

    csv_path = sys.argv[1]
    dry_run  = "--dry-run" in sys.argv

    print(f"Loading {csv_path} ...")
    rows = load_csv(csv_path)
    print(f"  {len(rows)} rows")

    day_items = build_day_items(rows)
    print(f"  {len(day_items)} unique days parsed")

    if not day_items:
        print("  No workout data found (file may be empty — this is expected until you start logging).")
        return

    total_w = sum(d["workouts_count"]   for d in day_items.values())
    total_s = sum(d["total_sets"]       for d in day_items.values())
    total_v = sum(d["total_volume_lbs"] for d in day_items.values())
    print(f"  {total_w} workouts  |  {total_s} sets  |  {total_v:,.0f} lbs total volume")

    if not dry_run:
        archive_to_s3(csv_path)

    write_to_dynamodb(day_items, dry_run=dry_run)

    if dry_run:
        print("\n--dry-run complete. Re-run without --dry-run to write to DynamoDB.")


if __name__ == "__main__":
    main()
