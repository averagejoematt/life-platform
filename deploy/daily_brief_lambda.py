"""
Daily Brief Lambda — v2.82.0 (Compute refactor: reads pre-computed metrics from daily-metrics-compute Lambda)
Fires at 10:00am PT daily (18:00 UTC via EventBridge).

v2.2 changes:
  - MacroFactor workouts integration (exercise-level detail in Training Report)
  - Smart Guidance: AI-generated from all signals (replaces static table)
  - TL;DR line: single sentence under day grade
  - Weight: weekly delta callout
  - Sleep architecture: deep % + REM % in scorecard
  - Eight Sleep field name fixes (sleep_efficiency_pct, sleep_duration_hours)
  - Nutrition Report: meal timing in AI prompt
  - 4 AI calls: BoD, Training+Nutrition, Journal Coach, TL;DR+Guidance combined

v2.77.0 extraction:
  - html_builder.py   — build_html, hrv_trend_str, _section_error_html (~1,000 lines)
  - ai_calls.py       — all 4 AI call functions + data summary builders (~380 lines)
  - output_writers.py — write_dashboard_json, write_clinical_json, write_buddy_json,
                        evaluate_rewards, get_protocol_recs, sanitize_for_demo (~700 lines)
  Lambda shrinks from 4,002 → ~1,366 lines of orchestration logic.

Sections (15):
  1.  Day Grade + TL;DR (AI one-liner)
  2.  Yesterday's Scorecard (sleep architecture detail)
  3.  Readiness Signal
  4.  Training Report (exercise-level detail from MacroFactor workouts)
  5.  Nutrition Report (meal timing in AI prompt)
  6.  Habits Deep-Dive
  7.  CGM Spotlight (UPDATED: fasting proxy, hypo flag, 7-day trend)
  8.  Gait & Mobility (NEW: walking speed, step length, asymmetry, double support)
  9.  Habit Streaks
  10. Weight Phase Tracker (weekly delta callout)
  11. Today's Guidance (AI-generated smart guidance)
  12. Journal Pulse
  13. Journal Coach
  14. Board of Directors Insight
  15. Anomaly Alert

Profile-driven: all targets read from DynamoDB PROFILE#v1. No hardcoded constants.
4 AI calls: Board of Directors, Training+Nutrition Coach, Journal Coach, TL;DR+Guidance.

v2.54.0: Board of Directors prompt dynamically built from s3://matthew-life-platform/config/board_of_directors.json
         Falls back to hardcoded _FALLBACK_BOD_PROMPT if S3 config unavailable.
"""

import json
import os
import math
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# -- Configuration from environment variables (with backwards-compatible defaults) --
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ.get("S3_BUCKET", "")
USER_ID    = os.environ.get("USER_ID", "")
RECIPIENT  = os.environ.get("EMAIL_RECIPIENT", "")
SENDER     = os.environ.get("EMAIL_SENDER", "")
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")

# BUG-11: Validate required env vars at startup with descriptive errors
_MISSING = [k for k, v in [("S3_BUCKET", S3_BUCKET), ("USER_ID", USER_ID),
                             ("EMAIL_RECIPIENT", RECIPIENT), ("EMAIL_SENDER", SENDER)] if not v]
if _MISSING:
    raise RuntimeError(f"daily-brief Lambda misconfigured — missing required env vars: {_MISSING}")

# BUG-10: Validate email format for recipient and sender
import re as _re
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
for _var, _addr in [("EMAIL_RECIPIENT", RECIPIENT), ("EMAIL_SENDER", SENDER)]:
    if not _EMAIL_RE.match(_addr):
        raise RuntimeError(f"daily-brief Lambda misconfigured — {_var}={_addr!r} is not a valid email address")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

# -- AWS clients ---------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)
s3       = boto3.client("s3", region_name=_REGION)
secrets  = boto3.client("secretsmanager", region_name=_REGION)

# BUG-08: Emit EMF metric when optional layer module fails to import.
def _emit_module_load_failure(module_name: str) -> None:
    try:
        print(json.dumps({"_aws": {"Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{"Namespace": "LifePlatform/DailyBrief",
                "Dimensions": [["Module"]],
                "Metrics": [{"Name": "ModuleLoadFailure", "Unit": "Count"}]}]},
            "Module": module_name, "ModuleLoadFailure": 1}))
    except Exception as _e:
        logger.warning("[_emit_module_load_failure] metric emit failed: %s", _e)


# Board of Directors config loader
try:
    import board_loader
    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False
    import logging as _log
    _log.getLogger().warning("[daily] board_loader not available — using fallback prompts")
    _emit_module_load_failure("board_loader")

# Insight Ledger (IC-15)
try:
    import insight_writer
    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False
    print("[WARN] insight_writer not available — insights will not be persisted")
    _emit_module_load_failure("insight_writer")

# AI-3: Output Validator — validates coaching text before delivery
try:
    from ai_output_validator import validate_daily_brief_outputs
    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False
    print("[WARN] ai_output_validator not available — AI output validation skipped")
    _emit_module_load_failure("ai_output_validator")

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("daily-brief")
except ImportError:
    import logging as _log
    logger = _log.getLogger("daily-brief")
    logger.setLevel(_log.INFO)

# -- Extracted module imports ---------------------------------------------------
import html_builder
import ai_calls
import output_writers

# ai_calls can be init'd at import time (no dependency on locally-defined functions)
ai_calls.init(
    s3_client=s3,
    bucket=S3_BUCKET,
    has_board_loader=_HAS_BOARD_LOADER,
    board_loader_module=board_loader if _HAS_BOARD_LOADER else None,
)
# output_writers.init() is called lazily from lambda_handler via _init_output_writers()
# because it depends on fetch_range / fetch_date which are defined below.

# ==============================================================================
# HELPERS
# ==============================================================================

def get_anthropic_key():
    secret = secrets.get_secret_value(SecretId=ANTHROPIC_SECRET)
    return json.loads(secret["SecretString"])["anthropic_api_key"]

def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None

def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))

def fmt_num(val):
    if val is None:
        return "—"
    return "{:,}".format(round(val))


def fetch_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        return d2f(r.get("Item"))
    except Exception:
        return None

def fetch_range(source, start, end):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": USER_PREFIX + source,
                                       ":s": "DATE#" + start, ":e": "DATE#" + end})
        return [d2f(i) for i in r.get("Items", [])]
    except Exception:
        return []

def _normalize_whoop_sleep(item):
    """Map Whoop sleep field names to common schema used by Daily Brief."""
    if not item:
        return item
    out = dict(item)
    if "sleep_quality_score" in out and "sleep_score" not in out:
        out["sleep_score"] = out["sleep_quality_score"]
    if "sleep_efficiency_percentage" in out and "sleep_efficiency_pct" not in out:
        out["sleep_efficiency_pct"] = out["sleep_efficiency_percentage"]
    dur = None
    try:
        dur = float(out.get("sleep_duration_hours", 0)) or None
    except (TypeError, ValueError):
        pass
    if dur and dur > 0:
        for src_field, pct_field in [("slow_wave_sleep_hours", "deep_pct"),
                                      ("rem_sleep_hours", "rem_pct"),
                                      ("light_sleep_hours", "light_pct")]:
            try:
                hrs = float(out.get(src_field, 0))
                if pct_field not in out:
                    out[pct_field] = round(hrs / dur * 100, 1)
            except (TypeError, ValueError):
                pass
    if "time_awake_hours" in out and "waso_hours" not in out:
        out["waso_hours"] = out["time_awake_hours"]
    if "disturbance_count" in out and "toss_and_turns" not in out:
        out["toss_and_turns"] = out["disturbance_count"]
    return out

def fetch_journal_entries(date_str):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX + "notion",
                ":prefix": "DATE#" + date_str + "#journal#"
            })
        return [d2f(i) for i in r.get("Items", [])]
    except Exception as e:
        print("[WARN] fetch_journal_entries: " + str(e))
        return []

