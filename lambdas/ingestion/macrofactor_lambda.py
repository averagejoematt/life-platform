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

import csv
import io
import json
import logging
import math
import os
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import boto3
from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from common.platform_logger import get_logger

    logger = get_logger("macrofactor")
except ImportError:
    logger = logging.getLogger("macrofactor")
    logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
PK = f"USER#{USER_ID}#SOURCE#macrofactor"
PK_WORKOUTS = f"USER#{USER_ID}#SOURCE#macrofactor_workouts"

s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

NUTRIENT_COLUMNS = OrderedDict(
    [
        ("Calories (kcal)", "calories_kcal"),
        ("Protein (g)", "protein_g"),
        ("Carbs (g)", "carbs_g"),
        ("Fat (g)", "fat_g"),
        ("Fiber (g)", "fiber_g"),
        ("Alcohol (g)", "alcohol_g"),
        ("Saturated Fat (g)", "saturated_fat_g"),
        ("Monounsaturated Fat (g)", "monounsaturated_fat_g"),
        ("Polyunsaturated Fat (g)", "polyunsaturated_fat_g"),
        ("Trans Fat (g)", "trans_fat_g"),
        ("Omega-3 (g)", "omega3_total_g"),
        ("Omega-3 ALA (g)", "omega3_ala_g"),
        ("Omega-3 DHA (g)", "omega3_dha_g"),
        ("Omega-3 EPA (g)", "omega3_epa_g"),
        ("Omega-6 (g)", "omega6_g"),
        ("Sugars (g)", "sugars_g"),
        ("Sugars Added (g)", "sugars_added_g"),
        ("Starch (g)", "starch_g"),
        ("Sodium (mg)", "sodium_mg"),
        ("Potassium (mg)", "potassium_mg"),
        ("Calcium (mg)", "calcium_mg"),
        ("Magnesium (mg)", "magnesium_mg"),
        ("Iron (mg)", "iron_mg"),
        ("Zinc (mg)", "zinc_mg"),
        ("Phosphorus (mg)", "phosphorus_mg"),
        ("Selenium (mcg)", "selenium_mcg"),
        ("Manganese (mg)", "manganese_mg"),
        ("Copper (mg)", "copper_mg"),
        ("Vitamin A (mcg)", "vitamin_a_mcg"),
        ("Vitamin C (mg)", "vitamin_c_mg"),
        ("Vitamin D (mcg)", "vitamin_d_mcg"),
        ("Vitamin E (mg)", "vitamin_e_mg"),
        ("Vitamin K (mcg)", "vitamin_k_mcg"),
        ("B1, Thiamine (mg)", "b1_thiamine_mg"),
        ("B2, Riboflavin (mg)", "b2_riboflavin_mg"),
        ("B3, Niacin (mg)", "b3_niacin_mg"),
        ("B5, Pantothenic Acid (mg)", "b5_pantothenic_mg"),
        ("B6, Pyridoxine (mg)", "b6_pyridoxine_mg"),
        ("B12, Cobalamin (mcg)", "b12_cobalamin_mcg"),
        ("Folate (mcg)", "folate_mcg"),
        ("Caffeine (mg)", "caffeine_mg"),
        ("Cholesterol (mg)", "cholesterol_mg"),
        ("Choline (mg)", "choline_mg"),
        ("Water (g)", "water_g"),
        ("Histidine (g)", "aa_histidine_g"),
        ("Isoleucine (g)", "aa_isoleucine_g"),
        ("Leucine (g)", "aa_leucine_g"),
        ("Lysine (g)", "aa_lysine_g"),
        ("Methionine (g)", "aa_methionine_g"),
        ("Cysteine (g)", "aa_cysteine_g"),
        ("Phenylalanine (g)", "aa_phenylalanine_g"),
        ("Threonine (g)", "aa_threonine_g"),
        ("Tryptophan (g)", "aa_tryptophan_g"),
        ("Tyrosine (g)", "aa_tyrosine_g"),
        ("Valine (g)", "aa_valine_g"),
    ]
)
NUTRIENT_FIELD_NAMES = set(NUTRIENT_COLUMNS.values())
COL_TO_FIELD = dict(NUTRIENT_COLUMNS)


# Phase 4.2 (2026-05-16): canonical impl in lambdas/numeric.py.
try:
    from common.numeric import floats_to_decimal  # noqa: F401
