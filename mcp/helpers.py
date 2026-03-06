"""
Shared computation helpers: aggregation, training load, statistics, classification.
"""
import math
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from mcp.config import FIELD_ALIASES, P40_GROUPS, logger
from mcp.core import get_profile, query_source, decimal_to_float, get_sot

# ── Aggregation ──

# ── Aggregation helpers ───────────────────────────────────────────────────────
def aggregate_items(items, period):
    buckets = defaultdict(lambda: defaultdict(list))
    skip_fields = {"pk", "sk", "source", "ingested_at", "date", "activities", "sport_types"}

    for item in items:
        date = item.get("date", "")
        if not date or len(date) < 7:
            continue
        if "#WORKOUT#" in item.get("sk", ""):
            continue
        key = date[:7] if period == "month" else date[:4]
        for field, value in item.items():
            if field in skip_fields:
                continue
            if isinstance(value, (int, float)):
                buckets[key][field].append(value)

    result = []
    for period_key in sorted(buckets.keys()):
        row = {"period": period_key}
        field_data = buckets[period_key]
        if field_data:
            row["days_with_data"] = len(next(iter(field_data.values())))
        for field, values in field_data.items():
            row[f"{field}_avg"] = round(sum(values) / len(values), 2)
            row[f"{field}_min"] = round(min(values), 2)
            row[f"{field}_max"] = round(max(values), 2)
        result.append(row)
    return result


def flatten_strava_activity(day_record):
    """Flatten a Strava day record + nested activities into one dict per activity."""
    activities = day_record.get("activities", [])
    result = []
    for act in activities:
        sport_type = act.get("sport_type") or act.get("type") or ""
        flat = {
            "date":                      day_record.get("date"),
            "name":                      act.get("name"),
            "enriched_name":             act.get("enriched_name"),
            "sport_type":                sport_type,
            "distance_miles":            act.get("distance_miles"),
            "total_elevation_gain_feet": act.get("total_elevation_gain_feet"),
            "moving_time_seconds":       act.get("moving_time_seconds"),
            "average_heartrate":         act.get("average_heartrate"),
            "max_heartrate":             act.get("max_heartrate"),
            "average_watts":             act.get("average_watts"),
            "kilojoules":                act.get("kilojoules"),
            "pr_count":                  act.get("pr_count"),
            "achievement_count":         act.get("achievement_count"),
            "strava_id":                 act.get("strava_id"),
        }
        result.append({k: v for k, v in flat.items() if v is not None})
    return result


# ── Training load model helpers ───────────────────────────────────────────────
def compute_daily_load_score(day_record):
    kj     = day_record.get("total_kilojoules") or 0
    dist   = day_record.get("total_distance_miles") or 0
    elev   = day_record.get("total_elevation_gain_feet") or 0
    hr_avg = day_record.get("average_heartrate") or 0
    time_s = day_record.get("total_moving_time_seconds") or 0

    if kj > 0:
        return float(kj)

    if hr_avg > 0 and time_s > 0:
        profile = get_profile()
        rhr = profile.get("resting_heart_rate_baseline", 55)
        mhr = profile.get("max_heart_rate", 190)
        hr_r = (hr_avg - rhr) / max(mhr - rhr, 1)
        trimp = (time_s / 3600) * hr_avg * 0.64 * math.exp(1.92 * hr_r)
        return round(trimp, 1)

    return round(dist * 10 + elev / 100, 1)


def compute_ewa(daily_values_chrono, decay_days):
    alpha  = 1.0 - math.exp(-1.0 / decay_days)
    ewa    = 0.0
    result = []
    for date_str, val in daily_values_chrono:
        ewa = alpha * val + (1 - alpha) * ewa
        result.append((date_str, round(ewa, 2)))
    return result


def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num   = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = math.sqrt(sum((x - mx)**2 for x in xs) * sum((y - my)**2 for y in ys))
    if denom == 0:
        return None
    return round(num / denom, 3)


def _linear_regression(points):
    """Simple OLS on list of (x, y) tuples. Returns slope, intercept, r_squared."""
    n = len(points)
    if n < 2:
        return None, None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = sum(xs)/n, sum(ys)/n
    ss_xx = sum((x - mx)**2 for x in xs)
    if ss_xx == 0:
        return 0, my, 0
    ss_xy = sum((x - mx)*(y - my) for x, y in zip(xs, ys))
    slope = ss_xy / ss_xx
    intercept = my - slope * mx
    ss_yy = sum((y - my)**2 for y in ys)
    r_sq = (ss_xy**2 / (ss_xx * ss_yy)) if ss_yy > 0 else 0
    return round(slope, 4), round(intercept, 2), round(r_sq, 3)


def classify_day_type(whoop_strain=None, strava_activities=None, daily_load=None):
    """
    Classify a day as rest/light/moderate/hard/race based on training signals.

    Priority:
      1. Strava activity type == 'Race' → 'race'
      2. Whoop strain or computed load → thresholds
      3. Strava activity count + distance as fallback

    Returns: 'rest', 'light', 'moderate', 'hard', or 'race'
    """
    # Check for race flag in Strava activities
    if strava_activities:
        for act in (strava_activities if isinstance(strava_activities, list) else [strava_activities]):
            if isinstance(act, dict):
                if act.get("workout_type") == "Race" or act.get("type", "").lower() == "race":
                    return "race"

    # Primary: Whoop strain (0-21 scale)
    if whoop_strain is not None:
        strain = float(whoop_strain)
        if strain < 4:
            return "rest"
        elif strain < 8:
            return "light"
        elif strain < 14:
            return "moderate"
        else:
            return "hard"

    # Secondary: computed load score (kJ or TRIMP)
    if daily_load is not None:
        load = float(daily_load)
        if load < 50:
            return "rest"
        elif load < 200:
            return "light"
        elif load < 500:
            return "moderate"
        else:
            return "hard"

    # Tertiary: Strava activity presence
    if strava_activities:
        acts = strava_activities if isinstance(strava_activities, list) else [strava_activities]
        if isinstance(acts[0], dict):
            total_dist = sum(float(a.get("total_distance_miles", 0) or 0) for a in acts)
            total_time = sum(float(a.get("total_moving_time_seconds", 0) or 0) for a in acts)
            if total_dist > 10 or total_time > 5400:
                return "hard"
            elif total_dist > 3 or total_time > 2700:
                return "moderate"
            elif total_dist > 0 or total_time > 0:
                return "light"

    return "rest"


