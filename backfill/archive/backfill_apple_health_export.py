#!/usr/bin/env python3
"""
backfill_apple_health_export.py — Full historical backfill from native Apple Health export.xml.

Streams the 1GB+ export.xml locally, applies SOT-aware tier filtering (matching the
health-auto-export-webhook Lambda), and merges into DynamoDB using update_item.

Key design decisions:
  - Tier 1 (Apple-exclusive): steps, energy, gait, flights, distance, audio → all readings
  - Tier 2 (cross-device): HR, RHR, HRV, respiratory, SpO2 → Apple Watch/iPhone only
  - Tier 3 (skip): nutrition (MacroFactor SOT), sleep (Eight Sleep SOT), body (Withings SOT)
  - Blood glucose: full CGM processing with daily aggregates + individual readings to S3
  - Uses update_item to MERGE with existing records, not overwrite
  - Streams XML with iterparse to handle 1GB+ files in bounded memory
  - Batches DynamoDB writes (one update per day at the end)

Usage:
    python3 backfill_apple_health_export.py [PATH_TO_EXPORT_XML] [--since YYYY-MM-DD]

    Default path: ~/Documents/Claude/apple_health_export 3/export.xml
    Default since: 2024-01-01 (last ~2 years)
"""

import xml.etree.ElementTree as ET
import json
import math
import os
import sys
import boto3
import gzip
from datetime import datetime, timezone
from decimal import Decimal
from collections import defaultdict

# ── Config ─────────────────────────────────────────────────────────────────────
S3_BUCKET      = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
REGION         = "us-west-2"
PK             = "USER#matthew#SOURCE#apple_health"

DEFAULT_EXPORT = os.path.expanduser("~/Documents/Claude/apple_health_export 3/export.xml")
DEFAULT_SINCE  = "2024-01-01"

# ── AWS clients ────────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(DYNAMODB_TABLE)
s3       = boto3.client("s3", region_name=REGION)


# ── Source Filtering (same as webhook Lambda) ──────────────────────────────────
APPLE_DEVICE_SUBSTRINGS = {"matt", "iphone", "apple watch", "watch", "apple"}


def is_apple_device(source_name):
    """Return True if the record source is an Apple device (or unknown)."""
    if not source_name:
        return True
    s = source_name.lower()
    return any(sub in s for sub in APPLE_DEVICE_SUBSTRINGS)


# ── HKQuantityType → field mapping with tiers ─────────────────────────────────
# tier 1 = Apple-exclusive (ingest all), tier 2 = filter to Apple devices
# agg: "sum" or "avg"

