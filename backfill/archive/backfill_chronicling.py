#!/usr/bin/env python3
"""
Chronicling habit tracker ingest — events export format.

HOW TO EXPORT FROM CHRONICLING:
  Settings → Export Data → Events CSV
  Drop into: ~/Documents/Claude/habits_drop/
  (Export whenever — script is idempotent and incremental by default)

WHAT THIS SCRIPT DOES:
  Reads the Chronicling events CSV (one row per habit completion) and writes
  one DynamoDB item per day containing:
    • habits         — {habit_name: count_logged_that_day}
    • by_group       — {group_name: {completed, possible}} using category metadata
    • completion_pct — fraction of known habits completed (0.0–1.0)
    • total_completed / total_possible

  INCREMENTAL: By default, skips any dates already in DynamoDB (only writes
  dates newer than the most recent stored date). Use --full to force a full
  upsert of all dates.

  This is safe to re-run at any time.

DynamoDB schema:
  pk: USER#matthew#SOURCE#chronicling
  sk: DATE#YYYY-MM-DD

Habit → Group mapping is embedded below (from categories export, Nov 2025).
Update HABIT_GROUPS if you add/change habits in Chronicling.

Usage:
  python3 backfill_chronicling.py events.csv
  python3 backfill_chronicling.py events.csv --full       # upsert all dates
  python3 backfill_chronicling.py events.csv --dry-run
  python3 backfill_chronicling.py events.csv --stats-only
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeSerializer

TABLE_NAME = "life-platform"
PK = "USER#matthew#SOURCE#chronicling"

# ── Habit → Group mapping (from categories export) ───────────────────────────
# Update this dict if habits are added/renamed in Chronicling.
HABIT_GROUPS = {
    # Data
    "Food Journal": "Data", "Weigh In": "Data", "Whoop Journal": "Data",
    # Discipline
    "Calorie Goal": "Discipline", "Cold Shower": "Discipline",
    "No Alcohol": "Discipline", "No Marijuana": "Discipline",
    "No Mindless Scrolling": "Discipline", "No Phone 30 Mins Before Bed": "Discipline",
    "No Porn": "Discipline", "Out of Bed Before 5am": "Discipline",
    # Growth
    "Deep Work Block": "Growth", "Morning Journal": "Growth",
    "Read Book": "Growth", "Read News": "Growth", "Write": "Growth",
    # Hygiene
    "Body Skincare": "Hygiene", "Evening Skincare": "Hygiene",
    "Floss": "Hygiene", "Morning Skincare": "Hygiene", "Mouthwash": "Hygiene",
    # Nutrition
    "Collagen": "Nutrition", "Day Supplements": "Nutrition",
    "Electrolytes": "Nutrition", "Hydrate 3L": "Nutrition",
    "Intermittent Fast 16:8": "Nutrition", "No Fried Food": "Nutrition",
    "No Solo Takeout": "Nutrition", "No Sweets": "Nutrition",
    "Probiotics": "Nutrition", "Protein Supplement": "Nutrition",
    "L Glutamine": "Nutrition",
    # Performance
    "Creatine": "Performance", "Primary Exercise": "Performance",
    "Secondary Exercise": "Performance", "Skill Development": "Performance",
    # Recovery
    "Normatec Legs": "Recovery", "Red Light Therapy": "Recovery",
    "Sauna": "Recovery", "Theragun": "Recovery",
    # Wellbeing
    "Daytime Glasses": "Wellbeing", "Evening Breathwork": "Wellbeing",
    "Evening Journal": "Wellbeing", "Evening Supplements": "Wellbeing",
    "Meditate": "Wellbeing", "Mobility": "Wellbeing",
    "Morning Breathwork": "Wellbeing", "Morning Sunlight": "Wellbeing",
    "Nighttime Glasses": "Wellbeing", "Social Gratitude Touchpoint": "Wellbeing",
    "Walk 5k": "Wellbeing",
}

# All known habits per group (used to compute possible count per day)
GROUP_POSSIBLE = defaultdict(set)
for habit, group in HABIT_GROUPS.items():
    GROUP_POSSIBLE[group].add(habit)


def get_last_stored_date(table) -> str | None:
    """Query DynamoDB for the most recent date stored for this source."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk > :min_sk",
        ExpressionAttributeValues={":pk": PK, ":min_sk": "DATE#0000"},
        ScanIndexForward=False,  # newest first
        Limit=1,
        ProjectionExpression="sk",
    )
    items = resp.get("Items", [])
    if items:
        return items[0]["sk"].replace("DATE#", "")
    return None


