#!/usr/bin/env python3
"""
Apple Health export.xml backfill processor.
Parses the full export, groups by date, uploads to S3 + DynamoDB.
Run: python3 backfill_apple_health.py

Processes ~2.6M records. Takes 5-15 minutes depending on machine.
"""

import xml.etree.ElementTree as ET
import json
import boto3
import gzip
from datetime import datetime, timezone
from decimal import Decimal
from collections import defaultdict
import time

EXPORT_PATH = "/Users/matthewwalker/Documents/Claude/apple_health_export/export.xml"
S3_BUCKET = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
REGION = "us-west-2"

s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

# ── Record types to capture, with short field names ──────────────────────────
QUANTITY_RECORDS = {
    # Activity
    "HKQuantityTypeIdentifierStepCount":                    "steps",
    "HKQuantityTypeIdentifierActiveEnergyBurned":           "active_calories",
    "HKQuantityTypeIdentifierBasalEnergyBurned":            "basal_calories",
    "HKQuantityTypeIdentifierFlightsClimbed":               "flights_climbed",
    "HKQuantityTypeIdentifierDistanceWalkingRunning":        "distance_walk_run_miles",
    "HKQuantityTypeIdentifierDistanceCycling":              "distance_cycling_miles",
    # Heart
    "HKQuantityTypeIdentifierHeartRate":                    "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate":             "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":     "hrv_sdnn",
    "HKQuantityTypeIdentifierWalkingHeartRateAverage":      "walking_heart_rate_avg",
    # Body
    "HKQuantityTypeIdentifierBodyMass":                     "weight_lbs",
    "HKQuantityTypeIdentifierBodyMassIndex":                "bmi",
    "HKQuantityTypeIdentifierBodyFatPercentage":            "body_fat_pct",
    "HKQuantityTypeIdentifierLeanBodyMass":                 "lean_mass_lbs",
    "HKQuantityTypeIdentifierWaistCircumference":           "waist_inches",
    # Respiratory / O2
    "HKQuantityTypeIdentifierOxygenSaturation":             "spo2_pct",
    "HKQuantityTypeIdentifierRespiratoryRate":              "respiratory_rate",
    "HKQuantityTypeIdentifierVO2Max":                       "vo2max",
    # Blood
    "HKQuantityTypeIdentifierBloodGlucose":                 "blood_glucose_mgdl",
    "HKQuantityTypeIdentifierBloodPressureSystolic":        "bp_systolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic":       "bp_diastolic",
    # Walking gait
    "HKQuantityTypeIdentifierWalkingSpeed":                 "walking_speed_mph",
    "HKQuantityTypeIdentifierWalkingStepLength":            "walking_step_length_in",
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage":   "walking_asymmetry_pct",
    "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage": "walking_double_support_pct",
    "HKQuantityTypeIdentifierAppleWalkingSteadiness":       "walking_steadiness_pct",
    # Nutrition
    "HKQuantityTypeIdentifierDietaryEnergyConsumed":        "nutrition_calories",
    "HKQuantityTypeIdentifierDietaryProtein":               "nutrition_protein_g",
    "HKQuantityTypeIdentifierDietaryCarbohydrates":         "nutrition_carbs_g",
    "HKQuantityTypeIdentifierDietaryFatTotal":              "nutrition_fat_g",
    "HKQuantityTypeIdentifierDietaryFatSaturated":          "nutrition_fat_saturated_g",
    "HKQuantityTypeIdentifierDietaryFatMonounsaturated":    "nutrition_fat_mono_g",
    "HKQuantityTypeIdentifierDietaryFatPolyunsaturated":    "nutrition_fat_poly_g",
    "HKQuantityTypeIdentifierDietarySugar":                 "nutrition_sugar_g",
    "HKQuantityTypeIdentifierDietaryFiber":                 "nutrition_fiber_g",
    "HKQuantityTypeIdentifierDietarySodium":                "nutrition_sodium_mg",
    "HKQuantityTypeIdentifierDietaryCholesterol":           "nutrition_cholesterol_mg",
    "HKQuantityTypeIdentifierDietaryWater":                 "nutrition_water_ml",
    "HKQuantityTypeIdentifierDietaryPotassium":             "nutrition_potassium_mg",
    "HKQuantityTypeIdentifierDietaryCalcium":               "nutrition_calcium_mg",
    "HKQuantityTypeIdentifierDietaryIron":                  "nutrition_iron_mg",
    "HKQuantityTypeIdentifierDietaryMagnesium":             "nutrition_magnesium_mg",
    "HKQuantityTypeIdentifierDietaryVitaminA":              "nutrition_vitamin_a_mcg",
    "HKQuantityTypeIdentifierDietaryVitaminC":              "nutrition_vitamin_c_mg",
    "HKQuantityTypeIdentifierDietaryVitaminD":              "nutrition_vitamin_d_mcg",
    "HKQuantityTypeIdentifierDietaryVitaminE":              "nutrition_vitamin_e_mg",
    "HKQuantityTypeIdentifierDietaryVitaminK":              "nutrition_vitamin_k_mcg",
    "HKQuantityTypeIdentifierDietaryVitaminB6":             "nutrition_vitamin_b6_mg",
    "HKQuantityTypeIdentifierDietaryVitaminB12":            "nutrition_vitamin_b12_mcg",
    "HKQuantityTypeIdentifierDietaryZinc":                  "nutrition_zinc_mg",
    "HKQuantityTypeIdentifierDietarySelenium":              "nutrition_selenium_mcg",
    "HKQuantityTypeIdentifierDietaryCaffeine":              "nutrition_caffeine_mg",
    "HKQuantityTypeIdentifierDietaryNiacin":                "nutrition_niacin_mg",
    "HKQuantityTypeIdentifierDietaryThiamin":               "nutrition_thiamin_mg",
    "HKQuantityTypeIdentifierDietaryRiboflavin":            "nutrition_riboflavin_mg",
    "HKQuantityTypeIdentifierDietaryFolate":                "nutrition_folate_mcg",
}