DAY_TYPE_THRESHOLDS = {
    "whoop_strain": {"rest": 4, "light": 8, "moderate": 14, "hard": 21},
    "load_score":   {"rest": 50, "light": 200, "moderate": 500, "hard": float("inf")},
}



# ── Chronicling / Habits helpers ──

def query_chronicling(start_date, end_date):
    """Query habit items (habitify or chronicling) based on source-of-truth.
    Name kept for backward compatibility with all habit tool call sites."""
    source = get_sot("habits")
    return query_source(source, start_date, end_date)


def _habit_series(items):
    """
    From raw chronicling items return a list of
    {date, habits: {name: 0/1}, by_group: {...}, total_completed, total_possible, completion_pct}
    sorted chronologically.
    """
    rows = []
    for item in sorted(items, key=lambda x: x.get("date", "")):
        if not item.get("habits"):
            continue
        rows.append({
            "date":            item.get("date"),
            "habits":          {k: int(v) for k, v in item.get("habits", {}).items()},
            "by_group":        item.get("by_group", {}),
            "total_completed": item.get("total_completed", 0),
            "total_possible":  item.get("total_possible", 0),
            "completion_pct":  item.get("completion_pct", 0),
        })
    return rows


# ── Whoop → normalised sleep field mapper ──────────────────────────────────
# Whoop is SOT for sleep duration, staging, score, and efficiency (v2.55.0).
# Eight Sleep remains SOT for bed environment (temperature, toss & turns).
# This normaliser maps Whoop DynamoDB fields to a common schema so all sleep
# consumers (tools_sleep, tools_correlation, tools_health, daily brief) use
# a consistent field vocabulary.

def normalize_whoop_sleep(item):
    """Map Whoop DynamoDB fields to normalised sleep analysis fields.

    Returns a new dict with the original item fields PLUS normalised aliases:
      sleep_score, sleep_efficiency_pct, deep_pct, rem_pct, light_pct,
      waso_hours, hrv_avg, sleep_onset_hour, wake_hour, sleep_midpoint_hour.

    Idempotent: if a target field already exists, it is NOT overwritten.
    """
    out = dict(item)  # shallow copy – preserve all original fields

    # Score & efficiency
    if "sleep_quality_score" in item and "sleep_score" not in item:
        out["sleep_score"] = item["sleep_quality_score"]
    if "sleep_efficiency_percentage" in item and "sleep_efficiency_pct" not in item:
        out["sleep_efficiency_pct"] = item["sleep_efficiency_percentage"]

    # Stage percentages from absolute hours
    dur = None
    try:
        dur = float(item["sleep_duration_hours"]) if item.get("sleep_duration_hours") else None
    except (ValueError, TypeError):
        pass

    if dur and dur > 0:
        for src_field, pct_field in [
            ("slow_wave_sleep_hours", "deep_pct"),
            ("rem_sleep_hours",      "rem_pct"),
            ("light_sleep_hours",    "light_pct"),
        ]:
            val = item.get(src_field)
            if val is not None and pct_field not in item:
                try:
                    out[pct_field] = round(float(val) / dur * 100, 1)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

    # WASO
    if "time_awake_hours" in item and "waso_hours" not in item:
        out["waso_hours"] = item["time_awake_hours"]

    # HRV
    if "hrv" in item and "hrv_avg" not in item:
        out["hrv_avg"] = item["hrv"]

    # Disturbances
    if "disturbance_count" in item and "toss_and_turns" not in item:
        out["toss_and_turns"] = item["disturbance_count"]

    # Circadian timing derived from ISO timestamps
    def _hour_from_iso(ts_str, tz_offset_hours=-8):
        """Extract decimal hour (local) from ISO timestamp string."""
        if not ts_str:
            return None
        try:
            clean = ts_str.replace("Z", "+00:00")
            t_part = clean.split("T")[1] if "T" in clean else None
            if not t_part:
                return None
            parts = t_part.split("+")[0].split("-")[0].split(":")
            utc_h = int(parts[0]) + int(parts[1]) / 60
            if len(parts) > 2:
                utc_h += float(parts[2].split(".")[0]) / 3600
            local_h = (utc_h + tz_offset_hours) % 24
            return round(local_h, 2)
        except Exception:
            return None

    if item.get("sleep_start") and "sleep_onset_hour" not in item:
        out["sleep_onset_hour"] = _hour_from_iso(item["sleep_start"])
    if item.get("sleep_end") and "wake_hour" not in item:
        out["wake_hour"] = _hour_from_iso(item["sleep_end"])
    if out.get("sleep_onset_hour") is not None and out.get("wake_hour") is not None:
        onset = out["sleep_onset_hour"]
        wake = out["wake_hour"]
        if wake < onset:  # crosses midnight
            mid = ((onset + wake + 24) / 2) % 24
        else:
            mid = (onset + wake) / 2
        out["sleep_midpoint_hour"] = round(mid, 2)

    return out
