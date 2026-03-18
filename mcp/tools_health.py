"""
Health & body composition tools.
"""
import json
import math
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from decimal import Decimal

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
from mcp.labs_helpers import (
    _get_genome_cached, _query_all_lab_draws, _query_dexa_scans,
    _query_lab_meta, _genome_context_for_biomarkers,
)
from mcp.strength_helpers import classify_exercise
from mcp.tools_training import tool_get_training_load
from mcp.helpers import normalize_whoop_sleep
def tool_get_health_dashboard(args):
    today     = datetime.utcnow().strftime("%Y-%m-%d")
    d30_start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    d7_start  = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    dashboard = {"as_of": today, "alerts": []}

    whoop_recent = query_source("whoop", d7_start, today)
    whoop_today  = next((w for w in sorted(whoop_recent, key=lambda x: x.get("date",""), reverse=True)
                         if w.get("recovery_score") is not None), None)
    if whoop_today:
        rec  = whoop_today.get("recovery_score")
        hrv  = whoop_today.get("hrv")
        rhr  = whoop_today.get("resting_heart_rate")
        slp  = whoop_today.get("sleep_duration_hours")
        dashboard["readiness"] = {
            "date":                  whoop_today.get("date"),
            "recovery_score":        rec,
            "hrv_ms":                hrv,
            "resting_heart_rate":    rhr,
            "sleep_hours":           slp,
            "recovery_status":       "green" if rec and rec >= 67 else ("yellow" if rec and rec >= 34 else "red"),
        }
        if rec is not None and rec < 34:
            dashboard["alerts"].append(f"⚠️ Recovery score {rec} — very low. Prioritise rest today.")
        if slp is not None and slp < 6:
            dashboard["alerts"].append(f"⚠️ Sleep {slp}h last night — below minimum threshold.")

    try:
        load_result = tool_get_training_load({"end_date": today, "start_date": d30_start})
        if "current_state" in load_result:
            cs = load_result["current_state"]
            dashboard["training_load"] = {
                "ctl_fitness":  cs["ctl_fitness"],
                "atl_fatigue":  cs["atl_fatigue"],
                "tsb_form":     cs["tsb_form"],
                "acwr":         cs["acwr"],
                "form_status":  cs["form_status"],
                "injury_risk":  cs["injury_risk"],
            }
            if cs.get("acwr") and cs["acwr"] > 1.3:
                dashboard["alerts"].append(f"⚠️ ACWR {cs['acwr']} — training load spike. Injury risk elevated.")
    except Exception as e:
        logger.warning(f"Training load failed in dashboard: {e}")

    strava_7d = query_source("strava", d7_start, today)
    if strava_7d:
        miles_7d = sum(float(d.get("total_distance_miles") or 0) for d in strava_7d)
        elev_7d  = sum(float(d.get("total_elevation_gain_feet") or 0) for d in strava_7d)
        acts_7d  = sum(int(d.get("activity_count") or 0) for d in strava_7d)
        dashboard["last_7_days"] = {
            "total_miles":      round(miles_7d, 1),
            "total_elev_feet":  round(elev_7d, 0),
            "activity_count":   acts_7d,
        }

    strava_30d = query_source("strava", d30_start, today)
    if strava_30d:
        miles_30d = sum(float(d.get("total_distance_miles") or 0) for d in strava_30d)
        elev_30d  = sum(float(d.get("total_elevation_gain_feet") or 0) for d in strava_30d)
        acts_30d  = sum(int(d.get("activity_count") or 0) for d in strava_30d)
        dashboard["last_30_days"] = {
            "total_miles":     round(miles_30d, 1),
            "total_elev_feet": round(elev_30d, 0),
            "activity_count":  acts_30d,
            "avg_miles_per_week": round(miles_30d / 4, 1),
        }

    trends = {}

    whoop_30d = query_source("whoop", d30_start, today)
    if whoop_30d:
        sorted_w = sorted(whoop_30d, key=lambda x: x.get("date", ""))
        hrv_vals = [float(w["hrv"]) for w in sorted_w if w.get("hrv") is not None]
        rhr_vals = [float(w["resting_heart_rate"]) for w in sorted_w if w.get("resting_heart_rate") is not None]
        rec_vals = [float(w["recovery_score"]) for w in sorted_w if w.get("recovery_score") is not None]
        if hrv_vals:
            half = len(hrv_vals) // 2
            hrv_trend = "improving" if sum(hrv_vals[half:])/len(hrv_vals[half:]) > sum(hrv_vals[:half])/len(hrv_vals[:half]) else "declining"
            trends["hrv_30d"] = {"avg": round(sum(hrv_vals)/len(hrv_vals), 1), "trend": hrv_trend, "n_days": len(hrv_vals)}
        if rhr_vals:
            half = len(rhr_vals) // 2
            rhr_trend = "improving" if sum(rhr_vals[half:])/len(rhr_vals[half:]) < sum(rhr_vals[:half])/len(rhr_vals[:half]) else "declining"
            trends["rhr_30d"] = {"avg": round(sum(rhr_vals)/len(rhr_vals), 1), "trend": rhr_trend, "n_days": len(rhr_vals)}
        if rec_vals:
            trends["recovery_30d"] = {"avg": round(sum(rec_vals)/len(rec_vals), 1), "n_days": len(rec_vals)}

    withings_30d = query_source("withings", d30_start, today)
    if withings_30d:
        sorted_wi = sorted(withings_30d, key=lambda x: x.get("date", ""))
        wt_vals   = [float(w["weight_lbs"]) for w in sorted_wi if w.get("weight_lbs") is not None]
        if wt_vals:
            wt_trend = "increasing" if wt_vals[-1] > wt_vals[0] else "decreasing"
            trends["weight_30d"] = {
                "current": wt_vals[-1],
                "start_of_period": wt_vals[0],
                "change_lbs": round(wt_vals[-1] - wt_vals[0], 1),
                "trend": wt_trend,
            }

    dashboard["biomarker_trends"] = trends
    dashboard["alert_count"] = len(dashboard["alerts"])
    if not dashboard["alerts"]:
        dashboard["alerts"] = ["✅ No alerts — all indicators within normal ranges."]

    return dashboard


