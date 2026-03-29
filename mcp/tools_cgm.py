"""
CGM / glucose tools.
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
)


# ── CGM helpers ──

# SEC-3 (HIGH): Compiled once at module load — avoids recompiling on every CGM call.
# Used by _load_cgm_readings to prevent S3 path traversal via malformed date_str.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_cgm_readings(date_str):
    """
    Load 5-minute CGM readings from S3 for a given date.
    Returns list of (hour_decimal, value_mg_dl) tuples sorted by time.

    SEC-3 (HIGH): date_str is validated before S3 key construction to prevent
    path traversal (e.g. '../../config/board_of_directors' -> wrong S3 object).
    A malformed date_str would split("-") into unexpected segments and produce
    a key like raw/matthew/cgm_readings/../../config/..., reading an unintended
    object. The regex + strptime checks eliminate this class of input entirely.
    """
    # Validate format and calendar validity before constructing S3 key
    if not _DATE_RE.match(str(date_str)):
        logger.warning("_load_cgm_readings: invalid date_str format: %r -- rejecting", date_str)
        return []
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning("_load_cgm_readings: non-calendar date: %r -- rejecting", date_str)
        return []
    try:
        y, m, d = date_str.split("-")
        key = f"raw/{USER_ID}/cgm_readings/{y}/{m}/{d}.json"
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        readings = json.loads(resp["Body"].read())
        result = []
        for r in readings:
            val = r.get("value")
            time_str = r.get("time", "")
            if val is None or not time_str:
                continue
            # Parse "2024-10-15 11:04:29 -0800" format
            try:
                parts = time_str.strip().split(" ")
                hms = parts[1].split(":")
                hour_dec = int(hms[0]) + int(hms[1]) / 60 + int(hms[2]) / 3600
                result.append((hour_dec, float(val)))
            except (IndexError, ValueError):
                continue
        return sorted(result, key=lambda x: x[0])
    except s3_client.exceptions.NoSuchKey:
        return []
    except Exception as e:
        logger.warning(f"CGM read failed for {date_str}: {e}")
        return []


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
        "summary": summary, "trend": trend, "clinical_flags": flags or [], "daily": rows,
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
        except Exception: return None

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
                          "Time above 140 is most actionable -- spikes raise core temperature, opposing deep sleep.",
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
        except Exception: return None

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


def tool_get_glucose_meal_response(args):
    """
    Levels-style postprandial glucose response analysis.

    For each meal logged in MacroFactor, matches 5-min CGM readings from S3
    to compute: pre-meal baseline, peak glucose, spike magnitude, time-to-peak,
    time to return to baseline, and a letter grade.

    Aggregates: best/worst meals, macro correlations (carbs/fiber/protein vs spike),
    personal food scores across multiple days.

    Based on Attia, Huberman, Lustig: postprandial spikes >30 mg/dL drive insulin
    resistance, inflammation, and accelerated glycation. Fiber, protein, and fat
    blunt the spike; refined carbs and sugar amplify it.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    meal_gap_minutes = args.get("meal_gap_minutes", 30)
    baseline_window_min = 30  # minutes before meal for baseline
    postprandial_window_min = 120  # 2-hour response window

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def t2d(t):
        """Convert HH:MM string to decimal hours."""
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        """Convert decimal hours to HH:MM string."""
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1
            m = 0
        return f"{h:02d}:{m:02d}"

    def score_spike(spike):
        """Grade a glucose spike magnitude."""
        if spike is None:
            return None
        if spike < 15:
            return "A"
        elif spike < 30:
            return "B"
        elif spike < 40:
            return "C"
        elif spike < 50:
            return "D"
        else:
            return "F"

    # ── Load MacroFactor food logs ────────────────────────────────────────
    mf_items = query_source("macrofactor", start_date, end_date)
    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    all_meals = []
    food_scores = defaultdict(list)  # food_name -> list of spike values
    days_with_data = 0
    days_without_cgm = 0

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue
        food_log = mf_item.get("food_log", [])
        if not food_log:
            continue

        # Load CGM readings for this day
        readings = _load_cgm_readings(date)
        if len(readings) < 20:  # need reasonable CGM coverage
            days_without_cgm += 1
            continue
        days_with_data += 1

        # ── Group food items into meals by timestamp proximity ────────
        entries_with_time = []
        for entry in food_log:
            td = t2d(entry.get("time"))
            if td is not None:
                entries_with_time.append((td, entry))
        entries_with_time.sort(key=lambda x: x[0])

        meals = []
        current_meal = []
        current_meal_start = None
        for td, entry in entries_with_time:
            if current_meal_start is None or (td - current_meal_start) * 60 > meal_gap_minutes:
                if current_meal:
                    meals.append(current_meal)
                current_meal = [(td, entry)]
                current_meal_start = td
            else:
                current_meal.append((td, entry))
        if current_meal:
            meals.append(current_meal)

        # ── Analyze each meal ─────────────────────────────────────────
        for meal_entries in meals:
            meal_time_dec = meal_entries[0][0]  # earliest item time
            meal_time_str = d2hm(meal_time_dec)

            # Meal macros
            meal_cals = sum(_sf(e.get("calories_kcal")) or 0 for _, e in meal_entries)
            meal_carbs = sum(_sf(e.get("carbs_g")) or 0 for _, e in meal_entries)
            meal_protein = sum(_sf(e.get("protein_g")) or 0 for _, e in meal_entries)
            meal_fat = sum(_sf(e.get("fat_g")) or 0 for _, e in meal_entries)
            meal_fiber = sum(_sf(e.get("fiber_g")) or 0 for _, e in meal_entries)
            meal_sugar = sum(_sf(e.get("sugars_g")) or 0 for _, e in meal_entries)
            food_names = [e.get("food_name", "Unknown") for _, e in meal_entries]

            # Pre-meal baseline: avg glucose in 30 min before meal
            baseline_start = meal_time_dec - baseline_window_min / 60
            baseline_readings = [v for t, v in readings if baseline_start <= t < meal_time_dec]
            if len(baseline_readings) < 2:
                # Try wider window (45 min)
                baseline_start = meal_time_dec - 45 / 60
                baseline_readings = [v for t, v in readings if baseline_start <= t < meal_time_dec]
            if len(baseline_readings) < 2:
                continue  # can't compute without baseline

            baseline = sum(baseline_readings) / len(baseline_readings)

            # Postprandial window: 2 hours after meal start
            post_start = meal_time_dec
            post_end = meal_time_dec + postprandial_window_min / 60
            post_readings = [(t, v) for t, v in readings if post_start <= t <= post_end]
            if len(post_readings) < 4:
                continue  # insufficient coverage

            # Peak and timing
            peak_time, peak_value = max(post_readings, key=lambda x: x[1])
            spike = round(peak_value - baseline, 1)
            time_to_peak_min = round((peak_time - meal_time_dec) * 60, 0)

            # Time to return to baseline (within 2hr window)
            returned_at = None
            if spike > 5:  # only track return if meaningful spike
                for t, v in post_readings:
                    if t > peak_time and v <= baseline + 5:
                        returned_at = round((t - meal_time_dec) * 60, 0)
                        break

            # AUC above baseline (trapezoidal, in mg/dL-minutes)
            auc = 0.0
            sorted_post = sorted(post_readings, key=lambda x: x[0])
            for i in range(1, len(sorted_post)):
                t0, v0 = sorted_post[i - 1]
                t1, v1 = sorted_post[i]
                dt_min = (t1 - t0) * 60
                excess0 = max(0, v0 - baseline)
                excess1 = max(0, v1 - baseline)
                auc += (excess0 + excess1) / 2 * dt_min

            grade = score_spike(spike)

            meal_record = {
                "date": date,
                "meal_time": meal_time_str,
                "foods": food_names[:8],  # cap at 8 for readability
                "item_count": len(food_names),
                "calories": round(meal_cals),
                "carbs_g": round(meal_carbs, 1),
                "protein_g": round(meal_protein, 1),
                "fat_g": round(meal_fat, 1),
                "fiber_g": round(meal_fiber, 1),
                "sugar_g": round(meal_sugar, 1),
                "baseline_mg_dl": round(baseline, 1),
                "peak_mg_dl": round(peak_value, 1),
                "spike_mg_dl": spike,
                "time_to_peak_min": int(time_to_peak_min),
                "return_to_baseline_min": int(returned_at) if returned_at else None,
                "auc_above_baseline": round(auc, 1),
                "grade": grade,
            }
            all_meals.append(meal_record)

            # Track per-food scores
            for _, entry in meal_entries:
                fn = entry.get("food_name", "Unknown")
                food_scores[fn].append(spike)

    if not all_meals:
        return {
            "error": "No meals with matching CGM data found.",
            "days_checked": len(mf_items),
            "days_without_cgm": days_without_cgm,
            "hint": "Need overlapping MacroFactor food logs + CGM readings on the same days.",
        }

    # ── Aggregate analysis ────────────────────────────────────────────────
    spikes = [m["spike_mg_dl"] for m in all_meals]
    grades = [m["grade"] for m in all_meals]
    avg_spike = round(sum(spikes) / len(spikes), 1)

    # Grade distribution
    grade_dist = {}
    for g in ["A", "B", "C", "D", "F"]:
        ct = grades.count(g)
        if ct > 0:
            grade_dist[g] = ct

    # Best and worst meals
    sorted_by_spike = sorted(all_meals, key=lambda x: x["spike_mg_dl"])
    best_meals = sorted_by_spike[:5]
    worst_meals = sorted_by_spike[-5:][::-1]

    # Food scores (foods appearing 2+ times)
    food_summary = []
    for fn, spikes_list in sorted(food_scores.items()):
        if len(spikes_list) >= 2:
            avg_s = round(sum(spikes_list) / len(spikes_list), 1)
            food_summary.append({
                "food": fn,
                "appearances": len(spikes_list),
                "avg_spike": avg_s,
                "grade": score_spike(avg_s),
            })
    food_summary.sort(key=lambda x: x["avg_spike"])

    # Macro correlations (carbs, fiber, protein, sugar vs spike)
    correlations = {}
    for macro_field, label in [
        ("carbs_g", "carbs"), ("fiber_g", "fiber"),
        ("protein_g", "protein"), ("fat_g", "fat"),
        ("sugar_g", "sugar"), ("calories", "calories"),
    ]:
        xs = [m[macro_field] for m in all_meals if m.get(macro_field) is not None]
        ys = [m["spike_mg_dl"] for m in all_meals if m.get(macro_field) is not None]
        if len(xs) >= 7:
            r_val = pearson_r(xs, ys)
            if r_val is not None:
                correlations[f"{label}_vs_spike"] = round(r_val, 3)

    # Fiber-to-carb ratio analysis
    high_fiber_meals = [m for m in all_meals if m["carbs_g"] > 10 and m["fiber_g"] / max(m["carbs_g"], 1) > 0.15]
    low_fiber_meals = [m for m in all_meals if m["carbs_g"] > 10 and m["fiber_g"] / max(m["carbs_g"], 1) <= 0.15]
    fiber_ratio_impact = None
    if len(high_fiber_meals) >= 3 and len(low_fiber_meals) >= 3:
        hf_avg = round(sum(m["spike_mg_dl"] for m in high_fiber_meals) / len(high_fiber_meals), 1)
        lf_avg = round(sum(m["spike_mg_dl"] for m in low_fiber_meals) / len(low_fiber_meals), 1)
        fiber_ratio_impact = {
            "high_fiber_ratio_meals": len(high_fiber_meals),
            "high_fiber_avg_spike": hf_avg,
            "low_fiber_ratio_meals": len(low_fiber_meals),
            "low_fiber_avg_spike": lf_avg,
            "fiber_benefit_mg_dl": round(lf_avg - hf_avg, 1),
        }

    # Personal recommendation
    rec = []
    if avg_spike > 40:
        rec.append("Average spike is HIGH (>40 mg/dL). Prioritize reducing refined carbs and adding fiber/protein to meals.")
    elif avg_spike > 30:
        rec.append("Average spike is ELEVATED (30-40 mg/dL). Good opportunity to optimize meal composition.")
    elif avg_spike > 15:
        rec.append("Average spike is MODERATE (15-30 mg/dL). Solid metabolic health -- fine-tune worst offenders.")
    else:
        rec.append("Average spike is EXCELLENT (<15 mg/dL). Outstanding glucose control.")

    if correlations.get("fiber_vs_spike") and correlations["fiber_vs_spike"] < -0.15:
        rec.append(f"Fiber is protective (r={correlations['fiber_vs_spike']}). Keep prioritizing high-fiber meals.")
    if correlations.get("sugar_vs_spike") and correlations["sugar_vs_spike"] > 0.2:
        rec.append(f"Sugar drives spikes (r={correlations['sugar_vs_spike']}). Reduce added sugars.")

    return {
        "period": {"start": start_date, "end": end_date},
        "data_coverage": {
            "days_with_food_log": len(mf_items),
            "days_with_cgm": days_with_data,
            "days_without_cgm": days_without_cgm,
            "total_meals_analyzed": len(all_meals),
        },
        "summary": {
            "avg_spike_mg_dl": avg_spike,
            "avg_grade": score_spike(avg_spike),
            "grade_distribution": grade_dist,
            "avg_time_to_peak_min": round(sum(m["time_to_peak_min"] for m in all_meals) / len(all_meals)),
        },
        "best_meals": best_meals,
        "worst_meals": worst_meals,
        "food_scores": food_summary[:20] if food_summary else None,
        "macro_correlations": correlations if correlations else None,
        "fiber_ratio_impact": fiber_ratio_impact,
        "recommendation": rec,
        "meals": all_meals[-30:],  # last 30 meals for detail
        "note": "Scoring: A (<15 spike), B (15-30), C (30-40), D (40-50), F (>50 mg/dL). "
                "Based on Attia/Huberman: spikes >30 drive insulin resistance. "
                "Fiber, protein, fat blunt spikes; refined carbs and sugar amplify them.",
    }


