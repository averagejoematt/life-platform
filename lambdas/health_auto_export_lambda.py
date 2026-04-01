"""
health_auto_export_lambda.py — Webhook receiver for Health Auto Export iOS app.

Receives automated POST requests from Health Auto Export (iOS) containing
Apple HealthKit data in JSON format. Primary use case: Dexcom Stelo CGM
glucose readings, but handles any configured HealthKit metrics.

Architecture:
  Health Auto Export (iOS) → Lambda Function URL → this Lambda → DynamoDB + S3

Auth: Bearer token stored in Secrets Manager (life-platform/health-auto-export).

Data flow:
  1. Validate bearer token from Authorization header
  2. Parse Health Auto Export JSON payload (metrics, workouts)
  3. For blood glucose: store individual readings in S3, daily aggregates in DynamoDB
  4. For other metrics: aggregate by day and merge into DynamoDB
  5. Uses update_item (not put_item) to merge with existing apple_health records

CGM-specific derived fields:
  blood_glucose_avg, blood_glucose_min, blood_glucose_max,
  blood_glucose_std_dev, blood_glucose_readings_count,
  blood_glucose_time_in_range_pct (70-180 mg/dL),
  blood_glucose_time_in_optimal_pct (70-120 mg/dL, Attia optimal),
  blood_glucose_time_below_70_pct, blood_glucose_time_above_140_pct,
  cgm_source ("dexcom_stelo" | "manual" based on reading frequency)

DynamoDB items:
  pk = USER#matthew#SOURCE#apple_health
  sk = DATE#YYYY-MM-DD

S3 raw storage:
  raw/health_auto_export/YYYY/MM/DD_HHmmss.json  (full payload)
  raw/cgm_readings/YYYY/MM/DD.json                (individual glucose readings)

IAM role: lambda-health-auto-export-role
Trigger: API Gateway HTTP API (bearer token auth)

v1.6.0 — Workout ingestion (Pliability, Breathwrk, recovery workouts)
  - Processes workouts from HAE payload (previously logged but dropped)
  - Classifies by HealthKit workout type into recovery categories:
    Flexibility (Pliability), Mind and Body, Breathing (Breathwrk),
    Yoga, Pilates, Cooldown, Tai Chi
  - Daily aggregates to DynamoDB: flexibility_minutes, flexibility_sessions,
    breathwork_minutes, breathwork_sessions, recovery_workout_minutes, recovery_workout_types
  - Individual workouts stored to S3 raw/workouts/YYYY/MM/DD.json
  - Non-recovery workouts (strength, running, etc.) stored to S3 but NOT
    aggregated to DynamoDB to avoid double-counting with Strava SOT
  - Enables mobility/recovery tracking and sleep-quality correlations
v1.5.0 — State of Mind ingestion (How We Feel / Apple Health)
  - Detects State of Mind payloads (separate HAE automation Data Type)
  - Stores individual check-ins to S3 raw/state_of_mind/YYYY/MM/DD.json
  - Each entry: timestamp, kind (dailyMood/momentaryEmotion), valence (-1 to +1),
    valence_classification, labels (e.g. Happy, Stressed), associations (e.g. Work, Family)
  - Daily aggregates to DynamoDB: avg_valence, check_in_count, dominant labels/associations
  - Enables mood-wearable correlations, pre-sleep mood → sleep quality analysis
  - Source: How We Feel app → HealthKit State of Mind → Health Auto Export → webhook
v1.4.0 — Blood pressure monitoring
  - Added blood_pressure_systolic, blood_pressure_diastolic to METRIC_MAP (Tier 1, avg)
  - Individual BP readings stored in S3 raw/blood_pressure/YYYY/MM/DD.json
  - Pulse from BP cuff tracked as blood_pressure_pulse
  - Enables cardiovascular risk tracking, sodium correlation
v1.3.0 — Water intake tracking
  - Moved dietary_water from SKIP_METRICS to METRIC_MAP (Tier 1, sum, field: water_intake_ml)
  - Water app → Apple Health → webhook → DynamoDB; tracks to the milliliter
v1.2.0 — Structured logging + auth resilience (RCA corrective actions)
  - Structured JSON log line on every webhook completion (CloudWatch Insights queryable)
  - Fields: event, request_id, metrics_count, matched_metrics, skipped_sot, duration_ms, payload_bytes
  - Auth failure structured logging with request_id for tracing
  - Request timing (duration_ms) from handler entry to response
v1.1.0 — Three-tier source filtering + expanded metrics
  - Tier 1 (Apple-exclusive): activity, gait, energy, audio — all readings ingested
  - Tier 2 (cross-device): HR, HRV, RHR, respiratory, SpO2 — filtered to Apple Watch only
  - Tier 3 (skip): nutrition (MacroFactor SOT), sleep (Eight Sleep SOT), body (Withings SOT)
  - Derived: total_calories_burned = active + basal
  - New fields: gait metrics, headphone_audio_exposure_db, *_apple suffixed cross-ref fields
  - Source detection via device name substring matching
v1.0.0 — Initial release
"""

import json
import logging
import math
import os
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from collections import defaultdict

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
S3_BUCKET      = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "life-platform")
SECRET_NAME    = os.environ.get("SECRET_NAME", "life-platform/ingestion-keys")
REGION         = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
USER_ID        = os.environ["USER_ID"]
PK             = f"USER#{USER_ID}#SOURCE#apple_health"

# ── AWS clients ────────────────────────────────────────────────────────────────
s3_client      = boto3.client("s3", region_name=REGION)
dynamodb       = boto3.resource("dynamodb", region_name=REGION)
table          = dynamodb.Table(DYNAMODB_TABLE)
secrets_client = boto3.client("secretsmanager", region_name=REGION)