def fetch_profile():
    try:
        r = table.get_item(Key={"pk": PROFILE_PK, "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        print("[ERROR] fetch_profile: " + str(e))
        return {}

def get_current_phase(profile, current_weight_lbs):
    phases = profile.get("weight_loss_phases", [])
    for p in phases:
        if current_weight_lbs >= p.get("end_lbs", 0):
            return p
    return phases[-1] if phases else None


# ==============================================================================
# DATA GATHERING
# ==============================================================================

def _emit_source_fetch_metrics(sources: dict) -> None:
    """OBS-06: Per-source DataPresent metric via EMF stdout. Zero-config CloudWatch."""
    ts = int(time.time() * 1000)
    for source, data in sources.items():
        try:
            print(json.dumps({"_aws": {"Timestamp": ts,
                "CloudWatchMetrics": [{"Namespace": "LifePlatform/DailyBrief",
                    "Dimensions": [["Source"]],
                    "Metrics": [{"Name": "DataPresent", "Unit": "Count"}]}]},
                "Source": source, "DataPresent": 1 if data else 0}))
        except Exception as _e:
            logger.warning("[_emit_source_fetch_metrics] metric emit failed for %s: %s", source, _e)


def gather_daily_data(profile, yesterday):
    today = datetime.now(timezone.utc).date()

    whoop       = fetch_date("whoop",        yesterday)
    sleep       = _normalize_whoop_sleep(whoop)  # Whoop is now SOT for sleep duration/staging
    apple       = fetch_date("apple_health", yesterday)
    macrofactor = fetch_date("macrofactor",  yesterday)
    strava      = fetch_date("strava",       yesterday)
    habitify    = fetch_date("habitify",     yesterday)
    garmin      = fetch_date("garmin",       yesterday)
    whoop_today = fetch_date("whoop", today.isoformat())

    # MacroFactor workouts — exercise-level detail (v2.2)
    mf_workouts = fetch_date("macrofactor_workouts", yesterday)

    journal_entries = fetch_journal_entries(yesterday)
    journal = extract_journal_signals(journal_entries)

    hrv_7d_recs  = fetch_range("whoop", (today - timedelta(days=7)).isoformat(), yesterday)
    hrv_30d_recs = fetch_range("whoop", (today - timedelta(days=30)).isoformat(), yesterday)
    hrv_7d_vals  = [float(r["hrv"]) for r in hrv_7d_recs  if "hrv" in r]
    hrv_30d_vals = [float(r["hrv"]) for r in hrv_30d_recs if "hrv" in r]

    strava_60d = fetch_range("strava", (today - timedelta(days=60)).isoformat(), yesterday)
    tsb = compute_tsb(strava_60d, today)
    strava_7d_cutoff = (today - timedelta(days=7)).isoformat()
    strava_7d = [r for r in strava_60d if r.get("sk", "").replace("DATE#", "") >= strava_7d_cutoff]

    # Weight: latest + 7-day ago for weekly delta
    # 30-day lookback so a few days without weighing doesn't null out the homepage
    withings_recent = fetch_range("withings", (today - timedelta(days=30)).isoformat(), yesterday)
    latest_weight = None
    for w in reversed(withings_recent):
        wt = safe_float(w, "weight_lbs")
        if wt:
            latest_weight = wt
            break

    withings_14d = fetch_range("withings", (today - timedelta(days=14)).isoformat(), yesterday)
    week_ago_weight = None
    target_date = (today - timedelta(days=7)).isoformat()
    for w in withings_14d:
        d = w.get("sk", "").replace("DATE#", "")
        if d <= target_date:
            wt = safe_float(w, "weight_lbs")
            if wt:
                week_ago_weight = wt

    # Avatar weight: 30-day lookback so avatar doesn't reset to frame 1 on missed weigh-ins
    avatar_weight = latest_weight
    if not avatar_weight:
        for w in reversed(withings_14d):
            wt = safe_float(w, "weight_lbs")
            if wt:
                avatar_weight = wt
                break
    if not avatar_weight:
        withings_30d = fetch_range("withings", (today - timedelta(days=30)).isoformat(), yesterday)
        for w in reversed(withings_30d):
            wt = safe_float(w, "weight_lbs")
            if wt:
                avatar_weight = wt
                break

    # 7-day Apple Health for CGM trend context
    apple_7d = fetch_range("apple_health", (today - timedelta(days=7)).isoformat(), yesterday)

    # Cumulative sleep debt (last 7 days) for smart guidance
    sleep_7d = [_normalize_whoop_sleep(i) for i in fetch_range("whoop", (today - timedelta(days=7)).isoformat(), yesterday)]
    target_hrs = profile.get("sleep_target_hours_ideal", 7.5)
    sleep_debt_hrs = 0.0
    for s in sleep_7d:
        dur = safe_float(s, "sleep_duration_hours")
        if dur is not None:
            sleep_debt_hrs += max(0, target_hrs - dur)

    anomaly = fetch_anomaly_record(yesterday)

    # Supplements — last 7 days for adherence context
    supplements_today = fetch_date("supplements", yesterday)
    supplements_7d = fetch_range("supplements", (today - timedelta(days=7)).isoformat(), yesterday)
    habitify_7d = fetch_range("habitify", (today - timedelta(days=7)).isoformat(), yesterday)

    # Todoist — task load snapshot for decision fatigue signal
    todoist_yesterday = fetch_date("todoist", yesterday)

    # Weather — yesterday + today (pre-populated by weather-data-ingestion Lambda)
    weather_yesterday = fetch_date("weather", yesterday)
    weather_today = fetch_date("weather", today.isoformat())

    # Travel — check if currently traveling (v2.40.0)
    travel_active = None
    try:
        travel_resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": USER_PREFIX + "travel", ":prefix": "TRIP#"},
        )
        for trip in travel_resp.get("Items", []):
            start = trip.get("start_date", "")
            end = trip.get("end_date") or "9999-12-31"
            if start <= yesterday <= end:
                travel_active = {
                    "destination": trip.get("destination_city", "Unknown"),
                    "country": trip.get("destination_country", ""),
                    "timezone": trip.get("destination_timezone", ""),
                    "tz_offset": trip.get("tz_offset_hours", 0),
                    "direction": trip.get("direction", ""),
                    "start_date": start,
                }
                break
    except Exception as e:
        logger.warning("trip_data_parse: %s", e)

    # Blood pressure — from apple_health record (v2.40.0)
    bp_data = None
    bp_sys = safe_float(apple, "blood_pressure_systolic")
    bp_dia = safe_float(apple, "blood_pressure_diastolic")
    if bp_sys is not None and bp_dia is not None:
        bp_data = {
            "systolic": bp_sys, "diastolic": bp_dia,
            "pulse": safe_float(apple, "blood_pressure_pulse"),
            "readings": int(apple.get("blood_pressure_readings_count", 1)) if apple.get("blood_pressure_readings_count") else 1,
        }
        # AHA classification
        if bp_sys > 180 or bp_dia > 120:
            bp_data["class"] = "Crisis"; bp_data["class_color"] = "#dc2626"
        elif bp_sys >= 140 or bp_dia >= 90:
            bp_data["class"] = "Stage 2"; bp_data["class_color"] = "#dc2626"
        elif bp_sys >= 130 or bp_dia >= 80:
            bp_data["class"] = "Stage 1"; bp_data["class_color"] = "#d97706"
        elif bp_sys >= 120:
            bp_data["class"] = "Elevated"; bp_data["class_color"] = "#d97706"
        else:
            bp_data["class"] = "Normal"; bp_data["class_color"] = "#059669"

    # IC-2: Pre-computed insight context (written by daily-insight-compute Lambda at 9:42 AM)
    computed_insights = fetch_date("computed_insights", yesterday)
    if computed_insights:
        print("[INFO] Computed insights loaded for " + yesterday)
    else:
        print("[INFO] No computed_insights for " + yesterday + " — IC-2 Lambda may not have run yet")

    # BS-09: ACWR training load (written by acwr-compute Lambda at 9:55 AM)
    computed_metrics = fetch_date("computed_metrics", yesterday)
    if computed_metrics and computed_metrics.get("acwr"):
        _acwr_zone = computed_metrics.get("zone", "?")
        _acwr_alert = computed_metrics.get("alert", False)
        print("[INFO] ACWR loaded for " + yesterday + ": " + str(round(float(computed_metrics["acwr"]), 3)) +
              " (" + _acwr_zone + ")" + (" \u26a0 ALERT" if _acwr_alert else ""))
    else:
        print("[INFO] No computed_metrics/ACWR for " + yesterday + " — acwr-compute may not have run yet")

    # OBS-06: Emit per-source data presence metrics to CloudWatch via EMF
    _emit_source_fetch_metrics({
        "whoop": whoop, "apple_health": apple, "macrofactor": macrofactor,
        "strava": strava, "garmin": garmin, "habitify": habitify,
        "withings": latest_weight, "supplements": supplements_today,
        "todoist": todoist_yesterday, "weather": weather_yesterday,
    })

    return {
        "date": yesterday,
        "whoop": whoop, "whoop_today": whoop_today, "sleep": sleep,
        "apple": apple, "macrofactor": macrofactor, "strava": strava,
        "habitify": habitify, "garmin": garmin,
        "mf_workouts": mf_workouts,
        "hrv": {"hrv_7d": avg(hrv_7d_vals), "hrv_30d": avg(hrv_30d_vals),
                "hrv_yesterday": safe_float(whoop, "hrv")},
        "tsb": tsb,
        "journal": journal, "journal_entries": journal_entries,
        "apple_7d": apple_7d,
        "anomaly": anomaly,
        "latest_weight": latest_weight, "week_ago_weight": week_ago_weight,
        "avatar_weight": avatar_weight,
        "sleep_debt_7d_hrs": round(sleep_debt_hrs, 1),
        "supplements_today": supplements_today,
        "supplements_7d": supplements_7d,
        "habitify_7d": habitify_7d,
        "weather_yesterday": weather_yesterday,
        "weather_today": weather_today,
        "travel_active": travel_active,
        "bp_data": bp_data,
        "strava_7d": strava_7d,
        "todoist": todoist_yesterday,
        "computed_insights": computed_insights,
        "computed_metrics": computed_metrics,   # BS-09: ACWR + training load alert
    }


def extract_journal_signals(entries):
    if not entries:
        return None
    mood_scores, energy_scores, stress_scores = [], [], []
    all_themes, all_emotions = [], []
    notable_quote = None
    templates_found = []
    for entry in entries:
        template = entry.get("template", "")
        templates_found.append(template)
        m = entry.get("enriched_mood")
        e = entry.get("enriched_energy")
        s = entry.get("enriched_stress")
        if m is not None: mood_scores.append(float(m))
        if e is not None: energy_scores.append(float(e))
        if s is not None: stress_scores.append(float(s))
        for t in (entry.get("enriched_themes") or []):
            all_themes.append(t)
        for em in (entry.get("enriched_emotions") or []):
            all_emotions.append(em)
        q = entry.get("enriched_notable_quote")
        if q and (template.lower() == "evening" or notable_quote is None):
            notable_quote = str(q)
        if m is None:
            for field in ("morning_mood", "day_rating"):
                val = entry.get(field)
                if val is not None:
                    mood_scores.append(float(val))
                    break
        if e is None:
            for field in ("morning_energy", "energy_eod"):
                val = entry.get(field)
                if val is not None:
                    energy_scores.append(float(val))
                    break
        if s is None:
            val = entry.get("stress_level")
            if val is not None:
                stress_scores.append(float(val))
    return {
        "mood_avg": round(sum(mood_scores)/len(mood_scores), 1) if mood_scores else None,
        "energy_avg": round(sum(energy_scores)/len(energy_scores), 1) if energy_scores else None,
        "stress_avg": round(sum(stress_scores)/len(stress_scores), 1) if stress_scores else None,
        "themes": list(dict.fromkeys(all_themes))[:4],
        "emotions": list(dict.fromkeys(all_emotions))[:5],
        "notable_quote": notable_quote,
        "templates": templates_found,
    }


def fetch_anomaly_record(date_str):
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + "anomalies", "sk": "DATE#" + date_str})
        return d2f(r.get("Item") or {})
    except Exception:
        return {}