def tool_get_fasting_glucose_validation(args):
    """
    Validate CGM fasting glucose proxy against venous lab draws.

    Two modes:
      1. Direct validation: same-day CGM overnight nadir vs lab fasting glucose
      2. Statistical validation: CGM nadir distribution vs historical lab values

    Computes proper overnight nadir using 00:00-06:00 window (avoids dawn
    phenomenon cortisol rise per Attia/Huberman). Also computes the narrower
    02:00-05:00 "deep nadir" which excludes both late digestion and dawn effect.

    Returns: nadir distribution, lab comparisons, bias analysis, confidence.
    """
    import statistics

    # ── Parameters ────────────────────────────────────────────────────────
    nadir_start = float(args.get("nadir_start_hour", 0))      # midnight
    nadir_end   = float(args.get("nadir_end_hour", 6))        # 6 AM
    deep_start  = float(args.get("deep_nadir_start_hour", 2)) # 2 AM
    deep_end    = float(args.get("deep_nadir_end_hour", 5))   # 5 AM
    min_readings = int(args.get("min_overnight_readings", 6))  # need ~30 min coverage

    # ── Discover all CGM days from S3 ─────────────────────────────────────
    paginator = s3_client.get_paginator("list_objects_v2")
    cgm_days = []  # list of "YYYY-MM-DD"
    for prefix_year in ["2024/", "2025/", "2026/"]:
        try:
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"raw/{USER_ID}/cgm_readings/{prefix_year}"):
                for obj in page.get("Contents", []):
                    key = obj["Key"]  # raw/cgm_readings/2024/10/01.json
                    parts = key.replace(f"raw/{USER_ID}/cgm_readings/", "").replace(".json", "").split("/")
                    if len(parts) == 3:
                        y, m, d = parts
                        cgm_days.append(f"{y}-{m.zfill(2)}-{d.zfill(2)}")
        except Exception:
            continue
    cgm_days.sort()

    if not cgm_days:
        return {"error": "No CGM data found in S3."}

    # ── Compute overnight nadirs for each day ────────────────────────────
    nadir_results = []  # list of dicts per day
    for date_str in cgm_days:
        readings = _load_cgm_readings(date_str)
        if not readings:
            continue

        # Filter to overnight window (midnight to nadir_end)
        overnight = [(h, v) for h, v in readings if nadir_start <= h < nadir_end]
        deep_night = [(h, v) for h, v in readings if deep_start <= h < deep_end]

        if len(overnight) < min_readings:
            continue

        overnight_vals = [v for _, v in overnight]
        on_min = min(overnight_vals)
        on_avg = sum(overnight_vals) / len(overnight_vals)
        on_min_time = None
        for h, v in overnight:
            if v == on_min:
                hh = int(h)
                mm = int((h - hh) * 60)
                on_min_time = f"{hh:02d}:{mm:02d}"
                break

        deep_min = None
        deep_avg = None
        if len(deep_night) >= 4:
            deep_vals = [v for _, v in deep_night]
            deep_min = min(deep_vals)
            deep_avg = round(sum(deep_vals) / len(deep_vals), 1)

        # Full-day min for comparison (current proxy method)
        all_vals = [v for _, v in readings]
        daily_min = min(all_vals) if all_vals else None

        nadir_results.append({
            "date": date_str,
            "overnight_nadir": on_min,
            "overnight_avg": round(on_avg, 1),
            "overnight_nadir_time": on_min_time,
            "overnight_readings": len(overnight),
            "deep_nadir": deep_min,
            "deep_avg": deep_avg,
            "daily_min": daily_min,
            "daily_min_vs_overnight": round(daily_min - on_min, 1) if daily_min is not None else None,
        })

    if not nadir_results:
        return {"error": "Insufficient overnight CGM readings across all days."}

    # ── Distribution stats ───────────────────────────────────────────────
    on_nadirs = [r["overnight_nadir"] for r in nadir_results]
    deep_nadirs = [r["deep_nadir"] for r in nadir_results if r["deep_nadir"] is not None]
    daily_mins = [r["daily_min"] for r in nadir_results if r["daily_min"] is not None]

    def dist_stats(vals, label):
        if not vals:
            return None
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "label": label,
            "n": n,
            "mean": round(statistics.mean(vals_sorted), 1),
            "median": round(statistics.median(vals_sorted), 1),
            "std_dev": round(statistics.stdev(vals_sorted), 1) if n > 1 else 0,
            "min": vals_sorted[0],
            "max": vals_sorted[-1],
            "p10": round(vals_sorted[int(n * 0.1)], 1),
            "p25": round(vals_sorted[int(n * 0.25)], 1),
            "p75": round(vals_sorted[int(n * 0.75)], 1),
            "p90": round(vals_sorted[int(n * 0.9)], 1),
        }

    distributions = {
        "overnight_nadir_00_06": dist_stats(on_nadirs, "Overnight nadir (00:00-06:00)"),
        "deep_nadir_02_05": dist_stats(deep_nadirs, "Deep nadir (02:00-05:00)"),
        "daily_minimum": dist_stats(daily_mins, "Daily minimum (current proxy)"),
    }

    # ── Load lab fasting glucose ─────────────────────────────────────────
    from boto3.dynamodb.conditions import Key
    lab_resp = table.query(
        KeyConditionExpression=Key("pk").eq(USER_PREFIX + "labs") & Key("sk").begins_with("DATE#")
    )
    lab_draws = []
    for item in lab_resp.get("Items", []):
        glucose_bm = item.get("biomarkers", {}).get("glucose", {})
        val = glucose_bm.get("value_numeric")
        if val is not None:
            lab_draws.append({
                "draw_date": item.get("draw_date"),
                "fasting_glucose_mg_dl": float(val),
                "provider": item.get("lab_provider", "unknown"),
            })

    # ── Direct validation (same-day overlap) ─────────────────────────────
    nadir_by_date = {r["date"]: r for r in nadir_results}
    direct_validations = []
    for draw in lab_draws:
        dd = draw["draw_date"]
        if dd in nadir_by_date:
            nr = nadir_by_date[dd]
            diff_overnight = round(draw["fasting_glucose_mg_dl"] - nr["overnight_nadir"], 1)
            diff_deep = round(draw["fasting_glucose_mg_dl"] - nr["deep_nadir"], 1) if nr["deep_nadir"] else None
            direct_validations.append({
                "date": dd,
                "lab_fasting_glucose": draw["fasting_glucose_mg_dl"],
                "cgm_overnight_nadir": nr["overnight_nadir"],
                "cgm_deep_nadir": nr["deep_nadir"],
                "cgm_daily_min": nr["daily_min"],
                "lab_minus_cgm_overnight": diff_overnight,
                "lab_minus_cgm_deep": diff_deep,
                "provider": draw["provider"],
            })

    # ── Statistical validation (no overlap) ──────────────────────────────
    stat_validations = []
    on_stats = distributions["overnight_nadir_00_06"]
    deep_stats = distributions["deep_nadir_02_05"]

    for draw in lab_draws:
        lab_val = draw["fasting_glucose_mg_dl"]
        z_overnight = None
        if on_stats and on_stats["std_dev"] > 0:
            z_overnight = round((lab_val - on_stats["mean"]) / on_stats["std_dev"], 2)
        z_deep = None
        if deep_stats and deep_stats["std_dev"] > 0:
            z_deep = round((lab_val - deep_stats["mean"]) / deep_stats["std_dev"], 2)

        pct = None
        if on_nadirs:
            below = sum(1 for v in on_nadirs if v <= lab_val)
            pct = round(below / len(on_nadirs) * 100, 1)

        stat_validations.append({
            "draw_date": draw["draw_date"],
            "lab_fasting_glucose": lab_val,
            "vs_overnight_nadir": {
                "z_score": z_overnight,
                "percentile_of_nadir_dist": pct,
                "within_1sd": abs(z_overnight) <= 1 if z_overnight is not None else None,
                "within_2sd": abs(z_overnight) <= 2 if z_overnight is not None else None,
            },
            "vs_deep_nadir": {
                "z_score": z_deep,
                "within_1sd": abs(z_deep) <= 1 if z_deep is not None else None,
            } if z_deep is not None else None,
            "provider": draw["provider"],
        })

    # ── Bias analysis ────────────────────────────────────────────────────
    bias = {}
    if on_stats and lab_draws:
        lab_mean = sum(d["fasting_glucose_mg_dl"] for d in lab_draws) / len(lab_draws)
        bias["lab_mean_fasting"] = round(lab_mean, 1)
        bias["cgm_overnight_nadir_mean"] = on_stats["mean"]
        bias["cgm_daily_min_mean"] = distributions["daily_minimum"]["mean"] if distributions["daily_minimum"] else None
        bias["lab_minus_cgm_overnight"] = round(lab_mean - on_stats["mean"], 1)
        if distributions["daily_minimum"]:
            bias["lab_minus_cgm_daily_min"] = round(lab_mean - distributions["daily_minimum"]["mean"], 1)
        if deep_stats:
            bias["cgm_deep_nadir_mean"] = deep_stats["mean"]
            bias["lab_minus_cgm_deep"] = round(lab_mean - deep_stats["mean"], 1)

        diff = bias["lab_minus_cgm_overnight"]
        if abs(diff) <= 5:
            bias["interpretation"] = "Excellent agreement -- CGM overnight nadir closely matches lab fasting glucose."
            bias["confidence"] = "high"
        elif abs(diff) <= 10:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = f"Good agreement -- lab reads ~{abs(diff)} mg/dL {direction} than CGM nadir. Within expected CGM accuracy range (+-10-15 mg/dL for Stelo)."
            bias["confidence"] = "moderate"
        elif abs(diff) <= 20:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = f"Moderate discrepancy -- lab reads ~{abs(diff)} mg/dL {direction}. Dexcom Stelo has MARD ~9% which can produce this gap. Consider a same-day validation."
            bias["confidence"] = "low"
        else:
            bias["interpretation"] = f"Significant discrepancy ({abs(diff)} mg/dL). CGM interstitial glucose lags venous by design, but this gap warrants investigation."
            bias["confidence"] = "very_low"

    # ── Insights ─────────────────────────────────────────────────────────
    insights = []

    if distributions["daily_minimum"] and on_stats:
        dm = distributions["daily_minimum"]["mean"]
        on = on_stats["mean"]
        diff = round(dm - on, 1)
        if abs(diff) > 3:
            insights.append(
                f"Daily minimum averages {dm} vs overnight nadir {on} ({diff:+.1f} mg/dL). "
                f"{'Daily min occurs outside overnight window -- current proxy slightly underestimates true fasting.' if diff < 0 else 'Daily min typically IS the overnight nadir -- current proxy is reasonable.'}"
            )
        else:
            insights.append(f"Daily minimum ({dm}) and overnight nadir ({on}) are very close -- current fasting proxy is a good approximation.")

    if deep_stats and on_stats:
        diff = round(deep_stats["mean"] - on_stats["mean"], 1)
        if abs(diff) > 2:
            insights.append(
                f"Deep nadir (2-5 AM: {deep_stats['mean']}) differs from broad overnight (0-6 AM: {on_stats['mean']}) by {diff:+.1f} mg/dL. "
                f"Dawn phenomenon may be raising late-night readings."
            )

    if on_stats and on_stats["std_dev"] > 8:
        insights.append(f"High overnight nadir variability (SD {on_stats['std_dev']} mg/dL). Factors: meal timing, alcohol, sleep quality, stress.")
    elif on_stats and on_stats["std_dev"] < 4:
        insights.append(f"Very stable overnight nadirs (SD {on_stats['std_dev']} mg/dL) -- strong metabolic consistency.")

    if len(lab_draws) >= 3:
        recent = lab_draws[-1]["fasting_glucose_mg_dl"]
        oldest = lab_draws[0]["fasting_glucose_mg_dl"]
        if recent > oldest + 5:
            insights.append(f"Lab fasting glucose trending up: {oldest} -> {recent} mg/dL over {len(lab_draws)} draws. Monitor with CGM confirmation.")
        elif recent < oldest - 5:
            insights.append(f"Lab fasting glucose trending down: {oldest} -> {recent} mg/dL -- positive trajectory.")

    if not direct_validations:
        insights.append("No same-day CGM + lab data available. Schedule your next blood draw while wearing the Stelo for gold-standard validation.")

    return {
        "cgm_coverage": {
            "first_date": cgm_days[0],
            "last_date": cgm_days[-1],
            "total_cgm_days": len(cgm_days),
            "days_with_valid_overnight": len(nadir_results),
        },
        "distributions": distributions,
        "lab_draws": lab_draws,
        "direct_validations": direct_validations if direct_validations else "No same-day overlap between CGM and lab draws.",
        "statistical_validations": stat_validations,
        "bias_analysis": bias,
        "insights": insights,
        "methodology": {
            "overnight_window": f"{int(nadir_start):02d}:00 - {int(nadir_end):02d}:00",
            "deep_nadir_window": f"{int(deep_start):02d}:00 - {int(deep_end):02d}:00",
            "min_readings_required": min_readings,
            "cgm_device": "Dexcom Stelo (MARD ~9%)",
            "note": "Interstitial glucose (CGM) lags venous blood by 5-15 min and can differ by +-10-15 mg/dL. Lab draws are single-point; CGM captures continuous overnight minimum.",
        },
        "board_of_directors": {
            "Attia": "Fasting glucose <90 mg/dL is optimal. Overnight CGM nadir is more informative than a single lab draw -- it captures the true metabolic baseline every night.",
            "Patrick": "Dawn phenomenon (4-7 AM cortisol rise) elevates glucose. The 2-5 AM deep nadir avoids this confounder and gives the cleanest fasting signal.",
            "Huberman": "Glucose regulation is a proxy for metabolic flexibility. Low overnight variability + clean nadirs indicate good insulin sensitivity and hepatic glucose control.",
        },
    }


# R13-F09: Standard medical disclaimer for CGM health-assessment responses.
_CGM_DISCLAIMER = (
    "For personal health tracking only. Not medical advice. "
    "Consult a qualified healthcare provider before making health decisions based on this data."
)


def tool_get_cgm(args):
    """Unified CGM intelligence dispatcher."""
    VALID_VIEWS = {
        "dashboard": tool_get_cgm_dashboard,
        "fasting":   tool_get_fasting_glucose_validation,
    }
    view = (args.get("view") or "dashboard").lower().strip()
    if view not in VALID_VIEWS:
        return {"error": f"Unknown view '{view}'.", "valid_views": list(VALID_VIEWS.keys()),
                "hint": "'dashboard' for time-in-range, variability, mean glucose, clinical flags. 'fasting' for overnight nadir-based fasting glucose validation."}
    result = VALID_VIEWS[view](args)
    # R13-F09: Inject disclaimer into all CGM view responses
    if isinstance(result, dict) and "error" not in result:
        result["_disclaimer"] = _CGM_DISCLAIMER
    return result
