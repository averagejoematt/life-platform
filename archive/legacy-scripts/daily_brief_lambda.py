"""
Daily Brief Lambda — v2.1.0 (Expanded Brief)
Fires at 10:00am PT daily (18:00 UTC via EventBridge).

Sections:
  1.  Day Grade — weighted 0-100 composite + letter grade
  2.  Yesterday's Scorecard — 8 component scores in a grid
  3.  Readiness Signal — Whoop recovery (today, from 9:30 AM refresh)
  4.  Training Report — activities + AI coach commentary
  5.  Nutrition Report — macros, meals + AI nutritionist commentary
  6.  Habits Deep-Dive — MVP checklist + group breakdown
  7.  CGM Spotlight — glucose metrics
  8.  Habit Streaks — MVP streak + full streak
  9.  Weight Phase Tracker — phase, rate vs target, milestone ETA
  10. Today's Guidance — profile-driven train/caffeine/sleep
  11. Journal Pulse — mood/energy/stress/themes
  12. Journal Coach — AI perspective + one tactical thing for today
  13. Board of Directors Insight — multi-sentence coaching paragraph
  14. Anomaly Alert — multi-source anomalies (if triggered)

Profile-driven: all targets read from DynamoDB PROFILE#v1. No hardcoded constants.
3 AI calls: Board of Directors, Training+Nutrition Coach, Journal Coach (all Haiku).
"""

import json
import math
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")
ses      = boto3.client("sesv2", region_name="us-west-2")
secrets  = boto3.client("secretsmanager", region_name="us-west-2")

RECIPIENT = "awsdev@mattsusername.com"
SENDER    = "awsdev@mattsusername.com"


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

def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))

def fmt_num(val):
    """Format number with commas, safe for f-strings in Python 3.11."""
    if val is None:
        return "—"
    return "{:,}".format(round(val))

def fetch_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": "USER#matthew#SOURCE#" + source, "sk": "DATE#" + date_str})
        return d2f(r.get("Item"))
    except Exception:
        return None

def fetch_range(source, start, end):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": "USER#matthew#SOURCE#" + source,
                                       ":s": "DATE#" + start, ":e": "DATE#" + end})
        return [d2f(i) for i in r.get("Items", [])]
    except Exception:
        return []

def fetch_journal_entries(date_str):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": "USER#matthew#SOURCE#notion",
                ":prefix": "DATE#" + date_str + "#journal#"
            })
        return [d2f(i) for i in r.get("Items", [])]
    except Exception as e:
        print("[WARN] fetch_journal_entries: " + str(e))
        return []

def call_anthropic(prompt, api_key, max_tokens=200):
    """Single Haiku call with retry."""
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


# ══════════════════════════════════════════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════════════════════════════════════════