def load_events(path: str) -> dict[str, dict]:
    """Parse events CSV → {date_str: {habits: {name: count}, raw_events: [...]}}"""
    by_date = defaultdict(lambda: {"habits": defaultdict(int), "notes": []})

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt_str = row["DateTime"].strip()
            if not dt_str:
                continue
            # Parse UTC datetime, convert to local date (Pacific)
            # LocalTime col already has the local date — use it as source of truth
            local_time = row.get("LocalTime", "").strip()
            try:
                # LocalTime format: "Sun, 9 Nov 2025, 08:54"
                # Extract date portion
                parts = local_time.split(",")
                # parts: ["Sun", " 9 Nov 2025", " 08:54"]
                date_str = datetime.strptime(parts[1].strip() + "," + parts[2].strip(),
                                             "%d %b %Y,%H:%M").strftime("%Y-%m-%d")
            except (IndexError, ValueError):
                # Fallback to UTC date from DateTime column
                date_str = dt_str[:10]

            category = row.get("Category", "").strip()
            count = int(row.get("Count", "1") or 1)
            notes = row.get("Notes", "").strip()

            by_date[date_str]["habits"][category] += count
            if notes:
                by_date[date_str]["notes"].append(f"{category}: {notes}")

    return by_date


def build_dynamo_item(date_str: str, day_data: dict) -> dict:
    """Build a DynamoDB item for a single day."""
    habits = dict(day_data["habits"])
    notes = day_data["notes"]

    # Compute group rollups
    by_group = {}
    for group, possible_habits in GROUP_POSSIBLE.items():
        completed_habits = [h for h in possible_habits if habits.get(h, 0) > 0]
        by_group[group] = {
            "completed": len(completed_habits),
            "possible": len(possible_habits),
            "pct": Decimal(str(round(len(completed_habits) / len(possible_habits), 4)))
                   if possible_habits else Decimal("0"),
            "habits_done": completed_habits,
        }

    total_possible = len(HABIT_GROUPS)
    total_completed = sum(1 for h in HABIT_GROUPS if habits.get(h, 0) > 0)
    # Count habits seen in events that aren't in our map (unknown = uncategorised)
    unknown = [h for h in habits if h not in HABIT_GROUPS]

    item = {
        "pk": PK,
        "sk": f"DATE#{date_str}",
        "source": "chronicling",
        "date": date_str,
        "habits": {k: Decimal(str(v)) for k, v in habits.items()},
        "by_group": by_group,
        "total_completed": total_completed,
        "total_possible": total_possible,
        "completion_pct": Decimal(str(round(total_completed / total_possible, 4)))
                          if total_possible else Decimal("0"),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if notes:
        item["notes"] = notes
    if unknown:
        item["uncategorised_habits"] = unknown

    return item


def main():
    dry_run = "--dry-run" in sys.argv
    stats_only = "--stats-only" in sys.argv
    full_upsert = "--full" in sys.argv
    csv_args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not csv_args:
        print("Usage: python3 backfill_chronicling.py <events.csv> [--full] [--dry-run] [--stats-only]")
        sys.exit(1)

    csv_path = csv_args[0]
    print(f"Loading: {csv_path}")
    by_date = load_events(csv_path)

    all_dates = sorted(by_date.keys())
    print(f"Parsed {len(by_date)} days: {all_dates[0]} → {all_dates[-1]}")

    if stats_only:
        for d in all_dates[-5:]:
            day = by_date[d]
            total = sum(1 for h in HABIT_GROUPS if day["habits"].get(h, 0) > 0)
            pct = total / len(HABIT_GROUPS)
            print(f"  {d}: {total}/{len(HABIT_GROUPS)} habits ({pct:.0%}) — {list(day['habits'].keys())[:5]}...")
        return

    # Determine which dates to write
    dates_to_write = all_dates

    if not full_upsert and not dry_run:
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table = dynamodb.Table(TABLE_NAME)
        last_date = get_last_stored_date(table)
        if last_date:
            dates_to_write = [d for d in all_dates if d > last_date]
            skipped = len(all_dates) - len(dates_to_write)
            print(f"Incremental mode: last stored date = {last_date}")
            print(f"  Skipping {skipped} already-stored days, writing {len(dates_to_write)} new days")
        else:
            print("No existing data — writing all days")
    elif dry_run:
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table = dynamodb.Table(TABLE_NAME)
        last_date = get_last_stored_date(table)
        if last_date and not full_upsert:
            dates_to_write = [d for d in all_dates if d > last_date]
        print(f"[DRY RUN] Would write {len(dates_to_write)} days:")
        for d in dates_to_write:
            day = by_date[d]
            total = sum(1 for h in HABIT_GROUPS if day["habits"].get(h, 0) > 0)
            print(f"  {d}: {total}/{len(HABIT_GROUPS)} habits ({total/len(HABIT_GROUPS):.0%})")
        return
    else:
        # --full
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table = dynamodb.Table(TABLE_NAME)
        print(f"Full upsert mode: writing all {len(dates_to_write)} days")

    if not dates_to_write:
        print("Nothing to write — all dates already stored. Use --full to force re-upsert.")
        return

    # Write to DynamoDB
    success = 0
    errors = 0
    with table.batch_writer() as batch:
        for date_str in dates_to_write:
            try:
                item = build_dynamo_item(date_str, by_date[date_str])
                batch.put_item(Item=item)
                success += 1
            except Exception as e:
                print(f"  ERROR on {date_str}: {e}")
                errors += 1

    print(f"\n✓ Done: {success} days written, {errors} errors")


if __name__ == "__main__":
    main()
