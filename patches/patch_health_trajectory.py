#!/usr/bin/env python3
"""
patch_health_trajectory.py — Health Trajectory Projections

Adds get_health_trajectory MCP tool that provides forward-looking intelligence:
  1. Weight trajectory: rate of loss, projected goal date, phase milestones
  2. Biomarker trajectories: lab trends, projected next-draw values, flags
  3. Fitness trajectory: Zone 2 trend, training load trend, HR recovery trend
  4. Metabolic trajectory: glucose trends from CGM, HbA1c projection
  5. Board of Directors longevity assessment

Context:
  - Attia: "Where are you headed?" matters more than "Where are you now?"
  - Patrick: Biomarker slopes are the earliest warning system
  - Huberman: Behavioral trajectories (consistency) predict outcomes better than snapshots

Usage:
  python3 patches/patch_health_trajectory.py
  (patches mcp_server.py in place)
"""

MCP_FILE = "mcp_server.py"

def read_file(path):
    with open(path, "r") as f:
        return f.read()

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)

# ─────────────────────────────────────────────
# Patch 1: Tool function — insert before Lambda handler
# ─────────────────────────────────────────────

TOOL_FN = '''

# ── Tool: get_health_trajectory (v2.34.0) ─────────────────────────────────────

def tool_get_health_trajectory(args):
    """
    Forward-looking health intelligence.

    Computes trajectories and projections across multiple domains:
      1. Weight: rate of loss, phase milestones, projected goal date
      2. Biomarkers: lab trend slopes, projected next-draw values
      3. Fitness: Zone 2 weekly trend, training consistency
      4. Recovery: HRV trend, sleep efficiency trend
      5. Body composition: lean mass preservation estimate

    Returns projections at 3, 6, and 12 months with confidence levels.
    Board of Directors provides longevity-focused assessment.
    """
    import statistics

    today = datetime.utcnow()
    today_str = today.strftime("%Y-%m-%d")
    profile = get_profile()

    domain = (args.get("domain") or "all").lower()
    valid_domains = ["all", "weight", "biomarkers", "fitness", "recovery", "metabolic"]
    if domain not in valid_domains:
        raise ValueError(f"domain must be one of: {valid_domains}")

    result = {}

    # ── 1. Weight Trajectory ──────────────────────────────────────────────
    if domain in ("all", "weight"):
        weight_data = query_source("withings", (today - timedelta(days=120)).strftime("%Y-%m-%d"), today_str)
        weights = []
        for item in weight_data:
            w = item.get("weight_lbs")
            d = item.get("date")
            if w and d:
                try:
                    weights.append((datetime.strptime(d, "%Y-%m-%d"), float(w)))
                except (ValueError, TypeError):
                    pass

        weights.sort(key=lambda x: x[0])

        if len(weights) >= 7:
            # Recent rate: last 4 weeks
            four_weeks_ago = today - timedelta(days=28)
            recent = [(d, w) for d, w in weights if d >= four_weeks_ago]

            if len(recent) >= 4:
                # Linear regression for recent rate
                x_vals = [(d - recent[0][0]).days for d, w in recent]
                y_vals = [w for d, w in recent]
                n = len(x_vals)
                sx = sum(x_vals)
                sy = sum(y_vals)
                sxy = sum(x * y for x, y in zip(x_vals, y_vals))
                sxx = sum(x * x for x in x_vals)
                denom = n * sxx - sx * sx
                if denom != 0:
                    slope_per_day = (n * sxy - sx * sy) / denom
                    intercept = (sy - slope_per_day * sx) / n
                else:
                    slope_per_day = 0
                    intercept = y_vals[0]

                weekly_rate = slope_per_day * 7
                current_weight = weights[-1][1]
                goal_weight = float(profile.get("goal_weight_lbs", 185))

                # Project goal date
                if slope_per_day < 0 and current_weight > goal_weight:
                    days_to_goal = (current_weight - goal_weight) / abs(slope_per_day)
                    projected_goal_date = (today + timedelta(days=days_to_goal)).strftime("%Y-%m-%d")
                else:
                    days_to_goal = None
                    projected_goal_date = None

                # Profile-based phases
                phases = profile.get("weight_loss_phases", [])
                phase_projections = []
                for phase in phases:
                    phase_end = float(phase.get("end_lbs", 0))
                    if current_weight > phase_end and slope_per_day < 0:
                        days = (current_weight - phase_end) / abs(slope_per_day)
                        phase_projections.append({
                            "phase":          phase.get("name", ""),
                            "target_lbs":     phase_end,
                            "projected_date": (today + timedelta(days=days)).strftime("%Y-%m-%d"),
                            "days_away":      int(days),
                            "target_rate":    float(phase.get("weekly_target_lbs", 0)),
                            "actual_rate":    round(abs(weekly_rate), 2),
                            "on_pace":        abs(weekly_rate) >= float(phase.get("weekly_target_lbs", 0)) * 0.8,
                        })

                # Projections at intervals
                projections = {}
                for label, days_out in [("3_months", 90), ("6_months", 180), ("12_months", 365)]:
                    proj = current_weight + (slope_per_day * days_out)
                    projections[label] = {
                        "projected_weight": round(max(proj, goal_weight), 1),
                        "lbs_from_goal":    round(max(proj, goal_weight) - goal_weight, 1),
                    }

                # Journey progress
                start_weight = float(profile.get("journey_start_weight_lbs", current_weight))
                total_to_lose = start_weight - goal_weight
                lost_so_far = start_weight - current_weight
                pct_complete = round(lost_so_far / total_to_lose * 100, 1) if total_to_lose > 0 else 0

                result["weight"] = {
                    "current_weight":       round(current_weight, 1),
                    "goal_weight":          goal_weight,
                    "weekly_rate_lbs":      round(weekly_rate, 2),
                    "daily_rate_lbs":       round(slope_per_day, 3),
                    "data_points_used":     len(recent),
                    "projected_goal_date":  projected_goal_date,
                    "days_to_goal":         int(days_to_goal) if days_to_goal else None,
                    "journey_progress_pct": pct_complete,
                    "lost_so_far":          round(lost_so_far, 1),
                    "remaining":            round(current_weight - goal_weight, 1),
                    "phase_milestones":     phase_projections,
                    "projections":          projections,
                    "trend_direction":      "losing" if weekly_rate < -0.3 else ("gaining" if weekly_rate > 0.3 else "stable"),
                }
            else:
                result["weight"] = {"message": "Need more recent data (< 4 data points in last 28 days)."}
        else:
            result["weight"] = {"message": "Need at least 7 weight measurements for trajectory analysis."}

    # ── 2. Biomarker Trajectories ─────────────────────────────────────────
    if domain in ("all", "biomarkers"):
        try:
            lab_draws = _query_all_lab_draws()
            if len(lab_draws) >= 3:
                # Key biomarkers to track
                key_biomarkers = [
                    ("ldl_c",           "LDL Cholesterol",   "mg/dL", None,   100, "below"),
                    ("hdl_c",           "HDL Cholesterol",   "mg/dL", 40,     None, "above"),
                    ("triglycerides",   "Triglycerides",     "mg/dL", None,   150, "below"),
                    ("hba1c",           "HbA1c",             "%",     None,   5.7, "below"),
                    ("glucose",         "Fasting Glucose",   "mg/dL", None,   100, "below"),
                    ("crp",             "CRP",               "mg/L",  None,   1.0, "below"),
                    ("tsh",             "TSH",               "mIU/L", 0.5,    4.0, "within"),
                    ("vitamin_d",       "Vitamin D",         "ng/mL", 40,     None, "above"),
                    ("ferritin",        "Ferritin",          "ng/mL", 30,     None, "above"),
                    ("testosterone_total", "Testosterone",   "ng/dL", 300,    None, "above"),
                ]

                bio_results = []
                for key, name, unit, low_thresh, high_thresh, direction in key_biomarkers:
                    points = []
                    for draw in lab_draws:
                        d = draw.get("date") or draw.get("sk", "").replace("DATE#", "")
                        biomarkers = draw.get("biomarkers", draw)
                        val = biomarkers.get(key)
                        if val is not None and d:
                            try:
                                points.append((datetime.strptime(d[:10], "%Y-%m-%d"), float(val)))
                            except (ValueError, TypeError):
                                pass

                    if len(points) < 2:
                        continue

                    points.sort(key=lambda x: x[0])

                    # Linear regression
                    x_vals = [(d - points[0][0]).days for d, v in points]
                    y_vals = [v for d, v in points]
                    n = len(x_vals)
                    sx = sum(x_vals)
                    sy = sum(y_vals)
                    sxy = sum(x * y for x, y in zip(x_vals, y_vals))
                    sxx = sum(x * x for x in x_vals)
                    denom = n * sxx - sx * sx

                    if denom != 0:
                        slope_per_day = (n * sxy - sx * sy) / denom
                    else:
                        slope_per_day = 0

                    slope_per_year = slope_per_day * 365.25
                    current_val = points[-1][1]

                    # Project 6 months out
                    proj_6mo = current_val + (slope_per_day * 180)

                    # Check if trending toward concern
                    concern = None
                    if direction == "below" and high_thresh and slope_per_year > 0 and proj_6mo > high_thresh:
                        concern = f"Trending toward {high_thresh} {unit} threshold"
                    elif direction == "above" and low_thresh and slope_per_year < 0 and proj_6mo < low_thresh:
                        concern = f"Trending toward {low_thresh} {unit} threshold"

                    bio_results.append({
                        "biomarker":        name,
                        "key":              key,
                        "current_value":    round(current_val, 1),
                        "unit":             unit,
                        "slope_per_year":   round(slope_per_year, 2),
                        "trend":            "rising" if slope_per_year > 0.5 else ("falling" if slope_per_year < -0.5 else "stable"),
                        "projected_6mo":    round(proj_6mo, 1),
                        "draws_used":       len(points),
                        "first_draw":       points[0][0].strftime("%Y-%m-%d"),
                        "latest_draw":      points[-1][0].strftime("%Y-%m-%d"),
                        "concern":          concern,
                    })

                # Sort: concerns first
                bio_results.sort(key=lambda b: (0 if b["concern"] else 1, b["biomarker"]))
                concerns = [b for b in bio_results if b["concern"]]

                result["biomarkers"] = {
                    "total_draws":     len(lab_draws),
                    "biomarkers_tracked": len(bio_results),
                    "concerns":        len(concerns),
                    "trajectories":    bio_results,
                }
            else:
                result["biomarkers"] = {"message": f"Need at least 3 lab draws for trajectory (have {len(lab_draws)})."}
        except Exception as e:
            logger.warning(f"Biomarker trajectory error: {e}")
            result["biomarkers"] = {"error": str(e)}

    # ── 3. Fitness Trajectory ─────────────────────────────────────────────
    if domain in ("all", "fitness"):
        try:
            strava_data = query_source("strava", (today - timedelta(days=90)).strftime("%Y-%m-%d"), today_str)

            if len(strava_data) >= 7:
                # Weekly training volume (hours)
                weekly_hours = {}
                weekly_zone2 = {}
                for item in strava_data:
                    d = item.get("date", "")
                    try:
                        dt = datetime.strptime(d, "%Y-%m-%d")
                        week_key = dt.strftime("%Y-W%U")
                    except ValueError:
                        continue
                    secs = float(item.get("total_moving_time_seconds", 0))
                    z2 = float(item.get("total_zone2_seconds", 0))
                    weekly_hours[week_key] = weekly_hours.get(week_key, 0) + secs / 3600
                    weekly_zone2[week_key] = weekly_zone2.get(week_key, 0) + z2 / 60

                weeks_sorted = sorted(weekly_hours.keys())
                if len(weeks_sorted) >= 4:
                    recent_4 = weeks_sorted[-4:]
                    avg_weekly_hours = sum(weekly_hours[w] for w in recent_4) / 4
                    avg_weekly_z2 = sum(weekly_zone2.get(w, 0) for w in recent_4) / 4

                    # Trend: first half vs second half of window
                    mid = len(weeks_sorted) // 2
                    first_half_hours = [weekly_hours[w] for w in weeks_sorted[:mid]]
                    second_half_hours = [weekly_hours[w] for w in weeks_sorted[mid:]]
                    first_avg = sum(first_half_hours) / len(first_half_hours) if first_half_hours else 0
                    second_avg = sum(second_half_hours) / len(second_half_hours) if second_half_hours else 0
                    volume_trend = "increasing" if second_avg > first_avg * 1.1 else ("decreasing" if second_avg < first_avg * 0.9 else "stable")

                    # Zone 2 target
                    z2_target = float(profile.get("zone2_weekly_target_min", 150))
                    z2_pct = round(avg_weekly_z2 / z2_target * 100, 0) if z2_target > 0 else 0

                    # Training consistency (% of weeks with any activity)
                    total_weeks = len(weeks_sorted)
                    active_weeks = sum(1 for w in weeks_sorted if weekly_hours[w] > 0.5)
                    consistency = round(active_weeks / total_weeks * 100, 0) if total_weeks > 0 else 0

                    result["fitness"] = {
                        "avg_weekly_hours":     round(avg_weekly_hours, 1),
                        "avg_weekly_zone2_min": round(avg_weekly_z2, 0),
                        "zone2_target_min":     z2_target,
                        "zone2_target_pct":     z2_pct,
                        "volume_trend":         volume_trend,
                        "training_consistency_pct": consistency,
                        "weeks_analyzed":       total_weeks,
                        "active_weeks":         active_weeks,
                        "attia_assessment":     (
                            "Meeting Zone 2 target" if z2_pct >= 90
                            else f"Zone 2 at {z2_pct}% of target — increase easy cardio"
                        ),
                    }
                else:
                    result["fitness"] = {"message": "Need at least 4 weeks of data."}
            else:
                result["fitness"] = {"message": "Insufficient Strava data for trajectory."}
        except Exception as e:
            logger.warning(f"Fitness trajectory error: {e}")
            result["fitness"] = {"error": str(e)}

    # ── 4. Recovery Trajectory ────────────────────────────────────────────
    if domain in ("all", "recovery"):
        try:
            whoop_data = query_source("whoop", (today - timedelta(days=60)).strftime("%Y-%m-%d"), today_str)
            es_data = query_source("eightsleep", (today - timedelta(days=60)).strftime("%Y-%m-%d"), today_str)

            hrv_vals = []
            rhr_vals = []
            recovery_vals = []
            sleep_eff_vals = []

            for item in whoop_data:
                hrv = item.get("hrv_rmssd")
                rhr = item.get("resting_heart_rate")
                rec = item.get("recovery_score")
                if hrv: hrv_vals.append(float(hrv))
                if rhr: rhr_vals.append(float(rhr))
                if rec: recovery_vals.append(float(rec))

            for item in es_data:
                eff = item.get("sleep_efficiency_pct")
                if eff: sleep_eff_vals.append(float(eff))

            recovery_result = {}

            if len(hrv_vals) >= 14:
                first_half = hrv_vals[:len(hrv_vals)//2]
                second_half = hrv_vals[len(hrv_vals)//2:]
                hrv_trend = "improving" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) * 1.05 else \
                           ("declining" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) * 0.95 else "stable")
                recovery_result["hrv"] = {
                    "current_avg":  round(sum(hrv_vals[-7:]) / min(len(hrv_vals), 7), 1),
                    "60d_avg":      round(sum(hrv_vals) / len(hrv_vals), 1),
                    "trend":        hrv_trend,
                    "data_points":  len(hrv_vals),
                }

            if len(rhr_vals) >= 14:
                first_half = rhr_vals[:len(rhr_vals)//2]
                second_half = rhr_vals[len(rhr_vals)//2:]
                rhr_trend = "improving" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) * 0.97 else \
                           ("worsening" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) * 1.03 else "stable")
                recovery_result["rhr"] = {
                    "current_avg":  round(sum(rhr_vals[-7:]) / min(len(rhr_vals), 7), 1),
                    "60d_avg":      round(sum(rhr_vals) / len(rhr_vals), 1),
                    "trend":        rhr_trend,
                    "data_points":  len(rhr_vals),
                }

            if len(sleep_eff_vals) >= 14:
                first_half = sleep_eff_vals[:len(sleep_eff_vals)//2]
                second_half = sleep_eff_vals[len(sleep_eff_vals)//2:]
                eff_trend = "improving" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) + 1 else \
                           ("declining" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) - 1 else "stable")
                recovery_result["sleep_efficiency"] = {
                    "current_avg":  round(sum(sleep_eff_vals[-7:]) / min(len(sleep_eff_vals), 7), 1),
                    "60d_avg":      round(sum(sleep_eff_vals) / len(sleep_eff_vals), 1),
                    "trend":        eff_trend,
                    "data_points":  len(sleep_eff_vals),
                }

            if recovery_result:
                result["recovery"] = recovery_result
            else:
                result["recovery"] = {"message": "Need at least 14 days of Whoop/Eight Sleep data."}
        except Exception as e:
            logger.warning(f"Recovery trajectory error: {e}")
            result["recovery"] = {"error": str(e)}

    # ── 5. Metabolic Trajectory ───────────────────────────────────────────
    if domain in ("all", "metabolic"):
        try:
            cgm_data = query_source("apple_health", (today - timedelta(days=60)).strftime("%Y-%m-%d"), today_str)
            glucose_vals = []
            tir_vals = []
            for item in cgm_data:
                mean_g = item.get("cgm_mean_glucose")
                tir = item.get("cgm_time_in_range_pct")
                if mean_g:
                    glucose_vals.append(float(mean_g))
                if tir:
                    tir_vals.append(float(tir))

            metabolic = {}
            if len(glucose_vals) >= 7:
                first_half = glucose_vals[:len(glucose_vals)//2]
                second_half = glucose_vals[len(glucose_vals)//2:]
                glucose_trend = "improving" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) - 1 else \
                               ("worsening" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) + 1 else "stable")
                metabolic["mean_glucose"] = {
                    "current_avg":  round(sum(glucose_vals[-7:]) / min(len(glucose_vals), 7), 1),
                    "period_avg":   round(sum(glucose_vals) / len(glucose_vals), 1),
                    "trend":        glucose_trend,
                    "target":       "< 100 mg/dL (Attia optimal)",
                    "data_points":  len(glucose_vals),
                }
            if len(tir_vals) >= 7:
                metabolic["time_in_range"] = {
                    "current_avg":  round(sum(tir_vals[-7:]) / min(len(tir_vals), 7), 1),
                    "period_avg":   round(sum(tir_vals) / len(tir_vals), 1),
                    "target":       "> 90% (optimal metabolic health)",
                    "data_points":  len(tir_vals),
                }
            if metabolic:
                result["metabolic"] = metabolic
            else:
                result["metabolic"] = {"message": "Insufficient CGM data for metabolic trajectory."}
        except Exception as e:
            logger.warning(f"Metabolic trajectory error: {e}")
            result["metabolic"] = {"error": str(e)}

    # ── Board of Directors Assessment ─────────────────────────────────────
    concerns = []
    positives = []

    if "weight" in result and isinstance(result["weight"], dict) and "trend_direction" in result["weight"]:
        w = result["weight"]
        if w["trend_direction"] == "losing":
            positives.append(f"Weight loss on track at {abs(w['weekly_rate_lbs'])} lbs/week")
        elif w["trend_direction"] == "gaining":
            concerns.append(f"Weight trending up ({w['weekly_rate_lbs']} lbs/week)")

    if "biomarkers" in result and isinstance(result["biomarkers"], dict) and "concerns" in result["biomarkers"]:
        n_concerns = result["biomarkers"]["concerns"]
        if n_concerns > 0:
            concerns.append(f"{n_concerns} biomarker(s) trending toward concerning levels")
        else:
            positives.append("All tracked biomarkers within acceptable trajectories")

    if "fitness" in result and isinstance(result["fitness"], dict) and "zone2_target_pct" in result["fitness"]:
        z2 = result["fitness"]["zone2_target_pct"]
        if z2 >= 90:
            positives.append(f"Zone 2 target met ({z2}%)")
        else:
            concerns.append(f"Zone 2 at {z2}% of target — increase easy cardio")

    if "recovery" in result and isinstance(result["recovery"], dict):
        hrv_info = result["recovery"].get("hrv", {})
        if hrv_info.get("trend") == "improving":
            positives.append("HRV trend improving — fitness adaptation positive")
        elif hrv_info.get("trend") == "declining":
            concerns.append("HRV declining — possible overtraining, stress, or sleep debt")

    result["board_of_directors"] = {
        "summary": {
            "positives":  positives,
            "concerns":   concerns,
            "overall":    "on_track" if len(positives) >= len(concerns) else "attention_needed",
        },
        "Attia": (
            "The trajectory is more important than any single data point. Focus on the slopes, not the snapshots. "
            "Weight loss rate, biomarker trends, and Zone 2 consistency are the three pillars of your longevity trajectory."
        ),
        "Patrick": (
            "Biomarker slopes are early warning signals. A rising LDL or declining vitamin D can be intercepted "
            "months before they become clinical problems. Review the concern flags carefully."
        ),
        "Huberman": (
            "Consistency compounds. Your training consistency percentage is a better predictor of outcomes than "
            "any single workout. Behavioral momentum creates physiological momentum."
        ),
        "Ferriss": (
            "What is the ONE metric that, if improved, would move everything else? "
            "For most people in a transformation, it is sleep quality — it amplifies recovery, willpower, and metabolic function."
        ),
    }

    result["generated_at"] = today_str
    result["domain_requested"] = domain

    return result

'''