except ImportError:
    if not TYPE_CHECKING:  # mypy sees ONE signature (the import); runtime unchanged (#1656)

        def floats_to_decimal(obj):
            if isinstance(obj, bool):
                return obj
            if isinstance(obj, float):
                return Decimal(str(obj))
            if isinstance(obj, dict):
                return {k: floats_to_decimal(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [floats_to_decimal(i) for i in obj]
            return obj


# #970 KEPT (deliberate): CSV-value coercion contract (val) with string sanitation
# ("-", "N/A", thousands commas), not digest_utils' record-field contract.
def safe_float(val):
    """A CSV cell → float, or None when the cell holds no usable number.

    The export is HAND-UPLOADED, so every cell is untrusted input and this is the
    single coercion chokepoint for the whole module (safe_int and every nutrient
    total route through it). Non-finite literals are absence, not numbers:
    'nan'/'inf' are what a pandas/spreadsheet round-trip writes for an empty cell,
    `float()` accepts them silently, and a NaN then poisons the day total —
    `common.numeric.floats_to_decimal` maps the non-finite result to None (#1207),
    so ONE 'nan' cell stores a real logged day with total_calories_kcal = None.
    """
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "-", "N/A", "n/a"):
        return None
    try:
        parsed = float(s.replace(",", ""))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")


def normalize_date(raw):
    """A CSV date cell → ISO `YYYY-MM-DD`, or None when no known format matches.

    ONE date contract for all three export formats. Before this existed the three
    parsers disagreed on the same cell: the diary dropped an unparseable date, the
    workout loop fell through and used it VERBATIM as the partition key
    (sk='DATE#April 4, 2026' — the TD-19 mis-partition class), and the summary
    parser only checked that positions 4 and 7 held dashes, so it accepted both a
    trailing time component ('2026-08-05 00:00:00' — the usual XLSX round-trip
    form) and an impossible month ('13/04/2026' → '2026-13-04'). A row keyed on
    any of those is invisible to every `DATE#`-keyed reader.

    A time component is stripped rather than rejected: the day is unambiguous, so
    dropping the row would lose real logged data.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    stem = s.split("T", 1)[0].split(" ", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(stem, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_entry(row):
    date_str = normalize_date(row.get("Date"))
    food_name = row.get("Food Name", "").strip()
    if not date_str or not food_name:
        return None

    nutrients = {COL_TO_FIELD[col]: safe_float(row.get(col)) for col in COL_TO_FIELD if safe_float(row.get(col)) is not None}
    entry = {
        k: v
        for k, v in {
            "food_name": food_name,
            "time": row.get("Time", "").strip() or None,
            "serving_size": row.get("Serving Size", "").strip() or None,
            "serving_qty": safe_float(row.get("Serving Qty")),
            "serving_wt_g": safe_float(row.get("Serving Weight (g)")),
            **nutrients,
        }.items()
        if v is not None
    }
    return date_str, entry


# ── Protein Distribution (Derived Metrics Phase 1d) ──────────────────────────
# Norton/Galpin: ≥30g protein per meal to maximize MPS via leucine threshold.
# Snacks (<400 kcal) excluded — only real meals count toward the score.
MEAL_CALORIE_THRESHOLD = 400  # kcal — eating occasions below this are "snacks"
PROTEIN_MPS_THRESHOLD = 30  # grams — minimum per meal for MPS


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
    "fiber_g": {"target": 38, "label": "Fiber"},
    "potassium_mg": {"target": 3400, "label": "Potassium"},
    "magnesium_mg": {"target": 420, "label": "Magnesium"},
    "vitamin_d_mcg": {"target": 100, "label": "Vitamin D"},  # 4000 IU
    "omega3_total_g": {"target": 3, "label": "Omega-3"},
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
        # ADR-104: a key exists in `totals` ONLY if some entry logged that nutrient
        # (the accumulator above skips None), so absence is already absent and no
        # value filter is needed. The old `if v != 0` filter dropped a genuinely
        # logged zero — 0 g alcohol, 0 g added sugar — leaving readers unable to
        # tell "logged none" from "never tracked": the exact inversion of the rule
        # it was reaching for.
        totals_prefixed = {f"total_{k}": round(v, 2) for k, v in data["totals"].items()}
        food_log = sorted(data["entries"], key=lambda e: e.get("time") or "00:00")
        # ── Protein distribution (Phase 1d) ──
        pds_score, pds_above, pds_total, pds_snacks = compute_protein_distribution(food_log)
        # ── Micronutrient sufficiency (Phase 1e) ──
        micro_suff, micro_avg = compute_micronutrient_sufficiency(totals_prefixed)

        item = {
            "pk": PK,
            "sk": f"DATE#{date_str}",
            "date": date_str,
            "source": "macrofactor",
            "schema_version": 1,
            "ingested_at": ingested_at,
            "entries_count": len(food_log),
            "food_log": food_log,
            **totals_prefixed,
            **(
                {
                    "protein_distribution_score": pds_score,
                    "meals_above_30g_protein": pds_above,
                    "total_meals": pds_total,
                    "total_snacks": pds_snacks,
                }
                if pds_score is not None
                else {}
            ),
            **({"micronutrient_sufficiency": micro_suff, "micronutrient_avg_pct": micro_avg} if micro_suff is not None else {}),
        }
        day_items[date_str] = item
    return day_items


def safe_int(val):
    # int() is safe here only because safe_float rejects non-finite values —
    # int(float('nan')) raises ValueError, so a 'nan' Reps/RIR cell used to
    # abort the workout ingest from three call sites at once.
    v = safe_float(val)
    return int(v) if v is not None else None


def parse_duration_min(val):
    """Parse a MacroFactor workout duration cell → float minutes, or None.

    Unparseable degrades to absence, NEVER to an exception. Only the final bare-
    number coercion used to be guarded, so a cell that merely CONTAINED an 'h'/'m'
    or a ':' took an unguarded path: '45 mins' became float('45 ins') and '1:ab'
    became int('ab'). Either raised ValueError out of build_workout_day_items and
    aborted the whole upload — one malformed cell losing every other workout in
    the file.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        if "h" in s or "m" in s:
            hours = minutes = 0.0
            rest = s
            if "h" in rest:
                h_part, rest = rest.split("h", 1)
                hours = float(h_part.strip()) if h_part.strip() else 0.0
            if "m" in rest:
                m_part = rest.replace("m", "").strip()
                minutes = float(m_part) if m_part else 0.0
            total = hours * 60 + minutes
        elif ":" in s:
            parts = s.split(":")
            if len(parts) == 3:
                total = int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
            elif len(parts) == 2:
                total = int(parts[0]) + int(parts[1]) / 60
            else:
                return None
        else:
            total = float(s)
    except (ValueError, TypeError):
        return None
    return round(total, 1) if math.isfinite(total) else None


def build_workout_day_items(rows):
    """Group set-level rows → exercises → workouts → days."""
    rows = [r for r in rows if r.get("Date", "").strip() and r.get("Exercise", "").strip()]
    if not rows:
        return {}

    workout_sets = defaultdict(list)
    skipped_dates = 0
    for row in rows:
        date_str = normalize_date(row["Date"])
        if date_str is None:
            # A date this parser cannot read must NEVER become the partition key:
            # the old loop had no `else`, so it wrote sk='DATE#April 4, 2026' — a
            # row no DATE#-keyed reader can ever see (the TD-19 class).
            skipped_dates += 1
            continue
        key = (date_str, row.get("Workout", "").strip(), row.get("Workout Duration", "").strip())
        workout_sets[key].append(row)
    if skipped_dates:
        print(f"Skipped {skipped_dates} workout rows with an unreadable Date.")

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
                s = {
                    k: v
                    for k, v in {
                        "set_index": i,
                        "set_type": row.get("Set Type", "").strip() or "normal",
                        "weight_lbs": safe_float(row.get("Weight (lbs)")),
                        "reps": safe_int(row.get("Reps")),
                        "rir": safe_int(row.get("RIR")),
                        "set_duration_sec": safe_int(row.get("Duration")),
                        "distance_yards": safe_float(row.get("Distance short (Yd)")),
                        "distance_miles": safe_float(row.get("Distance long (Mi)")),
                    }.items()
                    if v is not None
                }
                sets.append(s)

            ex_entry = {"exercise_name": ex_name, "sets": sets}
            if base_weight is not None:
                ex_entry["base_weight_lbs"] = base_weight
            exercises.append(ex_entry)

        workout = {
            k: v
            for k, v in {
                "workout_name": workout_name or "Workout",
                "workout_duration_min": parse_duration_min(duration_raw),
                "exercises": exercises,
            }.items()
            if v is not None
        }
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
            "pk": PK_WORKOUTS,
            "sk": f"DATE#{date_str}",
            "date": date_str,
            "source": "macrofactor_workouts",
            "schema_version": 1,
            "ingested_at": ingested_at,
            "workouts_count": len(workouts),
            "total_sets": total_sets,
            "total_volume_lbs": round(total_volume, 1),
            "unique_exercises": len(all_exercises),
            "workouts": workouts,
        }
    return day_items