# Cache the API key across invocations
_cached_api_key = None


def get_api_key():
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key
    resp = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    _cached_api_key = secret.get("health_auto_export_api_key") or secret.get("api_key")
    return _cached_api_key


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


def parse_date_str(date_str):
    """Parse Health Auto Export date format: 'yyyy-MM-dd HH:mm:ss Z' → date string."""
    if not date_str:
        return None
    return date_str[:10]


def parse_timestamp(date_str):
    """Parse full timestamp for individual reading storage."""
    if not date_str:
        return None
    # Format: "2026-02-24 14:30:00 -0800"
    return date_str.strip()


# ── Blood Glucose Processing ──────────────────────────────────────────────────

def process_blood_glucose(metric_data, units):
    """
    Process CGM blood glucose readings into daily aggregates + individual readings.

    Returns:
        daily_agg: dict of date → {avg, min, max, std_dev, count, time_in_range, ...}
        daily_readings: dict of date → list of individual readings
    """
    daily_readings = defaultdict(list)

    for reading in metric_data:
        date = parse_date_str(reading.get("date"))
        qty = reading.get("qty")
        if not date or qty is None:
            continue

        value = float(qty)
        # Convert mmol/L to mg/dL if needed
        if units and "mmol" in units.lower():
            # 1 mmol/L = 18.0182 mg/dL (molecular weight of glucose / 10)
            value = round(value * 18.0182, 1)

        daily_readings[date].append({
            "time": parse_timestamp(reading.get("date")),
            "value": value,
            "meal_time": reading.get("mealTime", "Unspecified"),
        })

    daily_agg = {}
    for date, readings in daily_readings.items():
        values = [r["value"] for r in readings]
        n = len(values)
        avg = sum(values) / n
        std_dev = math.sqrt(sum((v - avg) ** 2 for v in values) / n) if n > 1 else 0

        # 70-180 mg/dL: ADA standard Time in Range; 70-120: Attia metabolic optimal
        in_range = sum(1 for v in values if 70 <= v <= 180)
        in_optimal = sum(1 for v in values if 70 <= v <= 120)
        below_70 = sum(1 for v in values if v < 70)
        above_140 = sum(1 for v in values if v > 140)

        # Determine if CGM vs manual based on reading frequency
        # CGM: 5-min intervals = ~288/day; manual: 1-10/day
        # 20+ readings/day = CGM (288/day at 5-min intervals); <20 likely manual fingerstick
        cgm_source = "dexcom_stelo" if n >= 20 else "manual"

        daily_agg[date] = {
            "blood_glucose_avg": round(avg, 1),
            "blood_glucose_min": round(min(values), 1),
            "blood_glucose_max": round(max(values), 1),
            "blood_glucose_std_dev": round(std_dev, 1),
            "blood_glucose_readings_count": n,
            "blood_glucose_time_in_range_pct": round(in_range / n * 100, 1),
            "blood_glucose_time_in_optimal_pct": round(in_optimal / n * 100, 1),
            "blood_glucose_time_below_70_pct": round(below_70 / n * 100, 1),
            "blood_glucose_time_above_140_pct": round(above_140 / n * 100, 1),
            "cgm_source": cgm_source,
        }

    return daily_agg, daily_readings


# ── Generic Metric Processing ─────────────────────────────────────────────────

# ── Source Filtering ────────────────────────────────────────────────────────
# Apple Health acts as an aggregator — HealthKit receives data from Whoop,
# Eight Sleep, MacroFactor, Withings, etc. We must filter readings to avoid
# double-counting data that has its own dedicated SOT pipeline.
#
# Three tiers:
#   Tier 1 — Apple-exclusive: always ingest all readings (no other SOT)
#   Tier 2 — Cross-device: filter to Apple Watch/iPhone sources only
#   Tier 3 — Skip entirely: SOT covered by dedicated pipeline
# ────────────────────────────────────────────────────────────────────────────

# Substrings that identify Apple Watch / iPhone as the reading source.
# The app reports device names like "Matt 17" (iPhone), "Apple Watch" etc.
# We also accept readings with no source field (assumed Apple device).
APPLE_DEVICE_SUBSTRINGS = {
    "matt",          # iPhone name ("Matt 17", "Matt's iPhone", etc.)
    "iphone",
    "apple watch",
    "watch",
}


def is_apple_device(source_str):
    """Return True if the reading source is an Apple device (or unknown/missing)."""
    if not source_str:
        return True  # No source tag → assume Apple device
    s = source_str.lower()
    return any(sub in s for sub in APPLE_DEVICE_SUBSTRINGS)


# ── Metric Configuration ───────────────────────────────────────────────────
# Metrics we want to ingest (beyond blood glucose which has special handling).
# The app sends BOTH Title Case ("Step Count") and snake_case ("step_count")
# depending on JSON version / automation config.
#
# tier: 1 = Apple-exclusive (all readings), 2 = filter to Apple device only

METRIC_MAP = {}

