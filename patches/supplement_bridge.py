"""
supplement_bridge.py — Habitify → Supplements partition bridge.

Reads Habitify daily records, maps checked supplement habits to structured
supplement entries, and writes them to USER#matthew#SOURCE#supplements.

Can run as:
  1. Backfill: process all historical Habitify data
  2. Daily bridge: process a single date (for integration into daily pipeline)

Usage:
  python supplement_bridge.py                    # backfill all
  python supplement_bridge.py --date 2026-03-02  # single day
  python supplement_bridge.py --dry-run          # preview without writing
"""

import boto3
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from collections import defaultdict

# ── Config ──
REGION = "us-west-2"
TABLE_NAME = "life-platform"
USER_ID = "matthew"
HABITIFY_PK = f"USER#{USER_ID}#SOURCE#habitify"
SUPPLEMENTS_PK = f"USER#{USER_ID}#SOURCE#supplements"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

# ── Supplement Mapping ──
# Maps Habitify habit names → structured supplement metadata.
# Dosages are defaults — Matthew will update specific values later.
# Timing: morning (fasted), afternoon (with food), before_bed (sleep stack)

SUPPLEMENT_MAP = {
    # ── Morning batch (fasted) ──
    "Probiotics": {
        "dose": 1, "unit": "capsule", "timing": "morning",
        "category": "supplement",
        "notes": "Take on empty stomach for gut colonization"
    },
    "L Glutamine": {
        "dose": 5, "unit": "g", "timing": "morning",
        "category": "supplement",
        "notes": "Better absorbed fasted; gut lining + recovery"
    },
    "Collagen": {
        "dose": 10, "unit": "g", "timing": "morning",
        "category": "supplement",
        "notes": "Peptides; take away from other proteins for absorption"
    },
    "Electrolytes": {
        "dose": 1, "unit": "packet", "timing": "morning",
        "category": "supplement",
        "notes": "Morning hydration; sodium + potassium + magnesium"
    },

    # ── Afternoon batch (with food) ──
    "Multivitamin": {
        "dose": 1, "unit": "capsule", "timing": "with_meal",
        "category": "vitamin",
        "notes": "Take with fat-containing meal for fat-soluble vitamin absorption"
    },
    "Vitamin D": {
        "dose": 5000, "unit": "IU", "timing": "with_meal",
        "category": "vitamin",
        "notes": "Fat-soluble; take with meal. Huberman: pair with K2"
    },
    "Omega 3": {
        "dose": 2000, "unit": "mg", "timing": "with_meal",
        "category": "supplement",
        "notes": "EPA/DHA; take with fatty meal to reduce fishy burps"
    },
    "Zinc Picolinate": {
        "dose": 30, "unit": "mg", "timing": "with_meal",
        "category": "mineral",
        "notes": "Take with food to avoid nausea; immune + testosterone"
    },
    "Basic B Complex": {
        "dose": 1, "unit": "capsule", "timing": "with_meal",
        "category": "vitamin",
        "notes": "Energy metabolism; take earlier in day (can be stimulating)"
    },
    "Creatine": {
        "dose": 5, "unit": "g", "timing": "with_meal",
        "category": "supplement",
        "notes": "Monohydrate; timing doesn't matter, consistency does"
    },
    "Lions Mane": {
        "dose": 1000, "unit": "mg", "timing": "with_meal",
        "category": "supplement",
        "notes": "NGF support; cognitive function. Huberman: real fruiting body"
    },
    "Green Tea Phytosome": {
        "dose": 500, "unit": "mg", "timing": "with_meal",
        "category": "supplement",
        "notes": "EGCG; enhanced bioavailability phytosome form"
    },
    "NAC": {
        "dose": 600, "unit": "mg", "timing": "with_meal",
        "category": "supplement",
        "notes": "N-Acetyl Cysteine; glutathione precursor, liver support"
    },
    "Cordyceps": {
        "dose": 1000, "unit": "mg", "timing": "with_meal",
        "category": "supplement",
        "notes": "Energy + VO2max support; take earlier in day"
    },
    "Inositol": {
        "dose": 2000, "unit": "mg", "timing": "with_meal",
        "category": "supplement",
        "notes": "Myo-inositol; mood, insulin sensitivity, sleep quality"
    },
    "Protein Supplement": {
        "dose": 25, "unit": "g", "timing": "with_meal",
        "category": "supplement",
        "notes": "Whey/plant protein; hit daily protein target"
    },

    # ── Evening batch (before bed — sleep stack) ──
    "Glycine": {
        "dose": 3, "unit": "g", "timing": "before_bed",
        "category": "supplement",
        "notes": "Huberman sleep stack; lowers core body temp, enhances deep sleep"
    },
    "L-Threonate": {
        "dose": 2000, "unit": "mg", "timing": "before_bed",
        "category": "supplement",
        "notes": "Magnesium L-Threonate; crosses BBB, sleep + cognitive. ~144mg elemental Mg"
    },
    "Apigenin": {
        "dose": 50, "unit": "mg", "timing": "before_bed",
        "category": "supplement",
        "notes": "Huberman sleep stack; mild sedative, anxiolytic"
    },
    "Theanine": {
        "dose": 200, "unit": "mg", "timing": "before_bed",
        "category": "supplement",
        "notes": "Huberman sleep stack; calming without sedation. Skip if vivid dreams are an issue"
    },
    "Reishi": {
        "dose": 1000, "unit": "mg", "timing": "before_bed",
        "category": "supplement",
        "notes": "Calming adaptogen; immune modulation, sleep support"
    },
}