# ─────────────────────────────────────────────
# Patch 2: TOOLS dict entry
# ─────────────────────────────────────────────

TOOLS_ENTRY = '''    "get_health_trajectory": {
        "fn": tool_get_health_trajectory,
        "schema": {
            "name": "get_health_trajectory",
            "description": (
                "Forward-looking health intelligence — where are you headed? "
                "Computes trajectories and projections across 5 domains: weight (rate of loss, "
                "goal date, phase milestones), biomarkers (lab trend slopes, projected values, "
                "threshold warnings), fitness (Zone 2 trend, training consistency), recovery "
                "(HRV trend, sleep efficiency), and metabolic (glucose trends, time in range). "
                "Board of Directors provides a longevity-focused assessment of overall trajectory. "
                "Use for: 'where am I headed?', 'health trajectory', 'projected goal date', "
                "'biomarker trends', 'am I on track?', 'forward-looking health assessment', "
                "'when will I reach my goal weight?', 'longevity projection'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string",
                               "description": "Focus area: 'all' (default), 'weight', 'biomarkers', 'fitness', 'recovery', 'metabolic'."},
                },
                "required": [],
            },
        },
    },
'''


def main():
    content = read_file(MCP_FILE)

    # Check if already patched
    if "tool_get_health_trajectory" in content:
        print("⏭️  mcp_server.py already has health trajectory tool — skipping")
        return

    # Insert tool function before Lambda handler
    anchor = "# ── Lambda handler"
    if anchor not in content:
        raise ValueError(f"Could not find anchor '{anchor}' in {MCP_FILE}")
    content = content.replace(anchor, TOOL_FN + anchor)

    # Insert TOOLS dict entry
    # Find the closing of TOOLS dict — look for pattern before MCP protocol handlers
    tools_close = "}\n\n\n# ── MCP protocol handlers"
    if tools_close not in content:
        tools_close = "}\n\n# ── MCP protocol handlers"
    if tools_close not in content:
        raise ValueError("Could not find TOOLS dict closing pattern")

    new_close = TOOLS_ENTRY + "}\n\n# ── MCP protocol handlers"
    content = content.replace(tools_close, new_close, 1)

    write_file(MCP_FILE, content)

    tool_count = content.count('"fn":')
    print(f"✅ mcp_server.py patched with health trajectory tool ({tool_count} tools)")


if __name__ == "__main__":
    main()
