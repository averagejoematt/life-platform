"""
Correlation tools: caffeine, exercise, zone2, alcohol vs sleep.
"""
import json
import math
import re
import logging
from datetime import datetime, timedelta, timezone
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

def tool_get_caffeine_sleep_correlation(args):
    """
    Personal caffeine cutoff finder. Scans MacroFactor food_log for caffeine-containing
    entries, finds the last caffeine intake time per day, then correlates with same-night
    Whoop sleep metrics (SOT v2.55.0). Splits days into time buckets to show where sleep degrades.
    Based on Huberman & Attia: caffeine timing is one of the highest-leverage sleep interventions.
    """
    end_date   = args.get("end_date",   datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=89)).strftime("%Y-%m-%d"))

    mf_items = query_source("macrofactor", start_date, end_date)
    wh_raw   = query_source("whoop",       start_date, end_date)

    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}
    if not wh_raw:
        return {"error": "No Whoop data for range.", "start_date": start_date, "end_date": end_date}

    # Normalize Whoop fields and index by date
    sleep_by_date = {}
    for item in [normalize_whoop_sleep(i) for i in wh_raw]:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    def t2d(t):
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    # ── Extract per-day caffeine timing + sleep metrics ──────────────────────
    daily_rows = []

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue

        sleep = sleep_by_date.get(date)
        if not sleep:
            continue

        food_log = mf_item.get("food_log", [])
        total_caffeine = _sf(mf_item.get("total_caffeine_mg")) or 0

        # Find last caffeine intake time
        last_caffeine_time = None
        last_caffeine_food = None
        caffeine_entry_count = 0
        for entry in food_log:
            caf = _sf(entry.get("caffeine_mg"))
            if caf and caf > 0:
                td = t2d(entry.get("time"))
                if td is not None:
                    caffeine_entry_count += 1
                    if last_caffeine_time is None or td > last_caffeine_time:
                        last_caffeine_time = td
                        last_caffeine_food = entry.get("food_name", "Unknown")

        # Sleep metrics
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))

        if eff is None and score is None and deep is None:
            continue

        # Categorize
        if total_caffeine < 1:
            bucket = "no_caffeine"
        elif last_caffeine_time is None:
            bucket = "unknown_time"
        elif last_caffeine_time < 12:
            bucket = "before_noon"
        elif last_caffeine_time < 14:
            bucket = "noon_to_2pm"
        elif last_caffeine_time < 16:
            bucket = "2pm_to_4pm"
        else:
            bucket = "after_4pm"

        daily_rows.append({
            "date": date,
            "total_caffeine_mg": round(total_caffeine, 1),
            "last_caffeine_time": last_caffeine_time,
            "last_caffeine_time_hm": d2hm(last_caffeine_time),
            "last_caffeine_food": last_caffeine_food,
            "caffeine_entries": caffeine_entry_count,
            "bucket": bucket,
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
        })

    if len(daily_rows) < 5:
        return {
            "error": f"Only {len(daily_rows)} days with both caffeine and sleep data. Need at least 5.",
            "hint": "Ensure MacroFactor food logging and Whoop data overlap for the requested period.",
            "start_date": start_date, "end_date": end_date,
        }

    # ── Bucket analysis ──────────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
    ]

    BUCKET_ORDER = ["no_caffeine", "before_noon", "noon_to_2pm", "2pm_to_4pm", "after_4pm"]
    BUCKET_LABELS = {
        "no_caffeine":  "No Caffeine",
        "before_noon":  "Last Caffeine Before Noon",
        "noon_to_2pm":  "Last Caffeine 12-2 PM",
        "2pm_to_4pm":   "Last Caffeine 2-4 PM",
        "after_4pm":    "Last Caffeine After 4 PM",
        "unknown_time": "Caffeine (time unknown)",
    }

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_caffeine_mg": _avg([r["total_caffeine_mg"] for r in b_rows]),
            "metrics": {},
        }
        for field, label, _ in SLEEP_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Timing correlations (last caffeine time vs sleep) ────────────────────
    timed_rows = [r for r in daily_rows if r["last_caffeine_time"] is not None]

    timing_correlations = {}
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_caffeine_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]                for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later caffeine {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Dose correlations (total caffeine mg vs sleep) ───────────────────────
    dose_correlations = {}
    caff_rows = [r for r in daily_rows if r["total_caffeine_mg"] > 0]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["total_caffeine_mg"] for r in caff_rows if r[field] is not None]
        ys = [r[field]               for r in caff_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            dose_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # ── Personal cutoff recommendation ───────────────────────────────────────
    recommendation = None
    cutoff_time = None
    if bucket_data:
        ref_buckets = ["no_caffeine", "before_noon"]
        ref_effs = []
        for b in ref_buckets:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                ref_effs.append(bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"])
        ref_eff = max(ref_effs) if ref_effs else None

        if ref_eff is not None:
            degradation_threshold = 2.0
            for b in ["noon_to_2pm", "2pm_to_4pm", "after_4pm"]:
                if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                    b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                    if ref_eff - b_eff >= degradation_threshold:
                        cutoff_map = {"noon_to_2pm": "noon", "2pm_to_4pm": "2 PM", "after_4pm": "4 PM"}
                        cutoff_time = cutoff_map.get(b, b)
                        drop = round(ref_eff - b_eff, 1)
                        recommendation = (
                            f"Your sleep efficiency drops by {drop} percentage points when your last caffeine "
                            f"is after {cutoff_time}. Based on your data, your personal caffeine cutoff should be {cutoff_time}."
                        )
                        break

        if recommendation is None:
            eff_corr = timing_correlations.get("sleep_efficiency_pct")
            if eff_corr and eff_corr["impact"] == "HARMFUL":
                recommendation = (
                    f"No sharp cutoff detected in bucket analysis, but there is a continuous "
                    f"negative correlation (r={eff_corr['pearson_r']}) between later caffeine and sleep efficiency. "
                    f"Earlier is better for you -- aim for before 2 PM as a general guideline."
                )
                cutoff_time = "2 PM"
            else:
                recommendation = (
                    "Your data does not show a strong relationship between caffeine timing and sleep quality. "
                    "This could mean you metabolize caffeine efficiently, or there is not enough data yet. "
                    "Continue logging and re-check after 30+ days of data."
                )

    # ── Summary + alerts ─────────────────────────────────────────────────────
    all_caff_times = [r["last_caffeine_time"] for r in daily_rows if r["last_caffeine_time"] is not None]
    no_caff_days = sum(1 for r in daily_rows if r["bucket"] == "no_caffeine")

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "days_with_caffeine": len(all_caff_times),
        "days_without_caffeine": no_caff_days,
        "avg_last_caffeine_time": d2hm(sum(all_caff_times) / len(all_caff_times)) if all_caff_times else None,
        "avg_daily_caffeine_mg": _avg([r["total_caffeine_mg"] for r in daily_rows if r["total_caffeine_mg"] > 0]),
    }

    alerts = []
    if summary["avg_daily_caffeine_mg"] and summary["avg_daily_caffeine_mg"] > 400:
        alerts.append(
            f"Average daily caffeine is {summary['avg_daily_caffeine_mg']}mg -- exceeds the 400mg/day FDA safety threshold."
        )
    after_4_count = sum(1 for r in daily_rows if r["bucket"] == "after_4pm")
    if after_4_count > 0:
        pct = round(100 * after_4_count / len(daily_rows), 0)
        alerts.append(
            f"Caffeine consumed after 4 PM on {after_4_count} days ({pct:.0f}%). "
            "Caffeine has a half-life of 5-6 hours -- a 4 PM coffee means ~50% still circulating at 10 PM."
        )
    deep_corr = timing_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "HARMFUL" and abs(deep_corr["pearson_r"]) > 0.25:
        alerts.append(
            f"Later caffeine correlates with reduced deep sleep (r={deep_corr['pearson_r']}). "
            "Deep/SWS is when growth hormone releases -- critical during weight loss to preserve lean mass."
        )

    return {
        "summary": summary,
        "recommendation": {
            "cutoff_time": cutoff_time,
            "text": recommendation,
            "evidence_basis": "bucket_comparison" if cutoff_time and "drops by" in (recommendation or "") else "correlation" if cutoff_time else "insufficient_data",
        },
        "bucket_comparison": bucket_data,
        "timing_correlations": timing_correlations,
        "dose_correlations": dose_correlations,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "last_caffeine": r["last_caffeine_time_hm"],
                "last_caffeine_food": r["last_caffeine_food"],
                "caffeine_mg": r["total_caffeine_mg"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
            }
            for r in daily_rows
        ],
    }