def detect_csv_type(headers):
    """Detect whether CSV is nutrition diary, workout export, or daily summary."""
    if "Food Name" in headers:
        return "nutrition"
    if "Exercise" in headers and "Set Type" in headers:
        return "workout"
    # Reentry sweep (2026-05-03): MacroFactor changed default export to a daily-
    # summary format (one row per day with Calories/Protein/Fat/Carbs/Weight/
    # Expenditure). Pre-fix the Lambda silently rejected it as "unknown" — that's
    # why MacroFactor data was 22-day stale. Detect by Expenditure + Date columns.
    if "Expenditure" in headers and "Date" in headers and "Calories (kcal)" in headers:
        return "daily_summary"
    return "unknown"


def build_summary_day_items(rows):
    """Parse MacroFactor daily-summary CSV → DDB items.

    Reentry sweep (2026-05-03): one row per date with daily totals (no per-meal
    food log). Writes the same DATE# partition as the nutrition format with the
    same total_* field names. We use UpdateItem patterns implicitly via the
    standard PutItem path — for days that previously had food_log entries from
    a diary export, the food_log will be lost. This is acceptable: (a) Matthew
    rarely uses both formats for the same day, (b) the totals are what
    daily-metrics-compute consumes, and (c) the spec explicitly removed
    nutrition diary as MacroFactor's default in favor of summary.
    """
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day_items = {}
    skipped = 0
    from datetime import timedelta as _td

    EXCEL_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)  # Excel-1900 system, accounting for 1900 leap-year bug
    for row in rows:
        date_str = (row.get("Date") or "").strip()
        if not date_str:
            skipped += 1
            continue
        # Reentry sweep (2026-05-03): MacroFactor's XLSX export stores dates as
        # Excel serial numbers (e.g. 46110 = 2026-04-04). Our XLSX→CSV converter
        # in dropbox-poll preserves the raw value. Detect numeric date values
        # and convert to YYYY-MM-DD here.
        try:
            n = float(date_str)
            if 30000 < n < 80000:  # Excel serial range covering 1982 → 2119
                d = EXCEL_EPOCH + _td(days=int(n))
                date_str = d.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
        # One date contract with the diary + workout parsers (normalize_date):
        # slash forms, a trailing time component, and a real calendar check. The
        # old inline handling built the ISO string with int() casts and then only
        # asserted "length >= 10 with dashes at 4 and 7", so '2026-08-05 00:00:00'
        # and '13/04/2026' -> '2026-13-04' both passed straight into the sort key.
        iso_date = normalize_date(date_str)
        if iso_date is None:
            skipped += 1
            continue
        date_str = iso_date

        cal = safe_float(row.get("Calories (kcal)"))
        prot = safe_float(row.get("Protein (g)"))
        fat = safe_float(row.get("Fat (g)"))
        carbs = safe_float(row.get("Carbs (g)"))
        weight = safe_float(row.get("Weight (lbs)"))
        trend_weight = safe_float(row.get("Trend Weight (lbs)"))
        expenditure = safe_float(row.get("Expenditure"))
        target_cal = safe_float(row.get("Target Calories (kcal)"))
        target_prot = safe_float(row.get("Target Protein (g)"))

        # Skip rows with no nutrition data (MacroFactor sometimes exports empty future days)
        if all(v is None or v == 0 for v in (cal, prot, fat, carbs)):
            skipped += 1
            continue

        item = {
            "pk": PK,
            "sk": f"DATE#{date_str}",
            "date": date_str,
            "source": "macrofactor",
            "schema_version": 2,  # bumped from 1 to mark summary-format records
            "_format": "daily_summary",
            "ingested_at": ingested_at,
            # Validator (DATA-2) requires entries_count + food_log fields; daily-
            # summary format has no per-meal data, so emit empty placeholders.
            "entries_count": 0,
            "food_log": [],
        }
        if cal is not None:
            item["total_calories_kcal"] = round(cal, 2)
        if prot is not None:
            item["total_protein_g"] = round(prot, 2)
        if fat is not None:
            item["total_fat_g"] = round(fat, 2)
        if carbs is not None:
            item["total_carbs_g"] = round(carbs, 2)
        if weight is not None and weight > 0:
            item["weight_lbs_macrofactor"] = round(weight, 2)
        if trend_weight is not None and trend_weight > 0:
            item["trend_weight_lbs"] = round(trend_weight, 2)
        if expenditure is not None and expenditure > 0:
            item["expenditure_kcal"] = round(expenditure, 2)
            # (#484) Canonical name: readers (daily_insight, ai_context) and the
            # correlation engine key off `tdee_kcal`. Write it here so the deficit
            # chain converges forward without a per-reader backfill.
            item["tdee_kcal"] = round(expenditure, 2)
        if target_cal is not None and target_cal > 0:
            item["target_calories_kcal"] = round(target_cal, 2)
        if target_prot is not None and target_prot > 0:
            item["target_protein_g"] = round(target_prot, 2)
        day_items[date_str] = item
    print(f"Summary parser: {len(day_items)} days, skipped {skipped} blank/invalid rows")
    return day_items