# Types to SUM per day (additive)
SUM_TYPES = {
    "steps", "active_calories", "basal_calories", "flights_climbed",
    "distance_walk_run_miles", "distance_cycling_miles",
    "nutrition_calories", "nutrition_protein_g", "nutrition_carbs_g",
    "nutrition_fat_g", "nutrition_fat_saturated_g", "nutrition_fat_mono_g",
    "nutrition_fat_poly_g", "nutrition_sugar_g", "nutrition_fiber_g",
    "nutrition_sodium_mg", "nutrition_cholesterol_mg", "nutrition_water_ml",
    "nutrition_potassium_mg", "nutrition_calcium_mg", "nutrition_iron_mg",
    "nutrition_magnesium_mg", "nutrition_vitamin_a_mcg", "nutrition_vitamin_c_mg",
    "nutrition_vitamin_d_mcg", "nutrition_vitamin_e_mg", "nutrition_vitamin_k_mcg",
    "nutrition_vitamin_b6_mg", "nutrition_vitamin_b12_mcg", "nutrition_zinc_mg",
    "nutrition_selenium_mcg", "nutrition_caffeine_mg", "nutrition_niacin_mg",
    "nutrition_thiamin_mg", "nutrition_riboflavin_mg", "nutrition_folate_mcg",
}

# Types to AVERAGE per day
AVG_TYPES = {
    "heart_rate", "resting_heart_rate", "hrv_sdnn", "walking_heart_rate_avg",
    "weight_lbs", "bmi", "body_fat_pct", "lean_mass_lbs",
    "spo2_pct", "respiratory_rate", "vo2max",
    "blood_glucose_mgdl", "bp_systolic", "bp_diastolic",
    "walking_speed_mph", "walking_step_length_in", "walking_asymmetry_pct",
    "walking_double_support_pct", "walking_steadiness_pct",
    "waist_inches",
}

# For averaging: accumulate (sum, count) then divide at save time
# For blood glucose: also store min/max/readings count


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def parse_date(date_str):
    """Extract YYYY-MM-DD from Apple Health date string."""
    return date_str[:10] if date_str else None


