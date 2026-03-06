#!/usr/bin/env python3
"""
patch_mcp_v2150.py — Add 6 new tools to MCP server (v2.14.0 → v2.15.0)

New tools:
  - get_gait_analysis               : gait & mobility tracking (walking speed, step length, asymmetry)
  - get_energy_balance              : Apple Watch TDEE vs MacroFactor intake
  - get_movement_score              : NEAT estimate + daily movement composite
  - get_cgm_dashboard               : CGM glucose overview (time in range, variability, fasting trend)
  - get_glucose_sleep_correlation   : glucose vs Eight Sleep metrics
  - get_glucose_exercise_correlation: exercise vs rest day glucose patterns

Run: python3 patch_mcp_v2150.py
Then deploy: bash deploy_mcp.sh (or equivalent)
"""

import re
import sys
import os

MCP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")

# ── Read current file ──
with open(MCP_FILE, "r") as f:
    content = f.read()

# ── Verify starting version ──
if 'version": "2.15.0"' in content:
    print("Already at v2.15.0. Skipping.")
    sys.exit(0)

if '"get_gait_analysis"' in content:
    print("Tools already present. Skipping.")
    sys.exit(0)

print(f"Patching {MCP_FILE}...")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Insert tool functions before TOOLS dict
# ══════════════════════════════════════════════════════════════════════════════

