"""
MacroFactor data ingestion Lambda — Diary + Workout Export format.

Trigger: S3 ObjectCreated on s3://matthew-life-platform/uploads/macrofactor/*.csv

Auto-detects CSV type from headers:
  - "Food Name" header → nutrition diary (one row per food entry)
  - "Exercise" + "Set Type" header → workout log (one row per set)

Each invocation processes the full uploaded CSV and upserts one DynamoDB
item per day. Fully idempotent.

v1.1.0 — Added workout CSV support (merged from backfill_macrofactor_workouts.py)
"""

import json
import os
import logging
import csv
import io
import boto3
from collections import defaultdict, OrderedDict
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION         = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET      = os.environ.get("S3_BUCKET", "matthew-life-platform")
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ.get("USER_ID", "matthew")
PK             = f"USER#{USER_ID}#SOURCE#macrofactor"
PK_WORKOUTS    = f"USER#{USER_ID}#SOURCE#macrofactor_workouts"

s3_client = boto3.client("s3", region_name=REGION)
dynamodb  = boto3.resource("dynamodb", region_name=REGION)
table     = dynamodb.Table(DYNAMODB_TABLE)

NUTRIENT_COLUMNS = OrderedDict([
    ("Calories (kcal)",          "calories_kcal"),
    ("Protein (g)",              "protein_g"),
    ("Carbs (g)",                "carbs_g"),
    ("Fat (g)",                  "fat_g"),
    ("Fiber (g)",                "fiber_g"),
    ("Alcohol (g)",              "alcohol_g"),
    ("Saturated Fat (g)",        "saturated_fat_g"),
    ("Monounsaturated Fat (g)",  "monounsaturated_fat_g"),
    ("Polyunsaturated Fat (g)",  "polyunsaturated_fat_g"),
    ("Trans Fat (g)",            "trans_fat_g"),
    ("Omega-3 (g)",              "omega3_total_g"),
    ("Omega-3 ALA (g)",          "omega3_ala_g"),
    ("Omega-3 DHA (g)",          "omega3_dha_g"),
    ("Omega-3 EPA (g)",          "omega3_epa_g"),
    ("Omega-6 (g)",              "omega6_g"),
    ("Sugars (g)",               "sugars_g"),
    ("Sugars Added (g)",         "sugars_added_g"),
    ("Starch (g)",               "starch_g"),
    ("Sodium (mg)",              "sodium_mg"),
    ("Potassium (mg)",           "potassium_mg"),
    ("Calcium (mg)",             "calcium_mg"),
    ("Magnesium (mg)",           "magnesium_mg"),
    ("Iron (mg)",                "iron_mg"),
    ("Zinc (mg)",                "zinc_mg"),
    ("Phosphorus (mg)",          "phosphorus_mg"),
    ("Selenium (mcg)",           "selenium_mcg"),
    ("Manganese (mg)",           "manganese_mg"),
    ("Copper (mg)",              "copper_mg"),
    ("Vitamin A (mcg)",          "vitamin_a_mcg"),
    ("Vitamin C (mg)",           "vitamin_c_mg"),
    ("Vitamin D (mcg)",          "vitamin_d_mcg"),
    ("Vitamin E (mg)",           "vitamin_e_mg"),
    ("Vitamin K (mcg)",          "vitamin_k_mcg"),
    ("B1, Thiamine (mg)",        "b1_thiamine_mg"),
    ("B2, Riboflavin (mg)",      "b2_riboflavin_mg"),
    ("B3, Niacin (mg)",          "b3_niacin_mg"),
    ("B5, Pantothenic Acid (mg)","b5_pantothenic_mg"),
    ("B6, Pyridoxine (mg)",      "b6_pyridoxine_mg"),
    ("B12, Cobalamin (mcg)",     "b12_cobalamin_mcg"),
    ("Folate (mcg)",             "folate_mcg"),
    ("Caffeine (mg)",            "caffeine_mg"),
    ("Cholesterol (mg)",         "cholesterol_mg"),
    ("Choline (mg)",             "choline_mg"),
    ("Water (g)",                "water_g"),
    ("Histidine (g)",            "aa_histidine_g"),
    ("Isoleucine (g)",           "aa_isoleucine_g"),
    ("Leucine (g)",              "aa_leucine_g"),
    ("Lysine (g)",               "aa_lysine_g"),
    ("Methionine (g)",           "aa_methionine_g"),
    ("Cysteine (g)",             "aa_cysteine_g"),
    ("Phenylalanine (g)",        "aa_phenylalanine_g"),
    ("Threonine (g)",            "aa_threonine_g"),
    ("Tryptophan (g)",           "aa_tryptophan_g"),
    ("Tyrosine (g)",             "aa_tyrosine_g"),
    ("Valine (g)",               "aa_valine_g"),
])
NUTRIENT_FIELD_NAMES = set(NUTRIENT_COLUMNS.values())
COL_TO_FIELD         = dict(NUTRIENT_COLUMNS)


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(i) for i in obj]
    return obj


