"""
lambdas/web/site_api_observatory.py — observatory page endpoint handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 2, 2026-05-26).
These serve /api/{nutrition,training,physical,mind}_overview plus supporting
endpoints (frequent meals, meal glucose, strength benchmarks, food delivery,
strength deep-dive, journal analysis, benchmark trends, meal responses).

All shared helpers (_ok, _error, table, _query_source, _latest_item, etc.)
are imported from site_api_common — no circular references.
"""
import json
import re
import time  # noqa: F401 — used by some handlers
from datetime import datetime, timezone, timedelta
from decimal import Decimal  # noqa: F401 — kept for handlers that convert types

from boto3.dynamodb.conditions import Key

from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    logger,
    table,
    USER_ID, USER_PREFIX,
    EXPERIMENT_START, EXPERIMENT_BASELINE_WEIGHT_LBS,
    CORS_HEADERS,
    _ok, _error,
    _query_source, _latest_item, _decimal_to_float,
    _experiment_date,
    _get_profile,
    _load_supp_metadata,
    _load_content_filter,
    _scrub_blocked_terms,
    _is_blocked_vice,
)


def handle_nutrition_overview() -> dict:
    """
    GET /api/nutrition_overview
    Returns: 30-day macro averages, protein adherence, eating window, deficit status.
    Source: MacroFactor DynamoDB partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    d7 = _experiment_date(7)

    items = _query_source("macrofactor", d30, today)
    if not items:
        # Genesis week / no logging yet — return a shaped-but-empty 200 so the
        # site renders an honest empty state instead of a console 503.
        _empty_grp = {"avg_calories": None, "avg_protein_g": None, "avg_carbs_g": None,
                      "avg_fat_g": None, "avg_fiber_g": None, "days": 0, "count": 0, "protein_hit_pct": 0}
        return _ok({
            "nutrition": {"avg_calories": None, "avg_protein_g": None, "avg_carbs_g": None,
                          "avg_fat_g": None, "avg_fiber_g": None, "protein_target_g": 190,
                          "protein_hit_pct": 0, "protein_hit_days": 0, "days_logged": 0,
                          "tdee": None, "avg_deficit": None, "cal_7d_avg": None, "pro_7d_avg": None,
                          "latest_date": today, "latest_calories": None, "latest_protein_g": None},
            "nutrition_trend": [],
            "weekday_vs_weekend": {"weekday": dict(_empty_grp), "weekend": dict(_empty_grp)},
            "eating_window": None,
            "periodization": {"training_day": dict(_empty_grp), "rest_day": dict(_empty_grp)},
        }, cache_seconds=300)

    items.sort(key=lambda x: x.get("sk", ""))

    def safe_avg(field):
        vals = [float(i[field]) for i in items if i.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def safe_sum_avg(field):
        return safe_avg(field)

    # Support both old field names (calories) and new (total_calories_kcal)
    def _mf(item, field, alt_field=None):
        v = item.get(field) or item.get(alt_field or f"total_{field}")
        if v is None and field == "calories":
            v = item.get("total_calories_kcal")
        return float(v) if v is not None else None

    cal_vals = [_mf(i, "calories") for i in items if _mf(i, "calories") is not None]
    pro_vals = [_mf(i, "protein_g", "total_protein_g") for i in items if _mf(i, "protein_g", "total_protein_g") is not None]
    carb_vals = [_mf(i, "carbs_g", "total_carbs_g") for i in items if _mf(i, "carbs_g", "total_carbs_g") is not None]
    fat_vals = [_mf(i, "fat_g", "total_fat_g") for i in items if _mf(i, "fat_g", "total_fat_g") is not None]
    fiber_vals = [_mf(i, "fiber_g", "total_fiber_g") for i in items if _mf(i, "fiber_g", "total_fiber_g") is not None]

    protein_target = 190  # Matthew's protein target in grams — matches profile.protein_target_g
    protein_hit_days = sum(1 for v in pro_vals if v >= protein_target)
    protein_hit_pct = round(protein_hit_days / len(pro_vals) * 100) if pro_vals else 0

    # Latest day
    latest = items[-1] if items else {}
    latest_date = latest.get("date") or latest.get("sk", "").replace("DATE#", "")

    # 7-day vs 30-day comparison
    items_7d = [i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d7]
    cal_7d = [_mf(i, "calories") for i in items_7d if _mf(i, "calories") is not None]
    pro_7d = [_mf(i, "protein_g", "total_protein_g") for i in items_7d if _mf(i, "protein_g", "total_protein_g") is not None]

    # TDEE estimate (if available in latest record)
    tdee = float(latest.get("tdee") or latest.get("expenditure") or 0) or None
    avg_cal = round(sum(cal_vals) / len(cal_vals)) if cal_vals else None
    deficit = round(tdee - avg_cal) if tdee and avg_cal else None

    # Daily trend for chart
    trend = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        trend.append({
            "date": d,
            "calories": round(_mf(i, "calories")) if _mf(i, "calories") is not None else None,
            "protein_g": round(_mf(i, "protein_g", "total_protein_g"), 1) if _mf(i, "protein_g", "total_protein_g") is not None else None,
            "carbs_g": round(_mf(i, "carbs_g", "total_carbs_g"), 1) if _mf(i, "carbs_g", "total_carbs_g") is not None else None,
            "fat_g": round(_mf(i, "fat_g", "total_fat_g"), 1) if _mf(i, "fat_g", "total_fat_g") is not None else None,
        })

    # ── Weekday vs Weekend comparison ──
    weekday_items = []
    weekend_items = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        try:
            dow = datetime.strptime(d, "%Y-%m-%d").weekday()
        except Exception:
            continue
        if dow >= 5:
            weekend_items.append(i)
        else:
            weekday_items.append(i)

    def _group_avg(group, field, alt_field=None):
        vals = [_mf(x, field, alt_field) for x in group if _mf(x, field, alt_field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _group_pro_hit(group):
        hits = sum(1 for x in group if (_mf(x, "protein_g", "total_protein_g") or 0) >= protein_target)
        return round(hits / len(group) * 100) if group else 0

    weekday_vs_weekend = {
        "weekday": {
            "avg_calories": _group_avg(weekday_items, "calories"),
            "avg_protein_g": _group_avg(weekday_items, "protein_g", "total_protein_g"),
            "avg_carbs_g": _group_avg(weekday_items, "carbs_g", "total_carbs_g"),
            "avg_fat_g": _group_avg(weekday_items, "fat_g", "total_fat_g"),
            "avg_fiber_g": _group_avg(weekday_items, "fiber_g", "total_fiber_g"),
            "days": len(weekday_items),
            "protein_hit_pct": _group_pro_hit(weekday_items),
        },
        "weekend": {
            "avg_calories": _group_avg(weekend_items, "calories"),
            "avg_protein_g": _group_avg(weekend_items, "protein_g", "total_protein_g"),
            "avg_carbs_g": _group_avg(weekend_items, "carbs_g", "total_carbs_g"),
            "avg_fat_g": _group_avg(weekend_items, "fat_g", "total_fat_g"),
            "avg_fiber_g": _group_avg(weekend_items, "fiber_g", "total_fiber_g"),
            "days": len(weekend_items),
            "protein_hit_pct": _group_pro_hit(weekend_items),
        },
    }

    # ── Eating window (first/last meal time from food_log) ──
    eating_windows = []
    for i in items:
        food_log = i.get("food_log") or []
        times = []
        for entry in food_log:
            t = entry.get("time")
            if t:
                try:
                    parts = t.split(":")
                    hour_min = int(parts[0]) * 60 + int(parts[1])
                    times.append(hour_min)
                except (ValueError, IndexError):
                    pass
        if len(times) >= 2:
            first = min(times)
            last = max(times)
            window_hrs = round((last - first) / 60, 1)
            eating_windows.append({
                "first_meal_min": first,
                "last_meal_min": last,
                "window_hrs": window_hrs,
            })

    eating_window = None
    if eating_windows:
        avg_first = round(sum(e["first_meal_min"] for e in eating_windows) / len(eating_windows))
        avg_last = round(sum(e["last_meal_min"] for e in eating_windows) / len(eating_windows))
        avg_window = round(sum(e["window_hrs"] for e in eating_windows) / len(eating_windows), 1)
        eating_window = {
            "avg_hours": avg_window,
            "avg_first_meal": f"{avg_first // 60}:{avg_first % 60:02d}",
            "avg_last_meal": f"{avg_last // 60}:{avg_last % 60:02d}",
            "days_with_data": len(eating_windows),
        }

    # ── Caloric periodization (training days vs rest days) ──
    strava_items_30d = _query_source("strava", d30, today)
    training_dates = set()
    for s in strava_items_30d:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        training_dates.add(d)

    training_day_items = []
    rest_day_items = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        if d in training_dates:
            training_day_items.append(i)
        else:
            rest_day_items.append(i)

    periodization = {
        "training_day": {
            "avg_calories": _group_avg(training_day_items, "calories"),
            "avg_protein_g": _group_avg(training_day_items, "protein_g", "total_protein_g"),
            "count": len(training_day_items),
        },
        "rest_day": {
            "avg_calories": _group_avg(rest_day_items, "calories"),
            "avg_protein_g": _group_avg(rest_day_items, "protein_g", "total_protein_g"),
            "count": len(rest_day_items),
        },
    }
    # Compute deficit for each group if TDEE is available
    if tdee:
        for key in ("training_day", "rest_day"):
            avg = periodization[key]["avg_calories"]
            periodization[key]["avg_deficit"] = round(tdee - avg) if avg else None

    return _ok({
        "nutrition": {
            "avg_calories": round(sum(cal_vals) / len(cal_vals)) if cal_vals else None,
            "avg_protein_g": round(sum(pro_vals) / len(pro_vals), 1) if pro_vals else None,
            "avg_carbs_g": round(sum(carb_vals) / len(carb_vals), 1) if carb_vals else None,
            "avg_fat_g": round(sum(fat_vals) / len(fat_vals), 1) if fat_vals else None,
            "avg_fiber_g": round(sum(fiber_vals) / len(fiber_vals), 1) if fiber_vals else None,
            "protein_target_g": protein_target,
            "protein_hit_pct": protein_hit_pct,
            "protein_hit_days": protein_hit_days,
            "days_logged": len(items),
            "tdee": round(tdee) if tdee else None,
            "avg_deficit": deficit,
            "cal_7d_avg": round(sum(cal_7d) / len(cal_7d)) if cal_7d else None,
            "pro_7d_avg": round(sum(pro_7d) / len(pro_7d), 1) if pro_7d else None,
            "latest_date": latest_date,
            "latest_calories": round(_mf(latest, "calories")) if _mf(latest, "calories") else None,
            "latest_protein_g": round(_mf(latest, "protein_g", "total_protein_g"), 1) if _mf(latest, "protein_g", "total_protein_g") else None,
        },
        "nutrition_trend": trend,
        "weekday_vs_weekend": weekday_vs_weekend,
        "eating_window": eating_window,
        "periodization": periodization,
    }, cache_seconds=3600)



def handle_training_overview() -> dict:
    """
    GET /api/training_overview
    Returns: workout frequency, zone 2 minutes, training load, strength summary.
    Sources: Strava (cardio), Hevy (strength), Whoop (strain).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = _experiment_date(30)

    # Strava activities (90 days)
    strava_items = _query_source("strava", d90, today)
    strava_30d = [s for s in strava_items if (s.get("date") or s.get("sk", "").replace("DATE#", "")) >= d30]

    # Zone 2 detection: HR between 60-70% of max HR
    max_hr = 184  # Matthew's measured max HR — matches profile.max_heart_rate
    z2_low, z2_high = max_hr * 0.60, max_hr * 0.70
    z2_minutes_30d = 0
    # Z2 is recalculated after flattening activities below
    z2_target = 150  # minutes/week

    # Flatten nested activities lists from day-level Strava records
    all_activities_30d = []
    for s in strava_30d:
        acts = s.get("activities") or []
        if acts:
            for a in acts:
                a["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_30d.extend(acts)
        else:
            # Fallback: treat day record itself as a single activity
            s["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_30d.append(s)

    # Deduplicate WHOOP auto-detected activities that overlap with Garmin recordings.
    # WHOOP pushes duplicate workouts to Strava (often with 0 distance). If a Garmin
    # activity of the same sport_type exists on the same day, drop the WHOOP duplicate.
    def _dedup_whoop(activities):
        by_day_type = {}
        for a in activities:
            key = (a.get("_day_date", ""), (a.get("sport_type") or "").lower())
            by_day_type.setdefault(key, []).append(a)
        deduped = []
        for key, group in by_day_type.items():
            if len(group) > 1:
                non_whoop = [a for a in group if (a.get("device_name") or "").upper() != "WHOOP"]
                deduped.extend(non_whoop if non_whoop else [group[0]])
            else:
                deduped.extend(group)
        return deduped

    all_activities_30d = _dedup_whoop(all_activities_30d)

    all_activities_90d = []
    for s in strava_items:
        acts = s.get("activities") or []
        if acts:
            for a in acts:
                a["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_90d.extend(acts)
        else:
            s["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_90d.append(s)
    all_activities_90d = _dedup_whoop(all_activities_90d)

    total_workouts_90d = len(all_activities_90d)
    total_workouts_30d = len(all_activities_30d)
    weekly_avg = round(total_workouts_30d / 4.3, 1) if total_workouts_30d else 0

    # Activity type breakdown (30d)
    type_counts = {}
    for a in all_activities_30d:
        sport = a.get("sport_type") or a.get("type") or "Other"
        type_counts[sport] = type_counts.get(sport, 0) + 1
    top_activities = sorted(type_counts.items(), key=lambda x: -x[1])[:8]

    # Total training minutes and distance (30d)
    def _act_minutes(a):
        return float(a.get("duration_minutes") or a.get("moving_time_minutes") or
                      (a.get("moving_time_seconds") or 0) / 60 or 0)

    def _act_miles(a):
        if a.get("distance_miles"):
            return float(a["distance_miles"])
        if a.get("distance_meters"):
            return float(a["distance_meters"]) * 0.000621371
        if a.get("distance"):
            return float(a["distance"]) / 1609.34
        return 0.0

    total_minutes_30d = sum(_act_minutes(a) for a in all_activities_30d)
    total_distance_mi = sum(_act_miles(a) for a in all_activities_30d)

    # ── Modality breakdown (30d) — group by sport_type with per-modality stats ──
    from collections import defaultdict as _dd2
    modality_map = _dd2(lambda: {
        "count": 0, "total_min": 0, "total_mi": 0, "total_elev_ft": 0,
        "hr_sum": 0, "hr_count": 0, "z2_min": 0,
    })
    # Also compute prior 30d for trend (days 31-60)
    d60 = _experiment_date(60)
    prior_30d_acts = []
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        if d60 <= d < d30:
            acts = s.get("activities") or [s]
            prior_30d_acts.extend(acts)
    prior_type_counts = {}
    for a in prior_30d_acts:
        sport = a.get("sport_type") or a.get("type") or "Other"
        prior_type_counts[sport] = prior_type_counts.get(sport, 0) + 1

    for a in all_activities_30d:
        sport = a.get("sport_type") or a.get("type") or "Other"
        m = modality_map[sport]
        m["count"] += 1
        dur = _act_minutes(a)
        m["total_min"] += dur
        m["total_mi"] += _act_miles(a)
        m["total_elev_ft"] += float(a.get("total_elevation_gain_feet") or 0)
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        if avg_hr:
            m["hr_sum"] += float(avg_hr)
            m["hr_count"] += 1
            if z2_low <= float(avg_hr) <= z2_high:
                m["z2_min"] += dur

    modality_breakdown = []
    for sport, m in sorted(modality_map.items(), key=lambda x: -x[1]["count"]):
        prior_count = prior_type_counts.get(sport, 0)
        trend = m["count"] - prior_count  # positive = more active
        modality_breakdown.append({
            "type": sport,
            "count_30d": m["count"],
            "total_minutes_30d": round(m["total_min"]),
            "avg_duration_min": round(m["total_min"] / m["count"]) if m["count"] else 0,
            "avg_hr": round(m["hr_sum"] / m["hr_count"]) if m["hr_count"] else None,
            "total_distance_mi": round(m["total_mi"], 1),
            "total_elevation_ft": round(m["total_elev_ft"]),
            "z2_minutes": round(m["z2_min"]),
            "trend_vs_prior_30d": trend,
        })

    # Recalculate Z2 from all flattened activities
    z2_minutes_30d = 0
    for a in all_activities_30d:
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        dur = _act_minutes(a)
        if avg_hr and dur:
            if z2_low <= float(avg_hr) <= z2_high:
                z2_minutes_30d += dur
    z2_weekly_avg = round(z2_minutes_30d / 4.3)
    z2_pct = round(z2_weekly_avg / z2_target * 100) if z2_target else 0

    # ── Walking stats (Garmin steps + Apple Health fallback + Strava walks) ──
    garmin_30d = _query_source("garmin", d30, today)
    step_vals = [float(g["steps"]) for g in garmin_30d if g.get("steps")]
    # Fallback: use Apple Health step data if Garmin has none
    if not step_vals:
        ah_step_data = _query_source("apple_health", d30, today)
        step_vals = [float(h["steps"]) for h in ah_step_data if h.get("steps") and float(h["steps"]) > 0]
    avg_daily_steps = round(sum(step_vals) / len(step_vals)) if step_vals else None
    daily_steps_trend = []
    for g in sorted(garmin_30d, key=lambda x: x.get("date") or x.get("sk", "")):
        if g.get("steps"):
            _step_date = g.get("date") or g.get("sk", "").replace("DATE#", "")
            try:
                _step_dow = datetime.strptime(_step_date, "%Y-%m-%d").weekday()
            except Exception:
                _step_dow = 0
            daily_steps_trend.append({
                "date": _step_date,
                "steps": int(float(g["steps"])),
                "is_weekend": _step_dow >= 5,
            })

    walk_activities = [a for a in all_activities_30d if (a.get("sport_type") or "").lower() in ("walk", "hike")]
    ruck_activities = [a for a in all_activities_30d if "ruck" in (a.get("name") or "").lower() or "ruck" in (a.get("sport_type") or "").lower()]
    walking_data = {
        "avg_daily_steps": avg_daily_steps,
        "total_walks_30d": len(walk_activities),
        "total_rucks_30d": len(ruck_activities),
        "total_miles_30d": round(sum(_act_miles(a) for a in walk_activities), 1),
        "avg_pace_min_per_mi": None,
        "z2_minutes_walking": round(sum(
            _act_minutes(a) for a in walk_activities
            if a.get("average_heartrate") and z2_low <= float(a["average_heartrate"]) <= z2_high
        )),
        "daily_steps_trend": daily_steps_trend,
    }
    # Avg walking pace (min/mi)
    walk_w_speed = [a for a in walk_activities if a.get("average_speed_ms") and float(a["average_speed_ms"]) > 0]
    if walk_w_speed:
        avg_speed_ms = sum(float(a["average_speed_ms"]) for a in walk_w_speed) / len(walk_w_speed)
        walking_data["avg_pace_min_per_mi"] = round(26.8224 / avg_speed_ms, 1) if avg_speed_ms > 0 else None

    # ── Breathwork stats (Apple Health — check both breathwork_minutes and mindful_minutes) ──
    ah_30d = _query_source("apple_health", d30, today)
    bw_sessions = 0
    bw_minutes = 0.0
    for h in ah_30d:
        _bw = float(h.get("breathwork_minutes") or 0)
        _bs = int(float(h.get("breathwork_sessions") or 0))
        _mm = float(h.get("mindful_minutes") or 0)
        if _mm > 0 and _bw == 0:
            _bw = _mm
            _bs = max(_bs, 1)
        bw_sessions += _bs
        bw_minutes += _bw
    bw_weekly_trend = []
    bw_week_map = _dd2(lambda: {"sessions": 0, "minutes": 0.0})
    for h in ah_30d:
        d = h.get("date") or h.get("sk", "").replace("DATE#", "")
        try:
            wk = datetime.strptime(d, "%Y-%m-%d").strftime("%Y-W%V")
        except Exception:
            continue
        _bw = float(h.get("breathwork_minutes") or 0)
        _bs = int(float(h.get("breathwork_sessions") or 0))
        _mm = float(h.get("mindful_minutes") or 0)
        if _mm > 0 and _bw == 0:
            _bw = _mm
            _bs = max(_bs, 1)
        bw_week_map[wk]["sessions"] += _bs
        bw_week_map[wk]["minutes"] += _bw
    for wk in sorted(bw_week_map):
        bw_weekly_trend.append({"week": wk, **bw_week_map[wk]})
    breathwork_data = {
        "sessions_30d": bw_sessions,
        "total_minutes_30d": round(bw_minutes, 1),
        "avg_session_min": round(bw_minutes / bw_sessions, 1) if bw_sessions else None,
        "weekly_trend": bw_weekly_trend[-8:],
    }

    # ── V2: Daily modality minutes (30 days) for stacked bar chart ──
    _MODALITY_MAP = {
        "WeightTraining": "strength", "Workout": "strength",
        "Walk": "walking", "Hike": "hiking",
        "Ride": "cycling", "VirtualRide": "cycling",
        "Stretch": "stretching", "Yoga": "stretching",
        "Soccer": "soccer",
        "Breathwork": "breathwork",
    }
    _daily_mod = _dd2(lambda: _dd2(float))
    for a in all_activities_30d:
        _dm_date = a.get("_day_date", "")
        _dm_sport = a.get("sport_type") or a.get("type") or "Other"
        _dm_mapped = _MODALITY_MAP.get(_dm_sport, "other")
        _dm_dur = _act_minutes(a)
        _daily_mod[_dm_date][_dm_mapped] += _dm_dur
    # Add Apple Health breathwork minutes
    for h in ah_30d:
        _bw_d = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        if _bw_min > 0:
            _daily_mod[_bw_d]["breathwork"] += _bw_min
    _mod_keys = ["strength", "walking", "cycling", "stretching", "soccer", "hiking", "breathwork", "other"]
    daily_modality_minutes_30d = []
    _exp_start_date = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
    _days_since_exp = (datetime.now(timezone.utc) - _exp_start_date.replace(tzinfo=timezone.utc)).days + 1
    _mod_range = min(30, _days_since_exp)
    for i in range(_mod_range):
        dt = datetime.now(timezone.utc) - timedelta(days=_mod_range - 1 - i)
        _dm_d = dt.strftime("%Y-%m-%d")
        _dm_entry = {"date": _dm_d}
        _dm_total = 0
        for _mk in _mod_keys:
            _mv = round(_daily_mod.get(_dm_d, {}).get(_mk, 0))
            _dm_entry[_mk + "_min"] = _mv
            _dm_total += _mv
        _dm_entry["total_min"] = _dm_total
        daily_modality_minutes_30d.append(_dm_entry)

    # Whoop strain (30d)
    whoop_30d = _query_source("whoop", d30, today)
    strain_vals = [float(w["strain"]) for w in whoop_30d if w.get("strain")]
    avg_strain = round(sum(strain_vals) / len(strain_vals), 1) if strain_vals else None

    # Whoop workouts — per-workout HR zone data (enriches Strava)
    whoop_workouts = []
    try:
        resp = table.query(**with_phase_filter({  # ADR-058: hide pilot workouts
            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}whoop") & Key("sk").between(
                f"DATE#{d30}#WORKOUT#", f"DATE#{today}#WORKOUT#~"
            ),
        }))
        whoop_workouts = _decimal_to_float(resp.get("Items", []))
        # Add Whoop Z2 minutes from actual HR zones to the Z2 calculation
        for ww in whoop_workouts:
            z2_from_whoop = float(ww.get("zone_2_minutes", 0) or 0)
            if z2_from_whoop > 0:
                z2_minutes_30d += z2_from_whoop
        # Recalculate Z2 weekly avg with Whoop data
        if whoop_workouts:
            z2_weekly_avg = round(z2_minutes_30d / 4.3)
            z2_pct = round(z2_weekly_avg / z2_target * 100) if z2_target else 0
    except Exception as e:
        logger.warning(f"[training_overview] Whoop workout query failed (non-fatal): {e}")

    # Hevy — latest strength session info
    hevy_items = _query_source("hevy", d30, today)
    strength_sessions_30d = len(hevy_items)

    # Weekly trend (for chart) — use flattened activities
    from collections import defaultdict as _dd
    week_buckets = _dd(lambda: {"workouts": 0, "minutes": 0, "z2_min": 0})
    for a in all_activities_90d:
        d = a.get("_day_date") or ""
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
        except Exception:
            continue
        week_buckets[week_key]["workouts"] += 1
        dur = _act_minutes(a)
        week_buckets[week_key]["minutes"] += dur
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        if avg_hr and z2_low <= float(avg_hr) <= z2_high:
            week_buckets[week_key]["z2_min"] += dur

    weekly_trend = sorted([
        {"week": k, "workouts": v["workouts"], "minutes": round(v["minutes"]), "z2_min": round(v["z2_min"])}
        for k, v in week_buckets.items()
    ], key=lambda x: x["week"])[-12:]  # last 12 weeks

    return _ok({
        "training": {
            "workouts_30d": total_workouts_30d,
            "workouts_90d": total_workouts_90d,
            "weekly_avg": weekly_avg,
            "total_minutes_30d": round(total_minutes_30d),
            "total_distance_mi": round(total_distance_mi, 1),
            "z2_weekly_avg_min": z2_weekly_avg,
            "z2_target_min": z2_target,
            "z2_pct": min(z2_pct, 100),
            "avg_strain": avg_strain,
            "strength_sessions_30d": strength_sessions_30d,
            "top_activities": [{"type": t, "count": c} for t, c in top_activities],
            "whoop_workout_count": len(whoop_workouts),
            "active_modalities": len(modality_breakdown),
            "avg_daily_steps": walking_data["avg_daily_steps"],
        },
        "modality_breakdown": modality_breakdown,
        "daily_modality_minutes_30d": daily_modality_minutes_30d,
        "walking": walking_data,
        "breathwork": breathwork_data,
        "weekly_trend": weekly_trend,
        "whoop_workouts": [{
            "date": w.get("date"),
            "sport_name": w.get("sport_name", "Activity"),
            "strain": w.get("strain"),
            "zone_2_minutes": w.get("zone_2_minutes"),
            "zone_3_minutes": w.get("zone_3_minutes"),
            "distance_meter": w.get("distance_meter"),
            "average_heart_rate": w.get("average_heart_rate"),
        } for w in whoop_workouts[:20]],
    }, cache_seconds=3600)



def handle_weekly_physical_summary() -> dict:
    """
    GET /api/weekly_physical_summary
    Returns: 7-day array with per-day modality breakdown (Strava + Garmin steps + breathwork).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d7 = _experiment_date(7)

    strava_items = _query_source("strava", d7, today)
    garmin_items = _query_source("garmin", d7, today)
    ah_items = _query_source("apple_health", d7, today)

    # Build per-day maps
    garmin_by_date = {(g.get("date") or g.get("sk", "").replace("DATE#", "")): g for g in garmin_items}
    ah_by_date = {(h.get("date") or h.get("sk", "").replace("DATE#", "")): h for h in ah_items}

    # Flatten Strava activities by day, dedup by activity ID
    from collections import defaultdict
    day_activities = defaultdict(list)
    _seen_activity_ids = set()
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")[:10]
        acts = s.get("activities") or [s]
        for a in acts:
            # Dedup: skip if we've already seen this activity ID
            _aid = str(a.get("activity_id") or a.get("id") or a.get("strava_id") or "")
            if _aid and _aid in _seen_activity_ids:
                continue
            if _aid:
                _seen_activity_ids.add(_aid)
            sport = a.get("sport_type") or a.get("type") or "Other"
            dur = float(a.get("duration_minutes") or a.get("moving_time_minutes") or
                        (a.get("moving_time_seconds") or 0) / 60 or 0)
            day_activities[d].append({"type": sport, "minutes": round(dur)})

    # Build 7-day array
    days = []
    for i in range(7):
        dt = datetime.now(timezone.utc) - timedelta(days=6 - i)
        d = dt.strftime("%Y-%m-%d")
        dow = dt.strftime("%a")
        garmin = garmin_by_date.get(d, {})
        ah = ah_by_date.get(d, {})
        activities = day_activities.get(d, [])
        total_active_min = sum(a["minutes"] for a in activities)
        bw_min = float(ah.get("breathwork_minutes") or 0)
        mm_min = float(ah.get("mindful_minutes") or 0)
        if mm_min > 0 and bw_min == 0:
            bw_min = mm_min
        if bw_min > 0:
            activities.append({"type": "Breathwork", "minutes": round(bw_min)})
            total_active_min += bw_min
        days.append({
            "date": d,
            "day_of_week": dow,
            "steps": int(float(garmin.get("steps", 0))) if garmin.get("steps") else None,
            "activities": activities,
            "total_active_minutes": round(total_active_min),
        })

    return _ok({"days": days}, cache_seconds=3600)



def handle_protein_sources() -> dict:
    """
    GET /api/protein_sources
    Returns: Top protein sources from MacroFactor food_log, aggregated by food name.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    items = _query_source("macrofactor", d30, today)
    if not items:
        return _ok({"sources": [], "as_of_date": today}, cache_seconds=300)

    from collections import defaultdict
    # Aggregate protein contribution by food name
    food_protein = defaultdict(lambda: {"total_protein": 0.0, "frequency": 0, "total_cal": 0.0})
    days_count = len(items)

    for day in items:
        food_log = day.get("food_log") or []
        for entry in food_log:
            name = (entry.get("food_name") or "").strip()
            if not name or len(name) < 3:
                continue
            pro = float(entry.get("protein_g") or 0)
            if pro < 1:
                continue  # Skip items with negligible protein
            f = food_protein[name]
            f["total_protein"] += pro
            f["frequency"] += 1
            f["total_cal"] += float(entry.get("calories_kcal") or 0)

    total_protein_all = sum(f["total_protein"] for f in food_protein.values())
    sources = []
    for name, f in sorted(food_protein.items(), key=lambda x: -x[1]["total_protein"]):
        avg_daily = round(f["total_protein"] / days_count, 1) if days_count else 0
        pct = round(f["total_protein"] / total_protein_all * 100, 1) if total_protein_all else 0
        sources.append({
            "food": name,
            "avg_daily_g": avg_daily,
            "pct_of_total": pct,
            "frequency": f["frequency"],
            "avg_protein_per_serving": round(f["total_protein"] / f["frequency"], 1) if f["frequency"] else 0,
            "protein_cal_pct": round((f["total_protein"] * 4) / f["total_cal"] * 100) if f["total_cal"] > 0 else 0,
        })
        if len(sources) >= 12:
            break

    return _ok({
        "protein_sources": sources,
        "total_protein_30d_avg_g": round(total_protein_all / days_count, 1) if days_count else 0,
        "days_analyzed": days_count,
    }, cache_seconds=3600)



def handle_physical_overview() -> dict:
    """
    GET /api/physical_overview
    Returns: Latest + baseline DEXA scans, tape measurements, delta computations.
    Source: dexa + measurements DynamoDB partitions.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── 1. DEXA scans (all, sorted ascending) ──
    dexa_pk = f"{USER_PREFIX}dexa"
    # clinical archive — DEXA is date-independent (owner decision 2026-06-06)
    dexa_resp = table.query(**with_phase_filter({
        "KeyConditionExpression": Key("pk").eq(dexa_pk),
        "ScanIndexForward": True,
    }, include_pilot=True))
    dexa_items = _decimal_to_float(dexa_resp.get("Items", []))

    # Baseline = most recent scan on or before EXPERIMENT_START (the starting point)
    # Latest = most recent scan after EXPERIMENT_START (progress since Day 1)
    latest_dexa = None
    baseline_dexa = None
    if dexa_items:
        pre_experiment = [d for d in dexa_items if (d.get("scan_date") or "") <= EXPERIMENT_START]
        post_experiment = [d for d in dexa_items if (d.get("scan_date") or "") > EXPERIMENT_START]
        baseline_dexa = pre_experiment[-1] if pre_experiment else dexa_items[0]
        if post_experiment:
            latest_dexa = post_experiment[-1]
        else:
            # No post-experiment scan yet — show baseline as the current state
            latest_dexa = baseline_dexa
            baseline_dexa = None  # no comparison until a future scan exists

    def _dexa_summary(item):
        if not item:
            return None
        bc = item.get("body_composition", {})
        bs = item.get("body_score", {})
        bone = item.get("bone", {})
        idx = item.get("indices", {})
        s360 = item.get("score_360", {})
        seg_fat = item.get("segmental_fat", {})
        seg_lean = item.get("segmental_lean", {})
        limbs = item.get("limbs", {})
        targets = item.get("targets", {})
        changes = item.get("changes_vs_baseline", {})
        return {
            "scan_date": item.get("scan_date", ""),
            "body_composition": {
                "total_mass_lb": bc.get("total_mass_lb"),
                "body_fat_pct": bc.get("body_fat_pct"),
                "fat_mass_lb": bc.get("fat_mass_lb"),
                "lean_mass_lb": bc.get("lean_mass_lb"),
                "visceral_fat_lb": bc.get("visceral_fat_lb"),
                "visceral_fat_g": bc.get("visceral_fat_g"),
                "android_fat_pct": bc.get("android_fat_pct"),
                "gynoid_fat_pct": bc.get("gynoid_fat_pct"),
                "ag_ratio": bc.get("ag_ratio"),
            },
            "body_score": {
                "grade": bs.get("grade"),
                "numeric": bs.get("numeric"),
                "percentile": bs.get("percentile"),
            },
            "bone": {
                "t_score": bone.get("t_score"),
                "z_score": bone.get("z_score"),
            },
            "indices": {
                "almi_kg_m2": idx.get("almi_kg_m2"),
                "ffmi_kg_m2": idx.get("ffmi_kg_m2"),
                "fmi_kg_m2": idx.get("fmi_kg_m2"),
                "almi_percentile": idx.get("almi_percentile"),
                "ffmi_rating": idx.get("ffmi_rating"),
                "fmi_rating": idx.get("fmi_rating"),
            } if idx else None,
            "score_360": {
                "score": s360.get("score"),
                "biological_age": s360.get("biological_age"),
                "chronological_age": s360.get("chronological_age"),
                "biological_age_delta": s360.get("biological_age_delta"),
            } if s360 else None,
            "segmental_fat": {
                "arms_pct": seg_fat.get("arms_pct"),
                "trunk_pct": seg_fat.get("trunk_pct"),
                "legs_pct": seg_fat.get("legs_pct"),
            } if seg_fat else None,
            "segmental_lean": {
                "total_lb": seg_lean.get("total_lb"),
                "arms_lb": seg_lean.get("arms_lb"),
                "trunk_lb": seg_lean.get("trunk_lb"),
                "legs_lb": seg_lean.get("legs_lb"),
            } if seg_lean else None,
            "targets": targets if targets else None,
            "changes_vs_baseline": changes if changes else None,
        }

    # Days since latest DEXA
    days_since_dexa = None
    next_dexa_recommended = None
    if latest_dexa:
        try:
            scan_dt = datetime.strptime(latest_dexa.get("scan_date", ""), "%Y-%m-%d")
            days_since_dexa = (datetime.now(timezone.utc).replace(tzinfo=None) - scan_dt).days
            next_dt = scan_dt + timedelta(days=90)
            next_dexa_recommended = next_dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # ── 2. Tape measurements (latest session) ──
    meas_pk = f"{USER_PREFIX}measurements"
    # ADR-058: tape measurements are progress-tracking — hide pilot records
    # (page shows an honest empty state until post-restart measurements exist)
    meas_resp = table.query(**with_phase_filter({
        "KeyConditionExpression": Key("pk").eq(meas_pk),
        "ScanIndexForward": False,
        "Limit": 1,
    }))
    meas_items = _decimal_to_float(meas_resp.get("Items", []))
    tape = None
    tape_session_count = 0
    if meas_items:
        m = meas_items[0]
        # Count total sessions
        count_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot measurements
            "KeyConditionExpression": Key("pk").eq(meas_pk),
            "Select": "COUNT",
        }))
        tape_session_count = count_resp.get("Count", 1)

        # Build tape data from raw measurement fields
        raw = {}
        derived = {}
        for k, v in m.items():
            if k in ("pk", "sk", "ingested_at", "source_file", "unit", "measured_by", "date", "session_number"):
                continue
            if k in ("waist_height_ratio", "bilateral_symmetry_bicep_in", "bilateral_symmetry_thigh_in",
                      "trunk_sum_in", "limb_avg_in"):
                derived[k] = v
            elif k.endswith("_in"):
                raw[k] = v

        tape = {
            "session_date": m.get("date", m.get("sk", "").replace("DATE#", "")),
            "session_number": m.get("session_number", 1),
            **raw,
            "derived": {
                **derived,
                "waist_height_ratio_target": 0.5,
            },
        }

    # ── 3. Blood pressure (from apple_health) ──
    bp_data = None
    try:
        ah_pk = f"{USER_PREFIX}apple_health"
        ah_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot BP records
            "KeyConditionExpression": Key("pk").eq(ah_pk) & Key("sk").begins_with("DATE#"),
            "FilterExpression": "attribute_exists(bp_systolic) OR attribute_exists(blood_pressure_systolic)",
            "ScanIndexForward": False,
            "Limit": 30,
            "ProjectionExpression": ("sk, bp_systolic, bp_diastolic, blood_pressure_systolic, "
                                     "blood_pressure_diastolic, blood_pressure_readings_count"),
        }))
        bp_items = _decimal_to_float(ah_resp.get("Items", []))
        if bp_items:
            latest_bp = bp_items[0]
            sys_val = latest_bp.get("bp_systolic") or latest_bp.get("blood_pressure_systolic")
            dia_val = latest_bp.get("bp_diastolic") or latest_bp.get("blood_pressure_diastolic")
            bp_date = latest_bp.get("sk", "").replace("DATE#", "")
            # Status classification
            bp_status = "normal"
            if sys_val and float(sys_val) >= 140 or (dia_val and float(dia_val) >= 90):
                bp_status = "high"
            elif sys_val and float(sys_val) >= 130 or (dia_val and float(dia_val) >= 80):
                bp_status = "elevated"
            # Build trend
            bp_trend = []
            for bpi in bp_items:
                s = bpi.get("bp_systolic") or bpi.get("blood_pressure_systolic")
                d = bpi.get("bp_diastolic") or bpi.get("blood_pressure_diastolic")
                if s:
                    bp_trend.append({
                        "date": bpi.get("sk", "").replace("DATE#", ""),
                        "systolic": float(s),
                        "diastolic": float(d) if d else None,
                    })
            bp_data = {
                "systolic": float(sys_val) if sys_val else None,
                "diastolic": float(dia_val) if dia_val else None,
                "date": bp_date,
                "status": bp_status,
                "readings_count": len(bp_items),
                "trend": bp_trend[:14],
            }
    except Exception as _bp_e:
        logger.warning(f"BP query failed (non-fatal): {_bp_e}")

    return _ok({
        "latest_dexa": _dexa_summary(latest_dexa),
        "baseline_dexa": _dexa_summary(baseline_dexa),
        "dexa_scan_count": len(dexa_items),
        "days_since_dexa": days_since_dexa,
        "next_dexa_recommended": next_dexa_recommended,
        "tape_measurements": tape,
        "tape_session_count": tape_session_count,
        "blood_pressure": bp_data,
    }, cache_seconds=3600)



def handle_journal_analysis() -> dict:
    """
    GET /api/journal_analysis
    Returns 90-day journal theme analysis from cache partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)

    ja_pk = f"{USER_PREFIX}journal_analysis"
    resp = table.query(**with_phase_filter({  # ADR-058: hide pilot journal analysis
        "KeyConditionExpression": Key("pk").eq(ja_pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}"),
        "ScanIndexForward": True,
    }))
    items = _decimal_to_float(resp.get("Items", []))

    # Build theme frequency counts
    theme_counts = {}
    for item in items:
        for theme in item.get("themes", []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    total = len(items)
    top_themes = sorted(
        [{"theme": k, "count": v, "pct": round(v / max(total, 1) * 100)} for k, v in theme_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    # Sentiment trend — rolling 7-day average
    sentiment_trend = []
    daily_scores = [(item.get("date", ""), float(item.get("sentiment_score", 0))) for item in items]
    for i, (date, _) in enumerate(daily_scores):
        window = [s for _, s in daily_scores[max(0, i - 6):i + 1]]
        sentiment_trend.append({
            "date": date,
            "avg_sentiment": round(sum(window) / len(window), 3) if window else 0,
        })

    daily_themes = []
    for item in items:
        daily_themes.append({
            "date": item.get("date", item.get("sk", "").replace("DATE#", "")),
            "dominant_theme": item.get("dominant_theme", "other"),
            "themes": item.get("themes", []),
            "sentiment_score": float(item.get("sentiment_score", 0)),
            "sentiment_label": item.get("sentiment_label", "neutral"),
            "word_count": item.get("word_count", 0),
            "one_line_summary": item.get("one_line_summary", ""),
        })

    return _ok({
        "daily_themes": daily_themes,
        "top_themes": top_themes,
        "total_analyzed": total,
        "date_range": {"start": d90, "end": today},
        "sentiment_trend": sentiment_trend,
    }, cache_seconds=3600)



def handle_mind_overview() -> dict:
    """
    GET /api/mind_overview
    Returns: mood/energy/stress trends, vice streaks, social connection quality,
    mind pillar score, cognitive patterns (when journal data is available).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    d90 = _experiment_date(90)

    # ── 1. Mind pillar from character_sheet ──
    mind_pillar = None
    cs_pk = f"{USER_PREFIX}character_sheet"
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            mp = record.get("pillar_mind", {})
            mind_pillar = {
                "level": float(mp.get("level", 1)),
                "raw_score": float(mp.get("raw_score", 0)),
                "tier": mp.get("tier", "Foundation"),
            }
            break

    # ── 2. State of mind / mood data (Apple Health How We Feel) ──
    som_items = _query_source("state_of_mind", d30, today)
    mood_entries = []
    for s in som_items:
        valence = s.get("valence")
        if valence is not None:
            mood_entries.append({
                "date": s.get("date") or s.get("sk", "").replace("DATE#", ""),
                "valence": float(valence),
                "label": s.get("label", ""),
            })
    # Fallback: check apple_health partition for som_avg_valence (HAE writes here)
    if not mood_entries:
        ah_som = _query_source("apple_health", d30, today)
        for s in ah_som:
            valence = s.get("som_avg_valence")
            if valence is not None:
                mood_entries.append({
                    "date": s.get("date") or s.get("sk", "").replace("DATE#", ""),
                    "valence": float(valence),
                    "label": "",
                })
    mood_entries.sort(key=lambda x: x["date"])
    avg_valence = None
    if mood_entries:
        vals = [m["valence"] for m in mood_entries]
        avg_valence = round(sum(vals) / len(vals), 2)

    # ── 3. Vice streaks from habit_scores ──
    # Stage0 Fix 1 (2026-05-30): use _is_blocked_vice (matches both
    # blocked_vices full names AND blocked_vice_keywords substrings) so the
    # client doesn't have to ship a keyword list to filter what we missed.
    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot habit scores
        "KeyConditionExpression": Key("pk").eq(hs_pk),
        "ScanIndexForward": False,
        "Limit": 1,
    }))
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    vice_data = []
    if hs_items:
        latest_hs = hs_items[0]
        raw_vs = latest_hs.get("vice_streaks") or {}
        if isinstance(raw_vs, dict):
            for name, streak_val in raw_vs.items():
                if _is_blocked_vice(name):
                    continue
                vice_data.append({
                    "name": name,
                    "current_streak": int(streak_val or 0),
                    "holding": int(streak_val or 0) > 0,
                })
        vice_data.sort(key=lambda v: -v["current_streak"])

    # ── 4. Social connection quality (interactions) ──
    int_pk = f"{USER_PREFIX}interactions"
    try:
        int_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot interactions
            "KeyConditionExpression": Key("pk").eq(int_pk) & Key("sk").between(
                f"DATE#{d30}", f"DATE#{today}~"
            ),
            "ScanIndexForward": True,
        }))
        interactions = _decimal_to_float(int_resp.get("Items", []))
    except Exception:
        interactions = []

    total_interactions = len(interactions)
    depth_counts = {"surface": 0, "meaningful": 0, "deep": 0}
    for i in interactions:
        d = (i.get("depth") or "surface").lower()
        if d in depth_counts:
            depth_counts[d] += 1
    meaningful_pct = round((depth_counts["meaningful"] + depth_counts["deep"]) / total_interactions * 100) if total_interactions else 0

    # ── 5. Temptation resist rate (90d) ──
    temp_pk = f"{USER_PREFIX}temptations"
    try:
        temp_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot temptations
            "KeyConditionExpression": Key("pk").eq(temp_pk) & Key("sk").between(
                f"DATE#{d90}", f"DATE#{today}~"
            ),
        }))
        temptations = _decimal_to_float(temp_resp.get("Items", []))
    except Exception:
        temptations = []

    total_temptations = len(temptations)
    resisted = sum(1 for t in temptations if t.get("resisted"))
    resist_rate = round(resisted / total_temptations * 100) if total_temptations else None

    # ── 6. Journal entry count (as journaling progress signal) ──
    journal_pk = f"{USER_PREFIX}notion"
    try:
        j_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot journal records
            "KeyConditionExpression": Key("pk").eq(journal_pk) & Key("sk").between(
                f"DATE#{d30}", f"DATE#{today}"
            ),
            "Select": "COUNT",
        }))
        journal_count = j_resp.get("Count", 0)
    except Exception:
        journal_count = 0

    # ── 7. Meditation / breathwork (Apple Health) ──
    ah_mind = _query_source("apple_health", d30, today)
    meditation_sessions = []
    med_total_min = 0
    med_session_count = 0
    for h in ah_mind:
        _md = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        _bw_sess = int(float(h.get("breathwork_sessions") or 0))
        # Also check mindful_minutes (Breathwrk app writes here via HAE)
        _mm_min = float(h.get("mindful_minutes") or 0)
        if _mm_min > 0 and _bw_min == 0:
            _bw_min = _mm_min
            _bw_sess = max(_bw_sess, 1)  # At least 1 session if we have minutes
        if _bw_min > 0 or _bw_sess > 0:
            meditation_sessions.append({
                "date": _md,
                "minutes": round(_bw_min, 1),
                "sessions": _bw_sess,
            })
            med_total_min += _bw_min
            med_session_count += _bw_sess
    meditation_sessions.sort(key=lambda x: x["date"])
    meditation_data = {
        "sessions_30d": med_session_count,
        "total_minutes_30d": round(med_total_min, 1),
        "avg_session_min": round(med_total_min / med_session_count, 1) if med_session_count else None,
        "daily": meditation_sessions,
    }

    # ── 8. Vice streak timeline (30-day daily history) ──
    hs_30d_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot habit scores
        "KeyConditionExpression": Key("pk").eq(hs_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
        "ScanIndexForward": True,
    }))
    hs_30d_items = _decimal_to_float(hs_30d_resp.get("Items", []))
    vice_timeline = []
    for hs_day in hs_30d_items:
        day_date = hs_day.get("date") or hs_day.get("sk", "").replace("DATE#", "")
        raw_vs = hs_day.get("vice_streaks") or {}
        day_entry = {"date": day_date, "held": int(hs_day.get("vices_held", 0)), "total": int(hs_day.get("vices_total", 0))}
        # Include per-vice streaks (filtered)
        if isinstance(raw_vs, dict):
            streaks = {}
            for name, val in raw_vs.items():
                if _is_blocked_vice(name):
                    continue
                streaks[name] = int(val or 0)
            day_entry["streaks"] = streaks
        vice_timeline.append(day_entry)

    # ── 9. Energy level from journal analysis (latest entry) ──
    energy_level = None
    try:
        ja_resp = table.query(**with_phase_filter({  # ADR-058: hide pilot journal analysis
            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}journal_analysis") & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
            "ScanIndexForward": False, "Limit": 5,
        }))
        ja_items = _decimal_to_float(ja_resp.get("Items", []))
        energy_vals = [i.get("energy_level") for i in ja_items if i.get("energy_level")]
        if energy_vals:
            energy_level = energy_vals[0]  # Most recent
    except Exception:
        pass

    return _ok({
        "mind": {
            "mind_pillar": mind_pillar,
            "avg_valence": avg_valence,
            "mood_entries_count": len(mood_entries),
            "journal_entries_30d": journal_count,
            "resist_rate_pct": resist_rate,
            "total_temptations_90d": total_temptations,
            "resisted_90d": resisted,
            "total_interactions_30d": total_interactions,
            "meaningful_pct": meaningful_pct,
            "depth_counts": depth_counts,
            "energy_level": energy_level,
        },
        "vice_streaks": vice_data,
        "vice_timeline": vice_timeline,
        "mood_trend": mood_entries[-30:],
        "meditation": meditation_data,
    }, cache_seconds=3600)



def handle_frequent_meals() -> dict:
    """GET /api/frequent_meals — Top meals by frequency from MacroFactor food logs."""
    from datetime import datetime, timezone, timedelta
    from collections import Counter, defaultdict
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        items = _query_source("macrofactor", start_date, end_date)
        meal_counts = Counter()
        meal_macros = defaultdict(lambda: {"cal": 0, "protein": 0, "carbs": 0, "fat": 0, "count": 0})

        for day in items:
            food_log = day.get("food_log") or []
            for entry in food_log:
                name = (entry.get("food_name") or "").strip()
                if not name or len(name) < 3:
                    continue
                meal_counts[name] += 1
                m = meal_macros[name]
                m["cal"] += float(entry.get("calories_kcal") or 0)
                m["protein"] += float(entry.get("protein_g") or 0)
                m["carbs"] += float(entry.get("carbs_g") or 0)
                m["fat"] += float(entry.get("fat_g") or 0)
                m["count"] += 1

        top_meals = []
        for name, freq in meal_counts.most_common(8):
            m = meal_macros[name]
            cnt = m["count"] or 1
            avg_cal = round(m["cal"] / cnt)
            avg_pro = round(m["protein"] / cnt)
            avg_carb = round(m["carbs"] / cnt)
            ppc = round((avg_pro * 4 / avg_cal * 100)) if avg_cal > 0 else 0
            top_meals.append({
                "name": name,
                "frequency": freq,
                "avg_calories": avg_cal,
                "avg_protein_g": avg_pro,
                "avg_carbs_g": avg_carb,
                "protein_cal_pct": ppc,
            })

        return _ok({"meals": top_meals, "period_days": 30}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[frequent_meals] Failed: {e}")
        return _error(503, "Meal data temporarily unavailable.")



def handle_meal_glucose() -> dict:
    """GET /api/meal_glucose — Cross-reference MacroFactor meals with Dexcom CGM spikes."""
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = _experiment_date(30)

    try:
        mf_items = _query_source("macrofactor", start_date, end_date)
        cgm_items = _query_source("apple_health", start_date, end_date)

        # Build a map of date → glucose readings for spike calculation
        daily_glucose = {}
        for item in cgm_items:
            date = item.get("sk", "").replace("DATE#", "")
            avg = float(item.get("blood_glucose_avg", 0) or 0)
            peak = float(item.get("blood_glucose_max", 0) or 0)
            baseline = float(item.get("blood_glucose_min", 0) or 0)
            tir = float(item.get("blood_glucose_time_in_range_pct", 0) or 0)
            if avg > 0:
                daily_glucose[date] = {"avg": avg, "peak": peak, "baseline": baseline, "tir": tir}

        # Aggregate meals with glucose context
        meal_data = defaultdict(lambda: {
            "cal": 0, "protein": 0, "carbs": 0, "count": 0,
            "spike_sum": 0, "spike_count": 0, "category": "meal"
        })

        for day in mf_items:
            date = day.get("sk", "").replace("DATE#", "")
            food_log = day.get("food_log") or []
            glucose = daily_glucose.get(date)

            for entry in food_log:
                name = (entry.get("food_name") or "").strip()
                if not name or len(name) < 3:
                    continue
                cal = float(entry.get("calories_kcal") or 0)
                if cal < 100:
                    continue  # Skip small items (seasonings, condiments)

                m = meal_data[name]
                m["cal"] += cal
                m["protein"] += float(entry.get("protein_g") or 0)
                m["carbs"] += float(entry.get("carbs_g") or 0)
                m["count"] += 1

                # Estimate category from meal time
                time_str = entry.get("time") or ""
                if time_str:
                    try:
                        hour = int(time_str.split(":")[0])
                        if hour < 11:
                            m["category"] = "breakfast"
                        elif hour < 15:
                            m["category"] = "lunch"
                        elif hour < 18:
                            m["category"] = "snack"
                        else:
                            m["category"] = "dinner"
                    except (ValueError, IndexError):
                        pass

                # Approximate spike from daily glucose data
                if glucose and glucose["peak"] > 0 and glucose["avg"] > 0:
                    spike = glucose["peak"] - glucose["avg"]
                    # Weight by carb content — high-carb meals contribute more to spikes
                    carbs = float(entry.get("carbs_g") or 0)
                    if carbs > 20:
                        m["spike_sum"] += spike * 0.8
                        m["spike_count"] += 1
                    elif carbs > 5:
                        m["spike_sum"] += spike * 0.4
                        m["spike_count"] += 1

        # Build response — top 10 meals by frequency, with glucose grades
        results = []
        for name, m in sorted(meal_data.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
            cnt = m["count"] or 1
            avg_cal = round(m["cal"] / cnt)
            avg_pro = round(m["protein"] / cnt)
            avg_carb = round(m["carbs"] / cnt)
            avg_spike = round(m["spike_sum"] / m["spike_count"]) if m["spike_count"] > 0 else None

            # Grade based on estimated spike
            if avg_spike is None:
                grade = "?"
                curve = "gentle"
            elif avg_spike <= 15:
                grade = "A"
                curve = "flat"
            elif avg_spike <= 25:
                grade = "B"
                curve = "gentle"
            elif avg_spike <= 40:
                grade = "C"
                curve = "moderate"
            else:
                grade = "D"
                curve = "steep"

            results.append({
                "meal": name,
                "category": m["category"],
                "calories": avg_cal,
                "protein": avg_pro,
                "carbs": avg_carb,
                "spike": avg_spike if avg_spike is not None else 0,
                "grade": grade,
                "curve": curve,
            })

        return _ok({"meals": results, "period_days": 30, "has_cgm": bool(daily_glucose)}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[meal_glucose] Failed: {e}")
        return _error(503, "Meal glucose data temporarily unavailable.")



def handle_strength_benchmarks() -> dict:
    """GET /api/strength_benchmarks — Current 1RM and progress from Hevy data."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    targets = {
        # Matthew's personal 1RM goals -- should migrate to profile.strength_targets
        "Deadlift": 315, "Squat": 265, "Bench Press": 185, "Overhead Press": 135,
    }

    try:
        items = _query_source("hevy", start_date, end_date)
        # Find max weight for each target lift
        best = {}
        for day in items:
            exercises = day.get("exercises") or day.get("workout_exercises") or []
            for ex in exercises:
                name = ex.get("exercise_name") or ex.get("name") or ""
                for target_name in targets:
                    if target_name.lower() in name.lower():
                        sets = ex.get("sets") or []
                        for s in sets:
                            w = float(s.get("weight_lbs") or s.get("weight") or 0)
                            if w > best.get(target_name, 0):
                                best[target_name] = w

        benchmarks = []
        for lift, target in targets.items():
            current = best.get(lift, 0)
            benchmarks.append({
                "lift": lift,
                "current_1rm": round(current),
                "target": target,
                "progress_pct": round((current / target) * 100) if target > 0 else 0,
            })

        return _ok({"benchmarks": benchmarks, "period_days": 90}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[strength_benchmarks] Failed: {e}")
        return _error(503, "Strength data temporarily unavailable.")



def handle_food_delivery_overview() -> dict:
    """
    GET /api/food_delivery_overview
    Returns: 30-day food delivery stats from food_delivery DDB partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    items = _query_source("food_delivery", d30, today)
    if not items:
        return _ok({"food_delivery": None}, cache_seconds=3600)

    from collections import Counter, defaultdict
    total_orders = len(items)
    total_spend = sum(float(i.get("amount") or 0) for i in items)
    platform_counts = Counter()
    weekly_counts = defaultdict(int)
    binge_days = 0

    for i in items:
        platform_counts[i.get("platform") or "Unknown"] += 1
        if i.get("binge"):
            binge_days += 1
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        try:
            wk = datetime.strptime(d, "%Y-%m-%d").strftime("%Y-W%V")
            weekly_counts[wk] += 1
        except Exception:
            pass

    weekly_trend = sorted([{"week": k, "orders": v} for k, v in weekly_counts.items()], key=lambda x: x["week"])

    return _ok({
        "food_delivery": {
            "orders_30d": total_orders,
            "avg_spend": round(total_spend / total_orders, 2) if total_orders else 0,
            "total_spend_30d": round(total_spend, 2),
            "binge_days_30d": binge_days,
        },
        "platform_breakdown": [{"platform": p, "count": c} for p, c in platform_counts.most_common()],
        "weekly_trend": weekly_trend,
    }, cache_seconds=3600)



def handle_strength_deep_dive() -> dict:
    """
    GET /api/strength_deep_dive
    Returns: volume load trend, exercise variety, session patterns from Hevy data.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    items = _query_source("hevy", d90, today)
    if not items:
        return _ok({"strength": None, "message": "No strength data available"}, cache_seconds=3600)

    from collections import defaultdict, Counter

    # Volume load per week (sets × reps × weight)
    weekly_volume = defaultdict(float)
    exercise_freq = Counter()
    session_days = Counter()  # day of week
    session_hours = Counter()  # hour of day
    total_sets_30d = 0
    exercises_30d = set()

    for day in items:
        d = day.get("date") or day.get("sk", "").replace("DATE#", "")
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
        except Exception:
            continue

        exercises = day.get("exercises") or day.get("workout_exercises") or []
        for ex in exercises:
            name = ex.get("exercise_name") or ex.get("name") or "Unknown"
            sets = ex.get("sets") or []
            for s in sets:
                w = float(s.get("weight_lbs") or s.get("weight") or 0)
                r = int(s.get("reps") or 0)
                weekly_volume[week_key] += w * r
                total_sets_30d += 1 if d >= d30 else 0

            if d >= d30:
                exercise_freq[name] += 1
                exercises_30d.add(name)

        if d >= d30:
            session_days[dt.strftime("%a")] += 1

    volume_trend = sorted([
        {"week": k, "volume_lbs": round(v)}
        for k, v in weekly_volume.items()
    ], key=lambda x: x["week"])[-12:]

    top_exercises = [{"name": n, "frequency": c} for n, c in exercise_freq.most_common(10)]

    return _ok({
        "strength": {
            "sessions_90d": len(items),
            "sessions_30d": len([i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d30]),
            "distinct_exercises_30d": len(exercises_30d),
            "total_sets_30d": total_sets_30d,
        },
        "volume_trend": volume_trend,
        "top_exercises": top_exercises,
        "session_days": dict(session_days),
    }, cache_seconds=3600)



def handle_benchmark_trends() -> dict:
    """GET /api/benchmark_trends — Returns benchmark progress data."""
    try:
        # ADR-058: phase=pilot hidden by default; pre-genesis benchmarks won't leak.
        from phase_filter import with_phase_filter
        resp = table.query(**with_phase_filter({
            "KeyConditionExpression": 'pk = :pk',
            "ExpressionAttributeValues": {':pk': 'USER#matthew#SOURCE#benchmarks'},
            "ScanIndexForward": False,
            "Limit": 30,
        }))
        items = resp.get('Items', [])
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=300'},
            'body': json.dumps({'trends': items}, default=str)
        }
    except Exception as e:
        logger.warning(f"[site_api] benchmark_trends: {e}")
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=300'},
            'body': json.dumps({'trends': []})
        }



def handle_meal_responses() -> dict:
    """GET /api/meal_responses — Returns CGM x MacroFactor meal response data."""
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter
        resp = table.query(**with_phase_filter({
            "KeyConditionExpression": 'pk = :pk',
            "ExpressionAttributeValues": {':pk': 'USER#matthew#SOURCE#meal_responses'},
            "ScanIndexForward": False,
            "Limit": 50,
        }))
        items = resp.get('Items', [])
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=600'},
            'body': json.dumps({'meals': items}, default=str)
        }
    except Exception as e:
        logger.warning(f"[site_api] meal_responses: {e}")
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=600'},
            'body': json.dumps({'meals': []})
        }