def tool_get_readiness_score(args):
    """
    Unified readiness score (0–100) synthesising Whoop recovery, Whoop sleep quality,
    HRV 7-day trend, TSB training form, and Garmin Body Battery into a single
    GREEN / YELLOW / RED signal with a 1-line actionable recommendation.

    Weights:
      Whoop recovery score  : 35%
      Whoop sleep quality    : 25%
      HRV 7-day trend       : 20%
      TSB training form     : 10%
      Garmin Body Battery   : 10%

    If a component is unavailable, remaining weights are re-normalised so the
    score is still meaningful with partial data.

    Device agreement: Whoop vs Garmin HRV and RHR delta is computed and returned
    as a confidence signal — large disagreement flags lower score reliability.
    """
    end_date   = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start   = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d30_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    d90_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    components = {}

    # ── 1. Whoop recovery score (40%) ─────────────────────────────────────────
    whoop_recent = query_source("whoop", d7_start, end_date)
    whoop_sorted = sorted(whoop_recent, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today  = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)

    if whoop_today:
        rec_score = float(whoop_today["recovery_score"])
        components["whoop_recovery"] = {
            "score":        round(rec_score, 1),
            "weight":       0.35,
            "raw": {
                "date":           whoop_today.get("date"),
                "recovery_score": whoop_today.get("recovery_score"),
                "hrv_ms":         whoop_today.get("hrv"),
                "resting_hr":     whoop_today.get("resting_heart_rate"),
                "sleep_hours":    whoop_today.get("sleep_duration_hours"),
            },
        }

    # ── 2. Sleep quality score (25%) ─ Whoop SOT v2.55.0 ────────────────────────
    sleep_raw    = query_source("whoop", d7_start, end_date)
    sleep_recent = [normalize_whoop_sleep(i) for i in sleep_raw]
    sleep_sorted = sorted(sleep_recent, key=lambda x: x.get("date", ""), reverse=True)
    sleep_today  = next((s for s in sleep_sorted
                         if s.get("sleep_score") is not None or s.get("sleep_efficiency_pct") is not None), None)

    if sleep_today:
        # Prefer native sleep_score (0-100); fallback: derive from efficiency
        if sleep_today.get("sleep_score") is not None:
            es_score = float(sleep_today["sleep_score"])
            es_method = "sleep_score"
        else:
            eff = float(sleep_today["sleep_efficiency_pct"])
            # 75% eff → ~50 score; 85% → ~70; 95% → ~90 (linear: score = eff - 25)
            es_score  = _clamp(eff - 25.0)
            es_method = "derived_from_efficiency"

        components["sleep_quality"] = {
            "score":   round(es_score, 1),
            "weight":  0.25,
            "raw": {
                "date":                sleep_today.get("date"),
                "sleep_score":         sleep_today.get("sleep_score"),
                "sleep_efficiency_pct": sleep_today.get("sleep_efficiency_pct"),
                "sleep_duration_hours": sleep_today.get("sleep_duration_hours"),
                "rem_pct":             sleep_today.get("rem_pct"),
                "deep_pct":            sleep_today.get("deep_pct"),
                "scoring_method":      es_method,
            },
        }

    # ── 3. HRV 7-day trend vs 30-day baseline (20%) ───────────────────────────
    whoop_30d = query_source("whoop", d30_start, end_date)
    hrv_30d   = [float(w["hrv"]) for w in whoop_30d if w.get("hrv") is not None]
    hrv_7d    = [float(w["hrv"]) for w in whoop_recent if w.get("hrv") is not None]

    if len(hrv_30d) >= 7 and hrv_7d:
        baseline  = sum(hrv_30d) / len(hrv_30d)
        recent7   = sum(hrv_7d) / len(hrv_7d)
        ratio     = recent7 / baseline if baseline > 0 else 1.0
        trend_pct = round((ratio - 1.0) * 100, 1)
        # ratio=1.0 → 60, +10% → 80, -10% → 40
        hrv_score = _clamp(60.0 + (ratio - 1.0) * 200.0)

        components["hrv_trend"] = {
            "score":  round(hrv_score, 1),
            "weight": 0.20,
            "raw": {
                "hrv_7d_avg_ms":      round(recent7, 1),
                "hrv_30d_baseline_ms": round(baseline, 1),
                "trend_pct":          trend_pct,
                "trend_direction":    "above_baseline" if trend_pct > 3 else ("below_baseline" if trend_pct < -3 else "at_baseline"),
                "n_days_30d":         len(hrv_30d),
                "n_days_7d":          len(hrv_7d),
            },
        }

    # ── 4. TSB training form (10%) ────────────────────────────────────────────
    try:
        load_result = tool_get_training_load({"end_date": end_date})
        if "current_state" in load_result:
            cs  = load_result["current_state"]
            tsb = cs.get("tsb_form", 0.0)
            # TSB=0 → 70, +5 → 82.5, +10 → 95, -10 → 45, -20 → 20
            tsb_score = _clamp(70.0 + float(tsb) * 2.5)
            components["training_form"] = {
                "score":  round(tsb_score, 1),
                "weight": 0.10,
                "raw": {
                    "tsb_form":    cs.get("tsb_form"),
                    "ctl_fitness": cs.get("ctl_fitness"),
                    "atl_fatigue": cs.get("atl_fatigue"),
                    "acwr":        cs.get("acwr"),
                    "form_status": cs.get("form_status"),
                },
            }
    except Exception as e:
        logger.warning(f"get_readiness_score: TSB failed — {e}")

    # ── 5. Garmin Body Battery (10%) ──────────────────────────────────────────
    garmin_recent = query_source("garmin", d7_start, end_date)
    garmin_sorted = sorted(garmin_recent, key=lambda x: x.get("date", ""), reverse=True)
    garmin_today  = next((g for g in garmin_sorted
                          if g.get("body_battery_end") is not None or g.get("body_battery_high") is not None), None)

    if garmin_today:
        # Use end-of-day Body Battery as primary; fall back to high if end is missing
        bb = garmin_today.get("body_battery_end") or garmin_today.get("body_battery_high")
        if bb is not None:
            bb_score = _clamp(float(bb))  # Body Battery is already 0-100
            components["garmin_body_battery"] = {
                "score":  round(bb_score, 1),
                "weight": 0.10,
                "raw": {
                    "date":               garmin_today.get("date"),
                    "body_battery_end":   garmin_today.get("body_battery_end"),
                    "body_battery_high":  garmin_today.get("body_battery_high"),
                    "body_battery_low":   garmin_today.get("body_battery_low"),
                    "avg_stress":         garmin_today.get("avg_stress"),
                    "hrv_last_night":     garmin_today.get("hrv_last_night"),
                    "hrv_status":         garmin_today.get("hrv_status"),
                },
            }

    # ── Device agreement: Whoop vs Garmin cross-validation ───────────────────
    device_agreement = None
    if "whoop_recovery" in components and garmin_today is not None:
        whoop_hrv_val  = components["whoop_recovery"]["raw"].get("hrv_ms")
        garmin_hrv_val = garmin_today.get("hrv_last_night")
        whoop_rhr_val  = components["whoop_recovery"]["raw"].get("resting_hr")
        garmin_rhr_val = garmin_today.get("resting_heart_rate")

        checks = {}
        agreement_signals = []

        if whoop_hrv_val is not None and garmin_hrv_val is not None:
            hrv_diff = abs(float(whoop_hrv_val) - float(garmin_hrv_val))
            hrv_status = "agree" if hrv_diff <= 10 else ("minor_variance" if hrv_diff <= 20 else "flag")
            checks["hrv"] = {
                "whoop_ms": round(float(whoop_hrv_val), 1),
                "garmin_ms": round(float(garmin_hrv_val), 1),
                "delta_ms": round(float(whoop_hrv_val) - float(garmin_hrv_val), 1),
                "status": hrv_status,
            }
            agreement_signals.append(hrv_status)

        if whoop_rhr_val is not None and garmin_rhr_val is not None:
            rhr_diff = abs(float(whoop_rhr_val) - float(garmin_rhr_val))
            rhr_status = "agree" if rhr_diff <= 3 else ("minor_variance" if rhr_diff <= 6 else "flag")
            checks["rhr"] = {
                "whoop_bpm": round(float(whoop_rhr_val), 1),
                "garmin_bpm": round(float(garmin_rhr_val), 1),
                "delta_bpm": round(float(whoop_rhr_val) - float(garmin_rhr_val), 1),
                "status": rhr_status,
            }
            agreement_signals.append(rhr_status)

        if agreement_signals:
            has_flag = any(s == "flag" for s in agreement_signals)
            all_agree = all(s == "agree" for s in agreement_signals)
            confidence = "high" if all_agree else ("low" if has_flag else "moderate")
            device_agreement = {
                "confidence": confidence,
                "checks": checks,
                "note": "flag = significant inter-device disagreement; readiness score may be less reliable on flagged days",
            }

    # ── Weighted aggregate ────────────────────────────────────────────────────
    total_weight = sum(c["weight"] for c in components.values())

    if not components:
        return {"error": "No data available from any source for this date. Check ingestion pipeline."}

    raw_score = sum(c["score"] * c["weight"] for c in components.values()) / total_weight
    readiness_score = round(raw_score, 1)

    # Label
    if readiness_score >= 70:
        label = "GREEN"
    elif readiness_score >= 40:
        label = "YELLOW"
    else:
        label = "RED"

    # ── Recommendation ────────────────────────────────────────────────────────
    missing = []
    all_keys = {"whoop_recovery", "sleep_quality", "hrv_trend", "training_form", "garmin_body_battery"}
    for k in sorted(all_keys - set(components.keys())):
        missing.append(k.replace("_", " "))

    # Build context-aware recommendation
    rec_parts = []

    if label == "GREEN":
        rec_parts.append("You're primed — go ahead with your planned hard session.")
        if "training_form" in components and components["training_form"]["raw"].get("tsb_form", 0) > 8:
            rec_parts.append("TSB is notably positive, meaning you're very fresh — a good day for a PR attempt or race effort.")
    elif label == "YELLOW":
        rec_parts.append("Moderate readiness — a controlled effort is appropriate; skip high-intensity intervals.")
        if "whoop_recovery" in components and components["whoop_recovery"]["score"] < 50:
            rec_parts.append("Whoop recovery is low — prioritise aerobic work over heavy strength training today.")
        if "sleep_quality" in components and components["sleep_quality"]["score"] < 50:
            rec_parts.append("Sleep quality was below average — consider a shorter session and extra cool-down.")
    else:  # RED
        rec_parts.append("Recovery day. Hard training now will deepen fatigue without adding fitness.")
        if "hrv_trend" in components and components["hrv_trend"]["raw"]["trend_pct"] < -10:
            rec_parts.append("HRV is trending meaningfully below your baseline — this is your body asking for rest.")

    recommendation = " ".join(rec_parts)

    return {
        "date":             end_date,
        "readiness_score":  readiness_score,
        "label":            label,
        "recommendation":   recommendation,
        "components":       components,
        "device_agreement": device_agreement,
        "data_completeness": "full" if total_weight >= 0.99 else f"partial ({round(total_weight*100)}% weight covered)",
        "missing_components": missing if missing else None,
        "scoring_note":     (
            "Weights: Whoop recovery 35%, Whoop sleep quality 25%, HRV 7d trend 20%, TSB form 10%, "
            "Garmin Body Battery 10%. Missing components are excluded and remaining weights re-normalised."
        ),
        # R13-F09: Medical disclaimer on all health-assessment tool responses
        "_disclaimer": "For personal health tracking only. Not medical advice. Consult a qualified healthcare provider before making health decisions based on this data.",
    }


def tool_get_weight_loss_progress(args):
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", "2010-01-01")
    profile    = get_profile()

    journey_start      = profile.get("journey_start_date")
    journey_start_wt   = profile.get("journey_start_weight_lbs")
    goal_weight        = profile.get("goal_weight_lbs")
    target_weekly_loss = profile.get("target_weekly_loss_lbs", 1.5)
    height_in          = profile.get("height_inches", 70)
    dob_str            = profile.get("date_of_birth")

    effective_start = journey_start if journey_start else start_date

    withings_items = query_source("withings", effective_start, end_date)
    if not withings_items:
        return {"error": "No Withings weight data found. Ensure scale is syncing."}

    weight_series = []
    for item in sorted(withings_items, key=lambda x: x.get("date", "")):
        wt = item.get("weight_lbs")
        if wt is not None:
            weight_series.append({"date": item["date"], "weight_lbs": round(float(wt), 1)})

    if not weight_series:
        return {"error": "No weight_lbs field found in Withings data."}

    def calc_bmi(weight_lbs, height_in):
        if not height_in:
            return None
        return round(703 * weight_lbs / (height_in ** 2), 1)

    bmi_categories = [
        (18.5, "Underweight"),
        (25.0, "Normal weight"),
        (30.0, "Overweight"),
        (35.0, "Obese Class I"),
        (40.0, "Obese Class II"),
        (float("inf"), "Obese Class III"),
    ]

    def bmi_category(bmi):
        if bmi is None:
            return None
        for threshold, label in bmi_categories:
            if bmi < threshold:
                return label
        return "Obese Class III"

    for pt in weight_series:
        bmi = calc_bmi(pt["weight_lbs"], height_in)
        pt["bmi"]          = bmi
        pt["bmi_category"] = bmi_category(bmi)

    weekly_rates = []
    for i in range(len(weight_series)):
        pt = weight_series[i]
        target_dt = datetime.strptime(pt["date"], "%Y-%m-%d") - timedelta(days=7)
        prior = None
        best_gap = 999
        for j in range(i):
            d = datetime.strptime(weight_series[j]["date"], "%Y-%m-%d")
            gap = abs((target_dt - d).days)
            if gap < best_gap:
                best_gap = gap
                prior = weight_series[j]
        if prior and best_gap <= 4:
            days_diff = (datetime.strptime(pt["date"], "%Y-%m-%d") -
                         datetime.strptime(prior["date"], "%Y-%m-%d")).days
            if days_diff > 0:
                weekly_rate = round((prior["weight_lbs"] - pt["weight_lbs"]) / days_diff * 7, 2)
                pt["weekly_loss_rate_lbs"] = weekly_rate
                weekly_rates.append(weekly_rate)
                if weekly_rate > 2.5:
                    pt["rate_flag"] = "⚠️ Losing too fast (>2.5 lbs/wk) — risk of muscle loss. Check nutrition."
                elif weekly_rate < 0:
                    pt["rate_flag"] = "↑ Weight gain this week"
                elif weekly_rate < 0.25 and len(weight_series) > 14:
                    pt["rate_flag"] = "⏸ Very slow — review deficit"

    milestones = {}
    milestone_thresholds = [
        (40.0, "🎯 Exited Obese Class III → Class II (BMI < 40)"),
        (35.0, "🎯 Exited Obese Class II → Class I (BMI < 35)"),
        (30.0, "🎯 Exited Obese → Overweight (BMI < 30)"),
        (25.0, "🎯 Reached Normal Weight (BMI < 25)"),
    ]
    prev_bmi = None
    for pt in weight_series:
        bmi = pt.get("bmi")
        if bmi is None or prev_bmi is None:
            prev_bmi = bmi
            continue
        for threshold, label in milestone_thresholds:
            key = f"bmi_{threshold}"
            if key not in milestones and prev_bmi >= threshold > bmi:
                milestones[key] = {"date": pt["date"], "milestone": label, "bmi": bmi, "weight_lbs": pt["weight_lbs"]}
        prev_bmi = bmi

    current_bmi = weight_series[-1].get("bmi")
    upcoming_milestones = []
    if current_bmi:
        for threshold, label in sorted(milestone_thresholds, key=lambda x: x[0], reverse=True):
            if current_bmi >= threshold:
                lbs_to_threshold = round((threshold - 0.1) * (height_in ** 2) / 703 - weight_series[-1]["weight_lbs"], 1) * -1
                upcoming_milestones.append({
                    "milestone":          label,
                    "lbs_to_cross":       round(lbs_to_threshold, 1),
                    "weeks_at_current_pace": round(lbs_to_threshold / max(sum(weekly_rates[-4:]) / max(len(weekly_rates[-4:]), 1), 0.1), 1) if weekly_rates else None,
                })
                break

    plateau = None
    recent_14 = [pt for pt in weight_series
                 if (datetime.utcnow() - datetime.strptime(pt["date"], "%Y-%m-%d")).days <= 14]
    if len(recent_14) >= 3:
        wts = [pt["weight_lbs"] for pt in recent_14]
        spread = max(wts) - min(wts)
        if spread < 1.5:
            plateau = {
                "detected":  True,
                "duration_days": 14,
                "weight_range_lbs": spread,
                "note": "Scale has moved less than 1.5 lbs in 14 days. This is normal — check training load and sleep quality before changing nutrition.",
            }

    start_weight   = weight_series[0]["weight_lbs"]
    current_weight = weight_series[-1]["weight_lbs"]
    total_lost     = round(start_weight - current_weight, 1)
    avg_weekly     = round(sum(weekly_rates) / len(weekly_rates), 2) if weekly_rates else None

    projection = None
    if goal_weight and avg_weekly and avg_weekly > 0:
        weeks_remaining = (current_weight - goal_weight) / avg_weekly
        goal_date = datetime.utcnow() + timedelta(weeks=weeks_remaining)
        projection = {
            "goal_weight_lbs":       goal_weight,
            "lbs_remaining":         round(current_weight - goal_weight, 1),
            "avg_weekly_loss_lbs":   avg_weekly,
            "projected_goal_date":   goal_date.strftime("%Y-%m-%d"),
            "weeks_remaining":       round(weeks_remaining, 1),
        }
        if journey_start_wt:
            pct_complete = round(100 * (journey_start_wt - current_weight) / (journey_start_wt - goal_weight), 1)
            projection["pct_complete"] = pct_complete

    return {
        "journey_start_date":   journey_start,
        "journey_start_weight": journey_start_wt,
        "current_weight_lbs":   current_weight,
        "current_bmi":          weight_series[-1].get("bmi"),
        "current_bmi_category": weight_series[-1].get("bmi_category"),
        "total_lost_lbs":       total_lost,
        "avg_weekly_loss_lbs":  avg_weekly,
        "projection":           projection,
        "plateau_detected":     plateau,
        "milestones_achieved":  milestones,
        "next_milestone":       upcoming_milestones[0] if upcoming_milestones else None,
        "weight_series":        weight_series,
        "clinical_note":        "Safe loss rate: 0.5–2.0 lbs/week. >2.5 lbs/week consistently risks lean mass catabolism.",
    }