def safe_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "-", "N/A", "n/a"):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def parse_entry(row):
    date_str  = row.get("Date", "").strip()
    food_name = row.get("Food Name", "").strip()
    if not date_str or not food_name:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            date_str = datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    else:
        return None

    nutrients = {COL_TO_FIELD[col]: safe_float(row.get(col))
                 for col in COL_TO_FIELD if safe_float(row.get(col)) is not None}
    entry = {k: v for k, v in {
        "food_name":    food_name,
        "time":         row.get("Time", "").strip() or None,
        "serving_size": row.get("Serving Size", "").strip() or None,
        "serving_qty":  safe_float(row.get("Serving Qty")),
        "serving_wt_g": safe_float(row.get("Serving Weight (g)")),
        **nutrients,
    }.items() if v is not None}
    return date_str, entry



# ── Protein Distribution (Derived Metrics Phase 1d) ──────────────────────────
# Norton/Galpin: ≥30g protein per meal to maximize MPS via leucine threshold.
# Snacks (<400 kcal) excluded — only real meals count toward the score.
MEAL_CALORIE_THRESHOLD = 400  # kcal — eating occasions below this are "snacks"
PROTEIN_MPS_THRESHOLD = 30    # grams — minimum per meal for MPS


def compute_protein_distribution(food_log):
    """
    Group food_log entries into meals by 30-min time proximity.
    Exclude snacks (<MEAL_CALORIE_THRESHOLD kcal) from scoring.
    Returns (score_pct, meals_above_30g, total_meals, total_snacks).
    """
    if not food_log:
        return None, 0, 0, 0

    # Parse times, protein, and calories
    timed_entries = []
    for entry in food_log:
        time_str = entry.get("time")
        protein = entry.get("protein_g")
        calories = entry.get("calories_kcal")
        if not time_str or protein is None:
            continue
        try:
            parts = time_str.split(":")
            minutes_from_midnight = int(parts[0]) * 60 + int(parts[1])
            timed_entries.append((minutes_from_midnight, float(protein), float(calories or 0)))
        except (ValueError, IndexError):
            continue

    if not timed_entries:
        return None, 0, 0, 0

    timed_entries.sort(key=lambda x: x[0])

    # Group into eating occasions: entries within 30 min = same occasion
    occasions = []  # list of (total_protein, total_calories)
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

    # Separate meals from snacks
    meals = [(p, c) for p, c in occasions if c >= MEAL_CALORIE_THRESHOLD]
    total_snacks = len(occasions) - len(meals)
    total_meals = len(meals)

    if total_meals == 0:
        # All eating occasions were snacks — return 0 score with context
        return 0.0, 0, 0, total_snacks

    above_30g = sum(1 for p, c in meals if p >= PROTEIN_MPS_THRESHOLD)
    score = round(above_30g / total_meals * 100, 1)

    return score, above_30g, total_meals, total_snacks



# ── Micronutrient Sufficiency (Derived Metrics Phase 1e) ─────────────────────
# Board of Directors consensus targets for adult male, active, weight loss phase.
MICRONUTRIENT_TARGETS = {
    "fiber_g":         {"target": 38,   "label": "Fiber"},
    "potassium_mg":    {"target": 3400, "label": "Potassium"},
    "magnesium_mg":    {"target": 420,  "label": "Magnesium"},
    "vitamin_d_mcg":   {"target": 100,  "label": "Vitamin D"},   # 4000 IU
    "omega3_total_g":  {"target": 3,    "label": "Omega-3"},
}