def handle_workouts() -> dict:
    """
    GET /api/workouts
    Recent Hevy strength sessions with their per-exercise sets (reps × weight).
    Read-only — queries SOURCE#hevy WORKOUT# records for the last 30 days.
    Cache: 900s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    try:
        resp = table.query(**with_phase_filter({  # ADR-058: hide pilot workouts
            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}hevy") & Key("sk").between(
                f"DATE#{d30}#WORKOUT#", f"DATE#{today}#WORKOUT#~"
            ),
            "ScanIndexForward": False,
        }))
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as exc:  # noqa: BLE001
        return _ok({"workouts": [], "error": str(exc)[:120]}, cache_seconds=300)

    def _num(v):
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return None

    workouts = []
    for w in items[:30]:
        exercises = []
        for ex in (w.get("exercises") or []):
            sets = []
            for s in (ex.get("sets") or []):
                sets.append({
                    "type": s.get("type") or "normal",
                    "reps": _num(s.get("reps")),
                    "weight_kg": _num(s.get("weight_kg")),
                    "rpe": _num(s.get("rpe")),
                    "distance_m": _num(s.get("distance_m")),
                })
            exercises.append({"name": ex.get("name"), "notes": ex.get("notes") or "", "sets": sets})
        workouts.append({
            "date": w.get("date"),
            "title": w.get("title"),
            "duration_min": round((_num(w.get("duration_sec")) or 0) / 60),
            "total_volume_kg": _num(w.get("total_volume_kg")),
            "exercise_count": w.get("exercise_count"),
            "set_count": w.get("set_count"),
            "exercises": exercises,
        })
    return _ok({"workouts": workouts, "count": len(workouts)}, cache_seconds=900)
