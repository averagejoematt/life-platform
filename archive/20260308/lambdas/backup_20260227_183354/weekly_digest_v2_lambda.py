"""
Weekly Digest Lambda — v4.2.0 (Weekly Digest v2)
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
  12. Steps, CGM & Mobility (Apple Health)
  13. Journal & Mood (Notion)
  14. Productivity (Todoist)
  15. Open Insights
  16. Journey Assessment (12-week trajectory + next week focus)
"""

import json
import os
import logging
import math
import statistics
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────

# ── Config (env vars with backwards-compatible defaults) ──
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=REGION)
secrets  = boto3.client("secretsmanager", region_name=REGION)
s3       = boto3.client("s3", region_name=REGION)

RECIPIENT = "awsdev@mattsusername.com"
SENDER    = "awsdev@mattsusername.com"
DASHBOARD_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
CLINICAL_KEY = "dashboard/clinical.json"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_anthropic_key():
    secret = secrets.get_secret_value(SecretId="life-platform/anthropic")
    return json.loads(secret["SecretString"])["api_key"]

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

def fmt(val, unit="", dec=1):
    return "—" if val is None else f"{round(val, dec)}{unit}"

def fmt_num(val):
    if val is None: return "—"
    return "{:,}".format(round(val))

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

def dedup_activities(activities):
    if not activities or len(activities) <= 1:
        return activities
    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try: return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError): return None
    def richness(a):
        score = 0
        if float(a.get("distance_meters") or 0) > 0: score += 1000
        score += float(a.get("moving_time_seconds") or 0)
        if a.get("summary_polyline"): score += 500
        return score
    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed.sort(key=lambda x: x[2])
    remove = set()
    for j in range(len(indexed)):
        if j in remove: continue
        _, a_j, t_j = indexed[j]
        sport_j = (a_j.get("sport_type") or "").lower()
        for k in range(j + 1, len(indexed)):
            if k in remove: continue
            _, a_k, t_k = indexed[k]
            if (a_k.get("sport_type") or "").lower() != sport_j: continue
            if abs((t_k - t_j).total_seconds()) / 60 > 15: break
            if richness(a_j) >= richness(a_k): remove.add(k)
            else: remove.add(j)
    kept = [a for i, (_, a, _) in enumerate(indexed) if i not in remove]
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time


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


