"""
Daily Brief Lambda — v2.59.0 (Character Sheet Integration)
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
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
RECIPIENT  = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")
SENDER     = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/api-keys")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

# -- AWS clients ---------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)
s3       = boto3.client("s3", region_name=_REGION)
secrets  = boto3.client("secretsmanager", region_name=_REGION)

# Board of Directors config loader
try:
    import board_loader
    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False
    import logging as _log
    _log.getLogger().warning("[daily] board_loader not available — using fallback prompts")


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


def _section_error_html(section_name, error):
    """Render a graceful error placeholder when a section crashes."""
    print("[WARN] Section " + section_name + " failed: " + str(error))
    return ('<div style="background:#fef2f2;border-left:3px solid #fca5a5;'
            'border-radius:0 8px 8px 0;padding:8px 16px;margin:12px 16px 0;">'
            '<p style="font-size:11px;color:#991b1b;margin:0;">'
            '&#9888; ' + section_name + ' section unavailable</p></div>')

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
    # Compute stage percentages from hours (matching MCP normalizer)
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

def call_anthropic(prompt, api_key, max_tokens=200):
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST")
    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                resp = json.loads(r.read())
                return resp["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            print("[WARN] Anthropic HTTP " + str(e.code) + " attempt " + str(attempt))
            if attempt < 2 and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(5)
            else:
                raise
        except urllib.error.URLError as e:
            print("[WARN] Anthropic network error attempt " + str(attempt) + ": " + str(e))
            if attempt < 2:
                time.sleep(5)
            else:
                raise


# ==============================================================================
# PROFILE
# ==============================================================================

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
    withings_recent = fetch_range("withings", (today - timedelta(days=7)).isoformat(), yesterday)
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
    except Exception:
        pass

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
            bp_data["class"] = "Crisis"
            bp_data["class_color"] = "#dc2626"
        elif bp_sys >= 140 or bp_dia >= 90:
            bp_data["class"] = "Stage 2"
            bp_data["class_color"] = "#dc2626"
        elif bp_sys >= 130 or bp_dia >= 80:
            bp_data["class"] = "Stage 1"
            bp_data["class_color"] = "#d97706"
        elif bp_sys >= 120:
            bp_data["class"] = "Elevated"
            bp_data["class_color"] = "#d97706"
        else:
            bp_data["class"] = "Normal"
            bp_data["class_color"] = "#059669"

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


# ==============================================================================
# SCORING ENGINE  (extracted to scoring_engine.py — v2.76.0)
# Pure scoring functions live in scoring_engine.py. No logic here.
# ==============================================================================
from scoring_engine import (
    score_sleep, score_recovery, score_nutrition, score_movement,
    score_habits_registry, _score_habits_mvp_legacy, score_hydration,
    score_journal, score_glucose, COMPONENT_SCORERS,
    letter_grade, grade_colour, compute_day_grade,
)


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
        """Score how much data an activity has. Higher = keep."""
        score = 0
        dist = float(a.get("distance_meters") or 0)
        if dist > 0:
            score += 1000  # GPS data is strong signal
        score += float(a.get("moving_time_seconds") or 0)  # tiebreak: longer duration
        if a.get("summary_polyline"):
            score += 500  # has route
        if a.get("average_cadence") is not None:
            score += 100  # has cadence
        return score

    # Sort by start time
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

            # Must be same sport type
            if sport_j != sport_k:
                continue

            # Must start within 15 minutes of each other
            gap_min = abs((t_k - t_j).total_seconds()) / 60
            if gap_min > 15:
                break  # sorted by time, no more overlaps possible

            # Overlap detected — remove the less rich one
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
    # Also include any activities that had no parseable start time
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time




# ==============================================================================
# DAY GRADE
# ==============================================================================


def store_day_grade(date_str, total_score, grade, component_scores, weights, algo_version):
    try:
        item = {"pk": USER_PREFIX + "day_grade", "sk": "DATE#" + date_str,
                "date": date_str, "total_score": Decimal(str(total_score)),
                "letter_grade": grade, "algorithm_version": algo_version,
                "weights_snapshot": json.loads(json.dumps(weights), parse_float=Decimal) if weights else {},
                "computed_at": datetime.now(timezone.utc).isoformat()}
        for comp, score in component_scores.items():
            if score is not None:
                item["component_" + comp] = Decimal(str(score))
        table.put_item(Item=item)
        print("[INFO] Day grade stored: " + date_str + " -> " + str(total_score) + " (" + grade + ")")
    except Exception as e:
        print("[WARN] Failed to store day grade: " + str(e))


def store_habit_scores(date_str, component_details, component_scores, vice_streaks, profile):
    """Persist tier-level habit scores for historical trending.

    Writes to SOURCE#habit_scores partition with daily granularity.
    Enables MCP tools to query tier adherence trends, vice streak history,
    and synergy group patterns without recomputing from raw Habitify data.
    """
    try:
        hd = component_details.get("habits_mvp", {})
        if not hd or hd.get("composite_method") != "tier_weighted":
            return  # Only store if using new scoring

        t0 = hd.get("tier0", {})
        t1 = hd.get("tier1", {})
        vices = hd.get("vices", {})
        tier_status = hd.get("tier_status", {})

        # Missed Tier 0 habits (for pattern detection)
        missed_t0 = [name for name, done in tier_status.get(0, {}).items() if not done]

        # Synergy group completion from registry
        registry = profile.get("habit_registry", {})
        habitify = {}  # We don't have raw habitify here, compute from tier_status
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

        # Build DynamoDB item
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

        # Vice streaks as map
        if vice_streaks:
            item["vice_streaks"] = json.loads(json.dumps(vice_streaks), parse_float=Decimal)

        # Synergy group pcts as map
        if sg_pcts:
            item["synergy_groups"] = json.loads(json.dumps(sg_pcts), parse_float=Decimal)

        # Remove None values
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

    # Identify Tier 0, Tier 0+1, and vice habits
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

    # Fallback to legacy if no registry
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

        # Tier 0 streak (applicable_days aware)
        if not t0_broken:
            all_t0 = True
            for h in tier0_habits:
                meta = registry.get(h, {})
                applicable = meta.get("applicable_days", "daily")
                if applicable == "weekdays" and not is_weekday:
                    continue  # skip weekend-exempt habits
                done = habits_map.get(h, 0)
                if not (done is not None and float(done) >= 1):
                    all_t0 = False
                    break
            if all_t0:
                tier0_streak += 1
            else:
                t0_broken = True

        # Tier 0+1 streak
        if not t01_broken:
            all_t01 = True
            for h in tier01_habits:
                meta = registry.get(h, {})
                applicable = meta.get("applicable_days", "daily")
                if applicable == "weekdays" and not is_weekday:
                    continue
                if applicable == "post_training":
                    continue  # don't break streak for optional recovery days
                done = habits_map.get(h, 0)
                if not (done is not None and float(done) >= 1):
                    all_t01 = False
                    break
            if all_t01:
                tier01_streak += 1
            else:
                t01_broken = True

        # Per-vice streaks (days held)
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
# AI CALLS
# ==============================================================================

def build_data_summary(data, profile):
    journal = data.get("journal") or {}
    mf = data.get("macrofactor") or {}
    strava = data.get("strava") or {}
    habitify = data.get("habitify") or {}
    apple = data.get("apple") or {}
    sleep = data.get("sleep") or {}
    return {
        "date": data.get("date"),
        "recovery_score": safe_float(data.get("whoop"), "recovery_score"),
        "strain": safe_float(data.get("whoop"), "strain"),
        "sleep_score": safe_float(sleep, "sleep_score"),
        "sleep_duration_hrs": safe_float(sleep, "sleep_duration_hours"),
        "sleep_efficiency_pct": safe_float(sleep, "sleep_efficiency_pct"),
        "deep_sleep_pct": safe_float(sleep, "deep_pct"),
        "rem_sleep_pct": safe_float(sleep, "rem_pct"),
        "hrv_yesterday": data["hrv"].get("hrv_yesterday"),
        "hrv_7d_avg": data["hrv"].get("hrv_7d"),
        "hrv_30d_avg": data["hrv"].get("hrv_30d"),
        "calories": safe_float(mf, "total_calories_kcal"),
        "protein_g": safe_float(mf, "total_protein_g"),
        "fat_g": safe_float(mf, "total_fat_g"),
        "carbs_g": safe_float(mf, "total_carbs_g"),
        "fiber_g": safe_float(mf, "total_fiber_g"),
        "steps": safe_float(apple, "steps"),
        "water_ml": safe_float(apple, "water_intake_ml"),
        "glucose_avg": safe_float(apple, "blood_glucose_avg"),
        "glucose_tir": safe_float(apple, "blood_glucose_time_in_range_pct"),
        "glucose_std_dev": safe_float(apple, "blood_glucose_std_dev"),
        "glucose_min": safe_float(apple, "blood_glucose_min"),
        "walking_speed_mph": safe_float(apple, "walking_speed_mph"),
        "walking_step_length_in": safe_float(apple, "walking_step_length_in"),
        "walking_asymmetry_pct": safe_float(apple, "walking_asymmetry_pct"),
        "habits_completed": safe_float(habitify, "total_completed"),
        "habits_possible": safe_float(habitify, "total_possible"),
        "exercise_count": safe_float(strava, "activity_count"),
        "exercise_minutes": round((safe_float(strava, "total_moving_time_seconds") or 0) / 60, 1),
        "journal_mood": journal.get("mood_avg"),
        "journal_energy": journal.get("energy_avg"),
        "journal_stress": journal.get("stress_avg"),
        "current_weight": data.get("latest_weight"),
        "week_ago_weight": data.get("week_ago_weight"),
        "tsb": data.get("tsb"),
        "sleep_debt_7d_hrs": data.get("sleep_debt_7d_hrs"),
    }


def build_food_summary(data):
    mf = data.get("macrofactor") or {}
    food_log = mf.get("food_log", [])
    if not food_log:
        return "No food log data."
    meals = []
    for item in food_log:
        name = item.get("food_name", "?")
        cal = item.get("calories_kcal", 0)
        prot = item.get("protein_g", 0)
        t = item.get("time", "?")
        meals.append(str(t) + " - " + str(name) + " (" + str(round(float(cal))) + " cal, " + str(round(float(prot))) + "g P)")
    return "\n".join(meals)


def build_activity_summary(data):
    """Extract activity details from Strava."""
    strava = data.get("strava") or {}
    activities = strava.get("activities", [])
    if not activities:
        return "No activities recorded."
    lines = []
    for a in activities:
        name = a.get("name", "Activity")
        sport = a.get("sport_type", "?")
        duration_min = round((a.get("moving_time_seconds") or 0) / 60)
        avg_hr = a.get("average_heartrate")
        max_hr = a.get("max_heartrate")
        start = a.get("start_date_local", "")
        time_part = start.split("T")[1][:5] if "T" in start else "?"
        line = time_part + " - " + name + " (" + sport + ", " + str(duration_min) + " min"
        if avg_hr:
            line += ", avg HR " + str(round(avg_hr))
        if max_hr:
            line += ", max HR " + str(round(max_hr))
        line += ")"
        lines.append(line)
    return "\n".join(lines)


def build_workout_summary(data):
    """v2.2: Extract exercise-level detail from MacroFactor workouts."""
    mf_workouts = data.get("mf_workouts")
    if not mf_workouts:
        return "No strength training data."
    workouts = mf_workouts.get("workouts", [])
    if not workouts:
        return "No strength training data."
    lines = []
    for w in workouts:
        w_name = w.get("workout_name", "Workout")
        lines.append("WORKOUT: " + w_name)
        exercises = w.get("exercises", [])
        for ex in exercises:
            ex_name = ex.get("exercise_name", "?")
            sets = ex.get("sets", [])
            set_strs = []
            for s in sets:
                reps = s.get("reps", 0)
                weight = s.get("weight_lbs", 0)
                rir = s.get("rir")
                st = str(reps)
                if weight:
                    st += "@" + str(round(float(weight))) + "lb"
                if rir is not None:
                    st += " (RIR " + str(rir) + ")"
                set_strs.append(st)
            lines.append("  " + ex_name + ": " + ", ".join(set_strs))
        total_vol = mf_workouts.get("total_volume_lbs")
        total_sets = mf_workouts.get("total_sets")
        if total_vol:
            lines.append("Total volume: " + str(round(float(total_vol))) + " lbs, " + str(round(float(total_sets or 0))) + " sets")
    return "\n".join(lines)


def _build_weight_context(data, profile):
    """Dynamic weight context for AI prompts — replaces hardcoded '302->185' / 'losing 117 lbs'."""
    start_w = profile.get("journey_start_weight_lbs", 302)
    goal_w = profile.get("goal_weight_lbs", 185)
    current_w = data.get("latest_weight")
    if current_w:
        lost = round(start_w - current_w, 1)
        remaining = round(current_w - goal_w, 1)
        return (f"Started at {start_w} lbs, currently {round(current_w, 1)} lbs, "
                f"goal {goal_w} lbs ({lost} lost so far, {remaining} to go)")
    return f"{start_w}->{goal_w} lbs"


def _build_recent_training_summary(data):
    """Summarize last 7 days of training for AI context — prevents 'zero strength' panic on rest days."""
    strava_7d = data.get("strava_7d") or []
    if not strava_7d:
        return "No activities in last 7 days."
    lines = []
    for day_rec in strava_7d:
        date_str = day_rec.get("sk", "").replace("DATE#", "")
        activities = day_rec.get("activities", [])
        for a in activities:
            name = a.get("name", "Activity")
            sport = a.get("sport_type", "?")
            dur = round((a.get("moving_time_seconds") or 0) / 60)
            lines.append(f"{date_str}: {name} ({sport}, {dur} min)")
    return "\n".join(lines) if lines else "No activities in last 7 days."


def call_training_nutrition_coach(data, profile, api_key):
    """AI call: Training coach + Nutritionist combined. v2.2: includes workout detail + meal timing."""
    data_summary = build_data_summary(data, profile)
    food_summary = build_food_summary(data)
    activity_summary = build_activity_summary(data)
    workout_summary = build_workout_summary(data)
    weight_ctx = _build_weight_context(data, profile)
    recent_training = _build_recent_training_summary(data)

    prompt = """You are two coaches speaking to Matthew, a 36yo man in Phase 1 of weight loss (""" + weight_ctx + """, 1800 cal/day, 190g protein target).
Tone: direct, specific, no-BS. Reference specific numbers.

LAST 7 DAYS TRAINING CONTEXT:
""" + recent_training + """

STRAVA ACTIVITIES YESTERDAY:
""" + activity_summary + """

STRENGTH TRAINING DETAIL (from MacroFactor):
""" + workout_summary + """

FOOD LOG YESTERDAY (with timestamps):
""" + food_summary + """

MACRO TOTALS: """ + json.dumps({k: data_summary[k] for k in ["calories", "protein_g", "fat_g", "carbs_g", "fiber_g"] if k in data_summary}, default=str) + """
TARGETS: 1800 cal, P190g, F60g, C125g

INSTRUCTIONS:
- For TRAINING: Give per-activity feedback. For strength sessions, comment on exercise selection, volume, intensity (RIR), and how it connects to goals. For casual walks, just a brief NEAT acknowledgment. Do NOT give generic training advice. IMPORTANT: Consider the 7-day training context above. If yesterday was a rest day or light day after recent strength sessions, acknowledge that recovery is appropriate — do NOT panic about "zero strength training".
- For NUTRITION: Comment on macro adherence AND meal timing/distribution. When was protein consumed? Any long gaps? Be specific about what to adjust TODAY. Reference actual food items from the log.

Respond in EXACTLY this JSON format, no other text:
{"training": "2-4 sentences from sports scientist. Per-activity analysis. Reference specific exercises, sets, weights. Brief for walks.", "nutrition": "2-3 sentences from nutritionist about macro adherence + meal timing. Reference specific foods and timestamps. What to adjust today."}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=450)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except Exception as e:
        print("[WARN] Training/nutrition coach failed: " + str(e))
        return {}


def call_journal_coach(data, profile, api_key):
    journal_entries = data.get("journal_entries", [])
    if not journal_entries:
        return ""
    texts = []
    for e in journal_entries[:3]:
        raw = e.get("raw_text", "")
        if raw:
            texts.append(raw[:500])
    if not texts:
        return ""
    journal_text = "\n---\n".join(texts)
    obstacles = profile.get("primary_obstacles", [])
    obstacles_str = ", ".join(obstacles) if obstacles else "none specified"

    weight_ctx = _build_weight_context(data, profile)

    prompt = """You are a wise, warm-but-direct inner coach reading Matthew's journal from yesterday. He's 36, on a weight loss journey (""" + weight_ctx + """), battling: """ + obstacles_str + """.

His coaching tone: Jocko's discipline meets Attia's precision meets Brene Brown's vulnerability.

JOURNAL ENTRIES:
""" + journal_text + """

Write EXACTLY two parts separated by " || ":
Part 1: A perspective/reflection on what he wrote — something profound, motivating, or reframing. Not a summary. A mirror that shows him something he might not see. 2 sentences max.
Part 2: One specific tactical thing he can try JUST TODAY that would make a material difference based on what he wrote. Be concrete (e.g. "practice box breathing for 30 seconds before each meal" or "text one person you're grateful for before noon"). 1 sentence.

Format: [reflection] || [tactical thing]
No labels, no formatting. Natural voice. Max 80 words total."""

    try:
        return call_anthropic(prompt, api_key, max_tokens=250)
    except Exception as e:
        print("[WARN] Journal coach failed: " + str(e))
        return ""