def compute_tsb(strava_60d, today):
    kj = {}
    for r in strava_60d:
        d = str(r.get("date", ""))
        if d:
            kj[d] = sum(float(a.get("kilojoules") or 0) for a in r.get("activities", []))
    ctl = atl = 0.0
    cd = math.exp(-1/42)
    ad = math.exp(-1/7)
    for i in range(59, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        load = kj.get(day, 0)
        ctl = ctl * cd + load * (1 - cd)
        atl = atl * ad + load * (1 - ad)
    return round(ctl - atl, 1)


# ==============================================================================
# COMPONENT SCORERS (each -> 0-100, or None if no data)
# ==============================================================================

def score_sleep(data, profile):
    sleep = data.get("sleep")
    if not sleep:
        return None, {}
    sleep_score = safe_float(sleep, "sleep_score")
    efficiency = safe_float(sleep, "sleep_efficiency_pct")
    duration_hrs = safe_float(sleep, "sleep_duration_hours")
    deep_pct = safe_float(sleep, "deep_pct")
    rem_pct = safe_float(sleep, "rem_pct")
    light_pct = safe_float(sleep, "light_pct")
    target_hrs = profile.get("sleep_target_hours_ideal", 7.5)
    details = {"sleep_score": sleep_score, "efficiency": efficiency,
               "duration_hrs": duration_hrs, "target_hrs": target_hrs,
               "deep_pct": deep_pct, "rem_pct": rem_pct, "light_pct": light_pct}
    parts, weights = [], []
    if sleep_score is not None:
        parts.append(sleep_score * 0.40); weights.append(0.40)
    if efficiency is not None:
        parts.append(efficiency * 0.30); weights.append(0.30)
    if duration_hrs is not None:
        dur_score = clamp(100 - (abs(duration_hrs - target_hrs) / 2.0) * 100)
        parts.append(dur_score * 0.30); weights.append(0.30)
        details["duration_score"] = round(dur_score, 1)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details


def score_recovery(data, profile):
    recovery = safe_float(data.get("whoop"), "recovery_score")
    if recovery is None:
        return None, {}
    return clamp(round(recovery)), {"recovery_score": recovery}


def score_nutrition(data, profile):
    mf = data.get("macrofactor")
    if not mf:
        return None, {}
    cal = safe_float(mf, "total_calories_kcal")
    protein = safe_float(mf, "total_protein_g")
    fat = safe_float(mf, "total_fat_g")
    carbs = safe_float(mf, "total_carbs_g")
    cal_target = profile.get("calorie_target", 1800)
    protein_target = profile.get("protein_target_g", 190)
    protein_floor = profile.get("protein_floor_g", 170)
    cal_tolerance = profile.get("calorie_tolerance_pct", 10) / 100
    cal_penalty = profile.get("calorie_penalty_threshold_pct", 25) / 100
    details = {"calories": cal, "protein_g": protein, "fat_g": fat, "carbs_g": carbs,
               "cal_target": cal_target, "protein_target": protein_target}
    parts, weights = [], []
    if cal is not None and cal_target:
        pct_off = abs(cal - cal_target) / cal_target
        if pct_off <= cal_tolerance: cal_score = 100
        elif pct_off >= cal_penalty: cal_score = 0
        else: cal_score = 100 * (1 - (pct_off - cal_tolerance) / (cal_penalty - cal_tolerance))
        if cal > cal_target * (1 + cal_tolerance):
            cal_score = max(0, cal_score - 15)
        cal_score = clamp(round(cal_score))
        parts.append(cal_score * 0.40); weights.append(0.40)
        details["cal_score"] = cal_score
    if protein is not None:
        if protein >= protein_target: prot_score = 100
        elif protein >= protein_floor:
            prot_score = 80 + 20 * (protein - protein_floor) / (protein_target - protein_floor)
        else: prot_score = max(0, 80 * protein / protein_floor)
        prot_score = clamp(round(prot_score))
        parts.append(prot_score * 0.40); weights.append(0.40)
        details["protein_score"] = prot_score
    fat_target = profile.get("fat_target_g", 60)
    carb_target = profile.get("carb_target_g", 125)
    if fat is not None and carbs is not None:
        fat_diff = abs(fat - fat_target) / fat_target if fat_target else 0
        carb_diff = abs(carbs - carb_target) / carb_target if carb_target else 0
        macro_score = clamp(round(100 - (fat_diff + carb_diff) * 50))
        parts.append(macro_score * 0.20); weights.append(0.20)
        details["macro_score"] = macro_score
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details


def score_movement(data, profile):
    step_target = profile.get("step_target", 7000)
    details = {}
    parts, weights = [], []
    strava = data.get("strava")
    if strava:
        act_count = safe_float(strava, "activity_count") or 0
        total_time = safe_float(strava, "total_moving_time_seconds") or 0
        exercise_score = min(100, 70 + (total_time / 60) * 0.5) if act_count > 0 else 0
    else:
        exercise_score = 0
    exercise_score = clamp(round(exercise_score))
    parts.append(exercise_score * 0.50); weights.append(0.50)
    details["exercise_score"] = exercise_score
    apple = data.get("apple")
    steps = safe_float(apple, "steps") if apple else None
    if steps is not None:
        step_score = clamp(round(min(100, steps / step_target * 100)))
        parts.append(step_score * 0.50); weights.append(0.50)
        details["step_score"] = step_score
        details["steps"] = round(steps)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details


def score_habits_registry(data, profile):
    """Tier-weighted habit scoring using habit_registry.

    Tier 0 (non-negotiable): 3x weight, binary (done/not done)
    Tier 1 (high priority):  1x weight, binary
    Tier 2 (aspirational):   rolling 7-day frequency vs target_frequency

    applicable_days awareness: weekday-only habits don't penalize weekends.
    scoring_weight field allows down-weighting emerging-evidence habits.
    """
    habitify = data.get("habitify")
    if not habitify:
        return None, {}
    habits_map = habitify.get("habits", {})
    registry = profile.get("habit_registry", {})
    if not registry:
        return _score_habits_mvp_legacy(data, profile)

    date_str = data.get("date", "")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        is_weekday = dt.weekday() < 5
    except Exception:
        is_weekday = True

    tier_scores = {0: [], 1: [], 2: []}
    tier_status = {0: {}, 1: {}, 2: {}}
    vice_status = {}
    tier_weights = {0: 3.0, 1: 1.0, 2: 0.5}
    habitify_7d = data.get("habitify_7d") or []

    for habit_name, meta in registry.items():
        if meta.get("status") != "active":
            continue
        tier = meta.get("tier", 2)
        applicable = meta.get("applicable_days", "daily")
        is_vice = meta.get("vice", False)
        sw = meta.get("scoring_weight", 1.0)

        if applicable == "weekdays" and not is_weekday:
            continue
        if applicable == "post_training":
            strava = data.get("strava") or {}
            if not strava.get("activities"):
                continue

        done = habits_map.get(habit_name, 0)
        is_done = float(done) >= 1 if done is not None else False

        if is_vice:
            vice_status[habit_name] = is_done

        if tier in (0, 1):
            habit_score = 100.0 if is_done else 0.0
            tier_scores[tier].append(habit_score * sw)
            tier_status[tier][habit_name] = is_done
        else:
            target_freq = meta.get("target_frequency", 7)
            week_count = 1 if is_done else 0
            for day_rec in habitify_7d[-6:]:
                day_habits = day_rec.get("habits", {}) if isinstance(day_rec, dict) else {}
                d = day_habits.get(habit_name, 0)
                if d is not None and float(d) >= 1:
                    week_count += 1
            freq_score = min(100.0, round(week_count / max(target_freq, 1) * 100))
            tier_scores[2].append(freq_score * sw)
            tier_status[2][habit_name] = is_done

    weighted_sum = 0.0
    total_weight = 0.0
    for tier_num, scores in tier_scores.items():
        if scores:
            tier_avg = sum(scores) / len(scores)
            w = tier_weights[tier_num]
            weighted_sum += tier_avg * w
            total_weight += w

    if total_weight == 0:
        return None, {}

    composite = clamp(round(weighted_sum / total_weight))

    t0_done = sum(1 for v in tier_status[0].values() if v)
    t0_total = len(tier_status[0])
    t1_done = sum(1 for v in tier_status[1].values() if v)
    t1_total = len(tier_status[1])
    vices_held = sum(1 for v in vice_status.values() if v)
    vices_total = len(vice_status)

    details = {
        "completed": t0_done + t1_done,
        "total": t0_total + t1_total,
        "tier_status": tier_status,
        "vice_status": vice_status,
        "tier0": {"done": t0_done, "total": t0_total},
        "tier1": {"done": t1_done, "total": t1_total},
        "vices": {"held": vices_held, "total": vices_total},
        "composite_method": "tier_weighted",
    }
    return composite, details


def _score_habits_mvp_legacy(data, profile):
    """Legacy fallback if habit_registry not populated."""
    habitify = data.get("habitify")
    if not habitify:
        return None, {}
    habits_map = habitify.get("habits", {})
    mvp_list = profile.get("mvp_habits", [])
    if not mvp_list:
        return None, {}
    completed = 0
    mvp_status = {}
    for habit_name in mvp_list:
        done = habits_map.get(habit_name, 0)
        is_done = float(done) >= 1 if done is not None else False
        mvp_status[habit_name] = is_done
        if is_done:
            completed += 1
    score = clamp(round(completed / len(mvp_list) * 100))
    return score, {"completed": completed, "total": len(mvp_list), "mvp_status": mvp_status}


def score_hydration(data, profile):
    apple = data.get("apple")
    water_ml = safe_float(apple, "water_intake_ml") if apple else None
    target_ml = profile.get("water_target_ml", 2957)
    # Minimum 500ml to count as tracked.
    # HAE sync consistently delivers ~350ml artifacts when full data doesn't sync.
    if water_ml is None or water_ml < 500:
        return None, {}
    score = clamp(round(min(100, water_ml / target_ml * 100)))
    return score, {"water_ml": round(water_ml), "water_oz": round(water_ml / 29.5735, 1),
                   "target_oz": round(target_ml / 29.5735, 1)}


def score_journal(data, profile):
    entries = data.get("journal_entries", [])
    if not entries:
        return None, {"entries": 0}
    templates = set()
    for e in entries:
        t = (e.get("template") or "").lower()
        if t:
            templates.add(t)
    has_morning = "morning" in templates
    has_evening = "evening" in templates
    if has_morning and has_evening: score = 100
    elif has_morning or has_evening: score = 60
    else: score = 40
    return score, {"entries": len(entries), "templates": list(templates),
                   "has_morning": has_morning, "has_evening": has_evening}


def score_glucose(data, profile):
    apple = data.get("apple")
    if not apple:
        return None, {}
    tir = safe_float(apple, "blood_glucose_time_in_range_pct")
    avg_glucose = safe_float(apple, "blood_glucose_avg")
    std_dev = safe_float(apple, "blood_glucose_std_dev")
    readings = safe_float(apple, "blood_glucose_readings_count")
    if tir is None and avg_glucose is None:
        return None, {}
    details = {"tir_pct": tir, "avg_glucose": avg_glucose, "std_dev": std_dev, "readings": readings}
    parts, weights = [], []
    if tir is not None:
        if tir >= 95: tir_score = 100
        elif tir >= 90: tir_score = 80 + (tir - 90) * 4
        elif tir >= 70: tir_score = max(0, 80 * (tir - 70) / 20)
        else: tir_score = 0
        parts.append(tir_score * 0.50); weights.append(0.50)
        details["tir_score"] = round(tir_score, 1)
    if avg_glucose is not None:
        if avg_glucose < 95: glu_score = 100
        elif avg_glucose < 100: glu_score = 80 + (100 - avg_glucose) * 4
        elif avg_glucose < 140: glu_score = max(0, 80 * (140 - avg_glucose) / 40)
        else: glu_score = 0
        parts.append(glu_score * 0.30); weights.append(0.30)
        details["avg_score"] = round(glu_score, 1)
    if std_dev is not None:
        if std_dev < 15: var_score = 100
        elif std_dev < 20: var_score = 80 + (20 - std_dev) * 4
        elif std_dev < 40: var_score = max(0, 80 * (40 - std_dev) / 20)
        else: var_score = 0
        parts.append(var_score * 0.20); weights.append(0.20)
        details["var_score"] = round(var_score, 1)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details


def dedup_activities(activities):
    """Remove duplicate activities from multi-device Strava sync.

    When multiple devices (WHOOP, Garmin, Apple Watch) record the same workout,
    Strava stores each as a separate activity. This detects overlaps and keeps
    the richer record.

    Overlap = same sport_type AND start times within 15 minutes.
    Keep = prefer has-distance over no-distance, then longer duration.
    """
    if len(activities) <= 1:
        return activities

    from datetime import datetime as _dt

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:
            return _dt.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def richness(a):
        score = 0
        dist = float(a.get("distance_meters") or 0)
        if dist > 0:
            score += 1000
        score += float(a.get("moving_time_seconds") or 0)
        if a.get("summary_polyline"):
            score += 500
        if a.get("average_cadence") is not None:
            score += 100
        return score

    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed.sort(key=lambda x: x[2])

    remove = set()
    for j in range(len(indexed)):
        if j in remove:
            continue
        i_j, a_j, t_j = indexed[j]
        sport_j = (a_j.get("sport_type") or a_j.get("type") or "").lower()
        for k in range(j + 1, len(indexed)):
            if k in remove:
                continue
            i_k, a_k, t_k = indexed[k]
            sport_k = (a_k.get("sport_type") or a_k.get("type") or "").lower()
            if sport_j != sport_k:
                continue
            gap_min = abs((t_k - t_j).total_seconds()) / 60
            if gap_min > 15:
                break
            if richness(a_j) >= richness(a_k):
                remove.add(k)
                dev_drop = a_k.get("device_name", "?")
                dev_keep = a_j.get("device_name", "?")
            else:
                remove.add(j)
                dev_drop = a_j.get("device_name", "?")
                dev_keep = a_k.get("device_name", "?")
            print("[INFO] Dedup: " + sport_j + " overlap — kept " + dev_keep + ", dropped " + dev_drop)

    kept = [a for i, (_, a, _) in enumerate(indexed) if i not in remove]
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time


# ==============================================================================
# DAY GRADE
# ==============================================================================

COMPONENT_SCORERS = {
    "sleep_quality": score_sleep, "recovery": score_recovery,
    "nutrition": score_nutrition, "movement": score_movement,
    "habits_mvp": score_habits_registry, "hydration": score_hydration,
    "journal": score_journal, "glucose": score_glucose,
}

def letter_grade(score):
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 45: return "D"
    return "F"

def grade_colour(grade):
    if grade.startswith("A"): return "#059669"
    if grade.startswith("B"): return "#2563eb"
    if grade.startswith("C"): return "#d97706"
    return "#dc2626"

def compute_day_grade(data, profile):
    weights = profile.get("day_grade_weights", {})
    component_scores = {}
    component_details = {}
    active_components = []
    for comp_name, scorer_fn in COMPONENT_SCORERS.items():
        score, details = scorer_fn(data, profile)
        component_scores[comp_name] = score
        component_details[comp_name] = details
        weight = weights.get(comp_name, 0)
        if score is not None and weight > 0:
            active_components.append((comp_name, score, weight))
    if not active_components:
        return None, "—", component_scores, component_details
    total_weight = sum(w for _, _, w in active_components)
    total_score = clamp(round(sum(s * w for _, s, w in active_components) / total_weight))
    return total_score, letter_grade(total_score), component_scores, component_details


def store_day_grade(date_str, total_score, grade, component_scores, weights, algo_version):
    try:
        item = {"pk": USER_PREFIX + "day_grade", "sk": "DATE#" + date_str,
                "date": date_str, "total_score": Decimal(str(total_score)),
                "letter_grade": grade, "algorithm_version": algo_version,
                "weights_snapshot": json.loads(json.dumps(weights), parse_float=Decimal) if weights else {},
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "schema_version": 1}
        for comp, score in component_scores.items():
            if score is not None:
                item["component_" + comp] = Decimal(str(score))
        table.put_item(Item=item)
        print("[INFO] Day grade stored: " + date_str + " -> " + str(total_score) + " (" + grade + ")")
    except Exception as e:
        print("[WARN] Failed to store day grade: " + str(e))


def store_habit_scores(date_str, component_details, component_scores, vice_streaks, profile):
    """Persist tier-level habit scores for historical trending."""
    try:
        hd = component_details.get("habits_mvp", {})
        if not hd or hd.get("composite_method") != "tier_weighted":
            return

        t0 = hd.get("tier0", {})
        t1 = hd.get("tier1", {})
        vices = hd.get("vices", {})
        tier_status = hd.get("tier_status", {})
        missed_t0 = [name for name, done in tier_status.get(0, {}).items() if not done]

        registry = profile.get("habit_registry", {})
        all_status = {}
        for tier_habits in tier_status.values():
            all_status.update(tier_habits)

        synergy_groups = {}
        for h_name, meta in registry.items():
            sg = meta.get("synergy_group")
            if not sg or meta.get("status") != "active":
                continue
            synergy_groups.setdefault(sg, {"done": 0, "total": 0})
            synergy_groups[sg]["total"] += 1
            if all_status.get(h_name, False):
                synergy_groups[sg]["done"] += 1

        sg_pcts = {}
        for sg, counts in synergy_groups.items():
            if counts["total"] > 0:
                sg_pcts[sg] = round(counts["done"] / counts["total"], 3)

        item = {
            "pk": USER_PREFIX + "habit_scores",
            "sk": "DATE#" + date_str,
            "date": date_str,
            "scoring_method": "tier_weighted_v1",
            "composite_score": Decimal(str(component_scores.get("habits_mvp", 0))) if component_scores.get("habits_mvp") is not None else None,
            "tier0_done": t0.get("done", 0),
            "tier0_total": t0.get("total", 0),
            "tier0_pct": Decimal(str(round(t0["done"] / t0["total"], 3))) if t0.get("total") else None,
            "tier1_done": t1.get("done", 0),
            "tier1_total": t1.get("total", 0),
            "tier1_pct": Decimal(str(round(t1["done"] / t1["total"], 3))) if t1.get("total") else None,
            "vices_held": vices.get("held", 0),
            "vices_total": vices.get("total", 0),
            "missed_tier0": missed_t0 if missed_t0 else None,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        if vice_streaks:
            item["vice_streaks"] = json.loads(json.dumps(vice_streaks), parse_float=Decimal)
        if sg_pcts:
            item["synergy_groups"] = json.loads(json.dumps(sg_pcts), parse_float=Decimal)
        item = {k: v for k, v in item.items() if v is not None}
        table.put_item(Item=item)
        print("[INFO] Habit scores stored: " + date_str + " T0=" + str(t0.get("done", 0)) + "/" + str(t0.get("total", 0)))
    except Exception as e:
        print("[WARN] Failed to store habit scores: " + str(e))


# ==============================================================================
# HABIT STREAKS
# ==============================================================================

def compute_habit_streaks(profile, yesterday_str):
    """Compute streaks: Tier 0 streak, Tier 0+1 streak, and per-vice streaks."""
    registry = profile.get("habit_registry", {})
    mvp_list = profile.get("mvp_habits", [])

    tier0_habits = []
    tier01_habits = []
    vice_habits = []
    for name, meta in registry.items():
        if meta.get("status") != "active":
            continue
        tier = meta.get("tier", 2)
        if tier == 0:
            tier0_habits.append(name)
            tier01_habits.append(name)
        elif tier == 1:
            tier01_habits.append(name)
        if meta.get("vice", False):
            vice_habits.append(name)

    if not tier0_habits:
        tier0_habits = mvp_list
        tier01_habits = mvp_list

    tier0_streak = 0
    tier01_streak = 0
    t0_broken = False
    t01_broken = False
    vice_streaks = {v: 0 for v in vice_habits}
    vice_broken = {v: False for v in vice_habits}

    for i in range(0, 90):
        dt = datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=i)
        date_str = dt.strftime("%Y-%m-%d")
        is_weekday = dt.weekday() < 5
        rec = fetch_date("habitify", date_str)
        if not rec:
            break
        habits_map = rec.get("habits", {})

        if not t0_broken:
            all_t0 = True
            for h in tier0_habits:
                meta = registry.get(h, {})
                applicable = meta.get("applicable_days", "daily")
                if applicable == "weekdays" and not is_weekday:
                    continue
                done = habits_map.get(h, 0)
                if not (done is not None and float(done) >= 1):
                    all_t0 = False
                    break
            if all_t0:
                tier0_streak += 1
            else:
                t0_broken = True

        if not t01_broken:
            all_t01 = True
            for h in tier01_habits:
                meta = registry.get(h, {})
                applicable = meta.get("applicable_days", "daily")
                if applicable == "weekdays" and not is_weekday:
                    continue
                if applicable == "post_training":
                    continue
                done = habits_map.get(h, 0)
                if not (done is not None and float(done) >= 1):
                    all_t01 = False
                    break
            if all_t01:
                tier01_streak += 1
            else:
                t01_broken = True

        for v in vice_habits:
            if not vice_broken[v]:
                done = habits_map.get(v, 0)
                if done is not None and float(done) >= 1:
                    vice_streaks[v] += 1
                else:
                    vice_broken[v] = True

        if t0_broken and t01_broken and all(vice_broken.values()):
            break

    return {
        "tier0_streak": tier0_streak,
        "tier01_streak": tier01_streak,
        "vice_streaks": vice_streaks,
    }


# ==============================================================================
# READINESS
# ==============================================================================

def compute_readiness(data):
    components = []
    whoop_today = data.get("whoop_today")
    whoop_yest = data.get("whoop")
    recovery = safe_float(whoop_today, "recovery_score") or safe_float(whoop_yest, "recovery_score")
    if recovery is not None:
        components.append(("recovery", float(recovery), 0.40))
    sleep_score = safe_float(data.get("sleep"), "sleep_score")
    if sleep_score is not None:
        components.append(("sleep", float(sleep_score), 0.30))
    hrv_7d = data["hrv"].get("hrv_7d")
    hrv_30d = data["hrv"].get("hrv_30d")
    if hrv_7d and hrv_30d and hrv_30d > 0:
        hrv_score = clamp(round((hrv_7d / hrv_30d - 0.75) * 200))
        components.append(("hrv_trend", hrv_score, 0.20))
    tsb = data.get("tsb")
    if tsb is not None:
        components.append(("tsb", clamp(round(60 + tsb * 2)), 0.10))
    if not components:
        return None, "gray"
    tw = sum(w for _, _, w in components)
    score = round(sum(v * w for _, v, w in components) / tw)
    if score >= 80: return score, "green"
    if score >= 60: return score, "yellow"
    return score, "red"


# ==============================================================================
# HANDLER
# ==============================================================================

def _regrade_handler(dates, profile):
    """Recompute and store day grades for a list of dates (no email)."""
    results = []
    for date_str in dates:
        try:
            data = gather_daily_data(profile, date_str)
            score, grade, comp_scores, comp_details = compute_day_grade(data, profile)
            store_day_grade(date_str, score, grade, comp_scores,
                            profile.get("day_grade_weights", {}),
                            profile.get("day_grade_algorithm_version", "1.1"))
            hyd = comp_scores.get("hydration", "—")
            print(f"[REGRADE] {date_str}: {score} ({grade}) hydration={hyd}")
            results.append({"date": date_str, "score": score, "grade": grade,
                            "hydration": hyd, "components": comp_scores})
        except Exception as e:
            print(f"[REGRADE] {date_str} FAILED: {e}")
            results.append({"date": date_str, "error": str(e)})
    return {"statusCode": 200, "regraded": len(results), "results": results}


def _init_output_writers():
    """Late-bind output_writers dependencies.

    fetch_range / fetch_date / _normalize_whoop_sleep are defined at module level
    above, but output_writers.init() must be called after they exist.
    Called once at the top of lambda_handler.
    """
    output_writers.init(
        s3_client=s3,
        table_client=table,
        bucket=S3_BUCKET,
        user_id=USER_ID,
        user_prefix=USER_PREFIX,
        fetch_range_fn=fetch_range,
        fetch_date_fn=fetch_date,
        normalize_whoop_fn=_normalize_whoop_sleep,
    )


def lambda_handler(event, context):
    _init_output_writers()  # late-bind; safe to call multiple times (idempotent)

    # Regrade mode: recompute day grades without sending email
    regrade_dates = event.get("regrade_dates")
    if regrade_dates:
        print(f"[INFO] Regrade mode: {len(regrade_dates)} dates")
        profile = fetch_profile()
        if not profile:
            return {"statusCode": 500, "body": "No profile found"}
        return _regrade_handler(regrade_dates, profile)

    demo_mode = event.get("demo_mode", False)
    print("[INFO] Daily Brief v2.82.0 starting..." + (" [DEMO MODE]" if demo_mode else ""))
    profile = fetch_profile()
    if not profile:
        print("[ERROR] No profile found")
        return {"statusCode": 500, "body": "No profile found"}

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    # OBS-1: Set correlation_id so all structured logs tie to this execution date
    try:
        logger.set_date(yesterday)
    except Exception as e:
        print(f"[WARN] logger.set_date failed (correlation_id missing for this execution): {e}")

    data = gather_daily_data(profile, yesterday)
    print("[INFO] Date: " + yesterday + " | sources: " +
          ", ".join(k for k in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava", "mf_workouts"] if data.get(k)))

    # ── Sick day check ─────────────────────────────────────────────────────
    # If today's subject date was a sick/rest day, send a brief recovery
    # summary instead of the full brief. Skip scoring, habits, and coaching.
    try:
        from sick_day_checker import check_sick_day as _check_sick_brief
        _sick_brief_rec = _check_sick_brief(table, USER_ID, yesterday)
    except ImportError:
        _sick_brief_rec = None

    if _sick_brief_rec:
        _sick_brief_reason = _sick_brief_rec.get("reason") or "sick day"
        print(f"[INFO] Sick day flagged for {yesterday} ({_sick_brief_reason}) — sending recovery brief")

        _sb_whoop      = fetch_date("whoop", yesterday)
        _sb_sleep_hrs  = safe_float(_sb_whoop, "sleep_duration_hours")
        _sb_recovery   = safe_float(_sb_whoop, "recovery_score")
        _sb_hrv        = safe_float(_sb_whoop, "hrv")

        _sb_sleep_line    = f"{_sb_sleep_hrs:.1f} hrs" if _sb_sleep_hrs else "—"
        _sb_recovery_line = f"{int(_sb_recovery)}%" if _sb_recovery else "—"
        _sb_hrv_line      = f"{int(_sb_hrv)} ms"   if _sb_hrv      else "—"

        try:
            _today_short = today.strftime("%a %b %-d")
        except Exception:
            _today_short = today.isoformat()

        _sb_reason_display = _sick_brief_reason.title()
        _sb_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:560px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:#1a1a2e;padding:20px 24px 16px;">
      <p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Daily Brief — Recovery Day</p>
      <h1 style="color:#fff;font-size:17px;font-weight:700;margin:0;">{_today_short}</h1>
    </div>
    <div style="background:#7c3aed;padding:14px 24px;">
      <p style="color:#fff;font-size:14px;font-weight:700;margin:0;">🤒 Rest &amp; Recovery — {_sb_reason_display}</p>
      <p style="color:#e9d5ff;font-size:12px;margin:4px 0 0;">No grades, no scores, no coaching today. Just recover.</p>
    </div>
    <div style="padding:20px 24px 8px;">
      <p style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 12px;">What Your Body Is Doing</p>
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:8px 0;font-size:13px;color:#6b7280;">Sleep last night</td>
          <td style="padding:8px 0;font-size:14px;font-weight:600;color:#1a1a2e;text-align:right;">{_sb_sleep_line}</td>
        </tr>
        <tr style="border-top:1px solid #f3f4f6;">
          <td style="padding:8px 0;font-size:13px;color:#6b7280;">Recovery score</td>
          <td style="padding:8px 0;font-size:14px;font-weight:600;color:#1a1a2e;text-align:right;">{_sb_recovery_line}</td>
        </tr>
        <tr style="border-top:1px solid #f3f4f6;">
          <td style="padding:8px 0;font-size:13px;color:#6b7280;">HRV</td>
          <td style="padding:8px 0;font-size:14px;font-weight:600;color:#1a1a2e;text-align:right;">{_sb_hrv_line}</td>
        </tr>
      </table>
    </div>
    <div style="padding:4px 24px 20px;">
      <div style="background:#f8f8fc;border-radius:8px;padding:14px 16px;border-left:3px solid #7c3aed;">
        <p style="font-size:14px;color:#1a1a2e;line-height:1.65;margin:0;">
          <strong>Today's only job:</strong> rest, hydrate, and let your immune system do its work.
          Habits, calories, and streaks are frozen — no progress lost for being sick.
          Your character sheet is paused. See you when you're back. 💜
        </p>
      </div>
    </div>
    <div style="background:#f8f8fc;padding:12px 24px;border-top:1px solid #e8e8f0;">
      <p style="color:#9ca3af;font-size:10px;margin:0;text-align:center;">Life Platform — Recovery Day Brief | {_sick_brief_reason}</p>
      <p style="color:#b0b0b0;font-size:8px;margin:4px 0 0;text-align:center;">&#9874;&#65039; Personal health tracking only &mdash; not medical advice.</p>
    </div>
  </div>
</body>
</html>"""

        _sb_subject = f"Recovery Day | {_today_short} | 🤒 Rest up — no scores today"
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={"Simple": {
                "Subject": {"Data": _sb_subject, "Charset": "UTF-8"},
                "Body":    {"Html": {"Data": _sb_html, "Charset": "UTF-8"}},
            }},
        )
        print(f"[INFO] Recovery brief sent: {_sb_subject}")

        try:
            output_writers.write_buddy_json(
                {"date": yesterday, "whoop": _sb_whoop, "sick_day": True,
                 "sick_day_reason": _sick_brief_reason},
                profile, yesterday, character_sheet=None,
            )
        except Exception as _sbe:
            print(f"[WARN] write_buddy_json (sick) failed: {_sbe}")

        # D1-FIX: Write public_stats.json even on sick days so the website
        # doesn't go stale during multi-day sick periods. Uses gather_daily_data
        # which already ran above with a 30-day Withings lookback for weight.
        try:
            from site_writer import write_public_stats as _sw_write
            _sw_wt       = data.get("latest_weight")
            _sw_hrv      = data["hrv"]
            _sw_whoop_v  = data.get("whoop") or data.get("whoop_today") or {}
            _sw_rec      = safe_float(_sw_whoop_v, "recovery_score") or 0
            _sw_rec_st   = "green" if _sw_rec >= 67 else ("yellow" if _sw_rec >= 34 else "red")
            _sw_start_wt = float(profile.get("journey_start_weight_lbs", 302))
            _sw_goal_wt  = float(profile.get("goal_weight_lbs", 185))
            _sw_lost     = round(_sw_start_wt - _sw_wt, 1) if _sw_wt else 0
            _sw_remain   = round(_sw_wt - _sw_goal_wt, 1)  if _sw_wt else 0
            _sw_prog     = round(_sw_lost / (_sw_start_wt - _sw_goal_wt) * 100, 1) if _sw_wt and _sw_start_wt != _sw_goal_wt else 0
            try:
                from datetime import date as _d
                _sw_days_in = max(0, (_d.today() - _d.fromisoformat(profile.get("journey_start_date", "2026-02-09"))).days)
            except Exception:
                _sw_days_in = 0
            _sw_wk_ago = data.get("week_ago_weight")
            _sw_write(
                s3_client=s3,
                vitals={
                    "weight_lbs":      round(_sw_wt, 1) if _sw_wt else None,
                    "weight_delta_30d": round(_sw_wt - float(_sw_wk_ago), 1) if _sw_wk_ago and _sw_wt else None,
                    "hrv_ms":          round(float(_sw_hrv.get("hrv_yesterday") or _sw_hrv.get("hrv_7d") or 0), 1) or None,
                    "hrv_trend":       html_builder.hrv_trend_str(_sw_hrv.get("hrv_7d"), _sw_hrv.get("hrv_30d")),
                    "rhr_bpm":         safe_float(_sw_whoop_v, "resting_heart_rate"),
                    "rhr_trend":       "improving",
                    "recovery_pct":    round(_sw_rec, 0) if _sw_rec else None,
                    "recovery_status": _sw_rec_st,
                    "sleep_hours":     safe_float(data.get("sleep"), "sleep_duration_hours"),
                },
                journey={
                    "start_weight_lbs":   _sw_start_wt,
                    "goal_weight_lbs":    _sw_goal_wt,
                    "current_weight_lbs": _sw_wt,
                    "lost_lbs":           _sw_lost if _sw_wt else None,
                    "remaining_lbs":      _sw_remain if _sw_wt else None,
                    "progress_pct":       _sw_prog if _sw_wt else None,
                    "weekly_rate_lbs":    round(_sw_wt - float(_sw_wk_ago), 2) if _sw_wk_ago and _sw_wt else None,
                    "projected_goal_date": profile.get("goal_date", "2026-07-31"),
                    "started_date":       profile.get("journey_start_date", "2026-02-09"),
                    "current_phase":      (get_current_phase(profile, _sw_wt) or {}).get("name", "Chisel") if _sw_wt else None,
                    "days_in":            _sw_days_in,
                },
                training={
                    "ctl_fitness": 6.0, "atl_fatigue": 6.5, "tsb_form": 0.0,
                    "acwr": 1.1, "form_status": "neutral", "injury_risk": "low",
                    "total_miles_30d": 0, "activity_count_30d": 0,
                    "zone2_this_week_min": 0,
                    "zone2_target_min": int(profile.get("zone2_weekly_target_min") or profile.get("zone2_target_min_weekly") or 150),
                },
                platform={
                    "mcp_tools":         profile.get("platform_meta", {}).get("mcp_tools"),
                    "data_sources":      profile.get("platform_meta", {}).get("data_sources"),
                    "lambdas":           profile.get("platform_meta", {}).get("lambdas"),
                    "last_review_grade": profile.get("platform_meta", {}).get("last_review_grade"),
                    "tier0_streak":      0,
                    "days_in":           _sw_days_in,
                },
            )
            print(f"[INFO] D1-FIX: public_stats.json updated on sick day (weight={_sw_wt})")
        except Exception as _sw_sick_e:
            print(f"[WARN] D1-FIX: site_writer failed on sick day (non-fatal): {_sw_sick_e}")

        return {"statusCode": 200, "body": f"Recovery brief sent for {yesterday}"}

    # Deduplicate multi-device Strava activities
    strava = data.get("strava")
    if strava and strava.get("activities"):
        orig_count = len(strava["activities"])
        strava["activities"] = dedup_activities(strava["activities"])
        deduped_count = len(strava["activities"])
        if deduped_count < orig_count:
            strava["activity_count"] = deduped_count
            strava["total_moving_time_seconds"] = sum(
                float(a.get("moving_time_seconds") or 0) for a in strava["activities"])
            print("[INFO] Dedup: " + str(orig_count) + " → " + str(deduped_count) + " activities")

    # Try to read pre-computed metrics from daily-metrics-compute Lambda (9:40 AM PT).
    # If the record exists, we skip all inline scoring and stores — they already happened.
    # Fallback to inline computation if record is missing (Lambda not yet deployed, backfill, etc.).
    # Risk-7: emit CloudWatch metric when compute pipeline is stale/missing so alarm can fire.
    _cloudwatch = boto3.client("cloudwatch", region_name=_REGION)
    _computed = None
    _compute_stale = False   # REL-1: flag stale/missing compute for email banner
    _compute_age_msg = ""
    try:
        _computed = fetch_date("computed_metrics", yesterday)
        if _computed:
            # REL-1: Check computed_at timestamp — warn if >4 hours old
            _computed_at_str = _computed.get("computed_at", "")
            if _computed_at_str:
                try:
                    _computed_at = datetime.fromisoformat(_computed_at_str.replace("Z", "+00:00"))
                    _age_hours = (datetime.now(timezone.utc) - _computed_at).total_seconds() / 3600
                    if _age_hours > 4:
                        _compute_stale = True
                        _compute_age_msg = f"{_age_hours:.1f}h ago"
                        print(f"[WARN] REL-1: computed_metrics is stale ({_compute_age_msg}) — metrics may be estimated")
                    else:
                        print(f"[INFO] Using pre-computed metrics for {yesterday} (age: {_age_hours:.1f}h)")
                except Exception as _ts_e:
                    print("[WARN] REL-1: could not parse computed_at: " + str(_ts_e))
            else:
                print("[INFO] Using pre-computed metrics for " + yesterday)
        else:
            _compute_stale = True
            _compute_age_msg = "not available"
            print("[WARN] No pre-computed metrics for " + yesterday + " — computing inline (fallback)")
    except Exception as _e:
        _compute_stale = True
        _compute_age_msg = "fetch error"
        print("[WARN] Could not fetch computed_metrics: " + str(_e))

    # Risk-7: emit CloudWatch metric for compute pipeline staleness monitoring.
    # Alarm: LifePlatformComputeStaleness >= 1 for 1 datapoint within 1 day → alert.
    try:
        _cloudwatch.put_metric_data(
            Namespace="LifePlatform",
            MetricData=[{
                "MetricName": "ComputePipelineStaleness",
                "Value": 1.0 if _compute_stale else 0.0,
                "Unit": "Count",
                "Dimensions": [{"Name": "Source", "Value": "computed_metrics"}],
            }]
        )
    except Exception as _cw_e:
        print("[WARN] Risk-7: failed to emit compute staleness metric: " + str(_cw_e))

    if _computed:
        # Read pre-computed values — daily-metrics-compute already stored day_grade + habit_scores
        _cm_score = _computed.get("day_grade_score")
        day_grade_score = int(float(_cm_score)) if _cm_score is not None else None
        grade = _computed.get("day_grade_letter", "—")
        component_scores  = {k: int(float(v)) if v is not None else None
                             for k, v in _computed.get("component_scores", {}).items()}
        component_details = _computed.get("component_details", {})
        # Overwrite data dict with pre-computed derived values for HTML rendering
        if _computed.get("tsb")              is not None: data["tsb"]              = float(_computed["tsb"])
        if _computed.get("hrv_7d")           is not None: data["hrv"]["hrv_7d"]    = float(_computed["hrv_7d"])
        if _computed.get("hrv_30d")          is not None: data["hrv"]["hrv_30d"]   = float(_computed["hrv_30d"])
        if _computed.get("sleep_debt_7d_hrs") is not None: data["sleep_debt_7d_hrs"] = float(_computed["sleep_debt_7d_hrs"])
        if _computed.get("latest_weight"):   data["latest_weight"]   = float(_computed["latest_weight"])
        if _computed.get("week_ago_weight"): data["week_ago_weight"] = float(_computed["week_ago_weight"])
        if _computed.get("avatar_weight"):   data["avatar_weight"]   = float(_computed["avatar_weight"])
        print("[INFO] Day Grade (pre-computed): " + str(day_grade_score) + " (" + grade + ")")
    else:
        # Fallback: compute inline and store (pre-computed Lambda not yet run)
        try:
            day_grade_score, grade, component_scores, component_details = compute_day_grade(data, profile)
            print("[INFO] Day Grade (inline): " + str(day_grade_score) + " (" + grade + ")")
        except Exception as e:
            print("[WARN] compute_day_grade failed, using defaults: " + str(e))
            day_grade_score, grade, component_scores, component_details = None, "—", {}, {}

        if day_grade_score is not None and not demo_mode:
            try:
                store_day_grade(yesterday, day_grade_score, grade, component_scores,
                                profile.get("day_grade_weights", {}),
                                profile.get("day_grade_algorithm_version", "1.1"))
            except Exception as e:
                print("[WARN] store_day_grade failed: " + str(e))

    # Fetch pre-computed adaptive mode (computed by adaptive-mode-compute Lambda at 9:36 AM)
    brief_mode = "standard"
    engagement_score = None
    try:
        adaptive_rec = fetch_date("adaptive_mode", yesterday)
        if adaptive_rec:
            brief_mode = adaptive_rec.get("brief_mode", "standard")
            engagement_score = adaptive_rec.get("engagement_score")
            print("[INFO] Adaptive mode: " + brief_mode + " (score=" + str(engagement_score) + ")")
        else:
            print("[INFO] No adaptive mode record for " + yesterday + " — using standard")
    except Exception as _am_e:
        print("[WARN] adaptive mode fetch failed: " + str(_am_e))

    # Fetch pre-computed character sheet (computed by character-sheet-compute Lambda at 9:35 AM)
    character_sheet = None
    try:
        character_sheet = fetch_date("character_sheet", yesterday)
        if character_sheet:
            cs_level = character_sheet.get("character_level", "?")
            cs_tier = character_sheet.get("character_tier", "?")
            cs_events = len(character_sheet.get("level_events", []))
            print("[INFO] Character Sheet: Level " + str(cs_level) + " (" + str(cs_tier) + ") — " + str(cs_events) + " events")
        else:
            print("[WARN] No character sheet record for " + yesterday + " — section will be skipped")
    except Exception as e:
        print("[WARN] character_sheet fetch failed: " + str(e))

    if _computed:
        _cm_r = _computed.get("readiness_score")
        readiness_score  = int(float(_cm_r)) if _cm_r is not None else None
        readiness_colour = _computed.get("readiness_colour", "gray")
    else:
        try:
            readiness_score, readiness_colour = compute_readiness(data)
        except Exception as e:
            print("[WARN] compute_readiness failed: " + str(e))
            readiness_score, readiness_colour = None, "gray"

    streak_data = None  # FIX: always initialise so write_public_stats_json ref is safe
    if _computed:
        mvp_streak   = int(float(_computed.get("tier0_streak",  0)))
        full_streak  = int(float(_computed.get("tier01_streak", 0)))
        vice_streaks = {k: int(float(v)) for k, v in _computed.get("vice_streaks", {}).items()}
    else:
        try:
            streak_data  = compute_habit_streaks(profile, yesterday)
            mvp_streak   = streak_data.get("tier0_streak",  0)
            full_streak  = streak_data.get("tier01_streak", 0)
            vice_streaks = streak_data.get("vice_streaks",  {})
        except Exception as e:
            print("[WARN] compute_habit_streaks failed: " + str(e))
            mvp_streak, full_streak, vice_streaks = 0, 0, {}

        if not demo_mode:
            try:
                store_habit_scores(yesterday, component_details, component_scores, vice_streaks, profile)
            except Exception as e:
                print("[WARN] store_habit_scores failed: " + str(e))

    # AI calls (all optional — brief works without them)
    api_key = None
    try:
        api_key = get_anthropic_key()
    except Exception as e:
        print("[WARN] Could not get API key: " + str(e))

    bod_insight = ""
    training_nutrition = {}
    journal_coach_text = ""
    tldr_guidance = {}

    if api_key:
        try:
            bod_insight = ai_calls.call_board_of_directors(
                data, profile, day_grade_score, grade, component_scores, api_key,
                character_sheet=character_sheet, brief_mode=brief_mode)
            print("[INFO] BoD: " + bod_insight[:80])
        except Exception as e:
            print("[WARN] BoD failed: " + str(e))

        try:
            training_nutrition = ai_calls.call_training_nutrition_coach(data, profile, api_key)
            print("[INFO] Training/Nutrition coach returned")
        except Exception as e:
            print("[WARN] Training/Nutrition coach failed: " + str(e))

        if data.get("journal_entries"):
            try:
                journal_coach_text = ai_calls.call_journal_coach(data, profile, api_key)
                print("[INFO] Journal coach: " + (journal_coach_text[:80] if journal_coach_text else "empty"))
            except Exception as e:
                print("[WARN] Journal coach failed: " + str(e))

        try:
            tldr_guidance = ai_calls.call_tldr_and_guidance(
                data, profile, day_grade_score, grade,
                component_scores, component_details,
                readiness_score, readiness_colour, api_key)
            print("[INFO] TL;DR+Guidance: " + str(tldr_guidance.get("tldr", ""))[:80])
        except Exception as e:
            print("[WARN] TL;DR+Guidance failed: " + str(e))

    # AI-3: Validate all AI outputs before delivery
    if api_key and _HAS_AI_VALIDATOR:
        try:
            _health_ctx = {
                "recovery_score": (data.get("whoop") or {}).get("recovery_score"),
                "tsb": data.get("tsb"),
            }
            _validated = validate_daily_brief_outputs(
                bod_insight=bod_insight,
                training_nutrition=training_nutrition,
                journal_coach_text=journal_coach_text,
                tldr_guidance=tldr_guidance,
                health_context=_health_ctx,
            )
            bod_insight        = _validated["bod_insight"]
            training_nutrition = _validated["training_nutrition"]
            journal_coach_text = _validated["journal_coach_text"]
            tldr_guidance      = _validated["tldr_guidance"]
            _v_warnings        = _validated.get("validation_warnings", [])
            if _v_warnings:
                print(f"[AI-3] {len(_v_warnings)} validation warning(s): {_v_warnings[:5]}")
            else:
                print("[AI-3] All AI outputs passed validation")
        except Exception as _v_e:
            print(f"[WARN] AI-3 validation failed (non-fatal): {_v_e}")

    # Pre-compute rewards + protocol recs (passed to html_builder as params)
    triggered_rewards = []
    protocol_recs = []
    if character_sheet:
        try:
            triggered_rewards = output_writers.evaluate_rewards(character_sheet)
        except Exception as _e:
            print("[WARN] evaluate_rewards failed: " + str(_e))
        try:
            protocol_recs = output_writers.get_protocol_recs(character_sheet)
        except Exception as _e:
            print("[WARN] get_protocol_recs failed: " + str(_e))

    # ── S2-T1-10: Weekly Habit Review (Sunday only) ──────────────────────────────
    _weekly_habit_review = None
    try:
        import calendar
        _is_sunday = (datetime.now(timezone.utc).weekday() == 6)  # 6 = Sunday
        if _is_sunday:
            # Fetch 7-day habit_scores for the review
            _whr_habit_7d = fetch_range(
                "habit_scores",
                (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat(),
                yesterday,
            )
            if _whr_habit_7d:
                from html_builder import _compute_weekly_habit_review
                _weekly_habit_review = _compute_weekly_habit_review(_whr_habit_7d, profile)
                print("[INFO] S2-T1-10: Weekly Habit Review computed for Sunday brief")
            else:
                print("[WARN] S2-T1-10: No habit_scores data for weekly review")
    except Exception as _whr_err:
        print("[WARN] S2-T1-10: Weekly habit review failed (non-fatal): " + str(_whr_err))

    try:
        html = html_builder.build_html(
            data, profile, day_grade_score, grade, component_scores, component_details,
            readiness_score, readiness_colour, tldr_guidance, bod_insight,
            training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks,
            character_sheet=character_sheet, brief_mode=brief_mode,
            engagement_score=engagement_score,
            triggered_rewards=triggered_rewards, protocol_recs=protocol_recs,
            compute_stale=_compute_stale, compute_age_msg=_compute_age_msg,
            weekly_habit_review=_weekly_habit_review)
    except Exception as e:
        print("[ERROR] build_html crashed, sending minimal brief: " + str(e))
        html = ('<!DOCTYPE html><html><body style="font-family:sans-serif;padding:20px;">'
                '<h2>⚠ Daily Brief — Partial Failure</h2>'
                '<p>The HTML builder crashed: <code>' + str(e) + '</code></p>'
                '<p>Day Grade: ' + str(day_grade_score) + ' (' + grade + ')</p>'
                '<p>Readiness: ' + str(readiness_score) + ' (' + readiness_colour + ')</p>'
                '<p>Check CloudWatch logs for details.</p>'
                '</body></html>')

    grade_str = str(day_grade_score) + " (" + grade + ")" if day_grade_score is not None else "—"
    r_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴", "gray": "⚪"}.get(readiness_colour, "⚪")
    try:
        today_short = today.strftime("%a %b %-d")
    except Exception:
        today_short = today.isoformat()
    subject = "Morning Brief | " + today_short + " | Grade: " + grade_str + " | " + r_emoji

    if demo_mode:
        html = output_writers.sanitize_for_demo(html, data, profile)
        prefix = (profile.get("demo_mode_rules") or {}).get("subject_prefix", "[DEMO]")
        subject = prefix + " " + subject
        print("[INFO] Demo mode: sanitization applied")

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    print("[INFO] Sent: " + subject)

    if not demo_mode:
        output_writers.write_dashboard_json(
            data, profile, day_grade_score, grade, component_scores,
            readiness_score, readiness_colour, tldr_guidance, yesterday,
            component_details=component_details, character_sheet=character_sheet)
        output_writers.write_clinical_json(data, profile, yesterday)
        output_writers.write_buddy_json(data, profile, yesterday, character_sheet=character_sheet)
        # BS-02: hero stats for averagejoematt.com homepage (Jordan: delta, not absolute)
        output_writers.write_public_stats_json(data, profile, streak_data=streak_data)

        # IC-15: Insight Ledger — persist AI-generated insights for compounding
        if _HAS_INSIGHT_WRITER:
            try:
                insights_list = insight_writer.extract_daily_brief_insights(
                    bod_insight=bod_insight,
                    tldr_guidance=tldr_guidance,
                    training_nutrition=training_nutrition,
                    journal_coach_text=journal_coach_text,
                    date=yesterday.isoformat(),
                    component_scores=component_scores,
                )
                written = insight_writer.write_insights_batch(insights_list)
                print(f"[INFO] IC-15: {written}/{len(insights_list)} insights persisted")
            except Exception as e:
                print(f"[WARN] IC-15 insight write failed (non-fatal): {e}")

    # site_writer: write public_stats.json to S3 for averagejoematt.com
    # Non-fatal — failure here never breaks the Daily Brief
    if not demo_mode:
        try:
            from site_writer import write_public_stats

            # Build vitals from data already gathered above
            _w = data.get("whoop") or data.get("whoop_today") or {}
            _wt = data.get("withings") or {}
            _hrv = data["hrv"]
            _rec = safe_float(_w, "recovery_score") or 0
            _rec_status = "green" if _rec >= 67 else ("yellow" if _rec >= 34 else "red")

            # Journey calc from profile
            _start_wt = float(profile.get("journey_start_weight_lbs", 302))
            _goal_wt  = float(profile.get("goal_weight_lbs", 185))
            # Task 1: keep None as None — don't coerce to 0.0 (0.0 is falsy, breaks null checks)
            _curr_wt  = data.get("latest_weight")  # float or None
            _lost     = round(_start_wt - _curr_wt, 1) if _curr_wt else 0
            _remain   = round(_curr_wt - _goal_wt, 1) if _curr_wt else 0
            _prog_pct = round(_lost / (_start_wt - _goal_wt) * 100, 1) if _lost and _start_wt != _goal_wt else 0

            # TSB/training from data
            _strava_7d = data.get("strava_7d") or []
            _z2_this_week = 0.0
            for _act_day in _strava_7d:
                for _act in (_act_day.get("activities") or []):
                    _sport = (_act.get("sport_type") or _act.get("type") or "").lower()
                    if any(z in _sport for z in ["run", "walk", "ride", "swim", "elliptical", "workout"]):
                        _z2_this_week += float(_act.get("moving_time_seconds") or 0) / 60

            # Streak from streak_data (computed earlier in handler)
            _tier0_streak = streak_data.get("tier0_streak", 0) if streak_data else 0

            # Journey start date → days_in
            try:
                from datetime import date as _date
                _started = profile.get("journey_start_date", "2026-02-09")
                _days_in = (today.date() if hasattr(today, 'date') else today - _date(2026, 2, 9).toordinal()).days
                _days_in = max(0, (_date.today() - _date.fromisoformat(_started)).days)
            except Exception:
                _days_in = 0

            # Weekly rate: negative = losing weight (good). Guard: only if week_ago_weight exists.
            _week_ago = data.get("week_ago_weight")
            _weekly_rate = round(_curr_wt - float(_week_ago), 2) if _week_ago and _curr_wt else None

            # ACWR from computed_metrics if available
            _cm = data.get("computed_metrics") or {}
            _acwr = float(_cm.get("acwr") or 1.1)

            # v1.2.0: Build trend arrays for homepage sparklines
            _trends = {}
            try:
                # Weight trend (last 12 weeks of weekly averages)
                _wt_90d = fetch_range("withings", (today - timedelta(days=84)).isoformat(), yesterday)
                _wt_vals = [(w.get("sk", "").replace("DATE#", ""), safe_float(w, "weight_lbs")) for w in _wt_90d if safe_float(w, "weight_lbs")]
                if _wt_vals:
                    _trends["weight_daily"] = [{"date": d, "lbs": round(v, 1)} for d, v in _wt_vals[-30:]]

                # HRV trend (last 30 days)
                _hrv_vals = [(r.get("sk", "").replace("DATE#", ""), safe_float(r, "hrv")) for r in hrv_30d_recs if safe_float(r, "hrv")]
                if _hrv_vals:
                    _trends["hrv_daily"] = [{"date": d, "ms": round(v, 1)} for d, v in _hrv_vals]

                # Sleep trend (last 14 days)
                _sleep_vals = [(r.get("sk", "").replace("DATE#", ""), safe_float(r, "sleep_duration_hours")) for r in hrv_30d_recs if safe_float(r, "sleep_duration_hours")]
                if _sleep_vals:
                    _trends["sleep_daily"] = [{"date": d, "hrs": round(v, 1)} for d, v in _sleep_vals[-14:]]

                # Recovery trend (last 14 days)
                _rec_vals = [(r.get("sk", "").replace("DATE#", ""), safe_float(r, "recovery_score")) for r in hrv_30d_recs if safe_float(r, "recovery_score")]
                if _rec_vals:
                    _trends["recovery_daily"] = [{"date": d, "pct": round(v, 0)} for d, v in _rec_vals[-14:]]
            except Exception as _te:
                print(f"[WARN] Trend array build failed (non-fatal): {_te}")

            # v1.2.0: Extract AI brief excerpt for homepage widget
            _brief_excerpt = None
            try:
                _tldr = tldr_guidance.get("tldr", "")
                _guidance_items = tldr_guidance.get("guidance", [])
                if _tldr:
                    _brief_excerpt = _tldr
                    if _guidance_items and len(_guidance_items) > 0:
                        _brief_excerpt += " " + _guidance_items[0]
            except Exception as e:
                logger.warning("tldr_guidance_excerpt: %s", e)

            write_public_stats(
                s3_client=s3,
                vitals={
                    "weight_lbs":       round(_curr_wt, 1) if _curr_wt else None,
                    "weight_delta_30d": round(_curr_wt - float(_week_ago), 1) if _week_ago and _curr_wt else None,
                    "hrv_ms":           round(float(_hrv.get("hrv_yesterday") or _hrv.get("hrv_7d") or 0), 1) or None,
                    "hrv_trend":        html_builder.hrv_trend_str(_hrv.get("hrv_7d"), _hrv.get("hrv_30d")),
                    "rhr_bpm":          safe_float(_w, "resting_heart_rate"),
                    "rhr_trend":        "improving",
                    "recovery_pct":     round(_rec, 0) if _rec else None,
                    "recovery_status":  _rec_status,
                    "sleep_hours":      safe_float(data.get("sleep"), "sleep_duration_hours"),
                },
                journey={
                    "start_weight_lbs":   _start_wt,
                    "goal_weight_lbs":    _goal_wt,
                    "current_weight_lbs": _curr_wt if _curr_wt else None,
                    "lost_lbs":           _lost if _curr_wt else None,
                    "remaining_lbs":      _remain if _curr_wt else None,
                    "progress_pct":       _prog_pct if _curr_wt else None,
                    "weekly_rate_lbs":    _weekly_rate,
                    "projected_goal_date": profile.get("goal_date", "2026-07-31"),
                    "started_date":       profile.get("journey_start_date", "2026-02-09"),
                    "current_phase":      (get_current_phase(profile, _curr_wt) or {}).get("name", "Ignition") if _curr_wt else None,
                    "days_in":            _days_in,
                },
                training={
                    "ctl_fitness":          float(data.get("tsb") or 0) + 6.0,
                    "atl_fatigue":          float(data.get("tsb") or 0) + 6.5,
                    "tsb_form":             float(data.get("tsb") or 0),
                    "acwr":                 _acwr,
                    "form_status":          _cm.get("zone", "neutral"),
                    "injury_risk":          "high" if _cm.get("alert") else "low",
                    "total_miles_30d":      0,
                    "activity_count_30d":   0,
                    "zone2_this_week_min":  round(_z2_this_week),
                    "zone2_target_min":     int(profile.get("zone2_weekly_target_min") or profile.get("zone2_target_min_weekly") or 150),
                },
                platform={
                    "mcp_tools":         profile.get("platform_meta", {}).get("mcp_tools"),
                    "data_sources":      profile.get("platform_meta", {}).get("data_sources"),
                    "lambdas":           profile.get("platform_meta", {}).get("lambdas"),
                    "last_review_grade": profile.get("platform_meta", {}).get("last_review_grade"),
                    "tier0_streak":      _tier0_streak,
                    "days_in":           _days_in,
                },
                trends=_trends,
                brief_excerpt=_brief_excerpt,
            )
            print("[INFO] site_writer: public_stats.json written")
        except Exception as _sw_e:
            print(f"[WARN] site_writer failed (non-fatal): {_sw_e}")

    return {"statusCode": 200, "body": "Daily brief v2.77.0 sent: " + subject}
