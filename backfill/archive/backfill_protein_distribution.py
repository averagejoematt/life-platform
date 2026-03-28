"""
backfill_protein_distribution.py — Backfill protein_distribution_score for all MacroFactor records.

Reads existing DynamoDB records with food_log, computes meal groupings (≥400 kcal threshold),
protein distribution score, then updates records with new fields.

Usage: python backfill_protein_distribution.py [--dry-run]
"""

import sys
import boto3
from decimal import Decimal

DYNAMODB_TABLE = "life-platform"
PK = "USER#matthew#SOURCE#macrofactor"

MEAL_CALORIE_THRESHOLD = 400
PROTEIN_MPS_THRESHOLD = 30

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(DYNAMODB_TABLE)

dry_run = "--dry-run" in sys.argv


def compute_protein_distribution(food_log):
    """
    Group food_log entries into meals by 30-min time proximity.
    Exclude snacks (<400 kcal) from scoring.
    Returns (score_pct, meals_above_30g, total_meals, total_snacks).
    """
    if not food_log:
        return None, 0, 0, 0

    timed_entries = []
    for entry in food_log:
        time_str = entry.get("time")
        protein = entry.get("protein_g")
        calories = entry.get("calories_kcal")
        if not time_str or protein is None:
            continue
        try:
            parts = str(time_str).split(":")
            minutes_from_midnight = int(parts[0]) * 60 + int(parts[1])
            timed_entries.append((minutes_from_midnight, float(protein), float(calories or 0)))
        except (ValueError, IndexError):
            continue

    if not timed_entries:
        return None, 0, 0, 0

    timed_entries.sort(key=lambda x: x[0])

    # Group into eating occasions: entries within 30 min = same occasion
    occasions = []
    cur_start = timed_entries[0][0]
    cur_protein = timed_entries[0][1]
    cur_calories = timed_entries[0][2]

    for i in range(1, len(timed_entries)):
        time_min, protein, calories = timed_entries[i]
        if time_min - cur_start <= 30:
            cur_protein += protein
            cur_calories += calories
        else:
            occasions.append((cur_protein, cur_calories))
            cur_start = time_min
            cur_protein = protein
            cur_calories = calories

    occasions.append((cur_protein, cur_calories))

    meals = [(p, c) for p, c in occasions if c >= MEAL_CALORIE_THRESHOLD]
    total_snacks = len(occasions) - len(meals)
    total_meals = len(meals)

    if total_meals == 0:
        return 0.0, 0, 0, total_snacks

    above_30g = sum(1 for p, c in meals if p >= PROTEIN_MPS_THRESHOLD)
    score = round(above_30g / total_meals * 100, 1)

    return score, above_30g, total_meals, total_snacks


def scan_macrofactor_records():
    """Query all macrofactor records."""
    items = []
    kwargs = {
        "KeyConditionExpression": boto3.dynamodb.conditions.Key("pk").eq(PK),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def update_record(sk, score, above_30g, total_meals, total_snacks):
    """Update a single record with protein distribution fields."""
    table.update_item(
        Key={"pk": PK, "sk": sk},
        UpdateExpression="SET #pds = :pds, #above = :above, #total = :total, #snacks = :snacks",
        ExpressionAttributeNames={
            "#pds": "protein_distribution_score",
            "#above": "meals_above_30g_protein",
            "#total": "total_meals",
            "#snacks": "total_snacks",
        },
        ExpressionAttributeValues={
            ":pds": Decimal(str(score)),
            ":above": above_30g,
            ":total": total_meals,
            ":snacks": total_snacks,
        },
    )


def main():
    print("Scanning MacroFactor records...")
    items = scan_macrofactor_records()
    print(f"Found {len(items)} records")
    print(f"Meal threshold: ≥{MEAL_CALORIE_THRESHOLD} kcal | Protein target: ≥{PROTEIN_MPS_THRESHOLD}g\n")

    updated = 0
    skipped = 0
    scores = []
    snack_counts = []

    for item in items:
        sk = item["sk"]
        date_str = sk.replace("DATE#", "")
        food_log = item.get("food_log", [])

        if not food_log:
            skipped += 1
            continue

        # DynamoDB returns Decimal — convert for float math
        for entry in food_log:
            for key in ("protein_g", "calories_kcal"):
                if key in entry:
                    entry[key] = float(entry[key])

        score, above_30g, total_meals, total_snacks = compute_protein_distribution(food_log)

        if score is None:
            skipped += 1
            continue

        scores.append(score)
        snack_counts.append(total_snacks)

        if dry_run:
            label = f"{above_30g}/{total_meals} meals ≥30g"
            if total_snacks:
                label += f", {total_snacks} snack(s) excluded"
            print(f"  [DRY RUN] {date_str}: {score}% ({label})")
        else:
            update_record(sk, score, above_30g, total_meals, total_snacks)
            updated += 1
            if updated % 20 == 0:
                print(f"  ... {updated} days updated")

    print(f"\n✅ Backfill complete: {updated} days updated, {skipped} skipped")
    if dry_run:
        print(f"  (dry run — no DynamoDB writes)")

    if scores:
        avg = sum(scores) / len(scores)
        perfect = sum(1 for s in scores if s == 100)
        zero = sum(1 for s in scores if s == 0)
        snack_days = sum(1 for s in snack_counts if s > 0)
        print(f"\n📊 Summary ({len(scores)} days):")
        print(f"  Average protein distribution score: {avg:.1f}%")
        print(f"  Days with 100% distribution: {perfect}/{len(scores)}")
        print(f"  Days with 0% (no meal ≥30g): {zero}/{len(scores)}")
        print(f"  Days with snacks excluded: {snack_days}/{len(scores)}")


if __name__ == "__main__":
    main()
