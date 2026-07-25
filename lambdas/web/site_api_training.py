"""lambdas/web/site_api_training.py — training + strength endpoints (training_overview, strength_benchmarks, strength_deep_dive, benchmark_trends, workouts).

Split out of site_api_observatory.py (#1654 slice 3 — god-module breakup). The
routed handler entrypoints stay in the site_api_observatory facade as thin
delegators; this module holds the logic. Handlers receive the facade's globals()
as `_g` and read the monkeypatched/injectable state (table / _query_source /
_experiment_date / EXPERIMENT_START) via `_g["<name>"]`. This module does NOT
import the facade — no import cycle. All other shared helpers come straight from
site_api_common (identical binding semantics to the pre-split facade).
"""

import json
import os
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    CORS_HEADERS,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    logger,
)

_TRAIN_BLUEPRINT_PUBLIC = os.environ.get("TRAINING_BLUEPRINT_PUBLIC", "").strip().lower() in ("1", "true", "yes")

_MIN_DAILY_AVG_N = 3

_MIN_WEEKLY_WINDOW_DAYS = 7

_MUSCLE_MAP = [
    (["bench press", "chest press", "pec deck", "fly", "flye", "push up", "pushup"], ["Chest", "Triceps", "Shoulders"]),
    (["overhead press", "ohp", "shoulder press", "military press", "arnold"], ["Shoulders", "Triceps"]),
    (["tricep", "skull crusher", "pushdown", "push down", "close grip", "dip"], ["Triceps", "Chest"]),
    (["pull up", "pullup", "chin up", "chinup", "lat pulldown", "pull-up", "pull-down"], ["Back", "Biceps"]),
    (["row", "cable row", "t-bar", "seated row"], ["Back", "Biceps"]),
    (["deadlift"], ["Back", "Hamstrings", "Glutes", "Quads"]),
    (["back extension", "hyperextension", "good morning"], ["Back", "Hamstrings", "Glutes"]),
    (["bicep", "curl", "hammer curl"], ["Biceps"]),
    (["squat", "goblet"], ["Quads", "Glutes", "Hamstrings"]),
    (["leg press"], ["Quads", "Glutes", "Hamstrings"]),
    (["lunge", "step up", "bulgarian"], ["Quads", "Glutes", "Hamstrings"]),
    (["leg extension", "leg curl", "hamstring curl", "nordic"], ["Quads", "Hamstrings"]),
    (["hip thrust", "glute bridge", "hip abduct", "hip adduct"], ["Glutes", "Hamstrings"]),
    (["calf", "calves"], ["Calves"]),
    (
        [
            "plank",
            "crunch",
            "ab ",
            "abs ",
            "core",
            "oblique",
            "sit up",
            "situp",
            "hanging leg",
            "windshield",
            "leg raise",
            "knee raise",
            "russian twist",
            "hollow",
            "rollout",
            "ab wheel",
            "pallof",
            "anti-rotation",
            "anti rotation",
            "dead bug",
            "deadbug",
            "bird dog",
            "carry",
            "carries",
            "farmer",
            "suitcase",
            "woodchop",
            "wood chop",
        ],
        ["Core"],
    ),
]

_LANDMARKS = {
    "Chest": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Back": {"MEV": 10, "MAV_lo": 14, "MAV_hi": 20, "MRV": 25},
    "Shoulders": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 20, "MRV": 25},
    "Quads": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Hamstrings": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Glutes": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Biceps": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Triceps": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Calves": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Core": {"MEV": 4, "MAV_lo": 6, "MAV_hi": 16, "MRV": 25},
}


def _classify_muscles(name):
    nl = (name or "").lower()
    for kws, muscles in _MUSCLE_MAP:
        if any(k in nl for k in kws):
            return muscles
    return ["Other"]


