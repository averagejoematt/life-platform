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


def tool_get_sleep_environment_analysis(args):
    """
    Sleep environment optimization. Correlates Eight Sleep bed temperature
    with sleep outcomes. Huberman: core body temp drop is #1 sleep trigger.
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
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
        ("hrv_avg",              "HRV",                "higher_is_better"),
    ]

    records = []
    no_temp_count = 0

    for item in es_items:
        date = item.get("date")
        bed_temp_c = _sf(item.get("bed_temp_c"))
        bed_temp_f = _sf(item.get("bed_temp_f"))
        temp_level = _sf(item.get("temp_level_avg"))
        room_temp_c = _sf(item.get("room_temp_c"))
        room_temp_f = _sf(item.get("room_temp_f"))

        if bed_temp_c is not None and bed_temp_f is None:
            bed_temp_f = round(bed_temp_c * 9/5 + 32, 1)
        if bed_temp_f is not None and bed_temp_c is None:
            bed_temp_c = round((bed_temp_f - 32) * 5/9, 1)

        has_temp = bed_temp_f is not None or temp_level is not None
        if not has_temp:
            no_temp_count += 1
            continue

        eff = _sf(item.get("sleep_efficiency_pct"))
        score = _sf(item.get("sleep_score"))
        if eff is None and score is None:
            continue

        records.append({
            "date": date,
            "bed_temp_f": bed_temp_f, "bed_temp_c": bed_temp_c,
            "room_temp_f": room_temp_f, "room_temp_c": _sf(item.get("room_temp_c")),
            "temp_level": temp_level,
            "temp_level_min": _sf(item.get("temp_level_min")),
            "temp_level_max": _sf(item.get("temp_level_max")),
            "sleep_efficiency_pct": eff,
            "deep_pct": _sf(item.get("deep_pct")),
            "rem_pct": _sf(item.get("rem_pct")),
            "sleep_score": score,
            "sleep_duration_hours": _sf(item.get("sleep_duration_hours")),
            "time_to_sleep_min": _sf(item.get("time_to_sleep_min")),
            "hrv_avg": _sf(item.get("hrv_avg")),
        })

    if not records:
        return {
            "error": f"No nights with temperature data found. {no_temp_count} nights checked.",
            "start_date": start_date, "end_date": end_date,
            "tip": "Temperature data requires Eight Sleep ingestion v2.35.0+ (intervals API). Deploy and wait for new nights.",
        }

    has_bed_temp = sum(1 for r in records if r["bed_temp_f"] is not None)
    has_temp_level = sum(1 for r in records if r["temp_level"] is not None)
    use_bed_temp = has_bed_temp >= len(records) * 0.5
    use_temp_level = has_temp_level >= len(records) * 0.5

    # Bucket analysis by bed temperature (°F)
    bucket_data = {}
    if use_bed_temp:
        TEMP_BUCKETS = [
            ("below_64F", "Below 64°F (< 18°C)", lambda t: t < 64),
            ("64_66F",    "64-66°F (18-19°C)",    lambda t: 64 <= t < 66),
            ("66_68F",    "66-68°F (19-20°C)",    lambda t: 66 <= t < 68),
            ("68_70F",    "68-70°F (20-21°C)",    lambda t: 68 <= t < 70),
            ("70_72F",    "70-72°F (21-22°C)",    lambda t: 70 <= t < 72),
            ("above_72F", "Above 72°F (> 22°C)",  lambda t: t >= 72),
        ]
        for bucket_key, label, condition in TEMP_BUCKETS:
            b_records = [r for r in records if r["bed_temp_f"] is not None and condition(r["bed_temp_f"])]
            if not b_records:
                continue
            bucket_data[bucket_key] = {
                "label": label, "nights": len(b_records),
                "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    bucket_data[bucket_key]["metrics"][field] = {"label": mlabel, "avg": round(sum(vals)/len(vals), 2), "n": len(vals)}

    # Bucket analysis by temp level (-10 to +10)
    level_bucket_data = {}
    if use_temp_level:
        LEVEL_BUCKETS = [
            ("very_cool",  "Very Cool (-10 to -6)", lambda l: l <= -6),
            ("cool",       "Cool (-5 to -2)",       lambda l: -5 <= l <= -2),
            ("neutral",    "Neutral (-1 to +1)",    lambda l: -1 <= l <= 1),
            ("warm",       "Warm (+2 to +5)",       lambda l: 2 <= l <= 5),
            ("very_warm",  "Very Warm (+6 to +10)", lambda l: l >= 6),
        ]
        for bucket_key, label, condition in LEVEL_BUCKETS:
            b_records = [r for r in records if r["temp_level"] is not None and condition(r["temp_level"])]
            if not b_records:
                continue
            level_bucket_data[bucket_key] = {
                "label": label, "nights": len(b_records),
                "avg_level": _avg([r["temp_level"] for r in b_records]),
                "metrics": {},
            }
            for field, mlabel, _ in SLEEP_METRICS:
                vals = [r[field] for r in b_records if r[field] is not None]
                if vals:
                    level_bucket_data[bucket_key]["metrics"][field] = {"label": mlabel, "avg": round(sum(vals)/len(vals), 2), "n": len(vals)}

    # Pearson correlations
    temp_correlations = {}
    if use_bed_temp:
        temp_rows = [r for r in records if r["bed_temp_f"] is not None]
        for field, label, direction in SLEEP_METRICS:
            xs = [r["bed_temp_f"] for r in temp_rows if r[field] is not None]
            ys = [r[field] for r in temp_rows if r[field] is not None]
            r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
            if r_val is not None:
                if direction == "higher_is_better":
                    impact = "cooler_is_better" if r_val < -0.15 else ("warmer_is_better" if r_val > 0.15 else "no_significant_effect")
                else:
                    impact = "cooler_is_better" if r_val > 0.15 else ("warmer_is_better" if r_val < -0.15 else "no_significant_effect")
                temp_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    level_correlations = {}
    if use_temp_level:
        level_rows = [r for r in records if r["temp_level"] is not None]
        for field, label, direction in SLEEP_METRICS:
            xs = [r["temp_level"] for r in level_rows if r[field] is not None]
            ys = [r[field] for r in level_rows if r[field] is not None]
            r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
            if r_val is not None:
                if direction == "higher_is_better":
                    impact = "cooler_is_better" if r_val < -0.15 else ("warmer_is_better" if r_val > 0.15 else "no_significant_effect")
                else:
                    impact = "cooler_is_better" if r_val > 0.15 else ("warmer_is_better" if r_val < -0.15 else "no_significant_effect")
                level_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # Find optimal temperature
    optimal = {}
    if bucket_data:
        best_bucket = None
        best_eff = 0
        for bk, bv in bucket_data.items():
            eff = (bv.get("metrics", {}).get("sleep_efficiency_pct", {}) or {}).get("avg", 0)
            if eff > best_eff and bv["nights"] >= 3:
                best_eff = eff
                best_bucket = bk
        if best_bucket:
            optimal["by_efficiency"] = {"bucket": bucket_data[best_bucket]["label"], "avg_efficiency": best_eff, "nights": bucket_data[best_bucket]["nights"]}

        best_deep_bucket = None
        best_deep = 0
        for bk, bv in bucket_data.items():
            deep = (bv.get("metrics", {}).get("deep_pct", {}) or {}).get("avg", 0)
            if deep > best_deep and bv["nights"] >= 3:
                best_deep = deep
                best_deep_bucket = bk
        if best_deep_bucket:
            optimal["by_deep_sleep"] = {"bucket": bucket_data[best_deep_bucket]["label"], "avg_deep_pct": best_deep, "nights": bucket_data[best_deep_bucket]["nights"]}

    # Room temperature analysis
    room_analysis = None
    room_records = [r for r in records if r.get("room_temp_f") is not None]
    if room_records:
        room_temps = [r["room_temp_f"] for r in room_records]
        room_analysis = {"avg_room_temp_f": _avg(room_temps), "min_room_temp_f": round(min(room_temps), 1), "max_room_temp_f": round(max(room_temps), 1), "nights_measured": len(room_records)}

    # Board of Directors
    bod = []
    bod.append("Huberman: The single most important environmental factor for sleep is temperature. A 2-3°F core body temperature drop initiates the sleep cascade. Cool the bedroom to 65-68°F.")
    cool_benefit = temp_correlations.get("sleep_efficiency_pct", {}).get("impact")
    if cool_benefit == "cooler_is_better":
        r_val = temp_correlations["sleep_efficiency_pct"]["pearson_r"]
        bod.append(f"Your data confirms: cooler bed temperatures correlate with better sleep efficiency (r={r_val}).")
    elif cool_benefit == "warmer_is_better":
        bod.append("Your data shows warmer temperatures correlating with better sleep — your baseline room may already be quite cool, or you run cold at night.")
    deep_impact = temp_correlations.get("deep_pct", {}).get("impact")
    if deep_impact == "cooler_is_better":
        bod.append("Walker: Deep sleep is most sensitive to temperature. Your data confirms cooler bed temps increase deep sleep %.")
    if optimal.get("by_efficiency"):
        bod.append(f"Attia: Your optimal temperature zone for sleep efficiency is {optimal['by_efficiency']['bucket']} based on {optimal['by_efficiency']['nights']} nights.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_nights_with_temp_data": len(records),
        "nights_without_temp_data": no_temp_count,
        "temperature_summary": {
            "avg_bed_temp_f": _avg([r["bed_temp_f"] for r in records if r["bed_temp_f"]]),
            "avg_bed_temp_c": _avg([r["bed_temp_c"] for r in records if r["bed_temp_c"]]),
            "avg_temp_level": _avg([r["temp_level"] for r in records if r["temp_level"]]),
            "avg_room_temp_f": _avg([r["room_temp_f"] for r in records if r.get("room_temp_f")]),
        },
        "optimal_temperature": optimal,
        "bucket_analysis_bed_temp": bucket_data if bucket_data else None,
        "bucket_analysis_temp_level": level_bucket_data if level_bucket_data else None,
        "correlations_bed_temp": temp_correlations if temp_correlations else None,
        "correlations_temp_level": level_correlations if level_correlations else None,
        "room_temperature": room_analysis,
        "board_of_directors": bod,
        "methodology": (
            "Bed temperature from Eight Sleep intervals API. Sleep metrics from Eight Sleep trends. "
            "Bucket analysis splits nights by temperature range and compares average sleep outcomes. "
            "Pearson correlations quantify linear relationship between temperature and sleep quality. "
            "Optimal temperature = bucket with highest sleep efficiency among buckets with >= 3 nights. "
            "Clinical reference: Huberman/Walker recommend 65-68°F (18-20°C)."
        ),
        "source": "eightsleep (intervals + trends)",
    }