_METRIC_DEFS = [
    # ── Tier 1: Apple-exclusive (always ingest all readings) ──────────────
    # Activity / energy (Apple Watch TDEE)
    ({"Active Energy", "active_energy"},                  {"field": "active_calories",            "agg": "sum",         "tier": 1}),
    ({"Basal Energy Burned", "basal_energy_burned"},      {"field": "basal_calories",             "agg": "sum",         "tier": 1}),
    ({"Step Count", "step_count"},                        {"field": "steps",                      "agg": "sum",         "tier": 1}),
    ({"Flights Climbed", "flights_climbed"},              {"field": "flights_climbed",            "agg": "sum",         "tier": 1}),
    ({"Walking + Running Distance", "walking_running_distance"}, {"field": "distance_walk_run_miles", "agg": "sum",      "tier": 1}),
    # Gait / mobility (Apple Watch exclusive)
    ({"Walking Speed", "walking_speed"},                  {"field": "walking_speed_mph",          "agg": "avg",         "tier": 1}),
    ({"Walking Step Length", "walking_step_length"},      {"field": "walking_step_length_in",     "agg": "avg",         "tier": 1}),
    ({"Walking Double Support Percentage", "walking_double_support_percentage"}, {"field": "walking_double_support_pct", "agg": "avg", "tier": 1}),
    ({"Walking Asymmetry Percentage", "walking_asymmetry_percentage"},           {"field": "walking_asymmetry_pct",     "agg": "avg", "tier": 1}),
    # Audio (iPhone/AirPods exclusive)
    ({"Headphone Audio Exposure", "headphone_audio_exposure"}, {"field": "headphone_audio_exposure_db", "agg": "avg",   "tier": 1}),
    # Water intake (dedicated water app → Apple Health)
    # Unit conversion handled in post-processing (fl_oz_us → mL)
    ({"Dietary Water", "dietary_water", "Water", "water"},      {"field": "water_intake_raw",            "agg": "sum",   "tier": 1}),
    # Caffeine intake (water/caffeine tracking app → Apple Health)
    ({"Dietary Caffeine", "dietary_caffeine", "Caffeine", "caffeine"}, {"field": "caffeine_mg",            "agg": "sum",   "tier": 1}),
    # Mindful minutes (meditation/breathwork apps → Apple Health)
    ({"Mindful Minutes", "mindful_minutes", "Apple Mindfulness", "apple_mindfulness"},  {"field": "mindful_minutes",           "agg": "sum",         "tier": 1}),
    # Body weight (Withings scale → Apple Health — v1.4.2 fallback for Withings API delays)
    ({"Body Mass", "body_mass"},                          {"field": "weight_lbs",                "agg": "avg",         "tier": 1}),
    # Blood pressure (BP cuff → Apple Health — v1.4.0)
    ({"Blood Pressure Systolic", "blood_pressure_systolic"},   {"field": "blood_pressure_systolic",   "agg": "avg",         "tier": 1}),
    ({"Blood Pressure Diastolic", "blood_pressure_diastolic"}, {"field": "blood_pressure_diastolic",  "agg": "avg",         "tier": 1}),
    ({"Blood Pressure Pulse", "blood_pressure_pulse"},         {"field": "blood_pressure_pulse",      "agg": "avg",         "tier": 1}),
    # ── Tier 2: Cross-device (filter to Apple Watch readings only) ────────
    # These metrics also come from Whoop/Eight Sleep/Garmin — only keep Apple readings
    # to serve as cross-reference without polluting the primary SOT values.
    ({"Heart Rate", "heart_rate"},                        {"field": "heart_rate_apple",            "agg": "avg_special", "tier": 2}),
    ({"Resting Heart Rate", "resting_heart_rate"},        {"field": "resting_heart_rate_apple",    "agg": "avg",         "tier": 2}),
    ({"Heart Rate Variability", "heart_rate_variability"},{"field": "hrv_sdnn_apple",              "agg": "avg",         "tier": 2}),
    ({"Respiratory Rate", "respiratory_rate"},            {"field": "respiratory_rate_apple",      "agg": "avg",         "tier": 2}),
    ({"Oxygen Saturation", "blood_oxygen_saturation"},   {"field": "spo2_pct_apple",              "agg": "avg",         "tier": 2}),
]

# Build lookup from all name variants
for names, config in _METRIC_DEFS:
    for name in names:
        METRIC_MAP[name] = config


# ── Tier 3: Skip entirely (SOT covered by dedicated pipelines) ───────────
# sleep_analysis   → Eight Sleep is SOT for sleep
# All nutrition    → MacroFactor is SOT for nutrition
# body_mass/fat   → Withings is SOT for body composition
SKIP_METRICS = {
    # Glucose handled separately
    "Blood Glucose", "blood_glucose",
    # Sleep — Eight Sleep is SOT
    "sleep_analysis", "Sleep Analysis",
    # Body comp — Withings is primary, but accept body_mass from HAE as fallback
    # "body_mass", "Body Mass",  # v1.4.2: accept weight from HAE (Withings API has sync delays)
    "body_fat_percentage", "Body Fat Percentage",
    # Nutrition — MacroFactor is SOT (these flow into HealthKit from MF app)
    "dietary_energy", "Dietary Energy",
    "protein", "Protein",
    "carbohydrates", "Carbohydrates",
    "total_fat", "Total Fat",
    "fiber", "Fiber",
    "dietary_sugar", "Dietary Sugar",
    "sodium", "Sodium",
    "saturated_fat", "Saturated Fat",
    "monounsaturated_fat", "Monounsaturated Fat",
    "polyunsaturated_fat", "Polyunsaturated Fat",
    "cholesterol", "Cholesterol",
    "calcium", "Calcium",
    "iron", "Iron",
    "potassium", "Potassium",
    "magnesium", "Magnesium",
    "zinc", "Zinc",
    "selenium", "Selenium",
    "copper", "Copper",
    "manganese", "Manganese",
    "phosphorus", "Phosphorus",
    "vitamin_a", "Vitamin A",
    "vitamin_c", "Vitamin C",
    "vitamin_d", "Vitamin D",
    "vitamin_e", "Vitamin E",
    "vitamin_k", "Vitamin K",
    "vitamin_b6", "Vitamin B6",
    "vitamin_b12", "Vitamin B12",
    "thiamin", "Thiamin",
    "riboflavin", "Riboflavin",
    "niacin", "Niacin",
    "folate", "Folate",
    "pantothenic_acid", "Pantothenic Acid",
}