TOOL_FUNCTIONS = r'''

# ══════════════════════════════════════════════════════════════════════════════
# v2.15.0 — Gait, Energy Balance, Movement, CGM tools
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_gait_analysis(args):
    """Gait & mobility analysis from Apple Watch passive measurements."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": f"No Apple Health data for {start_date} to {end_date}."}

    items_sorted = sorted(items, key=lambda x: x.get("date", ""))
    GAIT_FIELDS = ["walking_speed_mph", "walking_step_length_in",
                    "walking_asymmetry_pct", "walking_double_support_pct"]

    rows = []
    for item in items_sorted:
        row = {"date": item.get("date")}
        has_gait = False
        for f in GAIT_FIELDS:
            v = item.get(f)
            if v is not None:
                row[f] = float(v)
                has_gait = True
        if has_gait:
            rows.append(row)

    if not rows:
        return {"error": "No gait data found. Requires Apple Watch + Health Auto Export webhook v1.1.0+."}

    # Period averages
    averages = {}
    for f in GAIT_FIELDS:
        vals = [r[f] for r in rows if f in r]
        if vals:
            averages[f] = round(sum(vals) / len(vals), 2)
            averages[f"{f}_min"] = round(min(vals), 2)
            averages[f"{f}_max"] = round(max(vals), 2)

    # Trend: first half vs second half
    trends = {}
    for f in GAIT_FIELDS:
        vals = [r[f] for r in rows if f in r]
        if len(vals) >= 6:
            mid = len(vals) // 2
            first_avg = sum(vals[:mid]) / mid
            second_avg = sum(vals[mid:]) / (len(vals) - mid)
            pct_change = round((second_avg - first_avg) / first_avg * 100, 1) if first_avg else 0
            improving = (f in ("walking_speed_mph", "walking_step_length_in") and pct_change > 1) or \
                        (f in ("walking_asymmetry_pct", "walking_double_support_pct") and pct_change < -1)
            declining = (f in ("walking_speed_mph", "walking_step_length_in") and pct_change < -1) or \
                        (f in ("walking_asymmetry_pct", "walking_double_support_pct") and pct_change > 1)
            trends[f] = {"first_half_avg": round(first_avg, 2), "second_half_avg": round(second_avg, 2),
                         "pct_change": pct_change, "direction": "improving" if improving else "declining" if declining else "stable"}

    # Clinical flags
    flags = []
    avg_speed = averages.get("walking_speed_mph")
    if avg_speed is not None:
        if avg_speed < 2.24:
            flags.append({"metric": "walking_speed_mph", "severity": "critical",
                          "message": f"Avg speed {avg_speed} mph < 1.0 m/s clinical threshold — strong adverse health predictor."})
        elif avg_speed < 3.0:
            flags.append({"metric": "walking_speed_mph", "severity": "warning",
                          "message": f"Avg speed {avg_speed} mph below optimal. Target >3.0 mph for age <60."})

    avg_asym = averages.get("walking_asymmetry_pct")
    if avg_asym is not None and avg_asym > 4.0:
        flags.append({"metric": "walking_asymmetry_pct", "severity": "warning",
                      "message": f"Avg asymmetry {avg_asym}% > 4% threshold — may indicate injury/compensation."})

    # Asymmetry spike detection
    asym_vals = [r.get("walking_asymmetry_pct") for r in rows if r.get("walking_asymmetry_pct") is not None]
    if len(asym_vals) >= 7:
        baseline_avg = sum(asym_vals[:-3]) / len(asym_vals[:-3])
        recent_avg = sum(asym_vals[-3:]) / 3
        if baseline_avg > 0 and (recent_avg - baseline_avg) / baseline_avg > 0.3:
            flags.append({"metric": "walking_asymmetry_pct", "severity": "alert",
                          "message": f"Asymmetry spike: recent {round(recent_avg, 1)}% vs baseline {round(baseline_avg, 1)}%."})

    speed_trend = trends.get("walking_speed_mph", {})
    if speed_trend.get("direction") == "declining" and abs(speed_trend.get("pct_change", 0)) > 3:
        flags.append({"metric": "walking_speed_mph", "severity": "warning",
                      "message": f"Walking speed declining {abs(speed_trend['pct_change'])}% — early longevity risk signal."})

    # Composite gait score (0-100): speed 40%, step length 30%, asymmetry 20%, double support 10%
    composite = None
    components = {}
    if avg_speed is not None:
        components["speed_score"] = round(max(0, min(100, (avg_speed - 2.0) / 2.0 * 100)), 0)
    avg_step = averages.get("walking_step_length_in")
    if avg_step is not None:
        components["step_length_score"] = round(max(0, min(100, (avg_step - 20) / 12.0 * 100)), 0)
    if avg_asym is not None:
        components["asymmetry_score"] = round(max(0, min(100, (8.0 - avg_asym) / 8.0 * 100)), 0)
    avg_ds = averages.get("walking_double_support_pct")
    if avg_ds is not None:
        components["double_support_score"] = round(max(0, min(100, (35.0 - avg_ds) / 15.0 * 100)), 0)

    if components:
        weights = {"speed_score": 0.4, "step_length_score": 0.3, "asymmetry_score": 0.2, "double_support_score": 0.1}
        ws, tw = 0, 0
        for k, w in weights.items():
            if k in components:
                ws += components[k] * w
                tw += w
        if tw > 0:
            composite = round(ws / tw, 0)

    return {
        "period": {"start": start_date, "end": end_date, "days_with_data": len(rows)},
        "composite_gait_score": composite,
        "composite_components": components if components else None,
        "averages": averages,
        "trends": trends if trends else None,
        "clinical_flags": flags if flags else None,
        "daily": rows[-14:],
        "interpretation": {
            "walking_speed": "Strongest single all-cause mortality predictor. <1.0 m/s (2.24 mph) is clinical flag.",
            "step_length": "Earliest aging gait marker — declines before speed. Track trajectory.",
            "asymmetry": ">3-4% sustained = injury/compensation. Sudden spikes may signal acute injury.",
            "double_support": "Higher = more cautious gait = fall risk indicator.",
            "composite": "0-100 weighted: speed 40%, step length 30%, asymmetry 20%, double support 10%.",
        },
    }


def tool_get_energy_balance(args):
    """Apple Watch TDEE vs MacroFactor intake — daily surplus/deficit."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    target_deficit = args.get("target_deficit_kcal", 500)

    ah_items = query_source("apple_health", start_date, end_date)
    mf_items = query_source("macrofactor", start_date, end_date)
    if not ah_items and not mf_items:
        return {"error": "No Apple Health or MacroFactor data in range."}

    ah_by_date = {i.get("date"): i for i in ah_items if i.get("date")}
    mf_by_date = {i.get("date"): i for i in mf_items if i.get("date")}
    all_dates = sorted(set(list(ah_by_date.keys()) + list(mf_by_date.keys())))

    daily = []
    balance_vals = []
    deficit_hit = 0
    surplus = 0

    for date in all_dates:
        ah = ah_by_date.get(date, {})
        mf = mf_by_date.get(date, {})
        active = ah.get("active_calories")
        basal = ah.get("basal_calories")
        tdee = ah.get("total_calories_burned")
        intake = mf.get("total_calories_kcal")
        if tdee is None and active is not None and basal is not None:
            tdee = float(active) + float(basal)

        row = {"date": date}
        if tdee is not None:
            row["tdee"] = round(float(tdee), 0)
            if active: row["active_calories"] = round(float(active), 0)
            if basal: row["basal_calories"] = round(float(basal), 0)
        if intake is not None:
            row["intake_kcal"] = round(float(intake), 0)
            prot = mf.get("total_protein_g")
            if prot: row["protein_g"] = round(float(prot), 0)
        if tdee is not None and intake is not None:
            bal = round(float(intake) - float(tdee), 0)
            row["balance_kcal"] = bal
            row["status"] = "deficit" if bal < 0 else "surplus"
            balance_vals.append(bal)
            if bal <= -target_deficit: deficit_hit += 1
            if bal > 0: surplus += 1
        daily.append(row)

    paired = len(balance_vals)
    summary = {"paired_days": paired}
    if balance_vals:
        avg_bal = round(sum(balance_vals) / paired, 0)
        summary["avg_daily_balance_kcal"] = avg_bal
        summary["avg_status"] = "deficit" if avg_bal < 0 else "surplus"
        summary["implied_weekly_change_lbs"] = round(avg_bal * 7 / 3500, 2)
        summary["deficit_target_hit_rate_pct"] = round(deficit_hit / paired * 100, 1)
        summary["surplus_days"] = surplus
        summary["surplus_day_pct"] = round(surplus / paired * 100, 1)
        if len(balance_vals) >= 7:
            summary["last_7d_avg_balance"] = round(sum(balance_vals[-7:]) / 7, 0)

    tdee_vals = [float(a.get("total_calories_burned")) for a in ah_by_date.values() if a.get("total_calories_burned")]
    if tdee_vals:
        summary["avg_apple_watch_tdee"] = round(sum(tdee_vals) / len(tdee_vals), 0)
    intake_vals = [float(m.get("total_calories_kcal")) for m in mf_by_date.values() if m.get("total_calories_kcal")]
    if intake_vals:
        summary["avg_intake_kcal"] = round(sum(intake_vals) / len(intake_vals), 0)

    return {
        "period": {"start": start_date, "end": end_date},
        "target_deficit_kcal": target_deficit,
        "summary": summary,
        "daily": daily,
        "note": "TDEE from Apple Watch (active + basal) is more accurate than formula-based BMR. 500 kcal/day deficit ≈ 1 lb/week loss.",
    }


def tool_get_movement_score(args):
    """Daily movement & NEAT analysis."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    step_target = args.get("step_target", 8000)

    sources = parallel_query_sources(["apple_health", "strava"], start_date, end_date)
    ah_items = sources.get("apple_health", [])
    strava_items = sources.get("strava", [])
    if not ah_items:
        return {"error": "No Apple Health data in range."}

    ah_by_date = {i.get("date"): i for i in ah_items if i.get("date")}
    strava_by_date = {i.get("date"): i for i in strava_items if i.get("date")}

    daily = []
    neat_vals = []
    step_vals = []
    sedentary_days = []

    for date in sorted(ah_by_date.keys()):
        ah = ah_by_date[date]
        strava = strava_by_date.get(date, {})
        steps = ah.get("steps")
        flights = ah.get("flights_climbed")
        distance = ah.get("distance_walk_run_miles")
        active_cal = ah.get("active_calories")
        exercise_kj = strava.get("total_kilojoules")
        exercise_kcal = float(exercise_kj) if exercise_kj else 0
        has_workout = int(float(strava.get("activity_count", 0))) > 0

        row = {"date": date, "has_workout": has_workout}
        if steps is not None:
            row["steps"] = int(float(steps))
            step_vals.append(float(steps))
        if flights is not None:
            row["flights_climbed"] = int(float(flights))
        if distance is not None:
            row["distance_miles"] = round(float(distance), 2)
        if active_cal is not None:
            row["active_calories"] = round(float(active_cal), 0)
            neat = max(0, round(float(active_cal) - exercise_kcal, 0))
            row["neat_estimate_kcal"] = neat
            neat_vals.append(neat)
        if steps and float(steps) < 5000 and not has_workout and (active_cal is None or float(active_cal) < 200):
            row["sedentary_flag"] = True
            sedentary_days.append(date)
        daily.append(row)

    summary = {"days_with_data": len(daily)}
    if step_vals:
        summary["avg_daily_steps"] = round(sum(step_vals) / len(step_vals), 0)
        summary["step_target"] = step_target
        summary["step_target_hit_rate_pct"] = round(sum(1 for s in step_vals if s >= step_target) / len(step_vals) * 100, 1)
    if neat_vals:
        summary["avg_neat_kcal"] = round(sum(neat_vals) / len(neat_vals), 0)
        active_vals = [r.get("active_calories") for r in daily if r.get("active_calories")]
        if active_vals:
            avg_active = sum(active_vals) / len(active_vals)
            if avg_active > 0:
                summary["neat_pct_of_active"] = round((sum(neat_vals) / len(neat_vals)) / avg_active * 100, 1)
    summary["sedentary_days"] = len(sedentary_days)
    summary["sedentary_day_pct"] = round(len(sedentary_days) / len(daily) * 100, 1) if daily else 0

    # Movement score per day
    if step_vals and len(step_vals) >= 7:
        baseline_steps = sum(step_vals) / len(step_vals)
        baseline_neat = sum(neat_vals) / len(neat_vals) if neat_vals else 1
        for row in daily:
            c = {}
            s = row.get("steps")
            if s is not None and baseline_steps > 0:
                c["steps"] = min(100, s / (baseline_steps * 1.5) * 100)
            f = row.get("flights_climbed")
            if f is not None:
                c["flights"] = min(100, f / 15 * 100)
            d = row.get("distance_miles")
            if d is not None:
                c["distance"] = min(100, d / 5.0 * 100)
            n = row.get("neat_estimate_kcal")
            if n is not None and baseline_neat > 0:
                c["neat"] = min(100, n / (baseline_neat * 1.5) * 100)
            if c:
                wts = {"steps": 0.5, "flights": 0.15, "distance": 0.15, "neat": 0.2}
                sc, tw = 0, 0
                for k, w in wts.items():
                    if k in c:
                        sc += c[k] * w
                        tw += w
                if tw > 0:
                    row["movement_score"] = round(sc / tw, 0)

    scores = [r["movement_score"] for r in daily if "movement_score" in r]
    if scores:
        summary["avg_movement_score"] = round(sum(scores) / len(scores), 0)

    return {
        "period": {"start": start_date, "end": end_date},
        "summary": summary,
        "sedentary_dates": sedentary_days[-10:] if sedentary_days else None,
        "daily": daily,
        "note": "NEAT is energy burned outside exercise. Sedentary = <5000 steps + no workout + <200 active cal.",
    }


def tool_get_cgm_dashboard(args):
    """CGM glucose daily dashboard from DynamoDB aggregates."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": "No Apple Health data in range."}

    glucose_days = [i for i in sorted(items, key=lambda x: x.get("date", "")) if i.get("blood_glucose_avg") is not None]
    if not glucose_days:
        return {"error": "No blood glucose data in range. Requires Dexcom Stelo + webhook."}

    rows = []
    cgm_ct = 0
    for item in glucose_days:
        row = {
            "date": item.get("date"),
            "avg": round(float(item["blood_glucose_avg"]), 1),
            "min": round(float(item.get("blood_glucose_min", 0)), 1),
            "max": round(float(item.get("blood_glucose_max", 0)), 1),
            "std_dev": round(float(item.get("blood_glucose_std_dev", 0)), 1),
            "readings": int(float(item.get("blood_glucose_readings_count", 0))),
            "time_in_range_pct": round(float(item.get("blood_glucose_time_in_range_pct", 0)), 1),
            "time_above_140_pct": round(float(item.get("blood_glucose_time_above_140_pct", 0)), 1),
            "time_below_70_pct": round(float(item.get("blood_glucose_time_below_70_pct", 0)), 1),
            "source": item.get("cgm_source", "unknown"),
        }
        rows.append(row)
        if item.get("cgm_source") == "dexcom_stelo":
            cgm_ct += 1

    avg_vals = [r["avg"] for r in rows]
    min_vals = [r["min"] for r in rows if r["min"] > 0]
    sd_vals = [r["std_dev"] for r in rows]
    tir_vals = [r["time_in_range_pct"] for r in rows]
    a140 = [r["time_above_140_pct"] for r in rows]

    summary = {
        "total_days": len(rows), "cgm_days": cgm_ct, "manual_days": len(rows) - cgm_ct,
        "avg_glucose": round(sum(avg_vals) / len(avg_vals), 1),
        "avg_fasting_proxy": round(sum(min_vals) / len(min_vals), 1) if min_vals else None,
        "avg_variability_sd": round(sum(sd_vals) / len(sd_vals), 1),
        "avg_time_in_range_pct": round(sum(tir_vals) / len(tir_vals), 1),
        "avg_time_above_140_pct": round(sum(a140) / len(a140), 1),
    }

    flags = []
    if summary["avg_glucose"] > 100:
        flags.append({"severity": "warning", "message": f"Mean glucose {summary['avg_glucose']} > 100 mg/dL optimal threshold."})
    if summary["avg_variability_sd"] > 25:
        flags.append({"severity": "warning", "message": f"Glucose variability SD {summary['avg_variability_sd']} > 25 target. Large postprandial spikes."})
    if summary["avg_time_in_range_pct"] < 90:
        flags.append({"severity": "warning", "message": f"Time in range {summary['avg_time_in_range_pct']}% < 90% target."})
    fp = summary.get("avg_fasting_proxy")
    if fp and fp > 100:
        flags.append({"severity": "warning", "message": f"Fasting proxy {fp} > 100 mg/dL. Target <90."})

    trend = None
    if len(avg_vals) >= 6:
        mid = len(avg_vals) // 2
        f_avg = sum(avg_vals[:mid]) / mid
        s_avg = sum(avg_vals[mid:]) / (len(avg_vals) - mid)
        pct = round((s_avg - f_avg) / f_avg * 100, 1) if f_avg else 0
        trend = {"first_half": round(f_avg, 1), "second_half": round(s_avg, 1), "pct_change": pct,
                 "direction": "improving" if pct < -2 else "worsening" if pct > 2 else "stable"}

    return {
        "period": {"start": start_date, "end": end_date},
        "summary": summary, "trend": trend, "clinical_flags": flags if flags else None, "daily": rows,
        "note": "Targets: mean <100, SD <20, TIR >90%, fasting <90. Time above 140 triggers insulin + inflammation.",
    }


def tool_get_glucose_sleep_correlation(args):
    """Correlate daily glucose with same-night Eight Sleep metrics."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    sources = parallel_query_sources(["apple_health", "eightsleep"], start_date, end_date)
    ah_items = sources.get("apple_health", [])
    es_items = sources.get("eightsleep", [])
    if not ah_items: return {"error": "No Apple Health data."}
    if not es_items: return {"error": "No Eight Sleep data."}

    es_by_date = {i.get("date"): i for i in es_items if i.get("date")}
    def _sf(v):
        if v is None: return None
        try: return float(v)
        except: return None

    SLEEP_METRICS = ["sleep_efficiency_pct", "deep_pct", "rem_pct", "sleep_score", "hrv", "time_to_sleep_min"]

    paired = []
    for item in sorted(ah_items, key=lambda x: x.get("date", "")):
        date = item.get("date")
        g_avg = _sf(item.get("blood_glucose_avg"))
        if not date or g_avg is None: continue
        sleep = es_by_date.get(date)
        if not sleep: continue
        sm_vals = {sm: _sf(sleep.get(sm)) for sm in SLEEP_METRICS}
        if sm_vals.get("sleep_efficiency_pct") is None and sm_vals.get("sleep_score") is None: continue

        bucket = "optimal_below_90" if g_avg < 90 else "normal_90_100" if g_avg < 100 else "elevated_100_110" if g_avg < 110 else "high_above_110"
        row = {"date": date, "bucket": bucket, "glucose_avg": g_avg,
               "glucose_sd": _sf(item.get("blood_glucose_std_dev")),
               "time_above_140": _sf(item.get("blood_glucose_time_above_140_pct"))}
        row.update(sm_vals)
        paired.append(row)

    if len(paired) < 5:
        return {"error": f"Only {len(paired)} paired days. Need >= 5."}

    buckets = defaultdict(list)
    for r in paired:
        buckets[r["bucket"]].append(r)

    bucket_summary = {}
    for bname, brows in sorted(buckets.items()):
        stats = {"n": len(brows)}
        for sm in SLEEP_METRICS:
            vals = [r[sm] for r in brows if r.get(sm) is not None]
            if vals: stats[f"avg_{sm}"] = round(sum(vals) / len(vals), 1)
        bucket_summary[bname] = stats

    correlations = {}
    for gm in ["glucose_avg", "glucose_sd", "time_above_140"]:
        for sm in SLEEP_METRICS:
            xs = [r[gm] for r in paired if r.get(gm) is not None and r.get(sm) is not None]
            ys = [r[sm] for r in paired if r.get(gm) is not None and r.get(sm) is not None]
            if len(xs) >= 7:
                r_val = pearson_r(xs, ys)
                if r_val is not None:
                    correlations[f"{gm}_vs_{sm}"] = round(r_val, 3)

    strong = {k: v for k, v in correlations.items() if abs(v) >= 0.2}

    return {
        "period": {"start": start_date, "end": end_date, "paired_days": len(paired)},
        "bucket_analysis": bucket_summary, "correlations": correlations,
        "notable_correlations": strong if strong else None, "daily": paired[-14:],
        "interpretation": "Negative r between glucose and sleep quality means higher glucose = worse sleep. "
                          "Time above 140 is most actionable — spikes raise core temperature, opposing deep sleep.",
    }


def tool_get_glucose_exercise_correlation(args):
    """Exercise vs rest day glucose comparison + intensity analysis."""
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    sources = parallel_query_sources(["apple_health", "strava"], start_date, end_date)
    ah_items = sources.get("apple_health", [])
    strava_items = sources.get("strava", [])
    if not ah_items: return {"error": "No Apple Health data."}

    ah_by_date = {i.get("date"): i for i in ah_items if i.get("date")}
    strava_by_date = {i.get("date"): i for i in strava_items if i.get("date")}
    def _sf(v):
        if v is None: return None
        try: return float(v)
        except: return None

    GM = ["glucose_avg", "glucose_sd", "time_in_range_pct", "time_above_140_pct", "glucose_min"]
    exercise_days = []
    rest_days = []

    for date in sorted(ah_by_date.keys()):
        ah = ah_by_date[date]
        g_avg = _sf(ah.get("blood_glucose_avg"))
        if g_avg is None: continue
        strava = strava_by_date.get(date, {})
        has_ex = int(float(strava.get("activity_count", 0))) > 0

        row = {"date": date, "glucose_avg": g_avg, "glucose_sd": _sf(ah.get("blood_glucose_std_dev")),
               "glucose_min": _sf(ah.get("blood_glucose_min")), "time_in_range_pct": _sf(ah.get("blood_glucose_time_in_range_pct")),
               "time_above_140_pct": _sf(ah.get("blood_glucose_time_above_140_pct"))}

        if has_ex:
            row["moving_time_min"] = round(float(strava.get("total_moving_time_seconds", 0)) / 60, 0)
            activities = strava.get("activities", [])
            hr_vals = [float(a["average_heartrate"]) for a in activities if a.get("average_heartrate")]
            if hr_vals: row["avg_hr"] = round(sum(hr_vals) / len(hr_vals), 0)
            exercise_days.append(row)
        else:
            rest_days.append(row)

    if not exercise_days and not rest_days:
        return {"error": "No days with both glucose + activity data."}

    comparison = {}
    for gm in GM:
        ex_v = [r[gm] for r in exercise_days if r.get(gm) is not None]
        re_v = [r[gm] for r in rest_days if r.get(gm) is not None]
        c = {}
        if ex_v: c["exercise_avg"] = round(sum(ex_v) / len(ex_v), 1); c["exercise_n"] = len(ex_v)
        if re_v: c["rest_avg"] = round(sum(re_v) / len(re_v), 1); c["rest_n"] = len(re_v)
        if ex_v and re_v:
            d = c["exercise_avg"] - c["rest_avg"]
            c["difference"] = round(d, 1)
            c["exercise_better"] = d > 0 if gm == "time_in_range_pct" else d < 0
        if c: comparison[gm] = c

    intensity = None
    hr_days = [r for r in exercise_days if r.get("avg_hr")]
    if len(hr_days) >= 5:
        easy = [r for r in hr_days if r["avg_hr"] < 140]
        hard = [r for r in hr_days if r["avg_hr"] >= 140]
        intensity = {}
        for label, grp in [("easy_below_140bpm", easy), ("hard_above_140bpm", hard)]:
            if len(grp) >= 2:
                st = {"n": len(grp)}
                for gm in GM:
                    vals = [r[gm] for r in grp if r.get(gm) is not None]
                    if vals: st[f"avg_{gm}"] = round(sum(vals) / len(vals), 1)
                intensity[label] = st

    correlations = {}
    for gm in GM:
        xs = [r.get("moving_time_min") for r in exercise_days if r.get("moving_time_min") and r.get(gm)]
        ys = [r[gm] for r in exercise_days if r.get("moving_time_min") and r.get(gm)]
        if len(xs) >= 7:
            rv = pearson_r(xs, ys)
            if rv is not None: correlations[f"duration_vs_{gm}"] = round(rv, 3)

    return {
        "period": {"start": start_date, "end": end_date,
                   "exercise_days": len(exercise_days), "rest_days": len(rest_days)},
        "exercise_vs_rest": comparison, "intensity_analysis": intensity,
        "correlations": correlations if correlations else None,
        "interpretation": "Exercise lowers glucose via GLUT4 uptake for 24-48h post. Zone 2 has strongest chronic benefit. "
                          "Look for lower avg, lower SD, higher TIR on exercise vs rest days.",
    }

'''