def _compute_muscle_volume(hevy_items, num_weeks):
    """Per-muscle working-set volume vs MEV/MAV/MRV landmarks (sets/week)."""
    sets_by_muscle = {}
    for day in hevy_items:
        for ex in day.get("exercises") or day.get("workout_exercises") or []:
            nm = ex.get("name") or ex.get("exercise_name") or ""
            working = [s for s in (ex.get("sets") or []) if str(s.get("type") or s.get("set_type") or "normal").lower() != "warmup"]
            n = len(working)
            if not n:
                continue
            for m in _classify_muscles(nm):
                if m == "Other":
                    continue
                sets_by_muscle[m] = sets_by_muscle.get(m, 0) + n
    out = []
    for m in sorted(sets_by_muscle, key=lambda x: sets_by_muscle[x], reverse=True):
        spw = round(sets_by_muscle[m] / num_weeks, 1) if num_weeks else sets_by_muscle[m]
        lm = _LANDMARKS.get(m, {"MEV": 0, "MAV_lo": 0, "MAV_hi": 0, "MRV": 99})
        if spw < lm["MEV"]:
            status = "under"
        elif spw <= lm["MAV_hi"]:
            status = "optimal"
        elif spw <= lm["MRV"]:
            status = "high"
        else:
            status = "over"
        out.append(
            {
                "muscle": m,
                "sets_per_week": spw,
                "total_sets": sets_by_muscle[m],
                "MEV": lm["MEV"],
                "MAV_lo": lm["MAV_lo"],
                "MAV_hi": lm["MAV_hi"],
                "MRV": lm["MRV"],
                "status": status,
            }
        )
    return out