# -- Board of Directors prompt builder -----------------------------------------

_FALLBACK_BOD_INTRO = None  # replaced by dynamic _build_bod_fallback()


def _build_daily_bod_intro_from_config(data=None, profile=None):
    """Build the Board of Directors role intro from S3 config.

    Returns the intro string (role description + tone), or None if unavailable.
    The caller appends data context, component scores, habits, journal, and output rules.
    """
    if not _HAS_BOARD_LOADER:
        return None

    config = board_loader.load_board(s3, S3_BUCKET)
    if not config:
        return None

    members = board_loader.get_feature_members(config, "daily_brief")
    if not members:
        return None

    # Build unified panel description from member titles and contributions
    panel_parts = []
    for mid, member, feat_cfg in members:
        role = feat_cfg.get("role", "unified_panel")
        if role == "unified_panel":
            title = member.get("title", member["name"])
            contribution = feat_cfg.get("contribution", "")
            panel_parts.append(f"{title} ({contribution})" if contribution else title)

    panel_desc = " + ".join(panel_parts) if panel_parts else "sports scientist + nutritionist + sleep specialist + behavioral coach"

    # Check for Huberman protocol_tips role
    protocol_note = ""
    for mid, member, feat_cfg in members:
        if feat_cfg.get("role") == "protocol_tips":
            protocol_note = f"\n{member['name']} provides: {feat_cfg.get('contribution', 'protocol recommendations')}"

    weight_ctx = _build_weight_context(data, profile) if data and profile else "302->185 lbs"
    intro = f"""You are the Board of Directors for Project40 — {panel_desc} — unified.
Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.
Tone: direct, empathetic, no-BS.{protocol_note}"""

    print("[INFO] Using config-driven daily BoD prompt")
    return intro


def call_board_of_directors(data, profile, day_grade, grade, component_scores, api_key, character_sheet=None, brief_mode="standard"):
    data_summary = build_data_summary(data, profile)
    comp_lines = []
    for comp, score in component_scores.items():
        label = comp.replace("_", " ").title()
        val = str(score) + "/100" if score is not None else "no data"
        comp_lines.append("  " + label + ": " + val)
    component_summary = "\n".join(comp_lines)
    obstacles = profile.get("primary_obstacles", [])
    health_ctx = "Primary obstacles: " + ", ".join(obstacles) + "." if obstacles else ""
    journal_ctx = ""
    journal_entries = data.get("journal_entries", [])
    if journal_entries:
        texts = []
        for e in journal_entries[:3]:
            raw = e.get("raw_text", "")
            if raw:
                texts.append(raw[:300])
        if texts:
            journal_ctx = "JOURNAL ENTRIES:\n" + "\n---\n".join(texts)

    # Build habit context from registry
    registry = profile.get("habit_registry", {})
    habitify = data.get("habitify") or {}
    h_map = habitify.get("habits", {})
    missed_t0 = []
    missed_t1 = []
    for h_name, meta in registry.items():
        if meta.get("status") != "active" or meta.get("tier", 2) > 1:
            continue
        done = h_map.get(h_name, 0)
        if not (done is not None and float(done) >= 1):
            why = meta.get("why_matthew", "")
            tier = meta.get("tier", 2)
            if tier == 0:
                missed_t0.append(h_name + (" — " + why[:80] if why else ""))
            elif tier == 1:
                missed_t1.append(h_name)
    habit_ctx = ""
    if missed_t0:
        habit_ctx += "\nMISSED TIER 0 (non-negotiable): " + "; ".join(missed_t0)
    if missed_t1:
        habit_ctx += "\nMISSED TIER 1 (high priority): " + ", ".join(missed_t1[:8])

    # Synergy group analysis
    synergy_misses = {}
    for h_name, meta in registry.items():
        if meta.get("status") != "active":
            continue
        sg = meta.get("synergy_group")
        if not sg:
            continue
        done = h_map.get(h_name, 0)
        if not (done is not None and float(done) >= 1):
            synergy_misses.setdefault(sg, []).append(h_name)
    for sg, misses in synergy_misses.items():
        total_in_group = sum(1 for _, m in registry.items() if m.get("synergy_group") == sg and m.get("status") == "active")
        if len(misses) >= total_in_group * 0.5 and total_in_group >= 3:
            habit_ctx += "\nSYNERGY ALERT: " + sg + " stack mostly missing (" + ", ".join(misses[:5]) + ")"

    # Build character sheet context for BoD
    character_ctx = ""
    if character_sheet:
        cs_level = character_sheet.get("character_level", 1)
        cs_tier = character_sheet.get("character_tier", "Foundation")
        cs_events = character_sheet.get("level_events", [])
        cs_effects = character_sheet.get("active_effects", [])
        character_ctx = "\nCHARACTER SHEET: Level " + str(cs_level) + " (" + cs_tier + ")"
        # Pillar summary
        for pn in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
            pd = character_sheet.get("pillar_" + pn, {})
            character_ctx += "\n  " + pn.capitalize() + ": Level " + str(pd.get("level", "?")) + " (" + str(pd.get("tier", "?")) + ") raw=" + str(pd.get("raw_score", "?"))
        if cs_events:
            character_ctx += "\nLEVEL EVENTS TODAY:"
            for ev in cs_events:
                ev_type = ev.get("type", "")
                if "tier" in ev_type:
                    character_ctx += "\n  " + ev.get("pillar", "").capitalize() + ": " + str(ev.get("old_tier", "")) + " \u2192 " + str(ev.get("new_tier", ""))
                elif "character" in ev_type:
                    character_ctx += "\n  Character Level " + str(ev.get("old_level", "")) + " \u2192 " + str(ev.get("new_level", ""))
                else:
                    arrow = "\u2191" if "up" in ev_type else "\u2193"
                    character_ctx += "\n  " + arrow + " " + ev.get("pillar", "").capitalize() + " Level " + str(ev.get("old_level", "")) + " \u2192 " + str(ev.get("new_level", ""))
        if cs_effects:
            character_ctx += "\nACTIVE EFFECTS: " + ", ".join(e.get("name", "") for e in cs_effects)

    # Try config-driven intro, fall back to dynamic default
    bod_intro = _build_daily_bod_intro_from_config(data, profile)
    if not bod_intro:
        print("[INFO] Using fallback dynamic daily BoD prompt")
        weight_ctx = _build_weight_context(data, profile)
        bod_intro = ("You are the Board of Directors for Project40 — sports scientist + nutritionist + sleep specialist + behavioral coach unified.\n"
                     f"Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.\n"
                     "Tone: direct, empathetic, no-BS.")

    prompt = bod_intro + """
""" + health_ctx + """

YESTERDAY'S DATA:
""" + json.dumps(data_summary, indent=2, default=str) + """

DAY GRADE: """ + str(day_grade if day_grade is not None else "N/A") + "/100 (" + grade + """)
""" + component_summary + """
""" + habit_ctx + """
""" + character_ctx + """
""" + journal_ctx + """

Write 2-3 sentences. Reference specific numbers (at least two). Connect yesterday to today. Celebrate wins briefly, name gaps directly — if a Tier 0 habit was missed, NAME it. If a synergy stack is broken, note it. If there are LEVEL EVENTS, mention them — these are rare and meaningful. If there are ACTIVE EFFECTS like Sleep Drag, note the impact. DO NOT start with "Matthew". Max 60 words."""

    # Tone modifier based on adaptive mode
    if brief_mode == "flourishing":
        prompt += "\n\nTONE: He is FLOURISHING — engagement is high, habits strong, trajectory improving. Lead with reinforcement. Be energising. Name what's working specifically. One brief forward-looking note."
    elif brief_mode == "struggling":
        prompt += "\n\nTONE: He is in a ROUGH PATCH — engagement is low, habits slipping. Be warm, not clinical. Acknowledge the difficulty without piling on. Focus on the smallest possible next right action. No guilt."

    return call_anthropic(prompt, api_key, max_tokens=200)