# Insert before TOOLS dict
anchor = "TOOLS = {"
if anchor not in content:
    print(f"ERROR: Could not find '{anchor}' in mcp_server.py")
    sys.exit(1)

content = content.replace(anchor, TOOL_FUNCTIONS + "\n" + anchor)
print("  ✅ Tool functions inserted")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Add TOOLS entries before the closing brace
# ══════════════════════════════════════════════════════════════════════════════

TOOLS_ENTRIES = '''
    # ── v2.15.0 — Gait, Energy Balance, Movement, CGM tools ─────────────────
    "get_gait_analysis": {
        "fn": tool_get_gait_analysis,
        "schema": {
            "name": "get_gait_analysis",
            "description": (
                "Gait & mobility tracker from Apple Watch. Tracks walking speed (strongest all-cause mortality "
                "predictor), step length (earliest aging marker), asymmetry (injury indicator), double support "
                "(fall risk). Composite score 0-100, clinical flags, trend analysis. <2.24 mph = clinical flag. "
                "Use for: 'gait analysis', 'walking speed trend', 'mobility health', 'injury detection'. "
                "Requires Apple Health webhook v1.1.0+."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 90d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
    "get_energy_balance": {
        "fn": tool_get_energy_balance,
        "schema": {
            "name": "get_energy_balance",
            "description": (
                "Daily energy balance: Apple Watch TDEE (active + basal cal) vs MacroFactor intake. "
                "Daily surplus/deficit, rolling averages, implied weight change. Uses real wearable data "
                "not formula BMR. Tracks deficit target hit rate. "
                "Use for: 'am I in a deficit?', 'calorie balance', 'TDEE vs intake', 'surplus or deficit?'. "
                "Requires Apple Health webhook + MacroFactor."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date":          {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":            {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                "target_deficit_kcal": {"type": "integer", "description": "Target daily deficit kcal (default: 500)."},
            }, "required": []},
        },
    },
    "get_movement_score": {
        "fn": tool_get_movement_score,
        "schema": {
            "name": "get_movement_score",
            "description": (
                "Daily movement & NEAT analysis. NEAT = energy burned outside exercise (larger than workouts "
                "for most people). Movement score 0-100, step target tracking, sedentary day flags. "
                "Use for: 'am I moving enough?', 'NEAT analysis', 'sedentary days', 'step trend', "
                "'non-exercise activity'. Requires Apple Health webhook. Strava enhances NEAT calc."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date":  {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":    {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                "step_target": {"type": "integer", "description": "Daily step target (default: 8000)."},
            }, "required": []},
        },
    },
    "get_cgm_dashboard": {
        "fn": tool_get_cgm_dashboard,
        "schema": {
            "name": "get_cgm_dashboard",
            "description": (
                "CGM blood glucose dashboard. Time in range (target >90%), variability (SD target <20), "
                "mean glucose (target <100), time above 140, fasting proxy. Clinical flags, trend analysis. "
                "Glucose management is a top-3 longevity lever (Attia, Huberman). "
                "Use for: 'glucose overview', 'CGM dashboard', 'blood sugar', 'time in range', "
                "'metabolic health', 'am I pre-diabetic?'. Requires Apple Health CGM webhook."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
    "get_glucose_sleep_correlation": {
        "fn": tool_get_glucose_sleep_correlation,
        "schema": {
            "name": "get_glucose_sleep_correlation",
            "description": (
                "Correlate glucose with same-night sleep. Buckets by glucose level, compares Eight Sleep "
                "outcomes. Pearson correlations for variability/spikes vs sleep quality. Elevated evening "
                "glucose raises core temp, opposing deep sleep (Huberman, Walker). "
                "Use for: 'does blood sugar affect sleep?', 'glucose sleep correlation', "
                "'do spikes hurt sleep?'. Requires Apple Health CGM + Eight Sleep."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 90d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
    "get_glucose_exercise_correlation": {
        "fn": tool_get_glucose_exercise_correlation,
        "schema": {
            "name": "get_glucose_exercise_correlation",
            "description": (
                "Exercise vs rest day glucose comparison. Intensity analysis (easy vs hard). Duration "
                "correlations. Zone 2 improves glucose disposal — trending this is a longevity biomarker "
                "(Attia). Exercise increases GLUT4 uptake for 24-48h. "
                "Use for: 'does exercise help blood sugar?', 'workout vs rest day glucose', "
                "'Zone 2 glucose benefit'. Requires Apple Health CGM + Strava."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 90d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
'''