def ex_eightsleep(recs_dict):
    recs = list(recs_dict.values()) if recs_dict else []
    if not recs: return None
    scores = [float(r["sleep_score"]) for r in recs if "sleep_score" in r]
    # Support both old and new field names
    durs = []
    for r in recs:
        d = safe_float(r, "sleep_duration_hours")
        if d is None:
            d = safe_float(r, "total_sleep_seconds")
            if d is not None: d = d / 3600
        if d is not None: durs.append(d)
    effs = []
    for r in recs:
        e = safe_float(r, "sleep_efficiency_pct") or safe_float(r, "sleep_efficiency")
        if e is not None: effs.append(e)
    deep_pcts = [float(r["deep_pct"]) for r in recs if "deep_pct" in r]
    rem_pcts = [float(r["rem_pct"]) for r in recs if "rem_pct" in r]
    # Fallback to seconds-based deep/rem
    if not deep_pcts:
        for r in recs:
            ds = safe_float(r, "deep_sleep_seconds")
            ts = safe_float(r, "total_sleep_seconds")
            if ds is not None and ts and ts > 0:
                deep_pcts.append(ds / ts * 100)
    if not rem_pcts:
        for r in recs:
            rs = safe_float(r, "rem_sleep_seconds")
            ts = safe_float(r, "total_sleep_seconds")
            if rs is not None and ts and ts > 0:
                rem_pcts.append(rs / ts * 100)
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
    alcohols = [float(r["total_alcohol_g"]) for r in recs if "total_alcohol_g" in r and float(r.get("total_alcohol_g", 0)) > 0]
    # 1 standard drink = 14g pure alcohol
    total_alcohol_g = sum(alcohols) if alcohols else 0
    total_drinks = round(total_alcohol_g / 14, 1) if total_alcohol_g > 0 else 0
    return {
        "calories_avg": avg(cals), "protein_avg_g": avg(prots),
        "fat_avg_g": avg(fats), "carbs_avg_g": avg(carbs), "fiber_avg_g": avg(fibers),
        "days_logged": len(recs),
        "protein_hit_rate": round(sum(1 for p in prots if p >= prot_target) / len(prots) * 100) if prots else None,
        "calorie_hit_rate": round(sum(1 for c in cals if c <= cal_target * 1.10) / len(cals) * 100) if cals else None,
        "protein_target": prot_target, "calorie_target": cal_target,
        "alcohol_drinks": total_drinks, "alcohol_days": len(alcohols),
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
        ("sleep", "eightsleep", "score_avg"),
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

def compute_sleep_debt(eightsleep_dict, target_hrs=7.5):
    if not eightsleep_dict: return None
    durs = []
    for r in eightsleep_dict.values():
        d = safe_float(r, "sleep_duration_hours")
        if d is None:
            d = safe_float(r, "total_sleep_seconds")
            if d is not None: d = d / 3600
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
        "eightsleep": ex_eightsleep(raw_this["eightsleep"]),
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
        "eightsleep": ex_eightsleep(raw_prior["eightsleep"]),
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
        ("eightsleep", ex_eightsleep, "eightsleep"),
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
    sleep_debt = compute_sleep_debt(raw_this["eightsleep"],
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

    return {
        "this": this, "prior": prior, "profile": profile,
        "training_load": training_load, "trends": trends,
        "sleep_debt": sleep_debt, "projection": projection,
        "open_insights": open_insights,
        "dates": {"this_start": w1_start, "this_end": w1_end,
                  "prior_start": w2_start, "prior_end": w2_end},
    }, profile


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HAIKU — BOARD OF DIRECTORS
# ══════════════════════════════════════════════════════════════════════════════

JOURNEY_PROMPT = """You are the Board of Directors for Matthew's health transformation — providing a quarterly-style executive assessment based on the full data history available.

CONTEXT:
Matthew Walker, 36, Seattle. Senior Director at a SaaS company. Goal: lose ~117 lbs (302→185),
build muscle, improve sleep and stress management. Current phase: Phase 1 Ignition (1800 cal/day,
190g protein, 3 lbs/week target). He tracks obsessively but struggles with consistency.

JOURNEY DATA:
{journey_json}

THIS WEEK'S SUMMARY:
{week_summary}

RULES:
- This is NOT a weekly recap. This is a 12-week trajectory assessment.
- Identify what's working (systems, not single weeks) and what's stalling.
- Be honest about plateaus, regression, or missing data.
- Name structural issues (not just "try harder").
- End with exactly ONE concrete focus area for next week, justified by the trajectory data.
- Be direct. 200 words max.

Write exactly these sections with these exact headers:

📊 TRAJECTORY ASSESSMENT
3-4 sentences on the 12-week arc. Is Matthew building momentum, plateauing, or regressing? Which systems are working and which aren't? Reference the grade trend and weight trajectory specifically.

🔍 BIGGEST STRUCTURAL GAP
2-3 sentences. What single system or behaviour pattern, if fixed, would have the largest compound effect? This should be something visible across multiple weeks, not a one-off.

🎯 NEXT WEEK'S FOCUS
2-3 sentences. One specific, measurable focus for next week that addresses the structural gap. Include a concrete target number or behaviour. Explain why this week specifically.

💪 MOMENTUM CHECK
1 sentence. Honest acknowledgment of what IS working, grounded in data."""


BOARD_PROMPT = """You are the coordinating intelligence for Matthew's Weekly Health Board of Advisors.

CONTEXT:
Matthew Walker, 36, Seattle. Senior Director at a SaaS company. Goal: lose ~117 lbs (302→185),
build muscle, improve sleep and stress management. Current phase: Phase 1 Ignition (1800 cal/day,
190g protein, 3 lbs/week target). He tracks obsessively but struggles with consistency.

DAY GRADES THIS WEEK (0-100 composite of sleep, recovery, nutrition, movement, habits, hydration, journal, glucose):
{grade_summary}

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

🎯 THE CHAIR — WEEKLY VERDICT
4–6 sentences. Clear verdict on THIS week only. Reference day grade average and trend. Name the single biggest win and single biggest miss. Do NOT recommend next-week actions — that’s the Journey Assessment’s job. Close with one sentence of genuine encouragement grounded in data.

💡 INSIGHT OF THE WEEK
One sentence. Concrete. Specific. Actionable in 7 days. Must reference actual numbers.

ADDITIONAL RULES:
- If data for your domain is missing or has <3 days, say 'Insufficient data this week' rather than speculating.
- If another advisor has already covered a topic, reference their name (e.g. 'As Dr. Park noted...') rather than re-analyzing the same data.

Be honest. Be a coach, not a cheerleader."""


def call_anthropic_with_retry(req, timeout=35, max_attempts=2, backoff_s=5):
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"[WARN] Anthropic HTTP {e.code} attempt {attempt}")
            if attempt < max_attempts and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(backoff_s)
            else: raise
        except urllib.error.URLError as e:
            print(f"[WARN] Anthropic network error attempt {attempt}: {e}")
            if attempt < max_attempts: time.sleep(backoff_s)
            else: raise


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

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001", "max_tokens": 1500,
        "messages": [{"role": "user", "content": BOARD_PROMPT.format(
            data_json=json.dumps(pd, indent=2, default=str),
            grade_summary=grade_summary)}]
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST")
    resp = call_anthropic_with_retry(req)
    return resp["content"][0]["text"]


def gather_journey_context(profile):
    """Query 12 weeks of day grade weekly averages + weight trajectory for journey assessment."""
    today = datetime.now(timezone.utc).date()
    w12_start = (today - timedelta(days=84)).isoformat()
    w1_end = (today - timedelta(days=1)).isoformat()

    # 12 weeks of day grades
    all_grades = query_range("day_grade", w12_start, w1_end)
    weekly_avgs = []
    for week_num in range(12, 0, -1):
        ws = (today - timedelta(days=week_num * 7)).isoformat()
        we = (today - timedelta(days=(week_num - 1) * 7)).isoformat()
        week_scores = []
        for d, r in all_grades.items():
            if ws <= d <= we:
                s = safe_float(r, "total_score")
                if s is not None:
                    week_scores.append(s)
        weekly_avgs.append({
            "week": f"W-{week_num}",
            "dates": f"{ws} to {we}",
            "avg_score": round(sum(week_scores) / len(week_scores), 1) if week_scores else None,
            "days_graded": len(week_scores),
        })

    # 12 weeks of Whoop HRV
    all_whoop = query_range("whoop", w12_start, w1_end)
    weekly_hrvs = []
    for week_num in range(12, 0, -1):
        ws = (today - timedelta(days=week_num * 7)).isoformat()
        we = (today - timedelta(days=(week_num - 1) * 7)).isoformat()
        wk_hrvs = []
        for d, r in all_whoop.items():
            if ws <= d <= we:
                h = safe_float(r, "hrv")
                if h is not None:
                    wk_hrvs.append(h)
        weekly_hrvs.append({
            "week": f"W-{week_num}",
            "hrv_avg": round(sum(wk_hrvs) / len(wk_hrvs), 1) if wk_hrvs else None,
            "days": len(wk_hrvs),
        })

    # 12 weeks of nutrition logging
    all_mf = query_range("macrofactor", w12_start, w1_end)
    weekly_nutrition = []
    for week_num in range(12, 0, -1):
        ws = (today - timedelta(days=week_num * 7)).isoformat()
        we = (today - timedelta(days=(week_num - 1) * 7)).isoformat()
        wk_days = 0
        wk_cals = []
        wk_prots = []
        for d, r in all_mf.items():
            if ws <= d <= we:
                wk_days += 1
                c = safe_float(r, "total_calories_kcal")
                p = safe_float(r, "total_protein_g")
                if c is not None: wk_cals.append(c)
                if p is not None: wk_prots.append(p)
        weekly_nutrition.append({
            "week": f"W-{week_num}",
            "days_logged": wk_days,
            "cal_avg": round(sum(wk_cals) / len(wk_cals)) if wk_cals else None,
            "protein_avg": round(sum(wk_prots) / len(wk_prots)) if wk_prots else None,
        })

    # 12 weeks of weight
    all_weight = query_range("withings", w12_start, w1_end)
    weekly_weights = []
    for week_num in range(12, 0, -1):
        ws = (today - timedelta(days=week_num * 7)).isoformat()
        we = (today - timedelta(days=(week_num - 1) * 7)).isoformat()
        wk_weights = []
        for d, r in all_weight.items():
            if ws <= d <= we:
                w = safe_float(r, "weight_lbs")
                if w is not None:
                    wk_weights.append(w)
        weekly_weights.append({
            "week": f"W-{week_num}",
            "avg_weight": round(sum(wk_weights) / len(wk_weights), 1) if wk_weights else None,
        })

    # Overall grade stats from all 12 weeks
    all_scores = [safe_float(r, "total_score") for r in all_grades.values() if safe_float(r, "total_score") is not None]
    grade_dist = defaultdict(int)
    for r in all_grades.values():
        g = r.get("letter_grade", "")
        if g.startswith("A"): grade_dist["A"] += 1
        elif g.startswith("B"): grade_dist["B"] += 1
        elif g.startswith("C"): grade_dist["C"] += 1
        elif g == "D": grade_dist["D"] += 1
        elif g == "F": grade_dist["F"] += 1

    start_weight = profile.get("journey_start_weight_lbs", 302)
    goal_weight = profile.get("goal_weight_lbs", 185)
    latest_weight = None
    for ww in reversed(weekly_weights):
        if ww.get("avg_weight"):
            latest_weight = ww["avg_weight"]
            break

    return {
        "weekly_grade_avgs": weekly_avgs,
        "weekly_hrvs": weekly_hrvs,
        "weekly_nutrition": weekly_nutrition,
        "weekly_weights": weekly_weights,
        "overall_12wk_avg": round(sum(all_scores) / len(all_scores), 1) if all_scores else None,
        "overall_12wk_grade_dist": dict(grade_dist),
        "total_days_graded": len(all_scores),
        "journey_start_weight": start_weight,
        "goal_weight": goal_weight,
        "latest_weight": latest_weight,
        "total_lost": round(start_weight - latest_weight, 1) if latest_weight else None,
        "pct_to_goal": round((start_weight - latest_weight) / (start_weight - goal_weight) * 100) if latest_weight and start_weight > goal_weight else None,
    }


def call_journey_haiku(journey_ctx, week_summary, api_key):
    """Second Haiku call for journey-level assessment."""
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001", "max_tokens": 800,
        "messages": [{"role": "user", "content": JOURNEY_PROMPT.format(
            journey_json=json.dumps(journey_ctx, indent=2, default=str),
            week_summary=week_summary)}]
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

def build_html(data, commentary, journey_commentary, profile):
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

    insight_box = (f'<div style="background:#fffbeb;border:2px solid #f59e0b;border-radius:10px;'
                   f'padding:16px 20px;margin-bottom:24px;">{insight_html}</div>') if insight_html else ""

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
    sleep_avg = comp_avgs.get("sleep_quality") or (t["eightsleep"]["score_avg"] if t.get("eightsleep") else None)
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
    if t.get("eightsleep"):
        s = t["eightsleep"]; sp = p.get("eightsleep") or {}
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
        if m.get("alcohol_drinks") and m["alcohol_drinks"] > 0:
            acol = "#e74c3c" if m["alcohol_drinks"] >= 7 else "#e67e22" if m["alcohol_drinks"] >= 3 else "#27ae60"
            nu_rows += row("🍺 Alcohol", f'<span style="color:{acol};font-weight:700;">{m["alcohol_drinks"]} drinks</span> ({m["alcohol_days"]} days)')
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
    # Steps
    if t.get("apple") and t["apple"].get("steps_avg"):
        a = t["apple"]; ap = p.get("apple") or {}
        step_target = profile.get("step_target", 8000)
        sa = a["steps_avg"]
        scol = "#059669" if sa >= step_target else "#d97706" if sa >= step_target * 0.75 else "#dc2626"
        cgm_rows += row("Avg Steps", f'<span style="color:{scol};font-weight:700;">{fmt_num(sa)}</span> (target {fmt_num(step_target)})',
            delta_html(sa, ap.get("steps_avg"), ""), highlight=True)
        if a.get("steps_total"):
            cgm_rows += row("Total Steps", fmt_num(a["steps_total"]))
    # Gait
    if t.get("apple") and t["apple"].get("gait_speed_avg"):
        a = t["apple"]
        gs = a["gait_speed_avg"]
        gs_col = "#059669" if gs >= 3.0 else "#d97706" if gs >= 2.24 else "#dc2626"
        cgm_rows += row("Walking Speed", f'<span style="color:{gs_col};">{fmt(gs, " mph")}</span> ({a.get("gait_days", 0)} days)')
    cgm_section = section("Steps, CGM & Mobility", "📊", tbl(cgm_rows)) if cgm_rows else ""

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

    # ── Journey Assessment (second AI call) ──
    journey_html = ""
    if journey_commentary:
        jc_html = ""
        for line in journey_commentary.strip().split("\n"):
            if any(line.startswith(e) for e in ("📊", "🔍", "🎯", "💪")):
                jc_html += f'<p style="font-size:13px;font-weight:700;color:#1a1a2e;margin:16px 0 4px;">{line}</p>'
            elif line.strip():
                jc_html += f'<p style="font-size:13px;color:#333;line-height:1.6;margin:0 0 8px;">{line}</p>'
        journey_html = (
            f'<div style="margin-bottom:28px;">'
            f'<h2 style="font-size:15px;font-weight:700;color:#1a1a2e;margin:0 0 8px;'
            f'border-bottom:2px solid #e8e8f0;padding-bottom:6px;">🏁 Journey Assessment — Board of Directors</h2>'
            f'<div style="background:linear-gradient(135deg,#f0fdf4,#ecfdf5);border-left:4px solid #059669;'
            f'padding:16px;border-radius:0 8px 8px 0;">{jc_html}</div></div>'
        )

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
{scorecard_html}
{insight_box}
{board_section}
{insights_html}
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
{journey_html}
</div>
<div style="background:#f8f8fc;padding:16px 32px;border-top:1px solid #e8e8f0;">
<p style="color:#999;font-size:11px;margin:0;">Life Platform v4.2 · Whoop · Eight Sleep · Withings · Strava · MacroFactor · Habitify · Notion · Apple Health · Todoist · AWS us-west-2</p>
</div></div></body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

# ==============================================================================
# CLINICAL JSON — Dashboard Phase 2 (v2.39.0)
# ==============================================================================

def _query_source_all(source):
    """Query all items for a source partition (labs, dexa, etc)."""
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": pk, ":prefix": "DATE#"},
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return d2f(sorted(items, key=lambda x: x.get("sk", "")))


def _query_genome_all():
    """Query all genome items."""
    pk = f"USER#{USER_ID}#SOURCE#genome"
    kwargs = {
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": pk},
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return d2f(items)


def write_clinical_json(data, profile):
    """Build and write clinical.json to S3 for the clinical summary page."""
    try:
        today = datetime.now(timezone.utc).date()
        thirty_ago = (today - timedelta(days=30)).isoformat()
        yesterday = (today - timedelta(days=1)).isoformat()

        # ── LABS ──
        lab_draws = _query_source_all("labs")
        labs_section = {}
        labs_flagged = []

        if lab_draws:
            latest_draw = lab_draws[-1]
            labs_section["latest_draw_date"] = latest_draw.get("draw_date")
            labs_section["provider"] = latest_draw.get("lab_provider")
            labs_section["total_draws"] = len(lab_draws)

            # Build markers table from latest draw
            markers = []
            bms = latest_draw.get("biomarkers", {})
            priority_cats = ["lipids", "metabolic", "diabetes", "cbc", "thyroid",
                             "liver", "kidney", "inflammation", "hormones"]
            all_keys = []
            for k, v in bms.items():
                cat = v.get("category", "")
                pri = priority_cats.index(cat) if cat in priority_cats else 99
                all_keys.append((pri, k, v))
            all_keys.sort()

            for _, key, bm in all_keys:
                val = bm.get("value_numeric") or bm.get("value")
                flag = bm.get("flag")
                rl, rh = bm.get("ref_low"), bm.get("ref_high")
                range_str = ""
                if rl is not None and rh is not None:
                    range_str = f"{rl}-{rh}"
                elif rl is not None:
                    range_str = f">{rl}"
                elif rh is not None:
                    range_str = f"<{rh}"
                norm_flag = flag.upper() if flag and flag not in ("normal", None) else None
                markers.append({
                    "name": bm.get("name", key),
                    "value": val,
                    "unit": bm.get("unit", ""),
                    "range": range_str,
                    "flag": norm_flag,
                    "category": bm.get("category", ""),
                })
            labs_section["markers"] = markers
            labs_section["flagged_count"] = sum(1 for m in markers if m.get("flag"))

            # Out-of-range history
            oor_map = {}
            for draw in lab_draws:
                for key, bm in draw.get("biomarkers", {}).items():
                    if bm.get("flag") in ("high", "low"):
                        if key not in oor_map:
                            oor_map[key] = {"name": bm.get("name", key), "count": 0,
                                            "latest_value": None}
                        oor_map[key]["count"] += 1
                        oor_map[key]["latest_value"] = bm.get("value_numeric") or bm.get("value")

            for key, info in sorted(oor_map.items(), key=lambda x: -x[1]["count"]):
                tested = sum(1 for d in lab_draws if key in d.get("biomarkers", {}))
                rate = round(100 * info["count"] / max(tested, 1), 1)
                persistence = "chronic" if rate >= 60 else ("recurring" if rate >= 30 else "occasional")
                labs_flagged.append({
                    "name": info["name"],
                    "persistence": persistence,
                    "draws_flagged": info["count"],
                    "total_draws": tested,
                    "latest_value": info["latest_value"],
                })

        # ── DEXA ──
        dexa_scans = _query_source_all("dexa")
        body_comp = {}
        if dexa_scans:
            scan = dexa_scans[-1]
            bc = scan.get("body_composition", {})
            height_in = profile.get("height_inches", 72)
            height_m = height_in * 0.0254
            lean_lb = bc.get("lean_mass_lb") or 0
            lean_kg = lean_lb * 0.4536
            ffmi = round(lean_kg / (height_m ** 2), 1) if height_m > 0 else None
            body_comp = {
                "scan_date": scan.get("scan_date"),
                "body_fat_pct": bc.get("body_fat_pct"),
                "lean_mass_lbs": lean_lb,
                "ffmi": ffmi,
                "visceral_fat_area_cm2": bc.get("visceral_fat_area_cm2") or bc.get("visceral_fat_g"),
                "bmd_t_score": bc.get("bmd_t_score"),
            }

        # ── SUPPLEMENTS ──
        supp_recs = query_range("supplements", thirty_ago, yesterday)
        seen_supps = {}
        for date_key, rec in supp_recs.items():
            entries = rec.get("entries", [])
            if isinstance(entries, list):
                for e in entries:
                    name = (e.get("name") or "").strip()
                    if name and name not in seen_supps:
                        seen_supps[name] = {
                            "name": name,
                            "dose": e.get("dose"),
                            "unit": e.get("unit", ""),
                            "timing": e.get("timing", ""),
                            "category": e.get("category", "supplement"),
                        }
        supplements = list(seen_supps.values())

        # ── GENOME FLAGS ──
        genome_all = _query_genome_all()
        genome_flags = []
        for snp in genome_all:
            if snp.get("sk", "").startswith("GENE#"):
                risk = snp.get("risk_level", "")
                if risk in ("unfavorable", "mixed"):
                    genome_flags.append({
                        "gene": snp.get("gene"),
                        "rsid": snp.get("rsid"),
                        "variant": snp.get("genotype"),
                        "risk": risk,
                        "category": snp.get("category", ""),
                        "note": snp.get("summary", ""),
                    })
        genome_flags.sort(key=lambda x: (0 if x["risk"] == "unfavorable" else 1, x.get("category", "")))

        # ── 30-DAY SLEEP ──
        sleep_recs = query_range("eightsleep", thirty_ago, yesterday)
        sleep_summary = {}
        if sleep_recs:
            scores = [safe_float(r, "sleep_score") for r in sleep_recs.values() if safe_float(r, "sleep_score")]
            durations = [safe_float(r, "sleep_duration_hours") for r in sleep_recs.values() if safe_float(r, "sleep_duration_hours")]
            effs = [safe_float(r, "sleep_efficiency_pct") for r in sleep_recs.values() if safe_float(r, "sleep_efficiency_pct")]
            deeps = [safe_float(r, "deep_pct") for r in sleep_recs.values() if safe_float(r, "deep_pct")]
            rems = [safe_float(r, "rem_pct") for r in sleep_recs.values() if safe_float(r, "rem_pct")]
            sleep_summary = {
                "avg_score": avg(scores),
                "avg_duration_hrs": avg(durations),
                "avg_efficiency_pct": avg(effs),
                "avg_deep_pct": avg(deeps),
                "avg_rem_pct": avg(rems),
                "days_with_data": len(scores),
            }

        # ── 30-DAY ACTIVITY ──
        strava_recs = query_range("strava", thirty_ago, yesterday)
        activity_summary = {}
        if strava_recs:
            max_hr = profile.get("max_heart_rate", 184)
            z2_lo, z2_hi = max_hr * 0.60, max_hr * 0.70
            total_sessions = 0
            z2_total_min = 0.0
            type_counts = {}
            for day_rec in strava_recs.values():
                for act in (day_rec.get("activities") or []):
                    total_sessions += 1
                    sport = act.get("sport_type") or act.get("type") or "Other"
                    type_counts[sport] = type_counts.get(sport, 0) + 1
                    avg_hr = safe_float(act, "average_heartrate")
                    dur_s = safe_float(act, "moving_time_seconds") or 0
                    if avg_hr and z2_lo <= avg_hr <= z2_hi:
                        z2_total_min += dur_s / 60

            weeks = max(1, (today - datetime.strptime(thirty_ago, "%Y-%m-%d").date()).days / 7)
            activity_summary = {
                "total_sessions_30d": total_sessions,
                "zone2_weekly_avg_min": round(z2_total_min / weeks),
                "types": type_counts,
            }

        # Avg strain from Whoop
        whoop_recs = query_range("whoop", thirty_ago, yesterday)
        vitals_summary = {}
        if whoop_recs:
            strains = [safe_float(r, "strain") for r in whoop_recs.values() if safe_float(r, "strain")]
            if strains:
                activity_summary["avg_strain"] = avg(strains)

            rhrs = [safe_float(r, "resting_heart_rate") for r in whoop_recs.values() if safe_float(r, "resting_heart_rate")]
            hrvs = [safe_float(r, "hrv") for r in whoop_recs.values() if safe_float(r, "hrv")]
            if rhrs:
                vitals_summary["rhr_avg"] = avg(rhrs)
                first_half, second_half = rhrs[:len(rhrs)//2], rhrs[len(rhrs)//2:]
                if first_half and second_half:
                    diff = avg(second_half) - avg(first_half)
                    vitals_summary["rhr_trend"] = "declining" if diff < -1 else ("rising" if diff > 1 else "stable")
            if hrvs:
                vitals_summary["hrv_avg_ms"] = avg(hrvs)
                first_half, second_half = hrvs[:len(hrvs)//2], hrvs[len(hrvs)//2:]
                if first_half and second_half:
                    diff = avg(second_half) - avg(first_half)
                    vitals_summary["hrv_trend"] = "improving" if diff > 1 else ("declining" if diff < -1 else "stable")

        # ── 30-DAY GLUCOSE ──
        apple_recs = query_range("apple_health", thirty_ago, yesterday)
        glucose_summary = {}
        if apple_recs:
            avgs = [safe_float(r, "blood_glucose_avg") for r in apple_recs.values() if safe_float(r, "blood_glucose_avg")]
            tirs = [safe_float(r, "blood_glucose_time_in_range_pct") for r in apple_recs.values() if safe_float(r, "blood_glucose_time_in_range_pct")]
            sds = [safe_float(r, "blood_glucose_std_dev") for r in apple_recs.values() if safe_float(r, "blood_glucose_std_dev")]
            mins = [safe_float(r, "blood_glucose_min") for r in apple_recs.values() if safe_float(r, "blood_glucose_min")]
            glucose_summary = {
                "avg_mg_dl": avg(avgs),
                "time_in_range_pct": avg(tirs),
                "variability_sd": avg(sds),
                "fasting_proxy_mg_dl": avg(mins),
                "days_with_data": len(avgs),
            }

        # ── WEIGHT (from Withings) ──
        withings_recs = query_range("withings", thirty_ago, yesterday)
        weight_current = None
        weight_30d_delta = None
        if withings_recs:
            sorted_dates = sorted(withings_recs.keys())
            for d in reversed(sorted_dates):
                w = safe_float(withings_recs[d], "weight_lbs")
                if w:
                    weight_current = round(w, 1)
                    break
            # Find weight ~30 days ago for delta
            if weight_current and sorted_dates:
                earliest_w = None
                for d in sorted_dates[:5]:  # first few days of range
                    w = safe_float(withings_recs[d], "weight_lbs")
                    if w:
                        earliest_w = round(w, 1)
                        break
                if earliest_w:
                    weight_30d_delta = round(weight_current - earliest_w, 1)
        vitals_summary["weight_current_lbs"] = weight_current
        vitals_summary["weight_30d_delta_lbs"] = weight_30d_delta

        # ── STEPS (from Apple Health) ──
        steps_vals = [safe_float(r, "steps") for r in apple_recs.values() if safe_float(r, "steps")]
        if steps_vals:
            vitals_summary["avg_daily_steps"] = round(avg(steps_vals))

        # ── METADATA ──
        source_count = sum(1 for x in [withings_recs, sleep_recs, strava_recs,
                                        whoop_recs, apple_recs, supp_recs,
                                        lab_draws, dexa_scans, genome_all]
                           if x)

        # ── ASSEMBLE ──
        clinical = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "weekly-digest",
            "period": "30-day",
            "patient_name": profile.get("name", "Matthew Walker"),
            "report_date": yesterday,
            "report_period": f"30 days ending {yesterday}",
            "sources_active": source_count,
            "vitals_summary": vitals_summary,
            "labs": labs_section,
            "labs_flagged": labs_flagged,
            "supplements": supplements,
            "body_composition": body_comp,
            "sleep_summary": sleep_summary,
            "activity_summary": activity_summary,
            "glucose_summary": glucose_summary,
            "genome_flags": genome_flags,
        }

        s3.put_object(
            Bucket=DASHBOARD_BUCKET,
            Key=CLINICAL_KEY,
            Body=json.dumps(clinical, default=str),
            ContentType="application/json",
            CacheControl="max-age=3600",
        )
        print("[INFO] Clinical JSON written to s3://" + DASHBOARD_BUCKET + "/" + CLINICAL_KEY)

    except Exception as e:
        print("[WARN] Clinical JSON write failed: " + str(e))
        import traceback
        traceback.print_exc()


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
    print("[INFO] Calling Haiku for Board commentary...")
    try:
        commentary = call_haiku(data, profile, api_key)
    except Exception as e:
        print(f"[WARN] Haiku failed: {e}")
        commentary = ("🎯 THE CHAIR — OVERVIEW\nCommentary unavailable.\n"
                      "💡 INSIGHT OF THE WEEK\nReview data sections below.")

    # ── Journey Assessment (second AI call) ──
    print("[INFO] Gathering 12-week journey context...")
    journey_ctx = gather_journey_context(profile)
    # Build a compact week summary for the journey prompt
    dg = data["this"].get("day_grades")
    week_summary_parts = []
    if dg:
        week_summary_parts.append(f"Day grade avg: {dg['avg_score']} ({dg['days_graded']}d)")
    if data["this"].get("whoop"):
        week_summary_parts.append(f"Recovery: {data['this']['whoop'].get('recovery_avg')}%, HRV: {data['this']['whoop'].get('hrv_avg')}ms")
    if data["this"].get("eightsleep"):
        week_summary_parts.append(f"Sleep score: {data['this']['eightsleep'].get('score_avg')}%")
    if data["this"].get("macrofactor"):
        week_summary_parts.append(f"Calories: {data['this']['macrofactor'].get('calories_avg')} kcal, Protein: {data['this']['macrofactor'].get('protein_avg_g')}g")
    if data["this"].get("withings"):
        week_summary_parts.append(f"Weight: {data['this']['withings'].get('weight_latest')} lbs")
    if data["this"].get("strava"):
        week_summary_parts.append(f"Zone 2: {data['this']['strava'].get('zone2_minutes')} min")
    if data["this"].get("habitify"):
        week_summary_parts.append(f"MVP habits: {data['this']['habitify'].get('mvp_avg_pct')}%")
    week_summary = " | ".join(week_summary_parts)

    journey_commentary = None
    print("[INFO] Calling Haiku for Journey Assessment...")
    try:
        journey_commentary = call_journey_haiku(journey_ctx, week_summary, api_key)
    except Exception as e:
        print(f"[WARN] Journey Haiku failed: {e}")

    html = build_html(data, commentary, journey_commentary, profile)

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

    # Write clinical JSON to S3 for dashboard clinical view (non-fatal)
    try:
        write_clinical_json(data, profile)
    except Exception as e:
        print(f"[WARN] Clinical JSON top-level failed: {e}")

    return {"statusCode": 200, "body": "Digest v4.0 sent."}
