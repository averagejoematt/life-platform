#!/usr/bin/env python3
"""
apply_features_6_7_8.py — Apply all three feature patches to source files.

Modifies:
  - mcp_server.py: 3 new tool functions + TOOLS entries
  - lambdas/strava_lambda.py: HR stream fetching for recovery metrics
  - lambdas/eightsleep_lambda.py: Temperature data from intervals API

Run: python3 patches/apply_features_6_7_8.py
Then: bash deploy/deploy_features_6_7_8.sh
"""
import os
import sys
import re

BASE = os.path.expanduser("~/Documents/Claude/life-platform")
os.chdir(BASE)


def read(path):
    with open(path, "r") as f:
        return f.read()


def write(path, content):
    with open(path, "w") as f:
        f.write(content)
    print(f"  ✅ Written: {path}")


def backup(path):
    import shutil
    bak = path + ".bak.f678"
    shutil.copy2(path, bak)
    print(f"  📦 Backup: {bak}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. PATCH MCP SERVER — 3 new tools
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ Patching mcp_server.py ═══")
backup("mcp_server.py")
mcp = read("mcp_server.py")

# ── Tool function: get_training_recommendation ────────────────────────────────
TOOL_TRAINING_REC = '''

# ── Feature #7: Readiness-Based Training Recommendation (v2.35.0) ────────────

def tool_get_training_recommendation(args):
    """
    Readiness-based training recommendation. Synthesizes recovery state, training
    load, recent activity history, muscle group recency, and sleep quality into
    a specific workout suggestion with Board of Directors rationale.
    """
    target_date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d14_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    d3_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Readiness signals ─────────────────────────────────────────────────
    readiness = {}
    whoop_items = query_source("whoop", d7_start, target_date)
    whoop_sorted = sorted(whoop_items, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)
    if whoop_today:
        readiness["whoop_recovery"] = _sf(whoop_today["recovery_score"])
        readiness["whoop_hrv"] = _sf(whoop_today.get("hrv"))
        readiness["whoop_rhr"] = _sf(whoop_today.get("resting_heart_rate"))

    es_items = query_source("eightsleep", d3_start, target_date)
    es_sorted = sorted(es_items, key=lambda x: x.get("date", ""), reverse=True)
    es_today = next((s for s in es_sorted if s.get("sleep_score") is not None), None)
    if es_today:
        readiness["sleep_score"] = _sf(es_today["sleep_score"])
        readiness["sleep_efficiency"] = _sf(es_today.get("sleep_efficiency_pct"))
        readiness["sleep_duration"] = _sf(es_today.get("sleep_duration_hours"))
        readiness["deep_pct"] = _sf(es_today.get("deep_pct"))

    garmin_items = query_source("garmin", d3_start, target_date)
    garmin_sorted = sorted(garmin_items, key=lambda x: x.get("date", ""), reverse=True)
    garmin_today = next((g for g in garmin_sorted if g.get("body_battery_high") is not None), None)
    if garmin_today:
        readiness["body_battery"] = _sf(garmin_today.get("body_battery_high")) or _sf(garmin_today.get("body_battery_end"))
        readiness["garmin_stress"] = _sf(garmin_today.get("avg_stress"))

    # ── 2. Training load ─────────────────────────────────────────────────────
    training_context = {}
    try:
        load_result = tool_get_training_load({"end_date": target_date})
        if "current_state" in load_result:
            cs = load_result["current_state"]
            training_context = {
                "ctl": cs.get("ctl_fitness"), "atl": cs.get("atl_fatigue"),
                "tsb": cs.get("tsb_form"), "acwr": cs.get("acwr"),
                "form_status": cs.get("form_status"), "injury_risk": cs.get("injury_risk"),
            }
    except Exception:
        pass

    # ── 3. Recent activity history ───────────────────────────────────────────
    strava_items = query_source("strava", d14_start, target_date)
    strava_by_date = {item.get("date"): item for item in strava_items if item.get("date")}

    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical", "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}
    recent_activities = []
    last_cardio_date = last_strength_date = last_hard_date = None

    for date in sorted(strava_by_date.keys(), reverse=True):
        if date > target_date:
            continue
        for act in strava_by_date[date].get("activities", []):
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            avg_hr = _sf(act.get("average_heartrate"))
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:
                continue
            is_hard = avg_hr is not None and avg_hr > max_hr * 0.8
            if sport in cardio_types and (last_cardio_date is None or date > last_cardio_date):
                last_cardio_date = date
            if sport in strength_types and (last_strength_date is None or date > last_strength_date):
                last_strength_date = date
            if is_hard and (last_hard_date is None or date > last_hard_date):
                last_hard_date = date
            recent_activities.append({
                "date": date, "sport": act.get("sport_type") or act.get("type"),
                "duration_min": round(elapsed / 60, 1), "avg_hr": avg_hr, "is_hard": is_hard,
            })

    # Consecutive training/rest days
    consecutive_rest = consecutive_train = 0
    check = datetime.strptime(target_date, "%Y-%m-%d")
    for i in range(7):
        d = (check - timedelta(days=i+1)).strftime("%Y-%m-%d")
        acts = [a for a in strava_by_date.get(d, {}).get("activities", [])
                if (_sf(a.get("elapsed_time_seconds")) or 0) >= 600]
        if acts:
            if i == 0: consecutive_train = 1
            elif consecutive_train > 0: consecutive_train += 1
            else: break
        else:
            if i == 0: consecutive_rest = 1
            elif consecutive_rest > 0: consecutive_rest += 1
            else: break

    def _days_since(d):
        if d is None: return None
        return (datetime.strptime(target_date, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days

    days_since_cardio = _days_since(last_cardio_date)
    days_since_strength = _days_since(last_strength_date)
    days_since_hard = _days_since(last_hard_date)

    # ── 4. Muscle group recency ──────────────────────────────────────────────
    muscle_last_trained = {}
    mf_items = query_source("macrofactor_workouts", d14_start, target_date)
    for item in mf_items:
        d = item.get("date")
        for wk in (item.get("workouts") or []):
            for ex in (wk.get("exercises") or []):
                cls = classify_exercise(ex.get("exercise_name", ""))
                for mg in cls["muscle_groups"]:
                    if mg not in muscle_last_trained or d > muscle_last_trained[mg]:
                        muscle_last_trained[mg] = d

    muscle_recovery = {}
    for mg, ld in muscle_last_trained.items():
        da = _days_since(ld)
        if da is not None:
            muscle_recovery[mg] = {
                "last_trained": ld, "days_ago": da,
                "status": "fully_recovered" if da >= 3 else ("recovering" if da >= 1 else "just_trained"),
            }

    # ── 5. Readiness tier ────────────────────────────────────────────────────
    signals = [v for v in [readiness.get("whoop_recovery"), readiness.get("sleep_score"),
                           readiness.get("body_battery")] if v is not None]
    composite = _avg(signals) if signals else 50
    tier = "GREEN" if composite >= 67 else ("YELLOW" if composite >= 33 else "RED")

    acwr = training_context.get("acwr")
    if acwr is not None and float(acwr) > 1.5:
        tier = "RED"
    if consecutive_train >= 5 and tier == "GREEN":
        tier = "YELLOW"

    # ── 6. Generate recommendation ───────────────────────────────────────────
    tsb = training_context.get("tsb")
    recovered = [mg for mg, info in muscle_recovery.items() if info["status"] == "fully_recovered"]
    push_ready = any(mg in recovered for mg in ["Chest", "Shoulders", "Triceps"])
    pull_ready = any(mg in recovered for mg in ["Back", "Biceps"])
    legs_ready = any(mg in recovered for mg in ["Quads", "Glutes", "Hamstrings"])

    def _strength_rec(intensity, rpe):
        if legs_ready:
            target, muscles = "Lower Body", [m for m in ["Quads","Glutes","Hamstrings","Calves"] if m in recovered]
        elif push_ready:
            target, muscles = "Upper Body Push", [m for m in ["Chest","Shoulders","Triceps"] if m in recovered]
        elif pull_ready:
            target, muscles = "Upper Body Pull", [m for m in ["Back","Biceps"] if m in recovered]
        else:
            target, muscles = "Full Body", recovered[:4] if recovered else ["General"]
        return {
            "type": f"Strength — {target}", "intensity": intensity,
            "description": f"Target: {', '.join(muscles)}. RPE {rpe}.",
            "duration_min": "45-60" if intensity == "Moderate" else "60-75",
            "target_muscles": muscles, "rpe_range": rpe,
        }

    if tier == "RED" or composite < 30:
        if consecutive_rest >= 2:
            rec = {"type": "Active Recovery", "intensity": "Very Easy",
                   "description": "Light walk, mobility, or gentle yoga. HR below 60% max.",
                   "duration_min": "20-30", "hr_ceiling": round(max_hr * 0.6)}
        else:
            rec = {"type": "Full Rest", "intensity": "None",
                   "description": "Recovery day. Focus on sleep, nutrition, stress management.",
                   "duration_min": "0"}
    elif tier == "YELLOW":
        if days_since_cardio is not None and days_since_cardio >= 2:
            rec = {"type": "Zone 2 Cardio", "intensity": "Easy",
                   "description": "Steady-state aerobic. Conversational pace. Build mitochondrial density.",
                   "duration_min": "45-60", "hr_ceiling": round(max_hr * 0.7), "hr_floor": round(max_hr * 0.6)}
        elif days_since_strength is not None and days_since_strength >= 2:
            rec = _strength_rec("Moderate", "6-7")
        else:
            rec = {"type": "Zone 2 Cardio", "intensity": "Easy",
                   "description": "Easy aerobic session. Keep it light today.",
                   "duration_min": "30-45", "hr_ceiling": round(max_hr * 0.7)}
    else:  # GREEN
        if days_since_hard is not None and days_since_hard >= 3 and (tsb is None or float(tsb) > -5):
            if days_since_cardio is not None and days_since_cardio >= 2:
                rec = {"type": "High-Intensity Intervals", "intensity": "Hard",
                       "description": "VO2max work: 4-6 x 3-4 min at 85-90% max HR, equal rest. Highest-ROI cardio session.",
                       "duration_min": "40-50", "hr_ceiling": round(max_hr * 0.9), "hr_floor": round(max_hr * 0.85)}
            else:
                rec = _strength_rec("Hard", "8-9")
        else:
            rec = {"type": "Zone 2 Cardio", "intensity": "Easy-Moderate",
                   "description": "Zone 2 base building. Recent hard effort — don't add fatigue.",
                   "duration_min": "45-60", "hr_ceiling": round(max_hr * 0.7), "hr_floor": round(max_hr * 0.6)}

    # ── 7. Warnings ──────────────────────────────────────────────────────────
    warnings = []
    if acwr is not None and float(acwr) > 1.3:
        warnings.append(f"\\u26a0\\ufe0f ACWR {acwr} > 1.3 injury threshold. Reduce load this week.")
    if consecutive_train >= 4:
        warnings.append(f"\\u26a0\\ufe0f {consecutive_train} consecutive training days. Consider rest.")
    if readiness.get("sleep_duration") and readiness["sleep_duration"] < 6:
        warnings.append(f"\\u26a0\\ufe0f Only {readiness['sleep_duration']}h sleep. Reduce intensity.")
    if readiness.get("garmin_stress") and readiness["garmin_stress"] > 50:
        warnings.append(f"\\u26a0\\ufe0f Garmin stress {readiness['garmin_stress']} (elevated).")

    # ── 8. Board of Directors ────────────────────────────────────────────────
    bod = []
    if tier == "GREEN":
        bod.append("Huberman: Full parasympathetic recovery. Sympathetic drive available for high-output work.")
        if "Strength" in rec.get("type", ""):
            bod.append("Galpin: Mechanical tension at 1-2 RIR drives hypertrophy most efficiently when recovered.")
        elif "Interval" in rec.get("type", ""):
            bod.append("Attia: VO2max is the strongest predictor of all-cause mortality. Hard intervals 1-2x/week = highest ROI.")
    elif tier == "YELLOW":
        bod.append("Attia: Zone 2 = longevity foundation. 150+ min/week builds mitochondrial density without recovery cost.")
    else:
        bod.append("Walker: Sleep debt is cumulative. Galpin: Training while depleted converts productive stress into destructive stress.")

    # Zone 2 weekly context
    try:
        z2 = tool_get_zone2_breakdown({"start_date": d7_start, "end_date": target_date})
        if "summary" in z2:
            z2_min = z2["summary"].get("total_zone2_minutes", 0)
            z2_tgt = z2["summary"].get("weekly_target_minutes", 150)
            if z2_tgt > 0 and z2_min / z2_tgt < 0.5:
                bod.append(f"Attia: Only {z2_min}/{z2_tgt} Zone 2 min this week. Prioritize Zone 2.")
    except Exception:
        pass

    return {
        "date": target_date, "readiness_tier": tier, "composite_readiness": round(composite, 1),
        "recommendation": rec, "warnings": warnings, "board_of_directors": bod,
        "readiness_signals": readiness,
        "training_context": {
            "days_since_cardio": days_since_cardio, "days_since_strength": days_since_strength,
            "days_since_hard_session": days_since_hard,
            "consecutive_rest_days": consecutive_rest, "consecutive_training_days": consecutive_train,
            "training_load": training_context,
        },
        "muscle_recovery": muscle_recovery, "recent_activities_7d": recent_activities[:10],
        "source": "whoop + eightsleep + garmin + strava + macrofactor_workouts",
    }
'''

# ── Tool function: get_hr_recovery_trend ──────────────────────────────────────
TOOL_HR_RECOVERY = '''

# ── Feature #8: Heart Rate Recovery Tracking (v2.35.0) ───────────────────────

def tool_get_hr_recovery_trend(args):
    """
    Heart rate recovery tracker. Extracts HR recovery metrics from Strava activities
    (stored by enhanced ingestion), trends over time, classifies against clinical
    thresholds. HR Recovery = strongest exercise-derived mortality predictor.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))
    sport_filter = (args.get("sport_type") or "").strip().lower()
    cooldown_only = args.get("cooldown_only", False)

    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    records = []
    for item in strava_items:
        date = item.get("date")
        for act in (item.get("activities") or []):
            hr_rec = act.get("hr_recovery")
            if not hr_rec or not isinstance(hr_rec, dict):
                continue
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport_filter and sport_filter not in sport.replace(" ", ""):
                continue
            has_cooldown = hr_rec.get("has_cooldown", False)
            if cooldown_only and not has_cooldown:
                continue
            peak = _sf(hr_rec.get("hr_peak"))
            recovery_60s = _sf(hr_rec.get("hr_recovery_60s"))
            recovery_intra = _sf(hr_rec.get("hr_recovery_intra"))
            best_recovery = recovery_60s or recovery_intra
            if peak is None or best_recovery is None:
                continue
            classification = ("excellent" if best_recovery >= 25 else "good" if best_recovery >= 18
                              else "average" if best_recovery >= 12 else "below_average")
            records.append({
                "date": date, "sport_type": act.get("sport_type") or act.get("type"),
                "activity_name": act.get("name", ""),
                "duration_min": round((_sf(act.get("elapsed_time_seconds")) or 0) / 60, 1),
                "hr_peak": peak, "hr_peak_pct_max": round(peak / max_hr * 100, 1),
                "hr_end_60s": _sf(hr_rec.get("hr_end_60s")),
                "hr_recovery_intra": recovery_intra, "hr_recovery_60s": recovery_60s,
                "hr_recovery_120s": _sf(hr_rec.get("hr_recovery_120s")),
                "has_cooldown": has_cooldown, "best_recovery_bpm": best_recovery,
                "classification": classification,
            })

    if not records:
        return {
            "error": "No activities with HR recovery data. Requires Strava ingestion v2.35.0+.",
            "start_date": start_date, "end_date": end_date,
            "tip": "HR recovery metrics are computed from HR streams during Strava ingestion. New activities after deployment will have this data.",
        }

    records.sort(key=lambda r: r["date"])
    total = len(records)

    # Trend: first half vs second half
    mid = total // 2
    first_avg = _avg([r["best_recovery_bpm"] for r in records[:mid]]) if mid > 0 else None
    second_avg = _avg([r["best_recovery_bpm"] for r in records[mid:]]) if mid > 0 else None
    trend_delta = round(second_avg - first_avg, 1) if first_avg and second_avg else None
    trend_dir = ("improving" if trend_delta and trend_delta > 2 else
                 "declining" if trend_delta and trend_delta < -2 else "stable")

    # Pearson: date vs recovery
    if len(records) >= 5:
        base = datetime.strptime(records[0]["date"], "%Y-%m-%d")
        xs = [(datetime.strptime(r["date"], "%Y-%m-%d") - base).days for r in records]
        ys = [r["best_recovery_bpm"] for r in records]
        r_val = pearson_r(xs, ys)
    else:
        r_val = None

    # Sport breakdown
    by_sport = {}
    for r in records:
        s = r["sport_type"] or "Unknown"
        by_sport.setdefault(s, []).append(r["best_recovery_bpm"])
    sport_summary = {s: {"activities": len(v), "avg_recovery_bpm": _avg(v)} for s, v in by_sport.items()}

    # Classification distribution
    dist = {"excellent": 0, "good": 0, "average": 0, "below_average": 0}
    for r in records:
        dist[r["classification"]] += 1

    # Clinical assessment
    overall_avg = _avg([r["best_recovery_bpm"] for r in records])
    if overall_avg and overall_avg >= 25: clinical = "Excellent autonomic function. Strong parasympathetic reactivation."
    elif overall_avg and overall_avg >= 18: clinical = "Good HR recovery. Healthy autonomic balance."
    elif overall_avg and overall_avg >= 12: clinical = "Average. Zone 2 training and stress management will improve parasympathetic tone."
    elif overall_avg: clinical = "Below average (<12 bpm). Clinical flag per Cole et al. (NEJM). Discuss with physician."
    else: clinical = "Insufficient data."

    cooldown_recs = [r for r in records if r["has_cooldown"]]
    no_cool = [r for r in records if not r["has_cooldown"]]

    bod = []
    if trend_dir == "improving":
        bod.append(f"Attia: HR recovery improving +{trend_delta} bpm — cardiovascular fitness trending in the right direction.")
    elif trend_dir == "declining":
        bod.append(f"Huberman: HR recovery declining {trend_delta} bpm — consider overtraining, sleep debt, or chronic stress.")
    if cooldown_recs and no_cool:
        bod.append(f"Galpin: {len(cooldown_recs)}/{total} activities include cooldown. 5-min easy cooldown improves recovery AND data quality.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_activities": total, "overall_avg_recovery_bpm": overall_avg, "clinical_assessment": clinical,
        "trend": {"direction": trend_dir, "delta_bpm": trend_delta, "first_half_avg": first_avg,
                  "second_half_avg": second_avg, "pearson_r": r_val},
        "classification_distribution": dist,
        "classification_pct": {k: round(v/total*100, 1) for k, v in dist.items()},
        "by_sport_type": sport_summary,
        "cooldown_analysis": {
            "with_cooldown": len(cooldown_recs), "without_cooldown": len(no_cool),
            "avg_recovery_with": _avg([r["best_recovery_bpm"] for r in cooldown_recs]),
            "avg_recovery_without": _avg([r["best_recovery_bpm"] for r in no_cool]),
        },
        "best_5": sorted(records, key=lambda r: r["best_recovery_bpm"], reverse=True)[:5],
        "worst_5": sorted(records, key=lambda r: r["best_recovery_bpm"])[:5],
        "board_of_directors": bod,
        "methodology": "HR recovery from Strava HR streams. Peak=30s rolling max. Recovery=peak minus HR at peak+60s (or last 60s avg). Thresholds: >25 excellent, 18-25 good, 12-18 average, <12 abnormal (Cole et al. NEJM 1999).",
        "source": "strava (HR streams)",
    }
'''

# ── Tool function: get_sleep_environment_analysis ─────────────────────────────
TOOL_SLEEP_ENV = '''

# ── Feature #6: Sleep Environment Optimization (v2.35.0) ─────────────────────

def tool_get_sleep_environment_analysis(args):
    """
    Sleep environment optimization. Correlates Eight Sleep bed temperature
    settings with sleep outcomes. Huberman: core body temp is the #1 sleep trigger.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))

    es_items = query_source("eightsleep", start_date, end_date)
    if not es_items:
        return {"error": "No Eight Sleep data for range.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hours", "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Onset Latency",      "lower_is_better"),
        ("hrv_avg",              "HRV",                "higher_is_better"),
    ]

    records = []
    no_temp = 0
    for item in es_items:
        bed_temp_f = _sf(item.get("bed_temp_f"))
        bed_temp_c = _sf(item.get("bed_temp_c"))
        temp_level = _sf(item.get("temp_level_avg"))
        if bed_temp_c and not bed_temp_f:
            bed_temp_f = round(bed_temp_c * 9/5 + 32, 1)
        if bed_temp_f and not bed_temp_c:
            bed_temp_c = round((bed_temp_f - 32) * 5/9, 1)
        if bed_temp_f is None and temp_level is None:
            no_temp += 1
            continue
        eff = _sf(item.get("sleep_efficiency_pct"))
        if eff is None and _sf(item.get("sleep_score")) is None:
            continue
        records.append({
            "date": item.get("date"), "bed_temp_f": bed_temp_f, "bed_temp_c": bed_temp_c,
            "temp_level": temp_level, "room_temp_f": _sf(item.get("room_temp_f")),
            "sleep_efficiency_pct": eff, "deep_pct": _sf(item.get("deep_pct")),
            "rem_pct": _sf(item.get("rem_pct")), "sleep_score": _sf(item.get("sleep_score")),
            "sleep_duration_hours": _sf(item.get("sleep_duration_hours")),
            "time_to_sleep_min": _sf(item.get("time_to_sleep_min")),
            "hrv_avg": _sf(item.get("hrv_avg")),
        })

    if not records:
        return {
            "error": f"No nights with temperature data ({no_temp} checked). Requires Eight Sleep ingestion v2.35.0+.",
            "tip": "Temperature data is fetched from the Eight Sleep intervals API. Deploy and wait for new nights.",
        }

    has_temp_f = sum(1 for r in records if r["bed_temp_f"] is not None)
    has_level = sum(1 for r in records if r["temp_level"] is not None)

    # Bucket analysis — bed temp °F
    bucket_data = {}
    if has_temp_f >= len(records) * 0.3:
        BUCKETS = [
            ("below_64F", "< 64°F", lambda t: t < 64), ("64_66F", "64-66°F", lambda t: 64 <= t < 66),
            ("66_68F", "66-68°F", lambda t: 66 <= t < 68), ("68_70F", "68-70°F", lambda t: 68 <= t < 70),
            ("70_72F", "70-72°F", lambda t: 70 <= t < 72), ("above_72F", "> 72°F", lambda t: t >= 72),
        ]
        for bk, label, cond in BUCKETS:
            br = [r for r in records if r["bed_temp_f"] is not None and cond(r["bed_temp_f"])]
            if not br: continue
            bucket_data[bk] = {"label": label, "nights": len(br),
                               "avg_temp_f": _avg([r["bed_temp_f"] for r in br]), "metrics": {}}
            for field, ml, _ in SLEEP_METRICS:
                vals = [r[field] for r in br if r[field] is not None]
                if vals:
                    bucket_data[bk]["metrics"][field] = {"label": ml, "avg": _avg(vals), "n": len(vals)}

    # Bucket analysis — temp level
    level_data = {}
    if has_level >= len(records) * 0.3:
        LBUCKETS = [
            ("very_cool", "Very Cool (-10 to -6)", lambda l: l <= -6),
            ("cool", "Cool (-5 to -2)", lambda l: -5 <= l <= -2),
            ("neutral", "Neutral (-1 to +1)", lambda l: -1 <= l <= 1),
            ("warm", "Warm (+2 to +5)", lambda l: 2 <= l <= 5),
            ("very_warm", "Very Warm (+6 to +10)", lambda l: l >= 6),
        ]
        for bk, label, cond in LBUCKETS:
            br = [r for r in records if r["temp_level"] is not None and cond(r["temp_level"])]
            if not br: continue
            level_data[bk] = {"label": label, "nights": len(br),
                              "avg_level": _avg([r["temp_level"] for r in br]), "metrics": {}}
            for field, ml, _ in SLEEP_METRICS:
                vals = [r[field] for r in br if r[field] is not None]
                if vals:
                    level_data[bk]["metrics"][field] = {"label": ml, "avg": _avg(vals), "n": len(vals)}

    # Pearson correlations
    temp_corr = {}
    if has_temp_f >= 5:
        tr = [r for r in records if r["bed_temp_f"] is not None]
        for field, label, direction in SLEEP_METRICS:
            xs = [r["bed_temp_f"] for r in tr if r[field] is not None]
            ys = [r[field] for r in tr if r[field] is not None]
            rv = pearson_r(xs, ys) if len(xs) >= 5 else None
            if rv is not None:
                impact = ("cooler_better" if (rv < -0.15 and direction == "higher_is_better") or (rv > 0.15 and direction == "lower_is_better")
                          else "warmer_better" if (rv > 0.15 and direction == "higher_is_better") or (rv < -0.15 and direction == "lower_is_better")
                          else "no_effect")
                temp_corr[field] = {"label": label, "pearson_r": rv, "n": len(xs), "impact": impact}

    # Optimal temp
    optimal = {}
    for bk, bv in bucket_data.items():
        eff = (bv.get("metrics", {}).get("sleep_efficiency_pct") or {}).get("avg", 0)
        if eff > optimal.get("best_eff", 0) and bv["nights"] >= 3:
            optimal = {"best_eff": eff, "bucket": bv["label"], "nights": bv["nights"]}

    # Board of Directors
    bod = ["Huberman: Core body temp drop is the #1 physiological sleep trigger. Cool bedroom to 65-68°F."]
    ci = temp_corr.get("sleep_efficiency_pct", {}).get("impact")
    if ci == "cooler_better":
        bod.append(f"Your data confirms: cooler = better efficiency (r={temp_corr['sleep_efficiency_pct']['pearson_r']}).")
    elif ci == "warmer_better":
        bod.append("Your data shows warmer = better. May indicate your baseline is already quite cool.")
    if optimal.get("bucket"):
        bod.append(f"Attia: Your optimal zone for efficiency is {optimal['bucket']} ({optimal['nights']} nights).")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "nights_with_temp": len(records), "nights_without_temp": no_temp,
        "temperature_summary": {
            "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in records if r["bed_temp_f"]]),
            "avg_bed_temp_c": _avg([r["bed_temp_c"] for r in records if r["bed_temp_c"]]),
            "avg_temp_level": _avg([r["temp_level"] for r in records if r["temp_level"]]),
        },
        "optimal_temperature": optimal if optimal.get("bucket") else None,
        "bucket_analysis_bed_temp": bucket_data or None,
        "bucket_analysis_temp_level": level_data or None,
        "correlations": temp_corr or None,
        "board_of_directors": bod,
        "source": "eightsleep",
    }
'''

# ── Insert all three tools into mcp_server.py ────────────────────────────────

# Find insertion point: before TOOLS = {
insert_marker = "\nTOOLS = {"
idx = mcp.find(insert_marker)
if idx == -1:
    print("ERROR: Could not find TOOLS = { in mcp_server.py")
    sys.exit(1)

mcp = mcp[:idx] + TOOL_TRAINING_REC + TOOL_HR_RECOVERY + TOOL_SLEEP_ENV + mcp[idx:]
print("  ✅ Inserted 3 tool functions")

# ── Add TOOLS dict entries ───────────────────────────────────────────────────
# Find the closing of the TOOLS dict — insert before the final closing }
# Strategy: find "get_health_trajectory" entry, go to its end, add our entries

TOOLS_ENTRIES = '''
    "get_training_recommendation": {
        "fn": tool_get_training_recommendation,
        "schema": {
            "name": "get_training_recommendation",
            "description": (
                "Readiness-based training recommendation. Synthesizes Whoop recovery, Eight Sleep quality, "
                "Garmin Body Battery, training load (CTL/ATL/TSB), recent activity history, and muscle group "
                "recency into a specific workout suggestion: type (Zone 2, intervals, strength upper/lower, "
                "active recovery, rest), intensity, duration, HR targets, and muscle groups. Board of Directors "
                "rationale. Warns about injury risk (ACWR), consecutive training, sleep debt. "
                "Use for: 'what should I do today?', 'workout recommendation', 'should I train?', "
                "'readiness-based training', 'what workout today?', 'am I recovered for a hard workout?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_hr_recovery_trend": {
        "fn": tool_get_hr_recovery_trend,
        "schema": {
            "name": "get_hr_recovery_trend",
            "description": (
                "Heart rate recovery tracker — strongest exercise-derived mortality predictor (Cole NEJM). "
                "Extracts post-peak HR recovery from Strava activity streams, trends over time, classifies "
                "against clinical thresholds (>25 excellent, 18-25 good, 12-18 average, <12 abnormal). "
                "Sport-type breakdown, cooldown vs no-cooldown comparison, best/worst sessions, fitness trajectory. "
                "Use for: 'HR recovery trend', 'heart rate recovery', 'am I getting fitter?', "
                "'cardiovascular fitness', 'autonomic function', 'post-exercise HR drop'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 180d ago)."},
                    "end_date": {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "sport_type": {"type": "string", "description": "Filter by sport (e.g. 'Run'). Case-insensitive."},
                    "cooldown_only": {"type": "boolean", "description": "Only activities with detected cooldown. Default: false."},
                },
                "required": [],
            },
        },
    },
    "get_sleep_environment_analysis": {
        "fn": tool_get_sleep_environment_analysis,
        "schema": {
            "name": "get_sleep_environment_analysis",
            "description": (
                "Sleep environment optimization. Correlates Eight Sleep bed temperature (°F/°C, heating/cooling level) "
                "with sleep outcomes (efficiency, deep %, REM %, score, latency, HRV). Bucket analysis by temp range, "
                "Pearson correlations, optimal temperature recommendation. "
                "Huberman: core body temp = #1 sleep trigger. Walker: sleeping too warm = most common sleep disruptor. "
                "Use for: 'optimal bed temperature', 'does temperature affect sleep?', 'Eight Sleep temperature', "
                "'sleep environment', 'bed cooling', 'what temp should I set my Eight Sleep?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 180d ago)."},
                    "end_date": {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },'''

# Find the last entry in TOOLS and add after it
# Look for the closing of get_health_trajectory entry
marker = '"get_health_trajectory":'
midx = mcp.find(marker)
if midx == -1:
    print("ERROR: Could not find get_health_trajectory in TOOLS")
    sys.exit(1)

# Find the end of this entry (track braces)
depth = 0
found = False
end_idx = midx
for i in range(midx, len(mcp)):
    if mcp[i] == '{':
        depth += 1
        found = True
    elif mcp[i] == '}':
        depth -= 1
        if found and depth == 0:
            end_idx = i + 1
            break

# Add comma after the entry if needed and insert
if mcp[end_idx:end_idx+1] == ',':
    insert_at = end_idx + 1
else:
    mcp = mcp[:end_idx] + ',' + mcp[end_idx:]
    insert_at = end_idx + 1

mcp = mcp[:insert_at] + TOOLS_ENTRIES + mcp[insert_at:]
print("  ✅ Inserted 3 TOOLS entries")

# Update version in handle_initialize
mcp = mcp.replace('"version": "2.26.0"', '"version": "2.35.0"')

write("mcp_server.py", mcp)

# Verify tool count
tool_count = mcp.count('"fn":')
print(f"  Tool count: {tool_count} (expected: 80)")


# ══════════════════════════════════════════════════════════════════════════════
# 2. PATCH STRAVA LAMBDA — HR stream fetching
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ Patching lambdas/strava_lambda.py ═══")
backup("lambdas/strava_lambda.py")
strava = read("lambdas/strava_lambda.py")

# Insert fetch_activity_streams after fetch_activity_zones (find the return after that function)
STRAVA_STREAM_FN = '''

def fetch_activity_streams(strava_id: str, secret: dict) -> tuple:
    """
    Fetch HR + time streams for an activity. Compute HR recovery metrics.
    Returns (hr_recovery_dict, secret).
    """
    try:
        url = f"https://www.strava.com/api/v3/activities/{strava_id}/streams?keys=heartrate,time&key_type=time"
        data, secret = strava_get(url, secret)

        hr_data = time_data = None
        for stream in data:
            if stream.get("type") == "heartrate":
                hr_data = stream.get("data", [])
            elif stream.get("type") == "time":
                time_data = stream.get("data", [])

        if not hr_data or not time_data or len(hr_data) < 60:
            return {}, secret

        # Rolling 30s average for peak detection
        rolling = []
        for i in range(len(hr_data)):
            start_idx = i
            while start_idx > 0 and time_data[i] - time_data[start_idx] < 30:
                start_idx -= 1
            window = hr_data[start_idx:i+1]
            rolling.append(sum(window) / len(window) if window else hr_data[i])

        peak = max(rolling)
        peak_idx = rolling.index(peak)
        peak_time = time_data[peak_idx]
        total_time = time_data[-1]

        # Last 60s average
        last_60s = [hr_data[i] for i in range(len(time_data)) if total_time - time_data[i] <= 60]
        end_60s = sum(last_60s) / len(last_60s) if last_60s else None

        recovery_intra = round(peak - end_60s, 1) if end_60s else None
        has_cooldown = end_60s is not None and end_60s < peak * 0.85

        result = {
            "hr_peak": round(peak, 1), "hr_peak_instant": round(max(hr_data), 1),
            "hr_end_60s": round(end_60s, 1) if end_60s else None,
            "hr_recovery_intra": recovery_intra, "has_cooldown": has_cooldown,
        }

        # Post-peak recovery (if data exists after peak)
        remaining = total_time - peak_time
        if remaining >= 60:
            t60 = peak_time + 60
            idx60 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - t60))
            w = hr_data[max(0, idx60-5):min(len(hr_data), idx60+5)]
            if w:
                hr60 = sum(w) / len(w)
                result["hr_at_peak_plus_60s"] = round(hr60, 1)
                result["hr_recovery_60s"] = round(peak - hr60, 1)

        if remaining >= 120:
            t120 = peak_time + 120
            idx120 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - t120))
            w = hr_data[max(0, idx120-5):min(len(hr_data), idx120+5)]
            if w:
                hr120 = sum(w) / len(w)
                result["hr_at_peak_plus_120s"] = round(hr120, 1)
                result["hr_recovery_120s"] = round(peak - hr120, 1)

        print(f"  HR stream: peak={result['hr_peak']}, recovery_intra={recovery_intra}, cooldown={has_cooldown}")
        return result, secret

    except urllib.error.HTTPError as e:
        if e.code in (404, 429):
            print(f"  Stream {strava_id}: HTTP {e.code}")
        return {}, secret
    except Exception as e:
        print(f"  Stream {strava_id} error: {e}")
        return {}, secret

'''

# Find the end of fetch_activity_zones function
zones_end_marker = "        return {}, secret\n\n\ndef fetch_activities"
zones_insert = strava.find(zones_end_marker)
if zones_insert == -1:
    # Try alternate
    zones_insert = strava.find("def fetch_activities")
    if zones_insert == -1:
        print("ERROR: Could not find insertion point in strava_lambda.py")
        sys.exit(1)
    strava = strava[:zones_insert] + STRAVA_STREAM_FN + strava[zones_insert:]
else:
    # Insert after the return but before fetch_activities
    insert_at = zones_insert + len("        return {}, secret\n")
    strava = strava[:insert_at] + STRAVA_STREAM_FN + strava[insert_at:]

print("  ✅ Inserted fetch_activity_streams function")

# Add HR stream fetching into the main ingestion loop
# Find where zone fetching happens and add stream fetching after it
zone_fetch_block = "                zone_data, secret = fetch_activity_zones(str(a[\"id\"]), secret)"
zone_idx = strava.find(zone_fetch_block)
if zone_idx != -1:
    # Find the end of the zone_data merging (next line with norm[...] = ...)
    # Look for the next line after zone merging to add our stream code
    after_zone = strava.find("\n", zone_idx + len(zone_fetch_block))
    # Find the end of the zone handling block
    # Search for the next outdented line
    lines_after = strava[after_zone:].split("\n")
    insert_offset = after_zone
    for i, line in enumerate(lines_after[1:], 1):
        if line.strip().startswith("norm[") or line.strip().startswith("if zone_data"):
            continue
        elif line.strip() and not line.startswith("                "):
            # Found end of zone block
            insert_offset = after_zone + sum(len(l) + 1 for l in lines_after[:i])
            break

    HR_STREAM_CALL = '''
                # Fetch HR streams for recovery metrics (activities >= 10 min with HR)
                elapsed_s = a.get("elapsed_time") or a.get("elapsed_time_seconds") or 0
                if elapsed_s >= 600:
                    hr_recovery, secret = fetch_activity_streams(str(a["id"]), secret)
                    if hr_recovery:
                        norm["hr_recovery"] = hr_recovery
'''
    strava = strava[:insert_offset] + HR_STREAM_CALL + strava[insert_offset:]
    print("  ✅ Inserted HR stream fetching in ingestion loop")
else:
    print("  ⚠️  Could not find zone fetch block — manual integration needed for HR streams")
    print("     Add after the zone_data fetch: fetch_activity_streams() call")

write("lambdas/strava_lambda.py", strava)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PATCH EIGHT SLEEP LAMBDA — Temperature data
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ Patching lambdas/eightsleep_lambda.py ═══")
backup("lambdas/eightsleep_lambda.py")
es = read("lambdas/eightsleep_lambda.py")

# Insert temperature functions before ingest_day
TEMP_FUNCTIONS = '''

def fetch_temperature_data(user_id, access_token, wake_date, tz):
    """Fetch bed temperature data from Eight Sleep intervals endpoint."""
    from_date = (datetime.strptime(wake_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        data = api_get(f"/v2/users/{user_id}/intervals", access_token,
                       params={"from": from_date, "to": wake_date, "tz": tz})
        intervals = data.get("intervals") or data.get("data") or []
        if not intervals:
            return {}
        target = next((i for i in intervals if (i.get("day") or i.get("date","")) == wake_date), None)
        if target is None and len(intervals) == 1:
            target = intervals[0]
        if target is None:
            return {}

        result = {}
        # Top-level temp fields
        for key in ["tempBedC", "bedTemperature"]:
            if target.get(key) is not None:
                result["bed_temp_c"] = round(float(target[key]), 1)
                result["bed_temp_f"] = round(float(target[key]) * 9/5 + 32, 1)
                break
        for key in ["tempRoomC", "roomTemperature"]:
            if target.get(key) is not None:
                result["room_temp_c"] = round(float(target[key]), 1)
                result["room_temp_f"] = round(float(target[key]) * 9/5 + 32, 1)
                break

        # Timeseries temp data
        ts = target.get("timeseries") or {}
        for ts_key in ["tempBedC", "tempBed"]:
            bed_ts = ts.get(ts_key, [])
            if bed_ts and "bed_temp_c" not in result:
                vals = []
                for p in bed_ts:
                    try:
                        v = float(p[1]) if isinstance(p, (list,tuple)) else float(p)
                        vals.append(v)
                    except: pass
                if vals:
                    result["bed_temp_c"] = round(sum(vals)/len(vals), 1)
                    result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
                    result["bed_temp_min_c"] = round(min(vals), 1)
                    result["bed_temp_max_c"] = round(max(vals), 1)

        # Per-stage temp levels
        stages = target.get("stages") or []
        levels = []
        for s in stages:
            t = s.get("temp") or s.get("temperature") or {}
            lv = t.get("level")
            if lv is not None:
                try: levels.append(float(lv))
                except: pass
        if levels:
            result["temp_level_avg"] = round(sum(levels)/len(levels), 1)
            result["temp_level_min"] = round(min(levels), 1)
            result["temp_level_max"] = round(max(levels), 1)

        # Score breakdown temp
        sq = target.get("sleepQualityScore") or {}
        for key in ["temperature", "tempBedC"]:
            val = sq.get(key)
            if isinstance(val, dict) and val.get("current") is not None and "bed_temp_c" not in result:
                try:
                    result["bed_temp_c"] = round(float(val["current"]), 1)
                    result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
                except: pass

        if result:
            print(f"Temp data: {list(result.keys())}")
        else:
            print(f"No temp data in intervals. Keys: {list(target.keys())[:10]}")
        return result
    except urllib.error.HTTPError as e:
        print(f"Intervals HTTP {e.code}")
        return {}
    except Exception as e:
        print(f"Temp fetch error: {e}")
        return {}


def extract_trends_temperature(trends_data, wake_date):
    """Check trends response for temperature data we might be missing."""
    days = trends_data.get("days") or []
    target = next((d for d in days if d.get("day") == wake_date), None)
    if target is None and len(days) == 1:
        target = days[0]
    if target is None:
        return {}
    result = {}
    for key in ["tempBedC", "bedTemperature", "bed_temp"]:
        if target.get(key) is not None:
            try:
                result["bed_temp_c"] = round(float(target[key]), 1)
                result["bed_temp_f"] = round(float(target[key]) * 9/5 + 32, 1)
            except: pass
    sq = target.get("sleepQualityScore") or {}
    for key in ["temperature", "tempBedC"]:
        val = sq.get(key)
        if isinstance(val, dict) and val.get("current") and "bed_temp_c" not in result:
            try:
                result["bed_temp_c"] = round(float(val["current"]), 1)
                result["bed_temp_f"] = round(result["bed_temp_c"] * 9/5 + 32, 1)
            except: pass
    return result

'''

# Insert before def ingest_day
ingest_marker = "\ndef ingest_day("
ingest_idx = es.find(ingest_marker)
if ingest_idx == -1:
    print("ERROR: Could not find ingest_day in eightsleep_lambda.py")
    sys.exit(1)

es = es[:ingest_idx] + TEMP_FUNCTIONS + es[ingest_idx:]
print("  ✅ Inserted temperature fetch functions")

# Add temperature fetching inside ingest_day, after trends fetch and before parse
# Find: trends = api_get(...) and the next line
trends_call = 'parsed = parse_trends_for_date(trends, wake_date, bed_side, tz_offset=tz_offset)'
trends_idx = es.find(trends_call)
if trends_idx != -1:
    TEMP_INTEGRATION = '''
    # Fetch temperature data
    temp_data = extract_trends_temperature(trends, wake_date)
    intervals_temp = fetch_temperature_data(user_id, token, wake_date, tz)
    temp_data.update(intervals_temp)

    '''
    es = es[:trends_idx] + TEMP_INTEGRATION + es[trends_idx:]
    print("  ✅ Inserted temperature fetch in ingest_day")
else:
    print("  ⚠️  Could not find parse_trends_for_date call — manual integration needed")

# Merge temp data into DDB item — find the table.put_item line
put_marker = "    table.put_item(Item=floats_to_decimal(db_item))"
put_idx = es.find(put_marker)
if put_idx != -1:
    TEMP_MERGE = '''    if temp_data:
        db_item.update(floats_to_decimal(temp_data))
        print(f"Temp data merged: {list(temp_data.keys())}")
'''
    es = es[:put_idx] + TEMP_MERGE + es[put_idx:]
    print("  ✅ Inserted temperature merge before DDB write")

write("lambdas/eightsleep_lambda.py", es)


# ══════════════════════════════════════════════════════════════════════════════
print("\n═══════════════════════════════════════════════")
print("  All patches applied!")
print("  Run: bash deploy/deploy_features_6_7_8.sh")
print("═══════════════════════════════════════════════")