# NOTE: dietary_water removed from SKIP_METRICS in v1.3.0 —
# water is tracked via a dedicated water app → Apple Health, not MacroFactor.


def process_generic_metrics(metrics):
    """Process non-glucose metrics into daily aggregates with source filtering."""
    daily_data = defaultdict(dict)
    matched = []
    skipped_sot = []
    unmatched = []
    filtered_counts = {}  # metric → {kept, dropped}

    for metric in metrics:
        name = metric.get("name", "")
        data = metric.get("data", [])

        if name in SKIP_METRICS:
            skipped_sot.append(name)
            continue

        if name not in METRIC_MAP:
            unmatched.append(name)
            continue

        matched.append(name)
        config = METRIC_MAP[name]
        field = config["field"]
        agg = config["agg"]
        tier = config["tier"]

        day_values = defaultdict(list)
        kept = 0
        dropped = 0

        for reading in data:
            date = parse_date_str(reading.get("date"))
            if not date:
                continue

            # Tier 2: filter to Apple device readings only
            if tier == 2:
                source = reading.get("source", "")
                if not is_apple_device(source):
                    dropped += 1
                    continue

            if agg == "avg_special":
                # Heart Rate comes as {Min, Avg, Max}
                qty = reading.get("Avg") or reading.get("qty")
            else:
                qty = reading.get("qty")

            if qty is not None:
                day_values[date].append(float(qty))
                kept += 1

        if tier == 2 and dropped > 0:
            filtered_counts[name] = {"kept": kept, "dropped": dropped}

        for date, values in day_values.items():
            if not values:
                continue
            if agg == "sum":
                daily_data[date][field] = round(sum(values), 2)
            elif agg in ("avg", "avg_special", "avg_pct"):
                daily_data[date][field] = round(sum(values) / len(values), 2)

    # ── Compute derived fields ──
    for date, fields in daily_data.items():
        ac = fields.get("active_calories")
        bc = fields.get("basal_calories")
        if ac is not None and bc is not None:
            fields["total_calories_burned"] = round(ac + bc, 2)

        # Water: convert fl_oz_us → mL (1 fl oz = 29.5735 mL)
        water_raw = fields.pop("water_intake_raw", None)
        if water_raw is not None:
            # 1 US fluid ounce = 29.5735 mL
            fields["water_intake_ml"] = round(water_raw * 29.5735)
            fields["water_intake_oz"] = round(water_raw, 1)

    # ── Logging ──
    if matched:
        print(f"Matched metrics ({len(matched)}): {matched}")
    if skipped_sot:
        print(f"Skipped (SOT elsewhere, {len(skipped_sot)}): {skipped_sot}")
    if unmatched:
        print(f"Unmatched (no mapping, {len(unmatched)}): {unmatched}")
    if filtered_counts:
        for m, counts in filtered_counts.items():
            print(f"Source filter [{m}]: kept {counts['kept']} Apple readings, dropped {counts['dropped']} non-Apple")

    return daily_data


# ── DynamoDB Write ─────────────────────────────────────────────────────────────

def merge_day_to_dynamo(date_str, fields):
    """
    Merge fields into existing DynamoDB record using update_item.
    Only updates specified fields — does NOT overwrite unrelated fields.
    """
    if not fields:
        return

    # Build update expression
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
    names["#upd"] = "webhook_ingested_at"
    values[":upd"] = datetime.now(timezone.utc).isoformat()

    # Ensure base fields exist
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


def save_cgm_readings_to_s3(date_str, readings):
    """Save individual CGM readings to S3 for detailed analysis."""
    s3_key = f"raw/{USER_ID}/cgm_readings/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    # Merge with existing readings for this day (idempotent)
    existing = []
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_cgm_readings %s: %s", s3_key, e)

    # Deduplicate by timestamp
    existing_times = {r["time"] for r in existing}
    new_readings = [r for r in readings if r["time"] not in existing_times]

    if new_readings:
        merged = sorted(existing + new_readings, key=lambda r: r["time"] or "")
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_readings)
    return 0


def save_bp_readings_to_s3(date_str, readings):
    """Save individual BP readings to S3 for detailed analysis (v1.4.0)."""
    s3_key = f"raw/{USER_ID}/blood_pressure/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    existing = []
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_bp_readings %s: %s", s3_key, e)

    existing_times = {r["time"] for r in existing}
    new_readings = [r for r in readings if r["time"] not in existing_times]

    if new_readings:
        merged = sorted(existing + new_readings, key=lambda r: r["time"] or "")
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_readings)
    return 0


def save_state_of_mind_to_s3(date_str, entries):
    """Save individual State of Mind check-ins to S3 (v1.5.0)."""
    s3_key = f"raw/{USER_ID}/state_of_mind/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    existing = []
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_state_of_mind %s: %s", s3_key, e)

    # Deduplicate by timestamp
    existing_times = {e.get("time") for e in existing}
    new_entries = [e for e in entries if e.get("time") not in existing_times]

    if new_entries:
        merged = sorted(existing + new_entries, key=lambda e: e.get("time") or "")
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_entries)
    return 0