def fetch_profile():
    try:
        r = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"})
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


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def gather_daily_data(profile, yesterday):
    today = datetime.now(timezone.utc).date()

    whoop       = fetch_date("whoop",        yesterday)
    sleep       = fetch_date("eightsleep",   yesterday)
    apple       = fetch_date("apple_health", yesterday)
    macrofactor = fetch_date("macrofactor",  yesterday)
    strava      = fetch_date("strava",       yesterday)
    habitify    = fetch_date("habitify",     yesterday)
    garmin      = fetch_date("garmin",       yesterday)
    whoop_today = fetch_date("whoop", today.isoformat())

    journal_entries = fetch_journal_entries(yesterday)
    journal = extract_journal_signals(journal_entries)

    hrv_7d_recs  = fetch_range("whoop", (today - timedelta(days=7)).isoformat(), yesterday)
    hrv_30d_recs = fetch_range("whoop", (today - timedelta(days=30)).isoformat(), yesterday)
    hrv_7d_vals  = [float(r["hrv"]) for r in hrv_7d_recs  if "hrv" in r]
    hrv_30d_vals = [float(r["hrv"]) for r in hrv_30d_recs if "hrv" in r]

    strava_60d = fetch_range("strava", (today - timedelta(days=60)).isoformat(), yesterday)
    tsb = compute_tsb(strava_60d, today)

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

    anomaly = fetch_anomaly_record(yesterday)

    return {
        "date": yesterday,
        "whoop": whoop, "whoop_today": whoop_today, "sleep": sleep,
        "apple": apple, "macrofactor": macrofactor, "strava": strava,
        "habitify": habitify, "garmin": garmin,
        "hrv": {"hrv_7d": avg(hrv_7d_vals), "hrv_30d": avg(hrv_30d_vals),
                "hrv_yesterday": safe_float(whoop, "hrv")},
        "tsb": tsb,
        "journal": journal, "journal_entries": journal_entries,
        "anomaly": anomaly,
        "latest_weight": latest_weight, "week_ago_weight": week_ago_weight,
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
        r = table.get_item(Key={"pk": "USER#matthew#SOURCE#anomalies", "sk": "DATE#" + date_str})
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


# ══════════════════════════════════════════════════════════════════════════════
# COMPONENT SCORERS (each → 0-100, or None if no data)
# ══════════════════════════════════════════════════════════════════════════════

def score_sleep(data, profile):
    sleep = data.get("sleep")
    if not sleep:
        return None, {}
    sleep_score = safe_float(sleep, "sleep_score")
    efficiency = safe_float(sleep, "sleep_efficiency")
    total_secs = safe_float(sleep, "total_sleep_seconds")
    target_hrs = profile.get("sleep_target_hours_ideal", 7.5)
    details = {"sleep_score": sleep_score, "efficiency": efficiency,
               "duration_hrs": round(total_secs / 3600, 1) if total_secs else None,
               "target_hrs": target_hrs}
    parts, weights = [], []
    if sleep_score is not None:
        parts.append(sleep_score * 0.40); weights.append(0.40)
    if efficiency is not None:
        parts.append(efficiency * 0.30); weights.append(0.30)
    if total_secs is not None:
        dur_hrs = total_secs / 3600
        dur_score = clamp(100 - (abs(dur_hrs - target_hrs) / 2.0) * 100)
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
        if act_count > 0:
            exercise_score = min(100, 70 + (total_time / 60) * 0.5)
        else:
            exercise_score = 0
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


def score_habits_mvp(data, profile):
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
    if water_ml is None:
        return None, {}
    score = clamp(round(min(100, water_ml / target_ml * 100)))
    return score, {"water_ml": round(water_ml), "water_oz": round(water_ml / 29.5735, 1),
                   "target_oz": round(target_ml / 29.5735, 1)}


def score_journal(data, profile):
    entries = data.get("journal_entries", [])
    if not entries:
        return 0, {"entries": 0}
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


# ══════════════════════════════════════════════════════════════════════════════
# DAY GRADE
# ══════════════════════════════════════════════════════════════════════════════

COMPONENT_SCORERS = {
    "sleep_quality": score_sleep, "recovery": score_recovery,
    "nutrition": score_nutrition, "movement": score_movement,
    "habits_mvp": score_habits_mvp, "hydration": score_hydration,
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
        item = {"pk": "USER#matthew#SOURCE#day_grade", "sk": "DATE#" + date_str,
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


# ══════════════════════════════════════════════════════════════════════════════
# HABIT STREAKS
# ══════════════════════════════════════════════════════════════════════════════

def compute_habit_streaks(profile, yesterday_str):
    mvp_list = profile.get("mvp_habits", [])
    mvp_streak = 0
    full_streak = 0
    mvp_broken = False
    full_broken = False
    for i in range(0, 90):
        date_str = (datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = fetch_date("habitify", date_str)
        if not rec:
            break
        habits_map = rec.get("habits", {})
        completion = safe_float(rec, "completion_pct")
        if not mvp_broken:
            all_mvp = True
            for habit in mvp_list:
                done = habits_map.get(habit, 0)
                if not (done is not None and float(done) >= 1):
                    all_mvp = False
                    break
            if all_mvp: mvp_streak += 1
            else: mvp_broken = True
        if not full_broken:
            if completion is not None and completion >= 1.0: full_streak += 1
            else: full_broken = True
        if mvp_broken and full_broken:
            break
    return mvp_streak, full_streak


# ══════════════════════════════════════════════════════════════════════════════
# READINESS
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# GUIDANCE
# ══════════════════════════════════════════════════════════════════════════════

def derive_guidance(data, readiness_score, colour, profile):
    if colour == "green": train = "Hard session OK — you're fresh and recovered"
    elif colour == "yellow": train = "Moderate session — avoid max effort today"
    else: train = "Easy or rest day — your body needs recovery"
    hrv_7d = data["hrv"].get("hrv_7d")
    hrv_30d = data["hrv"].get("hrv_30d")
    if hrv_7d and hrv_30d and hrv_7d < hrv_30d * 0.95:
        caffeine_cutoff, caffeine_note = "12:00pm", "HRV trending down"
    elif colour == "red":
        caffeine_cutoff, caffeine_note = "12:00pm", "Low readiness"
    elif colour == "yellow":
        caffeine_cutoff, caffeine_note = "1:00pm", "Standard cutoff"
    else:
        caffeine_cutoff, caffeine_note = "2:00pm", "Good recovery"
    bedtime = profile.get("bedtime_target", "21:00")
    try:
        bed_time_display = datetime.strptime(bedtime, "%H:%M").strftime("%-I:%M %p").lower()
    except Exception:
        bed_time_display = "9:00 pm"
    sleep_dur_secs = safe_float(data.get("sleep"), "total_sleep_seconds")
    target_hrs = profile.get("sleep_target_hours_ideal", 7.5)
    if sleep_dur_secs and sleep_dur_secs / 3600 < target_hrs - 0.5:
        debt = round(target_hrs - sleep_dur_secs / 3600, 1)
        sleep_note = "You're " + str(debt) + "hrs short — bed 30 min early"
    else:
        sleep_note = "Target " + str(target_hrs) + "hrs tonight"
    ew_start = profile.get("eating_window_start", "11:30")
    ew_end = profile.get("eating_window_end", "19:30")
    try:
        ews = datetime.strptime(ew_start, "%H:%M").strftime("%-I:%M %p").lower()
        ewe = datetime.strptime(ew_end, "%H:%M").strftime("%-I:%M %p").lower()
        eating_window = ews + " - " + ewe
    except Exception:
        eating_window = "11:30 am - 7:30 pm"
    return {"train": train, "caffeine_cutoff": caffeine_cutoff, "caffeine_note": caffeine_note,
            "bed_time": bed_time_display, "sleep_note": sleep_note, "eating_window": eating_window}


# ══════════════════════════════════════════════════════════════════════════════
# AI CALLS: Board of Directors, Training+Nutrition Coach, Journal Coach
# ══════════════════════════════════════════════════════════════════════════════

def build_data_summary(data, profile):
    """Shared data payload for AI prompts."""
    journal = data.get("journal") or {}
    mf = data.get("macrofactor") or {}
    strava = data.get("strava") or {}
    habitify = data.get("habitify") or {}
    apple = data.get("apple") or {}
    return {
        "date": data.get("date"),
        "recovery_score": safe_float(data.get("whoop"), "recovery_score"),
        "strain": safe_float(data.get("whoop"), "strain"),
        "sleep_score": safe_float(data.get("sleep"), "sleep_score"),
        "sleep_duration_hrs": round((safe_float(data.get("sleep"), "total_sleep_seconds") or 0) / 3600, 1),
        "hrv_yesterday": data["hrv"].get("hrv_yesterday"),
        "hrv_7d_avg": data["hrv"].get("hrv_7d"),
        "calories": safe_float(mf, "total_calories_kcal"),
        "protein_g": safe_float(mf, "total_protein_g"),
        "fat_g": safe_float(mf, "total_fat_g"),
        "carbs_g": safe_float(mf, "total_carbs_g"),
        "fiber_g": safe_float(mf, "total_fiber_g"),
        "steps": safe_float(apple, "steps"),
        "water_ml": safe_float(apple, "water_intake_ml"),
        "glucose_avg": safe_float(apple, "blood_glucose_avg"),
        "glucose_tir": safe_float(apple, "blood_glucose_time_in_range_pct"),
        "habits_completed": safe_float(habitify, "total_completed"),
        "habits_possible": safe_float(habitify, "total_possible"),
        "exercise_count": safe_float(strava, "activity_count"),
        "exercise_minutes": round((safe_float(strava, "total_moving_time_seconds") or 0) / 60, 1),
        "journal_mood": journal.get("mood_avg"),
        "journal_energy": journal.get("energy_avg"),
        "journal_stress": journal.get("stress_avg"),
        "current_weight": data.get("latest_weight"),
    }


def build_food_summary(data):
    """Extract meal timeline from MacroFactor food_log."""
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


def call_training_nutrition_coach(data, profile, api_key):
    """AI call: Training coach + Nutritionist combined."""
    data_summary = build_data_summary(data, profile)
    food_summary = build_food_summary(data)
    activity_summary = build_activity_summary(data)
    prompt = """You are two coaches speaking to Matthew, a 36yo man in Phase 1 of weight loss (302->185 lbs, 1800 cal/day, 190g protein target).
Tone: direct, specific, no-BS.

ACTIVITIES YESTERDAY:
""" + activity_summary + """

FOOD LOG YESTERDAY:
""" + food_summary + """

MACRO TOTALS: """ + json.dumps({k: data_summary[k] for k in ["calories", "protein_g", "fat_g", "carbs_g", "fiber_g"] if k in data_summary}, default=str) + """
TARGETS: 1800 cal, P190g, F60g, C125g

Respond in EXACTLY this JSON format, no other text:
{"training": "2-3 sentences from sports scientist about yesterday's training — what went well, what to watch, how it connects to goals. Reference specific numbers.", "nutrition": "2-3 sentences from nutritionist about yesterday's diet — macro adherence, meal timing, specific foods, what to adjust today. Reference specific numbers. Be direct about gaps."}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=350)
        # Strip markdown fences if present
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
    """AI call: Journal reflection + one tactical thing for today."""
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
    prompt = """You are a wise, warm-but-direct inner coach reading Matthew's journal from yesterday. He's 36, losing 117 lbs, battling: """ + obstacles_str + """.

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


def call_board_of_directors(data, profile, day_grade, grade, component_scores, api_key):
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
    prompt = """You are the Board of Directors for Project40 — sports scientist + nutritionist + sleep specialist + behavioral coach unified.
Speaking to Matthew, 36yo, losing 117 lbs (302->185). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.
Tone: direct, empathetic, no-BS.
""" + health_ctx + """

YESTERDAY'S DATA:
""" + json.dumps(data_summary, indent=2, default=str) + """

DAY GRADE: """ + str(day_grade if day_grade is not None else "N/A") + "/100 (" + grade + """)
""" + component_summary + """
""" + journal_ctx + """

Write 2-3 sentences. Reference specific numbers (at least two). Connect yesterday to today. Celebrate wins briefly, name gaps directly. DO NOT start with "Matthew". Max 60 words."""

    return call_anthropic(prompt, api_key, max_tokens=200)


# ══════════════════════════════════════════════════════════════════════════════
# HTML BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def hrv_trend_str(hrv_7d, hrv_30d):
    if not hrv_7d or not hrv_30d or hrv_30d == 0:
        return "no trend data"
    pct = round((hrv_7d / hrv_30d - 1) * 100)
    arrow = "+" if pct >= 0 else ""
    direction = "trending up" if pct >= 2 else "stable" if pct >= -2 else "trending down"
    return str(round(hrv_7d)) + "ms 7d avg (" + arrow + str(pct) + "% vs 30d, " + direction + ")"


def build_section(colour, icon, title, content):
    """Reusable section builder for the bordered cards."""
    return (
        '<div style="background:' + colour + ';border-left:3px solid;border-radius:0 8px 8px 0;'
        'padding:10px 16px;margin:12px 16px 0;">'
        '<p style="font-size:11px;font-weight:700;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">'
        + icon + ' ' + title + '</p>' + content + '</div>'
    )


def build_html(data, profile, day_grade_score, grade, component_scores, component_details,
               readiness_score, readiness_colour, guidance, bod_insight,
               training_nutrition, journal_coach_text, mvp_streak, full_streak):

    date_str = data["date"]
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_label = dt.strftime("%A, %b %-d")
    except Exception:
        day_label = date_str

    rc_map = {
        "green":  {"bg": "#d1fae5", "border": "#059669", "emoji": "G", "label": "Go", "text": "#065f46"},
        "yellow": {"bg": "#fef3c7", "border": "#d97706", "emoji": "M", "label": "Moderate", "text": "#92400e"},
        "red":    {"bg": "#fee2e2", "border": "#dc2626", "emoji": "E", "label": "Easy", "text": "#991b1b"},
        "gray":   {"bg": "#f3f4f6", "border": "#9ca3af", "emoji": "-", "label": "-", "text": "#374151"},
    }
    rc = rc_map.get(readiness_colour, rc_map["gray"])
    gc = grade_colour(grade) if grade != "—" else "#9ca3af"
    grade_display = str(day_grade_score) if day_grade_score is not None else "—"
    grade_letter = grade if grade != "—" else ""

    # ── Header + Day Grade ───────────────────────────────────────────────────
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
    html += '</td></tr></table></div>'

    # ── Scorecard Grid ───────────────────────────────────────────────────────
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
    sleep_det = str(sd.get("duration_hrs", "")) + "h" if sd.get("duration_hrs") else ""
    nd = component_details.get("nutrition", {})
    nutr_det = str(round(nd["calories"])) + " cal" if nd.get("calories") else ""
    md2 = component_details.get("movement", {})
    move_det = fmt_num(md2.get("steps")) + " steps" if md2.get("steps") else ""
    hd = component_details.get("habits_mvp", {})
    hab_det = str(hd.get("completed", "")) + "/" + str(hd.get("total", "")) + " MVP" if hd.get("total") else ""
    hyd = component_details.get("hydration", {})
    hyd_det = str(hyd.get("water_oz", "")) + "oz" if hyd.get("water_oz") else ""
    jd = component_details.get("journal", {})
    jou_det = " + ".join(t.title() for t in jd.get("templates", [])) if jd.get("templates") else ""
    gd = component_details.get("glucose", {})
    glu_det = ""
    if gd.get("avg_glucose"):
        glu_det = str(round(gd["avg_glucose"])) + " mg/dL"
    rd = component_details.get("recovery", {})
    rec_det = str(round(rd["recovery_score"])) + "%" if rd.get("recovery_score") else ""

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

    # ── Readiness ────────────────────────────────────────────────────────────
    rd_display = str(readiness_score) if readiness_score is not None else "—"
    rec_src = "today" if safe_float(data.get("whoop_today"), "recovery_score") else "yesterday"
    trend_s = hrv_trend_str(data["hrv"].get("hrv_7d"), data["hrv"].get("hrv_30d"))

    html += '<div style="background:' + rc["bg"] + ';border-top:2px solid ' + rc["border"] + ';border-bottom:2px solid ' + rc["border"] + ';padding:14px 24px;margin-top:4px;">'
    html += '<p style="font-size:10px;color:' + rc["text"] + ';margin:0;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Today\'s Readiness (' + rec_src + ' recovery)</p>'
    html += '<p style="font-size:34px;font-weight:800;color:' + rc["text"] + ';margin:0;line-height:1.1;">' + rd_display + ' <span style="font-size:14px;font-weight:600;">' + rc["label"].upper() + '</span></p>'
    html += '<p style="font-size:11px;color:' + rc["text"] + ';margin:6px 0 0;">HRV: <strong>' + trend_s + '</strong></p>'
    html += '</div>'

    # ── Training Report ──────────────────────────────────────────────────────
    strava = data.get("strava") or {}
    activities = strava.get("activities", [])
    training_comment = (training_nutrition or {}).get("training", "")
    if activities or training_comment:
        tc = '<div style="border-left:3px solid #7c3aed;background:#faf5ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        tc += '<p style="font-size:11px;font-weight:700;color:#6d28d9;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#127947; Training Report</p>'
        for a in activities:
            name = a.get("name", "Activity")
            sport = a.get("sport_type", "")
            dur_min = round((a.get("moving_time_seconds") or 0) / 60)
            avg_hr = a.get("average_heartrate")
            max_hr = a.get("max_heartrate")
            start = a.get("start_date_local", "")
            time_part = start.split("T")[1][:5] if "T" in str(start) else ""
            tc += '<p style="font-size:13px;color:#1a1a2e;margin:4px 0;font-weight:600;">' + name + '</p>'
            tc += '<p style="font-size:11px;color:#6b7280;margin:0 0 4px;">'
            if time_part:
                tc += time_part + ' &middot; '
            tc += sport + ' &middot; ' + str(dur_min) + ' min'
            if avg_hr:
                tc += ' &middot; Avg HR ' + str(round(avg_hr))
            if max_hr:
                tc += ' &middot; Max HR ' + str(round(max_hr))
            tc += '</p>'
        if training_comment:
            tc += '<p style="font-size:12px;color:#4c1d95;line-height:1.5;margin:8px 0 0;font-style:italic;">' + training_comment + '</p>'
        tc += '</div>'
        html += tc

    # ── Nutrition Report ─────────────────────────────────────────────────────
    mf = data.get("macrofactor") or {}
    if mf.get("total_calories_kcal") is not None:
        cal = round(safe_float(mf, "total_calories_kcal") or 0)
        prot = round(safe_float(mf, "total_protein_g") or 0)
        fat = round(safe_float(mf, "total_fat_g") or 0)
        carbs = round(safe_float(mf, "total_carbs_g") or 0)
        fiber = round(safe_float(mf, "total_fiber_g") or 0)
        cal_target = round(profile.get("calorie_target", 1800))
        prot_target = round(profile.get("protein_target_g", 190))

        def macro_bar(label, val, target, colour):
            pct = min(100, round(val / target * 100)) if target else 0
            return ('<div style="margin:4px 0;">'
                    '<div style="display:flex;justify-content:space-between;font-size:11px;">'
                    '<span style="color:#374151;font-weight:600;">' + label + '</span>'
                    '<span style="color:#6b7280;">' + str(val) + ' / ' + str(target) + '</span></div>'
                    '<div style="background:#e5e7eb;border-radius:3px;height:6px;margin-top:2px;">'
                    '<div style="background:' + colour + ';border-radius:3px;height:6px;width:' + str(pct) + '%;"></div></div></div>')

        nc = '<div style="border-left:3px solid #059669;background:#f0fdf4;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        nc += '<p style="font-size:11px;font-weight:700;color:#166534;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#127869; Nutrition Report</p>'
        cal_color = "#059669" if abs(cal - cal_target) / cal_target <= 0.10 else "#d97706" if abs(cal - cal_target) / cal_target <= 0.25 else "#dc2626"
        nc += macro_bar("Calories", cal, cal_target, cal_color)
        prot_color = "#059669" if prot >= prot_target else "#d97706" if prot >= 170 else "#dc2626"
        nc += macro_bar("Protein", str(prot) + "g", str(prot_target) + "g", prot_color)
        nc += macro_bar("Fat", str(fat) + "g", "60g", "#6b7280")
        nc += macro_bar("Carbs", str(carbs) + "g", "125g", "#6b7280")
        if fiber:
            nc += '<p style="font-size:10px;color:#6b7280;margin:4px 0 0;">Fiber: ' + str(fiber) + 'g</p>'

        # Meal timeline
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
        html += nc

    # ── Habits Deep-Dive ─────────────────────────────────────────────────────
    habitify = data.get("habitify") or {}
    mvp_list = profile.get("mvp_habits", [])
    habits_map = habitify.get("habits", {})
    by_group = habitify.get("by_group", {})
    if habits_map and mvp_list:
        hc = '<div style="border-left:3px solid #2563eb;background:#eff6ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        hc += '<p style="font-size:11px;font-weight:700;color:#1e40af;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#9989; Habits Deep-Dive</p>'
        # MVP checklist
        hc += '<p style="font-size:10px;color:#1e40af;font-weight:600;margin:0 0 4px;">MVP HABITS</p>'
        for habit_name in mvp_list:
            done = habits_map.get(habit_name, 0)
            is_done = float(done) >= 1 if done is not None else False
            icon = "&#9745;" if is_done else "&#9744;"
            color = "#059669" if is_done else "#dc2626"
            # Shorten long habit names
            short_name = habit_name
            if len(short_name) > 35:
                short_name = short_name[:32] + "..."
            hc += '<p style="font-size:12px;color:' + color + ';margin:2px 0;">' + icon + ' ' + short_name + '</p>'
        # Group summary
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
        html += hc

    # ── CGM Spotlight ────────────────────────────────────────────────────────
    apple = data.get("apple") or {}
    cgm_avg = safe_float(apple, "blood_glucose_avg")
    cgm_tir = safe_float(apple, "blood_glucose_time_in_range_pct")
    cgm_std = safe_float(apple, "blood_glucose_std_dev")
    cgm_min = safe_float(apple, "blood_glucose_min")
    cgm_max = safe_float(apple, "blood_glucose_max")
    cgm_above140 = safe_float(apple, "blood_glucose_time_above_140_pct")
    cgm_readings = safe_float(apple, "blood_glucose_readings_count")
    if cgm_avg is not None or cgm_tir is not None:
        gc2 = '<div style="border-left:3px solid #0ea5e9;background:#f0f9ff;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        gc2 += '<p style="font-size:11px;font-weight:700;color:#0369a1;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.5px;">&#128200; CGM Spotlight</p>'
        gc2 += '<table style="width:100%;border-collapse:collapse;"><tr>'
        if cgm_avg is not None:
            avg_color = "#059669" if cgm_avg < 100 else "#d97706" if cgm_avg < 120 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + avg_color + ';">' + str(round(cgm_avg)) + '</div><div style="font-size:9px;color:#6b7280;">Avg mg/dL</div></td>'
        if cgm_tir is not None:
            tir_color = "#059669" if cgm_tir >= 90 else "#d97706" if cgm_tir >= 70 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + tir_color + ';">' + str(round(cgm_tir)) + '%</div><div style="font-size:9px;color:#6b7280;">Time in Range</div></td>'
        if cgm_std is not None:
            std_color = "#059669" if cgm_std < 20 else "#d97706" if cgm_std < 30 else "#dc2626"
            gc2 += '<td style="text-align:center;padding:4px;"><div style="font-size:20px;font-weight:700;color:' + std_color + ';">' + str(round(cgm_std, 1)) + '</div><div style="font-size:9px;color:#6b7280;">Variability</div></td>'
        gc2 += '</tr></table>'
        extras = []
        if cgm_min is not None and cgm_max is not None:
            extras.append("Range: " + str(round(cgm_min)) + "-" + str(round(cgm_max)) + " mg/dL")
        if cgm_above140 is not None and cgm_above140 > 0:
            extras.append("Time >140: " + str(round(cgm_above140)) + "%")
        if cgm_readings is not None:
            extras.append(str(round(cgm_readings)) + " readings")
        if extras:
            gc2 += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">' + ' &middot; '.join(extras) + '</p>'
        gc2 += '</div>'
        html += gc2

    # ── Habit Streaks ────────────────────────────────────────────────────────
    if mvp_streak > 0 or full_streak > 0:
        fire = "&#128293;" * min(mvp_streak, 5) if mvp_streak > 0 else ""
        s_suffix = "s" if mvp_streak != 1 else ""
        mvp_text = "<strong>" + str(mvp_streak) + " day" + s_suffix + "</strong> MVP streak" if mvp_streak > 0 else "MVP streak: 0"
        full_text = " &middot; <strong>" + str(full_streak) + "</strong> perfect" if full_streak > 0 else ""
        html += '<div style="background:#fefce8;border-left:3px solid #eab308;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#854d0e;margin:0;text-transform:uppercase;letter-spacing:0.5px;">&#127942; Habit Streaks</p>'
        html += '<p style="font-size:13px;color:#713f12;margin:4px 0 0;">' + fire + ' ' + mvp_text + full_text + '</p></div>'
    else:
        html += '<div style="background:#fef2f2;border-left:3px solid #fca5a5;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#991b1b;margin:0;text-transform:uppercase;letter-spacing:0.5px;">&#127942; Habit Streaks</p>'
        html += '<p style="font-size:13px;color:#991b1b;margin:4px 0 0;">MVP streak: 0 — today is day 1</p></div>'

    # ── Weight Phase Tracker ─────────────────────────────────────────────────
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
            p_start = phase.get("start_lbs", latest_weight)
            p_total = p_start - p_end
            p_lost = p_start - latest_weight
            p_pct = max(0, min(100, round(p_lost / p_total * 100))) if p_total > 0 else 0
            goal_w = profile.get("goal_weight_lbs", 185)
            t_lose = profile.get("journey_start_weight_lbs", 302) - goal_w
            t_lost = profile.get("journey_start_weight_lbs", 302) - latest_weight
            t_pct = max(0, min(100, round(t_lost / t_lose * 100))) if t_lose > 0 else 0
            html += '<div style="background:#f0fdf4;border-left:3px solid #22c55e;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
            html += '<p style="font-size:11px;font-weight:700;color:#166534;margin:0;text-transform:uppercase;letter-spacing:0.5px;">&#9878; Phase ' + p_num + ': ' + p_name + ' (' + str(round(latest_weight)) + ' lbs)</p>'
            html += '<p style="font-size:13px;color:#14532d;margin:4px 0 0;"><span style="color:' + rc2 + ';font-weight:600;">' + rt + '</span></p>'
            html += '<table style="width:100%;margin-top:8px;"><tr>'
            html += '<td style="width:50%;"><div style="font-size:9px;color:#6b7280;">Phase</div>'
            html += '<div style="background:#dcfce7;border-radius:3px;height:6px;margin-top:3px;"><div style="background:#22c55e;border-radius:3px;height:6px;width:' + str(p_pct) + '%;"></div></div>'
            html += '<div style="font-size:9px;color:#6b7280;margin-top:2px;">' + str(round(latest_weight)) + ' > ' + str(p_end) + ' lbs (' + str(p_pct) + '%)</div></td>'
            html += '<td style="width:50%;padding-left:12px;"><div style="font-size:9px;color:#6b7280;">Journey</div>'
            html += '<div style="background:#dcfce7;border-radius:3px;height:6px;margin-top:3px;"><div style="background:#16a34a;border-radius:3px;height:6px;width:' + str(t_pct) + '%;"></div></div>'
            html += '<div style="font-size:9px;color:#6b7280;margin-top:2px;">' + str(round(t_lost)) + ' of ' + str(round(t_lose)) + ' lbs (' + str(t_pct) + '%)</div></td>'
            html += '</tr></table>'
            html += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">Phase milestone: ' + str(p_proj) + '</p></div>'

    # ── Today's Guidance ─────────────────────────────────────────────────────
    html += '<div style="padding:12px 8px 4px;">'
    html += '<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin:0 8px 6px;font-weight:600;">Today\'s Guidance</p>'
    html += '<table style="width:100%;border-collapse:collapse;">'
    for icon, label, value, note in [
        ("&#127947;", "Train", guidance["train"], ""),
        ("&#9749;", "Caffeine", "Cut off at " + guidance["caffeine_cutoff"], guidance["caffeine_note"]),
        ("&#128716;", "Sleep", "In bed by " + guidance["bed_time"], guidance["sleep_note"]),
        ("&#127869;", "Eating", guidance["eating_window"], "16:8 IF window"),
    ]:
        note_html = '<br><span style="font-size:11px;color:#9ca3af;">' + note + '</span>' if note else ""
        html += '<tr><td style="padding:8px 12px;width:28px;font-size:16px;">' + icon + '</td>'
        html += '<td style="padding:8px 0;color:#6b7280;font-size:12px;width:90px;">' + label + '</td>'
        html += '<td style="padding:8px 12px;font-size:12px;font-weight:600;color:#1a1a2e;">' + value + note_html + '</td></tr>'
    html += '</table></div>'

    # ── Journal Pulse ────────────────────────────────────────────────────────
    journal = data.get("journal")
    if journal:
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

    # ── Journal Coach ────────────────────────────────────────────────────────
    if journal_coach_text:
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

    # ── Board of Directors ───────────────────────────────────────────────────
    if bod_insight:
        html += '<div style="background:#f0f9ff;border-left:3px solid #0ea5e9;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 16px 0;">'
        html += '<p style="font-size:11px;font-weight:700;color:#0369a1;margin:0 0 4px;text-transform:uppercase;letter-spacing:0.5px;">&#129504; Board of Directors</p>'
        html += '<p style="font-size:13px;color:#0c4a6e;line-height:1.6;margin:0;">' + bod_insight + '</p></div>'

    # ── Anomaly Alert ────────────────────────────────────────────────────────
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

    # ── Footer ───────────────────────────────────────────────────────────────
    active_sources = []
    for name, key in [("Whoop", "whoop"), ("Eight Sleep", "sleep"), ("Strava", "strava"),
                       ("MacroFactor", "macrofactor"), ("Apple Health", "apple"), ("Habitify", "habitify")]:
        if data.get(key):
            active_sources.append(name)
    if data.get("journal"):
        active_sources.append("Notion")
    source_str = " &middot; ".join(active_sources) if active_sources else "No data sources"
    html += '<div style="background:#f8f8fc;padding:10px 24px;border-top:1px solid #e8e8f0;margin-top:12px;">'
    html += '<p style="color:#9ca3af;font-size:9px;margin:0;text-align:center;">Life Platform v2.1 &middot; ' + date_str + ' &middot; ' + source_str + '</p></div>'
    html += '</div></body></html>'
    return html


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    print("[INFO] Daily Brief v2.1 starting...")
    profile = fetch_profile()
    if not profile:
        print("[ERROR] No profile found")
        return {"statusCode": 500, "body": "No profile found"}

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()

    data = gather_daily_data(profile, yesterday)
    print("[INFO] Date: " + yesterday + " | sources: " +
          ", ".join(k for k in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava"] if data.get(k)))

    day_grade_score, grade, component_scores, component_details = compute_day_grade(data, profile)
    print("[INFO] Day Grade: " + str(day_grade_score) + " (" + grade + ")")

    if day_grade_score is not None:
        store_day_grade(yesterday, day_grade_score, grade, component_scores,
                        profile.get("day_grade_weights", {}),
                        profile.get("day_grade_algorithm_version", "1.0"))

    readiness_score, readiness_colour = compute_readiness(data)
    guidance = derive_guidance(data, readiness_score, readiness_colour, profile)
    mvp_streak, full_streak = compute_habit_streaks(profile, yesterday)

    # AI calls (all optional — brief works without them)
    api_key = None
    try:
        api_key = get_anthropic_key()
    except Exception as e:
        print("[WARN] Could not get API key: " + str(e))

    bod_insight = ""
    training_nutrition = {}
    journal_coach_text = ""

    if api_key:
        try:
            bod_insight = call_board_of_directors(data, profile, day_grade_score, grade, component_scores, api_key)
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
                print("[INFO] Journal coach: " + journal_coach_text[:80] if journal_coach_text else "[INFO] Journal coach: empty")
            except Exception as e:
                print("[WARN] Journal coach failed: " + str(e))

    html = build_html(data, profile, day_grade_score, grade, component_scores, component_details,
                      readiness_score, readiness_colour, guidance, bod_insight,
                      training_nutrition, journal_coach_text, mvp_streak, full_streak)

    grade_str = str(day_grade_score) + " (" + grade + ")" if day_grade_score is not None else "—"
    r_emoji = {"green": "G", "yellow": "M", "red": "E", "gray": "-"}.get(readiness_colour, "-")
    try:
        day_short = datetime.strptime(yesterday, "%Y-%m-%d").strftime("%a %b %-d")
    except Exception:
        day_short = yesterday
    subject = "Morning Brief | " + day_short + " | Grade: " + grade_str + " | " + r_emoji

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    print("[INFO] Sent: " + subject)
    return {"statusCode": 200, "body": "Daily brief v2.1 sent: " + subject}