def archive_raw(bucket, source_key, content_bytes, subfolder=""):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    import os

    fname = os.path.basename(source_key)
    sub = f"/{subfolder}" if subfolder else ""
    dest = f"raw/{USER_ID}/macrofactor{sub}/{now.strftime('%Y/%m')}/{fname}"
    s3_client.put_object(Bucket=bucket, Key=dest, Body=content_bytes, ContentType="text/csv")
    print(f"Archived to s3://{bucket}/{dest}")


def lambda_handler(event, context):
    if hasattr(logger, "set_date"):
        logger.set_date(pacific_today())  # OBS-1
    print(f"Event: {json.dumps(event)}")

    if "Records" in event:
        record = event["Records"][0]
        bucket = record["s3"]["bucket"]["name"]
        source_key = record["s3"]["object"]["key"]
    elif "bucket" in event and "key" in event:
        bucket, source_key = event["bucket"], event["key"]
    else:
        return {"statusCode": 400, "body": "No S3 record in event"}

    print(f"Processing s3://{bucket}/{source_key}")
    response = s3_client.get_object(Bucket=bucket, Key=source_key)
    content_bytes = response["Body"].read()
    print(f"Downloaded {len(content_bytes):,} bytes")

    text = content_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
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
    elif csv_type == "daily_summary":
        archive_raw(bucket, source_key, content_bytes, subfolder="daily_summary")
        day_items = build_summary_day_items(rows)
    else:
        # #469 (B-5): NEVER a silent 200. By the time this Lambda runs, dropbox_poll
        # has already hash-marked the file processed and moved it — a silent skip
        # here means an export-format change kills the pipe with zero retry and zero
        # signal (the 22-day May incident). Archive for forensics, then raise so the
        # ingestion-error alarm path fires and the failure is visible the same day.
        archive_raw(bucket, source_key, content_bytes, subfolder="unknown")
        headers = list(rows[0].keys())[:10]
        print(f"Unknown CSV format. Headers: {headers}")
        raise ValueError(f"Unknown MacroFactor CSV format (archived to raw/.../unknown/): headers={headers}")

    # REL-3: import safe_put_item once for the whole batch
    try:
        from common.item_size_guard import safe_put_item as _safe_put

        _use_safe_put = True
    except ImportError:
        print("[WARN] item_size_guard not available — falling back to direct put_item")
        _use_safe_put = False

    # DATA-2: import validator once for the batch
    try:
        from ingestion.ingestion_validator import validate_item as _validate_item

        _use_validator = True
    except ImportError:
        _use_validator = False

    # #482/X-6: standalone writer stamps phase like the framework does.
    _pfd: Callable[[str], str] | None
    try:
        from ingestion.ingestion_framework import phase_for_date

        _pfd = phase_for_date
    except ImportError:  # pragma: no cover — layer unavailable locally
        _pfd = None

    written = 0
    for date_str_key, item in day_items.items():
        source_label = item.get("source", csv_type)
        if _pfd and "phase" not in item:
            item["phase"] = _pfd(date_str_key)
        _mf_item = floats_to_decimal(item)
        # ── DATA-2: Validate before write ──
        if _use_validator:
            _vr = _validate_item(source_label, _mf_item, date_str_key)
            if _vr.should_skip_ddb:
                print(f"[DATA-2] CRITICAL: Skipping {source_label} DDB write for {date_str_key}: {_vr.errors}")
                _vr.archive_to_s3(s3_client, bucket=bucket, item=_mf_item)
                continue
            if _vr.warnings:
                print(f"[DATA-2] Validation warnings for {source_label}/{date_str_key}: {_vr.warnings}")
        # ── REL-3: safe_put_item handles 400KB limit, CW metrics, and truncation ──
        if _use_safe_put:
            _safe_put(table, _mf_item, source=source_label, date_str=date_str_key)
        else:
            table.put_item(Item=_mf_item)
        written += 1

    print(f"Written {written} DynamoDB items ({csv_type})")
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "source_file": source_key,
                "csv_type": csv_type,
                "rows_parsed": len(rows),
                "days_written": written,
            }
        ),
    }