def main():
    print("=" * 60)
    print("Apple Health Backfill Processor")
    print("=" * 60)
    print(f"Source: {EXPORT_PATH}")
    print("Streaming XML parse — this will take 5-15 minutes...\n")

    start_time = time.time()

    # Per-day accumulators
    # day_data[date] = {field: value_or_accumulator}
    day_sums = defaultdict(lambda: defaultdict(float))        # sum fields
    day_avg_acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))  # (sum, count)

    # Blood glucose: keep all readings per day for CGM
    bg_readings = defaultdict(list)

    # Workouts: list per day
    day_workouts = defaultdict(list)

    # Sleep: list per day
    day_sleep = defaultdict(list)

    record_count = 0
    workout_count = 0
    skipped = 0

    context = ET.iterparse(EXPORT_PATH, events=("start",))

    for event, elem in context:
        tag = elem.tag

        if tag == "Record":
            record_count += 1
            if record_count % 100000 == 0:
                elapsed = time.time() - start_time
                print(f"  Processed {record_count:,} records in {elapsed:.0f}s...")

            rtype = elem.get("type", "")
            start_date = parse_date(elem.get("startDate", ""))
            if not start_date:
                elem.clear()
                continue

            # Quantity records
            if rtype in QUANTITY_RECORDS:
                field = QUANTITY_RECORDS[rtype]
                try:
                    value = float(elem.get("value", "0") or "0")
                except (ValueError, TypeError):
                    elem.clear()
                    continue

                # Blood glucose: keep individual readings
                if field == "blood_glucose_mgdl":
                    bg_readings[start_date].append(value)
                elif field in SUM_TYPES:
                    day_sums[start_date][field] += value
                elif field in AVG_TYPES:
                    day_avg_acc[start_date][field][0] += value
                    day_avg_acc[start_date][field][1] += 1

            # Sleep
            elif rtype == "HKCategoryTypeIdentifierSleepAnalysis":
                source = elem.get("sourceName", "")
                end_date = elem.get("endDate", "")
                value = elem.get("value", "")
                day_sleep[start_date].append({
                    "source": source,
                    "start": elem.get("startDate", ""),
                    "end": end_date,
                    "value": value,
                })

            else:
                skipped += 1

            elem.clear()

        elif tag == "Workout":
            workout_count += 1
            start_date = parse_date(elem.get("startDate", ""))
            if not start_date:
                elem.clear()
                continue

            try:
                duration = float(elem.get("duration") or 0)
            except (ValueError, TypeError):
                duration = 0.0
            try:
                energy = float(elem.get("totalEnergyBurned") or 0)
            except (ValueError, TypeError):
                energy = 0.0
            try:
                distance = float(elem.get("totalDistance") or 0)
            except (ValueError, TypeError):
                distance = 0.0

            day_workouts[start_date].append({
                "type": elem.get("workoutActivityType", "").replace("HKWorkoutActivityType", ""),
                "source": elem.get("sourceName", ""),
                "duration_min": round(duration, 1),
                "calories": round(energy, 1),
                "distance": round(distance, 2),
                "distance_unit": elem.get("totalDistanceUnit", ""),
                "start": elem.get("startDate", ""),
                "end": elem.get("endDate", ""),
            })
            elem.clear()

        elif tag in ("ActivitySummary", "ClinicalRecord", "Audiogram"):
            elem.clear()

    elapsed = time.time() - start_time
    print(f"\nParse complete in {elapsed:.0f}s")
    print(f"  Records: {record_count:,}")
    print(f"  Workouts: {workout_count:,}")
    print(f"  Unique days (quantity): {len(day_sums) + len(day_avg_acc):,}")

    # Collect all dates
    all_dates = set()
    all_dates.update(day_sums.keys())
    all_dates.update(day_avg_acc.keys())
    all_dates.update(bg_readings.keys())
    all_dates.update(day_workouts.keys())
    all_dates.update(day_sleep.keys())

    print(f"  Total unique dates to save: {len(all_dates):,}")
    print(f"\nUploading to S3 + DynamoDB...")

    saved = 0
    errors = 0

    for date_str in sorted(all_dates):
        try:
            day = {"date": date_str, "source": "apple_health"}

            # Sum fields
            for field, value in day_sums[date_str].items():
                day[field] = round(value, 2)

            # Average fields
            for field, (total, count) in day_avg_acc[date_str].items():
                if count > 0:
                    day[field] = round(total / count, 2)

            # Blood glucose (CGM)
            if date_str in bg_readings:
                readings = bg_readings[date_str]
                day["blood_glucose_avg"] = round(sum(readings) / len(readings), 1)
                day["blood_glucose_min"] = round(min(readings), 1)
                day["blood_glucose_max"] = round(max(readings), 1)
                day["blood_glucose_readings_count"] = len(readings)
                # Time in range: 70-180 mg/dL
                in_range = sum(1 for r in readings if 70 <= r <= 180)
                day["blood_glucose_time_in_range_pct"] = round(in_range / len(readings) * 100, 1)

            # Workouts
            if date_str in day_workouts:
                day["workouts"] = day_workouts[date_str]
                day["workout_count"] = len(day_workouts[date_str])
                day["workout_total_minutes"] = round(sum(w["duration_min"] for w in day_workouts[date_str]), 1)
                day["workout_types"] = list({w["type"] for w in day_workouts[date_str]})

            # Sleep (raw entries — let MCP tool interpret)
            if date_str in day_sleep:
                day["sleep_records"] = day_sleep[date_str]
                day["sleep_record_count"] = len(day_sleep[date_str])

            day["ingested_at"] = datetime.now(timezone.utc).isoformat()

            # S3 (gzipped JSON)
            year, month, day_num = date_str[:4], date_str[5:7], date_str[8:10]
            s3_key = f"raw/apple_health/{year}/{month}/{day_num}.json.gz"
            compressed = gzip.compress(json.dumps(day, default=str).encode())
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=compressed,
                ContentType="application/json",
                ContentEncoding="gzip",
            )

            # DynamoDB
            db_item = {
                "pk": "USER#matthew#SOURCE#apple_health",
                "sk": f"DATE#{date_str}",
            }
            db_item.update(day)
            table.put_item(Item=floats_to_decimal(db_item))

            saved += 1
            if saved % 500 == 0:
                print(f"  Saved {saved:,} / {len(all_dates):,} days...")

        except Exception as e:
            errors += 1
            print(f"  ERROR on {date_str}: {e}")
            if errors > 20:
                print("Too many errors, stopping.")
                break

    total_elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Backfill complete in {total_elapsed:.0f}s")
    print(f"  Days saved: {saved:,}")
    print(f"  Errors: {errors}")
    print(f"  Date range: {min(all_dates)} → {max(all_dates)}")


if __name__ == "__main__":
    main()
