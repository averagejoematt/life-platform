"""
Feature #7: Readiness-Based Training Recommendation
Adds tool_get_training_recommendation to mcp_server.py

Insert this function BEFORE the TOOLS dict (before line ~8203).
Then add the TOOLS entry.
"""

# ══════════════════════════════════════════════════════════════════════════════
# PASTE INTO mcp_server.py — BEFORE the TOOLS = { line
# ══════════════════════════════════════════════════════════════════════════════

TRAINING_REC_CODE = '''
def tool_get_training_recommendation(args):
    """
    Readiness-based training recommendation. Synthesizes recovery state, training
    load, recent activity history, muscle group recency, and sleep quality into
    a specific workout suggestion with Board of Directors rationale.

    Based on Galpin (training periodization), Huberman (recovery science),
    Attia (longevity training framework), Seiler (polarized training).
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
        load_result = tool_get_training_load({"end_date": target_date})
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

    dates_7d = sorted(strava_by_date.keys())[-7:]
    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical",
                    "virtualrun", "virtualride", "trailrun"}
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

            recent_activities.append({
                "date": date,
                "sport": act.get("sport_type") or act.get("type"),
                "duration_min": round(elapsed / 60, 1),
                "avg_hr": avg_hr,
                "is_hard": is_hard,
            })

    # Consecutive rest/training days
    check_date = datetime.strptime(target_date, "%Y-%m-%d")
    for i in range(7):
        d = (check_date - timedelta(days=i+1)).strftime("%Y-%m-%d")
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
        if d is None: return None
        return (datetime.strptime(target_date, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days

    days_since_cardio = _days_since(last_cardio_date)
    days_since_strength = _days_since(last_strength_date)
    days_since_hard = _days_since(last_hard_date)

    # ── 4. Muscle group recency from strength data ───────────────────────────
    muscle_last_trained = {}
    mf_workout_items = query_source("macrofactor_workouts", d14_start, target_date)
    for item in mf_workout_items:
        d = item.get("date")
        for workout in (item.get("workouts") or []):
            for exercise in (workout.get("exercises") or []):
                ename = exercise.get("exercise_name", "")
                cls = classify_exercise(ename)
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
    if recovery_score is not None: signals.append(recovery_score)
    if sleep_score is not None: signals.append(sleep_score)
    if body_battery is not None: signals.append(body_battery)

    composite = _avg(signals) if signals else 50
    tier = "GREEN" if composite >= 67 else ("YELLOW" if composite >= 33 else "RED")

    # Injury risk override
    if acwr is not None and acwr > 1.5:
        tier = "RED"
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
        warnings.append(f"⚠️ Only {readiness['sleep_duration']}h sleep — short sleep impairs muscle protein synthesis and injury risk. Reduce intensity.")
    if readiness.get("whoop_hrv") and len([w for w in whoop_items if _sf(w.get("hrv"))]) >= 3:
        hrv_vals = [_sf(w.get("hrv")) for w in whoop_items if _sf(w.get("hrv"))]
        hrv_avg = _avg(hrv_vals)
        if readiness["whoop_hrv"] < hrv_avg * 0.8:
            warnings.append(f"⚠️ HRV ({readiness['whoop_hrv']}ms) is {round((1 - readiness['whoop_hrv']/hrv_avg)*100)}% below your 7-day average. Parasympathetic suppression — reduce intensity.")
    if readiness.get("garmin_stress") and readiness["garmin_stress"] > 50:
        warnings.append(f"⚠️ Garmin stress score {readiness['garmin_stress']} (elevated). Consider how allostatic load affects recovery.")

    # ── 8. Board of Directors rationale ───────────────────────────────────────
    bod_notes = []
    if tier == "GREEN":
        bod_notes.append("Huberman: Full parasympathetic recovery detected. Sympathetic drive available for high-output work.")
        if rec.get("type", "").startswith("Strength"):
            bod_notes.append("Galpin: Mechanical tension (heavy loads, 1-2 RIR) drives hypertrophy most efficiently when recovery is complete.")
        elif "Interval" in rec.get("type", ""):
            bod_notes.append("Attia: VO2max is the single strongest predictor of all-cause mortality. Hard intervals 1-2x/week are the highest-ROI investment.")
    elif tier == "YELLOW":
        bod_notes.append("Attia: Zone 2 is the longevity foundation — 150+ min/week builds mitochondrial density without recovery cost.")
        bod_notes.append("Huberman: Moderate training during partial recovery can still stimulate adaptation without digging a deeper hole.")
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
'''

# ══════════════════════════════════════════════════════════════════════════════
# TOOLS ENTRY — add inside TOOLS dict
# ══════════════════════════════════════════════════════════════════════════════

TRAINING_REC_TOOLS_ENTRY = '''
    "get_training_recommendation": {
        "fn": tool_get_training_recommendation,
        "schema": {
            "name": "get_training_recommendation",
            "description": (
                "Readiness-based training recommendation. Synthesizes Whoop recovery, Eight Sleep quality, "
                "Garmin Body Battery, training load (CTL/ATL/TSB), recent activity history, and muscle group "
                "recency into a specific workout suggestion: type (Zone 2, intervals, strength upper/lower, "
                "active recovery, rest), intensity, duration, HR targets, and muscle groups to target. "
                "Board of Directors provides rationale. Warns about injury risk (ACWR), consecutive training days, "
                "and sleep debt. Use for: 'what should I do today?', 'workout recommendation', 'should I train today?', "
                "'am I recovered enough for a hard workout?', 'readiness-based training', 'what workout today?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },'''

print("Feature #7 patch ready. Code to insert into mcp_server.py.")
print(f"Tool function: {len(TRAINING_REC_CODE.splitlines())} lines")
print(f"TOOLS entry: {len(TRAINING_REC_TOOLS_ENTRY.splitlines())} lines")
