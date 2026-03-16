"""
Weekly Digest Lambda — v4.0.0 (Weekly Digest v2)
Fires Sunday 8:30 AM PT via EventBridge.

Major rewrite from v3.3.0:
  - Day grade weekly trend (from retrocomputed grades)
  - Profile-driven targets (all from PROFILE#v1, no hardcoded constants)
  - Habitify replaces Chronicling for habits
  - MacroFactor workouts replaces Hevy for strength
  - Apple Health CGM/gait/steps/water summary
  - Batch range queries (faster)
  - Updated scorecard (8 components matching daily brief)
  - Updated Board of Directors prompt with grade context
  - Strava activity dedup

Sections:
  1. Day Grade Weekly Trend (NEW)
  2. Scorecard (8 components)
  3. Insight of the Week (AI)
  4. Board of Directors (6 advisors)
  5. Training (Strava + MacroFactor workouts)
  6. Training Load — Banister
  7. Recovery & HRV (Whoop)
  8. Sleep & Architecture (Eight Sleep)
  9. Habits (Habitify MVP + groups)
  10. Nutrition (MacroFactor)
  11. Weight & Body Composition
  12. CGM & Glucose (Apple Health)
  13. Journal & Mood (Notion)
  14. Productivity (Todoist)
  15. Open Insights
"""

import json
import math
import statistics
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

import os

# ── Shared digest utilities (digest_utils.py) ───────────────────────────────
from digest_utils import (
    d2f, avg, fmt, fmt_num, safe_float,
    dedup_activities,
    _normalize_whoop_sleep,
    compute_confidence,     # BS-05: confidence badges
)

# ── AWS clients ───────────────────────────────────────────────────────────────
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]
SENDER     = os.environ["EMAIL_SENDER"]
USER_ID    = os.environ["USER_ID"]

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)
secrets  = boto3.client("secretsmanager", region_name=_REGION)

# IC-15/16: Insight Ledger — progressive context + insight persistence
try:
    import insight_writer
    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False

# AI-3: Output validation
try:
    from ai_output_validator import validate_ai_output, AIOutputType
    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# OBS-1: Structured logger
try:
    from platform_logger import get_logger
    logger = get_logger("weekly-digest")