def training_overview(*, _g) -> dict:
    """
    GET /api/training_overview
    Returns: workout frequency, zone 2 minutes, training load, strength summary.
    Sources: Strava (cardio), Hevy (strength), Whoop (strain).
    Cache: 3600s.
    """
    table = _g["table"]
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = _experiment_date(30)

    # #1084 (ADR-077 "clamped, not hidden"): the "30d" window above is genesis-
    # clamped by _experiment_date, so early in a cycle it spans far fewer than 30
    # days. Weekly averages must divide by the REAL window length (the fixed /4.3
    # understated a 2-day cycle spread over "4.3 weeks") and read None below the
    # floor rather than extrapolating a day or two out to a week.
    _win_days = max((datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d30, "%Y-%m-%d")).days, 0)
    _win_weeks = _win_days / 7.0 if _win_days >= _MIN_WEEKLY_WINDOW_DAYS else None

    # Strava activities (90 days)
    strava_items = _query_source("strava", d90, today)
    strava_30d = [s for s in strava_items if (s.get("date") or s.get("sk", "").replace("DATE#", "")) >= d30]

    # Zone 2 detection: HR between 60-70% of max HR
    max_hr = 184  # Matthew's measured max HR — matches profile.max_heart_rate
    z2_low, z2_high = max_hr * 0.60, max_hr * 0.70
    z2_minutes_30d = 0
    # Z2 is recalculated after flattening activities below
    z2_target = 150  # minutes/week

    def _z2_weekly_stats(total_min):
        # #1084: weekly average over the real (genesis-clamped) window — None
        # below the _MIN_WEEKLY_WINDOW_DAYS floor; z2_pct rides along.
        wa = round(total_min / _win_weeks) if _win_weeks is not None else None
        pct = round(wa / z2_target * 100) if (wa is not None and z2_target) else None
        return wa, pct

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
    # #1084: real-window weekly rate, None below the floor (was a fixed /4.3).
    weekly_avg = round(total_workouts_30d / _win_weeks, 1) if _win_weeks is not None else None

    # Activity type breakdown (30d)
    type_counts = {}
    for a in all_activities_30d:
        sport = a.get("sport_type") or a.get("type") or "Other"
        type_counts[sport] = type_counts.get(sport, 0) + 1
    top_activities = sorted(type_counts.items(), key=lambda x: -x[1])[:8]

    # Total training minutes and distance (30d)
    def _act_minutes(a):
        return float(a.get("duration_minutes") or a.get("moving_time_minutes") or (a.get("moving_time_seconds") or 0) / 60 or 0)

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

    modality_map = _dd2(
        lambda: {
            "count": 0,
            "total_min": 0,
            "total_mi": 0,
            "total_elev_ft": 0,
            "hr_sum": 0,
            "hr_count": 0,
            "z2_min": 0,
        }
    )
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
        modality_breakdown.append(
            {
                "type": sport,
                "count_30d": m["count"],
                "total_minutes_30d": round(m["total_min"]),
                "avg_duration_min": round(m["total_min"] / m["count"]) if m["count"] else 0,
                "avg_hr": round(m["hr_sum"] / m["hr_count"]) if m["hr_count"] else None,
                "total_distance_mi": round(m["total_mi"], 1),
                "total_elevation_ft": round(m["total_elev_ft"]),
                "z2_minutes": round(m["z2_min"]),
                "trend_vs_prior_30d": trend,
            }
        )

    # Recalculate Z2 from all flattened activities
    # Staleness honesty (truth audit 2026-07-10): the 30d average masks a quiet current
    # week (218 min/wk average over weeks at 21 and 15 min). Track the trailing-7d Z2
    # alongside it so the front-end can show the CURRENT week vs target honestly.
    _d7_cal = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    z2_minutes_30d = 0
    z2_trailing_7d = 0.0
    for a in all_activities_30d:
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        dur = _act_minutes(a)
        if avg_hr and dur:
            if z2_low <= float(avg_hr) <= z2_high:
                z2_minutes_30d += dur
                if (a.get("_day_date") or "") >= _d7_cal:
                    z2_trailing_7d += dur
    z2_weekly_avg, z2_pct = _z2_weekly_stats(z2_minutes_30d)

    # ── Walking stats — per-day step merge, Apple-Health-first ──
    # Garmin is rate-limited/dead and emits a phantom ~298-step record that used to block
    # the Apple-Health fallback (it only fired when Garmin was *empty*). Now merge both
    # sources per day, prefer Apple Health, and only accept a Garmin-only day if it's
    # plausible (>=1000 steps) — which drops the phantom 298. (#8)
    garmin_30d = _query_source("garmin", d30, today)
    ah_30d = _query_source("apple_health", d30, today)
    _PHANTOM_STEP_FLOOR = 1000
    steps_by_date: dict = {}
    for h in ah_30d:
        if h.get("steps") and float(h["steps"]) > 0:
            _d = h.get("date") or h.get("sk", "").replace("DATE#", "")
            steps_by_date[_d] = max(steps_by_date.get(_d, 0), int(float(h["steps"])))
    for g in garmin_30d:
        if g.get("steps") and float(g["steps"]) > 0:
            _d = g.get("date") or g.get("sk", "").replace("DATE#", "")
            gs = int(float(g["steps"]))
            if _d not in steps_by_date and gs >= _PHANTOM_STEP_FLOOR:
                steps_by_date[_d] = gs  # Garmin only when Apple Health absent AND plausible
    # #1084 root cause: this mean divided by however few days existed — including
    # an n=1 "average" of ONLY today's partial count on Day 1 (ADR-105 violation:
    # no n, no uncertainty). Guard: today never counts (steps accrue until
    # midnight) and the mean needs _MIN_DAILY_AVG_N complete days; below the
    # floor it is None with an explicit reason. The per-day trend still charts
    # today — a labeled daily value, not a fabricated average.
    _complete_step_days = {d: v for d, v in steps_by_date.items() if d < today}
    avg_daily_steps_n = len(_complete_step_days)
    if avg_daily_steps_n >= _MIN_DAILY_AVG_N:
        avg_daily_steps = round(sum(_complete_step_days.values()) / avg_daily_steps_n)
        avg_daily_steps_reason = None
    else:
        avg_daily_steps = None
        avg_daily_steps_reason = "insufficient_data"
    daily_steps_trend = []
    for _step_date in sorted(steps_by_date):
        try:
            _step_dow = datetime.strptime(_step_date, "%Y-%m-%d").weekday()
        except Exception:
            _step_dow = 0
        daily_steps_trend.append({"date": _step_date, "steps": steps_by_date[_step_date], "is_weekend": _step_dow >= 5})

    walk_activities = [a for a in all_activities_30d if (a.get("sport_type") or "").lower() in ("walk", "hike")]
    ruck_activities = [
        a for a in all_activities_30d if "ruck" in (a.get("name") or "").lower() or "ruck" in (a.get("sport_type") or "").lower()
    ]
    walking_data = {
        "avg_daily_steps": avg_daily_steps,
        # #1084 / ADR-105: the claim carries its n; when the avg is None the
        # reason says why (front-ends self-hide on the null either way).
        "avg_daily_steps_n": avg_daily_steps_n,
        "avg_daily_steps_reason": avg_daily_steps_reason,
        "total_walks_30d": len(walk_activities),
        "total_rucks_30d": len(ruck_activities),
        "total_miles_30d": round(sum(_act_miles(a) for a in walk_activities), 1),
        "avg_pace_min_per_mi": None,
        "z2_minutes_walking": round(
            sum(
                _act_minutes(a)
                for a in walk_activities
                if a.get("average_heartrate") and z2_low <= float(a["average_heartrate"]) <= z2_high
            )
        ),
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
        "WeightTraining": "strength",
        "Workout": "strength",
        "Walk": "walking",
        "Hike": "hiking",
        "Ride": "cycling",
        "VirtualRide": "cycling",
        "Stretch": "stretching",
        "Yoga": "stretching",
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
    # #1084 sibling guard: day strain accrues until midnight, so today's row is a
    # partial — exclude it, and require the same complete-day floor as the steps
    # mean before claiming a 30d average.
    strain_vals = [
        float(w["strain"]) for w in whoop_30d if w.get("strain") and (w.get("date") or w.get("sk", "").replace("DATE#", ""))[:10] < today
    ]
    avg_strain = round(sum(strain_vals) / len(strain_vals), 1) if len(strain_vals) >= _MIN_DAILY_AVG_N else None

    # Whoop workouts — per-workout HR zone data (enriches Strava)
    whoop_workouts = []
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot workouts
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}whoop")
                    & Key("sk").between(f"DATE#{d30}#WORKOUT#", f"DATE#{today}#WORKOUT#~"),
                }
            )
        )
        whoop_workouts = _decimal_to_float(resp.get("Items", []))
        # Add Whoop Z2 minutes from actual HR zones to the Z2 calculation
        for ww in whoop_workouts:
            z2_from_whoop = float(ww.get("zone_2_minutes", 0) or 0)
            if z2_from_whoop > 0:
                z2_minutes_30d += z2_from_whoop
                _ww_date = ww.get("date") or ww.get("sk", "").replace("DATE#", "")[:10]
                if (_ww_date or "") >= _d7_cal:
                    z2_trailing_7d += z2_from_whoop
        # Recalculate Z2 weekly avg with Whoop data
        if whoop_workouts:
            z2_weekly_avg, z2_pct = _z2_weekly_stats(z2_minutes_30d)
    except Exception as e:
        logger.warning(f"[training_overview] Whoop workout query failed (non-fatal): {e}")

    # Hevy — latest strength session info
    hevy_items = _query_source("hevy", d30, today)
    strength_sessions_30d = len(hevy_items)
    # P1.3 — per-muscle weekly volume vs MEV/MAV/MRV (core-mapping bug fixed upstream, #186).
    _mv_weeks = max(1.0, min(30, _days_since_exp) / 7.0)
    muscle_volume = _compute_muscle_volume(hevy_items, _mv_weeks)

    # P2.3 — present-vs-PROVEN_BLUEPRINT training benchmark (NEVER public — flag stays OFF).
    # With the flag off (default) training_reference is never queried; nothing blueprint-derived
    # enters the public response (ADR-089: the blueprint may not surface to any public surface).
    training_blueprint = None
    if _TRAIN_BLUEPRINT_PUBLIC:
        _tr = _query_source("training_reference", "2010-01-01", today)
        _latest_tr = sorted(_tr, key=lambda x: x.get("sk", ""))[-1] if _tr else None
        if _latest_tr:
            training_blueprint = {
                "public": True,
                "confidence": _latest_tr.get("confidence"),
                "note": "present training vs the proven loss-period blueprint",
            }

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

    weekly_trend = sorted(
        [
            {"week": k, "workouts": v["workouts"], "minutes": round(v["minutes"]), "z2_min": round(v["z2_min"])}
            for k, v in week_buckets.items()
        ],
        key=lambda x: x["week"],
    )[
        -12:
    ]  # last 12 weeks

    # Recent cardio — the merged Strava + Whoop activity list, PLUS cardio/mobility logged
    # as Hevy exercises (Matthew logs Cycling/Elliptical/Stretching inside his Hevy sessions,
    # carrying distance/duration). Hevy was previously treated as strength-only, so cycling +
    # stretching never surfaced here (#5/#6). Newest first; distance in mi + km.
    _CARDIO = {
        "run",
        "running",
        "trailrun",
        "treadmill",
        "ride",
        "cycling",
        "virtualride",
        "ebikeride",
        "walk",
        "hike",
        "row",
        "rowing",
        "swim",
        "swimming",
        "elliptical",
        "stairmaster",
        "stairstepper",
    }
    cardio_sessions = []
    for a in sorted(all_activities_30d, key=lambda x: x.get("_day_date", "") or "", reverse=True):
        sport = (a.get("sport_type") or a.get("type") or "").strip()
        mi = _act_miles(a)
        if sport.lower() not in _CARDIO and not mi:
            continue
        cardio_sessions.append(
            {
                "date": a.get("_day_date"),
                "sport": sport or "Activity",
                "distance_mi": round(mi, 2) if mi else None,
                "minutes": round(_act_minutes(a)) or None,
                "avg_hr": a.get("average_heartrate") or a.get("avg_hr"),
                "source": "whoop" if a.get("strain") is not None else "strava",
            }
        )
        if len(cardio_sessions) >= 20:
            break

    # Fold in cardio/mobility-bearing Hevy exercises (#5/#6). Each exercise's sets carry
    # distance_m / duration_sec; sum per exercise per workout. Mobility (Stretching/Yoga)
    # shows as a session even with no distance.
    _HEVY_CARDIO = {"cycling", "elliptical", "rowing", "treadmill", "stair", "ski erg", "ski-erg", "assault", "echo bike", "air bike"}
    _HEVY_MOBILITY = {"stretching", "stretch", "mobility", "yoga", "foam roll"}
    hevy_cardio_30d = _query_source("hevy", d30, today)
    _hevy_cardio_min = 0.0  # P0.4: Hevy bike/elliptical steady-cardio minutes → Zone-2 base
    for w in sorted(hevy_cardio_30d, key=lambda x: x.get("date") or x.get("sk", ""), reverse=True):
        wdate = w.get("date") or w.get("sk", "").replace("DATE#", "")[:10]
        for ex in w.get("exercises") or []:
            nm = (ex.get("name") or ex.get("exercise_name") or "").strip()
            nl = nm.lower()
            is_cardio = any(k in nl for k in _HEVY_CARDIO)
            is_mob = any(k in nl for k in _HEVY_MOBILITY)
            if not (is_cardio or is_mob):
                continue
            sets = ex.get("sets") or []
            dist_m = sum(float(s.get("distance_m") or 0) for s in sets)
            secs = sum(float(s.get("duration_sec") or 0) for s in sets)
            if is_cardio and secs:
                _hevy_cardio_min += secs / 60.0
                if (wdate or "") >= _d7_cal:
                    z2_trailing_7d += secs / 60.0
            cardio_sessions.append(
                {
                    "date": wdate,
                    "sport": nm or ("Mobility" if is_mob else "Cardio"),
                    "distance_mi": round(dist_m * 0.000621371, 2) if dist_m else None,
                    "minutes": round(secs / 60) or None,
                    "avg_hr": None,
                    "modality": "mobility" if is_mob else "cardio",
                    "source": "hevy",
                }
            )
    cardio_sessions = sorted(cardio_sessions, key=lambda x: x.get("date") or "", reverse=True)[:20]

    # P0.4 — Zone-2 is cross-source: fold Hevy bike/elliptical minutes (logged steady
    # cardio, no HR stream) into the Z2 base alongside Strava + Whoop. Never Strava-only.
    if _hevy_cardio_min:
        z2_minutes_30d += _hevy_cardio_min
        z2_weekly_avg, z2_pct = _z2_weekly_stats(z2_minutes_30d)

    return _ok(
        {
            "training": {
                "workouts_30d": total_workouts_30d,
                "workouts_90d": total_workouts_90d,
                "weekly_avg": weekly_avg,
                "total_minutes_30d": round(total_minutes_30d),
                "total_distance_mi": round(total_distance_mi, 1),
                "z2_weekly_avg_min": z2_weekly_avg,
                "z2_target_min": z2_target,
                # Staleness honesty: z2_pct is the 30d AVERAGE vs target, served uncapped
                # (a capped 100 hid that it was an average at all); z2_trailing_7d_min is
                # the current week — the number that goes quiet when training stops.
                "z2_pct": z2_pct,
                "z2_trailing_7d_min": round(z2_trailing_7d),
                "avg_strain": avg_strain,
                "strength_sessions_30d": strength_sessions_30d,
                "top_activities": [{"type": t, "count": c} for t, c in top_activities],
                "whoop_workout_count": len(whoop_workouts),
                "active_modalities": len(modality_breakdown),
                "avg_daily_steps": walking_data["avg_daily_steps"],
            },
            "modality_breakdown": modality_breakdown,
            "muscle_volume": muscle_volume,
            "training_blueprint": training_blueprint,
            "daily_modality_minutes_30d": daily_modality_minutes_30d,
            "walking": walking_data,
            "breathwork": breathwork_data,
            "weekly_trend": weekly_trend,
            "whoop_workouts": [
                {
                    "date": w.get("date"),
                    "sport_name": w.get("sport_name", "Activity"),
                    "strain": w.get("strain"),
                    "zone_2_minutes": w.get("zone_2_minutes"),
                    "zone_3_minutes": w.get("zone_3_minutes"),
                    "distance_meter": w.get("distance_meter"),
                    "average_heart_rate": w.get("average_heart_rate"),
                }
                for w in whoop_workouts[:20]
            ],
            "cardio_sessions": cardio_sessions,
        },
        cache_seconds=3600,
    )


