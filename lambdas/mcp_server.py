"""
life-platform MCP Server v2.26.0
New in v2.26.0:
  - get_glucose_meal_response : Levels-style postprandial spike analysis -- MacroFactor food_log x S3 CGM readings
  - S3 client added for CGM 5-min reading access

New in v2.14.0:
  - get_alcohol_sleep_correlation : personal alcohol impact analyzer -- MacroFactor alcohol + Eight Sleep + next-day Whoop recovery

New in v2.13.0:
  - get_zone2_breakdown : Zone 2 training tracker -- weekly minutes, 5-zone distribution, target comparison, polarization alerts

New in v2.12.0:
  - get_exercise_sleep_correlation : personal exercise timing cutoff finder -- Strava end times + Eight Sleep

New in v2.8.0:
  - get_caffeine_sleep_correlation : personal caffeine cutoff finder -- MacroFactor food_log timing + Eight Sleep

New in v2.7.0:
  - Habitify integration: habitify added to SOURCES; Supplements added to P40_GROUPS;
    query_chronicling() SOT-aware; default SOT habits -> habitify

New in v2.6.0:
  - get_garmin_summary           : Garmin daily biometrics — Body Battery, HRV, stress, RHR, respiration
  - get_device_agreement         : cross-device validation — Whoop vs Garmin HRV/RHR agreement + disagreement flags
  - get_readiness_score updated  : Garmin Body Battery added as 5th component (10%); weights rebalanced;
                                   device_agreement section shows inter-device confidence signal

New in v2.5.1:
  - Fix: DynamoDB TTL attribute name corrected ('ttl_epoch' → 'ttl') in ddb_cache_set/get

New in v2.5.0:
  - save_insight                 : save a new insight from chat to the coaching log
  - get_insights                 : list insights with optional status filter; flags open >14 days
  - update_insight_outcome       : close the loop — record outcome and mark insight acted/resolved

New in v2.4.0:
  - get_readiness_score          : unified 0-100 readiness score (GREEN/YELLOW/RED) — Whoop + Eight Sleep + HRV trend + TSB

Tools:
  Habits / P40 tools (v2.1.0):
  - get_habit_adherence          : per-habit and per-group completion rates over any period
  - get_habit_streaks            : current streak, longest streak, days since last completion
  - get_keystone_habits          : habits most correlated with overall daily score (behavioral levers)
  - get_habit_health_correlations: correlate habit presence to biometric outcomes (HRV, recovery, weight, sleep)
  - get_group_trends             : weekly P40 group scores over time with trend direction
  - compare_habit_periods        : side-by-side adherence comparison of two date ranges
  - get_habit_stacks             : co-occurrence analysis — which habits cluster together
  - get_habit_dashboard          : current-state P40 briefing — 7d adherence, streaks, best/worst groups

  Strength tools (v2.0.0):
  - get_exercise_history         : deep dive on single exercise
  - get_strength_prs             : all-exercise PR leaderboard
  - get_muscle_volume            : weekly sets vs MEV/MAV/MRV landmarks
  - get_strength_progress        : longitudinal 1RM trend + plateau detection
  - get_workout_frequency        : adherence metrics and streaks
  - get_strength_standards       : bodyweight-relative strength classification

  - get_sources                  : list available sources and their date ranges
  - get_latest                   : most recent record(s) per source
  - get_daily_summary            : all sources for a single date
  - get_date_range               : time series (auto-aggregates for large windows)
  - find_days                    : filter days matching numeric field criteria (day-level only)
  - get_aggregated_summary       : monthly or yearly averages over any date range
  - get_field_stats              : min/max/avg/count + top-5 highs/lows + trend direction
  - search_activities            : search Strava activities by name, type, distance, elevation + percentile rank
  - compare_periods              : side-by-side comparison of two date ranges across any source
  - get_weekly_summary           : weekly training load totals for Strava
  - get_training_load            : CTL/ATL/TSB/ACWR — Banister fitness-fatigue model + injury risk
  - get_personal_records         : all-time PRs across every measurable dimension
  - get_cross_source_correlation : Pearson r between any two metrics with optional day lag
  - get_seasonal_patterns        : month-by-month averages across all years revealing annual cycles
  - get_health_dashboard         : current-state briefing — readiness, load, biomarker alerts
  - get_readiness_score          : unified 0-100 readiness score — Whoop + Eight Sleep + HRV trend + TSB → GREEN/YELLOW/RED
  - save_insight                 : save a new insight from chat to the coaching log
  - get_insights                 : list insights with optional status filter; flags open >14 days
  - update_insight_outcome       : close the loop — record outcome and mark insight acted/resolved
  - get_weight_loss_progress     : weekly rate of loss, BMI series, clinical milestones, plateau detection
  - get_body_composition_trend   : fat mass vs lean mass over time — is the loss fat or muscle?
  - get_energy_expenditure       : daily BMR + exercise calories = TDEE estimate and implied deficit
  - get_non_scale_victories      : fitness biomarker improvements since journey start
  - get_sleep_analysis           : clinical sleep quality report — architecture %, efficiency, circadian timing, social jetlag, debt
"""

import json
import os
import urllib.request
import re
import math
import bisect
import time
import hashlib
import concurrent.futures
import boto3
import logging
from collections import defaultdict
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Configuration from environment variables (with backwards-compatible defaults) ──
_REGION         = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME      = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET       = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID         = os.environ.get("USER_ID", "matthew")
API_SECRET_NAME = os.environ.get("API_SECRET_NAME", "life-platform/mcp-api-key")

dynamodb  = boto3.resource("dynamodb", region_name=_REGION)
table     = dynamodb.Table(TABLE_NAME)
secrets   = boto3.client("secretsmanager", region_name=_REGION)
s3_client = boto3.client("s3", region_name=_REGION)

USER_PREFIX     = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK      = f"USER#{USER_ID}"
PROFILE_SK      = "PROFILE#v1"
RAW_DAY_LIMIT   = 90

SOURCES = ["whoop", "withings", "strava", "todoist", "apple_health", "hevy", "eightsleep", "chronicling", "macrofactor", "garmin", "habitify", "notion", "labs", "dexa", "genome"]

# ── Source-of-truth domain ownership ─────────────────────────────────────────
# Each domain has exactly one authoritative source. Tools that compute aggregates
# or training load MUST read from the SOT source only — never sum across sources
# covering the same domain (e.g. Garmin + Strava would double-count cardio).
# Override per-domain in the DynamoDB profile record (seed_profile.py) to
# change ownership without touching code — e.g. if Garmin replaces Strava.
_DEFAULT_SOURCE_OF_TRUTH = {
    "cardio":      "strava",        # GPS activities — Strava is the hub (Garmin auto-syncs here)
    "strength":    "hevy",          # Sets/reps/weight — Hevy is the source
    "physiology":  "whoop",         # HRV, recovery, strain — Whoop (primary)
    "nutrition":   "macrofactor",   # Macros, food log — MacroFactor
    "sleep":       "eightsleep",
    "journal":     "notion",         # Subjective journal — Notion (morning, evening, ad-hoc)    # Sleep stages, HRV, efficiency — Eight Sleep
    "body":        "withings",      # Weight, body composition — Withings
    "steps":       "apple_health",  # Steps, passive movement — Apple Health
    "tasks":       "todoist",       # Productivity/tasks — Todoist
    "habits":      "habitify",      # P40 habit tracking — Habitify (was: Chronicling)
    "stress":      "garmin",        # Physiological stress score — Garmin (objective HRV-derived)
    "body_battery":"garmin",        # Energy reserve metric — Garmin (unique to platform)
    "gait":        "apple_health",  # Gait & mobility — Apple Watch exclusive
    "energy_expenditure": "apple_health",  # TDEE from Apple Watch (active + basal)
    "cgm":         "apple_health",  # Continuous glucose monitoring — Dexcom Stelo via HealthKit
}


def get_sot(domain: str) -> str:
    """Return the source-of-truth source name for a given domain.
    Reads profile override first; falls back to _DEFAULT_SOURCE_OF_TRUTH.
    """
    profile = get_profile()
    sot_overrides = profile.get("source_of_truth", {})
    return sot_overrides.get(domain, _DEFAULT_SOURCE_OF_TRUTH.get(domain, "strava"))

# P40 habit groups for reference / validation
P40_GROUPS = ["Data", "Discipline", "Growth", "Hygiene", "Nutrition", "Performance", "Recovery", "Supplements", "Wellbeing"]

FIELD_ALIASES = {
    "strava": {
        "distance_miles":        "total_distance_miles",
        "elevation_gain_feet":   "total_elevation_gain_feet",
        "elevation_gain":        "total_elevation_gain_feet",
        "distance":              "total_distance_miles",
    }
}

# ── Profile cache (loaded once per Lambda warm instance) ─────────────────────
_PROFILE_CACHE = None

def get_profile():
    global _PROFILE_CACHE
    if _PROFILE_CACHE is not None:
        return _PROFILE_CACHE
    try:
        resp = table.get_item(Key={"pk": PROFILE_PK, "sk": PROFILE_SK})
        _PROFILE_CACHE = decimal_to_float(resp.get("Item", {}))
    except Exception as e:
        logger.warning(f"Could not load profile: {e}")
        _PROFILE_CACHE = {}
    return _PROFILE_CACHE


# ── In-memory cache (survives across invocations on a warm Lambda instance) ───
_MEM_CACHE: dict = {}
MEM_CACHE_TTL = 600  # 10 minutes

def mem_cache_get(key: str):
    entry = _MEM_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < MEM_CACHE_TTL:
        logger.info(f"[cache:mem] hit — {key}")
        return entry["data"]
    return None

def mem_cache_set(key: str, data):
    _MEM_CACHE[key] = {"data": data, "ts": time.time()}
    logger.info(f"[cache:mem] stored — {key}")


# ── DynamoDB pre-computed cache (survives cold starts, written nightly) ───────
CACHE_PK       = "CACHE#matthew"
CACHE_TTL_SECS = 26 * 3600  # 26 hours

def ddb_cache_get(cache_key: str):
    """Read a pre-computed result from DynamoDB. Returns None on miss/expiry."""
    try:
        resp = table.get_item(Key={"pk": CACHE_PK, "sk": f"TOOL#{cache_key}"})
        item = resp.get("Item")
        if not item:
            return None
        ttl = item.get("ttl")
        if ttl and float(ttl) < time.time():
            logger.info(f"[cache:ddb] stale — {cache_key}")
            return None
        payload = item.get("payload")
        if payload:
            logger.info(f"[cache:ddb] hit — {cache_key}")
            return json.loads(payload)
    except Exception as e:
        logger.warning(f"[cache:ddb] read error for {cache_key}: {e}")
    return None

def ddb_cache_set(cache_key: str, data):
    """Write a pre-computed result to DynamoDB cache with a TTL."""
    try:
        ttl_epoch = int(time.time()) + CACHE_TTL_SECS
        table.put_item(Item={
            "pk":           CACHE_PK,
            "sk":           f"TOOL#{cache_key}",
            "payload":      json.dumps(data, default=str),
            "ttl":          Decimal(str(ttl_epoch)),   # DynamoDB TTL attribute — auto-expires after 26h
            "computed_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        logger.info(f"[cache:ddb] stored — {cache_key}")
    except Exception as e:
        logger.warning(f"[cache:ddb] write error for {cache_key}: {e}")


# ── Serialisation helpers ─────────────────────────────────────────────────────
def decimal_to_float(obj):
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    if isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def get_api_key():
    try:
        return secrets.get_secret_value(SecretId=API_SECRET_NAME)["SecretString"]
    except Exception as e:
        logger.warning(f"Could not retrieve API key: {e}")
        return None


# ── DynamoDB query with full pagination ───────────────────────────────────────
# Fields that are never numeric and are expensive to transfer (large arrays).
# Stripped post-fetch for any path that only needs numeric aggregation.
_LEAN_STRIP = {"activities", "sport_types", "pk", "sk", "ingested_at", "source"}


def query_source(source, start_date, end_date, lean=False):
    """Query DynamoDB by source + date range with full pagination.
    lean=True: strip large non-numeric fields post-fetch (saves ~30-50% RAM
    for Strava which embeds full activity objects in each day record).
    """
    pk = f"{USER_PREFIX}{source}"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}~"
        )
    }
    items = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
        logger.info(f"query_source paginating {source}: {len(items)} items so far")
    raw = decimal_to_float(items)
    if lean:
        return [{k: v for k, v in item.items() if k not in _LEAN_STRIP} for item in raw]
    return raw


def parallel_query_sources(sources, start_date, end_date, lean=False):
    """Query multiple DynamoDB sources concurrently. Returns {source: [items]}.
    lean=True: strip non-numeric/large fields post-fetch (see query_source)."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sources), 5)) as pool:
        future_to_src = {
            pool.submit(query_source, src, start_date, end_date, lean): src
            for src in sources
        }
        for future in concurrent.futures.as_completed(future_to_src):
            src = future_to_src[future]
            try:
                results[src] = future.result()
            except Exception as e:
                logger.warning(f"parallel_query_sources failed for {src}: {e}")
                results[src] = []
    return results


def date_diff_days(start, end):
    try:
        return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    except Exception:
        return 0


# ── Aggregation helpers ───────────────────────────────────────────────────────
def aggregate_items(items, period):
    buckets = defaultdict(lambda: defaultdict(list))
    skip_fields = {"pk", "sk", "source", "ingested_at", "date", "activities", "sport_types"}

    for item in items:
        date = item.get("date", "")
        if not date or len(date) < 7:
            continue
        if "#WORKOUT#" in item.get("sk", ""):
            continue
        key = date[:7] if period == "month" else date[:4]
        for field, value in item.items():
            if field in skip_fields:
                continue
            if isinstance(value, (int, float)):
                buckets[key][field].append(value)

    result = []
    for period_key in sorted(buckets.keys()):
        row = {"period": period_key}
        field_data = buckets[period_key]
        if field_data:
            row["days_with_data"] = len(next(iter(field_data.values())))
        for field, values in field_data.items():
            row[f"{field}_avg"] = round(sum(values) / len(values), 2)
            row[f"{field}_min"] = round(min(values), 2)
            row[f"{field}_max"] = round(max(values), 2)
        result.append(row)
    return result


def resolve_field(source, field):
    aliases = FIELD_ALIASES.get(source, {})
    return aliases.get(field, field)


def flatten_strava_activity(day_record):
    """Flatten a Strava day record + nested activities into one dict per activity."""
    activities = day_record.get("activities", [])
    result = []
    for act in activities:
        sport_type = act.get("sport_type") or act.get("type") or ""
        flat = {
            "date":                      day_record.get("date"),
            "name":                      act.get("name"),
            "enriched_name":             act.get("enriched_name"),
            "sport_type":                sport_type,
            "distance_miles":            act.get("distance_miles"),
            "total_elevation_gain_feet": act.get("total_elevation_gain_feet"),
            "moving_time_seconds":       act.get("moving_time_seconds"),
            "average_heartrate":         act.get("average_heartrate"),
            "max_heartrate":             act.get("max_heartrate"),
            "average_watts":             act.get("average_watts"),
            "kilojoules":                act.get("kilojoules"),
            "pr_count":                  act.get("pr_count"),
            "achievement_count":         act.get("achievement_count"),
            "strava_id":                 act.get("strava_id"),
        }
        result.append({k: v for k, v in flat.items() if v is not None})
    return result


# ── Training load model helpers ───────────────────────────────────────────────
def compute_daily_load_score(day_record):
    kj     = day_record.get("total_kilojoules") or 0
    dist   = day_record.get("total_distance_miles") or 0
    elev   = day_record.get("total_elevation_gain_feet") or 0
    hr_avg = day_record.get("average_heartrate") or 0
    time_s = day_record.get("total_moving_time_seconds") or 0

    if kj > 0:
        return float(kj)

    if hr_avg > 0 and time_s > 0:
        profile = get_profile()
        rhr = profile.get("resting_heart_rate_baseline", 55)
        mhr = profile.get("max_heart_rate", 190)
        hr_r = (hr_avg - rhr) / max(mhr - rhr, 1)
        trimp = (time_s / 3600) * hr_avg * 0.64 * math.exp(1.92 * hr_r)
        return round(trimp, 1)

    return round(dist * 10 + elev / 100, 1)


def compute_ewa(daily_values_chrono, decay_days):
    alpha  = 1.0 - math.exp(-1.0 / decay_days)
    ewa    = 0.0
    result = []
    for date_str, val in daily_values_chrono:
        ewa = alpha * val + (1 - alpha) * ewa
        result.append((date_str, round(ewa, 2)))
    return result


def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num   = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = math.sqrt(sum((x - mx)**2 for x in xs) * sum((y - my)**2 for y in ys))
    if denom == 0:
        return None
    return round(num / denom, 3)


# ── Strength training helpers ─────────────────────────────────────────────────

_EXERCISE_MUSCLE_MAP = [
    # (keywords, muscle_groups, movement_pattern)
    (["bench press", "chest press", "pec deck", "fly", "flye", "push up", "pushup"],
     ["Chest", "Triceps", "Shoulders"], "Push"),
    (["overhead press", "ohp", "shoulder press", "military press", "dumbbell press", "arnold"],
     ["Shoulders", "Triceps"], "Push"),
    (["tricep", "triceps", "skull crusher", "pushdown", "push down", "close grip", "dip"],
     ["Triceps", "Chest"], "Push"),
    (["pull up", "pullup", "chin up", "chinup", "lat pulldown", "pull-up", "pull-down"],
     ["Back", "Biceps"], "Pull"),
    (["row", "rowing", "cable row", "t-bar", "seated row"],
     ["Back", "Biceps"], "Pull"),
    (["deadlift"],
     ["Back", "Hamstrings", "Glutes", "Quads"], "Pull"),
    (["back extension", "hyperextension", "good morning"],
     ["Back", "Hamstrings", "Glutes"], "Pull"),
    (["bicep", "biceps", "curl", "hammer curl"],
     ["Biceps"], "Pull"),
    (["squat", "goblet"],
     ["Quads", "Glutes", "Hamstrings"], "Legs"),
    (["leg press"],
     ["Quads", "Glutes", "Hamstrings"], "Legs"),
    (["lunge", "step up", "bulgarian"],
     ["Quads", "Glutes", "Hamstrings"], "Legs"),
    (["leg extension", "leg curl", "hamstring curl", "nordic"],
     ["Quads", "Hamstrings"], "Legs"),
    (["hip thrust", "glute bridge", "hip abduct", "hip adduct"],
     ["Glutes", "Hamstrings"], "Legs"),
    (["calf", "calves", "standing calf", "seated calf"],
     ["Calves"], "Legs"),
    (["plank", "crunch", "ab ", "abs ", "core", "oblique", "sit up", "situp", "hanging leg", "windshield"],
     ["Core"], "Core"),
]

_BODYWEIGHT_EXERCISES = [
    "pull up", "pullup", "pull-up", "chin up", "chinup", "chin-up",
    "dip", "push up", "pushup", "push-up", "bodyweight squat",
]



# ── Day Type Classification (Phase 2c) ───────────────────────────────────────

def classify_day_type(whoop_strain=None, strava_activities=None, daily_load=None):
    """
    Classify a day as rest/light/moderate/hard/race based on training signals.

    Priority:
      1. Strava activity type == 'Race' → 'race'
      2. Whoop strain or computed load → thresholds
      3. Strava activity count + distance as fallback

    Returns: 'rest', 'light', 'moderate', 'hard', or 'race'
    """
    # Check for race flag in Strava activities
    if strava_activities:
        for act in (strava_activities if isinstance(strava_activities, list) else [strava_activities]):
            if isinstance(act, dict):
                if act.get("workout_type") == "Race" or act.get("type", "").lower() == "race":
                    return "race"

    # Primary: Whoop strain (0-21 scale)
    if whoop_strain is not None:
        strain = float(whoop_strain)
        if strain < 4:
            return "rest"
        elif strain < 8:
            return "light"
        elif strain < 14:
            return "moderate"
        else:
            return "hard"

    # Secondary: computed load score (kJ or TRIMP)
    if daily_load is not None:
        load = float(daily_load)
        if load < 50:
            return "rest"
        elif load < 200:
            return "light"
        elif load < 500:
            return "moderate"
        else:
            return "hard"

    # Tertiary: Strava activity presence
    if strava_activities:
        acts = strava_activities if isinstance(strava_activities, list) else [strava_activities]
        if isinstance(acts[0], dict):
            total_dist = sum(float(a.get("total_distance_miles", 0) or 0) for a in acts)
            total_time = sum(float(a.get("total_moving_time_seconds", 0) or 0) for a in acts)
            if total_dist > 10 or total_time > 5400:
                return "hard"
            elif total_dist > 3 or total_time > 2700:
                return "moderate"
            elif total_dist > 0 or total_time > 0:
                return "light"

    return "rest"


DAY_TYPE_THRESHOLDS = {
    "whoop_strain": {"rest": 4, "light": 8, "moderate": 14, "hard": 21},
    "load_score":   {"rest": 50, "light": 200, "moderate": 500, "hard": float("inf")},
}

def classify_exercise(name: str) -> dict:
    """Return {muscle_groups, movement_pattern} for an exercise name."""
    nl = name.lower()
    for keywords, muscles, pattern in _EXERCISE_MUSCLE_MAP:
        if any(kw in nl for kw in keywords):
            return {"muscle_groups": muscles, "movement_pattern": pattern}
    return {"muscle_groups": ["Other"], "movement_pattern": "Other"}


def is_bodyweight(name: str) -> bool:
    nl = name.lower()
    return any(kw in nl for kw in _BODYWEIGHT_EXERCISES)


def estimate_1rm(weight: float, reps: int) -> float | None:
    """Epley formula. Valid for reps 1-10."""
    if weight <= 0 or reps < 1 or reps > 10:
        return None
    if reps == 1:
        return round(weight, 1)
    return round(weight * (1 + reps / 30), 1)


def extract_hevy_sessions(hevy_items: list, exercise_name: str, include_warmups: bool = False) -> list:
    """
    Given raw DynamoDB hevy items and a target exercise name (fuzzy),
    return a list of session dicts sorted by date.
    Each session: {date, sets: [{set_type, weight_lbs, reps, estimated_1rm}], best_1rm, best_weight, volume}
    """
    target = exercise_name.lower()
    sessions = []
    for item in hevy_items:
        day_data = item.get("data", {})
        workouts = day_data.get("workouts", [])
        date_str = item.get("date") or item.get("sk", "")[:10]
        for workout in workouts:
            for ex in workout.get("exercises", []):
                ex_name = ex.get("name", "")
                if target not in ex_name.lower():
                    continue
                sets_out = []
                for s in ex.get("sets", []):
                    st = s.get("set_type", "normal")
                    if not include_warmups and st == "warmup":
                        continue
                    w = float(s.get("weight_lbs", 0) or 0)
                    r = int(s.get("reps", 0) or 0)
                    e1rm = None if is_bodyweight(ex_name) else estimate_1rm(w, r)
                    sets_out.append({"set_type": st, "weight_lbs": w, "reps": r, "estimated_1rm": e1rm})
                if not sets_out:
                    continue
                best_1rm = max((s["estimated_1rm"] for s in sets_out if s["estimated_1rm"]), default=None)
                best_weight = max((s["weight_lbs"] for s in sets_out), default=0)
                volume = sum(s["weight_lbs"] * s["reps"] for s in sets_out)
                sessions.append({
                    "date": date_str,
                    "exercise_name": ex_name,
                    "sets": sets_out,
                    "best_1rm": best_1rm,
                    "best_weight": best_weight,
                    "volume_lbs": round(volume, 1),
                    "set_count": len(sets_out),
                })
    sessions.sort(key=lambda x: x["date"])
    return sessions


_VOLUME_LANDMARKS = {
    "Chest":       {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Back":        {"MV": 6,  "MEV": 10, "MAV_lo": 14, "MAV_hi": 20, "MRV": 25},
    "Shoulders":   {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 20, "MRV": 25},
    "Quads":       {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Hamstrings":  {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Glutes":      {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Biceps":      {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Triceps":     {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Calves":      {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Core":        {"MV": 0,  "MEV": 4,  "MAV_lo": 6,  "MAV_hi": 16, "MRV": 25},
    "Other":       {"MV": 0,  "MEV": 0,  "MAV_lo": 0,  "MAV_hi": 0,  "MRV": 99},
}

def volume_status(muscle: str, sets_per_week: float) -> str:
    lm = _VOLUME_LANDMARKS.get(muscle, _VOLUME_LANDMARKS["Other"])
    if sets_per_week < lm["MV"]:
        return "below maintenance"
    if sets_per_week < lm["MEV"]:
        return "maintenance only"
    if sets_per_week <= lm["MAV_lo"]:
        return "approaching MEV / low optimal"
    if sets_per_week <= lm["MAV_hi"]:
        return "optimal (MEV–MAV)"
    if sets_per_week <= lm["MRV"]:
        return "approaching MRV – high volume"
    return "exceeding MRV – overtraining risk"


_STRENGTH_STANDARDS = {
    "bench press":     {"Untrained": 0.50, "Novice": 0.75, "Intermediate": 1.00, "Advanced": 1.50, "Elite": 2.00},
    "squat":           {"Untrained": 0.75, "Novice": 1.00, "Intermediate": 1.50, "Advanced": 2.00, "Elite": 2.75},
    "deadlift":        {"Untrained": 1.00, "Novice": 1.25, "Intermediate": 1.75, "Advanced": 2.50, "Elite": 3.25},
    "overhead press":  {"Untrained": 0.35, "Novice": 0.50, "Intermediate": 0.75, "Advanced": 1.00, "Elite": 1.50},
}
_STANDARD_LEVELS = ["Untrained", "Novice", "Intermediate", "Advanced", "Elite"]

def classify_standard(lift_key: str, bw_ratio: float) -> tuple[str, str | None, float | None]:
    """Return (level, next_level, ratio_needed_for_next)."""
    stds = _STRENGTH_STANDARDS[lift_key]
    current = "Untrained"
    for lvl in _STANDARD_LEVELS:
        if bw_ratio >= stds[lvl]:
            current = lvl
    idx = _STANDARD_LEVELS.index(current)
    if idx < len(_STANDARD_LEVELS) - 1:
        next_lvl = _STANDARD_LEVELS[idx + 1]
        next_ratio = stds[next_lvl]
    else:
        next_lvl = None
        next_ratio = None
    return current, next_lvl, next_ratio


# ── Tool implementations ──────────────────────────────────────────────────────

def tool_get_sources(_args):
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        oldest = table.query(
            KeyConditionExpression=Key("pk").eq(pk), Limit=1, ScanIndexForward=True,
            ProjectionExpression="#dt", ExpressionAttributeNames={"#dt": "date"},
        )
        newest = table.query(
            KeyConditionExpression=Key("pk").eq(pk), Limit=1, ScanIndexForward=False,
            ProjectionExpression="#dt", ExpressionAttributeNames={"#dt": "date"},
        )
        first = oldest["Items"][0]["date"] if oldest["Items"] else None
        last  = newest["Items"][0]["date"] if newest["Items"] else None
        result[source] = {"available": first is not None, "first_date": first, "latest_date": last}
    return result


def tool_get_latest(args):
    sources = args.get("sources", SOURCES)
    result  = {}
    for source in sources:
        pk = f"{USER_PREFIX}{source}"
        response = table.query(KeyConditionExpression=Key("pk").eq(pk), Limit=1, ScanIndexForward=False)
        items = decimal_to_float(response.get("Items", []))
        result[source] = items[0] if items else None
    return result


def tool_get_daily_summary(args):
    date = args.get("date")
    if not date:
        raise ValueError("'date' is required (YYYY-MM-DD)")
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        response = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(f"DATE#{date}")
        )
        items = decimal_to_float(response.get("Items", []))
        if items:
            result[source] = items
    return result


def tool_get_date_range(args):
    source     = args.get("source")
    start_date = args.get("start_date")
    end_date   = args.get("end_date")
    if not all([source, start_date, end_date]):
        raise ValueError("'source', 'start_date', and 'end_date' are required")
    if source not in SOURCES:
        raise ValueError(f"Unknown source '{source}'. Valid: {SOURCES}")

    days  = date_diff_days(start_date, end_date)
    items = query_source(source, start_date, end_date)

    if days > RAW_DAY_LIMIT:
        period = "year" if days > 365 * 2 else "month"
        return {
            "note":       f"Window of {days} days — returning {period}ly aggregates.",
            "period":     period,
            "source":     source,
            "aggregated": aggregate_items(items, period),
        }

    return {"note": "Raw daily data.", "source": source, "items": items}


def tool_find_days(args):
    source     = args.get("source")
    start_date = args.get("start_date")
    end_date   = args.get("end_date")
    filters    = args.get("filters", [])
    if not all([source, start_date, end_date]):
        raise ValueError("'source', 'start_date', and 'end_date' are required")

    items = query_source(source, start_date, end_date)

    def passes(item):
        for f in filters:
            field  = resolve_field(source, f["field"])
            actual = item.get(field)
            if actual is None:
                return False
            actual = float(actual)
            value  = float(f["value"])
            op     = f["op"]
            if op == ">"  and not actual >  value: return False
            if op == ">=" and not actual >= value: return False
            if op == "<"  and not actual <  value: return False
            if op == "<=" and not actual <= value: return False
            if op == "="  and not actual == value: return False
        return True

    matched = [item for item in items if passes(item)]

    if len(matched) > 200:
        key_fields = {"date", "recovery_score", "hrv", "strain", "weight_lbs",
                      "sleep_duration_hours", "resting_heart_rate",
                      "total_distance_miles", "total_elevation_gain_feet", "sport_types"}
        matched = [{k: v for k, v in m.items() if k in key_fields} for m in matched]

    return matched


def tool_get_aggregated_summary(args):
    source   = args.get("source")
    period   = args.get("period", "year")
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    if period not in ("month", "year"):
        raise ValueError("'period' must be 'month' or 'year'")

    if source and source in SOURCES:
        default_start = "2010-01-01"
    else:
        if period == "year":
            default_start = (datetime.utcnow() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
        else:
            default_start = (datetime.utcnow() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")

    start_date = args.get("start_date", default_start)
    sources_to_query = [source] if source and source in SOURCES else SOURCES

    cache_key = f"aggregated_summary_{period}_{start_date}_{end_date}_{','.join(sources_to_query)}"
    cached = ddb_cache_get(cache_key) or mem_cache_get(cache_key)
    if cached:
        return cached

    if len(sources_to_query) > 1:
        source_data = parallel_query_sources(sources_to_query, start_date, end_date, lean=True)
    else:
        source_data = {sources_to_query[0]: query_source(sources_to_query[0], start_date, end_date, lean=True)}

    result = {}
    for src, items in source_data.items():
        if items:
            result[src] = aggregate_items(items, period)

    payload = {
        "period":     period,
        "start_date": start_date,
        "end_date":   end_date,
        "note":       "Pass an explicit start_date to override the default window." if not args.get("start_date") else None,
        "sources":    result,
    }
    mem_cache_set(cache_key, payload)
    return payload


def tool_search_activities(args):
    start_date    = args.get("start_date", "2010-01-01")
    end_date      = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    name_contains = args.get("name_contains", "").lower()
    sport_type    = args.get("sport_type", "").lower()
    min_distance  = args.get("min_distance_miles")
    min_elevation = args.get("min_elevation_gain_feet")
    sort_by       = args.get("sort_by", "distance_miles")
    limit         = int(args.get("limit", 100))

    day_records = query_source(get_sot("cardio"), start_date, end_date)

    all_activities = []
    for day in day_records:
        all_activities.extend(flatten_strava_activity(day))

    all_sort_vals = sorted(
        [float(a.get(sort_by, 0) or 0) for a in all_activities if a.get(sort_by) is not None]
    )
    total_for_rank = len(all_sort_vals)

    def percentile_rank(val):
        if total_for_rank == 0:
            return None
        pos = bisect.bisect_left(all_sort_vals, float(val))
        return round(100.0 * pos / total_for_rank, 1)

    matched = []
    for act in all_activities:
        if name_contains:
            name_match     = name_contains in (act.get("name")          or "").lower()
            enriched_match = name_contains in (act.get("enriched_name") or "").lower()
            if not (name_match or enriched_match):
                continue
        if sport_type and sport_type not in (act.get("sport_type") or "").lower():
            continue
        if min_distance is not None:
            dist = act.get("distance_miles")
            if dist is None or float(dist) < float(min_distance):
                continue
        if min_elevation is not None:
            elev = act.get("total_elevation_gain_feet")
            if elev is None or float(elev) < float(min_elevation):
                continue
        matched.append(act)

    matched.sort(key=lambda x: float(x.get(sort_by, 0) or 0), reverse=True)

    results = []
    for act in matched[:limit]:
        enriched = dict(act)
        sort_val = act.get(sort_by)
        if sort_val is not None:
            pct = percentile_rank(sort_val)
            enriched[f"{sort_by}_all_time_percentile"] = pct
            if pct is not None:
                if pct >= 99:
                    enriched["context"] = f"ALL-TIME top 1% for {sort_by}"
                elif pct >= 95:
                    enriched["context"] = f"Top 5% all-time for {sort_by}"
                elif pct >= 90:
                    enriched["context"] = f"Top 10% all-time for {sort_by}"
        results.append(enriched)

    return {
        "total_matched":       len(matched),
        "showing":             len(results),
        "sorted_by":           sort_by,
        "all_time_total_acts": total_for_rank,
        "activities":          results,
    }


def tool_get_field_stats(args):
    source     = args.get("source")
    field      = args.get("field")
    start_date = args.get("start_date", "2010-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    if not source or not field:
        raise ValueError("'source' and 'field' are required")
    if source not in SOURCES:
        raise ValueError(f"Unknown source '{source}'. Valid: {SOURCES}")

    items = query_source(source, start_date, end_date)
    resolved_field = resolve_field(source, field)

    values = []
    for item in sorted(items, key=lambda x: x.get("date", "")):
        if "#WORKOUT#" in item.get("sk", ""):
            continue
        val = item.get(resolved_field)
        if val is not None:
            values.append((round(float(val), 2), item.get("date", "unknown")))

    if not values:
        return {"source": source, "field": resolved_field,
                "message": "No data found for this field in the specified range."}

    nums    = [v for v, _ in values]
    max_val = max(nums)
    min_val = min(nums)
    avg_val = round(sum(nums) / len(nums), 2)

    sorted_desc = sorted(values, key=lambda x: x[0], reverse=True)
    sorted_asc  = sorted(values, key=lambda x: x[0])
    top5_high   = [{"value": v, "date": d} for v, d in sorted_desc[:5]]
    top5_low    = [{"value": v, "date": d} for v, d in sorted_asc[:5]]

    third = max(1, len(values) // 3)
    early_avg = round(sum(v for v, _ in values[:third]) / third, 2)
    late_avg  = round(sum(v for v, _ in values[-third:]) / third, 2)
    delta     = round(late_avg - early_avg, 2)
    if abs(delta) < 0.5:
        trend = "stable"
    elif delta > 0:
        trend = f"increasing (+{delta} from early to recent average)"
    else:
        trend = f"decreasing ({delta} from early to recent average)"

    return {
        "source":           source,
        "field":            resolved_field,
        "start_date":       start_date,
        "end_date":         end_date,
        "count":            len(nums),
        "max":              max_val,
        "max_dates":        [d for v, d in values if v == max_val],
        "min":              min_val,
        "min_dates":        [d for v, d in values if v == min_val],
        "avg":              avg_val,
        "top5_highest":     top5_high,
        "top5_lowest":      top5_low,
        "trend":            trend,
        "early_period_avg": early_avg,
        "recent_period_avg":late_avg,
        "storytelling_tip": "Pair with get_aggregated_summary (period=year) for the full arc.",
    }


def tool_compare_periods(args):
    pa_start = args.get("period_a_start")
    pa_end   = args.get("period_a_end")
    pb_start = args.get("period_b_start")
    pb_end   = args.get("period_b_end")
    pa_label = args.get("period_a_label", "Period A")
    pb_label = args.get("period_b_label", "Period B")
    source   = args.get("source")

    if not all([pa_start, pa_end, pb_start, pb_end]):
        raise ValueError("period_a_start, period_a_end, period_b_start, period_b_end are all required")

    sources_to_query = [source] if source and source in SOURCES else SOURCES
    skip_fields = {"pk", "sk", "source", "ingested_at", "date", "activities", "sport_types"}

    result = {
        "period_a": {"label": pa_label, "start": pa_start, "end": pa_end},
        "period_b": {"label": pb_label, "start": pb_start, "end": pb_end},
        "sources":  {}
    }

    for src in sources_to_query:
        items_a = query_source(src, pa_start, pa_end)
        items_b = query_source(src, pb_start, pb_end)
        if not items_a and not items_b:
            continue

        def field_avgs(items):
            buckets = defaultdict(list)
            for item in items:
                if "#WORKOUT#" in item.get("sk", ""):
                    continue
                for k, v in item.items():
                    if k not in skip_fields and isinstance(v, (int, float)):
                        buckets[k].append(float(v))
            return {k: round(sum(v) / len(v), 2) for k, v in buckets.items() if v}

        avgs_a = field_avgs(items_a)
        avgs_b = field_avgs(items_b)
        all_fields = sorted(set(avgs_a) | set(avgs_b))

        comparisons = {}
        for field in all_fields:
            val_a = avgs_a.get(field)
            val_b = avgs_b.get(field)
            row = {pa_label: val_a, pb_label: val_b}
            if val_a is not None and val_b is not None:
                delta = round(val_b - val_a, 2)
                pct   = round(100.0 * delta / val_a, 1) if val_a != 0 else None
                row["delta"]     = delta
                row["pct_change"]= pct
                row["direction"] = "improved" if delta > 0 else ("declined" if delta < 0 else "unchanged")
            comparisons[field] = row

        result["sources"][src] = {
            "days_in_period_a": len(items_a),
            "days_in_period_b": len(items_b),
            "fields": comparisons,
        }

    return result


def tool_get_weekly_summary(args):
    start_date = args.get("start_date", "2000-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    sort_by    = args.get("sort_by", "total_distance_miles")
    limit      = int(args.get("limit", 52))
    sort_asc   = args.get("sort_ascending", False)

    day_records = query_source(get_sot("cardio"), start_date, end_date)

    weeks = defaultdict(lambda: {
        "total_distance_miles": 0.0,
        "total_elevation_gain_feet": 0.0,
        "total_moving_time_seconds": 0,
        "activity_count": 0,
        "days_active": 0,
        "sport_types": defaultdict(int),
        "dates": [],
    })

    for day in day_records:
        date_str = day.get("date", "")
        if not date_str:
            continue
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        except ValueError:
            continue

        w = weeks[key]
        w["total_distance_miles"]      += float(day.get("total_distance_miles") or 0)
        w["total_elevation_gain_feet"] += float(day.get("total_elevation_gain_feet") or 0)
        w["total_moving_time_seconds"] += int(day.get("total_moving_time_seconds") or 0)
        w["activity_count"]            += int(day.get("activity_count") or 0)
        w["days_active"]               += 1
        w["dates"].append(date_str)
        for st in (day.get("sport_types") or []):
            if st:
                w["sport_types"][st] += 1

    rows = []
    for week_key, w in weeks.items():
        rows.append({
            "week":                      week_key,
            "week_start":                min(w["dates"]) if w["dates"] else "",
            "week_end":                  max(w["dates"]) if w["dates"] else "",
            "total_distance_miles":      round(w["total_distance_miles"], 2),
            "total_elevation_gain_feet": round(w["total_elevation_gain_feet"], 1),
            "total_moving_time_seconds": w["total_moving_time_seconds"],
            "activity_count":            w["activity_count"],
            "days_active":               w["days_active"],
            "sport_types":               dict(w["sport_types"]),
        })

    rows.sort(key=lambda x: x.get(sort_by, 0), reverse=not sort_asc)

    return {
        "total_weeks_with_data": len(rows),
        "sorted_by":             sort_by,
        "weeks":                 rows[:limit],
    }


def tool_get_training_load(args):
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_dt   = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=180)
    start_date = args.get("start_date", start_dt.strftime("%Y-%m-%d"))
    warmup_dt  = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=84)
    warmup_start = warmup_dt.strftime("%Y-%m-%d")

    cardio_source = get_sot("cardio")
    day_records = query_source(cardio_source, warmup_start, end_date)

    load_by_date = {}
    for day in day_records:
        d = day.get("date")
        if d:
            load_by_date[d] = compute_daily_load_score(day)

    cur = warmup_dt
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    chrono = []
    while cur <= end_dt:
        ds = cur.strftime("%Y-%m-%d")
        chrono.append((ds, load_by_date.get(ds, 0.0)))
        cur += timedelta(days=1)

    ctl_series = compute_ewa(chrono, 42)
    atl_series = compute_ewa(chrono, 7)

    start_dt_req = datetime.strptime(start_date, "%Y-%m-%d")
    result_rows = []
    for (date_str, ctl), (_, atl) in zip(ctl_series, atl_series):
        if datetime.strptime(date_str, "%Y-%m-%d") < start_dt_req:
            continue
        tsb  = round(ctl - atl, 2)
        acwr = round(atl / ctl, 2) if ctl > 0 else None

        risk = "low"
        if acwr is not None:
            if acwr > 1.5:
                risk = "HIGH — injury risk elevated, consider reducing load"
            elif acwr > 1.3:
                risk = "moderate — monitor carefully"

        form = "neutral"
        if tsb > 5:
            form = "fresh — good for key sessions or race"
        elif tsb < -10:
            form = "fatigued — accumulated training stress is high"
        elif tsb < -25:
            form = "very fatigued — recovery priority"

        result_rows.append({
            "date":           date_str,
            "daily_load":     round(load_by_date.get(date_str, 0.0), 1),
            "ctl_fitness":    ctl,
            "atl_fatigue":    atl,
            "tsb_form":       tsb,
            "acwr":           acwr,
            "injury_risk":    risk,
            "form_status":    form,
        })

    if not result_rows:
        return {"message": "No training data found for the requested window."}

    latest = result_rows[-1]
    peak_ctl = max(result_rows, key=lambda r: r["ctl_fitness"])

    # Board rec 1D: Training monotony (Galpin) — weekly mean / SD of daily load
    last_7_loads = [r["daily_load"] for r in result_rows[-7:]]
    monotony_result = {}
    if len(last_7_loads) >= 7:
        mean_7 = sum(last_7_loads) / len(last_7_loads)
        var_7 = sum((x - mean_7) ** 2 for x in last_7_loads) / len(last_7_loads)
        sd_7 = var_7 ** 0.5 if var_7 > 0 else 0
        monotony = round(mean_7 / sd_7, 2) if sd_7 > 0 else None
        weekly_strain = round(sum(last_7_loads) * monotony, 1) if monotony else None
        monotony_result = {
            "training_monotony": monotony,
            "weekly_training_strain": weekly_strain,
            "monotony_risk": "HIGH — monotonous training increases illness/overtraining risk" if monotony and monotony > 2.0 else "ok",
        }

    return {
        "model":          "Banister Impulse-Response (CTL=42d EWA, ATL=7d EWA)",
        "load_proxy":     "kJ (cycling) > TRIMP (HR×time) > distance+elevation estimate",
        "current_state":  latest,
        "peak_fitness":   {"ctl": peak_ctl["ctl_fitness"], "date": peak_ctl["date"]},
        "monotony":       monotony_result,
        "series":         result_rows,
        "interpretation": {
            "CTL": "Fitness base (42-day). Higher = more aerobic capacity built.",
            "ATL": "Fatigue (7-day). Spikes after big training blocks.",
            "TSB": "Form = CTL - ATL. Positive = fresh, negative = tired.",
            "ACWR": "Acute:Chronic ratio. >1.3 caution, >1.5 injury risk.",
            "Monotony": "Weekly mean load / SD. >2.0 = illness risk (Galpin). Vary intensity.",
        },
    }


def tool_get_personal_records(args):
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    profile  = get_profile()
    dob_str  = profile.get("date_of_birth")

    def age_at(date_str):
        if not dob_str or not date_str:
            return None
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d")
            d   = datetime.strptime(date_str, "%Y-%m-%d")
            return round((d - dob).days / 365.25, 1)
        except Exception:
            return None

    records = {}

    pr_cache_key = f"personal_records_{end_date}"
    cached = ddb_cache_get(pr_cache_key) or mem_cache_get(pr_cache_key)
    if cached:
        return cached

    pr_sources = parallel_query_sources([get_sot("cardio"), get_sot("physiology"), get_sot("body")], "2000-01-01", end_date)

    strava_days = pr_sources.get(get_sot("cardio"), [])
    all_acts    = []
    for day in strava_days:
        all_acts.extend(flatten_strava_activity(day))

    act_fields = {
        "longest_activity_miles":         ("distance_miles",            "max"),
        "most_elevation_gain_feet":        ("total_elevation_gain_feet", "max"),
        "longest_moving_time_seconds":     ("moving_time_seconds",       "max"),
        "highest_avg_heartrate_bpm":       ("average_heartrate",         "max"),
        "highest_max_heartrate_bpm":       ("max_heartrate",             "max"),
        "highest_avg_watts":               ("average_watts",             "max"),
        "most_kilojoules":                 ("kilojoules",                "max"),
        "most_prs_in_one_activity":        ("pr_count",                  "max"),
    }

    for label, (field, mode) in act_fields.items():
        candidates = [(float(a[field]), a) for a in all_acts if a.get(field) is not None]
        if not candidates:
            continue
        best_val, best_act = max(candidates, key=lambda x: x[0])
        records[label] = {
            "value":      round(best_val, 2),
            "date":       best_act.get("date"),
            "activity":   best_act.get("name"),
            "sport_type": best_act.get("sport_type"),
            "age_at_record": age_at(best_act.get("date")),
        }

    day_fields = {
        "biggest_day_miles":     ("total_distance_miles",      "max"),
        "biggest_day_elevation": ("total_elevation_gain_feet", "max"),
        "most_activities_in_day":("activity_count",            "max"),
    }
    for label, (field, mode) in day_fields.items():
        candidates = [(float(d[field]), d) for d in strava_days if d.get(field)]
        if not candidates:
            continue
        best_val, best_day = max(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    weeks = defaultdict(lambda: {"miles": 0.0, "elev": 0.0, "dates": []})
    for day in strava_days:
        date_str = day.get("date", "")
        if not date_str:
            continue
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        except ValueError:
            continue
        weeks[key]["miles"] += float(day.get("total_distance_miles") or 0)
        weeks[key]["elev"]  += float(day.get("total_elevation_gain_feet") or 0)
        weeks[key]["dates"].append(date_str)

    if weeks:
        best_week_miles = max(weeks.items(), key=lambda x: x[1]["miles"])
        best_week_elev  = max(weeks.items(), key=lambda x: x[1]["elev"])
        records["biggest_week_miles"] = {
            "value": round(best_week_miles[1]["miles"], 2),
            "week":  best_week_miles[0],
            "week_start": min(best_week_miles[1]["dates"]),
            "age_at_record": age_at(min(best_week_miles[1]["dates"])),
        }
        records["biggest_week_elevation_feet"] = {
            "value": round(best_week_elev[1]["elev"], 1),
            "week":  best_week_elev[0],
            "week_start": min(best_week_elev[1]["dates"]),
            "age_at_record": age_at(min(best_week_elev[1]["dates"])),
        }

    whoop_days = pr_sources.get("whoop", [])
    whoop_fields = {
        "best_hrv_ms":              ("hrv",                 "max"),
        "lowest_resting_hr_bpm":    ("resting_heart_rate",  "min"),
        "best_recovery_score":      ("recovery_score",      "max"),
        "highest_strain":           ("strain",              "max"),
        "longest_sleep_hours":      ("sleep_duration_hours","max"),
        "worst_recovery_score":     ("recovery_score",      "min"),
    }
    for label, (field, mode) in whoop_fields.items():
        candidates = [(float(d[field]), d) for d in whoop_days if d.get(field) is not None]
        if not candidates:
            continue
        best_val, best_day = (max if mode == "max" else min)(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    withings_days = pr_sources.get("withings", [])
    withings_fields = {
        "heaviest_weight_lbs":   ("weight_lbs", "max"),
        "lightest_weight_lbs":   ("weight_lbs", "min"),
        "lowest_body_fat_pct":   ("body_fat_percentage", "min"),
        "highest_muscle_mass_lbs": ("muscle_mass_lbs", "max"),
    }
    for label, (field, mode) in withings_fields.items():
        candidates = [(float(d[field]), d) for d in withings_days if d.get(field) is not None]
        if not candidates:
            continue
        best_val, best_day = (max if mode == "max" else min)(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    payload = {
        "profile_dob":    dob_str,
        "records_through": end_date,
        "total_records":  len(records),
        "records":        records,
        "coaching_note":  "Age at record enables tracking whether peak performances are trending younger or older over time.",
    }
    ddb_cache_set(pr_cache_key, payload)
    mem_cache_set(pr_cache_key, payload)
    return payload


def tool_get_cross_source_correlation(args):
    source_a   = args.get("source_a")
    field_a    = args.get("field_a")
    source_b   = args.get("source_b")
    field_b    = args.get("field_b")
    start_date = args.get("start_date", "2019-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    lag_days   = int(args.get("lag_days", 0))

    if not all([source_a, field_a, source_b, field_b]):
        raise ValueError("source_a, field_a, source_b, field_b are all required")

    lag_end_dt  = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=abs(lag_days))
    lag_end     = lag_end_dt.strftime("%Y-%m-%d")

    items_a = query_source(source_a, start_date, lag_end)
    items_b = query_source(source_b, start_date, lag_end)

    fa = resolve_field(source_a, field_a)
    fb = resolve_field(source_b, field_b)

    dict_a = {}
    for item in items_a:
        d = item.get("date")
        v = item.get(fa)
        if d and v is not None:
            dict_a[d] = float(v)

    dict_b = {}
    for item in items_b:
        d = item.get("date")
        v = item.get(fb)
        if d and v is not None:
            dict_b[d] = float(v)

    pairs = []
    for date_str, val_a in sorted(dict_a.items()):
        if date_str > end_date:
            continue
        try:
            shifted = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
        except Exception:
            continue
        val_b = dict_b.get(shifted)
        if val_b is not None:
            pairs.append((date_str, val_a, val_b))

    if len(pairs) < 10:
        return {
            "error": f"Insufficient overlapping data points ({len(pairs)}). Try a wider date range or different sources."
        }

    xs = [p[1] for p in pairs]
    ys = [p[2] for p in pairs]
    r  = pearson_r(xs, ys)

    if r is None:
        interpretation = "Cannot compute (zero variance in one series)"
    else:
        abs_r = abs(r)
        direction = "positive" if r > 0 else "negative"
        if abs_r >= 0.7:
            strength = "strong"
        elif abs_r >= 0.4:
            strength = "moderate"
        elif abs_r >= 0.2:
            strength = "weak"
        else:
            strength = "negligible"
        interpretation = f"{strength} {direction} correlation"

    return {
        "source_a":       source_a,
        "field_a":        fa,
        "source_b":       source_b,
        "field_b":        fb,
        "lag_days":       lag_days,
        "lag_note":       f"Positive lag: does {fa} today predict {fb} in {lag_days} days?" if lag_days > 0 else "No lag — same-day relationship",
        "start_date":     start_date,
        "end_date":       end_date,
        "n_paired_days":  len(pairs),
        "pearson_r":      r,
        "r_squared":      round(r**2, 3) if r is not None else None,
        "interpretation": interpretation,
        "mean_a":         round(sum(xs)/len(xs), 2),
        "mean_b":         round(sum(ys)/len(ys), 2),
        "coaching_note":  "r > 0.4 is practically meaningful for coaching. r² tells you what % of variance is explained.",
    }


def tool_get_seasonal_patterns(args):
    source     = args.get("source")
    start_date = args.get("start_date", "2010-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    sources_to_query = [source] if source and source in SOURCES else SOURCES
    skip_fields = {"pk", "sk", "source", "ingested_at", "date", "activities", "sport_types"}

    month_names = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                   7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

    cache_key = f"seasonal_patterns_{start_date}_{end_date}_{','.join(sources_to_query)}"
    cached = ddb_cache_get(cache_key) or mem_cache_get(cache_key)
    if cached:
        return cached

    if len(sources_to_query) > 1:
        source_data = parallel_query_sources(sources_to_query, start_date, end_date, lean=True)
    else:
        source_data = {sources_to_query[0]: query_source(sources_to_query[0], start_date, end_date, lean=True)}

    result = {}
    for src in sources_to_query:
        items = source_data.get(src, [])
        if not items:
            continue

        month_buckets = defaultdict(lambda: defaultdict(list))
        year_counts   = defaultdict(set)

        for item in items:
            if "#WORKOUT#" in item.get("sk", ""):
                continue
            date_str = item.get("date", "")
            if not date_str or len(date_str) < 7:
                continue
            try:
                month = int(date_str[5:7])
                year  = date_str[:4]
            except ValueError:
                continue
            year_counts[month].add(year)
            for field, value in item.items():
                if field in skip_fields:
                    continue
                if isinstance(value, (int, float)):
                    month_buckets[month][field].append(float(value))

        months_result = []
        for m in range(1, 13):
            if m not in month_buckets:
                continue
            row = {
                "month":         m,
                "month_name":    month_names[m],
                "years_of_data": len(year_counts[m]),
            }
            for field, values in month_buckets[m].items():
                row[f"{field}_avg"] = round(sum(values) / len(values), 2)
                row[f"{field}_min"] = round(min(values), 2)
                row[f"{field}_max"] = round(max(values), 2)
            months_result.append(row)

        result[src] = months_result

    seasonal_payload = {
        "start_date": start_date,
        "end_date":   end_date,
        "note":       "Months averaged across all available years. 'years_of_data' shows how many years contribute to each month.",
        "sources":    result,
    }
    mem_cache_set(cache_key, seasonal_payload)
    ddb_cache_set(cache_key, seasonal_payload)
    return seasonal_payload


def tool_get_health_dashboard(args):
    today     = datetime.utcnow().strftime("%Y-%m-%d")
    d30_start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    d7_start  = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    dashboard = {"as_of": today, "alerts": []}

    whoop_recent = query_source("whoop", d7_start, today)
    whoop_today  = next((w for w in sorted(whoop_recent, key=lambda x: x.get("date",""), reverse=True)
                         if w.get("recovery_score") is not None), None)
    if whoop_today:
        rec  = whoop_today.get("recovery_score")
        hrv  = whoop_today.get("hrv")
        rhr  = whoop_today.get("resting_heart_rate")
        slp  = whoop_today.get("sleep_duration_hours")
        dashboard["readiness"] = {
            "date":                  whoop_today.get("date"),
            "recovery_score":        rec,
            "hrv_ms":                hrv,
            "resting_heart_rate":    rhr,
            "sleep_hours":           slp,
            "recovery_status":       "green" if rec and rec >= 67 else ("yellow" if rec and rec >= 34 else "red"),
        }
        if rec is not None and rec < 34:
            dashboard["alerts"].append(f"⚠️ Recovery score {rec} — very low. Prioritise rest today.")
        if slp is not None and slp < 6:
            dashboard["alerts"].append(f"⚠️ Sleep {slp}h last night — below minimum threshold.")

    try:
        load_result = tool_get_training_load({"end_date": today, "start_date": d30_start})
        if "current_state" in load_result:
            cs = load_result["current_state"]
            dashboard["training_load"] = {
                "ctl_fitness":  cs["ctl_fitness"],
                "atl_fatigue":  cs["atl_fatigue"],
                "tsb_form":     cs["tsb_form"],
                "acwr":         cs["acwr"],
                "form_status":  cs["form_status"],
                "injury_risk":  cs["injury_risk"],
            }
            if cs.get("acwr") and cs["acwr"] > 1.3:
                dashboard["alerts"].append(f"⚠️ ACWR {cs['acwr']} — training load spike. Injury risk elevated.")
    except Exception as e:
        logger.warning(f"Training load failed in dashboard: {e}")

    strava_7d = query_source("strava", d7_start, today)
    if strava_7d:
        miles_7d = sum(float(d.get("total_distance_miles") or 0) for d in strava_7d)
        elev_7d  = sum(float(d.get("total_elevation_gain_feet") or 0) for d in strava_7d)
        acts_7d  = sum(int(d.get("activity_count") or 0) for d in strava_7d)
        dashboard["last_7_days"] = {
            "total_miles":      round(miles_7d, 1),
            "total_elev_feet":  round(elev_7d, 0),
            "activity_count":   acts_7d,
        }

    strava_30d = query_source("strava", d30_start, today)
    if strava_30d:
        miles_30d = sum(float(d.get("total_distance_miles") or 0) for d in strava_30d)
        elev_30d  = sum(float(d.get("total_elevation_gain_feet") or 0) for d in strava_30d)
        acts_30d  = sum(int(d.get("activity_count") or 0) for d in strava_30d)
        dashboard["last_30_days"] = {
            "total_miles":     round(miles_30d, 1),
            "total_elev_feet": round(elev_30d, 0),
            "activity_count":  acts_30d,
            "avg_miles_per_week": round(miles_30d / 4, 1),
        }

    trends = {}

    whoop_30d = query_source("whoop", d30_start, today)
    if whoop_30d:
        sorted_w = sorted(whoop_30d, key=lambda x: x.get("date", ""))
        hrv_vals = [float(w["hrv"]) for w in sorted_w if w.get("hrv") is not None]
        rhr_vals = [float(w["resting_heart_rate"]) for w in sorted_w if w.get("resting_heart_rate") is not None]
        rec_vals = [float(w["recovery_score"]) for w in sorted_w if w.get("recovery_score") is not None]
        if hrv_vals:
            half = len(hrv_vals) // 2
            hrv_trend = "improving" if sum(hrv_vals[half:])/len(hrv_vals[half:]) > sum(hrv_vals[:half])/len(hrv_vals[:half]) else "declining"
            trends["hrv_30d"] = {"avg": round(sum(hrv_vals)/len(hrv_vals), 1), "trend": hrv_trend, "n_days": len(hrv_vals)}
        if rhr_vals:
            half = len(rhr_vals) // 2
            rhr_trend = "improving" if sum(rhr_vals[half:])/len(rhr_vals[half:]) < sum(rhr_vals[:half])/len(rhr_vals[:half]) else "declining"
            trends["rhr_30d"] = {"avg": round(sum(rhr_vals)/len(rhr_vals), 1), "trend": rhr_trend, "n_days": len(rhr_vals)}
        if rec_vals:
            trends["recovery_30d"] = {"avg": round(sum(rec_vals)/len(rec_vals), 1), "n_days": len(rec_vals)}

    withings_30d = query_source("withings", d30_start, today)
    if withings_30d:
        sorted_wi = sorted(withings_30d, key=lambda x: x.get("date", ""))
        wt_vals   = [float(w["weight_lbs"]) for w in sorted_wi if w.get("weight_lbs") is not None]
        if wt_vals:
            wt_trend = "increasing" if wt_vals[-1] > wt_vals[0] else "decreasing"
            trends["weight_30d"] = {
                "current": wt_vals[-1],
                "start_of_period": wt_vals[0],
                "change_lbs": round(wt_vals[-1] - wt_vals[0], 1),
                "trend": wt_trend,
            }

    dashboard["biomarker_trends"] = trends
    dashboard["alert_count"] = len(dashboard["alerts"])
    if not dashboard["alerts"]:
        dashboard["alerts"] = ["✅ No alerts — all indicators within normal ranges."]

    return dashboard


def tool_get_weight_loss_progress(args):
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", "2010-01-01")
    profile    = get_profile()

    journey_start      = profile.get("journey_start_date")
    journey_start_wt   = profile.get("journey_start_weight_lbs")
    goal_weight        = profile.get("goal_weight_lbs")
    target_weekly_loss = profile.get("target_weekly_loss_lbs", 1.5)
    height_in          = profile.get("height_inches", 70)
    dob_str            = profile.get("date_of_birth")

    effective_start = journey_start if journey_start else start_date

    withings_items = query_source("withings", effective_start, end_date)
    if not withings_items:
        return {"error": "No Withings weight data found. Ensure scale is syncing."}

    weight_series = []
    for item in sorted(withings_items, key=lambda x: x.get("date", "")):
        wt = item.get("weight_lbs")
        if wt is not None:
            weight_series.append({"date": item["date"], "weight_lbs": round(float(wt), 1)})

    if not weight_series:
        return {"error": "No weight_lbs field found in Withings data."}

    def calc_bmi(weight_lbs, height_in):
        if not height_in:
            return None
        return round(703 * weight_lbs / (height_in ** 2), 1)

    bmi_categories = [
        (18.5, "Underweight"),
        (25.0, "Normal weight"),
        (30.0, "Overweight"),
        (35.0, "Obese Class I"),
        (40.0, "Obese Class II"),
        (float("inf"), "Obese Class III"),
    ]

    def bmi_category(bmi):
        if bmi is None:
            return None
        for threshold, label in bmi_categories:
            if bmi < threshold:
                return label
        return "Obese Class III"

    for pt in weight_series:
        bmi = calc_bmi(pt["weight_lbs"], height_in)
        pt["bmi"]          = bmi
        pt["bmi_category"] = bmi_category(bmi)

    weekly_rates = []
    for i in range(len(weight_series)):
        pt = weight_series[i]
        target_dt = datetime.strptime(pt["date"], "%Y-%m-%d") - timedelta(days=7)
        prior = None
        best_gap = 999
        for j in range(i):
            d = datetime.strptime(weight_series[j]["date"], "%Y-%m-%d")
            gap = abs((target_dt - d).days)
            if gap < best_gap:
                best_gap = gap
                prior = weight_series[j]
        if prior and best_gap <= 4:
            days_diff = (datetime.strptime(pt["date"], "%Y-%m-%d") -
                         datetime.strptime(prior["date"], "%Y-%m-%d")).days
            if days_diff > 0:
                weekly_rate = round((prior["weight_lbs"] - pt["weight_lbs"]) / days_diff * 7, 2)
                pt["weekly_loss_rate_lbs"] = weekly_rate
                weekly_rates.append(weekly_rate)
                if weekly_rate > 2.5:
                    pt["rate_flag"] = "⚠️ Losing too fast (>2.5 lbs/wk) — risk of muscle loss. Check nutrition."
                elif weekly_rate < 0:
                    pt["rate_flag"] = "↑ Weight gain this week"
                elif weekly_rate < 0.25 and len(weight_series) > 14:
                    pt["rate_flag"] = "⏸ Very slow — review deficit"

    milestones = {}
    milestone_thresholds = [
        (40.0, "🎯 Exited Obese Class III → Class II (BMI < 40)"),
        (35.0, "🎯 Exited Obese Class II → Class I (BMI < 35)"),
        (30.0, "🎯 Exited Obese → Overweight (BMI < 30)"),
        (25.0, "🎯 Reached Normal Weight (BMI < 25)"),
    ]
    prev_bmi = None
    for pt in weight_series:
        bmi = pt.get("bmi")
        if bmi is None or prev_bmi is None:
            prev_bmi = bmi
            continue
        for threshold, label in milestone_thresholds:
            key = f"bmi_{threshold}"
            if key not in milestones and prev_bmi >= threshold > bmi:
                milestones[key] = {"date": pt["date"], "milestone": label, "bmi": bmi, "weight_lbs": pt["weight_lbs"]}
        prev_bmi = bmi

    current_bmi = weight_series[-1].get("bmi")
    upcoming_milestones = []
    if current_bmi:
        for threshold, label in sorted(milestone_thresholds, key=lambda x: x[0], reverse=True):
            if current_bmi >= threshold:
                lbs_to_threshold = round((threshold - 0.1) * (height_in ** 2) / 703 - weight_series[-1]["weight_lbs"], 1) * -1
                upcoming_milestones.append({
                    "milestone":          label,
                    "lbs_to_cross":       round(lbs_to_threshold, 1),
                    "weeks_at_current_pace": round(lbs_to_threshold / max(sum(weekly_rates[-4:]) / max(len(weekly_rates[-4:]), 1), 0.1), 1) if weekly_rates else None,
                })
                break

    plateau = None
    recent_14 = [pt for pt in weight_series
                 if (datetime.utcnow() - datetime.strptime(pt["date"], "%Y-%m-%d")).days <= 14]
    if len(recent_14) >= 3:
        wts = [pt["weight_lbs"] for pt in recent_14]
        spread = max(wts) - min(wts)
        if spread < 1.5:
            plateau = {
                "detected":  True,
                "duration_days": 14,
                "weight_range_lbs": spread,
                "note": "Scale has moved less than 1.5 lbs in 14 days. This is normal — check training load and sleep quality before changing nutrition.",
            }

    start_weight   = weight_series[0]["weight_lbs"]
    current_weight = weight_series[-1]["weight_lbs"]
    total_lost     = round(start_weight - current_weight, 1)
    avg_weekly     = round(sum(weekly_rates) / len(weekly_rates), 2) if weekly_rates else None

    projection = None
    if goal_weight and avg_weekly and avg_weekly > 0:
        weeks_remaining = (current_weight - goal_weight) / avg_weekly
        goal_date = datetime.utcnow() + timedelta(weeks=weeks_remaining)
        projection = {
            "goal_weight_lbs":       goal_weight,
            "lbs_remaining":         round(current_weight - goal_weight, 1),
            "avg_weekly_loss_lbs":   avg_weekly,
            "projected_goal_date":   goal_date.strftime("%Y-%m-%d"),
            "weeks_remaining":       round(weeks_remaining, 1),
        }
        if journey_start_wt:
            pct_complete = round(100 * (journey_start_wt - current_weight) / (journey_start_wt - goal_weight), 1)
            projection["pct_complete"] = pct_complete

    return {
        "journey_start_date":   journey_start,
        "journey_start_weight": journey_start_wt,
        "current_weight_lbs":   current_weight,
        "current_bmi":          weight_series[-1].get("bmi"),
        "current_bmi_category": weight_series[-1].get("bmi_category"),
        "total_lost_lbs":       total_lost,
        "avg_weekly_loss_lbs":  avg_weekly,
        "projection":           projection,
        "plateau_detected":     plateau,
        "milestones_achieved":  milestones,
        "next_milestone":       upcoming_milestones[0] if upcoming_milestones else None,
        "weight_series":        weight_series,
        "clinical_note":        "Safe loss rate: 0.5–2.0 lbs/week. >2.5 lbs/week consistently risks lean mass catabolism.",
    }


def tool_get_body_composition_trend(args):
    start_date = args.get("start_date", "2010-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    profile    = get_profile()
    journey_start = profile.get("journey_start_date", start_date)
    height_in     = profile.get("height_inches", 70)

    effective_start = journey_start if journey_start < start_date else start_date
    items = query_source("withings", effective_start, end_date)
    if not items:
        return {"error": "No Withings data found."}

    series = []
    for item in sorted(items, key=lambda x: x.get("date", "")):
        wt  = item.get("weight_lbs")
        bf  = item.get("body_fat_percentage")
        mm  = item.get("muscle_mass_lbs")
        bm  = item.get("bone_mass_lbs")
        visc= item.get("visceral_fat_index")
        if wt is None:
            continue
        wt = float(wt)
        pt  = {"date": item["date"], "weight_lbs": round(wt, 1)}
        if bf is not None:
            bf = float(bf)
            fat_lbs  = round(wt * bf / 100, 1)
            lean_lbs = round(wt - fat_lbs, 1)
            pt["body_fat_pct"]   = round(bf, 1)
            pt["fat_mass_lbs"]   = fat_lbs
            pt["lean_mass_lbs"]  = lean_lbs
            lean_kg   = lean_lbs * 0.453592
            height_m  = height_in * 0.0254
            pt["ffmi"] = round(lean_kg / (height_m ** 2), 1)
        if mm  is not None: pt["muscle_mass_lbs"]     = round(float(mm), 1)
        if bm  is not None: pt["bone_mass_lbs"]       = round(float(bm), 1)
        if visc is not None: pt["visceral_fat_index"] = round(float(visc), 1)
        series.append(pt)

    if not series:
        return {"error": "Weight data present but no body composition fields. Check Withings ingestor captures these fields."}

    has_composition = any("body_fat_pct" in pt for pt in series)
    summary = {"has_composition_data": has_composition}

    if has_composition:
        first_comp = next((pt for pt in series if "body_fat_pct" in pt), None)
        last_comp  = next((pt for pt in reversed(series) if "body_fat_pct" in pt), None)

        if first_comp and last_comp and first_comp["date"] != last_comp["date"]:
            wt_change   = round(last_comp["weight_lbs"]  - first_comp["weight_lbs"],  1)
            fat_change  = round(last_comp["fat_mass_lbs"] - first_comp["fat_mass_lbs"], 1) if "fat_mass_lbs" in last_comp and "fat_mass_lbs" in first_comp else None
            lean_change = round(last_comp["lean_mass_lbs"] - first_comp["lean_mass_lbs"], 1) if "lean_mass_lbs" in last_comp and "lean_mass_lbs" in first_comp else None

            summary["from_date"]           = first_comp["date"]
            summary["to_date"]             = last_comp["date"]
            summary["total_weight_change"] = wt_change
            summary["fat_mass_change_lbs"] = fat_change
            summary["lean_mass_change_lbs"]= lean_change

            if fat_change is not None and wt_change != 0:
                pct_fat_of_loss = round(100 * fat_change / wt_change, 1)
                summary["pct_of_loss_that_is_fat"] = pct_fat_of_loss
                if pct_fat_of_loss < 60:
                    summary["composition_alert"] = f"⚠️ Only {pct_fat_of_loss}% of weight lost is fat. Increase protein intake and resistance training to protect lean mass."
                else:
                    summary["composition_status"] = f"✅ {pct_fat_of_loss}% of weight lost is fat — good composition preservation."

    lean_loss_events = []
    prev = None
    for pt in series:
        if "lean_mass_lbs" not in pt:
            prev = pt
            continue
        if prev and "lean_mass_lbs" in prev:
            lean_delta = pt["lean_mass_lbs"] - prev["lean_mass_lbs"]
            if lean_delta < -2.0:
                lean_loss_events.append({
                    "date":           pt["date"],
                    "lean_lost_lbs":  round(abs(lean_delta), 1),
                    "flag":           "⚠️ Significant lean mass loss — check protein intake and training volume",
                })
        prev = pt

    # Board rec 1C: Lean mass velocity — 14-day rolling delta (Attia)
    lean_velocity = {}
    lean_pts = [(pt["date"], pt["lean_mass_lbs"]) for pt in series if "lean_mass_lbs" in pt]
    if len(lean_pts) >= 2:
        # Find data point closest to 14 days before the latest
        latest_date_str, latest_lean = lean_pts[-1]
        latest_dt = datetime.strptime(latest_date_str, "%Y-%m-%d")
        target_dt = latest_dt - timedelta(days=14)
        closest = min(lean_pts[:-1], key=lambda p: abs((datetime.strptime(p[0], "%Y-%m-%d") - target_dt).days))
        days_span = (latest_dt - datetime.strptime(closest[0], "%Y-%m-%d")).days
        if 7 <= days_span <= 28:  # reasonable window
            delta = round(latest_lean - closest[1], 2)
            weekly_rate = round(delta / (days_span / 7), 2)
            lean_velocity = {
                "from_date": closest[0],
                "to_date": latest_date_str,
                "days_span": days_span,
                "lean_delta_lbs": delta,
                "lean_rate_lbs_per_week": weekly_rate,
            }
            if weekly_rate < -0.5:
                lean_velocity["alert"] = f"\u26a0\ufe0f Losing {abs(weekly_rate)} lbs lean mass/week \u2014 increase protein and resistance training volume."
            elif weekly_rate > 0.1:
                lean_velocity["status"] = f"\u2705 Gaining lean mass (+{weekly_rate} lbs/week) during cut \u2014 excellent recomposition."
            else:
                lean_velocity["status"] = "Lean mass stable \u2014 good preservation during deficit."

    return {
        "summary":          summary,
        "lean_mass_velocity": lean_velocity,
        "lean_loss_events": lean_loss_events,
        "series":           series,
        "coaching_note":    "Target: >80% of weight lost should be fat. Protect lean mass with 0.7-1g protein per lb bodyweight and 2-3x resistance sessions/week.",
    }


def tool_get_energy_expenditure(args):
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    d30_start  = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    d7_start   = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    profile    = get_profile()

    height_in  = profile.get("height_inches", 70)
    dob_str    = profile.get("date_of_birth")
    sex        = profile.get("biological_sex", "male").lower()
    target_deficit_kcal = args.get("target_deficit_kcal", 500)

    withings_recent = query_source("withings", d7_start, end_date)
    current_weight_lbs = None
    for item in sorted(withings_recent, key=lambda x: x.get("date", ""), reverse=True):
        if item.get("weight_lbs"):
            current_weight_lbs = float(item["weight_lbs"])
            current_weight_date = item["date"]
            break

    if current_weight_lbs is None:
        return {"error": "No recent weight data. Ensure Withings is syncing."}

    weight_kg  = current_weight_lbs * 0.453592
    height_cm  = height_in * 2.54
    age_years  = None
    if dob_str:
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d")
            age_years = (datetime.utcnow() - dob).days / 365.25
        except Exception:
            pass
    age_years = age_years or 35

    if sex == "female":
        bmr = round(10 * weight_kg + 6.25 * height_cm - 5 * age_years - 161, 0)
    else:
        bmr = round(10 * weight_kg + 6.25 * height_cm - 5 * age_years + 5, 0)

    def exercise_kcal_from_strava(strava_items):
        total_kj   = sum(float(d.get("total_kilojoules") or 0) for d in strava_items)
        total_time = sum(float(d.get("total_moving_time_seconds") or 0) for d in strava_items)
        if total_kj > 0:
            return round(total_kj * 1.0, 0)
        hours = total_time / 3600
        return round(6 * weight_kg * hours, 0)

    strava_7d  = query_source("strava", d7_start, end_date)
    strava_30d = query_source("strava", d30_start, end_date)

    ex_kcal_7d       = exercise_kcal_from_strava(strava_7d)
    ex_kcal_30d      = exercise_kcal_from_strava(strava_30d)
    ex_daily_7d_avg  = round(ex_kcal_7d / 7, 0)
    ex_daily_30d_avg = round(ex_kcal_30d / 30, 0)

    tdee_7d_avg  = round(bmr + ex_daily_7d_avg, 0)
    tdee_30d_avg = round(bmr + ex_daily_30d_avg, 0)
    calorie_target_7d  = round(tdee_7d_avg  - target_deficit_kcal, 0)
    calorie_target_30d = round(tdee_30d_avg - target_deficit_kcal, 0)
    implied_weekly_loss_lbs = round(target_deficit_kcal * 7 / 3500, 2)

    journey_start_wt = profile.get("journey_start_weight_lbs")
    bmr_change = None
    if journey_start_wt:
        start_kg  = float(journey_start_wt) * 0.453592
        if sex == "female":
            bmr_start = round(10 * start_kg + 6.25 * height_cm - 5 * age_years - 161, 0)
        else:
            bmr_start = round(10 * start_kg + 6.25 * height_cm - 5 * age_years + 5, 0)
        bmr_change = {
            "bmr_at_start_weight": bmr_start,
            "bmr_now":             bmr,
            "bmr_reduction_kcal":  round(bmr_start - bmr, 0),
            "note": "BMR decreases as you lose weight — this is normal metabolic adaptation. Deficit targets should be recalculated every 10 lbs lost.",
        }

    return {
        "as_of_date":              end_date,
        "current_weight_lbs":      current_weight_lbs,
        "current_weight_date":     current_weight_date,
        "bmr_formula":             "Mifflin-St Jeor",
        "bmr_kcal":                bmr,
        "exercise_kcal_7d_daily_avg":  ex_daily_7d_avg,
        "exercise_kcal_30d_daily_avg": ex_daily_30d_avg,
        "tdee_7d_avg":             tdee_7d_avg,
        "tdee_30d_avg":            tdee_30d_avg,
        "target_deficit_kcal":     target_deficit_kcal,
        "calorie_target_based_on_7d":  calorie_target_7d,
        "calorie_target_based_on_30d": calorie_target_30d,
        "implied_weekly_loss_lbs": implied_weekly_loss_lbs,
        "bmr_change_since_start":  bmr_change,
        "coaching_note":           "Recalculate targets every 10 lbs lost as BMR decreases. Eating below 1200 kcal (women) or 1500 kcal (men) risks lean mass loss even with adequate protein.",
    }


def tool_get_non_scale_victories(args):
    end_date    = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    profile     = get_profile()
    journey_start = profile.get("journey_start_date")

    if not journey_start:
        return {"error": "journey_start_date not set in profile. Run seed_profile.py to add it."}

    js_dt          = datetime.strptime(journey_start, "%Y-%m-%d")
    baseline_start = journey_start
    baseline_end   = (js_dt + timedelta(days=30)).strftime("%Y-%m-%d")
    recent_start   = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    victories = []
    comparisons = {}

    whoop_base   = query_source("whoop", baseline_start, baseline_end)
    whoop_recent = query_source("whoop", recent_start, end_date)

    def whoop_avg(items, field):
        vals = [float(i[field]) for i in items if i.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    whoop_fields = [
        ("resting_heart_rate", "Resting Heart Rate", "bpm", "lower_is_better"),
        ("hrv",                "HRV",                "ms",  "higher_is_better"),
        ("recovery_score",     "Recovery Score",     "%",   "higher_is_better"),
        ("sleep_duration_hours","Sleep Duration",    "hrs", "higher_is_better"),
    ]

    for field, label, unit, direction in whoop_fields:
        base_avg   = whoop_avg(whoop_base,   field)
        recent_avg = whoop_avg(whoop_recent, field)
        if base_avg is None or recent_avg is None:
            continue
        delta = round(recent_avg - base_avg, 1)
        improved = (delta < 0) if direction == "lower_is_better" else (delta > 0)
        comparisons[field] = {
            "label":    label,
            "unit":     unit,
            "baseline": base_avg,
            "current":  recent_avg,
            "change":   delta,
            "improved": improved,
        }
        if improved and abs(delta) > 1:
            victories.append(f"✅ {label}: {'+' if delta > 0 else ''}{delta} {unit} vs journey start")

    strava_base   = query_source("strava", baseline_start, baseline_end)
    strava_recent = query_source("strava", recent_start, end_date)

    def strava_sum(items, field):
        return round(sum(float(i.get(field) or 0) for i in items), 1)

    def strava_count(items):
        return sum(int(i.get("activity_count") or 0) for i in items)

    base_acts   = strava_count(strava_base)
    recent_acts = strava_count(strava_recent)
    base_miles  = strava_sum(strava_base,   "total_distance_miles")
    recent_miles= strava_sum(strava_recent, "total_distance_miles")
    base_elev   = strava_sum(strava_base,   "total_elevation_gain_feet")
    recent_elev = strava_sum(strava_recent, "total_elevation_gain_feet")

    comparisons["activity_count_30d"] = {
        "label":    "Activities per month",
        "baseline": base_acts,
        "current":  recent_acts,
        "change":   recent_acts - base_acts,
        "improved": recent_acts > base_acts,
    }
    if recent_acts > base_acts:
        victories.append(f"✅ Activity count: {recent_acts} activities this month vs {base_acts} at start")

    comparisons["monthly_miles"] = {
        "label":    "Miles per month",
        "unit":     "miles",
        "baseline": base_miles,
        "current":  recent_miles,
        "change":   round(recent_miles - base_miles, 1),
        "improved": recent_miles > base_miles,
    }
    if recent_miles > base_miles:
        victories.append(f"✅ Monthly mileage: {recent_miles} miles this month vs {base_miles} at start")

    if recent_elev > base_elev and base_elev > 0:
        victories.append(f"✅ Elevation: {recent_elev:,.0f} ft this month vs {base_elev:,.0f} ft at start")

    def avg_speed_mph(items):
        total_dist = sum(float(i.get("total_distance_miles") or 0) for i in items)
        total_time = sum(float(i.get("total_moving_time_seconds") or 0) for i in items)
        if total_dist > 0 and total_time > 0:
            return round(total_dist / (total_time / 3600), 2)
        return None

    base_speed   = avg_speed_mph(strava_base)
    recent_speed = avg_speed_mph(strava_recent)
    if base_speed and recent_speed:
        speed_delta = round(recent_speed - base_speed, 2)
        comparisons["avg_speed_mph"] = {
            "label":    "Average moving speed",
            "unit":     "mph",
            "baseline": base_speed,
            "current":  recent_speed,
            "change":   speed_delta,
            "improved": speed_delta > 0,
        }
        if speed_delta > 0.1:
            victories.append(f"✅ Moving faster: {recent_speed} mph avg vs {base_speed} mph at journey start")

    return {
        "journey_start_date":  journey_start,
        "baseline_window":     f"{baseline_start} → {baseline_end}",
        "current_window":      f"{recent_start} → {end_date}",
        "victories_count":     len(victories),
        "victories":           victories if victories else ["Keep going — victories will appear as data accumulates."],
        "comparisons":         comparisons,
        "motivation_note":     "The scale is one signal. RHR, HRV, distances, and speed are all improving even when the scale stalls. These are the real markers of health transformation.",
    }


def tool_get_exercise_history(args):
    """Deep dive on a single exercise: all sessions, PR chronology, estimated 1RM trend."""
    exercise_name = args.get("exercise_name", "").strip()
    if not exercise_name:
        return {"error": "exercise_name is required"}
    start_date = args.get("start_date", "2000-01-01")
    end_date   = args.get("end_date", date.today().isoformat())
    include_warmups = args.get("include_warmups", False)

    items = query_range("hevy", start_date, end_date)
    sessions = extract_hevy_sessions(items, exercise_name, include_warmups)
    if not sessions:
        return {"error": f"No sessions found for '{exercise_name}' in [{start_date}, {end_date}]"}

    classification = classify_exercise(sessions[0]["exercise_name"])
    pr_weight = 0.0
    pr_1rm    = 0.0
    pr_log_weight = []
    pr_log_1rm    = []
    for s in sessions:
        if s["best_weight"] > pr_weight:
            pr_weight = s["best_weight"]
            pr_log_weight.append({"date": s["date"], "weight_lbs": s["best_weight"]})
        if s["best_1rm"] and s["best_1rm"] > pr_1rm:
            pr_1rm = s["best_1rm"]
            pr_log_1rm.append({"date": s["date"], "estimated_1rm": s["best_1rm"]})

    first_1rm = sessions[0]["best_1rm"]
    last_1rm  = sessions[-1]["best_1rm"]
    gain = round(last_1rm - first_1rm, 1) if first_1rm and last_1rm else None

    return {
        "exercise_name": sessions[0]["exercise_name"],
        "muscle_groups": classification["muscle_groups"],
        "movement_pattern": classification["movement_pattern"],
        "date_range": {"start": sessions[0]["date"], "end": sessions[-1]["date"]},
        "summary": {
            "total_sessions": len(sessions),
            "total_sets": sum(s["set_count"] for s in sessions),
            "best_weight_lbs": pr_weight,
            "best_estimated_1rm": pr_1rm if pr_1rm > 0 else None,
            "first_session_1rm": first_1rm,
            "last_session_1rm": last_1rm,
            "total_1rm_gain": gain,
        },
        "pr_chronology_weight": pr_log_weight,
        "pr_chronology_1rm": pr_log_1rm,
        "sessions": [
            {
                "date": s["date"],
                "set_count": s["set_count"],
                "best_weight_lbs": s["best_weight"],
                "best_1rm": s["best_1rm"],
                "volume_lbs": s["volume_lbs"],
                "sets": s["sets"],
            }
            for s in sessions
        ],
    }


def tool_get_strength_prs(args):
    """All-exercise PR leaderboard ranked by estimated 1RM."""
    start_date    = args.get("start_date", "2000-01-01")
    end_date      = args.get("end_date", date.today().isoformat())
    muscle_filter = args.get("muscle_group_filter", "").strip().lower()
    min_sessions  = int(args.get("min_sessions", 3))

    items = query_range("hevy", start_date, end_date)

    # Collect per-exercise: best weight, best 1rm, session count
    exercise_data: dict = {}
    for item in items:
        day_data = item.get("data", {})
        date_str = item.get("date") or item.get("sk", "")[:10]
        for workout in day_data.get("workouts", []):
            for ex in workout.get("exercises", []):
                name = ex.get("name", "")
                if not name or is_bodyweight(name):
                    continue
                if name not in exercise_data:
                    exercise_data[name] = {"sessions": set(), "best_weight": 0, "best_1rm": 0,
                                            "best_1rm_date": "", "best_weight_date": ""}
                ed = exercise_data[name]
                ed["sessions"].add(date_str)
                for s in ex.get("sets", []):
                    if s.get("set_type") == "warmup":
                        continue
                    w = float(s.get("weight_lbs", 0) or 0)
                    r = int(s.get("reps", 0) or 0)
                    e1rm = estimate_1rm(w, r)
                    if w > ed["best_weight"]:
                        ed["best_weight"] = w
                        ed["best_weight_date"] = date_str
                    if e1rm and e1rm > ed["best_1rm"]:
                        ed["best_1rm"] = e1rm
                        ed["best_1rm_date"] = date_str

    rows = []
    for name, ed in exercise_data.items():
        if len(ed["sessions"]) < min_sessions:
            continue
        cls = classify_exercise(name)
        if muscle_filter and not any(muscle_filter in m.lower() for m in cls["muscle_groups"]):
            continue
        rows.append({
            "exercise": name,
            "muscle_groups": cls["muscle_groups"],
            "movement_pattern": cls["movement_pattern"],
            "best_estimated_1rm": ed["best_1rm"] if ed["best_1rm"] > 0 else None,
            "best_1rm_date": ed["best_1rm_date"],
            "best_weight_lbs": ed["best_weight"],
            "best_weight_date": ed["best_weight_date"],
            "total_sessions": len(ed["sessions"]),
        })

    rows.sort(key=lambda r: r["best_estimated_1rm"] or 0, reverse=True)

    # Group by muscle
    by_muscle: dict = {}
    for r in rows:
        for m in r["muscle_groups"]:
            by_muscle.setdefault(m, 0)
            by_muscle[m] += 1

    return {
        "date_range": {"start": start_date, "end": end_date},
        "total_exercises": len(rows),
        "min_sessions_filter": min_sessions,
        "muscle_group_filter": muscle_filter or None,
        "prs_by_estimated_1rm": rows,
        "exercises_per_muscle_group": by_muscle,
    }


def tool_get_muscle_volume(args):
    """Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks."""
    start_date = args.get("start_date", "2000-01-01")
    end_date   = args.get("end_date", date.today().isoformat())
    period     = args.get("period", "week")  # "week" or "month"

    items = query_range("hevy", start_date, end_date)

    start_dt = datetime.fromisoformat(start_date)
    end_dt   = datetime.fromisoformat(end_date)
    total_days = max((end_dt - start_dt).days, 1)
    num_periods = total_days / 7 if period == "week" else total_days / 30.44

    muscle_sets:   dict[str, int] = {}
    muscle_volume: dict[str, float] = {}
    push_sets = pull_sets = leg_sets = core_sets = 0

    for item in items:
        day_data = item.get("data", {})
        for workout in day_data.get("workouts", []):
            for ex in workout.get("exercises", []):
                name = ex.get("name", "")
                cls = classify_exercise(name)
                normal_sets = [s for s in ex.get("sets", []) if s.get("set_type", "normal") != "warmup"]
                n = len(normal_sets)
                vol = sum(float(s.get("weight_lbs", 0) or 0) * int(s.get("reps", 0) or 0) for s in normal_sets)
                for m in cls["muscle_groups"]:
                    muscle_sets[m]   = muscle_sets.get(m, 0) + n
                    muscle_volume[m] = muscle_volume.get(m, 0.0) + vol
                pattern = cls["movement_pattern"]
                if pattern == "Push":   push_sets += n
                elif pattern == "Pull": pull_sets += n
                elif pattern == "Legs": leg_sets  += n
                elif pattern == "Core": core_sets += n

    period_label = "week" if period == "week" else "month"
    volume_report = {}
    for muscle in sorted(muscle_sets):
        total_sets = muscle_sets[muscle]
        avg = total_sets / num_periods if num_periods > 0 else 0
        lm  = _VOLUME_LANDMARKS.get(muscle, _VOLUME_LANDMARKS["Other"])
        volume_report[muscle] = {
            "total_sets": total_sets,
            f"avg_sets_per_{period_label}": round(avg, 1),
            "total_volume_lbs": round(muscle_volume.get(muscle, 0), 0),
            "volume_landmark_status": volume_status(muscle, avg),
            "landmarks": {
                "MV":  lm["MV"],
                "MEV": lm["MEV"],
                "MAV": f"{lm['MAV_lo']}–{lm['MAV_hi']}",
                "MRV": lm["MRV"],
            },
        }

    push_pull_ratio = round(push_sets / pull_sets, 2) if pull_sets > 0 else None

    return {
        "date_range": {"start": start_date, "end": end_date},
        "analysis_period": period_label,
        "num_periods_analyzed": round(num_periods, 1),
        "muscle_volume": volume_report,
        "movement_balance": {
            "push_sets": push_sets,
            "pull_sets": pull_sets,
            "leg_sets":  leg_sets,
            "core_sets": core_sets,
            "push_pull_ratio": push_pull_ratio,
            "push_pull_note": (
                "Balanced" if push_pull_ratio and 0.8 <= push_pull_ratio <= 1.2 else
                "Push-dominant – add more pulling" if push_pull_ratio and push_pull_ratio > 1.2 else
                "Pull-dominant" if push_pull_ratio else "No data"
            ),
        },
    }


def tool_get_strength_progress(args):
    """Longitudinal 1RM trend, rate of gain, plateau detection for a single exercise."""
    exercise_name = args.get("exercise_name", "").strip()
    if not exercise_name:
        return {"error": "exercise_name is required"}
    start_date = args.get("start_date", "2000-01-01")
    end_date   = args.get("end_date", date.today().isoformat())
    plateau_days = int(args.get("plateau_threshold_days", 90))

    items = query_range("hevy", start_date, end_date)
    sessions = extract_hevy_sessions(items, exercise_name)
    if not sessions:
        return {"error": f"No sessions found for '{exercise_name}'"}

    # Build 1RM time series
    time_series = [{"date": s["date"], "estimated_1rm": s["best_1rm"]} for s in sessions if s["best_1rm"]]
    if not time_series:
        return {"error": f"No 1RM data for '{exercise_name}' (bodyweight exercise or no valid reps ≤ 10)"}

    first_1rm  = time_series[0]["estimated_1rm"]
    latest_1rm = time_series[-1]["estimated_1rm"]
    all_time_pr = max(t["estimated_1rm"] for t in time_series)
    all_time_pr_date = next(t["date"] for t in reversed(time_series) if t["estimated_1rm"] == all_time_pr)
    total_gain = round(latest_1rm - first_1rm, 1)
    pct_gain   = round(total_gain / first_1rm * 100, 1) if first_1rm else None

    # Rate of gain per month
    start_dt = datetime.fromisoformat(time_series[0]["date"])
    end_dt   = datetime.fromisoformat(time_series[-1]["date"])
    months   = max((end_dt - start_dt).days / 30.44, 0.1)
    monthly_gain = round(total_gain / months, 2)

    # Plateau: days since last PR
    running_pr = 0.0
    last_pr_date = time_series[0]["date"]
    for t in time_series:
        if t["estimated_1rm"] > running_pr:
            running_pr = t["estimated_1rm"]
            last_pr_date = t["date"]
    last_pr_dt   = datetime.fromisoformat(last_pr_date)
    days_since   = (datetime.fromisoformat(time_series[-1]["date"]) - last_pr_dt).days
    in_plateau   = days_since >= plateau_days

    # Periodization: split into thirds
    n = len(time_series)
    thirds = [time_series[:n//3], time_series[n//3:2*n//3], time_series[2*n//3:]]
    def avg_1rm(lst):
        vals = [t["estimated_1rm"] for t in lst if t["estimated_1rm"]]
        return round(sum(vals)/len(vals), 1) if vals else None

    return {
        "exercise_name": sessions[0]["exercise_name"],
        "date_range": {"start": time_series[0]["date"], "end": time_series[-1]["date"]},
        "progression": {
            "first_1rm": first_1rm,
            "latest_1rm": latest_1rm,
            "all_time_pr": all_time_pr,
            "all_time_pr_date": all_time_pr_date,
            "total_gain_lbs": total_gain,
            "pct_gain": pct_gain,
            "avg_monthly_gain_lbs": monthly_gain,
        },
        "plateau": {
            "days_since_last_pr": days_since,
            "last_pr_date": last_pr_date,
            "in_plateau": in_plateau,
            "plateau_threshold_days": plateau_days,
            "note": f"No new 1RM PR in {days_since} days. Consider a deload or program change." if in_plateau else f"Active progression – last PR {days_since} days ago.",
        },
        "periodization_phases": {
            "early_avg_1rm": avg_1rm(thirds[0]),
            "mid_avg_1rm":   avg_1rm(thirds[1]),
            "late_avg_1rm":  avg_1rm(thirds[2]),
        },
        "one_rm_time_series": time_series,
    }


def tool_get_workout_frequency(args):
    """Adherence metrics: streaks, gaps, monthly counts, top exercises."""
    start_date = args.get("start_date", "2000-01-01")
    end_date   = args.get("end_date", date.today().isoformat())

    items = query_range("hevy", start_date, end_date)

    workout_dates = sorted({
        (item.get("date") or item.get("sk", "")[:10])
        for item in items
        if item.get("data", {}).get("workouts")
    })
    if not workout_dates:
        return {"error": "No workout data found"}

    # Streak and gap analysis
    date_objs = [datetime.fromisoformat(d) for d in workout_dates]
    longest_streak = 1
    cur_streak     = 1
    longest_gap    = 0
    for i in range(1, len(date_objs)):
        diff = (date_objs[i] - date_objs[i-1]).days
        if diff == 1:
            cur_streak += 1
            longest_streak = max(longest_streak, cur_streak)
        else:
            cur_streak = 1
            longest_gap = max(longest_gap, diff)

    total_days = max((date_objs[-1] - date_objs[0]).days, 1)
    avg_per_week  = round(len(workout_dates) / (total_days / 7), 2)
    avg_per_month = round(len(workout_dates) / (total_days / 30.44), 2)

    # Monthly breakdown
    monthly: dict[str, int] = {}
    for d in workout_dates:
        ym = d[:7]
        monthly[ym] = monthly.get(ym, 0) + 1

    # Top 15 exercises by frequency
    exercise_counts: dict[str, int] = {}
    for item in items:
        for workout in item.get("data", {}).get("workouts", []):
            for ex in workout.get("exercises", []):
                name = ex.get("name", "")
                if name:
                    exercise_counts[name] = exercise_counts.get(name, 0) + 1
    top_exercises = sorted(exercise_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    return {
        "date_range": {"start": workout_dates[0], "end": workout_dates[-1]},
        "total_workout_days": len(workout_dates),
        "avg_workouts_per_week": avg_per_week,
        "avg_workouts_per_month": avg_per_month,
        "longest_streak_days": longest_streak,
        "longest_gap_days": longest_gap,
        "monthly_breakdown": [{"year_month": ym, "workouts": cnt} for ym, cnt in sorted(monthly.items())],
        "top_exercises": [{"exercise": name, "sessions": cnt} for name, cnt in top_exercises],
    }


def tool_get_strength_standards(args):
    """Bodyweight-relative strength vs Novice/Intermediate/Advanced/Elite norms."""
    end_date = args.get("end_date", date.today().isoformat())
    bw_source = args.get("bodyweight_source", "withings")

    # Get bodyweight
    bodyweight = None
    if bw_source == "withings":
        bw_items = query_range("withings", "2000-01-01", end_date)
        for item in reversed(sorted(bw_items, key=lambda x: x.get("date") or x.get("sk", ""))):
            w = item.get("data", {}).get("weight_lbs") or item.get("data", {}).get("weight")
            if w:
                bodyweight = float(w)
                break
    if bodyweight is None:
        bodyweight = float(args.get("bodyweight_lbs", 0))
    if not bodyweight:
        return {"error": "Could not determine bodyweight. Pass bodyweight_lbs or ensure Withings data exists."}

    # Get all hevy data up to end_date
    items = query_range("hevy", "2000-01-01", end_date)

    # Find best 1RM for each standard lift
    standard_lifts = {
        "bench press":    "Barbell Bench Press",
        "squat":          "Barbell Back Squat",
        "deadlift":       "Deadlift",
        "overhead press": "Overhead Press",
    }

    best_1rms: dict[str, tuple[float, str]] = {}  # lift_key -> (1rm, date)
    for item in items:
        date_str = item.get("date") or item.get("sk", "")[:10]
        for workout in item.get("data", {}).get("workouts", []):
            for ex in workout.get("exercises", []):
                name = ex.get("name", "").lower()
                for lift_key in standard_lifts:
                    if lift_key not in name:
                        continue
                    for s in ex.get("sets", []):
                        if s.get("set_type") == "warmup":
                            continue
                        w = float(s.get("weight_lbs", 0) or 0)
                        r = int(s.get("reps", 0) or 0)
                        e1rm = estimate_1rm(w, r)
                        if e1rm:
                            if lift_key not in best_1rms or e1rm > best_1rms[lift_key][0]:
                                best_1rms[lift_key] = (e1rm, date_str)

    results = {}
    levels_found = []
    for lift_key, (canonical_name) in standard_lifts.items():
        if lift_key not in best_1rms:
            results[lift_key] = {"status": "no data found", "note": f"No sets recorded for '{lift_key}'"}
            continue
        best, best_date = best_1rms[lift_key]
        ratio = round(best / bodyweight, 3)
        level, next_lvl, next_ratio = classify_standard(lift_key, ratio)
        lbs_to_next = round((next_ratio * bodyweight) - best, 1) if next_ratio else None
        results[lift_key] = {
            "best_estimated_1rm_lbs": best,
            "date_achieved": best_date,
            "bw_ratio": ratio,
            "classification": level,
            "next_level": next_lvl,
            "lbs_to_next_level": lbs_to_next,
            "standards": {lvl: round(_STRENGTH_STANDARDS[lift_key][lvl] * bodyweight, 1) for lvl in _STANDARD_LEVELS},
        }
        levels_found.append(_STANDARD_LEVELS.index(level))

    overall = _STANDARD_LEVELS[round(sum(levels_found) / len(levels_found))] if levels_found else None

    return {
        "bodyweight_lbs": bodyweight,
        "bodyweight_source": bw_source,
        "analysis_date": end_date,
        "overall_strength_level": overall,
        "lifts": results,
        "note": "Standards based on bodyweight multipliers (male norms). Female lifters typically achieve 70–80% of these values.",
    }


def tool_get_sleep_analysis(args):
    """
    Clinical sleep analysis from Eight Sleep data.
    Surfaces architecture percentages, sleep efficiency, circadian timing,
    consistency, sleep debt, social jetlag, and WASO — the metrics a sleep
    physician actually uses rather than just raw hours.
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 90))   # rolling window
    target_h   = float(args.get("target_sleep_hours", 7.5))
    start_date = args.get("start_date") or (
        datetime.utcnow() - timedelta(days=days)
    ).strftime("%Y-%m-%d")

    items = query_source("eightsleep", start_date, end_date)
    if not items:
        return {"error": "No Eight Sleep data found for the requested window."}

    items = sorted(items, key=lambda x: x.get("date", ""))

    # ── Helper: safe average ─────────────────────────────────────────────────
    def avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def pct_below(vals, threshold):
        v = [x for x in vals if x is not None]
        if not v:
            return None
        return round(100.0 * sum(1 for x in v if x < threshold) / len(v), 1)

    def std_dev(vals):
        v = [x for x in vals if x is not None]
        if len(v) < 2:
            return None
        m = sum(v) / len(v)
        return round(math.sqrt(sum((x - m) ** 2 for x in v) / len(v)), 2)

    # Pull raw series for each field
    def series(field):
        return [float(item[field]) for item in items if item.get(field) is not None]

    n = len(items)

    # ── 1. Sleep architecture ─────────────────────────────────────────────────
    rem_pcts   = series("rem_pct")
    deep_pcts  = series("deep_pct")
    light_pcts = series("light_pct")
    eff_pcts   = series("sleep_efficiency_pct")
    dur_hrs    = series("sleep_duration_hours")
    waso_hrs   = series("waso_hours")
    latency    = series("time_to_sleep_min")
    resp_rates = series("respiratory_rate")
    hrv_vals   = series("hrv_avg")

    architecture = {
        "rem_avg_pct":         avg(rem_pcts),
        "rem_norm":            "20–25%",
        "rem_below_15pct_nights": pct_below(rem_pcts, 15),
        "deep_avg_pct":        avg(deep_pcts),
        "deep_norm":           "15–25%",
        "deep_below_10pct_nights": pct_below(deep_pcts, 10),
        "light_avg_pct":       avg(light_pcts),
        "avg_sleep_hours":     avg(dur_hrs),
        "avg_waso_hours":      avg(waso_hrs),
        "avg_latency_min":     avg(latency),
        "latency_over_30min_nights": pct_below([-x for x in latency], -30) if latency else None,
    }

    arch_alerts = []
    if architecture["rem_avg_pct"] and architecture["rem_avg_pct"] < 18:
        arch_alerts.append(
            f"⚠️ Average REM {architecture['rem_avg_pct']}% is below the 20–25% norm. "
            "Common causes: alcohol, sleep deprivation, SSRIs. Review evening habits."
        )
    if architecture["rem_below_15pct_nights"] and architecture["rem_below_15pct_nights"] > 30:
        arch_alerts.append(
            f"⚠️ {architecture['rem_below_15pct_nights']}% of nights have REM < 15%. "
            "Consistent low REM is associated with impaired emotional regulation and memory consolidation."
        )
    if architecture["deep_avg_pct"] and architecture["deep_avg_pct"] < 12:
        arch_alerts.append(
            f"⚠️ Average deep/SWS {architecture['deep_avg_pct']}% is low. "
            "Deep sleep is when growth hormone releases and metabolic restoration occurs. "
            "Alcohol, late exercise, and high stress suppress SWS."
        )
    if architecture["avg_latency_min"] and architecture["avg_latency_min"] > 30:
        arch_alerts.append(
            f"⚠️ Average sleep onset {architecture['avg_latency_min']} min — above the clinical threshold of 30 min. "
            "Persistent latency >30 min is a diagnostic criterion for insomnia."
        )
    architecture["clinical_alerts"] = arch_alerts

    # ── 2. Sleep efficiency ───────────────────────────────────────────────────
    efficiency = {
        "avg_sleep_efficiency_pct":   avg(eff_pcts),
        "clinical_target":            "≥ 85%",
        "cbt_i_threshold":            "< 80% consistently",
        "nights_below_85pct":         pct_below(eff_pcts, 85),
        "nights_below_80pct":         pct_below(eff_pcts, 80),
    }

    eff_alerts = []
    eff_avg = efficiency["avg_sleep_efficiency_pct"]
    if eff_avg and eff_avg < 80:
        eff_alerts.append(
            f"🚨 Average sleep efficiency {eff_avg}% — below the CBT-I treatment threshold of 80%. "
            "This warrants sleep restriction protocol consideration (consult a sleep specialist)."
        )
    elif eff_avg and eff_avg < 85:
        eff_alerts.append(
            f"⚠️ Average sleep efficiency {eff_avg}% — below the healthy target of 85%. "
            "Consider consistent wake time, limiting time in bed while awake, and reducing evening stimulants."
        )
    nb80 = efficiency["nights_below_80pct"]
    if nb80 and nb80 > 40:
        eff_alerts.append(
            f"⚠️ {nb80}% of nights show efficiency < 80% — chronic pattern, not isolated nights."
        )
    efficiency["clinical_alerts"] = eff_alerts

    # ── 3. Circadian timing & consistency ─────────────────────────────────────
    onset_hours   = series("sleep_onset_hour")
    wake_hours    = series("wake_hour")
    midpoint_hours= series("sleep_midpoint_hour")

    onset_sd  = std_dev(onset_hours)
    wake_sd   = std_dev(wake_hours)
    mid_sd    = std_dev(midpoint_hours)
    avg_onset = avg(onset_hours)
    avg_wake  = avg(wake_hours)
    avg_mid   = avg(midpoint_hours)

    def format_hour(h):
        if h is None:
            return None
        total_min = int(h * 60)
        hh = (total_min // 60) % 24
        mm = total_min % 60
        suffix = "am" if hh < 12 else "pm"
        hh12 = hh if 1 <= hh <= 12 else (12 if hh == 0 else hh - 12)
        return f"{hh12}:{mm:02d} {suffix}"

    # Social jetlag: split into weekday vs weekend midpoints
    weekday_mids, weekend_mids = [], []
    for item in items:
        mid = item.get("sleep_midpoint_hour")
        date_str = item.get("date", "")
        if mid is None or not date_str:
            continue
        try:
            dow = datetime.strptime(date_str, "%Y-%m-%d").weekday()  # 0=Mon
        except ValueError:
            continue
        if dow < 5:
            weekday_mids.append(float(mid))
        else:
            weekend_mids.append(float(mid))

    social_jetlag = None
    if weekday_mids and weekend_mids:
        # Circular mean difference for hours that wrap at 24
        def circ_mean(vals):
            sin_sum = sum(math.sin(v * math.pi / 12) for v in vals)
            cos_sum = sum(math.cos(v * math.pi / 12) for v in vals)
            return math.atan2(sin_sum / len(vals), cos_sum / len(vals)) * 12 / math.pi % 24
        wkday_mean = circ_mean(weekday_mids)
        wkend_mean = circ_mean(weekend_mids)
        diff = (wkend_mean - wkday_mean + 12) % 24 - 12   # signed, range -12..12
        social_jetlag = round(abs(diff), 2)

    circadian = {
        "avg_sleep_onset":          format_hour(avg_onset),
        "avg_wake_time":            format_hour(avg_wake),
        "avg_sleep_midpoint":       format_hour(avg_mid),
        "sleep_onset_consistency_sd_hours": onset_sd,
        "wake_consistency_sd_hours":        wake_sd,
        "midpoint_consistency_sd_hours":    mid_sd,
        "social_jetlag_hours":      social_jetlag,
        "social_jetlag_note":       "Difference in sleep midpoint weekday vs weekend. >1h linked to metabolic risk.",
        "weekday_nights_analyzed":  len(weekday_mids),
        "weekend_nights_analyzed":  len(weekend_mids),
    }

    circ_alerts = []
    if onset_sd and onset_sd > 1.0:
        circ_alerts.append(
            f"⚠️ Sleep onset varies ±{onset_sd}h SD — high variability undermines circadian entrainment. "
            "A consistent bedtime within 30 minutes nightly is the highest-leverage sleep habit."
        )
    if wake_sd and wake_sd > 0.75:
        circ_alerts.append(
            f"⚠️ Wake time varies ±{wake_sd}h SD. Consistent wake time (even weekends) is the "
            "single most effective anchor for circadian rhythm."
        )
    if social_jetlag and social_jetlag >= 2.0:
        circ_alerts.append(
            f"🚨 Social jetlag {social_jetlag}h — equivalent to flying through {round(social_jetlag)} time zones every "
            "weekend. Associated with obesity, metabolic syndrome, and increased cardiovascular risk."
        )
    elif social_jetlag and social_jetlag >= 1.0:
        circ_alerts.append(
            f"⚠️ Social jetlag {social_jetlag}h — above the 1h clinical threshold. "
            "Try to keep weekend sleep timing within 1h of weekday schedule."
        )
    circadian["clinical_alerts"] = circ_alerts

    # ── 4. Sleep debt ─────────────────────────────────────────────────────────
    nightly_debts = [
        round(target_h - float(item["sleep_duration_hours"]), 2)
        for item in items if item.get("sleep_duration_hours") is not None
    ]
    cumulative_debt_7d = None
    cumulative_debt_30d= None
    if nightly_debts:
        cumulative_debt_7d  = round(sum(nightly_debts[-7:]),  2)
        cumulative_debt_30d = round(sum(nightly_debts[-30:]), 2)

    debt = {
        "target_hours_per_night": target_h,
        "avg_nightly_debt_hours": avg(nightly_debts),
        "cumulative_debt_7d":     cumulative_debt_7d,
        "cumulative_debt_30d":    cumulative_debt_30d,
        "nights_meeting_target": round(
            100.0 * sum(1 for d in nightly_debts if d <= 0) / len(nightly_debts), 1
        ) if nightly_debts else None,
        "note": "Positive debt = below target. Research shows sleep debt accumulates and impairs cognition even when subjective sleepiness adapts.",
    }

    debt_alerts = []
    if cumulative_debt_7d and cumulative_debt_7d > 5:
        debt_alerts.append(
            f"⚠️ Rolling 7-day sleep debt is {cumulative_debt_7d}h. "
            f"Cognitive performance typically impaired when cumulative debt exceeds 5h."
        )
    if cumulative_debt_30d and cumulative_debt_30d > 15:
        debt_alerts.append(
            f"⚠️ 30-day cumulative debt {cumulative_debt_30d}h. "
            "Chronic sleep restriction has documented metabolic and immune consequences."
        )
    debt["clinical_alerts"] = debt_alerts

    # ── 5. Biometrics ─────────────────────────────────────────────────────────
    biometrics = {}
    if hrv_vals:
        biometrics["avg_sleep_hrv_ms"] = avg(hrv_vals)
        biometrics["hrv_note"] = "Sleep HRV from Eight Sleep tends to be lower than Whoop HRV (different measurement timing)."
    if resp_rates:
        avg_resp = avg(resp_rates)
        biometrics["avg_respiratory_rate"] = avg_resp
        biometrics["respiratory_norm"] = "12–18 bpm"
        if avg_resp and avg_resp > 18:
            biometrics["respiratory_alert"] = (
                f"⚠️ Average respiratory rate {avg_resp} bpm exceeds 18 bpm normal ceiling. "
                "Sustained elevation warrants evaluation for sleep-disordered breathing (OSA)."
            )
        elif avg_resp and avg_resp > 16:
            biometrics["respiratory_note_elevated"] = (
                f"Note: respiratory rate {avg_resp} bpm — upper-normal range. Monitor trend."
            )

    # ── 6. Sleep score trend ──────────────────────────────────────────────────
    scores = series("sleep_score")
    score_summary = {}
    if scores:
        score_summary["avg_sleep_score"] = avg(scores)
        if len(scores) >= 14:
            recent_half = scores[len(scores)//2:]
            early_half  = scores[:len(scores)//2]
            delta = round(avg(recent_half) - avg(early_half), 1)
            score_summary["trend"] = "improving" if delta > 2 else ("declining" if delta < -2 else "stable")
            score_summary["trend_delta"] = delta

    # ── 7. All alerts consolidated ────────────────────────────────────────────
    all_alerts = (
        architecture.get("clinical_alerts", []) +
        efficiency.get("clinical_alerts", []) +
        circadian.get("clinical_alerts", []) +
        debt.get("clinical_alerts", []) +
        ([biometrics["respiratory_alert"]] if biometrics.get("respiratory_alert") else [])
    )

    return {
        "analysis_window":    {"start": start_date, "end": end_date, "nights_analyzed": n},
        "sleep_architecture": architecture,
        "sleep_efficiency":   efficiency,
        "circadian_timing":   circadian,
        "sleep_debt":         debt,
        "biometrics":         biometrics,
        "sleep_score":        score_summary,
        "all_alerts":         all_alerts,
        "alert_count":        len(all_alerts),
        "source":             "eightsleep",
        "clinical_note":      (
            "Eight Sleep stage classification is consumer-grade. Architecture percentages "
            "should be interpreted as trends and screening signals, not clinical PSG equivalents. "
            "Consistent patterns across 30+ nights are more meaningful than individual night values."
        ),
    }


# ── Chronicling / Habits helpers ────────────────────────────────────────────

def query_chronicling(start_date, end_date):
    """Query habit items (habitify or chronicling) based on source-of-truth.
    Name kept for backward compatibility with all habit tool call sites."""
    source = get_sot("habits")
    return query_source(source, start_date, end_date)


def _habit_series(items):
    """
    From raw chronicling items return a list of
    {date, habits: {name: 0/1}, by_group: {...}, total_completed, total_possible, completion_pct}
    sorted chronologically.
    """
    rows = []
    for item in sorted(items, key=lambda x: x.get("date", "")):
        if not item.get("habits"):
            continue
        rows.append({
            "date":            item.get("date"),
            "habits":          {k: int(v) for k, v in item.get("habits", {}).items()},
            "by_group":        item.get("by_group", {}),
            "total_completed": item.get("total_completed", 0),
            "total_possible":  item.get("total_possible", 0),
            "completion_pct":  item.get("completion_pct", 0),
        })
    return rows


# ── MacroFactor reference data ────────────────────────────────────────────────

# RDA / optimal targets for get_micronutrient_report.
# Sources: NIH DRI (2024), Attia protocol, Rhonda Patrick, Bryan Johnson Blueprint.
_MICRONUTRIENT_TARGETS = {
    "total_fiber_g":            {"rda": 38,    "optimal": 50,    "unit": "g",   "category": "Macros",     "score": True},
    "total_omega3_total_g":     {"rda": 1.6,   "optimal": 4.0,   "unit": "g",   "category": "Fatty Acids","score": True},
    "total_omega3_dha_g":       {"rda": 0.5,   "optimal": 2.0,   "unit": "g",   "category": "Fatty Acids","score": True},
    "total_omega3_epa_g":       {"rda": 0.5,   "optimal": 1.5,   "unit": "g",   "category": "Fatty Acids","score": True},
    "total_omega6_g":           {"rda": None,  "optimal": None,  "unit": "g",   "category": "Fatty Acids"},
    "total_sodium_mg":          {"rda": 1500,  "optimal": 1500,  "unit": "mg",  "category": "Minerals",   "upper_limit": 2300},
    "total_potassium_mg":       {"rda": 3400,  "optimal": 4700,  "unit": "mg",  "category": "Minerals",   "score": True},
    "total_calcium_mg":         {"rda": 1000,  "optimal": 1200,  "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 2500},
    "total_magnesium_mg":       {"rda": 420,   "optimal": 500,   "unit": "mg",  "category": "Minerals",   "score": True},
    "total_iron_mg":            {"rda": 8,     "optimal": 18,    "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 45},
    "total_zinc_mg":            {"rda": 11,    "optimal": 15,    "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 40},
    "total_selenium_mcg":       {"rda": 55,    "optimal": 100,   "unit": "mcg", "category": "Minerals",   "score": True, "upper_limit": 400},
    "total_copper_mg":          {"rda": 0.9,   "optimal": 2.0,   "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 10},
    "total_phosphorus_mg":      {"rda": 700,   "optimal": 1000,  "unit": "mg",  "category": "Minerals",   "score": True},
    "total_vitamin_a_mcg":      {"rda": 900,   "optimal": 1500,  "unit": "mcg", "category": "Vitamins",   "score": True, "upper_limit": 3000},
    "total_vitamin_c_mg":       {"rda": 90,    "optimal": 500,   "unit": "mg",  "category": "Vitamins",   "score": True},
    "total_vitamin_d_mcg":      {"rda": 20,    "optimal": 50,    "unit": "mcg", "category": "Vitamins",   "score": True, "upper_limit": 100},
    "total_vitamin_e_mg":       {"rda": 15,    "optimal": 30,    "unit": "mg",  "category": "Vitamins",   "score": True, "upper_limit": 1000},
    "total_vitamin_k_mcg":      {"rda": 120,   "optimal": 300,   "unit": "mcg", "category": "Vitamins",   "score": True},
    "total_b1_thiamine_mg":     {"rda": 1.2,   "optimal": 5.0,   "unit": "mg",  "category": "B Vitamins", "score": True},
    "total_b2_riboflavin_mg":   {"rda": 1.3,   "optimal": 3.0,   "unit": "mg",  "category": "B Vitamins", "score": True},
    "total_b3_niacin_mg":       {"rda": 16,    "optimal": 25,    "unit": "mg",  "category": "B Vitamins", "score": True, "upper_limit": 35},
    "total_b5_pantothenic_mg":  {"rda": 5,     "optimal": 10,    "unit": "mg",  "category": "B Vitamins", "score": True},
    "total_b6_pyridoxine_mg":   {"rda": 1.7,   "optimal": 5.0,   "unit": "mg",  "category": "B Vitamins", "score": True, "upper_limit": 100},
    "total_b12_cobalamin_mcg":  {"rda": 2.4,   "optimal": 10.0,  "unit": "mcg", "category": "B Vitamins", "score": True},
    "total_folate_mcg":         {"rda": 400,   "optimal": 600,   "unit": "mcg", "category": "B Vitamins", "score": True, "upper_limit": 1000},
    "total_choline_mg":         {"rda": 550,   "optimal": 750,   "unit": "mg",  "category": "Other",      "score": True},
    "total_caffeine_mg":        {"rda": None,  "optimal": None,  "unit": "mg",  "category": "Other",      "upper_limit": 400},
}
_MICRO_CATEGORY_ORDER  = ["Macros", "Fatty Acids", "Minerals", "Vitamins", "B Vitamins", "Other"]
_OMEGA_RATIO_TARGET    = 4.0    # Attia / Simopoulos: keep O6:O3 < 4:1
_LEUCINE_MPS_THRESHOLD = 2.5    # g leucine per meal to trigger MPS (Phillips / Attia)


# ── Tool: get_micronutrient_report ────────────────────────────────────────────

def tool_get_micronutrient_report(args):
    """
    Score ~25 micronutrients against RDA and longevity-optimal targets.
    Flags chronic deficiencies (avg < 60% RDA), near-miss gaps (60-90%), upper-limit exceedances,
    omega-6:omega-3 ratio, and generates actionable longevity commentary.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    items = query_source("macrofactor", start_date, end_date)
    if not items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    n = len(items)
    totals_sum   = defaultdict(float)
    totals_count = defaultdict(int)
    for item in items:
        for field in _MICRONUTRIENT_TARGETS:
            v = item.get(field)
            if v is not None:
                totals_sum[field]   += float(v)
                totals_count[field] += 1

    categories   = {}
    deficiencies = []
    near_gaps    = []
    exceedances  = []

    for cat in _MICRO_CATEGORY_ORDER:
        cat_rows = []
        for field, meta in _MICRONUTRIENT_TARGETS.items():
            if meta.get("category") != cat:
                continue
            if totals_count[field] == 0:
                continue
            avg_val = round(totals_sum[field] / totals_count[field], 2)
            rda     = meta.get("rda")
            optimal = meta.get("optimal")
            ul      = meta.get("upper_limit")
            unit    = meta["unit"]
            row = {"field": field, "average": avg_val, "unit": unit, "days_logged": totals_count[field]}
            if rda:
                pct_rda = round(avg_val / rda * 100, 1)
                row["rda"]     = rda
                row["pct_rda"] = pct_rda
                if meta.get("score"):
                    if pct_rda < 60:
                        row["status"] = "DEFICIENT"
                        deficiencies.append({"field": field, "average": avg_val, "unit": unit, "pct_rda": pct_rda, "rda": rda})
                    elif pct_rda < 90:
                        row["status"] = "LOW"
                        near_gaps.append({"field": field, "average": avg_val, "unit": unit, "pct_rda": pct_rda, "rda": rda})
                    elif ul and avg_val > ul:
                        row["status"] = "ABOVE_UPPER_LIMIT"
                        exceedances.append({"field": field, "average": avg_val, "unit": unit, "upper_limit": ul})
                    else:
                        row["status"] = "ADEQUATE"
            if optimal:
                row["optimal"]      = optimal
                row["pct_optimal"]  = round(avg_val / optimal * 100, 1)
            cat_rows.append(row)
        if cat_rows:
            categories[cat] = sorted(cat_rows, key=lambda r: r.get("pct_rda", 999))

    omega6 = totals_sum.get("total_omega6_g", 0) / max(totals_count.get("total_omega6_g", 1), 1)
    omega3 = totals_sum.get("total_omega3_total_g", 0) / max(totals_count.get("total_omega3_total_g", 1), 1)
    o6_o3  = round(omega6 / omega3, 1) if omega3 > 0 else None

    longevity_flags = []
    if o6_o3 and o6_o3 > _OMEGA_RATIO_TARGET:
        longevity_flags.append(f"Omega-6:Omega-3 ratio is {o6_o3}:1 (target <{_OMEGA_RATIO_TARGET}:1). Pro-inflammatory — increase EPA/DHA or reduce seed oils.")
    dha_avg = totals_sum.get("total_omega3_dha_g", 0) / max(totals_count.get("total_omega3_dha_g", 1), 1)
    if dha_avg < 1.0:
        longevity_flags.append(f"DHA averages {round(dha_avg,2)}g/day — below the 1g+ associated with cognitive protection (Rhonda Patrick). Add fatty fish ≥3x/week or algae-based DHA supplement.")
    mag_avg = totals_sum.get("total_magnesium_mg", 0) / max(totals_count.get("total_magnesium_mg", 1), 1)
    if mag_avg < 350:
        longevity_flags.append(f"Magnesium averages {round(mag_avg)}mg/day. Sub-optimal magnesium is linked to poor sleep quality, elevated cortisol, and lower HRV. Target 400-500mg from food + glycinate supplement.")
    vd_avg = totals_sum.get("total_vitamin_d_mcg", 0) / max(totals_count.get("total_vitamin_d_mcg", 1), 1)
    if vd_avg < 25:
        longevity_flags.append(f"Vitamin D from food averages {round(vd_avg,1)}mcg/day. Difficult to reach optimal serum levels (60-80 ng/mL) from diet alone in the Pacific Northwest — consider 4,000-5,000 IU D3+K2 supplement.")

    return {
        "period":          {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "summary":         {"deficiencies": len(deficiencies), "near_gaps": len(near_gaps), "exceedances": len(exceedances),
                            "omega6_omega3_ratio": o6_o3, "omega6_omega3_status": "OK" if o6_o3 and o6_o3 <= _OMEGA_RATIO_TARGET else "HIGH" if o6_o3 else "insufficient_data"},
        "longevity_flags": longevity_flags,
        "deficiencies":    deficiencies,
        "near_gaps":       near_gaps,
        "exceedances":     exceedances,
        "by_category":     categories,
    }


# ── Tool: get_meal_timing ─────────────────────────────────────────────────────

def tool_get_meal_timing(args):
    """
    Eating window analysis: first bite, last bite, window duration, caloric distribution
    across morning/midday/evening/late, circadian consistency (SD of meal times),
    and overlap with sleep onset. Based on Satchin Panda / Salk Institute TRF research.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    items = query_source("macrofactor", start_date, end_date)
    if not items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    def t2d(t):
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    daily_rows  = []
    first_bites = []
    last_bites  = []
    windows     = []

    for item in sorted(items, key=lambda x: x["date"]):
        food_log = item.get("food_log", [])
        if not food_log:
            continue
        times = []
        morning_cal = midday_cal = evening_cal = late_cal = 0.0
        for entry in food_log:
            td  = t2d(entry.get("time"))
            cal = float(entry.get("calories_kcal", 0) or 0)
            if td is not None:
                times.append(td)
                if td < 11:   morning_cal += cal
                elif td < 15: midday_cal  += cal
                elif td < 20: evening_cal += cal
                else:         late_cal    += cal
        if not times:
            continue
        fb = min(times); lb = max(times); wh = round(lb - fb, 2)
        total_cal = float(item.get("total_calories_kcal", 0) or 0)
        first_bites.append(fb); last_bites.append(lb); windows.append(wh)
        daily_rows.append({
            "date": item["date"],
            "first_bite": d2hm(fb),
            "last_bite":  d2hm(lb),
            "eating_window_hrs": wh,
            "total_calories": round(total_cal, 0),
            "distribution": {
                "morning_pct": round(morning_cal / total_cal * 100, 1) if total_cal else 0,
                "midday_pct":  round(midday_cal  / total_cal * 100, 1) if total_cal else 0,
                "evening_pct": round(evening_cal / total_cal * 100, 1) if total_cal else 0,
                "late_pct":    round(late_cal    / total_cal * 100, 1) if total_cal else 0,
            },
            "late_eating_flag": lb >= 20.0,
        })

    if not daily_rows:
        return {"error": "No food log entries with timestamps found."}

    n = len(daily_rows)
    avg_fb  = sum(first_bites) / n
    avg_lb  = sum(last_bites)  / n
    avg_win = round(sum(windows) / n, 1)

    def stdev(vals):
        n2 = len(vals)
        if n2 < 2: return 0
        m = sum(vals) / n2
        return round(math.sqrt(sum((v - m)**2 for v in vals) / (n2 - 1)), 2)

    late_days = sum(1 for r in daily_rows if r["late_eating_flag"])

    # Eight Sleep sleep-onset overlap
    sleep_onset_avg = None
    try:
        si_items = query_source("eightsleep", start_date, end_date)
        onsets = []
        for si in si_items:
            onset_str = si.get("sleep_start_local") or si.get("sleep_onset_local")
            if onset_str:
                td = t2d(str(onset_str)[:5])
                if td is not None:
                    onsets.append(td if td > 8 else td + 24)
        if onsets:
            sleep_onset_avg = sum(onsets) / len(onsets)
    except Exception:
        pass

    pre_sleep_gap = None
    if sleep_onset_avg is not None:
        gap = sleep_onset_avg - avg_lb
        if gap < 0: gap += 24
        pre_sleep_gap = round(gap, 1)

    trf_flags = []
    if avg_win > 12:
        trf_flags.append(f"Average eating window is {avg_win}h — wider than the 10h TRF target. Try compressing to <10h for metabolic benefit.")
    if stdev(first_bites) > 1.5:
        trf_flags.append(f"First bite time varies by {stdev(first_bites)}h SD — inconsistent circadian signalling. Aim for <1h variation.")
    if late_days > n * 0.3:
        trf_flags.append(f"Eating after 8pm on {late_days}/{n} days. Late eating suppresses melatonin-mediated metabolic signalling.")
    if pre_sleep_gap is not None and pre_sleep_gap < 2.5:
        trf_flags.append(f"Average last bite → sleep gap is only {pre_sleep_gap}h. Panda recommends ≥3h to allow GLP-1 clearance before sleep onset.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "eating_window": {
            "avg_first_bite":                d2hm(avg_fb),
            "avg_last_bite":                 d2hm(avg_lb),
            "avg_window_hrs":                avg_win,
            "first_bite_consistency_sd_hrs": stdev(first_bites),
            "last_bite_consistency_sd_hrs":  stdev(last_bites),
            "trf_status": "OPTIMAL" if avg_win <= 10 else "BORDERLINE" if avg_win <= 12 else "WIDE",
        },
        "late_eating":  {"days_eating_after_8pm": late_days, "pct_days": round(late_days / n * 100, 1)},
        "sleep_overlap": {
            "avg_last_bite_to_sleep_hrs": pre_sleep_gap,
            "status": ("GOOD" if pre_sleep_gap and pre_sleep_gap >= 3 else
                       "MARGINAL" if pre_sleep_gap and pre_sleep_gap >= 2 else
                       "TOO_CLOSE" if pre_sleep_gap else "no_sleep_data"),
        },
        "circadian_flags": trf_flags,
        "daily_breakdown": daily_rows,
    }


# ── Tool: get_nutrition_biometrics_correlation ────────────────────────────────

def tool_get_nutrition_biometrics_correlation(args):
    """
    Pearson correlations between daily nutrition inputs and biometric outcomes across
    Whoop, Withings, and Eight Sleep. Optional lag tests next-day effects.
    This is the personalized insight layer — what does YOUR diet actually predict about
    YOUR recovery, sleep, HRV, and weight?
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))
    lag_days   = int(args.get("lag_days", 1))

    NUTRITION_FIELDS = [
        ("total_calories_kcal",  "Calories (kcal)"),
        ("total_protein_g",      "Protein (g)"),
        ("total_carbs_g",        "Carbs (g)"),
        ("total_fat_g",          "Fat (g)"),
        ("total_fiber_g",        "Fiber (g)"),
        ("total_omega3_total_g", "Omega-3 (g)"),
        ("total_sodium_mg",      "Sodium (mg)"),
        ("total_caffeine_mg",    "Caffeine (mg)"),
        ("total_magnesium_mg",   "Magnesium (mg)"),
        ("total_alcohol_g",      "Alcohol (g)"),
    ]
    BIOMETRIC_FIELDS = [
        ("whoop",      "hrv",                  "HRV (ms)"),
        ("whoop",      "recovery_score",        "Recovery Score"),
        ("whoop",      "resting_heart_rate",    "Resting HR (bpm)"),
        ("whoop",      "sleep_performance_pct", "Sleep Performance (%)"),
        ("whoop",      "strain",                "Strain"),
        ("withings",   "weight_lbs",            "Weight (lbs)"),
        ("eightsleep", "sleep_score",           "Sleep Score"),
        ("eightsleep", "efficiency",            "Sleep Efficiency (%)"),
        ("eightsleep", "hrv_avg_ms",            "Sleep HRV (ms)"),
    ]

    mf_items = query_source("macrofactor", start_date, end_date)
    if len(mf_items) < 14:
        return {"error": f"Need ≥14 days of MacroFactor data. Found {len(mf_items)}."}
    mf_by_date = {item["date"]: item for item in mf_items}

    bio_end  = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=lag_days + 1)).strftime("%Y-%m-%d")
    bio_srcs = list({src for src, _, _ in BIOMETRIC_FIELDS})
    bio_data = parallel_query_sources(bio_srcs, start_date, bio_end)
    bio_by_src = {src: {i["date"]: i for i in items} for src, items in bio_data.items()}

    results = []
    for nf, nf_label in NUTRITION_FIELDS:
        for bio_src, bf, bf_label in BIOMETRIC_FIELDS:
            bbd = bio_by_src.get(bio_src, {})
            pairs = []
            for ds, mf_item in mf_by_date.items():
                nv = mf_item.get(nf)
                if nv is None: continue
                bio_date = (datetime.strptime(ds, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
                bi = bbd.get(bio_date)
                if bi is None: continue
                bv = bi.get(bf)
                if bv is None: continue
                pairs.append((float(nv), float(bv)))
            if len(pairs) < 10:
                continue
            xs, ys = zip(*pairs)
            r = pearson_r(list(xs), list(ys))
            if r is None or abs(r) < 0.2:
                continue
            abs_r = abs(r)
            results.append({
                "nutrition":      nf_label,
                "biometric":      bf_label,
                "r":              r,
                "abs_r":          abs_r,
                "strength":       "strong" if abs_r >= 0.5 else "moderate" if abs_r >= 0.35 else "weak",
                "direction":      "positive" if r > 0 else "negative",
                "n_days":         len(pairs),
                "lag_days":       lag_days,
                "interpretation": f"{'Higher' if r > 0 else 'Lower'} {nf_label} → {'higher' if r > 0 else 'lower'} {bf_label} {'next day' if lag_days == 1 else f'{lag_days}d later' if lag_days > 1 else 'same day'}",
            })

    results.sort(key=lambda x: -x["abs_r"])
    actionable = [r for r in results if r["strength"] in ("strong", "moderate")]

    return {
        "period":              {"start_date": start_date, "end_date": end_date},
        "methodology":         f"Pearson r: nutrition → biometrics shifted +{lag_days} day(s). |r| ≥ 0.5 strong, ≥ 0.35 moderate, ≥ 0.2 weak. Only |r| ≥ 0.2 reported.",
        "top_findings":        results[:15],
        "actionable_findings": actionable,
        "total_tested":        len(NUTRITION_FIELDS) * len(BIOMETRIC_FIELDS),
        "significant_pairs":   len(results),
        "all_results":         results,
    }


# ── Tool: get_nutrition_summary ──────────────────────────────────────────────

def tool_get_nutrition_summary(args):
    """
    Daily macro breakdown + rolling averages for any date range.
    Returns per-day rows and period averages for calories, protein, carbs, fat, fiber,
    sodium, caffeine, omega-3, and key micronutrients.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    pk = USER_PREFIX + "macrofactor"
    table = get_table()
    items = query_date_range(table, pk, start_date, end_date)

    if not items:
        return {"error": "No MacroFactor data found for the requested range.", "start_date": start_date, "end_date": end_date}

    MACRO_FIELDS = [
        ("total_calories_kcal",  "calories_kcal"),
        ("total_protein_g",      "protein_g"),
        ("total_carbs_g",        "carbs_g"),
        ("total_fat_g",          "fat_g"),
        ("total_fiber_g",        "fiber_g"),
        ("total_sodium_mg",      "sodium_mg"),
        ("total_caffeine_mg",    "caffeine_mg"),
        ("total_omega3_total_g", "omega3_total_g"),
        ("total_potassium_mg",   "potassium_mg"),
        ("total_magnesium_mg",   "magnesium_mg"),
        ("total_vitamin_d_mcg",  "vitamin_d_mcg"),
        ("total_alcohol_g",      "alcohol_g"),
    ]

    daily_rows = []
    for item in sorted(items, key=lambda x: x["date"]):
        row = {"date": item["date"], "entries_logged": item.get("entries_count", 0)}
        for db_field, out_field in MACRO_FIELDS:
            v = item.get(db_field)
            if v is not None:
                row[out_field] = float(v)
        # Derived: protein % of calories
        cal  = row.get("calories_kcal", 0)
        prot = row.get("protein_g", 0)
        if cal > 0:
            row["protein_pct_of_calories"] = round(prot * 4 / cal * 100, 1)
        # Board rec 1A: fiber density (Norton) — normalizes for caloric intake
        fib = row.get("fiber_g", 0)
        if cal > 0 and fib > 0:
            row["fiber_per_1000kcal"] = round(fib / (cal / 1000), 1)
        daily_rows.append(row)

    # Period averages
    def avg(field):
        vals = [r[field] for r in daily_rows if field in r]
        return round(sum(vals) / len(vals), 1) if vals else None

    averages = {out: avg(out) for _, out in MACRO_FIELDS}
    averages["protein_pct_of_calories"] = avg("protein_pct_of_calories")
    averages["fiber_per_1000kcal"] = avg("fiber_per_1000kcal")

    # Reference targets (from profile / common goals)
    TARGETS = {
        "calories_kcal":    2400,
        "protein_g":        180,
        "fiber_g":          30,
        "fiber_per_1000kcal": 14,   # Board rec 1A (Norton): minimum fiber density
        "sodium_mg":        2300,
        "omega3_total_g":   2.0,
        "vitamin_d_mcg":    20,
    }
    target_comparison = {}
    for field, target in TARGETS.items():
        avg_val = averages.get(field)
        if avg_val is not None:
            target_comparison[field] = {
                "target":  target,
                "average": avg_val,
                "gap":     round(avg_val - target, 1),
                "pct_of_target": round(avg_val / target * 100, 1),
            }

    return {
        "period":            {"start_date": start_date, "end_date": end_date, "days_with_data": len(daily_rows)},
        "daily_averages":    averages,
        "target_comparison": target_comparison,
        "daily_breakdown":   daily_rows,
    }


# ── Tool: get_macro_targets ───────────────────────────────────────────────────

def tool_get_macro_targets(args):
    """
    Compare actual nutrition vs calorie / protein targets.
    Pulls recent Withings weight to compute TDEE-based calorie target,
    then scores daily adherence to each macro goal.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 30))
    start_date = args.get("start_date") or (
        (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    )
    calorie_target = args.get("calorie_target")   # optional override
    protein_target = args.get("protein_target")   # optional override

    table = get_table()
    pk_mf = USER_PREFIX + "macrofactor"
    items = query_date_range(table, pk_mf, start_date, end_date)

    if not items:
        return {"error": "No MacroFactor data found.", "start_date": start_date, "end_date": end_date}

    # Pull current weight for TDEE estimate if no calorie_target override
    if not calorie_target:
        try:
            pk_wt = USER_PREFIX + "withings"
            wt_items = query_date_range(table, pk_wt,
                (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d"),
                end_date)
            wt_items_sorted = sorted(wt_items, key=lambda x: x["date"], reverse=True)
            if wt_items_sorted:
                weight_lbs = float(wt_items_sorted[0].get("weight_lbs", 0))
                # Mifflin-St Jeor BMR for male (approx for Matthew)
                weight_kg = weight_lbs * 0.453592
                # height 72in = 182.88cm, age ~35
                bmr = 10 * weight_kg + 6.25 * 182.88 - 5 * 35 + 5
                tdee_estimate = round(bmr * 1.55)  # moderate activity
                calorie_target = calorie_target or tdee_estimate
        except Exception:
            pass
    calorie_target = calorie_target or 2400
    protein_target = protein_target or 180

    daily_rows = []
    hits_cal  = hits_prot = hits_fiber = 0
    for item in sorted(items, key=lambda x: x["date"]):
        cal   = float(item.get("total_calories_kcal", 0) or 0)
        prot  = float(item.get("total_protein_g",     0) or 0)
        fiber = float(item.get("total_fiber_g",       0) or 0)
        fat   = float(item.get("total_fat_g",         0) or 0)
        carbs = float(item.get("total_carbs_g",       0) or 0)

        cal_pct  = round(cal  / calorie_target * 100, 1)
        prot_pct = round(prot / protein_target * 100, 1)

        hit_cal  = 0.85 <= cal / calorie_target <= 1.10
        hit_prot = prot >= protein_target * 0.95
        hit_fiber = fiber >= 25

        hits_cal   += int(hit_cal)
        hits_prot  += int(hit_prot)
        hits_fiber += int(hit_fiber)

        daily_rows.append({
            "date":            item["date"],
            "calories_kcal":   round(cal, 0),
            "calories_pct":    cal_pct,
            "protein_g":       round(prot, 1),
            "protein_pct":     prot_pct,
            "fat_g":           round(fat, 1),
            "carbs_g":         round(carbs, 1),
            "fiber_g":         round(fiber, 1),
            "hit_calorie_target":  hit_cal,
            "hit_protein_target":  hit_prot,
            "hit_fiber_target":    hit_fiber,
        })

    n = len(daily_rows)
    return {
        "period":           {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "targets": {
            "calories_kcal":  calorie_target,
            "protein_g":      protein_target,
            "fiber_g":        25,
            "note":           "Calorie target estimated from TDEE (Mifflin-St Jeor × 1.55 activity factor) unless overridden.",
        },
        "adherence": {
            "calorie_target_hit_pct":  round(hits_cal  / n * 100, 1) if n else 0,
            "protein_target_hit_pct":  round(hits_prot / n * 100, 1) if n else 0,
            "fiber_target_hit_pct":    round(hits_fiber / n * 100, 1) if n else 0,
        },
        "daily_breakdown": daily_rows,
    }


# ── Tool: get_food_log ────────────────────────────────────────────────────────

def tool_get_food_log(args):
    """
    Return individual food entries logged on a specific date.
    Useful for 'what did I eat yesterday?', 'show me my food diary'.
    """
    date_str = args.get("date", (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"))

    table = get_table()
    pk = USER_PREFIX + "macrofactor"

    response = table.get_item(Key={"pk": pk, "sk": f"DATE#{date_str}"})
    item     = response.get("Item")

    if not item:
        return {"error": f"No MacroFactor data for {date_str}. Check the date or re-export from MacroFactor."}

    # Build clean food log
    food_log = item.get("food_log", [])
    clean_log = []
    for entry in food_log:
        clean_entry = {
            "food":         entry.get("food_name", "Unknown"),
            "time":         entry.get("time"),
            "serving":      entry.get("serving_size"),
            "calories":     entry.get("calories_kcal"),
            "protein_g":    entry.get("protein_g"),
            "carbs_g":      entry.get("carbs_g"),
            "fat_g":        entry.get("fat_g"),
            "fiber_g":      entry.get("fiber_g"),
        }
        clean_entry = {k: float(v) if isinstance(v, Decimal) else v
                       for k, v in clean_entry.items() if v is not None}
        clean_log.append(clean_entry)

    # Day totals
    totals = {
        "calories_kcal": float(item.get("total_calories_kcal") or 0),
        "protein_g":     float(item.get("total_protein_g")     or 0),
        "carbs_g":       float(item.get("total_carbs_g")        or 0),
        "fat_g":         float(item.get("total_fat_g")          or 0),
        "fiber_g":       float(item.get("total_fiber_g")        or 0),
        "sodium_mg":     float(item.get("total_sodium_mg")      or 0),
        "caffeine_mg":   float(item.get("total_caffeine_mg")    or 0),
        "omega3_total_g":float(item.get("total_omega3_total_g") or 0),
    }

    return {
        "date":          date_str,
        "entries_logged": item.get("entries_count", len(food_log)),
        "daily_totals":  totals,
        "food_log":      clean_log,
    }




# ── Tool: get_caffeine_sleep_correlation ─────────────────────────────────────

def tool_get_caffeine_sleep_correlation(args):
    """
    Personal caffeine cutoff finder. Scans MacroFactor food_log for caffeine-containing
    entries, finds the last caffeine intake time per day, then correlates with same-night
    Eight Sleep metrics. Splits days into time buckets to show where sleep degrades.
    Based on Huberman & Attia: caffeine timing is one of the highest-leverage sleep interventions.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))

    mf_items = query_source("macrofactor", start_date, end_date)
    es_items = query_source("eightsleep",  start_date, end_date)

    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    # Index Eight Sleep by date
    sleep_by_date = {}
    for item in es_items:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    def t2d(t):
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    # ── Extract per-day caffeine timing + sleep metrics ──────────────────────
    daily_rows = []

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue

        sleep = sleep_by_date.get(date)
        if not sleep:
            continue

        food_log = mf_item.get("food_log", [])
        total_caffeine = _sf(mf_item.get("total_caffeine_mg")) or 0

        # Find last caffeine intake time
        last_caffeine_time = None
        last_caffeine_food = None
        caffeine_entry_count = 0
        for entry in food_log:
            caf = _sf(entry.get("caffeine_mg"))
            if caf and caf > 0:
                td = t2d(entry.get("time"))
                if td is not None:
                    caffeine_entry_count += 1
                    if last_caffeine_time is None or td > last_caffeine_time:
                        last_caffeine_time = td
                        last_caffeine_food = entry.get("food_name", "Unknown")

        # Sleep metrics
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))

        if eff is None and score is None and deep is None:
            continue

        # Categorize
        if total_caffeine < 1:
            bucket = "no_caffeine"
        elif last_caffeine_time is None:
            bucket = "unknown_time"
        elif last_caffeine_time < 12:
            bucket = "before_noon"
        elif last_caffeine_time < 14:
            bucket = "noon_to_2pm"
        elif last_caffeine_time < 16:
            bucket = "2pm_to_4pm"
        else:
            bucket = "after_4pm"

        daily_rows.append({
            "date": date,
            "total_caffeine_mg": round(total_caffeine, 1),
            "last_caffeine_time": last_caffeine_time,
            "last_caffeine_time_hm": d2hm(last_caffeine_time),
            "last_caffeine_food": last_caffeine_food,
            "caffeine_entries": caffeine_entry_count,
            "bucket": bucket,
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
        })

    if len(daily_rows) < 5:
        return {
            "error": f"Only {len(daily_rows)} days with both caffeine and sleep data. Need at least 5.",
            "hint": "Ensure MacroFactor food logging and Eight Sleep data overlap for the requested period.",
            "start_date": start_date, "end_date": end_date,
        }

    # ── Bucket analysis ──────────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
    ]

    BUCKET_ORDER = ["no_caffeine", "before_noon", "noon_to_2pm", "2pm_to_4pm", "after_4pm"]
    BUCKET_LABELS = {
        "no_caffeine":  "No Caffeine",
        "before_noon":  "Last Caffeine Before Noon",
        "noon_to_2pm":  "Last Caffeine 12-2 PM",
        "2pm_to_4pm":   "Last Caffeine 2-4 PM",
        "after_4pm":    "Last Caffeine After 4 PM",
        "unknown_time": "Caffeine (time unknown)",
    }

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_caffeine_mg": _avg([r["total_caffeine_mg"] for r in b_rows]),
            "metrics": {},
        }
        for field, label, _ in SLEEP_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Timing correlations (last caffeine time vs sleep) ────────────────────
    timed_rows = [r for r in daily_rows if r["last_caffeine_time"] is not None]

    timing_correlations = {}
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_caffeine_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]                for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later caffeine {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Dose correlations (total caffeine mg vs sleep) ───────────────────────
    dose_correlations = {}
    caff_rows = [r for r in daily_rows if r["total_caffeine_mg"] > 0]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["total_caffeine_mg"] for r in caff_rows if r[field] is not None]
        ys = [r[field]               for r in caff_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            dose_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # ── Personal cutoff recommendation ───────────────────────────────────────
    recommendation = None
    cutoff_time = None
    if bucket_data:
        ref_buckets = ["no_caffeine", "before_noon"]
        ref_effs = []
        for b in ref_buckets:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                ref_effs.append(bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"])
        ref_eff = max(ref_effs) if ref_effs else None

        if ref_eff is not None:
            degradation_threshold = 2.0
            for b in ["noon_to_2pm", "2pm_to_4pm", "after_4pm"]:
                if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                    b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                    if ref_eff - b_eff >= degradation_threshold:
                        cutoff_map = {"noon_to_2pm": "noon", "2pm_to_4pm": "2 PM", "after_4pm": "4 PM"}
                        cutoff_time = cutoff_map.get(b, b)
                        drop = round(ref_eff - b_eff, 1)
                        recommendation = (
                            f"Your sleep efficiency drops by {drop} percentage points when your last caffeine "
                            f"is after {cutoff_time}. Based on your data, your personal caffeine cutoff should be {cutoff_time}."
                        )
                        break

        if recommendation is None:
            eff_corr = timing_correlations.get("sleep_efficiency_pct")
            if eff_corr and eff_corr["impact"] == "HARMFUL":
                recommendation = (
                    f"No sharp cutoff detected in bucket analysis, but there is a continuous "
                    f"negative correlation (r={eff_corr['pearson_r']}) between later caffeine and sleep efficiency. "
                    f"Earlier is better for you -- aim for before 2 PM as a general guideline."
                )
                cutoff_time = "2 PM"
            else:
                recommendation = (
                    "Your data does not show a strong relationship between caffeine timing and sleep quality. "
                    "This could mean you metabolize caffeine efficiently, or there is not enough data yet. "
                    "Continue logging and re-check after 30+ days of data."
                )

    # ── Summary + alerts ─────────────────────────────────────────────────────
    all_caff_times = [r["last_caffeine_time"] for r in daily_rows if r["last_caffeine_time"] is not None]
    no_caff_days = sum(1 for r in daily_rows if r["bucket"] == "no_caffeine")

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "days_with_caffeine": len(all_caff_times),
        "days_without_caffeine": no_caff_days,
        "avg_last_caffeine_time": d2hm(sum(all_caff_times) / len(all_caff_times)) if all_caff_times else None,
        "avg_daily_caffeine_mg": _avg([r["total_caffeine_mg"] for r in daily_rows if r["total_caffeine_mg"] > 0]),
    }

    alerts = []
    if summary["avg_daily_caffeine_mg"] and summary["avg_daily_caffeine_mg"] > 400:
        alerts.append(
            f"Average daily caffeine is {summary['avg_daily_caffeine_mg']}mg -- exceeds the 400mg/day FDA safety threshold."
        )
    after_4_count = sum(1 for r in daily_rows if r["bucket"] == "after_4pm")
    if after_4_count > 0:
        pct = round(100 * after_4_count / len(daily_rows), 0)
        alerts.append(
            f"Caffeine consumed after 4 PM on {after_4_count} days ({pct:.0f}%). "
            "Caffeine has a half-life of 5-6 hours -- a 4 PM coffee means ~50% still circulating at 10 PM."
        )
    deep_corr = timing_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "HARMFUL" and abs(deep_corr["pearson_r"]) > 0.25:
        alerts.append(
            f"Later caffeine correlates with reduced deep sleep (r={deep_corr['pearson_r']}). "
            "Deep/SWS is when growth hormone releases -- critical during weight loss to preserve lean mass."
        )

    return {
        "summary": summary,
        "recommendation": {
            "cutoff_time": cutoff_time,
            "text": recommendation,
            "evidence_basis": "bucket_comparison" if cutoff_time and "drops by" in (recommendation or "") else "correlation" if cutoff_time else "insufficient_data",
        },
        "bucket_comparison": bucket_data,
        "timing_correlations": timing_correlations,
        "dose_correlations": dose_correlations,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "last_caffeine": r["last_caffeine_time_hm"],
                "last_caffeine_food": r["last_caffeine_food"],
                "caffeine_mg": r["total_caffeine_mg"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
            }
            for r in daily_rows
        ],
    }



# ── Tool: get_exercise_sleep_correlation ─────────────────────────────────────

def tool_get_exercise_sleep_correlation(args):
    """
    Personal exercise timing cutoff finder. Extracts the last exercise end time
    per day from Strava (start_date_local + elapsed_time_seconds), then correlates
    with same-night Eight Sleep metrics. Splits days into time-of-day buckets to
    show where late exercise degrades (or improves) sleep quality.
    Also analyzes exercise intensity (avg HR) as a separate dimension.
    Based on Huberman, Galpin, and Attia: exercise timing is a modifiable lever
    for sleep quality, but the effect is highly individual.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=179)).strftime("%Y-%m-%d"))
    min_duration_min = int(args.get("min_duration_minutes", 15))
    exclude_types = [t.strip().lower() for t in (args.get("exclude_sport_types") or "").split(",") if t.strip()]

    strava_items = query_source("strava", start_date, end_date)
    es_items     = query_source("eightsleep", start_date, end_date)

    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    # Index Eight Sleep by date
    sleep_by_date = {}
    for item in es_items:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    # Get user profile for HR zones
    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _parse_local_time(dt_str):
        """Extract decimal hour from ISO local datetime string like '2026-02-15T12:55:30Z'."""
        if not dt_str:
            return None
        try:
            # Handle both 'T' separated and other formats
            time_part = dt_str.split("T")[1] if "T" in dt_str else None
            if not time_part:
                return None
            parts = time_part.replace("Z", "").split(":")
            return int(parts[0]) + int(parts[1]) / 60 + (int(parts[2].split(".")[0]) / 3600 if len(parts) > 2 else 0)
        except Exception:
            return None

    def _d2hm(d):
        """Decimal hours → HH:MM string."""
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _classify_intensity(avg_hr):
        """Classify exercise intensity based on % of max HR."""
        if avg_hr is None:
            return "unknown"
        pct = avg_hr / max_hr * 100
        if pct >= 80:
            return "high"
        elif pct >= 65:
            return "moderate"
        else:
            return "low"

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # ── Extract per-day exercise timing + sleep metrics ──────────────────────
    # All dates with Eight Sleep data form the universe; days without Strava = rest days
    all_dates = sorted(sleep_by_date.keys())
    strava_by_date = {}
    for item in strava_items:
        d = item.get("date")
        if d:
            strava_by_date[d] = item

    daily_rows = []

    for date in all_dates:
        if date < start_date or date > end_date:
            continue

        sleep = sleep_by_date[date]

        # Sleep metrics
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))
        hrv     = _sf(sleep.get("hrv_avg"))

        if eff is None and score is None and deep is None:
            continue

        strava_day = strava_by_date.get(date)
        activities = strava_day.get("activities", []) if strava_day else []

        # Filter activities by duration and excluded types
        valid_acts = []
        for act in activities:
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < min_duration_min * 60:
                continue
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport in exclude_types:
                continue
            valid_acts.append(act)

        # Find last exercise end time and aggregate intensity
        last_end_time = None
        last_sport = None
        last_end_hm = None
        total_exercise_min = 0
        avg_hr_weighted = None
        total_hr_time = 0
        weighted_hr_sum = 0
        activity_count = len(valid_acts)
        sport_types = []

        for act in valid_acts:
            start_local = act.get("start_date_local", "")
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            moving  = _sf(act.get("moving_time_seconds")) or elapsed
            avg_hr  = _sf(act.get("average_heartrate"))
            sport   = act.get("sport_type") or act.get("type") or "Unknown"

            start_decimal = _parse_local_time(start_local)
            if start_decimal is not None:
                end_decimal = start_decimal + elapsed / 3600
                if last_end_time is None or end_decimal > last_end_time:
                    last_end_time = end_decimal
                    last_sport = sport
                    last_end_hm = _d2hm(end_decimal)

            total_exercise_min += moving / 60
            if avg_hr is not None and moving > 0:
                weighted_hr_sum += avg_hr * moving
                total_hr_time += moving
            if sport not in sport_types:
                sport_types.append(sport)

        if total_hr_time > 0:
            avg_hr_weighted = round(weighted_hr_sum / total_hr_time, 1)

        # Bucket by last exercise end time
        if activity_count == 0:
            bucket = "rest_day"
        elif last_end_time is None:
            bucket = "unknown_time"
        elif last_end_time < 12:
            bucket = "before_noon"
        elif last_end_time < 15:
            bucket = "noon_to_3pm"
        elif last_end_time < 18:
            bucket = "3pm_to_6pm"
        elif last_end_time < 20:
            bucket = "6pm_to_8pm"
        else:
            bucket = "after_8pm"

        intensity = _classify_intensity(avg_hr_weighted)

        daily_rows.append({
            "date": date,
            "activity_count": activity_count,
            "total_exercise_min": round(total_exercise_min, 1),
            "last_end_time": last_end_time,
            "last_end_time_hm": last_end_hm,
            "last_sport": last_sport,
            "sport_types": sport_types,
            "avg_hr": avg_hr_weighted,
            "intensity": intensity,
            "bucket": bucket,
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
            "hrv_avg": hrv,
        })

    if len(daily_rows) < 10:
        return {
            "error": f"Only {len(daily_rows)} days with sleep data. Need at least 10.",
            "start_date": start_date, "end_date": end_date,
        }

    exercise_days = [r for r in daily_rows if r["bucket"] != "rest_day"]
    rest_days = [r for r in daily_rows if r["bucket"] == "rest_day"]

    # ── Bucket analysis ──────────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
        ("hrv_avg",              "HRV",                "higher_is_better"),
    ]

    BUCKET_ORDER = ["rest_day", "before_noon", "noon_to_3pm", "3pm_to_6pm", "6pm_to_8pm", "after_8pm"]
    BUCKET_LABELS = {
        "rest_day":     "Rest Day (No Exercise)",
        "before_noon":  "Exercise Ends Before Noon",
        "noon_to_3pm":  "Exercise Ends 12–3 PM",
        "3pm_to_6pm":   "Exercise Ends 3–6 PM",
        "6pm_to_8pm":   "Exercise Ends 6–8 PM",
        "after_8pm":    "Exercise Ends After 8 PM",
        "unknown_time": "Exercise (time unknown)",
    }

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_exercise_min": _avg([r["total_exercise_min"] for r in b_rows if r["total_exercise_min"] > 0]),
            "avg_hr": _avg([r["avg_hr"] for r in b_rows]),
            "metrics": {},
        }
        for field, label, _ in SLEEP_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Timing correlations (last exercise end time vs sleep) ────────────────
    timed_rows = [r for r in exercise_days if r["last_end_time"] is not None]

    timing_correlations = {}
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_end_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]           for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later exercise {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Intensity correlations (avg HR vs sleep, exercise days only) ─────────
    intensity_correlations = {}
    hr_rows = [r for r in exercise_days if r["avg_hr"] is not None]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["avg_hr"] for r in hr_rows if r[field] is not None]
        ys = [r[field]     for r in hr_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            intensity_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # ── Intensity x Timing interaction (high intensity + late = worst combo?) ─
    intensity_timing = {}
    for intensity_level in ["low", "moderate", "high"]:
        i_rows = [r for r in exercise_days if r["intensity"] == intensity_level and r["last_end_time"] is not None]
        if len(i_rows) < 3:
            continue
        late_rows = [r for r in i_rows if r["last_end_time"] >= 18]  # after 6pm
        early_rows = [r for r in i_rows if r["last_end_time"] < 18]
        if late_rows and early_rows:
            intensity_timing[intensity_level] = {
                "early_days": len(early_rows),
                "late_days": len(late_rows),
                "early_avg_efficiency": _avg([r["sleep_efficiency_pct"] for r in early_rows]),
                "late_avg_efficiency": _avg([r["sleep_efficiency_pct"] for r in late_rows]),
                "early_avg_deep": _avg([r["deep_pct"] for r in early_rows]),
                "late_avg_deep": _avg([r["deep_pct"] for r in late_rows]),
                "early_avg_hrv": _avg([r["hrv_avg"] for r in early_rows]),
                "late_avg_hrv": _avg([r["hrv_avg"] for r in late_rows]),
            }
            ee = intensity_timing[intensity_level]["early_avg_efficiency"]
            le = intensity_timing[intensity_level]["late_avg_efficiency"]
            if ee is not None and le is not None:
                intensity_timing[intensity_level]["efficiency_delta"] = round(le - ee, 2)

    # ── Exercise vs rest day comparison ──────────────────────────────────────
    exercise_vs_rest = {}
    if rest_days and exercise_days:
        for field, label, direction in SLEEP_METRICS:
            ex_vals = [r[field] for r in exercise_days if r[field] is not None]
            rest_vals = [r[field] for r in rest_days if r[field] is not None]
            if ex_vals and rest_vals:
                ex_avg = round(sum(ex_vals) / len(ex_vals), 2)
                rest_avg = round(sum(rest_vals) / len(rest_vals), 2)
                delta = round(ex_avg - rest_avg, 2)
                if direction == "lower_is_better":
                    verdict = "BETTER" if delta < -1 else "WORSE" if delta > 1 else "SIMILAR"
                else:
                    verdict = "BETTER" if delta > 1 else "WORSE" if delta < -1 else "SIMILAR"
                exercise_vs_rest[field] = {
                    "label": label,
                    "exercise_avg": ex_avg,
                    "rest_avg": rest_avg,
                    "delta": delta,
                    "verdict": verdict,
                    "exercise_n": len(ex_vals),
                    "rest_n": len(rest_vals),
                }

    # ── Personal cutoff recommendation ───────────────────────────────────────
    recommendation = None
    cutoff_time = None

    if bucket_data:
        # Use rest days + morning exercise as reference baseline
        ref_buckets = ["rest_day", "before_noon", "noon_to_3pm"]
        ref_effs = []
        for b in ref_buckets:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                ref_effs.append(bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"])
        ref_eff = max(ref_effs) if ref_effs else None

        if ref_eff is not None:
            degradation_threshold = 3.0  # Higher threshold than caffeine -- exercise has noise
            for b in ["3pm_to_6pm", "6pm_to_8pm", "after_8pm"]:
                if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                    b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                    if ref_eff - b_eff >= degradation_threshold:
                        cutoff_map = {"3pm_to_6pm": "3 PM", "6pm_to_8pm": "6 PM", "after_8pm": "8 PM"}
                        cutoff_time = cutoff_map.get(b, b)
                        drop = round(ref_eff - b_eff, 1)
                        recommendation = (
                            f"Your sleep efficiency drops by {drop} percentage points when exercise "
                            f"ends after {cutoff_time}. Based on your data, aim to finish workouts by {cutoff_time}."
                        )
                        # Check if it's intensity-dependent
                        if "high" in intensity_timing:
                            hi = intensity_timing["high"]
                            if hi.get("efficiency_delta") is not None and hi["efficiency_delta"] < -3:
                                recommendation += (
                                    f" This effect is amplified for high-intensity exercise "
                                    f"(efficiency delta: {hi['efficiency_delta']} pts late vs early)."
                                )
                        break

        if recommendation is None:
            eff_corr = timing_correlations.get("sleep_efficiency_pct")
            if eff_corr and eff_corr["impact"] == "HARMFUL":
                recommendation = (
                    f"No sharp cutoff detected in bucket analysis, but there is a continuous "
                    f"negative correlation (r={eff_corr['pearson_r']}) between later exercise and sleep efficiency. "
                    f"Earlier is generally better for you."
                )
                cutoff_time = "6 PM (suggested)"
            elif eff_corr and eff_corr["impact"] == "BENEFICIAL":
                recommendation = (
                    f"Your data suggests later exercise actually correlates with BETTER sleep (r={eff_corr['pearson_r']}). "
                    f"This is not uncommon -- some people sleep better after evening exercise due to temperature "
                    f"drop rebound. No cutoff needed; exercise when it fits your schedule."
                )
            else:
                recommendation = (
                    "Your data does not show a strong relationship between exercise timing and sleep quality. "
                    "This is actually good news -- it means you can exercise when convenient without worrying "
                    "about sleep impact. Continue tracking to confirm with more data."
                )

    # ── Summary + alerts ─────────────────────────────────────────────────────
    all_end_times = [r["last_end_time"] for r in exercise_days if r["last_end_time"] is not None]

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "exercise_days": len(exercise_days),
        "rest_days": len(rest_days),
        "avg_last_exercise_end": _d2hm(sum(all_end_times) / len(all_end_times)) if all_end_times else None,
        "avg_exercise_min_on_active_days": _avg([r["total_exercise_min"] for r in exercise_days if r["total_exercise_min"] > 0]),
        "avg_hr_on_active_days": _avg([r["avg_hr"] for r in exercise_days]),
        "intensity_distribution": {
            level: sum(1 for r in exercise_days if r["intensity"] == level)
            for level in ["low", "moderate", "high", "unknown"]
        },
    }

    alerts = []
    # Late high-intensity warning
    late_intense = [r for r in exercise_days if r["last_end_time"] and r["last_end_time"] >= 20 and r["intensity"] == "high"]
    if late_intense:
        pct = round(100 * len(late_intense) / len(exercise_days), 0)
        alerts.append(
            f"High-intensity exercise ending after 8 PM on {len(late_intense)} days ({pct:.0f}%). "
            "Intense late workouts elevate core temperature and cortisol, both of which delay sleep onset. "
            "Consider shifting these to earlier or replacing with low-intensity evening sessions."
        )
    # Exercise vs rest insight
    evr_eff = exercise_vs_rest.get("sleep_efficiency_pct")
    if evr_eff and evr_eff["verdict"] == "BETTER":
        alerts.append(
            f"You sleep better on exercise days: {evr_eff['exercise_avg']}% vs {evr_eff['rest_avg']}% "
            f"efficiency (+{evr_eff['delta']} pts). Exercise is a net positive for your sleep."
        )
    elif evr_eff and evr_eff["verdict"] == "WORSE":
        alerts.append(
            f"You sleep worse on exercise days: {evr_eff['exercise_avg']}% vs {evr_eff['rest_avg']}% "
            f"efficiency ({evr_eff['delta']} pts). This is unusual -- check timing and intensity patterns."
        )
    # Deep sleep impact
    deep_corr = timing_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "HARMFUL" and abs(deep_corr["pearson_r"]) > 0.25:
        alerts.append(
            f"Later exercise correlates with reduced deep sleep (r={deep_corr['pearson_r']}). "
            "Deep/SWS drives growth hormone release -- critical during body recomposition."
        )

    return {
        "summary": summary,
        "recommendation": {
            "cutoff_time": cutoff_time,
            "text": recommendation,
            "evidence_basis": ("bucket_comparison" if cutoff_time and "drops by" in (recommendation or "")
                              else "correlation" if cutoff_time
                              else "beneficial" if "BETTER" in (recommendation or "")
                              else "insufficient_data"),
        },
        "bucket_comparison": bucket_data,
        "exercise_vs_rest": exercise_vs_rest,
        "timing_correlations": timing_correlations,
        "intensity_correlations": intensity_correlations,
        "intensity_x_timing": intensity_timing,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "last_exercise_end": r["last_end_time_hm"],
                "last_sport": r["last_sport"],
                "exercise_min": r["total_exercise_min"],
                "avg_hr": r["avg_hr"],
                "intensity": r["intensity"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
                "hrv": r["hrv_avg"],
            }
            for r in daily_rows
        ],
    }



# ── Tool: get_zone2_breakdown ────────────────────────────────────────────────

def tool_get_zone2_breakdown(args):
    """
    Zone 2 training tracker. Classifies each Strava activity into HR zones based on
    average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2
    minutes, compares to the 150 min/week target (Attia, Huberman, WHO guidelines for
    moderate-intensity aerobic activity), and shows full 5-zone distribution.

    Zone 2 is the highest-evidence longevity training modality — it builds mitochondrial
    density, fat oxidation capacity, and cardiovascular base. Most people drastically
    undertrain Zone 2 relative to higher intensities.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))
    weekly_target_min = int(args.get("weekly_target_minutes", 150))
    min_duration_min  = int(args.get("min_duration_minutes", 10))

    # HR zone thresholds from profile
    profile = get_profile()
    max_hr  = float(profile.get("max_heart_rate", 190))
    rhr     = float(profile.get("resting_heart_rate_baseline", 60))

    # 5 zones by % of max HR (standard model)
    # Zone 1: 50-60%  (warm-up / recovery)
    # Zone 2: 60-70%  (aerobic base / fat burn — the longevity zone)
    # Zone 3: 70-80%  (tempo / aerobic capacity)
    # Zone 4: 80-90%  (threshold / lactate)
    # Zone 5: 90-100% (VO2 max / anaerobic)
    ZONE_BOUNDS = [
        ("zone_1", "Zone 1 (Recovery)",   0.50, 0.60),
        ("zone_2", "Zone 2 (Aerobic)",    0.60, 0.70),
        ("zone_3", "Zone 3 (Tempo)",      0.70, 0.80),
        ("zone_4", "Zone 4 (Threshold)",  0.80, 0.90),
        ("zone_5", "Zone 5 (VO2 Max)",    0.90, 1.00),
    ]

    zone_hr_ranges = {}
    for key, label, lo_pct, hi_pct in ZONE_BOUNDS:
        zone_hr_ranges[key] = {
            "label": label,
            "hr_low": round(max_hr * lo_pct, 0),
            "hr_high": round(max_hr * hi_pct, 0),
        }

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def classify_zone(avg_hr):
        """Classify activity into HR zone by avg HR."""
        if avg_hr is None:
            return "no_hr"
        pct = avg_hr / max_hr
        if pct < 0.50:
            return "below_zone_1"
        elif pct < 0.60:
            return "zone_1"
        elif pct < 0.70:
            return "zone_2"
        elif pct < 0.80:
            return "zone_3"
        elif pct < 0.90:
            return "zone_4"
        else:
            return "zone_5"

    # ── Query Strava activities ──────────────────────────────────────────────
    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}

    # Flatten all activities
    all_activities = []
    for day in sorted(strava_items, key=lambda x: x.get("date", "")):
        date = day.get("date", "")
        for act in day.get("activities", []):
            moving = _sf(act.get("moving_time_seconds")) or 0
            if moving < min_duration_min * 60:
                continue
            avg_hr = _sf(act.get("average_heartrate"))
            zone = classify_zone(avg_hr)
            sport = act.get("sport_type") or act.get("type") or "Unknown"
            all_activities.append({
                "date": date,
                "name": act.get("enriched_name") or act.get("name") or "Unnamed",
                "sport_type": sport,
                "moving_time_min": round(moving / 60, 1),
                "avg_hr": avg_hr,
                "max_hr": _sf(act.get("max_heartrate")),
                "zone": zone,
                "distance_miles": _sf(act.get("distance_miles")),
            })

    if not all_activities:
        return {"error": "No qualifying activities found.", "start_date": start_date, "end_date": end_date}

    # ── Weekly aggregation ───────────────────────────────────────────────────
    from collections import defaultdict

    def iso_week(date_str):
        """Return ISO year-week string like '2025-W48'."""
        from datetime import datetime as dt
        d = dt.strptime(date_str, "%Y-%m-%d")
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def week_start(date_str):
        """Return Monday of the week for a given date."""
        from datetime import datetime as dt
        d = dt.strptime(date_str, "%Y-%m-%d")
        monday = d - timedelta(days=d.weekday())
        return monday.strftime("%Y-%m-%d")

    weekly = defaultdict(lambda: {
        "zone_1_min": 0, "zone_2_min": 0, "zone_3_min": 0,
        "zone_4_min": 0, "zone_5_min": 0, "below_zone_1_min": 0,
        "no_hr_min": 0, "total_exercise_min": 0, "activity_count": 0,
        "zone_2_activities": [],
    })

    for act in all_activities:
        wk = week_start(act["date"])
        z = act["zone"]
        mins = act["moving_time_min"]
        weekly[wk]["total_exercise_min"] += mins
        weekly[wk]["activity_count"] += 1
        if z in ("zone_1", "zone_2", "zone_3", "zone_4", "zone_5"):
            weekly[wk][f"{z}_min"] += mins
        elif z == "below_zone_1":
            weekly[wk]["below_zone_1_min"] += mins
        else:
            weekly[wk]["no_hr_min"] += mins
        if z == "zone_2":
            weekly[wk]["zone_2_activities"].append({
                "date": act["date"],
                "name": act["name"],
                "sport": act["sport_type"],
                "minutes": mins,
                "avg_hr": act["avg_hr"],
            })

    weekly_sorted = []
    for wk in sorted(weekly.keys()):
        w = weekly[wk]
        z2 = w["zone_2_min"]
        pct_target = round(100 * z2 / weekly_target_min, 0) if weekly_target_min > 0 else None
        weekly_sorted.append({
            "week_start": wk,
            "zone_2_minutes": round(z2, 1),
            "target_pct": pct_target,
            "target_met": z2 >= weekly_target_min,
            "zone_1_min": round(w["zone_1_min"], 1),
            "zone_3_min": round(w["zone_3_min"], 1),
            "zone_4_min": round(w["zone_4_min"], 1),
            "zone_5_min": round(w["zone_5_min"], 1),
            "total_exercise_min": round(w["total_exercise_min"], 1),
            "activity_count": w["activity_count"],
            "zone_2_activities": w["zone_2_activities"],
        })

    # ── Zone distribution (full period) ──────────────────────────────────────
    zone_totals = {"zone_1": 0, "zone_2": 0, "zone_3": 0, "zone_4": 0, "zone_5": 0, "below_zone_1": 0, "no_hr": 0}
    zone_counts = {"zone_1": 0, "zone_2": 0, "zone_3": 0, "zone_4": 0, "zone_5": 0, "below_zone_1": 0, "no_hr": 0}
    for act in all_activities:
        z = act["zone"]
        zone_totals[z] = zone_totals.get(z, 0) + act["moving_time_min"]
        zone_counts[z] = zone_counts.get(z, 0) + 1

    total_min = sum(zone_totals.values())
    zone_distribution = {}
    for key, label, _, _ in ZONE_BOUNDS:
        mins = round(zone_totals.get(key, 0), 1)
        zone_distribution[key] = {
            "label": label,
            "total_minutes": mins,
            "activity_count": zone_counts.get(key, 0),
            "pct_of_training": round(100 * mins / total_min, 1) if total_min > 0 else 0,
            "hr_range": f"{zone_hr_ranges[key]['hr_low']:.0f}-{zone_hr_ranges[key]['hr_high']:.0f} bpm",
        }

    # ── Sport type breakdown for Zone 2 ──────────────────────────────────────
    z2_by_sport = defaultdict(lambda: {"minutes": 0, "count": 0})
    for act in all_activities:
        if act["zone"] == "zone_2":
            z2_by_sport[act["sport_type"]]["minutes"] += act["moving_time_min"]
            z2_by_sport[act["sport_type"]]["count"] += 1

    sport_breakdown = []
    for sport, data in sorted(z2_by_sport.items(), key=lambda x: -x[1]["minutes"]):
        sport_breakdown.append({
            "sport_type": sport,
            "zone_2_minutes": round(data["minutes"], 1),
            "activity_count": data["count"],
        })

    # ── Trend analysis ───────────────────────────────────────────────────────
    z2_weekly_vals = [w["zone_2_minutes"] for w in weekly_sorted]
    trend = None
    if len(z2_weekly_vals) >= 3:
        xs = list(range(len(z2_weekly_vals)))
        slope_r = pearson_r(xs, z2_weekly_vals) if len(xs) >= 3 else None
        avg_first_half = sum(z2_weekly_vals[:len(z2_weekly_vals)//2]) / max(len(z2_weekly_vals)//2, 1)
        avg_second_half = sum(z2_weekly_vals[len(z2_weekly_vals)//2:]) / max(len(z2_weekly_vals) - len(z2_weekly_vals)//2, 1)
        trend = {
            "direction": "INCREASING" if avg_second_half > avg_first_half + 5 else "DECREASING" if avg_second_half < avg_first_half - 5 else "STABLE",
            "first_half_avg_min": round(avg_first_half, 1),
            "second_half_avg_min": round(avg_second_half, 1),
            "correlation_r": slope_r,
        }

    # ── Summary ──────────────────────────────────────────────────────────────
    n_weeks = len(weekly_sorted)
    avg_z2_weekly = round(sum(z2_weekly_vals) / n_weeks, 1) if n_weeks > 0 else 0
    weeks_meeting_target = sum(1 for w in weekly_sorted if w["target_met"])

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "weeks_analyzed": n_weeks,
        "total_activities": len(all_activities),
        "zone_2_activities": zone_counts.get("zone_2", 0),
        "avg_weekly_zone_2_min": avg_z2_weekly,
        "weekly_target_min": weekly_target_min,
        "weeks_meeting_target": weeks_meeting_target,
        "target_hit_rate_pct": round(100 * weeks_meeting_target / n_weeks, 0) if n_weeks > 0 else 0,
        "total_zone_2_min": round(zone_totals.get("zone_2", 0), 1),
        "max_hr_used": max_hr,
        "zone_2_hr_range": f"{zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm",
    }

    # ── Alerts + recommendations ─────────────────────────────────────────────
    alerts = []

    if avg_z2_weekly < weekly_target_min * 0.5:
        deficit = round(weekly_target_min - avg_z2_weekly, 0)
        alerts.append(
            f"Zone 2 deficit: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({deficit:.0f} min shortfall). Zone 2 is the foundation of cardiovascular longevity -- "
            "consider adding 2-3 sessions of easy cardio (walking, cycling, easy jogging) per week "
            f"where HR stays in {zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm."
        )
    elif avg_z2_weekly < weekly_target_min:
        deficit = round(weekly_target_min - avg_z2_weekly, 0)
        alerts.append(
            f"Close to target: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({deficit:.0f} min shortfall). One additional Zone 2 session per week would close the gap."
        )

    # Polarization check: too much Zone 3 relative to Zone 2
    z3_total = zone_totals.get("zone_3", 0)
    z2_total = zone_totals.get("zone_2", 0)
    if z3_total > z2_total and z3_total > 30:
        alerts.append(
            f"Training polarization issue: more time in Zone 3 ({round(z3_total, 0)} min) than Zone 2 "
            f"({round(z2_total, 0)} min). Per Seiler's polarized training model, ~80% of endurance "
            "volume should be easy (Zone 1-2) with ~20% hard (Zone 4-5). Zone 3 is 'no man's land' -- "
            "too hard to build aerobic base, too easy for VO2 max gains."
        )

    # Zone 5 volume check
    z5_total = zone_totals.get("zone_5", 0)
    if z5_total > z2_total and z5_total > 20:
        alerts.append(
            f"High-intensity dominant: more Zone 5 ({round(z5_total, 0)} min) than Zone 2 ({round(z2_total, 0)} min). "
            "This pattern correlates with overtraining risk. Prioritize Zone 2 base building."
        )

    # No HR data warning
    no_hr_count = zone_counts.get("no_hr", 0)
    if no_hr_count > len(all_activities) * 0.3:
        alerts.append(
            f"{no_hr_count} of {len(all_activities)} activities ({round(100*no_hr_count/len(all_activities))}%) "
            "lack HR data. Zone classification requires heart rate -- ensure your HR monitor is connected during workouts."
        )

    return {
        "summary": summary,
        "zone_distribution": zone_distribution,
        "zone_hr_thresholds": zone_hr_ranges,
        "weekly_breakdown": weekly_sorted,
        "sport_type_zone2": sport_breakdown,
        "trend": trend,
        "alerts": alerts,
        "methodology": (
            f"Activities classified by average HR as percentage of max HR ({max_hr:.0f} bpm from profile). "
            f"Zone 2 = 60-70% max = {zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm. "
            "Full activity moving time is attributed to the classified zone. This is an approximation -- "
            "average HR doesn't capture intra-activity zone transitions. Activities without HR data are excluded "
            "from zone classification."
        ),
    }



# ── Tool: get_alcohol_sleep_correlation ──────────────────────────────────────

def tool_get_alcohol_sleep_correlation(args):
    """
    Personal alcohol impact analyzer. Correlates MacroFactor alcohol intake with
    same-night Eight Sleep data AND next-day Whoop recovery. Splits days into
    dose buckets (none / light / moderate / heavy), runs Pearson correlations for
    both dose and timing effects, and generates a personal impact assessment.

    One standard drink = ~14g pure alcohol (12oz beer, 5oz wine, 1.5oz spirits).
    Based on Huberman, Attia, and Walker: even moderate alcohol suppresses REM and
    deep sleep, raises resting HR, and impairs next-day HRV recovery.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))

    mf_items = query_source("macrofactor", start_date, end_date)
    es_items = query_source("eightsleep",  start_date, end_date)
    wh_items = query_source("whoop",       start_date, end_date)

    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    # Index by date
    sleep_by_date = {}
    for item in es_items:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    whoop_by_date = {}
    for item in (wh_items or []):
        d = item.get("date")
        if d:
            whoop_by_date[d] = item

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _t2d(t):
        """Time string HH:MM to decimal hours."""
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def _d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _next_date(date_str):
        """Return the next day as YYYY-MM-DD."""
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    # ── One standard drink = 14g pure alcohol ────────────────────────────────
    GRAMS_PER_DRINK = 14.0

    def _classify_dose(alcohol_g):
        if alcohol_g < 1:
            return "none"
        drinks = alcohol_g / GRAMS_PER_DRINK
        if drinks <= 1.0:
            return "light"       # ≤1 drink
        elif drinks <= 2.5:
            return "moderate"    # 1-2.5 drinks
        else:
            return "heavy"       # 3+ drinks

    # ── Extract per-day alcohol + sleep + next-day recovery ──────────────────
    daily_rows = []

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue

        # Same-night sleep
        sleep = sleep_by_date.get(date)
        if not sleep:
            continue

        # Alcohol from day totals
        total_alcohol_g = _sf(mf_item.get("total_alcohol_g")) or 0

        # Alcohol timing from food_log
        food_log = mf_item.get("food_log", [])
        last_drink_time = None
        last_drink_food = None
        drink_entries = 0
        for entry in food_log:
            alc = _sf(entry.get("alcohol_g"))
            if alc and alc > 0:
                td = _t2d(entry.get("time"))
                if td is not None:
                    drink_entries += 1
                    if last_drink_time is None or td > last_drink_time:
                        last_drink_time = td
                        last_drink_food = entry.get("food_name", "Unknown")

        # Sleep metrics (same night)
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))
        es_hrv  = _sf(sleep.get("hrv_avg"))

        if eff is None and score is None and deep is None:
            continue

        # Next-day Whoop recovery
        next_day = _next_date(date)
        whoop_next = whoop_by_date.get(next_day)
        next_recovery  = _sf(whoop_next.get("recovery_score")) if whoop_next else None
        next_hrv       = _sf(whoop_next.get("hrv")) if whoop_next else None
        next_rhr       = _sf(whoop_next.get("resting_heart_rate")) if whoop_next else None

        drinks = round(total_alcohol_g / GRAMS_PER_DRINK, 1) if total_alcohol_g > 0 else 0
        bucket = _classify_dose(total_alcohol_g)

        daily_rows.append({
            "date": date,
            "total_alcohol_g": round(total_alcohol_g, 1),
            "standard_drinks": drinks,
            "last_drink_time": last_drink_time,
            "last_drink_time_hm": _d2hm(last_drink_time),
            "last_drink_food": last_drink_food,
            "drink_entries": drink_entries,
            "bucket": bucket,
            # Same-night sleep
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
            "es_hrv": es_hrv,
            # Next-day recovery
            "next_recovery_score": next_recovery,
            "next_hrv": next_hrv,
            "next_rhr": next_rhr,
        })

    if len(daily_rows) < 5:
        return {
            "error": f"Only {len(daily_rows)} days with both nutrition and sleep data. Need at least 5.",
            "hint": "Ensure MacroFactor food logging and Eight Sleep data overlap. Re-check after 2+ weeks of consistent logging.",
            "start_date": start_date, "end_date": end_date,
        }

    # ── Metric definitions ───────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %",  "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",        "higher_is_better"),
        ("rem_pct",              "REM %",               "higher_is_better"),
        ("sleep_score",          "Sleep Score",         "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",      "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency", "lower_is_better"),
        ("es_hrv",               "Sleep HRV",           "higher_is_better"),
    ]

    RECOVERY_METRICS = [
        ("next_recovery_score",  "Next-Day Recovery",   "higher_is_better"),
        ("next_hrv",             "Next-Day HRV",        "higher_is_better"),
        ("next_rhr",             "Next-Day RHR",        "lower_is_better"),
    ]

    ALL_METRICS = SLEEP_METRICS + RECOVERY_METRICS

    # ── Bucket analysis ──────────────────────────────────────────────────────
    BUCKET_ORDER = ["none", "light", "moderate", "heavy"]
    BUCKET_LABELS = {
        "none":     "No Alcohol",
        "light":    "Light (≤1 drink / ≤14g)",
        "moderate": "Moderate (1-2.5 drinks / 14-35g)",
        "heavy":    "Heavy (3+ drinks / 35g+)",
    }

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_alcohol_g": _avg([r["total_alcohol_g"] for r in b_rows if r["total_alcohol_g"] > 0]),
            "avg_drinks": _avg([r["standard_drinks"] for r in b_rows if r["standard_drinks"] > 0]),
            "metrics": {},
        }
        for field, label, _ in ALL_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Dose correlations (total alcohol g vs metrics) ───────────────────────
    dose_correlations = {}
    for field, label, direction in ALL_METRICS:
        xs = [r["total_alcohol_g"] for r in daily_rows if r[field] is not None]
        ys = [r[field]             for r in daily_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            dose_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
            }

    # ── Timing correlations (last drink time vs sleep, drinking days only) ───
    timing_correlations = {}
    timed_rows = [r for r in daily_rows if r["last_drink_time"] is not None]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_drink_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]             for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later drinking {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Drinking vs sober comparison ─────────────────────────────────────────
    drinking_days = [r for r in daily_rows if r["bucket"] != "none"]
    sober_days    = [r for r in daily_rows if r["bucket"] == "none"]

    drinking_vs_sober = {}
    if drinking_days and sober_days:
        for field, label, direction in ALL_METRICS:
            dr_vals = [r[field] for r in drinking_days if r[field] is not None]
            so_vals = [r[field] for r in sober_days if r[field] is not None]
            if dr_vals and so_vals:
                dr_avg = round(sum(dr_vals) / len(dr_vals), 2)
                so_avg = round(sum(so_vals) / len(so_vals), 2)
                delta = round(dr_avg - so_avg, 2)
                if direction == "lower_is_better":
                    verdict = "BETTER" if delta < -1 else "WORSE" if delta > 1 else "SIMILAR"
                else:
                    verdict = "BETTER" if delta > 1 else "WORSE" if delta < -1 else "SIMILAR"
                drinking_vs_sober[field] = {
                    "label": label,
                    "drinking_avg": dr_avg,
                    "sober_avg": so_avg,
                    "delta": delta,
                    "verdict": verdict,
                    "drinking_n": len(dr_vals),
                    "sober_n": len(so_vals),
                }

    # ── Personal impact assessment ───────────────────────────────────────────
    assessment = None
    severity = None

    # Compare sober vs drinking bucket metrics
    if "none" in bucket_data and len(bucket_data) > 1:
        sober_eff = None
        if "sleep_efficiency_pct" in bucket_data["none"]["metrics"]:
            sober_eff = bucket_data["none"]["metrics"]["sleep_efficiency_pct"]["avg"]

        worst_bucket = None
        worst_drop = 0
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                if sober_eff is not None:
                    drop = sober_eff - b_eff
                    if drop > worst_drop:
                        worst_drop = drop
                        worst_bucket = b

        # Check REM impact (alcohol's most documented effect)
        sober_rem = None
        if "rem_pct" in bucket_data["none"]["metrics"]:
            sober_rem = bucket_data["none"]["metrics"]["rem_pct"]["avg"]

        rem_drops = {}
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "rem_pct" in bucket_data[b]["metrics"] and sober_rem:
                rem_drops[b] = round(sober_rem - bucket_data[b]["metrics"]["rem_pct"]["avg"], 1)

        # Check next-day recovery impact
        sober_rec = None
        rec_drops = {}
        if "next_recovery_score" in bucket_data["none"]["metrics"]:
            sober_rec = bucket_data["none"]["metrics"]["next_recovery_score"]["avg"]
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "next_recovery_score" in bucket_data[b]["metrics"] and sober_rec:
                rec_drops[b] = round(sober_rec - bucket_data[b]["metrics"]["next_recovery_score"]["avg"], 1)

        # Build assessment
        impacts = []
        if worst_drop >= 5:
            impacts.append(f"sleep efficiency drops {worst_drop:.1f} pts with {worst_bucket} drinking")
            severity = "HIGH"
        elif worst_drop >= 2:
            impacts.append(f"sleep efficiency drops {worst_drop:.1f} pts with {worst_bucket} drinking")
            severity = "MODERATE"

        for b, drop in rem_drops.items():
            if drop >= 3:
                impacts.append(f"REM drops {drop} pts with {b} drinking")
                if severity != "HIGH":
                    severity = "HIGH" if drop >= 5 else "MODERATE"

        for b, drop in rec_drops.items():
            if drop >= 5:
                impacts.append(f"next-day recovery drops {drop} pts with {b} drinking")
                severity = "HIGH"

        if impacts:
            assessment = "Alcohol is measurably affecting your recovery: " + "; ".join(impacts) + "."
        else:
            assessment = (
                "Your data does not yet show a strong alcohol impact on sleep or recovery. "
                "This could mean you metabolize alcohol well, drink infrequently, or there isn't enough data yet. "
                "Continue logging and re-check after 30+ days."
            )
            severity = "LOW"
    else:
        assessment = (
            "Not enough data to compare drinking vs sober nights. "
            "Continue logging food intake in MacroFactor for at least 2-3 weeks."
        )
        severity = "INSUFFICIENT_DATA"

    # ── Summary + alerts ─────────────────────────────────────────────────────
    drinking_count = len(drinking_days)
    sober_count = len(sober_days)
    all_drink_amounts = [r["total_alcohol_g"] for r in drinking_days if r["total_alcohol_g"] > 0]

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "drinking_days": drinking_count,
        "sober_days": sober_count,
        "drinking_frequency_pct": round(100 * drinking_count / len(daily_rows), 0) if daily_rows else 0,
        "avg_alcohol_g_on_drinking_days": _avg(all_drink_amounts),
        "avg_drinks_on_drinking_days": _avg([g / GRAMS_PER_DRINK for g in all_drink_amounts]) if all_drink_amounts else None,
        "avg_last_drink_time": _d2hm(
            sum(r["last_drink_time"] for r in timed_rows) / len(timed_rows)
        ) if timed_rows else None,
    }

    alerts = []

    # High frequency alert
    if summary["drinking_frequency_pct"] and summary["drinking_frequency_pct"] > 50:
        alerts.append(
            f"Alcohol consumed on {summary['drinking_frequency_pct']:.0f}% of days. "
            "Huberman and Attia recommend at minimum 3-4 alcohol-free days per week "
            "for liver recovery and hormonal regulation."
        )

    # REM suppression alert
    rem_corr = dose_correlations.get("rem_pct")
    if rem_corr and rem_corr["impact"] == "HARMFUL" and abs(rem_corr["pearson_r"]) > 0.2:
        alerts.append(
            f"Alcohol dose correlates with REM suppression (r={rem_corr['pearson_r']}). "
            "REM sleep is critical for emotional regulation, memory consolidation, and creativity. "
            "Even 1-2 drinks can reduce REM by 20-30% (Walker, 'Why We Sleep')."
        )

    # Deep sleep pseudo-enhancement warning
    deep_corr = dose_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "BENEFICIAL":
        alerts.append(
            "Alcohol appears to increase deep sleep % -- but this is misleading. "
            "Alcohol-induced 'deep sleep' is actually sedation, not restorative SWS. "
            "It lacks the memory-consolidating neural oscillations of natural deep sleep."
        )

    # Next-day HRV impact
    hrv_corr = dose_correlations.get("next_hrv")
    if hrv_corr and hrv_corr["impact"] == "HARMFUL" and abs(hrv_corr["pearson_r"]) > 0.2:
        alerts.append(
            f"Higher alcohol intake correlates with lower next-day HRV (r={hrv_corr['pearson_r']}). "
            "Alcohol impairs parasympathetic recovery -- your autonomic nervous system is still stressed "
            "the morning after, even if you feel fine."
        )

    # Late drinking alert
    late_drinks = [r for r in timed_rows if r["last_drink_time"] and r["last_drink_time"] >= 21]
    if late_drinks:
        pct = round(100 * len(late_drinks) / len(timed_rows), 0) if timed_rows else 0
        alerts.append(
            f"Last drink after 9 PM on {len(late_drinks)} drinking days ({pct:.0f}%). "
            "Alcohol takes ~1 hour per standard drink to metabolize. Late drinking means "
            "active alcohol metabolism during early sleep cycles when deep sleep should peak."
        )

    return {
        "summary": summary,
        "assessment": {
            "text": assessment,
            "severity": severity,
        },
        "bucket_comparison": bucket_data,
        "drinking_vs_sober": drinking_vs_sober,
        "dose_correlations": dose_correlations,
        "timing_correlations": timing_correlations,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "alcohol_g": r["total_alcohol_g"],
                "drinks": r["standard_drinks"],
                "last_drink": r["last_drink_time_hm"],
                "last_drink_food": r["last_drink_food"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
                "next_recovery": r["next_recovery_score"],
                "next_hrv": r["next_hrv"],
            }
            for r in daily_rows
        ],
    }

# ── Tool: get_habit_adherence ─────────────────────────────────────────────────

def tool_get_habit_adherence(args):
    """
    Per-habit and per-group completion rates over any date range.
    Returns habits ranked worst-to-best by adherence.
    """
    start_date = args.get("start_date", "2020-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    group_filter = (args.get("group") or "").strip()

    items = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if not series:
        return {"error": "No chronicling data found for the requested window."}

    n_days = len(series)
    habit_counts: dict[str, int]   = {}  # name -> days completed
    habit_days:   dict[str, int]   = {}  # name -> days tracked (possible)
    group_completed: dict[str, list] = {}
    group_possible:  dict[str, list] = {}

    for row in series:
        for habit, val in row["habits"].items():
            habit_counts[habit] = habit_counts.get(habit, 0) + int(val)
            habit_days[habit]   = habit_days.get(habit, 0) + 1
        for grp, gdata in row["by_group"].items():
            if group_filter and grp.lower() != group_filter.lower():
                continue
            group_completed.setdefault(grp, []).append(gdata.get("completed", 0))
            group_possible.setdefault(grp, []).append(gdata.get("possible", 0))

    # Per-habit table
    habit_rows = []
    for habit in sorted(habit_counts):
        days_tracked = habit_days[habit]
        days_done    = habit_counts[habit]
        pct = round(days_done / days_tracked, 4) if days_tracked else 0
        habit_rows.append({
            "habit":        habit,
            "days_done":    days_done,
            "days_tracked": days_tracked,
            "completion_pct": pct,
        })
    habit_rows.sort(key=lambda r: r["completion_pct"])

    # Per-group table
    group_rows = []
    for grp in P40_GROUPS:
        if grp not in group_completed:
            continue
        total_comp = sum(group_completed[grp])
        total_poss = sum(group_possible[grp])
        pct = round(total_comp / total_poss, 4) if total_poss else 0
        group_rows.append({
            "group":          grp,
            "total_completed": total_comp,
            "total_possible":  total_poss,
            "completion_pct":  pct,
        })
    group_rows.sort(key=lambda r: r["completion_pct"])

    # Overall
    all_comp = sum(row["total_completed"] for row in series)
    all_poss = sum(row["total_possible"]  for row in series)

    return {
        "start_date":     start_date,
        "end_date":       end_date,
        "days_analyzed":  n_days,
        "overall_completion_pct": round(all_comp / all_poss, 4) if all_poss else 0,
        "overall_completed": all_comp,
        "overall_possible":  all_poss,
        "by_group":       group_rows,
        "by_habit":       habit_rows,
        "note":           "Habits ranked worst-to-best. Pass group= to filter by P40 pillar.",
    }


# ── Tool: get_habit_streaks ───────────────────────────────────────────────────

def tool_get_habit_streaks(args):
    """
    Current streak, longest streak, and days since last completion for each habit.
    Returns sorted by current_streak descending.
    """
    start_date   = args.get("start_date", "2020-01-01")
    end_date     = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    habit_filter = (args.get("habit_name") or "").strip().lower()

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if not series:
        return {"error": "No chronicling data found."}

    # Collect all habit names
    all_habits = set()
    for row in series:
        all_habits |= set(row["habits"].keys())
    if habit_filter:
        all_habits = {h for h in all_habits if habit_filter in h.lower()}

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    def streak_stats(habit):
        done_dates = sorted(
            row["date"] for row in series if row["habits"].get(habit)
        )
        if not done_dates:
            return {"habit": habit, "current_streak": 0, "longest_streak": 0,
                    "days_since_last": None, "last_done_date": None, "total_completions": 0}

        # longest streak (consecutive days)
        longest = cur = 1
        for i in range(1, len(done_dates)):
            d1 = datetime.strptime(done_dates[i-1], "%Y-%m-%d")
            d2 = datetime.strptime(done_dates[i],   "%Y-%m-%d")
            if (d2 - d1).days == 1:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 1

        # current streak (working backwards from most recent done date)
        cur_streak = 1
        for i in range(len(done_dates)-1, 0, -1):
            d1 = datetime.strptime(done_dates[i-1], "%Y-%m-%d")
            d2 = datetime.strptime(done_dates[i],   "%Y-%m-%d")
            if (d2 - d1).days == 1:
                cur_streak += 1
            else:
                break
        # If last done wasn't yesterday or today, streak is 0
        last_dt = datetime.strptime(done_dates[-1], "%Y-%m-%d")
        gap_to_now = (end_dt - last_dt).days
        if gap_to_now > 1:
            cur_streak = 0

        return {
            "habit":             habit,
            "current_streak":    cur_streak,
            "longest_streak":    longest,
            "days_since_last":   gap_to_now,
            "last_done_date":    done_dates[-1],
            "total_completions": len(done_dates),
        }

    results = [streak_stats(h) for h in sorted(all_habits)]
    results.sort(key=lambda r: (-r["current_streak"], -r["longest_streak"]))

    active = [r for r in results if r["current_streak"] > 0]
    broken = [r for r in results if r["current_streak"] == 0]
    broken.sort(key=lambda r: (r["days_since_last"] or 9999))

    return {
        "start_date":      start_date,
        "end_date":        end_date,
        "active_streaks":  active,
        "broken_streaks":  broken,
        "note":            "current_streak=0 means not completed today or yesterday. days_since_last is days ago.",
    }


# ── Tool: get_keystone_habits ─────────────────────────────────────────────────

def tool_get_keystone_habits(args):
    """
    Identifies which individual habits have the highest Pearson correlation
    with overall daily completion_pct — the behavioral levers that lift everything.
    """
    start_date = args.get("start_date", "2020-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    top_n      = int(args.get("top_n", 15))

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if len(series) < 10:
        return {"error": f"Need at least 10 days of data (found {len(series)})."}

    overall_scores = [row["completion_pct"] for row in series]

    all_habits = set()
    for row in series:
        all_habits |= set(row["habits"].keys())

    correlations = []
    for habit in sorted(all_habits):
        habit_vals = [float(row["habits"].get(habit, 0)) for row in series]
        # Skip habits rarely tracked (less than 20% presence)
        done_count = sum(habit_vals)
        if done_count < max(3, len(series) * 0.05):
            continue
        r = pearson_r(habit_vals, overall_scores)
        if r is None:
            continue
        completion_rate = round(done_count / len(series), 3)
        correlations.append({
            "habit":           habit,
            "pearson_r":       r,
            "r_squared":       round(r**2, 3),
            "completion_rate": completion_rate,
            "interpretation":  (
                "strong lever" if r >= 0.5 else
                "moderate lever" if r >= 0.3 else
                "weak lever" if r >= 0.15 else
                "negligible"
            ),
            "n_days_done": int(done_count),
        })

    correlations.sort(key=lambda x: -x["pearson_r"])

    return {
        "start_date":   start_date,
        "end_date":     end_date,
        "days_analyzed": len(series),
        "top_n":        top_n,
        "keystone_habits": correlations[:top_n],
        "bottom_habits":   [h for h in reversed(correlations) if h["pearson_r"] < 0][:5],
        "coaching_note": (
            "Keystone habits are the behavioral levers: completing them on a given day predicts "
            "a higher overall P40 score. Focus willpower here first for cascade effects. "
            "r > 0.4 is practically meaningful."
        ),
    }


# ── Tool: get_habit_health_correlations ──────────────────────────────────────

def tool_get_habit_health_correlations(args):
    """
    Correlate individual habit completion (0/1) or group score with a biometric outcome.
    Returns Pearson r, and mean biometric on days habit was done vs not done.
    Supports optional lag (e.g. does cold shower today predict HRV tomorrow?).
    """
    habit_name    = (args.get("habit_name") or "").strip()
    group_name    = (args.get("group_name") or "").strip()
    health_source = args.get("health_source")        # e.g. "whoop"
    health_field  = args.get("health_field")         # e.g. "hrv"
    start_date    = args.get("start_date", "2020-01-01")
    end_date      = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    lag_days      = int(args.get("lag_days", 0))

    if not (habit_name or group_name):
        return {"error": "Provide habit_name or group_name."}
    if not health_source or not health_field:
        return {"error": "health_source and health_field are required (e.g. health_source='whoop', health_field='hrv')."}

    # Build date range that covers lag
    lag_end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=abs(lag_days))
    lag_end    = lag_end_dt.strftime("%Y-%m-%d")

    habit_items  = query_chronicling(start_date, lag_end)
    health_items = query_source(health_source, start_date, lag_end)

    habit_series  = _habit_series(habit_items)
    health_by_date = {}
    resolved = resolve_field(health_source, health_field)
    for item in health_items:
        d = item.get("date")
        v = item.get(resolved)
        if d and v is not None:
            health_by_date[d] = float(v)

    pairs_done     = []
    pairs_not_done = []
    xs = []   # habit value (0/1 or group pct)
    ys = []   # health value (shifted by lag)

    for row in habit_series:
        date_str = row["date"]
        if date_str > end_date:
            continue
        if lag_days > 0:
            shifted = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
        else:
            shifted = date_str
        health_val = health_by_date.get(shifted)
        if health_val is None:
            continue

        if habit_name:
            habit_val = float(row["habits"].get(habit_name, 0))
        else:  # group
            grp_data = row["by_group"].get(group_name)
            habit_val = grp_data["pct"] if grp_data else 0.0

        xs.append(habit_val)
        ys.append(health_val)
        if habit_val >= 0.5:
            pairs_done.append(health_val)
        else:
            pairs_not_done.append(health_val)

    if len(xs) < 10:
        return {"error": f"Insufficient paired data points ({len(xs)}). Try wider date range."}

    r = pearson_r(xs, ys)
    mean_done     = round(sum(pairs_done)     / len(pairs_done),     2) if pairs_done     else None
    mean_not_done = round(sum(pairs_not_done) / len(pairs_not_done), 2) if pairs_not_done else None
    delta = round(mean_done - mean_not_done, 2) if (mean_done is not None and mean_not_done is not None) else None

    direction = "habit done → higher {f}" if delta and delta > 0 else "habit done → lower {f}"

    return {
        "habit_name":     habit_name or None,
        "group_name":     group_name or None,
        "health_source":  health_source,
        "health_field":   resolved,
        "lag_days":       lag_days,
        "lag_note":       f"Does {habit_name or group_name} today predict {resolved} in {lag_days} day(s)?" if lag_days else "Same-day relationship.",
        "start_date":     start_date,
        "end_date":       end_date,
        "n_paired_days":  len(xs),
        "pearson_r":      r,
        "r_squared":      round(r**2, 3) if r else None,
        "interpretation": (
            "strong correlation" if r and abs(r) >= 0.5 else
            "moderate correlation" if r and abs(r) >= 0.3 else
            "weak correlation" if r and abs(r) >= 0.15 else
            "negligible correlation"
        ) if r is not None else "insufficient variance",
        "mean_health_when_done":     mean_done,
        "mean_health_when_not_done": mean_not_done,
        "delta":          delta,
        "n_days_done":    len(pairs_done),
        "n_days_not_done":len(pairs_not_done),
        "coaching_note":  "r > 0.3 is meaningful. Check both r and the mean difference for practical significance.",
    }


# ── Tool: get_group_trends ────────────────────────────────────────────────────

def tool_get_group_trends(args):
    """
    Weekly P40 group scores over time.
    Returns week-by-week completion % per group, with trend direction across the window.
    """
    start_date    = args.get("start_date", "2020-01-01")
    end_date      = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    groups_filter = args.get("groups")  # optional list

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if not series:
        return {"error": "No chronicling data found."}

    # Bucket into ISO weeks
    weeks: dict[str, dict[str, list]] = {}  # week_key -> {group -> [pcts]}
    for row in series:
        date_str = row["date"]
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            iso = dt.isocalendar()
            wk  = f"{iso[0]}-W{iso[1]:02d}"
        except ValueError:
            continue
        weeks.setdefault(wk, {"overall": [], "dates": []})
        weeks[wk]["overall"].append(row["completion_pct"])
        weeks[wk]["dates"].append(date_str)
        for grp, gdata in row["by_group"].items():
            if groups_filter and grp not in groups_filter:
                continue
            weeks[wk].setdefault(grp, []).append(gdata.get("pct", 0))

    week_rows = []
    for wk in sorted(weeks.keys()):
        wdata = weeks[wk]
        row = {
            "week":       wk,
            "week_start": min(wdata["dates"]) if wdata["dates"] else "",
            "week_end":   max(wdata["dates"]) if wdata["dates"] else "",
            "days_data":  len(wdata["overall"]),
            "overall_pct": round(sum(wdata["overall"]) / len(wdata["overall"]), 4) if wdata["overall"] else None,
        }
        for grp in P40_GROUPS:
            if grp in wdata and wdata[grp]:
                row[f"{grp}_pct"] = round(sum(wdata[grp]) / len(wdata[grp]), 4)
        week_rows.append(row)

    # Trend direction per group (first half vs second half avg)
    trends = {}
    n = len(week_rows)
    if n >= 4:
        half = n // 2
        for grp in ["overall"] + P40_GROUPS:
            key = f"{grp}_pct" if grp != "overall" else "overall_pct"
            early_vals = [r[key] for r in week_rows[:half]  if r.get(key) is not None]
            late_vals  = [r[key] for r in week_rows[half:]  if r.get(key) is not None]
            if early_vals and late_vals:
                early_avg = sum(early_vals) / len(early_vals)
                late_avg  = sum(late_vals)  / len(late_vals)
                delta = round(late_avg - early_avg, 4)
                trends[grp] = {
                    "early_avg": round(early_avg, 4),
                    "late_avg":  round(late_avg, 4),
                    "delta":     delta,
                    "direction": "improving" if delta > 0.02 else ("declining" if delta < -0.02 else "stable"),
                }

    return {
        "start_date":   start_date,
        "end_date":     end_date,
        "weeks_analyzed": len(week_rows),
        "weekly_scores": week_rows,
        "trend_summary": trends,
        "note":          "Completion % shown as 0–1. Filter with groups= list to focus on specific pillars.",
    }


# ── Tool: compare_habit_periods ───────────────────────────────────────────────

def tool_compare_habit_periods(args):
    """
    Side-by-side adherence comparison of two date ranges.
    Returns per-habit and per-group delta and direction.
    """
    pa_start = args.get("period_a_start")
    pa_end   = args.get("period_a_end")
    pb_start = args.get("period_b_start")
    pb_end   = args.get("period_b_end")
    pa_label = args.get("period_a_label", "Period A")
    pb_label = args.get("period_b_label", "Period B")

    if not all([pa_start, pa_end, pb_start, pb_end]):
        return {"error": "period_a_start, period_a_end, period_b_start, period_b_end are all required."}

    def period_stats(start, end):
        items  = query_chronicling(start, end)
        series = _habit_series(items)
        habit_rates: dict[str, float] = {}
        group_rates: dict[str, float] = {}
        n = len(series)
        if n == 0:
            return habit_rates, group_rates, n
        counts: dict[str, int] = {}
        for row in series:
            for habit, val in row["habits"].items():
                counts[habit] = counts.get(habit, 0) + int(val)
        for habit, done in counts.items():
            habit_rates[habit] = round(done / n, 4)
        grp_comp: dict[str, list] = {}
        grp_poss: dict[str, list] = {}
        for row in series:
            for grp, gdata in row["by_group"].items():
                grp_comp.setdefault(grp, []).append(gdata.get("completed", 0))
                grp_poss.setdefault(grp, []).append(gdata.get("possible", 0))
        for grp in P40_GROUPS:
            if grp in grp_comp and sum(grp_poss[grp]):
                group_rates[grp] = round(sum(grp_comp[grp]) / sum(grp_poss[grp]), 4)
        return habit_rates, group_rates, n

    habits_a, groups_a, days_a = period_stats(pa_start, pa_end)
    habits_b, groups_b, days_b = period_stats(pb_start, pb_end)

    all_habits = sorted(set(habits_a) | set(habits_b))
    habit_comparison = []
    for habit in all_habits:
        va = habits_a.get(habit)
        vb = habits_b.get(habit)
        delta = round(vb - va, 4) if (va is not None and vb is not None) else None
        habit_comparison.append({
            "habit":          habit,
            pa_label:         va,
            pb_label:         vb,
            "delta":          delta,
            "direction":      "improved" if delta and delta > 0.02 else ("declined" if delta and delta < -0.02 else "stable"),
        })
    habit_comparison.sort(key=lambda r: r.get("delta") or 0, reverse=True)

    group_comparison = []
    for grp in P40_GROUPS:
        va = groups_a.get(grp)
        vb = groups_b.get(grp)
        delta = round(vb - va, 4) if (va is not None and vb is not None) else None
        group_comparison.append({
            "group":     grp,
            pa_label:    va,
            pb_label:    vb,
            "delta":     delta,
            "direction": "improved" if delta and delta > 0.02 else ("declined" if delta and delta < -0.02 else "stable"),
        })
    group_comparison.sort(key=lambda r: r.get("delta") or 0, reverse=True)

    overall_a = sum(habits_a.values()) / len(habits_a) if habits_a else None
    overall_b = sum(habits_b.values()) / len(habits_b) if habits_b else None

    return {
        "period_a": {"label": pa_label, "start": pa_start, "end": pa_end, "days": days_a},
        "period_b": {"label": pb_label, "start": pb_start, "end": pb_end, "days": days_b},
        "overall": {
            pa_label: round(overall_a, 4) if overall_a else None,
            pb_label: round(overall_b, 4) if overall_b else None,
            "delta":  round(overall_b - overall_a, 4) if (overall_a and overall_b) else None,
        },
        "by_group": group_comparison,
        "by_habit": habit_comparison,
        "most_improved":  [h for h in habit_comparison if h.get("direction") == "improved"][:5],
        "most_declined":  [h for h in reversed(habit_comparison) if h.get("direction") == "declined"][:5],
    }


# ── Tool: get_habit_stacks ────────────────────────────────────────────────────

def tool_get_habit_stacks(args):
    """
    Co-occurrence analysis: which habits cluster together.
    Uses lift = P(A and B) / (P(A) * P(B)) to surface genuine co-occurrence
    beyond base rates. Returns top N habit pairs by lift.
    Also returns natural 'stacks' — groups of 3+ habits that co-occur on ≥60% of days.
    """
    start_date = args.get("start_date", "2020-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    top_n      = int(args.get("top_n", 20))
    min_pct    = float(args.get("min_pct", 0.1))  # minimum base rate for either habit

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if len(series) < 7:
        return {"error": "Need at least 7 days of data."}

    n = len(series)
    # Build presence rates
    habits = sorted({h for row in series for h in row["habits"]})
    p = {h: sum(row["habits"].get(h, 0) for row in series) / n for h in habits}
    # Filter out habits with very low base rates
    habits = [h for h in habits if p[h] >= min_pct]

    pair_counts: dict[tuple, int] = {}
    for row in series:
        done = [h for h in habits if row["habits"].get(h, 0)]
        for i in range(len(done)):
            for j in range(i+1, len(done)):
                key = (done[i], done[j])
                pair_counts[key] = pair_counts.get(key, 0) + 1

    pairs = []
    for (ha, hb), cnt in pair_counts.items():
        p_ab  = cnt / n
        lift  = p_ab / (p[ha] * p[hb]) if (p[ha] * p[hb]) > 0 else 0
        pairs.append({
            "habit_a":        ha,
            "habit_b":        hb,
            "co_occurrence_pct": round(p_ab, 4),
            "habit_a_base_rate": round(p[ha], 4),
            "habit_b_base_rate": round(p[hb], 4),
            "lift":           round(lift, 3),
            "n_days_together": cnt,
            "interpretation":  (
                "strongly cluster" if lift >= 2.0 else
                "tend to co-occur" if lift >= 1.5 else
                "slightly co-occur" if lift >= 1.2 else
                "independent"
            ),
        })
    pairs.sort(key=lambda r: -r["lift"])

    # Stack detection: find habits that all co-occur on >= threshold fraction of days
    threshold = 0.60
    stack_habits = [h for h in habits if p[h] >= 0.3]  # only habits done ≥30% of time
    stacks = []
    # Greedy: check all triples
    for i in range(len(stack_habits)):
        for j in range(i+1, len(stack_habits)):
            for k in range(j+1, len(stack_habits)):
                ha, hb, hc = stack_habits[i], stack_habits[j], stack_habits[k]
                co = sum(
                    1 for row in series
                    if row["habits"].get(ha) and row["habits"].get(hb) and row["habits"].get(hc)
                ) / n
                if co >= threshold:
                    stacks.append({
                        "stack": [ha, hb, hc],
                        "co_occurrence_pct": round(co, 4),
                        "type":  "routine stack",
                    })
    stacks.sort(key=lambda r: -r["co_occurrence_pct"])

    return {
        "start_date":    start_date,
        "end_date":      end_date,
        "days_analyzed": n,
        "top_pairs_by_lift": pairs[:top_n],
        "natural_stacks":    stacks[:20],
        "coaching_note": (
            "Lift > 1.5 means the habits genuinely cluster beyond chance. "
            "Natural stacks are habits you already do together 60%+ of the time — "
            "these are your existing routines."
        ),
    }


# ── Tool: get_habit_dashboard ─────────────────────────────────────────────────

def tool_get_habit_dashboard(args):
    """
    Current-state P40 briefing. Returns:
    - Today's and yesterday's completion status (latest available)
    - 7-day rolling group scores vs 30-day baseline
    - Current streaks for top habits
    - Best and worst groups this week
    - Trend vs previous 7-day window
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start   = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d14_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    d30_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")

    items_30d = query_chronicling(d30_start, end_date)
    series_30 = _habit_series(items_30d)

    if not series_30:
        return {"error": "No chronicling data found."}

    # Latest day
    latest = series_30[-1]
    today_status = {
        "date":             latest["date"],
        "total_completed":  latest["total_completed"],
        "total_possible":   latest["total_possible"],
        "completion_pct":   latest["completion_pct"],
        "status":           "green" if latest["completion_pct"] >= 0.70 else ("yellow" if latest["completion_pct"] >= 0.50 else "red"),
        "by_group":         {grp: round(gdata.get("pct", 0), 4) for grp, gdata in latest["by_group"].items()},
    }

    # 7-day stats
    series_7 = [r for r in series_30 if r["date"] >= d7_start]
    series_prev_7 = [r for r in series_30 if d14_start <= r["date"] < d7_start]

    def group_avgs(s):
        grp_comp: dict[str, list] = {}
        grp_poss: dict[str, list] = {}
        for row in s:
            for grp, gdata in row["by_group"].items():
                grp_comp.setdefault(grp, []).append(gdata.get("completed", 0))
                grp_poss.setdefault(grp, []).append(gdata.get("possible", 0))
        return {
            grp: round(sum(grp_comp[grp]) / sum(grp_poss[grp]), 4)
            for grp in P40_GROUPS if grp in grp_comp and sum(grp_poss.get(grp, [0]))
        }

    avgs_7    = group_avgs(series_7)
    avgs_prev = group_avgs(series_prev_7)
    avgs_30   = group_avgs(series_30)

    overall_7 = round(sum(r["completion_pct"] for r in series_7) / len(series_7), 4) if series_7 else None
    overall_30 = round(sum(r["completion_pct"] for r in series_30) / len(series_30), 4) if series_30 else None

    group_trend = {}
    for grp in P40_GROUPS:
        if grp in avgs_7:
            delta = round(avgs_7[grp] - avgs_prev.get(grp, avgs_7[grp]), 4)
            group_trend[grp] = {
                "7d_avg":  avgs_7[grp],
                "30d_avg": avgs_30.get(grp),
                "delta_vs_prev_7d": delta,
                "direction": "improving" if delta > 0.02 else ("declining" if delta < -0.02 else "stable"),
            }

    sorted_groups = sorted(group_trend.items(), key=lambda x: x[1]["7d_avg"], reverse=True)
    best_groups  = [grp for grp, _ in sorted_groups[:3]]
    worst_groups = [grp for grp, _ in sorted_groups[-3:]]

    # Streak highlights: top 5 habits by current streak
    streak_result = tool_get_habit_streaks({"start_date": d30_start, "end_date": end_date})
    top_streaks = streak_result.get("active_streaks", [])[:5]

    alerts = []
    if latest["completion_pct"] < 0.40:
        alerts.append(f"⚠️ Latest day only {round(latest['completion_pct']*100)}% — below 40% threshold.")
    for grp, data in group_trend.items():
        if data["direction"] == "declining" and data["7d_avg"] < 0.40:
            alerts.append(f"⚠️ {grp} group declining — 7d avg {round(data['7d_avg']*100)}%.")

    return {
        "as_of":         end_date,
        "today":         today_status,
        "rolling_7d": {
            "overall_pct":  overall_7,
            "baseline_30d": overall_30,
            "delta_vs_30d": round(overall_7 - overall_30, 4) if (overall_7 and overall_30) else None,
            "days_data":    len(series_7),
        },
        "group_trends":  group_trend,
        "best_groups":   best_groups,
        "worst_groups":  worst_groups,
        "top_streaks":   top_streaks,
        "alerts":        alerts if alerts else ["✅ P40 system nominal."],
        "alert_count":   len(alerts),
    }


def tool_get_garmin_summary(args):
    """
    Garmin daily biometrics over a date range.
    Returns Body Battery, physiological stress, overnight HRV, RHR, and respiration
    from the Garmin Epix. These are Garmin-native metrics not available from other sources.

    Key metrics:
      body_battery_end  — Energy reserve at end of day (0-100). Garmin's flagship metric.
                          <25 = depleted; 25-50 = low; 50-75 = moderate; >75 = well-recovered.
      body_battery_high — Peak energy reserve for the day (how recovered you started).
      avg_stress        — Physiological stress (HRV-derived, 0-100). Objective, not subjective.
                          <25 = restful; 25-50 = low stress; 50-75 = medium; >75 = high stress.
      hrv_last_night    — Overnight average HRV from Garmin (ms). Cross-check with Whoop HRV.
      hrv_status        — Garmin's qualitative HRV status: POOR / FAIR / GOOD / EXCELLENT.
      resting_heart_rate— Daily RHR from Garmin optical sensor (cross-check with Whoop).
      avg_respiration   — Waking average respiration rate (breaths/min).
      sleep_respiration — Sleep average respiration (cross-check with Eight Sleep).
    """
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"))
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    items = query_source("garmin", start_date, end_date)
    if not items:
        return {"error": f"No Garmin data found for {start_date} to {end_date}. "
                         "Check that garmin-data-ingestion Lambda is running and has ingested data."}

    items_sorted = sorted(items, key=lambda x: x.get("date", ""))

    # Build per-day rows
    rows = []
    for item in items_sorted:
        row = {"date": item.get("date")}
        for field in ["body_battery_end", "body_battery_high", "body_battery_low",
                      "avg_stress", "max_stress", "stress_qualifier",
                      "hrv_last_night", "hrv_status", "hrv_5min_high",
                      "resting_heart_rate", "avg_respiration", "sleep_respiration", "steps"]:
            val = item.get(field)
            if val is not None:
                row[field] = float(val) if isinstance(val, Decimal) else val
        rows.append(row)

    # Compute period averages for numeric fields
    numeric_fields = ["body_battery_end", "body_battery_high", "avg_stress",
                      "hrv_last_night", "resting_heart_rate", "avg_respiration", "sleep_respiration"]
    averages = {}
    for field in numeric_fields:
        vals = [float(r[field]) for r in rows if field in r]
        if vals:
            averages[field] = round(sum(vals) / len(vals), 1)

    # HRV status breakdown
    hrv_statuses = [r["hrv_status"] for r in rows if "hrv_status" in r]
    status_counts = {}
    for s in hrv_statuses:
        status_counts[s] = status_counts.get(s, 0) + 1

    # Body Battery interpretation
    avg_bb = averages.get("body_battery_end")
    bb_interpretation = None
    if avg_bb is not None:
        if avg_bb >= 75:
            bb_interpretation = "Well-recovered — high energy reserve at end of day"
        elif avg_bb >= 50:
            bb_interpretation = "Moderate — adequate recovery but room to improve"
        elif avg_bb >= 25:
            bb_interpretation = "Low — energy reserve depleted, prioritise recovery"
        else:
            bb_interpretation = "Depleted — significant recovery deficit, consider rest day"

    return {
        "period":             {"start": start_date, "end": end_date, "days": len(rows)},
        "daily":              rows,
        "averages":           averages,
        "hrv_status_breakdown": status_counts if status_counts else None,
        "body_battery_interpretation": bb_interpretation,
        "note": (
            "Body Battery is Garmin's proprietary energy-reserve metric (0-100), computed from "
            "overnight HRV, stress load, sleep quality, and activity. Avg stress is physiological "
            "(HRV-derived), not self-reported — it measures your body's stress response, not your "
            "perceived stress level."
        ),
    }


def tool_get_device_agreement(args):
    """
    Cross-device validation: Whoop vs Garmin agreement on HRV and RHR.
    Surfaces nights where the two devices significantly disagree, which is itself
    a signal — large disagreement often indicates a poor device fit, measurement
    artifact, or genuine physiological noise worth flagging.

    Agreement thresholds:
      HRV: |Whoop - Garmin| <= 10ms → agree; 10-20ms → minor variance; >20ms → flag
      RHR: |Whoop - Garmin| <= 3bpm → agree; 3-6bpm → minor variance; >6bpm → flag

    Returns:
      - Day-by-day comparison table
      - Overall agreement rate for each metric
      - Flagged disagreement days with context
      - Composite device confidence rating
    """
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    whoop_items  = {item["date"]: item for item in query_source("whoop", start_date, end_date)
                    if item.get("date")}
    garmin_items = {item["date"]: item for item in query_source("garmin", start_date, end_date)
                    if item.get("date")}

    all_dates = sorted(set(whoop_items.keys()) & set(garmin_items.keys()))

    if not all_dates:
        return {"error": f"No overlapping Whoop + Garmin data for {start_date} to {end_date}. "
                         "Ensure Garmin ingestion has run for this period."}

    hrv_agree = hrv_minor = hrv_flag = 0
    rhr_agree = rhr_minor = rhr_flag = 0
    comparison_rows = []
    flagged_days = []

    for date in all_dates:
        w = whoop_items[date]
        g = garmin_items[date]

        row = {"date": date}
        flags = []

        # ── HRV comparison ────────────────────────────────────────────────────
        whoop_hrv  = w.get("hrv")
        garmin_hrv = g.get("hrv_last_night")
        if whoop_hrv is not None and garmin_hrv is not None:
            wh = float(whoop_hrv)
            gh = float(garmin_hrv)
            diff = abs(wh - gh)
            row.update({
                "whoop_hrv_ms":   round(wh, 1),
                "garmin_hrv_ms":  round(gh, 1),
                "hrv_delta_ms":   round(wh - gh, 1),
                "hrv_abs_diff_ms": round(diff, 1),
            })
            if diff <= 10:
                row["hrv_agreement"] = "agree"
                hrv_agree += 1
            elif diff <= 20:
                row["hrv_agreement"] = "minor_variance"
                hrv_minor += 1
            else:
                row["hrv_agreement"] = "flag"
                hrv_flag += 1
                flags.append(f"HRV: Whoop {wh:.0f}ms vs Garmin {gh:.0f}ms (diff {diff:.0f}ms)")

        # ── RHR comparison ────────────────────────────────────────────────────
        whoop_rhr  = w.get("resting_heart_rate")
        garmin_rhr = g.get("resting_heart_rate")
        if whoop_rhr is not None and garmin_rhr is not None:
            wr = float(whoop_rhr)
            gr = float(garmin_rhr)
            diff = abs(wr - gr)
            row.update({
                "whoop_rhr_bpm":   round(wr, 1),
                "garmin_rhr_bpm":  round(gr, 1),
                "rhr_delta_bpm":   round(wr - gr, 1),
                "rhr_abs_diff_bpm": round(diff, 1),
            })
            if diff <= 3:
                row["rhr_agreement"] = "agree"
                rhr_agree += 1
            elif diff <= 6:
                row["rhr_agreement"] = "minor_variance"
                rhr_minor += 1
            else:
                row["rhr_agreement"] = "flag"
                rhr_flag += 1
                flags.append(f"RHR: Whoop {wr:.0f}bpm vs Garmin {gr:.0f}bpm (diff {diff:.0f}bpm)")

        comparison_rows.append(row)
        if flags:
            flagged_days.append({"date": date, "flags": flags})

    n = len(all_dates)
    hrv_days = hrv_agree + hrv_minor + hrv_flag
    rhr_days = rhr_agree + rhr_minor + rhr_flag

    hrv_agreement_rate = round(hrv_agree / hrv_days * 100, 1) if hrv_days else None
    rhr_agreement_rate = round(rhr_agree / rhr_days * 100, 1) if rhr_days else None

    # Composite device confidence
    combined_rate = None
    if hrv_agreement_rate is not None and rhr_agreement_rate is not None:
        combined_rate = round((hrv_agreement_rate + rhr_agreement_rate) / 2, 1)
    elif hrv_agreement_rate is not None:
        combined_rate = hrv_agreement_rate
    elif rhr_agreement_rate is not None:
        combined_rate = rhr_agreement_rate

    if combined_rate is not None:
        if combined_rate >= 80:
            confidence = "HIGH — devices closely agree; composite readiness score is reliable"
        elif combined_rate >= 60:
            confidence = "MODERATE — minor inter-device variance; composite score is broadly reliable"
        else:
            confidence = "LOW — significant disagreement; investigate fit, positioning, or artifacts"
    else:
        confidence = "UNKNOWN — insufficient overlapping data"

    return {
        "period":            {"start": start_date, "end": end_date, "overlapping_days": n},
        "hrv_agreement": {
            "agree_days":    hrv_agree,
            "minor_days":    hrv_minor,
            "flagged_days":  hrv_flag,
            "agreement_rate_pct": hrv_agreement_rate,
            "threshold_note": "Agree: ≤10ms delta; minor: 10-20ms; flag: >20ms",
        } if hrv_days else None,
        "rhr_agreement": {
            "agree_days":    rhr_agree,
            "minor_days":    rhr_minor,
            "flagged_days":  rhr_flag,
            "agreement_rate_pct": rhr_agreement_rate,
            "threshold_note": "Agree: ≤3bpm delta; minor: 3-6bpm; flag: >6bpm",
        } if rhr_days else None,
        "device_confidence":  confidence,
        "combined_agreement_rate_pct": combined_rate,
        "flagged_disagreement_days": flagged_days if flagged_days else None,
        "daily":             comparison_rows,
        "interpretation": (
            "HRV delta is expected between devices (Whoop uses 1-min intervals overnight; "
            "Garmin uses 5-min intervals) — 10-15ms variance is normal. Flags >20ms often "
            "indicate one device had a poor-fit night. RHR should agree within 3-5bpm; "
            "larger gaps suggest optical sensor placement or motion artifacts."
        ),
    }


def tool_get_readiness_score(args):
    """
    Unified readiness score (0–100) synthesising Whoop recovery, Eight Sleep quality,
    HRV 7-day trend, TSB training form, and Garmin Body Battery into a single
    GREEN / YELLOW / RED signal with a 1-line actionable recommendation.

    Weights:
      Whoop recovery score  : 35%
      Eight Sleep score     : 25%
      HRV 7-day trend       : 20%
      TSB training form     : 10%
      Garmin Body Battery   : 10%

    If a component is unavailable, remaining weights are re-normalised so the
    score is still meaningful with partial data.

    Device agreement: Whoop vs Garmin HRV and RHR delta is computed and returned
    as a confidence signal — large disagreement flags lower score reliability.
    """
    end_date   = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start   = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d30_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    d90_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    components = {}

    # ── 1. Whoop recovery score (40%) ─────────────────────────────────────────
    whoop_recent = query_source("whoop", d7_start, end_date)
    whoop_sorted = sorted(whoop_recent, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today  = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)

    if whoop_today:
        rec_score = float(whoop_today["recovery_score"])
        components["whoop_recovery"] = {
            "score":        round(rec_score, 1),
            "weight":       0.35,
            "raw": {
                "date":           whoop_today.get("date"),
                "recovery_score": whoop_today.get("recovery_score"),
                "hrv_ms":         whoop_today.get("hrv"),
                "resting_hr":     whoop_today.get("resting_heart_rate"),
                "sleep_hours":    whoop_today.get("sleep_duration_hours"),
            },
        }

    # ── 2. Eight Sleep score (30%) ────────────────────────────────────────────
    sleep_recent = query_source("eightsleep", d7_start, end_date)
    sleep_sorted = sorted(sleep_recent, key=lambda x: x.get("date", ""), reverse=True)
    sleep_today  = next((s for s in sleep_sorted
                         if s.get("sleep_score") is not None or s.get("sleep_efficiency_pct") is not None), None)

    if sleep_today:
        # Prefer native sleep_score (0-100); fallback: derive from efficiency
        if sleep_today.get("sleep_score") is not None:
            es_score = float(sleep_today["sleep_score"])
            es_method = "sleep_score"
        else:
            eff = float(sleep_today["sleep_efficiency_pct"])
            # 75% eff → ~50 score; 85% → ~70; 95% → ~90 (linear: score = eff - 25)
            es_score  = _clamp(eff - 25.0)
            es_method = "derived_from_efficiency"

        components["eight_sleep"] = {
            "score":   round(es_score, 1),
            "weight":  0.25,
            "raw": {
                "date":                sleep_today.get("date"),
                "sleep_score":         sleep_today.get("sleep_score"),
                "sleep_efficiency_pct": sleep_today.get("sleep_efficiency_pct"),
                "sleep_duration_hours": sleep_today.get("sleep_duration_hours"),
                "rem_pct":             sleep_today.get("rem_pct"),
                "deep_pct":            sleep_today.get("deep_pct"),
                "scoring_method":      es_method,
            },
        }

    # ── 3. HRV 7-day trend vs 30-day baseline (20%) ───────────────────────────
    whoop_30d = query_source("whoop", d30_start, end_date)
    hrv_30d   = [float(w["hrv"]) for w in whoop_30d if w.get("hrv") is not None]
    hrv_7d    = [float(w["hrv"]) for w in whoop_recent if w.get("hrv") is not None]

    if len(hrv_30d) >= 7 and hrv_7d:
        baseline  = sum(hrv_30d) / len(hrv_30d)
        recent7   = sum(hrv_7d) / len(hrv_7d)
        ratio     = recent7 / baseline if baseline > 0 else 1.0
        trend_pct = round((ratio - 1.0) * 100, 1)
        # ratio=1.0 → 60, +10% → 80, -10% → 40
        hrv_score = _clamp(60.0 + (ratio - 1.0) * 200.0)

        components["hrv_trend"] = {
            "score":  round(hrv_score, 1),
            "weight": 0.20,
            "raw": {
                "hrv_7d_avg_ms":      round(recent7, 1),
                "hrv_30d_baseline_ms": round(baseline, 1),
                "trend_pct":          trend_pct,
                "trend_direction":    "above_baseline" if trend_pct > 3 else ("below_baseline" if trend_pct < -3 else "at_baseline"),
                "n_days_30d":         len(hrv_30d),
                "n_days_7d":          len(hrv_7d),
            },
        }

    # ── 4. TSB training form (10%) ────────────────────────────────────────────
    try:
        load_result = tool_get_training_load({"end_date": end_date})
        if "current_state" in load_result:
            cs  = load_result["current_state"]
            tsb = cs.get("tsb_form", 0.0)
            # TSB=0 → 70, +5 → 82.5, +10 → 95, -10 → 45, -20 → 20
            tsb_score = _clamp(70.0 + float(tsb) * 2.5)
            components["training_form"] = {
                "score":  round(tsb_score, 1),
                "weight": 0.10,
                "raw": {
                    "tsb_form":    cs.get("tsb_form"),
                    "ctl_fitness": cs.get("ctl_fitness"),
                    "atl_fatigue": cs.get("atl_fatigue"),
                    "acwr":        cs.get("acwr"),
                    "form_status": cs.get("form_status"),
                },
            }
    except Exception as e:
        logger.warning(f"get_readiness_score: TSB failed — {e}")

    # ── 5. Garmin Body Battery (10%) ──────────────────────────────────────────
    garmin_recent = query_source("garmin", d7_start, end_date)
    garmin_sorted = sorted(garmin_recent, key=lambda x: x.get("date", ""), reverse=True)
    garmin_today  = next((g for g in garmin_sorted
                          if g.get("body_battery_end") is not None or g.get("body_battery_high") is not None), None)

    if garmin_today:
        # Use end-of-day Body Battery as primary; fall back to high if end is missing
        bb = garmin_today.get("body_battery_end") or garmin_today.get("body_battery_high")
        if bb is not None:
            bb_score = _clamp(float(bb))  # Body Battery is already 0-100
            components["garmin_body_battery"] = {
                "score":  round(bb_score, 1),
                "weight": 0.10,
                "raw": {
                    "date":               garmin_today.get("date"),
                    "body_battery_end":   garmin_today.get("body_battery_end"),
                    "body_battery_high":  garmin_today.get("body_battery_high"),
                    "body_battery_low":   garmin_today.get("body_battery_low"),
                    "avg_stress":         garmin_today.get("avg_stress"),
                    "hrv_last_night":     garmin_today.get("hrv_last_night"),
                    "hrv_status":         garmin_today.get("hrv_status"),
                },
            }

    # ── Device agreement: Whoop vs Garmin cross-validation ───────────────────
    device_agreement = None
    if "whoop_recovery" in components and garmin_today is not None:
        whoop_hrv_val  = components["whoop_recovery"]["raw"].get("hrv_ms")
        garmin_hrv_val = garmin_today.get("hrv_last_night")
        whoop_rhr_val  = components["whoop_recovery"]["raw"].get("resting_hr")
        garmin_rhr_val = garmin_today.get("resting_heart_rate")

        checks = {}
        agreement_signals = []

        if whoop_hrv_val is not None and garmin_hrv_val is not None:
            hrv_diff = abs(float(whoop_hrv_val) - float(garmin_hrv_val))
            hrv_status = "agree" if hrv_diff <= 10 else ("minor_variance" if hrv_diff <= 20 else "flag")
            checks["hrv"] = {
                "whoop_ms": round(float(whoop_hrv_val), 1),
                "garmin_ms": round(float(garmin_hrv_val), 1),
                "delta_ms": round(float(whoop_hrv_val) - float(garmin_hrv_val), 1),
                "status": hrv_status,
            }
            agreement_signals.append(hrv_status)

        if whoop_rhr_val is not None and garmin_rhr_val is not None:
            rhr_diff = abs(float(whoop_rhr_val) - float(garmin_rhr_val))
            rhr_status = "agree" if rhr_diff <= 3 else ("minor_variance" if rhr_diff <= 6 else "flag")
            checks["rhr"] = {
                "whoop_bpm": round(float(whoop_rhr_val), 1),
                "garmin_bpm": round(float(garmin_rhr_val), 1),
                "delta_bpm": round(float(whoop_rhr_val) - float(garmin_rhr_val), 1),
                "status": rhr_status,
            }
            agreement_signals.append(rhr_status)

        if agreement_signals:
            has_flag = any(s == "flag" for s in agreement_signals)
            all_agree = all(s == "agree" for s in agreement_signals)
            confidence = "high" if all_agree else ("low" if has_flag else "moderate")
            device_agreement = {
                "confidence": confidence,
                "checks": checks,
                "note": "flag = significant inter-device disagreement; readiness score may be less reliable on flagged days",
            }

    # ── Weighted aggregate ────────────────────────────────────────────────────
    total_weight = sum(c["weight"] for c in components.values())

    if not components:
        return {"error": "No data available from any source for this date. Check ingestion pipeline."}

    raw_score = sum(c["score"] * c["weight"] for c in components.values()) / total_weight
    readiness_score = round(raw_score, 1)

    # Label
    if readiness_score >= 70:
        label = "GREEN"
    elif readiness_score >= 40:
        label = "YELLOW"
    else:
        label = "RED"

    # ── Recommendation ────────────────────────────────────────────────────────
    missing = []
    all_keys = {"whoop_recovery", "eight_sleep", "hrv_trend", "training_form", "garmin_body_battery"}
    for k in sorted(all_keys - set(components.keys())):
        missing.append(k.replace("_", " "))

    # Build context-aware recommendation
    rec_parts = []

    if label == "GREEN":
        rec_parts.append("You're primed — go ahead with your planned hard session.")
        if "training_form" in components and components["training_form"]["raw"].get("tsb_form", 0) > 8:
            rec_parts.append("TSB is notably positive, meaning you're very fresh — a good day for a PR attempt or race effort.")
    elif label == "YELLOW":
        rec_parts.append("Moderate readiness — a controlled effort is appropriate; skip high-intensity intervals.")
        if "whoop_recovery" in components and components["whoop_recovery"]["score"] < 50:
            rec_parts.append("Whoop recovery is low — prioritise aerobic work over heavy strength training today.")
        if "eight_sleep" in components and components["eight_sleep"]["score"] < 50:
            rec_parts.append("Sleep quality was below average — consider a shorter session and extra cool-down.")
    else:  # RED
        rec_parts.append("Recovery day. Hard training now will deepen fatigue without adding fitness.")
        if "hrv_trend" in components and components["hrv_trend"]["raw"]["trend_pct"] < -10:
            rec_parts.append("HRV is trending meaningfully below your baseline — this is your body asking for rest.")

    recommendation = " ".join(rec_parts)

    return {
        "date":             end_date,
        "readiness_score":  readiness_score,
        "label":            label,
        "recommendation":   recommendation,
        "components":       components,
        "device_agreement": device_agreement,
        "data_completeness": "full" if total_weight >= 0.99 else f"partial ({round(total_weight*100)}% weight covered)",
        "missing_components": missing if missing else None,
        "scoring_note":     (
            "Weights: Whoop recovery 35%, Eight Sleep 25%, HRV 7d trend 20%, TSB form 10%, "
            "Garmin Body Battery 10%. Missing components are excluded and remaining weights re-normalised."
        ),
    }


# ── Tools: Insights Coaching Log (v2.5.0) ────────────────────────────────────
INSIGHTS_PK = USER_PREFIX + "insights"


def tool_save_insight(args):
    """Save a new insight to the coaching log.
    PK: USER#matthew#SOURCE#insights
    SK: INSIGHT#<ISO-timestamp>
    """
    text   = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")

    tags   = args.get("tags") or []
    source = args.get("source") or "chat"

    now        = datetime.utcnow()
    ts         = now.strftime("%Y-%m-%dT%H:%M:%S")
    insight_id = ts  # human-readable, doubles as sort key suffix
    sk         = f"INSIGHT#{ts}"

    item = {
        "pk":           INSIGHTS_PK,
        "sk":           sk,
        "insight_id":   insight_id,
        "text":         text,
        "date_saved":   now.strftime("%Y-%m-%d"),
        "source":       source,
        "status":       "open",
        "outcome_notes": "",
        "tags":         tags,
    }
    table.put_item(Item=item)
    logger.info(f"save_insight: saved insight_id={insight_id}")
    return {
        "saved":        True,
        "insight_id":   insight_id,
        "date_saved":   item["date_saved"],
        "text_preview": text[:120] + ("…" if len(text) > 120 else ""),
        "tags":         tags,
        "source":       source,
    }


def tool_get_insights(args):
    """List insights from the coaching log.
    Optionally filter by status (open/acted/resolved).
    Returns newest-first. Flags items open >14 days.
    """
    status_filter = args.get("status_filter")  # None = all
    limit         = int(args.get("limit") or 50)
    today         = datetime.utcnow().date()

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(INSIGHTS_PK) & Key("sk").begins_with("INSIGHT#"),
        ScanIndexForward=False,  # newest first
        Limit=200,
    )
    items = resp.get("Items", [])

    results = []
    for item in items:
        status = item.get("status", "open")
        if status_filter and status != status_filter:
            continue

        date_saved = item.get("date_saved", "")
        try:
            days_open = (today - datetime.strptime(date_saved, "%Y-%m-%d").date()).days
        except Exception:
            days_open = None

        results.append({
            "insight_id":    item.get("insight_id", ""),
            "text":          item.get("text", ""),
            "date_saved":    date_saved,
            "days_open":     days_open,
            "source":        item.get("source", "chat"),
            "status":        status,
            "outcome_notes": item.get("outcome_notes", ""),
            "tags":          item.get("tags", []),
            "stale":         (days_open is not None and days_open > 14 and status == "open"),
        })
        if len(results) >= limit:
            break

    stale_count = sum(1 for r in results if r["stale"])
    return {
        "total":         len(results),
        "stale_count":   stale_count,
        "status_filter": status_filter or "all",
        "insights":      results,
    }


def tool_update_insight_outcome(args):
    """Update the outcome notes and/or status of an existing insight.
    insight_id is the timestamp string returned by save_insight (e.g. 2026-02-22T09:15:00).
    status must be one of: open, acted, resolved.
    """
    insight_id     = (args.get("insight_id") or "").strip()
    outcome_notes  = (args.get("outcome_notes") or "").strip()
    new_status     = (args.get("status") or "acted").strip()

    if not insight_id:
        raise ValueError("insight_id is required")
    if new_status not in ("open", "acted", "resolved"):
        raise ValueError("status must be one of: open, acted, resolved")

    sk = f"INSIGHT#{insight_id}"

    # Verify the item exists
    existing = table.get_item(Key={"pk": INSIGHTS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"No insight found with id={insight_id}")

    table.update_item(
        Key={"pk": INSIGHTS_PK, "sk": sk},
        UpdateExpression="SET #s = :s, outcome_notes = :o, date_updated = :d",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": new_status,
            ":o": outcome_notes,
            ":d": datetime.utcnow().strftime("%Y-%m-%d"),
        },
    )
    logger.info(f"update_insight_outcome: insight_id={insight_id} status={new_status}")
    return {
        "updated":       True,
        "insight_id":    insight_id,
        "status":        new_status,
        "outcome_notes": outcome_notes,
        "text_preview":  existing.get("text", "")[:120],
    }




# ── Labs / DEXA / Genome helpers (v2.11.0) ───────────────────────────────────

_GENOME_CACHE_V2 = None

def _get_genome_cached():
    """Query all genome SNPs once per Lambda invocation."""
    global _GENOME_CACHE_V2
    if _GENOME_CACHE_V2 is not None:
        return _GENOME_CACHE_V2
    pk = f"{USER_PREFIX}genome"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    _GENOME_CACHE_V2 = decimal_to_float(items)
    return _GENOME_CACHE_V2


def _query_all_lab_draws():
    """Query all blood draw items from labs source, sorted chronologically."""
    pk = f"{USER_PREFIX}labs"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return decimal_to_float(sorted(items, key=lambda x: x.get("sk", "")))


def _query_dexa_scans():
    """Query all DEXA scan items, sorted chronologically."""
    pk = f"{USER_PREFIX}dexa"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return decimal_to_float(items)


def _query_lab_meta():
    """Query labs provider metadata items (non-DATE# SKs)."""
    pk = f"{USER_PREFIX}labs"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    all_items = decimal_to_float(items)
    return [i for i in all_items if not i.get("sk", "").startswith("DATE#")]


_GENOME_LAB_XREF = {
    "ldl_c":             ["ABCG8", "SLCO1B1"],
    "cholesterol_total": ["ABCG8"],
    "triglycerides":     ["ADIPOQ"],
    "glucose":           ["FTO", "IRS1", "TCF7L2"],
    "hba1c":             ["FTO", "IRS1", "TCF7L2"],
    "vitamin_d_25oh":    ["VDR", "GC", "CYP2R1"],
    "homocysteine":      ["MTHFR", "MTRR"],
    "ferritin":          ["HFE"],
    "crp_hs":            ["CRP", "IL6"],
    "folate":            ["MTHFR", "MTRR"],
    "vitamin_b12":       ["MTHFR", "MTRR"],
    "omega_3_index":     ["FADS2"],
    "testosterone_total":["SHBG"],
    "apolipoprotein_b":  ["ABCG8", "SLCO1B1"],
}


def _genome_context_for_biomarkers(biomarker_keys):
    """Return genome annotations relevant to a set of biomarker keys."""
    genes_needed = set()
    for bk in biomarker_keys:
        genes_needed.update(_GENOME_LAB_XREF.get(bk, []))
    if not genes_needed:
        return {}
    all_snps = _get_genome_cached()
    relevant = [s for s in all_snps if s.get("gene") in genes_needed]
    if not relevant:
        return {}
    result = {}
    for bk in biomarker_keys:
        genes = _GENOME_LAB_XREF.get(bk, [])
        if not genes:
            continue
        matches = [s for s in relevant if s.get("gene") in genes]
        if matches:
            result[bk] = [{
                "gene": s.get("gene"), "rsid": s.get("rsid"),
                "genotype": s.get("genotype"), "risk_level": s.get("risk_level"),
                "summary": s.get("summary"),
            } for s in matches]
    return result


def _linear_regression(points):
    """Simple OLS on list of (x, y) tuples. Returns slope, intercept, r_squared."""
    n = len(points)
    if n < 2:
        return None, None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = sum(xs)/n, sum(ys)/n
    ss_xx = sum((x - mx)**2 for x in xs)
    if ss_xx == 0:
        return 0, my, 0
    ss_xy = sum((x - mx)*(y - my) for x, y in zip(xs, ys))
    slope = ss_xy / ss_xx
    intercept = my - slope * mx
    ss_yy = sum((y - my)**2 for y in ys)
    r_sq = (ss_xy**2 / (ss_xx * ss_yy)) if ss_yy > 0 else 0
    return round(slope, 4), round(intercept, 2), round(r_sq, 3)




# ═══════════════════════════════════════════════════════════════════════════════
# Labs / DEXA / Genome tools (v2.11.0)
# ═══════════════════════════════════════════════════════════════════════════════


def tool_get_lab_results(args):
    """Single draw detail with genome annotations, or summary of all draws."""
    draw_date = args.get("draw_date")
    category = args.get("category")
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found in DynamoDB"}

    if not draw_date:
        summaries = []
        for d in draws:
            summaries.append({
                "draw_date": d.get("draw_date"),
                "provider": d.get("lab_provider"),
                "lab_network": d.get("lab_network"),
                "fasting": d.get("fasting"),
                "total_biomarkers": d.get("total_biomarkers"),
                "out_of_range_count": d.get("out_of_range_count"),
                "out_of_range": d.get("out_of_range", []),
            })
        return {"total_draws": len(draws), "draws": summaries,
                "hint": "Pass draw_date to see full biomarkers for a specific draw."}

    draw = next((d for d in draws if d.get("draw_date") == draw_date), None)
    if not draw:
        return {"error": f"No draw for {draw_date}",
                "available_dates": [d.get("draw_date") for d in draws]}

    biomarkers = draw.get("biomarkers", {})
    if category:
        biomarkers = {k: v for k, v in biomarkers.items()
                      if v.get("category") == category}

    genome_ctx = _genome_context_for_biomarkers(list(biomarkers.keys()))
    categories = sorted(set(v.get("category", "")
                            for v in draw.get("biomarkers", {}).values()))

    return {
        "draw_date": draw_date,
        "provider": draw.get("lab_provider"),
        "lab_network": draw.get("lab_network"),
        "physician": draw.get("physician"),
        "fasting": draw.get("fasting"),
        "total_biomarkers": draw.get("total_biomarkers"),
        "out_of_range_count": draw.get("out_of_range_count"),
        "out_of_range": draw.get("out_of_range", []),
        "biomarkers": biomarkers,
        "genome_context": genome_ctx if genome_ctx else None,
        "categories_in_draw": categories,
    }


def tool_get_lab_trends(args):
    """Biomarker trajectory across all draws with slope, projection, derived ratios."""
    biomarkers_req = args.get("biomarkers", [])
    single = args.get("biomarker")
    if single:
        biomarkers_req = [single]
    include_derived = args.get("include_derived_ratios", True)
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    from datetime import datetime as _dt

    trends = {}
    for bm_key in biomarkers_req:
        points = []
        for d in draws:
            bms = d.get("biomarkers", {})
            if bm_key in bms:
                val = bms[bm_key].get("value_numeric") or bms[bm_key].get("value")
                if isinstance(val, (int, float)):
                    date = d.get("draw_date", "")
                    points.append({"date": date, "value": round(val, 2),
                                   "flag": bms[bm_key].get("flag", "normal"),
                                   "ref": bms[bm_key].get("ref_text", ""),
                                   "unit": bms[bm_key].get("unit", "")})
        if not points:
            trends[bm_key] = {"error": f"No data for '{bm_key}'",
                              "hint": "Use search_biomarker to find valid names."}
            continue

        base = _dt.strptime(points[0]["date"], "%Y-%m-%d")
        reg_pts = [( (_dt.strptime(p["date"], "%Y-%m-%d") - base).days, p["value"] ) for p in points]
        slope, intercept, r_sq = _linear_regression(reg_pts)

        if slope is not None:
            direction = "rising" if slope > 0.001 else ("falling" if slope < -0.001 else "stable")
            slope_per_year = round(slope * 365.25, 2)
        else:
            direction, slope_per_year = "insufficient_data", None

        projected_1yr = None
        if slope is not None and len(reg_pts) >= 2:
            projected_1yr = round(intercept + slope * (reg_pts[-1][0] + 365), 2)

        trends[bm_key] = {
            "values": points, "data_points": len(points),
            "direction": direction, "slope_per_year": slope_per_year,
            "r_squared": r_sq, "projected_1yr": projected_1yr,
            "latest": points[-1]["value"], "earliest": points[0]["value"],
            "total_change": round(points[-1]["value"] - points[0]["value"], 2),
        }

    derived = {}
    if include_derived:
        for d in draws:
            bms = d.get("biomarkers", {})
            date = d.get("draw_date", "")
            tg_v = bms.get("triglycerides", {}).get("value_numeric") or bms.get("triglycerides", {}).get("value")
            hdl_v = bms.get("hdl", {}).get("value_numeric") or bms.get("hdl", {}).get("value")
            tc_v = bms.get("cholesterol_total", {}).get("value_numeric") or bms.get("cholesterol_total", {}).get("value")

            if isinstance(tg_v, (int, float)) and isinstance(hdl_v, (int, float)) and hdl_v > 0:
                derived.setdefault("tg_hdl_ratio", []).append({
                    "date": date, "value": round(tg_v / hdl_v, 2),
                    "interpretation": "optimal <1.0, good <2.0, elevated >=2.0 (insulin resistance proxy)"})
            if isinstance(tc_v, (int, float)) and isinstance(hdl_v, (int, float)):
                derived.setdefault("non_hdl_cholesterol", []).append({
                    "date": date, "value": round(tc_v - hdl_v, 1),
                    "interpretation": "optimal <130, borderline 130-159, high >=160"})
            if isinstance(tc_v, (int, float)) and isinstance(hdl_v, (int, float)) and hdl_v > 0:
                derived.setdefault("tc_hdl_ratio", []).append({
                    "date": date, "value": round(tc_v / hdl_v, 2),
                    "interpretation": "optimal <3.5, good <5.0, elevated >=5.0"})

    genome_ctx = _genome_context_for_biomarkers(biomarkers_req)
    result = {"trends": trends, "total_draws": len(draws),
              "date_range": f"{draws[0].get('draw_date')} to {draws[-1].get('draw_date')}"}
    if derived:
        result["derived_ratios"] = derived
    if genome_ctx:
        result["genome_context"] = genome_ctx
    return result


def tool_get_out_of_range_history(args):
    """Every flagged biomarker across all draws with persistence and genome drivers."""
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    oor_map = defaultdict(list)
    for d in draws:
        date = d.get("draw_date", "")
        bms = d.get("biomarkers", {})
        for key, bm_data in bms.items():
            if bm_data.get("flag") in ("high", "low"):
                val = bm_data.get("value_numeric") or bm_data.get("value")
                oor_map[key].append({
                    "date": date, "value": val, "flag": bm_data["flag"],
                    "unit": bm_data.get("unit", ""), "ref_text": bm_data.get("ref_text", ""),
                    "category": bm_data.get("category", "")})

    total_draws = len(draws)
    flagged = []
    for key, occurrences in sorted(oor_map.items(), key=lambda x: -len(x[1])):
        tested_count = sum(1 for d in draws if key in d.get("biomarkers", {}))
        flagged_rate = round(100 * len(occurrences) / max(tested_count, 1), 1)
        flagged.append({
            "biomarker": key, "category": occurrences[0]["category"],
            "times_flagged": len(occurrences), "times_tested": tested_count,
            "flag_rate_pct": flagged_rate,
            "persistence": "chronic" if flagged_rate >= 60 else ("recurring" if flagged_rate >= 30 else "occasional"),
            "occurrences": occurrences})

    chronic_keys = [f["biomarker"] for f in flagged if f["persistence"] == "chronic"]
    genome_ctx = _genome_context_for_biomarkers(chronic_keys)

    return {
        "total_draws": total_draws,
        "date_range": f"{draws[0].get('draw_date')} to {draws[-1].get('draw_date')}",
        "flagged_biomarkers": flagged, "total_unique_flags": len(flagged),
        "chronic_flags": chronic_keys,
        "genome_drivers": genome_ctx if genome_ctx else None,
        "insight": ("Chronic out-of-range biomarkers with genome drivers suggest genetic baseline "
                    "rather than lifestyle failure.") if genome_ctx else None}


def tool_search_biomarker(args):
    """Free-text search for a biomarker across all draws."""
    query = args.get("query", "").lower().strip()
    if not query:
        return {"error": "Provide a search query (e.g. 'ldl', 'cholesterol', 'thyroid')."}

    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    matches = defaultdict(list)
    for d in draws:
        date = d.get("draw_date", "")
        bms = d.get("biomarkers", {})
        for key, bm_data in bms.items():
            cat = bm_data.get("category", "")
            if query in key.lower() or query in cat.lower():
                val = bm_data.get("value_numeric") or bm_data.get("value")
                matches[key].append({
                    "date": date, "value": val, "flag": bm_data.get("flag", "normal"),
                    "unit": bm_data.get("unit", ""), "ref_text": bm_data.get("ref_text", ""),
                    "category": cat})

    if not matches:
        all_keys = set()
        for d in draws:
            all_keys.update(d.get("biomarkers", {}).keys())
        return {"error": f"No match for '{query}'", "available_biomarkers": sorted(all_keys)}

    results = []
    for key, values in sorted(matches.items()):
        numeric_vals = [v["value"] for v in values if isinstance(v["value"], (int, float))]
        entry = {"biomarker": key, "category": values[0]["category"],
                 "unit": values[0]["unit"], "data_points": len(values), "values": values}
        if len(numeric_vals) >= 2:
            entry["latest"] = numeric_vals[-1]
            entry["earliest"] = numeric_vals[0]
            entry["change"] = round(numeric_vals[-1] - numeric_vals[0], 2)
            entry["direction"] = "rising" if entry["change"] > 0.5 else ("falling" if entry["change"] < -0.5 else "stable")
        results.append(entry)

    genome_ctx = _genome_context_for_biomarkers([r["biomarker"] for r in results])
    return {"query": query, "matches": len(results), "results": results,
            "genome_context": genome_ctx if genome_ctx else None}


def tool_get_genome_insights(args):
    """Query genome SNPs by category/risk/gene with optional cross-reference."""
    category = args.get("category")
    risk_level = args.get("risk_level")
    gene = args.get("gene")
    cross_ref = args.get("cross_reference")

    all_snps = _get_genome_cached()
    if not all_snps:
        return {"error": "No genome data found."}

    filtered = [s for s in all_snps if s.get("sk", "").startswith("GENE#")]
    if category:
        filtered = [s for s in filtered if s.get("category") == category]
    if risk_level:
        filtered = [s for s in filtered if s.get("risk_level") == risk_level]
    if gene:
        g = gene.upper()
        filtered = [s for s in filtered if s.get("gene", "").upper() == g]

    snps_out = []
    for s in filtered:
        entry = {"gene": s.get("gene"), "rsid": s.get("rsid"),
                 "genotype": s.get("genotype"), "category": s.get("category"),
                 "risk_level": s.get("risk_level"), "summary": s.get("summary")}
        if s.get("actionable_recs"):
            entry["actionable_recs"] = s["actionable_recs"]
        if s.get("related_biomarkers"):
            entry["related_biomarkers"] = s["related_biomarkers"]
        snps_out.append(entry)

    result = {"total_snps": len(snps_out),
              "filters_applied": {k: v for k, v in {"category": category, "risk_level": risk_level, "gene": gene}.items() if v},
              "snps": snps_out}

    if cross_ref == "labs" and snps_out:
        draws = _query_all_lab_draws()
        if draws:
            latest = draws[-1]
            bms = latest.get("biomarkers", {})
            snp_genes = set(s["gene"] for s in snps_out)
            lab_links = {}
            for bm_key, gene_list in _GENOME_LAB_XREF.items():
                if any(g in snp_genes for g in gene_list) and bm_key in bms:
                    val = bms[bm_key].get("value_numeric") or bms[bm_key].get("value")
                    lab_links[bm_key] = {"latest_value": val, "latest_date": latest.get("draw_date"),
                                         "flag": bms[bm_key].get("flag"), "unit": bms[bm_key].get("unit")}
            if lab_links:
                result["lab_cross_reference"] = lab_links

    if cross_ref == "nutrition" and snps_out:
        from datetime import datetime as _dt, timedelta as _td
        today = _dt.now().strftime("%Y-%m-%d")
        week_ago = (_dt.now() - _td(days=7)).strftime("%Y-%m-%d")
        try:
            mf = query_source("macrofactor", week_ago, today)
            if mf:
                result["nutrition_cross_reference"] = {
                    "period": f"{week_ago} to {today}", "days": len(mf),
                    "avg_calories": round(sum(d.get("total_calories_kcal", 0) for d in mf) / len(mf)),
                    "avg_protein_g": round(sum(d.get("total_protein_g", 0) for d in mf) / len(mf), 1),
                    "avg_fat_g": round(sum(d.get("total_fat_g", 0) for d in mf) / len(mf), 1),
                    "avg_omega3_g": round(sum(d.get("total_omega3_g", 0) for d in mf) / len(mf), 2)}
        except Exception as e:
            logger.warning(f"Nutrition cross-ref failed: {e}")

    if not category and not risk_level and not gene:
        cats, risks = defaultdict(int), defaultdict(int)
        for s in snps_out:
            cats[s.get("category", "unknown")] += 1
            risks[s.get("risk_level", "unknown")] += 1
        result["category_breakdown"] = dict(sorted(cats.items()))
        result["risk_breakdown"] = dict(sorted(risks.items()))
        result["available_categories"] = sorted(cats.keys())

    return result


def tool_get_body_composition_snapshot(args):
    """DEXA scan interpretation with FFMI, posture, Withings anchoring."""
    scans = _query_dexa_scans()
    if not scans:
        return {"error": "No DEXA scans found."}

    scan_date = args.get("date")
    if scan_date:
        scan = next((s for s in scans if s.get("scan_date") == scan_date), None)
        if not scan:
            return {"error": f"No scan for {scan_date}",
                    "available": [s.get("scan_date") for s in scans]}
    else:
        scan = scans[-1]

    bc = scan.get("body_composition", {})
    posture = scan.get("posture")
    interp = scan.get("interpretations", {})

    profile = get_profile()
    height_in = profile.get("height_inches", 72)
    height_m = height_in * 0.0254
    lean_lb = bc.get("lean_mass_lb", 0)
    lean_kg = lean_lb * 0.4536
    weight_lb = bc.get("weight_lb", 0)
    weight_kg = weight_lb * 0.4536

    ffmi = round(lean_kg / (height_m ** 2), 1) if height_m > 0 else None
    ffmi_norm = round(ffmi + 6.1 * (1.80 - height_m), 1) if ffmi else None
    ffmi_class = None
    if ffmi:
        if ffmi >= 25: ffmi_class = "exceptional (near natural limit)"
        elif ffmi >= 22: ffmi_class = "advanced"
        elif ffmi >= 20: ffmi_class = "above average"
        elif ffmi >= 18: ffmi_class = "average"
        else: ffmi_class = "below average"

    vat_g = bc.get("visceral_fat_g") or 999
    ag = bc.get("ag_ratio") or 99
    bmd_t = bc.get("bmd_t_score") or -9

    result = {
        "scan_date": scan.get("scan_date"), "provider": scan.get("provider"),
        "body_composition": {
            "weight_lb": bc.get("weight_lb"), "body_fat_pct": bc.get("body_fat_pct"),
            "fat_mass_lb": bc.get("fat_mass_lb"), "lean_mass_lb": lean_lb,
            "visceral_fat_g": bc.get("visceral_fat_g"),
            "visceral_fat_category": "elite" if vat_g < 500 else ("normal" if vat_g < 1000 else "elevated"),
            "android_fat_pct": bc.get("android_fat_pct"), "gynoid_fat_pct": bc.get("gynoid_fat_pct"),
            "ag_ratio": bc.get("ag_ratio"),
            "ag_status": "optimal" if ag <= 1.0 else ("slightly elevated" if ag <= 1.2 else "elevated"),
            "bmd_t_score": bc.get("bmd_t_score"),
            "bmd_status": "excellent" if bmd_t >= 1.0 else ("normal" if bmd_t >= -1.0 else "low")},
        "derived_metrics": {
            "ffmi": ffmi, "ffmi_normalized": ffmi_norm, "ffmi_classification": ffmi_class,
            "bmi": round(weight_kg / (height_m ** 2), 1) if height_m > 0 else None},
        "interpretations": interp}

    if posture:
        captures = []
        for key in ["capture_1", "capture_2"]:
            cap = posture.get(key, {})
            sag = cap.get("sagittal", {})
            trans = cap.get("transverse", {})
            if sag or trans:
                captures.append({
                    "shoulder_forward_in": sag.get("shoulder_forward_in"),
                    "hip_forward_in": sag.get("hip_forward_in"),
                    "shoulder_rotation_deg": trans.get("shoulder_rotation_deg"),
                    "shoulder_rotation_dir": trans.get("shoulder_rotation_dir")})
        if captures:
            avg_sh = round(sum(c.get("shoulder_forward_in", 0) for c in captures) / len(captures), 1)
            avg_hip = round(sum(c.get("hip_forward_in", 0) for c in captures) / len(captures), 1)
            flags = []
            if avg_sh > 2.0: flags.append("Forward shoulder posture — possible upper-cross syndrome")
            if avg_hip > 2.5: flags.append("Forward hip — possible anterior pelvic tilt")
            result["posture_summary"] = {
                "avg_shoulder_forward_in": avg_sh, "avg_hip_forward_in": avg_hip,
                "primary_rotation": captures[0].get("shoulder_rotation_dir", "unknown"),
                "flags": flags}

    try:
        from datetime import datetime as _dt, timedelta as _td
        today = _dt.now().strftime("%Y-%m-%d")
        week_ago = (_dt.now() - _td(days=7)).strftime("%Y-%m-%d")
        withings = query_source("withings", week_ago, today)
        if withings:
            lw = withings[-1]
            result["withings_current"] = {
                "date": lw.get("date"), "weight_lb": lw.get("weight_lbs"),
                "body_fat_pct": lw.get("body_fat_pct"),
                "weight_delta_since_dexa": round((lw.get("weight_lbs") or 0) - (bc.get("weight_lb") or 0), 1) if lw.get("weight_lbs") else None,
                "note": "Withings bioimpedance is less accurate than DEXA. Use DEXA as calibration anchor."}
    except Exception as e:
        logger.warning(f"Withings anchor failed: {e}")

    return result


def tool_get_health_risk_profile(args):
    """Multi-domain risk synthesis: cardiovascular, metabolic, longevity."""
    domain = args.get("domain")
    draws = _query_all_lab_draws()
    genome = _get_genome_cached()
    genome_snps = [s for s in genome if s.get("sk", "").startswith("GENE#")]
    dexa = _query_dexa_scans()

    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().strftime("%Y-%m-%d")
    result = {"assessment_date": today}

    def _get_bm(bms, key):
        b = bms.get(key, {})
        return b.get("value_numeric") or b.get("value")

    if not domain or domain == "cardiovascular":
        cv = {"domain": "cardiovascular", "factors": []}
        if draws:
            bms = draws[-1].get("biomarkers", {})
            ldl = _get_bm(bms, "ldl_c"); hdl = _get_bm(bms, "hdl")
            tg = _get_bm(bms, "triglycerides"); tc = _get_bm(bms, "cholesterol_total")
            apob = _get_bm(bms, "apolipoprotein_b"); crp = _get_bm(bms, "crp_hs")

            if isinstance(ldl, (int, float)):
                cv["factors"].append({"marker": "LDL-C", "value": ldl, "unit": "mg/dL",
                    "risk": "elevated" if ldl >= 100 else "optimal",
                    "note": "Attia target <100; <70 if high-risk"})
            if isinstance(hdl, (int, float)):
                cv["factors"].append({"marker": "HDL", "value": hdl, "unit": "mg/dL",
                    "risk": "optimal" if hdl >= 50 else "low"})
            if isinstance(tg, (int, float)) and isinstance(hdl, (int, float)) and hdl > 0:
                r = round(tg / hdl, 2)
                cv["factors"].append({"marker": "TG/HDL ratio", "value": r,
                    "risk": "optimal" if r < 1.0 else ("good" if r < 2.0 else "elevated"),
                    "note": "Insulin resistance proxy — target <1.0"})
            if isinstance(apob, (int, float)):
                cv["factors"].append({"marker": "ApoB", "value": apob, "unit": "mg/dL",
                    "risk": "optimal" if apob < 80 else ("borderline" if apob < 100 else "elevated"),
                    "note": "Best single predictor of atherosclerotic CV risk"})
            if isinstance(crp, (int, float)):
                cv["factors"].append({"marker": "hs-CRP", "value": crp, "unit": "mg/L",
                    "risk": "optimal" if crp < 1.0 else ("borderline" if crp < 3.0 else "elevated")})

        cv_genes = [s for s in genome_snps if s.get("gene") in ("ABCG8", "SLCO1B1")]
        if cv_genes:
            cv["genetic_factors"] = [{"gene": s["gene"], "genotype": s.get("genotype"),
                "risk_level": s.get("risk_level"), "summary": s.get("summary")} for s in cv_genes]

        if dexa:
            vat = dexa[-1].get("body_composition", {}).get("visceral_fat_g")
            if vat is not None:
                cv["factors"].append({"marker": "Visceral fat", "value": vat, "unit": "g",
                    "risk": "elite" if vat < 500 else ("normal" if vat < 1000 else "elevated")})

        try:
            whoop = query_source("whoop", (_dt.now() - _td(days=30)).strftime("%Y-%m-%d"), today, lean=True)
            if whoop:
                hrvs = [d.get("hrv") for d in whoop if d.get("hrv")]
                if hrvs:
                    cv["factors"].append({"marker": "30d avg HRV", "value": round(sum(hrvs)/len(hrvs), 1),
                        "unit": "ms", "note": "Higher = better CV health"})
        except Exception:
            pass


        # ASCVD 10-year risk (stored on labs records by patch_ascvd_risk.py)
        if draws:
            latest = draws[-1]
            ascvd_pct = latest.get("ascvd_risk_10yr_pct")
            if ascvd_pct is not None and isinstance(ascvd_pct, (int, float, Decimal)):
                ascvd_cat = latest.get("ascvd_risk_category", "unknown")
                ascvd_inputs = latest.get("ascvd_inputs", {})
                ascvd_caveats = latest.get("ascvd_caveats", [])
                cv["factors"].append({
                    "marker": "ASCVD 10yr Risk",
                    "value": float(ascvd_pct),
                    "unit": "%",
                    "risk": ascvd_cat,
                    "equation": "Pooled Cohort Equations (2013 ACC/AHA)",
                    "note": "Age-extrapolated — validated for 40-79" if any("extrapolated" in str(c) for c in ascvd_caveats) else "Within validated age range",
                    "inputs": {k: float(v) if isinstance(v, (Decimal, int, float)) else v for k, v in ascvd_inputs.items()},
                })

        elevated = sum(1 for f in cv["factors"] if f.get("risk") in ("elevated", "high", "low"))
        cv["overall_risk"] = "elevated" if elevated >= 2 else ("borderline" if elevated == 1 else "low")
        result["cardiovascular"] = cv

    if not domain or domain == "metabolic":
        met = {"domain": "metabolic", "factors": []}
        if draws:
            bms = draws[-1].get("biomarkers", {})
            glu = _get_bm(bms, "glucose"); a1c = _get_bm(bms, "hba1c")

            if isinstance(glu, (int, float)):
                met["factors"].append({"marker": "Fasting glucose", "value": glu, "unit": "mg/dL",
                    "risk": "optimal" if glu < 90 else ("borderline" if glu < 100 else "elevated"),
                    "note": "Attia optimal <90"})
                glu_trend = [{"date": d.get("draw_date"), "value": _get_bm(d.get("biomarkers", {}), "glucose")}
                             for d in draws if isinstance(_get_bm(d.get("biomarkers", {}), "glucose"), (int, float))]
                if len(glu_trend) >= 2:
                    met["factors"][-1]["trend"] = glu_trend

            if isinstance(a1c, (int, float)):
                met["factors"].append({"marker": "HbA1c", "value": a1c, "unit": "%",
                    "risk": "optimal" if a1c < 5.4 else ("borderline" if a1c < 5.7 else "prediabetic" if a1c < 6.5 else "diabetic"),
                    "note": "Attia optimal <5.4"})

        fto = [s for s in genome_snps if s.get("gene") == "FTO"]
        irs = [s for s in genome_snps if s.get("gene") == "IRS1"]
        if fto or irs:
            met["genetic_factors"] = []
            if fto:
                unfav = sum(1 for s in fto if s.get("risk_level") == "unfavorable")
                met["genetic_factors"].append({"cluster": "FTO obesity variants", "total": len(fto),
                    "unfavorable": unfav, "implication": "Exercise + protein + PUFA mitigate risk"})
            for s in irs:
                met["genetic_factors"].append({"gene": s["gene"], "genotype": s.get("genotype"),
                    "risk_level": s.get("risk_level"), "summary": s.get("summary")})

        if dexa:
            bc = dexa[-1].get("body_composition", {})
            bf = bc.get("body_fat_pct"); ag = bc.get("ag_ratio")
            if bf is not None:
                met["factors"].append({"marker": "Body fat %", "value": bf, "source": "DEXA",
                    "risk": "lean" if bf < 15 else ("healthy" if bf < 20 else "elevated")})
            if ag is not None:
                met["factors"].append({"marker": "A/G ratio", "value": ag, "source": "DEXA",
                    "risk": "optimal" if ag <= 1.0 else "slightly elevated",
                    "note": "Target <=1.0"})

        elevated = sum(1 for f in met["factors"] if f.get("risk") in ("elevated", "prediabetic", "diabetic"))
        met["overall_risk"] = "elevated" if elevated >= 2 else ("borderline" if elevated == 1 else "low")
        result["metabolic"] = met

    if not domain or domain == "longevity":
        lon = {"domain": "longevity", "factors": []}

        if dexa:
            bc = dexa[-1].get("body_composition", {})
            bmd = bc.get("bmd_t_score")
            if bmd is not None:
                lon["factors"].append({"marker": "BMD T-score", "value": bmd,
                    "risk": "excellent" if bmd >= 1.0 else ("normal" if bmd >= -1.0 else "low"),
                    "note": "Critical for fracture risk in aging"})
            lean_lb = bc.get("lean_mass_lb", 0)
            profile = get_profile()
            height_m = profile.get("height_inches", 72) * 0.0254
            if lean_lb and height_m > 0:
                ffmi = round((lean_lb * 0.4536) / (height_m ** 2), 1)
                lon["factors"].append({"marker": "FFMI", "value": ffmi,
                    "risk": "excellent" if ffmi >= 22 else ("good" if ffmi >= 20 else "average"),
                    "note": "Muscle mass protects against all-cause mortality"})

        if draws:
            a1c_vals = [_get_bm(d.get("biomarkers", {}), "hba1c") for d in draws]
            a1c_vals = [v for v in a1c_vals if isinstance(v, (int, float))]
            if a1c_vals:
                lon["factors"].append({"marker": "HbA1c range", "value": f"{min(a1c_vals)}-{max(a1c_vals)}%",
                    "risk": "optimal" if max(a1c_vals) < 5.4 else "monitor"})

        telo = [s for s in genome_snps if "telomere" in (s.get("summary", "") + " " + s.get("category", "")).lower()]
        if telo:
            unfav = sum(1 for s in telo if s.get("risk_level") == "unfavorable")
            lon["genetic_factors"] = {"telomere_variants": len(telo), "unfavorable": unfav,
                "mitigations": ["stress reduction", "omega-3", "exercise", "sleep optimization"]}

        try:
            whoop = query_source("whoop", (_dt.now() - _td(days=90)).strftime("%Y-%m-%d"), today, lean=True)
            if whoop:
                hrvs = [d.get("hrv") for d in whoop if d.get("hrv")]
                if hrvs:
                    lon["factors"].append({"marker": "90d avg HRV", "value": round(sum(hrvs)/len(hrvs), 1),
                        "unit": "ms", "note": "Higher HRV correlates with longevity"})
        except Exception:
            pass

        good = len([f for f in lon["factors"] if f.get("risk") in ("excellent", "optimal")])
        lon["overall_assessment"] = "strong" if good >= 2 else "moderate"
        result["longevity"] = lon

    return result


def tool_get_next_lab_priorities(args):
    """Genome-informed recommendations for next blood panel."""
    genome = _get_genome_cached()
    genome_snps = [s for s in genome if s.get("sk", "").startswith("GENE#")]
    draws = _query_all_lab_draws()

    recs = []
    existing = set()
    latest_date = None
    if draws:
        latest_date = draws[-1].get("draw_date")
        for d in draws:
            existing.update(d.get("biomarkers", {}).keys())

    mthfr = [s for s in genome_snps if s.get("gene") in ("MTHFR", "MTRR")]
    if mthfr:
        recs.append({"test": "Homocysteine", "priority": "high",
            "reason": f"MTHFR/MTRR variants ({len(mthfr)} SNPs) — impaired methylation",
            "already_tested": "homocysteine" in existing,
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in mthfr],
            "action": "Monitor quarterly; supplement 5-methylfolate + methylcobalamin"})

    vdr = [s for s in genome_snps if s.get("gene") in ("VDR", "GC", "CYP2R1")]
    if vdr:
        has_vitd = any(k for k in existing if "vitamin_d" in k or "25oh" in k)
        recs.append({"test": "Vitamin D (25-OH)", "priority": "high",
            "reason": f"Triple deficiency risk — {len(vdr)} SNPs across VDR/GC/CYP2R1",
            "already_tested": has_vitd,
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in vdr],
            "action": "Target 50-80 ng/mL with D3+K2", "cadence": "quarterly"})

    fads = [s for s in genome_snps if s.get("gene") == "FADS2"]
    if fads:
        recs.append({"test": "Omega-3 Index", "priority": "high",
            "reason": "FADS2 — poor ALA→EPA conversion; need direct EPA/DHA",
            "already_tested": any(k for k in existing if "omega" in k),
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in fads],
            "action": "Target index >8%; supplement EPA/DHA directly"})

    slco = [s for s in genome_snps if s.get("gene") == "SLCO1B1"]
    if slco:
        recs.append({"test": "CK + liver enzymes (pre-statin baseline)", "priority": "medium",
            "reason": "SLCO1B1 statin sensitivity",
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in slco],
            "action": "If statins needed: rosuvastatin/pravastatin only + CoQ10"})

    choline = [s for s in genome_snps if "choline" in (s.get("summary", "") + " " + str(s.get("actionable_recs", ""))).lower()]
    if choline:
        recs.append({"test": "Choline / Betaine / TMAO", "priority": "medium",
            "reason": f"{len(choline)} choline-related variants",
            "action": "Increase dietary choline or supplement phosphatidylcholine"})

    if draws:
        ldl_flags = sum(1 for d in draws if "ldl_c" in d.get("out_of_range", []))
        if ldl_flags >= 2:
            recs.append({"test": "NMR LipoProfile (advanced lipid panel)", "priority": "high",
                "reason": f"LDL-C flagged {ldl_flags}/{len(draws)} draws",
                "action": "LDL particle count + size — more predictive than LDL-C alone",
                "genome_note": "ABCG8 T;T explains genetic LDL elevation"})

    recs.append({"test": "CMP + CBC + HbA1c + lipids", "priority": "routine",
        "reason": "Baseline monitoring", "cadence": "annually", "last_tested": latest_date})

    priority_order = {"high": 0, "medium": 1, "routine": 2}
    return {
        "total_recommendations": len(recs), "latest_draw": latest_date,
        "total_historical_draws": len(draws), "genome_snps_analyzed": len(genome_snps),
        "recommendations": sorted(recs, key=lambda r: priority_order.get(r.get("priority", "routine"), 3)),
        "note": "Data-driven suggestions based on genome + lab history. Discuss with physician."}



# ── Tool registry ─────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# v2.15.0 — Gait, Energy Balance, Movement, CGM tools
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_gait_analysis(args):
    """Gait & mobility analysis from Apple Watch passive measurements."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": f"No Apple Health data for {start_date} to {end_date}."}

    items_sorted = sorted(items, key=lambda x: x.get("date", ""))
    GAIT_FIELDS = ["walking_speed_mph", "walking_step_length_in",
                    "walking_asymmetry_pct", "walking_double_support_pct"]

    rows = []
    for item in items_sorted:
        row = {"date": item.get("date")}
        has_gait = False
        for f in GAIT_FIELDS:
            v = item.get(f)
            if v is not None:
                row[f] = float(v)
                has_gait = True
        if has_gait:
            rows.append(row)

    if not rows:
        return {"error": "No gait data found. Requires Apple Watch + Health Auto Export webhook v1.1.0+."}

    # Period averages
    averages = {}
    for f in GAIT_FIELDS:
        vals = [r[f] for r in rows if f in r]
        if vals:
            averages[f] = round(sum(vals) / len(vals), 2)
            averages[f"{f}_min"] = round(min(vals), 2)
            averages[f"{f}_max"] = round(max(vals), 2)

    # Trend: first half vs second half
    trends = {}
    for f in GAIT_FIELDS:
        vals = [r[f] for r in rows if f in r]
        if len(vals) >= 6:
            mid = len(vals) // 2
            first_avg = sum(vals[:mid]) / mid
            second_avg = sum(vals[mid:]) / (len(vals) - mid)
            pct_change = round((second_avg - first_avg) / first_avg * 100, 1) if first_avg else 0
            improving = (f in ("walking_speed_mph", "walking_step_length_in") and pct_change > 1) or \
                        (f in ("walking_asymmetry_pct", "walking_double_support_pct") and pct_change < -1)
            declining = (f in ("walking_speed_mph", "walking_step_length_in") and pct_change < -1) or \
                        (f in ("walking_asymmetry_pct", "walking_double_support_pct") and pct_change > 1)
            trends[f] = {"first_half_avg": round(first_avg, 2), "second_half_avg": round(second_avg, 2),
                         "pct_change": pct_change, "direction": "improving" if improving else "declining" if declining else "stable"}

    # Clinical flags
    flags = []
    avg_speed = averages.get("walking_speed_mph")
    if avg_speed is not None:
        if avg_speed < 2.24:
            flags.append({"metric": "walking_speed_mph", "severity": "critical",
                          "message": f"Avg speed {avg_speed} mph < 1.0 m/s clinical threshold — strong adverse health predictor."})
        elif avg_speed < 3.0:
            flags.append({"metric": "walking_speed_mph", "severity": "warning",
                          "message": f"Avg speed {avg_speed} mph below optimal. Target >3.0 mph for age <60."})

    avg_asym = averages.get("walking_asymmetry_pct")
    if avg_asym is not None and avg_asym > 4.0:
        flags.append({"metric": "walking_asymmetry_pct", "severity": "warning",
                      "message": f"Avg asymmetry {avg_asym}% > 4% threshold — may indicate injury/compensation."})

    # Asymmetry spike detection
    asym_vals = [r.get("walking_asymmetry_pct") for r in rows if r.get("walking_asymmetry_pct") is not None]
    if len(asym_vals) >= 7:
        baseline_avg = sum(asym_vals[:-3]) / len(asym_vals[:-3])
        recent_avg = sum(asym_vals[-3:]) / 3
        if baseline_avg > 0 and (recent_avg - baseline_avg) / baseline_avg > 0.3:
            flags.append({"metric": "walking_asymmetry_pct", "severity": "alert",
                          "message": f"Asymmetry spike: recent {round(recent_avg, 1)}% vs baseline {round(baseline_avg, 1)}%."})

    speed_trend = trends.get("walking_speed_mph", {})
    if speed_trend.get("direction") == "declining" and abs(speed_trend.get("pct_change", 0)) > 3:
        flags.append({"metric": "walking_speed_mph", "severity": "warning",
                      "message": f"Walking speed declining {abs(speed_trend['pct_change'])}% — early longevity risk signal."})

    # Composite gait score (0-100): speed 40%, step length 30%, asymmetry 20%, double support 10%
    composite = None
    components = {}
    if avg_speed is not None:
        components["speed_score"] = round(max(0, min(100, (avg_speed - 2.0) / 2.0 * 100)), 0)
    avg_step = averages.get("walking_step_length_in")
    if avg_step is not None:
        components["step_length_score"] = round(max(0, min(100, (avg_step - 20) / 12.0 * 100)), 0)
    if avg_asym is not None:
        components["asymmetry_score"] = round(max(0, min(100, (8.0 - avg_asym) / 8.0 * 100)), 0)
    avg_ds = averages.get("walking_double_support_pct")
    if avg_ds is not None:
        components["double_support_score"] = round(max(0, min(100, (35.0 - avg_ds) / 15.0 * 100)), 0)

    if components:
        weights = {"speed_score": 0.4, "step_length_score": 0.3, "asymmetry_score": 0.2, "double_support_score": 0.1}
        ws, tw = 0, 0
        for k, w in weights.items():
            if k in components:
                ws += components[k] * w
                tw += w
        if tw > 0:
            composite = round(ws / tw, 0)

    return {
        "period": {"start": start_date, "end": end_date, "days_with_data": len(rows)},
        "composite_gait_score": composite,
        "composite_components": components if components else None,
        "averages": averages,
        "trends": trends if trends else None,
        "clinical_flags": flags if flags else None,
        "daily": rows[-14:],
        "interpretation": {
            "walking_speed": "Strongest single all-cause mortality predictor. <1.0 m/s (2.24 mph) is clinical flag.",
            "step_length": "Earliest aging gait marker — declines before speed. Track trajectory.",
            "asymmetry": ">3-4% sustained = injury/compensation. Sudden spikes may signal acute injury.",
            "double_support": "Higher = more cautious gait = fall risk indicator.",
            "composite": "0-100 weighted: speed 40%, step length 30%, asymmetry 20%, double support 10%.",
        },
    }


def tool_get_energy_balance(args):
    """Apple Watch TDEE vs MacroFactor intake — daily surplus/deficit."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    target_deficit = args.get("target_deficit_kcal", 500)

    ah_items = query_source("apple_health", start_date, end_date)
    mf_items = query_source("macrofactor", start_date, end_date)
    if not ah_items and not mf_items:
        return {"error": "No Apple Health or MacroFactor data in range."}

    ah_by_date = {i.get("date"): i for i in ah_items if i.get("date")}
    mf_by_date = {i.get("date"): i for i in mf_items if i.get("date")}
    all_dates = sorted(set(list(ah_by_date.keys()) + list(mf_by_date.keys())))

    daily = []
    balance_vals = []
    deficit_hit = 0
    surplus = 0

    for date in all_dates:
        ah = ah_by_date.get(date, {})
        mf = mf_by_date.get(date, {})
        active = ah.get("active_calories")
        basal = ah.get("basal_calories")
        tdee = ah.get("total_calories_burned")
        intake = mf.get("total_calories_kcal")
        if tdee is None and active is not None and basal is not None:
            tdee = float(active) + float(basal)

        row = {"date": date}
        if tdee is not None:
            row["tdee"] = round(float(tdee), 0)
            if active: row["active_calories"] = round(float(active), 0)
            if basal: row["basal_calories"] = round(float(basal), 0)
        if intake is not None:
            row["intake_kcal"] = round(float(intake), 0)
            prot = mf.get("total_protein_g")
            if prot: row["protein_g"] = round(float(prot), 0)
        if tdee is not None and intake is not None:
            bal = round(float(intake) - float(tdee), 0)
            row["balance_kcal"] = bal
            row["status"] = "deficit" if bal < 0 else "surplus"
            balance_vals.append(bal)
            if bal <= -target_deficit: deficit_hit += 1
            if bal > 0: surplus += 1
        daily.append(row)

    paired = len(balance_vals)
    summary = {"paired_days": paired}
    if balance_vals:
        avg_bal = round(sum(balance_vals) / paired, 0)
        summary["avg_daily_balance_kcal"] = avg_bal
        summary["avg_status"] = "deficit" if avg_bal < 0 else "surplus"
        summary["implied_weekly_change_lbs"] = round(avg_bal * 7 / 3500, 2)
        summary["deficit_target_hit_rate_pct"] = round(deficit_hit / paired * 100, 1)
        summary["surplus_days"] = surplus
        summary["surplus_day_pct"] = round(surplus / paired * 100, 1)
        if len(balance_vals) >= 7:
            summary["last_7d_avg_balance"] = round(sum(balance_vals[-7:]) / 7, 0)

    tdee_vals = [float(a.get("total_calories_burned")) for a in ah_by_date.values() if a.get("total_calories_burned")]
    if tdee_vals:
        summary["avg_apple_watch_tdee"] = round(sum(tdee_vals) / len(tdee_vals), 0)
    intake_vals = [float(m.get("total_calories_kcal")) for m in mf_by_date.values() if m.get("total_calories_kcal")]
    if intake_vals:
        summary["avg_intake_kcal"] = round(sum(intake_vals) / len(intake_vals), 0)

    return {
        "period": {"start": start_date, "end": end_date},
        "target_deficit_kcal": target_deficit,
        "summary": summary,
        "daily": daily,
        "note": "TDEE from Apple Watch (active + basal) is more accurate than formula-based BMR. 500 kcal/day deficit ≈ 1 lb/week loss.",
    }


def tool_get_movement_score(args):
    """Daily movement & NEAT analysis."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    step_target = args.get("step_target", 8000)

    sources = parallel_query_sources(["apple_health", "strava"], start_date, end_date)
    ah_items = sources.get("apple_health", [])
    strava_items = sources.get("strava", [])
    if not ah_items:
        return {"error": "No Apple Health data in range."}

    ah_by_date = {i.get("date"): i for i in ah_items if i.get("date")}
    strava_by_date = {i.get("date"): i for i in strava_items if i.get("date")}

    daily = []
    neat_vals = []
    step_vals = []
    sedentary_days = []

    for date in sorted(ah_by_date.keys()):
        ah = ah_by_date[date]
        strava = strava_by_date.get(date, {})
        steps = ah.get("steps")
        flights = ah.get("flights_climbed")
        distance = ah.get("distance_walk_run_miles")
        active_cal = ah.get("active_calories")
        exercise_kj = strava.get("total_kilojoules")
        exercise_kcal = float(exercise_kj) if exercise_kj else 0
        has_workout = int(float(strava.get("activity_count", 0))) > 0

        row = {"date": date, "has_workout": has_workout}
        if steps is not None:
            row["steps"] = int(float(steps))
            step_vals.append(float(steps))
        if flights is not None:
            row["flights_climbed"] = int(float(flights))
        if distance is not None:
            row["distance_miles"] = round(float(distance), 2)
        if active_cal is not None:
            row["active_calories"] = round(float(active_cal), 0)
            neat = max(0, round(float(active_cal) - exercise_kcal, 0))
            row["neat_estimate_kcal"] = neat
            neat_vals.append(neat)
        if steps and float(steps) < 5000 and not has_workout and (active_cal is None or float(active_cal) < 200):
            row["sedentary_flag"] = True
            sedentary_days.append(date)
        daily.append(row)

    summary = {"days_with_data": len(daily)}
    if step_vals:
        summary["avg_daily_steps"] = round(sum(step_vals) / len(step_vals), 0)
        summary["step_target"] = step_target
        summary["step_target_hit_rate_pct"] = round(sum(1 for s in step_vals if s >= step_target) / len(step_vals) * 100, 1)
    if neat_vals:
        summary["avg_neat_kcal"] = round(sum(neat_vals) / len(neat_vals), 0)
        active_vals = [r.get("active_calories") for r in daily if r.get("active_calories")]
        if active_vals:
            avg_active = sum(active_vals) / len(active_vals)
            if avg_active > 0:
                summary["neat_pct_of_active"] = round((sum(neat_vals) / len(neat_vals)) / avg_active * 100, 1)
    summary["sedentary_days"] = len(sedentary_days)
    summary["sedentary_day_pct"] = round(len(sedentary_days) / len(daily) * 100, 1) if daily else 0

    # Movement score per day
    if step_vals and len(step_vals) >= 7:
        baseline_steps = sum(step_vals) / len(step_vals)
        baseline_neat = sum(neat_vals) / len(neat_vals) if neat_vals else 1
        for row in daily:
            c = {}
            s = row.get("steps")
            if s is not None and baseline_steps > 0:
                c["steps"] = min(100, s / (baseline_steps * 1.5) * 100)
            f = row.get("flights_climbed")
            if f is not None:
                c["flights"] = min(100, f / 15 * 100)
            d = row.get("distance_miles")
            if d is not None:
                c["distance"] = min(100, d / 5.0 * 100)
            n = row.get("neat_estimate_kcal")
            if n is not None and baseline_neat > 0:
                c["neat"] = min(100, n / (baseline_neat * 1.5) * 100)
            if c:
                wts = {"steps": 0.5, "flights": 0.15, "distance": 0.15, "neat": 0.2}
                sc, tw = 0, 0
                for k, w in wts.items():
                    if k in c:
                        sc += c[k] * w
                        tw += w
                if tw > 0:
                    row["movement_score"] = round(sc / tw, 0)

    scores = [r["movement_score"] for r in daily if "movement_score" in r]
    if scores:
        summary["avg_movement_score"] = round(sum(scores) / len(scores), 0)

    return {
        "period": {"start": start_date, "end": end_date},
        "summary": summary,
        "sedentary_dates": sedentary_days[-10:] if sedentary_days else None,
        "daily": daily,
        "note": "NEAT is energy burned outside exercise. Sedentary = <5000 steps + no workout + <200 active cal.",
    }


def tool_get_cgm_dashboard(args):
    """CGM glucose daily dashboard from DynamoDB aggregates."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": "No Apple Health data in range."}

    glucose_days = [i for i in sorted(items, key=lambda x: x.get("date", "")) if i.get("blood_glucose_avg") is not None]
    if not glucose_days:
        return {"error": "No blood glucose data in range. Requires Dexcom Stelo + webhook."}

    rows = []
    cgm_ct = 0
    for item in glucose_days:
        row = {
            "date": item.get("date"),
            "avg": round(float(item["blood_glucose_avg"]), 1),
            "min": round(float(item.get("blood_glucose_min", 0)), 1),
            "max": round(float(item.get("blood_glucose_max", 0)), 1),
            "std_dev": round(float(item.get("blood_glucose_std_dev", 0)), 1),
            "readings": int(float(item.get("blood_glucose_readings_count", 0))),
            "time_in_range_pct": round(float(item.get("blood_glucose_time_in_range_pct", 0)), 1),
            "time_above_140_pct": round(float(item.get("blood_glucose_time_above_140_pct", 0)), 1),
            "time_below_70_pct": round(float(item.get("blood_glucose_time_below_70_pct", 0)), 1),
            "source": item.get("cgm_source", "unknown"),
        }
        rows.append(row)
        if item.get("cgm_source") == "dexcom_stelo":
            cgm_ct += 1

    avg_vals = [r["avg"] for r in rows]
    min_vals = [r["min"] for r in rows if r["min"] > 0]
    sd_vals = [r["std_dev"] for r in rows]
    tir_vals = [r["time_in_range_pct"] for r in rows]
    a140 = [r["time_above_140_pct"] for r in rows]

    summary = {
        "total_days": len(rows), "cgm_days": cgm_ct, "manual_days": len(rows) - cgm_ct,
        "avg_glucose": round(sum(avg_vals) / len(avg_vals), 1),
        "avg_fasting_proxy": round(sum(min_vals) / len(min_vals), 1) if min_vals else None,
        "avg_variability_sd": round(sum(sd_vals) / len(sd_vals), 1),
        "avg_time_in_range_pct": round(sum(tir_vals) / len(tir_vals), 1),
        "avg_time_above_140_pct": round(sum(a140) / len(a140), 1),
    }

    flags = []
    if summary["avg_glucose"] > 100:
        flags.append({"severity": "warning", "message": f"Mean glucose {summary['avg_glucose']} > 100 mg/dL optimal threshold."})
    if summary["avg_variability_sd"] > 25:
        flags.append({"severity": "warning", "message": f"Glucose variability SD {summary['avg_variability_sd']} > 25 target. Large postprandial spikes."})
    if summary["avg_time_in_range_pct"] < 90:
        flags.append({"severity": "warning", "message": f"Time in range {summary['avg_time_in_range_pct']}% < 90% target."})
    fp = summary.get("avg_fasting_proxy")
    if fp and fp > 100:
        flags.append({"severity": "warning", "message": f"Fasting proxy {fp} > 100 mg/dL. Target <90."})

    trend = None
    if len(avg_vals) >= 6:
        mid = len(avg_vals) // 2
        f_avg = sum(avg_vals[:mid]) / mid
        s_avg = sum(avg_vals[mid:]) / (len(avg_vals) - mid)
        pct = round((s_avg - f_avg) / f_avg * 100, 1) if f_avg else 0
        trend = {"first_half": round(f_avg, 1), "second_half": round(s_avg, 1), "pct_change": pct,
                 "direction": "improving" if pct < -2 else "worsening" if pct > 2 else "stable"}

    return {
        "period": {"start": start_date, "end": end_date},
        "summary": summary, "trend": trend, "clinical_flags": flags if flags else None, "daily": rows,
        "note": "Targets: mean <100, SD <20, TIR >90%, fasting <90. Time above 140 triggers insulin + inflammation.",
    }


def tool_get_glucose_sleep_correlation(args):
    """Correlate daily glucose with same-night Eight Sleep metrics."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    sources = parallel_query_sources(["apple_health", "eightsleep"], start_date, end_date)
    ah_items = sources.get("apple_health", [])
    es_items = sources.get("eightsleep", [])
    if not ah_items: return {"error": "No Apple Health data."}
    if not es_items: return {"error": "No Eight Sleep data."}

    es_by_date = {i.get("date"): i for i in es_items if i.get("date")}
    def _sf(v):
        if v is None: return None
        try: return float(v)
        except: return None

    SLEEP_METRICS = ["sleep_efficiency_pct", "deep_pct", "rem_pct", "sleep_score", "hrv", "time_to_sleep_min"]

    paired = []
    for item in sorted(ah_items, key=lambda x: x.get("date", "")):
        date = item.get("date")
        g_avg = _sf(item.get("blood_glucose_avg"))
        if not date or g_avg is None: continue
        sleep = es_by_date.get(date)
        if not sleep: continue
        sm_vals = {sm: _sf(sleep.get(sm)) for sm in SLEEP_METRICS}
        if sm_vals.get("sleep_efficiency_pct") is None and sm_vals.get("sleep_score") is None: continue

        bucket = "optimal_below_90" if g_avg < 90 else "normal_90_100" if g_avg < 100 else "elevated_100_110" if g_avg < 110 else "high_above_110"
        row = {"date": date, "bucket": bucket, "glucose_avg": g_avg,
               "glucose_sd": _sf(item.get("blood_glucose_std_dev")),
               "time_above_140": _sf(item.get("blood_glucose_time_above_140_pct"))}
        row.update(sm_vals)
        paired.append(row)

    if len(paired) < 5:
        return {"error": f"Only {len(paired)} paired days. Need >= 5."}

    buckets = defaultdict(list)
    for r in paired:
        buckets[r["bucket"]].append(r)

    bucket_summary = {}
    for bname, brows in sorted(buckets.items()):
        stats = {"n": len(brows)}
        for sm in SLEEP_METRICS:
            vals = [r[sm] for r in brows if r.get(sm) is not None]
            if vals: stats[f"avg_{sm}"] = round(sum(vals) / len(vals), 1)
        bucket_summary[bname] = stats

    correlations = {}
    for gm in ["glucose_avg", "glucose_sd", "time_above_140"]:
        for sm in SLEEP_METRICS:
            xs = [r[gm] for r in paired if r.get(gm) is not None and r.get(sm) is not None]
            ys = [r[sm] for r in paired if r.get(gm) is not None and r.get(sm) is not None]
            if len(xs) >= 7:
                r_val = pearson_r(xs, ys)
                if r_val is not None:
                    correlations[f"{gm}_vs_{sm}"] = round(r_val, 3)

    strong = {k: v for k, v in correlations.items() if abs(v) >= 0.2}

    return {
        "period": {"start": start_date, "end": end_date, "paired_days": len(paired)},
        "bucket_analysis": bucket_summary, "correlations": correlations,
        "notable_correlations": strong if strong else None, "daily": paired[-14:],
        "interpretation": "Negative r between glucose and sleep quality means higher glucose = worse sleep. "
                          "Time above 140 is most actionable — spikes raise core temperature, opposing deep sleep.",
    }


def tool_get_glucose_exercise_correlation(args):
    """Exercise vs rest day glucose comparison + intensity analysis."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    sources = parallel_query_sources(["apple_health", "strava"], start_date, end_date)
    ah_items = sources.get("apple_health", [])
    strava_items = sources.get("strava", [])
    if not ah_items: return {"error": "No Apple Health data."}

    ah_by_date = {i.get("date"): i for i in ah_items if i.get("date")}
    strava_by_date = {i.get("date"): i for i in strava_items if i.get("date")}
    def _sf(v):
        if v is None: return None
        try: return float(v)
        except: return None

    GM = ["glucose_avg", "glucose_sd", "time_in_range_pct", "time_above_140_pct", "glucose_min"]
    exercise_days = []
    rest_days = []

    for date in sorted(ah_by_date.keys()):
        ah = ah_by_date[date]
        g_avg = _sf(ah.get("blood_glucose_avg"))
        if g_avg is None: continue
        strava = strava_by_date.get(date, {})
        has_ex = int(float(strava.get("activity_count", 0))) > 0

        row = {"date": date, "glucose_avg": g_avg, "glucose_sd": _sf(ah.get("blood_glucose_std_dev")),
               "glucose_min": _sf(ah.get("blood_glucose_min")), "time_in_range_pct": _sf(ah.get("blood_glucose_time_in_range_pct")),
               "time_above_140_pct": _sf(ah.get("blood_glucose_time_above_140_pct"))}

        if has_ex:
            row["moving_time_min"] = round(float(strava.get("total_moving_time_seconds", 0)) / 60, 0)
            activities = strava.get("activities", [])
            hr_vals = [float(a["average_heartrate"]) for a in activities if a.get("average_heartrate")]
            if hr_vals: row["avg_hr"] = round(sum(hr_vals) / len(hr_vals), 0)
            exercise_days.append(row)
        else:
            rest_days.append(row)

    if not exercise_days and not rest_days:
        return {"error": "No days with both glucose + activity data."}

    comparison = {}
    for gm in GM:
        ex_v = [r[gm] for r in exercise_days if r.get(gm) is not None]
        re_v = [r[gm] for r in rest_days if r.get(gm) is not None]
        c = {}
        if ex_v: c["exercise_avg"] = round(sum(ex_v) / len(ex_v), 1); c["exercise_n"] = len(ex_v)
        if re_v: c["rest_avg"] = round(sum(re_v) / len(re_v), 1); c["rest_n"] = len(re_v)
        if ex_v and re_v:
            d = c["exercise_avg"] - c["rest_avg"]
            c["difference"] = round(d, 1)
            c["exercise_better"] = d > 0 if gm == "time_in_range_pct" else d < 0
        if c: comparison[gm] = c

    intensity = None
    hr_days = [r for r in exercise_days if r.get("avg_hr")]
    if len(hr_days) >= 5:
        easy = [r for r in hr_days if r["avg_hr"] < 140]
        hard = [r for r in hr_days if r["avg_hr"] >= 140]
        intensity = {}
        for label, grp in [("easy_below_140bpm", easy), ("hard_above_140bpm", hard)]:
            if len(grp) >= 2:
                st = {"n": len(grp)}
                for gm in GM:
                    vals = [r[gm] for r in grp if r.get(gm) is not None]
                    if vals: st[f"avg_{gm}"] = round(sum(vals) / len(vals), 1)
                intensity[label] = st

    correlations = {}
    for gm in GM:
        xs = [r.get("moving_time_min") for r in exercise_days if r.get("moving_time_min") and r.get(gm)]
        ys = [r[gm] for r in exercise_days if r.get("moving_time_min") and r.get(gm)]
        if len(xs) >= 7:
            rv = pearson_r(xs, ys)
            if rv is not None: correlations[f"duration_vs_{gm}"] = round(rv, 3)

    return {
        "period": {"start": start_date, "end": end_date,
                   "exercise_days": len(exercise_days), "rest_days": len(rest_days)},
        "exercise_vs_rest": comparison, "intensity_analysis": intensity,
        "correlations": correlations if correlations else None,
        "interpretation": "Exercise lowers glucose via GLUT4 uptake for 24-48h post. Zone 2 has strongest chronic benefit. "
                          "Look for lower avg, lower SD, higher TIR on exercise vs rest days.",
    }



# ── Journal tools (v2.16.0) ──────────────────────────────────────────────────

def _query_journal(start_date, end_date, template=None):
    """Query journal entries from DynamoDB. Returns list of items."""
    pk = f"{USER_PREFIX}notion"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}#journal",
            f"DATE#{end_date}#journal#~"
        ),
        "ScanIndexForward": True,
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # Filter to journal items only
    items = [i for i in items if "#journal#" in i.get("sk", "")]

    # Optional template filter
    if template:
        template_lower = template.lower().replace(" ", "_").replace("-", "_")
        alias_map = {
            "morning": "morning", "evening": "evening", "weekly": "weekly",
            "weekly_reflection": "weekly", "stressor": "stressor",
            "health_event": "health", "health": "health",
        }
        sk_suffix = alias_map.get(template_lower, template_lower)
        items = [i for i in items if f"#journal#{sk_suffix}" in i.get("sk", "")]

    return [decimal_to_float(i) for i in items]


def tool_get_journal_entries(args):
    """Retrieve journal entries for a date range with optional template filter."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    template = args.get("template")
    include_enriched = args.get("include_enriched", True)

    items = _query_journal(start, end, template)

    if not items:
        return {"entries": [], "count": 0, "date_range": f"{start} to {end}",
                "message": "No journal entries found. Start journaling in Notion!"}

    # Optionally strip enriched fields for cleaner output
    if not include_enriched:
        for item in items:
            keys_to_remove = [k for k in item if k.startswith("enriched_")]
            for k in keys_to_remove:
                del item[k]

    # Remove internal fields
    for item in items:
        item.pop("pk", None)
        item.pop("sk", None)
        item.pop("raw_text", None)  # Haiku sees this, user doesn't need it

    return {
        "entries": items,
        "count": len(items),
        "date_range": f"{start} to {end}",
        "templates_found": list(set(i.get("template", "") for i in items)),
    }


def tool_search_journal(args):
    """Full-text search across journal entries."""
    query = args.get("query", "").lower().strip()
    if not query:
        raise ValueError("query parameter is required")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", "2020-01-01")
    end = args.get("end_date", today)

    items = _query_journal(start, end)

    # Search across raw_text and enriched fields
    matches = []
    keywords = query.split()

    for item in items:
        searchable = " ".join([
            str(item.get("raw_text", "")),
            " ".join(item.get("enriched_themes", [])),
            " ".join(item.get("enriched_emotions", [])),
            " ".join(item.get("enriched_avoidance_flags", [])),
            " ".join(item.get("enriched_growth_signals", [])),
            " ".join(item.get("enriched_pain", [])),
            str(item.get("enriched_notable_quote", "")),
            str(item.get("enriched_sleep_context", "")),
            str(item.get("enriched_exercise_context", "")),
            " ".join(item.get("enriched_values_lived", [])),
            " ".join(item.get("enriched_cognitive_patterns", [])),
        ]).lower()

        if all(kw in searchable for kw in keywords):
            # Build a concise match summary
            match = {
                "date": item.get("date"),
                "template": item.get("template"),
                "enriched_mood": item.get("enriched_mood"),
                "enriched_stress": item.get("enriched_stress"),
                "enriched_themes": item.get("enriched_themes"),
                "enriched_emotions": item.get("enriched_emotions"),
                "enriched_notable_quote": item.get("enriched_notable_quote"),
            }
            # Add template-specific highlights
            for field in ["win_of_the_day", "what_drained_me", "notable_events",
                          "what_happened", "notes", "todays_intention", "gratitude",
                          "avoiding", "biggest_win", "biggest_challenge", "description"]:
                if field in item and item[field]:
                    match[field] = item[field]
            matches.append(match)

    return {
        "query": query,
        "matches": [decimal_to_float(m) for m in matches],
        "count": len(matches),
        "date_range": f"{start} to {end}",
    }


def tool_get_mood_trend(args):
    """Mood/energy/stress scores over time with enriched signals."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    metric = args.get("metric", "all")  # mood|energy|stress|all

    items = _query_journal(start, end)

    if not items:
        return {"trend": [], "message": "No journal entries found for this period."}

    # Build daily scores (prefer enriched, fall back to structured)
    daily = {}  # date -> {mood, energy, stress, themes, sentiment}
    for item in items:
        date = item.get("date")
        if not date:
            continue
        if date not in daily:
            daily[date] = {"date": date, "entries": 0}

        daily[date]["entries"] += 1
        template = item.get("template", "")

        # Mood: enriched > morning_mood > day_rating
        mood = item.get("enriched_mood") or item.get("morning_mood") or item.get("day_rating")
        if mood and ("mood" not in daily[date] or template == "Evening"):
            daily[date]["mood"] = float(mood) if mood else None

        # Energy: enriched > morning_energy > energy_eod
        energy = item.get("enriched_energy") or item.get("morning_energy") or item.get("energy_eod")
        if energy and ("energy" not in daily[date] or template == "Evening"):
            daily[date]["energy"] = float(energy) if energy else None

        # Stress: enriched > stress_level
        stress = item.get("enriched_stress") or item.get("stress_level")
        if stress and ("stress" not in daily[date] or template == "Evening"):
            daily[date]["stress"] = float(stress) if stress else None

        # Themes and sentiment from enrichment
        themes = item.get("enriched_themes", [])
        if themes:
            daily[date].setdefault("themes", []).extend(themes)

        sentiment = item.get("enriched_sentiment")
        if sentiment:
            daily[date]["sentiment"] = sentiment

        quote = item.get("enriched_notable_quote")
        if quote:
            daily[date]["notable_quote"] = quote

    trend = sorted(daily.values(), key=lambda x: x["date"])

    # Compute rolling 7-day averages
    for metric_name in ["mood", "energy", "stress"]:
        values = [(i, d.get(metric_name)) for i, d in enumerate(trend) if d.get(metric_name) is not None]
        for idx, val in values:
            window = [v for j, v in values if idx - 6 <= j <= idx]
            if window:
                trend[idx][f"{metric_name}_7d_avg"] = round(sum(window) / len(window), 2)

    # Summary stats
    summary = {}
    for metric_name in ["mood", "energy", "stress"]:
        vals = [d.get(metric_name) for d in trend if d.get(metric_name) is not None]
        if vals:
            summary[metric_name] = {
                "avg": round(sum(vals) / len(vals), 2),
                "min": min(vals),
                "max": max(vals),
                "latest": vals[-1],
                "days_tracked": len(vals),
            }
            # Trend direction (first half vs second half)
            if len(vals) >= 4:
                mid = len(vals) // 2
                first_avg = sum(vals[:mid]) / mid
                second_avg = sum(vals[mid:]) / (len(vals) - mid)
                delta = second_avg - first_avg
                if metric_name == "stress":
                    # For stress, down is good
                    direction = "improving" if delta < -0.3 else "worsening" if delta > 0.3 else "stable"
                else:
                    direction = "improving" if delta > 0.3 else "declining" if delta < -0.3 else "stable"
                summary[metric_name]["trend_direction"] = direction
                summary[metric_name]["half_delta"] = round(delta, 2)

    # Top recurring themes
    all_themes = []
    for d in trend:
        all_themes.extend(d.get("themes", []))
    theme_counts = {}
    for t in all_themes:
        theme_counts[t] = theme_counts.get(t, 0) + 1
    top_themes = sorted(theme_counts.items(), key=lambda x: -x[1])[:5]

    result = {
        "trend": trend,
        "summary": summary,
        "top_themes": [{"theme": t, "count": c} for t, c in top_themes],
        "days_with_entries": len(trend),
        "date_range": f"{start} to {end}",
    }

    # Filter to requested metric if not "all"
    if metric != "all" and metric in summary:
        result["summary"] = {metric: summary[metric]}

    return result


def tool_get_journal_insights(args):
    """Cross-entry pattern analysis — the 'so what?' tool."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)

    items = _query_journal(start, end)

    if not items:
        return {"message": "No journal entries found. Start journaling to unlock insights!"}

    # Aggregate enriched signals
    emotions_all = []
    themes_all = []
    patterns_all = []
    growth_all = []
    avoidance_all = []
    values_all = []
    gratitude_all = []
    pain_all = []

    mood_scores = []
    energy_scores = []
    stress_scores = []
    ownership_scores = []
    social_entries = []
    flow_count = 0
    alcohol_days = 0
    total_days = set()
    quotes = []

    for item in items:
        date = item.get("date", "")
        total_days.add(date)

        emotions_all.extend(item.get("enriched_emotions", []))
        themes_all.extend(item.get("enriched_themes", []))
        patterns_all.extend(item.get("enriched_cognitive_patterns", []))
        growth_all.extend(item.get("enriched_growth_signals", []))
        avoidance_all.extend(item.get("enriched_avoidance_flags", []))
        values_all.extend(item.get("enriched_values_lived", []))
        gratitude_all.extend(item.get("enriched_gratitude", []))
        pain_all.extend(item.get("enriched_pain", []))

        mood = item.get("enriched_mood")
        if mood: mood_scores.append(float(mood))
        energy = item.get("enriched_energy")
        if energy: energy_scores.append(float(energy))
        stress = item.get("enriched_stress")
        if stress: stress_scores.append(float(stress))
        ownership = item.get("enriched_ownership")
        if ownership: ownership_scores.append(float(ownership))

        social = item.get("enriched_social_quality")
        if social: social_entries.append(social)

        if item.get("enriched_flow"): flow_count += 1
        if item.get("enriched_alcohol"): alcohol_days += 1

        quote = item.get("enriched_notable_quote")
        if quote: quotes.append({"date": date, "quote": quote})

    def rank_items(items_list, top_n=8):
        counts = {}
        for i in items_list:
            counts[i] = counts.get(i, 0) + 1
        return [{"item": k, "count": v} for k, v in
                sorted(counts.items(), key=lambda x: -x[1])[:top_n]]

    def avg(vals):
        return round(sum(vals) / len(vals), 2) if vals else None

    # Cognitive pattern breakdown
    positive_patterns = ["reframing", "growth mindset", "self-compassion", "perspective-taking"]
    neg_patterns = [p for p in patterns_all if p not in positive_patterns]
    pos_patterns = [p for p in patterns_all if p in positive_patterns]

    # Social quality distribution
    social_dist = {}
    for s in social_entries:
        social_dist[s] = social_dist.get(s, 0) + 1

    result = {
        "date_range": f"{start} to {end}",
        "total_entries": len(items),
        "days_with_entries": len(total_days),

        "scores": {
            "mood_avg": avg(mood_scores),
            "energy_avg": avg(energy_scores),
            "stress_avg": avg(stress_scores),
            "ownership_avg": avg(ownership_scores),
        },

        "top_emotions": rank_items(emotions_all),
        "top_themes": rank_items(themes_all),
        "top_values_lived": rank_items(values_all),

        "cognitive_patterns": {
            "negative": rank_items(neg_patterns, 5),
            "positive": rank_items(pos_patterns, 5),
            "total_flags": len(patterns_all),
        },

        "growth_signals": rank_items(growth_all, 5),
        "avoidance_flags": rank_items(avoidance_all, 5),

        "social_connection": {
            "distribution": social_dist,
            "entries_with_social": len(social_entries),
        },

        "flow_states": {
            "count": flow_count,
            "pct_of_entries": round(flow_count / len(items) * 100, 1) if items else 0,
        },

        "gratitude": {
            "unique_items": len(set(gratitude_all)),
            "top_items": rank_items(gratitude_all, 5),
        },

        "pain_flags": rank_items(pain_all, 5),

        "alcohol_days": alcohol_days,

        "notable_quotes": quotes[-5:],  # Last 5 quotes
    }

    return result


def tool_get_journal_correlations(args):
    """Correlate journal signals with wearable data."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    signal = args.get("signal", "all")  # stress|mood|energy|sleep_quality|all

    # Get journal data
    journal_items = _query_journal(start, end)
    if not journal_items:
        return {"message": "No journal entries found for correlation analysis."}

    # Build daily journal scores
    journal_by_date = {}
    for item in journal_items:
        date = item.get("date")
        if not date:
            continue
        if date not in journal_by_date:
            journal_by_date[date] = {}
        jd = journal_by_date[date]

        # Take enriched scores where available, fall back to structured
        for field, enriched_key, structured_keys in [
            ("mood", "enriched_mood", ["morning_mood", "day_rating"]),
            ("energy", "enriched_energy", ["morning_energy", "energy_eod"]),
            ("stress", "enriched_stress", ["stress_level"]),
            ("sleep_quality", None, ["subjective_sleep_quality"]),
        ]:
            if field in jd:
                continue
            val = item.get(enriched_key) if enriched_key else None
            if not val:
                for sk in structured_keys:
                    val = item.get(sk)
                    if val:
                        break
            if val:
                jd[field] = float(val)

    # Get wearable data for same dates
    wearable_sources = {
        "whoop": ["recovery_score", "hrv", "resting_heart_rate", "strain"],
        "eightsleep": ["sleep_score", "sleep_efficiency", "total_sleep_seconds"],
        "garmin": ["avg_stress", "body_battery_end", "training_readiness"],
    }

    wearable_by_date = {}
    for source, fields in wearable_sources.items():
        source_items = query_source_range(source, start, end)
        for item in source_items:
            date = item.get("date")
            if not date:
                continue
            wearable_by_date.setdefault(date, {})
            for f in fields:
                val = item.get(f)
                if val is not None:
                    wearable_by_date[date][f"{source}_{f}"] = float(val)

    # Build paired observations for correlation
    correlations = {}
    journal_signals = ["mood", "energy", "stress", "sleep_quality"]
    if signal != "all":
        journal_signals = [signal]

    for js in journal_signals:
        for wearable_field in sorted(set(f for d in wearable_by_date.values() for f in d)):
            pairs = []
            for date in journal_by_date:
                j_val = journal_by_date[date].get(js)
                w_val = (wearable_by_date.get(date) or {}).get(wearable_field)
                if j_val is not None and w_val is not None:
                    pairs.append((j_val, w_val))

            if len(pairs) >= 5:
                # Compute Pearson r
                n = len(pairs)
                sum_x = sum(p[0] for p in pairs)
                sum_y = sum(p[1] for p in pairs)
                sum_xy = sum(p[0] * p[1] for p in pairs)
                sum_x2 = sum(p[0] ** 2 for p in pairs)
                sum_y2 = sum(p[1] ** 2 for p in pairs)

                denom = math.sqrt((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2))
                if denom > 0:
                    r = (n * sum_xy - sum_x * sum_y) / denom
                    strength = "strong" if abs(r) > 0.5 else "moderate" if abs(r) > 0.3 else "weak"
                    direction = "positive" if r > 0 else "negative"

                    correlations.setdefault(js, []).append({
                        "wearable_metric": wearable_field,
                        "pearson_r": round(r, 3),
                        "strength": strength,
                        "direction": direction,
                        "n": n,
                    })

    # Sort by absolute correlation strength
    for js in correlations:
        correlations[js].sort(key=lambda x: -abs(x["pearson_r"]))

    # Notable divergences (subjective vs objective)
    divergences = []
    for date in journal_by_date:
        j = journal_by_date[date]
        w = wearable_by_date.get(date, {})

        # Sleep quality divergence: low subjective + high objective (or vice versa)
        subj_sleep = j.get("sleep_quality")
        obj_sleep = w.get("eightsleep_sleep_score")
        if subj_sleep and obj_sleep:
            if subj_sleep <= 2 and obj_sleep >= 80:
                divergences.append({
                    "date": date, "type": "sleep_misperception_negative",
                    "subjective": subj_sleep, "objective": obj_sleep,
                    "note": "Felt terrible but objective sleep was good — possible sleep state misperception",
                })
            elif subj_sleep >= 4 and obj_sleep <= 60:
                divergences.append({
                    "date": date, "type": "sleep_misperception_positive",
                    "subjective": subj_sleep, "objective": obj_sleep,
                    "note": "Felt great but objective sleep was poor — may not be reading body signals accurately",
                })

        # Stress divergence: high journal stress + high Whoop recovery
        subj_stress = j.get("stress")
        obj_recovery = w.get("whoop_recovery_score")
        if subj_stress and obj_recovery:
            if subj_stress >= 4 and obj_recovery >= 80:
                divergences.append({
                    "date": date, "type": "psychological_not_physiological",
                    "subjective_stress": subj_stress, "whoop_recovery": obj_recovery,
                    "note": "High perceived stress but body recovering well — likely psychological, not physical",
                })

    return {
        "date_range": f"{start} to {end}",
        "journal_days": len(journal_by_date),
        "wearable_days": len(wearable_by_date),
        "paired_days": len(set(journal_by_date) & set(wearable_by_date)),
        "correlations": correlations,
        "notable_divergences": divergences[:10],
    }


def query_source_range(source, start_date, end_date):
    """Helper: query a source for a date range."""
    pk = f"{USER_PREFIX}{source}"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}"
        ),
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [decimal_to_float(i) for i in items]



def tool_get_training_recommendation(args):
    """
    Readiness-based training recommendation. Synthesizes recovery state, training
    load, recent activity history, muscle group recency, and sleep quality into
    a specific workout suggestion with Board of Directors rationale.

    Based on Galpin (training periodization), Huberman (recovery science),
    Attia (longevity training framework), Seiler (polarized training).
    """
    target_date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d14_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    d3_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Readiness signals ─────────────────────────────────────────────────
    readiness = {}

    # Whoop recovery
    whoop_items = query_source("whoop", d7_start, target_date)
    whoop_sorted = sorted(whoop_items, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)
    if whoop_today:
        readiness["whoop_recovery"] = _sf(whoop_today["recovery_score"])
        readiness["whoop_hrv"] = _sf(whoop_today.get("hrv"))
        readiness["whoop_rhr"] = _sf(whoop_today.get("resting_heart_rate"))
        readiness["whoop_strain_yesterday"] = _sf(whoop_today.get("strain"))

    # Eight Sleep
    es_items = query_source("eightsleep", d3_start, target_date)
    es_sorted = sorted(es_items, key=lambda x: x.get("date", ""), reverse=True)
    es_today = next((s for s in es_sorted if s.get("sleep_score") is not None), None)
    if es_today:
        readiness["sleep_score"] = _sf(es_today["sleep_score"])
        readiness["sleep_efficiency"] = _sf(es_today.get("sleep_efficiency_pct"))
        readiness["sleep_duration"] = _sf(es_today.get("sleep_duration_hours"))
        readiness["deep_pct"] = _sf(es_today.get("deep_pct"))
        readiness["rem_pct"] = _sf(es_today.get("rem_pct"))

    # Garmin Body Battery
    garmin_items = query_source("garmin", d3_start, target_date)
    garmin_sorted = sorted(garmin_items, key=lambda x: x.get("date", ""), reverse=True)
    garmin_today = next((g for g in garmin_sorted if g.get("body_battery_high") is not None), None)
    if garmin_today:
        readiness["body_battery"] = _sf(garmin_today.get("body_battery_high")) or _sf(garmin_today.get("body_battery_end"))
        readiness["garmin_stress"] = _sf(garmin_today.get("avg_stress"))
        readiness["training_readiness_garmin"] = _sf(garmin_today.get("training_readiness"))

    # ── 2. Training load context ─────────────────────────────────────────────
    training_context = {}
    try:
        load_result = tool_get_training_load({"end_date": target_date})
        if "current_state" in load_result:
            cs = load_result["current_state"]
            training_context["ctl"] = cs.get("ctl_fitness")
            training_context["atl"] = cs.get("atl_fatigue")
            training_context["tsb"] = cs.get("tsb_form")
            training_context["acwr"] = cs.get("acwr")
            training_context["form_status"] = cs.get("form_status")
            training_context["injury_risk"] = cs.get("injury_risk")
    except Exception:
        pass

    # ── 3. Recent activity history ───────────────────────────────────────────
    strava_items = query_source("strava", d14_start, target_date)
    strava_by_date = {}
    for item in strava_items:
        d = item.get("date")
        if d:
            strava_by_date[d] = item

    # Activity patterns over last 7 days
    recent_activities = []
    last_cardio_date = None
    last_strength_date = None
    last_hard_date = None
    consecutive_rest_days = 0
    consecutive_training_days = 0

    dates_7d = sorted(strava_by_date.keys())[-7:]
    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical",
                    "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}

    for i, date in enumerate(sorted(strava_by_date.keys(), reverse=True)):
        if date > target_date:
            continue
        day = strava_by_date[date]
        acts = day.get("activities", [])

        for act in acts:
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            avg_hr = _sf(act.get("average_heartrate"))
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:  # skip <10 min
                continue

            is_cardio = sport in cardio_types
            is_strength = sport in strength_types
            is_hard = avg_hr is not None and avg_hr > max_hr * 0.8

            if is_cardio and (last_cardio_date is None or date > last_cardio_date):
                last_cardio_date = date
            if is_strength and (last_strength_date is None or date > last_strength_date):
                last_strength_date = date
            if is_hard and (last_hard_date is None or date > last_hard_date):
                last_hard_date = date

            recent_activities.append({
                "date": date,
                "sport": act.get("sport_type") or act.get("type"),
                "duration_min": round(elapsed / 60, 1),
                "avg_hr": avg_hr,
                "is_hard": is_hard,
            })

    # Consecutive rest/training days
    check_date = datetime.strptime(target_date, "%Y-%m-%d")
    for i in range(7):
        d = (check_date - timedelta(days=i+1)).strftime("%Y-%m-%d")
        day_data = strava_by_date.get(d, {})
        acts = day_data.get("activities", [])
        real_acts = [a for a in acts if (_sf(a.get("elapsed_time_seconds")) or 0) >= 600]
        if real_acts:
            if i == 0:
                consecutive_training_days = 1
            elif consecutive_training_days > 0:
                consecutive_training_days += 1
            else:
                break
        else:
            if i == 0:
                consecutive_rest_days = 1
            elif consecutive_rest_days > 0:
                consecutive_rest_days += 1
            else:
                break

    # Days since last activities
    def _days_since(d):
        if d is None: return None
        return (datetime.strptime(target_date, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days

    days_since_cardio = _days_since(last_cardio_date)
    days_since_strength = _days_since(last_strength_date)
    days_since_hard = _days_since(last_hard_date)

    # ── 4. Muscle group recency from strength data ───────────────────────────
    muscle_last_trained = {}
    mf_workout_items = query_source("macrofactor_workouts", d14_start, target_date)
    for item in mf_workout_items:
        d = item.get("date")
        for workout in (item.get("workouts") or []):
            for exercise in (workout.get("exercises") or []):
                ename = exercise.get("exercise_name", "")
                cls = classify_exercise(ename)
                for mg in cls["muscle_groups"]:
                    if mg not in muscle_last_trained or d > muscle_last_trained[mg]:
                        muscle_last_trained[mg] = d

    muscle_recovery = {}
    for mg, last_date in muscle_last_trained.items():
        days_ago = _days_since(last_date)
        if days_ago is not None:
            status = "fully_recovered" if days_ago >= 3 else ("recovering" if days_ago >= 1 else "just_trained")
            muscle_recovery[mg] = {"last_trained": last_date, "days_ago": days_ago, "status": status}

    # ── 5. Compute readiness tier ────────────────────────────────────────────
    recovery_score = readiness.get("whoop_recovery")
    sleep_score = readiness.get("sleep_score")
    body_battery = readiness.get("body_battery")
    tsb = training_context.get("tsb")
    acwr = training_context.get("acwr")

    # Composite readiness (0-100)
    signals = []
    if recovery_score is not None: signals.append(recovery_score)
    if sleep_score is not None: signals.append(sleep_score)
    if body_battery is not None: signals.append(body_battery)

    composite = _avg(signals) if signals else 50
    tier = "GREEN" if composite >= 67 else ("YELLOW" if composite >= 33 else "RED")

    # Injury risk override
    if acwr is not None and acwr > 1.5:
        tier = "RED"
    if consecutive_training_days >= 5:
        tier = min(tier, "YELLOW") if tier == "GREEN" else tier

    # ── 6. Generate recommendation ───────────────────────────────────────────
    rec = {}

    if tier == "RED" or composite < 30:
        # Low readiness → rest or very easy
        if consecutive_rest_days >= 2:
            rec = {
                "type": "Active Recovery",
                "intensity": "Very Easy",
                "description": "Light walk, mobility work, or gentle yoga. Keep HR below 60% max.",
                "duration_min": "20-30",
                "hr_ceiling": round(max_hr * 0.6),
            }
        else:
            rec = {
                "type": "Full Rest",
                "intensity": "None",
                "description": "Your body needs recovery. Focus on sleep, nutrition, and stress management.",
                "duration_min": "0",
                "hr_ceiling": None,
            }
    elif tier == "YELLOW":
        # Moderate readiness → Zone 2 or easy strength
        if days_since_cardio is not None and days_since_cardio >= 2:
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy",
                "description": "Steady-state aerobic work. Conversational pace. Build mitochondrial density without taxing recovery.",
                "duration_min": "45-60",
                "hr_ceiling": round(max_hr * 0.7),
                "hr_floor": round(max_hr * 0.6),
            }
        elif days_since_strength is not None and days_since_strength >= 2:
            # Find recovered muscle groups
            recovered = [mg for mg, info in muscle_recovery.items() if info["status"] == "fully_recovered"]
            push_ready = any(mg in recovered for mg in ["Chest", "Shoulders", "Triceps"])
            pull_ready = any(mg in recovered for mg in ["Back", "Biceps"])
            legs_ready = any(mg in recovered for mg in ["Quads", "Glutes", "Hamstrings"])

            if legs_ready:
                target = "Lower Body"
                muscles = [mg for mg in ["Quads", "Glutes", "Hamstrings", "Calves"] if mg in recovered]
            elif push_ready:
                target = "Upper Body Push"
                muscles = [mg for mg in ["Chest", "Shoulders", "Triceps"] if mg in recovered]
            elif pull_ready:
                target = "Upper Body Pull"
                muscles = [mg for mg in ["Back", "Biceps"] if mg in recovered]
            else:
                target = "Full Body (Light)"
                muscles = recovered[:4] if recovered else ["General"]

            rec = {
                "type": f"Strength — {target}",
                "intensity": "Moderate",
                "description": f"Moderate loads, controlled tempo. Focus on {', '.join(muscles)}. Stay 2-3 RIR from failure.",
                "duration_min": "45-60",
                "target_muscles": muscles,
                "rpe_range": "6-7",
            }
        else:
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy",
                "description": "Easy aerobic session. You've been active recently — keep it light today.",
                "duration_min": "30-45",
                "hr_ceiling": round(max_hr * 0.7),
            }
    else:
        # GREEN — full capacity available
        if days_since_hard is not None and days_since_hard >= 3 and (tsb is None or tsb > -5):
            # Ready for hard effort
            if days_since_cardio is not None and days_since_cardio >= 2:
                rec = {
                    "type": "High-Intensity Intervals",
                    "intensity": "Hard",
                    "description": "VO2max work: 4-6 intervals of 3-4 minutes at 85-90% max HR with equal rest. This is the highest-ROI session for cardiovascular fitness.",
                    "duration_min": "40-50",
                    "hr_ceiling": round(max_hr * 0.9),
                    "hr_floor": round(max_hr * 0.85),
                }
            else:
                # Find recovered muscle groups for heavy strength
                recovered = [mg for mg, info in muscle_recovery.items() if info["status"] == "fully_recovered"]
                push_ready = any(mg in recovered for mg in ["Chest", "Shoulders", "Triceps"])
                pull_ready = any(mg in recovered for mg in ["Back", "Biceps"])
                legs_ready = any(mg in recovered for mg in ["Quads", "Glutes", "Hamstrings"])

                if legs_ready:
                    target = "Lower Body"
                    muscles = [mg for mg in ["Quads", "Glutes", "Hamstrings", "Calves"] if mg in recovered]
                elif push_ready:
                    target = "Upper Body Push"
                    muscles = [mg for mg in ["Chest", "Shoulders", "Triceps"] if mg in recovered]
                elif pull_ready:
                    target = "Upper Body Pull"
                    muscles = [mg for mg in ["Back", "Biceps"] if mg in recovered]
                else:
                    target = "Full Body"
                    muscles = recovered[:4] if recovered else ["General"]

                rec = {
                    "type": f"Strength — {target}",
                    "intensity": "Hard",
                    "description": f"Heavy compound lifts. Push to 1-2 RIR on working sets. Target: {', '.join(muscles)}.",
                    "duration_min": "60-75",
                    "target_muscles": muscles,
                    "rpe_range": "8-9",
                }
        else:
            # Green but recent hard session or negative TSB → Zone 2
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy-Moderate",
                "description": "Solid Zone 2 session. You're recovered but had a hard effort recently — build aerobic base without adding fatigue.",
                "duration_min": "45-60",
                "hr_ceiling": round(max_hr * 0.7),
                "hr_floor": round(max_hr * 0.6),
            }

    # ── 7. Warnings ──────────────────────────────────────────────────────────
    warnings = []
    if acwr is not None and acwr > 1.3:
        warnings.append(f"⚠️ ACWR is {acwr} — above 1.3 injury threshold. Reduce training load this week.")
    if consecutive_training_days >= 4:
        warnings.append(f"⚠️ {consecutive_training_days} consecutive training days. Consider a rest day soon.")
    if readiness.get("sleep_duration") and readiness["sleep_duration"] < 6:
        warnings.append(f"⚠️ Only {readiness['sleep_duration']}h sleep — short sleep impairs muscle protein synthesis and injury risk. Reduce intensity.")
    if readiness.get("whoop_hrv") and len([w for w in whoop_items if _sf(w.get("hrv"))]) >= 3:
        hrv_vals = [_sf(w.get("hrv")) for w in whoop_items if _sf(w.get("hrv"))]
        hrv_avg = _avg(hrv_vals)
        if readiness["whoop_hrv"] < hrv_avg * 0.8:
            warnings.append(f"⚠️ HRV ({readiness['whoop_hrv']}ms) is {round((1 - readiness['whoop_hrv']/hrv_avg)*100)}% below your 7-day average. Parasympathetic suppression — reduce intensity.")
    if readiness.get("garmin_stress") and readiness["garmin_stress"] > 50:
        warnings.append(f"⚠️ Garmin stress score {readiness['garmin_stress']} (elevated). Consider how allostatic load affects recovery.")

    # ── 8. Board of Directors rationale ───────────────────────────────────────
    bod_notes = []
    if tier == "GREEN":
        bod_notes.append("Huberman: Full parasympathetic recovery detected. Sympathetic drive available for high-output work.")
        if rec.get("type", "").startswith("Strength"):
            bod_notes.append("Galpin: Mechanical tension (heavy loads, 1-2 RIR) drives hypertrophy most efficiently when recovery is complete.")
        elif "Interval" in rec.get("type", ""):
            bod_notes.append("Attia: VO2max is the single strongest predictor of all-cause mortality. Hard intervals 1-2x/week are the highest-ROI investment.")
    elif tier == "YELLOW":
        bod_notes.append("Attia: Zone 2 is the longevity foundation — 150+ min/week builds mitochondrial density without recovery cost.")
        bod_notes.append("Huberman: Moderate training during partial recovery can still stimulate adaptation without digging a deeper hole.")
    else:
        bod_notes.append("Walker: Sleep debt is cumulative and cannot be repaid by a single night. Prioritize recovery.")
        bod_notes.append("Galpin: Training in a depleted state converts productive stress into destructive stress.")

    # Zone 2 weekly check
    try:
        z2_result = tool_get_zone2_breakdown({"start_date": d7_start, "end_date": target_date})
        if "summary" in z2_result:
            z2_min = z2_result["summary"].get("total_zone2_minutes", 0)
            z2_target = z2_result["summary"].get("weekly_target_minutes", 150)
            z2_pct = round(z2_min / z2_target * 100) if z2_target > 0 else 0
            if z2_pct < 50:
                bod_notes.append(f"Attia: Only {z2_min} of {z2_target} Zone 2 minutes this week ({z2_pct}%). Prioritize Zone 2 sessions.")
    except Exception:
        pass

    return {
        "date": target_date,
        "readiness_tier": tier,
        "composite_readiness": round(composite, 1),
        "recommendation": rec,
        "warnings": warnings,
        "board_of_directors": bod_notes,
        "readiness_signals": readiness,
        "training_context": {
            "days_since_cardio": days_since_cardio,
            "days_since_strength": days_since_strength,
            "days_since_hard_session": days_since_hard,
            "consecutive_rest_days": consecutive_rest_days,
            "consecutive_training_days": consecutive_training_days,
            "training_load": training_context,
        },
        "muscle_recovery": muscle_recovery,
        "recent_activities_7d": recent_activities[:10],
        "source": "whoop + eightsleep + garmin + strava + macrofactor_workouts",
    }



def tool_get_hr_recovery_trend(args):
    """
    Heart rate recovery tracker — strongest exercise-derived mortality predictor.
    Extracts post-peak HR recovery from Strava activity streams, trends over time.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))
    sport_filter = (args.get("sport_type") or "").strip().lower()
    cooldown_only = args.get("cooldown_only", False)

    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    records = []
    for item in strava_items:
        date = item.get("date")
        for act in (item.get("activities") or []):
            hr_rec = act.get("hr_recovery")
            if not hr_rec or not isinstance(hr_rec, dict):
                continue
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport_filter and sport_filter not in sport.replace(" ", ""):
                continue
            has_cooldown = hr_rec.get("has_cooldown", False)
            if cooldown_only and not has_cooldown:
                continue
            peak = _sf(hr_rec.get("hr_peak"))
            recovery_intra = _sf(hr_rec.get("hr_recovery_intra"))
            recovery_60s = _sf(hr_rec.get("hr_recovery_60s"))
            recovery_120s = _sf(hr_rec.get("hr_recovery_120s"))
            best_recovery = recovery_60s or recovery_intra
            if peak is None or best_recovery is None:
                continue
            if best_recovery >= 25: classification = "excellent"
            elif best_recovery >= 18: classification = "good"
            elif best_recovery >= 12: classification = "average"
            else: classification = "below_average"
            records.append({
                "date": date,
                "sport_type": act.get("sport_type") or act.get("type"),
                "activity_name": act.get("name", ""),
                "duration_min": round((_sf(act.get("elapsed_time_seconds")) or 0) / 60, 1),
                "hr_peak": peak,
                "hr_peak_pct_max": round(peak / max_hr * 100, 1) if peak else None,
                "hr_end_60s": _sf(hr_rec.get("hr_end_60s")),
                "hr_recovery_intra": recovery_intra,
                "hr_recovery_60s": recovery_60s,
                "hr_recovery_120s": recovery_120s,
                "has_cooldown": has_cooldown,
                "best_recovery_bpm": best_recovery,
                "classification": classification,
            })

    if not records:
        return {
            "error": "No activities with HR recovery data found. HR recovery requires Strava ingestion v2.35.0+ with stream fetching.",
            "start_date": start_date, "end_date": end_date,
            "tip": "Activities need HR data and >= 10 min duration. Recovery metrics computed from HR streams during ingestion.",
        }

    records.sort(key=lambda r: r["date"])

    mid = len(records) // 2
    first_half = records[:mid] if mid > 0 else records
    second_half = records[mid:] if mid > 0 else records
    first_avg = _avg([r["best_recovery_bpm"] for r in first_half])
    second_avg = _avg([r["best_recovery_bpm"] for r in second_half])

    trend_direction = None
    trend_delta = None
    if first_avg is not None and second_avg is not None:
        trend_delta = round(second_avg - first_avg, 1)
        trend_direction = "improving" if trend_delta > 2 else ("declining" if trend_delta < -2 else "stable")

    date_ordinals = []
    recovery_vals = []
    base_date = datetime.strptime(records[0]["date"], "%Y-%m-%d")
    for r in records:
        d = (datetime.strptime(r["date"], "%Y-%m-%d") - base_date).days
        date_ordinals.append(d)
        recovery_vals.append(r["best_recovery_bpm"])
    r_val = pearson_r(date_ordinals, recovery_vals) if len(date_ordinals) >= 5 else None

    by_sport = {}
    for r in records:
        s = r["sport_type"] or "Unknown"
        if s not in by_sport:
            by_sport[s] = {"activities": 0, "avg_recovery": [], "avg_peak_hr": []}
        by_sport[s]["activities"] += 1
        by_sport[s]["avg_recovery"].append(r["best_recovery_bpm"])
        by_sport[s]["avg_peak_hr"].append(r["hr_peak"])
    sport_summary = {}
    for s, data in by_sport.items():
        sport_summary[s] = {
            "activities": data["activities"],
            "avg_recovery_bpm": _avg(data["avg_recovery"]),
            "avg_peak_hr": _avg(data["avg_peak_hr"]),
        }

    dist = {"excellent": 0, "good": 0, "average": 0, "below_average": 0}
    for r in records:
        dist[r["classification"]] += 1
    total = len(records)
    dist_pct = {k: round(v / total * 100, 1) for k, v in dist.items()}

    sorted_by_recovery = sorted(records, key=lambda r: r["best_recovery_bpm"], reverse=True)
    best_5 = sorted_by_recovery[:5]
    worst_5 = sorted_by_recovery[-5:]

    cooldown_records = [r for r in records if r["has_cooldown"]]
    no_cooldown = [r for r in records if not r["has_cooldown"]]

    overall_avg = _avg([r["best_recovery_bpm"] for r in records])
    if overall_avg and overall_avg >= 25:
        clinical = "Excellent autonomic function. Strong parasympathetic reactivation indicates high cardiovascular fitness."
    elif overall_avg and overall_avg >= 18:
        clinical = "Good HR recovery. Healthy autonomic balance. Continue current training approach."
    elif overall_avg and overall_avg >= 12:
        clinical = "Average HR recovery. Room for improvement — Zone 2 training and stress management will enhance parasympathetic tone."
    elif overall_avg:
        clinical = "Below average HR recovery (<12 bpm). Clinical flag per Cole et al. (NEJM). Discuss with physician."
    else:
        clinical = "Insufficient data for clinical assessment."

    bod = []
    if trend_direction == "improving":
        bod.append(f"Attia: HR recovery improving by {trend_delta} bpm — cardiovascular fitness trending in the right direction.")
    elif trend_direction == "declining":
        bod.append(f"Huberman: HR recovery declining by {abs(trend_delta)} bpm — consider overtraining, sleep debt, or chronic stress.")
    if cooldown_records and no_cooldown:
        bod.append(f"Galpin: {len(cooldown_records)} of {total} activities include cooldown. Adding 5-min easy cooldown improves recovery data reliability.")
    if dist["below_average"] > 0 and dist["below_average"] / total > 0.3:
        bod.append("Attia: >30% of sessions show below-average recovery. Consider reducing volume and prioritizing sleep.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_activities_with_hr_recovery": total,
        "overall_avg_recovery_bpm": overall_avg,
        "clinical_assessment": clinical,
        "trend": {
            "direction": trend_direction, "delta_bpm": trend_delta,
            "first_half_avg": first_avg, "second_half_avg": second_avg,
            "pearson_r": r_val,
            "interpretation": (
                f"HR recovery {'improving' if trend_direction == 'improving' else 'declining' if trend_direction == 'declining' else 'stable'} "
                f"over the period ({'+' if (trend_delta or 0) > 0 else ''}{trend_delta} bpm)."
            ) if trend_delta is not None else None,
        },
        "classification_distribution": dist,
        "classification_distribution_pct": dist_pct,
        "by_sport_type": sport_summary,
        "cooldown_analysis": {
            "activities_with_cooldown": len(cooldown_records),
            "activities_without_cooldown": len(no_cooldown),
            "avg_recovery_with_cooldown": _avg([r["best_recovery_bpm"] for r in cooldown_records]),
            "avg_recovery_without_cooldown": _avg([r["best_recovery_bpm"] for r in no_cooldown]),
            "note": "Activities with cooldown give more reliable HR recovery measurements.",
        },
        "best_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in best_5],
        "worst_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in worst_5],
        "board_of_directors": bod,
        "methodology": (
            "HR recovery computed from Strava HR streams during ingestion. "
            "Peak HR = 30s rolling average max. Recovery = peak minus HR at peak+60s (preferred) "
            "or peak minus last-60s average (fallback). Clinical thresholds per Cole et al. (NEJM 1999): "
            ">25 excellent, 18-25 good, 12-18 average, <12 below average."
        ),
        "source": "strava (HR streams)",
    }



def tool_get_sleep_environment_analysis(args):
    """
    Sleep environment optimization. Correlates Eight Sleep bed temperature
    with sleep outcomes. Huberman: core body temp drop is #1 sleep trigger.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))

    es_items = query_source("eightsleep", start_date, end_date)
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hours", "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
        ("hrv_avg",              "HRV",                "higher_is_better"),
    ]

    records = []
    no_temp_count = 0

    for item in es_items:
        date = item.get("date")
        bed_temp_c = _sf(item.get("bed_temp_c"))
        bed_temp_f = _sf(item.get("bed_temp_f"))
        temp_level = _sf(item.get("temp_level_avg"))
        room_temp_c = _sf(item.get("room_temp_c"))
        room_temp_f = _sf(item.get("room_temp_f"))

        if bed_temp_c is not None and bed_temp_f is None:
            bed_temp_f = round(bed_temp_c * 9/5 + 32, 1)
        if bed_temp_f is not None and bed_temp_c is None:
            bed_temp_c = round((bed_temp_f - 32) * 5/9, 1)

        has_temp = bed_temp_f is not None or temp_level is not None
        if not has_temp:
            no_temp_count += 1
            continue

        eff = _sf(item.get("sleep_efficiency_pct"))
        score = _sf(item.get("sleep_score"))
        if eff is None and score is None:
            continue

        records.append({
            "date": date,
            "bed_temp_f": bed_temp_f, "bed_temp_c": bed_temp_c,
            "room_temp_f": room_temp_f, "room_temp_c": _sf(item.get("room_temp_c")),
            "temp_level": temp_level,
            "temp_level_min": _sf(item.get("temp_level_min")),
            "temp_level_max": _sf(item.get("temp_level_max")),
            "sleep_efficiency_pct": eff,
            "deep_pct": _sf(item.get("deep_pct")),
            "rem_pct": _sf(item.get("rem_pct")),
            "sleep_score": score,
            "sleep_duration_hours": _sf(item.get("sleep_duration_hours")),
            "time_to_sleep_min": _sf(item.get("time_to_sleep_min")),
            "hrv_avg": _sf(item.get("hrv_avg")),
        })

    if not records:
        return {
            "error": f"No nights with temperature data found. {no_temp_count} nights checked.",
            "start_date": start_date, "end_date": end_date,
            "tip": "Temperature data requires Eight Sleep ingestion v2.35.0+ (intervals API). Deploy and wait for new nights.",
        }

    has_bed_temp = sum(1 for r in records if r["bed_temp_f"] is not None)
    has_temp_level = sum(1 for r in records if r["temp_level"] is not None)
    use_bed_temp = has_bed_temp >= len(records) * 0.5
    use_temp_level = has_temp_level >= len(records) * 0.5

    # Bucket analysis by bed temperature (°F)
    bucket_data = {}
    if use_bed_temp:
        TEMP_BUCKETS = [
            ("below_64F", "Below 64°F (< 18°C)", lambda t: t < 64),
            ("64_66F",    "64-66°F (18-19°C)",    lambda t: 64 <= t < 66),
            ("66_68F",    "66-68°F (19-20°C)",    lambda t: 66 <= t < 68),
            ("68_70F",    "68-70°F (20-21°C)",    lambda t: 68 <= t < 70),
            ("70_72F",    "70-72°F (21-22°C)",    lambda t: 70 <= t < 72),
            ("above_72F", "Above 72°F (> 22°C)",  lambda t: t >= 72),
        ]
        for bucket_key, label, condition in TEMP_BUCKETS:
            b_records = [r for r in records if r["bed_temp_f"] is not None and condition(r["bed_temp_f"])]
            if not b_records:
                continue
            bucket_data[bucket_key] = {
                "label": label, "nights": len(b_records),
                "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    bucket_data[bucket_key]["metrics"][field] = {"label": mlabel, "avg": round(sum(vals)/len(vals), 2), "n": len(vals)}

    # Bucket analysis by temp level (-10 to +10)
    level_bucket_data = {}
    if use_temp_level:
        LEVEL_BUCKETS = [
            ("very_cool",  "Very Cool (-10 to -6)", lambda l: l <= -6),
            ("cool",       "Cool (-5 to -2)",       lambda l: -5 <= l <= -2),
            ("neutral",    "Neutral (-1 to +1)",    lambda l: -1 <= l <= 1),
            ("warm",       "Warm (+2 to +5)",       lambda l: 2 <= l <= 5),
            ("very_warm",  "Very Warm (+6 to +10)", lambda l: l >= 6),
        ]
        for bucket_key, label, condition in LEVEL_BUCKETS:
            b_records = [r for r in records if r["temp_level"] is not None and condition(r["temp_level"])]
            if not b_records:
                continue
            level_bucket_data[bucket_key] = {
                "label": label, "nights": len(b_records),
                "avg_level": _avg([r["temp_level"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    level_bucket_data[bucket_key]["metrics"][field] = {"label": mlabel, "avg": round(sum(vals)/len(vals), 2), "n": len(vals)}

    # Pearson correlations
    temp_correlations = {}
    if use_bed_temp:
        temp_rows = [r for r in records if r["bed_temp_f"] is not None]
        for field, label, direction in SLEEP_METRICS:
            xs = [r["bed_temp_f"] for r in temp_rows if r[field] is not None]
            ys = [r[field] for r in temp_rows if r[field] is not None]
            r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
            if r_val is not None:
                if direction == "higher_is_better":
                    impact = "cooler_is_better" if r_val < -0.15 else ("warmer_is_better" if r_val > 0.15 else "no_significant_effect")
                else:
                    impact = "cooler_is_better" if r_val > 0.15 else ("warmer_is_better" if r_val < -0.15 else "no_significant_effect")
                temp_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    level_correlations = {}
    if use_temp_level:
        level_rows = [r for r in records if r["temp_level"] is not None]
        for field, label, direction in SLEEP_METRICS:
            xs = [r["temp_level"] for r in level_rows if r[field] is not None]
            ys = [r[field] for r in level_rows if r[field] is not None]
            r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
            if r_val is not None:
                if direction == "higher_is_better":
                    impact = "cooler_is_better" if r_val < -0.15 else ("warmer_is_better" if r_val > 0.15 else "no_significant_effect")
                else:
                    impact = "cooler_is_better" if r_val > 0.15 else ("warmer_is_better" if r_val < -0.15 else "no_significant_effect")
                level_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # Find optimal temperature
    optimal = {}
    if bucket_data:
        best_bucket = None
        best_eff = 0
        for bk, bv in bucket_data.items():
            eff = (bv.get("metrics", {}).get("sleep_efficiency_pct", {}) or {}).get("avg", 0)
            if eff > best_eff and bv["nights"] >= 3:
                best_eff = eff
                best_bucket = bk
        if best_bucket:
            optimal["by_efficiency"] = {"bucket": bucket_data[best_bucket]["label"], "avg_efficiency": best_eff, "nights": bucket_data[best_bucket]["nights"]}

        best_deep_bucket = None
        best_deep = 0
        for bk, bv in bucket_data.items():
            deep = (bv.get("metrics", {}).get("deep_pct", {}) or {}).get("avg", 0)
            if deep > best_deep and bv["nights"] >= 3:
                best_deep = deep
                best_deep_bucket = bk
        if best_deep_bucket:
            optimal["by_deep_sleep"] = {"bucket": bucket_data[best_deep_bucket]["label"], "avg_deep_pct": best_deep, "nights": bucket_data[best_deep_bucket]["nights"]}

    # Room temperature analysis
    room_analysis = None
    room_records = [r for r in records if r.get("room_temp_f") is not None]
    if room_records:
        room_temps = [r["room_temp_f"] for r in room_records]
        room_analysis = {"avg_room_temp_f": _avg(room_temps), "min_room_temp_f": round(min(room_temps), 1), "max_room_temp_f": round(max(room_temps), 1), "nights_measured": len(room_records)}

    # Board of Directors
    bod = []
    bod.append("Huberman: The single most important environmental factor for sleep is temperature. A 2-3°F core body temperature drop initiates the sleep cascade. Cool the bedroom to 65-68°F.")
    cool_benefit = temp_correlations.get("sleep_efficiency_pct", {}).get("impact")
    if cool_benefit == "cooler_is_better":
        r_val = temp_correlations["sleep_efficiency_pct"]["pearson_r"]
        bod.append(f"Your data confirms: cooler bed temperatures correlate with better sleep efficiency (r={r_val}).")
    elif cool_benefit == "warmer_is_better":
        bod.append("Your data shows warmer temperatures correlating with better sleep — your baseline room may already be quite cool, or you run cold at night.")
    deep_impact = temp_correlations.get("deep_pct", {}).get("impact")
    if deep_impact == "cooler_is_better":
        bod.append("Walker: Deep sleep is most sensitive to temperature. Your data confirms cooler bed temps increase deep sleep %.")
    if optimal.get("by_efficiency"):
        bod.append(f"Attia: Your optimal temperature zone for sleep efficiency is {optimal['by_efficiency']['bucket']} based on {optimal['by_efficiency']['nights']} nights.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_nights_with_temp_data": len(records),
        "nights_without_temp_data": no_temp_count,
        "temperature_summary": {
            "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in records if r["bed_temp_f"]]),
            "avg_bed_temp_c": _avg([r["bed_temp_c"] for r in records if r["bed_temp_c"]]),
            "avg_temp_level": _avg([r["temp_level"] for r in records if r["temp_level"]]),
            "avg_room_temp_f": _avg([r["room_temp_f"] for r in records if r.get("room_temp_f")]),
        },
        "optimal_temperature": optimal,
        "bucket_analysis_bed_temp": bucket_data if bucket_data else None,
        "bucket_analysis_temp_level": level_bucket_data if level_bucket_data else None,
        "correlations_bed_temp": temp_correlations if temp_correlations else None,
        "correlations_temp_level": level_correlations if level_correlations else None,
        "room_temperature": room_analysis,
        "board_of_directors": bod,
        "methodology": (
            "Bed temperature from Eight Sleep intervals API. Sleep metrics from Eight Sleep trends. "
            "Bucket analysis splits nights by temperature range and compares average sleep outcomes. "
            "Pearson correlations quantify linear relationship between temperature and sleep quality. "
            "Optimal temperature = bucket with highest sleep efficiency among buckets with >= 3 nights. "
            "Clinical reference: Huberman/Walker recommend 65-68°F (18-20°C)."
        ),
        "source": "eightsleep (intervals + trends)",
    }



# ══════════════════════════════════════════════════════════════════════════════
# Feature #9: Supplement & Medication Log
# ══════════════════════════════════════════════════════════════════════════════

def tool_log_supplement(args):
    """
    Log a supplement or medication entry. Writes to DynamoDB supplements partition.
    Supports multiple entries per day (appends to existing list).
    """
    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    name = args.get("name", "").strip()
    if not name:
        return {"error": "Supplement name is required."}

    dose = args.get("dose")
    unit = args.get("unit", "")
    timing = args.get("timing", "")  # morning, with_meal, before_bed, etc.
    notes = args.get("notes", "")
    category = args.get("category", "supplement")  # supplement, medication, vitamin, mineral

    entry = {
        "name": name,
        "dose": Decimal(str(dose)) if dose is not None else None,
        "unit": unit,
        "timing": timing,
        "category": category,
        "notes": notes,
        "logged_at": datetime.utcnow().isoformat(),
    }
    # Remove None values
    entry = {k: v for k, v in entry.items() if v is not None and v != ""}

    table = boto3.resource("dynamodb", region_name=_REGION).Table(TABLE_NAME)

    # Try to append to existing record, or create new
    try:
        table.update_item(
            Key={"pk": USER_PREFIX + "supplements", "sk": f"DATE#{date}"},
            UpdateExpression="SET #s = list_append(if_not_exists(#s, :empty), :entry), #d = :date, #src = :src, #ua = :ua",
            ExpressionAttributeNames={"#s": "supplements", "#d": "date", "#src": "source", "#ua": "updated_at"},
            ExpressionAttributeValues={
                ":entry": [entry],
                ":empty": [],
                ":date": date,
                ":src": "supplements",
                ":ua": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        return {"error": f"Failed to log supplement: {e}"}

    dose_str = f" {dose}{unit}" if dose else ""
    timing_str = f" ({timing})" if timing else ""
    return {
        "status": "logged",
        "date": date,
        "entry": f"{name}{dose_str}{timing_str}",
        "message": f"Logged {name}{dose_str}{timing_str} for {date}.",
    }


def tool_get_supplement_log(args):
    """
    Retrieve supplement/medication log for a date range.
    Shows what was taken, dosage, timing, and adherence patterns.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    name_filter = (args.get("name") or "").strip().lower()

    items = query_source("supplements", start_date, end_date)
    if not items:
        return {"error": "No supplement data for range.", "start_date": start_date, "end_date": end_date,
                "tip": "Use log_supplement to start tracking. Example: log 500mg magnesium glycinate before bed."}

    all_entries = []
    by_supplement = {}
    by_date = {}

    for item in items:
        date = item.get("date")
        entries = item.get("supplements") or []
        day_entries = []
        for entry in entries:
            ename = entry.get("name", "")
            if name_filter and name_filter not in ename.lower():
                continue
            entry["date"] = date
            all_entries.append(entry)
            day_entries.append(entry)

            # Aggregate by supplement name
            key = ename.lower()
            if key not in by_supplement:
                by_supplement[key] = {"name": ename, "days_taken": 0, "entries": [], "doses": [], "timings": set()}
            by_supplement[key]["days_taken"] += 1
            by_supplement[key]["entries"].append(entry)
            if entry.get("dose") is not None:
                by_supplement[key]["doses"].append(float(entry["dose"]))
            if entry.get("timing"):
                by_supplement[key]["timings"].add(entry["timing"])

        if day_entries:
            by_date[date] = day_entries

    if not all_entries:
        return {"error": f"No entries found{' for ' + name_filter if name_filter else ''}.",
                "start_date": start_date, "end_date": end_date}

    # Total days in range
    d_start = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (d_end - d_start).days + 1
    days_logged = len(by_date)

    # Summary per supplement
    supplement_summary = []
    for key, data in sorted(by_supplement.items(), key=lambda x: x[1]["days_taken"], reverse=True):
        avg_dose = round(sum(data["doses"]) / len(data["doses"]), 1) if data["doses"] else None
        adherence_pct = round(data["days_taken"] / total_days * 100, 1)
        supplement_summary.append({
            "name": data["name"],
            "days_taken": data["days_taken"],
            "adherence_pct": adherence_pct,
            "avg_dose": avg_dose,
            "unit": data["entries"][0].get("unit", "") if data["entries"] else "",
            "typical_timings": sorted(data["timings"]),
            "category": data["entries"][0].get("category", "supplement") if data["entries"] else "",
        })

    # Recent log (last 7 days)
    recent = {}
    for date in sorted(by_date.keys(), reverse=True)[:7]:
        recent[date] = [{"name": e.get("name"), "dose": float(e["dose"]) if e.get("dose") else None,
                         "unit": e.get("unit", ""), "timing": e.get("timing", "")} for e in by_date[date]]

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_days_in_range": total_days,
        "days_with_entries": days_logged,
        "total_entries": len(all_entries),
        "unique_supplements": len(by_supplement),
        "supplement_summary": supplement_summary,
        "recent_log": recent,
        "source": "supplements (manual log via log_supplement)",
    }


def tool_get_supplement_correlation(args):
    """
    Cross-reference supplement intake with health outcomes.
    Compares days taking a supplement vs days without across sleep, recovery, glucose, HRV.
    Enhances N=1 experiments with supplement-specific analysis.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    supplement_name = (args.get("name") or "").strip().lower()

    if not supplement_name:
        return {"error": "Supplement name required. Specify which supplement to analyze."}

    supp_items = query_source("supplements", start_date, end_date)
    if not supp_items:
        return {"error": "No supplement data for range.", "start_date": start_date, "end_date": end_date}

    # Find days with and without this supplement
    days_with = set()
    for item in supp_items:
        for entry in (item.get("supplements") or []):
            if supplement_name in (entry.get("name") or "").lower():
                days_with.add(item.get("date"))

    if not days_with:
        return {"error": f"No entries found for '{supplement_name}'.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # Fetch health data
    sources = {"whoop": None, "eightsleep": None, "garmin": None, "apple_health": None}
    for src in sources:
        try:
            sources[src] = query_source(src, start_date, end_date)
        except Exception:
            pass

    # Build day-level metrics
    METRICS = [
        ("whoop", "recovery_score", "Whoop Recovery", "higher_is_better"),
        ("whoop", "hrv", "HRV", "higher_is_better"),
        ("whoop", "resting_heart_rate", "Resting HR", "lower_is_better"),
        ("eightsleep", "sleep_score", "Sleep Score", "higher_is_better"),
        ("eightsleep", "sleep_efficiency_pct", "Sleep Efficiency", "higher_is_better"),
        ("eightsleep", "deep_pct", "Deep Sleep %", "higher_is_better"),
        ("eightsleep", "rem_pct", "REM %", "higher_is_better"),
        ("eightsleep", "time_to_sleep_min", "Sleep Onset", "lower_is_better"),
        ("garmin", "body_battery_high", "Body Battery", "higher_is_better"),
        ("garmin", "avg_stress", "Garmin Stress", "lower_is_better"),
        ("apple_health", "blood_glucose_avg", "Glucose Avg", "lower_is_better"),
    ]

    # Index source data by date
    by_date = {}
    for src, items in sources.items():
        if not items:
            continue
        for item in items:
            d = item.get("date")
            if d not in by_date:
                by_date[d] = {}
            by_date[d][src] = item

    # All dates in range
    all_dates = set(by_date.keys())
    days_without = all_dates - days_with

    # Compare metrics
    comparisons = []
    for src, field, label, direction in METRICS:
        with_vals = []
        without_vals = []
        for d in days_with:
            if d in by_date and src in by_date[d]:
                v = _sf(by_date[d][src].get(field))
                if v is not None:
                    with_vals.append(v)
        for d in days_without:
            if d in by_date and src in by_date[d]:
                v = _sf(by_date[d][src].get(field))
                if v is not None:
                    without_vals.append(v)

        if len(with_vals) >= 3 and len(without_vals) >= 3:
            avg_with = _avg(with_vals)
            avg_without = _avg(without_vals)
            delta = round(avg_with - avg_without, 2)

            if direction == "higher_is_better":
                effect = "positive" if delta > 0 else ("negative" if delta < 0 else "neutral")
            else:
                effect = "positive" if delta < 0 else ("negative" if delta > 0 else "neutral")

            comparisons.append({
                "metric": label,
                "avg_with_supplement": avg_with,
                "avg_without_supplement": avg_without,
                "delta": delta,
                "effect": effect,
                "n_with": len(with_vals),
                "n_without": len(without_vals),
            })

    # Board of Directors
    bod = []
    positive_effects = [c for c in comparisons if c["effect"] == "positive"]
    negative_effects = [c for c in comparisons if c["effect"] == "negative"]

    if positive_effects:
        metrics = ", ".join([c["metric"] for c in positive_effects[:3]])
        bod.append(f"Attia: {supplement_name.title()} shows positive association with {metrics}. Correlation ≠ causation — consider running a formal N=1 experiment with create_experiment.")
    if negative_effects:
        metrics = ", ".join([c["metric"] for c in negative_effects[:3]])
        bod.append(f"Huberman: Possible negative association with {metrics}. Check timing and dosage — many supplements are timing-dependent.")
    if len(days_with) < 14:
        bod.append(f"Attia: Only {len(days_with)} days of data. Minimum 14 days recommended for meaningful N=1 analysis.")
    if not comparisons:
        bod.append("Insufficient overlapping data between supplement log and health metrics for comparison.")

    return {
        "supplement": supplement_name,
        "period": {"start_date": start_date, "end_date": end_date},
        "days_with_supplement": len(days_with),
        "days_without_supplement": len(days_without),
        "comparisons": comparisons,
        "board_of_directors": bod,
        "methodology": (
            "Compares average health metrics on days taking the supplement vs days without. "
            "Effect direction accounts for whether higher or lower is better for each metric. "
            "Requires >= 3 data points in each group. Correlation only — use N=1 experiments for causal inference."
        ),
        "source": "supplements + whoop + eightsleep + garmin + apple_health",
    }



# ══════════════════════════════════════════════════════════════════════════════
# Feature #10: Weather & Seasonal Correlation
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_weather_range(start_date, end_date):
    """
    Fetch weather data from Open-Meteo archive API for Seattle.
    Caches results in DynamoDB weather partition.
    Returns list of day records.
    """
    # Seattle coordinates
    LAT, LON = 47.6062, -122.3321

    # Check DynamoDB cache first
    cached = query_source("weather", start_date, end_date)
    cached_dates = {item.get("date") for item in cached if item.get("date")}

    # Find missing dates
    missing_dates = []
    d = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= d_end:
        ds = d.strftime("%Y-%m-%d")
        if ds not in cached_dates:
            missing_dates.append(ds)
        d += timedelta(days=1)

    # Fetch missing from Open-Meteo
    if missing_dates:
        fetch_start = min(missing_dates)
        fetch_end = max(missing_dates)
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={LAT}&longitude={LON}"
            f"&start_date={fetch_start}&end_date={fetch_end}"
            f"&daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            f"relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max,"
            f"surface_pressure_mean,daylight_duration,uv_index_max,"
            f"sunshine_duration"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&precipitation_unit=mm&timezone=America/Los_Angeles"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            daily = data.get("daily", {})
            dates = daily.get("time", [])
            table = boto3.resource("dynamodb", region_name=_REGION).Table(TABLE_NAME)

            new_records = []
            for i, date_str in enumerate(dates):
                if date_str not in set(missing_dates):
                    continue
                daylight_hrs = round(float(daily["daylight_duration"][i] or 0) / 3600, 2)
                sunshine_hrs = round(float(daily["sunshine_duration"][i] or 0) / 3600, 2)
                record = {
                    "date": date_str,
                    "temp_high_f": daily["temperature_2m_max"][i],
                    "temp_low_f": daily["temperature_2m_min"][i],
                    "temp_avg_f": daily["temperature_2m_mean"][i],
                    "humidity_pct": daily["relative_humidity_2m_mean"][i],
                    "precipitation_mm": daily["precipitation_sum"][i],
                    "wind_speed_max_mph": daily["wind_speed_10m_max"][i],
                    "pressure_hpa": daily["surface_pressure_mean"][i],
                    "daylight_hours": daylight_hrs,
                    "sunshine_hours": sunshine_hrs,
                    "uv_index_max": daily["uv_index_max"][i],
                }
                new_records.append(record)

                # Cache in DynamoDB
                db_item = {
                    "pk": USER_PREFIX + "weather",
                    "sk": f"DATE#{date_str}",
                    "source": "weather",
                    **record,
                }
                try:
                    from decimal import Decimal
                    def _to_decimal(obj):
                        if isinstance(obj, float):
                            return Decimal(str(round(obj, 4)))
                        if isinstance(obj, dict):
                            return {k: _to_decimal(v) for k, v in obj.items()}
                        if isinstance(obj, list):
                            return [_to_decimal(v) for v in obj]
                        return obj
                    table.put_item(Item=_to_decimal(db_item))
                except Exception as e:
                    logger.warning(f"Weather cache write failed for {date_str}: {e}")

            print(f"Fetched and cached {len(new_records)} weather days from Open-Meteo")
            cached.extend(new_records)

        except Exception as e:
            logger.warning(f"Open-Meteo fetch failed: {e}")
            # Continue with whatever cached data we have

    return cached


def tool_get_weather_correlation(args):
    """
    Weather & seasonal correlation analysis. Fetches weather for Seattle from
    Open-Meteo (free API), caches in DynamoDB, and correlates with health metrics.

    Huberman: Light exposure (daylight hours) is the master circadian lever.
    Walker: Seasonal light changes drive mood, energy, and sleep timing shifts.
    Attia: Barometric pressure changes correlate with joint pain and headaches.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # Fetch weather data (cached + fresh from Open-Meteo)
    weather_items = _fetch_weather_range(start_date, end_date)
    if not weather_items:
        return {"error": "Could not fetch weather data.", "start_date": start_date, "end_date": end_date}

    weather_by_date = {w.get("date"): w for w in weather_items if w.get("date")}

    # Fetch health data
    health_sources = {}
    for src in ["whoop", "eightsleep", "garmin", "apple_health"]:
        try:
            health_sources[src] = {item.get("date"): item for item in query_source(src, start_date, end_date) if item.get("date")}
        except Exception:
            health_sources[src] = {}

    # Journal mood/energy
    journal_by_date = {}
    try:
        journal_items = query_source("notion", start_date, end_date)
        for item in journal_items:
            d = item.get("date")
            if d and not d in journal_by_date:
                journal_by_date[d] = {}
            for field in ["morning_mood", "morning_energy", "stress_level", "day_rating"]:
                v = _sf(item.get(field))
                if v is not None:
                    journal_by_date.setdefault(d, {})[field] = v
    except Exception:
        pass

    # Weather variables to correlate
    WEATHER_VARS = [
        ("temp_avg_f", "Temperature (°F)"),
        ("humidity_pct", "Humidity (%)"),
        ("precipitation_mm", "Precipitation (mm)"),
        ("daylight_hours", "Daylight Hours"),
        ("sunshine_hours", "Sunshine Hours"),
        ("pressure_hpa", "Barometric Pressure (hPa)"),
        ("uv_index_max", "UV Index"),
    ]

    # Health metrics to compare against
    HEALTH_METRICS = [
        ("whoop", "recovery_score", "Whoop Recovery"),
        ("whoop", "hrv", "HRV"),
        ("eightsleep", "sleep_score", "Sleep Score"),
        ("eightsleep", "sleep_efficiency_pct", "Sleep Efficiency"),
        ("eightsleep", "deep_pct", "Deep Sleep %"),
        ("garmin", "avg_stress", "Garmin Stress"),
        ("garmin", "body_battery_high", "Body Battery"),
    ]
    JOURNAL_METRICS = [
        ("morning_mood", "Morning Mood"),
        ("morning_energy", "Morning Energy"),
        ("stress_level", "Stress Level"),
        ("day_rating", "Day Rating"),
    ]

    # Compute correlations
    correlations = {}
    for wvar, wlabel in WEATHER_VARS:
        correlations[wvar] = {"label": wlabel, "health_correlations": {}, "journal_correlations": {}}

        for src, field, hlabel in HEALTH_METRICS:
            xs, ys = [], []
            for d, w in weather_by_date.items():
                wv = _sf(w.get(wvar))
                if wv is None: continue
                hv = _sf(health_sources.get(src, {}).get(d, {}).get(field))
                if hv is not None:
                    xs.append(wv); ys.append(hv)
            r = pearson_r(xs, ys) if len(xs) >= 10 else None
            if r is not None:
                correlations[wvar]["health_correlations"][field] = {"label": hlabel, "pearson_r": r, "n": len(xs)}

        for jfield, jlabel in JOURNAL_METRICS:
            xs, ys = [], []
            for d, w in weather_by_date.items():
                wv = _sf(w.get(wvar))
                if wv is None: continue
                jv = journal_by_date.get(d, {}).get(jfield)
                if jv is not None:
                    xs.append(wv); ys.append(jv)
            r = pearson_r(xs, ys) if len(xs) >= 10 else None
            if r is not None:
                correlations[wvar]["journal_correlations"][jfield] = {"label": jlabel, "pearson_r": r, "n": len(xs)}

    # Remove empty correlation groups
    for wvar in list(correlations.keys()):
        if not correlations[wvar]["health_correlations"] and not correlations[wvar]["journal_correlations"]:
            del correlations[wvar]

    # Weather summary
    weather_summary = {
        "avg_temp_f": _avg([_sf(w.get("temp_avg_f")) for w in weather_items]),
        "avg_humidity_pct": _avg([_sf(w.get("humidity_pct")) for w in weather_items]),
        "total_precip_mm": round(sum(_sf(w.get("precipitation_mm")) or 0 for w in weather_items), 1),
        "avg_daylight_hours": _avg([_sf(w.get("daylight_hours")) for w in weather_items]),
        "avg_sunshine_hours": _avg([_sf(w.get("sunshine_hours")) for w in weather_items]),
        "rainy_days": sum(1 for w in weather_items if (_sf(w.get("precipitation_mm")) or 0) > 0.5),
        "total_days": len(weather_items),
    }

    # Seasonal comparison (if enough data)
    seasonal = None
    if len(weather_items) >= 60:
        mid = len(weather_items) // 2
        first_half = weather_items[:mid]
        second_half = weather_items[mid:]
        seasonal = {
            "first_half_avg_daylight": _avg([_sf(w.get("daylight_hours")) for w in first_half]),
            "second_half_avg_daylight": _avg([_sf(w.get("daylight_hours")) for w in second_half]),
            "daylight_trend": "increasing" if (_avg([_sf(w.get("daylight_hours")) for w in second_half]) or 0) > (_avg([_sf(w.get("daylight_hours")) for w in first_half]) or 0) else "decreasing",
        }

    # Find strongest correlations
    notable = []
    for wvar, data in correlations.items():
        for field, corr in {**data.get("health_correlations", {}), **data.get("journal_correlations", {})}.items():
            r = corr.get("pearson_r", 0)
            if abs(r) >= 0.2:
                notable.append({"weather": data["label"], "health": corr["label"], "r": r, "n": corr["n"]})
    notable.sort(key=lambda x: abs(x["r"]), reverse=True)

    # Board of Directors
    bod = []
    daylight_mood = correlations.get("daylight_hours", {}).get("journal_correlations", {}).get("morning_mood", {})
    if daylight_mood and daylight_mood.get("pearson_r", 0) > 0.15:
        bod.append(f"Huberman: Daylight correlates with your mood (r={daylight_mood['pearson_r']}). Morning sunlight within 30 min of waking is the single highest-ROI circadian intervention.")
    
    sunshine_sleep = correlations.get("sunshine_hours", {}).get("health_correlations", {}).get("sleep_score", {})
    if sunshine_sleep and sunshine_sleep.get("pearson_r", 0) > 0.15:
        bod.append(f"Walker: More sunshine correlates with better sleep (r={sunshine_sleep['pearson_r']}). Light exposure during the day strengthens the circadian sleep drive.")

    pressure_corrs = correlations.get("pressure_hpa", {}).get("health_correlations", {})
    if any(abs(c.get("pearson_r", 0)) > 0.2 for c in pressure_corrs.values()):
        bod.append("Attia: Barometric pressure shows correlation with your health metrics. Low-pressure systems (storms) can affect joint inflammation, headaches, and autonomic function.")

    if weather_summary.get("rainy_days", 0) > weather_summary.get("total_days", 1) * 0.5:
        bod.append("Note: Seattle's rain prevalence means outdoor light exposure requires intentionality. Consider a 10,000 lux light therapy lamp for morning use during dark months.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "location": "Seattle, WA (47.61, -122.33)",
        "weather_summary": weather_summary,
        "correlations": correlations,
        "notable_correlations": notable[:10],
        "seasonal_analysis": seasonal,
        "board_of_directors": bod,
        "methodology": (
            "Weather data from Open-Meteo archive API (free, WMO-grade). Cached in DynamoDB after first fetch. "
            "Pearson correlations between daily weather variables and health metrics. "
            "Requires >= 10 overlapping data points per correlation pair. "
            "Huberman: daylight = master circadian lever. Walker: light drives sleep-wake timing."
        ),
        "source": "open-meteo + whoop + eightsleep + garmin + apple_health + notion",
    }



# ══════════════════════════════════════════════════════════════════════════════
# Feature #11: Training Periodization Planner
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_training_periodization(args):
    """
    Training periodization analysis. Detects mesocycle phases, deload needs,
    progressive overload tracking, and training polarization.

    Galpin framework: Base → Build → Peak → Deload (3:1 or 4:1 ratio).
    Attia: Training is the most potent longevity drug — but only with periodization.
    Seiler: 80/20 polarized model — 80% easy, 20% hard for optimal adaptation.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    weeks_back = int(args.get("weeks", 12))
    start_date = args.get("start_date",
        (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Fetch training data ───────────────────────────────────────────────
    strava_items = query_source("strava", start_date, end_date)
    mf_workout_items = query_source("macrofactor_workouts", start_date, end_date)

    if not strava_items and not mf_workout_items:
        return {"error": "No training data for range.", "start_date": start_date, "end_date": end_date}

    # ── 2. Build weekly training profile ─────────────────────────────────────
    from collections import defaultdict

    def _week_key(date_str):
        d = datetime.strptime(date_str, "%Y-%m-%d")
        # ISO week: Monday start
        return d.strftime("%G-W%V")

    weeks = defaultdict(lambda: {
        "cardio_minutes": 0, "strength_minutes": 0, "total_minutes": 0,
        "zone2_minutes": 0, "hard_minutes": 0, "easy_minutes": 0,
        "sessions": 0, "strength_sessions": 0, "cardio_sessions": 0,
        "total_volume_lbs": 0, "rest_days": 0, "dates": set(),
        "activities": [],
    })

    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical",
                    "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}

    # Process Strava activities
    for item in strava_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        weeks[wk]["dates"].add(date)
        for act in (item.get("activities") or []):
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:
                continue
            duration_min = elapsed / 60
            avg_hr = _sf(act.get("average_heartrate"))

            weeks[wk]["sessions"] += 1
            weeks[wk]["total_minutes"] += duration_min

            is_cardio = sport in cardio_types
            is_strength = sport in strength_types

            if is_cardio:
                weeks[wk]["cardio_sessions"] += 1
                weeks[wk]["cardio_minutes"] += duration_min

                if avg_hr:
                    hr_pct = avg_hr / max_hr * 100
                    if hr_pct <= 70:
                        weeks[wk]["zone2_minutes"] += duration_min
                        weeks[wk]["easy_minutes"] += duration_min
                    elif hr_pct >= 80:
                        weeks[wk]["hard_minutes"] += duration_min
                    else:
                        weeks[wk]["easy_minutes"] += duration_min  # Zone 3 counted as moderate

            elif is_strength:
                weeks[wk]["strength_sessions"] += 1
                weeks[wk]["strength_minutes"] += duration_min

            weeks[wk]["activities"].append({
                "date": date, "sport": sport,
                "duration_min": round(duration_min, 1),
                "avg_hr": avg_hr,
            })

    # Process MacroFactor workouts for volume tracking
    for item in mf_workout_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        vol = _sf(item.get("total_volume_lbs")) or 0
        weeks[wk]["total_volume_lbs"] += vol

    # Calculate rest days per week
    for wk, data in weeks.items():
        data["rest_days"] = 7 - len(data["dates"])
        data["dates"] = sorted(data["dates"])  # Convert set to sorted list

    # ── 3. Weekly progression analysis ───────────────────────────────────────
    sorted_weeks = sorted(weeks.keys())
    weekly_summary = []
    for wk in sorted_weeks:
        w = weeks[wk]
        total_min = w["total_minutes"]
        easy_pct = round(w["easy_minutes"] / total_min * 100, 1) if total_min > 0 else 0
        hard_pct = round(w["hard_minutes"] / total_min * 100, 1) if total_min > 0 else 0

        # Classify week phase
        if total_min < 60:
            phase = "deload"
        elif w["sessions"] <= 2:
            phase = "deload"
        else:
            if w["hard_minutes"] > total_min * 0.3:
                phase = "build"
            elif total_min > 300:
                phase = "peak"
            else:
                phase = "base"

        weekly_summary.append({
            "week": wk,
            "phase": phase,
            "sessions": w["sessions"],
            "total_minutes": round(total_min, 1),
            "cardio_minutes": round(w["cardio_minutes"], 1),
            "strength_minutes": round(w["strength_minutes"], 1),
            "zone2_minutes": round(w["zone2_minutes"], 1),
            "hard_minutes": round(w["hard_minutes"], 1),
            "easy_pct": easy_pct,
            "hard_pct": hard_pct,
            "volume_lbs": round(w["total_volume_lbs"], 1),
            "rest_days": w["rest_days"],
            "cardio_sessions": w["cardio_sessions"],
            "strength_sessions": w["strength_sessions"],
        })

    # ── 4. Deload detection ──────────────────────────────────────────────────
    deload_analysis = {
        "weeks_since_last_deload": 0,
        "deload_recommended": False,
        "reason": None,
    }

    # Count consecutive non-deload weeks from end
    consecutive = 0
    for ws in reversed(weekly_summary):
        if ws["phase"] == "deload":
            break
        consecutive += 1
    deload_analysis["weeks_since_last_deload"] = consecutive

    if consecutive >= 4:
        deload_analysis["deload_recommended"] = True
        deload_analysis["reason"] = f"{consecutive} consecutive training weeks without deload. Galpin recommends 3:1 or 4:1 loading-to-deload ratio."
    elif consecutive >= 3:
        # Check if volume is trending up
        recent_3 = weekly_summary[-3:] if len(weekly_summary) >= 3 else weekly_summary
        if len(recent_3) >= 3:
            vols = [w["total_minutes"] for w in recent_3]
            if all(vols[i] >= vols[i-1] for i in range(1, len(vols))):
                deload_analysis["deload_recommended"] = True
                deload_analysis["reason"] = "3 consecutive weeks of increasing volume. Progressive overload is good, but a deload preserves adaptation."

    # ── 5. Training polarization check (Seiler) ─────────────────────────────
    total_easy = sum(w["easy_minutes"] for wk, w in weeks.items())
    total_hard = sum(w["hard_minutes"] for wk, w in weeks.items())
    total_all = total_easy + total_hard
    polarization = None

    if total_all > 0:
        easy_ratio = round(total_easy / total_all * 100, 1)
        hard_ratio = round(total_hard / total_all * 100, 1)
        mid_ratio = round(100 - easy_ratio - hard_ratio, 1)

        if easy_ratio >= 75:
            pol_status = "well_polarized"
        elif easy_ratio >= 60:
            pol_status = "moderately_polarized"
        else:
            pol_status = "too_much_intensity"

        polarization = {
            "easy_pct": easy_ratio,
            "hard_pct": hard_ratio,
            "middle_zone_pct": mid_ratio,
            "status": pol_status,
            "seiler_target": "80% easy / 20% hard — the polarized model maximizes adaptation while minimizing overtraining risk.",
        }

    # ── 6. Progressive overload tracking (strength) ──────────────────────────
    overload = None
    vol_weeks = [(ws["week"], ws["volume_lbs"]) for ws in weekly_summary if ws["volume_lbs"] > 0]
    if len(vol_weeks) >= 4:
        mid = len(vol_weeks) // 2
        first_half_vol = _avg([v for _, v in vol_weeks[:mid]])
        second_half_vol = _avg([v for _, v in vol_weeks[mid:]])
        if first_half_vol and second_half_vol:
            delta_pct = round((second_half_vol - first_half_vol) / first_half_vol * 100, 1)
            overload = {
                "first_half_avg_volume_lbs": first_half_vol,
                "second_half_avg_volume_lbs": second_half_vol,
                "delta_pct": delta_pct,
                "trend": "increasing" if delta_pct > 5 else ("decreasing" if delta_pct < -5 else "stable"),
                "note": "Progressive overload detected." if delta_pct > 5 else (
                    "Volume declining — ensure this is intentional (deload/cut)." if delta_pct < -5
                    else "Volume stable — consider adding progressive overload."
                ),
            }

    # ── 7. Training consistency ──────────────────────────────────────────────
    sessions_per_week = [ws["sessions"] for ws in weekly_summary]
    avg_sessions = _avg(sessions_per_week)
    consistency_pct = round(
        sum(1 for s in sessions_per_week if s >= 3) / len(sessions_per_week) * 100, 1
    ) if sessions_per_week else 0

    consistency = {
        "avg_sessions_per_week": avg_sessions,
        "weeks_with_3plus_sessions_pct": consistency_pct,
        "total_weeks_analyzed": len(weekly_summary),
        "assessment": "excellent" if consistency_pct >= 85 else (
            "good" if consistency_pct >= 70 else (
                "needs_improvement" if consistency_pct >= 50 else "inconsistent"
            )
        ),
    }

    # ── 8. Zone 2 target tracking ────────────────────────────────────────────
    z2_weekly = [ws["zone2_minutes"] for ws in weekly_summary]
    z2_target = 150
    z2_hit_rate = round(sum(1 for z in z2_weekly if z >= z2_target) / len(z2_weekly) * 100, 1) if z2_weekly else 0

    zone2_status = {
        "avg_weekly_minutes": _avg(z2_weekly),
        "target_minutes": z2_target,
        "weeks_hitting_target_pct": z2_hit_rate,
        "current_week": round(z2_weekly[-1], 1) if z2_weekly else 0,
    }

    # ── 9. Board of Directors ────────────────────────────────────────────────
    bod = []

    if deload_analysis["deload_recommended"]:
        bod.append(f"Galpin: {deload_analysis['reason']} Reduce volume by 40-60% this week. Maintain intensity on key lifts but cut sets in half.")

    if polarization:
        if polarization["status"] == "too_much_intensity":
            bod.append(f"Seiler: Only {polarization['easy_pct']}% of your training is easy. The 80/20 model says you need more Zone 2 and fewer moderate sessions. 'No man's land' (Zone 3) generates fatigue without proportional adaptation.")
        elif polarization["status"] == "well_polarized":
            bod.append("Seiler: Training well polarized — strong easy/hard split. This is the highest-evidence approach for long-term development.")

    if overload and overload["trend"] == "increasing":
        bod.append(f"Galpin: Progressive overload confirmed (+{overload['delta_pct']}% volume). This is the fundamental driver of hypertrophy and strength adaptation.")
    elif overload and overload["trend"] == "decreasing":
        bod.append(f"Galpin: Volume declining by {abs(overload['delta_pct'])}%. If not intentional (cut/deload), this represents a missed adaptation opportunity.")

    if zone2_status["weeks_hitting_target_pct"] < 50:
        bod.append(f"Attia: Only hitting Zone 2 target {zone2_status['weeks_hitting_target_pct']}% of weeks. Zone 2 is the highest-ROI longevity training modality — aim for 150 min/week.")

    if consistency["assessment"] in ("needs_improvement", "inconsistent"):
        bod.append(f"Attia: Consistency ({consistency['avg_sessions_per_week']} sessions/week avg) matters more than intensity. The best program is the one you actually do.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "weeks": len(weekly_summary)},
        "weekly_breakdown": weekly_summary,
        "deload_analysis": deload_analysis,
        "polarization": polarization,
        "progressive_overload": overload,
        "training_consistency": consistency,
        "zone2_status": zone2_status,
        "board_of_directors": bod,
        "methodology": (
            "Weekly training classified into phases: base (moderate consistent), build (>30% high intensity), "
            "peak (>300 min/week), deload (<60 min or <=2 sessions). Polarization per Seiler (80/20 model). "
            "Progressive overload = first-half vs second-half average weekly volume. "
            "Deload trigger: 4+ consecutive loading weeks or 3 weeks of rising volume. "
            "Zone 2 threshold: avg HR <= 70% max HR (Attia/WHO 150 min/week target)."
        ),
        "source": "strava + macrofactor_workouts",
    }



# ══════════════════════════════════════════════════════════════════════════════
# Tool functions (relocated from post-TOOLS position)
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_glucose_meal_response(args):
    """
    Levels-style postprandial glucose response analysis.

    For each meal logged in MacroFactor, matches 5-min CGM readings from S3
    to compute: pre-meal baseline, peak glucose, spike magnitude, time-to-peak,
    time to return to baseline, and a letter grade.

    Aggregates: best/worst meals, macro correlations (carbs/fiber/protein vs spike),
    personal food scores across multiple days.

    Based on Attia, Huberman, Lustig: postprandial spikes >30 mg/dL drive insulin
    resistance, inflammation, and accelerated glycation. Fiber, protein, and fat
    blunt the spike; refined carbs and sugar amplify it.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    meal_gap_minutes = args.get("meal_gap_minutes", 30)
    baseline_window_min = 30  # minutes before meal for baseline
    postprandial_window_min = 120  # 2-hour response window

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def t2d(t):
        """Convert HH:MM string to decimal hours."""
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        """Convert decimal hours to HH:MM string."""
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1
            m = 0
        return f"{h:02d}:{m:02d}"

    def score_spike(spike):
        """Grade a glucose spike magnitude."""
        if spike is None:
            return None
        if spike < 15:
            return "A"
        elif spike < 30:
            return "B"
        elif spike < 40:
            return "C"
        elif spike < 50:
            return "D"
        else:
            return "F"

    # ── Load MacroFactor food logs ────────────────────────────────────────
    mf_items = query_source("macrofactor", start_date, end_date)
    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    all_meals = []
    food_scores = defaultdict(list)  # food_name -> list of spike values
    days_with_data = 0
    days_without_cgm = 0

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue
        food_log = mf_item.get("food_log", [])
        if not food_log:
            continue

        # Load CGM readings for this day
        readings = _load_cgm_readings(date)
        if len(readings) < 20:  # need reasonable CGM coverage
            days_without_cgm += 1
            continue
        days_with_data += 1

        # ── Group food items into meals by timestamp proximity ────────
        entries_with_time = []
        for entry in food_log:
            td = t2d(entry.get("time"))
            if td is not None:
                entries_with_time.append((td, entry))
        entries_with_time.sort(key=lambda x: x[0])

        meals = []
        current_meal = []
        current_meal_start = None
        for td, entry in entries_with_time:
            if current_meal_start is None or (td - current_meal_start) * 60 > meal_gap_minutes:
                if current_meal:
                    meals.append(current_meal)
                current_meal = [(td, entry)]
                current_meal_start = td
            else:
                current_meal.append((td, entry))
        if current_meal:
            meals.append(current_meal)

        # ── Analyze each meal ─────────────────────────────────────────
        for meal_entries in meals:
            meal_time_dec = meal_entries[0][0]  # earliest item time
            meal_time_str = d2hm(meal_time_dec)

            # Meal macros
            meal_cals = sum(_sf(e.get("calories_kcal")) or 0 for _, e in meal_entries)
            meal_carbs = sum(_sf(e.get("carbs_g")) or 0 for _, e in meal_entries)
            meal_protein = sum(_sf(e.get("protein_g")) or 0 for _, e in meal_entries)
            meal_fat = sum(_sf(e.get("fat_g")) or 0 for _, e in meal_entries)
            meal_fiber = sum(_sf(e.get("fiber_g")) or 0 for _, e in meal_entries)
            meal_sugar = sum(_sf(e.get("sugars_g")) or 0 for _, e in meal_entries)
            food_names = [e.get("food_name", "Unknown") for _, e in meal_entries]

            # Pre-meal baseline: avg glucose in 30 min before meal
            baseline_start = meal_time_dec - baseline_window_min / 60
            baseline_readings = [v for t, v in readings if baseline_start <= t < meal_time_dec]
            if len(baseline_readings) < 2:
                # Try wider window (45 min)
                baseline_start = meal_time_dec - 45 / 60
                baseline_readings = [v for t, v in readings if baseline_start <= t < meal_time_dec]
            if len(baseline_readings) < 2:
                continue  # can't compute without baseline

            baseline = sum(baseline_readings) / len(baseline_readings)

            # Postprandial window: 2 hours after meal start
            post_start = meal_time_dec
            post_end = meal_time_dec + postprandial_window_min / 60
            post_readings = [(t, v) for t, v in readings if post_start <= t <= post_end]
            if len(post_readings) < 4:
                continue  # insufficient coverage

            # Peak and timing
            peak_time, peak_value = max(post_readings, key=lambda x: x[1])
            spike = round(peak_value - baseline, 1)
            time_to_peak_min = round((peak_time - meal_time_dec) * 60, 0)

            # Time to return to baseline (within 2hr window)
            returned_at = None
            if spike > 5:  # only track return if meaningful spike
                for t, v in post_readings:
                    if t > peak_time and v <= baseline + 5:
                        returned_at = round((t - meal_time_dec) * 60, 0)
                        break

            # AUC above baseline (trapezoidal, in mg/dL-minutes)
            auc = 0.0
            sorted_post = sorted(post_readings, key=lambda x: x[0])
            for i in range(1, len(sorted_post)):
                t0, v0 = sorted_post[i - 1]
                t1, v1 = sorted_post[i]
                dt_min = (t1 - t0) * 60
                excess0 = max(0, v0 - baseline)
                excess1 = max(0, v1 - baseline)
                auc += (excess0 + excess1) / 2 * dt_min

            grade = score_spike(spike)

            meal_record = {
                "date": date,
                "meal_time": meal_time_str,
                "foods": food_names[:8],  # cap at 8 for readability
                "item_count": len(food_names),
                "calories": round(meal_cals),
                "carbs_g": round(meal_carbs, 1),
                "protein_g": round(meal_protein, 1),
                "fat_g": round(meal_fat, 1),
                "fiber_g": round(meal_fiber, 1),
                "sugar_g": round(meal_sugar, 1),
                "baseline_mg_dl": round(baseline, 1),
                "peak_mg_dl": round(peak_value, 1),
                "spike_mg_dl": spike,
                "time_to_peak_min": int(time_to_peak_min),
                "return_to_baseline_min": int(returned_at) if returned_at else None,
                "auc_above_baseline": round(auc, 1),
                "grade": grade,
            }
            all_meals.append(meal_record)

            # Track per-food scores
            for _, entry in meal_entries:
                fn = entry.get("food_name", "Unknown")
                food_scores[fn].append(spike)

    if not all_meals:
        return {
            "error": "No meals with matching CGM data found.",
            "days_checked": len(mf_items),
            "days_without_cgm": days_without_cgm,
            "hint": "Need overlapping MacroFactor food logs + CGM readings on the same days.",
        }

    # ── Aggregate analysis ────────────────────────────────────────────────
    spikes = [m["spike_mg_dl"] for m in all_meals]
    grades = [m["grade"] for m in all_meals]
    avg_spike = round(sum(spikes) / len(spikes), 1)

    # Grade distribution
    grade_dist = {}
    for g in ["A", "B", "C", "D", "F"]:
        ct = grades.count(g)
        if ct > 0:
            grade_dist[g] = ct

    # Best and worst meals
    sorted_by_spike = sorted(all_meals, key=lambda x: x["spike_mg_dl"])
    best_meals = sorted_by_spike[:5]
    worst_meals = sorted_by_spike[-5:][::-1]

    # Food scores (foods appearing 2+ times)
    food_summary = []
    for fn, spikes_list in sorted(food_scores.items()):
        if len(spikes_list) >= 2:
            avg_s = round(sum(spikes_list) / len(spikes_list), 1)
            food_summary.append({
                "food": fn,
                "appearances": len(spikes_list),
                "avg_spike": avg_s,
                "grade": score_spike(avg_s),
            })
    food_summary.sort(key=lambda x: x["avg_spike"])

    # Macro correlations (carbs, fiber, protein, sugar vs spike)
    correlations = {}
    for macro_field, label in [
        ("carbs_g", "carbs"), ("fiber_g", "fiber"),
        ("protein_g", "protein"), ("fat_g", "fat"),
        ("sugar_g", "sugar"), ("calories", "calories"),
    ]:
        xs = [m[macro_field] for m in all_meals if m.get(macro_field) is not None]
        ys = [m["spike_mg_dl"] for m in all_meals if m.get(macro_field) is not None]
        if len(xs) >= 7:
            r_val = pearson_r(xs, ys)
            if r_val is not None:
                correlations[f"{label}_vs_spike"] = round(r_val, 3)

    # Fiber-to-carb ratio analysis
    high_fiber_meals = [m for m in all_meals if m["carbs_g"] > 10 and m["fiber_g"] / max(m["carbs_g"], 1) > 0.15]
    low_fiber_meals = [m for m in all_meals if m["carbs_g"] > 10 and m["fiber_g"] / max(m["carbs_g"], 1) <= 0.15]
    fiber_ratio_impact = None
    if len(high_fiber_meals) >= 3 and len(low_fiber_meals) >= 3:
        hf_avg = round(sum(m["spike_mg_dl"] for m in high_fiber_meals) / len(high_fiber_meals), 1)
        lf_avg = round(sum(m["spike_mg_dl"] for m in low_fiber_meals) / len(low_fiber_meals), 1)
        fiber_ratio_impact = {
            "high_fiber_ratio_meals": len(high_fiber_meals),
            "high_fiber_avg_spike": hf_avg,
            "low_fiber_ratio_meals": len(low_fiber_meals),
            "low_fiber_avg_spike": lf_avg,
            "fiber_benefit_mg_dl": round(lf_avg - hf_avg, 1),
        }

    # Personal recommendation
    rec = []
    if avg_spike > 40:
        rec.append("Average spike is HIGH (>40 mg/dL). Prioritize reducing refined carbs and adding fiber/protein to meals.")
    elif avg_spike > 30:
        rec.append("Average spike is ELEVATED (30-40 mg/dL). Good opportunity to optimize meal composition.")
    elif avg_spike > 15:
        rec.append("Average spike is MODERATE (15-30 mg/dL). Solid metabolic health — fine-tune worst offenders.")
    else:
        rec.append("Average spike is EXCELLENT (<15 mg/dL). Outstanding glucose control.")

    if correlations.get("fiber_vs_spike") and correlations["fiber_vs_spike"] < -0.15:
        rec.append(f"Fiber is protective (r={correlations['fiber_vs_spike']}). Keep prioritizing high-fiber meals.")
    if correlations.get("sugar_vs_spike") and correlations["sugar_vs_spike"] > 0.2:
        rec.append(f"Sugar drives spikes (r={correlations['sugar_vs_spike']}). Reduce added sugars.")

    return {
        "period": {"start": start_date, "end": end_date},
        "data_coverage": {
            "days_with_food_log": len(mf_items),
            "days_with_cgm": days_with_data,
            "days_without_cgm": days_without_cgm,
            "total_meals_analyzed": len(all_meals),
        },
        "summary": {
            "avg_spike_mg_dl": avg_spike,
            "avg_grade": score_spike(avg_spike),
            "grade_distribution": grade_dist,
            "avg_time_to_peak_min": round(sum(m["time_to_peak_min"] for m in all_meals) / len(all_meals)),
        },
        "best_meals": best_meals,
        "worst_meals": worst_meals,
        "food_scores": food_summary[:20] if food_summary else None,
        "macro_correlations": correlations if correlations else None,
        "fiber_ratio_impact": fiber_ratio_impact,
        "recommendation": rec,
        "meals": all_meals[-30:],  # last 30 meals for detail
        "note": "Scoring: A (<15 spike), B (15-30), C (30-40), D (40-50), F (>50 mg/dL). "
                "Based on Attia/Huberman: spikes >30 drive insulin resistance. "
                "Fiber, protein, fat blunt spikes; refined carbs and sugar amplify them.",
    }




# ── Tool: get_day_type_analysis (Phase 2c) ───────────────────────────────────

def tool_get_day_type_analysis(args):
    """
    Segment any metric by day type (rest/light/moderate/hard/race).

    Cross-references Whoop strain, Strava activities, and computed load
    to classify each day, then groups selected metrics by day type.

    Use cases:
      - 'How does my sleep differ on hard training days vs rest days?'
      - 'Do I eat more on training days?'
      - 'What\'s my average HRV by day type?'
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 90))
    start_date = args.get("start_date") or (
        datetime.utcnow() - timedelta(days=days)
    ).strftime("%Y-%m-%d")
    metrics    = args.get("metrics", ["sleep", "recovery", "nutrition"])
    if isinstance(metrics, str):
        metrics = [metrics]

    # Gather classification data
    whoop_data = {d["date"]: d for d in query_source("whoop", start_date, end_date, lean=True) if d.get("date")}
    strava_data = {d["date"]: d for d in query_source(get_sot("cardio"), start_date, end_date, lean=True) if d.get("date")}

    # Classify each day
    cur = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    classified = {}  # date -> day_type
    while cur <= end_dt:
        ds = cur.strftime("%Y-%m-%d")
        w = whoop_data.get(ds, {})
        s = strava_data.get(ds, {})
        strain = w.get("strain")
        load = compute_daily_load_score(s) if s else None
        classified[ds] = classify_day_type(
            whoop_strain=strain,
            strava_activities=s,
            daily_load=load,
        )
        cur += timedelta(days=1)

    # Count by type
    type_counts = {}
    for dt in classified.values():
        type_counts[dt] = type_counts.get(dt, 0) + 1

    # Gather metrics by day type
    type_metrics = {t: [] for t in ["rest", "light", "moderate", "hard", "race"]}

    # Batch fetch nutrition data if requested
    mf_data = {}
    if "nutrition" in metrics:
        pk_mf = USER_PREFIX + "macrofactor"
        table = get_table()
        try:
            mf_items = query_date_range(table, pk_mf, start_date, end_date)
            mf_data = {item["date"]: item for item in mf_items if item.get("date")}
        except Exception:
            pass

    for ds, day_type in classified.items():
        w = whoop_data.get(ds, {})
        entry = {"date": ds, "strain": w.get("strain")}

        if "sleep" in metrics or "recovery" in metrics:
            entry["recovery_score"] = w.get("recovery_score")
            entry["hrv"] = w.get("hrv")
            entry["resting_heart_rate"] = w.get("resting_heart_rate")
            entry["sleep_performance"] = w.get("sleep_performance")
            entry["total_sleep_hours"] = round(float(w["total_sleep_seconds"]) / 3600, 2) if w.get("total_sleep_seconds") else None

        if "nutrition" in metrics:
            mf = mf_data.get(ds, {})
            entry["calories_kcal"] = float(mf["total_calories_kcal"]) if mf.get("total_calories_kcal") else None
            entry["protein_g"] = float(mf["total_protein_g"]) if mf.get("total_protein_g") else None
            entry["carbs_g"] = float(mf["total_carbs_g"]) if mf.get("total_carbs_g") else None
            entry["fat_g"] = float(mf["total_fat_g"]) if mf.get("total_fat_g") else None

        type_metrics[day_type].append(entry)

    # Compute averages per type
    def avg_field(entries, field):
        vals = [float(e[field]) for e in entries if e.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    summary_fields = ["strain", "recovery_score", "hrv", "resting_heart_rate",
                      "sleep_performance", "total_sleep_hours",
                      "calories_kcal", "protein_g", "carbs_g", "fat_g"]
    summaries = {}
    for day_type, entries in type_metrics.items():
        if not entries:
            continue
        summaries[day_type] = {
            "count": len(entries),
            "averages": {f: avg_field(entries, f) for f in summary_fields},
        }

    # Key insights
    insights = []
    rest_hrv = summaries.get("rest", {}).get("averages", {}).get("hrv")
    hard_hrv = summaries.get("hard", {}).get("averages", {}).get("hrv")
    if rest_hrv and hard_hrv:
        diff = round(rest_hrv - hard_hrv, 1)
        if diff > 10:
            insights.append(f"HRV drops {diff} ms on hard vs rest days — significant recovery impact. Prioritize sleep after hard sessions.")
        elif diff > 5:
            insights.append(f"HRV drops {diff} ms on hard days — moderate recovery impact.")

    rest_cal = summaries.get("rest", {}).get("averages", {}).get("calories_kcal")
    hard_cal = summaries.get("hard", {}).get("averages", {}).get("calories_kcal")
    if rest_cal and hard_cal:
        diff = round(hard_cal - rest_cal)
        if diff > 300:
            insights.append(f"Eating {diff} kcal more on hard days vs rest — verify this aligns with your deficit goal.")
        elif diff < -200:
            insights.append(f"Eating {abs(diff)} kcal LESS on hard days — consider fueling better around training.")

    rest_sleep = summaries.get("rest", {}).get("averages", {}).get("total_sleep_hours")
    hard_sleep = summaries.get("hard", {}).get("averages", {}).get("total_sleep_hours")
    if rest_sleep and hard_sleep:
        diff = round(hard_sleep - rest_sleep, 2)
        if diff < -0.3:
            insights.append(f"Sleeping {abs(diff)} hrs LESS after hard days — your body needs MORE sleep for recovery, not less.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "total_days": len(classified)},
        "day_type_distribution": type_counts,
        "thresholds": DAY_TYPE_THRESHOLDS,
        "summaries": summaries,
        "insights": insights,
        "classification_source": "Whoop strain (primary) > computed load score > Strava distance/time",
    }




# ── Tool: get_fasting_glucose_validation ──────────────────────────────────────

def tool_get_fasting_glucose_validation(args):
    """
    Validate CGM fasting glucose proxy against venous lab draws.

    Two modes:
      1. Direct validation: same-day CGM overnight nadir vs lab fasting glucose
      2. Statistical validation: CGM nadir distribution vs historical lab values

    Computes proper overnight nadir using 00:00-06:00 window (avoids dawn
    phenomenon cortisol rise per Attia/Huberman). Also computes the narrower
    02:00-05:00 "deep nadir" which excludes both late digestion and dawn effect.

    Returns: nadir distribution, lab comparisons, bias analysis, confidence.
    """
    import statistics

    # ── Parameters ────────────────────────────────────────────────────────
    nadir_start = float(args.get("nadir_start_hour", 0))      # midnight
    nadir_end   = float(args.get("nadir_end_hour", 6))        # 6 AM
    deep_start  = float(args.get("deep_nadir_start_hour", 2)) # 2 AM
    deep_end    = float(args.get("deep_nadir_end_hour", 5))   # 5 AM
    min_readings = int(args.get("min_overnight_readings", 6))  # need ~30 min coverage

    # ── Discover all CGM days from S3 ─────────────────────────────────────
    paginator = s3_client.get_paginator("list_objects_v2")
    cgm_days = []  # list of "YYYY-MM-DD"
    for prefix_year in ["2024/", "2025/", "2026/"]:
        try:
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"raw/cgm_readings/{prefix_year}"):
                for obj in page.get("Contents", []):
                    key = obj["Key"]  # raw/cgm_readings/2024/10/01.json
                    parts = key.replace("raw/cgm_readings/", "").replace(".json", "").split("/")
                    if len(parts) == 3:
                        y, m, d = parts
                        cgm_days.append(f"{y}-{m.zfill(2)}-{d.zfill(2)}")
        except Exception:
            continue
    cgm_days.sort()

    if not cgm_days:
        return {"error": "No CGM data found in S3."}

    # ── Compute overnight nadirs for each day ────────────────────────────
    nadir_results = []  # list of dicts per day
    for date_str in cgm_days:
        readings = _load_cgm_readings(date_str)
        if not readings:
            continue

        # Filter to overnight window (midnight to nadir_end)
        overnight = [(h, v) for h, v in readings if nadir_start <= h < nadir_end]
        deep_night = [(h, v) for h, v in readings if deep_start <= h < deep_end]

        if len(overnight) < min_readings:
            continue

        overnight_vals = [v for _, v in overnight]
        on_min = min(overnight_vals)
        on_avg = sum(overnight_vals) / len(overnight_vals)
        on_min_time = None
        for h, v in overnight:
            if v == on_min:
                hh = int(h)
                mm = int((h - hh) * 60)
                on_min_time = f"{hh:02d}:{mm:02d}"
                break

        deep_min = None
        deep_avg = None
        if len(deep_night) >= 4:
            deep_vals = [v for _, v in deep_night]
            deep_min = min(deep_vals)
            deep_avg = round(sum(deep_vals) / len(deep_vals), 1)

        # Full-day min for comparison (current proxy method)
        all_vals = [v for _, v in readings]
        daily_min = min(all_vals) if all_vals else None

        nadir_results.append({
            "date": date_str,
            "overnight_nadir": on_min,
            "overnight_avg": round(on_avg, 1),
            "overnight_nadir_time": on_min_time,
            "overnight_readings": len(overnight),
            "deep_nadir": deep_min,
            "deep_avg": deep_avg,
            "daily_min": daily_min,
            "daily_min_vs_overnight": round(daily_min - on_min, 1) if daily_min is not None else None,
        })

    if not nadir_results:
        return {"error": "Insufficient overnight CGM readings across all days."}

    # ── Distribution stats ───────────────────────────────────────────────
    on_nadirs = [r["overnight_nadir"] for r in nadir_results]
    deep_nadirs = [r["deep_nadir"] for r in nadir_results if r["deep_nadir"] is not None]
    daily_mins = [r["daily_min"] for r in nadir_results if r["daily_min"] is not None]

    def dist_stats(vals, label):
        if not vals:
            return None
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "label": label,
            "n": n,
            "mean": round(statistics.mean(vals_sorted), 1),
            "median": round(statistics.median(vals_sorted), 1),
            "std_dev": round(statistics.stdev(vals_sorted), 1) if n > 1 else 0,
            "min": vals_sorted[0],
            "max": vals_sorted[-1],
            "p10": round(vals_sorted[int(n * 0.1)], 1),
            "p25": round(vals_sorted[int(n * 0.25)], 1),
            "p75": round(vals_sorted[int(n * 0.75)], 1),
            "p90": round(vals_sorted[int(n * 0.9)], 1),
        }

    distributions = {
        "overnight_nadir_00_06": dist_stats(on_nadirs, "Overnight nadir (00:00-06:00)"),
        "deep_nadir_02_05": dist_stats(deep_nadirs, "Deep nadir (02:00-05:00)"),
        "daily_minimum": dist_stats(daily_mins, "Daily minimum (current proxy)"),
    }

    # ── Load lab fasting glucose ─────────────────────────────────────────
    table = get_table()
    from boto3.dynamodb.conditions import Key
    lab_resp = table.query(
        KeyConditionExpression=Key("pk").eq(USER_PREFIX + "labs") & Key("sk").begins_with("DATE#")
    )
    lab_draws = []
    for item in lab_resp.get("Items", []):
        glucose_bm = item.get("biomarkers", {}).get("glucose", {})
        val = glucose_bm.get("value_numeric")
        if val is not None:
            lab_draws.append({
                "draw_date": item.get("draw_date"),
                "fasting_glucose_mg_dl": float(val),
                "provider": item.get("lab_provider", "unknown"),
            })

    # ── Direct validation (same-day overlap) ─────────────────────────────
    nadir_by_date = {r["date"]: r for r in nadir_results}
    direct_validations = []
    for draw in lab_draws:
        dd = draw["draw_date"]
        if dd in nadir_by_date:
            nr = nadir_by_date[dd]
            diff_overnight = round(draw["fasting_glucose_mg_dl"] - nr["overnight_nadir"], 1)
            diff_deep = round(draw["fasting_glucose_mg_dl"] - nr["deep_nadir"], 1) if nr["deep_nadir"] else None
            direct_validations.append({
                "date": dd,
                "lab_fasting_glucose": draw["fasting_glucose_mg_dl"],
                "cgm_overnight_nadir": nr["overnight_nadir"],
                "cgm_deep_nadir": nr["deep_nadir"],
                "cgm_daily_min": nr["daily_min"],
                "lab_minus_cgm_overnight": diff_overnight,
                "lab_minus_cgm_deep": diff_deep,
                "provider": draw["provider"],
            })

    # ── Statistical validation (no overlap) ──────────────────────────────
    stat_validations = []
    on_stats = distributions["overnight_nadir_00_06"]
    deep_stats = distributions["deep_nadir_02_05"]

    for draw in lab_draws:
        lab_val = draw["fasting_glucose_mg_dl"]
        # Z-score vs overnight nadir distribution
        z_overnight = None
        if on_stats and on_stats["std_dev"] > 0:
            z_overnight = round((lab_val - on_stats["mean"]) / on_stats["std_dev"], 2)
        z_deep = None
        if deep_stats and deep_stats["std_dev"] > 0:
            z_deep = round((lab_val - deep_stats["mean"]) / deep_stats["std_dev"], 2)

        # Percentile estimate
        pct = None
        if on_nadirs:
            below = sum(1 for v in on_nadirs if v <= lab_val)
            pct = round(below / len(on_nadirs) * 100, 1)

        stat_validations.append({
            "draw_date": draw["draw_date"],
            "lab_fasting_glucose": lab_val,
            "vs_overnight_nadir": {
                "z_score": z_overnight,
                "percentile_of_nadir_dist": pct,
                "within_1sd": abs(z_overnight) <= 1 if z_overnight is not None else None,
                "within_2sd": abs(z_overnight) <= 2 if z_overnight is not None else None,
            },
            "vs_deep_nadir": {
                "z_score": z_deep,
                "within_1sd": abs(z_deep) <= 1 if z_deep is not None else None,
            } if z_deep is not None else None,
            "provider": draw["provider"],
        })

    # ── Bias analysis ────────────────────────────────────────────────────
    bias = {}
    if on_stats and lab_draws:
        lab_mean = sum(d["fasting_glucose_mg_dl"] for d in lab_draws) / len(lab_draws)
        bias["lab_mean_fasting"] = round(lab_mean, 1)
        bias["cgm_overnight_nadir_mean"] = on_stats["mean"]
        bias["cgm_daily_min_mean"] = distributions["daily_minimum"]["mean"] if distributions["daily_minimum"] else None
        bias["lab_minus_cgm_overnight"] = round(lab_mean - on_stats["mean"], 1)
        if distributions["daily_minimum"]:
            bias["lab_minus_cgm_daily_min"] = round(lab_mean - distributions["daily_minimum"]["mean"], 1)
        if deep_stats:
            bias["cgm_deep_nadir_mean"] = deep_stats["mean"]
            bias["lab_minus_cgm_deep"] = round(lab_mean - deep_stats["mean"], 1)

        # Interpretation
        diff = bias["lab_minus_cgm_overnight"]
        if abs(diff) <= 5:
            bias["interpretation"] = "Excellent agreement — CGM overnight nadir closely matches lab fasting glucose."
            bias["confidence"] = "high"
        elif abs(diff) <= 10:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = f"Good agreement — lab reads ~{abs(diff)} mg/dL {direction} than CGM nadir. Within expected CGM accuracy range (±10-15 mg/dL for Stelo)."
            bias["confidence"] = "moderate"
        elif abs(diff) <= 20:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = f"Moderate discrepancy — lab reads ~{abs(diff)} mg/dL {direction}. Dexcom Stelo has MARD ~9% which can produce this gap. Consider a same-day validation."
            bias["confidence"] = "low"
        else:
            bias["interpretation"] = f"Significant discrepancy ({abs(diff)} mg/dL). CGM interstitial glucose lags venous by design, but this gap warrants investigation. Could indicate sensor placement, calibration, or timing issues."
            bias["confidence"] = "very_low"

    # ── Insights ─────────────────────────────────────────────────────────
    insights = []

    # Daily min vs overnight nadir comparison
    if distributions["daily_minimum"] and on_stats:
        dm = distributions["daily_minimum"]["mean"]
        on = on_stats["mean"]
        diff = round(dm - on, 1)
        if abs(diff) > 3:
            insights.append(
                f"Daily minimum averages {dm} vs overnight nadir {on} ({diff:+.1f} mg/dL). "
                f"{'Daily min occurs outside overnight window — current proxy slightly underestimates true fasting.' if diff < 0 else 'Daily min typically IS the overnight nadir — current proxy is reasonable.'}"
            )
        else:
            insights.append(f"Daily minimum ({dm}) and overnight nadir ({on}) are very close — current fasting proxy is a good approximation.")

    # Deep nadir vs standard nadir
    if deep_stats and on_stats:
        diff = round(deep_stats["mean"] - on_stats["mean"], 1)
        if abs(diff) > 2:
            insights.append(
                f"Deep nadir (2-5 AM: {deep_stats['mean']}) differs from broad overnight (0-6 AM: {on_stats['mean']}) by {diff:+.1f} mg/dL. "
                f"Dawn phenomenon may be raising late-night readings."
            )

    # Variability
    if on_stats and on_stats["std_dev"] > 8:
        insights.append(f"High overnight nadir variability (SD {on_stats['std_dev']} mg/dL). Factors: meal timing, alcohol, sleep quality, stress.")
    elif on_stats and on_stats["std_dev"] < 4:
        insights.append(f"Very stable overnight nadirs (SD {on_stats['std_dev']} mg/dL) — strong metabolic consistency.")

    # Lab trend
    if len(lab_draws) >= 3:
        recent = lab_draws[-1]["fasting_glucose_mg_dl"]
        oldest = lab_draws[0]["fasting_glucose_mg_dl"]
        if recent > oldest + 5:
            insights.append(f"Lab fasting glucose trending up: {oldest} → {recent} mg/dL over {len(lab_draws)} draws. Monitor with CGM confirmation.")
        elif recent < oldest - 5:
            insights.append(f"Lab fasting glucose trending down: {oldest} → {recent} mg/dL — positive trajectory.")

    if not direct_validations:
        insights.append("No same-day CGM + lab data available. Schedule your next blood draw while wearing the Stelo for gold-standard validation.")

    return {
        "cgm_coverage": {
            "first_date": cgm_days[0],
            "last_date": cgm_days[-1],
            "total_cgm_days": len(cgm_days),
            "days_with_valid_overnight": len(nadir_results),
        },
        "distributions": distributions,
        "lab_draws": lab_draws,
        "direct_validations": direct_validations if direct_validations else "No same-day overlap between CGM and lab draws.",
        "statistical_validations": stat_validations,
        "bias_analysis": bias,
        "insights": insights,
        "methodology": {
            "overnight_window": f"{int(nadir_start):02d}:00 - {int(nadir_end):02d}:00",
            "deep_nadir_window": f"{int(deep_start):02d}:00 - {int(deep_end):02d}:00",
            "min_readings_required": min_readings,
            "cgm_device": "Dexcom Stelo (MARD ~9%)",
            "note": "Interstitial glucose (CGM) lags venous blood by 5-15 min and can differ by ±10-15 mg/dL. Lab draws are single-point; CGM captures continuous overnight minimum.",
        },
        "board_of_directors": {
            "Attia": "Fasting glucose <90 mg/dL is optimal. Overnight CGM nadir is more informative than a single lab draw — it captures the true metabolic baseline every night.",
            "Patrick": "Dawn phenomenon (4-7 AM cortisol rise) elevates glucose. The 2-5 AM deep nadir avoids this confounder and gives the cleanest fasting signal.",
            "Huberman": "Glucose regulation is a proxy for metabolic flexibility. Low overnight variability + clean nadirs indicate good insulin sensitivity and hepatic glucose control.",
        },
    }




# ── N=1 Experiment Framework (v2.34.0) ────────────────────────────────────────
EXPERIMENTS_PK = USER_PREFIX + "experiments"
TRAVEL_PK = USER_PREFIX + "travel"

# Metrics automatically compared in get_experiment_results.
# Each tuple: (source, field_path, display_name, higher_is_better)
# field_path supports nested access via "." (e.g. "activities.0.average_heartrate" would be complex;
# we stick to day-level aggregates).
_EXPERIMENT_METRICS = [
    # Sleep
    ("eightsleep", "sleep_score",                "Sleep Score",          True),
    ("eightsleep", "sleep_efficiency_pct",       "Sleep Efficiency %",   True),
    ("eightsleep", "deep_sleep_pct",             "Deep Sleep %",         True),
    ("eightsleep", "rem_sleep_pct",              "REM Sleep %",          True),
    ("eightsleep", "sleep_onset_latency_min",    "Sleep Onset Latency",  False),
    # Recovery
    ("whoop",      "recovery_score",             "Whoop Recovery",       True),
    ("whoop",      "hrv_rmssd",                  "HRV (rMSSD)",         True),
    ("whoop",      "resting_heart_rate",         "Resting HR",          False),
    # Stress & Energy
    ("garmin",     "average_stress_level",       "Garmin Stress",       False),
    ("garmin",     "body_battery_high",          "Body Battery Peak",   True),
    # Body
    ("withings",   "weight_lbs",                 "Weight (lbs)",        None),  # direction depends on goal
    # Nutrition
    ("macrofactor", "calories",                  "Calories",            None),
    ("macrofactor", "protein_g",                 "Protein (g)",         None),
    # Movement
    ("apple_health", "steps",                    "Steps",               True),
    # Glucose (if available)
    ("apple_health", "cgm_mean_glucose",         "Mean Glucose",        False),
    ("apple_health", "cgm_time_in_range_pct",    "CGM Time in Range %", True),
]


def _extract_metric(item, field_path):
    """Extract a numeric value from a DynamoDB item, handling nested dicts."""
    val = item
    for part in field_path.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def tool_create_experiment(args):
    """Create a new N=1 experiment.

    Tracks a specific protocol change (supplement, diet, sleep hygiene, training
    adjustment, etc.) with start date and metrics to monitor. The system will
    automatically compare the experiment period against the equivalent pre-period
    when you call get_experiment_results.

    Board of Directors rules:
      - One variable at a time (Huberman)
      - Minimum 14 days for meaningful signal (Attia)
      - Define success criteria upfront (Ferriss)
    """
    name       = (args.get("name") or "").strip()
    hypothesis = (args.get("hypothesis") or "").strip()
    start_date = (args.get("start_date") or "").strip()
    tags       = args.get("tags") or []
    notes      = (args.get("notes") or "").strip()

    if not name:
        raise ValueError("name is required (e.g. 'Creatine 5g daily', 'No caffeine after 10am')")
    if not hypothesis:
        raise ValueError("hypothesis is required (e.g. 'Will improve deep sleep % by >5%')")

    now = datetime.utcnow()
    if not start_date:
        start_date = now.strftime("%Y-%m-%d")

    # Generate a slug-style ID
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    exp_id = f"{slug}_{start_date}"
    sk = f"EXP#{exp_id}"

    # Check for duplicate
    existing = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if existing:
        raise ValueError(f"Experiment '{exp_id}' already exists. Choose a different name or start date.")

    item = {
        "pk":           EXPERIMENTS_PK,
        "sk":           sk,
        "experiment_id": exp_id,
        "name":         name,
        "hypothesis":   hypothesis,
        "start_date":   start_date,
        "end_date":     None,       # null = still active
        "status":       "active",   # active, completed, abandoned
        "tags":         tags,
        "notes":        notes,
        "outcome":      "",
        "created_at":   now.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Clean None values for DynamoDB
    clean_item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=clean_item)
    logger.info(f"create_experiment: created {exp_id}")

    return {
        "created":       True,
        "experiment_id": exp_id,
        "name":          name,
        "hypothesis":    hypothesis,
        "start_date":    start_date,
        "status":        "active",
        "tags":          tags,
        "board_of_directors": {
            "Huberman": "One variable at a time. Track for at least 2 weeks before drawing conclusions. Control for confounders: sleep timing, stress, travel.",
            "Attia":    "Define your primary endpoint now. What number would convince you this worked? Statistical noise requires ≥14 days of data.",
            "Ferriss":  "What does the minimum effective dose look like? Start with the smallest intervention that could produce a measurable change.",
        },
    }


def tool_list_experiments(args):
    """List all N=1 experiments with status and duration.

    Filter by status: active, completed, abandoned, or all.
    Shows days active, whether minimum duration (14d) has been met.
    """
    status_filter = args.get("status")  # None = all
    today = datetime.utcnow().strftime("%Y-%m-%d")

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"),
        ScanIndexForward=False,
    )
    items = resp.get("Items", [])

    results = []
    for item in items:
        status = item.get("status", "active")
        if status_filter and status != status_filter:
            continue

        start = item.get("start_date", "")
        end = item.get("end_date", today)
        try:
            days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
        except Exception:
            days = None

        results.append({
            "experiment_id": item.get("experiment_id", ""),
            "name":          item.get("name", ""),
            "hypothesis":    item.get("hypothesis", ""),
            "start_date":    start,
            "end_date":      item.get("end_date"),
            "status":        status,
            "days_active":   days,
            "min_duration_met": days is not None and days >= 14,
            "tags":          item.get("tags", []),
            "notes":         item.get("notes", ""),
            "outcome":       item.get("outcome", ""),
        })

    active = sum(1 for r in results if r["status"] == "active")
    completed = sum(1 for r in results if r["status"] == "completed")

    return {
        "total":     len(results),
        "active":    active,
        "completed": completed,
        "filter":    status_filter or "all",
        "experiments": results,
    }


def tool_get_experiment_results(args):
    """Auto-compare before vs during metrics for an experiment.

    Computes the mean of key health metrics for:
      - BEFORE period: same number of days immediately before the experiment start
      - DURING period: experiment start to end (or today if still active)

    Reports: metric name, before mean, during mean, delta, % change, direction.

    Board of Directors evaluates the results with context from the hypothesis.
    """
    exp_id = (args.get("experiment_id") or "").strip()
    if not exp_id:
        raise ValueError("experiment_id is required")

    sk = f"EXP#{exp_id}"
    item = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if not item:
        raise ValueError(f"No experiment found with id={exp_id}")

    start_date = item.get("start_date", "")
    end_date = item.get("end_date") or datetime.utcnow().strftime("%Y-%m-%d")
    status = item.get("status", "active")
    hypothesis = item.get("hypothesis", "")

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid start_date or end_date on experiment")

    during_days = (end_dt - start_dt).days
    if during_days < 1:
        return {"error": "Experiment has less than 1 day of data. Check back later."}

    # Before period = same number of days before start
    before_start = (start_dt - timedelta(days=during_days)).strftime("%Y-%m-%d")
    before_end = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    during_start = start_date
    during_end = end_date

    # Gather unique sources needed
    sources_needed = list(set(m[0] for m in _EXPERIMENT_METRICS))

    # Query before + during in parallel
    before_data = {}
    during_data = {}
    for src in sources_needed:
        try:
            before_items = query_source(src, before_start, before_end)
            during_items = query_source(src, during_start, during_end)
            before_data[src] = before_items
            during_data[src] = during_items
        except Exception as e:
            logger.warning(f"get_experiment_results: failed to query {src}: {e}")

    # Compute metric comparisons
    comparisons = []
    for source, field, display_name, higher_is_better in _EXPERIMENT_METRICS:
        before_vals = []
        during_vals = []

        for item_b in before_data.get(source, []):
            v = _extract_metric(item_b, field)
            if v is not None:
                before_vals.append(v)

        for item_d in during_data.get(source, []):
            v = _extract_metric(item_d, field)
            if v is not None:
                during_vals.append(v)

        # Need at least 3 data points in each period for meaningful comparison
        if len(before_vals) < 3 or len(during_vals) < 3:
            continue

        before_mean = sum(before_vals) / len(before_vals)
        during_mean = sum(during_vals) / len(during_vals)
        delta = during_mean - before_mean
        pct_change = (delta / before_mean * 100) if before_mean != 0 else None

        # Determine if change is favorable
        if higher_is_better is True:
            direction = "improved" if delta > 0 else ("worsened" if delta < 0 else "unchanged")
        elif higher_is_better is False:
            direction = "improved" if delta < 0 else ("worsened" if delta > 0 else "unchanged")
        else:
            direction = "increased" if delta > 0 else ("decreased" if delta < 0 else "unchanged")

        comparisons.append({
            "metric":        display_name,
            "source":        source,
            "before_mean":   round(before_mean, 2),
            "during_mean":   round(during_mean, 2),
            "delta":         round(delta, 2),
            "pct_change":    round(pct_change, 1) if pct_change is not None else None,
            "direction":     direction,
            "before_n":      len(before_vals),
            "during_n":      len(during_vals),
        })

    # Sort: improved first, then worsened, then unchanged
    order = {"improved": 0, "worsened": 1, "increased": 2, "decreased": 3, "unchanged": 4}
    comparisons.sort(key=lambda c: order.get(c["direction"], 5))

    improved = [c for c in comparisons if c["direction"] == "improved"]
    worsened = [c for c in comparisons if c["direction"] == "worsened"]

    # Minimum duration warning
    min_duration_met = during_days >= 14
    duration_warning = None
    if not min_duration_met:
        duration_warning = (
            f"Only {during_days} days of data. Board recommends minimum 14 days "
            f"for reliable signal. Results may be noise."
        )

    return {
        "experiment": {
            "id":         exp_id,
            "name":       item.get("name", ""),
            "hypothesis": hypothesis,
            "status":     status,
            "start_date": start_date,
            "end_date":   end_date if status != "active" else f"{end_date} (ongoing)",
        },
        "comparison_period": {
            "before": f"{before_start} → {before_end} ({during_days} days)",
            "during": f"{during_start} → {during_end} ({during_days} days)",
        },
        "duration_warning":  duration_warning,
        "metrics_compared":  len(comparisons),
        "improved_count":    len(improved),
        "worsened_count":    len(worsened),
        "comparisons":       comparisons,
        "board_of_directors": {
            "Attia": (
                f"{'✅ Minimum 14-day threshold met.' if min_duration_met else '⚠️ Under 14 days — treat as preliminary.'} "
                f"{'Strong signal: ' + str(len(improved)) + ' metrics improved.' if len(improved) > len(worsened) else ''} "
                f"Look at effect sizes, not just direction. A 1% change is noise; 5%+ over 14+ days is signal."
            ),
            "Huberman": (
                "Check for confounders: did sleep timing, stress, travel, or other habits change during this period? "
                "The strongest signal is when multiple related metrics move in the same direction."
            ),
            "Ferriss": (
                f"Hypothesis: '{hypothesis}'. "
                f"{'The data supports this hypothesis.' if len(improved) > len(worsened) else 'The data does not clearly support this hypothesis.'} "
                "Consider: is the juice worth the squeeze? Even a positive result needs to be sustainable."
            ),
        },
    }


def tool_end_experiment(args):
    """End an active experiment and record the outcome.

    Marks the experiment as 'completed' or 'abandoned' with outcome notes.
    Run get_experiment_results first to see the data before closing.
    """
    exp_id  = (args.get("experiment_id") or "").strip()
    outcome = (args.get("outcome") or "").strip()
    status  = (args.get("status") or "completed").strip()
    end_date = (args.get("end_date") or "").strip()

    if not exp_id:
        raise ValueError("experiment_id is required")
    if status not in ("completed", "abandoned"):
        raise ValueError("status must be 'completed' or 'abandoned'")

    sk = f"EXP#{exp_id}"
    existing = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"No experiment found with id={exp_id}")
    if existing.get("status") != "active":
        raise ValueError(f"Experiment is already {existing.get('status')} — cannot end again")

    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")

    table.update_item(
        Key={"pk": EXPERIMENTS_PK, "sk": sk},
        UpdateExpression="SET #s = :s, outcome = :o, end_date = :e, ended_at = :ea",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s":  status,
            ":o":  outcome,
            ":e":  end_date,
            ":ea": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    logger.info(f"end_experiment: {exp_id} → {status}")

    start_date = existing.get("start_date", "")
    try:
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
    except Exception:
        days = None

    return {
        "ended":         True,
        "experiment_id": exp_id,
        "name":          existing.get("name", ""),
        "status":        status,
        "start_date":    start_date,
        "end_date":      end_date,
        "days_run":      days,
        "outcome":       outcome,
        "tip":           "Run get_experiment_results to see the full before/after comparison.",
    }



# ── Tool: get_health_trajectory (v2.34.0) ─────────────────────────────────────

def tool_get_health_trajectory(args):
    """
    Forward-looking health intelligence.

    Computes trajectories and projections across multiple domains:
      1. Weight: rate of loss, phase milestones, projected goal date
      2. Biomarkers: lab trend slopes, projected next-draw values
      3. Fitness: Zone 2 weekly trend, training consistency
      4. Recovery: HRV trend, sleep efficiency trend
      5. Body composition: lean mass preservation estimate

    Returns projections at 3, 6, and 12 months with confidence levels.
    Board of Directors provides longevity-focused assessment.
    """
    import statistics

    today = datetime.utcnow()
    today_str = today.strftime("%Y-%m-%d")
    profile = get_profile()

    domain = (args.get("domain") or "all").lower()
    valid_domains = ["all", "weight", "biomarkers", "fitness", "recovery", "metabolic"]
    if domain not in valid_domains:
        raise ValueError(f"domain must be one of: {valid_domains}")

    result = {}

    # ── 1. Weight Trajectory ──────────────────────────────────────────────
    if domain in ("all", "weight"):
        weight_data = query_source("withings", (today - timedelta(days=120)).strftime("%Y-%m-%d"), today_str)
        weights = []
        for item in weight_data:
            w = item.get("weight_lbs")
            d = item.get("date")
            if w and d:
                try:
                    weights.append((datetime.strptime(d, "%Y-%m-%d"), float(w)))
                except (ValueError, TypeError):
                    pass

        weights.sort(key=lambda x: x[0])

        if len(weights) >= 7:
            # Recent rate: last 4 weeks
            four_weeks_ago = today - timedelta(days=28)
            recent = [(d, w) for d, w in weights if d >= four_weeks_ago]

            if len(recent) >= 4:
                # Linear regression for recent rate
                x_vals = [(d - recent[0][0]).days for d, w in recent]
                y_vals = [w for d, w in recent]
                n = len(x_vals)
                sx = sum(x_vals)
                sy = sum(y_vals)
                sxy = sum(x * y for x, y in zip(x_vals, y_vals))
                sxx = sum(x * x for x in x_vals)
                denom = n * sxx - sx * sx
                if denom != 0:
                    slope_per_day = (n * sxy - sx * sy) / denom
                    intercept = (sy - slope_per_day * sx) / n
                else:
                    slope_per_day = 0
                    intercept = y_vals[0]

                weekly_rate = slope_per_day * 7
                current_weight = weights[-1][1]
                goal_weight = float(profile.get("goal_weight_lbs", 185))

                # Project goal date
                if slope_per_day < 0 and current_weight > goal_weight:
                    days_to_goal = (current_weight - goal_weight) / abs(slope_per_day)
                    projected_goal_date = (today + timedelta(days=days_to_goal)).strftime("%Y-%m-%d")
                else:
                    days_to_goal = None
                    projected_goal_date = None

                # Profile-based phases
                phases = profile.get("weight_loss_phases", [])
                phase_projections = []
                for phase in phases:
                    phase_end = float(phase.get("end_lbs", 0))
                    if current_weight > phase_end and slope_per_day < 0:
                        days = (current_weight - phase_end) / abs(slope_per_day)
                        phase_projections.append({
                            "phase":          phase.get("name", ""),
                            "target_lbs":     phase_end,
                            "projected_date": (today + timedelta(days=days)).strftime("%Y-%m-%d"),
                            "days_away":      int(days),
                            "target_rate":    float(phase.get("weekly_target_lbs", 0)),
                            "actual_rate":    round(abs(weekly_rate), 2),
                            "on_pace":        abs(weekly_rate) >= float(phase.get("weekly_target_lbs", 0)) * 0.8,
                        })

                # Projections at intervals
                projections = {}
                for label, days_out in [("3_months", 90), ("6_months", 180), ("12_months", 365)]:
                    proj = current_weight + (slope_per_day * days_out)
                    projections[label] = {
                        "projected_weight": round(max(proj, goal_weight), 1),
                        "lbs_from_goal":    round(max(proj, goal_weight) - goal_weight, 1),
                    }

                # Journey progress
                start_weight = float(profile.get("journey_start_weight_lbs", current_weight))
                total_to_lose = start_weight - goal_weight
                lost_so_far = start_weight - current_weight
                pct_complete = round(lost_so_far / total_to_lose * 100, 1) if total_to_lose > 0 else 0

                result["weight"] = {
                    "current_weight":       round(current_weight, 1),
                    "goal_weight":          goal_weight,
                    "weekly_rate_lbs":      round(weekly_rate, 2),
                    "daily_rate_lbs":       round(slope_per_day, 3),
                    "data_points_used":     len(recent),
                    "projected_goal_date":  projected_goal_date,
                    "days_to_goal":         int(days_to_goal) if days_to_goal else None,
                    "journey_progress_pct": pct_complete,
                    "lost_so_far":          round(lost_so_far, 1),
                    "remaining":            round(current_weight - goal_weight, 1),
                    "phase_milestones":     phase_projections,
                    "projections":          projections,
                    "trend_direction":      "losing" if weekly_rate < -0.3 else ("gaining" if weekly_rate > 0.3 else "stable"),
                }
            else:
                result["weight"] = {"message": "Need more recent data (< 4 data points in last 28 days)."}
        else:
            result["weight"] = {"message": "Need at least 7 weight measurements for trajectory analysis."}

    # ── 2. Biomarker Trajectories ─────────────────────────────────────────
    if domain in ("all", "biomarkers"):
        try:
            lab_draws = _query_all_lab_draws()
            if len(lab_draws) >= 3:
                # Key biomarkers to track
                key_biomarkers = [
                    ("ldl_c",           "LDL Cholesterol",   "mg/dL", None,   100, "below"),
                    ("hdl_c",           "HDL Cholesterol",   "mg/dL", 40,     None, "above"),
                    ("triglycerides",   "Triglycerides",     "mg/dL", None,   150, "below"),
                    ("hba1c",           "HbA1c",             "%",     None,   5.7, "below"),
                    ("glucose",         "Fasting Glucose",   "mg/dL", None,   100, "below"),
                    ("crp",             "CRP",               "mg/L",  None,   1.0, "below"),
                    ("tsh",             "TSH",               "mIU/L", 0.5,    4.0, "within"),
                    ("vitamin_d",       "Vitamin D",         "ng/mL", 40,     None, "above"),
                    ("ferritin",        "Ferritin",          "ng/mL", 30,     None, "above"),
                    ("testosterone_total", "Testosterone",   "ng/dL", 300,    None, "above"),
                ]

                bio_results = []
                for key, name, unit, low_thresh, high_thresh, direction in key_biomarkers:
                    points = []
                    for draw in lab_draws:
                        d = draw.get("date") or draw.get("sk", "").replace("DATE#", "")
                        biomarkers = draw.get("biomarkers", draw)
                        val = biomarkers.get(key)
                        if val is not None and d:
                            try:
                                points.append((datetime.strptime(d[:10], "%Y-%m-%d"), float(val)))
                            except (ValueError, TypeError):
                                pass

                    if len(points) < 2:
                        continue

                    points.sort(key=lambda x: x[0])

                    # Linear regression
                    x_vals = [(d - points[0][0]).days for d, v in points]
                    y_vals = [v for d, v in points]
                    n = len(x_vals)
                    sx = sum(x_vals)
                    sy = sum(y_vals)
                    sxy = sum(x * y for x, y in zip(x_vals, y_vals))
                    sxx = sum(x * x for x in x_vals)
                    denom = n * sxx - sx * sx

                    if denom != 0:
                        slope_per_day = (n * sxy - sx * sy) / denom
                    else:
                        slope_per_day = 0

                    slope_per_year = slope_per_day * 365.25
                    current_val = points[-1][1]

                    # Project 6 months out
                    proj_6mo = current_val + (slope_per_day * 180)

                    # Check if trending toward concern
                    concern = None
                    if direction == "below" and high_thresh and slope_per_year > 0 and proj_6mo > high_thresh:
                        concern = f"Trending toward {high_thresh} {unit} threshold"
                    elif direction == "above" and low_thresh and slope_per_year < 0 and proj_6mo < low_thresh:
                        concern = f"Trending toward {low_thresh} {unit} threshold"

                    bio_results.append({
                        "biomarker":        name,
                        "key":              key,
                        "current_value":    round(current_val, 1),
                        "unit":             unit,
                        "slope_per_year":   round(slope_per_year, 2),
                        "trend":            "rising" if slope_per_year > 0.5 else ("falling" if slope_per_year < -0.5 else "stable"),
                        "projected_6mo":    round(proj_6mo, 1),
                        "draws_used":       len(points),
                        "first_draw":       points[0][0].strftime("%Y-%m-%d"),
                        "latest_draw":      points[-1][0].strftime("%Y-%m-%d"),
                        "concern":          concern,
                    })

                # Sort: concerns first
                bio_results.sort(key=lambda b: (0 if b["concern"] else 1, b["biomarker"]))
                concerns = [b for b in bio_results if b["concern"]]

                result["biomarkers"] = {
                    "total_draws":     len(lab_draws),
                    "biomarkers_tracked": len(bio_results),
                    "concerns":        len(concerns),
                    "trajectories":    bio_results,
                }
            else:
                result["biomarkers"] = {"message": f"Need at least 3 lab draws for trajectory (have {len(lab_draws)})."}
        except Exception as e:
            logger.warning(f"Biomarker trajectory error: {e}")
            result["biomarkers"] = {"error": str(e)}

    # ── 3. Fitness Trajectory ─────────────────────────────────────────────
    if domain in ("all", "fitness"):
        try:
            strava_data = query_source("strava", (today - timedelta(days=90)).strftime("%Y-%m-%d"), today_str)

            if len(strava_data) >= 7:
                # Weekly training volume (hours)
                weekly_hours = {}
                weekly_zone2 = {}
                for item in strava_data:
                    d = item.get("date", "")
                    try:
                        dt = datetime.strptime(d, "%Y-%m-%d")
                        week_key = dt.strftime("%Y-W%U")
                    except ValueError:
                        continue
                    secs = float(item.get("total_moving_time_seconds", 0))
                    z2 = float(item.get("total_zone2_seconds", 0))
                    weekly_hours[week_key] = weekly_hours.get(week_key, 0) + secs / 3600
                    weekly_zone2[week_key] = weekly_zone2.get(week_key, 0) + z2 / 60

                weeks_sorted = sorted(weekly_hours.keys())
                if len(weeks_sorted) >= 4:
                    recent_4 = weeks_sorted[-4:]
                    avg_weekly_hours = sum(weekly_hours[w] for w in recent_4) / 4
                    avg_weekly_z2 = sum(weekly_zone2.get(w, 0) for w in recent_4) / 4

                    # Trend: first half vs second half of window
                    mid = len(weeks_sorted) // 2
                    first_half_hours = [weekly_hours[w] for w in weeks_sorted[:mid]]
                    second_half_hours = [weekly_hours[w] for w in weeks_sorted[mid:]]
                    first_avg = sum(first_half_hours) / len(first_half_hours) if first_half_hours else 0
                    second_avg = sum(second_half_hours) / len(second_half_hours) if second_half_hours else 0
                    volume_trend = "increasing" if second_avg > first_avg * 1.1 else ("decreasing" if second_avg < first_avg * 0.9 else "stable")

                    # Zone 2 target
                    z2_target = float(profile.get("zone2_weekly_target_min", 150))
                    z2_pct = round(avg_weekly_z2 / z2_target * 100, 0) if z2_target > 0 else 0

                    # Training consistency (% of weeks with any activity)
                    total_weeks = len(weeks_sorted)
                    active_weeks = sum(1 for w in weeks_sorted if weekly_hours[w] > 0.5)
                    consistency = round(active_weeks / total_weeks * 100, 0) if total_weeks > 0 else 0

                    result["fitness"] = {
                        "avg_weekly_hours":     round(avg_weekly_hours, 1),
                        "avg_weekly_zone2_min": round(avg_weekly_z2, 0),
                        "zone2_target_min":     z2_target,
                        "zone2_target_pct":     z2_pct,
                        "volume_trend":         volume_trend,
                        "training_consistency_pct": consistency,
                        "weeks_analyzed":       total_weeks,
                        "active_weeks":         active_weeks,
                        "attia_assessment":     (
                            "Meeting Zone 2 target" if z2_pct >= 90
                            else f"Zone 2 at {z2_pct}% of target — increase easy cardio"
                        ),
                    }
                else:
                    result["fitness"] = {"message": "Need at least 4 weeks of data."}
            else:
                result["fitness"] = {"message": "Insufficient Strava data for trajectory."}
        except Exception as e:
            logger.warning(f"Fitness trajectory error: {e}")
            result["fitness"] = {"error": str(e)}

    # ── 4. Recovery Trajectory ────────────────────────────────────────────
    if domain in ("all", "recovery"):
        try:
            whoop_data = query_source("whoop", (today - timedelta(days=60)).strftime("%Y-%m-%d"), today_str)
            es_data = query_source("eightsleep", (today - timedelta(days=60)).strftime("%Y-%m-%d"), today_str)

            hrv_vals = []
            rhr_vals = []
            recovery_vals = []
            sleep_eff_vals = []

            for item in whoop_data:
                hrv = item.get("hrv_rmssd")
                rhr = item.get("resting_heart_rate")
                rec = item.get("recovery_score")
                if hrv: hrv_vals.append(float(hrv))
                if rhr: rhr_vals.append(float(rhr))
                if rec: recovery_vals.append(float(rec))

            for item in es_data:
                eff = item.get("sleep_efficiency_pct")
                if eff: sleep_eff_vals.append(float(eff))

            recovery_result = {}

            if len(hrv_vals) >= 14:
                first_half = hrv_vals[:len(hrv_vals)//2]
                second_half = hrv_vals[len(hrv_vals)//2:]
                hrv_trend = "improving" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) * 1.05 else                            ("declining" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) * 0.95 else "stable")
                recovery_result["hrv"] = {
                    "current_avg":  round(sum(hrv_vals[-7:]) / min(len(hrv_vals), 7), 1),
                    "60d_avg":      round(sum(hrv_vals) / len(hrv_vals), 1),
                    "trend":        hrv_trend,
                    "data_points":  len(hrv_vals),
                }

            if len(rhr_vals) >= 14:
                first_half = rhr_vals[:len(rhr_vals)//2]
                second_half = rhr_vals[len(rhr_vals)//2:]
                rhr_trend = "improving" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) * 0.97 else                            ("worsening" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) * 1.03 else "stable")
                recovery_result["rhr"] = {
                    "current_avg":  round(sum(rhr_vals[-7:]) / min(len(rhr_vals), 7), 1),
                    "60d_avg":      round(sum(rhr_vals) / len(rhr_vals), 1),
                    "trend":        rhr_trend,
                    "data_points":  len(rhr_vals),
                }

            if len(sleep_eff_vals) >= 14:
                first_half = sleep_eff_vals[:len(sleep_eff_vals)//2]
                second_half = sleep_eff_vals[len(sleep_eff_vals)//2:]
                eff_trend = "improving" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) + 1 else                            ("declining" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) - 1 else "stable")
                recovery_result["sleep_efficiency"] = {
                    "current_avg":  round(sum(sleep_eff_vals[-7:]) / min(len(sleep_eff_vals), 7), 1),
                    "60d_avg":      round(sum(sleep_eff_vals) / len(sleep_eff_vals), 1),
                    "trend":        eff_trend,
                    "data_points":  len(sleep_eff_vals),
                }

            if recovery_result:
                result["recovery"] = recovery_result
            else:
                result["recovery"] = {"message": "Need at least 14 days of Whoop/Eight Sleep data."}
        except Exception as e:
            logger.warning(f"Recovery trajectory error: {e}")
            result["recovery"] = {"error": str(e)}

    # ── 5. Metabolic Trajectory ───────────────────────────────────────────
    if domain in ("all", "metabolic"):
        try:
            cgm_data = query_source("apple_health", (today - timedelta(days=60)).strftime("%Y-%m-%d"), today_str)
            glucose_vals = []
            tir_vals = []
            for item in cgm_data:
                mean_g = item.get("cgm_mean_glucose")
                tir = item.get("cgm_time_in_range_pct")
                if mean_g:
                    glucose_vals.append(float(mean_g))
                if tir:
                    tir_vals.append(float(tir))

            metabolic = {}
            if len(glucose_vals) >= 7:
                first_half = glucose_vals[:len(glucose_vals)//2]
                second_half = glucose_vals[len(glucose_vals)//2:]
                glucose_trend = "improving" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) - 1 else                                ("worsening" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) + 1 else "stable")
                metabolic["mean_glucose"] = {
                    "current_avg":  round(sum(glucose_vals[-7:]) / min(len(glucose_vals), 7), 1),
                    "period_avg":   round(sum(glucose_vals) / len(glucose_vals), 1),
                    "trend":        glucose_trend,
                    "target":       "< 100 mg/dL (Attia optimal)",
                    "data_points":  len(glucose_vals),
                }
            if len(tir_vals) >= 7:
                metabolic["time_in_range"] = {
                    "current_avg":  round(sum(tir_vals[-7:]) / min(len(tir_vals), 7), 1),
                    "period_avg":   round(sum(tir_vals) / len(tir_vals), 1),
                    "target":       "> 90% (optimal metabolic health)",
                    "data_points":  len(tir_vals),
                }
            if metabolic:
                result["metabolic"] = metabolic
            else:
                result["metabolic"] = {"message": "Insufficient CGM data for metabolic trajectory."}
        except Exception as e:
            logger.warning(f"Metabolic trajectory error: {e}")
            result["metabolic"] = {"error": str(e)}

    # ── Board of Directors Assessment ─────────────────────────────────────
    concerns = []
    positives = []

    if "weight" in result and isinstance(result["weight"], dict) and "trend_direction" in result["weight"]:
        w = result["weight"]
        if w["trend_direction"] == "losing":
            positives.append(f"Weight loss on track at {abs(w['weekly_rate_lbs'])} lbs/week")
        elif w["trend_direction"] == "gaining":
            concerns.append(f"Weight trending up ({w['weekly_rate_lbs']} lbs/week)")

    if "biomarkers" in result and isinstance(result["biomarkers"], dict) and "concerns" in result["biomarkers"]:
        n_concerns = result["biomarkers"]["concerns"]
        if n_concerns > 0:
            concerns.append(f"{n_concerns} biomarker(s) trending toward concerning levels")
        else:
            positives.append("All tracked biomarkers within acceptable trajectories")

    if "fitness" in result and isinstance(result["fitness"], dict) and "zone2_target_pct" in result["fitness"]:
        z2 = result["fitness"]["zone2_target_pct"]
        if z2 >= 90:
            positives.append(f"Zone 2 target met ({z2}%)")
        else:
            concerns.append(f"Zone 2 at {z2}% of target — increase easy cardio")

    if "recovery" in result and isinstance(result["recovery"], dict):
        hrv_info = result["recovery"].get("hrv", {})
        if hrv_info.get("trend") == "improving":
            positives.append("HRV trend improving — fitness adaptation positive")
        elif hrv_info.get("trend") == "declining":
            concerns.append("HRV declining — possible overtraining, stress, or sleep debt")

    result["board_of_directors"] = {
        "summary": {
            "positives":  positives,
            "concerns":   concerns,
            "overall":    "on_track" if len(positives) >= len(concerns) else "attention_needed",
        },
        "Attia": (
            "The trajectory is more important than any single data point. Focus on the slopes, not the snapshots. "
            "Weight loss rate, biomarker trends, and Zone 2 consistency are the three pillars of your longevity trajectory."
        ),
        "Patrick": (
            "Biomarker slopes are early warning signals. A rising LDL or declining vitamin D can be intercepted "
            "months before they become clinical problems. Review the concern flags carefully."
        ),
        "Huberman": (
            "Consistency compounds. Your training consistency percentage is a better predictor of outcomes than "
            "any single workout. Behavioral momentum creates physiological momentum."
        ),
        "Ferriss": (
            "What is the ONE metric that, if improved, would move everything else? "
            "For most people in a transformation, it is sleep quality — it amplifies recovery, willpower, and metabolic function."
        ),
    }

    result["generated_at"] = today_str
    result["domain_requested"] = domain

    return result

# ── Lambda handler ────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    # EventBridge scheduled rule — run nightly cache warmer, no auth needed
    if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
        logger.info("[lambda_handler] EventBridge trigger — running nightly cache warmer")
        result = nightly_cache_warmer()
        return {"statusCode": 200, "body": json.dumps(result),
                "headers": {"Content-Type": "application/json"}}

    expected_key = get_api_key()
    if expected_key:
        provided_key = (event.get("headers") or {}).get("x-api-key", "")
        if provided_key != expected_key:
            return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"}),
                    "headers": {"Content-Type": "application/json"}}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"}),
                "headers": {"Content-Type": "application/json"}}

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})
    logger.info(f"MCP request: method={method} id={rpc_id}")

    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return {
            "statusCode": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32601, "message": f"Method not found: {method}"}}),
            "headers": {"Content-Type": "application/json"},
        }

    try:
        result = handler(params)
        if result is None:
            return {"statusCode": 204, "body": ""}
        response_body = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except ValueError as e:
        response_body = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": str(e)}}
    except Exception as e:
        logger.error(f"Tool error: {e}", exc_info=True)
        response_body = {"jsonrpc": "2.0", "id": rpc_id,
                         "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}

    return {
        "statusCode": 200,
        "body":       json.dumps(response_body, default=str),
        "headers":    {"Content-Type": "application/json"},
    }



# ── Feature #12: Social Connection Scoring ─────────────────────────────────────

def tool_get_social_connection_trend(args):
    """
    Aggregates enriched_social_quality from journal entries over time.
    Tracks social connection quality, streaks, rolling averages, and
    correlates with health outcomes. Seligman PERMA model.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    QUALITY_MAP = {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4}

    journal_items = query_source("notion", start_date, end_date)
    if not journal_items:
        return {"error": "No journal data for range.", "start_date": start_date, "end_date": end_date}

    daily_social = {}
    daily_mood = {}
    daily_energy = {}
    daily_stress = {}
    for item in journal_items:
        d = item.get("date")
        if not d:
            continue
        sq = item.get("enriched_social_quality")
        if sq and sq in QUALITY_MAP:
            score = QUALITY_MAP[sq]
            if d not in daily_social or score > daily_social[d]["score"]:
                daily_social[d] = {"quality": sq, "score": score}
        for field, store in [("enriched_mood", daily_mood), ("enriched_energy", daily_energy), ("enriched_stress", daily_stress)]:
            v = _sf(item.get(field))
            if v is not None:
                store[d] = v

    if not daily_social:
        return {"error": "No enriched_social_quality data found.", "entries_checked": len(journal_items)}

    sorted_dates = sorted(daily_social.keys())
    scores = [daily_social[d]["score"] for d in sorted_dates]

    distribution = {}
    for d, info in daily_social.items():
        q = info["quality"]
        distribution[q] = distribution.get(q, 0) + 1

    rolling_7d = []
    rolling_30d = []
    for i, d in enumerate(sorted_dates):
        w7 = scores[max(0, i-6):i+1]
        w30 = scores[max(0, i-29):i+1]
        rolling_7d.append({"date": d, "avg": round(sum(w7)/len(w7), 2)})
        rolling_30d.append({"date": d, "avg": round(sum(w30)/len(w30), 2)})

    current_streak = 0
    longest_streak = 0
    temp_streak = 0
    for d in sorted_dates:
        if daily_social[d]["score"] >= 3:
            temp_streak += 1
            longest_streak = max(longest_streak, temp_streak)
        else:
            temp_streak = 0
    for d in reversed(sorted_dates):
        if daily_social[d]["score"] >= 3:
            current_streak += 1
        else:
            break

    days_since_meaningful = None
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for d in reversed(sorted_dates):
        if daily_social[d]["score"] >= 3:
            days_since_meaningful = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days
            break

    health_correlations = []
    HEALTH_SOURCES = [
        ("whoop", "recovery_score", "Recovery"), ("whoop", "hrv", "HRV"),
        ("eightsleep", "sleep_score", "Sleep Score"), ("garmin", "avg_stress", "Stress"),
        ("garmin", "body_battery_high", "Body Battery"),
    ]
    health_data = {}
    for src, _, _ in HEALTH_SOURCES:
        if src not in health_data:
            try:
                health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
            except Exception:
                health_data[src] = {}

    for src, field, label in HEALTH_SOURCES:
        xs, ys = [], []
        for d in sorted_dates:
            sq = daily_social[d]["score"]
            hv = _sf(health_data.get(src, {}).get(d, {}).get(field))
            if hv is not None:
                xs.append(sq)
                ys.append(hv)
        if len(xs) >= 10:
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / n
            sx = (sum((x-mx)**2 for x in xs) / n) ** 0.5
            sy = (sum((y-my)**2 for y in ys) / n) ** 0.5
            r = round(cov / (sx * sy), 3) if sx > 0 and sy > 0 else 0
            health_correlations.append({"metric": label, "r": r, "n": n,
                                        "interpretation": "strong" if abs(r) > 0.5 else "moderate" if abs(r) > 0.3 else "weak"})

    journal_correlations = []
    for field_data, label in [(daily_mood, "Mood"), (daily_energy, "Energy"), (daily_stress, "Stress")]:
        xs, ys = [], []
        for d in sorted_dates:
            if d in field_data:
                xs.append(daily_social[d]["score"])
                ys.append(field_data[d])
        if len(xs) >= 10:
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / n
            sx = (sum((x-mx)**2 for x in xs) / n) ** 0.5
            sy = (sum((y-my)**2 for y in ys) / n) ** 0.5
            r = round(cov / (sx * sy), 3) if sx > 0 and sy > 0 else 0
            journal_correlations.append({"metric": label, "r": r, "n": n})

    meaningful_days = [d for d in sorted_dates if daily_social[d]["score"] >= 3]
    low_days = [d for d in sorted_dates if daily_social[d]["score"] <= 2]
    comparison = {}
    for src, field, label in HEALTH_SOURCES:
        m_vals = [_sf(health_data.get(src, {}).get(d, {}).get(field)) for d in meaningful_days]
        l_vals = [_sf(health_data.get(src, {}).get(d, {}).get(field)) for d in low_days]
        m_avg, l_avg = _avg(m_vals), _avg(l_vals)
        if m_avg is not None and l_avg is not None:
            comparison[label] = {"meaningful_avg": m_avg, "low_social_avg": l_avg, "diff": round(m_avg - l_avg, 2)}

    return {
        "start_date": start_date, "end_date": end_date,
        "total_days_with_data": len(daily_social), "distribution": distribution,
        "overall_avg_score": _avg(scores),
        "score_legend": {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4},
        "rolling_7d_latest": rolling_7d[-1] if rolling_7d else None,
        "rolling_30d_latest": rolling_30d[-1] if rolling_30d else None,
        "streaks": {"current_meaningful_streak": current_streak, "longest_meaningful_streak": longest_streak,
                    "days_since_meaningful": days_since_meaningful},
        "health_correlations": health_correlations, "journal_correlations": journal_correlations,
        "meaningful_vs_low_comparison": comparison,
        "perma_context": "Seligman PERMA: Relationships are #1 wellbeing predictor. Holt-Lunstad: isolation increases mortality 26%. Target: meaningful+ connection 5+ days/week.",
    }


def tool_get_social_isolation_risk(args):
    """Flags periods of social isolation and correlates with health declines."""
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    isolation_threshold = int(args.get("consecutive_days", 3))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    QUALITY_MAP = {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4}

    journal_items = query_source("notion", start_date, end_date)
    if not journal_items:
        return {"error": "No journal data.", "start_date": start_date, "end_date": end_date}

    daily_social = {}
    for item in journal_items:
        d = item.get("date")
        sq = item.get("enriched_social_quality")
        if d and sq and sq in QUALITY_MAP:
            score = QUALITY_MAP[sq]
            if d not in daily_social or score > daily_social[d]:
                daily_social[d] = score

    if not daily_social:
        return {"error": "No enriched social quality data.", "entries_checked": len(journal_items)}

    sorted_dates = sorted(daily_social.keys())
    episodes = []
    current_episode = []
    for d in sorted_dates:
        if daily_social[d] < 3:
            current_episode.append(d)
        else:
            if len(current_episode) >= isolation_threshold:
                episodes.append({"start": current_episode[0], "end": current_episode[-1], "duration_days": len(current_episode)})
            current_episode = []
    if len(current_episode) >= isolation_threshold:
        episodes.append({"start": current_episode[0], "end": current_episode[-1], "duration_days": len(current_episode)})

    current_isolation_days = 0
    for d in reversed(sorted_dates):
        if daily_social[d] < 3:
            current_isolation_days += 1
        else:
            break
    currently_isolated = current_isolation_days >= isolation_threshold

    episode_health_impact = []
    health_data = {}
    for src in ["whoop", "eightsleep", "garmin"]:
        try:
            health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
        except Exception:
            health_data[src] = {}

    for ep in episodes:
        ep_start = datetime.strptime(ep["start"], "%Y-%m-%d")
        pre_start = (ep_start - timedelta(days=7)).strftime("%Y-%m-%d")
        pre_end = (ep_start - timedelta(days=1)).strftime("%Y-%m-%d")
        impact = {"episode": ep, "health_deltas": {}}
        for src, field, label in [("whoop","recovery_score","Recovery"),("whoop","hrv","HRV"),("eightsleep","sleep_score","Sleep"),("garmin","avg_stress","Stress")]:
            pre_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in health_data.get(src,{}) if pre_start <= d <= pre_end]
            ep_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in health_data.get(src,{}) if ep["start"] <= d <= ep["end"]]
            pa, ea = _avg(pre_vals), _avg(ep_vals)
            if pa is not None and ea is not None:
                impact["health_deltas"][label] = {"before": pa, "during": ea, "change": round(ea - pa, 2)}
        if impact["health_deltas"]:
            episode_health_impact.append(impact)

    total_days = len(sorted_dates)
    isolated_days = sum(1 for d in sorted_dates if daily_social[d] < 3)
    isolation_pct = round(100 * isolated_days / total_days, 1) if total_days else 0
    risk_level = "high" if (isolation_pct > 60 or currently_isolated) else "moderate" if (isolation_pct > 40 or len(episodes) >= 3) else "low"

    coaching = []
    if currently_isolated:
        coaching.append(f"Low-social period: {current_isolation_days} days. Reach out to one person today.")
    if risk_level != "low":
        coaching.append("Huberman: Social connection activates oxytocin, directly reducing cortisol. Schedule recurring social commitments.")
    if isolation_pct > 50:
        coaching.append("Attia: Loneliness is as harmful to longevity as obesity and smoking.")

    return {
        "start_date": start_date, "end_date": end_date, "risk_level": risk_level,
        "isolation_episodes": episodes, "total_episodes": len(episodes),
        "currently_isolated": currently_isolated, "current_isolation_days": current_isolation_days if currently_isolated else 0,
        "isolation_pct": isolation_pct, "episode_health_impact": episode_health_impact, "coaching": coaching,
    }


# ── Feature #25: Meditation & Breathwork Correlation ───────────────────────────

def tool_get_meditation_correlation(args):
    """Correlates mindful_minutes from Apple Health with health metrics."""
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    ah_items = query_source("apple_health", start_date, end_date)
    ah_by_date = {item.get("date"): item for item in (ah_items or []) if item.get("date")}

    daily_minutes = {}
    for d, item in ah_by_date.items():
        mm = _sf(item.get("mindful_minutes"))
        if mm is not None and mm > 0:
            daily_minutes[d] = mm

    if not daily_minutes:
        return {"error": "No mindful_minutes data found.", "start_date": start_date, "end_date": end_date,
                "tip": "Enable 'Mindful Minutes' in Health Auto Export iOS app.",
                "apps": "Apple Mindfulness, Headspace, Calm, Insight Timer, Ten Percent Happier"}

    all_dates = sorted(ah_by_date.keys())
    practice_dates = sorted(daily_minutes.keys())
    total_days = len(all_dates)
    practice_days = len(practice_dates)
    adherence_pct = round(100 * practice_days / total_days, 1) if total_days else 0

    current_streak = 0
    longest_streak = 0
    temp_streak = 0
    for d in all_dates:
        if d in daily_minutes:
            temp_streak += 1
            longest_streak = max(longest_streak, temp_streak)
        else:
            temp_streak = 0
    for d in reversed(all_dates):
        if d in daily_minutes:
            current_streak += 1
        else:
            break

    health_data = {}
    for src in ["whoop", "eightsleep", "garmin"]:
        try:
            health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
        except Exception:
            health_data[src] = {}

    non_practice_dates = [d for d in all_dates if d not in daily_minutes]
    COMPARE_METRICS = [
        ("whoop","recovery_score","Recovery","higher_is_better"),("whoop","hrv","HRV","higher_is_better"),
        ("whoop","resting_heart_rate","Resting HR","lower_is_better"),("eightsleep","sleep_score","Sleep Score","higher_is_better"),
        ("eightsleep","sleep_efficiency","Sleep Efficiency","higher_is_better"),("garmin","avg_stress","Stress","lower_is_better"),
        ("garmin","body_battery_high","Body Battery","higher_is_better"),
    ]

    comparison = []
    for src, field, label, direction in COMPARE_METRICS:
        p_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in practice_dates]
        n_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in non_practice_dates]
        p_avg, n_avg = _avg(p_vals), _avg(n_vals)
        if p_avg is not None and n_avg is not None:
            diff = round(p_avg - n_avg, 2)
            favorable = (diff > 0 and direction == "higher_is_better") or (diff < 0 and direction == "lower_is_better")
            comparison.append({"metric": label, "meditation_days": p_avg, "no_meditation_days": n_avg,
                               "diff": diff, "favorable": favorable,
                               "n_meditation": len([v for v in p_vals if v is not None]),
                               "n_control": len([v for v in n_vals if v is not None])})

    dose_response = {}
    for low, high, label in [(0,5,"0-5 min"),(5,10,"5-10 min"),(10,20,"10-20 min"),(20,999,"20+ min")]:
        bucket_dates = [d for d, m in daily_minutes.items() if low <= m < high]
        if not bucket_dates:
            continue
        bm = {}
        for src, field, ml, _ in COMPARE_METRICS:
            vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in bucket_dates]
            a = _avg(vals)
            if a is not None:
                bm[ml] = a
        dose_response[label] = {"days": len(bucket_dates), "avg_minutes": _avg([daily_minutes[d] for d in bucket_dates]), "health_metrics": bm}

    correlations = []
    for src, field, label, _ in COMPARE_METRICS:
        xs, ys = [], []
        for d in practice_dates:
            hv = _sf(health_data.get(src,{}).get(d,{}).get(field))
            if hv is not None:
                xs.append(daily_minutes[d])
                ys.append(hv)
        if len(xs) >= 10:
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / n
            sx, sy = (sum((x-mx)**2 for x in xs)/n)**0.5, (sum((y-my)**2 for y in ys)/n)**0.5
            r = round(cov/(sx*sy), 3) if sx > 0 and sy > 0 else 0
            correlations.append({"metric": label, "r": r, "n": n})

    next_day = []
    for src, field, label, direction in COMPARE_METRICS[:4]:
        p_next, n_next = [], []
        for d in all_dates:
            nd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            hv = _sf(health_data.get(src,{}).get(nd,{}).get(field))
            if hv is not None:
                (p_next if d in daily_minutes else n_next).append(hv)
        pa, na = _avg(p_next), _avg(n_next)
        if pa is not None and na is not None:
            next_day.append({"metric": f"Next-day {label}", "after_meditation": pa, "after_no_meditation": na, "diff": round(pa-na, 2)})

    return {
        "start_date": start_date, "end_date": end_date,
        "summary": {"total_practice_days": practice_days, "total_days_in_range": total_days,
                     "adherence_pct": adherence_pct, "avg_minutes_per_session": _avg(list(daily_minutes.values())),
                     "total_minutes": round(sum(daily_minutes.values()), 1)},
        "streaks": {"current_streak": current_streak, "longest_streak": longest_streak},
        "meditation_vs_no_meditation": comparison, "dose_response": dose_response,
        "correlations": correlations, "next_day_effects": next_day,
        "coaching": {
            "huberman": "NSDR and physiological sigh are highest-ROI protocols. 5 min/day improves prefrontal cortex function within 8 weeks.",
            "attia": "Dose-response is logarithmic. Consistency > duration. Diminishing returns above ~20 min/day.",
            "walker": "Pre-sleep meditation (10-20 min) reduces sleep onset latency by ~50%.",
            "target": "Minimum effective dose: 5-13 min/day. Optimal: 10-20 min. 5+ days/week for HRV adaptation.",
        },
    }


# ── Travel & Jet Lag Detection (v2.40.0) ─────────────────────────────────────

# Common timezone offsets from UTC (standard time; DST adds +1 for most)
_TZ_OFFSETS = {
    "America/Los_Angeles": -8, "America/Denver": -7, "America/Chicago": -6,
    "America/New_York": -5, "America/Anchorage": -9, "Pacific/Honolulu": -10,
    "Europe/London": 0, "Europe/Paris": 1, "Europe/Berlin": 1, "Europe/Rome": 1,
    "Europe/Madrid": 1, "Europe/Amsterdam": 1, "Europe/Zurich": 1,
    "Asia/Tokyo": 9, "Asia/Shanghai": 8, "Asia/Hong_Kong": 8, "Asia/Singapore": 8,
    "Asia/Seoul": 9, "Asia/Bangkok": 7, "Asia/Dubai": 4, "Asia/Kolkata": 5.5,
    "Australia/Sydney": 10, "Australia/Melbourne": 10, "Australia/Perth": 8,
    "Pacific/Auckland": 12, "America/Sao_Paulo": -3, "America/Mexico_City": -6,
    "America/Toronto": -5, "America/Vancouver": -8, "Africa/Cairo": 2,
    "America/Lima": -5, "America/Bogota": -5, "America/Buenos_Aires": -3,
}
HOME_TZ = "America/Los_Angeles"
HOME_OFFSET = _TZ_OFFSETS[HOME_TZ]


def _tz_offset(tz_name):
    """Get UTC offset for a timezone name. Returns None if unknown."""
    return _TZ_OFFSETS.get(tz_name)


def _is_traveling(date_str=None):
    """Check if a given date (or today) falls within an active trip. Returns trip dict or None."""
    check_date = date_str or datetime.utcnow().strftime("%Y-%m-%d")
    try:
        resp = get_table().query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": TRAVEL_PK, ":prefix": "TRIP#"},
        )
        for item in resp.get("Items", []):
            item = _d2f(item)
            start = item.get("start_date", "")
            end = item.get("end_date") or "9999-12-31"
            if start <= check_date <= end:
                return item
        return None
    except Exception:
        return None


def tool_log_travel(args):
    """
    Log a trip (start or end). Creates a new trip record or closes an active one.
    action: 'start' (default) or 'end'
    """
    action = args.get("action", "start").lower()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tbl = get_table()

    if action == "end":
        # Find the active trip and close it
        trip_id = args.get("trip_id", "")
        end_date = args.get("end_date", today)
        if trip_id:
            # Direct close by trip_id
            try:
                tbl.update_item(
                    Key={"pk": TRAVEL_PK, "sk": trip_id},
                    UpdateExpression="SET end_date = :ed, #st = :st, updated_at = :ua",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={
                        ":ed": end_date, ":st": "completed",
                        ":ua": datetime.utcnow().isoformat(),
                    },
                )
                return {"status": "trip_ended", "trip_id": trip_id, "end_date": end_date}
            except Exception as e:
                return {"error": f"Failed to end trip: {e}"}
        else:
            # Find the most recent active trip
            active = _is_traveling(today)
            if not active:
                return {"error": "No active trip found. Specify trip_id or start a new trip."}
            sk = f"TRIP#{active.get('slug', '')}_{active.get('start_date', '')}"
            try:
                tbl.update_item(
                    Key={"pk": TRAVEL_PK, "sk": sk},
                    UpdateExpression="SET end_date = :ed, #st = :st, updated_at = :ua",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={
                        ":ed": end_date, ":st": "completed",
                        ":ua": datetime.utcnow().isoformat(),
                    },
                )
                return {"status": "trip_ended", "trip_id": sk, "end_date": end_date,
                        "destination": active.get("destination_city")}
            except Exception as e:
                return {"error": f"Failed to end trip: {e}"}

    # ── Start a new trip ──
    dest_city = args.get("destination_city", "").strip()
    dest_country = args.get("destination_country", "").strip()
    dest_tz = args.get("destination_timezone", "").strip()
    start_date = args.get("start_date", today)
    purpose = args.get("purpose", "personal")  # personal, work, family, vacation
    notes = args.get("notes", "")

    if not dest_city:
        return {"error": "destination_city is required."}

    # Compute timezone offset
    dest_offset = _tz_offset(dest_tz) if dest_tz else None
    tz_diff = None
    direction = None
    if dest_offset is not None:
        tz_diff = dest_offset - HOME_OFFSET
        direction = "eastbound" if tz_diff > 0 else ("westbound" if tz_diff < 0 else "same_zone")

    # Generate slug
    slug = re.sub(r"[^a-z0-9]+", "_", dest_city.lower()).strip("_")
    sk = f"TRIP#{slug}_{start_date}"

    item = {
        "pk": TRAVEL_PK,
        "sk": sk,
        "slug": slug,
        "destination_city": dest_city,
        "destination_country": dest_country,
        "destination_timezone": dest_tz,
        "home_timezone": HOME_TZ,
        "tz_offset_hours": Decimal(str(tz_diff)) if tz_diff is not None else None,
        "direction": direction,
        "start_date": start_date,
        "end_date": None,
        "purpose": purpose,
        "status": "active",
        "notes": notes,
        "source": "travel",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    item = {k: v for k, v in item.items() if v is not None and v != ""}

    try:
        tbl.put_item(Item=item)
    except Exception as e:
        return {"error": f"Failed to log trip: {e}"}

    result = {
        "status": "trip_started", "trip_id": sk, "destination": dest_city,
        "start_date": start_date,
    }
    if tz_diff is not None:
        result["tz_offset_hours"] = float(tz_diff)
        result["direction"] = direction
        abs_diff = abs(tz_diff)
        # Huberman: ~1 day recovery per timezone crossed, eastbound harder
        est_recovery = round(abs_diff * (1.5 if direction == "eastbound" else 1.0))
        result["estimated_recovery_days"] = est_recovery
        result["jet_lag_protocol"] = {
            "huberman_rule": f"~1 day per TZ crossed ({abs_diff} zones = ~{est_recovery} days). Eastbound is harder.",
            "light_exposure": "Get bright light at destination morning time. Avoid evening light first 2-3 days.",
            "meal_timing": "Eat meals on destination schedule immediately. Fasting on travel day may help.",
            "melatonin": f"If eastbound, low-dose melatonin (0.5-1mg) at destination bedtime for first {min(est_recovery, 5)} nights.",
            "exercise": "Light exercise (walk, Zone 2) at destination morning to anchor circadian rhythm.",
        }
    return result


def tool_get_travel_log(args):
    """List all trips with optional status filter."""
    status_filter = (args.get("status") or "").lower()

    try:
        resp = get_table().query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": TRAVEL_PK, ":prefix": "TRIP#"},
        )
    except Exception as e:
        return {"error": f"Failed to query travel log: {e}"}

    trips = [_d2f(item) for item in resp.get("Items", [])]
    if status_filter:
        trips = [t for t in trips if t.get("status") == status_filter]

    trips.sort(key=lambda t: t.get("start_date", ""), reverse=True)

    # Check for currently active
    active = [t for t in trips if t.get("status") == "active"]

    summary = []
    for t in trips:
        entry = {
            "trip_id": t.get("sk"),
            "destination": f"{t.get('destination_city', '')}, {t.get('destination_country', '')}".strip(", "),
            "dates": f"{t.get('start_date', '?')} → {t.get('end_date', 'ongoing')}",
            "status": t.get("status"),
            "tz_offset_hours": t.get("tz_offset_hours"),
            "direction": t.get("direction"),
            "purpose": t.get("purpose"),
        }
        if t.get("end_date") and t.get("start_date"):
            try:
                d1 = datetime.strptime(t["start_date"], "%Y-%m-%d")
                d2 = datetime.strptime(t["end_date"], "%Y-%m-%d")
                entry["duration_days"] = (d2 - d1).days + 1
            except ValueError:
                pass
        summary.append(entry)

    return {
        "total_trips": len(trips),
        "currently_traveling": bool(active),
        "active_trip": {
            "destination": active[0].get("destination_city"),
            "since": active[0].get("start_date"),
            "tz_offset": active[0].get("tz_offset_hours"),
        } if active else None,
        "trips": summary,
    }


def tool_get_jet_lag_recovery(args):
    """
    Post-trip recovery analysis. Compares pre-trip baseline metrics to
    post-return recovery curve. Shows days-to-baseline for key metrics.
    """
    trip_id = args.get("trip_id", "")
    recovery_window_days = int(args.get("recovery_window_days", 14))

    # Find the trip
    if trip_id:
        try:
            resp = get_table().get_item(Key={"pk": TRAVEL_PK, "sk": trip_id})
            trip = _d2f(resp.get("Item") or {})
        except Exception:
            trip = {}
    else:
        # Find most recent completed trip
        try:
            resp = get_table().query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={":pk": TRAVEL_PK, ":prefix": "TRIP#"},
            )
            trips = [_d2f(i) for i in resp.get("Items", [])]
            completed = [t for t in trips if t.get("status") == "completed"]
            completed.sort(key=lambda t: t.get("end_date", ""), reverse=True)
            trip = completed[0] if completed else {}
        except Exception:
            trip = {}

    if not trip or not trip.get("end_date"):
        return {"error": "No completed trip found. End an active trip first with log_travel action='end'."}

    start_date = trip.get("start_date", "")
    end_date = trip.get("end_date", "")
    tz_diff = trip.get("tz_offset_hours", 0)

    # Pre-trip baseline: 7 days before departure
    pre_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    pre_end = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    # Post-return recovery window
    post_start = end_date
    post_end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=recovery_window_days)).strftime("%Y-%m-%d")

    # Metrics to track recovery
    recovery_metrics = [
        ("whoop", "recovery_score", "Recovery Score", True),
        ("whoop", "hrv", "HRV", True),
        ("whoop", "resting_heart_rate", "Resting HR", False),
        ("eightsleep", "sleep_score", "Sleep Score", True),
        ("eightsleep", "sleep_efficiency", "Sleep Efficiency", True),
        ("garmin", "body_battery_high", "Body Battery", True),
        ("garmin", "avg_stress", "Stress", False),
        ("apple_health", "steps", "Steps", True),
    ]

    results = {}
    for source, field, label, higher_is_better in recovery_metrics:
        # Pre-trip baseline
        pre_items = query_source(source, pre_start, pre_end)
        pre_vals = [float(i[field]) for i in pre_items if i.get(field) is not None]
        if not pre_vals:
            continue
        baseline = sum(pre_vals) / len(pre_vals)

        # Post-return daily values
        post_items = query_source(source, post_start, post_end)
        daily = []
        days_to_baseline = None
        for item in sorted(post_items, key=lambda x: x.get("date", "")):
            val = item.get(field)
            if val is None:
                continue
            val = float(val)
            day_num = (datetime.strptime(item.get("date", post_start), "%Y-%m-%d") -
                       datetime.strptime(end_date, "%Y-%m-%d")).days
            daily.append({"day": day_num, "value": round(val, 1)})

            # Check if recovered to baseline
            if days_to_baseline is None:
                if higher_is_better and val >= baseline * 0.95:
                    days_to_baseline = day_num
                elif not higher_is_better and val <= baseline * 1.05:
                    days_to_baseline = day_num

        if daily:
            post_avg = sum(d["value"] for d in daily) / len(daily)
            pct_change = round((post_avg - baseline) / baseline * 100, 1) if baseline else 0
            results[label] = {
                "pre_trip_baseline": round(baseline, 1),
                "post_return_avg": round(post_avg, 1),
                "pct_change": pct_change,
                "days_to_baseline": days_to_baseline,
                "recovered": days_to_baseline is not None,
                "daily_recovery_curve": daily[:recovery_window_days],
            }

    # Summary
    recovered_metrics = [k for k, v in results.items() if v.get("recovered")]
    not_recovered = [k for k, v in results.items() if not v.get("recovered")]
    avg_recovery_days = None
    recovery_days_list = [v["days_to_baseline"] for v in results.values() if v.get("days_to_baseline") is not None]
    if recovery_days_list:
        avg_recovery_days = round(sum(recovery_days_list) / len(recovery_days_list), 1)

    return {
        "trip": {
            "destination": trip.get("destination_city"),
            "dates": f"{start_date} → {end_date}",
            "tz_offset_hours": tz_diff,
            "direction": trip.get("direction"),
        },
        "analysis_window": {"pre_trip": f"{pre_start} → {pre_end}", "post_return": f"{post_start} → {post_end}"},
        "metrics": results,
        "summary": {
            "metrics_tracked": len(results),
            "recovered": len(recovered_metrics),
            "not_yet_recovered": len(not_recovered),
            "avg_days_to_baseline": avg_recovery_days,
            "recovered_metrics": recovered_metrics,
            "still_recovering": not_recovered,
        },
        "coaching": {
            "huberman": f"Jet lag recovery: ~1 day per timezone crossed ({abs(tz_diff or 0)} zones). "
                        f"{'Eastbound travel is harder — your body prefers to delay, not advance.' if (tz_diff or 0) > 0 else 'Westbound is easier — staying up later is natural.'}",
            "attia": "Monitor HRV as the primary recovery signal. Training intensity should match recovery — keep it Zone 2 until HRV returns to baseline.",
            "walker": "Avoid sleeping pills; they suppress REM. Melatonin (0.5-1mg) at destination bedtime for the first few nights only.",
        },
    }


# ── Helper: load BP readings from S3 ───────────────────────────────────────────

def _load_bp_readings(date_str):
    """Load individual BP readings from S3 for a given date.
    Returns list of dicts with time, systolic, diastolic, pulse."""
    try:
        y, m, d = date_str.split("-")
        key = f"raw/blood_pressure/{y}/{m}/{d}.json"
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        return []
    except Exception as e:
        logger.warning(f"BP read failed for {date_str}: {e}")
        return []


# ── Tool: get_blood_pressure_dashboard ────────────────────────────────────────

def tool_get_state_of_mind_trend(args):
    """State of Mind valence trend from How We Feel / Apple Health."""
    today = datetime.now().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)

    # ── Load daily aggregates from DynamoDB ──
    days_data = []
    current = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while current <= end_dt:
        ds = current.strftime("%Y-%m-%d")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + "apple_health", "sk": f"DATE#{ds}"})
            item = resp.get("Item", {})
            valence = item.get("som_avg_valence")
            if valence is not None:
                days_data.append({
                    "date": ds,
                    "avg_valence": float(valence),
                    "min_valence": float(item.get("som_min_valence", valence)),
                    "max_valence": float(item.get("som_max_valence", valence)),
                    "check_in_count": int(item.get("som_check_in_count", 0)),
                    "mood_count": int(item.get("som_mood_count", 0)),
                    "emotion_count": int(item.get("som_emotion_count", 0)),
                    "top_labels": item.get("som_top_labels", ""),
                    "top_associations": item.get("som_top_associations", ""),
                })
        except Exception:
            pass
        current += timedelta(days=1)

    if not days_data:
        return {
            "status": "no_data",
            "message": (
                "No State of Mind data found. To start collecting:\n"
                "1. Use How We Feel (or Apple Health State of Mind) to log moods\n"
                "2. In Health Auto Export app, create a NEW REST API automation:\n"
                "   - Data Type: 'State of Mind' (not Health Metrics)\n"
                "   - URL: same Lambda Function URL as your existing automation\n"
                "   - Headers: same Authorization Bearer token\n"
                "   - Export Format: JSON, Version 2\n"
                "   - Date Range: 'Since Last Sync'\n"
                "3. Check-ins will flow: How We Feel → HealthKit → HAE → Lambda → DynamoDB + S3"
            ),
            "period": {"start": start, "end": end},
        }

    # ── Load individual entries from S3 for label/association deep analysis ──
    all_labels = []
    all_associations = []
    all_entries = []
    for d in days_data:
        ds = d["date"]
        try:
            y, m, day = ds.split("-")
            key = f"raw/state_of_mind/{y}/{m}/{day}.json"
            resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            entries = json.loads(resp["Body"].read())
            for e in entries:
                all_entries.append(e)
                all_labels.extend(e.get("labels", []))
                all_associations.extend(e.get("associations", []))
        except Exception:
            pass

    # ── Valence statistics ──
    valences = [d["avg_valence"] for d in days_data]
    overall_avg = sum(valences) / len(valences)
    total_check_ins = sum(d["check_in_count"] for d in days_data)

    # 7-day rolling average for recent trend
    recent_7 = [d for d in days_data if d["date"] >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
    recent_avg = sum(d["avg_valence"] for d in recent_7) / len(recent_7) if recent_7 else None

    # Trend direction (first half vs second half)
    mid = len(valences) // 2
    if mid > 0:
        first_half = sum(valences[:mid]) / mid
        second_half = sum(valences[mid:]) / len(valences[mid:])
        delta = second_half - first_half
        if delta > 0.1:
            trend_direction = "improving"
        elif delta < -0.1:
            trend_direction = "declining"
        else:
            trend_direction = "stable"
    else:
        trend_direction = "insufficient_data"
        delta = 0

    # ── Label frequency analysis ──
    from collections import Counter
    label_freq = Counter(all_labels).most_common(10)
    assoc_freq = Counter(all_associations).most_common(10)

    # ── Valence by association (which life areas drive best/worst mood) ──
    assoc_valences = {}
    for e in all_entries:
        v = e.get("valence")
        if v is None:
            continue
        for a in e.get("associations", []):
            if a not in assoc_valences:
                assoc_valences[a] = []
            assoc_valences[a].append(float(v))

    assoc_avg = {}
    for a, vals in assoc_valences.items():
        if len(vals) >= 2:
            assoc_avg[a] = {"avg_valence": round(sum(vals) / len(vals), 3), "count": len(vals)}
    assoc_sorted = sorted(assoc_avg.items(), key=lambda x: -x[1]["avg_valence"])

    # ── Valence classification distribution ──
    class_counts = Counter()
    for e in all_entries:
        vc = e.get("valence_classification", "unknown")
        class_counts[vc] += 1
    class_dist = dict(class_counts.most_common())

    # ── Time-of-day analysis ──
    time_buckets = {"morning": [], "afternoon": [], "evening": [], "night": []}
    for e in all_entries:
        t = e.get("time", "")
        v = e.get("valence")
        if not t or v is None:
            continue
        try:
            parts = str(t).split(" ")
            hour = int(parts[1].split(":")[0]) if len(parts) > 1 else None
            if hour is not None:
                if 5 <= hour < 12:
                    time_buckets["morning"].append(float(v))
                elif 12 <= hour < 17:
                    time_buckets["afternoon"].append(float(v))
                elif 17 <= hour < 21:
                    time_buckets["evening"].append(float(v))
                else:
                    time_buckets["night"].append(float(v))
        except (IndexError, ValueError):
            pass

    time_of_day = {}
    for bucket, vals in time_buckets.items():
        if vals:
            time_of_day[bucket] = {"avg_valence": round(sum(vals) / len(vals), 3), "count": len(vals)}

    # ── Valence interpretation ──
    def interpret_valence(v):
        if v >= 0.67:
            return "very pleasant"
        elif v >= 0.33:
            return "pleasant"
        elif v >= 0.05:
            return "slightly pleasant"
        elif v >= -0.05:
            return "neutral"
        elif v >= -0.33:
            return "slightly unpleasant"
        elif v >= -0.67:
            return "unpleasant"
        else:
            return "very unpleasant"

    # ── Best / worst days ──
    sorted_days = sorted(days_data, key=lambda d: d["avg_valence"])
    worst_3 = sorted_days[:3] if len(sorted_days) >= 3 else sorted_days
    best_3 = sorted_days[-3:][::-1] if len(sorted_days) >= 3 else sorted_days[::-1]

    return {
        "period": {"start": start, "end": end},
        "summary": {
            "days_with_data": len(days_data),
            "total_check_ins": total_check_ins,
            "avg_check_ins_per_day": round(total_check_ins / len(days_data), 1),
            "overall_avg_valence": round(overall_avg, 3),
            "overall_interpretation": interpret_valence(overall_avg),
            "recent_7day_avg": round(recent_avg, 3) if recent_avg is not None else None,
            "recent_interpretation": interpret_valence(recent_avg) if recent_avg is not None else None,
            "trend_direction": trend_direction,
            "trend_delta": round(delta, 3),
        },
        "valence_distribution": class_dist,
        "top_emotion_labels": [{"label": l, "count": c} for l, c in label_freq],
        "top_life_associations": [{"association": a, "count": c} for a, c in assoc_freq],
        "valence_by_association": [
            {"association": a, **v} for a, v in assoc_sorted
        ],
        "time_of_day_pattern": time_of_day,
        "best_days": [{"date": d["date"], "valence": d["avg_valence"], "labels": d["top_labels"]} for d in best_3],
        "worst_days": [{"date": d["date"], "valence": d["avg_valence"], "labels": d["top_labels"]} for d in worst_3],
        "daily_detail": [
            {
                "date": d["date"],
                "avg_valence": d["avg_valence"],
                "check_ins": d["check_in_count"],
                "labels": d["top_labels"],
                "associations": d["top_associations"],
            }
            for d in days_data[-30:]  # Last 30 days detail
        ],
    }


def tool_get_blood_pressure_dashboard(args):
    """
    Blood pressure dashboard. Current status, AHA classification, trend,
    morning vs evening patterns, variability analysis.

    AHA categories:
      Normal:    <120 / <80
      Elevated:  120-129 / <80
      Stage 1:   130-139 / 80-89
      Stage 2:   >=140 / >=90
      Crisis:    >180 / >120
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": "No Apple Health data for range.", "start_date": start_date, "end_date": end_date}

    # Collect days with BP data
    bp_days = []
    for item in items:
        sys_val = item.get("blood_pressure_systolic")
        dia_val = item.get("blood_pressure_diastolic")
        if sys_val is None or dia_val is None:
            continue
        bp_days.append({
            "date": item.get("date", ""),
            "systolic": float(sys_val),
            "diastolic": float(dia_val),
            "pulse": float(item["blood_pressure_pulse"]) if item.get("blood_pressure_pulse") is not None else None,
            "readings_count": int(item.get("blood_pressure_readings_count", 1)),
        })

    if not bp_days:
        return {
            "status": "no_data",
            "message": "No blood pressure readings found in the date range. Ensure BP cuff syncs to Apple Health.",
            "start_date": start_date, "end_date": end_date,
        }

    bp_days.sort(key=lambda x: x["date"])

    # AHA classification
    def classify_bp(sys, dia):
        if sys > 180 or dia > 120:
            return "crisis"
        if sys >= 140 or dia >= 90:
            return "stage_2_hypertension"
        if 130 <= sys <= 139 or 80 <= dia <= 89:
            return "stage_1_hypertension"
        if 120 <= sys <= 129 and dia < 80:
            return "elevated"
        return "normal"

    # Current (latest reading)
    latest = bp_days[-1]
    latest_class = classify_bp(latest["systolic"], latest["diastolic"])

    # Averages
    sys_vals = [d["systolic"] for d in bp_days]
    dia_vals = [d["diastolic"] for d in bp_days]
    pulse_vals = [d["pulse"] for d in bp_days if d["pulse"] is not None]
    avg_sys = round(sum(sys_vals) / len(sys_vals), 1)
    avg_dia = round(sum(dia_vals) / len(dia_vals), 1)
    avg_class = classify_bp(avg_sys, avg_dia)

    # Variability (SD)
    import math as _math
    sys_sd = round(_math.sqrt(sum((v - avg_sys)**2 for v in sys_vals) / len(sys_vals)), 1) if len(sys_vals) > 1 else 0
    dia_sd = round(_math.sqrt(sum((v - avg_dia)**2 for v in dia_vals) / len(dia_vals)), 1) if len(dia_vals) > 1 else 0

    # Trend (first half vs second half)
    mid = len(bp_days) // 2
    if mid > 0:
        first_half_sys = sum(d["systolic"] for d in bp_days[:mid]) / mid
        second_half_sys = sum(d["systolic"] for d in bp_days[mid:]) / len(bp_days[mid:])
        trend_sys = round(second_half_sys - first_half_sys, 1)
        trend_dir = "rising" if trend_sys > 2 else ("falling" if trend_sys < -2 else "stable")
    else:
        trend_sys = 0
        trend_dir = "insufficient_data"

    # Morning vs Evening analysis (from S3 individual readings)
    morning_sys, morning_dia = [], []
    evening_sys, evening_dia = [], []
    total_readings = 0
    for day in bp_days:
        readings = _load_bp_readings(day["date"])
        for r in readings:
            total_readings += 1
            time_str = r.get("time", "")
            try:
                hour = int(time_str.split(" ")[1].split(":")[0])
            except (IndexError, ValueError):
                continue
            s, d = r.get("systolic"), r.get("diastolic")
            if s is None or d is None:
                continue
            if 5 <= hour < 12:
                morning_sys.append(float(s))
                morning_dia.append(float(d))
            elif hour >= 18:
                evening_sys.append(float(s))
                evening_dia.append(float(d))

    time_of_day = None
    if morning_sys and evening_sys:
        time_of_day = {
            "morning_avg": {"systolic": round(sum(morning_sys)/len(morning_sys), 1),
                           "diastolic": round(sum(morning_dia)/len(morning_dia), 1),
                           "readings": len(morning_sys)},
            "evening_avg": {"systolic": round(sum(evening_sys)/len(evening_sys), 1),
                           "diastolic": round(sum(evening_dia)/len(evening_dia), 1),
                           "readings": len(evening_sys)},
            "note": "Morning BP is typically higher (cortisol awakening response). " +
                    ("Your pattern matches." if sum(morning_sys)/len(morning_sys) > sum(evening_sys)/len(evening_sys)
                     else "Your evening is higher than morning — consider stress/sodium timing."),
        }

    # Classification distribution
    class_dist = {}
    for d in bp_days:
        c = classify_bp(d["systolic"], d["diastolic"])
        class_dist[c] = class_dist.get(c, 0) + 1

    # Coaching
    coaching = {}
    if avg_sys >= 130 or avg_dia >= 85:
        coaching["attia"] = "Sustained BP above 130/85 accelerates arterial aging. Sodium restriction (<2000mg), regular Zone 2, and sleep optimization are first-line interventions."
    if sys_sd > 12:
        coaching["huberman"] = f"High systolic variability (SD={sys_sd}). Consider consistent measurement timing, limiting caffeine before readings, and 5 min seated rest pre-measurement."
    if avg_class == "normal":
        coaching["summary"] = "Blood pressure is well-controlled. Continue current lifestyle factors."
    else:
        coaching["summary"] = f"Average classification: {avg_class.replace('_', ' ').title()}. Track trends and discuss with your physician if sustained."

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_bp": len(bp_days), "total_readings": total_readings},
        "current": {
            "date": latest["date"],
            "systolic": latest["systolic"], "diastolic": latest["diastolic"],
            "pulse": latest.get("pulse"),
            "classification": latest_class,
        },
        "averages": {
            "systolic": avg_sys, "diastolic": avg_dia,
            "pulse": round(sum(pulse_vals)/len(pulse_vals), 1) if pulse_vals else None,
            "classification": avg_class,
        },
        "variability": {"systolic_sd": sys_sd, "diastolic_sd": dia_sd,
                        "note": "SD >12 mmHg systolic suggests high visit-to-visit variability (independent CV risk factor)"},
        "trend": {"systolic_delta": trend_sys, "direction": trend_dir},
        "time_of_day": time_of_day,
        "classification_distribution": class_dist,
        "daily_readings": [{"date": d["date"], "systolic": d["systolic"], "diastolic": d["diastolic"],
                            "pulse": d.get("pulse"), "class": classify_bp(d["systolic"], d["diastolic"])}
                           for d in bp_days],
        "coaching": coaching,
    }


# ── Tool: get_blood_pressure_correlation ──────────────────────────────────────

def tool_get_blood_pressure_correlation(args):
    """
    Correlate blood pressure with lifestyle factors: sodium, training load, stress,
    sleep quality, caffeine, weight. Pearson r + bucketed comparisons.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))

    ah_items = query_source("apple_health", start_date, end_date)
    mf_items = query_source("macrofactor",  start_date, end_date)
    es_items = query_source("eightsleep",   start_date, end_date)
    wh_items = query_source("whoop",        start_date, end_date)
    wi_items = query_source("withings",     start_date, end_date)
    ga_items = query_source("garmin",       start_date, end_date)
    st_items = query_source("strava",       start_date, end_date)

    # Build date-indexed lookups
    def by_date(items):
        out = {}
        for i in items:
            d = i.get("date")
            if d:
                out[d] = i
        return out

    bp_by_date = {}
    for item in ah_items:
        s = item.get("blood_pressure_systolic")
        d = item.get("blood_pressure_diastolic")
        if s is not None and d is not None:
            bp_by_date[item.get("date", "")] = {"systolic": float(s), "diastolic": float(d)}

    if len(bp_by_date) < 5:
        return {"error": f"Need at least 5 days with BP data, found {len(bp_by_date)}.",
                "start_date": start_date, "end_date": end_date}

    mf_map = by_date(mf_items)
    es_map = by_date(es_items)
    wh_map = by_date(wh_items)
    wi_map = by_date(wi_items)
    ga_map = by_date(ga_items)
    st_map = by_date(st_items)

    # Correlate BP with various factors
    correlations = []
    ah_map = by_date(ah_items)

    factor_pairs = [
        ("Sodium (mg)",        mf_map, "total_sodium_mg"),
        ("Calories",           mf_map, "total_calories_kcal"),
        ("Caffeine (mg)",      ah_map, "caffeine_mg"),
        ("Sleep Efficiency %", es_map, "sleep_efficiency"),
        ("Sleep Score",        es_map, "sleep_score"),
        ("Recovery Score",     wh_map, "recovery_score"),
        ("HRV",               wh_map, "hrv"),
        ("Garmin Stress",      ga_map, "avg_stress"),
        ("Weight (lbs)",       wi_map, "weight_lbs"),
        ("Steps",              ah_map, "steps"),
        ("Training Load",      st_map, "total_kilojoules"),
    ]

    for factor_name, source_map, field in factor_pairs:
        sys_xs, sys_ys, dia_xs, dia_ys = [], [], [], []
        for date, bp in bp_by_date.items():
            src = source_map.get(date, {})
            val = src.get(field)
            if val is not None:
                try:
                    v = float(val)
                    sys_xs.append(v)
                    sys_ys.append(bp["systolic"])
                    dia_xs.append(v)
                    dia_ys.append(bp["diastolic"])
                except (ValueError, TypeError):
                    pass

        if len(sys_xs) >= 5:
            r_sys = pearson_r(sys_xs, sys_ys)
            r_dia = pearson_r(dia_xs, dia_ys)
            correlations.append({
                "factor": factor_name,
                "n_days": len(sys_xs),
                "systolic_r": round(r_sys, 3) if r_sys is not None else None,
                "diastolic_r": round(r_dia, 3) if r_dia is not None else None,
                "strength": "strong" if r_sys is not None and abs(r_sys) >= 0.4 else
                           ("moderate" if r_sys is not None and abs(r_sys) >= 0.2 else "weak"),
            })

    # Sort by absolute systolic correlation strength
    correlations.sort(key=lambda c: abs(c.get("systolic_r") or 0), reverse=True)

    # Exercise day vs rest day comparison
    exercise_bp, rest_bp = [], []
    for date, bp in bp_by_date.items():
        st = st_map.get(date, {})
        if st.get("activity_count") and int(st["activity_count"]) > 0:
            exercise_bp.append(bp)
        else:
            rest_bp.append(bp)

    exercise_vs_rest = None
    if exercise_bp and rest_bp:
        exercise_vs_rest = {
            "exercise_days": {
                "n": len(exercise_bp),
                "avg_systolic": round(sum(b["systolic"] for b in exercise_bp) / len(exercise_bp), 1),
                "avg_diastolic": round(sum(b["diastolic"] for b in exercise_bp) / len(exercise_bp), 1),
            },
            "rest_days": {
                "n": len(rest_bp),
                "avg_systolic": round(sum(b["systolic"] for b in rest_bp) / len(rest_bp), 1),
                "avg_diastolic": round(sum(b["diastolic"] for b in rest_bp) / len(rest_bp), 1),
            },
        }

    # Sodium bucketing (if enough data)
    sodium_buckets = None
    sodium_bp = []
    for date, bp in bp_by_date.items():
        mf = mf_map.get(date, {})
        na = mf.get("total_sodium_mg")
        if na is not None:
            sodium_bp.append({"sodium": float(na), **bp})

    if len(sodium_bp) >= 10:
        sodium_bp.sort(key=lambda x: x["sodium"])
        low_cut = len(sodium_bp) // 3
        high_cut = 2 * len(sodium_bp) // 3
        low = sodium_bp[:low_cut]
        mid = sodium_bp[low_cut:high_cut]
        high = sodium_bp[high_cut:]
        sodium_buckets = {
            "low_sodium": {
                "range": f"<{int(low[-1]['sodium'])} mg" if low else "",
                "n": len(low),
                "avg_systolic": round(sum(x["systolic"] for x in low) / len(low), 1) if low else None,
                "avg_diastolic": round(sum(x["diastolic"] for x in low) / len(low), 1) if low else None,
            },
            "mid_sodium": {
                "range": f"{int(mid[0]['sodium'])}-{int(mid[-1]['sodium'])} mg" if mid else "",
                "n": len(mid),
                "avg_systolic": round(sum(x["systolic"] for x in mid) / len(mid), 1) if mid else None,
                "avg_diastolic": round(sum(x["diastolic"] for x in mid) / len(mid), 1) if mid else None,
            },
            "high_sodium": {
                "range": f">{int(high[0]['sodium'])} mg" if high else "",
                "n": len(high),
                "avg_systolic": round(sum(x["systolic"] for x in high) / len(high), 1) if high else None,
                "avg_diastolic": round(sum(x["diastolic"] for x in high) / len(high), 1) if high else None,
            },
        }

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_bp": len(bp_by_date)},
        "correlations": correlations,
        "exercise_vs_rest": exercise_vs_rest,
        "sodium_dose_response": sodium_buckets,
        "coaching": {
            "attia": "Sodium is the strongest modifiable BP lever. Track your personal dose-response — some people are salt-sensitive (RAAS genetics), others are not.",
            "huberman": "Consistent Zone 2 cardio (150 min/week) is the most evidence-backed BP intervention after sodium. Acute post-exercise hypotension lasts 12-24 hours.",
            "walker": "Poor sleep quality (especially <85% efficiency) reliably raises next-day BP by 5-10 mmHg via sympathetic overdrive.",
        },
    }


TOOLS = {
    "get_sources": {
        "fn": tool_get_sources,
        "schema": {
            "name": "get_sources",
            "description": "List all available data sources and their date ranges in the life platform.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_latest": {
        "fn": tool_get_latest,
        "schema": {
            "name": "get_latest",
            "description": "Get the most recent record(s) for one or more sources. Useful for current status checks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sources": {"type": "array", "items": {"type": "string"},
                                "description": f"List of sources to fetch. Defaults to all. Valid: {SOURCES}"}
                },
                "required": [],
            },
        },
    },
    "get_daily_summary": {
        "fn": tool_get_daily_summary,
        "schema": {
            "name": "get_daily_summary",
            "description": "Get all available data across every source for a single date. Best starting point for 'how was my day/yesterday?' questions.",
            "inputSchema": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "Date in YYYY-MM-DD format."}},
                "required": ["date"],
            },
        },
    },
    "get_date_range": {
        "fn": tool_get_date_range,
        "schema": {
            "name": "get_date_range",
            "description": f"Get time-series records for a single source. Returns raw daily data for windows up to {RAW_DAY_LIMIT} days, monthly aggregates beyond that. Use get_aggregated_summary for multi-year trends.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (inclusive)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (inclusive)."},
                },
                "required": ["source", "start_date", "end_date"],
            },
        },
    },
    "find_days": {
        "fn": tool_find_days,
        "schema": {
            "name": "find_days",
            "description": "Find days within a date range where numeric fields meet filter conditions. For Strava, use field names: 'total_distance_miles', 'total_elevation_gain_feet'. For Whoop: 'hrv', 'recovery_score', 'strain'. Great for correlations. IMPORTANT: This tool operates on day-level aggregates only — it cannot search inside individual activity names or sport types. For any query involving specific activity names, first/longest/highest achievements, named events, or sport-type filtering, you MUST use search_activities instead.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "filters": {
                        "type": "array",
                        "description": "List of field filter conditions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op":    {"type": "string", "enum": [">", ">=", "<", "<=", "="]},
                                "value": {"type": "number"},
                            },
                            "required": ["field", "op", "value"],
                        },
                    },
                },
                "required": ["source", "start_date", "end_date"],
            },
        },
    },
    "get_aggregated_summary": {
        "fn": tool_get_aggregated_summary,
        "schema": {
            "name": "get_aggregated_summary",
            "description": "Get monthly or yearly averages across any date range. Use this for long-horizon questions like 'summarize my health history' or 'how has my weight trended over the years'. Returns avg/min/max per period per source.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Optional. If omitted all sources included. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "period":     {"type": "string", "enum": ["month", "year"],
                                   "description": "Use 'year' for multi-year history, 'month' for 1-3 year windows."},
                },
                "required": [],
            },
        },
    },
    "get_field_stats": {
        "fn": tool_get_field_stats,
        "schema": {
            "name": "get_field_stats",
            "description": "Get rich stats for a numeric field: min/max/avg/count, dates of the all-time peak and trough, top-5 highest and top-5 lowest readings with dates, and a trend direction. Use this to find actual historical peaks rather than guessing AND to build a narrative arc. Examples: 'what was my heaviest weight ever?' (source=withings, field=weight_lbs), 'best HRV day' (source=whoop, field=hrv), 'lowest resting heart rate' (source=whoop, field=resting_heart_rate). Always prefer this over get_aggregated_summary when the user asks about a specific extreme value or record. For full narrative context, follow up with get_aggregated_summary (period=year) to show the trend between the peaks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "field":      {"type": "string", "description": "The numeric field name to analyze. E.g. 'weight_lbs', 'hrv', 'recovery_score', 'resting_heart_rate', 'total_distance_miles'."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01 (all-time)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["source", "field"],
            },
        },
    },
    "search_activities": {
        "fn": tool_search_activities,
        "schema": {
            "name": "search_activities",
            "description": "Search Strava activities by name keyword, sport type, minimum distance, or minimum elevation gain. ALWAYS use this tool (not find_days) for: named activities ('first century', 'mailbox peak', 'machu picchu'), achievement queries (longest run, biggest hike, first 100-mile ride), or sorting by distance/elevation to find top efforts. CRITICAL: Do NOT filter by sport_type when looking for longest/biggest/most impressive efforts — long walks and hikes count equally to runs and should be included. Only pass sport_type if the user explicitly asks for a specific type (e.g. 'my longest run' vs 'my longest activity'). Results include an all-time percentile rank and a context flag for exceptional values so you can narrate how remarkable the effort was.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":              {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date":                {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "name_contains":           {"type": "string", "description": "Keyword to search in activity name (case-insensitive). E.g. 'machu', 'half marathon', 'trail'."},
                    "sport_type":              {"type": "string", "description": "Filter by sport type (case-insensitive). Common values: 'Run', 'Walk', 'Hike', 'Ride', 'VirtualRide', 'WeightTraining'."},
                    "min_distance_miles":      {"type": "number", "description": "Only return activities with distance >= this value in miles."},
                    "min_elevation_gain_feet": {"type": "number", "description": "Only return activities with elevation gain >= this value in feet."},
                    "sort_by":                 {"type": "string", "description": "Field to sort results by descending. Options: 'distance_miles', 'total_elevation_gain_feet', 'moving_time_seconds', 'kilojoules'. Default: 'distance_miles'."},
                    "limit":                   {"type": "number", "description": "Max results to return. Default 100."},
                },
                "required": [],
            },
        },
    },
    "compare_periods": {
        "fn": tool_compare_periods,
        "schema": {
            "name": "compare_periods",
            "description": "Side-by-side comparison of two date ranges across one or all sources. Returns per-field averages for both periods plus delta and % change. Use for benchmarking questions: 'how does my fitness now compare to my 2022 peak?', 'was I more active this year vs last year?', 'did my HRV improve after I started running more?'. Label your periods meaningfully (e.g. 'Peak 2022', 'Current').",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period_a_start": {"type": "string", "description": "Start date of period A (YYYY-MM-DD)."},
                    "period_a_end":   {"type": "string", "description": "End date of period A (YYYY-MM-DD)."},
                    "period_b_start": {"type": "string", "description": "Start date of period B (YYYY-MM-DD)."},
                    "period_b_end":   {"type": "string", "description": "End date of period B (YYYY-MM-DD)."},
                    "period_a_label": {"type": "string", "description": "Human-readable label for period A. E.g. 'Peak 2022', 'Pre-injury', 'Last year'."},
                    "period_b_label": {"type": "string", "description": "Human-readable label for period B. E.g. 'Current', 'Post-injury', 'This year'."},
                    "source":         {"type": "string", "description": f"Optional. Limit to one source. Valid: {SOURCES}. Omit to compare all sources."},
                },
                "required": ["period_a_start", "period_a_end", "period_b_start", "period_b_end"],
            },
        },
    },
    "get_weekly_summary": {
        "fn": tool_get_weekly_summary,
        "schema": {
            "name": "get_weekly_summary",
            "description": "Group Strava activities into ISO calendar weeks and return per-week totals (distance, elevation, time, activity count, sport type breakdown). Use for training load questions: 'what was my biggest training week ever?', 'show my weekly mileage this year', 'what were my top 10 highest mileage weeks?'. Sort by distance (default), elevation, or time. Chronological order available via sort_ascending=true for trend analysis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":     {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2000-01-01 (all-time)."},
                    "end_date":       {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "sort_by":        {"type": "string", "description": "Field to sort weeks by. Options: 'total_distance_miles' (default), 'total_elevation_gain_feet', 'total_moving_time_seconds', 'activity_count'."},
                    "limit":          {"type": "number", "description": "Max weeks to return. Default 52."},
                    "sort_ascending": {"type": "boolean", "description": "Set true for chronological order (trend view). Default false (best weeks first)."},
                },
                "required": [],
            },
        },
    },
    "get_training_load": {
        "fn": tool_get_training_load,
        "schema": {
            "name": "get_training_load",
            "description": "Compute the Banister fitness-fatigue model: CTL (42-day fitness), ATL (7-day fatigue), TSB (form = CTL-ATL), and ACWR (injury risk ratio). Use for: 'how fit am I right now?', 'am I overtraining?', 'am I ready for a race?', 'when was my peak fitness?', 'what is my injury risk?'. ACWR > 1.3 = caution, > 1.5 = danger. TSB positive = fresh, negative = fatigued. Returns a full time series plus current state summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 6 months ago."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_personal_records": {
        "fn": tool_get_personal_records,
        "schema": {
            "name": "get_personal_records",
            "description": "All-time personal records (PRs) across every measurable dimension — the athlete's trophy case. Includes: longest activity, most elevation, biggest week, best HRV, lowest resting HR, best recovery score, heaviest/lightest weight, lowest body fat, and more. Each record includes the date it was set and age at the time (requires profile DOB). Use for: 'what are my all-time best performances?', 'when was I fittest?', 'what are my PRs?', 'have I ever run further than X miles?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date": {"type": "string", "description": "Only consider records up to this date. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_cross_source_correlation": {
        "fn": tool_get_cross_source_correlation,
        "schema": {
            "name": "get_cross_source_correlation",
            "description": "Pearson correlation between any two numeric metrics, with optional day lag. Surfaces statistical associations — note correlations do not imply causation. Examples: 'is HRV associated with next-day training output?' (source_a=whoop, field_a=hrv, source_b=strava, field_b=total_distance_miles, lag_days=1), 'does task count correlate with recovery score?' (source_a=todoist, field_a=tasks_completed, source_b=whoop, field_b=recovery_score), 'how does weight track with training volume?' (source_a=withings, field_a=weight_lbs, source_b=strava, field_b=total_distance_miles). r > 0.4 is practically meaningful for n=1 data; interpret patterns as hypotheses to test, not conclusions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_a":   {"type": "string", "description": f"First data source. Valid: {SOURCES}"},
                    "field_a":    {"type": "string", "description": "Field from source_a (e.g. 'hrv', 'recovery_score', 'weight_lbs')"},
                    "source_b":   {"type": "string", "description": f"Second data source. Valid: {SOURCES}"},
                    "field_b":    {"type": "string", "description": "Field from source_b (e.g. 'total_distance_miles', 'recovery_score')"},
                    "lag_days":   {"type": "number", "description": "Shift source_b forward N days. Use lag=1 to ask 'does A today predict B tomorrow?'. Default 0."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2019-01-01."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["source_a", "field_a", "source_b", "field_b"],
            },
        },
    },
    "get_seasonal_patterns": {
        "fn": tool_get_seasonal_patterns,
        "schema": {
            "name": "get_seasonal_patterns",
            "description": "Month-by-month averages aggregated across ALL years, revealing annual cycles. Use for: 'do I always gain weight in winter?', 'what month do I train most?', 'when is my HRV historically highest?', 'what are my seasonal training patterns?', 'when should I plan my peak event?'. Essential for periodisation and setting realistic seasonal targets. Each month shows how many years of data contribute.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Optional. Limit to one source. Valid: {SOURCES}. Omit for all sources."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_health_dashboard": {
        "fn": tool_get_health_dashboard,
        "schema": {
            "name": "get_health_dashboard",
            "description": "Current-state morning briefing in a single call. Returns: today's readiness (recovery score, HRV, RHR, sleep), training load status (CTL/ATL/TSB/ACWR), 7-day and 30-day training summaries, 30-day biomarker trends (HRV, RHR, weight), and automated alerts for anything outside healthy ranges. Use for: 'how am I doing?', 'morning check-in', 'give me a health briefing', 'am I overtrained?', 'should I train hard today?'",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_weight_loss_progress": {
        "fn": tool_get_weight_loss_progress,
        "schema": {
            "name": "get_weight_loss_progress",
            "description": "The core weight-loss coaching report. Returns: weekly rate of loss with fast/slow flags, full BMI series with clinical milestone flags (Obese III→II→I→Overweight→Normal), projected goal date at current pace, plateau detection (14+ days of minimal movement), and % complete toward goal. Use for: 'how is my weight loss going?', 'when will I reach my goal?', 'am I losing too fast?', 'am I in a plateau?', 'what BMI am I at?'. Requires journey_start_date, goal_weight_lbs in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Override start date YYYY-MM-DD. Defaults to journey_start_date from profile."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_body_composition_trend": {
        "fn": tool_get_body_composition_trend,
        "schema": {
            "name": "get_body_composition_trend",
            "description": "Tracks fat mass vs lean/muscle mass over time from Withings data — the question the scale alone cannot answer: are you losing fat or muscle? Returns fat mass, lean mass, body fat %, FFMI series, and flags significant lean mass loss events. Use for: 'am I losing fat or muscle?', 'how is my body composition changing?', 'am I protecting my lean mass?', 'what is my body fat percentage trend?'. Requires Withings body composition sync.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to journey_start_date from profile."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_energy_expenditure": {
        "fn": tool_get_energy_expenditure,
        "schema": {
            "name": "get_energy_expenditure",
            "description": "Estimates Total Daily Energy Expenditure (TDEE) = BMR + exercise calories. BMR computed via Mifflin-St Jeor (most validated for people with obesity). Exercise calories from Strava kilojoules or TRIMP estimate. Returns implied daily calorie target at a given deficit, and shows how BMR has changed since start weight (metabolic adaptation). Use for: 'how many calories should I eat?', 'what is my TDEE?', 'how much am I burning?', 'how has my metabolism changed as I lose weight?'. Requires height_inches, date_of_birth, biological_sex in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_deficit_kcal": {"type": "number", "description": "Daily calorie deficit target. Default 500 (≈1 lb/week). Use 750 for 1.5 lbs/week, 1000 for 2 lbs/week."},
                    "end_date":            {"type": "string",  "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_non_scale_victories": {
        "fn": tool_get_non_scale_victories,
        "schema": {
            "name": "get_non_scale_victories",
            "description": "Surfaces fitness and health improvements since journey start that are independent of the scale — critical for motivation during plateaus. Compares: resting HR, HRV, recovery score, sleep, activity count, monthly mileage, and moving speed between the first 30 days of the journey and the most recent 30 days. Use for: 'what non-scale victories have I had?', 'how has my fitness improved?', 'I am in a plateau — am I still making progress?', 'has my heart rate improved since I started?'. Requires journey_start_date in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_exercise_history": {
        "fn": tool_get_exercise_history,
        "schema": {
            "name": "get_exercise_history",
            "description": "Deep dive on a single exercise: all sessions, per-set detail, PR chronology, and estimated 1RM trend. Use for: 'show me all my bench press sessions', 'when did I hit a bench PR?', 'how has my squat progressed?'. Fuzzy matches exercise name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "exercise_name":   {"type": "string", "description": "Exercise name to search (case-insensitive, fuzzy match). E.g. 'bench press', 'squat', 'deadlift'."},
                    "start_date":      {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2000-01-01."},
                    "end_date":        {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "include_warmups": {"type": "boolean", "description": "Include warmup sets. Default false."},
                },
                "required": ["exercise_name"],
            },
        },
    },
    "get_strength_prs": {
        "fn": tool_get_strength_prs,
        "schema": {
            "name": "get_strength_prs",
            "description": "All-exercise PR leaderboard ranked by estimated 1RM (Epley formula). Shows best weight, best reps, and estimated 1-rep max for every exercise with sufficient data. Use for: 'what are my strength PRs?', 'what's my best bench press?', 'show me my top lifts by muscle group'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":           {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":             {"type": "string", "description": "End date YYYY-MM-DD."},
                    "muscle_group_filter":  {"type": "string", "description": "Optional filter by muscle group. E.g. 'chest', 'back', 'legs'."},
                    "min_sessions":         {"type": "number", "description": "Minimum sessions required for exercise to appear. Default 3."},
                },
                "required": [],
            },
        },
    },
    "get_muscle_volume": {
        "fn": tool_get_muscle_volume,
        "schema": {
            "name": "get_muscle_volume",
            "description": "Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks (Renaissance Periodization). Shows if training volume is below maintenance, optimal, or exceeding recovery capacity. Also analyses push/pull/legs balance. Use for: 'am I training enough chest?', 'what is my weekly volume?', 'am I overtraining?', 'is my push/pull ratio balanced?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "period":     {"type": "string", "description": "Aggregation period: 'week' (default) or 'month'."},
                },
                "required": [],
            },
        },
    },
    "get_strength_progress": {
        "fn": tool_get_strength_progress,
        "schema": {
            "name": "get_strength_progress",
            "description": "Longitudinal 1RM trend, rate of gain, and plateau detection for a single exercise. Splits history into thirds for periodization analysis. Use for: 'am I still getting stronger at bench?', 'how fast is my squat progressing?', 'am I in a plateau?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "exercise_name":          {"type": "string", "description": "Exercise name (fuzzy match)."},
                    "start_date":             {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":               {"type": "string", "description": "End date YYYY-MM-DD."},
                    "plateau_threshold_days": {"type": "number", "description": "Days without PR to flag plateau. Default 90."},
                },
                "required": ["exercise_name"],
            },
        },
    },
    "get_workout_frequency": {
        "fn": tool_get_workout_frequency,
        "schema": {
            "name": "get_workout_frequency",
            "description": "Adherence metrics: total workouts, avg per week/month, longest streak, longest gap, month-by-month breakdown, and top 15 most-trained exercises. Use for: 'how consistent am I?', 'what is my workout streak?', 'how many days per week do I train?', 'what exercises do I do most?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                },
                "required": [],
            },
        },
    },
    "get_strength_standards": {
        "fn": tool_get_strength_standards,
        "schema": {
            "name": "get_strength_standards",
            "description": "Bodyweight-relative strength vs Untrained/Novice/Intermediate/Advanced/Elite norms for bench press, squat, deadlift, and overhead press. Uses current bodyweight from Withings. Use for: 'how strong am I?', 'what level is my bench press?', 'how far am I from an advanced deadlift?', 'what are my strength standards?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date":           {"type": "string", "description": "Only use data up to this date. Defaults to today."},
                    "bodyweight_source":  {"type": "string", "description": "'withings' (default) or 'profile'."},
                    "bodyweight_lbs":     {"type": "number", "description": "Override bodyweight in lbs if no Withings data."},
                },
                "required": [],
            },
        },
    },
    "get_sleep_analysis": {
        "fn": tool_get_sleep_analysis,
        "schema": {
            "name": "get_sleep_analysis",
            "description": (
                "Clinical sleep analysis from Eight Sleep data. Goes beyond raw hours to surface the metrics a "
                "sleep physician uses: sleep architecture percentages (REM/deep/light as % of TST with clinical "
                "norms), sleep efficiency (sleep/TIB ×100, target ≥85%, CBT-I flag <80%), WASO (true "
                "wake-after-sleep-onset), circadian timing (avg onset/wake/midpoint in local time), sleep "
                "regularity (SD of onset and wake hours), social jetlag (weekday vs weekend midpoint delta, "
                "threshold 1h), sleep debt (rolling 7d and 30d vs target), and respiratory rate screening. "
                "All alerts reference evidence-based clinical thresholds. "
                "Use for: 'how is my sleep quality?', 'do I have enough REM?', 'is my sleep consistent?', "
                "'what is my sleep efficiency?', 'do I have social jetlag?', 'how much sleep debt do I have?', "
                "'is my respiratory rate normal?'. Requires Eight Sleep data in life-platform."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":          {"type": "string", "description": "Start date YYYY-MM-DD. Overrides 'days' if provided."},
                    "end_date":            {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "days":                {"type": "number", "description": "Rolling window in days from end_date (default: 90). Ignored if start_date provided."},
                    "target_sleep_hours":  {"type": "number", "description": "Nightly sleep target for debt calculation (default: 7.5h)."},
                },
                "required": [],
            },
        },
    },
    # ── MacroFactor longevity nutrition tools ─────────────────────────────────
    "get_micronutrient_report": {
        "fn": tool_get_micronutrient_report,
        "schema": {
            "name": "get_micronutrient_report",
            "description": (
                "Score ~25 micronutrients against RDA and longevity-optimal targets (Attia, Rhonda Patrick, "
                "Bryan Johnson Blueprint). Flags chronic deficiencies (avg < 60% RDA), near-miss gaps (60-90%), "
                "upper-limit exceedances, omega-6:omega-3 ratio, and Pacific Northwest vitamin D risk. "
                "Results grouped by category: Fatty Acids, Minerals, Vitamins, B Vitamins. "
                "Use for: 'am I micronutrient deficient?', 'is my omega-3 intake good?', 'what vitamins am I low in?', "
                "'is my vitamin D ok?', 'give me a nutrient sufficiency report'. Requires MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_meal_timing": {
        "fn": tool_get_meal_timing,
        "schema": {
            "name": "get_meal_timing",
            "description": (
                "Eating window analysis based on Satchin Panda / Salk Institute TRF research. "
                "Returns: first and last bite times, eating window duration, caloric distribution across "
                "morning/midday/evening/late, circadian consistency (SD of meal times), and gap between "
                "last bite and sleep onset (from Eight Sleep data). Flags TRF violations and late eating. "
                "Use for: 'what is my eating window?', 'am I eating too late?', 'is my meal timing circadian-aligned?', "
                "'how close to sleep am I eating?', 'do I practice time-restricted eating?'. Requires MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_nutrition_biometrics_correlation": {
        "fn": tool_get_nutrition_biometrics_correlation,
        "schema": {
            "name": "get_nutrition_biometrics_correlation",
            "description": (
                "Pearson correlations between 10 daily nutrition metrics and 9 biometric outcomes across "
                "Whoop, Withings, and Eight Sleep — with optional day lag to test next-day effects. "
                "Reveals YOUR personal diet-health relationships: does protein predict recovery? Does caffeine "
                "suppress sleep efficiency? Does calorie deficit lower HRV next day? "
                "Use for: 'does my diet affect my recovery?', 'does protein improve HRV?', "
                "'what nutrition patterns hurt my sleep?', 'does caffeine affect my sleep score?', "
                "'what does my diet predict about my performance?'. Requires ≥14 days of MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "lag_days":   {"type": "number", "description": "Shift biometrics forward N days. 1 = does today\'s nutrition predict tomorrow\'s outcomes? Default 1."},
                },
                "required": [],
            },
        },
    },
    # ── MacroFactor / Nutrition tools ─────────────────────────────────────────
    "get_nutrition_summary": {
        "fn": tool_get_nutrition_summary,
        "schema": {
            "name": "get_nutrition_summary",
            "description": (
                "Daily macro breakdown and rolling averages from MacroFactor. Returns per-day rows and period "
                "averages for calories, protein, carbs, fat, fiber, sodium, caffeine, omega-3, potassium, "
                "magnesium, and vitamin D. Also shows gap vs reference targets. "
                "Use for: 'how is my nutrition?', 'what are my average macros?', 'am I getting enough fiber?', "
                "'show me this week\\'s nutrition', 'how\\'s my omega-3 intake?'. Requires MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_macro_targets": {
        "fn": tool_get_macro_targets,
        "schema": {
            "name": "get_macro_targets",
            "description": (
                "Compare actual daily nutrition vs calorie and protein targets. Estimates TDEE from current "
                "Withings weight using Mifflin-St Jeor formula. Shows day-by-day adherence and hit rates. "
                "Calorie and protein targets can be overridden. "
                "Use for: 'am I hitting my protein goal?', 'how often am I in a deficit?', "
                "'am I eating enough?', 'show my calorie adherence this month'. Requires MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":      {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":        {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "days":            {"type": "number", "description": "Rolling window in days (default: 30). Ignored if start_date provided."},
                    "calorie_target":  {"type": "number", "description": "Override daily calorie target (kcal). Defaults to TDEE estimate."},
                    "protein_target":  {"type": "number", "description": "Override daily protein target (g). Default: 180g."},
                },
                "required": [],
            },
        },
    },
    "get_food_log": {
        "fn": tool_get_food_log,
        "schema": {
            "name": "get_food_log",
            "description": (
                "Return individual food entries logged on a specific date, with per-item macros and daily totals. "
                "Use for: 'what did I eat yesterday?', 'show me my food diary for Monday', "
                "'what was in my food log on Feb 21?'. Requires MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: yesterday)."},
                },
                "required": [],
            },
        },
    },
    "get_caffeine_sleep_correlation": {
        "fn": tool_get_caffeine_sleep_correlation,
        "schema": {
            "name": "get_caffeine_sleep_correlation",
            "description": (
                "Personal caffeine cutoff finder. Scans MacroFactor food_log for caffeine-containing items, "
                "finds the last caffeine intake time per day, then correlates with same-night Eight Sleep "
                "data (efficiency, deep sleep %, REM %, sleep score, onset latency). "
                "Splits days into time buckets (no caffeine / before noon / noon-2pm / 2pm-4pm / after 4pm) "
                "and compares average sleep quality across buckets. Also runs Pearson correlations for "
                "both timing and dose effects. Generates a personal cutoff recommendation. "
                "Based on Huberman and Attia guidance that caffeine timing is one of the highest-leverage sleep interventions. "
                "Use for: 'what is my caffeine cutoff?', 'does caffeine affect my sleep?', "
                "'when should I stop drinking coffee?', 'how does caffeine timing affect my deep sleep?', "
                "'caffeine and sleep correlation'. Requires MacroFactor food log data + Eight Sleep data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_exercise_sleep_correlation": {
        "fn": tool_get_exercise_sleep_correlation,
        "schema": {
            "name": "get_exercise_sleep_correlation",
            "description": (
                "Personal exercise timing cutoff finder. Extracts the last exercise end time per day from "
                "Strava (start_date_local + elapsed_time_seconds), then correlates with same-night Eight Sleep "
                "data (efficiency, deep sleep %, REM %, sleep score, onset latency, HRV). "
                "Splits days into time-of-day buckets (rest day / before noon / noon-3pm / 3-6pm / 6-8pm / after 8pm) "
                "and compares average sleep quality across buckets. Also analyzes exercise intensity via average HR "
                "and the interaction of intensity x timing (does a hard evening workout hurt more than an easy one?). "
                "Includes rest-day vs exercise-day comparison, Pearson correlations for timing and intensity effects, "
                "and a personal recommendation on exercise cutoff time. "
                "Based on Huberman, Galpin, and Attia guidance that exercise timing is a modifiable sleep lever. "
                "Use for: 'do late workouts hurt my sleep?', 'exercise timing and sleep quality', "
                "'when should I stop exercising before bed?', 'does evening exercise affect my deep sleep?', "
                "'exercise vs rest day sleep comparison'. Requires Strava + Eight Sleep data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":            {"type": "string", "description": "Start date YYYY-MM-DD (default: 180 days ago)."},
                    "end_date":              {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "min_duration_minutes":  {"type": "integer", "description": "Minimum activity duration in minutes to include (default: 15). Filters out very short activities."},
                    "exclude_sport_types":   {"type": "string", "description": "Comma-separated sport types to exclude (e.g. 'Walk,Yoga'). Case-insensitive."},
                },
                "required": [],
            },
        },
    },
    "get_zone2_breakdown": {
        "fn": tool_get_zone2_breakdown,
        "schema": {
            "name": "get_zone2_breakdown",
            "description": (
                "Zone 2 training tracker and weekly breakdown. Classifies Strava activities into 5 HR zones "
                "based on average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2 "
                "minutes and compares to the 150 min/week target (Attia, Huberman, WHO moderate-intensity guidelines). "
                "Shows full 5-zone training distribution, sport type breakdown for Zone 2, weekly trend analysis, "
                "and training polarization alerts (Zone 3 'no man\'s land' warning per Seiler). "
                "Zone 2 (60-70% max HR) is the highest-evidence longevity training modality — builds mitochondrial "
                "density, fat oxidation capacity, and cardiovascular base. "
                "Use for: 'how much Zone 2 am I doing?', 'am I hitting my Zone 2 target?', "
                "'show my training zone distribution', 'weekly Zone 2 minutes', 'zone 2 trend', "
                "'am I doing enough easy cardio?', 'training polarization check'. Requires Strava data with HR."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":             {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":               {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "weekly_target_minutes":   {"type": "integer", "description": "Weekly Zone 2 target in minutes (default: 150, per Attia/WHO guidelines)."},
                    "min_duration_minutes":    {"type": "integer", "description": "Minimum activity duration in minutes to include (default: 10)."},
                },
                "required": [],
            },
        },
    },
    "get_alcohol_sleep_correlation": {
        "fn": tool_get_alcohol_sleep_correlation,
        "schema": {
            "name": "get_alcohol_sleep_correlation",
            "description": (
                "Personal alcohol impact analyzer. Correlates MacroFactor alcohol intake (grams, standard drinks) "
                "with same-night Eight Sleep data (efficiency, deep %, REM %, sleep score, onset latency, HRV) "
                "AND next-day Whoop recovery (recovery score, HRV, resting HR). "
                "Splits days into dose buckets (none / light ≤1 drink / moderate 1-2.5 drinks / heavy 3+ drinks) "
                "and compares sleep + recovery quality across buckets. Also runs Pearson correlations for "
                "dose effects, timing effects (last drink time), and drinking-vs-sober comparison. "
                "Generates a personal impact severity assessment. One standard drink = 14g pure alcohol. "
                "Based on Huberman, Attia, and Walker: alcohol suppresses REM, raises resting HR, and impairs HRV recovery. "
                "Use for: 'is alcohol affecting my sleep?', 'how does drinking affect my recovery?', "
                "'alcohol and sleep correlation', 'should I drink less?', 'drinking vs sober sleep comparison', "
                "'how does alcohol affect my HRV?'. Requires MacroFactor food log + Eight Sleep data. "
                "Whoop data enhances next-day recovery analysis but is not required."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    # ── Habits / P40 tools ────────────────────────────────────────────────────
    "get_habit_adherence": {
        "fn": tool_get_habit_adherence,
        "schema": {
            "name": "get_habit_adherence",
            "description": (
                "Per-habit and per-group P40 completion rates over any date range. "
                "Returns habits ranked worst-to-best by adherence. "
                "Use for: 'how consistent am I with cold showers?', 'which P40 group is weakest?', "
                "'show my habit adherence this month'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 2020-01-01)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "group":      {"type": "string", "description": f"Optional P40 group filter. Valid: {P40_GROUPS}"},
                },
                "required": [],
            },
        },
    },
    "get_habit_streaks": {
        "fn": tool_get_habit_streaks,
        "schema": {
            "name": "get_habit_streaks",
            "description": (
                "Current streak, longest streak, and days since last completion for each P40 habit. "
                "Use for: 'what is my longest meditation streak?', 'which habits have I been consistent with?', "
                "'show my active streaks'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":  {"type": "string", "description": "Start date YYYY-MM-DD (default: 2020-01-01)."},
                    "end_date":    {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "habit_name":  {"type": "string", "description": "Optional habit name filter (fuzzy match)."},
                },
                "required": [],
            },
        },
    },
    "get_keystone_habits": {
        "fn": tool_get_keystone_habits,
        "schema": {
            "name": "get_keystone_habits",
            "description": (
                "Identifies which individual habits have the highest Pearson correlation with overall daily "
                "P40 completion score — the behavioral levers that lift everything else when done. "
                "r >= 0.5 = strong lever, r >= 0.3 = moderate. "
                "Use for: 'what are my keystone habits?', 'which habits have the most impact?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "top_n":      {"type": "number",  "description": "Number of top habits to return (default: 15)."},
                },
                "required": [],
            },
        },
    },
    "get_habit_health_correlations": {
        "fn": tool_get_habit_health_correlations,
        "schema": {
            "name": "get_habit_health_correlations",
            "description": (
                "Correlate a P40 habit or group score with a biometric outcome (HRV, recovery, weight, sleep). "
                "Supports lag_days to test predictive effects (e.g., does cold shower today predict HRV tomorrow?). "
                "Use for: 'does my Nutrition score predict recovery?', 'does meditation improve HRV?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "habit_name":    {"type": "string", "description": "Exact habit name (provide this OR group_name)."},
                    "group_name":    {"type": "string", "description": f"P40 group name (provide this OR habit_name). Valid: {P40_GROUPS}"},
                    "health_source": {"type": "string", "description": "Biometric source (e.g. 'whoop', 'withings', 'eightsleep')."},
                    "health_field":  {"type": "string", "description": "Biometric field (e.g. 'hrv', 'recovery_score', 'weight_lbs', 'total_score')."},
                    "start_date":    {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":      {"type": "string", "description": "End date YYYY-MM-DD."},
                    "lag_days":      {"type": "number",  "description": "Shift health metric N days forward (default: 0). Use 1 to test 'does A today predict B tomorrow?'."},
                },
                "required": ["health_source", "health_field"],
            },
        },
    },
    "get_group_trends": {
        "fn": tool_get_group_trends,
        "schema": {
            "name": "get_group_trends",
            "description": (
                "Weekly P40 group scores over time with trend direction (improving / stable / declining). "
                "Use for: 'how have my habits trended this year?', 'which P40 pillars are improving?', "
                "'show weekly habit scores'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "groups":     {"type": "array", "items": {"type": "string"},
                                   "description": f"Optional list of P40 groups to include. Valid: {P40_GROUPS}"},
                },
                "required": [],
            },
        },
    },
    "compare_habit_periods": {
        "fn": tool_compare_habit_periods,
        "schema": {
            "name": "compare_habit_periods",
            "description": (
                "Side-by-side P40 adherence comparison of two date ranges. Returns per-habit and per-group delta. "
                "Use for: 'how did my habits change after I started running more?', "
                "'compare this month to last month', 'was I more consistent pre-injury vs now?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period_a_start": {"type": "string", "description": "Start of period A (YYYY-MM-DD)."},
                    "period_a_end":   {"type": "string", "description": "End of period A (YYYY-MM-DD)."},
                    "period_b_start": {"type": "string", "description": "Start of period B (YYYY-MM-DD)."},
                    "period_b_end":   {"type": "string", "description": "End of period B (YYYY-MM-DD)."},
                    "period_a_label": {"type": "string", "description": "Label for period A (e.g. 'Last month')."},
                    "period_b_label": {"type": "string", "description": "Label for period B (e.g. 'This month')."},
                },
                "required": ["period_a_start", "period_a_end", "period_b_start", "period_b_end"],
            },
        },
    },
    "get_habit_stacks": {
        "fn": tool_get_habit_stacks,
        "schema": {
            "name": "get_habit_stacks",
            "description": (
                "Co-occurrence analysis: which P40 habits cluster together beyond chance. "
                "Uses lift = P(A and B) / (P(A) × P(B)). Lift > 1.5 = genuine clustering. "
                "Also identifies natural 'stacks' — 3+ habits co-occurring ≥60% of days. "
                "Use for: 'which habits do I always do together?', 'what are my natural morning routines?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "top_n":      {"type": "number",  "description": "Number of top pairs to return (default: 20)."},
                    "min_pct":    {"type": "number",  "description": "Minimum base rate to include a habit (default: 0.1 = 10%)."},
                },
                "required": [],
            },
        },
    },
    "get_habit_dashboard": {
        "fn": tool_get_habit_dashboard,
        "schema": {
            "name": "get_habit_dashboard",
            "description": (
                "Current-state P40 briefing. Shows: latest day status, 7-day rolling scores vs 30-day baseline, "
                "best/worst groups, top active streaks, and alerts for declining areas. "
                "Use for: 'how are my habits?', 'P40 morning check-in', 'what habits need attention?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_garmin_summary": {
        "fn": tool_get_garmin_summary,
        "schema": {
            "name": "get_garmin_summary",
            "description": (
                "Garmin Epix daily biometrics over a date range. Returns Body Battery (energy reserve 0-100), "
                "physiological stress score (HRV-derived, objective), overnight HRV (cross-check with Whoop), "
                "resting heart rate, and respiration rate. "
                "Body Battery is Garmin's flagship metric — it shows how much energy reserve you have "
                "throughout the day and how well you recovered. Avg stress is objective physiological stress "
                "(not self-reported) derived from continuous HRV monitoring. "
                "Use for: 'what is my Body Battery?', 'how stressed am I physiologically?', "
                "'show my Garmin data', 'what was my energy reserve this week?', "
                "'compare my Garmin HRV to Whoop'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 7 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_device_agreement": {
        "fn": tool_get_device_agreement,
        "schema": {
            "name": "get_device_agreement",
            "description": (
                "Cross-device validation: Whoop vs Garmin agreement on HRV and resting heart rate. "
                "Surfaces days where the two devices significantly disagree (>20ms HRV or >6bpm RHR delta), "
                "which indicates lower confidence in readiness scores for those days. "
                "Agreement rates and a composite device confidence rating are returned. "
                "Use for: 'do Whoop and Garmin agree?', 'how reliable is my readiness score?', "
                "'are there days where devices disagreed?', 'cross-device HRV validation', "
                "'device confidence check'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_readiness_score": {
        "fn": tool_get_readiness_score,
        "schema": {
            "name": "get_readiness_score",
            "description": (
                "Unified readiness score (0-100) synthesising Whoop recovery (35%), Eight Sleep score (25%), "
                "HRV 7-day trend vs 30-day baseline (20%), TSB training form (10%), and "
                "Garmin Body Battery (10%) into a single GREEN / YELLOW / RED signal with a 1-line "
                "actionable recommendation. Also includes a device_agreement section showing Whoop vs "
                "Garmin HRV/RHR delta as a confidence signal — flag status means lower score reliability. "
                "Reduces cognitive load: one number instead of 5 separate metrics tells you "
                "'train hard today' vs 'go easy' vs 'rest day'. Missing components are excluded and "
                "remaining weights re-normalised. "
                "Use for: 'should I train hard today?', 'what is my readiness score?', "
                "'am I ready for a key session?', 'how am I feeling today?', 'morning readiness check-in'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "save_insight": {
        "fn": tool_save_insight,
        "schema": {
            "name": "save_insight",
            "description": (
                "Save a new insight to the personal coaching log. "
                "Use whenever Claude or Matthew identifies something worth tracking and following up on — "
                "a hypothesis, a behavioural change to try, a pattern noticed, or a recommendation to act on. "
                "Returns the insight_id needed for update_insight_outcome. "
                "Use for: 'save this insight', 'track this idea', 'add this to the coaching log', "
                "'remember to follow up on this'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text":   {"type": "string",  "description": "The insight text to save. Be specific and actionable."},
                    "tags":   {"type": "array",   "items": {"type": "string"},
                               "description": "Optional list of tags (e.g. ['sleep', 'hrv', 'caffeine'])."},
                    "source": {"type": "string",  "description": "Origin of the insight: 'chat' (default) or 'email'."},
                },
                "required": ["text"],
            },
        },
    },
    "get_insights": {
        "fn": tool_get_insights,
        "schema": {
            "name": "get_insights",
            "description": (
                "List insights from the personal coaching log. "
                "Returns all insights newest-first with days_open calculated. "
                "Stale flag is set for open insights older than 14 days. "
                "Use for: 'what insights are open?', 'show my coaching log', "
                "'what have I been meaning to act on?', 'any stale insights?', "
                "'show me resolved insights'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status_filter": {"type": "string",
                                      "description": "Filter by status: 'open', 'acted', or 'resolved'. Omit for all."},
                    "limit":         {"type": "integer", "description": "Max results to return (default: 50)."},
                },
                "required": [],
            },
        },
    },
    "update_insight_outcome": {
        "fn": tool_update_insight_outcome,
        "schema": {
            "name": "update_insight_outcome",
            "description": (
                "Close the loop on a saved insight — record what happened when you acted on it. "
                "Updates the insight's status and adds outcome notes. "
                "Use for: 'I tried the caffeine cutoff — it worked', 'mark this insight as resolved', "
                "'update the outcome for insight X', 'close out this coaching log item'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "insight_id":    {"type": "string", "description": "The insight_id returned by save_insight (e.g. 2026-02-22T09:15:00)."},
                    "outcome_notes": {"type": "string", "description": "What happened — did it work? What did you learn?"},
                    "status":        {"type": "string", "description": "New status: 'acted' (tried it) or 'resolved' (fully closed). Default: 'acted'."},
                },
                "required": ["insight_id"],
            },
        },
    },
    "get_lab_results": {
        "fn": tool_get_lab_results,
        "schema": {
            "name": "get_lab_results",
            "description": (
                "Get blood work results. Without a date, returns summary of all 7 draws (2019-2025). "
                "With a date, returns full biomarkers with genome cross-reference annotations. "
                "Filter by category: lipids, cbc, metabolic, thyroid, liver, kidney, etc. "
                "Use for: 'show my latest blood work', 'lipids in 2024', 'all lab draws'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "draw_date": {"type": "string", "description": "Draw date YYYY-MM-DD. Omit to list all."},
                    "category":  {"type": "string", "description": "Filter: lipids, cbc, metabolic, thyroid, liver, kidney, electrolytes, minerals, diabetes, hormones, etc."},
                },
                "required": [],
            },
        },
    },
    "get_lab_trends": {
        "fn": tool_get_lab_trends,
        "schema": {
            "name": "get_lab_trends",
            "description": (
                "Track biomarker trajectory across all 7 draws (2019-2025). Slope per year, 1-year projection, "
                "derived ratios (TG/HDL, non-HDL, TC/HDL). Genome flags for genetic drivers. "
                "Use for: 'LDL trend', 'cholesterol trajectory', 'is glucose rising', 'TG/HDL ratio over time'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "biomarker":  {"type": "string", "description": "Single key: 'ldl_c', 'hba1c', 'glucose'. Use search_biomarker to find names."},
                    "biomarkers": {"type": "array", "items": {"type": "string"}, "description": "Multiple keys."},
                    "include_derived_ratios": {"type": "boolean", "description": "Include TG/HDL, non-HDL, TC/HDL. Default true."},
                },
                "required": [],
            },
        },
    },
    "get_out_of_range_history": {
        "fn": tool_get_out_of_range_history,
        "schema": {
            "name": "get_out_of_range_history",
            "description": (
                "All out-of-range biomarkers across draws with persistence (chronic/recurring/occasional) "
                "and genome-driven explanations. Use for: 'flagged biomarkers', 'persistent issues', 'genetic vs lifestyle flags'."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "search_biomarker": {
        "fn": tool_search_biomarker,
        "schema": {
            "name": "search_biomarker",
            "description": (
                "Free-text biomarker search across all draws. Values over time + trend. "
                "Use when you don't know the exact key. 'find cholesterol', 'search thyroid', 'iron markers'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term: 'cholesterol', 'thyroid', 'liver', 'iron'."},
                },
                "required": ["query"],
            },
        },
    },
    "get_genome_insights": {
        "fn": tool_get_genome_insights,
        "schema": {
            "name": "get_genome_insights",
            "description": (
                "Query 110 genome SNPs by category/risk/gene. Cross-reference with labs or nutrition. "
                "Categories: metabolism, cardiovascular, nutrients, methylation, inflammation, longevity, etc. "
                "Risks: unfavorable, mixed, neutral, favorable. "
                "Use for: 'genome metabolism', 'unfavorable SNPs', 'FTO variants', 'genome + labs cross-ref'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category":        {"type": "string", "description": "SNP category filter."},
                    "risk_level":      {"type": "string", "description": "unfavorable, mixed, neutral, favorable."},
                    "gene":            {"type": "string", "description": "Gene name: FTO, MTHFR, ABCG8."},
                    "cross_reference": {"type": "string", "description": "'labs' or 'nutrition' for cross-ref data."},
                },
                "required": [],
            },
        },
    },
    "get_body_composition_snapshot": {
        "fn": tool_get_body_composition_snapshot,
        "schema": {
            "name": "get_body_composition_snapshot",
            "description": (
                "DEXA scan: FFMI, visceral fat, BMD, A/G ratio, posture analysis, Withings delta. "
                "Use for: 'DEXA results', 'body composition', 'FFMI', 'posture', 'weight change since DEXA'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Scan date YYYY-MM-DD. Omit for latest."},
                },
                "required": [],
            },
        },
    },
    "get_health_risk_profile": {
        "fn": tool_get_health_risk_profile,
        "schema": {
            "name": "get_health_risk_profile",
            "description": (
                "Health risk synthesis: cardiovascular, metabolic, longevity. Combines 7 lab draws, "
                "110 genome SNPs, DEXA, wearable HRV into unified assessment. "
                "Use for: 'health risk profile', 'CV risk', 'metabolic health', 'longevity assessment'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "'cardiovascular', 'metabolic', 'longevity'. Omit for all."},
                },
                "required": [],
            },
        },
    },
    "get_day_type_analysis": {
        "fn": tool_get_day_type_analysis,
        "schema": {
            "name": "get_day_type_analysis",
            "description": "Segment health metrics by training day type (rest/light/moderate/hard/race). Cross-references Whoop strain, Strava, and training load to classify each day, then compares averages for sleep, recovery, and nutrition across day types. Shows associations, not causation. Use for: 'how does my sleep differ on hard vs easy days?', 'do I eat more on rest days?', 'what\'s my HRV pattern on hard vs easy days?', 'how do my recovery metrics look by day type?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 90 days ago."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "days":       {"type": "number", "description": "Lookback window in days. Default 90. Ignored if start_date provided."},
                    "metrics":    {"type": "array", "items": {"type": "string"}, "description": "Metric groups to analyze: 'sleep', 'recovery', 'nutrition'. Default: all three."},
                },
                "required": [],
            },
        },
    },
    "get_next_lab_priorities": {
        "fn": tool_get_next_lab_priorities,
        "schema": {
            "name": "get_next_lab_priorities",
            "description": (
                "Genome-informed next blood panel recommendations. Tests to add based on genetic risk, "
                "persistent flags, and gaps. Priority levels + rationale. "
                "Use for: 'what to test next', 'plan next blood draw', 'missing tests'."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },

    # ── v2.15.0 — Gait, Energy Balance, Movement, CGM tools ─────────────────
    "get_gait_analysis": {
        "fn": tool_get_gait_analysis,
        "schema": {
            "name": "get_gait_analysis",
            "description": (
                "Gait & mobility tracker from Apple Watch. Tracks walking speed (strongest all-cause mortality "
                "predictor), step length (earliest aging marker), asymmetry (injury indicator), double support "
                "(fall risk). Composite score 0-100, clinical flags, trend analysis. <2.24 mph = clinical flag. "
                "Use for: 'gait analysis', 'walking speed trend', 'mobility health', 'injury detection'. "
                "Requires Apple Health webhook v1.1.0+."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 90d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
    "get_energy_balance": {
        "fn": tool_get_energy_balance,
        "schema": {
            "name": "get_energy_balance",
            "description": (
                "Daily energy balance: Apple Watch TDEE (active + basal cal) vs MacroFactor intake. "
                "Daily surplus/deficit, rolling averages, implied weight change. Uses real wearable data "
                "not formula BMR. Tracks deficit target hit rate. "
                "Use for: 'am I in a deficit?', 'calorie balance', 'TDEE vs intake', 'surplus or deficit?'. "
                "Requires Apple Health webhook + MacroFactor."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date":          {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":            {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                "target_deficit_kcal": {"type": "integer", "description": "Target daily deficit kcal (default: 500)."},
            }, "required": []},
        },
    },
    "get_movement_score": {
        "fn": tool_get_movement_score,
        "schema": {
            "name": "get_movement_score",
            "description": (
                "Daily movement & NEAT analysis. NEAT = energy burned outside exercise (larger than workouts "
                "for most people). Movement score 0-100, step target tracking, sedentary day flags. "
                "Use for: 'am I moving enough?', 'NEAT analysis', 'sedentary days', 'step trend', "
                "'non-exercise activity'. Requires Apple Health webhook. Strava enhances NEAT calc."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date":  {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":    {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                "step_target": {"type": "integer", "description": "Daily step target (default: 8000)."},
            }, "required": []},
        },
    },
    "get_cgm_dashboard": {
        "fn": tool_get_cgm_dashboard,
        "schema": {
            "name": "get_cgm_dashboard",
            "description": (
                "CGM blood glucose dashboard. Time in range (target >90%), variability (SD target <20), "
                "mean glucose (target <100), time above 140, fasting proxy. Clinical flags, trend analysis. "
                "Glucose management is a top-3 longevity lever (Attia, Huberman). "
                "Use for: 'glucose overview', 'CGM dashboard', 'blood sugar', 'time in range', "
                "'metabolic health', 'am I pre-diabetic?'. Requires Apple Health CGM webhook."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
    "get_glucose_sleep_correlation": {
        "fn": tool_get_glucose_sleep_correlation,
        "schema": {
            "name": "get_glucose_sleep_correlation",
            "description": (
                "Correlate glucose with same-night sleep. Buckets by glucose level, compares Eight Sleep "
                "outcomes. Pearson correlations for variability/spikes vs sleep quality. Elevated evening "
                "glucose raises core temp, opposing deep sleep (Huberman, Walker). "
                "Use for: 'does blood sugar affect sleep?', 'glucose sleep correlation', "
                "'do spikes hurt sleep?'. Requires Apple Health CGM + Eight Sleep."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 90d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
    "get_glucose_meal_response": {
        "fn": tool_get_glucose_meal_response,
        "schema": {
            "name": "get_glucose_meal_response",
            "description": (
                "Levels-style postprandial glucose response analysis. For each meal logged in MacroFactor, "
                "matches 5-minute CGM readings to compute: pre-meal baseline, peak glucose, spike magnitude, "
                "time-to-peak, AUC, and a letter grade (A-F). Aggregates best/worst meals, per-food scores "
                "across days, and macro correlations (carbs/fiber/protein/sugar vs spike). "
                "Based on Attia, Huberman, Lustig: spikes >30 mg/dL drive insulin resistance and inflammation. "
                "Use for: 'which foods spike my glucose?', 'meal glucose response', 'food scoring', "
                "'postprandial analysis', 'best and worst meals for blood sugar', 'does fiber help my glucose?'. "
                "Requires MacroFactor food log + CGM data (Dexcom Stelo via Apple Health webhook)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":        {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":          {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "meal_gap_minutes":  {"type": "integer", "description": "Minutes gap to consider separate meals (default: 30)."},
                },
                "required": [],
            },
        },
    },
    "get_fasting_glucose_validation": {
        "fn": tool_get_fasting_glucose_validation,
        "schema": {
            "name": "get_fasting_glucose_validation",
            "description": "Validate CGM fasting glucose accuracy against venous lab draws. Computes proper overnight nadir (midnight-6AM) from raw CGM readings, builds distribution, and compares against 6 historical blood draws. Two modes: direct same-day validation when overlap exists, and statistical validation (z-scores, percentiles) when not. Shows bias analysis, confidence level, and Board of Directors interpretation. Use for: 'how accurate is my CGM fasting glucose?', 'validate CGM against labs', 'compare overnight nadir to blood work', 'is my fasting proxy trustworthy?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "nadir_start_hour": {"type": "number", "description": "Start of overnight window (decimal hours). Default 0 (midnight)."},
                    "nadir_end_hour": {"type": "number", "description": "End of overnight window (decimal hours). Default 6 (6 AM)."},
                    "deep_nadir_start_hour": {"type": "number", "description": "Start of deep nadir window. Default 2 (2 AM). Avoids late digestion."},
                    "deep_nadir_end_hour": {"type": "number", "description": "End of deep nadir window. Default 5 (5 AM). Avoids dawn phenomenon."},
                    "min_overnight_readings": {"type": "number", "description": "Minimum CGM readings in overnight window. Default 6 (~30 min coverage)."},
                },
                "required": [],
            },
        },
    },
    "get_glucose_exercise_correlation": {
        "fn": tool_get_glucose_exercise_correlation,
        "schema": {
            "name": "get_glucose_exercise_correlation",
            "description": (
                "Exercise vs rest day glucose comparison. Intensity analysis (easy vs hard). Duration "
                "correlations. Zone 2 improves glucose disposal — trending this is a longevity biomarker "
                "(Attia). Exercise increases GLUT4 uptake for 24-48h. "
                "Use for: 'does exercise help blood sugar?', 'workout vs rest day glucose', "
                "'Zone 2 glucose benefit'. Requires Apple Health CGM + Strava."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 90d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },

    # ── Journal tools (v2.16.0) ────────────────────────────────────────────────
    "get_journal_entries": {
        "fn": tool_get_journal_entries,
        "schema": {
            "name": "get_journal_entries",
            "description": (
                "Retrieve journal entries for a date range with optional template filter. "
                "Returns structured fields + Haiku-enriched signals (mood, energy, stress, "
                "themes, emotions, cognitive patterns, values, etc). "
                "Use for: 'show my journal from last week', 'what did I write this morning?', "
                "'evening entries from January', 'my weekly reflections'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 7 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "template":   {"type": "string", "description": "Filter by template: morning, evening, stressor, health_event, weekly. Optional."},
                    "include_enriched": {"type": "boolean", "description": "Include Haiku-enriched fields (default: true)."},
                },
                "required": [],
            },
        },
    },
    "search_journal": {
        "fn": tool_search_journal,
        "schema": {
            "name": "search_journal",
            "description": (
                "Full-text search across all journal entries — searches raw text, themes, "
                "emotions, avoidance flags, pain mentions, quotes, and all enriched fields. "
                "Use for: 'when did I mention back pain?', 'find entries about work stress', "
                "'search for entries where I felt lonely', 'find journal mentions of alcohol'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query":      {"type": "string", "description": "Search keywords (all must match)."},
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: all time)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                },
                "required": ["query"],
            },
        },
    },
    "get_mood_trend": {
        "fn": tool_get_mood_trend,
        "schema": {
            "name": "get_mood_trend",
            "description": (
                "Mood, energy, and stress scores over time with 7-day rolling averages, "
                "trend direction, and recurring themes at peaks/valleys. Combines structured "
                "Notion scores with Haiku-enriched signals for the most accurate longitudinal view. "
                "Use for: 'how has my mood been this month?', 'stress trend over 30 days', "
                "'am I getting better?', 'energy trend', 'mood and stress together'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "metric":     {"type": "string", "description": "mood, energy, stress, or all (default: all)."},
                },
                "required": [],
            },
        },
    },
    "get_journal_insights": {
        "fn": tool_get_journal_insights,
        "schema": {
            "name": "get_journal_insights",
            "description": (
                "Cross-entry pattern analysis — the 'so what?' tool. Surfaces recurring themes, "
                "dominant emotions, cognitive pattern frequency (CBT: catastrophizing, rumination, "
                "reframing, growth mindset), avoidance flags, ownership trend (locus of control), "
                "values alignment, social connection quality, flow state frequency, and gratitude patterns. "
                "Based on Seligman (PERMA), Beck (CBT), Ferriss (fear-setting), Jocko (ownership), "
                "Huberman (stress), Csikszentmihalyi (flow). "
                "Use for: 'what patterns do you see in my journal?', 'what am I consistently avoiding?', "
                "'how is my ownership trending?', 'cognitive pattern analysis', 'journal insights'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_journal_correlations": {
        "fn": tool_get_journal_correlations,
        "schema": {
            "name": "get_journal_correlations",
            "description": (
                "Correlate journal signals (mood, energy, stress, subjective sleep quality) "
                "with wearable data (Whoop recovery/HRV/strain, Eight Sleep score/efficiency, "
                "Garmin stress/Body Battery/readiness). Finds Pearson correlations and notable "
                "divergences where subjective experience doesn't match objective data "
                "(e.g. 'felt terrible but Eight Sleep scored 85' = possible sleep state misperception). "
                "Use for: 'does my mood correlate with HRV?', 'subjective vs objective sleep', "
                "'do high-stress days affect my recovery?', 'journal-wearable correlations'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 60 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "signal":     {"type": "string", "description": "stress, mood, energy, sleep_quality, or all (default: all)."},
                },
                "required": [],
            },
        },
    },
    "create_experiment": {
        "fn": tool_create_experiment,
        "schema": {
            "name": "create_experiment",
            "description": (
                "Start tracking a new N=1 experiment. An experiment is a specific protocol change "
                "(supplement, diet shift, sleep hygiene tweak, training adjustment) with a hypothesis "
                "and start date. The system will automatically compare before/after metrics when you "
                "call get_experiment_results. Board rules: one variable at a time, minimum 14 days, "
                "define success criteria upfront. "
                "Use for: 'I'm starting creatine today', 'track my no-caffeine-after-10am experiment', "
                "'create experiment for cold plunge protocol', 'I want to test if X improves Y'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name":       {"type": "string", "description": "Short name of the intervention (e.g. 'Creatine 5g daily', 'No screens after 9pm')."},
                    "hypothesis": {"type": "string", "description": "What you expect to happen (e.g. 'Will improve deep sleep % by >5%')."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to today."},
                    "tags":       {"type": "array", "items": {"type": "string"},
                                   "description": "Optional tags (e.g. ['sleep', 'supplement', 'caffeine'])."},
                    "notes":      {"type": "string", "description": "Additional context or protocol details."},
                },
                "required": ["name", "hypothesis"],
            },
        },
    },
    "list_experiments": {
        "fn": tool_list_experiments,
        "schema": {
            "name": "list_experiments",
            "description": (
                "List all N=1 experiments with their status, duration, and whether minimum "
                "data threshold (14 days) has been met. Filter by status. "
                "Use for: 'what experiments am I running?', 'show active experiments', "
                "'list completed experiments', 'any experiments ready to evaluate?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: 'active', 'completed', 'abandoned'. Omit for all."},
                },
                "required": [],
            },
        },
    },
    "get_experiment_results": {
        "fn": tool_get_experiment_results,
        "schema": {
            "name": "get_experiment_results",
            "description": (
                "Auto-compare before vs during metrics for an N=1 experiment. "
                "Automatically queries sleep, recovery, stress, body composition, nutrition, "
                "movement, and glucose metrics for both the pre-experiment baseline period "
                "and the experiment period. Reports deltas, % changes, and direction "
                "(improved/worsened). Board of Directors evaluates results against hypothesis. "
                "Use for: 'how is my creatine experiment going?', 'did cutting caffeine help my sleep?', "
                "'show experiment results', 'evaluate my N=1', 'did this actually work?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "The experiment_id from create_experiment or list_experiments."},
                },
                "required": ["experiment_id"],
            },
        },
    },
    "end_experiment": {
        "fn": tool_end_experiment,
        "schema": {
            "name": "end_experiment",
            "description": (
                "End an active N=1 experiment and record the outcome. "
                "Run get_experiment_results first to review the data. "
                "Status can be 'completed' (ran full course) or 'abandoned' (stopped early). "
                "Use for: 'end my creatine experiment', 'I'm stopping the no-caffeine experiment', "
                "'mark experiment as completed', 'abandon experiment X'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "The experiment_id to end."},
                    "outcome":       {"type": "string", "description": "What happened — did it work? What did you learn?"},
                    "status":        {"type": "string", "description": "'completed' (default) or 'abandoned'."},
                    "end_date":      {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["experiment_id"],
            },
        },
    },

    "get_health_trajectory": {
        "fn": tool_get_health_trajectory,
        "schema": {
            "name": "get_health_trajectory",
            "description": (
                "Forward-looking health intelligence — where are you headed? "
                "Computes trajectories and projections across 5 domains: weight (rate of loss, "
                "goal date, phase milestones), biomarkers (lab trend slopes, projected values, "
                "threshold warnings), fitness (Zone 2 trend, training consistency), recovery "
                "(HRV trend, sleep efficiency), and metabolic (glucose trends, time in range). "
                "Board of Directors provides a longevity-focused assessment of overall trajectory. "
                "Use for: 'where am I headed?', 'health trajectory', 'projected goal date', "
                "'biomarker trends', 'am I on track?', 'forward-looking health assessment', "
                "'when will I reach my goal weight?', 'longevity projection'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string",
                               "description": "Focus area: 'all' (default), 'weight', 'biomarkers', 'fitness', 'recovery', 'metabolic'."},
                },
                "required": [],
            },
        },
    },
    "get_hr_recovery_trend": {
        "fn": tool_get_hr_recovery_trend,
        "schema": {
            "name": "get_hr_recovery_trend",
            "description": (
                "Heart rate recovery tracker — the strongest exercise-derived mortality predictor (Cole et al., NEJM). "
                "Extracts post-peak HR recovery from Strava activity streams, trends over time, classifies against "
                "clinical thresholds (>25 excellent, 18-25 good, 12-18 average, <12 abnormal). Shows sport-type "
                "breakdown, cooldown vs no-cooldown comparison, best/worst sessions, and fitness trajectory. "
                "Board of Directors provides longevity assessment. "
                "Use for: 'HR recovery trend', 'heart rate recovery', 'am I getting fitter?', "
                "'cardiovascular fitness trajectory', 'autonomic function', 'post-exercise HR drop'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 180 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "sport_type": {"type": "string", "description": "Filter by sport type (e.g. 'Run', 'Ride'). Case-insensitive."},
                    "cooldown_only": {"type": "boolean", "description": "Only include activities with detected cooldown. Default: false."},
                },
                "required": [],
            },
        },
    },
    "get_sleep_environment_analysis": {
        "fn": tool_get_sleep_environment_analysis,
        "schema": {
            "name": "get_sleep_environment_analysis",
            "description": (
                "Sleep environment optimization. Correlates Eight Sleep bed temperature settings "
                "(heating/cooling level, bed temp F/C) with sleep outcomes (efficiency, deep %, "
                "REM %, score, onset latency, HRV). Splits nights into temperature buckets, "
                "computes Pearson correlations, and identifies your optimal thermal sleep profile. "
                "Huberman: core body temperature is the #1 physiological sleep trigger. "
                "Walker: sleeping too warm is the most common modifiable sleep disruptor. "
                "Use for: 'optimal bed temperature', 'does temperature affect my sleep?', "
                "'Eight Sleep temperature correlation', 'sleep environment', 'bed cooling analysis', "
                "'what temperature should I set my Eight Sleep?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 180 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "log_supplement": {
        "fn": tool_log_supplement,
        "schema": {
            "name": "log_supplement",
            "description": (
                "Log a supplement or medication. Writes to the supplements partition in DynamoDB. "
                "Supports name, dose, unit, timing (morning, with_meal, before_bed, post_workout), "
                "category (supplement, medication, vitamin, mineral), and notes. Multiple entries per day. "
                "Use for: 'log 500mg magnesium before bed', 'track my creatine', 'I took vitamin D this morning', "
                "'log my medication', 'supplement log entry'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Supplement or medication name (required)."},
                    "dose": {"type": "number", "description": "Dosage amount (e.g. 500 for 500mg)."},
                    "unit": {"type": "string", "description": "Unit: mg, mcg, g, IU, ml, capsule, tablet."},
                    "timing": {"type": "string", "description": "When taken: morning, with_meal, before_bed, post_workout, evening, afternoon."},
                    "category": {"type": "string", "description": "Category: supplement, medication, vitamin, mineral. Default: supplement."},
                    "notes": {"type": "string", "description": "Optional notes."},
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": ["name"],
            },
        },
    },
    "get_supplement_log": {
        "fn": tool_get_supplement_log,
        "schema": {
            "name": "get_supplement_log",
            "description": (
                "Retrieve supplement/medication log. Shows what was taken, dosage, timing, adherence patterns, "
                "and per-supplement summary with adherence percentage. Filter by supplement name. "
                "Use for: 'show my supplement log', 'what supplements am I taking?', 'supplement adherence', "
                "'am I consistent with creatine?', 'medication history'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "name": {"type": "string", "description": "Filter by supplement name (partial match, case-insensitive)."},
                },
                "required": [],
            },
        },
    },
    "get_supplement_correlation": {
        "fn": tool_get_supplement_correlation,
        "schema": {
            "name": "get_supplement_correlation",
            "description": (
                "Cross-reference a specific supplement with health outcomes. Compares days taking the supplement "
                "vs days without across recovery, sleep, HRV, glucose, stress. Enhances N=1 experiments. "
                "Use for: 'is magnesium helping my sleep?', 'creatine impact on recovery', "
                "'does vitamin D affect my HRV?', 'supplement effectiveness', 'is this supplement working?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Supplement name to analyze (required). Partial match, case-insensitive."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": ["name"],
            },
        },
    },
    "get_weather_correlation": {
        "fn": tool_get_weather_correlation,
        "schema": {
            "name": "get_weather_correlation",
            "description": (
                "Weather & seasonal correlation analysis. Fetches Seattle weather from Open-Meteo "
                "(free API), caches in DynamoDB, and correlates temperature, humidity, precipitation, "
                "daylight hours, sunshine, barometric pressure, and UV index with health metrics "
                "(recovery, HRV, sleep, stress, Body Battery) and journal signals (mood, energy, stress). "
                "Huberman: daylight is the master circadian lever. Walker: seasonal light drives sleep. "
                "Attia: barometric pressure affects inflammation and autonomic function. "
                "Use for: 'does weather affect my sleep?', 'daylight and mood correlation', "
                "'seasonal patterns in my health', 'weather impact on recovery', "
                "'does rain affect my energy?', 'sunshine and sleep quality'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_training_periodization": {
        "fn": tool_get_training_periodization,
        "schema": {
            "name": "get_training_periodization",
            "description": (
                "Training periodization planner. Analyzes weekly training patterns to detect mesocycle phases "
                "(base/build/peak/deload), deload needs (Galpin 3:1 or 4:1 ratio), progressive overload "
                "tracking (strength volume trends), training polarization (Seiler 80/20 model), Zone 2 "
                "target adherence (Attia 150 min/week), and training consistency. "
                "Use for: 'do I need a deload?', 'training periodization', 'am I overtraining?', "
                "'progressive overload trend', 'training polarization check', 'weekly training summary', "
                "'mesocycle analysis', 'should I take a rest week?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 12 weeks ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "weeks": {"type": "integer", "description": "Number of weeks to analyze (default: 12). Ignored if start_date provided."},
                },
                "required": [],
            },
        },
    },
    "get_training_recommendation": {
        "fn": tool_get_training_recommendation,
        "schema": {
            "name": "get_training_recommendation",
            "description": (
                "Readiness-based training recommendation. Synthesizes Whoop recovery, Eight Sleep quality, "
                "Garmin Body Battery, training load (CTL/ATL/TSB), recent activity history, and muscle group "
                "recency into a specific workout suggestion: type (Zone 2, intervals, strength upper/lower, "
                "active recovery, rest), intensity, duration, HR targets, and muscle groups to target. "
                "Board of Directors provides rationale. Warns about injury risk (ACWR), consecutive training days, "
                "and sleep debt. Use for: 'what should I do today?', 'workout recommendation', 'should I train today?', "
                "'am I recovered enough for a hard workout?', 'readiness-based training', 'what workout today?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_social_connection_trend": {
        "fn": tool_get_social_connection_trend,
        "schema": {
            "name": "get_social_connection_trend",
            "description": (
                "Social connection quality trend from journal entries. Tracks enriched_social_quality "
                "(alone/surface/meaningful/deep) over time with rolling averages, streaks, and PERMA "
                "wellbeing model context. Correlates social quality with recovery, HRV, sleep, stress. "
                "Seligman: Relationships are the #1 predictor of sustained wellbeing. "
                "Use for: 'social connection trend', 'meaningful connections', 'PERMA score'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_social_isolation_risk": {
        "fn": tool_get_social_isolation_risk,
        "schema": {
            "name": "get_social_isolation_risk",
            "description": (
                "Social isolation risk detector. Flags periods of 3+ consecutive days without meaningful "
                "social connection. Correlates isolation episodes with health metric declines. "
                "Use for: 'am I socially isolated?', 'isolation risk', 'loneliness health impact'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "consecutive_days": {"type": "integer", "description": "Consecutive days threshold (default: 3)."},
                },
                "required": [],
            },
        },
    },
    "get_meditation_correlation": {
        "fn": tool_get_meditation_correlation,
        "schema": {
            "name": "get_meditation_correlation",
            "description": (
                "Meditation and breathwork analysis. Tracks mindful_minutes from Apple Health, "
                "correlates with HRV, stress, sleep, recovery, Body Battery. Shows meditation vs "
                "non-meditation day comparisons, dose-response, next-day effects, streaks. "
                "Huberman: NSDR is highest-ROI. Attia: consistency > duration. "
                "Use for: 'meditation impact', 'does meditation help HRV?', 'breathwork effects'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    # ── Travel & Jet Lag (v2.40.0) ────────────────────────────────────────────
    "log_travel": {
        "fn": tool_log_travel,
        "schema": {
            "name": "log_travel",
            "description": (
                "Log a trip start or end. Tracks destination, timezone offset, and travel direction. "
                "On trip start: computes timezone difference, provides Huberman jet lag protocol "
                "(light exposure, meal timing, melatonin window, exercise). On trip end: closes the active trip. "
                "Travel records are used by anomaly detector (suppresses false positives during travel) "
                "and daily brief (travel mode banner). "
                "Use for: 'I'm traveling to London', 'log a trip to Tokyo', 'I'm back home', 'end my trip'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "'start' (default) or 'end'."},
                    "destination_city": {"type": "string", "description": "City name (required for start)."},
                    "destination_country": {"type": "string", "description": "Country name."},
                    "destination_timezone": {"type": "string", "description": "IANA timezone (e.g. 'Europe/London', 'Asia/Tokyo'). Enables jet lag protocol."},
                    "start_date": {"type": "string", "description": "Trip start YYYY-MM-DD (default: today)."},
                    "end_date": {"type": "string", "description": "Trip end YYYY-MM-DD (for action='end', default: today)."},
                    "purpose": {"type": "string", "description": "personal, work, family, vacation."},
                    "trip_id": {"type": "string", "description": "Trip ID to end (for action='end'). If omitted, ends most recent active trip."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": [],
            },
        },
    },
    "get_travel_log": {
        "fn": tool_get_travel_log,
        "schema": {
            "name": "get_travel_log",
            "description": (
                "List all trips with status, timezone offsets, and duration. Shows currently active trip if any. "
                "Filter by status (active/completed). "
                "Use for: 'show my trips', 'am I traveling?', 'travel history', 'list completed trips'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: 'active', 'completed'. Omit for all."},
                },
                "required": [],
            },
        },
    },
    "get_jet_lag_recovery": {
        "fn": tool_get_jet_lag_recovery,
        "schema": {
            "name": "get_jet_lag_recovery",
            "description": (
                "Post-trip recovery analysis. Compares 7-day pre-trip baseline to post-return recovery curve "
                "across 8 metrics (HRV, recovery, sleep, stress, Body Battery, steps). Shows days-to-baseline "
                "for each metric, overall recovery summary, and Board coaching. "
                "Huberman: ~1 day recovery per timezone crossed, eastbound harder. "
                "Use for: 'how did I recover from my trip?', 'jet lag recovery', 'post-travel analysis', "
                "'did travel affect my sleep?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string", "description": "Trip ID from get_travel_log. Omit for most recent completed trip."},
                    "recovery_window_days": {"type": "integer", "description": "Days after return to analyze (default: 14)."},
                },
                "required": [],
            },
        },
    },
    "get_blood_pressure_dashboard": {
        "fn": tool_get_blood_pressure_dashboard,
        "schema": {
            "name": "get_blood_pressure_dashboard",
            "description": (
                "Blood pressure dashboard. Current status, AHA classification (normal/elevated/stage1/stage2/crisis), "
                "30-day trend, morning vs evening patterns from individual readings, variability analysis (SD). "
                "SD >12 mmHg systolic is an independent cardiovascular risk factor. "
                "Use for: 'blood pressure status', 'BP trend', 'am I hypertensive?', "
                "'morning vs evening BP', 'blood pressure variability'. "
                "Requires BP cuff syncing to Apple Health."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_blood_pressure_correlation": {
        "fn": tool_get_blood_pressure_correlation,
        "schema": {
            "name": "get_blood_pressure_correlation",
            "description": (
                "Correlate blood pressure with lifestyle factors: sodium intake, training load, stress, "
                "sleep quality, caffeine, weight. Pearson r for systolic and diastolic vs 11 factors. "
                "Exercise vs rest day comparison. Sodium dose-response buckets (low/mid/high). "
                "Attia: sodium is strongest modifiable lever. Huberman: Zone 2 is most evidence-backed BP intervention. "
                "Use for: 'does sodium affect my BP?', 'exercise and blood pressure', "
                "'what affects my blood pressure?', 'BP correlations', 'salt sensitivity'. "
                "Requires BP cuff syncing to Apple Health + 5+ days of data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_state_of_mind_trend": {
        "fn": tool_get_state_of_mind_trend,
        "schema": {
            "name": "get_state_of_mind_trend",
            "description": (
                "State of Mind valence trend from How We Feel / Apple Health. Tracks mood check-ins "
                "(momentary emotions + daily moods) with valence (-1 to +1), emotion labels (Happy, Stressed, "
                "Calm, Anxious, etc.), and life area associations (Work, Family, Health, Fitness, Money, etc.). "
                "Shows overall valence trend, 7-day rolling average, time-of-day patterns, best/worst days, "
                "top emotion labels, valence by life area (which domains drive best/worst mood), and "
                "valence classification distribution. Huberman: mood is circadian — cortisol, dopamine, serotonin "
                "fluctuate throughout day. Walker: evening mood valence predicts sleep onset latency. "
                "Seligman: momentary mood sampling is clinically validated experience sampling method (ESM). "
                "Use for: 'how has my mood been?', 'state of mind trend', 'valence trend', 'mood check-ins', "
                "'what makes me feel best?', 'mood by time of day', 'How We Feel data', "
                "'emotional patterns', 'which life areas affect my mood?'. "
                "Requires How We Feel (or Apple State of Mind) + Health Auto Export State of Mind automation."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
}

# ── MCP protocol handlers ─────────────────────────────────────────────────────
def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities":    {"tools": {}},
        "serverInfo":      {"name": "life-platform", "version": "2.41.0"},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}


# ── SEC-3: MCP input validation ───────────────────────────────────────────────
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_STR_LEN = 500   # cap free-text inputs to prevent oversized payloads
_MAX_ARRAY_LEN = 100

def _validate_tool_args(tool_name: str, arguments: dict, schema: dict) -> dict:
    """Validate and sanitize tool arguments against the tool's inputSchema.
    Returns a cleaned copy of arguments; raises ValueError on hard failures."""
    if not isinstance(arguments, dict):
        raise ValueError(f"Tool '{tool_name}': arguments must be an object, got {type(arguments).__name__}")

    props    = schema.get("properties", {})
    required = schema.get("required", [])
    cleaned  = {}

    # Check required fields
    for field in required:
        if field not in arguments:
            raise ValueError(f"Tool '{tool_name}': missing required argument '{field}'")

    # Validate and coerce each provided argument
    for key, value in arguments.items():
        # Drop unknown keys — don't error, just ignore (future-proof)
        if key not in props:
            logger.warning(f"[SEC-3] Tool '{tool_name}': unknown arg '{key}' — dropped")
            continue

        expected_type = props[key].get("type")
        enum_vals     = props[key].get("enum")

        # Enum validation
        if enum_vals is not None and value not in enum_vals:
            raise ValueError(f"Tool '{tool_name}': arg '{key}' must be one of {enum_vals}, got {value!r}")

        # Type coercion / validation
        if expected_type == "string":
            if not isinstance(value, str):
                value = str(value)
            # Cap length
            if len(value) > _MAX_STR_LEN:
                logger.warning(f"[SEC-3] Tool '{tool_name}': arg '{key}' truncated {len(value)}→{_MAX_STR_LEN}")
                value = value[:_MAX_STR_LEN]
            # Date format check for date-named fields
            if ("date" in key or key.endswith("_day")) and value and not _DATE_RE.match(value):
                raise ValueError(f"Tool '{tool_name}': arg '{key}' must be YYYY-MM-DD, got {value!r}")
        elif expected_type == "number" or expected_type == "integer":
            if not isinstance(value, (int, float)):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Tool '{tool_name}': arg '{key}' must be numeric, got {value!r}")
        elif expected_type == "boolean":
            if not isinstance(value, bool):
                value = bool(value)
        elif expected_type == "array":
            if not isinstance(value, list):
                raise ValueError(f"Tool '{tool_name}': arg '{key}' must be an array, got {type(value).__name__}")
            if len(value) > _MAX_ARRAY_LEN:
                logger.warning(f"[SEC-3] Tool '{tool_name}': arg '{key}' array truncated to {_MAX_ARRAY_LEN}")
                value = value[:_MAX_ARRAY_LEN]

        cleaned[key] = value

    return cleaned


def handle_tools_call(params):
    name      = params.get("name")
    arguments = params.get("arguments", {})
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")
    # SEC-3: validate arguments against tool's inputSchema before dispatch
    input_schema = TOOLS[name]["schema"].get("inputSchema", {})
    try:
        arguments = _validate_tool_args(name, arguments, input_schema)
    except ValueError as ve:
        logger.warning(f"[SEC-3] Validation error for '{name}': {ve}")
        return {"content": [{"type": "text", "text": json.dumps(
            {"error": "invalid_arguments", "detail": str(ve)}, default=str)}]}
    logger.info(f"Calling tool '{name}' with args: {arguments}")
    result = TOOLS[name]["fn"](arguments)
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


METHOD_HANDLERS = {
    "initialize":                handle_initialize,
    "tools/list":                handle_tools_list,
    "tools/call":                handle_tools_call,
    "notifications/initialized": lambda _: None,
}


# ── Nightly cache warmer ──────────────────────────────────────────────────────
# Triggered by EventBridge at 03:00 UTC daily. Pre-computes the slowest tools
# and writes results to the DynamoDB CACHE# partition so that Claude's first
# morning query is instant rather than waiting 8-15 seconds.

# Sources excluded from warmer heavy queries — apple_health has 3000+ items
# and takes ~20s to paginate; it's rarely the focus of aggregation queries.
WARMER_CORE_SOURCES = [s for s in SOURCES if s not in ("apple_health", "hevy")]


def nightly_cache_warmer():
    """Pre-compute expensive tool results and store in DynamoDB cache.
    Excludes apple_health from aggregate queries (3000+ items, ~20s paginate).
    Lambda timeout is 300s; typical warmer runtime ~60-90s.
    Per-step timing is logged so slowdowns are easy to diagnose.
    """
    warmer_start = time.time()
    today    = datetime.utcnow().strftime("%Y-%m-%d")
    five_yrs = (datetime.utcnow() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    two_yrs  = (datetime.utcnow() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    results  = {}
    logger.info(f"[warmer] START date={today} sources={WARMER_CORE_SOURCES}")

    # 1. get_aggregated_summary — year view (5 years, core sources only)
    _t = time.time()
    try:
        logger.info("[warmer] computing aggregated_summary year (core sources)")
        source_data = parallel_query_sources(WARMER_CORE_SOURCES, five_yrs, today, lean=True)
        agg_result = {}
        for src, items in source_data.items():
            if items:
                agg_result[src] = aggregate_items(items, "year")
        data = {"period": "year", "start_date": five_yrs, "end_date": today,
                "sources": agg_result, "note": "warmer: apple_health excluded"}
        cache_key = f"aggregated_summary_year_{five_yrs}_{today}_{','.join(WARMER_CORE_SOURCES)}"
        ddb_cache_set(cache_key, data)
        mem_cache_set(cache_key, data)
        results["aggregated_summary_year"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] aggregated_summary year failed: {e}")
        results["aggregated_summary_year"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 2. get_aggregated_summary — month view (2 years, core sources only)
    _t = time.time()
    try:
        logger.info("[warmer] computing aggregated_summary month (core sources)")
        source_data = parallel_query_sources(WARMER_CORE_SOURCES, two_yrs, today, lean=True)
        agg_result = {}
        for src, items in source_data.items():
            if items:
                agg_result[src] = aggregate_items(items, "month")
        data = {"period": "month", "start_date": two_yrs, "end_date": today,
                "sources": agg_result, "note": "warmer: apple_health excluded"}
        cache_key = f"aggregated_summary_month_{two_yrs}_{today}_{','.join(WARMER_CORE_SOURCES)}"
        ddb_cache_set(cache_key, data)
        mem_cache_set(cache_key, data)
        results["aggregated_summary_month"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] aggregated_summary month failed: {e}")
        results["aggregated_summary_month"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 3. get_personal_records
    _t = time.time()
    try:
        logger.info("[warmer] computing personal_records")
        data = tool_get_personal_records({"end_date": today})
        ddb_cache_set("personal_records_all", data)
        mem_cache_set("personal_records_all", data)
        results["personal_records"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] personal_records failed: {e}")
        results["personal_records"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 4. get_seasonal_patterns (core sources only — apple_health volume)
    _t = time.time()
    try:
        logger.info("[warmer] computing seasonal_patterns (core sources)")
        data = tool_get_seasonal_patterns({"start_date": "2010-01-01", "end_date": today,
                                           "source": None})
        ddb_cache_set("seasonal_patterns_all", data)
        mem_cache_set("seasonal_patterns_all", data)
        results["seasonal_patterns"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] seasonal_patterns failed: {e}")
        results["seasonal_patterns"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 5. get_health_dashboard
    _t = time.time()
    try:
        logger.info("[warmer] computing health_dashboard")
        data = tool_get_health_dashboard({})
        ddb_cache_set("health_dashboard_today", data)
        mem_cache_set("health_dashboard_today", data)
        results["health_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] health_dashboard failed: {e}")
        results["health_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 6. get_habit_dashboard
    _t = time.time()
    try:
        logger.info("[warmer] computing habit_dashboard")
        data = tool_get_habit_dashboard({})
        ddb_cache_set("habit_dashboard_today", data)
        mem_cache_set("habit_dashboard_today", data)
        results["habit_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] habit_dashboard failed: {e}")
        results["habit_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    total_ms = int((time.time() - warmer_start) * 1000)
    errors   = [k for k, v in results.items() if not v.get("status", "").startswith("ok")]
    status   = "COMPLETE" if not errors else f"PARTIAL — {len(errors)} step(s) failed: {errors}"
    logger.info(f"[warmer] {status} total_ms={total_ms} steps={json.dumps(results)}")
    if errors:
        logger.error(f"[warmer] FAILED steps: {errors}")

    return {"warmer": status, "date": today, "total_ms": total_ms, "results": results}


# ── Helper: load CGM readings from S3 ─────────────────────────────────────────

def _load_cgm_readings(date_str):
    """
    Load 5-minute CGM readings from S3 for a given date.
    Returns list of (hour_decimal, value_mg_dl) tuples sorted by time.
    """
    try:
        y, m, d = date_str.split("-")
        key = f"raw/cgm_readings/{y}/{m}/{d}.json"
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        readings = json.loads(resp["Body"].read())
        result = []
        for r in readings:
            val = r.get("value")
            time_str = r.get("time", "")
            if val is None or not time_str:
                continue
            # Parse "2024-10-15 11:04:29 -0800" format
            try:
                parts = time_str.strip().split(" ")
                hms = parts[1].split(":")
                hour_dec = int(hms[0]) + int(hms[1]) / 60 + int(hms[2]) / 3600
                result.append((hour_dec, float(val)))
            except (IndexError, ValueError):
                continue
        return sorted(result, key=lambda x: x[0])
    except s3_client.exceptions.NoSuchKey:
        return []
    except Exception as e:
        logger.warning(f"CGM read failed for {date_str}: {e}")
        return []


# ── Tool: get_glucose_meal_response ───────────────────────────────────────────