def compute_micronutrient_sufficiency(totals_prefixed):
    """
    Compute per-nutrient sufficiency as % of optimal daily target.
    Returns (sufficiency_map, avg_pct) or (None, None) if no data.
    
    sufficiency_map: {nutrient_key: {"actual": float, "target": float, "pct": float}}
    Pct is capped at 100 — exceeding target still scores 100%.
    """
    sufficiency = {}
    pcts = []

    for nutrient_key, config in MICRONUTRIENT_TARGETS.items():
        total_key = f"total_{nutrient_key}"
        actual = totals_prefixed.get(total_key)
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


def build_day_items(rows):
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
    print(f"Skipped {skipped} blank rows. Parsed {len(days)} unique days.")

    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_items = {}
    for date_str, data in days.items():
        totals_prefixed = {f"total_{k}": round(v, 2)
                           for k, v in data["totals"].items() if v != 0}
        food_log = sorted(data["entries"], key=lambda e: e.get("time") or "00:00")
        # ── Protein distribution (Phase 1d) ──
        pds_score, pds_above, pds_total, pds_snacks = compute_protein_distribution(food_log)
        # ── Micronutrient sufficiency (Phase 1e) ──
        micro_suff, micro_avg = compute_micronutrient_sufficiency(totals_prefixed)


        item = {
            "pk":             PK,
            "sk":             f"DATE#{date_str}",
            "date":           date_str,
            "source":         "macrofactor",
            "schema_version": 1,
            "ingested_at":    ingested_at,
            "entries_count": len(food_log),
            "food_log":      food_log,
            **totals_prefixed,
            **({"protein_distribution_score": pds_score,
                "meals_above_30g_protein": pds_above,
                "total_meals": pds_total,
                "total_snacks": pds_snacks} if pds_score is not None else {}),
            **({"micronutrient_sufficiency": micro_suff,
                "micronutrient_avg_pct": micro_avg} if micro_suff is not None else {}),
        }
        day_items[date_str] = item
    return day_items


def safe_int(val):
    v = safe_float(val)
    return int(v) if v is not None else None


def parse_duration_min(val):
    """Parse MacroFactor workout duration string → float minutes."""
    if not val or not str(val).strip():
        return None
    s = str(val).strip()
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
    if ':' in s:
        parts = s.split(':')
        if len(parts) == 3:
            return round(int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60, 1)
        if len(parts) == 2:
            return round(int(parts[0]) + int(parts[1]) / 60, 1)
    try:
        return round(float(s), 1)
    except ValueError:
        return None


def build_workout_day_items(rows):
    """Group set-level rows → exercises → workouts → days."""
    rows = [r for r in rows if r.get("Date", "").strip() and r.get("Exercise", "").strip()]
    if not rows:
        return {}

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

    day_workouts = defaultdict(list)
    for (date_str, workout_name, duration_raw), set_rows in workout_sets.items():
        exercise_sets = defaultdict(list)
        for row in set_rows:
            exercise_sets[row.get("Exercise", "").strip()].append(row)

        exercises = []
        for ex_name, ex_rows in exercise_sets.items():
            base_weight = safe_float(ex_rows[0].get("Exercise Base Weight (lbs)"))
            sets = []
            for i, row in enumerate(ex_rows, 1):
                s = {k: v for k, v in {
                    "set_index":        i,
                    "set_type":         row.get("Set Type", "").strip() or "normal",
                    "weight_lbs":       safe_float(row.get("Weight (lbs)")),
                    "reps":             safe_int(row.get("Reps")),
                    "rir":              safe_int(row.get("RIR")),
                    "set_duration_sec": safe_int(row.get("Duration")),
                    "distance_yards":   safe_float(row.get("Distance short (Yd)")),
                    "distance_miles":   safe_float(row.get("Distance long (Mi)")),
                }.items() if v is not None}
                sets.append(s)

            ex_entry = {"exercise_name": ex_name, "sets": sets}
            if base_weight is not None:
                ex_entry["base_weight_lbs"] = base_weight
            exercises.append(ex_entry)

        workout = {k: v for k, v in {
            "workout_name":         workout_name or "Workout",
            "workout_duration_min": parse_duration_min(duration_raw),
            "exercises":            exercises,
        }.items() if v is not None}
        day_workouts[date_str].append(workout)

    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_items = {}
    for date_str, workouts in day_workouts.items():
        total_sets = 0
        total_volume = 0.0
        all_exercises = set()
        for w in workouts:
            for ex in w["exercises"]:
                all_exercises.add(ex["exercise_name"])
                for s in ex["sets"]:
                    total_sets += 1
                    total_volume += (s.get("weight_lbs") or 0) * (s.get("reps") or 0)

        day_items[date_str] = {
            "pk":               PK_WORKOUTS,
            "sk":               f"DATE#{date_str}",
            "date":             date_str,
            "source":           "macrofactor_workouts",
            "schema_version":   1,
            "ingested_at":      ingested_at,
            "workouts_count":   len(workouts),
            "total_sets":       total_sets,
            "total_volume_lbs": round(total_volume, 1),
            "unique_exercises":  len(all_exercises),
            "workouts":         workouts,
        }
    return day_items