except ImportError:
    import logging as _log
    logger = _log.getLogger("weekly-digest")
    logger.setLevel(_log.INFO)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_anthropic_key():
    secret = secrets.get_secret_value(SecretId=os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys"))
    return json.loads(secret["SecretString"])["anthropic_api_key"]

# d2f, avg, fmt, fmt_num, safe_float imported from digest_utils

def fetch_profile():
    try:
        r = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        print(f"[ERROR] fetch_profile: {e}")
        return {}

def query_range(source, start_date, end_date):
    """Batch query all records for a source in a date range."""
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk, ":s": f"DATE#{start_date}", ":e": f"DATE#{end_date}",
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item.get("date") or item["sk"].replace("DATE#", "")
            records[date_str] = d2f(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records

def query_journal_range(start_date, end_date):
    """Query all journal entries in a range."""
    entries_by_date = defaultdict(list)
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": f"USER#{USER_ID}#SOURCE#notion",
            ":s": f"DATE#{start_date}#journal#",
            ":e": f"DATE#{end_date}#journal#zzz",
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item["sk"].split("#")[1]
            entries_by_date[date_str].append(d2f(item))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return dict(entries_by_date)

def delta_html(cur, prev, unit="", dec=1, invert=False):
    if cur is None or prev is None: return ""
    diff = round(cur - prev, dec)
    if diff == 0: return '<span style="color:#888;font-size:11px;"> →0</span>'
    better = (diff < 0) if invert else (diff > 0)
    color = "#27ae60" if better else "#e74c3c"
    arrow = "↑" if diff > 0 else "↓"
    return f'<span style="color:{color};font-size:11px;"> {arrow}{abs(diff)}{unit}</span>'

def hit_bar(pct, color="#27ae60"):
    if pct is None: return "—"
    w = max(0, min(100, pct))
    return (f'<span style="font-weight:600;">{pct}%</span> '
            f'<span style="display:inline-block;width:80px;height:8px;background:#eee;'
            f'border-radius:4px;vertical-align:middle;">'
            f'<span style="display:inline-block;width:{w}%;height:8px;background:{color};'
            f'border-radius:4px;"></span></span>')


# ══════════════════════════════════════════════════════════════════════════════
# STRAVA DEDUP (from daily brief v2.2.3)
# ══════════════════════════════════════════════════════════════════════════════

# dedup_activities imported from digest_utils


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTORS — return summarized dicts from raw records
# ══════════════════════════════════════════════════════════════════════════════

def ex_day_grades(grades_dict):
    """Extract day grade summary from {date: record} dict."""
    if not grades_dict:
        return None
    days = []
    for date_str in sorted(grades_dict.keys()):
        rec = grades_dict[date_str]
        score = safe_float(rec, "total_score")
        grade = rec.get("letter_grade", "—")
        if score is not None:
            days.append({"date": date_str, "score": score, "grade": grade})
    if not days:
        return None
    scores = [d["score"] for d in days]
    grade_counts = defaultdict(int)
    for d in days:
        g = d["grade"]
        if g.startswith("A"): grade_counts["A"] += 1
        elif g.startswith("B"): grade_counts["B"] += 1
        elif g.startswith("C"): grade_counts["C"] += 1
        elif g == "D": grade_counts["D"] += 1
        elif g == "F": grade_counts["F"] += 1
    return {
        "days": days,
        "avg_score": avg(scores),
        "min_score": min(scores),
        "max_score": max(scores),
        "grade_counts": dict(grade_counts),
        "days_graded": len(days),
    }


def ex_whoop(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    hrvs = [float(r["hrv"]) for r in recs if "hrv" in r]
    recoveries = [float(r["recovery_score"]) for r in recs if "recovery_score" in r]
    rhrs = [float(r["resting_heart_rate"]) for r in recs if "resting_heart_rate" in r]
    strains = [float(r["strain"]) for r in recs if "strain" in r]
    return {"hrv_avg": avg(hrvs), "hrv_min": min(hrvs, default=None),
            "hrv_max": max(hrvs, default=None),
            "recovery_avg": avg(recoveries), "recovery_min": min(recoveries, default=None),
            "rhr_avg": avg(rhrs), "strain_avg": avg(strains), "days": len(recs)}


# _normalize_whoop_sleep imported from digest_utils


def ex_whoop_sleep(recs_dict):
    """Extract sleep metrics from Whoop records (SOT for sleep duration/staging v2.55.0)."""
    recs = [_normalize_whoop_sleep(r) for r in (recs_dict.values() if recs_dict else [])]
    if not recs: return None
    scores = [float(r["sleep_score"]) for r in recs if "sleep_score" in r]
    durs = []
    for r in recs:
        d = safe_float(r, "sleep_duration_hours")
        if d is not None: durs.append(d)
    effs = [safe_float(r, "sleep_efficiency_pct") for r in recs]
    effs = [e for e in effs if e is not None]
    deep_pcts = [float(r["deep_pct"]) for r in recs if "deep_pct" in r]
    rem_pcts = [float(r["rem_pct"]) for r in recs if "rem_pct" in r]
    return {"score_avg": avg(scores), "score_min": min(scores, default=None),
            "duration_avg_hrs": avg(durs), "efficiency_avg": avg(effs),
            "deep_pct": avg(deep_pcts), "rem_pct": avg(rem_pcts),
            "nights": len(recs)}


def ex_withings(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    weights = [float(r["weight_lbs"]) for r in recs if "weight_lbs" in r]
    bodyfats = [float(r["body_fat_pct"]) for r in recs if "body_fat_pct" in r]
    sr = sorted(recs, key=lambda r: r.get("sk", ""), reverse=True)
    return {"weight_latest": float(sr[0]["weight_lbs"]) if sr and "weight_lbs" in sr[0] else None,
            "weight_avg": avg(weights), "weight_min": min(weights, default=None),
            "weight_max": max(weights, default=None), "body_fat_avg": avg(bodyfats),
            "measurements": len(recs)}


def ex_strava(recs_dict, profile):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    max_hr = profile.get("max_heart_rate", 186)
    z2_low = max_hr * 0.60
    z2_high = max_hr * 0.70
    acts = []
    zone2_mins = 0
    daily_loads = []
    for r in recs:
        day_kj = 0
        day_acts = r.get("activities", [])
        day_acts = dedup_activities(day_acts)
        for a in day_acts:
            hr = float(a.get("average_heartrate") or 0)
            secs = float(a.get("moving_time_seconds") or 0)
            kj = float(a.get("kilojoules") or 0)
            day_kj += kj
            obj = {"date": r.get("date", ""),
                   "name": a.get("enriched_name") or a.get("name", ""),
                   "sport": a.get("sport_type", ""),
                   "miles": round(float(a.get("distance_miles") or 0), 1),
                   "elev": round(float(a.get("total_elevation_gain_feet") or 0)),
                   "hr": round(hr) if hr else None,
                   "mins": round(secs / 60), "kj": kj}
            acts.append(obj)
            if hr and z2_low <= hr <= z2_high:
                zone2_mins += obj["mins"]
        if day_kj > 0: daily_loads.append(day_kj)
    total_mins = sum(a["mins"] for a in acts)
    z2_pct = round(zone2_mins / total_mins * 100) if total_mins else 0
    mono = round(statistics.mean(daily_loads) / statistics.stdev(daily_loads), 2) \
        if len(daily_loads) >= 3 and statistics.stdev(daily_loads) > 0 else None
    return {"total_miles": round(sum(a["miles"] for a in acts), 1),
            "total_elevation_feet": round(sum(a["elev"] for a in acts)),
            "total_minutes": total_mins, "activity_count": len(acts),
            "zone2_minutes": round(zone2_mins), "zone2_pct": z2_pct,
            "zone2_target": 150, "zone2_hr_range": f"{round(z2_low)}-{round(z2_high)}",
            "training_monotony": mono, "activities": acts}


def ex_macrofactor(recs_dict, profile):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    cal_target = profile.get("calorie_target", 1800)
    prot_target = profile.get("protein_target_g", 190)
    cals = [float(r["total_calories_kcal"]) for r in recs if "total_calories_kcal" in r]
    prots = [float(r["total_protein_g"]) for r in recs if "total_protein_g" in r]
    fats = [float(r["total_fat_g"]) for r in recs if "total_fat_g" in r]
    carbs = [float(r["total_carbs_g"]) for r in recs if "total_carbs_g" in r]
    fibers = [float(r["total_fiber_g"]) for r in recs if "total_fiber_g" in r]
    return {
        "calories_avg": avg(cals), "protein_avg_g": avg(prots),
        "fat_avg_g": avg(fats), "carbs_avg_g": avg(carbs), "fiber_avg_g": avg(fibers),
        "days_logged": len(recs),
        "protein_hit_rate": round(sum(1 for p in prots if p >= prot_target) / len(prots) * 100) if prots else None,
        "calorie_hit_rate": round(sum(1 for c in cals if c <= cal_target * 1.10) / len(cals) * 100) if cals else None,
        "protein_target": prot_target, "calorie_target": cal_target,
    }


def ex_macrofactor_workouts(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    workouts = []
    total_vol = 0
    total_sets = 0
    for r in recs:
        for w in r.get("workouts", []):
            wk = {"date": r.get("date", ""), "name": w.get("workout_name", "Workout"),
                  "exercises": len(w.get("exercises", [])),
                  "volume_lbs": round(float(w.get("total_volume_lbs") or 0))}
            workouts.append(wk)
        total_vol += float(r.get("total_volume_lbs") or 0)
        total_sets += int(r.get("total_sets") or 0)
    if not workouts: return None
    return {"workout_count": len(workouts), "workouts": workouts,
            "total_volume_lbs": round(total_vol), "total_sets": total_sets,
            "best_workout": max(workouts, key=lambda w: w["volume_lbs"], default=None)}


def ex_habitify(recs_dict, profile):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    mvp_list = profile.get("mvp_habits", [])
    daily_mvp_pcts = []
    daily_overall_pcts = []
    mvp_completion = defaultdict(int)  # habit_name -> days completed
    mvp_days_available = 0
    for r in recs:
        habits_map = r.get("habits", {})
        if not habits_map: continue
        mvp_days_available += 1
        mvp_done = 0
        for h in mvp_list:
            done = habits_map.get(h, 0)
            if done is not None and float(done) >= 1:
                mvp_done += 1
                mvp_completion[h] += 1
        if mvp_list:
            daily_mvp_pcts.append(mvp_done / len(mvp_list) * 100)
        comp = safe_float(r, "completion_pct")
        if comp is not None:
            daily_overall_pcts.append(comp * 100)
    return {
        "mvp_avg_pct": avg(daily_mvp_pcts),
        "overall_avg_pct": avg(daily_overall_pcts),
        "mvp_completion": dict(mvp_completion),
        "mvp_total": len(mvp_list),
        "days_tracked": mvp_days_available,
    }


def ex_apple_health(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    steps = [float(r["steps"]) for r in recs if "steps" in r]
    water = [float(r["water_intake_ml"]) for r in recs if "water_intake_ml" in r and float(r.get("water_intake_ml", 0)) >= 118]
    glucose_avgs = [float(r["blood_glucose_avg"]) for r in recs if "blood_glucose_avg" in r]
    tir_vals = [float(r["blood_glucose_time_in_range_pct"]) for r in recs if "blood_glucose_time_in_range_pct" in r]
    gait_speeds = [float(r["walking_speed_mph"]) for r in recs if "walking_speed_mph" in r]
    return {
        "steps_avg": avg(steps), "steps_total": round(sum(steps)) if steps else None,
        "water_avg_ml": avg(water), "water_days": len(water),
        "glucose_avg": avg(glucose_avgs), "glucose_tir_avg": avg(tir_vals),
        "glucose_days": len(glucose_avgs),
        "gait_speed_avg": avg(gait_speeds), "gait_days": len(gait_speeds),
        "days": len(recs),
    }


def ex_todoist(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    c = [int(r.get("tasks_completed", 0)) for r in recs]
    return {"tasks_completed": sum(c), "avg_per_day": avg(c), "days": len(recs)}


def ex_journal(entries_by_date):
    """Extract journal signals from {date: [entries]} dict."""
    if not entries_by_date: return None
    mood_scores, energy_scores, stress_scores = [], [], []
    all_themes, all_emotions, all_avoidance, all_cognitive = [], [], [], []
    notable_quotes = []
    templates_count = {}
    daily_mood = {}
    total_entries = 0
    for date_str, entries in entries_by_date.items():
        for entry in entries:
            total_entries += 1
            template = str(entry.get("template", ""))
            templates_count[template] = templates_count.get(template, 0) + 1
            m = entry.get("enriched_mood")
            e = entry.get("enriched_energy")
            s = entry.get("enriched_stress")
            if m is not None:
                mood_scores.append(float(m))
                daily_mood.setdefault(date_str, []).append(float(m))
            if e is not None: energy_scores.append(float(e))
            if s is not None: stress_scores.append(float(s))
            if m is None:
                for field in ("morning_mood", "day_rating"):
                    val = entry.get(field)
                    if val is not None:
                        mood_scores.append(float(val))
                        daily_mood.setdefault(date_str, []).append(float(val))
                        break
            if e is None:
                for field in ("morning_energy", "energy_eod"):
                    val = entry.get(field)
                    if val is not None: energy_scores.append(float(val)); break
            if s is None:
                val = entry.get("stress_level")
                if val is not None: stress_scores.append(float(val))
            for t in (entry.get("enriched_themes") or []): all_themes.append(str(t))
            for em in (entry.get("enriched_emotions") or []): all_emotions.append(str(em))
            for av in (entry.get("enriched_avoidance_flags") or []): all_avoidance.append(str(av))
            for cp in (entry.get("enriched_cognitive_patterns") or []): all_cognitive.append(str(cp))
            q = entry.get("enriched_notable_quote")
            if q: notable_quotes.append({"date": date_str, "quote": str(q)})
    if total_entries == 0: return None
    theme_freq = defaultdict(int)
    for t in all_themes: theme_freq[t] += 1
    emotion_freq = defaultdict(int)
    for em in all_emotions: emotion_freq[em] += 1
    daily_mood_avg = {d: round(sum(v)/len(v), 1) for d, v in daily_mood.items() if v}
    best_day = max(daily_mood_avg.items(), key=lambda x: x[1], default=(None, None))
    worst_day = min(daily_mood_avg.items(), key=lambda x: x[1], default=(None, None))
    return {
        "mood_avg": avg(mood_scores), "energy_avg": avg(energy_scores),
        "stress_avg": avg(stress_scores), "entries": total_entries,
        "days_journaled": len(entries_by_date),
        "top_themes": sorted(theme_freq.items(), key=lambda x: -x[1])[:6],
        "top_emotions": sorted(emotion_freq.items(), key=lambda x: -x[1])[:6],
        "avoidance_flags": list(dict.fromkeys(all_avoidance))[:5],
        "cognitive_patterns": list(dict.fromkeys(all_cognitive))[:5],
        "notable_quotes": notable_quotes[:3],
        "best_mood_day": {"date": best_day[0], "score": best_day[1]} if best_day[0] else None,
        "worst_mood_day": {"date": worst_day[0], "score": worst_day[1]} if worst_day[0] else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CHARACTER SHEET EXTRACTION (v2.71.0)
# ══════════════════════════════════════════════════════════════════════════════

def ex_character_sheet(recs_dict):
    """Extract weekly character sheet summary from pre-computed records."""
    if not recs_dict:
        return None

    pillar_order = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    tier_order = ["Foundation", "Momentum", "Discipline", "Mastery", "Elite"]
    dates = sorted(recs_dict.keys())
    latest = recs_dict[dates[-1]] if dates else {}
    earliest = recs_dict[dates[0]] if dates else {}

    levels = [recs_dict[d].get("character_level", 0) for d in dates]
    start_level = levels[0] if levels else 0
    end_level = levels[-1] if levels else 0

    all_events = []
    for d in dates:
        for ev in recs_dict[d].get("level_events", []):
            all_events.append({**ev, "date": d})

    pillar_summary = {}
    for p in pillar_order:
        start_pd = earliest.get(f"pillar_{p}", {})
        end_pd = latest.get(f"pillar_{p}", {})
        xp_earned = sum(recs_dict[d].get(f"pillar_{p}", {}).get("xp_delta", 0) for d in dates)
        raw_scores = [recs_dict[d].get(f"pillar_{p}", {}).get("raw_score") for d in dates]
        raw_scores = [r for r in raw_scores if r is not None]
        avg_raw = round(sum(raw_scores) / len(raw_scores), 1) if raw_scores else None

        pillar_summary[p] = {
            "start_level": start_pd.get("level", 0),
            "end_level": end_pd.get("level", 0),
            "level_delta": end_pd.get("level", 0) - start_pd.get("level", 0),
            "tier": end_pd.get("tier", "Foundation"),
            "tier_emoji": end_pd.get("tier_emoji", "\U0001f528"),
            "xp_earned": xp_earned,
            "avg_raw": avg_raw,
        }

    # Closest to next tier transition
    closest_to_tier = None
    min_gap = 999
    for p in pillar_order:
        end_pd = latest.get(f"pillar_{p}", {})
        level = end_pd.get("level", 0)
        tier = end_pd.get("tier", "Foundation")
        tier_idx = tier_order.index(tier) if tier in tier_order else 0
        if tier_idx < len(tier_order) - 1:
            next_min = [1, 21, 41, 61, 81][tier_idx + 1]
            gap = next_min - level
            if 0 < gap < min_gap:
                min_gap = gap
                closest_to_tier = {
                    "pillar": p, "current_level": level,
                    "current_tier": tier, "next_tier": tier_order[tier_idx + 1],
                    "levels_needed": gap,
                }

    return {
        "character_level_start": start_level,
        "character_level_end": end_level,
        "character_level_delta": end_level - start_level,
        "character_tier": latest.get("character_tier", "Foundation"),
        "character_tier_emoji": latest.get("character_tier_emoji", "\U0001f528"),
        "character_xp": latest.get("character_xp", 0),
        "pillar_summary": pillar_summary,
        "events": all_events,
        "closest_to_tier": closest_to_tier,
        "days_with_data": len(dates),
        "active_effects": latest.get("active_effects", []),
    }


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING LOAD (Banister)
# ══════════════════════════════════════════════════════════════════════════════

def compute_banister(strava_60d):
    kj = {}
    for date_str, r in strava_60d.items():
        acts = dedup_activities(r.get("activities", []))
        kj[date_str] = sum(float(a.get("kilojoules") or 0) for a in acts)
    today = datetime.now(timezone.utc).date()
    ctl = atl = 0.0
    cd, ad = math.exp(-1/42), math.exp(-1/7)
    for i in range(59, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        load = kj.get(day, 0)
        ctl = ctl * cd + load * (1 - cd)
        atl = atl * ad + load * (1 - ad)
    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)}


# ══════════════════════════════════════════════════════════════════════════════
# 4-WEEK TRENDS
# ══════════════════════════════════════════════════════════════════════════════

def compute_4week_trends(weekly_data):
    """Given 4 weeks of extracted data (newest first), compute trend arrows."""
    trends = {}
    for metric, source, field in [
        ("weight", "withings", "weight_avg"),
        ("hrv", "whoop", "hrv_avg"),
        ("recovery", "whoop", "recovery_avg"),
        ("sleep", "sleep", "score_avg"),
        ("rhr", "whoop", "rhr_avg"),
        ("day_grade", "day_grades", "avg_score"),
    ]:
        vals = []
        for wk in weekly_data.get(source, []):
            vals.append(wk.get(field) if wk else None)
        v = [x for x in vals if x is not None]
        if len(v) < 2:
            trends[metric] = "→"
        else:
            slope = v[0] - v[-1]
            trends[metric] = "→" if abs(slope) < 0.5 else ("↑" if slope > 0 else "↓")
    return trends


# ══════════════════════════════════════════════════════════════════════════════
# WEIGHT PROJECTION
# ══════════════════════════════════════════════════════════════════════════════

def weight_projection(w4_weight_avgs, goal_weight, current_weight):
    vals = [w for w in w4_weight_avgs if w is not None]
    if len(vals) < 2 or current_weight is None or goal_weight is None:
        return None
    total_delta = vals[0] - vals[-1]
    if abs(total_delta) < 0.5:
        return {"status": "insufficient_data"}
    rate_per_week = total_delta / (len(vals) - 1)
    if rate_per_week >= 0:
        return {"status": "not_losing"}
    weeks_to_goal = (current_weight - goal_weight) / abs(rate_per_week)
    eta = datetime.now(timezone.utc).date() + timedelta(weeks=weeks_to_goal)
    return {"status": "ok", "weeks": round(weeks_to_goal),
            "rate_per_week": round(abs(rate_per_week), 1), "eta": eta.strftime("%B %Y")}


# ══════════════════════════════════════════════════════════════════════════════
# SLEEP DEBT
# ══════════════════════════════════════════════════════════════════════════════

def compute_sleep_debt(whoop_dict, target_hrs=7.5):
    """Compute 7-day sleep debt from Whoop records (SOT for sleep duration v2.55.0)."""
    if not whoop_dict: return None
    durs = []
    for r in whoop_dict.values():
        d = safe_float(r, "sleep_duration_hours")
        if d is not None: durs.append(d)
    if not durs: return None
    debt = round(max(0, (target_hrs * len(durs)) - sum(durs)), 1)
    return {"debt_hrs": debt, "nights": len(durs), "avg_hrs": avg(durs), "target_hrs": target_hrs}


# ══════════════════════════════════════════════════════════════════════════════
# OPEN INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_stale_insights(days_threshold=7):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": f"USER#{USER_ID}#SOURCE#insights",
                ":s": "INSIGHT#0", ":e": "INSIGHT#z"})
        items = r.get("Items", [])
    except Exception as e:
        print(f"[WARN] fetch_stale_insights: {e}")
        return []
    now = datetime.now(timezone.utc)
    stale = []
    for item in items:
        if str(item.get("status", "")).lower() != "open": continue
        saved = item.get("date_saved", "")
        try:
            saved_dt = datetime.fromisoformat(saved.replace("Z", "+00:00"))
            days_open = (now - saved_dt).days
        except Exception: days_open = 0
        if days_open >= days_threshold:
            stale.append({"text": str(item.get("text", "")),
                          "date_saved": saved[:10], "days_open": days_open,
                          "tags": [str(t) for t in (item.get("tags") or [])]})
    stale.sort(key=lambda x: x["days_open"], reverse=True)
    return stale


# ══════════════════════════════════════════════════════════════════════════════
# DATA ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def gather_all():
    today = datetime.now(timezone.utc).date()
    # This week = yesterday back 7 days; prior week = 8-14 days back
    w1_end = (today - timedelta(days=1)).isoformat()
    w1_start = (today - timedelta(days=7)).isoformat()
    w2_end = (today - timedelta(days=8)).isoformat()
    w2_start = (today - timedelta(days=14)).isoformat()
    w3_start = (today - timedelta(days=21)).isoformat()
    w4_start = (today - timedelta(days=28)).isoformat()

    print(f"[INFO] This week: {w1_start} → {w1_end}")
    print(f"[INFO] Prior week: {w2_start} → {w2_end}")

    profile = fetch_profile()
    if not profile:
        print("[ERROR] No profile found")
        return None, None

    # ── Batch query all sources for this week + prior week ──
    sources = ["whoop", "eightsleep", "strava", "apple_health",
               "macrofactor", "macrofactor_workouts", "withings",
               "habitify", "todoist", "garmin", "day_grade"]
    raw_this = {}
    raw_prior = {}
    for src in sources:
        full = query_range(src, w4_start, w1_end)  # get 4 weeks in one query
        raw_this[src] = {d: r for d, r in full.items() if w1_start <= d <= w1_end}
        raw_prior[src] = {d: r for d, r in full.items() if w2_start <= d <= w2_end}
        print(f"  {src}: {len(raw_this[src])} this week, {len(raw_prior[src])} prior")

    # Journal entries
    journal_this = query_journal_range(w1_start, w1_end)
    journal_prior = query_journal_range(w2_start, w2_end)
    print(f"  journal: {len(journal_this)} days this week, {len(journal_prior)} prior")

    # ── Extract this week + prior week ──
    this = {
        "day_grades": ex_day_grades(raw_this["day_grade"]),
        "whoop": ex_whoop(raw_this["whoop"]),
        "sleep": ex_whoop_sleep(raw_this["whoop"]),
        "strava": ex_strava(raw_this["strava"], profile),
        "apple": ex_apple_health(raw_this["apple_health"]),
        "macrofactor": ex_macrofactor(raw_this["macrofactor"], profile),
        "mf_workouts": ex_macrofactor_workouts(raw_this["macrofactor_workouts"]),
        "withings": ex_withings(raw_this["withings"]),
        "habitify": ex_habitify(raw_this["habitify"], profile),
        "todoist": ex_todoist(raw_this["todoist"]),
        "journal": ex_journal(journal_this),
    }
    prior = {
        "day_grades": ex_day_grades(raw_prior["day_grade"]),
        "whoop": ex_whoop(raw_prior["whoop"]),
        "sleep": ex_whoop_sleep(raw_prior["whoop"]),
        "strava": ex_strava(raw_prior["strava"], profile),
        "apple": ex_apple_health(raw_prior["apple_health"]),
        "macrofactor": ex_macrofactor(raw_prior["macrofactor"], profile),
        "mf_workouts": ex_macrofactor_workouts(raw_prior["macrofactor_workouts"]),
        "withings": ex_withings(raw_prior["withings"]),
        "habitify": ex_habitify(raw_prior["habitify"], profile),
        "todoist": ex_todoist(raw_prior["todoist"]),
        "journal": ex_journal(journal_prior),
    }

    # ── 4-week trends ──
    # Build weekly extractions for weeks 3 and 4
    raw_w3 = {src: {d: r for d, r in query_range(src, w3_start, w2_start).items()
                     if w3_start <= d < w2_start} for src in ["day_grade"]}
    # Reuse data already queried (4 weeks in one shot above)
    full_data = {}
    for src in sources:
        full = query_range(src, w4_start, w1_end)
        full_data[src] = full

    def extract_week(src_data, start, end):
        return {d: r for d, r in src_data.items() if start <= d <= end}

    w3_end = (today - timedelta(days=15)).isoformat()
    w4_end = (today - timedelta(days=22)).isoformat()

    weekly_extractions = {}
    for src_key, extractor, src_name in [
        ("whoop", ex_whoop, "whoop"),
        ("sleep", ex_whoop_sleep, "whoop"),
        ("withings", ex_withings, "withings"),
    ]:
        weeks = []
        for ws, we in [(w1_start, w1_end), (w2_start, w2_end), (w3_start, w3_end), (w4_start, w4_end)]:
            week_data = extract_week(full_data.get(src_name, {}), ws, we)
            weeks.append(extractor(week_data))
        weekly_extractions[src_key] = weeks

    # Day grade 4-week
    dg_weeks = []
    for ws, we in [(w1_start, w1_end), (w2_start, w2_end), (w3_start, w3_end), (w4_start, w4_end)]:
        week_data = extract_week(full_data.get("day_grade", {}), ws, we)
        dg_weeks.append(ex_day_grades(week_data))
    weekly_extractions["day_grades"] = dg_weeks

    trends = compute_4week_trends(weekly_extractions)

    # ── Banister (60-day Strava) ──
    strava_60d = query_range("strava", (today - timedelta(days=60)).isoformat(), w1_end)
    training_load = compute_banister(strava_60d)

    # ── Sleep debt ──
    sleep_debt = compute_sleep_debt(raw_this["whoop"],
                                     profile.get("sleep_target_hours_ideal", 7.5))

    # ── Weight projection ──
    w4_weight_avgs = []
    for wk in weekly_extractions.get("withings", []):
        w4_weight_avgs.append(wk.get("weight_avg") if wk else None)
    cur_weight = this["withings"]["weight_latest"] if this.get("withings") else None
    goal = profile.get("goal_weight_lbs", 185)
    projection = weight_projection(w4_weight_avgs, goal, cur_weight)

    # Open insights
    open_insights = fetch_stale_insights(days_threshold=7)

    # ── Character Sheet (Phase 4 v2.71.0) ──
    cs_this_raw = query_range("character_sheet", w1_start, w1_end)
    cs_prior_raw = query_range("character_sheet", w2_start, w2_end)
    character_sheet = ex_character_sheet(cs_this_raw)
    character_sheet_prior = ex_character_sheet(cs_prior_raw)
    print(f"  character_sheet: {len(cs_this_raw)} days this week, {len(cs_prior_raw)} prior")

    return {
        "this": this, "prior": prior, "profile": profile,
        "training_load": training_load, "trends": trends,
        "sleep_debt": sleep_debt, "projection": projection,
        "open_insights": open_insights,
        "character_sheet": character_sheet,
        "character_sheet_prior": character_sheet_prior,
        "dates": {"this_start": w1_start, "this_end": w1_end,
                  "prior_start": w2_start, "prior_end": w2_end},
    }, profile


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HAIKU — BOARD OF DIRECTORS
# ══════════════════════════════════════════════════════════════════════════════

BOARD_PROMPT = """You are the coordinating intelligence for Matthew's Weekly Health Board of Advisors.

CONTEXT:
Matthew Walker, 36, Seattle. Senior Director at a SaaS company. Goal: lose ~117 lbs (302→185),
build muscle, improve sleep and stress management. He tracks obsessively but struggles with consistency.

{journey_context}

DAY GRADES THIS WEEK (0-100 composite of sleep, recovery, nutrition, movement, habits, hydration, journal, glucose):
{grade_summary}

{previous_insights}

THIS WEEK'S DATA vs PRIOR WEEK (+ 4-week trends):
{data_json}

RULES:
- Do NOT summarise numbers Matthew can already read.
- DO identify patterns, causes, and cross-domain interactions.
- Reference specific numbers only when they illuminate a pattern.
- If data is missing, say so — do not fabricate insight.
- Be direct. Name problems. Celebrate wins briefly.
- Each advisor must NOT repeat other sections.

Write exactly these six sections with these exact headers:

🏋️ DR. SARAH CHEN — SPORTS SCIENTIST
Training quality, Zone 2 adequacy, TSB/CTL/ATL, periodisation, recovery. Is Matthew building fitness or just accumulating fatigue? What does the Banister model + day grades say about his readiness?

🥗 DR. MARCUS WEBB — NUTRITIONIST
Calorie/protein adherence, macro balance, meal timing patterns. Is nutrition supporting or undermining training and recovery? Reference hit rates and specific shortfalls.

😴 DR. LISA PARK — SLEEP & CIRCADIAN SPECIALIST
Sleep architecture (REM%, deep%), efficiency, sleep debt, upstream causes. What's driving sleep quality — duration, architecture, or efficiency? Connect to training load and day grades.

🩺 DR. JAMES OKAFOR — LONGEVITY & PREVENTIVE MEDICINE
Long-term trajectory. What does the 4-week trend say? What leading indicator is most encouraging or concerning? What data gaps matter most?

🧠 COACH MAYA RODRIGUEZ — BEHAVIOURAL PERFORMANCE
The gap between knowing and doing. Where did Matthew underperform vs his own standards? Use journal data (mood, themes, avoidance flags, cognitive patterns) + habit data + day grades to connect subjective experience with objective performance. Be direct and human.

🎯 THE CHAIR — VERDICT & PRIORITY
4–6 sentences. Clear verdict. Reference day grade average and trend. Name ONE priority for next week with specific data justification. One sentence of genuine encouragement grounded in data.

💡 INSIGHT OF THE WEEK
One sentence. Concrete. Specific. Actionable in 7 days. Must reference actual numbers.

Be honest. Be a coach, not a cheerleader."""


def call_anthropic_with_retry(req, timeout=55, max_attempts=None, backoff_s=None):
    # Delegates to retry_utils for exponential backoff + CloudWatch metrics (P1.8/P1.9)
    import retry_utils
    return retry_utils.call_anthropic_raw(req, timeout=timeout)


def call_haiku(data, profile, api_key):
    clean = d2f(data)
    pd = json.loads(json.dumps(clean))
    # Trim activities for token economy
    for wk in ("this", "prior"):
        if pd.get(wk, {}).get("strava"):
            pd[wk]["strava"]["activities"] = pd[wk]["strava"].get("activities", [])[:5]

    # Build grade summary
    grades = data.get("this", {}).get("day_grades")
    grade_lines = []
    if grades and grades.get("days"):
        for d in grades["days"]:
            grade_lines.append(f"  {d['date']}: {d['score']} ({d['grade']})")
        grade_lines.append(f"  Weekly avg: {grades['avg_score']}")
    grade_summary = "\n".join(grade_lines) if grade_lines else "No day grade data available."

    # IC-16: Progressive context — inject recent high-value insights
    previous_insights = ""
    if _HAS_INSIGHT_WRITER:
        try:
            previous_insights = insight_writer.build_insights_context(
                days=30, max_items=8, label="PREVIOUS INSIGHTS (last 30 days)")
        except Exception as e:
            print(f"[WARN] IC-16 progressive context failed: {e}")

    # P2: Dynamic journey context (replaces hardcoded 'Phase 1 Ignition')
    try:
        _start = datetime.strptime(profile.get("journey_start_date", "2026-02-22"), "%Y-%m-%d").date()
        _days_in = max(1, (datetime.now(timezone.utc).date() - _start).days + 1)
        _week_num = max(1, (_days_in + 6) // 7)
        _start_w = profile.get("journey_start_weight_lbs", 302)
        _goal_w = profile.get("goal_weight_lbs", 185)
        _cal = profile.get("calorie_target", 1800)
        _pro = profile.get("protein_target_g", 190)
        if _week_num <= 4:
            _stage = "Foundation Stage — habit formation + consistency over intensity"
            _coaching_note = (f"At Week {_week_num}, walks at {_start_w}+ lbs carry real cardiovascular load. "
                              "Evaluate movement volume generously. Don't apply intermediate-athlete benchmarks.")
        elif _week_num <= 12:
            _stage = "Momentum Stage — progressive overload appropriate, recovery-guided intensity"
            _coaching_note = f"Week {_week_num}: bodyweight-adjusted benchmarks apply, not absolute standards."
        elif _week_num <= 26:
            _stage = "Building Stage — periodization and performance metrics actionable"
            _coaching_note = f"Week {_week_num}: protocol optimization and deficit sustainability are primary levers."
        else:
            _stage = "Advanced Stage — data-driven protocol refinement"
            _coaching_note = f"Week {_week_num}: performance coaching fully applicable."
        journey_context = (
            f"JOURNEY STAGE: Week {_week_num} ({_days_in} days in) | {_start_w}→{_goal_w} lbs | {_stage}\n"
            f"Current targets: {_cal} kcal/day, {_pro}g protein\n"
            f"Week {_week_num} coaching principle: {_coaching_note}"
        )
    except Exception:
        journey_context = "JOURNEY STAGE: Week 1 of transformation | 302→185 lbs"

    payload = json.dumps({
        "model": os.environ.get("AI_MODEL", "claude-sonnet-4-6"), "max_tokens": 1500,
        "messages": [{"role": "user", "content": BOARD_PROMPT.format(
            data_json=json.dumps(pd, indent=2, default=str),
            grade_summary=grade_summary,
            previous_insights=previous_insights,
            journey_context=journey_context)}]
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST")
    resp = call_anthropic_with_retry(req)
    return resp["content"][0]["text"]


# ══════════════════════════════════════════════════════════════════════════════
# HTML BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def grade_colour(grade):
    if grade.startswith("A"): return "#059669"
    if grade.startswith("B"): return "#2563eb"
    if grade.startswith("C"): return "#d97706"
    return "#dc2626"

def build_html(data, commentary, profile):
    t = data["this"]
    p = data["prior"]
    tl = data["training_load"]
    tr = data["trends"]
    sd = data["sleep_debt"]
    prj = data["projection"]
    dates = data["dates"]

    try:
        dt_start = datetime.strptime(dates["this_start"], "%Y-%m-%d")
        dt_end = datetime.strptime(dates["this_end"], "%Y-%m-%d")
        week_label = f'{dt_start.strftime("%b %-d")} → {dt_end.strftime("%b %-d, %Y")}'
    except Exception:
        week_label = f'{dates["this_start"]} → {dates["this_end"]}'

    def row(label, value, dlt="", highlight=False):
        bg = "#fff8e7" if highlight else "#ffffff"
        return (f'<tr style="background:{bg}">'
                f'<td style="padding:6px 12px;color:#666;font-size:13px;">{label}</td>'
                f'<td style="padding:6px 12px;font-size:13px;font-weight:600;">{value}{dlt}</td></tr>')

    def section(title, emoji, content):
        return (f'<div style="margin-bottom:28px;">'
                f'<h2 style="font-size:15px;font-weight:700;color:#1a1a2e;margin:0 0 8px;'
                f'border-bottom:2px solid #e8e8f0;padding-bottom:6px;">{emoji} {title}</h2>'
                f'{content}</div>')

    def tbl(rows):
        return f'<table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:8px;overflow:hidden;">{rows}</table>'

    # ── Parse commentary ──
    board_html = insight_html = ""
    in_insight = False
    for line in commentary.strip().split("\n"):
        if line.startswith("💡"):
            in_insight = True
            insight_html += f'<p style="font-size:13px;font-weight:700;color:#92400e;margin:0 0 6px;">{line}</p>'
        elif in_insight:
            if line.strip():
                insight_html += f'<p style="font-size:14px;color:#78350f;line-height:1.7;margin:0;">{line}</p>'
        elif any(line.startswith(e) for e in ("🏋️", "🥗", "😴", "🩺", "🧠", "🎯")):
            board_html += f'<p style="font-size:13px;font-weight:700;color:#1a1a2e;margin:16px 0 4px;">{line}</p>'
        elif line.strip():
            board_html += f'<p style="font-size:13px;color:#333;line-height:1.6;margin:0 0 8px;">{line}</p>'

    # BS-05: confidence badge on Insight of the Week
    # Henning: weekly insight n = days_graded (7 → always LOW per <14 rule, correctly signals snapshot)
    _insight_badge = ""
    try:
        _wk_dg = t.get("day_grades")
        _dg_n = _wk_dg.get("days_graded") if _wk_dg else None
        _wk_conf = compute_confidence(days_of_data=_dg_n)
        _insight_badge = _wk_conf["badge_html"]
    except Exception:
        _insight_badge = ""

    insight_box = (f'<div style="background:#fffbeb;border:2px solid #f59e0b;border-radius:10px;'
                   f'padding:16px 20px;margin-bottom:24px;">'
                   + (f'<div style="margin-bottom:8px;">{_insight_badge}</div>' if _insight_badge else "")
                   + f'{insight_html}</div>') if insight_html else ""

    # ══════════════════════════════════════════════════════════════════════════
    # DAY GRADE WEEKLY TREND (NEW)
    # ══════════════════════════════════════════════════════════════════════════
    grade_section = ""
    dg = t.get("day_grades")
    dg_prior = p.get("day_grades")
    if dg and dg.get("days"):
        dg_avg = dg["avg_score"]
        dg_prior_avg = dg_prior["avg_score"] if dg_prior else None
        from_letter = lambda s: "A+" if s >= 95 else "A" if s >= 90 else "A-" if s >= 85 else "B+" if s >= 80 else "B" if s >= 75 else "B-" if s >= 70 else "C+" if s >= 65 else "C" if s >= 60 else "C-" if s >= 55 else "D" if s >= 45 else "F"
        avg_grade = from_letter(dg_avg)
        avg_color = grade_colour(avg_grade)
        t4_dg = tr.get("day_grade", "→")

        # Daily grade bars
        bars_html = '<div style="display:flex;gap:4px;align-items:flex-end;height:80px;margin:12px 0;">'
        for d in dg["days"]:
            h = max(8, round(d["score"] * 0.75))
            gc = grade_colour(d["grade"])
            day_name = ""
            try: day_name = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a")[0]
            except Exception: pass
            bars_html += (f'<div style="flex:1;text-align:center;">'
                          f'<div style="font-size:9px;color:{gc};font-weight:700;margin-bottom:2px;">{d["score"]}</div>'
                          f'<div style="height:{h}px;background:{gc};border-radius:3px 3px 0 0;margin:0 auto;width:80%;"></div>'
                          f'<div style="font-size:8px;color:#9ca3af;margin-top:2px;">{day_name}</div>'
                          f'<div style="font-size:8px;color:#9ca3af;">{d["grade"]}</div>'
                          f'</div>')
        bars_html += '</div>'

        # Grade distribution chips
        gc_counts = dg.get("grade_counts", {})
        dist_html = '<div style="display:flex;gap:6px;justify-content:center;margin-top:8px;">'
        for g_letter, g_color in [("A", "#059669"), ("B", "#2563eb"), ("C", "#d97706"), ("D", "#dc2626"), ("F", "#dc2626")]:
            count = gc_counts.get(g_letter, 0)
            if count > 0:
                dist_html += f'<span style="background:{g_color}20;color:{g_color};font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;">{count}{g_letter}</span>'
        dist_html += '</div>'

        dlt = delta_html(dg_avg, dg_prior_avg)

        grade_section = (
            f'<div style="background:linear-gradient(135deg,#f8f9fc,#f0f4ff);border-radius:12px;padding:16px 20px;margin-bottom:24px;border:1px solid #e2e8f0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<div>'
            f'<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin:0;">Weekly Day Grade</p>'
            f'<p style="font-size:28px;font-weight:800;color:{avg_color};margin:4px 0 0;line-height:1;">{round(dg_avg)} <span style="font-size:16px;">{avg_grade}</span>{dlt}</p>'
            f'<p style="font-size:10px;color:#9ca3af;margin:2px 0 0;">4-week trend: {t4_dg} &middot; Range: {dg["min_score"]}–{dg["max_score"]}</p>'
            f'</div>'
            f'<div style="text-align:right;">'
            f'<p style="font-size:10px;color:#9ca3af;margin:0;">{dg["days_graded"]} days graded</p>'
            f'{dist_html}'
            f'</div></div>'
            f'{bars_html}'
            f'</div>'
        )

    # ══════════════════════════════════════════════════════════════════════════
    # CHARACTER SHEET WEEKLY SUMMARY (Phase 4)
    # ══════════════════════════════════════════════════════════════════════════
    character_section = ""
    cs = data.get("character_sheet")
    cs_prior = data.get("character_sheet_prior")
    if cs:
        tier_colors = {
            "Foundation": {"bg": "#f3f4f6", "bar": "#6b7280", "text": "#374151"},
            "Momentum":   {"bg": "#fef3c7", "bar": "#d97706", "text": "#92400e"},
            "Discipline": {"bg": "#dbeafe", "bar": "#2563eb", "text": "#1e40af"},
            "Mastery":    {"bg": "#d1fae5", "bar": "#059669", "text": "#065f46"},
            "Elite":      {"bg": "#fae8ff", "bar": "#9333ea", "text": "#6b21a8"},
        }
        cs_tier = cs.get("character_tier", "Foundation")
        cs_emoji = cs.get("character_tier_emoji", "\U0001f528")
        tc = tier_colors.get(cs_tier, tier_colors["Foundation"])
        lvl_end = cs.get("character_level_end", 0)
        lvl_delta = cs.get("character_level_delta", 0)
        lvl_arrow = f' <span style="color:#059669;font-size:12px;">(+{lvl_delta})</span>' if lvl_delta > 0 else (f' <span style="color:#d97706;font-size:12px;">({lvl_delta})</span>' if lvl_delta < 0 else '')
        xp_total = cs.get("character_xp", 0)

        cs_html = (f'<div style="background:{tc["bg"]};border-left:4px solid {tc["bar"]};'
                   f'border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:4px;">'
                   f'<table style="width:100%;"><tr><td>'
                   f'<span style="font-size:20px;">{cs_emoji}</span> '
                   f'<span style="font-size:18px;font-weight:800;color:{tc["text"]};">Level {lvl_end}</span>{lvl_arrow} '
                   f'<span style="font-size:11px;color:{tc["text"]};font-weight:600;">{cs_tier.upper()}</span>'
                   f'</td><td style="text-align:right;">'
                   f'<span style="font-size:10px;color:#9ca3af;">{xp_total:,} XP</span>'
                   f'</td></tr></table>')

        # Pillar mini-table with weekly deltas
        pillar_emojis = {"sleep": "\U0001f634", "movement": "\U0001f3cb", "nutrition": "\U0001f957",
                         "metabolic": "\U0001fa7a", "mind": "\U0001f9e0", "relationships": "\U0001f91d",
                         "consistency": "\U0001f3af"}
        ps = cs.get("pillar_summary", {})
        cs_html += '<div style="margin-top:8px;">'
        for p_name in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
            pd = ps.get(p_name, {})
            p_level = pd.get("end_level", 0)
            p_delta = pd.get("level_delta", 0)
            p_tier = pd.get("tier", "Foundation")
            p_tc = tier_colors.get(p_tier, tier_colors["Foundation"])
            p_emoji = pillar_emojis.get(p_name, "")
            p_avg = pd.get("avg_raw")
            avg_str = f' avg {round(p_avg)}' if p_avg is not None else ''
            delta_str = ''
            if p_delta > 0:
                delta_str = f' <span style="color:#059669;">+{p_delta}</span>'
            elif p_delta < 0:
                delta_str = f' <span style="color:#d97706;">{p_delta}</span>'
            cs_html += (f'<div style="margin:2px 0;"><table style="width:100%;"><tr>'
                        f'<td style="width:90px;font-size:10px;color:#6b7280;">{p_emoji} {p_name.capitalize()}</td>'
                        f'<td><div style="background:#e5e7eb;border-radius:3px;height:5px;">'
                        f'<div style="background:{p_tc["bar"]};border-radius:3px;height:5px;width:{p_level}%;"></div></div></td>'
                        f'<td style="width:80px;text-align:right;font-size:10px;color:{p_tc["text"]};font-weight:600;">Lv{p_level}{delta_str}{avg_str}</td>'
                        f'</tr></table></div>')
        cs_html += '</div>'

        # Weekly events
        cs_events = cs.get("events", [])
        if cs_events:
            cs_html += '<div style="margin-top:6px;padding-top:6px;border-top:1px solid #e5e7eb;">'
            for ev in cs_events:
                ev_type = ev.get("type", "")
                ev_pillar = ev.get("pillar", "").replace("_", " ").title()
                ev_date = ev.get("date", "")
                is_up = "up" in ev_type
                ev_col = "#059669" if is_up else "#d97706"
                ev_icon = "\u2B06" if is_up else "\u2B07"
                if "tier" in ev_type:
                    ev_label = f'{ev_pillar}: {ev.get("old_tier", "")} \u2192 {ev.get("new_tier", "")}'
                elif "character" in ev_type:
                    ev_label = f'Character Level {ev.get("old_level", "")} \u2192 {ev.get("new_level", "")}'
                else:
                    ev_label = f'{ev_pillar} Lv{ev.get("old_level", "")} \u2192 {ev.get("new_level", "")}'
                cs_html += (f'<span style="display:inline-block;background:#fff;border:1px solid {ev_col};'
                            f'border-radius:12px;padding:2px 8px;font-size:10px;color:{ev_col};'
                            f'margin:2px 3px 2px 0;font-weight:600;">{ev_icon} {ev_label}</span>')
            cs_html += '</div>'

        # Closest to tier-up nudge
        ctt = cs.get("closest_to_tier")
        if ctt:
            cs_html += (f'<div style="margin-top:6px;font-size:10px;color:#6b7280;">'
                        f'\U0001f4a1 <b>{ctt["pillar"].capitalize()}</b> is {ctt["levels_needed"]} levels from '
                        f'{ctt["next_tier"]} tier</div>')

        cs_html += '</div>'
        character_section = section("Character Sheet", cs_emoji, cs_html)

    # ══════════════════════════════════════════════════════════════════════════
    # SCORECARD (matching daily brief 8 components)
    # ══════════════════════════════════════════════════════════════════════════
    def sc_cell(label, val, emoji, detail=""):
        if val is None:
            vc, vd = "#9ca3af", "—"
        else:
            vd = str(round(val))
            vc = "#059669" if val >= 80 else "#2563eb" if val >= 60 else "#d97706" if val >= 40 else "#dc2626"
        det = f'<div style="font-size:9px;color:#9ca3af;margin-top:1px;">{detail}</div>' if detail else ""
        return (f'<td style="padding:8px 4px;text-align:center;width:12.5%;">'
                f'<div style="font-size:11px;">{emoji}</div>'
                f'<div style="font-size:16px;font-weight:700;color:{vc};">{vd}</div>'
                f'<div style="font-size:9px;color:#6b7280;">{label}</div>{det}</td>')

    # Compute weekly avg for each component from day grades
    comp_avgs = {}
    if dg and dg.get("days"):
        for comp in ["sleep_quality", "recovery", "nutrition", "movement", "habits_mvp", "hydration", "journal", "glucose"]:
            vals = []
            for d_date in [d["date"] for d in dg["days"]]:
                rec = data.get("_raw_grades", {}).get(d_date, {})
                v = safe_float(rec, f"component_{comp}")
                if v is not None: vals.append(v)
            comp_avgs[comp] = avg(vals) if vals else None

    # Fallback: compute from extracted data
    sleep_avg = comp_avgs.get("sleep_quality") or (t["sleep"]["score_avg"] if t.get("sleep") else None)
    recovery_avg = comp_avgs.get("recovery") or (t["whoop"]["recovery_avg"] if t.get("whoop") else None)
    nutrition_avg = comp_avgs.get("nutrition")
    movement_avg = comp_avgs.get("movement")
    habits_avg = comp_avgs.get("habits_mvp") or (t["habitify"]["mvp_avg_pct"] if t.get("habitify") else None)
    hydration_avg = comp_avgs.get("hydration")
    journal_avg = comp_avgs.get("journal")
    glucose_avg = comp_avgs.get("glucose")

    scorecard_html = (
        f'<div style="background:#f8f9fc;border-radius:10px;padding:12px 4px;margin-bottom:24px;">'
        f'<p style="text-align:center;font-size:11px;color:#888;margin:0 0 8px;text-transform:uppercase;letter-spacing:1px;">Weekly Component Averages</p>'
        f'<table style="width:100%;border-collapse:collapse;"><tr>'
        f'{sc_cell("Sleep", sleep_avg, "🛌")}'
        f'{sc_cell("Recovery", recovery_avg, "💚")}'
        f'{sc_cell("Nutrition", nutrition_avg, "🍽")}'
        f'{sc_cell("Movement", movement_avg, "🏃")}'
        f'{sc_cell("Habits", habits_avg, "✅")}'
        f'{sc_cell("Water", hydration_avg, "💧")}'
        f'{sc_cell("Journal", journal_avg, "📓")}'
        f'{sc_cell("Glucose", glucose_avg, "📈")}'
        f'</tr></table></div>'
    )

    # ══════════════════════════════════════════════════════════════════════════
    # TRAINING
    # ══════════════════════════════════════════════════════════════════════════
    tr_rows = ""
    if t.get("strava"):
        s = t["strava"]; sp = p.get("strava") or {}
        tr_rows += row("Activities", str(s.get("activity_count", 0)))
        tr_rows += row("Total Moving Time", fmt((s.get("total_minutes") or 0) / 60, " hrs"), delta_html(s.get("total_minutes"), sp.get("total_minutes"), " min"))
        tr_rows += row("Total Miles", fmt(s.get("total_miles"), " mi"), delta_html(s.get("total_miles"), sp.get("total_miles"), " mi"))
        tr_rows += row("Elevation Gain", f'{s.get("total_elevation_feet", 0):,} ft')

        z2 = s.get("zone2_minutes", 0)
        z2_target = s.get("zone2_target", 150)
        z2_pct = s.get("zone2_pct", 0)
        z2col = "#27ae60" if z2 >= z2_target else "#e67e22" if z2 >= 60 else "#e74c3c"
        tr_rows += row(f'Zone 2 ({s.get("zone2_hr_range", "?")} bpm)',
            f'<span style="color:{z2col};font-weight:700;">{z2} / {z2_target} min ({z2_pct}% of cardio)</span>',
            delta_html(z2, sp.get("zone2_minutes"), " min") if sp.get("zone2_minutes") is not None else "", highlight=True)

        mono = s.get("training_monotony")
        if mono is not None:
            mcol = "#27ae60" if mono < 1.5 else "#e67e22" if mono < 2.0 else "#e74c3c"
            mlabel = "Varied ✓" if mono < 1.5 else "Moderate" if mono < 2.0 else "⚠ High — plateau risk"
            tr_rows += row("Training Monotony", f'<span style="color:{mcol};">{mono} — {mlabel}</span>')

        for act in s.get("activities", [])[:6]:
            d = f'{act["miles"]} mi · {act["elev"]:,} ft'
            if act.get("hr"): d += f' · {act["hr"]} bpm'
            d += f' · {act["mins"]} min'
            tr_rows += row(f'↳ {act["date"]} {act["name"]}', d)

    # Strength (MacroFactor workouts)
    mfw = t.get("mf_workouts")
    if mfw:
        tr_rows += row("Strength Sessions", str(mfw["workout_count"]),
                        delta_html(mfw["workout_count"], (p.get("mf_workouts") or {}).get("workout_count")))
        tr_rows += row("Total Volume", f'{fmt_num(mfw["total_volume_lbs"])} lbs, {mfw["total_sets"]} sets', highlight=True)
        for w in mfw.get("workouts", [])[:4]:
            tr_rows += row(f'↳ {w["date"]} {w["name"]}', f'{w["exercises"]} exercises · {fmt_num(w["volume_lbs"])} lbs')
    training_section = section("Training", "🏃", tbl(tr_rows)) if tr_rows else ""

    # ── Banister ──
    tsb = tl.get("tsb", 0)
    tcol = "#27ae60" if tsb >= 0 else "#e67e22" if tsb >= -15 else "#e74c3c"
    tlabel = "Fresh" if tsb >= 5 else "Neutral" if tsb >= -5 else "Fatigued" if tsb >= -15 else "Very Fatigued"
    bl_rows = row("CTL — Fitness (42d)", fmt(tl.get("ctl")), highlight=True)
    bl_rows += row("ATL — Fatigue (7d)", fmt(tl.get("atl")))
    bl_rows += row("TSB — Form", f'<span style="color:{tcol};font-weight:700;">{fmt(tl.get("tsb"))} ({tlabel})</span>')
    banister_section = section("Training Load — Banister", "📈", tbl(bl_rows))

    # ── Recovery ──
    rec_rows = ""
    if t.get("whoop"):
        w = t["whoop"]; wp = p.get("whoop") or {}
        t4 = tr
        rec_rows += row("Avg Recovery", fmt(w.get("recovery_avg"), "%"),
            delta_html(w.get("recovery_avg"), wp.get("recovery_avg"), "%") + f' <span style="font-size:11px;color:#888;">4wk {t4.get("recovery","→")}</span>', highlight=True)
        rec_rows += row("Avg HRV", fmt(w.get("hrv_avg"), " ms"),
            delta_html(w.get("hrv_avg"), wp.get("hrv_avg"), " ms") + f' <span style="font-size:11px;color:#888;">4wk {t4.get("hrv","→")}</span>')
        rec_rows += row("HRV Range", f'{fmt(w.get("hrv_min"), " ms")} – {fmt(w.get("hrv_max"), " ms")}')
        rec_rows += row("Avg RHR", fmt(w.get("rhr_avg"), " bpm"),
            delta_html(w.get("rhr_avg"), wp.get("rhr_avg"), " bpm", invert=True) + f' <span style="font-size:11px;color:#888;">4wk {t4.get("rhr","→")}</span>')
        rec_rows += row("Avg Strain", fmt(w.get("strain_avg")))
    recovery_section = section("Recovery & HRV", "❤️", tbl(rec_rows)) if rec_rows else ""

    # ── Sleep ──
    sl_rows = ""
    if t.get("sleep"):
        s = t["sleep"]; sp = p.get("sleep") or {}
        sl_rows += row("Avg Sleep Score", fmt(s.get("score_avg"), "%"),
            delta_html(s.get("score_avg"), sp.get("score_avg"), "%") + f' <span style="font-size:11px;color:#888;">4wk {tr.get("sleep","→")}</span>', highlight=True)
        sl_rows += row("Worst Night", fmt(s.get("score_min"), "%"))
        sl_rows += row("Avg Duration", fmt(s.get("duration_avg_hrs"), " hrs"), delta_html(s.get("duration_avg_hrs"), sp.get("duration_avg_hrs"), " hrs"))
        if s.get("efficiency_avg"):
            ecol = "#27ae60" if s["efficiency_avg"] >= 85 else "#e67e22" if s["efficiency_avg"] >= 80 else "#e74c3c"
            sl_rows += row("Efficiency", f'<span style="color:{ecol};">{fmt(s["efficiency_avg"], "%")}</span>')
        if s.get("deep_pct"):
            dcol = "#27ae60" if s["deep_pct"] >= 15 else "#e67e22" if s["deep_pct"] >= 10 else "#e74c3c"
            sl_rows += row("Deep %", f'<span style="color:{dcol};">{fmt(s["deep_pct"], "%")}</span> (target 15-20%)')
        if s.get("rem_pct"):
            rcol = "#27ae60" if s["rem_pct"] >= 20 else "#e67e22" if s["rem_pct"] >= 15 else "#e74c3c"
            sl_rows += row("REM %", f'<span style="color:{rcol};">{fmt(s["rem_pct"], "%")}</span> (target 20-25%)')
        if sd:
            dcol = "#27ae60" if sd["debt_hrs"] <= 2 else "#e67e22" if sd["debt_hrs"] <= 5 else "#e74c3c"
            sl_rows += row("7-Day Sleep Debt", f'<span style="color:{dcol};font-weight:700;">{fmt(sd["debt_hrs"], " hrs")}</span>', highlight=True)
    sleep_section = section("Sleep & Architecture", "😴", tbl(sl_rows)) if sl_rows else ""

    # ── Habits ──
    hab_rows = ""
    if t.get("habitify"):
        h = t["habitify"]; hp = p.get("habitify") or {}
        mvp_pct = h.get("mvp_avg_pct")
        mvp_col = "#27ae60" if (mvp_pct or 0) >= 80 else "#e67e22" if (mvp_pct or 0) >= 50 else "#e74c3c"
        hab_rows += row("MVP Completion (avg)", f'<span style="color:{mvp_col};font-weight:700;">{fmt(mvp_pct, "%")}</span>',
            delta_html(mvp_pct, hp.get("mvp_avg_pct"), "%"), highlight=True)
        if h.get("overall_avg_pct"):
            hab_rows += row("Overall Completion", fmt(h["overall_avg_pct"], "%"))
        hab_rows += row("Days Tracked", str(h.get("days_tracked", 0)))
        # Per-habit completion
        mvp_comp = h.get("mvp_completion", {})
        mvp_total_days = h.get("days_tracked", 1)
        for habit_name in profile.get("mvp_habits", []):
            days_done = mvp_comp.get(habit_name, 0)
            pct = round(days_done / mvp_total_days * 100) if mvp_total_days else 0
            hcol = "#27ae60" if pct >= 80 else "#e67e22" if pct >= 50 else "#e74c3c"
            short = habit_name[:30] + "..." if len(habit_name) > 30 else habit_name
            hab_rows += row(f'↳ {short}', f'<span style="color:{hcol};">{days_done}/{mvp_total_days} ({pct}%)</span>')
    habits_section = section("Habits — MVP Tracker", "✅", tbl(hab_rows)) if hab_rows else ""

    # ── Nutrition ──
    nu_rows = ""
    if t.get("macrofactor"):
        m = t["macrofactor"]; mp = p.get("macrofactor") or {}
        nu_rows += row("Avg Calories", f'{fmt(m.get("calories_avg"), " kcal")} (target {m.get("calorie_target")})',
            delta_html(m.get("calories_avg"), mp.get("calories_avg"), " kcal", invert=True), highlight=True)
        nu_rows += row("Calorie Hit Rate", hit_bar(m.get("calorie_hit_rate")))
        nu_rows += row("Avg Protein", f'{fmt(m.get("protein_avg_g"), "g")} (target {m.get("protein_target")}g)',
            delta_html(m.get("protein_avg_g"), mp.get("protein_avg_g"), "g"))
        nu_rows += row("Protein Hit Rate", hit_bar(m.get("protein_hit_rate"), "#2980b9"))
        if m.get("fat_avg_g"): nu_rows += row("Avg Fat", fmt(m["fat_avg_g"], "g"))
        if m.get("carbs_avg_g"): nu_rows += row("Avg Carbs", fmt(m["carbs_avg_g"], "g"))
        if m.get("fiber_avg_g"): nu_rows += row("Avg Fiber", fmt(m["fiber_avg_g"], "g"))
        nu_rows += row("Days Logged", str(m.get("days_logged", 0)))
    nutrition_section = section("Nutrition", "🥗", tbl(nu_rows)) if nu_rows else ""

    # ── Weight ──
    wt_rows = ""
    if t.get("withings"):
        w = t["withings"]; wp = p.get("withings") or {}
        wt_rows += row("Latest Weight", fmt(w.get("weight_latest"), " lbs"),
            delta_html(w.get("weight_latest"), wp.get("weight_latest"), " lbs", invert=True) + f' <span style="font-size:11px;color:#888;">4wk {tr.get("weight","→")}</span>', highlight=True)
        wt_rows += row("Weekly Range", f'{fmt(w.get("weight_min"), " lbs")} – {fmt(w.get("weight_max"), " lbs")}')
        if w.get("body_fat_avg"):
            wt_rows += row("Body Fat %", fmt(w["body_fat_avg"], "%"), delta_html(w.get("body_fat_avg"), wp.get("body_fat_avg"), "%", invert=True))
        goal = profile.get("goal_weight_lbs", 185)
        if w.get("weight_latest") and goal:
            to_go = round(w["weight_latest"] - goal, 1)
            start = profile.get("journey_start_weight_lbs", 302)
            lost = round(start - w["weight_latest"], 1)
            pct = round(lost / (start - goal) * 100) if start > goal else 0
            wt_rows += row("Journey Progress", f'{lost} lbs lost · {pct}% · {to_go} lbs to go', highlight=True)
        if prj:
            if prj.get("status") == "ok":
                pcol = "#27ae60" if prj["rate_per_week"] >= 0.5 else "#e67e22"
                wt_rows += row("📅 Projection", f'<span style="color:{pcol};">{prj["rate_per_week"]} lbs/wk → goal ~{prj["eta"]} ({prj["weeks"]} weeks)</span>')
            elif prj.get("status") == "not_losing":
                wt_rows += row("📅 Projection", '<span style="color:#e74c3c;">Weight flat or trending up</span>')
    weight_section = section("Weight & Body Composition", "⚖️", tbl(wt_rows)) if wt_rows else ""

    # ── CGM & Glucose ──
    cgm_rows = ""
    if t.get("apple") and t["apple"].get("glucose_avg"):
        a = t["apple"]; ap = p.get("apple") or {}
        gavg = a["glucose_avg"]
        gcol = "#059669" if gavg < 100 else "#d97706" if gavg < 120 else "#dc2626"
        cgm_rows += row("Avg Glucose", f'<span style="color:{gcol};font-weight:700;">{fmt(gavg, " mg/dL")}</span>',
            delta_html(gavg, ap.get("glucose_avg"), " mg/dL", invert=True), highlight=True)
        if a.get("glucose_tir_avg"):
            tir_col = "#059669" if a["glucose_tir_avg"] >= 90 else "#d97706"
            cgm_rows += row("Time in Range", f'<span style="color:{tir_col};">{fmt(a["glucose_tir_avg"], "%")}</span>')
        cgm_rows += row("Days w/ CGM Data", str(a.get("glucose_days", 0)))
    # Gait
    if t.get("apple") and t["apple"].get("gait_speed_avg"):
        a = t["apple"]
        gs = a["gait_speed_avg"]
        gs_col = "#059669" if gs >= 3.0 else "#d97706" if gs >= 2.24 else "#dc2626"
        cgm_rows += row("Walking Speed", f'<span style="color:{gs_col};">{fmt(gs, " mph")}</span> ({a.get("gait_days", 0)} days)')
    cgm_section = section("CGM & Mobility", "📊", tbl(cgm_rows)) if cgm_rows else ""

    # ── Journal ──
    jn_rows = ""
    jt = t.get("journal")
    jp = p.get("journal")
    if jt:
        def mood_color(val, invert=False):
            if val is None: return "#888"
            if invert: return "#27ae60" if val <= 2 else "#e67e22" if val <= 3 else "#e74c3c"
            return "#e74c3c" if val < 3 else "#e67e22" if val < 4 else "#27ae60"
        mc = mood_color(jt.get("mood_avg"))
        ec = mood_color(jt.get("energy_avg"))
        sc2 = mood_color(jt.get("stress_avg"), invert=True)
        jn_rows += row("Mood", f'<span style="color:{mc};font-weight:700;">{fmt(jt.get("mood_avg"))}/5</span>',
            delta_html(jt.get("mood_avg"), jp.get("mood_avg") if jp else None) if jp else "", highlight=True)
        jn_rows += row("Energy", f'<span style="color:{ec};font-weight:700;">{fmt(jt.get("energy_avg"))}/5</span>',
            delta_html(jt.get("energy_avg"), jp.get("energy_avg") if jp else None) if jp else "")
        jn_rows += row("Stress", f'<span style="color:{sc2};font-weight:700;">{fmt(jt.get("stress_avg"))}/5</span>',
            delta_html(jt.get("stress_avg"), jp.get("stress_avg") if jp else None, invert=True) if jp else "")
        jn_rows += row("Entries", f'{jt.get("entries", 0)} across {jt.get("days_journaled", 0)} days')
        if jt.get("top_themes"):
            chips = " ".join(f'<span style="display:inline-block;background:#f0f4ff;color:#4a6cf7;font-size:10px;padding:2px 8px;border-radius:10px;margin:2px;">{t} ({c})</span>' for t, c in jt["top_themes"][:5])
            jn_rows += row("Themes", chips)
        if jt.get("avoidance_flags"):
            jn_rows += row("⚠ Avoidance", f'<span style="color:#dc2626;">{", ".join(jt["avoidance_flags"][:3])}</span>')
        if jt.get("notable_quotes"):
            for nq in jt["notable_quotes"][:2]:
                jn_rows += row(f'📝 {nq["date"]}', f'<span style="font-style:italic;color:#4338ca;">"{nq["quote"]}"</span>')
    journal_section = section("Journal & Mood", "📓", tbl(jn_rows)) if jn_rows else ""

    # ── Productivity ──
    pr_rows = ""
    if t.get("todoist"):
        td = t["todoist"]; tdp = p.get("todoist") or {}
        pr_rows += row("Tasks Completed", str(td.get("tasks_completed", 0)), delta_html(td.get("tasks_completed"), tdp.get("tasks_completed")))
        pr_rows += row("Avg Per Day", fmt(td.get("avg_per_day")))
    productivity_section = section("Productivity", "✅", tbl(pr_rows)) if pr_rows else ""

    # ── Open Insights ──
    insights_html = ""
    oi = data.get("open_insights", [])
    if oi:
        items = ""
        for ins in oi:
            age_col = "#dc2626" if ins["days_open"] >= 30 else "#d97706"
            items += (f'<div style="padding:8px 0;border-bottom:1px solid #fde68a;">'
                      f'<p style="font-size:12px;color:#1a1a2e;margin:0 0 3px;">{ins["text"]}</p>'
                      f'<p style="font-size:10px;color:#888;margin:0;">Saved {ins["date_saved"]} · '
                      f'<span style="color:{age_col};font-weight:700;">{ins["days_open"]}d open</span></p></div>')
        insights_html = (f'<div style="background:#fffbeb;border:2px solid #f59e0b;border-radius:10px;'
                         f'padding:16px 20px;margin-bottom:24px;">'
                         f'<p style="font-size:13px;font-weight:700;color:#92400e;margin:0 0 10px;">'
                         f'⏳ {len(oi)} Open Insight{"s" if len(oi)>1 else ""}</p>{items}</div>')

    board_section = section("Board of Advisors", "📋",
        f'<div style="background:#f0f4ff;border-left:4px solid #4a6cf7;padding:16px;border-radius:0 8px 8px 0;">{board_html}</div>')

    # ── Assemble ──
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:660px;margin:32px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.09);">
<div style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);padding:28px 32px;">
<h1 style="color:#fff;font-size:22px;margin:0 0 4px;">Weekly Report</h1>
<p style="color:#8892b0;font-size:13px;margin:0;">{week_label} · Deltas vs prior week · 4-week trend arrows</p>
</div>
<div style="padding:28px 32px;">
{grade_section}
{character_section}
{scorecard_html}
{insights_html}
{insight_box}
{board_section}
{training_section}
{banister_section}
{recovery_section}
{sleep_section}
{habits_section}
{nutrition_section}
{weight_section}
{cgm_section}
{journal_section}
{productivity_section}
</div>
<div style="background:#f8f8fc;padding:16px 32px;border-top:1px solid #e8e8f0;">
<p style="color:#999;font-size:11px;margin:0;">Life Platform v4.0 · Whoop · Eight Sleep · Withings · Strava · MacroFactor · Habitify · Notion · Apple Health · Todoist · AWS us-west-2</p>
<p style="color:#bbb;font-size:9px;margin:6px 0 0;">⚕️ Personal health tracking only — not medical advice. Consult a qualified healthcare professional before making changes to your diet, exercise, or supplement regimen.</p>
</div></div></body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    print("[INFO] Weekly Digest v4.0 starting...")
    result = gather_all()
    if result is None or result[0] is None:
        return {"statusCode": 500, "body": "Failed to gather data"}
    data, profile = result
    dates = data["dates"]
    print(f"[INFO] {dates['this_start']} → {dates['this_end']}")

    # Store raw grades for component scorecard
    raw_grades = query_range("day_grade", dates["this_start"], dates["this_end"])
    data["_raw_grades"] = raw_grades

    api_key = get_anthropic_key()
    logger.set_date(dates.get("this_end", ""))  # OBS-1
    print("[INFO] Calling Haiku for Board commentary...")
    try:
        commentary = call_haiku(data, profile, api_key)
    except Exception as e:
        print(f"[WARN] Haiku failed: {e}")
        commentary = ("🎯 THE CHAIR — OVERVIEW\nCommentary unavailable.\n"
                      "💡 INSIGHT OF THE WEEK\nReview data sections below.")

    # AI-3: Validate output before rendering
    if _HAS_AI_VALIDATOR and commentary:
        _val = validate_ai_output(commentary, AIOutputType.WEEKLY_DIGEST)
        if _val.blocked:
            print(f"[AI-3] Weekly digest commentary BLOCKED: {_val.block_reason}")
            commentary = _val.safe_fallback
        elif _val.warnings:
            print(f"[AI-3] Weekly digest warnings: {_val.warnings}")

    html = build_html(data, commentary, profile)

    dg = data["this"].get("day_grades")
    grade_str = f'{round(dg["avg_score"])} ({dg["days_graded"]}d)' if dg else "—"

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": f"Weekly Report · {dates['this_end']} · Grade: {grade_str}", "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    print("[INFO] Sent.")

    # IC-15: Persist insights from this digest
    if _HAS_INSIGHT_WRITER and commentary:
        try:
            insights = []
            # Write the full Board commentary as a coaching insight
            insights.append({
                "digest_type": "weekly_digest",
                "insight_type": "coaching",
                "text": commentary[:800],
                "pillars": ["sleep", "movement", "nutrition", "mind", "consistency"],
                "tags": ["weekly", "board", "coaching"],
                "confidence": "high",
                "actionable": True,
                "date": dates.get("this_end", ""),
            })
            written = insight_writer.write_insights_batch(insights)
            print(f"[INFO] IC-15: {written} weekly insights persisted")
        except Exception as e:
            print(f"[WARN] IC-15 insight write failed (non-fatal): {e}")

    return {"statusCode": 200, "body": "Digest v4.0 sent."}
