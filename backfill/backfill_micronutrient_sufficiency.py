"""
backfill_micronutrient_sufficiency.py — Backfill micronutrient_sufficiency for all MacroFactor records.

Reads existing DynamoDB records, computes per-nutrient sufficiency from stored totals,
and updates records with micronutrient_sufficiency map + micronutrient_avg_pct.

Usage: python backfill_micronutrient_sufficiency.py [--dry-run]
"""

import sys
import boto3
from decimal import Decimal

DYNAMODB_TABLE = "life-platform"
PK = "USER#matthew#SOURCE#macrofactor"

MICRONUTRIENT_TARGETS = {
    "fiber_g":         {"target": 38,   "label": "Fiber"},
    "potassium_mg":    {"target": 3400, "label": "Potassium"},
    "magnesium_mg":    {"target": 420,  "label": "Magnesium"},
    "vitamin_d_mcg":   {"target": 100,  "label": "Vitamin D"},   # 4000 IU
    "omega3_total_g":  {"target": 3,    "label": "Omega-3"},
}

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(DYNAMODB_TABLE)

dry_run = "--dry-run" in sys.argv


def compute_sufficiency(item):
    """Compute micronutrient sufficiency from stored totals on a DynamoDB item."""
    sufficiency = {}
    pcts = []

    for nutrient_key, config in MICRONUTRIENT_TARGETS.items():
        total_key = f"total_{nutrient_key}"
        actual = item.get(total_key)
        if actual is None:
            continue
        actual = float(actual)
        target = config["target"]
        pct = min(round(actual / target * 100, 1), 100.0)
        sufficiency[nutrient_key] = {
            "actual": round(actual, 1),
            "target": target,
            "pct": pct,
        }
        pcts.append(pct)

    if not pcts:
        return None, None

    avg_pct = round(sum(pcts) / len(pcts), 1)
    return sufficiency, avg_pct


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(i) for i in obj]
    return obj


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


def update_record(sk, sufficiency, avg_pct):
    """Update a single record with micronutrient sufficiency fields."""
    table.update_item(
        Key={"pk": PK, "sk": sk},
        UpdateExpression="SET #suff = :suff, #avg = :avg",
        ExpressionAttributeNames={
            "#suff": "micronutrient_sufficiency",
            "#avg": "micronutrient_avg_pct",
        },
        ExpressionAttributeValues={
            ":suff": floats_to_decimal(sufficiency),
            ":avg": Decimal(str(avg_pct)),
        },
    )


def main():
    print("Scanning MacroFactor records...")
    items = scan_macrofactor_records()
    print(f"Found {len(items)} records\n")

    updated = 0
    skipped = 0
    avg_pcts = []
    nutrient_avgs = {k: [] for k in MICRONUTRIENT_TARGETS}

    for item in items:
        sk = item["sk"]
        date_str = sk.replace("DATE#", "")

        sufficiency, avg_pct = compute_sufficiency(item)

        if sufficiency is None:
            skipped += 1
            continue

        avg_pcts.append(avg_pct)
        for nutrient_key, data in sufficiency.items():
            nutrient_avgs[nutrient_key].append(data["pct"])

        if dry_run:
            details = ", ".join(f"{MICRONUTRIENT_TARGETS[k]['label']}={v['pct']}%" for k, v in sufficiency.items())
            print(f"  [DRY RUN] {date_str}: avg {avg_pct}% — {details}")
        else:
            update_record(sk, sufficiency, avg_pct)
            updated += 1
            if updated % 20 == 0:
                print(f"  ... {updated} days updated")

    print(f"\n✅ Backfill complete: {updated} days updated, {skipped} skipped")
    if dry_run:
        print(f"  (dry run — no DynamoDB writes)")

    if avg_pcts:
        overall_avg = sum(avg_pcts) / len(avg_pcts)
        print(f"\n📊 Summary ({len(avg_pcts)} days):")
        print(f"  Overall average sufficiency: {overall_avg:.1f}%")
        print(f"  Per-nutrient averages:")
        for key, config in MICRONUTRIENT_TARGETS.items():
            vals = nutrient_avgs[key]
            if vals:
                avg = sum(vals) / len(vals)
                at_100 = sum(1 for v in vals if v >= 100)
                print(f"    {config['label']:12s}: {avg:5.1f}% avg  |  {at_100}/{len(vals)} days at target")
            else:
                print(f"    {config['label']:12s}: no data")


if __name__ == "__main__":
    main()