def tool_get_exercise_sleep_correlation(args):
    """
    Personal exercise timing cutoff finder. Extracts the last exercise end time
    per day from Strava (start_date_local + elapsed_time_seconds), then correlates
    with same-night Whoop sleep metrics (SOT v2.55.0). Splits days into time-of-day
    buckets to show where late exercise degrades (or improves) sleep quality.
    Also analyzes exercise intensity (avg HR) as a separate dimension.
    Based on Huberman, Galpin, and Attia: exercise timing is a modifiable lever
    for sleep quality, but the effect is highly individual.
    """
    end_date   = args.get("end_date",   datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=179)).strftime("%Y-%m-%d"))
    min_duration_min = int(args.get("min_duration_minutes", 15))
    exclude_types = [t.strip().lower() for t in (args.get("exclude_sport_types") or "").split(",") if t.strip()]

    strava_items = query_source("strava", start_date, end_date)
    wh_raw       = query_source("whoop",  start_date, end_date)

    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}
    if not wh_raw:
        return {"error": "No Whoop data for range.", "start_date": start_date, "end_date": end_date}

    # Normalize Whoop fields and index by date
    sleep_by_date = {}
    for item in [normalize_whoop_sleep(i) for i in wh_raw]:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    # Get user profile for HR zones
    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _parse_local_time(dt_str):
        """Extract decimal hour from ISO local datetime string like '2026-02-15T12:55:30Z'."""
        if not dt_str:
            return None
        try:
            # Handle both 'T' separated and other formats
            time_part = dt_str.split("T")[1] if "T" in dt_str else None
            if not time_part:
                return None
            parts = time_part.replace("Z", "").split(":")
            return int(parts[0]) + int(parts[1]) / 60 + (int(parts[2].split(".")[0]) / 3600 if len(parts) > 2 else 0)
        except Exception:
            return None

    def _d2hm(d):
        """Decimal hours → HH:MM string."""
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _classify_intensity(avg_hr):
        """Classify exercise intensity based on % of max HR."""
        if avg_hr is None:
            return "unknown"
        pct = avg_hr / max_hr * 100
        if pct >= 80:
            return "high"
        elif pct >= 65:
            return "moderate"
        else:
            return "low"

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # ── Extract per-day exercise timing + sleep metrics ──────────────────────
    # All dates with Whoop sleep data form the universe; days without Strava = rest days
    all_dates = sorted(sleep_by_date.keys())
    strava_by_date = {}
    for item in strava_items:
        d = item.get("date")
        if d:
            strava_by_date[d] = item

    daily_rows = []

    for date in all_dates:
        if date < start_date or date > end_date:
            continue

        sleep = sleep_by_date[date]

        # Sleep metrics
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))
        hrv     = _sf(sleep.get("hrv_avg"))

        if eff is None and score is None and deep is None:
            continue

        strava_day = strava_by_date.get(date)
        activities = strava_day.get("activities", []) if strava_day else []

        # Filter activities by duration and excluded types
        valid_acts = []
        for act in activities:
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < min_duration_min * 60:
                continue
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport in exclude_types:
                continue
            valid_acts.append(act)

        # Find last exercise end time and aggregate intensity
        last_end_time = None
        last_sport = None
        last_end_hm = None
        total_exercise_min = 0
        avg_hr_weighted = None
        total_hr_time = 0
        weighted_hr_sum = 0
        activity_count = len(valid_acts)
        sport_types = []

        for act in valid_acts:
            start_local = act.get("start_date_local", "")
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            moving  = _sf(act.get("moving_time_seconds")) or elapsed
            avg_hr  = _sf(act.get("average_heartrate"))
            sport   = act.get("sport_type") or act.get("type") or "Unknown"

            start_decimal = _parse_local_time(start_local)
            if start_decimal is not None:
                end_decimal = start_decimal + elapsed / 3600
                if last_end_time is None or end_decimal > last_end_time:
                    last_end_time = end_decimal
                    last_sport = sport
                    last_end_hm = _d2hm(end_decimal)

            total_exercise_min += moving / 60
            if avg_hr is not None and moving > 0:
                weighted_hr_sum += avg_hr * moving
                total_hr_time += moving
            if sport not in sport_types:
                sport_types.append(sport)

        if total_hr_time > 0:
            avg_hr_weighted = round(weighted_hr_sum / total_hr_time, 1)

        # Bucket by last exercise end time
        if activity_count == 0:
            bucket = "rest_day"
        elif last_end_time is None:
            bucket = "unknown_time"
        elif last_end_time < 12:
            bucket = "before_noon"
        elif last_end_time < 15:
            bucket = "noon_to_3pm"
        elif last_end_time < 18:
            bucket = "3pm_to_6pm"
        elif last_end_time < 20:
            bucket = "6pm_to_8pm"
        else:
            bucket = "after_8pm"

        intensity = _classify_intensity(avg_hr_weighted)

        daily_rows.append({
            "date": date,
            "activity_count": activity_count,
            "total_exercise_min": round(total_exercise_min, 1),
            "last_end_time": last_end_time,
            "last_end_time_hm": last_end_hm,
            "last_sport": last_sport,
            "sport_types": sport_types,
            "avg_hr": avg_hr_weighted,
            "intensity": intensity,
            "bucket": bucket,
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
            "hrv_avg": hrv,
        })

    if len(daily_rows) < 10:
        return {
            "error": f"Only {len(daily_rows)} days with sleep data. Need at least 10.",
            "start_date": start_date, "end_date": end_date,
        }

    exercise_days = [r for r in daily_rows if r["bucket"] != "rest_day"]
    rest_days = [r for r in daily_rows if r["bucket"] == "rest_day"]

    # ── Bucket analysis ──────────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %", "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",       "higher_is_better"),
        ("rem_pct",              "REM %",              "higher_is_better"),
        ("sleep_score",          "Sleep Score",        "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",     "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency","lower_is_better"),
        ("hrv_avg",              "HRV",                "higher_is_better"),
    ]

    BUCKET_ORDER = ["rest_day", "before_noon", "noon_to_3pm", "3pm_to_6pm", "6pm_to_8pm", "after_8pm"]
    BUCKET_LABELS = {
        "rest_day":     "Rest Day (No Exercise)",
        "before_noon":  "Exercise Ends Before Noon",
        "noon_to_3pm":  "Exercise Ends 12–3 PM",
        "3pm_to_6pm":   "Exercise Ends 3–6 PM",
        "6pm_to_8pm":   "Exercise Ends 6–8 PM",
        "after_8pm":    "Exercise Ends After 8 PM",
        "unknown_time": "Exercise (time unknown)",
    }

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_exercise_min": _avg([r["total_exercise_min"] for r in b_rows if r["total_exercise_min"] > 0]),
            "avg_hr": _avg([r["avg_hr"] for r in b_rows]),
            "metrics": {},
        }
        for field, label, _ in SLEEP_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Timing correlations (last exercise end time vs sleep) ────────────────
    timed_rows = [r for r in exercise_days if r["last_end_time"] is not None]

    timing_correlations = {}
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_end_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]           for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later exercise {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Intensity correlations (avg HR vs sleep, exercise days only) ─────────
    intensity_correlations = {}
    hr_rows = [r for r in exercise_days if r["avg_hr"] is not None]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["avg_hr"] for r in hr_rows if r[field] is not None]
        ys = [r[field]     for r in hr_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            intensity_correlations[field] = {"label": label, "pearson_r": r_val, "n": len(xs), "impact": impact}

    # ── Intensity x Timing interaction (high intensity + late = worst combo?) ─
    intensity_timing = {}
    for intensity_level in ["low", "moderate", "high"]:
        i_rows = [r for r in exercise_days if r["intensity"] == intensity_level and r["last_end_time"] is not None]
        if len(i_rows) < 3:
            continue
        late_rows = [r for r in i_rows if r["last_end_time"] >= 18]  # after 6pm
        early_rows = [r for r in i_rows if r["last_end_time"] < 18]
        if late_rows and early_rows:
            intensity_timing[intensity_level] = {
                "early_days": len(early_rows),
                "late_days": len(late_rows),
                "early_avg_efficiency": _avg([r["sleep_efficiency_pct"] for r in early_rows]),
                "late_avg_efficiency": _avg([r["sleep_efficiency_pct"] for r in late_rows]),
                "early_avg_deep": _avg([r["deep_pct"] for r in early_rows]),
                "late_avg_deep": _avg([r["deep_pct"] for r in late_rows]),
                "early_avg_hrv": _avg([r["hrv_avg"] for r in early_rows]),
                "late_avg_hrv": _avg([r["hrv_avg"] for r in late_rows]),
            }
            ee = intensity_timing[intensity_level]["early_avg_efficiency"]
            le = intensity_timing[intensity_level]["late_avg_efficiency"]
            if ee is not None and le is not None:
                intensity_timing[intensity_level]["efficiency_delta"] = round(le - ee, 2)

    # ── Exercise vs rest day comparison ──────────────────────────────────────
    exercise_vs_rest = {}
    if rest_days and exercise_days:
        for field, label, direction in SLEEP_METRICS:
            ex_vals = [r[field] for r in exercise_days if r[field] is not None]
            rest_vals = [r[field] for r in rest_days if r[field] is not None]
            if ex_vals and rest_vals:
                ex_avg = round(sum(ex_vals) / len(ex_vals), 2)
                rest_avg = round(sum(rest_vals) / len(rest_vals), 2)
                delta = round(ex_avg - rest_avg, 2)
                if direction == "lower_is_better":
                    verdict = "BETTER" if delta < -1 else "WORSE" if delta > 1 else "SIMILAR"
                else:
                    verdict = "BETTER" if delta > 1 else "WORSE" if delta < -1 else "SIMILAR"
                exercise_vs_rest[field] = {
                    "label": label,
                    "exercise_avg": ex_avg,
                    "rest_avg": rest_avg,
                    "delta": delta,
                    "verdict": verdict,
                    "exercise_n": len(ex_vals),
                    "rest_n": len(rest_vals),
                }

    # ── Personal cutoff recommendation ───────────────────────────────────────
    recommendation = None
    cutoff_time = None

    if bucket_data:
        # Use rest days + morning exercise as reference baseline
        ref_buckets = ["rest_day", "before_noon", "noon_to_3pm"]
        ref_effs = []
        for b in ref_buckets:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                ref_effs.append(bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"])
        ref_eff = max(ref_effs) if ref_effs else None

        if ref_eff is not None:
            degradation_threshold = 3.0  # Higher threshold than caffeine -- exercise has noise
            for b in ["3pm_to_6pm", "6pm_to_8pm", "after_8pm"]:
                if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                    b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                    if ref_eff - b_eff >= degradation_threshold:
                        cutoff_map = {"3pm_to_6pm": "3 PM", "6pm_to_8pm": "6 PM", "after_8pm": "8 PM"}
                        cutoff_time = cutoff_map.get(b, b)
                        drop = round(ref_eff - b_eff, 1)
                        recommendation = (
                            f"Your sleep efficiency drops by {drop} percentage points when exercise "
                            f"ends after {cutoff_time}. Based on your data, aim to finish workouts by {cutoff_time}."
                        )
                        # Check if it's intensity-dependent
                        if "high" in intensity_timing:
                            hi = intensity_timing["high"]
                            if hi.get("efficiency_delta") is not None and hi["efficiency_delta"] < -3:
                                recommendation += (
                                    f" This effect is amplified for high-intensity exercise "
                                    f"(efficiency delta: {hi['efficiency_delta']} pts late vs early)."
                                )
                        break

        if recommendation is None:
            eff_corr = timing_correlations.get("sleep_efficiency_pct")
            if eff_corr and eff_corr["impact"] == "HARMFUL":
                recommendation = (
                    f"No sharp cutoff detected in bucket analysis, but there is a continuous "
                    f"negative correlation (r={eff_corr['pearson_r']}) between later exercise and sleep efficiency. "
                    f"Earlier is generally better for you."
                )
                cutoff_time = "6 PM (suggested)"
            elif eff_corr and eff_corr["impact"] == "BENEFICIAL":
                recommendation = (
                    f"Your data suggests later exercise actually correlates with BETTER sleep (r={eff_corr['pearson_r']}). "
                    f"This is not uncommon -- some people sleep better after evening exercise due to temperature "
                    f"drop rebound. No cutoff needed; exercise when it fits your schedule."
                )
            else:
                recommendation = (
                    "Your data does not show a strong relationship between exercise timing and sleep quality. "
                    "This is actually good news -- it means you can exercise when convenient without worrying "
                    "about sleep impact. Continue tracking to confirm with more data."
                )

    # ── Summary + alerts ─────────────────────────────────────────────────────
    all_end_times = [r["last_end_time"] for r in exercise_days if r["last_end_time"] is not None]

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "exercise_days": len(exercise_days),
        "rest_days": len(rest_days),
        "avg_last_exercise_end": _d2hm(sum(all_end_times) / len(all_end_times)) if all_end_times else None,
        "avg_exercise_min_on_active_days": _avg([r["total_exercise_min"] for r in exercise_days if r["total_exercise_min"] > 0]),
        "avg_hr_on_active_days": _avg([r["avg_hr"] for r in exercise_days]),
        "intensity_distribution": {
            level: sum(1 for r in exercise_days if r["intensity"] == level)
            for level in ["low", "moderate", "high", "unknown"]
        },
    }

    alerts = []
    # Late high-intensity warning
    late_intense = [r for r in exercise_days if r["last_end_time"] and r["last_end_time"] >= 20 and r["intensity"] == "high"]
    if late_intense:
        pct = round(100 * len(late_intense) / len(exercise_days), 0)
        alerts.append(
            f"High-intensity exercise ending after 8 PM on {len(late_intense)} days ({pct:.0f}%). "
            "Intense late workouts elevate core temperature and cortisol, both of which delay sleep onset. "
            "Consider shifting these to earlier or replacing with low-intensity evening sessions."
        )
    # Exercise vs rest insight
    evr_eff = exercise_vs_rest.get("sleep_efficiency_pct")
    if evr_eff and evr_eff["verdict"] == "BETTER":
        alerts.append(
            f"You sleep better on exercise days: {evr_eff['exercise_avg']}% vs {evr_eff['rest_avg']}% "
            f"efficiency (+{evr_eff['delta']} pts). Exercise is a net positive for your sleep."
        )
    elif evr_eff and evr_eff["verdict"] == "WORSE":
        alerts.append(
            f"You sleep worse on exercise days: {evr_eff['exercise_avg']}% vs {evr_eff['rest_avg']}% "
            f"efficiency ({evr_eff['delta']} pts). This is unusual -- check timing and intensity patterns."
        )
    # Deep sleep impact
    deep_corr = timing_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "HARMFUL" and abs(deep_corr["pearson_r"]) > 0.25:
        alerts.append(
            f"Later exercise correlates with reduced deep sleep (r={deep_corr['pearson_r']}). "
            "Deep/SWS drives growth hormone release -- critical during body recomposition."
        )

    return {
        "summary": summary,
        "recommendation": {
            "cutoff_time": cutoff_time,
            "text": recommendation,
            "evidence_basis": ("bucket_comparison" if cutoff_time and "drops by" in (recommendation or "")
                              else "correlation" if cutoff_time
                              else "beneficial" if "BETTER" in (recommendation or "")
                              else "insufficient_data"),
        },
        "bucket_comparison": bucket_data,
        "exercise_vs_rest": exercise_vs_rest,
        "timing_correlations": timing_correlations,
        "intensity_correlations": intensity_correlations,
        "intensity_x_timing": intensity_timing,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "last_exercise_end": r["last_end_time_hm"],
                "last_sport": r["last_sport"],
                "exercise_min": r["total_exercise_min"],
                "avg_hr": r["avg_hr"],
                "intensity": r["intensity"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
                "hrv": r["hrv_avg"],
            }
            for r in daily_rows
        ],
    }