def call_tldr_and_guidance(data, profile, day_grade, grade, component_scores, component_details, readiness_score, readiness_colour, api_key):
    """v2.2: Combined TL;DR + Smart Guidance — one AI call that returns both."""
    data_summary = build_data_summary(data, profile)

    # Build context about missed habits (registry-aware)
    habitify = data.get("habitify") or {}
    habits_map = habitify.get("habits", {})
    registry = profile.get("habit_registry", {})
    missed_mvp = []
    missed_context = []
    if registry:
        for h_name, meta in registry.items():
            if meta.get("status") != "active" or meta.get("tier", 2) > 1:
                continue
            done = habits_map.get(h_name, 0)
            if not (done is not None and float(done) >= 1):
                missed_mvp.append(h_name)
                why = meta.get("why_matthew", "")
                impact = meta.get("expected_impact", "")
                if why:
                    missed_context.append(h_name + " (T" + str(meta.get("tier", "?")) + "): " + why[:60])
    else:
        mvp_list = profile.get("mvp_habits", [])
        for h in mvp_list:
            done = habits_map.get(h, 0)
            if not (done is not None and float(done) >= 1):
                missed_mvp.append(h)

    # Component scores summary
    comp_lines = []
    for comp, score in component_scores.items():
        if score is not None:
            comp_lines.append(comp.replace("_", " ") + ": " + str(score))
        elif comp == "hydration":
            comp_lines.append("hydration: NO DATA (Apple Health sync gap — do not give hydration tips)")

    # Sleep architecture
    sleep = data.get("sleep") or {}
    sleep_arch = ""
    deep = safe_float(sleep, "deep_pct")
    rem = safe_float(sleep, "rem_pct")
    if deep is not None:
        sleep_arch = "Deep: " + str(round(deep)) + "%, REM: " + str(round(rem or 0)) + "%"

    weight_ctx = _build_weight_context(data, profile)

    prompt = """You are the intelligence engine behind Matthew's Life Platform daily brief. Your job: synthesize ALL of yesterday's data into (1) one TL;DR sentence and (2) 3-4 smart, personalized guidance items for TODAY.

Matthew: 36yo, weight loss journey (""" + weight_ctx + """). Phase 1: 1800 cal/day, 190g protein, 16:8 IF.

YESTERDAY'S SIGNALS:
- Day grade: """ + str(day_grade) + "/100 (" + grade + """)
- Components: """ + ", ".join(comp_lines) + """
- Recovery/readiness: """ + str(readiness_score) + " (" + readiness_colour + """)
- HRV: """ + str(data_summary.get("hrv_yesterday")) + "ms yesterday, 7d avg " + str(data_summary.get("hrv_7d_avg")) + "ms, 30d avg " + str(data_summary.get("hrv_30d_avg")) + """ms
- TSB (training stress balance): """ + str(data_summary.get("tsb")) + """
- Sleep: """ + str(data_summary.get("sleep_duration_hrs")) + "hrs, score " + str(data_summary.get("sleep_score")) + ", efficiency " + str(data_summary.get("sleep_efficiency_pct")) + "%. " + sleep_arch + """
- 7-day sleep debt: """ + str(data.get("sleep_debt_7d_hrs")) + """hrs
- Calories: """ + str(data_summary.get("calories")) + "/1800, Protein: " + str(data_summary.get("protein_g")) + """/190g
- Glucose: avg """ + str(data_summary.get("glucose_avg")) + " mg/dL, TIR " + str(data_summary.get("glucose_tir")) + """%, overnight low """ + str(data_summary.get("glucose_min")) + """ mg/dL
- Gait: walking speed """ + str(data_summary.get("walking_speed_mph")) + " mph, step length " + str(data_summary.get("walking_step_length_in")) + " in, asymmetry " + str(data_summary.get("walking_asymmetry_pct")) + """%
- Steps: """ + str(data_summary.get("steps")) + """
- Weight: """ + str(data_summary.get("current_weight")) + " lbs (week ago: " + str(data_summary.get("week_ago_weight")) + """)
- Missed habits: """ + (", ".join(missed_mvp) if missed_mvp else "none — all completed") + """
- Missed habit context: """ + ("; ".join(missed_context[:5]) if missed_context else "n/a") + """
- Journal mood: """ + str(data_summary.get("journal_mood")) + "/5, stress: " + str(data_summary.get("journal_stress")) + """/5

RULES:
- TL;DR: One sentence, max 20 words. The single most important takeaway from yesterday. Specific. Not generic.
- Guidance: 3-4 items, each with an emoji prefix and 1 sentence. These must be SMART — derived from the data above, not static advice. Each item should be something that could ONLY apply to TODAY given this specific data combination. Avoid repeating daily constants (IF window, supplements, bedtime) unless there is a data-driven reason to modify them today.
- Examples of smart guidance: "HRV down 15% + high stress yesterday — do Zone 2 instead of planned HIIT", "Protein 40g short yesterday — front-load with 50g shake before first meal", "3.2hr sleep debt this week — prioritize nap or 30min earlier bedtime tonight"
- Examples of BAD guidance (too generic): "Stay hydrated", "Get 7.5 hours of sleep", "Caffeine cutoff at noon"
- NEVER suggest hydration tips if hydration shows NO DATA — the sync is broken, not the behaviour. Suggesting hydration when we have no data is misleading.

Respond in EXACTLY this JSON format, no other text:
{"tldr": "One sentence TL;DR", "guidance": ["emoji + sentence 1", "emoji + sentence 2", "emoji + sentence 3"]}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=400)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except Exception as e:
        print("[WARN] TL;DR+Guidance failed: " + str(e))
        return {}


# ==============================================================================
# HTML BUILDER
# ==============================================================================

def hrv_trend_str(hrv_7d, hrv_30d):
    if not hrv_7d or not hrv_30d or hrv_30d == 0:
        return "no trend data"
    pct = round((hrv_7d / hrv_30d - 1) * 100)
    arrow = "+" if pct >= 0 else ""
    direction = "trending up" if pct >= 2 else "stable" if pct >= -2 else "trending down"
    return str(round(hrv_7d)) + "ms 7d avg (" + arrow + str(pct) + "% vs 30d, " + direction + ")"


def build_html(data, profile, day_grade_score, grade, component_scores, component_details,
               readiness_score, readiness_colour, tldr_guidance, bod_insight,
               training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks=None,
               character_sheet=None, brief_mode="standard", engagement_score=None):

    date_str = data["date"]
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_label = dt.strftime("%A, %b %-d")
    except Exception:
        day_label = date_str

    rc_map = {
        "green":  {"bg": "#d1fae5", "border": "#059669", "label": "Go", "text": "#065f46"},
        "yellow": {"bg": "#fef3c7", "border": "#d97706", "label": "Moderate", "text": "#92400e"},
        "red":    {"bg": "#fee2e2", "border": "#dc2626", "label": "Easy", "text": "#991b1b"},
        "gray":   {"bg": "#f3f4f6", "border": "#9ca3af", "label": "-", "text": "#374151"},
    }
    rc = rc_map.get(readiness_colour, rc_map["gray"])
    gc = grade_colour(grade) if grade != "—" else "#9ca3af"
    grade_display = str(day_grade_score) if day_grade_score is not None else "—"
    grade_letter = grade if grade != "—" else ""

    # -- Header + Day Grade + TL;DR -------------------------------------------
    html = '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
    html += '<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;">'
    html += '<div style="max-width:480px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">'
    html += '<div style="background:linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);padding:20px 24px 16px;">'
    html += '<table style="width:100%;"><tr><td>'
    html += '<p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Morning Brief</p>'
    html += '<h1 style="color:#fff;font-size:17px;font-weight:700;margin:0;">' + day_label + '</h1>'
    html += '</td><td style="text-align:right;">'
    html += '<div style="font-size:38px;font-weight:800;color:' + gc + ';line-height:1;">' + grade_display + '</div>'
    html += '<div style="font-size:16px;font-weight:700;color:' + gc + ';margin-top:2px;">' + grade_letter + '</div>'
    html += '<div style="font-size:10px;color:#8892b0;margin-top:2px;">DAY GRADE</div>'
    html += '</td></tr></table>'

    # v2.2: TL;DR line
    tldr_text = (tldr_guidance or {}).get("tldr", "")
    if tldr_text:
        html += '<p style="color:#ccd6f6;font-size:12px;margin:10px 0 0;line-height:1.4;font-style:italic;">' + tldr_text + '</p>'

    html += '</div>'

    # -- Scorecard Grid (v2.2: sleep architecture detail) ----------------------
    def sc_cell(label, score, emoji, detail=""):
        if score is None:
            vd, bw, vc = "—", "0", "#9ca3af"
        else:
            vd, bw = str(score), str(score)
            vc = "#059669" if score >= 80 else "#2563eb" if score >= 60 else "#d97706" if score >= 40 else "#dc2626"
        det = '<div style="font-size:9px;color:#9ca3af;margin-top:1px;">' + detail + '</div>' if detail else ""
        return ('<td style="padding:8px 6px;width:25%;vertical-align:top;">'
                '<div style="font-size:12px;margin-bottom:4px;">' + emoji + ' <span style="color:#6b7280;font-size:10px;">' + label + '</span></div>'
                '<div style="font-size:20px;font-weight:700;color:' + vc + ';">' + vd + '</div>'
                '<div style="background:#e5e7eb;border-radius:3px;height:4px;margin-top:4px;">'
                '<div style="background:' + vc + ';border-radius:3px;height:4px;width:' + bw + '%;"></div></div>'
                + det + '</td>')

    sd = component_details.get("sleep_quality", {})
    # v2.2: show duration + deep/REM architecture
    sleep_det_parts = []
    if sd.get("duration_hrs"):
        sleep_det_parts.append(str(sd["duration_hrs"]) + "h")
    if sd.get("deep_pct") is not None:
        sleep_det_parts.append("D:" + str(round(sd["deep_pct"])) + "%")
    if sd.get("rem_pct") is not None:
        sleep_det_parts.append("R:" + str(round(sd["rem_pct"])) + "%")
    sleep_det = " ".join(sleep_det_parts)

    nd = component_details.get("nutrition", {})
    nutr_det = str(round(nd["calories"])) + " cal" if nd.get("calories") else ""
    md2 = component_details.get("movement", {})
    move_det = fmt_num(md2.get("steps")) + " steps" if md2.get("steps") else ""
    hd = component_details.get("habits_mvp", {})
    t0 = hd.get("tier0", {})
    t1 = hd.get("tier1", {})
    if t0.get("total"):
        hab_det = str(t0.get("done", 0)) + "/" + str(t0.get("total", 0)) + " T0"
        if t1.get("total"):
            hab_det += " · " + str(t1.get("done", 0)) + "/" + str(t1.get("total", 0)) + " T1"
    elif hd.get("total"):
        hab_det = str(hd.get("completed", "")) + "/" + str(hd.get("total", "")) + " MVP"
    else:
        hab_det = ""
    hyd = component_details.get("hydration", {})
    hyd_det = str(hyd.get("water_oz", "")) + "oz" if hyd.get("water_oz") else ""
    jd = component_details.get("journal", {})
    jou_det = " + ".join(t.title() for t in jd.get("templates", [])) if jd.get("templates") else ""
    gd = component_details.get("glucose", {})
    glu_det = str(round(gd["avg_glucose"])) + " mg/dL" if gd.get("avg_glucose") else ""
    rd = component_details.get("recovery", {})
    rec_det = str(round(rd["recovery_score"])) + "%" if rd.get("recovery_score") else ""

    # -- Travel Banner (v2.40.0) -----------------------------------------------
    try:
      travel = data.get("travel_active")
      if travel:
        tz_off = travel.get("tz_offset", 0)
        direction = travel.get("direction", "")
        dest = travel.get("destination", "Unknown")
        country = travel.get("country", "")
        dest_label = f"{dest}, {country}" if country else dest
        html += '<!-- S:travel -->'
        html += '<div style="background:#fef3c7;border-left:4px solid #f59e0b;border-radius:0 8px 8px 0;padding:12px 16px;margin:8px 16px;">'
        html += '<p style="font-size:12px;font-weight:700;color:#92400e;margin:0;">&#9992; Travel Mode: ' + dest_label + '</p>'
        coaching_lines = []
        if abs(tz_off) >= 3:
            coaching_lines.append('Jet lag protocol: ' + ('Morning light + evening melatonin (0.5mg)' if direction == 'eastbound' else 'Evening light + delay meals to local schedule') + f' ({abs(tz_off)} zones {direction}).')
        coaching_lines.append('Anomaly alerts are suppressed during travel. Focus on hydration and movement.')
        for line in coaching_lines:
            html += '<p style="font-size:10px;color:#78350f;margin:4px 0 0;">' + line + '</p>'
        html += '</div>'
        html += '<!-- /S:travel -->'
    except Exception as _e:
        html += _section_error_html("Travel", _e)

    # -- Adaptive Mode Banner (flourishing / struggling) ----------------------
    try:
      if brief_mode == "flourishing":
        score_str = " (" + str(engagement_score) + "/100)" if engagement_score is not None else ""
        html += '<div style="background:#d1fae5;border-left:4px solid #059669;border-radius:0 8px 8px 0;padding:10px 16px;margin:8px 16px 0;">'
        html += '<p style="font-size:12px;font-weight:700;color:#065f46;margin:0;">\U0001f31f You\'re Flourishing' + score_str + '</p>'
        html += '<p style="font-size:10px;color:#047857;margin:4px 0 0;">Journal, habits, and trend are all tracking well. Keep the momentum.&thinsp;&#129351;</p>'
        html += '</div>'
      elif brief_mode == "struggling":
        score_str = " (" + str(engagement_score) + "/100)" if engagement_score is not None else ""
        html += '<div style="background:#fff7ed;border-left:4px solid #f59e0b;border-radius:0 8px 8px 0;padding:10px 16px;margin:8px 16px 0;">'
        html += '<p style="font-size:12px;font-weight:700;color:#92400e;margin:0;">\U0001f49b Rough Patch Detected' + score_str + '</p>'
        html += '<p style="font-size:10px;color:#78350f;margin:4px 0 0;">Today\'s brief is adjusted for recovery mode. One thing at a time \u2014 the platform has you.</p>'
        html += '</div>'
    except Exception as _e:
        html += _section_error_html("Adaptive Mode Banner", _e)

    try:
      html += '<!-- S:scorecard -->'
      html += '<div style="padding:12px 8px 4px;">'
      html += '<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin:0 8px 6px;font-weight:600;">Yesterday\'s Scorecard</p>'
      html += '<table style="width:100%;border-collapse:collapse;"><tr>'
      html += sc_cell("Sleep", component_scores.get("sleep_quality"), "&#128716;", sleep_det)
      html += sc_cell("Recovery", component_scores.get("recovery"), "&#128154;", rec_det)
      html += sc_cell("Nutrition", component_scores.get("nutrition"), "&#127869;", nutr_det)
      html += sc_cell("Movement", component_scores.get("movement"), "&#127939;", move_det)
      html += '</tr><tr>'
      html += sc_cell("Habits", component_scores.get("habits_mvp"), "&#9989;", hab_det)
      html += sc_cell("Hydration", component_scores.get("hydration"), "&#128167;", hyd_det)
      html += sc_cell("Journal", component_scores.get("journal"), "&#128211;", jou_det)
      html += sc_cell("Glucose", component_scores.get("glucose"), "&#128200;", glu_det)
      html += '</tr></table></div>'
      html += '<!-- /S:scorecard -->'
    except Exception as _e:
        html += _section_error_html("Scorecard", _e)

    # -- Character Sheet (v2.59.0 — reads pre-computed record) ------------------
    try:
      if character_sheet:
        cs_level = character_sheet.get("character_level", 1)
        cs_tier = character_sheet.get("character_tier", "Foundation")
        cs_emoji = character_sheet.get("character_tier_emoji", "\U0001f528")
        cs_events = character_sheet.get("level_events", [])
        cs_effects = character_sheet.get("active_effects", [])
        cs_xp = character_sheet.get("character_xp", 0)

        # Tier colour mapping
        tier_colors = {
            "Foundation": {"bg": "#f3f4f6", "bar": "#6b7280", "text": "#374151"},
            "Momentum":   {"bg": "#fef3c7", "bar": "#d97706", "text": "#92400e"},
            "Discipline": {"bg": "#dbeafe", "bar": "#2563eb", "text": "#1e40af"},
            "Mastery":    {"bg": "#d1fae5", "bar": "#059669", "text": "#065f46"},
            "Elite":      {"bg": "#fae8ff", "bar": "#9333ea", "text": "#6b21a8"},
        }
        tc = tier_colors.get(cs_tier, tier_colors["Foundation"])

        html += '<!-- S:character_sheet -->'
        html += '<div style="background:' + tc["bg"] + ';border-left:4px solid ' + tc["bar"] + ';border-radius:0 8px 8px 0;padding:12px 16px;margin:10px 16px 0;">'

        # Header row: emoji + level + tier + XP
        html += '<table style="width:100%;"><tr><td>'
        html += '<span style="font-size:22px;">' + cs_emoji + '</span> '
        html += '<span style="font-size:20px;font-weight:800;color:' + tc["text"] + ';">Level ' + str(cs_level) + '</span> '
        html += '<span style="font-size:12px;color:' + tc["text"] + ';font-weight:600;">' + cs_tier.upper() + '</span>'
        html += '</td><td style="text-align:right;">'
        html += '<span style="font-size:10px;color:#9ca3af;">' + "{:,}".format(cs_xp) + ' XP</span>'
        html += '</td></tr></table>'

        # Avatar composite — inline PNG (192px source, rendered at 96px for email)
        avatar_tier = cs_tier.lower()
        avatar_url = 'https://dash.averagejoematt.com/avatar/email/' + avatar_tier + '-composite.png'
        html += '<div style="text-align:center;margin:8px 0 4px;">'
        html += '<img src="' + avatar_url + '" width="96" height="96" '
        html += 'style="image-rendering:pixelated;image-rendering:crisp-edges;" '
        html += 'alt="' + cs_tier + ' Avatar" />'
        html += '</div>'

        # Level-up / level-down events (rare and meaningful)
        for ev in cs_events:
            ev_type = ev.get("type", "")
            ev_pillar = ev.get("pillar", "").replace("_", " ").title()
            if "tier" in ev_type:
                old_t = ev.get("old_tier", "")
                new_t = ev.get("new_tier", "")
                is_up = "up" in ev_type
                ev_col = "#059669" if is_up else "#d97706"
                ev_icon = "\u2B06" if is_up else "\u2B07"
                html += '<div style="background:#fff;border:1px solid ' + ev_col + ';border-radius:6px;padding:6px 10px;margin:8px 0 4px;">'
                html += '<span style="font-size:12px;font-weight:700;color:' + ev_col + ';">' + ev_icon + ' ' + ev_pillar + ': ' + old_t + ' \u2192 ' + new_t + '</span></div>'
            elif "character" in ev_type:
                old_l = ev.get("old_level", "")
                new_l = ev.get("new_level", "")
                is_up = int(new_l) > int(old_l) if old_l and new_l else True
                ev_col = "#059669" if is_up else "#d97706"
                ev_icon = "\u2B06" if is_up else "\u2B07"
                html += '<div style="background:#fff;border:1px solid ' + ev_col + ';border-radius:6px;padding:6px 10px;margin:8px 0 4px;">'
                html += '<span style="font-size:12px;font-weight:700;color:' + ev_col + ';">' + ev_icon + ' Character Level ' + str(old_l) + ' \u2192 ' + str(new_l) + '</span></div>'
            elif "level" in ev_type:
                old_l = ev.get("old_level", "")
                new_l = ev.get("new_level", "")
                is_up = "up" in ev_type
                ev_col = "#059669" if is_up else "#d97706"
                ev_icon = "\u2B06" if is_up else "\u2B07"
                html += '<div style="background:#fff;border:1px solid ' + ev_col + ';border-radius:6px;padding:6px 10px;margin:8px 0 4px;">'
                html += '<span style="font-size:12px;font-weight:700;color:' + ev_col + ';">' + ev_icon + ' ' + ev_pillar + ' Level ' + str(old_l) + ' \u2192 ' + str(new_l) + '</span></div>'

        # 7 pillar mini-bars
        pillar_order = [("sleep", "\U0001f634"), ("movement", "\U0001f3cb"), ("nutrition", "\U0001f957"),
                        ("metabolic", "\U0001fa7a"), ("mind", "\U0001f9e0"), ("relationships", "\U0001f91d"),
                        ("consistency", "\U0001f3af")]
        html += '<div style="margin-top:8px;">'
        for p_name, p_emoji in pillar_order:
            pd = character_sheet.get("pillar_" + p_name, {})
            p_level = pd.get("level", 1)
            p_tier = pd.get("tier", "Foundation")
            p_raw = pd.get("raw_score")
            p_tc = tier_colors.get(p_tier, tier_colors["Foundation"])
            p_label = p_name.capitalize()
            raw_str = " (" + str(round(p_raw)) + ")" if p_raw is not None else ""

            html += '<div style="margin:3px 0;">'
            html += '<table style="width:100%;"><tr>'
            html += '<td style="width:90px;font-size:10px;color:#6b7280;">' + p_emoji + ' ' + p_label + '</td>'
            html += '<td style="width:auto;">'
            html += '<div style="background:#e5e7eb;border-radius:3px;height:6px;">'
            html += '<div style="background:' + p_tc["bar"] + ';border-radius:3px;height:6px;width:' + str(p_level) + '%;"></div></div>'
            html += '</td>'
            html += '<td style="width:60px;text-align:right;font-size:10px;color:' + p_tc["text"] + ';font-weight:600;">Lv' + str(p_level) + raw_str + '</td>'
            html += '</tr></table></div>'
        html += '</div>'

        # Active effects (Sleep Drag, Synergy Bonus, etc.)
        if cs_effects:
            html += '<div style="margin-top:6px;padding-top:6px;border-top:1px solid #e5e7eb;">'
            for eff in cs_effects:
                eff_name = eff.get("name", "")
                eff_emoji = eff.get("emoji", "")
                eff_desc = eff.get("description", "")
                targets = eff.get("targets", {})
                target_str = ", ".join(k.capitalize() + " " + ("+" if v > 0 else "") + str(round(v * 100)) + "%" for k, v in targets.items())
                html += '<span style="display:inline-block;background:#fff;border:1px solid #d1d5db;border-radius:12px;padding:2px 8px;font-size:10px;color:#374151;margin:2px 3px 2px 0;">'
                html += eff_emoji + ' ' + eff_name
                if target_str:
                    html += ' <span style="color:#9ca3af;">(' + target_str + ')</span>'
                html += '</span>'
            html += '</div>'

        # Triggered rewards (Phase 4)
        try:
            triggered_rewards = _evaluate_rewards_brief(character_sheet)
            if triggered_rewards:
                html += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e5e7eb;">'
                for rw in triggered_rewards:
                    html += '<div style="background:#fef3c7;border:1px solid #d97706;border-radius:6px;padding:6px 10px;margin:4px 0;">'
                    html += '<span style="font-size:12px;font-weight:700;color:#92400e;">🏆 REWARD UNLOCKED: ' + str(rw.get('title', '')) + '</span>'
                    rw_desc = rw.get('description', '')
                    if rw_desc:
                        html += '<br/><span style="font-size:11px;color:#92400e;">' + str(rw_desc) + '</span>'
                    html += '</div>'
                html += '</div>'
        except Exception as _rw_e:
            print('[WARN] rewards eval failed: ' + str(_rw_e))

        # Protocol recommendations for struggling pillars (Phase 4)
        try:
            protocol_recs = _get_protocol_recs_brief(character_sheet)
            if protocol_recs:
                html += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e5e7eb;">'
                html += '<div style="font-size:10px;font-weight:700;color:#6b7280;margin-bottom:4px;">📋 PROTOCOL RECOMMENDATIONS</div>'
                for pr in protocol_recs:
                    pr_pillar = pr.get('pillar', '').capitalize()
                    pr_level = pr.get('level', 0)
                    pr_dropped = pr.get('dropped', False)
                    pr_reason = '↓ dropped' if pr_dropped else 'Lv' + str(pr_level)
                    html += '<div style="margin:3px 0;font-size:11px;color:#374151;">'
                    html += '<span style="font-weight:600;">' + pr_pillar + '</span>'
                    html += ' <span style="color:#9ca3af;">(' + pr_reason + ')</span>: '
                    protos = pr.get('protocols', [])
                    html += ', '.join(str(p) if isinstance(p, str) else str(p.get('name', p)) for p in protos)
                    html += '</div>'
                html += '</div>'
        except Exception as _pr_e:
            print('[WARN] protocol recs failed: ' + str(_pr_e))

        html += '</div>'
        html += '<!-- /S:character_sheet -->'
    except Exception as _e:
        html += _section_error_html("Character Sheet", _e)

    # -- Readiness -------------------------------------------------------------
    try:
      rd_display = str(readiness_score) if readiness_score is not None else "—"
      rec_src = "today" if safe_float(data.get("whoop_today"), "recovery_score") else "yesterday"
      trend_s = hrv_trend_str(data["hrv"].get("hrv_7d"), data["hrv"].get("hrv_30d"))

      html += '<!-- S:readiness -->'
      html += '<div style="background:' + rc["bg"] + ';border-top:2px solid ' + rc["border"] + ';border-bottom:2px solid ' + rc["border"] + ';padding:14px 24px;margin-top:4px;">'
      html += '<p style="font-size:10px;color:' + rc["text"] + ';margin:0;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Today\'s Readiness (' + rec_src + ' recovery)</p>'
      html += '<p style="font-size:34px;font-weight:800;color:' + rc["text"] + ';margin:0;line-height:1.1;">' + rd_display + ' <span style="font-size:14px;font-weight:600;">' + rc["label"].upper() + '</span></p>'
      html += '<p style="font-size:11px;color:' + rc["text"] + ';margin:6px 0 0;">HRV: <strong>' + trend_s + '</strong></p>'
      html += '</div>'
      html += '<!-- /S:readiness -->'
    except Exception as _e:
        html += _section_error_html("Readiness", _e)

    # -- Training Report (v2.2: exercise-level detail) -------------------------
    try:
      strava = data.get("strava") or {}
      activities = strava.get("activities", [])
      mf_workouts = data.get("mf_workouts") or {}
      mf_workout_list = mf_workouts.get("workouts", [])
      training_comment = (training_nutrition or {}).get("training", "")

      if activities or mf_workout_list or training_comment:
        tc = '<div style="border-left:3px solid #7c3aed;background:#faf5ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        tc += '<p style="font-size:11px;font-weight:700;color:#6d28d9;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#127947; Training Report</p>'

        # Show each activity from Strava with inline workout detail if available
        for a in activities:
            name = a.get("name", "Activity")
            sport = a.get("sport_type", "")
            dur_min = round((a.get("moving_time_seconds") or 0) / 60)
            avg_hr = a.get("average_heartrate")
            max_hr = a.get("max_heartrate")
            start = a.get("start_date_local", "")
            time_part = start.split("T")[1][:5] if "T" in str(start) else ""
            tc += '<p style="font-size:13px;color:#1a1a2e;margin:6px 0 2px;font-weight:600;">' + name + '</p>'
            tc += '<p style="font-size:11px;color:#6b7280;margin:0 0 2px;">'
            if time_part:
                tc += time_part + ' &middot; '
            tc += sport + ' &middot; ' + str(dur_min) + ' min'
            if avg_hr:
                tc += ' &middot; Avg HR ' + str(round(avg_hr))
            if max_hr:
                tc += ' &middot; Max HR ' + str(round(max_hr))
            tc += '</p>'

        # v2.2: Inline exercise detail from MacroFactor workouts
        if mf_workout_list:
            for w in mf_workout_list:
                w_name = w.get("workout_name", "")
                if w_name:
                    tc += '<p style="font-size:10px;color:#7c3aed;font-weight:600;margin:6px 0 3px;text-transform:uppercase;">' + w_name + '</p>'
                exercises = w.get("exercises", [])
                for ex in exercises:
                    ex_name = ex.get("exercise_name", "?")
                    sets = ex.get("sets", [])
                    # Compact set display
                    set_parts = []
                    for s in sets:
                        reps = s.get("reps", 0)
                        weight = s.get("weight_lbs", 0)
                        if weight:
                            set_parts.append(str(reps) + "x" + str(round(float(weight))))
                        else:
                            set_parts.append(str(reps) + " reps")
                    set_str = ", ".join(set_parts)
                    tc += '<p style="font-size:11px;color:#374151;margin:1px 0;line-height:1.3;">'
                    tc += '<span style="font-weight:600;">' + ex_name + '</span>'
                    tc += ' <span style="color:#6b7280;">— ' + set_str + '</span></p>'
                total_vol = mf_workouts.get("total_volume_lbs")
                total_sets = mf_workouts.get("total_sets")
                if total_vol:
                    tc += '<p style="font-size:10px;color:#6b7280;margin:4px 0 0;">'
                    tc += 'Total: ' + fmt_num(total_vol) + ' lbs volume, ' + str(round(float(total_sets or 0))) + ' sets</p>'

        if training_comment:
            tc += '<p style="font-size:12px;color:#4c1d95;line-height:1.5;margin:8px 0 0;font-style:italic;">' + training_comment + '</p>'
        tc += '</div>'
        html += '<!-- S:training -->' + tc + '<!-- /S:training -->'
    except Exception as _e:
        html += _section_error_html("Training Report", _e)

    # -- Nutrition Report ------------------------------------------------------
    try:
      mf = data.get("macrofactor") or {}
      if mf.get("total_calories_kcal") is not None:
        cal = round(safe_float(mf, "total_calories_kcal") or 0)
        prot = round(safe_float(mf, "total_protein_g") or 0)
        fat = round(safe_float(mf, "total_fat_g") or 0)
        carbs = round(safe_float(mf, "total_carbs_g") or 0)
        fiber = round(safe_float(mf, "total_fiber_g") or 0)
        cal_target = round(profile.get("calorie_target", 1800))
        prot_target = round(profile.get("protein_target_g", 190))

        def macro_bar(label, val, target, colour, unit=""):
            pct = min(100, round(val / target * 100)) if target else 0
            return ('<div style="margin:4px 0;">'
                    '<div style="display:flex;justify-content:space-between;font-size:11px;">'
                    '<span style="color:#374151;font-weight:600;">' + label + '</span>'
                    '<span style="color:#6b7280;">' + str(val) + unit + ' / ' + str(target) + unit + '</span></div>'
                    '<div style="background:#e5e7eb;border-radius:3px;height:6px;margin-top:2px;">'
                    '<div style="background:' + colour + ';border-radius:3px;height:6px;width:' + str(pct) + '%;"></div></div></div>')

        nc = '<div style="border-left:3px solid #059669;background:#f0fdf4;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        nc += '<p style="font-size:11px;font-weight:700;color:#166534;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#127869; Nutrition Report</p>'
        cal_color = "#059669" if abs(cal - cal_target) / cal_target <= 0.10 else "#d97706" if abs(cal - cal_target) / cal_target <= 0.25 else "#dc2626"
        nc += macro_bar("Calories", cal, cal_target, cal_color, " kcal")
        prot_color = "#059669" if prot >= prot_target else "#d97706" if prot >= 170 else "#dc2626"
        fat_tgt = round(profile.get("fat_target_g", 60))
        carb_tgt = round(profile.get("carb_target_g", 125))
        nc += macro_bar("Protein", prot, prot_target, prot_color, "g")
        nc += macro_bar("Fat", fat, fat_tgt, "#6b7280", "g")
        nc += macro_bar("Carbs", carbs, carb_tgt, "#6b7280", "g")
        if fiber:
            nc += '<p style="font-size:10px;color:#6b7280;margin:4px 0 0;">Fiber: ' + str(fiber) + 'g</p>'

        food_log = mf.get("food_log", [])
        if food_log:
            seen_times = set()
            meal_groups = []
            for item in food_log:
                t = str(item.get("time", ""))
                if t not in seen_times:
                    seen_times.add(t)
                    meal_groups.append(t)
            nc += '<p style="font-size:10px;color:#6b7280;margin:6px 0 2px;font-weight:600;">Meals: ' + str(len(food_log)) + ' items across ' + str(len(meal_groups)) + ' eating window(s)</p>'

        nutrition_comment = (training_nutrition or {}).get("nutrition", "")
        if nutrition_comment:
            nc += '<p style="font-size:12px;color:#14532d;line-height:1.5;margin:8px 0 0;font-style:italic;">' + nutrition_comment + '</p>'
        nc += '</div>'
        html += '<!-- S:nutrition -->' + nc + '<!-- /S:nutrition -->'
    except Exception as _e:
        html += _section_error_html("Nutrition Report", _e)

    # -- Habits Deep-Dive (v2.47: tier-organized from habit_registry) ----------
    try:
      habitify = data.get("habitify") or {}
      habits_map = habitify.get("habits", {})
      registry = profile.get("habit_registry", {})
      by_group = habitify.get("by_group", {})
      hd_details = component_details.get("habits_mvp", {})
      tier_status = hd_details.get("tier_status", {})
      vice_stat = hd_details.get("vice_status", {})

      if habits_map and (registry or profile.get("mvp_habits")):
        hc = '<div style="border-left:3px solid #2563eb;background:#eff6ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        hc += '<p style="font-size:11px;font-weight:700;color:#1e40af;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#9989; Habits Deep-Dive</p>'

        # Tier 0: Non-Negotiable
        t0 = tier_status.get(0, {})
        if t0:
            t0_done = sum(1 for v in t0.values() if v)
            t0_color = "#059669" if t0_done == len(t0) else "#dc2626"
            hc += '<p style="font-size:10px;color:' + t0_color + ';font-weight:700;margin:0 0 3px;">TIER 0 — NON-NEGOTIABLE (' + str(t0_done) + '/' + str(len(t0)) + ')</p>'
            for habit_name, is_done in t0.items():
                icon = "&#9745;" if is_done else "&#9744;"
                color = "#059669" if is_done else "#dc2626"
                short = habit_name[:35] + "..." if len(habit_name) > 35 else habit_name
                hc += '<p style="font-size:12px;color:' + color + ';margin:1px 0;">' + icon + ' ' + short + '</p>'

        # Tier 1: High Priority
        t1 = tier_status.get(1, {})
        if t1:
            t1_done = sum(1 for v in t1.values() if v)
            t1_color = "#059669" if t1_done >= len(t1) * 0.8 else "#d97706" if t1_done >= len(t1) * 0.5 else "#dc2626"
            hc += '<p style="font-size:10px;color:' + t1_color + ';font-weight:700;margin:8px 0 3px;">TIER 1 — HIGH PRIORITY (' + str(t1_done) + '/' + str(len(t1)) + ')</p>'
            for habit_name, is_done in t1.items():
                icon = "&#9745;" if is_done else "&#9744;"
                color = "#059669" if is_done else "#d97706"
                short = habit_name[:35] + "..." if len(habit_name) > 35 else habit_name
                hc += '<p style="font-size:11px;color:' + color + ';margin:1px 0;">' + icon + ' ' + short + '</p>'

        # Vice Sub-Section with streaks
        if vice_stat:
            held = sum(1 for v in vice_stat.values() if v)
            v_color = "#059669" if held == len(vice_stat) else "#d97706" if held >= len(vice_stat) * 0.7 else "#dc2626"
            hc += '<p style="font-size:10px;color:' + v_color + ';font-weight:700;margin:8px 0 3px;">&#128721; VICES (' + str(held) + '/' + str(len(vice_stat)) + ' held)</p>'
            vs = vice_streaks if vice_streaks else {}
            for habit_name, is_done in vice_stat.items():
                icon = "&#9745;" if is_done else "&#9744;"
                color = "#059669" if is_done else "#dc2626"
                streak = vs.get(habit_name, 0)
                streak_txt = " &#128293;" + str(streak) + "d" if streak >= 2 else ""
                short = habit_name[:30] + "..." if len(habit_name) > 30 else habit_name
                hc += '<p style="font-size:11px;color:' + color + ';margin:1px 0;">' + icon + ' ' + short + streak_txt + '</p>'

        # Tier 2 summary (collapsed — just count)
        t2 = tier_status.get(2, {})
        if t2:
            t2_done = sum(1 for v in t2.values() if v)
            hc += '<p style="font-size:10px;color:#6b7280;margin:8px 0 3px;">TIER 2 — ASPIRATIONAL: ' + str(t2_done) + '/' + str(len(t2)) + ' today</p>'

        # Group performance (keep existing)
        if by_group:
            hc += '<p style="font-size:10px;color:#1e40af;font-weight:600;margin:8px 0 4px;">GROUP PERFORMANCE</p>'
            for group_name, group_data in sorted(by_group.items()):
                g_done = group_data.get("completed", 0)
                g_total = group_data.get("possible", 0)
                g_pct = round(group_data.get("pct", 0) * 100)
                pct_color = "#059669" if g_pct >= 80 else "#d97706" if g_pct >= 50 else "#dc2626"
                hc += '<p style="font-size:11px;color:#374151;margin:1px 0;">'
                hc += '<span style="color:' + pct_color + ';font-weight:600;">' + str(g_pct) + '%</span> '
                hc += group_name + ' (' + str(g_done) + '/' + str(g_total) + ')</p>'

        total_comp = safe_float(habitify, "total_completed") or 0
        total_poss = safe_float(habitify, "total_possible") or 1
        overall_pct = round(total_comp / total_poss * 100)
        hc += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">Overall: ' + str(round(total_comp)) + '/' + str(round(total_poss)) + ' (' + str(overall_pct) + '%)</p>'
        hc += '</div>'
        html += '<!-- S:habits -->' + hc + '<!-- /S:habits -->'
    except Exception as _e:
        html += _section_error_html("Habits Deep-Dive", _e)

    # -- Supplements (v2.36: reads from supplement log) --------------------------
    try:
      supp_today = data.get("supplements_today") or {}
      supp_7d = data.get("supplements_7d") or []
      supp_entries = supp_today.get("supplements", [])
      if supp_entries:
        html += '<!-- S:supplements -->'
        html += '<div style="background:#fdf4ff;border-left:3px solid #a855f7;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#7e22ce;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128138; Supplements</p>'
        for entry in supp_entries:
            s_name = entry.get("name", "?")
            s_dose = entry.get("dose")
            s_unit = entry.get("unit", "")
            s_timing = entry.get("timing", "")
            dose_str = " " + str(s_dose) + s_unit if s_dose else ""
            timing_str = " (" + s_timing.replace("_", " ") + ")" if s_timing else ""
            html += '<p style="font-size:12px;color:#581c87;margin:2px 0;">&#9745; ' + s_name + dose_str + timing_str + '</p>'
        # 7-day adherence: which supplements were taken on how many of last 7 days
        if supp_7d:
            by_name = {}
            days_with_data = set()
            for day_rec in supp_7d:
                d = day_rec.get("date", "")
                days_with_data.add(d)
                for e in (day_rec.get("supplements") or []):
                    n = e.get("name", "").lower()
                    if n not in by_name:
                        by_name[n] = {"name": e.get("name", "?"), "days": 0}
                    by_name[n]["days"] += 1
            if by_name:
                top_supps = sorted(by_name.values(), key=lambda x: x["days"], reverse=True)[:5]
                adherence_chips = ""
                for s in top_supps:
                    pct = round(s["days"] / 7 * 100)
                    col = "#059669" if pct >= 80 else "#d97706" if pct >= 50 else "#dc2626"
                    adherence_chips += '<span style="display:inline-block;background:#fff;border:1px solid ' + col + ';border-radius:12px;padding:2px 8px;font-size:9px;color:' + col + ';font-weight:600;margin:2px 3px 2px 0;">' + s["name"] + ' ' + str(s["days"]) + '/7d</span>'
                html += '<p style="font-size:9px;color:#9ca3af;margin:6px 0 2px;">7-day adherence:</p>'
                html += '<div>' + adherence_chips + '</div>'
        html += '</div>'
        html += '<!-- /S:supplements -->'
    except Exception as _e:
        html += _section_error_html("Supplements", _e)

        # -- CGM Spotlight (v2.3: fasting proxy, hypo flag, 7-day trend) ----------
    try:
      apple = data.get("apple") or {}
      cgm_avg = safe_float(apple, "blood_glucose_avg")
      cgm_tir = safe_float(apple, "blood_glucose_time_in_range_pct")
      cgm_std = safe_float(apple, "blood_glucose_std_dev")
      cgm_min = safe_float(apple, "blood_glucose_min")
      cgm_max = safe_float(apple, "blood_glucose_max")
      cgm_above140 = safe_float(apple, "blood_glucose_time_above_140_pct")
      cgm_below70 = safe_float(apple, "blood_glucose_time_below_70_pct")
      cgm_readings = safe_float(apple, "blood_glucose_readings_count")
    # 7-day CGM trend
      apple_7d = data.get("apple_7d") or []
      cgm_7d_avgs = [safe_float(d, "blood_glucose_avg") for d in apple_7d if safe_float(d, "blood_glucose_avg") is not None]
      cgm_7d_avg = round(sum(cgm_7d_avgs) / len(cgm_7d_avgs), 1) if cgm_7d_avgs else None
      if cgm_avg is not None or cgm_tir is not None:
        gc2 = '<div style="border-left:3px solid #0ea5e9;background:#f0f9ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        gc2 += '<p style="font-size:11px;font-weight:700;color:#0369a1;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128200; CGM Spotlight</p>'
        gc2 += '<table style="width:100%;border-collapse:collapse;"><tr>'
        if cgm_avg is not None:
            avg_color = "#059669" if cgm_avg < 100 else "#d97706" if cgm_avg < 120 else "#dc2626"
            trend_arrow = ""
            if cgm_7d_avg is not None and cgm_avg is not None:
                delta = cgm_avg - cgm_7d_avg
                if delta > 5: trend_arrow = ' <span style="color:#dc2626;font-size:10px;">&#9650;</span>'
                elif delta < -5: trend_arrow = ' <span style="color:#059669;font-size:10px;">&#9660;</span>'
                else: trend_arrow = ' <span style="color:#9ca3af;font-size:10px;">&#9644;</span>'
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + avg_color + ';">' + str(round(cgm_avg)) + trend_arrow + '</div><div style="font-size:9px;color:#6b7280;">Avg mg/dL</div></td>'
        if cgm_tir is not None:
            tir_color = "#059669" if cgm_tir >= 90 else "#d97706" if cgm_tir >= 70 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + tir_color + ';">' + str(round(cgm_tir)) + '%</div><div style="font-size:9px;color:#6b7280;">Time in Range</div></td>'
        if cgm_std is not None:
            std_color = "#059669" if cgm_std < 20 else "#d97706" if cgm_std < 30 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + std_color + ';">' + str(round(cgm_std, 1)) + '</div><div style="font-size:9px;color:#6b7280;">Variability</div></td>'
        if cgm_min is not None:
            fasting_color = "#059669" if cgm_min < 90 else "#d97706" if cgm_min < 100 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + fasting_color + ';">' + str(round(cgm_min)) + '</div><div style="font-size:9px;color:#6b7280;">Overnight Low</div></td>'
        gc2 += '</tr></table>'
        extras = []
        if cgm_min is not None and cgm_max is not None:
            extras.append("Range: " + str(round(cgm_min)) + "-" + str(round(cgm_max)) + " mg/dL")
        if cgm_above140 is not None and cgm_above140 > 0:
            extras.append("Time >140: " + str(round(cgm_above140)) + "%")
        if cgm_below70 is not None and cgm_below70 > 0:
            extras.append('<span style="color:#dc2626;font-weight:700;">&#9888; Hypo: ' + str(round(cgm_below70)) + '% below 70</span>')
        if cgm_readings is not None:
            extras.append(str(round(cgm_readings)) + " readings")
        if cgm_7d_avg is not None:
            extras.append("7d avg: " + str(round(cgm_7d_avg)) + " mg/dL")
        if extras:
            gc2 += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">' + ' &middot; '.join(extras) + '</p>'
        gc2 += '</div>'
        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->'
    except Exception as _e:
        html += _section_error_html("CGM Spotlight", _e)

    # -- Gait & Mobility (v2.3) ------------------------------------------------
    try:
      gait_speed = safe_float(apple, "walking_speed_mph")
      gait_step_len = safe_float(apple, "walking_step_length_in")
      gait_asym = safe_float(apple, "walking_asymmetry_pct")
      gait_dbl_support = safe_float(apple, "walking_double_support_pct")
      has_gait = any(v is not None and v > 0 for v in [gait_speed, gait_step_len])
      if has_gait:
        gt = '<div style="border-left:3px solid #10b981;background:#f0fdf4;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        gt += '<p style="font-size:11px;font-weight:700;color:#065f46;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#129406; Gait &amp; Mobility</p>'
        gt += '<table style="width:100%;border-collapse:collapse;"><tr>'
        if gait_speed is not None and gait_speed > 0:
            # Walking speed: strongest all-cause mortality predictor
            # <2.24 mph clinical flag, <3.0 suboptimal, >=3.0 good
            sp_color = "#dc2626" if gait_speed < 2.24 else "#d97706" if gait_speed < 3.0 else "#059669"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + sp_color + ';">' + str(round(gait_speed, 2)) + '</div><div style="font-size:9px;color:#6b7280;">Speed (mph)</div></td>'
        if gait_step_len is not None and gait_step_len > 0:
            # Step length: normal ~26-30 inches for adult male
            sl_color = "#dc2626" if gait_step_len < 22 else "#d97706" if gait_step_len < 26 else "#059669"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + sl_color + ';">' + str(round(gait_step_len, 1)) + '</div><div style="font-size:9px;color:#6b7280;">Step (in)</div></td>'
        if gait_asym is not None and gait_asym > 0:
            # Asymmetry: >3% injury flag, >5% significant
            as_color = "#059669" if gait_asym < 3 else "#d97706" if gait_asym < 5 else "#dc2626"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + as_color + ';">' + str(round(gait_asym, 1)) + '%</div><div style="font-size:9px;color:#6b7280;">Asymmetry</div></td>'
        if gait_dbl_support is not None and gait_dbl_support > 0:
            # Double support: <28% good, >30% flag (fall risk)
            # Apple Health reports as decimal (0.35 = 35%)
            dbl_pct = gait_dbl_support * 100 if gait_dbl_support < 1 else gait_dbl_support
            ds_color = "#059669" if dbl_pct < 28 else "#d97706" if dbl_pct < 32 else "#dc2626"
            gt += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + ds_color + ';">' + str(round(dbl_pct, 1)) + '%</div><div style="font-size:9px;color:#6b7280;">Dbl Support</div></td>'
        gt += '</tr></table>'
        gait_notes = []
        if gait_speed is not None and gait_speed < 2.24:
            gait_notes.append('<span style="color:#dc2626;font-weight:700;">&#9888; Walking speed below clinical threshold (2.24 mph)</span>')
        if gait_asym is not None and gait_asym >= 5:
            gait_notes.append('<span style="color:#dc2626;font-weight:700;">&#9888; Significant asymmetry — possible injury compensation</span>')
        elif gait_asym is not None and gait_asym >= 3:
            gait_notes.append('<span style="color:#d97706;">Mild asymmetry — monitor for change</span>')
        if gait_notes:
            gt += '<p style="font-size:10px;margin:6px 0 0;">' + ' &middot; '.join(gait_notes) + '</p>'
        gt += '</div>'
        html += '<!-- S:gait -->' + gt + '<!-- /S:gait -->'
    except Exception as _e:
        html += _section_error_html("Gait & Mobility", _e)

    # -- Habit Streaks (v2.47: tier-aware + vice streaks) -----------------------
    try:
      has_any_streak = mvp_streak > 0 or full_streak > 0
      vs = vice_streaks if vice_streaks else {}
      top_vice_streaks = sorted(vs.items(), key=lambda x: x[1], reverse=True)[:3] if vs else []
      if has_any_streak or any(s > 0 for _, s in top_vice_streaks):
        fire = "&#128293;" * min(mvp_streak, 5) if mvp_streak > 0 else ""
        s_suffix = "s" if mvp_streak != 1 else ""
        t0_text = "<strong>" + str(mvp_streak) + " day" + s_suffix + "</strong> Tier 0 streak" if mvp_streak > 0 else "Tier 0: 0"
        t01_text = " &middot; <strong>" + str(full_streak) + "</strong> T0+T1" if full_streak > 0 else ""
        html += '<div style="background:#fefce8;border-left:3px solid #eab308;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#854d0e;margin:0;text-transform:uppercase;letter-spacing:0.5px;">&#127942; Habit Streaks</p>'
        html += '<p style="font-size:13px;color:#713f12;margin:4px 0 0;">' + fire + ' ' + t0_text + t01_text + '</p>'
        # Vice streaks
        if top_vice_streaks and any(s >= 2 for _, s in top_vice_streaks):
            v_chips = ""
            for v_name, v_days in top_vice_streaks:
                if v_days >= 2:
                    v_col = "#059669" if v_days >= 14 else "#d97706" if v_days >= 7 else "#6b7280"
                    short = v_name.replace("No ", "").replace("no ", "")[:15]
                    v_chips += '<span style="display:inline-block;background:#fff;border:1px solid ' + v_col + ';border-radius:12px;padding:2px 8px;font-size:9px;color:' + v_col + ';font-weight:600;margin:2px 3px 2px 0;">&#128293;' + str(v_days) + 'd ' + short + '</span>'
            if v_chips:
                html += '<div style="margin-top:4px;">' + v_chips + '</div>'
        html += '</div>'
      else:
        html += '<div style="background:#fef2f2;border-left:3px solid #fca5a5;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#991b1b;margin:0;text-transform:uppercase;letter-spacing:0.5px;">&#127942; Habit Streaks</p>'
        html += '<p style="font-size:13px;color:#991b1b;margin:4px 0 0;">Tier 0 streak: 0 — today is day 1</p></div>'
    except Exception as _e:
        html += _section_error_html("Habit Streaks", _e)

    # -- Weather Context (v2.36: from weather-data-ingestion Lambda) -----------
    try:
      weather = data.get("weather_yesterday") or data.get("weather_today") or {}
      w_temp = safe_float(weather, "temp_avg_f")
      w_daylight = safe_float(weather, "daylight_hours")
      w_precip = safe_float(weather, "precipitation_mm")
      w_pressure = safe_float(weather, "pressure_hpa")
      if w_temp is not None:
        html += '<!-- S:weather -->'
        html += '<div style="background:#f0fdfa;border-left:3px solid #14b8a6;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#0f766e;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#127780; Weather &amp; Environment</p>'
        html += '<table style="width:100%;border-collapse:collapse;"><tr>'
        # Temp
        html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:16px;font-weight:700;color:#0f766e;">' + str(round(w_temp)) + '&deg;F</div>'
        html += '<div style="font-size:9px;color:#9ca3af;">Avg Temp</div></td>'
        # Daylight
        if w_daylight:
            dl_col = "#059669" if w_daylight >= 12 else "#d97706" if w_daylight >= 10 else "#dc2626"
            html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:16px;font-weight:700;color:' + dl_col + ';">' + str(round(w_daylight, 1)) + 'h</div>'
            html += '<div style="font-size:9px;color:#9ca3af;">Daylight</div></td>'
        # Precipitation
        if w_precip is not None:
            p_icon = "&#127783;" if w_precip > 0.5 else "&#9728;"
            html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:16px;">' + p_icon + '</div>'
            html += '<div style="font-size:9px;color:#9ca3af;">' + (str(round(w_precip, 1)) + "mm" if w_precip > 0 else "Dry") + '</div></td>'
        # Pressure
        if w_pressure:
            p_label = "Low" if w_pressure < 1010 else "Normal" if w_pressure < 1020 else "High"
            html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:13px;font-weight:700;color:#6b7280;">' + p_label + '</div>'
            html += '<div style="font-size:9px;color:#9ca3af;">' + str(round(w_pressure)) + ' hPa</div></td>'
        html += '</tr></table>'
        # Daylight coaching nudge
        if w_daylight and w_daylight < 10:
            html += '<p style="font-size:10px;color:#0f766e;margin:6px 0 0;font-style:italic;">&#128161; Short daylight — prioritize morning outdoor light within 30 min of waking (Huberman).</p>'
        if w_pressure and w_pressure < 1008:
            html += '<p style="font-size:10px;color:#0f766e;margin:4px 0 0;font-style:italic;">&#9888; Low pressure system — may affect joint inflammation and recovery.</p>'
        html += '</div>'
        html += '<!-- /S:weather -->'
    except Exception as _e:
        html += _section_error_html("Weather", _e)

    # -- Blood Pressure Tile (v2.40.0) -----------------------------------------
    try:
      bp = data.get("bp_data")
      if bp:
        bp_col = bp.get("class_color", "#059669")
        bp_cls = bp.get("class", "Normal")
        html += '<!-- S:blood_pressure -->'
        html += '<div style="background:#f0f9ff;border-left:3px solid #0284c7;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#0369a1;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#129656; Blood Pressure</p>'
        html += '<table style="width:100%;border-collapse:collapse;"><tr>'
        html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:18px;font-weight:700;color:#0c4a6e;">' + str(round(bp["systolic"])) + '/' + str(round(bp["diastolic"])) + '</div>'
        html += '<div style="font-size:9px;color:#9ca3af;">mmHg</div></td>'
        html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:13px;font-weight:700;color:' + bp_col + ';">' + bp_cls + '</div>'
        html += '<div style="font-size:9px;color:#9ca3af;">AHA Class</div></td>'
        if bp.get("pulse") is not None:
            html += '<td style="text-align:center;padding:4px 6px;"><div style="font-size:16px;font-weight:700;color:#6b7280;">' + str(round(bp["pulse"])) + '</div>'
            html += '<div style="font-size:9px;color:#9ca3af;">Pulse</div></td>'
        html += '</tr></table>'
        if bp.get("class") in ("Stage 1", "Stage 2", "Crisis"):
            html += '<p style="font-size:10px;color:#0369a1;margin:6px 0 0;font-style:italic;">&#9888; Elevated reading — confirm with repeat measurement after 5 min seated rest.</p>'
        html += '</div>'
        html += '<!-- /S:blood_pressure -->'
    except Exception as _e:
        html += _section_error_html("Blood Pressure", _e)

        # -- Weight Phase Tracker (v2.2: weekly delta callout) ---------------------
    try:
      latest_weight = data.get("latest_weight")
      if latest_weight:
        phase = get_current_phase(profile, latest_weight)
        if phase:
            p_name = phase.get("name", "?")
            p_num = str(phase.get("phase", "?"))
            p_end = phase.get("end_lbs", 0)
            p_rate = phase.get("weekly_target_lbs", 0)
            p_proj = phase.get("projected_end", "?")
            week_ago = data.get("week_ago_weight")
            if week_ago:
                wd = round(week_ago - latest_weight, 1)
                rc2 = "#059669" if wd >= p_rate * 0.8 else "#d97706" if wd > 0 else "#dc2626"
                rt = str(wd) + " lbs this week (target: " + str(p_rate) + ")"
            else:
                rc2 = "#9ca3af"
                rt = "Target: " + str(p_rate) + " lbs/week"
                wd = None
            p_start = phase.get("start_lbs", latest_weight)
            p_total = p_start - p_end
            p_lost = p_start - latest_weight
            p_pct = max(0, min(100, round(p_lost / p_total * 100))) if p_total > 0 else 0
            goal_w = profile.get("goal_weight_lbs", 185)
            t_lose = profile.get("journey_start_weight_lbs", 302) - goal_w
            t_lost = profile.get("journey_start_weight_lbs", 302) - latest_weight
            t_pct = max(0, min(100, round(t_lost / t_lose * 100))) if t_lose > 0 else 0
            html += '<!-- S:weight_phase -->'
            html += '<div style="background:#f0fdf4;border-left:3px solid #22c55e;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
            html += '<p style="font-size:11px;font-weight:700;color:#166534;margin:0;text-transform:uppercase;letter-spacing:0.5px;">&#9878; Phase ' + p_num + ': ' + p_name + '</p>'
            # v2.2: Big weight number + weekly delta
            html += '<p style="font-size:22px;font-weight:800;color:#14532d;margin:4px 0 0;line-height:1;">' + str(round(latest_weight, 1)) + ' <span style="font-size:12px;font-weight:400;color:#6b7280;">lbs</span></p>'
            if wd is not None:
                arrow = "&#9660;" if wd > 0 else "&#9650;" if wd < 0 else "&#8212;"
                html += '<p style="font-size:11px;color:' + rc2 + ';margin:2px 0 0;font-weight:600;">' + arrow + ' ' + rt + '</p>'
            else:
                html += '<p style="font-size:11px;color:#9ca3af;margin:2px 0 0;">' + rt + '</p>'
            html += '<table style="width:100%;margin-top:8px;"><tr>'
            html += '<td style="width:50%;"><div style="font-size:9px;color:#6b7280;">Phase</div>'
            html += '<div style="background:#dcfce7;border-radius:3px;height:6px;margin-top:3px;"><div style="background:#22c55e;border-radius:3px;height:6px;width:' + str(p_pct) + '%;"></div></div>'
            html += '<div style="font-size:9px;color:#6b7280;margin-top:2px;">' + str(round(latest_weight)) + ' > ' + str(p_end) + ' lbs (' + str(p_pct) + '%)</div></td>'
            html += '<td style="width:50%;padding-left:12px;"><div style="font-size:9px;color:#6b7280;">Journey</div>'
            html += '<div style="background:#dcfce7;border-radius:3px;height:6px;margin-top:3px;"><div style="background:#16a34a;border-radius:3px;height:6px;width:' + str(t_pct) + '%;"></div></div>'
            html += '<div style="font-size:9px;color:#6b7280;margin-top:2px;">' + str(round(t_lost)) + ' of ' + str(round(t_lose)) + ' lbs (' + str(t_pct) + '%)</div></td>'
            html += '</tr></table>'
            html += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">Phase milestone: ' + str(p_proj) + '</p></div>'
            html += '<!-- /S:weight_phase -->'
    except Exception as _e:
        html += _section_error_html("Weight Phase", _e)

    # -- Today's Guidance (v2.2: AI-generated smart guidance) ------------------
    try:
      html += '<!-- S:guidance -->'
      guidance_items = (tldr_guidance or {}).get("guidance", [])
      if guidance_items:
        html += '<div style="background:#f0f9ff;border-left:3px solid #6366f1;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#4338ca;margin:0 0 8px;text-transform:uppercase;letter-spacing:0.5px;">&#127919; Today\'s Guidance</p>'
        for item in guidance_items:
            html += '<p style="font-size:12px;color:#1e1b4b;line-height:1.5;margin:4px 0;">' + item + '</p>'
        html += '</div>'
      else:
        # Fallback: minimal static guidance if AI call failed
        html += '<div style="background:#f0f9ff;border-left:3px solid #6366f1;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#4338ca;margin:0 0 8px;text-transform:uppercase;letter-spacing:0.5px;">&#127919; Today\'s Guidance</p>'
        html += '<p style="font-size:12px;color:#1e1b4b;margin:4px 0;">AI guidance unavailable — check readiness signal above for training decision.</p>'
        html += '</div>'
      html += '<!-- /S:guidance -->'
    except Exception as _e:
        html += _section_error_html("Guidance", _e)

    # -- Journal Pulse ---------------------------------------------------------
    try:
      journal = data.get("journal")
      if journal:
        html += '<!-- S:journal_pulse -->'
        def mood_em(val):
            if val is None: return "—", "#888"
            if val >= 4: return "&#128522;", "#059669"
            if val >= 3: return "&#128528;", "#d97706"
            return "&#128532;", "#dc2626"
        def stress_em(val):
            if val is None: return "—", "#888"
            if val <= 2: return "&#128524;", "#059669"
            if val <= 3: return "&#128528;", "#d97706"
            return "&#128552;", "#dc2626"
        me, mc = mood_em(journal.get("mood_avg"))
        ee, ec = mood_em(journal.get("energy_avg"))
        se, sc = stress_em(journal.get("stress_avg"))
        html += '<div style="background:#faf5ff;border-left:3px solid #8b5cf6;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        templates = journal.get("templates", [])
        t_label = " + ".join(dict.fromkeys(t.title() for t in templates)) if templates else "Journal"
        html += '<p style="font-size:11px;font-weight:700;color:#6d28d9;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128211; Journal Pulse &middot; ' + t_label + '</p>'
        html += '<table style="width:100%;border-collapse:collapse;"><tr>'
        for lbl, val, em, col in [("Mood", journal.get("mood_avg"), me, mc), ("Energy", journal.get("energy_avg"), ee, ec), ("Stress", journal.get("stress_avg"), se, sc)]:
            v = str(val) + "/5" if val is not None else "—"
            html += '<td style="text-align:center;padding:6px 8px;"><div style="font-size:16px;">' + em + '</div>'
            html += '<div style="font-size:14px;font-weight:700;color:' + col + ';">' + v + '</div>'
            html += '<div style="font-size:9px;color:#9ca3af;margin-top:1px;">' + lbl + '</div></td>'
        html += '</tr></table>'
        if journal.get("themes"):
            chips = " ".join('<span style="display:inline-block;background:#f0f4ff;color:#4a6cf7;font-size:9px;padding:2px 6px;border-radius:8px;margin:2px;">' + t + '</span>' for t in journal["themes"][:4])
            html += '<div style="margin-top:6px;text-align:center;">' + chips + '</div>'
        if journal.get("notable_quote"):
            html += '<div style="margin-top:8px;padding:6px 10px;border-left:2px solid #c7d2fe;background:#f8f9ff;border-radius:0 6px 6px 0;">'
            html += '<p style="font-size:11px;color:#4338ca;font-style:italic;margin:0;line-height:1.4;">"' + journal["notable_quote"] + '"</p></div>'
        html += '</div>'
        html += '<!-- /S:journal_pulse -->'
    except Exception as _e:
        html += _section_error_html("Journal Pulse", _e)

    # -- Journal Coach ---------------------------------------------------------
    try:
      if journal_coach_text:
        html += '<!-- S:journal_coach -->'
        parts = journal_coach_text.split(" || ")
        reflection = parts[0].strip() if len(parts) >= 1 else ""
        tactical = parts[1].strip() if len(parts) >= 2 else ""
        html += '<div style="background:#fef7ed;border-left:3px solid #f59e0b;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#92400e;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128161; Journal Coach</p>'
        if reflection:
            html += '<p style="font-size:12px;color:#78350f;line-height:1.6;margin:0 0 6px;">' + reflection + '</p>'
        if tactical:
            html += '<p style="font-size:12px;color:#92400e;line-height:1.5;margin:0;font-weight:600;">&#127919; Today: ' + tactical + '</p>'
        html += '</div>'
        html += '<!-- /S:journal_coach -->'
    except Exception as _e:
        html += _section_error_html("Journal Coach", _e)

    # -- Board of Directors ----------------------------------------------------
    try:
      if bod_insight:
        html += '<!-- S:bod -->'
        html += '<div style="background:#f0f9ff;border-left:3px solid #0ea5e9;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#0369a1;margin:0 0 4px;text-transform:uppercase;letter-spacing:0.5px;">&#129504; Board of Directors</p>'
        html += '<p style="font-size:13px;color:#0c4a6e;line-height:1.6;margin:0;">' + bod_insight + '</p></div>'
        html += '<!-- /S:bod -->'
    except Exception as _e:
        html += _section_error_html("Board of Directors", _e)

    # -- Anomaly Alert ---------------------------------------------------------
    try:
      anomaly_data = data.get("anomaly", {})
      if anomaly_data.get("severity") in ("moderate", "high"):
        flagged = anomaly_data.get("anomalous_metrics", [])
        hypothesis = anomaly_data.get("hypothesis", "")
        sev_col = "#dc2626" if anomaly_data.get("severity") == "high" else "#d97706"
        chips = ""
        for m in flagged:
            arrow = "&#8595;" if m.get("direction") == "low" else "&#8593;"
            chips += '<span style="display:inline-block;background:#fff;border:1px solid ' + sev_col + ';border-radius:12px;padding:2px 8px;font-size:10px;color:' + sev_col + ';font-weight:600;margin:2px 3px 2px 0;">' + arrow + ' ' + m.get("label", "") + '</span>'
        html += '<div style="background:#fff7ed;border-left:3px solid ' + sev_col + ';border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:' + sev_col + ';margin:0 0 4px;text-transform:uppercase;letter-spacing:0.5px;">&#9888; Anomaly Detected</p>'
        html += '<div>' + chips + '</div>'
        if hypothesis:
            html += '<p style="font-size:11px;color:#374151;line-height:1.5;margin:6px 0 0;">' + hypothesis + '</p>'
        html += '</div>'
    except Exception as _e:
        html += _section_error_html("Anomaly Alert", _e)

    # -- Footer ----------------------------------------------------------------
    active_sources = []
    for name, key in [("Whoop", "whoop"), ("Eight Sleep", "sleep"), ("Strava", "strava"),
                       ("MacroFactor", "macrofactor"), ("Apple Health", "apple"), ("Habitify", "habitify"),
                       ("MF Workouts", "mf_workouts"), ("Supplements", "supplements_today"),
                       ("Weather", "weather_yesterday")]:
        if data.get(key):
            active_sources.append(name)
    if data.get("journal"):
        active_sources.append("Notion")
    source_str = " &middot; ".join(active_sources) if active_sources else "No data sources"
    html += '<div style="background:#f8f8fc;padding:10px 24px;border-top:1px solid #e8e8f0;margin-top:12px;">'
    html += '<p style="color:#9ca3af;font-size:9px;margin:0;text-align:center;">Life Platform v2.36 &middot; ' + date_str + ' &middot; ' + source_str + '</p></div>'
    html += '</div></body></html>'
    return html




def sanitize_for_demo(html, data, profile):
    """Apply demo mode sanitization using profile-driven rules.
    
    Rules in profile["demo_mode_rules"]:
      redact_patterns: list of words → case-insensitive replace with "[redacted]"
      replace_values: dict mapping field names to replacement text
        Supported: weight_lbs, calories, protein, body_fat_pct
        Uses actual data values to find/replace all occurrences
      hide_sections: list of section names to strip entirely
        Available: scorecard, readiness, training, nutrition, habits, cgm,
                   weight_phase, guidance, journal_pulse, journal_coach, bod
      subject_prefix: string prepended to email subject (e.g. "[DEMO]")
    """
    import re
    rules = profile.get("demo_mode_rules", {})
    if not rules:
        return html

    # 1. Hide entire sections via comment markers
    for section in rules.get("hide_sections", []):
        pattern = r'<!-- S:' + re.escape(section) + r' -->.*?<!-- /S:' + re.escape(section) + r' -->'
        html = re.sub(pattern, '', html, flags=re.DOTALL)

    # 2. Replace specific data values with masked text
    rv = rules.get("replace_values", {})

    if "weight_lbs" in rv:
        mask = rv["weight_lbs"]
        # Replace actual weight values from data
        for w in [data.get("latest_weight"), data.get("week_ago_weight")]:
            if w:
                for fmt in [str(round(float(w), 1)), str(round(float(w)))]:
                    html = html.replace(fmt, mask)
        # Replace phase target weights
        for phase in profile.get("weight_loss_phases", []):
            for key in ["start_lbs", "end_lbs"]:
                v = phase.get(key)
                if v:
                    for fmt in [str(round(float(v), 1)), str(round(float(v)))]:
                        html = html.replace(fmt, mask)
        # Replace journey weights
        for key in ["goal_weight_lbs", "journey_start_weight_lbs"]:
            v = profile.get(key)
            if v:
                for fmt in [str(round(float(v), 1)), str(round(float(v)))]:
                    html = html.replace(fmt, mask)

    if "calories" in rv:
        mask = rv["calories"]
        mf = data.get("macrofactor") or {}
        cal = mf.get("total_calories_kcal")
        if cal:
            html = html.replace(str(round(float(cal))), mask)
        cal_target = profile.get("calorie_target")
        if cal_target:
            html = html.replace(str(round(float(cal_target))), mask)

    if "protein" in rv:
        mask = rv["protein"]
        mf = data.get("macrofactor") or {}
        prot = mf.get("total_protein_g")
        if prot:
            html = html.replace(str(round(float(prot))), mask)

    # 3. Redact text patterns (case-insensitive, word boundary)
    for pat in rules.get("redact_patterns", []):
        html = re.sub(r'(?i)\b' + re.escape(pat) + r'(?:s|ed|ing)?\b', '[redacted]', html)

    # 4. Add demo banner at top of email
    demo_banner = ('<div style="background:#fef3c7;border:2px solid #f59e0b;border-radius:8px;'
                   'padding:8px 16px;margin:0 16px 8px;text-align:center;">'
                   '<p style="font-size:11px;color:#92400e;margin:0;font-weight:700;">'
                   '&#128274; DEMO VERSION — Some data redacted for privacy</p></div>')
    # Insert after the header div closes (after the dark gradient header)
    header_end = '</div></div>'  # end of header section
    idx = html.find(header_end)
    if idx > 0:
        insert_at = idx + len(header_end)
        html = html[:insert_at] + demo_banner + html[insert_at:]

    return html


# ==============================================================================
# DASHBOARD JSON GENERATOR
# ==============================================================================

DASHBOARD_BUCKET = S3_BUCKET  # From env var
DASHBOARD_KEY = "dashboard/data.json"


def _build_avatar_data(character_sheet, profile, current_weight=None):
    """Build avatar display state from character sheet + weight data.

    Returns dict with tier, body_frame, badges, effects, expressions, elite_crown, alignment_ring.
    Used by dashboard and buddy JSON writers.
    """
    if not character_sheet:
        return None

    tier = (character_sheet.get("character_tier") or "Foundation").lower().replace(" ", "_")
    pillar_names = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]

    # --- Body frame (from weight journey) ---
    start_w = profile.get("journey_start_weight_lbs", 302)
    goal_w = profile.get("goal_weight_lbs", 185)
    cw = current_weight or start_w
    if start_w != goal_w:
        composition_score = max(0, min(100, ((start_w - cw) / (start_w - goal_w)) * 100))
    else:
        composition_score = 100
    if composition_score >= 75:
        body_frame = 3
    elif composition_score >= 36:
        body_frame = 2
    else:
        body_frame = 1

    # --- Badge states (hidden / dim / bright based on pillar level) ---
    badges = {}
    for pn in pillar_names:
        pd = character_sheet.get(f"pillar_{pn}", {})
        lvl = pd.get("level", 1) if pd else 1
        if lvl >= 61:
            badges[pn] = "bright"
        elif lvl >= 41:
            badges[pn] = "dim"
        else:
            badges[pn] = "hidden"

    # --- Active effects (just names for CSS class matching) ---
    raw_effects = character_sheet.get("active_effects", [])
    effect_names = [e.get("name", "").lower().replace(" ", "_") for e in raw_effects if e.get("name")]

    # --- Pillar micro-expressions ---
    sleep_lvl = (character_sheet.get("pillar_sleep") or {}).get("level", 1)
    move_lvl = (character_sheet.get("pillar_movement") or {}).get("level", 1)
    meta_lvl = (character_sheet.get("pillar_metabolic") or {}).get("level", 1)
    cons_lvl = (character_sheet.get("pillar_consistency") or {}).get("level", 1)
    expressions = {
        "eyes": "bright" if sleep_lvl >= 61 else ("dim" if sleep_lvl < 35 else "normal"),
        "posture": "forward" if move_lvl >= 61 else "normal",
        "skin_tone": "warm" if meta_lvl >= 61 else ("cool" if meta_lvl < 35 else "normal"),
        "ground": "solid" if cons_lvl >= 61 else ("faded" if cons_lvl < 35 else "normal"),
    }

    # --- Elite extras ---
    char_lvl = character_sheet.get("character_level", 1)
    all_discipline = all(badges[p] != "hidden" for p in pillar_names)
    elite_crown = char_lvl >= 81
    alignment_ring = all_discipline and all(badges[p] == "bright" for p in pillar_names)

    return {
        "tier": tier,
        "body_frame": body_frame,
        "composition_score": round(composition_score, 1),
        "badges": badges,
        "effects": effect_names,
        "expressions": expressions,
        "elite_crown": elite_crown,
        "alignment_ring": alignment_ring,
    }


def write_dashboard_json(data, profile, day_grade_score, grade, component_scores,
                         readiness_score, readiness_colour, tldr_guidance, yesterday,
                         component_details=None, character_sheet=None):
    """Write dashboard.json to S3 for the static web dashboard.

    Builds a compact JSON with 6 tiles worth of data plus 7-day sparklines.
    Called at the end of the daily brief after all data has been gathered.
    """
    if component_details is None:
        component_details = {}
    try:
        today = datetime.now(timezone.utc).date()

        # --- Sparkline data (7-day histories) ---
        # Sleep sparkline: 7 days of sleep scores
        sleep_7d = [_normalize_whoop_sleep(i) for i in fetch_range("whoop",
                               (today - timedelta(days=7)).isoformat(), yesterday)]
        sleep_sparkline = [safe_float(d, "sleep_score") for d in sleep_7d]

        # HRV sparkline
        hrv_7d_recs = fetch_range("whoop",
                                  (today - timedelta(days=7)).isoformat(), yesterday)
        hrv_sparkline = [safe_float(d, "hrv") for d in hrv_7d_recs]

        # Weight sparkline (may have gaps — fill forward)
        withings_14d = fetch_range("withings",
                                   (today - timedelta(days=14)).isoformat(), yesterday)
        weight_by_date = {}
        for w in withings_14d:
            d = w.get("sk", "").replace("DATE#", "")
            wt = safe_float(w, "weight_lbs")
            if wt:
                weight_by_date[d] = wt
        weight_sparkline = []
        last_w = None
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i + 1)).isoformat()
            if d in weight_by_date:
                last_w = weight_by_date[d]
            if last_w is not None:
                weight_sparkline.append(round(last_w, 1))

        # Glucose sparkline: 7 days of daily avg
        apple_7d = data.get("apple_7d") or []
        glucose_sparkline = [safe_float(d, "blood_glucose_avg") for d in apple_7d]

        # --- Build readiness training recommendation ---
        training_rec = ""
        if readiness_colour == "green":
            training_rec = "Hard workout OK · Follow today's plan"
        elif readiness_colour == "yellow":
            training_rec = "Moderate effort · Zone 2 or easy strength"
        elif readiness_colour == "red":
            training_rec = "Active recovery only · Walk, yoga, stretch"

        # If TSB data available, enhance recommendation
        tsb = data.get("tsb")
        if tsb is not None:
            if tsb < -20:
                training_rec = "Overreached · Deload recommended"
            elif tsb > 15:
                training_rec = "Fresh legs · Good day for a hard session"

        # --- Weight context ---
        latest_weight = data.get("latest_weight")
        week_ago_weight = data.get("week_ago_weight")
        weekly_delta = None
        if latest_weight and week_ago_weight:
            weekly_delta = round(latest_weight - week_ago_weight, 1)

        phase = get_current_phase(profile, latest_weight) if latest_weight else None
        phase_name = phase.get("name", "") if phase else ""
        journey_start = profile.get("journey_start_weight_lbs", 302)
        goal_weight = profile.get("goal_weight_lbs", 185)
        journey_pct = None
        if latest_weight and journey_start and goal_weight:
            total_to_lose = journey_start - goal_weight
            lost = journey_start - latest_weight
            journey_pct = max(0, min(100, round(lost / total_to_lose * 100))) if total_to_lose > 0 else 0

        # --- Glucose context ---
        apple = data.get("apple") or {}
        glucose_avg = safe_float(apple, "blood_glucose_avg")
        glucose_tir = safe_float(apple, "blood_glucose_time_in_range_pct")
        glucose_std = safe_float(apple, "blood_glucose_std_dev")
        glucose_min = safe_float(apple, "blood_glucose_min")

        # --- Sleep context ---
        sleep = data.get("sleep") or {}
        sleep_score = safe_float(sleep, "sleep_score")
        sleep_duration = safe_float(sleep, "sleep_duration_hours")
        sleep_efficiency = safe_float(sleep, "sleep_efficiency_pct")
        deep_pct = safe_float(sleep, "deep_pct")
        rem_pct = safe_float(sleep, "rem_pct")

        # --- Zone 2 this week ---
        zone2_min = None
        try:
            # Count this calendar week's Zone 2 minutes from Strava
            week_start = today - timedelta(days=today.weekday())  # Monday
            strava_week = fetch_range("strava", week_start.isoformat(), yesterday)
            max_hr = profile.get("max_heart_rate", 184)
            z2_lo = max_hr * 0.60
            z2_hi = max_hr * 0.70
            z2_total = 0.0
            for day_rec in strava_week:
                for act in (day_rec.get("activities") or []):
                    avg_hr = safe_float(act, "average_heartrate")
                    dur_s = safe_float(act, "moving_time_seconds") or 0
                    if avg_hr and z2_lo <= avg_hr <= z2_hi:
                        z2_total += dur_s / 60
            zone2_min = round(z2_total)
        except Exception:
            pass

        # --- Count active sources ---
        source_names = ["whoop", "sleep", "macrofactor", "habitify",
                        "apple", "strava", "garmin", "supplements_today",
                        "weather_yesterday"]
        sources_active = sum(1 for s_name in source_names if data.get(s_name))
        if data.get("journal"):
            sources_active += 1

        # --- Assemble JSON ---
        dashboard = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date": yesterday,
            "readiness": {
                "score": readiness_score,
                "color": readiness_colour,
                "label": {"green": "Go", "yellow": "Moderate",
                          "red": "Easy", "gray": "No Data"}.get(readiness_colour, "—"),
                "training_rec": training_rec,
            },
            "sleep": {
                "score": sleep_score,
                "duration_hrs": sleep_duration,
                "efficiency": sleep_efficiency,
                "deep_pct": deep_pct,
                "rem_pct": rem_pct,
                "sparkline": sleep_sparkline,
            },
            "hrv": {
                "value": safe_float(data.get("whoop"), "hrv"),
                "avg_7d": data["hrv"].get("hrv_7d"),
                "avg_30d": data["hrv"].get("hrv_30d"),
                "sparkline": hrv_sparkline,
            },
            "weight": {
                "current": latest_weight,
                "weekly_delta": weekly_delta,
                "phase": phase_name,
                "journey_pct": journey_pct,
                "sparkline": weight_sparkline,
            },
            "glucose": {
                "avg": glucose_avg,
                "tir_pct": glucose_tir,
                "variability": glucose_std,
                "fasting_proxy": glucose_min,
                "sparkline": glucose_sparkline,
            },
            "tsb": tsb,
            "zone2_min": zone2_min,
            "day_grade": {
                "score": day_grade_score,
                "letter": grade if grade != "—" else None,
                "components": {
                    "sleep": component_scores.get("sleep_quality"),
                    "recovery": component_scores.get("recovery"),
                    "nutrition": component_scores.get("nutrition"),
                    "movement": component_scores.get("movement"),
                    "habits": component_scores.get("habits_mvp"),
                    "habits_tier0": (component_details.get("habits_mvp", {}).get("tier0", {}).get("done")),
                    "habits_tier1": (component_details.get("habits_mvp", {}).get("tier1", {}).get("done")),
                    "hydration": component_scores.get("hydration"),
                    "journal": component_scores.get("journal"),
                    "glucose": component_scores.get("glucose"),
                },
                "tldr": (tldr_guidance or {}).get("tldr", ""),
            },
            "sources_active": sources_active,
            "character_sheet": {
                "level": character_sheet.get("character_level", 1) if character_sheet else None,
                "tier": character_sheet.get("character_tier") if character_sheet else None,
                "tier_emoji": character_sheet.get("character_tier_emoji") if character_sheet else None,
                "xp": character_sheet.get("character_xp", 0) if character_sheet else None,
                "pillars": {pn: {"level": (character_sheet.get("pillar_" + pn) or {}).get("level"),
                                  "tier": (character_sheet.get("pillar_" + pn) or {}).get("tier"),
                                  "raw_score": (character_sheet.get("pillar_" + pn) or {}).get("raw_score")}
                             for pn in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]}
                if character_sheet else {},
                "events": character_sheet.get("level_events", []) if character_sheet else [],
                "effects": [{"name": e.get("name"), "emoji": e.get("emoji")} for e in character_sheet.get("active_effects", [])] if character_sheet else [],
            } if character_sheet else None,
            "avatar": _build_avatar_data(character_sheet, profile, data.get("avatar_weight") or data.get("latest_weight")),
        }

        # Write to S3
        s3.put_object(
            Bucket=DASHBOARD_BUCKET,
            Key=DASHBOARD_KEY,
            Body=json.dumps(dashboard, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Dashboard JSON written to s3://" + DASHBOARD_BUCKET + "/" + DASHBOARD_KEY)

    except Exception as e:
        # Non-fatal: dashboard is a nice-to-have, don't fail the brief
        print("[WARN] Dashboard JSON write failed: " + str(e))


# ==============================================================================
# REWARD EVALUATION + PROTOCOL RECOMMENDATIONS (Phase 4, v2.71.0)
# ==============================================================================

REWARDS_PK = f"USER#{USER_ID}#SOURCE#rewards"
CS_CONFIG_KEY = "config/character_sheet.json"
_PILLAR_ORDER_CS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


def _evaluate_rewards_brief(character_sheet):
    """Check all active rewards against current character sheet. Returns newly triggered rewards."""
    if not character_sheet:
        return []
    tier_order = ["Foundation", "Momentum", "Discipline", "Mastery", "Elite"]
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": REWARDS_PK, ":prefix": "REWARD#"},
        )
        items = resp.get("Items", [])
    except Exception as e:
        print("[WARN] evaluate_rewards query failed: " + str(e))
        return []

    triggered = []
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        if item.get("status") != "active":
            continue
        condition = d2f(item.get("condition", {}))
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except Exception:
                continue
        met = False
        ctype = condition.get("type", "")
        if ctype == "character_level":
            met = character_sheet.get("character_level", 0) >= condition.get("level", 999)
        elif ctype == "character_tier":
            cur = character_sheet.get("character_tier", "Foundation")
            tgt = condition.get("tier", "Elite")
            met = (tier_order.index(cur) >= tier_order.index(tgt)
                   if cur in tier_order and tgt in tier_order else False)
        elif ctype == "pillar_level":
            p = condition.get("pillar", "")
            met = character_sheet.get("pillar_" + p, {}).get("level", 0) >= condition.get("level", 999)
        elif ctype == "pillar_tier":
            p = condition.get("pillar", "")
            cur = character_sheet.get("pillar_" + p, {}).get("tier", "Foundation")
            tgt = condition.get("tier", "Elite")
            met = (tier_order.index(cur) >= tier_order.index(tgt)
                   if cur in tier_order and tgt in tier_order else False)
        if met:
            try:
                table.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression="SET #s = :s, triggered_at = :t",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "triggered", ":t": now},
                )
                triggered.append({
                    "reward_id": str(item.get("reward_id", "")),
                    "title": str(d2f(item.get("title", ""))),
                    "description": str(d2f(item.get("description", ""))),
                    "condition": condition,
                })
            except Exception as e:
                print("[WARN] failed to update reward " + str(item.get("reward_id")) + ": " + str(e))
    return triggered


def _get_protocol_recs_brief(character_sheet):
    """Get protocol recommendations for struggling pillars from S3 config."""
    if not character_sheet:
        return []
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=CS_CONFIG_KEY)
        config = json.loads(resp["Body"].read())
    except Exception as e:
        print("[WARN] protocol recs: config load failed: " + str(e))
        return []

    protocols_config = config.get("protocols", {})
    if not protocols_config:
        return []

    events = character_sheet.get("level_events", [])
    dropped = {ev.get("pillar", "") for ev in events if "down" in ev.get("type", "")}

    recs = []
    for pillar in _PILLAR_ORDER_CS:
        pdata = character_sheet.get("pillar_" + pillar, {})
        level = pdata.get("level", 1)
        tier = pdata.get("tier", "Foundation")
        if (pillar in dropped or level < 41) and pillar in protocols_config:
            pillar_protos = protocols_config[pillar]
            if isinstance(pillar_protos, dict) and tier in pillar_protos:
                tier_recs = pillar_protos[tier]
                if tier_recs:
                    recs.append({
                        "pillar": pillar,
                        "tier": tier,
                        "level": level,
                        "dropped": pillar in dropped,
                        "protocols": tier_recs[:2],
                    })
    return recs


def write_clinical_json(data, profile, yesterday):
    """Write clinical.json to S3 for the clinical summary view.

    Queries labs, DEXA, genome, supplements, and computes 30-day averages.
    Called at the end of the daily brief after all data has been gathered.
    """
    try:
        today = datetime.now(timezone.utc).date()

        # --- Vitals: 30-day averages ---
        whoop_30d = fetch_range("whoop",
                                (today - timedelta(days=30)).isoformat(), yesterday)
        rhr_vals = [safe_float(r, "resting_heart_rate") for r in whoop_30d]
        rhr_vals = [v for v in rhr_vals if v is not None]
        hrv_vals = [safe_float(r, "hrv") for r in whoop_30d]
        hrv_vals = [v for v in hrv_vals if v is not None]

        # Weight: current + 30-day delta
        withings_30d = fetch_range("withings",
                                   (today - timedelta(days=30)).isoformat(), yesterday)
        weight_current = None
        weight_30d_ago = None
        for w in reversed(withings_30d):
            wt = safe_float(w, "weight_lbs")
            if wt and weight_current is None:
                weight_current = wt
        for w in withings_30d:
            wt = safe_float(w, "weight_lbs")
            if wt:
                weight_30d_ago = wt
                break
        weight_30d_delta = None
        if weight_current and weight_30d_ago:
            weight_30d_delta = round(weight_current - weight_30d_ago, 1)

        vitals = {
            "weight_current": weight_current,
            "weight_30d_delta": weight_30d_delta,
            "rhr_avg": round(sum(rhr_vals) / len(rhr_vals)) if rhr_vals else None,
            "hrv_avg": round(sum(hrv_vals) / len(hrv_vals)) if hrv_vals else None,
            "bp_systolic": None,
            "bp_diastolic": None,
        }

        # --- Body Composition (DEXA) — latest scan ---
        body_comp = {}
        try:
            resp = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={
                    ":pk": USER_PREFIX + "dexa",
                    ":sk": "DATE#"
                },
                ScanIndexForward=False,
                Limit=1
            )
            if resp.get("Items"):
                dexa = resp["Items"][0]
                bc = dexa.get("body_composition", {})
                bd = dexa.get("bone_density", {})
                body_comp = {
                    "scan_date": dexa.get("scan_date"),
                    "body_fat_pct": d2f(bc.get("body_fat_pct")),
                    "ffmi": d2f(dexa.get("interpretations", {}).get("ffmi")),
                    "lean_mass_lbs": d2f(bc.get("lean_mass_lbs")),
                    "fat_mass_lbs": d2f(bc.get("fat_mass_lbs")),
                    "visceral_fat_area": d2f(bc.get("visceral_fat_g")),
                    "bmd": d2f(bd.get("t_score")),
                }
        except Exception as e:
            print("[WARN] Clinical: DEXA query failed: " + str(e))

        # --- Lab Results — latest draw ---
        labs = {}
        try:
            resp = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={
                    ":pk": USER_PREFIX + "labs",
                    ":sk": "DATE#"
                },
                ScanIndexForward=False,
                Limit=1
            )
            all_draws = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={
                    ":pk": USER_PREFIX + "labs",
                    ":sk": "DATE#"
                },
                Select="COUNT"
            )
            total_draws = all_draws.get("Count", 0)

            if resp.get("Items"):
                lab_rec = resp["Items"][0]
                biomarkers_raw = lab_rec.get("biomarkers", {})
                out_of_range = lab_rec.get("out_of_range", [])

                biomarker_list = []
                cat_order = [
                    "lipids", "lipids_advanced", "cardiovascular",
                    "metabolic", "cbc", "cbc_differential",
                    "liver", "kidney", "thyroid",
                    "hormones", "inflammation", "iron",
                    "vitamins", "minerals", "electrolytes",
                    "immune", "omega_fatty_acids", "prostate",
                    "toxicology", "genetics", "blood_type", "digestive"
                ]
                cat_names = {
                    "lipids": "Lipids", "lipids_advanced": "Advanced Lipids",
                    "cardiovascular": "Cardiovascular", "metabolic": "Metabolic",
                    "cbc": "Complete Blood Count", "cbc_differential": "CBC Differential",
                    "liver": "Liver", "kidney": "Kidney", "thyroid": "Thyroid",
                    "hormones": "Hormones", "inflammation": "Inflammation",
                    "iron": "Iron Studies", "vitamins": "Vitamins", "minerals": "Minerals",
                    "electrolytes": "Electrolytes", "immune": "Immune",
                    "omega_fatty_acids": "Omega Fatty Acids", "prostate": "Prostate",
                    "toxicology": "Toxicology", "genetics": "Genetics",
                    "blood_type": "Blood Type", "digestive": "Digestive"
                }

                by_cat = {}
                for key, bm in biomarkers_raw.items():
                    cat = bm.get("category", "other")
                    if cat not in by_cat:
                        by_cat[cat] = []
                    flag = bm.get("flag", "normal")
                    flag_code = None
                    if flag == "high":
                        flag_code = "H"
                    elif flag == "low":
                        flag_code = "L"

                    val = bm.get("value_numeric")
                    if val is None:
                        val = bm.get("value")
                    decimals = 0
                    if isinstance(val, (int, float)):
                        if val != 0 and abs(val) < 1:
                            decimals = 2
                        elif abs(val) < 10:
                            decimals = 1

                    by_cat[cat].append({
                        "name": key.replace("_", " ").title(),
                        "value": d2f(val) if isinstance(val, (int, float)) else val,
                        "unit": bm.get("unit", ""),
                        "range": bm.get("ref_text", ""),
                        "flag": flag_code,
                        "decimals": decimals,
                        "category": cat_names.get(cat, cat.replace("_", " ").title()),
                    })

                for cat in cat_order:
                    if cat in by_cat:
                        biomarker_list.extend(sorted(by_cat[cat], key=lambda x: x["name"]))
                for cat in sorted(by_cat.keys()):
                    if cat not in cat_order:
                        biomarker_list.extend(sorted(by_cat[cat], key=lambda x: x["name"]))

                labs = {
                    "latest_draw_date": lab_rec.get("draw_date"),
                    "lab_provider": lab_rec.get("lab_provider"),
                    "total_draws": total_draws,
                    "biomarkers": biomarker_list,
                    "flagged_count": len(out_of_range),
                }
        except Exception as e:
            print("[WARN] Clinical: labs query failed: " + str(e))

        # --- Supplements — deduplicate to unique current stack ---
        supplements = []
        try:
            supp_7d = fetch_range("supplements",
                                  (today - timedelta(days=7)).isoformat(), yesterday)
            seen = {}
            for day_rec in supp_7d:
                for s_item in (day_rec.get("supplements") or []):
                    name = s_item.get("name", "").strip()
                    if name and name.lower() not in seen:
                        dose_str = ""
                        if s_item.get("dose") and s_item.get("unit"):
                            dose_str = str(s_item["dose"]) + " " + str(s_item["unit"])
                        elif s_item.get("dose"):
                            dose_str = str(s_item["dose"])
                        seen[name.lower()] = {
                            "name": name,
                            "dose": dose_str,
                            "timing": s_item.get("timing", ""),
                        }
            supplements = sorted(seen.values(), key=lambda x: x["name"])
        except Exception as e:
            print("[WARN] Clinical: supplements query failed: " + str(e))

        # --- Sleep 30-day averages ---
        sleep_30d = [_normalize_whoop_sleep(i) for i in fetch_range("whoop",
                                (today - timedelta(days=30)).isoformat(), yesterday)]
        s_scores = [v for v in (safe_float(r, "sleep_score") for r in sleep_30d) if v is not None]
        s_dur = [v for v in (safe_float(r, "sleep_duration_hours") for r in sleep_30d) if v is not None]
        s_eff = [v for v in (safe_float(r, "sleep_efficiency_pct") for r in sleep_30d) if v is not None]
        s_deep = [v for v in (safe_float(r, "deep_pct") for r in sleep_30d) if v is not None]
        s_rem = [v for v in (safe_float(r, "rem_pct") for r in sleep_30d) if v is not None]

        sleep_summary = {
            "avg_score": round(sum(s_scores) / len(s_scores)) if s_scores else None,
            "avg_duration_hrs": round(sum(s_dur) / len(s_dur), 1) if s_dur else None,
            "avg_efficiency": round(sum(s_eff) / len(s_eff)) if s_eff else None,
            "avg_deep_pct": round(sum(s_deep) / len(s_deep)) if s_deep else None,
            "avg_rem_pct": round(sum(s_rem) / len(s_rem)) if s_rem else None,
            "avg_bedtime": None,
            "avg_wake": None,
        }

        # --- Activity: weekly averages (last 4 weeks) ---
        strava_28d = fetch_range("strava",
                                 (today - timedelta(days=28)).isoformat(), yesterday)
        apple_28d = fetch_range("apple_health",
                                (today - timedelta(days=28)).isoformat(), yesterday)

        max_hr = profile.get("max_heart_rate", 184)
        z2_lo = max_hr * 0.60
        z2_hi = max_hr * 0.70
        total_sessions = 0
        total_z2_min = 0.0
        sport_counts = {}
        for day_rec in strava_28d:
            for act in (day_rec.get("activities") or []):
                total_sessions += 1
                sport = act.get("sport_type", "Unknown")
                sport_counts[sport] = sport_counts.get(sport, 0) + 1
                avg_hr = safe_float(act, "average_heartrate")
                dur_s = safe_float(act, "moving_time_seconds") or 0
                if avg_hr and z2_lo <= avg_hr <= z2_hi:
                    total_z2_min += dur_s / 60

        step_vals = [v for v in (safe_float(r, "steps") for r in apple_28d) if v is not None]
        top_sports = sorted(sport_counts.items(), key=lambda x: -x[1])[:3]
        primary_types = [sp[0] for sp in top_sports]

        weeks = 4.0
        activity_summary = {
            "avg_sessions_week": round(total_sessions / weeks, 1) if total_sessions else 0,
            "avg_zone2_min": round(total_z2_min / weeks) if total_z2_min else 0,
            "avg_daily_steps": round(sum(step_vals) / len(step_vals)) if step_vals else None,
            "primary_types": primary_types,
            "ctl": None,
            "tsb": data.get("tsb"),
        }

        # --- Glucose / Metabolic ---
        apple_30d = fetch_range("apple_health",
                                (today - timedelta(days=30)).isoformat(), yesterday)
        gl_avgs = [v for v in (safe_float(r, "blood_glucose_avg") for r in apple_30d) if v is not None]
        gl_tir = [v for v in (safe_float(r, "blood_glucose_time_in_range_pct") for r in apple_30d) if v is not None]
        gl_sd = [v for v in (safe_float(r, "blood_glucose_std_dev") for r in apple_30d) if v is not None]
        gl_min = [v for v in (safe_float(r, "blood_glucose_min") for r in apple_30d) if v is not None]

        glucose_summary = {
            "mean": round(sum(gl_avgs) / len(gl_avgs)) if gl_avgs else None,
            "tir_pct": round(sum(gl_tir) / len(gl_tir)) if gl_tir else None,
            "variability_sd": round(sum(gl_sd) / len(gl_sd), 1) if gl_sd else None,
            "fasting_proxy": round(sum(gl_min) / len(gl_min)) if gl_min else None,
        }

        # --- Genome flags (unfavorable + mixed only) ---
        genome_flags = []
        try:
            resp = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
                ExpressionAttributeValues={
                    ":pk": USER_PREFIX + "genome",
                    ":sk": "GENE#"
                }
            )
            for item in (resp.get("Items") or []):
                risk = item.get("risk_level", "")
                if risk in ("unfavorable", "mixed"):
                    genome_flags.append({
                        "gene": item.get("gene", ""),
                        "variant": item.get("genotype", ""),
                        "risk": risk,
                        "note": item.get("summary", ""),
                    })
            genome_flags.sort(key=lambda x: (0 if x["risk"] == "unfavorable" else 1, x["gene"]))
        except Exception as e:
            print("[WARN] Clinical: genome query failed: " + str(e))

        # --- Count active sources ---
        sources_active = 0
        source_names = ["whoop", "sleep", "macrofactor", "habitify",
                        "apple", "strava", "garmin", "supplements_today",
                        "weather_yesterday"]
        for s_name in source_names:
            if data.get(s_name):
                sources_active += 1
        if data.get("journal"):
            sources_active += 1

        # --- Assemble clinical JSON ---
        clinical = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_date": yesterday,
            "report_period": "30 days ending " + yesterday,
            "patient_name": profile.get("name", "Matthew Walker"),
            "sources_active": sources_active,
            "vitals": vitals,
            "body_comp": body_comp,
            "labs": labs,
            "supplements": supplements,
            "sleep_30d": sleep_summary,
            "activity": activity_summary,
            "glucose": glucose_summary,
            "genome_flags": genome_flags,
        }

        # Write to S3
        s3.put_object(
            Bucket=DASHBOARD_BUCKET,
            Key="dashboard/clinical.json",
            Body=json.dumps(clinical, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Clinical JSON written to s3://" + DASHBOARD_BUCKET + "/dashboard/clinical.json")

    except Exception as e:
        # Non-fatal
        print("[WARN] Clinical JSON write failed: " + str(e))


# ==============================================================================
# BUDDY ACCOUNTABILITY PAGE — DATA GENERATOR (v2.53.0)
# ==============================================================================

BUDDY_LOOKBACK_DAYS = 7


def _buddy_days_since(date_str, ref_date):
    """Days between a YYYY-MM-DD string and a date object."""
    if not date_str:
        return 99
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(date_str, "%Y-%m-%d").date() if isinstance(date_str, str) else date_str
        return (ref_date - d).days
    except Exception:
        return 99


def _buddy_friendly_date(date_str):
    """Convert YYYY-MM-DD to 'Mon Feb 27' style."""
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(date_str, "%Y-%m-%d")
        return d.strftime("%a %b %-d")
    except Exception:
        return date_str or ""


def _buddy_friendly_name(name, sport_type):
    """Make activity names more readable."""
    friendly = {
        "Walk": "Walk", "Run": "Run", "Ride": "Bike Ride",
        "VirtualRide": "Indoor Ride", "WeightTraining": "Weight Training",
        "Hike": "Hike", "Yoga": "Yoga", "Swim": "Swim",
    }
    if name == sport_type or not name:
        return friendly.get(sport_type, sport_type)
    return name


def write_buddy_json(data, profile, yesterday, character_sheet=None):
    """Generate buddy/data.json for accountability partner page."""
    try:
        today_dt = datetime.now(timezone.utc).date()
        lookback_start = (today_dt - timedelta(days=BUDDY_LOOKBACK_DAYS)).isoformat()
        lookback_end = today_dt.isoformat()

        mf_days = fetch_range("macrofactor", lookback_start, lookback_end)
        strava_days = fetch_range("strava", lookback_start, lookback_end)
        habit_days = fetch_range("habitify", lookback_start, lookback_end)
        weight_days = fetch_range("withings", lookback_start, lookback_end)

        # Food Logging Signal
        mf_logged_dates = set()
        latest_mf_date = None
        total_cals = []
        total_protein = []
        for item in mf_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            cals = safe_float(item, "total_calories_kcal") or safe_float(item, "calories") or safe_float(item, "energy_kcal")
            prot = safe_float(item, "total_protein_g") or safe_float(item, "protein_g") or safe_float(item, "protein")
            if cals and cals > 200:
                mf_logged_dates.add(date_str)
                total_cals.append(cals)
                if prot:
                    total_protein.append(prot)
                if not latest_mf_date or date_str > latest_mf_date:
                    latest_mf_date = date_str

        days_since_food = _buddy_days_since(latest_mf_date, today_dt)
        food_logged_count = len(mf_logged_dates)
        if days_since_food <= 1 and food_logged_count >= 5:
            food_status = "green"
            food_text = f"Consistent \u2014 logged meals {food_logged_count} of last {BUDDY_LOOKBACK_DAYS} days"
        elif days_since_food <= 2 and food_logged_count >= 3:
            food_status = "green"
            food_text = f"Logging food \u2014 {food_logged_count} of last {BUDDY_LOOKBACK_DAYS} days tracked"
        elif days_since_food <= 3:
            food_status = "yellow"
            food_text = f"Last food log was {days_since_food} days ago"
        else:
            food_status = "red"
            food_text = f"No food logged in {days_since_food} days \u2014 might be off track"

        food_snapshot = ""
        if total_cals:
            avg_cals = int(sum(total_cals) / len(total_cals))
            if total_protein:
                avg_prot = int(sum(total_protein) / len(total_protein))
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week with {avg_prot}g protein."
            else:
                food_snapshot = f"Averaging about {avg_cals:,} calories per day this week."

        # Exercise Signal (dedup multi-device: WHOOP + Garmin)
        # "This week" = Monday–today, resets every Monday
        monday = today_dt - timedelta(days=today_dt.weekday())  # Mon=0
        monday_str = monday.isoformat()
        day_of_week = today_dt.strftime("%A")  # e.g. "Tuesday"

        activities = []       # all 7-day activities (for highlights)
        week_activities = []  # Monday–today only (for count/status)
        latest_activity_date = None
        for item in strava_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            raw_acts = item.get("activities", [])
            acts = dedup_activities(raw_acts) if isinstance(raw_acts, list) else []
            if isinstance(acts, list):
                for a in acts:
                    sport = a.get("sport_type") or a.get("type", "Activity")
                    name = a.get("name", sport)
                    dist = safe_float(a, "distance_miles")
                    moving_sec = safe_float(a, "moving_time_seconds")
                    dur_min = int(moving_sec / 60) if moving_sec else None
                    detail_parts = []
                    if dist and dist > 0.1:
                        detail_parts.append(f"{dist:.1f} mi")
                    if dur_min:
                        detail_parts.append(f"{dur_min} min")
                    entry = {
                        "name": _buddy_friendly_name(name, sport),
                        "detail": ", ".join(detail_parts) if detail_parts else sport,
                        "date": _buddy_friendly_date(date_str),
                        "sort_date": date_str,
                    }
                    activities.append(entry)
                    if date_str >= monday_str:
                        week_activities.append(entry)
                    if not latest_activity_date or date_str > latest_activity_date:
                        latest_activity_date = date_str

        week_count = len(week_activities)
        days_since_exercise = _buddy_days_since(latest_activity_date, today_dt)
        days_into_week = today_dt.weekday() + 1  # Mon=1, Tue=2, ..., Sun=7

        if week_count >= 3:
            exercise_status = "green"
            exercise_text = f"Active \u2014 {week_count} sessions this week"
        elif week_count >= 1 and days_since_exercise <= 2:
            exercise_status = "green"
            exercise_text = f"{week_count} session{'s' if week_count != 1 else ''} so far this week"
        elif week_count >= 1:
            exercise_status = "yellow"
            exercise_text = f"{week_count} session{'s' if week_count != 1 else ''} this week, last was {days_since_exercise} days ago"
        elif days_into_week <= 2:
            # Monday or Tuesday with no sessions yet — not alarming
            exercise_status = "yellow"
            exercise_text = f"No sessions yet this week ({day_of_week})"
        else:
            exercise_status = "red"
            exercise_text = f"No exercise this week \u2014 last session {days_since_exercise} days ago"

        activities.sort(key=lambda x: x.get("sort_date", ""), reverse=True)
        activity_highlights = [
            {"name": a["name"], "detail": a["detail"], "date": a["date"]}
            for a in activities[:4]
        ]

        # Routine Signal
        latest_habit_date = None
        habit_logged_count = 0
        for item in habit_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            completed = safe_float(item, "completed_count") or safe_float(item, "total_completed")
            if completed and completed > 0:
                habit_logged_count += 1
                if not latest_habit_date or date_str > latest_habit_date:
                    latest_habit_date = date_str

        days_since_habits = _buddy_days_since(latest_habit_date, today_dt)
        if days_since_habits <= 1 and habit_logged_count >= 4:
            routine_status = "green"
            routine_text = "In his routine \u2014 habits tracked consistently"
        elif days_since_habits <= 2:
            routine_status = "green"
            routine_text = "Routine is holding, habits being logged"
        elif days_since_habits <= 3:
            routine_status = "yellow"
            routine_text = f"Habit tracking quiet for {days_since_habits} days"
        else:
            routine_status = "red"
            routine_text = f"No habit data in {days_since_habits} days \u2014 routine may have slipped"

        # Weight Signal
        weights = []
        for item in weight_days:
            date_str = (item.get("sk") or "").replace("DATE#", "")
            w = safe_float(item, "weight_lbs")
            if w and w > 100:
                weights.append((date_str, w))
        weights.sort(key=lambda x: x[0])
        latest_weight_date = weights[-1][0] if weights else None
        days_since_weigh = _buddy_days_since(latest_weight_date, today_dt)

        if len(weights) >= 2:
            delta = weights[-1][1] - weights[0][1]
            if delta < -0.5:
                weight_status = "green"
                weight_text = "Heading in the right direction"
            elif delta < 0.5:
                weight_status = "green"
                weight_text = "Weight holding steady"
            else:
                weight_status = "yellow"
                weight_text = "Weight ticked up slightly this week"
        elif len(weights) == 1:
            weight_status = "green" if days_since_weigh <= 3 else "yellow"
            weight_text = "Weighed in" + (f" {days_since_weigh} days ago" if days_since_weigh > 1 else " recently")
        else:
            weight_status = "yellow" if days_since_weigh <= 7 else "red"
            weight_text = f"No weigh-in in {days_since_weigh}+ days"

        # Beacon
        statuses = [food_status, exercise_status, routine_status, weight_status]
        red_count = statuses.count("red")
        yellow_count = statuses.count("yellow")
        if red_count >= 2:
            beacon = "red"
            beacon_label = "Check in on him"
            beacon_summary = "Multiple signals have gone quiet. He might be in a rough stretch."
            prompt = "Time to reach out. Don\u2019t make it about health data \u2014 just ask how he\u2019s really doing. Be direct but kind."
        elif red_count >= 1 or yellow_count >= 2:
            beacon = "yellow"
            beacon_label = "Might be a quiet stretch"
            beacon_summary = "A couple of things have dropped off. Probably fine, but worth a nudge."
            prompt = "A casual check-in would be good. Don\u2019t lead with the health stuff \u2014 just ask how his week\u2019s going."
        else:
            beacon = "green"
            beacon_label = "Matt's doing his thing"
            beacon_summary = "He's logging food, exercising, and sticking to his routine. All good."
            prompt = "No action needed. If you reach out, just be a mate \u2014 talk about life, not health."

        # Journey Stats
        journey_start = profile.get("journey_start_date", "2026-02-22")
        goal_weight = safe_float(profile, "goal_weight_lbs") or 185
        start_weight = safe_float(profile, "start_weight_lbs") or 302
        try:
            journey_days = (today_dt - datetime.strptime(journey_start, "%Y-%m-%d").date()).days
        except Exception:
            journey_days = 0
        current_weight = weights[-1][1] if weights else (data.get("avatar_weight") or start_weight)
        lost_lbs = round(start_weight - current_weight, 1)
        total_to_lose = start_weight - goal_weight
        pct_complete = round((lost_lbs / total_to_lose) * 100, 0) if total_to_lose > 0 else 0

        # Friendly timestamp
        try:
            now_pt = datetime.now(timezone.utc) - timedelta(hours=8)
            day_name = now_pt.strftime("%A")
            tod = "morning" if now_pt.hour < 12 else "afternoon" if now_pt.hour < 17 else "evening"
            month_day = now_pt.strftime("%B %-d")
            time_pt = now_pt.strftime("%-I:%M %p").lower().replace(" ", "")  # "9:15am"
            friendly_time = f"{day_name} {tod}, {month_day} at {time_pt} PT"
        except Exception:
            friendly_time = yesterday

        buddy_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date": yesterday,
            "beacon": beacon,
            "beacon_label": beacon_label,
            "beacon_summary": beacon_summary,
            "prompt_for_tom": prompt,
            "status_lines": [
                {"area": "Food Logging", "status": food_status, "text": food_text},
                {"area": "Exercise", "status": exercise_status, "text": exercise_text},
                {"area": "Routine", "status": routine_status, "text": routine_text},
                {"area": "Weight", "status": weight_status, "text": weight_text},
            ],
            "activity_highlights": activity_highlights,
            "food_snapshot": food_snapshot,
            "journey": {
                "days": journey_days,
                "lost_lbs": lost_lbs,
                "pct_complete": int(pct_complete),
                "goal_lbs": int(goal_weight),
            },
            "last_updated_friendly": friendly_time,
            "character_sheet": {
                "level": character_sheet.get("character_level", 1),
                "tier": character_sheet.get("character_tier"),
                "tier_emoji": character_sheet.get("character_tier_emoji"),
                "events": character_sheet.get("level_events", []),
            } if character_sheet else None,
            "avatar": _build_avatar_data(character_sheet, profile, current_weight),
        }

        s3.put_object(
            Bucket=S3_BUCKET,
            Key="buddy/data.json",
            Body=json.dumps(buddy_data, default=str),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        print("[INFO] Buddy JSON written to s3://" + S3_BUCKET + "/buddy/data.json")

    except Exception as e:
        print("[WARN] Buddy JSON write failed: " + str(e))


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


def lambda_handler(event, context):
    # Regrade mode: recompute day grades without sending email
    regrade_dates = event.get("regrade_dates")
    if regrade_dates:
        print(f"[INFO] Regrade mode: {len(regrade_dates)} dates")
        profile = fetch_profile()
        if not profile:
            return {"statusCode": 500, "body": "No profile found"}
        return _regrade_handler(regrade_dates, profile)

    demo_mode = event.get("demo_mode", False)
    print("[INFO] Daily Brief v2.59.0 (Character Sheet Integration) starting..." + (" [DEMO MODE]" if demo_mode else ""))
    profile = fetch_profile()
    if not profile:
        print("[ERROR] No profile found")
        return {"statusCode": 500, "body": "No profile found"}

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()

    data = gather_daily_data(profile, yesterday)
    print("[INFO] Date: " + yesterday + " | sources: " +
          ", ".join(k for k in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava", "mf_workouts"] if data.get(k)))

    # Deduplicate multi-device Strava activities (v2.2.2)
    strava = data.get("strava")
    if strava and strava.get("activities"):
        orig_count = len(strava["activities"])
        strava["activities"] = dedup_activities(strava["activities"])
        deduped_count = len(strava["activities"])
        if deduped_count < orig_count:
            # Recompute aggregates from deduped list
            strava["activity_count"] = deduped_count
            strava["total_moving_time_seconds"] = sum(
                float(a.get("moving_time_seconds") or 0) for a in strava["activities"])
            print("[INFO] Dedup: " + str(orig_count) + " → " + str(deduped_count) + " activities")







    try:
        day_grade_score, grade, component_scores, component_details = compute_day_grade(data, profile)
        print("[INFO] Day Grade: " + str(day_grade_score) + " (" + grade + ")")
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

    # Fetch pre-computed adaptive mode (v2.73.0 — computed by adaptive-mode-compute Lambda at 9:36 AM)
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

    # Fetch pre-computed character sheet (v2.59.0 — computed by character-sheet-compute Lambda at 9:35 AM)
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

    try:
        readiness_score, readiness_colour = compute_readiness(data)
    except Exception as e:
        print("[WARN] compute_readiness failed: " + str(e))
        readiness_score, readiness_colour = None, "gray"
    try:
        streak_data = compute_habit_streaks(profile, yesterday)
        mvp_streak = streak_data.get("tier0_streak", 0)
        full_streak = streak_data.get("tier01_streak", 0)
        vice_streaks = streak_data.get("vice_streaks", {})
    except Exception as e:
        print("[WARN] compute_habit_streaks failed: " + str(e))
        mvp_streak, full_streak, vice_streaks = 0, 0, {}

    # Store tier-level habit scores for historical trending (v2.47.0)
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
            bod_insight = call_board_of_directors(data, profile, day_grade_score, grade, component_scores, api_key, character_sheet=character_sheet, brief_mode=brief_mode)
            print("[INFO] BoD: " + bod_insight[:80])
        except Exception as e:
            print("[WARN] BoD failed: " + str(e))

        try:
            training_nutrition = call_training_nutrition_coach(data, profile, api_key)
            print("[INFO] Training/Nutrition coach returned")
        except Exception as e:
            print("[WARN] Training/Nutrition coach failed: " + str(e))

        if data.get("journal_entries"):
            try:
                journal_coach_text = call_journal_coach(data, profile, api_key)
                print("[INFO] Journal coach: " + (journal_coach_text[:80] if journal_coach_text else "empty"))
            except Exception as e:
                print("[WARN] Journal coach failed: " + str(e))

        try:
            tldr_guidance = call_tldr_and_guidance(data, profile, day_grade_score, grade,
                                                    component_scores, component_details,
                                                    readiness_score, readiness_colour, api_key)
            print("[INFO] TL;DR+Guidance: " + str(tldr_guidance.get("tldr", ""))[:80])
        except Exception as e:
            print("[WARN] TL;DR+Guidance failed: " + str(e))

    try:
        html = build_html(data, profile, day_grade_score, grade, component_scores, component_details,
                          readiness_score, readiness_colour, tldr_guidance, bod_insight,
                          training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks,
                          character_sheet=character_sheet, brief_mode=brief_mode,
                          engagement_score=engagement_score)
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

    # Demo mode: sanitize HTML and prefix subject
    if demo_mode:
        html = sanitize_for_demo(html, data, profile)
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

    # Write dashboard JSON to S3 (non-fatal)
    if not demo_mode:
        write_dashboard_json(data, profile, day_grade_score, grade, component_scores,
                             readiness_score, readiness_colour, tldr_guidance, yesterday,
                             component_details=component_details, character_sheet=character_sheet)
        write_clinical_json(data, profile, yesterday)
        write_buddy_json(data, profile, yesterday, character_sheet=character_sheet)

    return {"statusCode": 200, "body": "Daily brief v2.2 sent: " + subject}