def tool_get_body_composition_trend(args):
    start_date = args.get("start_date", "2010-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    profile    = get_profile()
    journey_start = profile.get("journey_start_date", start_date)
    height_in     = profile.get("height_inches", 70)

    effective_start = journey_start if journey_start < start_date else start_date
    items = query_source("withings", effective_start, end_date)
    if not items:
        return {"error": "No Withings data found."}

    series = []
    for item in sorted(items, key=lambda x: x.get("date", "")):
        wt  = item.get("weight_lbs")
        bf  = item.get("body_fat_percentage")
        mm  = item.get("muscle_mass_lbs")
        bm  = item.get("bone_mass_lbs")
        visc= item.get("visceral_fat_index")
        if wt is None:
            continue
        wt = float(wt)
        pt  = {"date": item["date"], "weight_lbs": round(wt, 1)}
        if bf is not None:
            bf = float(bf)
            fat_lbs  = round(wt * bf / 100, 1)
            lean_lbs = round(wt - fat_lbs, 1)
            pt["body_fat_pct"]   = round(bf, 1)
            pt["fat_mass_lbs"]   = fat_lbs
            pt["lean_mass_lbs"]  = lean_lbs
            lean_kg   = lean_lbs * 0.453592
            height_m  = height_in * 0.0254
            pt["ffmi"] = round(lean_kg / (height_m ** 2), 1)
        if mm  is not None: pt["muscle_mass_lbs"]     = round(float(mm), 1)
        if bm  is not None: pt["bone_mass_lbs"]       = round(float(bm), 1)
        if visc is not None: pt["visceral_fat_index"] = round(float(visc), 1)
        series.append(pt)

    if not series:
        return {"error": "Weight data present but no body composition fields. Check Withings ingestor captures these fields."}

    has_composition = any("body_fat_pct" in pt for pt in series)
    summary = {"has_composition_data": has_composition}

    if has_composition:
        first_comp = next((pt for pt in series if "body_fat_pct" in pt), None)
        last_comp  = next((pt for pt in reversed(series) if "body_fat_pct" in pt), None)

        if first_comp and last_comp and first_comp["date"] != last_comp["date"]:
            wt_change   = round(last_comp["weight_lbs"]  - first_comp["weight_lbs"],  1)
            fat_change  = round(last_comp["fat_mass_lbs"] - first_comp["fat_mass_lbs"], 1) if "fat_mass_lbs" in last_comp and "fat_mass_lbs" in first_comp else None
            lean_change = round(last_comp["lean_mass_lbs"] - first_comp["lean_mass_lbs"], 1) if "lean_mass_lbs" in last_comp and "lean_mass_lbs" in first_comp else None

            summary["from_date"]           = first_comp["date"]
            summary["to_date"]             = last_comp["date"]
            summary["total_weight_change"] = wt_change
            summary["fat_mass_change_lbs"] = fat_change
            summary["lean_mass_change_lbs"]= lean_change

            if fat_change is not None and wt_change != 0:
                pct_fat_of_loss = round(100 * fat_change / wt_change, 1)
                summary["pct_of_loss_that_is_fat"] = pct_fat_of_loss
                if pct_fat_of_loss < 60:
                    summary["composition_alert"] = f"⚠️ Only {pct_fat_of_loss}% of weight lost is fat. Increase protein intake and resistance training to protect lean mass."
                else:
                    summary["composition_status"] = f"✅ {pct_fat_of_loss}% of weight lost is fat — good composition preservation."

    lean_loss_events = []
    prev = None
    for pt in series:
        if "lean_mass_lbs" not in pt:
            prev = pt
            continue
        if prev and "lean_mass_lbs" in prev:
            lean_delta = pt["lean_mass_lbs"] - prev["lean_mass_lbs"]
            if lean_delta < -2.0:
                lean_loss_events.append({
                    "date":           pt["date"],
                    "lean_lost_lbs":  round(abs(lean_delta), 1),
                    "flag":           "⚠️ Significant lean mass loss — check protein intake and training volume",
                })
        prev = pt

    # Board rec 1C: Lean mass velocity — 14-day rolling delta (Attia)
    lean_velocity = {}
    lean_pts = [(pt["date"], pt["lean_mass_lbs"]) for pt in series if "lean_mass_lbs" in pt]
    if len(lean_pts) >= 2:
        # Find data point closest to 14 days before the latest
        latest_date_str, latest_lean = lean_pts[-1]
        latest_dt = datetime.strptime(latest_date_str, "%Y-%m-%d")
        target_dt = latest_dt - timedelta(days=14)
        closest = min(lean_pts[:-1], key=lambda p: abs((datetime.strptime(p[0], "%Y-%m-%d") - target_dt).days))
        days_span = (latest_dt - datetime.strptime(closest[0], "%Y-%m-%d")).days
        if 7 <= days_span <= 28:  # reasonable window
            delta = round(latest_lean - closest[1], 2)
            weekly_rate = round(delta / (days_span / 7), 2)
            lean_velocity = {
                "from_date": closest[0],
                "to_date": latest_date_str,
                "days_span": days_span,
                "lean_delta_lbs": delta,
                "lean_rate_lbs_per_week": weekly_rate,
            }
            if weekly_rate < -0.5:
                lean_velocity["alert"] = f"\u26a0\ufe0f Losing {abs(weekly_rate)} lbs lean mass/week \u2014 increase protein and resistance training volume."
            elif weekly_rate > 0.1:
                lean_velocity["status"] = f"\u2705 Gaining lean mass (+{weekly_rate} lbs/week) during cut \u2014 excellent recomposition."
            else:
                lean_velocity["status"] = "Lean mass stable \u2014 good preservation during deficit."

    return {
        "summary":          summary,
        "lean_mass_velocity": lean_velocity,
        "lean_loss_events": lean_loss_events,
        "series":           series,
        "coaching_note":    "Target: >80% of weight lost should be fat. Protect lean mass with 0.7-1g protein per lb bodyweight and 2-3x resistance sessions/week.",
    }


def tool_get_energy_expenditure(args):
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    d30_start  = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    d7_start   = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    profile    = get_profile()

    height_in  = profile.get("height_inches", 70)
    dob_str    = profile.get("date_of_birth")
    sex        = profile.get("biological_sex", "male").lower()
    target_deficit_kcal = args.get("target_deficit_kcal", 500)

    withings_recent = query_source("withings", d7_start, end_date)
    current_weight_lbs = None
    for item in sorted(withings_recent, key=lambda x: x.get("date", ""), reverse=True):
        if item.get("weight_lbs"):
            current_weight_lbs = float(item["weight_lbs"])
            current_weight_date = item["date"]
            break

    if current_weight_lbs is None:
        return {"error": "No recent weight data. Ensure Withings is syncing."}

    weight_kg  = current_weight_lbs * 0.453592
    height_cm  = height_in * 2.54
    age_years  = None
    if dob_str:
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d")
            age_years = (datetime.utcnow() - dob).days / 365.25
        except Exception:
            pass
    age_years = age_years or 35

    if sex == "female":
        bmr = round(10 * weight_kg + 6.25 * height_cm - 5 * age_years - 161, 0)
    else:
        bmr = round(10 * weight_kg + 6.25 * height_cm - 5 * age_years + 5, 0)

    def exercise_kcal_from_strava(strava_items):
        total_kj   = sum(float(d.get("total_kilojoules") or 0) for d in strava_items)
        total_time = sum(float(d.get("total_moving_time_seconds") or 0) for d in strava_items)
        if total_kj > 0:
            return round(total_kj * 1.0, 0)
        hours = total_time / 3600
        return round(6 * weight_kg * hours, 0)

    strava_7d  = query_source("strava", d7_start, end_date)
    strava_30d = query_source("strava", d30_start, end_date)

    ex_kcal_7d       = exercise_kcal_from_strava(strava_7d)
    ex_kcal_30d      = exercise_kcal_from_strava(strava_30d)
    ex_daily_7d_avg  = round(ex_kcal_7d / 7, 0)
    ex_daily_30d_avg = round(ex_kcal_30d / 30, 0)

    tdee_7d_avg  = round(bmr + ex_daily_7d_avg, 0)
    tdee_30d_avg = round(bmr + ex_daily_30d_avg, 0)
    calorie_target_7d  = round(tdee_7d_avg  - target_deficit_kcal, 0)
    calorie_target_30d = round(tdee_30d_avg - target_deficit_kcal, 0)
    implied_weekly_loss_lbs = round(target_deficit_kcal * 7 / 3500, 2)

    journey_start_wt = profile.get("journey_start_weight_lbs")
    bmr_change = None
    if journey_start_wt:
        start_kg  = float(journey_start_wt) * 0.453592
        if sex == "female":
            bmr_start = round(10 * start_kg + 6.25 * height_cm - 5 * age_years - 161, 0)
        else:
            bmr_start = round(10 * start_kg + 6.25 * height_cm - 5 * age_years + 5, 0)
        bmr_change = {
            "bmr_at_start_weight": bmr_start,
            "bmr_now":             bmr,
            "bmr_reduction_kcal":  round(bmr_start - bmr, 0),
            "note": "BMR decreases as you lose weight — this is normal metabolic adaptation. Deficit targets should be recalculated every 10 lbs lost.",
        }

    return {
        "as_of_date":              end_date,
        "current_weight_lbs":      current_weight_lbs,
        "current_weight_date":     current_weight_date,
        "bmr_formula":             "Mifflin-St Jeor",
        "bmr_kcal":                bmr,
        "exercise_kcal_7d_daily_avg":  ex_daily_7d_avg,
        "exercise_kcal_30d_daily_avg": ex_daily_30d_avg,
        "tdee_7d_avg":             tdee_7d_avg,
        "tdee_30d_avg":            tdee_30d_avg,
        "target_deficit_kcal":     target_deficit_kcal,
        "calorie_target_based_on_7d":  calorie_target_7d,
        "calorie_target_based_on_30d": calorie_target_30d,
        "implied_weekly_loss_lbs": implied_weekly_loss_lbs,
        "bmr_change_since_start":  bmr_change,
        "coaching_note":           "Recalculate targets every 10 lbs lost as BMR decreases. Eating below 1200 kcal (women) or 1500 kcal (men) risks lean mass loss even with adequate protein.",
    }


def tool_get_non_scale_victories(args):
    end_date    = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    profile     = get_profile()
    journey_start = profile.get("journey_start_date")

    if not journey_start:
        return {"error": "journey_start_date not set in profile. Run seed_profile.py to add it."}

    js_dt          = datetime.strptime(journey_start, "%Y-%m-%d")
    baseline_start = journey_start
    baseline_end   = (js_dt + timedelta(days=30)).strftime("%Y-%m-%d")
    recent_start   = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    victories = []
    comparisons = {}

    whoop_base   = query_source("whoop", baseline_start, baseline_end)
    whoop_recent = query_source("whoop", recent_start, end_date)

    def whoop_avg(items, field):
        vals = [float(i[field]) for i in items if i.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    whoop_fields = [
        ("resting_heart_rate", "Resting Heart Rate", "bpm", "lower_is_better"),
        ("hrv",                "HRV",                "ms",  "higher_is_better"),
        ("recovery_score",     "Recovery Score",     "%",   "higher_is_better"),
        ("sleep_duration_hours","Sleep Duration",    "hrs", "higher_is_better"),
    ]

    for field, label, unit, direction in whoop_fields:
        base_avg   = whoop_avg(whoop_base,   field)
        recent_avg = whoop_avg(whoop_recent, field)
        if base_avg is None or recent_avg is None:
            continue
        delta = round(recent_avg - base_avg, 1)
        improved = (delta < 0) if direction == "lower_is_better" else (delta > 0)
        comparisons[field] = {
            "label":    label,
            "unit":     unit,
            "baseline": base_avg,
            "current":  recent_avg,
            "change":   delta,
            "improved": improved,
        }
        if improved and abs(delta) > 1:
            victories.append(f"✅ {label}: {'+' if delta > 0 else ''}{delta} {unit} vs journey start")

    strava_base   = query_source("strava", baseline_start, baseline_end)
    strava_recent = query_source("strava", recent_start, end_date)

    def strava_sum(items, field):
        return round(sum(float(i.get(field) or 0) for i in items), 1)

    def strava_count(items):
        return sum(int(i.get("activity_count") or 0) for i in items)

    base_acts   = strava_count(strava_base)
    recent_acts = strava_count(strava_recent)
    base_miles  = strava_sum(strava_base,   "total_distance_miles")
    recent_miles= strava_sum(strava_recent, "total_distance_miles")
    base_elev   = strava_sum(strava_base,   "total_elevation_gain_feet")
    recent_elev = strava_sum(strava_recent, "total_elevation_gain_feet")

    comparisons["activity_count_30d"] = {
        "label":    "Activities per month",
        "baseline": base_acts,
        "current":  recent_acts,
        "change":   recent_acts - base_acts,
        "improved": recent_acts > base_acts,
    }
    if recent_acts > base_acts:
        victories.append(f"✅ Activity count: {recent_acts} activities this month vs {base_acts} at start")

    comparisons["monthly_miles"] = {
        "label":    "Miles per month",
        "unit":     "miles",
        "baseline": base_miles,
        "current":  recent_miles,
        "change":   round(recent_miles - base_miles, 1),
        "improved": recent_miles > base_miles,
    }
    if recent_miles > base_miles:
        victories.append(f"✅ Monthly mileage: {recent_miles} miles this month vs {base_miles} at start")

    if recent_elev > base_elev and base_elev > 0:
        victories.append(f"✅ Elevation: {recent_elev:,.0f} ft this month vs {base_elev:,.0f} ft at start")

    def avg_speed_mph(items):
        total_dist = sum(float(i.get("total_distance_miles") or 0) for i in items)
        total_time = sum(float(i.get("total_moving_time_seconds") or 0) for i in items)
        if total_dist > 0 and total_time > 0:
            return round(total_dist / (total_time / 3600), 2)
        return None

    base_speed   = avg_speed_mph(strava_base)
    recent_speed = avg_speed_mph(strava_recent)
    if base_speed and recent_speed:
        speed_delta = round(recent_speed - base_speed, 2)
        comparisons["avg_speed_mph"] = {
            "label":    "Average moving speed",
            "unit":     "mph",
            "baseline": base_speed,
            "current":  recent_speed,
            "change":   speed_delta,
            "improved": speed_delta > 0,
        }
        if speed_delta > 0.1:
            victories.append(f"✅ Moving faster: {recent_speed} mph avg vs {base_speed} mph at journey start")

    return {
        "journey_start_date":  journey_start,
        "baseline_window":     f"{baseline_start} → {baseline_end}",
        "current_window":      f"{recent_start} → {end_date}",
        "victories_count":     len(victories),
        "victories":           victories if victories else ["Keep going — victories will appear as data accumulates."],
        "comparisons":         comparisons,
        "motivation_note":     "The scale is one signal. RHR, HRV, distances, and speed are all improving even when the scale stalls. These are the real markers of health transformation.",
    }


def tool_get_body_composition_snapshot(args):
    """DEXA scan interpretation with FFMI, posture, Withings anchoring."""
    scans = _query_dexa_scans()
    if not scans:
        return {"error": "No DEXA scans found."}

    scan_date = args.get("date")
    if scan_date:
        scan = next((s for s in scans if s.get("scan_date") == scan_date), None)
        if not scan:
            return {"error": f"No scan for {scan_date}",
                    "available": [s.get("scan_date") for s in scans]}
    else:
        scan = scans[-1]

    bc = scan.get("body_composition", {})
    posture = scan.get("posture")
    interp = scan.get("interpretations", {})

    profile = get_profile()
    height_in = profile.get("height_inches", 72)
    height_m = height_in * 0.0254
    lean_lb = bc.get("lean_mass_lb", 0)
    lean_kg = lean_lb * 0.4536
    weight_lb = bc.get("weight_lb", 0)
    weight_kg = weight_lb * 0.4536

    ffmi = round(lean_kg / (height_m ** 2), 1) if height_m > 0 else None
    ffmi_norm = round(ffmi + 6.1 * (1.80 - height_m), 1) if ffmi else None
    ffmi_class = None
    if ffmi:
        if ffmi >= 25: ffmi_class = "exceptional (near natural limit)"
        elif ffmi >= 22: ffmi_class = "advanced"
        elif ffmi >= 20: ffmi_class = "above average"
        elif ffmi >= 18: ffmi_class = "average"
        else: ffmi_class = "below average"

    vat_g = bc.get("visceral_fat_g") or 999
    ag = bc.get("ag_ratio") or 99
    bmd_t = bc.get("bmd_t_score") or -9

    result = {
        "scan_date": scan.get("scan_date"), "provider": scan.get("provider"),
        "body_composition": {
            "weight_lb": bc.get("weight_lb"), "body_fat_pct": bc.get("body_fat_pct"),
            "fat_mass_lb": bc.get("fat_mass_lb"), "lean_mass_lb": lean_lb,
            "visceral_fat_g": bc.get("visceral_fat_g"),
            "visceral_fat_category": "elite" if vat_g < 500 else ("normal" if vat_g < 1000 else "elevated"),
            "android_fat_pct": bc.get("android_fat_pct"), "gynoid_fat_pct": bc.get("gynoid_fat_pct"),
            "ag_ratio": bc.get("ag_ratio"),
            "ag_status": "optimal" if ag <= 1.0 else ("slightly elevated" if ag <= 1.2 else "elevated"),
            "bmd_t_score": bc.get("bmd_t_score"),
            "bmd_status": "excellent" if bmd_t >= 1.0 else ("normal" if bmd_t >= -1.0 else "low")},
        "derived_metrics": {
            "ffmi": ffmi, "ffmi_normalized": ffmi_norm, "ffmi_classification": ffmi_class,
            "bmi": round(weight_kg / (height_m ** 2), 1) if height_m > 0 else None},
        "interpretations": interp}

    if posture:
        captures = []
        for key in ["capture_1", "capture_2"]:
            cap = posture.get(key, {})
            sag = cap.get("sagittal", {})
            trans = cap.get("transverse", {})
            if sag or trans:
                captures.append({
                    "shoulder_forward_in": sag.get("shoulder_forward_in"),
                    "hip_forward_in": sag.get("hip_forward_in"),
                    "shoulder_rotation_deg": trans.get("shoulder_rotation_deg"),
                    "shoulder_rotation_dir": trans.get("shoulder_rotation_dir")})
        if captures:
            avg_sh = round(sum(c.get("shoulder_forward_in", 0) for c in captures) / len(captures), 1)
            avg_hip = round(sum(c.get("hip_forward_in", 0) for c in captures) / len(captures), 1)
            flags = []
            if avg_sh > 2.0: flags.append("Forward shoulder posture — possible upper-cross syndrome")
            if avg_hip > 2.5: flags.append("Forward hip — possible anterior pelvic tilt")
            result["posture_summary"] = {
                "avg_shoulder_forward_in": avg_sh, "avg_hip_forward_in": avg_hip,
                "primary_rotation": captures[0].get("shoulder_rotation_dir", "unknown"),
                "flags": flags}

    try:
        from datetime import datetime as _dt, timedelta as _td
        today = _dt.now().strftime("%Y-%m-%d")
        week_ago = (_dt.now() - _td(days=7)).strftime("%Y-%m-%d")
        withings = query_source("withings", week_ago, today)
        if withings:
            lw = withings[-1]
            result["withings_current"] = {
                "date": lw.get("date"), "weight_lb": lw.get("weight_lbs"),
                "body_fat_pct": lw.get("body_fat_pct"),
                "weight_delta_since_dexa": round((lw.get("weight_lbs") or 0) - (bc.get("weight_lb") or 0), 1) if lw.get("weight_lbs") else None,
                "note": "Withings bioimpedance is less accurate than DEXA. Use DEXA as calibration anchor."}
    except Exception as e:
        logger.warning(f"Withings anchor failed: {e}")

    return result


def tool_get_health_risk_profile(args):
    """Multi-domain risk synthesis: cardiovascular, metabolic, longevity."""
    domain = args.get("domain")
    draws = _query_all_lab_draws()
    genome = _get_genome_cached()
    genome_snps = [s for s in genome if s.get("sk", "").startswith("GENE#")]
    dexa = _query_dexa_scans()

    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().strftime("%Y-%m-%d")
    result = {"assessment_date": today}

    def _get_bm(bms, key):
        b = bms.get(key, {})
        return b.get("value_numeric") or b.get("value")

    if not domain or domain == "cardiovascular":
        cv = {"domain": "cardiovascular", "factors": []}
        if draws:
            bms = draws[-1].get("biomarkers", {})
            ldl = _get_bm(bms, "ldl_c"); hdl = _get_bm(bms, "hdl")
            tg = _get_bm(bms, "triglycerides"); tc = _get_bm(bms, "cholesterol_total")
            apob = _get_bm(bms, "apolipoprotein_b"); crp = _get_bm(bms, "crp_hs")

            if isinstance(ldl, (int, float)):
                cv["factors"].append({"marker": "LDL-C", "value": ldl, "unit": "mg/dL",
                    "risk": "elevated" if ldl >= 100 else "optimal",
                    "note": "Attia target <100; <70 if high-risk"})
            if isinstance(hdl, (int, float)):
                cv["factors"].append({"marker": "HDL", "value": hdl, "unit": "mg/dL",
                    "risk": "optimal" if hdl >= 50 else "low"})
            if isinstance(tg, (int, float)) and isinstance(hdl, (int, float)) and hdl > 0:
                r = round(tg / hdl, 2)
                cv["factors"].append({"marker": "TG/HDL ratio", "value": r,
                    "risk": "optimal" if r < 1.0 else ("good" if r < 2.0 else "elevated"),
                    "note": "Insulin resistance proxy — target <1.0"})
            if isinstance(apob, (int, float)):
                cv["factors"].append({"marker": "ApoB", "value": apob, "unit": "mg/dL",
                    "risk": "optimal" if apob < 80 else ("borderline" if apob < 100 else "elevated"),
                    "note": "Best single predictor of atherosclerotic CV risk"})
            if isinstance(crp, (int, float)):
                cv["factors"].append({"marker": "hs-CRP", "value": crp, "unit": "mg/L",
                    "risk": "optimal" if crp < 1.0 else ("borderline" if crp < 3.0 else "elevated")})

        cv_genes = [s for s in genome_snps if s.get("gene") in ("ABCG8", "SLCO1B1")]
        if cv_genes:
            cv["genetic_factors"] = [{"gene": s["gene"], "genotype": s.get("genotype"),
                "risk_level": s.get("risk_level"), "summary": s.get("summary")} for s in cv_genes]

        if dexa:
            vat = dexa[-1].get("body_composition", {}).get("visceral_fat_g")
            if vat is not None:
                cv["factors"].append({"marker": "Visceral fat", "value": vat, "unit": "g",
                    "risk": "elite" if vat < 500 else ("normal" if vat < 1000 else "elevated")})

        try:
            whoop = query_source("whoop", (_dt.now() - _td(days=30)).strftime("%Y-%m-%d"), today, lean=True)
            if whoop:
                hrvs = [d.get("hrv") for d in whoop if d.get("hrv")]
                if hrvs:
                    cv["factors"].append({"marker": "30d avg HRV", "value": round(sum(hrvs)/len(hrvs), 1),
                        "unit": "ms", "note": "Higher = better CV health"})
        except Exception:
            pass


        # ASCVD 10-year risk (stored on labs records by patch_ascvd_risk.py)
        if draws:
            latest = draws[-1]
            ascvd_pct = latest.get("ascvd_risk_10yr_pct")
            if ascvd_pct is not None and isinstance(ascvd_pct, (int, float, Decimal)):
                ascvd_cat = latest.get("ascvd_risk_category", "unknown")
                ascvd_inputs = latest.get("ascvd_inputs", {})
                ascvd_caveats = latest.get("ascvd_caveats", [])
                cv["factors"].append({
                    "marker": "ASCVD 10yr Risk",
                    "value": float(ascvd_pct),
                    "unit": "%",
                    "risk": ascvd_cat,
                    "equation": "Pooled Cohort Equations (2013 ACC/AHA)",
                    "note": "Age-extrapolated — validated for 40-79" if any("extrapolated" in str(c) for c in ascvd_caveats) else "Within validated age range",
                    "inputs": {k: float(v) if isinstance(v, (Decimal, int, float)) else v for k, v in ascvd_inputs.items()},
                })

        elevated = sum(1 for f in cv["factors"] if f.get("risk") in ("elevated", "high", "low"))
        cv["overall_risk"] = "elevated" if elevated >= 2 else ("borderline" if elevated == 1 else "low")
        result["cardiovascular"] = cv

    if not domain or domain == "metabolic":
        met = {"domain": "metabolic", "factors": []}
        if draws:
            bms = draws[-1].get("biomarkers", {})
            glu = _get_bm(bms, "glucose"); a1c = _get_bm(bms, "hba1c")

            if isinstance(glu, (int, float)):
                met["factors"].append({"marker": "Fasting glucose", "value": glu, "unit": "mg/dL",
                    "risk": "optimal" if glu < 90 else ("borderline" if glu < 100 else "elevated"),
                    "note": "Attia optimal <90"})
                glu_trend = [{"date": d.get("draw_date"), "value": _get_bm(d.get("biomarkers", {}), "glucose")}
                             for d in draws if isinstance(_get_bm(d.get("biomarkers", {}), "glucose"), (int, float))]
                if len(glu_trend) >= 2:
                    met["factors"][-1]["trend"] = glu_trend

            if isinstance(a1c, (int, float)):
                met["factors"].append({"marker": "HbA1c", "value": a1c, "unit": "%",
                    "risk": "optimal" if a1c < 5.4 else ("borderline" if a1c < 5.7 else "prediabetic" if a1c < 6.5 else "diabetic"),
                    "note": "Attia optimal <5.4"})

        fto = [s for s in genome_snps if s.get("gene") == "FTO"]
        irs = [s for s in genome_snps if s.get("gene") == "IRS1"]
        if fto or irs:
            met["genetic_factors"] = []
            if fto:
                unfav = sum(1 for s in fto if s.get("risk_level") == "unfavorable")
                met["genetic_factors"].append({"cluster": "FTO obesity variants", "total": len(fto),
                    "unfavorable": unfav, "implication": "Exercise + protein + PUFA mitigate risk"})
            for s in irs:
                met["genetic_factors"].append({"gene": s["gene"], "genotype": s.get("genotype"),
                    "risk_level": s.get("risk_level"), "summary": s.get("summary")})

        if dexa:
            bc = dexa[-1].get("body_composition", {})
            bf = bc.get("body_fat_pct"); ag = bc.get("ag_ratio")
            if bf is not None:
                met["factors"].append({"marker": "Body fat %", "value": bf, "source": "DEXA",
                    "risk": "lean" if bf < 15 else ("healthy" if bf < 20 else "elevated")})
            if ag is not None:
                met["factors"].append({"marker": "A/G ratio", "value": ag, "source": "DEXA",
                    "risk": "optimal" if ag <= 1.0 else "slightly elevated",
                    "note": "Target <=1.0"})

        elevated = sum(1 for f in met["factors"] if f.get("risk") in ("elevated", "prediabetic", "diabetic"))
        met["overall_risk"] = "elevated" if elevated >= 2 else ("borderline" if elevated == 1 else "low")
        result["metabolic"] = met

    if not domain or domain == "longevity":
        lon = {"domain": "longevity", "factors": []}

        if dexa:
            bc = dexa[-1].get("body_composition", {})
            bmd = bc.get("bmd_t_score")
            if bmd is not None:
                lon["factors"].append({"marker": "BMD T-score", "value": bmd,
                    "risk": "excellent" if bmd >= 1.0 else ("normal" if bmd >= -1.0 else "low"),
                    "note": "Critical for fracture risk in aging"})
            lean_lb = bc.get("lean_mass_lb", 0)
            profile = get_profile()
            height_m = profile.get("height_inches", 72) * 0.0254
            if lean_lb and height_m > 0:
                ffmi = round((lean_lb * 0.4536) / (height_m ** 2), 1)
                lon["factors"].append({"marker": "FFMI", "value": ffmi,
                    "risk": "excellent" if ffmi >= 22 else ("good" if ffmi >= 20 else "average"),
                    "note": "Muscle mass protects against all-cause mortality"})

        if draws:
            a1c_vals = [_get_bm(d.get("biomarkers", {}), "hba1c") for d in draws]
            a1c_vals = [v for v in a1c_vals if isinstance(v, (int, float))]
            if a1c_vals:
                lon["factors"].append({"marker": "HbA1c range", "value": f"{min(a1c_vals)}-{max(a1c_vals)}%",
                    "risk": "optimal" if max(a1c_vals) < 5.4 else "monitor"})

        telo = [s for s in genome_snps if "telomere" in (s.get("summary", "") + " " + s.get("category", "")).lower()]
        if telo:
            unfav = sum(1 for s in telo if s.get("risk_level") == "unfavorable")
            lon["genetic_factors"] = {"telomere_variants": len(telo), "unfavorable": unfav,
                "mitigations": ["stress reduction", "omega-3", "exercise", "sleep optimization"]}

        try:
            whoop = query_source("whoop", (_dt.now() - _td(days=90)).strftime("%Y-%m-%d"), today, lean=True)
            if whoop:
                hrvs = [d.get("hrv") for d in whoop if d.get("hrv")]
                if hrvs:
                    lon["factors"].append({"marker": "90d avg HRV", "value": round(sum(hrvs)/len(hrvs), 1),
                        "unit": "ms", "note": "Higher HRV correlates with longevity"})
        except Exception:
            pass

        good = len([f for f in lon["factors"] if f.get("risk") in ("excellent", "optimal")])
        lon["overall_assessment"] = "strong" if good >= 2 else "moderate"
        result["longevity"] = lon

    return result


def tool_get_next_lab_priorities(args):
    """Genome-informed recommendations for next blood panel."""
    genome = _get_genome_cached()
    genome_snps = [s for s in genome if s.get("sk", "").startswith("GENE#")]
    draws = _query_all_lab_draws()

    recs = []
    existing = set()
    latest_date = None
    if draws:
        latest_date = draws[-1].get("draw_date")
        for d in draws:
            existing.update(d.get("biomarkers", {}).keys())

    mthfr = [s for s in genome_snps if s.get("gene") in ("MTHFR", "MTRR")]
    if mthfr:
        recs.append({"test": "Homocysteine", "priority": "high",
            "reason": f"MTHFR/MTRR variants ({len(mthfr)} SNPs) — impaired methylation",
            "already_tested": "homocysteine" in existing,
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in mthfr],
            "action": "Monitor quarterly; supplement 5-methylfolate + methylcobalamin"})

    vdr = [s for s in genome_snps if s.get("gene") in ("VDR", "GC", "CYP2R1")]
    if vdr:
        has_vitd = any(k for k in existing if "vitamin_d" in k or "25oh" in k)
        recs.append({"test": "Vitamin D (25-OH)", "priority": "high",
            "reason": f"Triple deficiency risk — {len(vdr)} SNPs across VDR/GC/CYP2R1",
            "already_tested": has_vitd,
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in vdr],
            "action": "Target 50-80 ng/mL with D3+K2", "cadence": "quarterly"})

    fads = [s for s in genome_snps if s.get("gene") == "FADS2"]
    if fads:
        recs.append({"test": "Omega-3 Index", "priority": "high",
            "reason": "FADS2 — poor ALA→EPA conversion; need direct EPA/DHA",
            "already_tested": any(k for k in existing if "omega" in k),
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in fads],
            "action": "Target index >8%; supplement EPA/DHA directly"})

    slco = [s for s in genome_snps if s.get("gene") == "SLCO1B1"]
    if slco:
        recs.append({"test": "CK + liver enzymes (pre-statin baseline)", "priority": "medium",
            "reason": "SLCO1B1 statin sensitivity",
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in slco],
            "action": "If statins needed: rosuvastatin/pravastatin only + CoQ10"})

    choline = [s for s in genome_snps if "choline" in (s.get("summary", "") + " " + str(s.get("actionable_recs", ""))).lower()]
    if choline:
        recs.append({"test": "Choline / Betaine / TMAO", "priority": "medium",
            "reason": f"{len(choline)} choline-related variants",
            "action": "Increase dietary choline or supplement phosphatidylcholine"})

    if draws:
        ldl_flags = sum(1 for d in draws if "ldl_c" in d.get("out_of_range", []))
        if ldl_flags >= 2:
            recs.append({"test": "NMR LipoProfile (advanced lipid panel)", "priority": "high",
                "reason": f"LDL-C flagged {ldl_flags}/{len(draws)} draws",
                "action": "LDL particle count + size — more predictive than LDL-C alone",
                "genome_note": "ABCG8 T;T explains genetic LDL elevation"})

    recs.append({"test": "CMP + CBC + HbA1c + lipids", "priority": "routine",
        "reason": "Baseline monitoring", "cadence": "annually", "last_tested": latest_date})

    priority_order = {"high": 0, "medium": 1, "routine": 2}
    return {
        "total_recommendations": len(recs), "latest_draw": latest_date,
        "total_historical_draws": len(draws), "genome_snps_analyzed": len(genome_snps),
        "recommendations": sorted(recs, key=lambda r: priority_order.get(r.get("priority", "routine"), 3)),
        "note": "Data-driven suggestions based on genome + lab history. Discuss with physician."}