QUANTITY_MAP = {
    # ── Tier 1: Apple-exclusive ──
    "HKQuantityTypeIdentifierStepCount":                       {"field": "steps",                      "agg": "sum", "tier": 1},
    "HKQuantityTypeIdentifierActiveEnergyBurned":              {"field": "active_calories",            "agg": "sum", "tier": 1},
    "HKQuantityTypeIdentifierBasalEnergyBurned":               {"field": "basal_calories",             "agg": "sum", "tier": 1},
    "HKQuantityTypeIdentifierFlightsClimbed":                  {"field": "flights_climbed",            "agg": "sum", "tier": 1},
    "HKQuantityTypeIdentifierDistanceWalkingRunning":          {"field": "distance_walk_run_miles",    "agg": "sum", "tier": 1},
    "HKQuantityTypeIdentifierWalkingSpeed":                    {"field": "walking_speed_mph",          "agg": "avg", "tier": 1},
    "HKQuantityTypeIdentifierWalkingStepLength":               {"field": "walking_step_length_in",     "agg": "avg", "tier": 1},
    "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage":  {"field": "walking_double_support_pct", "agg": "avg", "tier": 1},
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage":      {"field": "walking_asymmetry_pct",      "agg": "avg", "tier": 1},
    "HKQuantityTypeIdentifierAppleWalkingSteadiness":          {"field": "walking_steadiness_pct",     "agg": "avg", "tier": 1},
    "HKQuantityTypeIdentifierEnvironmentalAudioExposure":      {"field": "env_audio_exposure_db",      "agg": "avg", "tier": 1},
    "HKQuantityTypeIdentifierHeadphoneAudioExposure":          {"field": "headphone_audio_exposure_db","agg": "avg", "tier": 1},

    # ── Tier 2: Cross-device (Apple only → _apple suffix) ──
    "HKQuantityTypeIdentifierHeartRate":                       {"field": "heart_rate_apple",           "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierRestingHeartRate":                {"field": "resting_heart_rate_apple",   "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":        {"field": "hrv_sdnn_apple",             "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierRespiratoryRate":                 {"field": "respiratory_rate_apple",     "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierOxygenSaturation":                {"field": "spo2_pct_apple",             "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierWalkingHeartRateAverage":         {"field": "walking_hr_avg_apple",       "agg": "avg", "tier": 2},

    # Blood glucose — special handling below
    "HKQuantityTypeIdentifierBloodGlucose":                    {"field": "_glucose", "agg": "special", "tier": 1},
}

# Tier 3: skip entirely (these HK types exist in the export but have dedicated SOT pipelines)
SKIP_TYPES = {
    # Sleep → Eight Sleep SOT
    "HKCategoryTypeIdentifierSleepAnalysis",
    # Body comp → Withings SOT
    "HKQuantityTypeIdentifierBodyMass",
    "HKQuantityTypeIdentifierBodyMassIndex",
    "HKQuantityTypeIdentifierBodyFatPercentage",
    "HKQuantityTypeIdentifierLeanBodyMass",
    "HKQuantityTypeIdentifierWaistCircumference",
    # Nutrition → MacroFactor SOT
    "HKQuantityTypeIdentifierDietaryEnergyConsumed",
    "HKQuantityTypeIdentifierDietaryProtein",
    "HKQuantityTypeIdentifierDietaryCarbohydrates",
    "HKQuantityTypeIdentifierDietaryFatTotal",
    "HKQuantityTypeIdentifierDietaryFatSaturated",
    "HKQuantityTypeIdentifierDietaryFatMonounsaturated",
    "HKQuantityTypeIdentifierDietaryFatPolyunsaturated",
    "HKQuantityTypeIdentifierDietarySugar",
    "HKQuantityTypeIdentifierDietaryFiber",
    "HKQuantityTypeIdentifierDietarySodium",
    "HKQuantityTypeIdentifierDietaryCholesterol",
    "HKQuantityTypeIdentifierDietaryWater",
    "HKQuantityTypeIdentifierDietaryPotassium",
    "HKQuantityTypeIdentifierDietaryCalcium",
    "HKQuantityTypeIdentifierDietaryIron",
    "HKQuantityTypeIdentifierDietaryMagnesium",
    "HKQuantityTypeIdentifierDietaryVitaminA",
    "HKQuantityTypeIdentifierDietaryVitaminC",
    "HKQuantityTypeIdentifierDietaryVitaminD",
    "HKQuantityTypeIdentifierDietaryVitaminE",
    "HKQuantityTypeIdentifierDietaryVitaminK",
    "HKQuantityTypeIdentifierDietaryVitaminB6",
    "HKQuantityTypeIdentifierDietaryVitaminB12",
    "HKQuantityTypeIdentifierDietaryZinc",
    "HKQuantityTypeIdentifierDietarySelenium",
    "HKQuantityTypeIdentifierDietaryCaffeine",
    "HKQuantityTypeIdentifierDietaryNiacin",
    "HKQuantityTypeIdentifierDietaryThiamin",
    "HKQuantityTypeIdentifierDietaryRiboflavin",
    "HKQuantityTypeIdentifierDietaryFolate",
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


# ── XML Streaming Parser ──────────────────────────────────────────────────────

def parse_export(filepath, since_date):
    """
    Stream-parse Apple Health export.xml, collecting daily aggregates.
    
    Returns:
        day_data: dict of date → dict of field → value (fully aggregated)
        day_glucose: dict of date → list of {time, value} readings
        stats: parsing statistics dict
    """
    # Accumulators
    day_sums = defaultdict(lambda: defaultdict(float))          # date → field → running sum
    day_avg_acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))  # date → field → [total, count]
    day_glucose = defaultdict(list)                             # date → [{time, value}]

    stats = {
        "total_records": 0,
        "skipped_old": 0,
        "skipped_sot": 0,
        "skipped_non_apple": 0,
        "skipped_unmapped": 0,
        "processed": 0,
        "glucose_readings": 0,
    }

    print(f"Parsing {filepath} (records since {since_date})...")
    print("This may take 2-5 minutes for a 1GB file...\n")

    context = ET.iterparse(filepath, events=("end",))
    last_progress = 0

    for _, elem in context:
        if elem.tag != "Record":
            elem.clear()
            continue

        stats["total_records"] += 1

        # Progress indicator every 500K records
        if stats["total_records"] % 500_000 == 0:
            print(f"  ... {stats['total_records']:,} records parsed")

        rtype = elem.get("type", "")
        start_date_raw = elem.get("startDate", "")
        date_str = start_date_raw[:10] if start_date_raw else None

        if not date_str or date_str < since_date:
            stats["skipped_old"] += 1
            elem.clear()
            continue

        # Tier 3: skip SOT-covered types
        if rtype in SKIP_TYPES:
            stats["skipped_sot"] += 1
            elem.clear()
            continue

        # Unknown type?
        if rtype not in QUANTITY_MAP:
            stats["skipped_unmapped"] += 1
            elem.clear()
            continue

        config = QUANTITY_MAP[rtype]
        tier = config["tier"]
        source_name = elem.get("sourceName", "")

        # Tier 2: filter to Apple devices only
        if tier == 2 and not is_apple_device(source_name):
            stats["skipped_non_apple"] += 1
            elem.clear()
            continue

        # Parse value
        try:
            value = float(elem.get("value", "0") or "0")
        except (ValueError, TypeError):
            elem.clear()
            continue

        # Blood glucose: special handling
        if config["agg"] == "special":
            day_glucose[date_str].append({
                "time": start_date_raw.strip(),
                "value": value,
            })
            stats["glucose_readings"] += 1
            elem.clear()
            continue

        # Regular metrics
        field = config["field"]
        if config["agg"] == "sum":
            day_sums[date_str][field] += value
        elif config["agg"] == "avg":
            day_avg_acc[date_str][field][0] += value
            day_avg_acc[date_str][field][1] += 1

        stats["processed"] += 1
        elem.clear()

    # ── Build final day records ──
    all_dates = set()
    all_dates.update(day_sums.keys())
    all_dates.update(day_avg_acc.keys())
    all_dates.update(day_glucose.keys())

    day_data = {}
    for date_str in sorted(all_dates):
        fields = {}

        # Sum fields
        for field, value in day_sums[date_str].items():
            fields[field] = round(value, 2)

        # Avg fields
        for field, (total, count) in day_avg_acc[date_str].items():
            if count > 0:
                fields[field] = round(total / count, 2)

        # Derived: total calories
        ac = fields.get("active_calories")
        bc = fields.get("basal_calories")
        if ac is not None and bc is not None:
            fields["total_calories_burned"] = round(ac + bc, 2)

        # Blood glucose aggregates
        if date_str in day_glucose:
            readings = day_glucose[date_str]
            values = [r["value"] for r in readings]
            n = len(values)
            avg = sum(values) / n
            std_dev = math.sqrt(sum((v - avg) ** 2 for v in values) / n) if n > 1 else 0
            in_range = sum(1 for v in values if 70 <= v <= 180)
            below_70 = sum(1 for v in values if v < 70)
            above_140 = sum(1 for v in values if v > 140)

            fields["blood_glucose_avg"] = round(avg, 1)
            fields["blood_glucose_min"] = round(min(values), 1)
            fields["blood_glucose_max"] = round(max(values), 1)
            fields["blood_glucose_std_dev"] = round(std_dev, 1)
            fields["blood_glucose_readings_count"] = n
            fields["blood_glucose_time_in_range_pct"] = round(in_range / n * 100, 1)
            fields["blood_glucose_time_below_70_pct"] = round(below_70 / n * 100, 1)
            fields["blood_glucose_time_above_140_pct"] = round(above_140 / n * 100, 1)
            fields["cgm_source"] = "dexcom_stelo" if n >= 20 else "manual"

        if fields:
            day_data[date_str] = fields

    return day_data, day_glucose, stats


# ── DynamoDB Writer ────────────────────────────────────────────────────────────

def merge_day_to_dynamo(date_str, fields):
    """Merge fields into DynamoDB using update_item (same as webhook Lambda)."""
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

    # Always update ingested_at
    set_parts.append("#upd = :upd")
    names["#upd"] = "backfill_ingested_at"
    values[":upd"] = datetime.now(timezone.utc).isoformat()

    # Ensure base fields
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


def save_glucose_to_s3(date_str, readings):
    """Save individual glucose readings to S3 (same path as webhook Lambda)."""
    s3_key = f"raw/cgm_readings/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    # Merge with existing
    existing = []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except Exception:
        pass

    existing_times = {r["time"] for r in existing}
    new_readings = [r for r in readings if r["time"] not in existing_times]

    if new_readings:
        merged = sorted(existing + new_readings, key=lambda r: r["time"] or "")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
    return len(new_readings)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXPORT
    since_date = DEFAULT_SINCE

    # Parse --since flag
    for i, arg in enumerate(sys.argv):
        if arg == "--since" and i + 1 < len(sys.argv):
            since_date = sys.argv[i + 1]

    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        print(f"Usage: python3 {sys.argv[0]} [PATH_TO_EXPORT_XML] [--since YYYY-MM-DD]")
        sys.exit(1)

    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"Apple Health Historical Backfill")
    print(f"================================")
    print(f"File: {filepath} ({file_size_mb:.0f} MB)")
    print(f"Since: {since_date}")
    print(f"Target: DynamoDB table={DYNAMODB_TABLE}, S3={S3_BUCKET}")
    print()

    # ── Parse ──
    day_data, day_glucose, stats = parse_export(filepath, since_date)

    print(f"\n{'─' * 50}")
    print(f"Parsing complete:")
    print(f"  Total records scanned:   {stats['total_records']:>10,}")
    print(f"  Processed (Tier 1+2):    {stats['processed']:>10,}")
    print(f"  Skipped (before {since_date}): {stats['skipped_old']:>10,}")
    print(f"  Skipped (SOT elsewhere): {stats['skipped_sot']:>10,}")
    print(f"  Skipped (non-Apple T2):  {stats['skipped_non_apple']:>10,}")
    print(f"  Skipped (unmapped type): {stats['skipped_unmapped']:>10,}")
    print(f"  Glucose readings:        {stats['glucose_readings']:>10,}")
    print(f"  Days with data:          {len(day_data):>10,}")
    print(f"{'─' * 50}\n")

    if not day_data:
        print("No data to write. Exiting.")
        return

    # Show sample day
    sample_date = sorted(day_data.keys())[-1]
    print(f"Sample day ({sample_date}): {json.dumps(day_data[sample_date], indent=2)}\n")

    # ── Confirm ──
    date_range = f"{min(day_data.keys())} → {max(day_data.keys())}"
    resp = input(f"Write {len(day_data)} days ({date_range}) to DynamoDB? [y/N] ")
    if resp.lower() != "y":
        print("Aborted.")
        return

    # ── Write to DynamoDB ──
    print(f"\nWriting {len(day_data)} days to DynamoDB...")
    written = 0
    errors = 0

    for date_str in sorted(day_data.keys()):
        try:
            merge_day_to_dynamo(date_str, day_data[date_str])
            written += 1
            if written % 50 == 0:
                print(f"  ... {written}/{len(day_data)} days written")
        except Exception as e:
            errors += 1
            print(f"  ERROR writing {date_str}: {e}")

    # ── Save glucose readings to S3 ──
    glucose_new = 0
    if day_glucose:
        print(f"\nSaving glucose readings to S3...")
        for date_str, readings in sorted(day_glucose.items()):
            try:
                n = save_glucose_to_s3(date_str, readings)
                glucose_new += n
            except Exception as e:
                print(f"  ERROR saving glucose {date_str}: {e}")

    # ── Summary ──
    print(f"\n{'═' * 50}")
    print(f"BACKFILL COMPLETE")
    print(f"  Days written to DynamoDB: {written}")
    print(f"  Errors: {errors}")
    print(f"  Date range: {date_range}")
    print(f"  Glucose readings saved to S3: {glucose_new}")
    if day_data:
        fields_seen = set()
        for fields in day_data.values():
            fields_seen.update(fields.keys())
        print(f"  Fields: {sorted(fields_seen)}")
    print(f"{'═' * 50}")


if __name__ == "__main__":
    main()
