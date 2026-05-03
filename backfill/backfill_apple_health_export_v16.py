#!/usr/bin/env python3
"""
backfill_apple_health_export_v16.py — v1.6-parity historical backfill from native
Apple Health export.xml.

Mirrors the v1.6.0 live HAE Lambda's coverage:
    BP, water, caffeine, mindful sessions, workouts, State of Mind

v16.1 — Source-priority deduplication (CRITICAL FIX)
  Apple Health's export.xml contains DUPLICATE records when multiple devices
  or apps observe the same physical phenomenon (e.g. iPhone + Garmin both
  count the same steps you walked; My Water app + MacroFactor both record
  the same glass of water). Naive summation produces 2x-30x inflated values.

  Fix: For each metric type, define a SOURCE_PRIORITY ordering. Only records
  from the highest-priority source PRESENT IN THE DATA are used; lower-priority
  duplicates are skipped. This is conservative — minor edge-case loss when a
  lower-priority source captures readings the higher-priority source missed
  (e.g. wearing watch without phone), but eliminates the duplication problem.

Also fixes:
  • Water unit detection — respects unit attribute (mL or fl_oz_us)
  • Per-day source-resolution log printed in dry-run for sanity check

Usage:
    python3 backfill_apple_health_export_v16.py [PATH] [--since YYYY-MM-DD] [--dry-run]
"""

import xml.etree.ElementTree as ET
import json
import math
import os
import sys
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from collections import defaultdict, Counter

# ── Config ─────────────────────────────────────────────────────────────────────
S3_BUCKET      = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
REGION         = "us-west-2"
USER_ID        = "matthew"
PK             = f"USER#{USER_ID}#SOURCE#apple_health"

DEFAULT_EXPORT = os.path.expanduser(
    "~/Documents/Claude/life-platform/datadrops/apple_health_drop/"
    "apple_health_export_may2/export.xml"
)
DEFAULT_SINCE  = "2024-01-01"

# ── AWS clients (lazy — only initialized if not dry-run) ──────────────────────
_dynamodb = None
_s3 = None
_table = None

def _aws():
    global _dynamodb, _s3, _table
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _s3 = boto3.client("s3", region_name=REGION)
        _table = _dynamodb.Table(DYNAMODB_TABLE)
    return _table, _s3


# ── Source Filtering (Tier 2 — cross-device cardio) ──────────────────────────
APPLE_DEVICE_SUBSTRINGS = {"matt", "iphone", "apple watch", "watch", "apple"}


def is_apple_device(source_name):
    if not source_name:
        return True
    s = source_name.lower()
    return any(sub in s for sub in APPLE_DEVICE_SUBSTRINGS)


# ── SOURCE PRIORITY (v16.1 fix) ──────────────────────────────────────────────
# For each duplication-prone metric, list source names in priority order.
# We pick the highest-priority source that actually has data for the day,
# and ignore all others. Substring match, case-insensitive.
#
# Convention:
#   activity (steps/cal/flights/distance) → iPhone canonical, Watch fallback,
#                                            Garmin Connect last (often duplicates)
#   water/caffeine/nutrition → user-facing logging app preferred over mirrors
#   weight → leave None (Withings is SOT via separate pipeline; HAE is fallback)