def process_state_of_mind(payload):
    """
    Process State of Mind data from Health Auto Export (v1.5.0).

    HAE sends State of Mind as a separate data type (not in metrics[]).
    The payload may contain a top-level list of entries or nested under
    various keys. We detect flexibly.

    HealthKit State of Mind fields:
      - kind: "dailyMood" or "momentaryEmotion"
      - valence: float -1.0 to +1.0
      - valenceClassification: "veryUnpleasant" .. "veryPleasant" (1-7)
      - labels: ["Happy", "Calm", "Stressed", ...]
      - associations: ["Work", "Family", "Health", ...]
      - date/startDate/endDate: timestamp
      - source: app name ("How We Feel", "Health", etc.)

    Returns:
      daily_entries: dict of date → list of normalized check-in dicts
      daily_agg: dict of date → {avg_valence, check_in_count, ...}
    """
    # ── Find the entries array ──
    # HAE might send as: top-level list, or {"data": {"stateOfMind": [...]}},
    # or {"stateOfMind": [...]}, or {"data": [...]}
    entries_raw = []
    if isinstance(payload, list):
        entries_raw = payload
    elif isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, list):
            entries_raw = data
        elif isinstance(data, dict):
            # Try known keys
            for key in ("stateOfMind", "state_of_mind", "stateofmind",
                        "StateOfMind", "entries", "samples"):
                if key in data and isinstance(data[key], list):
                    entries_raw = data[key]
                    break
            # If still empty, check if data has metrics (normal payload) — not SoM
            if not entries_raw and "metrics" in data:
                return {}, {}  # Normal metrics payload, not SoM

    if not entries_raw:
        return {}, {}

    # ── Valence classification mapping ──
    VALENCE_MAP = {
        1: "veryUnpleasant", 2: "unpleasant", 3: "slightlyUnpleasant",
        4: "neutral", 5: "slightlyPleasant", 6: "pleasant", 7: "veryPleasant",
    }

    # ── Normalize entries ──
    daily_entries = defaultdict(list)

    for raw in entries_raw:
        if not isinstance(raw, dict):
            continue

        # Extract date — try multiple field names
        date_field = (raw.get("date") or raw.get("startDate")
                      or raw.get("start_date") or raw.get("start")
                      or raw.get("end") or raw.get("timestamp") or "")
        date_str = parse_date_str(str(date_field)) if date_field else None
        if not date_str:
            continue

        time_str = parse_timestamp(str(date_field)) if date_field else None

        # Valence: float -1.0 to +1.0
        valence = raw.get("valence")
        if valence is not None:
            valence = float(valence)
        else:
            # Try valenceClassification int (1-7) → convert to -1..+1 range
            vc = raw.get("valenceClassification")
            if vc is not None:
                try:
                    # Convert HealthKit 1-7 scale to -1..+1: subtract midpoint (4), divide by range (3)
                    valence = (int(vc) - 4) / 3.0  # 1→-1.0, 4→0.0, 7→1.0
                except (ValueError, TypeError):
                    pass

        if valence is None:
            continue  # No mood value, skip

        # Classification string
        vc_raw = raw.get("valenceClassification", "")
        if isinstance(vc_raw, int):
            valence_class = VALENCE_MAP.get(vc_raw, f"level_{vc_raw}")
        elif isinstance(vc_raw, str) and vc_raw:
            valence_class = vc_raw
        else:
            # Derive from valence float
            if valence <= -0.67:
                valence_class = "veryUnpleasant"
            elif valence <= -0.33:
                valence_class = "unpleasant"
            elif valence <= -0.05:
                valence_class = "slightlyUnpleasant"
            elif valence <= 0.05:
                valence_class = "neutral"
            elif valence <= 0.33:
                valence_class = "slightlyPleasant"
            elif valence <= 0.67:
                valence_class = "pleasant"
            else:
                valence_class = "veryPleasant"

        # Kind
        kind = raw.get("kind", raw.get("type", "unknown"))
        # Normalize to camelCase
        kind_lower = str(kind).lower().replace(" ", "").replace("_", "")
        if "mood" in kind_lower or "daily" in kind_lower:
            kind = "dailyMood"
        elif "emotion" in kind_lower or "momentary" in kind_lower:
            kind = "momentaryEmotion"

        # Labels (emotions)
        labels = raw.get("labels", raw.get("label", []))
        if isinstance(labels, str):
            labels = [labels] if labels else []

        # Associations (life areas)
        associations = raw.get("associations", raw.get("association", []))
        if isinstance(associations, str):
            associations = [associations] if associations else []

        # Source app
        source = raw.get("source", raw.get("sourceName", ""))

        entry = {
            "time": time_str,
            "kind": kind,
            "valence": round(valence, 4),
            "valence_classification": valence_class,
            "labels": labels,
            "associations": associations,
            "source": source,
        }
        daily_entries[date_str].append(entry)

    # ── Daily aggregates ──
    daily_agg = {}
    for date_str, entries in daily_entries.items():
        valences = [e["valence"] for e in entries]
        all_labels = []
        all_assoc = []
        moods = 0
        emotions = 0
        for e in entries:
            all_labels.extend(e["labels"])
            all_assoc.extend(e["associations"])
            if e["kind"] == "dailyMood":
                moods += 1
            else:
                emotions += 1

        # Count label/association frequency
        label_counts = defaultdict(int)
        for l in all_labels:
            label_counts[l] += 1
        assoc_counts = defaultdict(int)
        for a in all_assoc:
            assoc_counts[a] += 1

        # Top labels and associations (up to 3)
        top_labels = sorted(label_counts.items(), key=lambda x: -x[1])[:3]
        top_assoc = sorted(assoc_counts.items(), key=lambda x: -x[1])[:3]

        avg_valence = sum(valences) / len(valences)
        daily_agg[date_str] = {
            "som_avg_valence": round(avg_valence, 4),
            "som_min_valence": round(min(valences), 4),
            "som_max_valence": round(max(valences), 4),
            "som_check_in_count": len(entries),
            "som_mood_count": moods,
            "som_emotion_count": emotions,
            "som_top_labels": ", ".join(l for l, _ in top_labels) if top_labels else None,
            "som_top_associations": ", ".join(a for a, _ in top_assoc) if top_assoc else None,
        }

    return daily_entries, daily_agg


