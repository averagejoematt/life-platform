#!/usr/bin/env python3
"""
MacroFactor historical backfill — Granular Diary Export format.

HOW TO EXPORT FROM MACROFACTOR:
  More → Data Management → Data Export → Granular Export tab
  → select "Food diary" → choose "All time" → Export
  (The file will be named something like MacroFactor-YYYYMMDDHHMMSS.csv)

WHAT THIS SCRIPT DOES:
  Reads the granular CSV (one row per food item logged) and writes one
  DynamoDB item per day containing:
    • daily_totals  — sum of all 55 nutrient columns across the day
    • food_log      — list of individual food entries (name, time, serving, nutrients)

  This is a full-history idempotent upsert.  Re-running is safe.

DynamoDB schema:
  pk:   USER#matthew#SOURCE#macrofactor
  sk:   DATE#YYYY-MM-DD

Usage:
  python3 backfill_macrofactor.py path/to/MacroFactor-*.csv
  python3 backfill_macrofactor.py path/to/MacroFactor-*.csv --dry-run
  python3 backfill_macrofactor.py path/to/MacroFactor-*.csv --stats-only
"""

import csv
import sys
import json
import boto3
from collections import defaultdict, OrderedDict
from datetime import datetime, timezone
from decimal import Decimal

DYNAMODB_TABLE = "life-platform"
REGION         = "us-west-2"
S3_BUCKET      = "matthew-life-platform"
PK             = "USER#matthew#SOURCE#macrofactor"

# ── Exact column → canonical field name ──────────────────────────────────────
# Built against the confirmed export schema from MacroFactor-20260222092841.csv
# Format: "Exact CSV Header" -> ("field_name", "unit_hint")

NUTRIENT_COLUMNS = OrderedDict([
    # Core macros
    ("Calories (kcal)",          ("calories_kcal",           "kcal")),
    ("Protein (g)",              ("protein_g",               "g")),
    ("Carbs (g)",                ("carbs_g",                 "g")),
    ("Fat (g)",                  ("fat_g",                   "g")),
    ("Fiber (g)",                ("fiber_g",                 "g")),
    ("Alcohol (g)",              ("alcohol_g",               "g")),

    # Fat breakdown
    ("Saturated Fat (g)",        ("saturated_fat_g",         "g")),
    ("Monounsaturated Fat (g)",  ("monounsaturated_fat_g",   "g")),
    ("Polyunsaturated Fat (g)",  ("polyunsaturated_fat_g",   "g")),
    ("Trans Fat (g)",            ("trans_fat_g",             "g")),

    # Omega-3 / Omega-6
    ("Omega-3 (g)",              ("omega3_total_g",          "g")),
    ("Omega-3 ALA (g)",          ("omega3_ala_g",            "g")),
    ("Omega-3 DHA (g)",          ("omega3_dha_g",            "g")),
    ("Omega-3 EPA (g)",          ("omega3_epa_g",            "g")),
    ("Omega-6 (g)",              ("omega6_g",                "g")),

    # Carb breakdown
    ("Sugars (g)",               ("sugars_g",                "g")),
    ("Sugars Added (g)",         ("sugars_added_g",          "g")),
    ("Starch (g)",               ("starch_g",                "g")),

    # Key minerals
    ("Sodium (mg)",              ("sodium_mg",               "mg")),
    ("Potassium (mg)",           ("potassium_mg",            "mg")),
    ("Calcium (mg)",             ("calcium_mg",              "mg")),
    ("Magnesium (mg)",           ("magnesium_mg",            "mg")),
    ("Iron (mg)",                ("iron_mg",                 "mg")),
    ("Zinc (mg)",                ("zinc_mg",                 "mg")),
    ("Phosphorus (mg)",          ("phosphorus_mg",           "mg")),
    ("Selenium (mcg)",           ("selenium_mcg",            "mcg")),
    ("Manganese (mg)",           ("manganese_mg",            "mg")),
    ("Copper (mg)",              ("copper_mg",               "mg")),

    # Vitamins
    ("Vitamin A (mcg)",          ("vitamin_a_mcg",           "mcg")),
    ("Vitamin C (mg)",           ("vitamin_c_mg",            "mg")),
    ("Vitamin D (mcg)",          ("vitamin_d_mcg",           "mcg")),
    ("Vitamin E (mg)",           ("vitamin_e_mg",            "mg")),
    ("Vitamin K (mcg)",          ("vitamin_k_mcg",           "mcg")),
    ("B1, Thiamine (mg)",        ("b1_thiamine_mg",          "mg")),
    ("B2, Riboflavin (mg)",      ("b2_riboflavin_mg",        "mg")),
    ("B3, Niacin (mg)",          ("b3_niacin_mg",            "mg")),
    ("B5, Pantothenic Acid (mg)",("b5_pantothenic_mg",       "mg")),
    ("B6, Pyridoxine (mg)",      ("b6_pyridoxine_mg",        "mg")),
    ("B12, Cobalamin (mcg)",     ("b12_cobalamin_mcg",       "mcg")),
    ("Folate (mcg)",             ("folate_mcg",              "mcg")),

    # Performance / health extras
    ("Caffeine (mg)",            ("caffeine_mg",             "mg")),
    ("Cholesterol (mg)",         ("cholesterol_mg",          "mg")),
    ("Choline (mg)",             ("choline_mg",              "mg")),
    ("Water (g)",                ("water_g",                 "g")),

    # Amino acids (EAA profile)
    ("Histidine (g)",            ("aa_histidine_g",          "g")),
    ("Isoleucine (g)",           ("aa_isoleucine_g",         "g")),
    ("Leucine (g)",              ("aa_leucine_g",            "g")),
    ("Lysine (g)",               ("aa_lysine_g",             "g")),
    ("Methionine (g)",           ("aa_methionine_g",         "g")),
    ("Cysteine (g)",             ("aa_cysteine_g",           "g")),
    ("Phenylalanine (g)",        ("aa_phenylalanine_g",      "g")),
    ("Threonine (g)",            ("aa_threonine_g",          "g")),
    ("Tryptophan (g)",           ("aa_tryptophan_g",         "g")),
    ("Tyrosine (g)",             ("aa_tyrosine_g",           "g")),
    ("Valine (g)",               ("aa_valine_g",             "g")),
])