SOURCE_PRIORITY = {
    # Activity metrics — iPhone is canonical (it has motion coprocessor + Watch sync)
    "steps":                       ["matt 17", "matt", "iphone", "apple watch", "watch", "connect"],
    "active_calories":             ["matt 17", "matt", "iphone", "apple watch", "watch", "connect"],
    "basal_calories":              ["matt 17", "matt", "iphone", "apple watch", "watch", "connect"],
    "flights_climbed":             ["matt 17", "matt", "iphone", "apple watch", "watch", "connect"],
    "distance_walk_run_miles":     ["matt 17", "matt", "iphone", "apple watch", "watch", "connect"],

    # Gait metrics — Watch-only typically, iPhone fallback
    "walking_speed_mph":           ["apple watch", "watch", "matt 17", "matt", "iphone"],
    "walking_step_length_in":      ["apple watch", "watch", "matt 17", "matt", "iphone"],
    "walking_double_support_pct":  ["apple watch", "watch", "matt 17", "matt", "iphone"],
    "walking_asymmetry_pct":       ["apple watch", "watch", "matt 17", "matt", "iphone"],
    "walking_steadiness_pct":      ["apple watch", "watch", "matt 17", "matt", "iphone"],

    # Water — user-facing logging app first; MacroFactor often mirrors
    "water_intake_raw":            ["my water", "waterminder", "watermind", "matt 17", "iphone", "macrofactor"],
    # Caffeine — same priority
    "caffeine_mg":                 ["my water", "waterminder", "watermind", "matt 17", "iphone", "macrofactor"],

    # Mindful — meditation/breath apps direct; HAE-style mirrors last
    "mindful_minutes":             ["balance", "calm", "headspace", "breathwrk", "apple", "matt 17", "iphone"],

    # Audio — iPhone direct
    "headphone_audio_exposure_db": ["matt 17", "matt", "iphone"],
    "env_audio_exposure_db":       ["apple watch", "watch", "matt 17", "iphone"],

    # Weight from Apple — only used as fallback when Withings is delayed
    "weight_lbs_apple":            ["withings", "matt 17", "iphone", "apple"],

    # BP — single source (cuff); priority list mostly cosmetic
    "blood_pressure_systolic":     ["health", "matt 17", "iphone"],
    "blood_pressure_diastolic":    ["health", "matt 17", "iphone"],

    # Tier 2 metrics already filtered by is_apple_device — leave priority empty (use all Apple)
}


def pick_source(field_name, source_counts):
    """Given a field name and a {source: count} dict for one day, return the
    highest-priority source that's present, or None if no priority defined.
    None means: accept all sources (no dedup).
    """
    priority = SOURCE_PRIORITY.get(field_name)
    if not priority:
        return None
    # Lowercase source set for matching
    available = {src.lower(): src for src in source_counts.keys()}
    for needle in priority:
        for low, orig in available.items():
            if needle in low:
                return orig
    # No priority match — fall back to most common source
    return source_counts.most_common(1)[0][0] if source_counts else None