def strength_benchmarks(*, _g) -> dict:
    """GET /api/strength_benchmarks — Current 1RM and progress from Hevy data."""
    _query_source = _g["_query_source"]
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    targets = {
        # Matthew's personal 1RM goals -- should migrate to profile.strength_targets
        "Deadlift": 315,
        "Squat": 265,
        "Bench Press": 185,
        "Overhead Press": 135,
    }

    try:
        items = _query_source("hevy", start_date, end_date)
        # Find max weight for each target lift, AND a per-session (per-day) estimated-1RM
        # history so the front-end can render the Lift Index trend (P0.1) — load moving up
        # over weeks, never a 1RM target/goal.
        best = {}
        history = {t: {} for t in targets}  # lift -> {date: best_e1rm_that_day}
        for day in items:
            d = day.get("date") or day.get("sk", "").replace("DATE#", "")[:10]
            exercises = day.get("exercises") or day.get("workout_exercises") or []
            for ex in exercises:
                name = ex.get("exercise_name") or ex.get("name") or ""
                for target_name in targets:
                    if target_name.lower() in name.lower():
                        sets = ex.get("sets") or []
                        for s in sets:
                            # Hevy stores set weight in weight_kg (native unit); the old
                            # weight_lbs/weight read was always 0 → every 1RM read 0. Convert,
                            # then estimate 1RM via Epley (the column promises "estimated 1RM").
                            w_kg = s.get("weight_kg")
                            w = float(w_kg) * 2.2046226 if w_kg not in (None, "") else float(s.get("weight_lbs") or s.get("weight") or 0)
                            reps = int(s.get("reps") or 0)
                            if w <= 0 or reps < 1 or reps > 12:
                                continue
                            e1rm = w * (1 + reps / 30.0)  # Epley estimated 1RM (lb)
                            if e1rm > best.get(target_name, 0):
                                best[target_name] = e1rm
                            if d and e1rm > history[target_name].get(d, 0):
                                history[target_name][d] = e1rm

        benchmarks = []
        for lift, target in targets.items():
            current = best.get(lift, 0)
            logged = current > 0  # a lift not performed in the window isn't "0 / 0%" — it's no-data
            exceeded = logged and current > target  # already past the goal → "exceeded", not "129%"
            hist = [{"date": dd, "e1rm": round(history[lift][dd])} for dd in sorted(history[lift])]
            benchmarks.append(
                {
                    "lift": lift,
                    "current_1rm": round(current) if logged else None,
                    "target": target,
                    # Clamp progress at 100 (a goal already beaten isn't "129% of progress");
                    # None when the lift wasn't logged this window so the UI shows "—" not 0%.
                    "progress_pct": (min(100, round((current / target) * 100)) if target > 0 else 0) if logged else None,
                    "exceeded": exceeded,
                    "logged": logged,
                    # P0.1 Lift Index: per-session estimated-1RM trend (lb) + the count gate.
                    "history": hist,
                    "sessions": len(hist),
                }
            )

        return _ok({"benchmarks": benchmarks, "period_days": 90}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[strength_benchmarks] Failed: {e}")
        return _error(503, "Strength data temporarily unavailable.")


def strength_deep_dive(*, _g) -> dict:
    """
    GET /api/strength_deep_dive
    Returns: volume load trend, exercise variety, session patterns from Hevy data.
    Cache: 3600s.
    """
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    items = _query_source("hevy", d90, today)
    if not items:
        return _ok({"strength": None, "message": "No strength data available"}, cache_seconds=3600)

    from collections import Counter, defaultdict

    # Volume load per week (sets × reps × weight)
    weekly_volume = defaultdict(float)
    exercise_freq = Counter()
    session_days = Counter()  # day of week
    Counter()  # hour of day
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

    volume_trend = sorted([{"week": k, "volume_lbs": round(v)} for k, v in weekly_volume.items()], key=lambda x: x["week"])[-12:]

    top_exercises = [{"name": n, "frequency": c} for n, c in exercise_freq.most_common(10)]

    return _ok(
        {
            "strength": {
                "sessions_90d": len(items),
                "sessions_30d": len([i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d30]),
                "distinct_exercises_30d": len(exercises_30d),
                "total_sets_30d": total_sets_30d,
            },
            "volume_trend": volume_trend,
            "top_exercises": top_exercises,
            "session_days": dict(session_days),
        },
        cache_seconds=3600,
    )


def benchmark_trends(*, _g) -> dict:
    """GET /api/benchmark_trends — Returns benchmark progress data."""
    table = _g["table"]
    try:
        # ADR-058: phase=pilot hidden by default; pre-genesis benchmarks won't leak.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "USER#matthew#SOURCE#benchmarks"},
                    "ScanIndexForward": False,
                    "Limit": 30,
                }
            )
        )
        items = resp.get("Items", [])
        return {
            "statusCode": 200,
            "headers": {**CORS_HEADERS, "Cache-Control": "max-age=300"},
            "body": json.dumps({"trends": items}, default=str),
        }
    except Exception as e:
        logger.warning(f"[site_api] benchmark_trends: {e}")
        return {"statusCode": 200, "headers": {**CORS_HEADERS, "Cache-Control": "max-age=300"}, "body": json.dumps({"trends": []})}


