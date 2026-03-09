"""
Scoring Engine — Day Grade computation for the Life Platform.

Extracted from daily_brief_lambda.py (v2.75.0) as a standalone module — v2.76.0.
Used by: daily_brief_lambda.py, character_sheet_lambda.py (future)

Pure functions only — no AWS / DynamoDB / boto3 dependencies.
All functions take (data, profile) dicts and return (score, details) tuples.

Extraction order per review:
  Phase 1 (this file): scoring_engine.py  ← you are here
  Phase 2 (future):    ai_calls.py
  Phase 3 (future):    data_writers.py (dashboard/buddy JSON + store_day_grade/store_habit_scores)
  Phase 4 (future):    data_fetchers.py (gather_daily_data, fetch_*)
  Phase 5 (future):    html_builder.py (build_html → section helpers)
  Phase 6 (future):    lambda_handler.py (lambda_handler, _regrade_handler)
"""

from datetime import datetime


# ==============================================================================
# SHARED HELPERS  (self-contained — no imports from daily_brief)
# ==============================================================================

def safe_float(rec, field, default=None):
    if rec and field in rec:
        try:
            return float(rec[field])
        except Exception:
            return default
    return default


def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))


# ==============================================================================
# COMPONENT SCORERS  (each returns (score: int|None, details: dict))
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
    details = {
        "sleep_score": sleep_score, "efficiency": efficiency,
        "duration_hrs": duration_hrs, "target_hrs": target_hrs,
        "deep_pct": deep_pct, "rem_pct": rem_pct, "light_pct": light_pct,
    }
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
    details = {
        "calories": cal, "protein_g": protein, "fat_g": fat, "carbs_g": carbs,
        "cal_target": cal_target, "protein_target": protein_target,
    }
    parts, weights = [], []
    if cal is not None and cal_target:
        pct_off = abs(cal - cal_target) / cal_target
        if pct_off <= cal_tolerance:
            cal_score = 100
        elif pct_off >= cal_penalty:
            cal_score = 0
        else:
            cal_score = 100 * (1 - (pct_off - cal_tolerance) / (cal_penalty - cal_tolerance))
        if cal > cal_target * (1 + cal_tolerance):
            cal_score = max(0, cal_score - 15)
        cal_score = clamp(round(cal_score))
        parts.append(cal_score * 0.40); weights.append(0.40)
        details["cal_score"] = cal_score
    if protein is not None:
        if protein >= protein_target:
            prot_score = 100
        elif protein >= protein_floor:
            prot_score = 80 + 20 * (protein - protein_floor) / (protein_target - protein_floor)
        else:
            prot_score = max(0, 80 * protein / protein_floor)
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
    # Below 500ml treated as no data — HAE sync artifacts deliver ~350ml when
    # full data doesn't sync (hourly push too infrequent → payload truncates metrics).
    if water_ml is None or water_ml < 500:
        return None, {}
    score = clamp(round(min(100, water_ml / target_ml * 100)))
    return score, {
        "water_ml": round(water_ml),
        "water_oz": round(water_ml / 29.5735, 1),
        "target_oz": round(target_ml / 29.5735, 1),
    }


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
    if has_morning and has_evening:
        score = 100
    elif has_morning or has_evening:
        score = 60
    else:
        score = 40
    return score, {
        "entries": len(entries), "templates": list(templates),
        "has_morning": has_morning, "has_evening": has_evening,
    }


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
        if tir >= 95:   tir_score = 100
        elif tir >= 90: tir_score = 80 + (tir - 90) * 4
        elif tir >= 70: tir_score = max(0, 80 * (tir - 70) / 20)
        else:           tir_score = 0
        parts.append(tir_score * 0.50); weights.append(0.50)
        details["tir_score"] = round(tir_score, 1)
    if avg_glucose is not None:
        if avg_glucose < 95:    glu_score = 100
        elif avg_glucose < 100: glu_score = 80 + (100 - avg_glucose) * 4
        elif avg_glucose < 140: glu_score = max(0, 80 * (140 - avg_glucose) / 40)
        else:                   glu_score = 0
        parts.append(glu_score * 0.30); weights.append(0.30)
        details["avg_score"] = round(glu_score, 1)
    if std_dev is not None:
        if std_dev < 15:   var_score = 100
        elif std_dev < 20: var_score = 80 + (20 - std_dev) * 4
        elif std_dev < 40: var_score = max(0, 80 * (40 - std_dev) / 20)
        else:              var_score = 0
        parts.append(var_score * 0.20); weights.append(0.20)
        details["var_score"] = round(var_score, 1)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details


# ==============================================================================
# DAY GRADE
# ==============================================================================

COMPONENT_SCORERS = {
    "sleep_quality": score_sleep,
    "recovery":      score_recovery,
    "nutrition":     score_nutrition,
    "movement":      score_movement,
    "habits_mvp":    score_habits_registry,
    "hydration":     score_hydration,
    "journal":       score_journal,
    "glucose":       score_glucose,
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
    """Run all component scorers and compute weighted day grade.

    Returns: (total_score, letter_grade, component_scores, component_details)
    """
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
