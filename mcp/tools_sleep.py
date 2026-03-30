"""
Sleep analysis tools.
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
    normalize_whoop_sleep,
)


def tool_get_sleep_analysis(args):
    """
    Clinical sleep analysis from Whoop data (SOT for sleep duration, staging,
    score, and efficiency as of v2.55.0). Surfaces architecture percentages,
    sleep efficiency, circadian timing, consistency, sleep debt, social jetlag,
    and WASO — the metrics a sleep physician actually uses.

    Whoop is preferred over Eight Sleep because the wrist sensor captures ALL
    sleep regardless of location (couch, travel, naps), whereas Eight Sleep only
    sees time spent in the pod.
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 90))   # rolling window
    target_h   = float(args.get("target_sleep_hours", 7.5))
    start_date = args.get("start_date") or (
        datetime.utcnow() - timedelta(days=days)
    ).strftime("%Y-%m-%d")

    raw_items = query_source("whoop", start_date, end_date)
    if not raw_items:
        return {"error": "No Whoop data found for the requested window."}
    items = [normalize_whoop_sleep(i) for i in raw_items]

    items = sorted(items, key=lambda x: x.get("date", ""))

    # ── Helper: safe average ─────────────────────────────────────────────────
    def avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def pct_below(vals, threshold):
        v = [x for x in vals if x is not None]
        if not v:
            return None
        return round(100.0 * sum(1 for x in v if x < threshold) / len(v), 1)

    def std_dev(vals):
        v = [x for x in vals if x is not None]
        if len(v) < 2:
            return None
        m = sum(v) / len(v)
        return round(math.sqrt(sum((x - m) ** 2 for x in v) / len(v)), 2)

    # Pull raw series for each field
    def series(field):
        return [float(item[field]) for item in items if item.get(field) is not None]

    n = len(items)

    # ── 1. Sleep architecture ─────────────────────────────────────────────────
    rem_pcts   = series("rem_pct")
    deep_pcts  = series("deep_pct")
    light_pcts = series("light_pct")
    eff_pcts   = series("sleep_efficiency_pct")
    dur_hrs    = series("sleep_duration_hours")
    waso_hrs   = series("waso_hours")
    latency    = series("time_to_sleep_min")
    resp_rates = series("respiratory_rate")
    hrv_vals   = series("hrv_avg")

    architecture = {
        "rem_avg_pct":         avg(rem_pcts),
        "rem_norm":            "20–25%",
        "rem_below_15pct_nights": pct_below(rem_pcts, 15),
        "deep_avg_pct":        avg(deep_pcts),
        "deep_norm":           "15–25%",
        "deep_below_10pct_nights": pct_below(deep_pcts, 10),
        "light_avg_pct":       avg(light_pcts),
        "avg_sleep_hours":     avg(dur_hrs),
        "avg_waso_hours":      avg(waso_hrs),
        "avg_latency_min":     avg(latency),
        "latency_over_30min_nights": pct_below([-x for x in latency], -30) if latency else None,
    }

    arch_alerts = []
    if architecture["rem_avg_pct"] and architecture["rem_avg_pct"] < 18:
        arch_alerts.append(
            f"⚠️ Average REM {architecture['rem_avg_pct']}% is below the 20–25% norm. "
            "Common causes: alcohol, sleep deprivation, SSRIs. Review evening habits."
        )
    if architecture["rem_below_15pct_nights"] and architecture["rem_below_15pct_nights"] > 30:
        arch_alerts.append(
            f"⚠️ {architecture['rem_below_15pct_nights']}% of nights have REM < 15%. "
            "Consistent low REM is associated with impaired emotional regulation and memory consolidation."
        )
    if architecture["deep_avg_pct"] and architecture["deep_avg_pct"] < 12:
        arch_alerts.append(
            f"⚠️ Average deep/SWS {architecture['deep_avg_pct']}% is low. "
            "Deep sleep is when growth hormone releases and metabolic restoration occurs. "
            "Alcohol, late exercise, and high stress suppress SWS."
        )
    if architecture["avg_latency_min"] and architecture["avg_latency_min"] > 30:
        arch_alerts.append(
            f"⚠️ Average sleep onset {architecture['avg_latency_min']} min — above the clinical threshold of 30 min. "
            "Persistent latency >30 min is a diagnostic criterion for insomnia."
        )
    architecture["clinical_alerts"] = arch_alerts

    # ── 2. Sleep efficiency ───────────────────────────────────────────────────
    efficiency = {
        "avg_sleep_efficiency_pct":   avg(eff_pcts),
        "clinical_target":            "≥ 85%",
        "cbt_i_threshold":            "< 80% consistently",
        "nights_below_85pct":         pct_below(eff_pcts, 85),
        "nights_below_80pct":         pct_below(eff_pcts, 80),
    }

    # 85%: AASM healthy target; 80%: CBT-I treatment threshold (Morin et al.)
    eff_alerts = []
    eff_avg = efficiency["avg_sleep_efficiency_pct"]
    if eff_avg and eff_avg < 80:
        eff_alerts.append(
            f"🚨 Average sleep efficiency {eff_avg}% — below the CBT-I treatment threshold of 80%. "
            "This warrants sleep restriction protocol consideration (consult a sleep specialist)."
        )
    elif eff_avg and eff_avg < 85:
        eff_alerts.append(
            f"⚠️ Average sleep efficiency {eff_avg}% — below the healthy target of 85%. "
            "Consider consistent wake time, limiting time in bed while awake, and reducing evening stimulants."
        )
    nb80 = efficiency["nights_below_80pct"]
    if nb80 and nb80 > 40:
        eff_alerts.append(
            f"⚠️ {nb80}% of nights show efficiency < 80% — chronic pattern, not isolated nights."
        )
    efficiency["clinical_alerts"] = eff_alerts

    # ── 3. Circadian timing & consistency ─────────────────────────────────────
    onset_hours   = series("sleep_onset_hour")
    wake_hours    = series("wake_hour")
    midpoint_hours= series("sleep_midpoint_hour")

    onset_sd  = std_dev(onset_hours)
    wake_sd   = std_dev(wake_hours)
    mid_sd    = std_dev(midpoint_hours)
    avg_onset = avg(onset_hours)
    avg_wake  = avg(wake_hours)
    avg_mid   = avg(midpoint_hours)

    def format_hour(h):
        if h is None:
            return None
        total_min = int(h * 60)
        hh = (total_min // 60) % 24
        mm = total_min % 60
        suffix = "am" if hh < 12 else "pm"
        hh12 = hh if 1 <= hh <= 12 else (12 if hh == 0 else hh - 12)
        return f"{hh12}:{mm:02d} {suffix}"

    # Social jetlag: split into weekday vs weekend midpoints
    weekday_mids, weekend_mids = [], []
    for item in items:
        mid = item.get("sleep_midpoint_hour")
        date_str = item.get("date", "")
        if mid is None or not date_str:
            continue
        try:
            dow = datetime.strptime(date_str, "%Y-%m-%d").weekday()  # 0=Mon
        except ValueError:
            continue
        if dow < 5:
            weekday_mids.append(float(mid))
        else:
            weekend_mids.append(float(mid))

    social_jetlag = None
    if weekday_mids and weekend_mids:
        # Circular mean difference for hours that wrap at 24
        def circ_mean(vals):
            sin_sum = sum(math.sin(v * math.pi / 12) for v in vals)
            cos_sum = sum(math.cos(v * math.pi / 12) for v in vals)
            return math.atan2(sin_sum / len(vals), cos_sum / len(vals)) * 12 / math.pi % 24
        wkday_mean = circ_mean(weekday_mids)
        wkend_mean = circ_mean(weekend_mids)
        diff = (wkend_mean - wkday_mean + 12) % 24 - 12   # signed, range -12..12
        social_jetlag = round(abs(diff), 2)

    circadian = {
        "avg_sleep_onset":          format_hour(avg_onset),
        "avg_wake_time":            format_hour(avg_wake),
        "avg_sleep_midpoint":       format_hour(avg_mid),
        "sleep_onset_consistency_sd_hours": onset_sd,
        "wake_consistency_sd_hours":        wake_sd,
        "midpoint_consistency_sd_hours":    mid_sd,
        "social_jetlag_hours":      social_jetlag,
        "social_jetlag_note":       "Difference in sleep midpoint weekday vs weekend. >1h linked to metabolic risk.",
        "weekday_nights_analyzed":  len(weekday_mids),
        "weekend_nights_analyzed":  len(weekend_mids),
    }

    # Wittmann 2006; wake stricter because it anchors the circadian clock more strongly
    circ_alerts = []
    if onset_sd and onset_sd > 1.0:
        circ_alerts.append(
            f"⚠️ Sleep onset varies ±{onset_sd}h SD — high variability undermines circadian entrainment. "
            "A consistent bedtime within 30 minutes nightly is the highest-leverage sleep habit."
        )
    if wake_sd and wake_sd > 0.75:
        circ_alerts.append(
            f"⚠️ Wake time varies ±{wake_sd}h SD. Consistent wake time (even weekends) is the "
            "single most effective anchor for circadian rhythm."
        )
    if social_jetlag and social_jetlag >= 2.0:
        circ_alerts.append(
            f"🚨 Social jetlag {social_jetlag}h — equivalent to flying through {round(social_jetlag)} time zones every "
            "weekend. Associated with obesity, metabolic syndrome, and increased cardiovascular risk."
        )
    elif social_jetlag and social_jetlag >= 1.0:
        circ_alerts.append(
            f"⚠️ Social jetlag {social_jetlag}h — above the 1h clinical threshold. "
            "Try to keep weekend sleep timing within 1h of weekday schedule."
        )
    circadian["clinical_alerts"] = circ_alerts

    # ── 4. Sleep debt ─────────────────────────────────────────────────────────
    nightly_debts = [
        round(target_h - float(item["sleep_duration_hours"]), 2)
        for item in items if item.get("sleep_duration_hours") is not None
    ]
    cumulative_debt_7d = None
    cumulative_debt_30d= None
    if nightly_debts:
        cumulative_debt_7d  = round(sum(nightly_debts[-7:]),  2)
        cumulative_debt_30d = round(sum(nightly_debts[-30:]), 2)

    debt = {
        "target_hours_per_night": target_h,
        "avg_nightly_debt_hours": avg(nightly_debts),
        "cumulative_debt_7d":     cumulative_debt_7d,
        "cumulative_debt_30d":    cumulative_debt_30d,
        "nights_meeting_target": round(
            100.0 * sum(1 for d in nightly_debts if d <= 0) / len(nightly_debts), 1
        ) if nightly_debts else None,
        "note": "Positive debt = below target. Research shows sleep debt accumulates and impairs cognition even when subjective sleepiness adapts.",
    }

    # Van Dongen 2003: cognitive impairment at ~6h cumulative debt
    debt_alerts = []
    if cumulative_debt_7d and cumulative_debt_7d > 5:
        debt_alerts.append(
            f"⚠️ Rolling 7-day sleep debt is {cumulative_debt_7d}h. "
            f"Cognitive performance typically impaired when cumulative debt exceeds 5h."
        )
    if cumulative_debt_30d and cumulative_debt_30d > 15:
        debt_alerts.append(
            f"⚠️ 30-day cumulative debt {cumulative_debt_30d}h. "
            "Chronic sleep restriction has documented metabolic and immune consequences."
        )
    debt["clinical_alerts"] = debt_alerts

    # ── 5. Biometrics ─────────────────────────────────────────────────────────
    biometrics = {}
    if hrv_vals:
        biometrics["avg_sleep_hrv_ms"] = avg(hrv_vals)
        biometrics["hrv_note"] = "Sleep HRV from Eight Sleep tends to be lower than Whoop HRV (different measurement timing)."
    if resp_rates:
        avg_resp = avg(resp_rates)
        biometrics["avg_respiratory_rate"] = avg_resp
        biometrics["respiratory_norm"] = "12–18 bpm"
        if avg_resp and avg_resp > 18:
            biometrics["respiratory_alert"] = (
                f"⚠️ Average respiratory rate {avg_resp} bpm exceeds 18 bpm normal ceiling. "
                "Sustained elevation warrants evaluation for sleep-disordered breathing (OSA)."
            )
        elif avg_resp and avg_resp > 16:
            biometrics["respiratory_note_elevated"] = (
                f"Note: respiratory rate {avg_resp} bpm — upper-normal range. Monitor trend."
            )

    # ── 6. Sleep score trend ──────────────────────────────────────────────────
    scores = series("sleep_score")
    score_summary = {}
    if scores:
        score_summary["avg_sleep_score"] = avg(scores)
        if len(scores) >= 14:
            recent_half = scores[len(scores)//2:]
            early_half  = scores[:len(scores)//2]
            delta = round(avg(recent_half) - avg(early_half), 1)
            score_summary["trend"] = "improving" if delta > 2 else ("declining" if delta < -2 else "stable")
            score_summary["trend_delta"] = delta

    # ── 7. All alerts consolidated ────────────────────────────────────────────
    all_alerts = (
        architecture.get("clinical_alerts", []) +
        efficiency.get("clinical_alerts", []) +
        circadian.get("clinical_alerts", []) +
        debt.get("clinical_alerts", []) +
        ([biometrics["respiratory_alert"]] if biometrics.get("respiratory_alert") else [])
    )

    return {
        "analysis_window":    {"start": start_date, "end": end_date, "nights_analyzed": n},
        "sleep_architecture": architecture,
        "sleep_efficiency":   efficiency,
        "circadian_timing":   circadian,
        "sleep_debt":         debt,
        "biometrics":         biometrics,
        "sleep_score":        score_summary,
        "all_alerts":         all_alerts,
        "alert_count":        len(all_alerts),
        "source":             "whoop",
        "clinical_note":      (
            "Whoop wrist-based sleep staging is consumer-grade. Architecture percentages "
            "should be interpreted as trends and screening signals, not clinical PSG equivalents. "
            "Consistent patterns across 30+ nights are more meaningful than individual night values. "
            "Whoop is preferred over Eight Sleep because it captures ALL sleep regardless of location."
        ),
    }



# ── BS-SL1: Sleep Environment Optimizer ────────────────────────────────────

def tool_get_sleep_environment_analysis(args):
    """
    BS-SL1: Cross-reference Eight Sleep bed temperature data with Whoop sleep
    staging and efficiency to find personal optimal temperature settings.
    Huberman/Walker: core body temperature drop of 1-3°F is the primary
    trigger for sleep onset. Eight Sleep controls this precisely.
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 90))
    start_date = args.get("start_date") or (
        datetime.utcnow() - timedelta(days=days)
    ).strftime("%Y-%m-%d")

    data = parallel_query_sources(["eightsleep", "whoop"], start_date, end_date)
    es_items = {i.get("date"): i for i in data.get("eightsleep", []) if i.get("date")}
    wh_items = {i.get("date"): i for i in data.get("whoop", []) if i.get("date")}

    # Build paired dataset
    paired = []
    for date_key in sorted(set(es_items.keys()) & set(wh_items.keys())):
        es = es_items[date_key]
        wh = wh_items[date_key]

        bed_temp  = es.get("bed_temperature_f") or es.get("bed_temp_f")
        room_temp = es.get("room_temperature_f") or es.get("room_temp_f")
        es_level  = es.get("sleep_temperature_level") or es.get("temperature_level")

        efficiency   = wh.get("sleep_efficiency")
        deep_pct     = wh.get("deep_sleep_pct") or wh.get("sws_pct")
        rem_pct      = wh.get("rem_sleep_pct")
        hrv          = wh.get("hrv")
        sleep_score  = wh.get("sleep_performance_pct") or wh.get("sleep_score")
        duration_h   = wh.get("sleep_duration_hours")

        if bed_temp is None and room_temp is None:
            continue
        if efficiency is None and deep_pct is None:
            continue

        paired.append({
            "date":          date_key,
            "bed_temp_f":    float(bed_temp) if bed_temp else None,
            "room_temp_f":   float(room_temp) if room_temp else None,
            "temp_level":    es_level,
            "efficiency":    float(efficiency) if efficiency else None,
            "deep_pct":      float(deep_pct) if deep_pct else None,
            "rem_pct":       float(rem_pct) if rem_pct else None,
            "hrv":           float(hrv) if hrv else None,
            "sleep_score":   float(sleep_score) if sleep_score else None,
            "duration_h":    float(duration_h) if duration_h else None,
        })

    if len(paired) < 14:
        return {"error": f"Need ≥14 nights of paired Eight Sleep + Whoop data. Found {len(paired)}."}

    # ── Temperature band analysis ──
    def bucket_temp(t):
        if t is None:
            return None
        if t < 64:
            return "cold (<64°F)"
        elif t < 67:
            return "cool (64-66°F)"
        elif t < 70:
            return "neutral (67-69°F)"
        elif t < 73:
            return "warm (70-72°F)"
        else:
            return "hot (73°F+)"

    band_stats = defaultdict(lambda: {
        "nights": 0, "efficiency": [], "deep_pct": [], "rem_pct": [],
        "hrv": [], "sleep_score": [], "duration_h": [],
    })
    for p in paired:
        band = bucket_temp(p.get("bed_temp_f"))
        if not band:
            band = bucket_temp(p.get("room_temp_f"))
        if not band:
            continue
        bs = band_stats[band]
        bs["nights"] += 1
        for field in ["efficiency", "deep_pct", "rem_pct", "hrv", "sleep_score", "duration_h"]:
            if p.get(field) is not None:
                bs[field].append(p[field])

    def safe_avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    band_results = []
    for band_name in ["cold (<64°F)", "cool (64-66°F)", "neutral (67-69°F)", "warm (70-72°F)", "hot (73°F+)"]:
        bs = band_stats.get(band_name)
        if not bs or bs["nights"] < 3:
            continue
        band_results.append({
            "band":            band_name,
            "nights":          bs["nights"],
            "avg_efficiency":  safe_avg(bs["efficiency"]),
            "avg_deep_pct":    safe_avg(bs["deep_pct"]),
            "avg_rem_pct":     safe_avg(bs["rem_pct"]),
            "avg_hrv":         safe_avg(bs["hrv"]),
            "avg_sleep_score": safe_avg(bs["sleep_score"]),
            "avg_duration_h":  safe_avg(bs["duration_h"]),
        })

    # Find optimal band by composite score (efficiency + deep + HRV)
    best_band = None
    best_composite = -1
    for br in band_results:
        eff = br.get("avg_efficiency") or 0
        dep = br.get("avg_deep_pct") or 0
        hrv_v = br.get("avg_hrv") or 0
        # Composite: efficiency 40% (best-validated consumer metric), deep 30%, HRV 30%
        composite = eff / 100 * 40 + dep / 30 * 30 + min(hrv_v / 100, 1.0) * 30
        br["composite_score"] = round(composite, 1)
        if composite > best_composite:
            best_composite = composite
            best_band = br["band"]

    # ── Correlations: bed temp vs sleep metrics ──
    correlations = []
    bed_temps = [p["bed_temp_f"] for p in paired if p.get("bed_temp_f") is not None]
    for metric_name, metric_key in [("efficiency", "efficiency"), ("deep_sleep_pct", "deep_pct"),
                                     ("rem_sleep_pct", "rem_pct"), ("HRV", "hrv")]:
        vals = [p[metric_key] for p in paired if p.get("bed_temp_f") is not None and p.get(metric_key) is not None]
        temps = [p["bed_temp_f"] for p in paired if p.get("bed_temp_f") is not None and p.get(metric_key) is not None]
        if len(vals) >= 14:
            r = pearson_r(temps, vals)
            if r is not None:
                correlations.append({
                    "metric": metric_name,
                    "r":      r,
                    "n":      len(vals),
                    "interpretation": (
                        f"{'Cooler' if r < 0 else 'Warmer'} bed temps "
                        f"correlate with {'better' if (r < 0 and metric_name != 'HRV') or (r > 0 and metric_name == 'HRV') else 'lower'} {metric_name}"
                        if abs(r) >= 0.2 else f"No meaningful correlation with {metric_name}"
                    ),
                })

    # ── Recommendations ──
    recommendations = []
    if best_band:
        recommendations.append(f"Your best sleep occurs in the {best_band} range. Set Eight Sleep to target this band.")
    cool_bands = [br for br in band_results if "cold" in br["band"] or "cool" in br["band"]]
    warm_bands = [br for br in band_results if "warm" in br["band"] or "hot" in br["band"]]
    if cool_bands and warm_bands:
        cool_eff = safe_avg([b.get("avg_efficiency") or 0 for b in cool_bands])
        warm_eff = safe_avg([b.get("avg_efficiency") or 0 for b in warm_bands])
        if cool_eff and warm_eff and cool_eff > warm_eff + 2:
            recommendations.append(
                f"Cool nights average {cool_eff}% efficiency vs {warm_eff}% warm. "
                "Huberman/Walker: cooler is better for deep sleep initiation."
            )

    return {
        "period":          {"start_date": start_date, "end_date": end_date, "paired_nights": len(paired)},
        "optimal_band":    best_band,
        "band_analysis":   band_results,
        "correlations":    correlations,
        "recommendations": recommendations,
        "methodology":     (
            "Pairs Eight Sleep bed temperature with Whoop sleep staging nightly. "
            "Groups nights into temperature bands and compares sleep efficiency, deep %, "
            "REM %, and HRV across bands. Composite score weights: efficiency 40%, deep 30%, HRV 30%. "
            "Clinical reference: Huberman/Walker recommend 65-68°F (18-20°C) for optimal sleep."
        ),
    }