def workouts(*, _g) -> dict:
    """
    GET /api/workouts
    Recent Hevy strength sessions with their per-exercise sets (reps × weight).
    Read-only — queries SOURCE#hevy WORKOUT# records for the last 30 days.
    Cache: 900s.
    """
    table = _g["table"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot workouts
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}hevy")
                    & Key("sk").between(f"DATE#{d30}#WORKOUT#", f"DATE#{today}#WORKOUT#~"),
                    "ScanIndexForward": False,
                }
            )
        )
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
        for ex in w.get("exercises") or []:
            sets = []
            for s in ex.get("sets") or []:
                sets.append(
                    {
                        "type": s.get("type") or "normal",
                        "reps": _num(s.get("reps")),
                        "weight_kg": _num(s.get("weight_kg")),
                        "rpe": _num(s.get("rpe")),
                        "distance_m": _num(s.get("distance_m")),
                    }
                )
            exercises.append({"name": ex.get("name"), "notes": ex.get("notes") or "", "sets": sets})
        workouts.append(
            {
                "date": w.get("date"),
                "title": w.get("title"),
                "duration_min": round((_num(w.get("duration_sec")) or 0) / 60),
                "total_volume_kg": _num(w.get("total_volume_kg")),
                "exercise_count": w.get("exercise_count"),
                "set_count": w.get("set_count"),
                "exercises": exercises,
            }
        )
    return _ok({"workouts": workouts, "count": len(workouts)}, cache_seconds=900)