def detect_csv_type(headers):
    """Detect whether CSV is nutrition diary or workout export."""
    if "Food Name" in headers:
        return "nutrition"
    if "Exercise" in headers and "Set Type" in headers:
        return "workout"
    return "unknown"


def archive_raw(bucket, source_key, content_bytes, subfolder=""):
    from datetime import datetime, timezone
    now     = datetime.now(timezone.utc)
    import os
    fname   = os.path.basename(source_key)
    sub     = f"/{subfolder}" if subfolder else ""
    dest    = f"raw/macrofactor{sub}/{now.strftime('%Y/%m')}/{fname}"
    s3_client.put_object(Bucket=bucket, Key=dest, Body=content_bytes, ContentType="text/csv")
    print(f"Archived to s3://{bucket}/{dest}")


def lambda_handler(event, context):
    print(f"Event: {json.dumps(event)}")

    if "Records" in event:
        record     = event["Records"][0]
        bucket     = record["s3"]["bucket"]["name"]
        source_key = record["s3"]["object"]["key"]
    elif "bucket" in event and "key" in event:
        bucket, source_key = event["bucket"], event["key"]
    else:
        return {"statusCode": 400, "body": "No S3 record in event"}

    print(f"Processing s3://{bucket}/{source_key}")
    response      = s3_client.get_object(Bucket=bucket, Key=source_key)
    content_bytes = response["Body"].read()
    print(f"Downloaded {len(content_bytes):,} bytes")

    text   = content_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows   = list(reader)
    print(f"CSV rows: {len(rows)}")

    if not rows:
        print("Empty CSV — skipping")
        return {"statusCode": 200, "body": "Empty CSV"}

    csv_type = detect_csv_type(rows[0].keys())
    print(f"Detected CSV type: {csv_type}")

    if csv_type == "nutrition":
        archive_raw(bucket, source_key, content_bytes)
        day_items = build_day_items(rows)
    elif csv_type == "workout":
        archive_raw(bucket, source_key, content_bytes, subfolder="workouts")
        day_items = build_workout_day_items(rows)
    else:
        print(f"Unknown CSV format. Headers: {list(rows[0].keys())[:10]}")
        return {"statusCode": 200, "body": "Unknown CSV format — skipped"}

    written = 0
    for date_str_key, item in day_items.items():
        # ── Item size estimation + CloudWatch metric (P1.10) ─────────────────────
        item_json = json.dumps(floats_to_decimal(item), default=str)
        item_size_kb = len(item_json.encode('utf-8')) / 1024
        if item_size_kb > 350:
            print(f"[SIZE-WARNING] ⚠️ MacroFactor item for {date_str_key} is {item_size_kb:.0f}KB — approaching 400KB DynamoDB limit!")
        elif item_size_kb > 250:
            print(f"[SIZE-INFO] MacroFactor item for {date_str_key} is {item_size_kb:.0f}KB")
        try:
            cw = boto3.client("cloudwatch", region_name=REGION)
            cw.put_metric_data(
                Namespace="LifePlatform/Ingestion",
                MetricData=[{
                    "MetricName": "DynamoDBItemSizeKB",
                    "Dimensions": [{"Name": "Source", "Value": "macrofactor"}],
                    "Value": item_size_kb,
                    "Unit": "Kilobytes",
                }],
            )
        except Exception as e:
            print(f"[WARN] CloudWatch item size metric failed (non-fatal): {e}")
        table.put_item(Item=floats_to_decimal(item))
        written += 1

    print(f"Written {written} DynamoDB items ({csv_type})")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "source_file":  source_key,
            "csv_type":     csv_type,
            "rows_parsed":  len(rows),
            "days_written": written,
        })
    }
