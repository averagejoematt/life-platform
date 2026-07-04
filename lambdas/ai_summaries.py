"""
lambdas/ai_summaries.py — pure data-summary builders + numeric leaf utils.

Extracted from ai_calls.py (god-module split, 2026-06-08). These functions are
*pure*: they transform a `data`/`profile` dict into a summary dict/string and
call nothing in the AI layer (no call_anthropic, no module state). Keeping them
here shrinks ai_calls.py and gives the summary logic a testable home.

ai_calls.py re-exports everything below (`from ai_summaries import *`-style) so
existing callers — only daily_brief_lambda, via `import ai_calls` namespace
access — keep working unchanged.
"""

from typing import Any


def _safe_float(rec, field, default=None):
    if rec and field in rec:
        try:
            return float(rec[field])
        except Exception:
            return default
    return default


def _avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def build_data_summary(data: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    journal = data.get("journal") or {}
    mf = data.get("macrofactor") or {}
    strava = data.get("strava") or {}
    habitify = data.get("habitify") or {}
    apple = data.get("apple") or {}
    sleep = data.get("sleep") or {}
    # Phase-3: narrate the SAME whoop the numeric vitals block shows (the chosen
    # "primary" day — today-if-finalized else yesterday), falling back to the legacy
    # yesterday record when a caller hasn't set primary_whoop.
    _pw = data.get("primary_whoop") or data.get("whoop")
    return {
        "date": data.get("date"),
        "recovery_score": _safe_float(_pw, "recovery_score"),
        "strain": _safe_float(_pw, "strain"),
        "sleep_score": _safe_float(sleep, "sleep_score"),
        "sleep_duration_hrs": _safe_float(sleep, "sleep_duration_hours"),
        "sleep_efficiency_pct": _safe_float(sleep, "sleep_efficiency_pct"),
        "deep_sleep_pct": _safe_float(sleep, "deep_pct"),
        "rem_sleep_pct": _safe_float(sleep, "rem_pct"),
        "hrv_yesterday": data.get("hrv", {}).get("hrv_yesterday"),
        "hrv_7d_avg": data.get("hrv", {}).get("hrv_7d"),
        "hrv_30d_avg": data.get("hrv", {}).get("hrv_30d"),
        "calories": _safe_float(mf, "total_calories_kcal"),
        "protein_g": _safe_float(mf, "total_protein_g"),
        "fat_g": _safe_float(mf, "total_fat_g"),
        "carbs_g": _safe_float(mf, "total_carbs_g"),
        "fiber_g": _safe_float(mf, "total_fiber_g"),
        "steps": _safe_float(apple, "steps"),
        "water_ml": _safe_float(apple, "water_intake_ml"),
        "glucose_avg": _safe_float(apple, "blood_glucose_avg"),
        "glucose_tir": _safe_float(apple, "blood_glucose_time_in_range_pct"),
        "glucose_std_dev": _safe_float(apple, "blood_glucose_std_dev"),
        "glucose_min": _safe_float(apple, "blood_glucose_min"),
        "walking_speed_mph": _safe_float(apple, "walking_speed_mph"),
        "walking_step_length_in": _safe_float(apple, "walking_step_length_in"),
        "walking_asymmetry_pct": _safe_float(apple, "walking_asymmetry_pct"),
        "habits_completed": _safe_float(habitify, "total_completed"),
        "habits_possible": _safe_float(habitify, "total_possible"),
        "exercise_count": _safe_float(strava, "activity_count"),
        "exercise_minutes": round((_safe_float(strava, "total_moving_time_seconds") or 0) / 60, 1),
        "journal_mood": journal.get("mood_avg"),
        "journal_energy": journal.get("energy_avg"),
        "journal_stress": journal.get("stress_avg"),
        "current_weight": data.get("latest_weight"),
        "week_ago_weight": data.get("week_ago_weight"),
        "tsb": data.get("tsb"),
        "tsb_basis_note": data.get("tsb_basis_note"),  # #490/M-3: provenance suffix
        "sleep_debt_7d_hrs": data.get("sleep_debt_7d_hrs"),
    }


def build_food_summary(data: dict[str, Any]) -> dict[str, Any]:
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


def build_activity_summary(data: dict[str, Any]) -> dict[str, Any]:
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
        max_hr_act = a.get("max_heartrate")
        start = a.get("start_date_local", "")
        time_part = start.split("T")[1][:5] if "T" in start else "?"
        line = time_part + " - " + name + " (" + sport + ", " + str(duration_min) + " min"
        if avg_hr:
            line += ", avg HR " + str(round(avg_hr))
        if max_hr_act:
            line += ", max HR " + str(round(max_hr_act))
        line += ")"
        lines.append(line)
    return "\n".join(lines)


def build_workout_summary(data: dict[str, Any]) -> dict[str, Any]:
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