def tool_get_zone2_breakdown(args):
    """
    Zone 2 training tracker. Classifies each Strava activity into HR zones based on
    average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2
    minutes, compares to the 150 min/week target (Attia, Huberman, WHO guidelines for
    moderate-intensity aerobic activity), and shows full 5-zone distribution.

    Zone 2 is the highest-evidence longevity training modality — it builds mitochondrial
    density, fat oxidation capacity, and cardiovascular base. Most people drastically
    undertrain Zone 2 relative to higher intensities.
    """
    end_date   = args.get("end_date",   datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=89)).strftime("%Y-%m-%d"))
    weekly_target_min = int(args.get("weekly_target_minutes", 150))
    min_duration_min  = int(args.get("min_duration_minutes", 10))

    # HR zone thresholds from profile
    profile = get_profile()
    max_hr  = float(profile.get("max_heart_rate", 190))
    rhr     = float(profile.get("resting_heart_rate_baseline", 60))

    # 5 zones by % of max HR (standard model)
    # Zone 1: 50-60%  (warm-up / recovery)
    # Zone 2: 60-70%  (aerobic base / fat burn — the longevity zone)
    # Zone 3: 70-80%  (tempo / aerobic capacity)
    # Zone 4: 80-90%  (threshold / lactate)
    # Zone 5: 90-100% (VO2 max / anaerobic)
    ZONE_BOUNDS = [
        ("zone_1", "Zone 1 (Recovery)",   0.50, 0.60),
        ("zone_2", "Zone 2 (Aerobic)",    0.60, 0.70),
        ("zone_3", "Zone 3 (Tempo)",      0.70, 0.80),
        ("zone_4", "Zone 4 (Threshold)",  0.80, 0.90),
        ("zone_5", "Zone 5 (VO2 Max)",    0.90, 1.00),
    ]

    zone_hr_ranges = {}
    for key, label, lo_pct, hi_pct in ZONE_BOUNDS:
        zone_hr_ranges[key] = {
            "label": label,
            "hr_low": round(max_hr * lo_pct, 0),
            "hr_high": round(max_hr * hi_pct, 0),
        }

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def classify_zone(avg_hr):
        """Classify activity into HR zone by avg HR."""
        if avg_hr is None:
            return "no_hr"
        pct = avg_hr / max_hr
        if pct < 0.50:
            return "below_zone_1"
        elif pct < 0.60:
            return "zone_1"
        elif pct < 0.70:
            return "zone_2"
        elif pct < 0.80:
            return "zone_3"
        elif pct < 0.90:
            return "zone_4"
        else:
            return "zone_5"

    # ── Query Strava activities ──────────────────────────────────────────────
    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}

    # Flatten all activities
    all_activities = []
    for day in sorted(strava_items, key=lambda x: x.get("date", "")):
        date = day.get("date", "")
        for act in day.get("activities", []):
            moving = _sf(act.get("moving_time_seconds")) or 0
            if moving < min_duration_min * 60:
                continue
            avg_hr = _sf(act.get("average_heartrate"))
            zone = classify_zone(avg_hr)
            sport = act.get("sport_type") or act.get("type") or "Unknown"
            all_activities.append({
                "date": date,
                "name": act.get("enriched_name") or act.get("name") or "Unnamed",
                "sport_type": sport,
                "moving_time_min": round(moving / 60, 1),
                "avg_hr": avg_hr,
                "max_hr": _sf(act.get("max_heartrate")),
                "zone": zone,
                "distance_miles": _sf(act.get("distance_miles")),
            })

    if not all_activities:
        return {"error": "No qualifying activities found.", "start_date": start_date, "end_date": end_date}

    # ── Weekly aggregation ───────────────────────────────────────────────────
    from collections import defaultdict

    def iso_week(date_str):
        """Return ISO year-week string like '2025-W48'."""
        from datetime import datetime as dt, timezone
        d = dt.strptime(date_str, "%Y-%m-%d")
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def week_start(date_str):
        """Return Monday of the week for a given date."""
        from datetime import datetime as dt, timezone
        d = dt.strptime(date_str, "%Y-%m-%d")
        monday = d - timedelta(days=d.weekday())
        return monday.strftime("%Y-%m-%d")

    weekly = defaultdict(lambda: {
        "zone_1_min": 0, "zone_2_min": 0, "zone_3_min": 0,
        "zone_4_min": 0, "zone_5_min": 0, "below_zone_1_min": 0,
        "no_hr_min": 0, "total_exercise_min": 0, "activity_count": 0,
        "zone_2_activities": [],
    })

    for act in all_activities:
        wk = week_start(act["date"])
        z = act["zone"]
        mins = act["moving_time_min"]
        weekly[wk]["total_exercise_min"] += mins
        weekly[wk]["activity_count"] += 1
        if z in ("zone_1", "zone_2", "zone_3", "zone_4", "zone_5"):
            weekly[wk][f"{z}_min"] += mins
        elif z == "below_zone_1":
            weekly[wk]["below_zone_1_min"] += mins
        else:
            weekly[wk]["no_hr_min"] += mins
        if z == "zone_2":
            weekly[wk]["zone_2_activities"].append({
                "date": act["date"],
                "name": act["name"],
                "sport": act["sport_type"],
                "minutes": mins,
                "avg_hr": act["avg_hr"],
            })

    weekly_sorted = []
    for wk in sorted(weekly.keys()):
        w = weekly[wk]
        z2 = w["zone_2_min"]
        pct_target = round(100 * z2 / weekly_target_min, 0) if weekly_target_min > 0 else None
        weekly_sorted.append({
            "week_start": wk,
            "zone_2_minutes": round(z2, 1),
            "target_pct": pct_target,
            "target_met": z2 >= weekly_target_min,
            "zone_1_min": round(w["zone_1_min"], 1),
            "zone_3_min": round(w["zone_3_min"], 1),
            "zone_4_min": round(w["zone_4_min"], 1),
            "zone_5_min": round(w["zone_5_min"], 1),
            "total_exercise_min": round(w["total_exercise_min"], 1),
            "activity_count": w["activity_count"],
            "zone_2_activities": w["zone_2_activities"],
        })

    # ── Zone distribution (full period) ──────────────────────────────────────
    zone_totals = {"zone_1": 0, "zone_2": 0, "zone_3": 0, "zone_4": 0, "zone_5": 0, "below_zone_1": 0, "no_hr": 0}
    zone_counts = {"zone_1": 0, "zone_2": 0, "zone_3": 0, "zone_4": 0, "zone_5": 0, "below_zone_1": 0, "no_hr": 0}
    for act in all_activities:
        z = act["zone"]
        zone_totals[z] = zone_totals.get(z, 0) + act["moving_time_min"]
        zone_counts[z] = zone_counts.get(z, 0) + 1

    total_min = sum(zone_totals.values())
    zone_distribution = {}
    for key, label, _, _ in ZONE_BOUNDS:
        mins = round(zone_totals.get(key, 0), 1)
        zone_distribution[key] = {
            "label": label,
            "total_minutes": mins,
            "activity_count": zone_counts.get(key, 0),
            "pct_of_training": round(100 * mins / total_min, 1) if total_min > 0 else 0,
            "hr_range": f"{zone_hr_ranges[key]['hr_low']:.0f}-{zone_hr_ranges[key]['hr_high']:.0f} bpm",
        }

    # ── Sport type breakdown for Zone 2 ──────────────────────────────────────
    z2_by_sport = defaultdict(lambda: {"minutes": 0, "count": 0})
    for act in all_activities:
        if act["zone"] == "zone_2":
            z2_by_sport[act["sport_type"]]["minutes"] += act["moving_time_min"]
            z2_by_sport[act["sport_type"]]["count"] += 1

    sport_breakdown = []
    for sport, data in sorted(z2_by_sport.items(), key=lambda x: -x[1]["minutes"]):
        sport_breakdown.append({
            "sport_type": sport,
            "zone_2_minutes": round(data["minutes"], 1),
            "activity_count": data["count"],
        })

    # ── Trend analysis ───────────────────────────────────────────────────────
    z2_weekly_vals = [w["zone_2_minutes"] for w in weekly_sorted]
    trend = None
    if len(z2_weekly_vals) >= 3:
        xs = list(range(len(z2_weekly_vals)))
        slope_r = pearson_r(xs, z2_weekly_vals) if len(xs) >= 3 else None
        avg_first_half = sum(z2_weekly_vals[:len(z2_weekly_vals)//2]) / max(len(z2_weekly_vals)//2, 1)
        avg_second_half = sum(z2_weekly_vals[len(z2_weekly_vals)//2:]) / max(len(z2_weekly_vals) - len(z2_weekly_vals)//2, 1)
        trend = {
            "direction": "INCREASING" if avg_second_half > avg_first_half + 5 else "DECREASING" if avg_second_half < avg_first_half - 5 else "STABLE",
            "first_half_avg_min": round(avg_first_half, 1),
            "second_half_avg_min": round(avg_second_half, 1),
            "correlation_r": slope_r,
        }

    # ── Summary ──────────────────────────────────────────────────────────────
    n_weeks = len(weekly_sorted)
    avg_z2_weekly = round(sum(z2_weekly_vals) / n_weeks, 1) if n_weeks > 0 else 0
    weeks_meeting_target = sum(1 for w in weekly_sorted if w["target_met"])

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "weeks_analyzed": n_weeks,
        "total_activities": len(all_activities),
        "zone_2_activities": zone_counts.get("zone_2", 0),
        "avg_weekly_zone_2_min": avg_z2_weekly,
        "weekly_target_min": weekly_target_min,
        "weeks_meeting_target": weeks_meeting_target,
        "target_hit_rate_pct": round(100 * weeks_meeting_target / n_weeks, 0) if n_weeks > 0 else 0,
        "total_zone_2_min": round(zone_totals.get("zone_2", 0), 1),
        "max_hr_used": max_hr,
        "zone_2_hr_range": f"{zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm",
    }

    # ── Alerts + recommendations ─────────────────────────────────────────────
    alerts = []

    if avg_z2_weekly < weekly_target_min * 0.5:
        deficit = round(weekly_target_min - avg_z2_weekly, 0)
        alerts.append(
            f"Zone 2 deficit: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({deficit:.0f} min shortfall). Zone 2 is the foundation of cardiovascular longevity -- "
            "consider adding 2-3 sessions of easy cardio (walking, cycling, easy jogging) per week "
            f"where HR stays in {zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm."
        )
    elif avg_z2_weekly < weekly_target_min:
        deficit = round(weekly_target_min - avg_z2_weekly, 0)
        alerts.append(
            f"Close to target: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({deficit:.0f} min shortfall). One additional Zone 2 session per week would close the gap."
        )

    # Polarization check: too much Zone 3 relative to Zone 2
    z3_total = zone_totals.get("zone_3", 0)
    z2_total = zone_totals.get("zone_2", 0)
    if z3_total > z2_total and z3_total > 30:
        alerts.append(
            f"Training polarization issue: more time in Zone 3 ({round(z3_total, 0)} min) than Zone 2 "
            f"({round(z2_total, 0)} min). Per Seiler's polarized training model, ~80% of endurance "
            "volume should be easy (Zone 1-2) with ~20% hard (Zone 4-5). Zone 3 is 'no man's land' -- "
            "too hard to build aerobic base, too easy for VO2 max gains."
        )

    # Zone 5 volume check
    z5_total = zone_totals.get("zone_5", 0)
    if z5_total > z2_total and z5_total > 20:
        alerts.append(
            f"High-intensity dominant: more Zone 5 ({round(z5_total, 0)} min) than Zone 2 ({round(z2_total, 0)} min). "
            "This pattern correlates with overtraining risk. Prioritize Zone 2 base building."
        )

    # No HR data warning
    no_hr_count = zone_counts.get("no_hr", 0)
    if no_hr_count > len(all_activities) * 0.3:
        alerts.append(
            f"{no_hr_count} of {len(all_activities)} activities ({round(100*no_hr_count/len(all_activities))}%) "
            "lack HR data. Zone classification requires heart rate -- ensure your HR monitor is connected during workouts."
        )

    return {
        "summary": summary,
        "zone_distribution": zone_distribution,
        "zone_hr_thresholds": zone_hr_ranges,
        "weekly_breakdown": weekly_sorted,
        "sport_type_zone2": sport_breakdown,
        "trend": trend,
        "alerts": alerts,
        "methodology": (
            f"Activities classified by average HR as percentage of max HR ({max_hr:.0f} bpm from profile). "
            f"Zone 2 = 60-70% max = {zone_hr_ranges['zone_2']['hr_low']:.0f}-{zone_hr_ranges['zone_2']['hr_high']:.0f} bpm. "
            "Full activity moving time is attributed to the classified zone. This is an approximation -- "
            "average HR doesn't capture intra-activity zone transitions. Activities without HR data are excluded "
            "from zone classification."
        ),
    }


def tool_get_alcohol_sleep_correlation(args):
    """
    Personal alcohol impact analyzer. Correlates MacroFactor alcohol intake with
    same-night Whoop sleep data (SOT v2.55.0) AND next-day Whoop recovery. Splits days into
    dose buckets (none / light / moderate / heavy), runs Pearson correlations for
    both dose and timing effects, and generates a personal impact assessment.

    One standard drink = ~14g pure alcohol (12oz beer, 5oz wine, 1.5oz spirits).
    Based on Huberman, Attia, and Walker: even moderate alcohol suppresses REM and
    deep sleep, raises resting HR, and impairs next-day HRV recovery.
    """
    end_date   = args.get("end_date",   datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=89)).strftime("%Y-%m-%d"))

    mf_items = query_source("macrofactor", start_date, end_date)
    wh_raw   = query_source("whoop",       start_date, end_date)

    if not mf_items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}
    if not wh_raw:
        return {"error": "No Whoop data for range.", "start_date": start_date, "end_date": end_date}

    # Normalize Whoop fields and index by date (sleep + recovery from same source)
    sleep_by_date = {}
    for item in [normalize_whoop_sleep(i) for i in wh_raw]:
        d = item.get("date")
        if d:
            sleep_by_date[d] = item

    # Recovery data lives in the same Whoop items (recovery_score, hrv, resting_heart_rate)
    whoop_by_date = sleep_by_date  # same source, already normalised

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _t2d(t):
        """Time string HH:MM to decimal hours."""
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def _d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _next_date(date_str):
        """Return the next day as YYYY-MM-DD."""
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    # ── One standard drink = 14g pure alcohol ────────────────────────────────
    GRAMS_PER_DRINK = 14.0

    def _classify_dose(alcohol_g):
        if alcohol_g < 1:
            return "none"
        drinks = alcohol_g / GRAMS_PER_DRINK
        if drinks <= 1.0:
            return "light"       # ≤1 drink
        elif drinks <= 2.5:
            return "moderate"    # 1-2.5 drinks
        else:
            return "heavy"       # 3+ drinks

    # ── Extract per-day alcohol + sleep + next-day recovery ──────────────────
    daily_rows = []

    for mf_item in sorted(mf_items, key=lambda x: x.get("date", "")):
        date = mf_item.get("date")
        if not date:
            continue

        # Same-night sleep
        sleep = sleep_by_date.get(date)
        if not sleep:
            continue

        # Alcohol from day totals
        total_alcohol_g = _sf(mf_item.get("total_alcohol_g")) or 0

        # Alcohol timing from food_log
        food_log = mf_item.get("food_log", [])
        last_drink_time = None
        last_drink_food = None
        drink_entries = 0
        for entry in food_log:
            alc = _sf(entry.get("alcohol_g"))
            if alc and alc > 0:
                td = _t2d(entry.get("time"))
                if td is not None:
                    drink_entries += 1
                    if last_drink_time is None or td > last_drink_time:
                        last_drink_time = td
                        last_drink_food = entry.get("food_name", "Unknown")

        # Sleep metrics (same night)
        eff     = _sf(sleep.get("sleep_efficiency_pct"))
        deep    = _sf(sleep.get("deep_pct"))
        rem     = _sf(sleep.get("rem_pct"))
        score   = _sf(sleep.get("sleep_score"))
        dur     = _sf(sleep.get("sleep_duration_hours"))
        latency = _sf(sleep.get("time_to_sleep_min"))
        es_hrv  = _sf(sleep.get("hrv_avg"))

        if eff is None and score is None and deep is None:
            continue

        # Next-day Whoop recovery
        next_day = _next_date(date)
        whoop_next = whoop_by_date.get(next_day)
        next_recovery  = _sf(whoop_next.get("recovery_score")) if whoop_next else None
        next_hrv       = _sf(whoop_next.get("hrv")) if whoop_next else None
        next_rhr       = _sf(whoop_next.get("resting_heart_rate")) if whoop_next else None

        drinks = round(total_alcohol_g / GRAMS_PER_DRINK, 1) if total_alcohol_g > 0 else 0
        bucket = _classify_dose(total_alcohol_g)

        daily_rows.append({
            "date": date,
            "total_alcohol_g": round(total_alcohol_g, 1),
            "standard_drinks": drinks,
            "last_drink_time": last_drink_time,
            "last_drink_time_hm": _d2hm(last_drink_time),
            "last_drink_food": last_drink_food,
            "drink_entries": drink_entries,
            "bucket": bucket,
            # Same-night sleep
            "sleep_efficiency_pct": eff,
            "deep_pct": deep,
            "rem_pct": rem,
            "sleep_score": score,
            "sleep_duration_hrs": dur,
            "time_to_sleep_min": latency,
            "es_hrv": es_hrv,
            # Next-day recovery
            "next_recovery_score": next_recovery,
            "next_hrv": next_hrv,
            "next_rhr": next_rhr,
        })

    if len(daily_rows) < 5:
        return {
            "error": f"Only {len(daily_rows)} days with both nutrition and sleep data. Need at least 5.",
            "hint": "Ensure MacroFactor food logging and Whoop data overlap. Re-check after 2+ weeks of consistent logging.",
            "start_date": start_date, "end_date": end_date,
        }

    # ── Metric definitions ───────────────────────────────────────────────────
    SLEEP_METRICS = [
        ("sleep_efficiency_pct", "Sleep Efficiency %",  "higher_is_better"),
        ("deep_pct",             "Deep Sleep %",        "higher_is_better"),
        ("rem_pct",              "REM %",               "higher_is_better"),
        ("sleep_score",          "Sleep Score",         "higher_is_better"),
        ("sleep_duration_hrs",   "Sleep Duration",      "higher_is_better"),
        ("time_to_sleep_min",    "Sleep Onset Latency", "lower_is_better"),
        ("es_hrv",               "Sleep HRV",           "higher_is_better"),
    ]

    RECOVERY_METRICS = [
        ("next_recovery_score",  "Next-Day Recovery",   "higher_is_better"),
        ("next_hrv",             "Next-Day HRV",        "higher_is_better"),
        ("next_rhr",             "Next-Day RHR",        "lower_is_better"),
    ]

    ALL_METRICS = SLEEP_METRICS + RECOVERY_METRICS

    # ── Bucket analysis ──────────────────────────────────────────────────────
    BUCKET_ORDER = ["none", "light", "moderate", "heavy"]
    BUCKET_LABELS = {
        "none":     "No Alcohol",
        "light":    "Light (≤1 drink / ≤14g)",
        "moderate": "Moderate (1-2.5 drinks / 14-35g)",
        "heavy":    "Heavy (3+ drinks / 35g+)",
    }

    bucket_data = {}
    for b in BUCKET_ORDER:
        b_rows = [r for r in daily_rows if r["bucket"] == b]
        if not b_rows:
            continue
        bucket_data[b] = {
            "label": BUCKET_LABELS[b],
            "days": len(b_rows),
            "avg_alcohol_g": _avg([r["total_alcohol_g"] for r in b_rows if r["total_alcohol_g"] > 0]),
            "avg_drinks": _avg([r["standard_drinks"] for r in b_rows if r["standard_drinks"] > 0]),
            "metrics": {},
        }
        for field, label, _ in ALL_METRICS:
            vals = [r[field] for r in b_rows if r[field] is not None]
            if vals:
                bucket_data[b]["metrics"][field] = {
                    "label": label,
                    "avg": round(sum(vals) / len(vals), 2),
                    "n": len(vals),
                }

    # ── Dose correlations (total alcohol g vs metrics) ───────────────────────
    dose_correlations = {}
    for field, label, direction in ALL_METRICS:
        xs = [r["total_alcohol_g"] for r in daily_rows if r[field] is not None]
        ys = [r[field]             for r in daily_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            dose_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
            }

    # ── Timing correlations (last drink time vs sleep, drinking days only) ───
    timing_correlations = {}
    timed_rows = [r for r in daily_rows if r["last_drink_time"] is not None]
    for field, label, direction in SLEEP_METRICS:
        xs = [r["last_drink_time"] for r in timed_rows if r[field] is not None]
        ys = [r[field]             for r in timed_rows if r[field] is not None]
        r_val = pearson_r(xs, ys) if len(xs) >= 5 else None
        if r_val is not None:
            if direction == "higher_is_better":
                impact = "HARMFUL" if r_val < -0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            else:
                impact = "HARMFUL" if r_val > 0.15 else "NEUTRAL" if abs(r_val) < 0.15 else "BENEFICIAL"
            timing_correlations[field] = {
                "label": label, "pearson_r": r_val, "n": len(xs), "impact": impact,
                "interpretation": (
                    f"Later drinking {'strongly ' if abs(r_val) > 0.4 else ''}correlates with "
                    f"{'worse' if impact == 'HARMFUL' else 'better' if impact == 'BENEFICIAL' else 'no significant change in'} "
                    f"{label.lower()}"
                ),
            }

    # ── Drinking vs sober comparison ─────────────────────────────────────────
    drinking_days = [r for r in daily_rows if r["bucket"] != "none"]
    sober_days    = [r for r in daily_rows if r["bucket"] == "none"]

    drinking_vs_sober = {}
    if drinking_days and sober_days:
        for field, label, direction in ALL_METRICS:
            dr_vals = [r[field] for r in drinking_days if r[field] is not None]
            so_vals = [r[field] for r in sober_days if r[field] is not None]
            if dr_vals and so_vals:
                dr_avg = round(sum(dr_vals) / len(dr_vals), 2)
                so_avg = round(sum(so_vals) / len(so_vals), 2)
                delta = round(dr_avg - so_avg, 2)
                if direction == "lower_is_better":
                    verdict = "BETTER" if delta < -1 else "WORSE" if delta > 1 else "SIMILAR"
                else:
                    verdict = "BETTER" if delta > 1 else "WORSE" if delta < -1 else "SIMILAR"
                drinking_vs_sober[field] = {
                    "label": label,
                    "drinking_avg": dr_avg,
                    "sober_avg": so_avg,
                    "delta": delta,
                    "verdict": verdict,
                    "drinking_n": len(dr_vals),
                    "sober_n": len(so_vals),
                }

    # ── Personal impact assessment ───────────────────────────────────────────
    assessment = None
    severity = None

    # Compare sober vs drinking bucket metrics
    if "none" in bucket_data and len(bucket_data) > 1:
        sober_eff = None
        if "sleep_efficiency_pct" in bucket_data["none"]["metrics"]:
            sober_eff = bucket_data["none"]["metrics"]["sleep_efficiency_pct"]["avg"]

        worst_bucket = None
        worst_drop = 0
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "sleep_efficiency_pct" in bucket_data[b]["metrics"]:
                b_eff = bucket_data[b]["metrics"]["sleep_efficiency_pct"]["avg"]
                if sober_eff is not None:
                    drop = sober_eff - b_eff
                    if drop > worst_drop:
                        worst_drop = drop
                        worst_bucket = b

        # Check REM impact (alcohol's most documented effect)
        sober_rem = None
        if "rem_pct" in bucket_data["none"]["metrics"]:
            sober_rem = bucket_data["none"]["metrics"]["rem_pct"]["avg"]

        rem_drops = {}
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "rem_pct" in bucket_data[b]["metrics"] and sober_rem:
                rem_drops[b] = round(sober_rem - bucket_data[b]["metrics"]["rem_pct"]["avg"], 1)

        # Check next-day recovery impact
        sober_rec = None
        rec_drops = {}
        if "next_recovery_score" in bucket_data["none"]["metrics"]:
            sober_rec = bucket_data["none"]["metrics"]["next_recovery_score"]["avg"]
        for b in ["light", "moderate", "heavy"]:
            if b in bucket_data and "next_recovery_score" in bucket_data[b]["metrics"] and sober_rec:
                rec_drops[b] = round(sober_rec - bucket_data[b]["metrics"]["next_recovery_score"]["avg"], 1)

        # Build assessment
        impacts = []
        if worst_drop >= 5:
            impacts.append(f"sleep efficiency drops {worst_drop:.1f} pts with {worst_bucket} drinking")
            severity = "HIGH"
        elif worst_drop >= 2:
            impacts.append(f"sleep efficiency drops {worst_drop:.1f} pts with {worst_bucket} drinking")
            severity = "MODERATE"

        for b, drop in rem_drops.items():
            if drop >= 3:
                impacts.append(f"REM drops {drop} pts with {b} drinking")
                if severity != "HIGH":
                    severity = "HIGH" if drop >= 5 else "MODERATE"

        for b, drop in rec_drops.items():
            if drop >= 5:
                impacts.append(f"next-day recovery drops {drop} pts with {b} drinking")
                severity = "HIGH"

        if impacts:
            assessment = "Alcohol is measurably affecting your recovery: " + "; ".join(impacts) + "."
        else:
            assessment = (
                "Your data does not yet show a strong alcohol impact on sleep or recovery. "
                "This could mean you metabolize alcohol well, drink infrequently, or there isn't enough data yet. "
                "Continue logging and re-check after 30+ days."
            )
            severity = "LOW"
    else:
        assessment = (
            "Not enough data to compare drinking vs sober nights. "
            "Continue logging food intake in MacroFactor for at least 2-3 weeks."
        )
        severity = "INSUFFICIENT_DATA"

    # ── Summary + alerts ─────────────────────────────────────────────────────
    drinking_count = len(drinking_days)
    sober_count = len(sober_days)
    all_drink_amounts = [r["total_alcohol_g"] for r in drinking_days if r["total_alcohol_g"] > 0]

    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "days_analyzed": len(daily_rows),
        "drinking_days": drinking_count,
        "sober_days": sober_count,
        "drinking_frequency_pct": round(100 * drinking_count / len(daily_rows), 0) if daily_rows else 0,
        "avg_alcohol_g_on_drinking_days": _avg(all_drink_amounts),
        "avg_drinks_on_drinking_days": _avg([g / GRAMS_PER_DRINK for g in all_drink_amounts]) if all_drink_amounts else None,
        "avg_last_drink_time": _d2hm(
            sum(r["last_drink_time"] for r in timed_rows) / len(timed_rows)
        ) if timed_rows else None,
    }

    alerts = []

    # High frequency alert
    if summary["drinking_frequency_pct"] and summary["drinking_frequency_pct"] > 50:
        alerts.append(
            f"Alcohol consumed on {summary['drinking_frequency_pct']:.0f}% of days. "
            "Huberman and Attia recommend at minimum 3-4 alcohol-free days per week "
            "for liver recovery and hormonal regulation."
        )

    # REM suppression alert
    rem_corr = dose_correlations.get("rem_pct")
    if rem_corr and rem_corr["impact"] == "HARMFUL" and abs(rem_corr["pearson_r"]) > 0.2:
        alerts.append(
            f"Alcohol dose correlates with REM suppression (r={rem_corr['pearson_r']}). "
            "REM sleep is critical for emotional regulation, memory consolidation, and creativity. "
            "Even 1-2 drinks can reduce REM by 20-30% (Walker, 'Why We Sleep')."
        )

    # Deep sleep pseudo-enhancement warning
    deep_corr = dose_correlations.get("deep_pct")
    if deep_corr and deep_corr["impact"] == "BENEFICIAL":
        alerts.append(
            "Alcohol appears to increase deep sleep % -- but this is misleading. "
            "Alcohol-induced 'deep sleep' is actually sedation, not restorative SWS. "
            "It lacks the memory-consolidating neural oscillations of natural deep sleep."
        )

    # Next-day HRV impact
    hrv_corr = dose_correlations.get("next_hrv")
    if hrv_corr and hrv_corr["impact"] == "HARMFUL" and abs(hrv_corr["pearson_r"]) > 0.2:
        alerts.append(
            f"Higher alcohol intake correlates with lower next-day HRV (r={hrv_corr['pearson_r']}). "
            "Alcohol impairs parasympathetic recovery -- your autonomic nervous system is still stressed "
            "the morning after, even if you feel fine."
        )

    # Late drinking alert
    late_drinks = [r for r in timed_rows if r["last_drink_time"] and r["last_drink_time"] >= 21]
    if late_drinks:
        pct = round(100 * len(late_drinks) / len(timed_rows), 0) if timed_rows else 0
        alerts.append(
            f"Last drink after 9 PM on {len(late_drinks)} drinking days ({pct:.0f}%). "
            "Alcohol takes ~1 hour per standard drink to metabolize. Late drinking means "
            "active alcohol metabolism during early sleep cycles when deep sleep should peak."
        )

    return {
        "summary": summary,
        "assessment": {
            "text": assessment,
            "severity": severity,
        },
        "bucket_comparison": bucket_data,
        "drinking_vs_sober": drinking_vs_sober,
        "dose_correlations": dose_correlations,
        "timing_correlations": timing_correlations,
        "alerts": alerts,
        "daily_detail": [
            {
                "date": r["date"],
                "alcohol_g": r["total_alcohol_g"],
                "drinks": r["standard_drinks"],
                "last_drink": r["last_drink_time_hm"],
                "last_drink_food": r["last_drink_food"],
                "sleep_eff": r["sleep_efficiency_pct"],
                "deep_pct": r["deep_pct"],
                "rem_pct": r["rem_pct"],
                "sleep_score": r["sleep_score"],
                "next_recovery": r["next_recovery_score"],
                "next_hrv": r["next_hrv"],
            }
            for r in daily_rows
        ],
    }