# ── Workout Processing (v1.6.0) ────────────────────────────────────────────────

# Recovery workout types — these are NOT tracked by Strava and represent
# mobility/breathwork/recovery modalities we want to aggregate.
# Maps HealthKit workout name → category for DynamoDB fields.
RECOVERY_WORKOUT_TYPES = {
    # Flexibility / Mobility (Pliability, stretching apps)
    "Flexibility":      "flexibility",
    "flexibility":      "flexibility",
    # Breathwork (Breathwrk, Wim Hof, etc.)
    "Mind and Body":    "breathwork",
    "mind_and_body":    "breathwork",
    "Breathing":        "breathwork",
    "breathing":        "breathwork",
    # Yoga / Pilates
    "Yoga":             "yoga",
    "yoga":             "yoga",
    "Pilates":          "pilates",
    "pilates":          "pilates",
    # Cooldown / Tai Chi
    "Cooldown":         "cooldown",
    "cooldown":         "cooldown",
    "Tai Chi":          "tai_chi",
    "tai_chi":          "tai_chi",
}


def process_workouts(workouts):
    """
    Process workouts from HAE payload (v1.6.0).

    Classifies each workout, stores all to S3, and aggregates
    recovery-type workouts (flexibility, breathwork, yoga, etc.) to DynamoDB.
    Non-recovery workouts (strength, running, cycling) are stored to S3
    for reference but NOT written to DynamoDB to avoid double-counting with Strava.

    Returns:
        daily_workouts: dict of date → list of normalized workout dicts (all types, for S3)
        daily_agg: dict of date → {flexibility_minutes, breathwork_minutes, etc.} (recovery only, for DDB)
    """
    daily_workouts = defaultdict(list)

    for w in workouts:
        date = parse_date_str(w.get("start", ""))
        if not date:
            continue

        name = w.get("name", "Unknown")
        duration_sec = w.get("duration", 0)
        try:
            duration_sec = float(duration_sec)
        except (ValueError, TypeError):
            duration_sec = 0
        duration_min = round(duration_sec / 60, 1)

        # Active energy: prefer summary field, fall back to summing readings
        energy_kcal = 0
        aeb = w.get("activeEnergyBurned", {})
        if isinstance(aeb, dict) and aeb.get("qty") is not None:
            try:
                energy_kcal = round(float(aeb["qty"]), 1)
            except (ValueError, TypeError):
                pass
        elif not energy_kcal:
            ae_readings = w.get("activeEnergy", [])
            if ae_readings:
                energy_kcal = round(sum(float(r.get("qty", 0)) for r in ae_readings), 1)

        category = RECOVERY_WORKOUT_TYPES.get(name, "other")

        workout_record = {
            "id": w.get("id", ""),
            "name": name,
            "category": category,
            "start": w.get("start", ""),
            "end": w.get("end", ""),
            "duration_min": duration_min,
            "active_energy_kcal": energy_kcal,
            "is_indoor": w.get("isIndoor"),
            "is_recovery_type": category != "other",
        }
        daily_workouts[date].append(workout_record)

    # ── Build daily aggregates for recovery workouts only ──
    daily_agg = {}
    for date, wkts in daily_workouts.items():
        recovery = [w for w in wkts if w["is_recovery_type"]]
        if not recovery:
            continue

        agg = {}

        # Per-category minutes and sessions
        cat_minutes = defaultdict(float)
        cat_sessions = defaultdict(int)
        for w in recovery:
            cat = w["category"]
            cat_minutes[cat] += w["duration_min"]
            cat_sessions[cat] += 1

        if cat_minutes.get("flexibility"):
            agg["flexibility_minutes"] = round(cat_minutes["flexibility"], 1)
            agg["flexibility_sessions"] = cat_sessions["flexibility"]

        if cat_minutes.get("breathwork"):
            agg["breathwork_minutes"] = round(cat_minutes["breathwork"], 1)
            agg["breathwork_sessions"] = cat_sessions["breathwork"]

        if cat_minutes.get("yoga"):
            agg["yoga_minutes"] = round(cat_minutes["yoga"], 1)
            agg["yoga_sessions"] = cat_sessions["yoga"]

        if cat_minutes.get("pilates"):
            agg["pilates_minutes"] = round(cat_minutes["pilates"], 1)
            agg["pilates_sessions"] = cat_sessions["pilates"]

        if cat_minutes.get("cooldown"):
            agg["cooldown_minutes"] = round(cat_minutes["cooldown"], 1)

        if cat_minutes.get("tai_chi"):
            agg["tai_chi_minutes"] = round(cat_minutes["tai_chi"], 1)

        # Totals across all recovery types
        total_min = sum(cat_minutes.values())
        agg["recovery_workout_minutes"] = round(total_min, 1)
        agg["recovery_workout_sessions"] = len(recovery)
        agg["recovery_workout_types"] = ", ".join(sorted(set(
            w["category"] for w in recovery
        )))

        daily_agg[date] = agg

    return daily_workouts, daily_agg


