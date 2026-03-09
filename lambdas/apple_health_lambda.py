#!/usr/bin/env python3
"""
Apple Health incremental Lambda processor.
Triggered by S3 PutObject on: imports/apple_health/export.xml (or .xml.gz)

Logic:
1. Find most recent date already stored in DynamoDB
2. Parse only records newer than that date (plus 7-day overlap buffer for late writes)
3. Merge with existing DynamoDB records for overlap days
4. Save to S3 (raw/apple_health/) + DynamoDB
5. Move processed file to imports/apple_health/processed/{timestamp}_export.xml.gz
"""

import xml.etree.ElementTree as ET
import logging
import json
import boto3
import gzip
import io
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from collections import defaultdict

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "life-platform")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
USER_ID        = os.environ["USER_ID"]
OVERLAP_DAYS = 14  # Reprocess last N days to catch late-arriving records

s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


# ── Same field maps as backfill (keep in sync) ───────────────────────────────
QUANTITY_RECORDS = {
    "HKQuantityTypeIdentifierStepCount":                    "steps",
    "HKQuantityTypeIdentifierActiveEnergyBurned":           "active_calories",
    "HKQuantityTypeIdentifierBasalEnergyBurned":            "basal_calories",
    "HKQuantityTypeIdentifierFlightsClimbed":               "flights_climbed",
    "HKQuantityTypeIdentifierDistanceWalkingRunning":        "distance_walk_run_miles",
    "HKQuantityTypeIdentifierDistanceCycling":              "distance_cycling_miles",
    "HKQuantityTypeIdentifierHeartRate":                    "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate":             "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":     "hrv_sdnn",
    "HKQuantityTypeIdentifierWalkingHeartRateAverage":      "walking_heart_rate_avg",
    "HKQuantityTypeIdentifierBodyMass":                     "weight_lbs",
    "HKQuantityTypeIdentifierBodyMassIndex":                "bmi",
    "HKQuantityTypeIdentifierBodyFatPercentage":            "body_fat_pct",
    "HKQuantityTypeIdentifierLeanBodyMass":                 "lean_mass_lbs",
    "HKQuantityTypeIdentifierWaistCircumference":           "waist_inches",
    "HKQuantityTypeIdentifierOxygenSaturation":             "spo2_pct",
    "HKQuantityTypeIdentifierRespiratoryRate":              "respiratory_rate",
    "HKQuantityTypeIdentifierVO2Max":                       "vo2max",
    "HKQuantityTypeIdentifierBloodGlucose":                 "blood_glucose_mgdl",
    "HKQuantityTypeIdentifierBloodPressureSystolic":        "bp_systolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic":       "bp_diastolic",
    "HKQuantityTypeIdentifierWalkingSpeed":                 "walking_speed_mph",
    "HKQuantityTypeIdentifierWalkingStepLength":            "walking_step_length_in",
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage":   "walking_asymmetry_pct",
    "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage": "walking_double_support_pct",
    "HKQuantityTypeIdentifierAppleWalkingSteadiness":       "walking_steadiness_pct",
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

AVG_TYPES = {
    "heart_rate", "resting_heart_rate", "hrv_sdnn", "walking_heart_rate_avg",
    "weight_lbs", "bmi", "body_fat_pct", "lean_mass_lbs",
    "spo2_pct", "respiratory_rate", "vo2max",
    "blood_glucose_mgdl", "bp_systolic", "bp_diastolic",
    "walking_speed_mph", "walking_step_length_in", "walking_asymmetry_pct",
    "walking_double_support_pct", "walking_steadiness_pct", "waist_inches",
}


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def parse_date(date_str):
    return date_str[:10] if date_str else None


def get_latest_stored_date():
    """Query DynamoDB for the most recent apple_health record."""
    try:
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(
                f"USER#{USER_ID}#SOURCE#apple_health"
            ),
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("items") or response.get("Items", [])
        if items:
            sk = items[0].get("sk", "DATE#2000-01-01")
            return sk.replace("DATE#", "")
    except Exception as e:
        print(f"Warning: Could not query latest date: {e}")
    return "2000-01-01"


def process_xml(xml_stream, cutoff_date):
    """Stream-parse XML, collecting records on or after cutoff_date."""
    day_sums = defaultdict(lambda: defaultdict(float))
    day_avg_acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    bg_readings = defaultdict(list)
    day_workouts = defaultdict(list)
    day_sleep = defaultdict(list)

    record_count = 0
    skipped_old = 0

    context = ET.iterparse(xml_stream, events=("start",))

    for event, elem in context:
        tag = elem.tag

        if tag == "Record":
            record_count += 1
            rtype = elem.get("type", "")
            start_date = parse_date(elem.get("startDate", ""))

            if not start_date or start_date < cutoff_date:
                skipped_old += 1
                elem.clear()
                continue

            if rtype in QUANTITY_RECORDS:
                field = QUANTITY_RECORDS[rtype]
                try:
                    value = float(elem.get("value", "0") or "0")
                except (ValueError, TypeError):
                    elem.clear()
                    continue

                if field == "blood_glucose_mgdl":
                    bg_readings[start_date].append(value)
                elif field in SUM_TYPES:
                    day_sums[start_date][field] += value
                elif field in AVG_TYPES:
                    day_avg_acc[start_date][field][0] += value
                    day_avg_acc[start_date][field][1] += 1

            elif rtype == "HKCategoryTypeIdentifierSleepAnalysis":
                day_sleep[start_date].append({
                    "source": elem.get("sourceName", ""),
                    "start": elem.get("startDate", ""),
                    "end": elem.get("endDate", ""),
                    "value": elem.get("value", ""),
                })

            elem.clear()

        elif tag == "Workout":
            start_date = parse_date(elem.get("startDate", ""))
            if not start_date or start_date < cutoff_date:
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

    print(f"Parsed {record_count:,} records, skipped {skipped_old:,} older than cutoff")

    return day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep


def build_day_record(date_str, day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep):
    """Assemble a single day's data dict."""
    day = {"date": date_str, "source": "apple_health"}

    for field, value in day_sums[date_str].items():
        day[field] = round(value, 2)

    for field, (total, count) in day_avg_acc[date_str].items():
        if count > 0:
            day[field] = round(total / count, 2)

    if date_str in bg_readings:
        readings = bg_readings[date_str]
        day["blood_glucose_avg"] = round(sum(readings) / len(readings), 1)
        day["blood_glucose_min"] = round(min(readings), 1)
        day["blood_glucose_max"] = round(max(readings), 1)
        day["blood_glucose_readings_count"] = len(readings)
        in_range = sum(1 for r in readings if 70 <= r <= 180)
        day["blood_glucose_time_in_range_pct"] = round(in_range / len(readings) * 100, 1)

    if date_str in day_workouts:
        day["workouts"] = day_workouts[date_str]
        day["workout_count"] = len(day_workouts[date_str])
        day["workout_total_minutes"] = round(
            sum(w["duration_min"] for w in day_workouts[date_str]), 1
        )
        day["workout_types"] = list({w["type"] for w in day_workouts[date_str]})

    if date_str in day_sleep:
        day["sleep_records"] = day_sleep[date_str]
        day["sleep_record_count"] = len(day_sleep[date_str])

    day["ingested_at"] = datetime.now(timezone.utc).isoformat()
    return day


def save_day(date_str, day):
    """Write one day to S3 (gzipped) and DynamoDB."""
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

    db_item = {"pk": f"USER#{USER_ID}#SOURCE#apple_health", "sk": f"DATE#{date_str}", "schema_version": 1}
    db_item.update(day)
    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item
        _vr = _validate_item("apple_health", floats_to_decimal(db_item), date_str)
        if _vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping apple_health DDB write for {date_str}: {_vr.errors}")
            _vr.archive_to_s3(s3_client, bucket=S3_BUCKET, item=db_item)
            return
        if _vr.warnings:
            logger.warning(f"[DATA-2] Validation warnings for apple_health/{date_str}: {_vr.warnings}")
    except ImportError:
        pass
    table.put_item(Item=floats_to_decimal(db_item))


def lambda_handler(event, context):
    print("Apple Health Lambda triggered")
    print(f"Event: {json.dumps(event, default=str)}")

    # Get S3 trigger info
    record = event["Records"][0]["s3"]
    bucket = record["bucket"]["name"]
    key = record["object"]["key"]
    print(f"Processing: s3://{bucket}/{key}")

    # Determine cutoff date (latest stored minus overlap buffer)
    latest_date = get_latest_stored_date()
    cutoff_dt = datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=OVERLAP_DAYS)
    cutoff_date = cutoff_dt.strftime("%Y-%m-%d")
    print(f"Latest stored date: {latest_date}, processing from: {cutoff_date}")

    # Download export from S3
    print("Downloading export from S3...")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()

    # Handle gzipped or plain XML
    if key.endswith(".gz"):
        xml_data = gzip.decompress(body)
    else:
        xml_data = body

    xml_stream = io.BytesIO(xml_data)

    # Parse
    print("Parsing XML...")
    day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep = process_xml(
        xml_stream, cutoff_date
    )

    # Collect all dates in this parse
    all_dates = set()
    all_dates.update(day_sums.keys())
    all_dates.update(day_avg_acc.keys())
    all_dates.update(bg_readings.keys())
    all_dates.update(day_workouts.keys())
    all_dates.update(day_sleep.keys())

    print(f"Found data for {len(all_dates)} days")

    # Save each day
    saved = 0
    errors = 0
    for date_str in sorted(all_dates):
        try:
            day = build_day_record(
                date_str, day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep
            )
            save_day(date_str, day)
            saved += 1
        except Exception as e:
            errors += 1
            print(f"ERROR saving {date_str}: {e}")

    print(f"Saved {saved} days, {errors} errors")

    # Archive the processed file
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_key = f"imports/apple_health/processed/{ts}_export.xml.gz"
    archive_body = gzip.compress(xml_data) if not key.endswith(".gz") else body
    s3_client.put_object(Bucket=S3_BUCKET, Key=archive_key, Body=archive_body)
    s3_client.delete_object(Bucket=bucket, Key=key)
    print(f"Archived to {archive_key}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "days_saved": saved,
            "errors": errors,
            "date_range": f"{min(all_dates)} → {max(all_dates)}" if all_dates else "none",
            "cutoff_used": cutoff_date,
        }),
    }