# Canonical field name set for quick lookup
NUTRIENT_FIELD_NAMES = {v[0] for v in NUTRIENT_COLUMNS.values()}

# Reverse map: CSV column header → canonical field name
COL_TO_FIELD = {col: field for col, (field, _) in NUTRIENT_COLUMNS.items()}


# ── Utilities ─────────────────────────────────────────────────────────────────

def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(item) for item in obj]
    return obj


def safe_float(val):
    """Return float or None for blank / non-numeric cells."""
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "-", "N/A", "n/a"):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def round2(v):
    return round(v, 2) if v is not None else None


# ── CSV parsing ───────────────────────────────────────────────────────────────

def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def parse_entry(row):
    """
    Parse a single food diary row into a structured dict.
    Returns None if the row has no date or no food name (blank rows).
    """
    date_str  = row.get("Date", "").strip()
    food_name = row.get("Food Name", "").strip()

    if not date_str or not food_name:
        return None

    # Normalise date → YYYY-MM-DD
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            date_str = datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    else:
        return None  # unparseable date

    nutrients = {}
    for col, field in COL_TO_FIELD.items():
        v = safe_float(row.get(col))
        if v is not None:
            nutrients[field] = v

    entry = {
        "food_name":    food_name,
        "time":         row.get("Time", "").strip() or None,
        "serving_size": row.get("Serving Size", "").strip() or None,
        "serving_qty":  safe_float(row.get("Serving Qty")),
        "serving_wt_g": safe_float(row.get("Serving Weight (g)")),
        **nutrients,
    }
    # Remove None values from entry
    entry = {k: v for k, v in entry.items() if v is not None}

    return date_str, entry


def build_day_items(rows):
    """
    Group food entries by date, sum nutrient totals, return day items.
    """
    # date_str → {"entries": [...], "totals": {field: sum}}
    days = defaultdict(lambda: {"entries": [], "totals": defaultdict(float)})

    skipped = 0
    for row in rows:
        result = parse_entry(row)
        if result is None:
            skipped += 1
            continue
        date_str, entry = result
        days[date_str]["entries"].append(entry)
        for field in NUTRIENT_FIELD_NAMES:
            v = entry.get(field)
            if v is not None:
                days[date_str]["totals"][field] += v

    if skipped:
        print(f"  Skipped {skipped} blank/unparseable rows")

    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_items = {}

    for date_str, data in days.items():
        totals = {k: round2(v) for k, v in data["totals"].items() if v != 0}

        # Sort food log by time if available
        food_log = sorted(
            data["entries"],
            key=lambda e: e.get("time") or "00:00"
        )

        item = {
            "pk":           PK,
            "sk":           f"DATE#{date_str}",
            "date":         date_str,
            "source":       "macrofactor",
            "ingested_at":  ingested_at,
            "entries_count": len(food_log),
            **{f"total_{k}" if not k.startswith("aa_") else k: v
               for k, v in totals.items()},
            "food_log":     food_log,
        }
        # Fix: totals use total_ prefix except amino acids which are rare enough
        # to keep under their own aa_ namespace. Let's actually be consistent:
        # rename back — strip the double-prefix issue above
        # Rebuild cleanly:
        totals_prefixed = {}
        for k, v in totals.items():
            totals_prefixed[f"total_{k}"] = v
        item = {
            "pk":            PK,
            "sk":            f"DATE#{date_str}",
            "date":          date_str,
            "source":        "macrofactor",
            "ingested_at":   ingested_at,
            "entries_count": len(food_log),
            "food_log":      food_log,
        }
        item.update(totals_prefixed)

        day_items[date_str] = item

    return day_items


