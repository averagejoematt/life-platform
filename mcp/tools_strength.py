"""
Strength training tools: exercise history, PRs, volume, progress, frequency, standards.
"""
import json
import math
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from mcp.config import (
    table, s3_client, S3_BUCKET, USER_PREFIX, USER_ID, SOURCES,
    P40_GROUPS, FIELD_ALIASES, logger,
    INSIGHTS_PK, EXPERIMENTS_PK, TRAVEL_PK,
)
from mcp.core import (
    query_source, parallel_query_sources, query_source_range,
    get_profile, get_sot, decimal_to_float,
    ddb_cache_get, ddb_cache_set, mem_cache_get, mem_cache_set,
    date_diff_days, resolve_field,
)
from mcp.helpers import (
    aggregate_items, flatten_strava_activity,
    compute_daily_load_score, compute_ewa, pearson_r, _linear_regression,
    classify_day_type, query_chronicling, _habit_series,
)
from mcp.strength_helpers import (
    classify_exercise, is_bodyweight, estimate_1rm,
    extract_hevy_sessions, volume_status, classify_standard,
    attia_benchmark_status,
    _VOLUME_LANDMARKS, _STRENGTH_STANDARDS, _STANDARD_LEVELS, _ATTIA_TARGETS,
)
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


def tool_get_centenarian_benchmarks(args):
    """Compare compound lift 1RMs against Attia centenarian decathlon targets."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    bw_source  = args.get("bodyweight_source", "withings")

    # Get bodyweight
    bodyweight = None
    bw_items = query_source("withings", "2000-01-01", end_date)
    for item in reversed(sorted(bw_items, key=lambda x: x.get("date") or "")):
        w = (item.get("weight_lbs") or item.get("data", {}).get("weight_lbs")
             or item.get("data", {}).get("weight"))
        if w:
            bodyweight = float(w)
            break
    if bodyweight is None:
        bodyweight = float(args.get("bodyweight_lbs", 0))
    if not bodyweight:
        return {"error": "Could not determine bodyweight. Pass bodyweight_lbs or ensure Withings data exists."}

    # Canonical exercise names to search for each lift
    _LIFT_SEARCH = {
        "deadlift":        "deadlift",
        "squat":           "squat",
        "bench press":     "bench press",
        "overhead press":  "overhead press",
    }

    hevy_items = query_source("hevy", "2000-01-01", end_date)

    best_1rms: dict[str, tuple[float, str]] = {}
    for item in hevy_items:
        date_str = item.get("date") or item.get("sk", "")[:10]
        for workout in item.get("data", {}).get("workouts", []):
            for ex in workout.get("exercises", []):
                name_lc = ex.get("name", "").lower()
                for lift_key, keyword in _LIFT_SEARCH.items():
                    if keyword not in name_lc:
                        continue
                    for s in ex.get("sets", []):
                        if s.get("set_type") == "warmup":
                            continue
                        w = float(s.get("weight_lbs", 0) or 0)
                        r = int(s.get("reps", 0) or 0)
                        e1rm = estimate_1rm(w, r)
                        if e1rm and (lift_key not in best_1rms or e1rm > best_1rms[lift_key][0]):
                            best_1rms[lift_key] = (e1rm, date_str)

    lifts_out = {}
    statuses  = []
    for lift_key in _ATTIA_TARGETS:
        if lift_key not in best_1rms:
            lifts_out[lift_key] = {
                "status": "no_data",
                "status_label": "No lift data found",
                "note": f"Log {lift_key} in Hevy to start tracking.",
            }
            continue
        best, best_date = best_1rms[lift_key]
        ratio  = round(best / bodyweight, 3)
        result = attia_benchmark_status(lift_key, ratio)
        result["best_estimated_1rm_lbs"] = best
        result["date_achieved"]           = best_date
        result["lbs_to_target"] = round(
            max(0, (_ATTIA_TARGETS[lift_key]["target_ratio"] - ratio) * bodyweight), 1
        )
        lifts_out[lift_key] = result
        statuses.append(result["status"])

    # Overall readiness score (0-100) based on weighted pct_of_target
    pcts = [
        v["pct_of_target"]
        for v in lifts_out.values()
        if "pct_of_target" in v
    ]
    overall_pct = round(sum(pcts) / len(pcts), 1) if pcts else None

    # Weakest lift by gap to target
    lifts_with_gap = [
        (k, v) for k, v in lifts_out.items()
        if v.get("gap_to_target_bw_ratio", 0) > 0
    ]
    priority_lift = (
        min(lifts_with_gap, key=lambda x: x[1]["pct_of_target"])[0]
        if lifts_with_gap else None
    )

    return {
        "bodyweight_lbs": bodyweight,
        "as_of_date": end_date,
        "overall_pct_of_targets": overall_pct,
        "priority_lift": priority_lift,
        "framework": (
            "Peter Attia centenarian decathlon — ratios needed NOW to maintain "
            "functional independence at 80-85. Assumes ~8-12% strength decline per decade from 40."
        ),
        "lifts": lifts_out,
    }


def tool_get_strength(args):
    """Unified strength intelligence dispatcher."""
    VALID_VIEWS = {
        "progress":  tool_get_strength_progress,
        "prs":       tool_get_strength_prs,
        "standards": tool_get_strength_standards,
    }
    view = (args.get("view") or "progress").lower().strip()
    if view not in VALID_VIEWS:
        return {"error": f"Unknown view '{view}'.", "valid_views": list(VALID_VIEWS.keys()),
                "hint": "'progress' for volume/load trends, 'prs' for all-time personal records by lift, 'standards' for bodyweight-relative strength levels."}
    return VALID_VIEWS[view](args)