# ── HKQuantityType → field mapping with tiers ─────────────────────────────────

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

    # NEW v1.3.0: Water intake (unit-aware: mL or fl_oz_us)
    "HKQuantityTypeIdentifierDietaryWater":                    {"field": "water_intake_raw",           "agg": "sum_water_unit_aware", "tier": 1},
    # NEW: Caffeine
    "HKQuantityTypeIdentifierDietaryCaffeine":                 {"field": "caffeine_mg",                "agg": "sum", "tier": 1},
    # NEW v1.4.0: Blood pressure (Tier 1 — cuff is the only source)
    "HKQuantityTypeIdentifierBloodPressureSystolic":           {"field": "blood_pressure_systolic",    "agg": "avg", "tier": 1, "track_individual_bp": "systolic"},
    "HKQuantityTypeIdentifierBloodPressureDiastolic":          {"field": "blood_pressure_diastolic",   "agg": "avg", "tier": 1, "track_individual_bp": "diastolic"},
    # Body mass: v1.4.2 fallback for Withings API delays
    "HKQuantityTypeIdentifierBodyMass":                        {"field": "weight_lbs_apple",           "agg": "avg", "tier": 1},

    # ── Tier 2: Cross-device (Apple only → _apple suffix) ──
    "HKQuantityTypeIdentifierHeartRate":                       {"field": "heart_rate_apple",           "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierRestingHeartRate":                {"field": "resting_heart_rate_apple",   "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":        {"field": "hrv_sdnn_apple",             "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierRespiratoryRate":                 {"field": "respiratory_rate_apple",     "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierOxygenSaturation":                {"field": "spo2_pct_apple",             "agg": "avg", "tier": 2},
    "HKQuantityTypeIdentifierWalkingHeartRateAverage":         {"field": "walking_hr_avg_apple",       "agg": "avg", "tier": 2},

    # Blood glucose — special handling
    "HKQuantityTypeIdentifierBloodGlucose":                    {"field": "_glucose", "agg": "special", "tier": 1},
}

# Category-type metrics
CATEGORY_DURATION_MAP = {
    "HKCategoryTypeIdentifierMindfulSession":                  {"field": "mindful_minutes",            "agg": "sum", "tier": 1},
}

# Tier 3: skip entirely
SKIP_TYPES = {
    "HKCategoryTypeIdentifierSleepAnalysis",
    "HKQuantityTypeIdentifierBodyMassIndex",
    "HKQuantityTypeIdentifierBodyFatPercentage",
    "HKQuantityTypeIdentifierLeanBodyMass",
    "HKQuantityTypeIdentifierWaistCircumference",
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
    "HKQuantityTypeIdentifierDietaryNiacin",
    "HKQuantityTypeIdentifierDietaryThiamin",
    "HKQuantityTypeIdentifierDietaryRiboflavin",
    "HKQuantityTypeIdentifierDietaryFolate",
    "HKQuantityTypeIdentifierDietaryPantothenicAcid",
    "HKQuantityTypeIdentifierDietaryPhosphorus",
    "HKQuantityTypeIdentifierDietaryCopper",
    "HKQuantityTypeIdentifierDietaryManganese",
}

RECOVERY_WORKOUT_TYPES = {
    "Flexibility":   "flexibility",
    "MindAndBody":   "breathwork",
    "Breathing":     "breathwork",
    "Yoga":          "yoga",
    "Pilates":       "pilates",
    "Cooldown":      "cooldown",
    "TaiChi":        "tai_chi",
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


def parse_dt(date_str):
    if not date_str:
        return None, None
    return date_str[:10], date_str.strip()


def parse_minutes_between(start_str, end_str):
    try:
        sd = datetime.strptime(start_str.strip()[:19], "%Y-%m-%d %H:%M:%S")
        ed = datetime.strptime(end_str.strip()[:19], "%Y-%m-%d %H:%M:%S")
        return max(0.0, (ed - sd).total_seconds() / 60.0)
    except Exception:
        return 0.0


# ── XML Streaming Parser (v16.1 — source-aware) ──────────────────────────────

def parse_export(filepath, since_date):
    """
    Stream-parse export.xml. For each Tier 1/2 quantity record, accumulate
    per-day-per-source values. After parsing, resolve source priority per
    metric per day to pick the canonical source's contribution.
    """
    # Per-day-per-source accumulators
    # day_per_source[date][field][source] = {"sum": float, "vals": [floats]}
    day_per_source = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"sum": 0.0, "vals": []})))
    # Source counts for sanity / picking
    day_source_counts = defaultdict(lambda: defaultdict(Counter))  # date → field → {src: count}

    # Special accumulators (no source dedup needed — single-source by nature)
    day_glucose = defaultdict(list)
    day_bp_sys  = defaultdict(list)
    day_bp_dia  = defaultdict(list)
    # Water needs special handling — unit detection + dedup by timestamp WITHIN chosen source
    day_water_per_source = defaultdict(lambda: defaultdict(dict))  # date → src → {ts: ml}
    day_caffeine_per_source = defaultdict(lambda: defaultdict(dict))
    day_mindful_per_source = defaultdict(lambda: defaultdict(list))  # date → src → [{start,end,duration}]
    day_workouts = defaultdict(list)
    day_som      = defaultdict(list)

    stats = {
        "total_records": 0,
        "skipped_old": 0,
        "skipped_sot": 0,
        "skipped_non_apple": 0,
        "skipped_unmapped": 0,
        "processed_raw": 0,   # before source dedup
        "glucose_readings": 0,
        "bp_readings": 0,
        "water_readings_raw": 0,
        "caffeine_readings_raw": 0,
        "mindful_sessions_raw": 0,
        "workouts": 0,
        "som_entries": 0,
        "unmapped_types": Counter(),
    }

    print(f"Parsing {filepath} (records since {since_date})...")
    print("This may take 2-5 minutes for a 1GB file...\n")

    for _, elem in ET.iterparse(filepath, events=("end",)):
        tag = elem.tag

        if tag == "Record":
            stats["total_records"] += 1
            if stats["total_records"] % 500_000 == 0:
                print(f"  ... {stats['total_records']:,} records parsed")

            rtype = elem.get("type", "")
            start_raw = elem.get("startDate", "")
            end_raw   = elem.get("endDate", "")
            date_str, ts_full = parse_dt(start_raw)

            if not date_str or date_str < since_date:
                stats["skipped_old"] += 1
                elem.clear()
                continue

            if rtype in SKIP_TYPES:
                stats["skipped_sot"] += 1
                elem.clear()
                continue

            # ── Category-type metrics ──
            if rtype in CATEGORY_DURATION_MAP:
                config = CATEGORY_DURATION_MAP[rtype]
                if rtype == "HKCategoryTypeIdentifierMindfulSession":
                    duration_min = parse_minutes_between(start_raw, end_raw)
                    if duration_min > 0:
                        src = elem.get("sourceName", "?")
                        day_mindful_per_source[date_str][src].append({
                            "start": start_raw, "end": end_raw,
                            "duration_min": round(duration_min, 2),
                        })
                        day_source_counts[date_str][config["field"]][src] += 1
                        stats["mindful_sessions_raw"] += 1
                elem.clear()
                continue

            # ── Quantity-type ──
            if rtype not in QUANTITY_MAP:
                stats["skipped_unmapped"] += 1
                stats["unmapped_types"][rtype] += 1
                elem.clear()
                continue

            config = QUANTITY_MAP[rtype]
            tier = config["tier"]
            source_name = elem.get("sourceName", "?")

            if tier == 2 and not is_apple_device(source_name):
                stats["skipped_non_apple"] += 1
                elem.clear()
                continue

            try:
                value = float(elem.get("value", "0") or "0")
            except (ValueError, TypeError):
                elem.clear()
                continue

            # Glucose: no dedup needed (single CGM)
            if config["agg"] == "special":
                day_glucose[date_str].append({"time": ts_full, "value": value})
                stats["glucose_readings"] += 1
                elem.clear()
                continue

            # BP: track individual readings (single cuff source typically)
            track_bp = config.get("track_individual_bp")
            if track_bp == "systolic":
                day_bp_sys[date_str].append({"time": ts_full, "value": round(value)})
                stats["bp_readings"] += 1
            elif track_bp == "diastolic":
                day_bp_dia[date_str].append({"time": ts_full, "value": round(value)})

            field = config["field"]

            # Water: unit-aware + per-source timestamp dedup
            if config["agg"] == "sum_water_unit_aware":
                unit = (elem.get("unit") or "").lower()
                if unit in ("ml", ""):
                    ml_value = value
                elif unit in ("fl_oz_us", "fl_oz", "floz"):
                    ml_value = value * 29.5735
                elif unit == "l":
                    ml_value = value * 1000
                else:
                    # Unknown unit — log and assume mL
                    ml_value = value
                day_water_per_source[date_str][source_name][ts_full] = ml_value
                day_source_counts[date_str][field][source_name] += 1
                stats["water_readings_raw"] += 1
                stats["processed_raw"] += 1
                elem.clear()
                continue

            # Caffeine: per-source timestamp dedup
            if rtype == "HKQuantityTypeIdentifierDietaryCaffeine":
                day_caffeine_per_source[date_str][source_name][ts_full] = value
                day_source_counts[date_str][field][source_name] += 1
                stats["caffeine_readings_raw"] += 1
                stats["processed_raw"] += 1
                elem.clear()
                continue

            # Standard sum/avg accumulators with source tracking
            acc = day_per_source[date_str][field][source_name]
            acc["sum"] += value
            acc["vals"].append(value)
            day_source_counts[date_str][field][source_name] += 1
            stats["processed_raw"] += 1
            elem.clear()
            continue

        # ── <Workout> ──
        if tag == "Workout":
            start_raw = elem.get("startDate", "")
            date_str, _ = parse_dt(start_raw)
            if not date_str or date_str < since_date:
                elem.clear()
                continue
            wtype_raw = elem.get("workoutActivityType", "")
            wtype = wtype_raw.replace("HKWorkoutActivityType", "")
            try:
                duration = float(elem.get("duration", "0") or "0")
                if (elem.get("durationUnit", "min") or "min").lower().startswith("s"):
                    duration /= 60.0
            except (ValueError, TypeError):
                duration = 0.0
            try:
                energy = float(elem.get("totalEnergyBurned", "0") or "0")
            except (ValueError, TypeError):
                energy = 0.0
            category = RECOVERY_WORKOUT_TYPES.get(wtype, "other")
            day_workouts[date_str].append({
                "id": f"{wtype}_{start_raw}",
                "name": wtype,
                "category": category,
                "start": start_raw,
                "end": elem.get("endDate", ""),
                "duration_min": round(duration, 1),
                "active_energy_kcal": round(energy, 1),
                "source": elem.get("sourceName", ""),
                "is_recovery_type": category != "other",
            })
            stats["workouts"] += 1
            elem.clear()
            continue

        if tag == "StateOfMind" or tag.endswith("StateOfMind"):
            start_raw = (elem.get("startDate") or elem.get("creationDate")
                         or elem.get("date") or "")
            date_str, ts_full = parse_dt(start_raw)
            if not date_str or date_str < since_date:
                elem.clear()
                continue
            valence = elem.get("valence")
            try:
                valence = float(valence) if valence is not None else None
            except (ValueError, TypeError):
                valence = None
            kind_raw = elem.get("kind", "unknown")
            kind_lower = str(kind_raw).lower().replace(" ", "").replace("_", "")
            if "mood" in kind_lower or "daily" in kind_lower:
                kind = "dailyMood"
            elif "emotion" in kind_lower or "momentary" in kind_lower:
                kind = "momentaryEmotion"
            else:
                kind = kind_raw
            entry = {
                "time": ts_full,
                "kind": kind,
                "valence": valence,
                "valence_classification": elem.get("valenceClassification", ""),
                "labels": [],
                "associations": [],
                "source": elem.get("sourceName", ""),
            }
            if valence is not None:
                day_som[date_str].append(entry)
                stats["som_entries"] += 1
            elem.clear()
            continue

        elem.clear()

    # ── Resolve per-day per-field source priority and build daily aggregates ──
    all_dates = set()
    all_dates.update(day_per_source.keys())
    all_dates.update(day_glucose.keys())
    all_dates.update(day_bp_sys.keys())
    all_dates.update(day_water_per_source.keys())
    all_dates.update(day_caffeine_per_source.keys())
    all_dates.update(day_mindful_per_source.keys())
    all_dates.update(day_workouts.keys())
    all_dates.update(day_som.keys())

    # Source-resolution audit log: date → field → chosen_source (rejected_sources)
    audit = defaultdict(dict)

    day_data = {}
    for date_str in sorted(all_dates):
        fields = {}

        # ── Standard sum/avg fields with source priority ──
        for field, src_data in day_per_source[date_str].items():
            chosen = pick_source(field, day_source_counts[date_str][field])
            other_sources = [s for s in src_data.keys() if s != chosen]
            audit[date_str][field] = {
                "chosen": chosen,
                "rejected": other_sources,
            }
            if chosen and chosen in src_data:
                acc = src_data[chosen]
                # Determine agg type from QUANTITY_MAP — find by field
                agg = None
                for cfg in QUANTITY_MAP.values():
                    if cfg.get("field") == field:
                        agg = cfg["agg"]
                        break
                if agg == "sum":
                    fields[field] = round(acc["sum"], 2)
                elif agg == "avg":
                    if acc["vals"]:
                        fields[field] = round(sum(acc["vals"]) / len(acc["vals"]), 2)

        # Derived: total calories
        ac = fields.get("active_calories")
        bc = fields.get("basal_calories")
        if ac is not None and bc is not None:
            fields["total_calories_burned"] = round(ac + bc, 2)

        # ── Water: pick source, then sum unique timestamps from that source ──
        water_per_src = day_water_per_source.get(date_str, {})
        if water_per_src:
            water_src_counts = Counter({s: len(d) for s, d in water_per_src.items()})
            chosen = pick_source("water_intake_raw", water_src_counts)
            other_sources = [s for s in water_per_src.keys() if s != chosen]
            audit[date_str]["water_intake_ml"] = {"chosen": chosen, "rejected": other_sources}
            if chosen and chosen in water_per_src:
                readings = water_per_src[chosen]   # {ts: ml_value}
                total_ml = sum(readings.values())
                fields["water_intake_ml"] = round(total_ml)
                fields["water_intake_oz"] = round(total_ml / 29.5735, 1)
                fields["water_readings_count"] = len(readings)

        # ── Caffeine: pick source, sum unique timestamps ──
        caf_per_src = day_caffeine_per_source.get(date_str, {})
        if caf_per_src:
            caf_src_counts = Counter({s: len(d) for s, d in caf_per_src.items()})
            chosen = pick_source("caffeine_mg", caf_src_counts)
            other_sources = [s for s in caf_per_src.keys() if s != chosen]
            audit[date_str]["caffeine_mg"] = {"chosen": chosen, "rejected": other_sources}
            if chosen and chosen in caf_per_src:
                readings = caf_per_src[chosen]
                fields["caffeine_mg"] = round(sum(readings.values()), 1)
                fields["caffeine_readings_count"] = len(readings)

        # ── Mindful: pick source, sum durations from chosen source ──
        mindful_per_src = day_mindful_per_source.get(date_str, {})
        if mindful_per_src:
            mind_src_counts = Counter({s: len(d) for s, d in mindful_per_src.items()})
            chosen = pick_source("mindful_minutes", mind_src_counts)
            other_sources = [s for s in mindful_per_src.keys() if s != chosen]
            audit[date_str]["mindful_minutes"] = {"chosen": chosen, "rejected": other_sources}
            if chosen and chosen in mindful_per_src:
                sessions = mindful_per_src[chosen]
                fields["mindful_minutes"] = round(sum(s["duration_min"] for s in sessions), 1)
                fields["mindful_sessions"] = len(sessions)

        # ── Glucose CGM aggregates ──
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

        # BP daily count
        sys_count = len(day_bp_sys.get(date_str, []))
        if sys_count:
            fields["blood_pressure_readings_count"] = sys_count

        # Workouts: recovery aggregates
        wkts = day_workouts.get(date_str, [])
        recovery = [w for w in wkts if w["is_recovery_type"]]
        if recovery:
            cat_minutes = defaultdict(float)
            cat_sessions = defaultdict(int)
            for w in recovery:
                cat = w["category"]
                cat_minutes[cat] += w["duration_min"]
                cat_sessions[cat] += 1
            for cat, minutes in cat_minutes.items():
                fields[f"{cat}_minutes"] = round(minutes, 1)
                fields[f"{cat}_sessions"] = cat_sessions[cat]
            fields["recovery_workout_minutes"] = round(sum(cat_minutes.values()), 1)
            fields["recovery_workout_sessions"] = len(recovery)
            fields["recovery_workout_types"] = ", ".join(sorted(set(w["category"] for w in recovery)))

        # State of Mind aggregates
        som = day_som.get(date_str, [])
        if som:
            valences = [e["valence"] for e in som if e["valence"] is not None]
            if valences:
                fields["som_avg_valence"] = round(sum(valences) / len(valences), 4)
                fields["som_min_valence"] = round(min(valences), 4)
                fields["som_max_valence"] = round(max(valences), 4)
            fields["som_check_in_count"] = len(som)
            fields["som_mood_count"] = sum(1 for e in som if e["kind"] == "dailyMood")
            fields["som_emotion_count"] = sum(1 for e in som if e["kind"] == "momentaryEmotion")

        if fields:
            day_data[date_str] = fields

    return {
        "day_data": day_data,
        "day_glucose": day_glucose,
        "day_bp_sys": day_bp_sys,
        "day_bp_dia": day_bp_dia,
        "day_workouts": day_workouts,
        "day_som": day_som,
        "stats": stats,
        "audit": audit,
    }