def tool_get_day_type_analysis(args):
    """
    Segment any metric by day type (rest/light/moderate/hard/race).

    Cross-references Whoop strain, Strava activities, and computed load
    to classify each day, then groups selected metrics by day type.

    Use cases:
      - 'How does my sleep differ on hard training days vs rest days?'
      - 'Do I eat more on training days?'
      - 'What\'s my average HRV by day type?'
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 90))
    start_date = args.get("start_date") or (
        datetime.utcnow() - timedelta(days=days)
    ).strftime("%Y-%m-%d")
    metrics    = args.get("metrics", ["sleep", "recovery", "nutrition"])
    if isinstance(metrics, str):
        metrics = [metrics]

    # Gather classification data
    whoop_data = {d["date"]: d for d in query_source("whoop", start_date, end_date, lean=True) if d.get("date")}
    strava_data = {d["date"]: d for d in query_source(get_sot("cardio"), start_date, end_date, lean=True) if d.get("date")}

    # Classify each day
    cur = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    classified = {}  # date -> day_type
    while cur <= end_dt:
        ds = cur.strftime("%Y-%m-%d")
        w = whoop_data.get(ds, {})
        s = strava_data.get(ds, {})
        strain = w.get("strain")
        load = compute_daily_load_score(s) if s else None
        classified[ds] = classify_day_type(
            whoop_strain=strain,
            strava_activities=s,
            daily_load=load,
        )
        cur += timedelta(days=1)

    # Count by type
    type_counts = {}
    for dt in classified.values():
        type_counts[dt] = type_counts.get(dt, 0) + 1

    # Gather metrics by day type
    type_metrics = {t: [] for t in ["rest", "light", "moderate", "hard", "race"]}

    # Batch fetch nutrition data if requested
    mf_data = {}
    if "nutrition" in metrics:
        pk_mf = USER_PREFIX + "macrofactor"
        # table already imported from mcp.config
        try:
            mf_items = query_source_range(table, pk_mf, start_date, end_date)
            mf_data = {item["date"]: item for item in mf_items if item.get("date")}
        except Exception:
            pass

    for ds, day_type in classified.items():
        w = whoop_data.get(ds, {})
        entry = {"date": ds, "strain": w.get("strain")}

        if "sleep" in metrics or "recovery" in metrics:
            entry["recovery_score"] = w.get("recovery_score")
            entry["hrv"] = w.get("hrv")
            entry["resting_heart_rate"] = w.get("resting_heart_rate")
            entry["sleep_performance"] = w.get("sleep_performance")
            entry["total_sleep_hours"] = round(float(w["total_sleep_seconds"]) / 3600, 2) if w.get("total_sleep_seconds") else None

        if "nutrition" in metrics:
            mf = mf_data.get(ds, {})
            entry["calories_kcal"] = float(mf["total_calories_kcal"]) if mf.get("total_calories_kcal") else None
            entry["protein_g"] = float(mf["total_protein_g"]) if mf.get("total_protein_g") else None
            entry["carbs_g"] = float(mf["total_carbs_g"]) if mf.get("total_carbs_g") else None
            entry["fat_g"] = float(mf["total_fat_g"]) if mf.get("total_fat_g") else None

        type_metrics[day_type].append(entry)

    # Compute averages per type
    def avg_field(entries, field):
        vals = [float(e[field]) for e in entries if e.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    summary_fields = ["strain", "recovery_score", "hrv", "resting_heart_rate",
                      "sleep_performance", "total_sleep_hours",
                      "calories_kcal", "protein_g", "carbs_g", "fat_g"]
    summaries = {}
    for day_type, entries in type_metrics.items():
        if not entries:
            continue
        summaries[day_type] = {
            "count": len(entries),
            "averages": {f: avg_field(entries, f) for f in summary_fields},
        }

    # Key insights
    insights = []
    rest_hrv = summaries.get("rest", {}).get("averages", {}).get("hrv")
    hard_hrv = summaries.get("hard", {}).get("averages", {}).get("hrv")
    if rest_hrv and hard_hrv:
        diff = round(rest_hrv - hard_hrv, 1)
        if diff > 10:
            insights.append(f"HRV drops {diff} ms on hard vs rest days — significant recovery impact. Prioritize sleep after hard sessions.")
        elif diff > 5:
            insights.append(f"HRV drops {diff} ms on hard days — moderate recovery impact.")

    rest_cal = summaries.get("rest", {}).get("averages", {}).get("calories_kcal")
    hard_cal = summaries.get("hard", {}).get("averages", {}).get("calories_kcal")
    if rest_cal and hard_cal:
        diff = round(hard_cal - rest_cal)
        if diff > 300:
            insights.append(f"Eating {diff} kcal more on hard days vs rest — verify this aligns with your deficit goal.")
        elif diff < -200:
            insights.append(f"Eating {abs(diff)} kcal LESS on hard days — consider fueling better around training.")

    rest_sleep = summaries.get("rest", {}).get("averages", {}).get("total_sleep_hours")
    hard_sleep = summaries.get("hard", {}).get("averages", {}).get("total_sleep_hours")
    if rest_sleep and hard_sleep:
        diff = round(hard_sleep - rest_sleep, 2)
        if diff < -0.3:
            insights.append(f"Sleeping {abs(diff)} hrs LESS after hard days — your body needs MORE sleep for recovery, not less.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "total_days": len(classified)},
        "day_type_distribution": type_counts,
        "thresholds": DAY_TYPE_THRESHOLDS,  # noqa: F821
        "summaries": summaries,
        "insights": insights,
        "classification_source": "Whoop strain (primary) > computed load score > Strava distance/time",
    }


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

                # Attia lean-mass-preservation gate: flag if loss rate > 1% body weight/week
                safe_rate_threshold = round(current_weight * 0.01, 2)
                rate_warning = None
                if abs(weekly_rate) > safe_rate_threshold:
                    rate_warning = {
                        "flag": True,
                        "current_rate_lbs_per_week": round(abs(weekly_rate), 2),
                        "safe_threshold_lbs_per_week": safe_rate_threshold,
                        "excess_lbs_per_week": round(abs(weekly_rate) - safe_rate_threshold, 2),
                        "message": (
                            f"⚠️ Losing {abs(round(weekly_rate, 2))} lbs/week — "
                            f"exceeds the 1% body weight threshold ({safe_rate_threshold} lbs/week). "
                            "Sustained rates above this threshold risk lean mass catabolism. "
                            "Prioritise 3×/week resistance training and ≥0.7g protein per lb body weight."
                        ),
                        "attia_target": "0.5–1.0% body weight/week for optimal lean mass preservation",
                    }

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
                    "rate_warning":         rate_warning,
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

                    # Strength frequency check (Attia/Huberman: 3+x/week during weight loss)
                    weekly_strength = {}
                    for item in strava_data:
                        d = item.get("date", "")
                        try:
                            dt = datetime.strptime(d, "%Y-%m-%d")
                            wk = dt.strftime("%Y-W%U")
                        except ValueError:
                            continue
                        for act in (item.get("activities") or []):
                            sport = (act.get("sport_type") or act.get("type", "")).lower()
                            if any(k in sport for k in ["weight", "strength", "gym", "lift"]):
                                weekly_strength[wk] = weekly_strength.get(wk, 0) + 1

                    strength_warning = None
                    if weekly_strength:
                        recent_strength_weeks = [weekly_strength.get(w, 0) for w in weeks_sorted[-4:]]
                        avg_strength_per_week = sum(recent_strength_weeks) / len(recent_strength_weeks)
                        if avg_strength_per_week < 3:
                            strength_warning = {
                                "flag": True,
                                "avg_strength_sessions_per_week": round(avg_strength_per_week, 1),
                                "target": 3,
                                "message": (
                                    f"⚠️ Only {round(avg_strength_per_week, 1)} strength sessions/week (target ≥3). "
                                    "During a caloric deficit, resistance training frequency is the primary "
                                    "lever for lean mass preservation."
                                ),
                            }

                    result["fitness"] = {
                        "avg_weekly_hours":     round(avg_weekly_hours, 1),
                        "avg_weekly_zone2_min": round(avg_weekly_z2, 0),
                        "zone2_target_min":     z2_target,
                        "zone2_target_pct":     z2_pct,
                        "volume_trend":         volume_trend,
                        "training_consistency_pct": consistency,
                        "weeks_analyzed":       total_weeks,
                        "active_weeks":         active_weeks,
                        "strength_warning":     strength_warning,
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
            # Normalize Whoop data for sleep efficiency (SOT v2.55.0)
            whoop_normd = [normalize_whoop_sleep(i) for i in whoop_data]

            hrv_vals = []
            rhr_vals = []
            recovery_vals = []
            sleep_eff_vals = []

            for item in whoop_normd:
                hrv = item.get("hrv_rmssd")
                rhr = item.get("resting_heart_rate")
                rec = item.get("recovery_score")
                eff = item.get("sleep_efficiency_pct")
                if hrv: hrv_vals.append(float(hrv))
                if rhr: rhr_vals.append(float(rhr))
                if rec: recovery_vals.append(float(rec))
                if eff: sleep_eff_vals.append(float(eff))

            recovery_result = {}

            if len(hrv_vals) >= 14:
                first_half = hrv_vals[:len(hrv_vals)//2]
                second_half = hrv_vals[len(hrv_vals)//2:]
                hrv_trend = "improving" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) * 1.05 else                            ("declining" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) * 0.95 else "stable")
                recovery_result["hrv"] = {
                    "current_avg":  round(sum(hrv_vals[-7:]) / min(len(hrv_vals), 7), 1),
                    "60d_avg":      round(sum(hrv_vals) / len(hrv_vals), 1),
                    "trend":        hrv_trend,
                    "data_points":  len(hrv_vals),
                }

            if len(rhr_vals) >= 14:
                first_half = rhr_vals[:len(rhr_vals)//2]
                second_half = rhr_vals[len(rhr_vals)//2:]
                rhr_trend = "improving" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) * 0.97 else                            ("worsening" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) * 1.03 else "stable")
                recovery_result["rhr"] = {
                    "current_avg":  round(sum(rhr_vals[-7:]) / min(len(rhr_vals), 7), 1),
                    "60d_avg":      round(sum(rhr_vals) / len(rhr_vals), 1),
                    "trend":        rhr_trend,
                    "data_points":  len(rhr_vals),
                }

            if len(sleep_eff_vals) >= 14:
                first_half = sleep_eff_vals[:len(sleep_eff_vals)//2]
                second_half = sleep_eff_vals[len(sleep_eff_vals)//2:]
                eff_trend = "improving" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) + 1 else                            ("declining" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) - 1 else "stable")
                recovery_result["sleep_efficiency"] = {
                    "current_avg":  round(sum(sleep_eff_vals[-7:]) / min(len(sleep_eff_vals), 7), 1),
                    "60d_avg":      round(sum(sleep_eff_vals) / len(sleep_eff_vals), 1),
                    "trend":        eff_trend,
                    "data_points":  len(sleep_eff_vals),
                }

            if recovery_result:
                result["recovery"] = recovery_result
            else:
                result["recovery"] = {"message": "Need at least 14 days of Whoop data for recovery trajectory."}
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
                glucose_trend = "improving" if sum(second_half)/len(second_half) < sum(first_half)/len(first_half) - 1 else                                ("worsening" if sum(second_half)/len(second_half) > sum(first_half)/len(first_half) + 1 else "stable")
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
        if w.get("rate_warning"):
            concerns.append(w["rate_warning"]["message"])

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
        if result["fitness"].get("strength_warning"):
            concerns.append(result["fitness"]["strength_warning"]["message"])

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


# ══════════════════════════════════════════════════════════════════════════════
# HYDRATION TRACKING ENHANCEMENT  (#30)
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_hydration_score(args):
    """
    Hydration adequacy scoring: bodyweight-adjusted daily target,
    deficit alerts, rolling average, adequacy rate, and correlation
    with exercise intensity and journal energy scores.
    Source: apple_health (water_intake_ml). Bodyweight target: 35ml/kg (Webb).
    Fallback guidance: Habitify manual log if Apple Health sync is incomplete.
    """
    end   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    target_ml_override = args.get("target_ml")

    # Pull water data from apple_health (SOT for water domain)
    water_items = query_source("apple_health", start, end)
    if not water_items:
        return {
            "error": "No Apple Health data found. Ensure the 9pm HAE automation is running.",
            "hint":  "Water field: water_intake_ml in apple_health source.",
        }

    # Get weight for personalized target
    weight_kg = None
    try:
        wt_items = query_source("withings",
            (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d"), end)
        if wt_items:
            wt_items.sort(key=lambda x: x.get("date", ""), reverse=True)
            weight_lbs = float(wt_items[0].get("weight_lbs") or 0)
            if weight_lbs > 0:
                weight_kg = round(weight_lbs * 0.453592, 1)
    except Exception:
        pass

    # Compute target: 35ml/kg (Webb's guidance), 2500ml floor, or override
    if target_ml_override:
        daily_target_ml = float(target_ml_override)
    elif weight_kg:
        daily_target_ml = max(2500, round(weight_kg * 35))
    else:
        daily_target_ml = 3000  # reasonable default

    daily_target_oz = round(daily_target_ml / 29.5735, 1)

    # Pull exercise intensity for correlation
    strava_items = query_source("strava", start, end)
    exercise_by_date = {}
    for item in (strava_items or []):
        d = item.get("date", "")
        item = decimal_to_float(item)
        acts = item.get("activities", [])
        if acts:
            total_min = sum(
                float(a.get("moving_time_seconds", 0)) / 60
                for a in acts
            )
            hr_list = [float(a.get("average_heartrate") or 0) for a in acts if a.get("average_heartrate")]
            avg_hr = sum(hr_list) / len(hr_list) if hr_list else 0
            exercise_by_date[d] = {"total_min": round(total_min, 1), "avg_hr": round(avg_hr, 1)}

    # Build daily rows
    daily_rows = []
    deficit_days = []
    zero_data_days = 0
    water_vals = []

    for item in sorted(water_items, key=lambda x: x.get("date", "")):
        d = item.get("date", "")
        if not d:
            continue
        item = decimal_to_float(item)

        ml = float(item.get("water_intake_ml") or 0)
        oz = float(item.get("water_intake_oz") or (ml / 29.5735 if ml else 0))

        has_data = ml >= 500  # 500ml min = actual reading (same threshold as daily brief)
        if not has_data:
            zero_data_days += 1
            continue

        water_vals.append(ml)
        pct_target = round(ml / daily_target_ml * 100, 1)
        met_target = ml >= daily_target_ml * 0.9  # 90% counts as met
        score = min(100, round(pct_target))

        ex = exercise_by_date.get(d)
        row = {
            "date":             d,
            "water_ml":         round(ml, 0),
            "water_oz":         round(oz, 1),
            "pct_target":       pct_target,
            "met_target":       met_target,
            "score":            score,
            "exercise_min":     ex["total_min"] if ex else 0,
            "exercise_avg_hr":  ex["avg_hr"]    if ex else None,
        }
        daily_rows.append(row)
        if not met_target:
            deficit_days.append(d)

    if not daily_rows:
        return {
            "error": "No valid water readings found (>= 500ml). Check the 9pm HAE automation.",
            "zero_data_days": zero_data_days,
            "hint": "If the 9pm HAE automation is not running, water data will not appear in the Daily Brief.",
        }

    n = len(daily_rows)
    avg_ml = round(sum(water_vals) / n, 0)
    avg_oz = round(avg_ml / 29.5735, 1)
    adequacy_rate = round((n - len(deficit_days)) / n * 100, 1)
    avg_score = round(sum(r["score"] for r in daily_rows) / n, 1)

    # Streak: current consecutive days at target
    streak = 0
    for row in reversed(daily_rows):
        if row["met_target"]:
            streak += 1
        else:
            break

    # Correlation: exercise days vs rest days
    ex_days   = [r for r in daily_rows if r["exercise_min"] > 20]
    rest_days = [r for r in daily_rows if r["exercise_min"] <= 20]
    ex_avg_ml   = round(sum(r["water_ml"] for r in ex_days)   / max(1, len(ex_days)),   0) if ex_days   else None
    rest_avg_ml = round(sum(r["water_ml"] for r in rest_days) / max(1, len(rest_days)), 0) if rest_days else None

    # Recommendations
    recs = []
    if avg_ml < daily_target_ml * 0.8:
        gap = round((daily_target_ml - avg_ml) / 1000, 1)
        recs.append(
            f"Average intake ({int(avg_ml)}ml) is {int(100 - avg_ml/daily_target_ml*100)}% below target. "
            f"Add ~{gap}L/day — try one extra large glass at each meal."
        )
    if len(deficit_days) > n * 0.5:
        recs.append(
            f"Missing target on {len(deficit_days)}/{n} days ({int(len(deficit_days)/n*100)}%). "
            "Set a mid-day hydration check alarm."
        )
    if ex_avg_ml and rest_avg_ml and ex_avg_ml < rest_avg_ml:
        recs.append(
            f"Exercise days avg {int(ex_avg_ml)}ml vs rest days {int(rest_avg_ml)}ml — "
            "you are drinking LESS on training days. Add 500ml intra-workout."
        )
    if weight_kg:
        add_per_hr = round(weight_kg * 0.7)  # ~700ml/hr moderate exercise
        recs.append(
            f"At {weight_kg}kg, add ~{add_per_hr}ml for each hour of exercise "
            f"(above your {int(daily_target_ml)}ml base target)."
        )

    return {
        "period":    {"start_date": start, "end_date": end, "days_with_data": n},
        "target": {
            "daily_target_ml":  daily_target_ml,
            "daily_target_oz":  daily_target_oz,
            "basis":            f"35ml/kg x {weight_kg}kg" if weight_kg else "3000ml default",
            "weight_kg":        weight_kg,
        },
        "summary": {
            "avg_ml":                avg_ml,
            "avg_oz":                avg_oz,
            "avg_score":             avg_score,
            "adequacy_rate_pct":     adequacy_rate,
            "deficit_days":          len(deficit_days),
            "zero_data_days":        zero_data_days,
            "current_streak_days":   streak,
        },
        "exercise_correlation": {
            "exercise_days_avg_ml": ex_avg_ml,
            "rest_days_avg_ml":     rest_avg_ml,
            "note": "Higher hydration on exercise days expected — flag if inverted.",
        },
        "deficit_dates":   deficit_days,
        "recommendations": recs,
        "daily_breakdown": daily_rows,
    }


def tool_get_daily_metrics(args):
    """Unified daily metrics dispatcher.
    movement_score lives in tools_lifestyle; energy_expenditure and hydration_score are local.
    """
    from mcp.tools_lifestyle import tool_get_movement_score
    VALID_VIEWS = {
        "movement":   tool_get_movement_score,
        "energy":     tool_get_energy_expenditure,
        "hydration":  tool_get_hydration_score,
    }
    view = (args.get("view") or "movement").lower().strip()
    if view not in VALID_VIEWS:
        return {"error": f"Unknown view '{view}'.", "valid_views": list(VALID_VIEWS.keys()),
                "hint": "'movement' for NEAT/step score, 'energy' for calorie expenditure vs intake, 'hydration' for daily water intake adequacy."}
    return VALID_VIEWS[view](args)


# R13-F09: Standard medical disclaimer injected into all health-assessment responses.
_HEALTH_DISCLAIMER = (
    "For personal health tracking only. Not medical advice. "
    "Consult a qualified healthcare provider before making health decisions based on this data."
)


def tool_get_health(args):
    """
    Unified health intelligence dispatcher. Routes to the appropriate underlying
    function based on the 'view' parameter.
    Board recommendation (11-0): health_risk_profile and health_trajectory are
    also warmed nightly so view= dispatch hits cache on warm invocations.
    """
    VALID_VIEWS = {
        "dashboard":    tool_get_health_dashboard,
        "risk_profile": tool_get_health_risk_profile,
        "trajectory":   tool_get_health_trajectory,
    }
    view = (args.get("view") or "dashboard").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Default is 'dashboard'. Use 'risk_profile' for CV/metabolic/longevity risk, 'trajectory' for forward-looking projections.",
        }
    result = VALID_VIEWS[view](args)
    # R13-F09: Inject disclaimer into all health view responses
    if isinstance(result, dict) and "error" not in result:
        result["_disclaimer"] = _HEALTH_DISCLAIMER
    return result


# ── BS-MP1: Autonomic Balance Score ──────────────────────────────────────

def tool_get_autonomic_balance(args):
    """
    BS-MP1: Synthesizes HRV, resting heart rate, respiratory rate, and sleep
    quality into a 4-quadrant nervous system state model:
      - Flow (high energy + positive): high HRV, low RHR, good sleep, normal RR
      - Stress (high energy + negative): low HRV, elevated RHR, poor sleep
      - Recovery (low energy + positive): moderate HRV, low RHR, high deep sleep
      - Burnout (low energy + negative): low HRV, elevated RHR, poor sleep, elevated RR
    Provides rolling 7-day trend and state transition detection.
    Porges polyvagal theory + Huberman ANS framework.
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 30))
    start_date = args.get("start_date") or (
        datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)
    ).strftime("%Y-%m-%d")

    whoop_items = query_source("whoop", start_date, end_date)
    if len(whoop_items) < 7:
        return {"error": f"Need ≥7 days of Whoop data. Found {len(whoop_items)}."}

    items = sorted(whoop_items, key=lambda x: x.get("date", ""))

    # Compute personal baselines (full window)
    def safe_list(field):
        return [float(i[field]) for i in items if i.get(field) is not None]

    hrv_all = safe_list("hrv")
    rhr_all = safe_list("resting_heart_rate")
    rr_all  = safe_list("respiratory_rate")
    eff_all = safe_list("sleep_efficiency")
    rec_all = safe_list("recovery_score")

    def avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    def std(vals):
        if len(vals) < 2:
            return 0
        m = sum(vals) / len(vals)
        return round(math.sqrt(sum((v - m)**2 for v in vals) / (len(vals) - 1)), 2)

    baselines = {
        "hrv":  {"mean": avg(hrv_all), "sd": std(hrv_all)},
        "rhr":  {"mean": avg(rhr_all), "sd": std(rhr_all)},
        "rr":   {"mean": avg(rr_all),  "sd": std(rr_all)},
        "eff":  {"mean": avg(eff_all),  "sd": std(eff_all)},
        "rec":  {"mean": avg(rec_all),  "sd": std(rec_all)},
    }

    def z_score(value, baseline):
        if value is None or baseline["sd"] == 0:
            return 0
        return round((value - baseline["mean"]) / baseline["sd"], 2)

    def classify_quadrant(hrv_z, rhr_z, eff_z, rr_z):
        """
        4-quadrant model:
          Energy axis: HRV_z (positive = high vagal tone = energy available)
          Valence axis: composite of RHR_z (inverted), efficiency_z, RR_z (inverted)
        """
        energy = hrv_z
        valence = (-rhr_z + eff_z - rr_z) / 3  # positive = good recovery signals

        if energy >= 0 and valence >= 0:
            return "FLOW", energy, valence
        elif energy >= 0 and valence < 0:
            return "STRESS", energy, valence
        elif energy < 0 and valence >= 0:
            return "RECOVERY", energy, valence
        else:
            return "BURNOUT", energy, valence

    # ── Daily scoring ──
    daily_states = []
    for item in items:
        hrv_val = item.get("hrv")
        rhr_val = item.get("resting_heart_rate")
        rr_val  = item.get("respiratory_rate")
        eff_val = item.get("sleep_efficiency")
        rec_val = item.get("recovery_score")

        hrv_z = z_score(float(hrv_val) if hrv_val else None, baselines["hrv"])
        rhr_z = z_score(float(rhr_val) if rhr_val else None, baselines["rhr"])
        rr_z  = z_score(float(rr_val)  if rr_val  else None, baselines["rr"])
        eff_z = z_score(float(eff_val)  if eff_val else None, baselines["eff"])

        quadrant, energy, valence = classify_quadrant(hrv_z, rhr_z, eff_z, rr_z)

        # Autonomic balance score 0-100
        # Centre is 50; flow pushes up, burnout pulls down
        raw_score = 50 + (energy + valence) * 12.5
        balance_score = max(0, min(100, round(raw_score)))

        daily_states.append({
            "date":           item.get("date"),
            "quadrant":       quadrant,
            "balance_score":  balance_score,
            "energy_axis":    round(energy, 2),
            "valence_axis":   round(valence, 2),
            "hrv":            float(hrv_val) if hrv_val else None,
            "rhr":            float(rhr_val) if rhr_val else None,
            "rr":             float(rr_val)  if rr_val  else None,
            "efficiency":     float(eff_val) if eff_val else None,
            "recovery":       float(rec_val) if rec_val else None,
        })

    # ── Current state (latest) ──
    current = daily_states[-1] if daily_states else {}

    # ── 7-day rolling trend ──
    recent_7 = daily_states[-7:] if len(daily_states) >= 7 else daily_states
    quadrant_counts = defaultdict(int)
    for ds in recent_7:
        quadrant_counts[ds["quadrant"]] += 1
    dominant_state = max(quadrant_counts, key=quadrant_counts.get) if quadrant_counts else "UNKNOWN"
    avg_score_7d = avg([ds["balance_score"] for ds in recent_7])

    # State transitions
    transitions = []
    for i in range(1, len(daily_states)):
        if daily_states[i]["quadrant"] != daily_states[i-1]["quadrant"]:
            transitions.append({
                "date":  daily_states[i]["date"],
                "from":  daily_states[i-1]["quadrant"],
                "to":    daily_states[i]["quadrant"],
            })

    # Consecutive days in current state
    streak = 1
    if len(daily_states) >= 2:
        for i in range(len(daily_states) - 2, -1, -1):
            if daily_states[i]["quadrant"] == current.get("quadrant"):
                streak += 1
            else:
                break

    # ── Contextual coaching ──
    _coaching = {
        "FLOW":     "Autonomic nervous system in optimal state. High vagal tone + good recovery signals. Train hard, challenge yourself, or tackle high-cognitive-load work.",
        "STRESS":   "High sympathetic activation. HRV is available but recovery signals are poor. Risk of overreach if sustained >3 days. Prioritise parasympathetic activators: box breathing, cold exposure, early sleep.",
        "RECOVERY": "Low energy but positive recovery trajectory. Body is rebuilding. Light movement only — this state precedes a Flow transition if respected.",
        "BURNOUT":  "Low HRV + poor recovery + elevated RHR/RR. Sustained burnout erodes training adaptations and habit compliance. Immediate priorities: sleep hygiene, caloric adequacy, social connection, reduce training volume 50%.",
    }

    return {
        "period":           {"start_date": start_date, "end_date": end_date, "days_with_data": len(daily_states)},
        "current_state":    {
            "date":          current.get("date"),
            "quadrant":      current.get("quadrant"),
            "balance_score": current.get("balance_score"),
            "energy_axis":   current.get("energy_axis"),
            "valence_axis":  current.get("valence_axis"),
            "days_in_state": streak,
            "coaching":      _coaching.get(current.get("quadrant"), ""),
        },
        "seven_day_trend":  {
            "dominant_state":     dominant_state,
            "avg_balance_score":  avg_score_7d,
            "state_distribution": dict(quadrant_counts),
        },
        "baselines":        baselines,
        "transitions":      transitions[-10:],  # last 10 transitions
        "daily_states":     daily_states,
        "methodology":      (
            "4-quadrant autonomic model using Z-scores against personal baselines. "
            "Energy axis = HRV Z-score (vagal tone). Valence axis = mean of inverted RHR Z, "
            "sleep efficiency Z, inverted respiratory rate Z. Balance score 0-100 maps both axes. "
            "Based on Porges polyvagal theory + Huberman ANS framework. "
            "Sustained burnout (>3 consecutive days) is a strong signal to reduce load."
        ),
        "_disclaimer": "This platform provides personal health data aggregation and AI-generated insights for informational purposes only. Always consult a qualified healthcare provider for medical advice.",
    }