# Find the last entry in TOOLS dict and insert before closing brace
# Look for the pattern: closing of get_next_lab_priorities entry + closing TOOLS brace
last_entry_pattern = '"get_next_lab_priorities"'
if last_entry_pattern not in content:
    # Fallback: find the closing brace of TOOLS
    print("  ⚠️  get_next_lab_priorities not found, using fallback pattern")

# Insert before the closing "}" of TOOLS dict
# Find the TOOLS dict closing — it's a "}" on its own line after all entries
# Strategy: find the line with just "}" after the last tool entry
lines = content.split("\n")
tools_start = None
tools_end = None
brace_depth = 0
for i, line in enumerate(lines):
    if line.strip() == "TOOLS = {":
        tools_start = i
        brace_depth = 1
        continue
    if tools_start is not None:
        brace_depth += line.count("{") - line.count("}")
        if brace_depth == 0:
            tools_end = i
            break

if tools_end is None:
    print("ERROR: Could not find end of TOOLS dict")
    sys.exit(1)

# Insert new entries before the closing brace
lines.insert(tools_end, TOOLS_ENTRIES)
content = "\n".join(lines)
print(f"  ✅ TOOLS entries inserted at line {tools_end}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Update version
# ══════════════════════════════════════════════════════════════════════════════

content = content.replace('"version": "2.14.0"', '"version": "2.15.0"')
content = content.replace("life-platform MCP Server v2.14.0", "life-platform MCP Server v2.15.0")
print("  ✅ Version updated to 2.15.0")

# ── Update SOT defaults to include new domains ──
old_sot = '''    "body_battery":"garmin",        # Energy reserve metric — Garmin (unique to platform)
}'''
new_sot = '''    "body_battery":"garmin",        # Energy reserve metric — Garmin (unique to platform)
    "gait":        "apple_health",  # Gait & mobility — Apple Watch exclusive
    "energy_expenditure": "apple_health",  # TDEE from Apple Watch (active + basal)
    "cgm":         "apple_health",  # Continuous glucose monitoring — Dexcom Stelo via HealthKit
}'''
content = content.replace(old_sot, new_sot)
print("  ✅ SOT defaults updated")

# ── Write ──
with open(MCP_FILE, "w") as f:
    f.write(content)

print(f"\n✅ MCP server patched to v2.15.0 — 6 new tools added")
print("   Run deploy script to push to Lambda.")