def bridge_day(date_str, dry_run=False):
    """
    Read Habitify record for a date, map supplement habits to structured entries,
    and write to the supplements partition.

    Returns dict with results.
    """
    # Read Habitify record
    resp = table.get_item(Key={"pk": HABITIFY_PK, "sk": f"DATE#{date_str}"})
    item = resp.get("Item")
    if not item:
        return {"date": date_str, "status": "no_habitify_data"}

    habits = item.get("habits", {})
    if not habits:
        return {"date": date_str, "status": "no_habits"}

    # Find checked supplement habits
    entries = []
    for habit_name, completed in habits.items():
        # DynamoDB stores as Decimal
        if int(completed) != 1:
            continue
        if habit_name not in SUPPLEMENT_MAP:
            continue

        meta = SUPPLEMENT_MAP[habit_name]
        entry = {
            "name": habit_name,
            "dose": Decimal(str(meta["dose"])),
            "unit": meta["unit"],
            "timing": meta["timing"],
            "category": meta["category"],
            "notes": meta["notes"],
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "source": "habitify_bridge",
        }
        entries.append(entry)

    if not entries:
        return {"date": date_str, "status": "no_supplements_checked", "habits_checked": sum(1 for v in habits.values() if int(v) == 1)}

    if dry_run:
        return {
            "date": date_str,
            "status": "dry_run",
            "supplements": [f"{e['name']} ({e['dose']}{e['unit']}, {e['timing']})" for e in entries],
            "count": len(entries),
        }

    # Write to supplements partition (overwrite for idempotency)
    table.put_item(Item={
        "pk": SUPPLEMENTS_PK,
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "supplements",
        "supplements": entries,
        "bridge_source": "habitify",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "date": date_str,
        "status": "written",
        "count": len(entries),
        "supplements": [e["name"] for e in entries],
    }


def backfill_all(dry_run=False):
    """Process all historical Habitify records."""
    from boto3.dynamodb.conditions import Key

    # Query all Habitify records
    items = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(HABITIFY_PK),
        "ProjectionExpression": "sk",
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    dates = sorted([i["sk"].replace("DATE#", "") for i in items])
    print(f"Found {len(dates)} Habitify records to process")

    results = {"written": 0, "no_supplements": 0, "errors": 0}
    for date_str in dates:
        try:
            result = bridge_day(date_str, dry_run=dry_run)
            status = result.get("status")
            if status == "written" or status == "dry_run":
                results["written"] += 1
                print(f"  {date_str}: {result.get('count', 0)} supplements — {', '.join(result.get('supplements', []))}")
            elif status in ("no_supplements_checked", "no_habits"):
                results["no_supplements"] += 1
            else:
                results["no_supplements"] += 1
        except Exception as e:
            results["errors"] += 1
            print(f"  {date_str}: ERROR — {e}")

    print(f"\nDone: {results['written']} days written, {results['no_supplements']} days with no supplements, {results['errors']} errors")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Habitify → Supplements bridge")
    parser.add_argument("--date", help="Single date to process (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if args.date:
        result = bridge_day(args.date, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
    else:
        backfill_all(dry_run=args.dry_run)