# ── DynamoDB / S3 Writers (unchanged) ─────────────────────────────────────────

def merge_day_to_dynamo(date_str, fields):
    table, _ = _aws()
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
    set_parts.append("#upd = :upd")
    names["#upd"] = "backfill_v16_ingested_at"
    values[":upd"] = datetime.now(timezone.utc).isoformat()
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
    _, s3 = _aws()
    s3_key = f"raw/{USER_ID}/cgm_readings/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
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
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key,
                      Body=json.dumps(merged, default=str), ContentType="application/json")
    return len(new_readings)


def save_bp_to_s3(date_str, sys_readings, dia_readings):
    _, s3 = _aws()
    s3_key = f"raw/{USER_ID}/blood_pressure/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    dia_by_time = {r["time"]: r["value"] for r in dia_readings}
    paired = [
        {"time": r["time"], "systolic": r["value"], "diastolic": dia_by_time.get(r["time"])}
        for r in sys_readings
    ]
    existing = []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except Exception:
        pass
    existing_times = {r["time"] for r in existing}
    new = [r for r in paired if r["time"] not in existing_times]
    if new:
        merged = sorted(existing + new, key=lambda r: r["time"] or "")
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key,
                      Body=json.dumps(merged, default=str), ContentType="application/json")
    return len(new)


