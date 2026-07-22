"""
Training tools: load, PRs, correlation, seasonal, periodization, recommendation, HR recovery.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from mcp.core import get_profile, get_sot, query_source
from mcp.helpers import compute_daily_load_score, compute_ewa
from mcp.tools_correlation import tool_get_zone2_breakdown


def _get_training_load(args):
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=180)
    start_date = args.get("start_date", start_dt.strftime("%Y-%m-%d"))
    warmup_dt = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=84)
    warmup_start = warmup_dt.strftime("%Y-%m-%d")

    cardio_source = get_sot("cardio")
    day_records = query_source(cardio_source, warmup_start, end_date)

    load_by_date = {}
    for day in day_records:
        d = day.get("date")
        if d:
            load_by_date[d] = compute_daily_load_score(day)

    cur = warmup_dt
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    chrono = []
    while cur <= end_dt:
        ds = cur.strftime("%Y-%m-%d")
        chrono.append((ds, load_by_date.get(ds, 0.0)))
        cur += timedelta(days=1)

    # Banister 1991 Impulse-Response model: CTL 42-day, ATL 7-day
    ctl_series = compute_ewa(chrono, 42)
    atl_series = compute_ewa(chrono, 7)

    start_dt_req = datetime.strptime(start_date, "%Y-%m-%d")
    result_rows = []
    for (date_str, ctl), (_, atl) in zip(ctl_series, atl_series):
        if datetime.strptime(date_str, "%Y-%m-%d") < start_dt_req:
            continue
        tsb = round(ctl - atl, 2)
        acwr = round(atl / ctl, 2) if ctl > 0 else None

        risk = "low"
        # Gabbett 2016: >1.3 moderate injury risk, >1.5 high; 0.8-1.3 is sweet spot
        if acwr is not None:
            if acwr > 1.5:
                risk = "HIGH — injury risk elevated, consider reducing load"
            elif acwr > 1.3:
                risk = "moderate — monitor carefully"

        form = "neutral"
        if tsb > 5:
            form = "fresh — good for key sessions or race"
        elif tsb < -25:  # #490: most-negative first — the old order made this unreachable
            form = "very fatigued — recovery priority"
        elif tsb < -10:
            form = "fatigued — accumulated training stress is high"

        result_rows.append(
            {
                "date": date_str,
                "daily_load": round(load_by_date.get(date_str, 0.0), 1),
                "ctl_fitness": ctl,
                "atl_fatigue": atl,
                "tsb_form": tsb,
                "acwr": acwr,
                "injury_risk": risk,
                "form_status": form,
            }
        )

    if not result_rows:
        return {"error": "No training data found for the requested window."}

    latest = result_rows[-1]
    peak_ctl = max(result_rows, key=lambda r: r["ctl_fitness"])

    # Board rec 1D: Training monotony (Galpin) — weekly mean / SD of daily load
    last_7_loads = [r["daily_load"] for r in result_rows[-7:]]
    monotony_result = {}
    if len(last_7_loads) >= 7:
        mean_7 = sum(last_7_loads) / len(last_7_loads)
        var_7 = sum((x - mean_7) ** 2 for x in last_7_loads) / len(last_7_loads)
        sd_7 = var_7**0.5 if var_7 > 0 else 0
        monotony = round(mean_7 / sd_7, 2) if sd_7 > 0 else None
        weekly_strain = round(sum(last_7_loads) * monotony, 1) if monotony else None
        monotony_result = {
            "training_monotony": monotony,
            "weekly_training_strain": weekly_strain,
            "monotony_risk": "HIGH — monotonous training increases illness/overtraining risk" if monotony and monotony > 2.0 else "ok",
        }

    return {
        "model": "Banister Impulse-Response (CTL=42d EWA, ATL=7d EWA)",
        "load_proxy": "kJ (cycling) > TRIMP (HR×time) > distance+elevation estimate",
        "current_state": latest,
        "peak_fitness": {"ctl": peak_ctl["ctl_fitness"], "date": peak_ctl["date"]},
        "monotony": monotony_result,
        "series": result_rows,
        "interpretation": {
            "CTL": "Fitness base (42-day). Higher = more aerobic capacity built.",
            "ATL": "Fatigue (7-day). Spikes after big training blocks.",
            "TSB": "Form = CTL - ATL. Positive = fresh, negative = tired.",
            "ACWR": "Acute:Chronic ratio. >1.3 caution, >1.5 injury risk.",
            "Monotony": "Weekly mean load / SD. >2.0 = illness risk (Galpin). Vary intensity.",
        },
    }


def _get_training_periodization(args):
    """
    Training periodization analysis. Detects mesocycle phases, deload needs,
    progressive overload tracking, and training polarization.

    Galpin framework: Base → Build → Peak → Deload (3:1 or 4:1 ratio).
    Attia: Training is the most potent longevity drug — but only with periodization.
    Seiler: 80/20 polarized model — 80% easy, 20% hard for optimal adaptation.
    """
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    weeks_back = int(args.get("weeks", 12))
    start_date = args.get("start_date", (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Fetch training data ───────────────────────────────────────────────
    strava_items = query_source("strava", start_date, end_date)
    mf_workout_items = query_source("macrofactor_workouts", start_date, end_date)

    if not strava_items and not mf_workout_items:
        return {"error": "No training data for range.", "start_date": start_date, "end_date": end_date}

    # ── 2. Build weekly training profile ─────────────────────────────────────
    def _week_key(date_str):
        d = datetime.strptime(date_str, "%Y-%m-%d")
        # ISO week: Monday start
        return d.strftime("%G-W%V")

    weeks = defaultdict(
        lambda: {
            "cardio_minutes": 0,
            "strength_minutes": 0,
            "total_minutes": 0,
            "zone2_minutes": 0,
            "hard_minutes": 0,
            "easy_minutes": 0,
            "sessions": 0,
            "strength_sessions": 0,
            "cardio_sessions": 0,
            "total_volume_lbs": 0,
            "rest_days": 0,
            "dates": set(),
            "activities": [],
        }
    )

    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical", "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}

    # Process Strava activities
    for item in strava_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        weeks[wk]["dates"].add(date)
        for act in item.get("activities") or []:
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:
                continue
            duration_min = elapsed / 60
            avg_hr = _sf(act.get("average_heartrate"))

            weeks[wk]["sessions"] += 1
            weeks[wk]["total_minutes"] += duration_min

            is_cardio = sport in cardio_types
            is_strength = sport in strength_types

            if is_cardio:
                weeks[wk]["cardio_sessions"] += 1
                weeks[wk]["cardio_minutes"] += duration_min

                if avg_hr:
                    hr_pct = avg_hr / max_hr * 100
                    if hr_pct <= 70:
                        weeks[wk]["zone2_minutes"] += duration_min
                        weeks[wk]["easy_minutes"] += duration_min
                    elif hr_pct >= 80:
                        weeks[wk]["hard_minutes"] += duration_min
                    else:
                        weeks[wk]["easy_minutes"] += duration_min  # Zone 3 counted as moderate

            elif is_strength:
                weeks[wk]["strength_sessions"] += 1
                weeks[wk]["strength_minutes"] += duration_min

            weeks[wk]["activities"].append(
                {
                    "date": date,
                    "sport": sport,
                    "duration_min": round(duration_min, 1),
                    "avg_hr": avg_hr,
                }
            )

    # Process MacroFactor workouts for volume tracking
    for item in mf_workout_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        vol = _sf(item.get("total_volume_lbs")) or 0
        weeks[wk]["total_volume_lbs"] += vol

    # Calculate rest days per week
    for wk, data in weeks.items():
        data["rest_days"] = 7 - len(data["dates"])
        data["dates"] = sorted(data["dates"])  # Convert set to sorted list

    # ── 3. Weekly progression analysis ───────────────────────────────────────
    sorted_weeks = sorted(weeks.keys())
    weekly_summary = []
    for wk in sorted_weeks:
        w = weeks[wk]
        total_min = w["total_minutes"]
        easy_pct = round(w["easy_minutes"] / total_min * 100, 1) if total_min > 0 else 0
        hard_pct = round(w["hard_minutes"] / total_min * 100, 1) if total_min > 0 else 0

        # Classify week phase
        if total_min < 60:
            phase = "deload"
        elif w["sessions"] <= 2:
            phase = "deload"
        else:
            if w["hard_minutes"] > total_min * 0.3:
                phase = "build"
            elif total_min > 300:
                phase = "peak"
            else:
                phase = "base"

        weekly_summary.append(
            {
                "week": wk,
                "phase": phase,
                "sessions": w["sessions"],
                "total_minutes": round(total_min, 1),
                "cardio_minutes": round(w["cardio_minutes"], 1),
                "strength_minutes": round(w["strength_minutes"], 1),
                "zone2_minutes": round(w["zone2_minutes"], 1),
                "hard_minutes": round(w["hard_minutes"], 1),
                "easy_pct": easy_pct,
                "hard_pct": hard_pct,
                "volume_lbs": round(w["total_volume_lbs"], 1),
                "rest_days": w["rest_days"],
                "cardio_sessions": w["cardio_sessions"],
                "strength_sessions": w["strength_sessions"],
            }
        )

    # ── 4. Deload detection ──────────────────────────────────────────────────
    deload_analysis = {
        "weeks_since_last_deload": 0,
        "deload_recommended": False,
        "reason": None,
    }

    # Count consecutive non-deload weeks from end
    consecutive = 0
    for ws in reversed(weekly_summary):
        if ws["phase"] == "deload":
            break
        consecutive += 1
    deload_analysis["weeks_since_last_deload"] = consecutive

    if consecutive >= 4:
        deload_analysis["deload_recommended"] = True
        deload_analysis["reason"] = (
            f"{consecutive} consecutive training weeks without deload. Galpin recommends 3:1 or 4:1 loading-to-deload ratio."
        )
    elif consecutive >= 3:
        # Check if volume is trending up
        recent_3 = weekly_summary[-3:] if len(weekly_summary) >= 3 else weekly_summary
        if len(recent_3) >= 3:
            vols = [w["total_minutes"] for w in recent_3]
            if all(vols[i] >= vols[i - 1] for i in range(1, len(vols))):
                deload_analysis["deload_recommended"] = True
                deload_analysis["reason"] = (
                    "3 consecutive weeks of increasing volume. Progressive overload is good, but a deload preserves adaptation."
                )

    # ── 5. Training polarization check (Seiler) ─────────────────────────────
    total_easy = sum(w["easy_minutes"] for wk, w in weeks.items())
    total_hard = sum(w["hard_minutes"] for wk, w in weeks.items())
    total_all = total_easy + total_hard
    polarization = None

    if total_all > 0:
        easy_ratio = round(total_easy / total_all * 100, 1)
        hard_ratio = round(total_hard / total_all * 100, 1)
        mid_ratio = round(100 - easy_ratio - hard_ratio, 1)

        if easy_ratio >= 75:
            pol_status = "well_polarized"
        elif easy_ratio >= 60:
            pol_status = "moderately_polarized"
        else:
            pol_status = "too_much_intensity"

        polarization = {
            "easy_pct": easy_ratio,
            "hard_pct": hard_ratio,
            "middle_zone_pct": mid_ratio,
            "status": pol_status,
            "seiler_target": "80% easy / 20% hard — the polarized model maximizes adaptation while minimizing overtraining risk.",
        }

    # ── 6. Progressive overload tracking (strength) ──────────────────────────
    overload = None
    vol_weeks = [(ws["week"], ws["volume_lbs"]) for ws in weekly_summary if ws["volume_lbs"] > 0]
    if len(vol_weeks) >= 4:
        mid = len(vol_weeks) // 2
        first_half_vol = _avg([v for _, v in vol_weeks[:mid]])
        second_half_vol = _avg([v for _, v in vol_weeks[mid:]])
        if first_half_vol and second_half_vol:
            delta_pct = round((second_half_vol - first_half_vol) / first_half_vol * 100, 1)
            overload = {
                "first_half_avg_volume_lbs": first_half_vol,
                "second_half_avg_volume_lbs": second_half_vol,
                "delta_pct": delta_pct,
                "trend": "increasing" if delta_pct > 5 else ("decreasing" if delta_pct < -5 else "stable"),
                "note": (
                    "Progressive overload detected."
                    if delta_pct > 5
                    else (
                        "Volume declining — ensure this is intentional (deload/cut)."
                        if delta_pct < -5
                        else "Volume stable — consider adding progressive overload."
                    )
                ),
            }

    # ── 7. Training consistency ──────────────────────────────────────────────
    sessions_per_week = [ws["sessions"] for ws in weekly_summary]
    avg_sessions = _avg(sessions_per_week)
    consistency_pct = round(sum(1 for s in sessions_per_week if s >= 3) / len(sessions_per_week) * 100, 1) if sessions_per_week else 0

    consistency = {
        "avg_sessions_per_week": avg_sessions,
        "weeks_with_3plus_sessions_pct": consistency_pct,
        "total_weeks_analyzed": len(weekly_summary),
        "assessment": (
            "excellent"
            if consistency_pct >= 85
            else ("good" if consistency_pct >= 70 else ("needs_improvement" if consistency_pct >= 50 else "inconsistent"))
        ),
    }

    # ── 8. Zone 2 target tracking ────────────────────────────────────────────
    z2_weekly = [ws["zone2_minutes"] for ws in weekly_summary]
    z2_target = 150
    z2_hit_rate = round(sum(1 for z in z2_weekly if z >= z2_target) / len(z2_weekly) * 100, 1) if z2_weekly else 0

    zone2_status = {
        "avg_weekly_minutes": _avg(z2_weekly),
        "target_minutes": z2_target,
        "weeks_hitting_target_pct": z2_hit_rate,
        "current_week": round(z2_weekly[-1], 1) if z2_weekly else 0,
    }

    # ── 9. Board of Directors ────────────────────────────────────────────────
    bod = []

    if deload_analysis["deload_recommended"]:
        bod.append(
            f"Galpin: {deload_analysis['reason']} Reduce volume by 40-60% this week. Maintain intensity on key lifts but cut sets in half."
        )

    if polarization:
        if polarization["status"] == "too_much_intensity":
            bod.append(
                f"Seiler: Only {polarization['easy_pct']}% of your training is easy. The 80/20 model says you need more Zone 2 and fewer moderate sessions. 'No man's land' (Zone 3) generates fatigue without proportional adaptation."
            )
        elif polarization["status"] == "well_polarized":
            bod.append(
                "Seiler: Training well polarized — strong easy/hard split. This is the highest-evidence approach for long-term development."
            )

    if overload and overload["trend"] == "increasing":
        bod.append(
            f"Galpin: Progressive overload confirmed (+{overload['delta_pct']}% volume). This is the fundamental driver of hypertrophy and strength adaptation."
        )
    elif overload and overload["trend"] == "decreasing":
        bod.append(
            f"Galpin: Volume declining by {abs(overload['delta_pct'])}%. If not intentional (cut/deload), this represents a missed adaptation opportunity."
        )

    if zone2_status["weeks_hitting_target_pct"] < 50:
        bod.append(
            f"Attia: Only hitting Zone 2 target {zone2_status['weeks_hitting_target_pct']}% of weeks. Zone 2 is the highest-ROI longevity training modality — aim for 150 min/week."
        )

    if consistency["assessment"] in ("needs_improvement", "inconsistent"):
        bod.append(
            f"Attia: Consistency ({consistency['avg_sessions_per_week']} sessions/week avg) matters more than intensity. The best program is the one you actually do."
        )

    return {
        "period": {"start_date": start_date, "end_date": end_date, "weeks": len(weekly_summary)},
        "weekly_breakdown": weekly_summary,
        "deload_analysis": deload_analysis,
        "polarization": polarization,
        "progressive_overload": overload,
        "training_consistency": consistency,
        "zone2_status": zone2_status,
        "board_of_directors": bod,
        "methodology": (
            "Weekly training classified into phases: base (moderate consistent), build (>30% high intensity), "
            "peak (>300 min/week), deload (<60 min or <=2 sessions). Polarization per Seiler (80/20 model). "
            "Progressive overload = first-half vs second-half average weekly volume. "
            "Deload trigger: 4+ consecutive loading weeks or 3 weeks of rising volume. "
            "Zone 2 threshold: avg HR <= 70% max HR (Attia/WHO 150 min/week target)."
        ),
        "source": "strava + macrofactor_workouts",
    }


def _get_training_recommendation(args):
    """
    Readiness-based training recommendation. Synthesizes recovery state, training
    load, recent activity history, muscle group recency, and sleep quality into
    a specific workout suggestion with Board of Directors rationale.

    Based on Galpin (training periodization), Huberman (recovery science),
    Attia (longevity training framework), Seiler (polarized training).
    """
    target_date = args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    d7_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d14_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    d3_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Readiness signals ─────────────────────────────────────────────────
    readiness = {}

    # Whoop recovery
    whoop_items = query_source("whoop", d7_start, target_date)
    whoop_sorted = sorted(whoop_items, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)
    if whoop_today:
        readiness["whoop_recovery"] = _sf(whoop_today["recovery_score"])
        readiness["whoop_hrv"] = _sf(whoop_today.get("hrv"))
        readiness["whoop_rhr"] = _sf(whoop_today.get("resting_heart_rate"))
        readiness["whoop_strain_yesterday"] = _sf(whoop_today.get("strain"))

    # Eight Sleep
    es_items = query_source("eightsleep", d3_start, target_date)
    es_sorted = sorted(es_items, key=lambda x: x.get("date", ""), reverse=True)
    es_today = next((s for s in es_sorted if s.get("sleep_score") is not None), None)
    if es_today:
        readiness["sleep_score"] = _sf(es_today["sleep_score"])
        readiness["sleep_efficiency"] = _sf(es_today.get("sleep_efficiency_pct"))
        readiness["sleep_duration"] = _sf(es_today.get("sleep_duration_hours"))
        readiness["deep_pct"] = _sf(es_today.get("deep_pct"))
        readiness["rem_pct"] = _sf(es_today.get("rem_pct"))

    # Garmin Body Battery
    garmin_items = query_source("garmin", d3_start, target_date)
    garmin_sorted = sorted(garmin_items, key=lambda x: x.get("date", ""), reverse=True)
    garmin_today = next((g for g in garmin_sorted if g.get("body_battery_high") is not None), None)
    if garmin_today:
        readiness["body_battery"] = _sf(garmin_today.get("body_battery_high")) or _sf(garmin_today.get("body_battery_end"))
        readiness["garmin_stress"] = _sf(garmin_today.get("avg_stress"))
        readiness["training_readiness_garmin"] = _sf(garmin_today.get("training_readiness"))

    # ── 2. Training load context ─────────────────────────────────────────────
    training_context = {}
    try:
        load_result = _get_training_load({"end_date": target_date})
        if "current_state" in load_result:
            cs = load_result["current_state"]
            training_context["ctl"] = cs.get("ctl_fitness")
            training_context["atl"] = cs.get("atl_fatigue")
            training_context["tsb"] = cs.get("tsb_form")
            training_context["acwr"] = cs.get("acwr")
            training_context["form_status"] = cs.get("form_status")
            training_context["injury_risk"] = cs.get("injury_risk")
    except Exception:
        pass

    # ── 3. Recent activity history ───────────────────────────────────────────
    strava_items = query_source("strava", d14_start, target_date)
    strava_by_date = {}
    for item in strava_items:
        d = item.get("date")
        if d:
            strava_by_date[d] = item

    # Activity patterns over last 7 days
    recent_activities = []
    last_cardio_date = None
    last_strength_date = None
    last_hard_date = None
    consecutive_rest_days = 0
    consecutive_training_days = 0

    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical", "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}

    for i, date in enumerate(sorted(strava_by_date.keys(), reverse=True)):
        if date > target_date:
            continue
        day = strava_by_date[date]
        acts = day.get("activities", [])

        for act in acts:
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            avg_hr = _sf(act.get("average_heartrate"))
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:  # skip <10 min
                continue

            is_cardio = sport in cardio_types
            is_strength = sport in strength_types
            is_hard = avg_hr is not None and avg_hr > max_hr * 0.8

            if is_cardio and (last_cardio_date is None or date > last_cardio_date):
                last_cardio_date = date
            if is_strength and (last_strength_date is None or date > last_strength_date):
                last_strength_date = date
            if is_hard and (last_hard_date is None or date > last_hard_date):
                last_hard_date = date

            recent_activities.append(
                {
                    "date": date,
                    "sport": act.get("sport_type") or act.get("type"),
                    "duration_min": round(elapsed / 60, 1),
                    "avg_hr": avg_hr,
                    "is_hard": is_hard,
                }
            )

    # Consecutive rest/training days
    check_date = datetime.strptime(target_date, "%Y-%m-%d")
    for i in range(7):
        d = (check_date - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        day_data = strava_by_date.get(d, {})
        acts = day_data.get("activities", [])
        real_acts = [a for a in acts if (_sf(a.get("elapsed_time_seconds")) or 0) >= 600]
        if real_acts:
            if i == 0:
                consecutive_training_days = 1
            elif consecutive_training_days > 0:
                consecutive_training_days += 1
            else:
                break
        else:
            if i == 0:
                consecutive_rest_days = 1
            elif consecutive_rest_days > 0:
                consecutive_rest_days += 1
            else:
                break

    # Days since last activities
    def _days_since(d):
        if d is None:
            return None
        return (datetime.strptime(target_date, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days

    days_since_cardio = _days_since(last_cardio_date)
    days_since_strength = _days_since(last_strength_date)
    days_since_hard = _days_since(last_hard_date)

    # ── 4. Muscle group recency from strength data ───────────────────────────
    muscle_last_trained = {}
    mf_workout_items = query_source("macrofactor_workouts", d14_start, target_date)
    for item in mf_workout_items:
        d = item.get("date")
        for workout in item.get("workouts") or []:
            for exercise in workout.get("exercises") or []:
                ename = exercise.get("exercise_name", "")
                cls = classify_exercise(ename)  # noqa: F821
                for mg in cls["muscle_groups"]:
                    if mg not in muscle_last_trained or d > muscle_last_trained[mg]:
                        muscle_last_trained[mg] = d

    muscle_recovery = {}
    for mg, last_date in muscle_last_trained.items():
        days_ago = _days_since(last_date)
        if days_ago is not None:
            status = "fully_recovered" if days_ago >= 3 else ("recovering" if days_ago >= 1 else "just_trained")
            muscle_recovery[mg] = {"last_trained": last_date, "days_ago": days_ago, "status": status}

    # ── 5. Compute readiness tier ────────────────────────────────────────────
    recovery_score = readiness.get("whoop_recovery")
    sleep_score = readiness.get("sleep_score")
    body_battery = readiness.get("body_battery")
    tsb = training_context.get("tsb")
    acwr = training_context.get("acwr")

    # Composite readiness (0-100)
    signals = []
    if recovery_score is not None:
        signals.append(recovery_score)
    if sleep_score is not None:
        signals.append(sleep_score)
    if body_battery is not None:
        signals.append(body_battery)

    composite = _avg(signals) if signals else 50
    tier = "GREEN" if composite >= 67 else ("YELLOW" if composite >= 33 else "RED")

    # Injury risk override
    if acwr is not None and acwr > 1.5:
        tier = "RED"
    # Meeusen 2013: non-functional overreaching risk after 5+ consecutive training days
    if consecutive_training_days >= 5:
        tier = min(tier, "YELLOW") if tier == "GREEN" else tier

    # ── 6. Generate recommendation ───────────────────────────────────────────
    rec = {}

    if tier == "RED" or composite < 30:
        # Low readiness → rest or very easy
        if consecutive_rest_days >= 2:
            rec = {
                "type": "Active Recovery",
                "intensity": "Very Easy",
                "description": "Light walk, mobility work, or gentle yoga. Keep HR below 60% max.",
                "duration_min": "20-30",
                "hr_ceiling": round(max_hr * 0.6),
            }
        else:
            rec = {
                "type": "Full Rest",
                "intensity": "None",
                "description": "Your body needs recovery. Focus on sleep, nutrition, and stress management.",
                "duration_min": "0",
                "hr_ceiling": None,
            }
    elif tier == "YELLOW":
        # Moderate readiness → Zone 2 or easy strength
        if days_since_cardio is not None and days_since_cardio >= 2:
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy",
                "description": "Steady-state aerobic work. Conversational pace. Build mitochondrial density without taxing recovery.",
                "duration_min": "45-60",
                "hr_ceiling": round(max_hr * 0.7),
                "hr_floor": round(max_hr * 0.6),
            }
        elif days_since_strength is not None and days_since_strength >= 2:
            # Find recovered muscle groups
            recovered = [mg for mg, info in muscle_recovery.items() if info["status"] == "fully_recovered"]
            push_ready = any(mg in recovered for mg in ["Chest", "Shoulders", "Triceps"])
            pull_ready = any(mg in recovered for mg in ["Back", "Biceps"])
            legs_ready = any(mg in recovered for mg in ["Quads", "Glutes", "Hamstrings"])

            if legs_ready:
                target = "Lower Body"
                muscles = [mg for mg in ["Quads", "Glutes", "Hamstrings", "Calves"] if mg in recovered]
            elif push_ready:
                target = "Upper Body Push"
                muscles = [mg for mg in ["Chest", "Shoulders", "Triceps"] if mg in recovered]
            elif pull_ready:
                target = "Upper Body Pull"
                muscles = [mg for mg in ["Back", "Biceps"] if mg in recovered]
            else:
                target = "Full Body (Light)"
                muscles = recovered[:4] if recovered else ["General"]

            rec = {
                "type": f"Strength — {target}",
                "intensity": "Moderate",
                "description": f"Moderate loads, controlled tempo. Focus on {', '.join(muscles)}. Stay 2-3 RIR from failure.",
                "duration_min": "45-60",
                "target_muscles": muscles,
                "rpe_range": "6-7",
            }
        else:
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy",
                "description": "Easy aerobic session. You've been active recently — keep it light today.",
                "duration_min": "30-45",
                "hr_ceiling": round(max_hr * 0.7),
            }
    else:
        # GREEN — full capacity available
        if days_since_hard is not None and days_since_hard >= 3 and (tsb is None or tsb > -5):
            # Ready for hard effort
            if days_since_cardio is not None and days_since_cardio >= 2:
                rec = {
                    "type": "High-Intensity Intervals",
                    "intensity": "Hard",
                    "description": "VO2max work: 4-6 intervals of 3-4 minutes at 85-90% max HR with equal rest. This is the highest-ROI session for cardiovascular fitness.",
                    "duration_min": "40-50",
                    "hr_ceiling": round(max_hr * 0.9),
                    "hr_floor": round(max_hr * 0.85),
                }
            else:
                # Find recovered muscle groups for heavy strength
                recovered = [mg for mg, info in muscle_recovery.items() if info["status"] == "fully_recovered"]
                push_ready = any(mg in recovered for mg in ["Chest", "Shoulders", "Triceps"])
                pull_ready = any(mg in recovered for mg in ["Back", "Biceps"])
                legs_ready = any(mg in recovered for mg in ["Quads", "Glutes", "Hamstrings"])

                if legs_ready:
                    target = "Lower Body"
                    muscles = [mg for mg in ["Quads", "Glutes", "Hamstrings", "Calves"] if mg in recovered]
                elif push_ready:
                    target = "Upper Body Push"
                    muscles = [mg for mg in ["Chest", "Shoulders", "Triceps"] if mg in recovered]
                elif pull_ready:
                    target = "Upper Body Pull"
                    muscles = [mg for mg in ["Back", "Biceps"] if mg in recovered]
                else:
                    target = "Full Body"
                    muscles = recovered[:4] if recovered else ["General"]

                rec = {
                    "type": f"Strength — {target}",
                    "intensity": "Hard",
                    "description": f"Heavy compound lifts. Push to 1-2 RIR on working sets. Target: {', '.join(muscles)}.",
                    "duration_min": "60-75",
                    "target_muscles": muscles,
                    "rpe_range": "8-9",
                }
        else:
            # Green but recent hard session or negative TSB → Zone 2
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy-Moderate",
                "description": "Solid Zone 2 session. You're recovered but had a hard effort recently — build aerobic base without adding fatigue.",
                "duration_min": "45-60",
                "hr_ceiling": round(max_hr * 0.7),
                "hr_floor": round(max_hr * 0.6),
            }

    # ── 7. Warnings ──────────────────────────────────────────────────────────
    warnings = []
    if acwr is not None and acwr > 1.3:
        warnings.append(f"⚠️ ACWR is {acwr} — above 1.3 injury threshold. Reduce training load this week.")
    if consecutive_training_days >= 4:
        warnings.append(f"⚠️ {consecutive_training_days} consecutive training days. Consider a rest day soon.")
    if readiness.get("sleep_duration") and readiness["sleep_duration"] < 6:
        warnings.append(
            f"⚠️ Only {readiness['sleep_duration']}h sleep — short sleep impairs muscle protein synthesis and injury risk. Reduce intensity."
        )
    if readiness.get("whoop_hrv") and len([w for w in whoop_items if _sf(w.get("hrv"))]) >= 3:
        hrv_vals = [_sf(w.get("hrv")) for w in whoop_items if _sf(w.get("hrv"))]
        hrv_avg = _avg(hrv_vals)
        if readiness["whoop_hrv"] < hrv_avg * 0.8:
            warnings.append(
                f"⚠️ HRV ({readiness['whoop_hrv']}ms) is {round((1 - readiness['whoop_hrv']/hrv_avg)*100)}% below your 7-day average. Parasympathetic suppression — reduce intensity."
            )
    if readiness.get("garmin_stress") and readiness["garmin_stress"] > 50:
        warnings.append(f"⚠️ Garmin stress score {readiness['garmin_stress']} (elevated). Consider how allostatic load affects recovery.")

    # ── 8. Board of Directors rationale ───────────────────────────────────────
    bod_notes = []
    if tier == "GREEN":
        bod_notes.append("Huberman: Full parasympathetic recovery detected. Sympathetic drive available for high-output work.")
        if rec.get("type", "").startswith("Strength"):
            bod_notes.append(
                "Galpin: Mechanical tension (heavy loads, 1-2 RIR) drives hypertrophy most efficiently when recovery is complete."
            )
        elif "Interval" in rec.get("type", ""):
            bod_notes.append(
                "Attia: VO2max is the single strongest predictor of all-cause mortality. Hard intervals 1-2x/week are the highest-ROI investment."
            )
    elif tier == "YELLOW":
        bod_notes.append("Attia: Zone 2 is the longevity foundation — 150+ min/week builds mitochondrial density without recovery cost.")
        bod_notes.append(
            "Huberman: Moderate training during partial recovery can still stimulate adaptation without digging a deeper hole."
        )
    else:
        bod_notes.append("Walker: Sleep debt is cumulative and cannot be repaid by a single night. Prioritize recovery.")
        bod_notes.append("Galpin: Training in a depleted state converts productive stress into destructive stress.")

    # Zone 2 weekly check
    try:
        z2_result = tool_get_zone2_breakdown({"start_date": d7_start, "end_date": target_date})
        if "summary" in z2_result:
            z2_min = z2_result["summary"].get("total_zone2_minutes", 0)
            z2_target = z2_result["summary"].get("weekly_target_minutes", 150)
            z2_pct = round(z2_min / z2_target * 100) if z2_target > 0 else 0
            if z2_pct < 50:
                bod_notes.append(f"Attia: Only {z2_min} of {z2_target} Zone 2 minutes this week ({z2_pct}%). Prioritize Zone 2 sessions.")
    except Exception:
        pass

    return {
        "date": target_date,
        "readiness_tier": tier,
        "composite_readiness": round(composite, 1),
        "recommendation": rec,
        "warnings": warnings,
        "board_of_directors": bod_notes,
        "readiness_signals": readiness,
        "training_context": {
            "days_since_cardio": days_since_cardio,
            "days_since_strength": days_since_strength,
            "days_since_hard_session": days_since_hard,
            "consecutive_rest_days": consecutive_rest_days,
            "consecutive_training_days": consecutive_training_days,
            "training_load": training_context,
        },
        "muscle_recovery": muscle_recovery,
        "recent_activities_7d": recent_activities[:10],
        "source": "whoop + eightsleep + garmin + strava + macrofactor_workouts",
    }


# ═══════════════════════════════════════════════════════════════════════
# #28 — EXERCISE VARIETY SCORING (Sponsor: Dr. Sarah Chen)
# ═══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# LACTATE THRESHOLD ESTIMATION  (#27)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# EXERCISE EFFICIENCY TRENDING  (#39)
# ══════════════════════════════════════════════════════════════════════════════


def tool_get_acwr_status(args):
    """
    BS-09: Acute:Chronic Workload Ratio status.
    Reads pre-computed acwr fields from the computed_metrics partition.
    Falls back to live computation from Whoop strain if pre-computed record is missing.
    """
    end_date = args.get("date", (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"))
    days_back = int(args.get("days_back", 14))  # how many days of history to return

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # ── Read from computed_metrics (prefer pre-computed) ─────────────────────
    cm_records = query_source(
        "computed_metrics", (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days_back - 1)).strftime("%Y-%m-%d"), end_date
    )

    history = []
    for rec in sorted(cm_records, key=lambda r: r.get("date", ""), reverse=True):
        acwr = _sf(rec.get("acwr"))
        if acwr is None and "acute_load_7d" not in rec:
            continue  # skip records that have no ACWR data at all
        history.append(
            {
                "date": rec.get("date"),
                "acwr": acwr,
                "acute_load_7d": _sf(rec.get("acute_load_7d")),
                "chronic_load_28d": _sf(rec.get("chronic_load_28d")),
                "zone": rec.get("acwr_zone", "unknown"),
                "alert": bool(rec.get("acwr_alert", False)),
                "alert_reason": rec.get("acwr_alert_reason"),
                "method": rec.get("acwr_method", "ewma"),
            }
        )

    if not history:
        return {
            "error": "No ACWR data found in computed_metrics. acwr-compute Lambda may not have run yet for this date range.",
            "hint": 'Run the acwr-compute Lambda manually: aws lambda invoke --function-name acwr-compute --payload \'{"date":"'
            + end_date
            + "\"}' /tmp/out.json",
        }

    latest = history[0]

    # ── Trend (last 7 days with data) ────────────────────────────────────────
    recent_acwrs = [h["acwr"] for h in history if h.get("acwr") is not None][:7]
    trend = None
    if len(recent_acwrs) >= 3:
        if recent_acwrs[0] > recent_acwrs[-1] * 1.05:
            trend = "rising"
        elif recent_acwrs[0] < recent_acwrs[-1] * 0.95:
            trend = "falling"
        else:
            trend = "stable"

    # ── Alert count ──────────────────────────────────────────────────────────
    alerts_7d = sum(1 for h in history[:7] if h.get("alert"))

    # ── Board coaching note ──────────────────────────────────────────────────
    zone = latest.get("zone", "unknown")
    acwr = latest.get("acwr")
    coaching = None
    if zone == "danger":
        coaching = "Attia + Galpin: ACWR above 1.5 is the strongest predictor of non-contact injury in the next 7 days. Rest is not optional this week."
    elif zone == "caution":
        coaching = "Galpin: ACWR in the caution zone (1.3-1.5). Reduce volume by 30-40%. Maintain intensity on 1-2 key sessions; cut accessory work."
    elif zone == "safe":
        coaching = "Galpin: ACWR in the optimal window (0.8-1.3). Current load progression is appropriate for continued adaptation."
    elif zone == "detraining":
        coaching = "Attia: Chronic load exceeds acute — you are doing less than your body is adapted to. Increase training frequency or duration this week."

    return {
        "date": latest.get("date"),
        "acwr": acwr,
        "zone": zone,
        "alert": latest.get("alert"),
        "alert_reason": latest.get("alert_reason"),
        "acute_load_7d": latest.get("acute_load_7d"),
        "chronic_load_28d": latest.get("chronic_load_28d"),
        "trend_7d": trend,
        "alerts_last_7d": alerts_7d,
        "coaching": coaching,
        "history": history,
        "method": latest.get("method", "ewma"),
        "interpretation": (
            "ACWR = EWMA(7d) Whoop strain / EWMA(28d) Whoop strain (#543 — exponentially-"
            "weighted, not flat rolling means). Zones (population-derived, Gabbett 2016 / "
            "Hulin 2014): safe 0.8-1.3, above 1.3 elevated injury risk, below 0.8 detraining."
        ),
        "_coupling_caveat": (
            "ACWR is a coupled ratio — the acute load (numerator) is a mathematical component "
            "of the chronic load (denominator), so they move together by construction (Lolli "
            "et al. 2019). A directional recovery signal, not a precise injury predictor."
        ),
        "_proxy_note": (
            "Whoop strain is a cardiac stress measure (heart rate-based), not a mechanical load "
            "measure. Gabbett thresholds were validated on team sport athletes using session RPE. "
            "Heavy strength training at low cardiac output may not register as high acute load. "
            "Use ACWR as a directional recovery signal, not a precise injury predictor."
        ),
        "_disclaimer": "For personal training guidance only. Not medical advice.",
    }


def tool_get_training(args):
    """Unified training intelligence dispatcher.
    Board vote 11-0: training_load, training_recommendation, training_periodization
    added to nightly warmer in same commit (all multi-source, expensive on-demand).
    """
    VALID_VIEWS = {
        "load": _get_training_load,
        "periodization": _get_training_periodization,
        "recommendation": _get_training_recommendation,
    }
    view = (args.get("view") or "load").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'load' for CTL/ATL/TSB fitness-fatigue model, 'periodization' for mesocycle analysis, 'recommendation' for today's workout suggestion.",
        }
    return VALID_VIEWS[view](args)