# ── DynamoDB write ─────────────────────────────────────────────────────────────

def write_to_dynamodb(day_items, dry_run=False):
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table    = dynamodb.Table(DYNAMODB_TABLE)

    dates = sorted(day_items.keys())
    print(f"\nWriting {len(dates)} day items  ({dates[0]} → {dates[-1]})")

    for i, date_str in enumerate(dates, 1):
        item = floats_to_decimal(day_items[date_str])
        if dry_run:
            t = day_items[date_str]
            cal  = t.get("total_calories_kcal", "—")
            prot = t.get("total_protein_g",     "—")
            fat  = t.get("total_fat_g",         "—")
            carb = t.get("total_carbs_g",        "—")
            n    = t.get("entries_count",        0)
            print(f"  [DRY RUN] {date_str}: {n:2d} entries  "
                  f"cal={cal}  P={prot}g  C={carb}g  F={fat}g")
        else:
            table.put_item(Item=item)
            if i % 50 == 0 or i == len(dates):
                print(f"  [{i}/{len(dates)}] written up to {date_str}")

    if not dry_run:
        print("Done.")


# ── S3 archive ─────────────────────────────────────────────────────────────────

def archive_to_s3(csv_path, dry_run=False):
    if dry_run:
        return
    s3  = boto3.client("s3", region_name=REGION)
    now = datetime.now(timezone.utc)
    import os
    filename = os.path.basename(csv_path)
    key = f"raw/macrofactor/exports/{now.strftime('%Y/%m')}/{filename}"
    with open(csv_path, "rb") as f:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=f.read(), ContentType="text/csv")
    print(f"✓ Raw CSV archived → s3://{S3_BUCKET}/{key}")


# ── Stats summary ──────────────────────────────────────────────────────────────

def print_stats(day_items):
    days    = sorted(day_items.keys())
    n       = len(days)
    total_entries = sum(d["entries_count"] for d in day_items.values())

    def avg(field):
        vals = [d.get(field) for d in day_items.values() if d.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    print(f"\n{'─'*50}")
    print(f"  Days logged:       {n}  ({days[0]} → {days[-1]})")
    print(f"  Food entries:      {total_entries}  (avg {total_entries/n:.1f}/day)")
    print(f"\n  Daily averages:")
    print(f"    Calories:        {avg('total_calories_kcal')} kcal")
    print(f"    Protein:         {avg('total_protein_g')} g")
    print(f"    Carbs:           {avg('total_carbs_g')} g")
    print(f"    Fat:             {avg('total_fat_g')} g")
    print(f"    Fiber:           {avg('total_fiber_g')} g")
    print(f"    Sodium:          {avg('total_sodium_mg')} mg")
    print(f"    Omega-3 total:   {avg('total_omega3_total_g')} g")
    print(f"    Caffeine:        {avg('total_caffeine_mg')} mg")
    print(f"{'─'*50}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 backfill_macrofactor.py <MacroFactor-*.csv> [--dry-run] [--stats-only]")
        sys.exit(1)

    csv_path   = sys.argv[1]
    dry_run    = "--dry-run"    in sys.argv
    stats_only = "--stats-only" in sys.argv

    print(f"Loading {csv_path} ...")
    rows = load_csv(csv_path)
    print(f"  {len(rows)} rows loaded")

    print("Parsing diary entries ...")
    day_items = build_day_items(rows)
    print(f"  {len(day_items)} unique days parsed")

    if not day_items:
        print("  No food data found (file may be empty — this is expected until you start logging).")
        return

    print_stats(day_items)

    if stats_only:
        print("--stats-only: not writing to DynamoDB.")
        return

    if not dry_run:
        archive_to_s3(csv_path)

    write_to_dynamodb(day_items, dry_run=dry_run)

    if dry_run:
        print("\n--dry-run complete. Re-run without --dry-run to write to DynamoDB.")


if __name__ == "__main__":
    main()