def save_workouts_to_s3(date_str, workouts_list):
    _, s3 = _aws()
    s3_key = f"raw/{USER_ID}/workouts/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    existing = []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except Exception:
        pass
    existing_ids = {w.get("id") for w in existing if w.get("id")}
    new = [w for w in workouts_list if w.get("id") and w["id"] not in existing_ids]
    if new:
        merged = existing + new
        merged.sort(key=lambda w: w.get("start", ""))
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key,
                      Body=json.dumps(merged, default=str), ContentType="application/json")
    return len(new)


def save_som_to_s3(date_str, entries):
    _, s3 = _aws()
    s3_key = f"raw/{USER_ID}/state_of_mind/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    existing = []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        existing = json.loads(resp["Body"].read())
    except Exception:
        pass
    existing_times = {e.get("time") for e in existing}
    new = [e for e in entries if e.get("time") not in existing_times]
    if new:
        merged = sorted(existing + new, key=lambda e: e.get("time") or "")
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key,
                      Body=json.dumps(merged, default=str), ContentType="application/json")
    return len(new)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    filepath = args[0] if args and not args[0].startswith("--") else DEFAULT_EXPORT
    since_date = DEFAULT_SINCE
    for i, arg in enumerate(args):
        if arg == "--since" and i + 1 < len(args):
            since_date = args[i + 1]

    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        print(f"Usage: python3 {sys.argv[0]} [PATH] [--since YYYY-MM-DD] [--dry-run]")
        sys.exit(1)

    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print("Apple Health Historical Backfill — v1.6 parity (v16.1 source-aware)")
    print("=" * 60)
    print(f"File:    {filepath} ({file_size_mb:.0f} MB)")
    print(f"Since:   {since_date}")
    print(f"Target:  table={DYNAMODB_TABLE}, s3={S3_BUCKET}")
    print(f"Mode:    {'DRY RUN (no writes)' if dry_run else 'LIVE (will write to AWS)'}")
    print()

    parsed = parse_export(filepath, since_date)
    day_data    = parsed["day_data"]
    day_glucose = parsed["day_glucose"]
    day_bp_sys  = parsed["day_bp_sys"]
    day_bp_dia  = parsed["day_bp_dia"]
    day_workouts = parsed["day_workouts"]
    day_som     = parsed["day_som"]
    stats       = parsed["stats"]
    audit       = parsed["audit"]

    print(f"\n{'─' * 60}")
    print("Parsing complete:")
    print(f"  Total records scanned:    {stats['total_records']:>12,}")
    print(f"  Skipped (before {since_date}): {stats['skipped_old']:>12,}")
    print(f"  Skipped (SOT elsewhere):  {stats['skipped_sot']:>12,}")
    print(f"  Skipped (non-Apple T2):   {stats['skipped_non_apple']:>12,}")
    print(f"  Skipped (unmapped type):  {stats['skipped_unmapped']:>12,}")
    print(f"  Processed (raw, pre-dedup): {stats['processed_raw']:>10,}")
    print(f"  Glucose readings:         {stats['glucose_readings']:>12,}")
    print(f"  BP readings:              {stats['bp_readings']:>12,}")
    print(f"  Water readings (raw):     {stats['water_readings_raw']:>12,}")
    print(f"  Caffeine readings (raw):  {stats['caffeine_readings_raw']:>12,}")
    print(f"  Mindful sessions (raw):   {stats['mindful_sessions_raw']:>12,}")
    print(f"  Workouts:                 {stats['workouts']:>12,}")
    print(f"  State of Mind entries:    {stats['som_entries']:>12,}")
    print(f"  Days with data:           {len(day_data):>12,}")
    print(f"{'─' * 60}\n")

    if stats["unmapped_types"]:
        print("Top 10 unmapped types:")
        for rtype, n in stats["unmapped_types"].most_common(10):
            print(f"  {n:>8,}  {rtype}")
        print()

    # ── Source resolution audit (dry-run only) ──
    if dry_run and audit:
        print("Source resolution audit (sample — first 3 days):")
        for date_str in sorted(audit.keys())[:3]:
            print(f"  {date_str}:")
            for field, choice in sorted(audit[date_str].items()):
                rej = f"  [rejected: {choice['rejected']}]" if choice['rejected'] else ""
                print(f"    {field:30s} ← {choice['chosen']}{rej}")
            print()

    if not day_data:
        print("No data to write. Exiting.")
        return

    sample_date = sorted(day_data.keys())[-1]
    print(f"Sample day ({sample_date}):")
    print(json.dumps(day_data[sample_date], indent=2, default=str))
    print()

    if dry_run:
        print(f"{'═' * 60}")
        print("DRY RUN — no AWS writes performed.")
        print(f"  Would write {len(day_data)} days to DynamoDB")
        print(f"  Would write glucose readings for {len(day_glucose)} days to S3")
        print(f"  Would write BP readings for {len(day_bp_sys)} days to S3")
        print(f"  Would write workouts for {len(day_workouts)} days to S3")
        print(f"  Would write SoM entries for {len(day_som)} days to S3")
        print(f"  Re-run without --dry-run to commit.")
        print(f"{'═' * 60}")
        return

    date_range = f"{min(day_data.keys())} → {max(day_data.keys())}"
    resp = input(f"Write {len(day_data)} days ({date_range}) to DynamoDB and S3? [y/N] ")
    if resp.lower() != "y":
        print("Aborted.")
        return

    print(f"\nWriting {len(day_data)} days to DynamoDB...")
    written = errors = 0
    for date_str in sorted(day_data.keys()):
        try:
            merge_day_to_dynamo(date_str, day_data[date_str])
            written += 1
            if written % 50 == 0:
                print(f"  ... {written}/{len(day_data)} days written")
        except Exception as e:
            errors += 1
            print(f"  ERROR writing {date_str}: {e}")

    glucose_new = 0
    if day_glucose:
        print(f"\nSaving glucose readings to S3...")
        for date_str, readings in sorted(day_glucose.items()):
            try:
                glucose_new += save_glucose_to_s3(date_str, readings)
            except Exception as e:
                print(f"  ERROR glucose {date_str}: {e}")

    bp_new = 0
    if day_bp_sys:
        print(f"\nSaving BP readings to S3...")
        for date_str, sys_r in sorted(day_bp_sys.items()):
            try:
                bp_new += save_bp_to_s3(date_str, sys_r, day_bp_dia.get(date_str, []))
            except Exception as e:
                print(f"  ERROR BP {date_str}: {e}")

    workout_new = 0
    if day_workouts:
        print(f"\nSaving workouts to S3...")
        for date_str, wkts in sorted(day_workouts.items()):
            try:
                workout_new += save_workouts_to_s3(date_str, wkts)
            except Exception as e:
                print(f"  ERROR workouts {date_str}: {e}")

    som_new = 0
    if day_som:
        print(f"\nSaving State of Mind entries to S3...")
        for date_str, entries in sorted(day_som.items()):
            try:
                som_new += save_som_to_s3(date_str, entries)
            except Exception as e:
                print(f"  ERROR SoM {date_str}: {e}")

    print(f"\n{'═' * 60}")
    print("BACKFILL COMPLETE")
    print(f"  Days written to DynamoDB: {written}")
    print(f"  Errors:                   {errors}")
    print(f"  Date range:               {date_range}")
    print(f"  S3 — glucose readings:    {glucose_new}")
    print(f"  S3 — BP readings:         {bp_new}")
    print(f"  S3 — workouts:            {workout_new}")
    print(f"  S3 — SoM entries:         {som_new}")
    if day_data:
        fields_seen = set()
        for fields in day_data.values():
            fields_seen.update(fields.keys())
        print(f"  Fields written (sample): {sorted(fields_seen)[:15]}{'...' if len(fields_seen) > 15 else ''}")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