def save_workouts_to_s3(date_str, workouts_list):
    """Save individual workout records to S3, merging with existing (v1.6.0)."""
    s3_key = f"raw/{USER_ID}/workouts/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"

    existing = []
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        logger.warning("s3_read_workouts %s: %s", s3_key, e)

    # Deduplicate by workout id
    existing_ids = {w.get("id") for w in existing if w.get("id")}
    new_workouts = [w for w in workouts_list if w.get("id") and w["id"] not in existing_ids]

    if new_workouts:
        merged = existing + new_workouts
        merged.sort(key=lambda w: w.get("start", ""))
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(merged, default=str),
            ContentType="application/json",
        )
        return len(new_workouts)
    return 0


def save_raw_payload(payload):
    """Archive the raw webhook payload to S3."""
    now = datetime.now(timezone.utc)
    s3_key = (
        f"raw/{USER_ID}/health_auto_export/"
        f"{now.strftime('%Y/%m/%d_%H%M%S')}.json"
    )
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(payload, default=str),
        ContentType="application/json",
    )
    return s3_key


# ── Lambda Handler ─────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    """
    Lambda Function URL handler for Health Auto Export webhooks.

    Expects:
      - POST request with JSON body
      - Authorization: Bearer <api_key> header
    """
    _request_start = datetime.now(timezone.utc)
    if hasattr(logger, "set_date"): logger.set_date(_request_start.strftime("%Y-%m-%d"))  # OBS-1
    print(f"Health Auto Export webhook received")

    # ── Auth ──
    headers = event.get("headers", {})
    auth_header = headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header else ""

    # Also check query string for ?key=... (fallback for apps that can't set headers)
    query_params = event.get("queryStringParameters") or {}
    if not token:
        token = query_params.get("key", "")

    if not token:
        print("ERROR: No authorization token provided")
        print(json.dumps({"event": "auth_failure", "reason": "no_token", "request_id": context.aws_request_id if context else "local"}))
        return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"})}

    try:
        expected_key = get_api_key()
        if token != expected_key:
            print("ERROR: Invalid API key")
            return {"statusCode": 403, "body": json.dumps({"error": "Forbidden"})}
    except Exception as e:
        print(f"ERROR: Could not validate API key: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Auth error"})}

    # ── Parse body ──
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError) as e:
        print(f"ERROR: Invalid JSON body: {e}")
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"})}

    # Health Auto Export wraps everything in a "data" key
    data = payload.get("data", payload)
    metrics = data.get("metrics", []) if isinstance(data, dict) else []
    workouts = data.get("workouts", []) if isinstance(data, dict) else []

    print(f"Payload: {len(metrics)} metrics, {len(workouts)} workouts")

    # ── Detect State of Mind payload (v1.5.0) ──
    # HAE sends SoM as a separate Data Type automation, so payload shape differs.
    # If no metrics and no workouts, this might be a State of Mind payload.
    som_daily_entries, som_daily_agg = process_state_of_mind(payload)
    som_entries_new = 0
    som_days = 0

    if som_daily_entries:
        print(f"State of Mind detected: {sum(len(v) for v in som_daily_entries.values())} entries across {len(som_daily_entries)} days")
        for date_str, entries in som_daily_entries.items():
            n = save_state_of_mind_to_s3(date_str, entries)
            som_entries_new += n

        for date_str, agg in som_daily_agg.items():
            merge_day_to_dynamo(date_str, agg)
            som_days += 1

        if som_entries_new:
            print(f"State of Mind: {som_entries_new} new entries saved to S3, {som_days} days updated in DynamoDB")

    # ── Archive raw payload ──
    s3_key = save_raw_payload(payload)
    print(f"Raw payload archived: s3://{S3_BUCKET}/{s3_key}")

    # ── Process blood glucose (CGM) ──
    glucose_metric = None
    for m in metrics:
        metric_name = m.get("name", "")
        if metric_name in ("Blood Glucose", "blood_glucose"):
            glucose_metric = m
            break

    glucose_days = 0
    glucose_readings_new = 0

    if glucose_metric:
        glucose_data = glucose_metric.get("data", [])
        glucose_units = glucose_metric.get("units", "mg/dL")
        print(f"Blood Glucose: {len(glucose_data)} readings, units={glucose_units}")

        daily_agg, daily_readings = process_blood_glucose(glucose_data, glucose_units)

        for date_str, agg in daily_agg.items():
            merge_day_to_dynamo(date_str, agg)
            glucose_days += 1

        for date_str, readings in daily_readings.items():
            n = save_cgm_readings_to_s3(date_str, readings)
            glucose_readings_new += n

        print(f"Glucose: {glucose_days} days updated, {glucose_readings_new} new readings saved")
    else:
        print("No blood glucose data in payload")

    # ── Process other metrics ──
    other_daily = process_generic_metrics(metrics)
    other_days = 0
    for date_str, fields in other_daily.items():
        merge_day_to_dynamo(date_str, fields)
        other_days += 1

    if other_days:
        fields_written = set()
        for fields in other_daily.values():
            fields_written.update(fields.keys())
        print(f"Other metrics: {other_days} days updated, fields: {sorted(fields_written)}")

    # ── Process blood pressure individual readings (v1.4.0 + v1.4.1 combined format) ──
    bp_readings_new = 0

    # v1.4.1: Handle combined "blood_pressure" metric with nested systolic/diastolic
    for m in metrics:
        if m.get("name") in ("blood_pressure", "Blood Pressure"):
            bp_data = m.get("data", [])
            bp_daily = defaultdict(list)
            for reading in bp_data:
                date = parse_date_str(reading.get("date") or reading.get("start"))
                ts = parse_timestamp(reading.get("date") or reading.get("start"))
                sys_val = reading.get("systolic") or reading.get("qty")
                dia_val = reading.get("diastolic")
                if not date or sys_val is None:
                    continue
                bp_daily[date].append({
                    "time": ts,
                    "systolic": round(float(sys_val)),
                    "diastolic": round(float(dia_val)) if dia_val is not None else None,
                    "pulse": round(float(reading.get("pulse", 0))) if reading.get("pulse") else None,
                })
            for date_str, readings in bp_daily.items():
                n = save_bp_readings_to_s3(date_str, readings)
                bp_readings_new += n
                avg_sys = round(sum(r["systolic"] for r in readings) / len(readings))
                avg_dia = round(sum(r["diastolic"] for r in readings if r["diastolic"]) / max(1, len([r for r in readings if r["diastolic"]])))
                merge_day_to_dynamo(date_str, {
                    "bp_systolic": avg_sys,
                    "bp_diastolic": avg_dia,
                    "blood_pressure_systolic": avg_sys,
                    "blood_pressure_diastolic": avg_dia,
                    "blood_pressure_readings_count": len(readings),
                })
            if bp_readings_new:
                print(f"Blood Pressure: {bp_readings_new} new readings saved (combined format)")
            break

    # v1.4.0: Handle separate systolic/diastolic metrics
    if bp_readings_new == 0:
        for m in metrics:
            if m.get("name") in ("Blood Pressure Systolic", "blood_pressure_systolic"):
                bp_sys_data = m.get("data", [])
                bp_dia_data = []
                bp_pulse_data = []
                for m2 in metrics:
                    if m2.get("name") in ("Blood Pressure Diastolic", "blood_pressure_diastolic"):
                        bp_dia_data = m2.get("data", [])
                    elif m2.get("name") in ("Blood Pressure Pulse", "blood_pressure_pulse"):
                        bp_pulse_data = m2.get("data", [])
                bp_daily = defaultdict(list)
                dia_by_time = {parse_timestamp(r.get("date")): r.get("qty") for r in bp_dia_data if r.get("qty") is not None}
                pulse_by_time = {parse_timestamp(r.get("date")): r.get("qty") for r in bp_pulse_data if r.get("qty") is not None}
                for reading in bp_sys_data:
                    date = parse_date_str(reading.get("date"))
                    ts = parse_timestamp(reading.get("date"))
                    sys_val = reading.get("qty")
                    if not date or sys_val is None:
                        continue
                    bp_daily[date].append({
                        "time": ts,
                        "systolic": round(float(sys_val)),
                        "diastolic": round(float(dia_by_time.get(ts, 0))) if dia_by_time.get(ts) else None,
                        "pulse": round(float(pulse_by_time.get(ts, 0))) if pulse_by_time.get(ts) else None,
                    })
                for date_str, readings in bp_daily.items():
                    n = save_bp_readings_to_s3(date_str, readings)
                    bp_readings_new += n
                    merge_day_to_dynamo(date_str, {"blood_pressure_readings_count": len(readings)})
                if bp_readings_new:
                    print(f"Blood Pressure: {bp_readings_new} new readings saved to S3")
            break

    # ── Process workouts (v1.6.0) ──
    workout_days = 0
    workout_new = 0
    recovery_days = 0

    if workouts:
        daily_workouts, workout_daily_agg = process_workouts(workouts)

        # Log workout types found
        all_types = set()
        for wkts in daily_workouts.values():
            for w in wkts:
                all_types.add(f"{w['name']} ({w['category']})")
        print(f"Workout types found: {sorted(all_types)}")

        # Save ALL workouts to S3 (including non-recovery, for reference)
        for date_str, wkts in daily_workouts.items():
            n = save_workouts_to_s3(date_str, wkts)
            if n > 0:
                workout_new += n
                workout_days += 1

        # Write recovery-type aggregates to DynamoDB
        for date_str, agg in workout_daily_agg.items():
            merge_day_to_dynamo(date_str, agg)
            recovery_days += 1

        if workout_new or recovery_days:
            print(f"Workouts: {workout_new} new saved to S3 across {workout_days} days, "
                  f"{recovery_days} days with recovery aggregates written to DynamoDB")
    else:
        print("No workouts in payload")

    # ── Summary ──
    duration_ms = int((datetime.now(timezone.utc) - _request_start).total_seconds() * 1000) if _request_start else 0
    result = {
        "glucose_days_updated": glucose_days,
        "glucose_new_readings": glucose_readings_new,
        "other_metric_days": other_days,
        "som_entries_new": som_entries_new,
        "som_days_updated": som_days,
        "workout_days": workout_days,
        "workout_new": workout_new,
        "recovery_days": recovery_days,
        "metrics_received": [m.get("name") for m in metrics],
        "workouts_received": len(workouts),
        "raw_archive": s3_key,
    }
    print(f"Result: {json.dumps(result)}")

    # Structured log line for CloudWatch Insights queries
    structured_log = {
        "event": "webhook_complete",
        "request_id": context.aws_request_id if context else "local",
        "metrics_count": len(metrics),
        "workouts_count": len(workouts),
        "glucose_days": glucose_days,
        "glucose_readings_new": glucose_readings_new,
        "other_metric_days": other_days,
        "som_entries_new": som_entries_new,
        "som_days": som_days,
        "workout_new": workout_new,
        "recovery_days": recovery_days,
        "matched_metrics": len([m for m in metrics if m.get("name") in METRIC_MAP]),
        "skipped_sot": len([m for m in metrics if m.get("name") in SKIP_METRICS]),
        "duration_ms": duration_ms,
        "payload_bytes": len(body) if isinstance(body, str) else 0,
    }
    print(json.dumps(structured_log))

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok", **result}),
    }
