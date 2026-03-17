"""
Lifestyle tools: insights, supplements, weather, social, meditation, travel, BP, experiments, gait, energy, movement, state_of_mind.
"""
import json
import math
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from boto3.dynamodb.conditions import Key

from mcp.config import (
    table, s3_client, S3_BUCKET, USER_PREFIX, USER_ID, SOURCES,
    P40_GROUPS, FIELD_ALIASES, logger,
    INSIGHTS_PK, EXPERIMENTS_PK, TRAVEL_PK, RUCK_PK,
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
from mcp.labs_helpers import (
    _get_genome_cached, _query_all_lab_draws, _query_dexa_scans,
    _query_lab_meta, _genome_context_for_biomarkers,
)

# ── Travel constants ──

_TZ_OFFSETS = {
    "America/Los_Angeles": -8, "America/Denver": -7, "America/Chicago": -6,
    "America/New_York": -5, "America/Anchorage": -9, "Pacific/Honolulu": -10,
    "Europe/London": 0, "Europe/Paris": 1, "Europe/Berlin": 1, "Europe/Rome": 1,
    "Europe/Madrid": 1, "Europe/Amsterdam": 1, "Europe/Zurich": 1,
    "Asia/Tokyo": 9, "Asia/Shanghai": 8, "Asia/Hong_Kong": 8, "Asia/Singapore": 8,
    "Asia/Seoul": 9, "Asia/Bangkok": 7, "Asia/Dubai": 4, "Asia/Kolkata": 5.5,
    "Australia/Sydney": 10, "Australia/Melbourne": 10, "Australia/Perth": 8,
    "Pacific/Auckland": 12, "America/Sao_Paulo": -3, "America/Mexico_City": -6,
    "America/Toronto": -5, "America/Vancouver": -8, "Africa/Cairo": 2,
    "America/Lima": -5, "America/Bogota": -5, "America/Buenos_Aires": -3,
}
HOME_TZ = "America/Los_Angeles"
HOME_OFFSET = _TZ_OFFSETS[HOME_TZ]


def _tz_offset(tz_name):
    """Get UTC offset for a timezone name. Returns None if unknown."""
    return _TZ_OFFSETS.get(tz_name)


def _is_traveling(date_str=None):
    """Check if a given date (or today) falls within an active trip. Returns trip dict or None."""
    check_date = date_str or datetime.utcnow().strftime("%Y-%m-%d")
    try:
        resp = get_table().query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": TRAVEL_PK, ":prefix": "TRIP#"},
        )
        for item in resp.get("Items", []):
            item = _d2f(item)
            start = item.get("start_date", "")
            end = item.get("end_date") or "9999-12-31"
            if start <= check_date <= end:
                return item
        return None
    except Exception:
        return None


# ── Experiment metrics ──

_EXPERIMENT_METRICS = [
    # Sleep
    ("whoop",      "sleep_score",               "Sleep Score",          True),   # normalized from sleep_quality_score
    ("whoop",      "sleep_efficiency_pct",      "Sleep Efficiency %",   True),   # normalized from sleep_efficiency_percentage
    ("whoop",      "deep_pct",                  "Deep Sleep %",         True),   # normalized from slow_wave_sleep_hours
    ("whoop",      "rem_pct",                   "REM Sleep %",          True),   # normalized from rem_sleep_hours
    ("eightsleep", "sleep_onset_latency_min",    "Sleep Onset Latency",  False),  # Eight Sleep only — Whoop doesn't track
    # Recovery
    ("whoop",      "recovery_score",             "Whoop Recovery",       True),
    ("whoop",      "hrv_rmssd",                  "HRV (rMSSD)",         True),
    ("whoop",      "resting_heart_rate",         "Resting HR",          False),
    # Stress & Energy
    ("garmin",     "average_stress_level",       "Garmin Stress",       False),
    ("garmin",     "body_battery_high",          "Body Battery Peak",   True),
    # Body
    ("withings",   "weight_lbs",                 "Weight (lbs)",        None),  # direction depends on goal
    # Nutrition
    ("macrofactor", "calories",                  "Calories",            None),
    ("macrofactor", "protein_g",                 "Protein (g)",         None),
    # Movement
    ("apple_health", "steps",                    "Steps",               True),
    # Glucose (if available)
    ("apple_health", "cgm_mean_glucose",         "Mean Glucose",        False),
    ("apple_health", "cgm_time_in_range_pct",    "CGM Time in Range %", True),
]


def _extract_metric(item, field_path):
    """Extract a numeric value from a DynamoDB item, handling nested dicts."""
    val = item
    for part in field_path.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _fetch_weather_range(start_date, end_date):
    """
    Fetch weather data from Open-Meteo archive API for Seattle.
    Caches results in DynamoDB weather partition.
    Returns list of day records.
    """
    # Seattle coordinates
    LAT, LON = 47.6062, -122.3321

    # Check DynamoDB cache first
    cached = query_source("weather", start_date, end_date)
    cached_dates = {item.get("date") for item in cached if item.get("date")}

    # Find missing dates
    missing_dates = []
    d = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= d_end:
        ds = d.strftime("%Y-%m-%d")
        if ds not in cached_dates:
            missing_dates.append(ds)
        d += timedelta(days=1)

    # Fetch missing from Open-Meteo
    if missing_dates:
        fetch_start = min(missing_dates)
        fetch_end = max(missing_dates)
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={LAT}&longitude={LON}"
            f"&start_date={fetch_start}&end_date={fetch_end}"
            f"&daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            f"relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max,"
            f"surface_pressure_mean,daylight_duration,uv_index_max,"
            f"sunshine_duration"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&precipitation_unit=mm&timezone=America/Los_Angeles"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            daily = data.get("daily", {})
            dates = daily.get("time", [])
            table = boto3.resource("dynamodb", region_name=_REGION).Table(TABLE_NAME)

            new_records = []
            for i, date_str in enumerate(dates):
                if date_str not in set(missing_dates):
                    continue
                daylight_hrs = round(float(daily["daylight_duration"][i] or 0) / 3600, 2)
                sunshine_hrs = round(float(daily["sunshine_duration"][i] or 0) / 3600, 2)
                record = {
                    "date": date_str,
                    "temp_high_f": daily["temperature_2m_max"][i],
                    "temp_low_f": daily["temperature_2m_min"][i],
                    "temp_avg_f": daily["temperature_2m_mean"][i],
                    "humidity_pct": daily["relative_humidity_2m_mean"][i],
                    "precipitation_mm": daily["precipitation_sum"][i],
                    "wind_speed_max_mph": daily["wind_speed_10m_max"][i],
                    "pressure_hpa": daily["surface_pressure_mean"][i],
                    "daylight_hours": daylight_hrs,
                    "sunshine_hours": sunshine_hrs,
                    "uv_index_max": daily["uv_index_max"][i],
                }
                new_records.append(record)

                # Cache in DynamoDB
                db_item = {
                    "pk": USER_PREFIX + "weather",
                    "sk": f"DATE#{date_str}",
                    "source": "weather",
                    **record,
                }
                try:
                    from decimal import Decimal
                    def _to_decimal(obj):
                        if isinstance(obj, float):
                            return Decimal(str(round(obj, 4)))
                        if isinstance(obj, dict):
                            return {k: _to_decimal(v) for k, v in obj.items()}
                        if isinstance(obj, list):
                            return [_to_decimal(v) for v in obj]
                        return obj
                    table.put_item(Item=_to_decimal(db_item))
                except Exception as e:
                    logger.warning(f"Weather cache write failed for {date_str}: {e}")

            print(f"Fetched and cached {len(new_records)} weather days from Open-Meteo")
            cached.extend(new_records)

        except Exception as e:
            logger.warning(f"Open-Meteo fetch failed: {e}")
            # Continue with whatever cached data we have

    return cached


def _load_bp_readings(date_str):
    """Load individual BP readings from S3 for a given date.
    Returns list of dicts with time, systolic, diastolic, pulse."""
    try:
        y, m, d = date_str.split("-")
        key = f"raw/blood_pressure/{y}/{m}/{d}.json"
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        return []
    except Exception as e:
        logger.warning(f"BP read failed for {date_str}: {e}")
        return []


def tool_save_insight(args):
    """Save a new insight to the coaching log.
    PK: USER#matthew#SOURCE#insights
    SK: INSIGHT#<ISO-timestamp>
    """
    text   = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")

    tags   = args.get("tags") or []
    source = args.get("source") or "chat"

    now        = datetime.utcnow()
    ts         = now.strftime("%Y-%m-%dT%H:%M:%S")
    insight_id = ts  # human-readable, doubles as sort key suffix
    sk         = f"INSIGHT#{ts}"

    item = {
        "pk":           INSIGHTS_PK,
        "sk":           sk,
        "insight_id":   insight_id,
        "text":         text,
        "date_saved":   now.strftime("%Y-%m-%d"),
        "source":       source,
        "status":       "open",
        "outcome_notes": "",
        "tags":         tags,
    }
    table.put_item(Item=item)
    logger.info(f"save_insight: saved insight_id={insight_id}")
    return {
        "saved":        True,
        "insight_id":   insight_id,
        "date_saved":   item["date_saved"],
        "text_preview": text[:120] + ("…" if len(text) > 120 else ""),
        "tags":         tags,
        "source":       source,
    }


def tool_get_insights(args):
    """List insights from the coaching log.
    Optionally filter by status (open/acted/resolved).
    Returns newest-first. Flags items open >14 days.
    """
    status_filter = args.get("status_filter")  # None = all
    limit         = int(args.get("limit") or 50)
    today         = datetime.utcnow().date()

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(INSIGHTS_PK) & Key("sk").begins_with("INSIGHT#"),
        ScanIndexForward=False,  # newest first
        Limit=200,
    )
    items = resp.get("Items", [])

    results = []
    for item in items:
        status = item.get("status", "open")
        if status_filter and status != status_filter:
            continue

        date_saved = item.get("date_saved", "")
        try:
            days_open = (today - datetime.strptime(date_saved, "%Y-%m-%d").date()).days
        except Exception:
            days_open = None

        results.append({
            "insight_id":    item.get("insight_id", ""),
            "text":          item.get("text", ""),
            "date_saved":    date_saved,
            "days_open":     days_open,
            "source":        item.get("source", "chat"),
            "status":        status,
            "outcome_notes": item.get("outcome_notes", ""),
            "tags":          item.get("tags", []),
            "stale":         (days_open is not None and days_open > 14 and status == "open"),
        })
        if len(results) >= limit:
            break

    stale_count = sum(1 for r in results if r["stale"])
    return {
        "total":         len(results),
        "stale_count":   stale_count,
        "status_filter": status_filter or "all",
        "insights":      results,
    }


def tool_update_insight_outcome(args):
    """Update the outcome notes and/or status of an existing insight.
    insight_id is the timestamp string returned by save_insight (e.g. 2026-02-22T09:15:00).
    status must be one of: open, acted, resolved.
    """
    insight_id     = (args.get("insight_id") or "").strip()
    outcome_notes  = (args.get("outcome_notes") or "").strip()
    new_status     = (args.get("status") or "acted").strip()

    if not insight_id:
        raise ValueError("insight_id is required")
    if new_status not in ("open", "acted", "resolved"):
        raise ValueError("status must be one of: open, acted, resolved")

    sk = f"INSIGHT#{insight_id}"

    # Verify the item exists
    existing = table.get_item(Key={"pk": INSIGHTS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"No insight found with id={insight_id}")

    table.update_item(
        Key={"pk": INSIGHTS_PK, "sk": sk},
        UpdateExpression="SET #s = :s, outcome_notes = :o, date_updated = :d",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": new_status,
            ":o": outcome_notes,
            ":d": datetime.utcnow().strftime("%Y-%m-%d"),
        },
    )
    logger.info(f"update_insight_outcome: insight_id={insight_id} status={new_status}")
    return {
        "updated":       True,
        "insight_id":    insight_id,
        "status":        new_status,
        "outcome_notes": outcome_notes,
        "text_preview":  existing.get("text", "")[:120],
    }


def tool_log_supplement(args):
    """
    Log a supplement or medication entry. Writes to DynamoDB supplements partition.
    Supports multiple entries per day (appends to existing list).
    """
    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    name = args.get("name", "").strip()
    if not name:
        return {"error": "Supplement name is required."}

    dose = args.get("dose")
    unit = args.get("unit", "")
    timing = args.get("timing", "")  # morning, with_meal, before_bed, etc.
    notes = args.get("notes", "")
    category = args.get("category", "supplement")  # supplement, medication, vitamin, mineral

    entry = {
        "name": name,
        "dose": Decimal(str(dose)) if dose is not None else None,
        "unit": unit,
        "timing": timing,
        "category": category,
        "notes": notes,
        "logged_at": datetime.utcnow().isoformat(),
    }
    # Remove None values
    entry = {k: v for k, v in entry.items() if v is not None and v != ""}

    table = boto3.resource("dynamodb", region_name=_REGION).Table(TABLE_NAME)

    # Try to append to existing record, or create new
    try:
        table.update_item(
            Key={"pk": USER_PREFIX + "supplements", "sk": f"DATE#{date}"},
            UpdateExpression="SET #s = list_append(if_not_exists(#s, :empty), :entry), #d = :date, #src = :src, #ua = :ua",
            ExpressionAttributeNames={"#s": "supplements", "#d": "date", "#src": "source", "#ua": "updated_at"},
            ExpressionAttributeValues={
                ":entry": [entry],
                ":empty": [],
                ":date": date,
                ":src": "supplements",
                ":ua": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        return {"error": f"Failed to log supplement: {e}"}

    dose_str = f" {dose}{unit}" if dose else ""
    timing_str = f" ({timing})" if timing else ""
    return {
        "status": "logged",
        "date": date,
        "entry": f"{name}{dose_str}{timing_str}",
        "message": f"Logged {name}{dose_str}{timing_str} for {date}.",
    }


def tool_get_supplement_log(args):
    """
    Retrieve supplement/medication log for a date range.
    Shows what was taken, dosage, timing, and adherence patterns.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    name_filter = (args.get("name") or "").strip().lower()

    items = query_source("supplements", start_date, end_date)
    if not items:
        return {"error": "No supplement data for range.", "start_date": start_date, "end_date": end_date,
                "tip": "Use log_supplement to start tracking. Example: log 500mg magnesium glycinate before bed."}

    all_entries = []
    by_supplement = {}
    by_date = {}

    for item in items:
        date = item.get("date")
        entries = item.get("supplements") or []
        day_entries = []
        for entry in entries:
            ename = entry.get("name", "")
            if name_filter and name_filter not in ename.lower():
                continue
            entry["date"] = date
            all_entries.append(entry)
            day_entries.append(entry)

            # Aggregate by supplement name
            key = ename.lower()
            if key not in by_supplement:
                by_supplement[key] = {"name": ename, "days_taken": 0, "entries": [], "doses": [], "timings": set()}
            by_supplement[key]["days_taken"] += 1
            by_supplement[key]["entries"].append(entry)
            if entry.get("dose") is not None:
                by_supplement[key]["doses"].append(float(entry["dose"]))
            if entry.get("timing"):
                by_supplement[key]["timings"].add(entry["timing"])

        if day_entries:
            by_date[date] = day_entries

    if not all_entries:
        return {"error": f"No entries found{' for ' + name_filter if name_filter else ''}.",
                "start_date": start_date, "end_date": end_date}

    # Total days in range
    d_start = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (d_end - d_start).days + 1
    days_logged = len(by_date)

    # Summary per supplement
    supplement_summary = []
    for key, data in sorted(by_supplement.items(), key=lambda x: x[1]["days_taken"], reverse=True):
        avg_dose = round(sum(data["doses"]) / len(data["doses"]), 1) if data["doses"] else None
        adherence_pct = round(data["days_taken"] / total_days * 100, 1)
        supplement_summary.append({
            "name": data["name"],
            "days_taken": data["days_taken"],
            "adherence_pct": adherence_pct,
            "avg_dose": avg_dose,
            "unit": data["entries"][0].get("unit", "") if data["entries"] else "",
            "typical_timings": sorted(data["timings"]),
            "category": data["entries"][0].get("category", "supplement") if data["entries"] else "",
        })

    # Recent log (last 7 days)
    recent = {}
    for date in sorted(by_date.keys(), reverse=True)[:7]:
        recent[date] = [{"name": e.get("name"), "dose": float(e["dose"]) if e.get("dose") else None,
                         "unit": e.get("unit", ""), "timing": e.get("timing", "")} for e in by_date[date]]

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_days_in_range": total_days,
        "days_with_entries": days_logged,
        "total_entries": len(all_entries),
        "unique_supplements": len(by_supplement),
        "supplement_summary": supplement_summary,
        "recent_log": recent,
        "source": "supplements (manual log via log_supplement)",
    }


def tool_get_supplement_correlation(args):
    """
    Cross-reference supplement intake with health outcomes.
    Compares days taking a supplement vs days without across sleep, recovery, glucose, HRV.
    Enhances N=1 experiments with supplement-specific analysis.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    supplement_name = (args.get("name") or "").strip().lower()

    if not supplement_name:
        return {"error": "Supplement name required. Specify which supplement to analyze."}

    supp_items = query_source("supplements", start_date, end_date)
    if not supp_items:
        return {"error": "No supplement data for range.", "start_date": start_date, "end_date": end_date}

    # Find days with and without this supplement
    days_with = set()
    for item in supp_items:
        for entry in (item.get("supplements") or []):
            if supplement_name in (entry.get("name") or "").lower():
                days_with.add(item.get("date"))

    if not days_with:
        return {"error": f"No entries found for '{supplement_name}'.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # Fetch health data
    sources = {"whoop": None, "eightsleep": None, "garmin": None, "apple_health": None}
    for src in sources:
        try:
            sources[src] = query_source(src, start_date, end_date)
        except Exception:
            pass
    # Normalize Whoop sleep fields (sleep_score, deep_pct, etc.)
    if sources.get("whoop"):
        sources["whoop"] = [normalize_whoop_sleep(i) for i in sources["whoop"]]

    # Build day-level metrics
    METRICS = [
        ("whoop", "recovery_score", "Whoop Recovery", "higher_is_better"),
        ("whoop", "hrv", "HRV", "higher_is_better"),
        ("whoop", "resting_heart_rate", "Resting HR", "lower_is_better"),
        ("whoop", "sleep_score", "Sleep Score", "higher_is_better"),
        ("whoop", "sleep_efficiency_pct", "Sleep Efficiency", "higher_is_better"),
        ("whoop", "deep_pct", "Deep Sleep %", "higher_is_better"),
        ("whoop", "rem_pct", "REM %", "higher_is_better"),
        ("eightsleep", "time_to_sleep_min", "Sleep Onset", "lower_is_better"),  # Eight Sleep only
        ("garmin", "body_battery_high", "Body Battery", "higher_is_better"),
        ("garmin", "avg_stress", "Garmin Stress", "lower_is_better"),
        ("apple_health", "blood_glucose_avg", "Glucose Avg", "lower_is_better"),
    ]

    # Index source data by date
    by_date = {}
    for src, items in sources.items():
        if not items:
            continue
        for item in items:
            d = item.get("date")
            if d not in by_date:
                by_date[d] = {}
            by_date[d][src] = item

    # All dates in range
    all_dates = set(by_date.keys())
    days_without = all_dates - days_with

    # Compare metrics
    comparisons = []
    for src, field, label, direction in METRICS:
        with_vals = []
        without_vals = []
        for d in days_with:
            if d in by_date and src in by_date[d]:
                v = _sf(by_date[d][src].get(field))
                if v is not None:
                    with_vals.append(v)
        for d in days_without:
            if d in by_date and src in by_date[d]:
                v = _sf(by_date[d][src].get(field))
                if v is not None:
                    without_vals.append(v)

        if len(with_vals) >= 3 and len(without_vals) >= 3:
            avg_with = _avg(with_vals)
            avg_without = _avg(without_vals)
            delta = round(avg_with - avg_without, 2)

            if direction == "higher_is_better":
                effect = "positive" if delta > 0 else ("negative" if delta < 0 else "neutral")
            else:
                effect = "positive" if delta < 0 else ("negative" if delta > 0 else "neutral")

            comparisons.append({
                "metric": label,
                "avg_with_supplement": avg_with,
                "avg_without_supplement": avg_without,
                "delta": delta,
                "effect": effect,
                "n_with": len(with_vals),
                "n_without": len(without_vals),
            })

    # Board of Directors
    bod = []
    positive_effects = [c for c in comparisons if c["effect"] == "positive"]
    negative_effects = [c for c in comparisons if c["effect"] == "negative"]

    if positive_effects:
        metrics = ", ".join([c["metric"] for c in positive_effects[:3]])
        bod.append(f"Attia: {supplement_name.title()} shows positive association with {metrics}. Correlation ≠ causation — consider running a formal N=1 experiment with create_experiment.")
    if negative_effects:
        metrics = ", ".join([c["metric"] for c in negative_effects[:3]])
        bod.append(f"Huberman: Possible negative association with {metrics}. Check timing and dosage — many supplements are timing-dependent.")
    if len(days_with) < 14:
        bod.append(f"Attia: Only {len(days_with)} days of data. Minimum 14 days recommended for meaningful N=1 analysis.")
    if not comparisons:
        bod.append("Insufficient overlapping data between supplement log and health metrics for comparison.")

    return {
        "supplement": supplement_name,
        "period": {"start_date": start_date, "end_date": end_date},
        "days_with_supplement": len(days_with),
        "days_without_supplement": len(days_without),
        "comparisons": comparisons,
        "board_of_directors": bod,
        "methodology": (
            "Compares average health metrics on days taking the supplement vs days without. "
            "Effect direction accounts for whether higher or lower is better for each metric. "
            "Requires >= 3 data points in each group. Correlation only — use N=1 experiments for causal inference."
        ),
        "source": "supplements + whoop + garmin + apple_health (sleep from Whoop SOT)",
    }


def tool_get_weather_correlation(args):
    """
    Weather & seasonal correlation analysis. Fetches weather for Seattle from
    Open-Meteo (free API), caches in DynamoDB, and correlates with health metrics.

    Huberman: Light exposure (daylight hours) is the master circadian lever.
    Walker: Seasonal light changes drive mood, energy, and sleep timing shifts.
    Attia: Barometric pressure changes correlate with joint pain and headaches.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # Fetch weather data (cached + fresh from Open-Meteo)
    weather_items = _fetch_weather_range(start_date, end_date)
    if not weather_items:
        return {"error": "Could not fetch weather data.", "start_date": start_date, "end_date": end_date}

    weather_by_date = {w.get("date"): w for w in weather_items if w.get("date")}

    # Fetch health data
    health_sources = {}
    for src in ["whoop", "garmin", "apple_health"]:
        try:
            items = query_source(src, start_date, end_date)
            if src == "whoop":
                items = [normalize_whoop_sleep(i) for i in items]
            health_sources[src] = {item.get("date"): item for item in items if item.get("date")}
        except Exception:
            health_sources[src] = {}

    # Journal mood/energy
    journal_by_date = {}
    try:
        journal_items = query_source("notion", start_date, end_date)
        for item in journal_items:
            d = item.get("date")
            if d and not d in journal_by_date:
                journal_by_date[d] = {}
            for field in ["morning_mood", "morning_energy", "stress_level", "day_rating"]:
                v = _sf(item.get(field))
                if v is not None:
                    journal_by_date.setdefault(d, {})[field] = v
    except Exception:
        pass

    # Weather variables to correlate
    WEATHER_VARS = [
        ("temp_avg_f", "Temperature (°F)"),
        ("humidity_pct", "Humidity (%)"),
        ("precipitation_mm", "Precipitation (mm)"),
        ("daylight_hours", "Daylight Hours"),
        ("sunshine_hours", "Sunshine Hours"),
        ("pressure_hpa", "Barometric Pressure (hPa)"),
        ("uv_index_max", "UV Index"),
    ]

    # Health metrics to compare against
    HEALTH_METRICS = [
        ("whoop", "recovery_score", "Whoop Recovery"),
        ("whoop", "hrv", "HRV"),
        ("whoop", "sleep_score", "Sleep Score"),
        ("whoop", "sleep_efficiency_pct", "Sleep Efficiency"),
        ("whoop", "deep_pct", "Deep Sleep %"),
        ("garmin", "avg_stress", "Garmin Stress"),
        ("garmin", "body_battery_high", "Body Battery"),
    ]
    JOURNAL_METRICS = [
        ("morning_mood", "Morning Mood"),
        ("morning_energy", "Morning Energy"),
        ("stress_level", "Stress Level"),
        ("day_rating", "Day Rating"),
    ]

    # Compute correlations
    correlations = {}
    for wvar, wlabel in WEATHER_VARS:
        correlations[wvar] = {"label": wlabel, "health_correlations": {}, "journal_correlations": {}}

        for src, field, hlabel in HEALTH_METRICS:
            xs, ys = [], []
            for d, w in weather_by_date.items():
                wv = _sf(w.get(wvar))
                if wv is None: continue
                hv = _sf(health_sources.get(src, {}).get(d, {}).get(field))
                if hv is not None:
                    xs.append(wv); ys.append(hv)
            r = pearson_r(xs, ys) if len(xs) >= 10 else None
            if r is not None:
                correlations[wvar]["health_correlations"][field] = {"label": hlabel, "pearson_r": r, "n": len(xs)}

        for jfield, jlabel in JOURNAL_METRICS:
            xs, ys = [], []
            for d, w in weather_by_date.items():
                wv = _sf(w.get(wvar))
                if wv is None: continue
                jv = journal_by_date.get(d, {}).get(jfield)
                if jv is not None:
                    xs.append(wv); ys.append(jv)
            r = pearson_r(xs, ys) if len(xs) >= 10 else None
            if r is not None:
                correlations[wvar]["journal_correlations"][jfield] = {"label": jlabel, "pearson_r": r, "n": len(xs)}

    # Remove empty correlation groups
    for wvar in list(correlations.keys()):
        if not correlations[wvar]["health_correlations"] and not correlations[wvar]["journal_correlations"]:
            del correlations[wvar]

    # Weather summary
    weather_summary = {
        "avg_temp_f": _avg([_sf(w.get("temp_avg_f")) for w in weather_items]),
        "avg_humidity_pct": _avg([_sf(w.get("humidity_pct")) for w in weather_items]),
        "total_precip_mm": round(sum(_sf(w.get("precipitation_mm")) or 0 for w in weather_items), 1),
        "avg_daylight_hours": _avg([_sf(w.get("daylight_hours")) for w in weather_items]),
        "avg_sunshine_hours": _avg([_sf(w.get("sunshine_hours")) for w in weather_items]),
        "rainy_days": sum(1 for w in weather_items if (_sf(w.get("precipitation_mm")) or 0) > 0.5),
        "total_days": len(weather_items),
    }

    # Seasonal comparison (if enough data)
    seasonal = None
    if len(weather_items) >= 60:
        mid = len(weather_items) // 2
        first_half = weather_items[:mid]
        second_half = weather_items[mid:]
        seasonal = {
            "first_half_avg_daylight": _avg([_sf(w.get("daylight_hours")) for w in first_half]),
            "second_half_avg_daylight": _avg([_sf(w.get("daylight_hours")) for w in second_half]),
            "daylight_trend": "increasing" if (_avg([_sf(w.get("daylight_hours")) for w in second_half]) or 0) > (_avg([_sf(w.get("daylight_hours")) for w in first_half]) or 0) else "decreasing",
        }

    # Find strongest correlations
    notable = []
    for wvar, data in correlations.items():
        for field, corr in {**data.get("health_correlations", {}), **data.get("journal_correlations", {})}.items():
            r = corr.get("pearson_r", 0)
            if abs(r) >= 0.2:
                notable.append({"weather": data["label"], "health": corr["label"], "r": r, "n": corr["n"]})
    notable.sort(key=lambda x: abs(x["r"]), reverse=True)

    # Board of Directors
    bod = []
    daylight_mood = correlations.get("daylight_hours", {}).get("journal_correlations", {}).get("morning_mood", {})
    if daylight_mood and daylight_mood.get("pearson_r", 0) > 0.15:
        bod.append(f"Huberman: Daylight correlates with your mood (r={daylight_mood['pearson_r']}). Morning sunlight within 30 min of waking is the single highest-ROI circadian intervention.")
    
    sunshine_sleep = correlations.get("sunshine_hours", {}).get("health_correlations", {}).get("sleep_score", {})
    if sunshine_sleep and sunshine_sleep.get("pearson_r", 0) > 0.15:
        bod.append(f"Walker: More sunshine correlates with better sleep (r={sunshine_sleep['pearson_r']}). Light exposure during the day strengthens the circadian sleep drive.")

    pressure_corrs = correlations.get("pressure_hpa", {}).get("health_correlations", {})
    if any(abs(c.get("pearson_r", 0)) > 0.2 for c in pressure_corrs.values()):
        bod.append("Attia: Barometric pressure shows correlation with your health metrics. Low-pressure systems (storms) can affect joint inflammation, headaches, and autonomic function.")

    if weather_summary.get("rainy_days", 0) > weather_summary.get("total_days", 1) * 0.5:
        bod.append("Note: Seattle's rain prevalence means outdoor light exposure requires intentionality. Consider a 10,000 lux light therapy lamp for morning use during dark months.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "location": "Seattle, WA (47.61, -122.33)",
        "weather_summary": weather_summary,
        "correlations": correlations,
        "notable_correlations": notable[:10],
        "seasonal_analysis": seasonal,
        "board_of_directors": bod,
        "methodology": (
            "Weather data from Open-Meteo archive API (free, WMO-grade). Cached in DynamoDB after first fetch. "
            "Pearson correlations between daily weather variables and health metrics. "
            "Requires >= 10 overlapping data points per correlation pair. "
            "Huberman: daylight = master circadian lever. Walker: light drives sleep-wake timing."
        ),
        "source": "open-meteo + whoop + garmin + apple_health + notion (sleep from Whoop SOT)",
    }


def tool_get_social_connection_trend(args):
    """
    Aggregates enriched_social_quality from journal entries over time.
    Tracks social connection quality, streaks, rolling averages, and
    correlates with health outcomes. Seligman PERMA model.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    QUALITY_MAP = {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4}

    journal_items = query_source("notion", start_date, end_date)
    if not journal_items:
        return {"error": "No journal data for range.", "start_date": start_date, "end_date": end_date}

    daily_social = {}
    daily_mood = {}
    daily_energy = {}
    daily_stress = {}
    for item in journal_items:
        d = item.get("date")
        if not d:
            continue
        sq = item.get("enriched_social_quality")
        if sq and sq in QUALITY_MAP:
            score = QUALITY_MAP[sq]
            if d not in daily_social or score > daily_social[d]["score"]:
                daily_social[d] = {"quality": sq, "score": score}
        for field, store in [("enriched_mood", daily_mood), ("enriched_energy", daily_energy), ("enriched_stress", daily_stress)]:
            v = _sf(item.get(field))
            if v is not None:
                store[d] = v

    if not daily_social:
        return {"error": "No enriched_social_quality data found.", "entries_checked": len(journal_items)}

    sorted_dates = sorted(daily_social.keys())
    scores = [daily_social[d]["score"] for d in sorted_dates]

    distribution = {}
    for d, info in daily_social.items():
        q = info["quality"]
        distribution[q] = distribution.get(q, 0) + 1

    rolling_7d = []
    rolling_30d = []
    for i, d in enumerate(sorted_dates):
        w7 = scores[max(0, i-6):i+1]
        w30 = scores[max(0, i-29):i+1]
        rolling_7d.append({"date": d, "avg": round(sum(w7)/len(w7), 2)})
        rolling_30d.append({"date": d, "avg": round(sum(w30)/len(w30), 2)})

    current_streak = 0
    longest_streak = 0
    temp_streak = 0
    for d in sorted_dates:
        if daily_social[d]["score"] >= 3:
            temp_streak += 1
            longest_streak = max(longest_streak, temp_streak)
        else:
            temp_streak = 0
    for d in reversed(sorted_dates):
        if daily_social[d]["score"] >= 3:
            current_streak += 1
        else:
            break

    days_since_meaningful = None
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for d in reversed(sorted_dates):
        if daily_social[d]["score"] >= 3:
            days_since_meaningful = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days
            break

    health_correlations = []
    HEALTH_SOURCES = [
        ("whoop", "recovery_score", "Recovery"), ("whoop", "hrv", "HRV"),
        ("whoop", "sleep_quality_score", "Sleep Score"), ("garmin", "avg_stress", "Stress"),
        ("garmin", "body_battery_high", "Body Battery"),
    ]
    health_data = {}
    for src, _, _ in HEALTH_SOURCES:
        if src not in health_data:
            try:
                health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
            except Exception:
                health_data[src] = {}

    for src, field, label in HEALTH_SOURCES:
        xs, ys = [], []
        for d in sorted_dates:
            sq = daily_social[d]["score"]
            hv = _sf(health_data.get(src, {}).get(d, {}).get(field))
            if hv is not None:
                xs.append(sq)
                ys.append(hv)
        if len(xs) >= 10:
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / n
            sx = (sum((x-mx)**2 for x in xs) / n) ** 0.5
            sy = (sum((y-my)**2 for y in ys) / n) ** 0.5
            r = round(cov / (sx * sy), 3) if sx > 0 and sy > 0 else 0
            health_correlations.append({"metric": label, "r": r, "n": n,
                                        "interpretation": "strong" if abs(r) > 0.5 else "moderate" if abs(r) > 0.3 else "weak"})

    journal_correlations = []
    for field_data, label in [(daily_mood, "Mood"), (daily_energy, "Energy"), (daily_stress, "Stress")]:
        xs, ys = [], []
        for d in sorted_dates:
            if d in field_data:
                xs.append(daily_social[d]["score"])
                ys.append(field_data[d])
        if len(xs) >= 10:
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / n
            sx = (sum((x-mx)**2 for x in xs) / n) ** 0.5
            sy = (sum((y-my)**2 for y in ys) / n) ** 0.5
            r = round(cov / (sx * sy), 3) if sx > 0 and sy > 0 else 0
            journal_correlations.append({"metric": label, "r": r, "n": n})

    meaningful_days = [d for d in sorted_dates if daily_social[d]["score"] >= 3]
    low_days = [d for d in sorted_dates if daily_social[d]["score"] <= 2]
    comparison = {}
    for src, field, label in HEALTH_SOURCES:
        m_vals = [_sf(health_data.get(src, {}).get(d, {}).get(field)) for d in meaningful_days]
        l_vals = [_sf(health_data.get(src, {}).get(d, {}).get(field)) for d in low_days]
        m_avg, l_avg = _avg(m_vals), _avg(l_vals)
        if m_avg is not None and l_avg is not None:
            comparison[label] = {"meaningful_avg": m_avg, "low_social_avg": l_avg, "diff": round(m_avg - l_avg, 2)}

    return {
        "start_date": start_date, "end_date": end_date,
        "total_days_with_data": len(daily_social), "distribution": distribution,
        "overall_avg_score": _avg(scores),
        "score_legend": {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4},
        "rolling_7d_latest": rolling_7d[-1] if rolling_7d else None,
        "rolling_30d_latest": rolling_30d[-1] if rolling_30d else None,
        "streaks": {"current_meaningful_streak": current_streak, "longest_meaningful_streak": longest_streak,
                    "days_since_meaningful": days_since_meaningful},
        "health_correlations": health_correlations, "journal_correlations": journal_correlations,
        "meaningful_vs_low_comparison": comparison,
        "perma_context": "Seligman PERMA: Relationships are #1 wellbeing predictor. Holt-Lunstad: isolation increases mortality 26%. Target: meaningful+ connection 5+ days/week.",
    }


def tool_get_social_isolation_risk(args):
    """Flags periods of social isolation and correlates with health declines."""
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    isolation_threshold = int(args.get("consecutive_days", 3))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    QUALITY_MAP = {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4}

    journal_items = query_source("notion", start_date, end_date)
    if not journal_items:
        return {"error": "No journal data.", "start_date": start_date, "end_date": end_date}

    daily_social = {}
    for item in journal_items:
        d = item.get("date")
        sq = item.get("enriched_social_quality")
        if d and sq and sq in QUALITY_MAP:
            score = QUALITY_MAP[sq]
            if d not in daily_social or score > daily_social[d]:
                daily_social[d] = score

    if not daily_social:
        return {"error": "No enriched social quality data.", "entries_checked": len(journal_items)}

    sorted_dates = sorted(daily_social.keys())
    episodes = []
    current_episode = []
    for d in sorted_dates:
        if daily_social[d] < 3:
            current_episode.append(d)
        else:
            if len(current_episode) >= isolation_threshold:
                episodes.append({"start": current_episode[0], "end": current_episode[-1], "duration_days": len(current_episode)})
            current_episode = []
    if len(current_episode) >= isolation_threshold:
        episodes.append({"start": current_episode[0], "end": current_episode[-1], "duration_days": len(current_episode)})

    current_isolation_days = 0
    for d in reversed(sorted_dates):
        if daily_social[d] < 3:
            current_isolation_days += 1
        else:
            break
    currently_isolated = current_isolation_days >= isolation_threshold

    episode_health_impact = []
    health_data = {}
    for src in ["whoop", "garmin"]:
        try:
            health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
        except Exception:
            health_data[src] = {}

    for ep in episodes:
        ep_start = datetime.strptime(ep["start"], "%Y-%m-%d")
        pre_start = (ep_start - timedelta(days=7)).strftime("%Y-%m-%d")
        pre_end = (ep_start - timedelta(days=1)).strftime("%Y-%m-%d")
        impact = {"episode": ep, "health_deltas": {}}
        for src, field, label in [("whoop","recovery_score","Recovery"),("whoop","hrv","HRV"),("whoop","sleep_quality_score","Sleep"),("garmin","avg_stress","Stress")]:
            pre_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in health_data.get(src,{}) if pre_start <= d <= pre_end]
            ep_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in health_data.get(src,{}) if ep["start"] <= d <= ep["end"]]
            pa, ea = _avg(pre_vals), _avg(ep_vals)
            if pa is not None and ea is not None:
                impact["health_deltas"][label] = {"before": pa, "during": ea, "change": round(ea - pa, 2)}
        if impact["health_deltas"]:
            episode_health_impact.append(impact)

    total_days = len(sorted_dates)
    isolated_days = sum(1 for d in sorted_dates if daily_social[d] < 3)
    isolation_pct = round(100 * isolated_days / total_days, 1) if total_days else 0
    risk_level = "high" if (isolation_pct > 60 or currently_isolated) else "moderate" if (isolation_pct > 40 or len(episodes) >= 3) else "low"

    coaching = []
    if currently_isolated:
        coaching.append(f"Low-social period: {current_isolation_days} days. Reach out to one person today.")
    if risk_level != "low":
        coaching.append("Huberman: Social connection activates oxytocin, directly reducing cortisol. Schedule recurring social commitments.")
    if isolation_pct > 50:
        coaching.append("Attia: Loneliness is as harmful to longevity as obesity and smoking.")

    return {
        "start_date": start_date, "end_date": end_date, "risk_level": risk_level,
        "isolation_episodes": episodes, "total_episodes": len(episodes),
        "currently_isolated": currently_isolated, "current_isolation_days": current_isolation_days if currently_isolated else 0,
        "isolation_pct": isolation_pct, "episode_health_impact": episode_health_impact, "coaching": coaching,
    }


def tool_get_meditation_correlation(args):
    """Correlates mindful_minutes from Apple Health with health metrics."""
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    ah_items = query_source("apple_health", start_date, end_date)
    ah_by_date = {item.get("date"): item for item in (ah_items or []) if item.get("date")}

    daily_minutes = {}
    for d, item in ah_by_date.items():
        mm = _sf(item.get("mindful_minutes"))
        if mm is not None and mm > 0:
            daily_minutes[d] = mm

    if not daily_minutes:
        return {"error": "No mindful_minutes data found.", "start_date": start_date, "end_date": end_date,
                "tip": "Enable 'Mindful Minutes' in Health Auto Export iOS app.",
                "apps": "Apple Mindfulness, Headspace, Calm, Insight Timer, Ten Percent Happier"}

    all_dates = sorted(ah_by_date.keys())
    practice_dates = sorted(daily_minutes.keys())
    total_days = len(all_dates)
    practice_days = len(practice_dates)
    adherence_pct = round(100 * practice_days / total_days, 1) if total_days else 0

    current_streak = 0
    longest_streak = 0
    temp_streak = 0
    for d in all_dates:
        if d in daily_minutes:
            temp_streak += 1
            longest_streak = max(longest_streak, temp_streak)
        else:
            temp_streak = 0
    for d in reversed(all_dates):
        if d in daily_minutes:
            current_streak += 1
        else:
            break

    health_data = {}
    for src in ["whoop", "garmin"]:
        try:
            health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
        except Exception:
            health_data[src] = {}

    non_practice_dates = [d for d in all_dates if d not in daily_minutes]
    COMPARE_METRICS = [
        ("whoop","recovery_score","Recovery","higher_is_better"),("whoop","hrv","HRV","higher_is_better"),
        ("whoop","resting_heart_rate","Resting HR","lower_is_better"),("whoop","sleep_quality_score","Sleep Score","higher_is_better"),
        ("whoop","sleep_efficiency_percentage","Sleep Efficiency","higher_is_better"),("garmin","avg_stress","Stress","lower_is_better"),
        ("garmin","body_battery_high","Body Battery","higher_is_better"),
    ]

    comparison = []
    for src, field, label, direction in COMPARE_METRICS:
        p_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in practice_dates]
        n_vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in non_practice_dates]
        p_avg, n_avg = _avg(p_vals), _avg(n_vals)
        if p_avg is not None and n_avg is not None:
            diff = round(p_avg - n_avg, 2)
            favorable = (diff > 0 and direction == "higher_is_better") or (diff < 0 and direction == "lower_is_better")
            comparison.append({"metric": label, "meditation_days": p_avg, "no_meditation_days": n_avg,
                               "diff": diff, "favorable": favorable,
                               "n_meditation": len([v for v in p_vals if v is not None]),
                               "n_control": len([v for v in n_vals if v is not None])})

    dose_response = {}
    for low, high, label in [(0,5,"0-5 min"),(5,10,"5-10 min"),(10,20,"10-20 min"),(20,999,"20+ min")]:
        bucket_dates = [d for d, m in daily_minutes.items() if low <= m < high]
        if not bucket_dates:
            continue
        bm = {}
        for src, field, ml, _ in COMPARE_METRICS:
            vals = [_sf(health_data.get(src,{}).get(d,{}).get(field)) for d in bucket_dates]
            a = _avg(vals)
            if a is not None:
                bm[ml] = a
        dose_response[label] = {"days": len(bucket_dates), "avg_minutes": _avg([daily_minutes[d] for d in bucket_dates]), "health_metrics": bm}

    correlations = []
    for src, field, label, _ in COMPARE_METRICS:
        xs, ys = [], []
        for d in practice_dates:
            hv = _sf(health_data.get(src,{}).get(d,{}).get(field))
            if hv is not None:
                xs.append(daily_minutes[d])
                ys.append(hv)
        if len(xs) >= 10:
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / n
            sx, sy = (sum((x-mx)**2 for x in xs)/n)**0.5, (sum((y-my)**2 for y in ys)/n)**0.5
            r = round(cov/(sx*sy), 3) if sx > 0 and sy > 0 else 0
            correlations.append({"metric": label, "r": r, "n": n})

    next_day = []
    for src, field, label, direction in COMPARE_METRICS[:4]:
        p_next, n_next = [], []
        for d in all_dates:
            nd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            hv = _sf(health_data.get(src,{}).get(nd,{}).get(field))
            if hv is not None:
                (p_next if d in daily_minutes else n_next).append(hv)
        pa, na = _avg(p_next), _avg(n_next)
        if pa is not None and na is not None:
            next_day.append({"metric": f"Next-day {label}", "after_meditation": pa, "after_no_meditation": na, "diff": round(pa-na, 2)})

    return {
        "start_date": start_date, "end_date": end_date,
        "summary": {"total_practice_days": practice_days, "total_days_in_range": total_days,
                     "adherence_pct": adherence_pct, "avg_minutes_per_session": _avg(list(daily_minutes.values())),
                     "total_minutes": round(sum(daily_minutes.values()), 1)},
        "streaks": {"current_streak": current_streak, "longest_streak": longest_streak},
        "meditation_vs_no_meditation": comparison, "dose_response": dose_response,
        "correlations": correlations, "next_day_effects": next_day,
        "coaching": {
            "huberman": "NSDR and physiological sigh are highest-ROI protocols. 5 min/day improves prefrontal cortex function within 8 weeks.",
            "attia": "Dose-response is logarithmic. Consistency > duration. Diminishing returns above ~20 min/day.",
            "walker": "Pre-sleep meditation (10-20 min) reduces sleep onset latency by ~50%.",
            "target": "Minimum effective dose: 5-13 min/day. Optimal: 10-20 min. 5+ days/week for HRV adaptation.",
        },
    }


def tool_log_travel(args):
    """
    Log a trip (start or end). Creates a new trip record or closes an active one.
    action: 'start' (default) or 'end'
    """
    action = args.get("action", "start").lower()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tbl = get_table()

    if action == "end":
        # Find the active trip and close it
        trip_id = args.get("trip_id", "")
        end_date = args.get("end_date", today)
        if trip_id:
            # Direct close by trip_id
            try:
                tbl.update_item(
                    Key={"pk": TRAVEL_PK, "sk": trip_id},
                    UpdateExpression="SET end_date = :ed, #st = :st, updated_at = :ua",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={
                        ":ed": end_date, ":st": "completed",
                        ":ua": datetime.utcnow().isoformat(),
                    },
                )
                return {"status": "trip_ended", "trip_id": trip_id, "end_date": end_date}
            except Exception as e:
                return {"error": f"Failed to end trip: {e}"}
        else:
            # Find the most recent active trip
            active = _is_traveling(today)
            if not active:
                return {"error": "No active trip found. Specify trip_id or start a new trip."}
            sk = f"TRIP#{active.get('slug', '')}_{active.get('start_date', '')}"
            try:
                tbl.update_item(
                    Key={"pk": TRAVEL_PK, "sk": sk},
                    UpdateExpression="SET end_date = :ed, #st = :st, updated_at = :ua",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={
                        ":ed": end_date, ":st": "completed",
                        ":ua": datetime.utcnow().isoformat(),
                    },
                )
                return {"status": "trip_ended", "trip_id": sk, "end_date": end_date,
                        "destination": active.get("destination_city")}
            except Exception as e:
                return {"error": f"Failed to end trip: {e}"}

    # ── Start a new trip ──
    dest_city = args.get("destination_city", "").strip()
    dest_country = args.get("destination_country", "").strip()
    dest_tz = args.get("destination_timezone", "").strip()
    start_date = args.get("start_date", today)
    purpose = args.get("purpose", "personal")  # personal, work, family, vacation
    notes = args.get("notes", "")

    if not dest_city:
        return {"error": "destination_city is required."}

    # Compute timezone offset
    dest_offset = _tz_offset(dest_tz) if dest_tz else None
    tz_diff = None
    direction = None
    if dest_offset is not None:
        tz_diff = dest_offset - HOME_OFFSET
        direction = "eastbound" if tz_diff > 0 else ("westbound" if tz_diff < 0 else "same_zone")

    # Generate slug
    slug = re.sub(r"[^a-z0-9]+", "_", dest_city.lower()).strip("_")
    sk = f"TRIP#{slug}_{start_date}"

    item = {
        "pk": TRAVEL_PK,
        "sk": sk,
        "slug": slug,
        "destination_city": dest_city,
        "destination_country": dest_country,
        "destination_timezone": dest_tz,
        "home_timezone": HOME_TZ,
        "tz_offset_hours": Decimal(str(tz_diff)) if tz_diff is not None else None,
        "direction": direction,
        "start_date": start_date,
        "end_date": None,
        "purpose": purpose,
        "status": "active",
        "notes": notes,
        "source": "travel",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    item = {k: v for k, v in item.items() if v is not None and v != ""}

    try:
        tbl.put_item(Item=item)
    except Exception as e:
        return {"error": f"Failed to log trip: {e}"}

    result = {
        "status": "trip_started", "trip_id": sk, "destination": dest_city,
        "start_date": start_date,
    }
    if tz_diff is not None:
        result["tz_offset_hours"] = float(tz_diff)
        result["direction"] = direction
        abs_diff = abs(tz_diff)
        # Huberman: ~1 day recovery per timezone crossed, eastbound harder
        est_recovery = round(abs_diff * (1.5 if direction == "eastbound" else 1.0))
        result["estimated_recovery_days"] = est_recovery
        result["jet_lag_protocol"] = {
            "huberman_rule": f"~1 day per TZ crossed ({abs_diff} zones = ~{est_recovery} days). Eastbound is harder.",
            "light_exposure": "Get bright light at destination morning time. Avoid evening light first 2-3 days.",
            "meal_timing": "Eat meals on destination schedule immediately. Fasting on travel day may help.",
            "melatonin": f"If eastbound, low-dose melatonin (0.5-1mg) at destination bedtime for first {min(est_recovery, 5)} nights.",
            "exercise": "Light exercise (walk, Zone 2) at destination morning to anchor circadian rhythm.",
        }
    return result


def tool_get_travel_log(args):
    """List all trips with optional status filter."""
    status_filter = (args.get("status") or "").lower()

    try:
        resp = get_table().query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": TRAVEL_PK, ":prefix": "TRIP#"},
        )
    except Exception as e:
        return {"error": f"Failed to query travel log: {e}"}

    trips = [_d2f(item) for item in resp.get("Items", [])]
    if status_filter:
        trips = [t for t in trips if t.get("status") == status_filter]

    trips.sort(key=lambda t: t.get("start_date", ""), reverse=True)

    # Check for currently active
    active = [t for t in trips if t.get("status") == "active"]

    summary = []
    for t in trips:
        entry = {
            "trip_id": t.get("sk"),
            "destination": f"{t.get('destination_city', '')}, {t.get('destination_country', '')}".strip(", "),
            "dates": f"{t.get('start_date', '?')} \u2192 {t.get('end_date', 'ongoing')}",
            "status": t.get("status"),
            "tz_offset_hours": t.get("tz_offset_hours"),
            "direction": t.get("direction"),
            "purpose": t.get("purpose"),
        }
        if t.get("end_date") and t.get("start_date"):
            try:
                d1 = datetime.strptime(t["start_date"], "%Y-%m-%d")
                d2 = datetime.strptime(t["end_date"], "%Y-%m-%d")
                entry["duration_days"] = (d2 - d1).days + 1
            except ValueError:
                pass
        summary.append(entry)

    return {
        "total_trips": len(trips),
        "currently_traveling": bool(active),
        "active_trip": {
            "destination": active[0].get("destination_city"),
            "since": active[0].get("start_date"),
            "tz_offset": active[0].get("tz_offset_hours"),
        } if active else None,
        "trips": summary,
    }


def tool_get_jet_lag_recovery(args):
    """
    Post-trip recovery analysis. Compares pre-trip baseline metrics to
    post-return recovery curve. Shows days-to-baseline for key metrics.
    """
    trip_id = args.get("trip_id", "")
    recovery_window_days = int(args.get("recovery_window_days", 14))

    # Find the trip
    if trip_id:
        try:
            resp = get_table().get_item(Key={"pk": TRAVEL_PK, "sk": trip_id})
            trip = _d2f(resp.get("Item") or {})
        except Exception:
            trip = {}
    else:
        # Find most recent completed trip
        try:
            resp = get_table().query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={":pk": TRAVEL_PK, ":prefix": "TRIP#"},
            )
            trips = [_d2f(i) for i in resp.get("Items", [])]
            completed = [t for t in trips if t.get("status") == "completed"]
            completed.sort(key=lambda t: t.get("end_date", ""), reverse=True)
            trip = completed[0] if completed else {}
        except Exception:
            trip = {}

    if not trip or not trip.get("end_date"):
        return {"error": "No completed trip found. End an active trip first with log_travel action='end'."}

    start_date = trip.get("start_date", "")
    end_date = trip.get("end_date", "")
    tz_diff = trip.get("tz_offset_hours", 0)

    # Pre-trip baseline: 7 days before departure
    pre_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    pre_end = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    # Post-return recovery window
    post_start = end_date
    post_end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=recovery_window_days)).strftime("%Y-%m-%d")

    # Metrics to track recovery
    recovery_metrics = [
        ("whoop", "recovery_score", "Recovery Score", True),
        ("whoop", "hrv", "HRV", True),
        ("whoop", "resting_heart_rate", "Resting HR", False),
        ("whoop", "sleep_quality_score", "Sleep Score", True),
        ("whoop", "sleep_efficiency_percentage", "Sleep Efficiency", True),
        ("garmin", "body_battery_high", "Body Battery", True),
        ("garmin", "avg_stress", "Stress", False),
        ("apple_health", "steps", "Steps", True),
    ]

    results = {}
    for source, field, label, higher_is_better in recovery_metrics:
        # Pre-trip baseline
        pre_items = query_source(source, pre_start, pre_end)
        pre_vals = [float(i[field]) for i in pre_items if i.get(field) is not None]
        if not pre_vals:
            continue
        baseline = sum(pre_vals) / len(pre_vals)

        # Post-return daily values
        post_items = query_source(source, post_start, post_end)
        daily = []
        days_to_baseline = None
        for item in sorted(post_items, key=lambda x: x.get("date", "")):
            val = item.get(field)
            if val is None:
                continue
            val = float(val)
            day_num = (datetime.strptime(item.get("date", post_start), "%Y-%m-%d") -
                       datetime.strptime(end_date, "%Y-%m-%d")).days
            daily.append({"day": day_num, "value": round(val, 1)})

            # Check if recovered to baseline
            if days_to_baseline is None:
                if higher_is_better and val >= baseline * 0.95:
                    days_to_baseline = day_num
                elif not higher_is_better and val <= baseline * 1.05:
                    days_to_baseline = day_num

        if daily:
            post_avg = sum(d["value"] for d in daily) / len(daily)
            pct_change = round((post_avg - baseline) / baseline * 100, 1) if baseline else 0
            results[label] = {
                "pre_trip_baseline": round(baseline, 1),
                "post_return_avg": round(post_avg, 1),
                "pct_change": pct_change,
                "days_to_baseline": days_to_baseline,
                "recovered": days_to_baseline is not None,
                "daily_recovery_curve": daily[:recovery_window_days],
            }

    # Summary
    recovered_metrics = [k for k, v in results.items() if v.get("recovered")]
    not_recovered = [k for k, v in results.items() if not v.get("recovered")]
    avg_recovery_days = None
    recovery_days_list = [v["days_to_baseline"] for v in results.values() if v.get("days_to_baseline") is not None]
    if recovery_days_list:
        avg_recovery_days = round(sum(recovery_days_list) / len(recovery_days_list), 1)

    return {
        "trip": {
            "destination": trip.get("destination_city"),
            "dates": f"{start_date} \u2192 {end_date}",
            "tz_offset_hours": tz_diff,
            "direction": trip.get("direction"),
        },
        "analysis_window": {"pre_trip": f"{pre_start} \u2192 {pre_end}", "post_return": f"{post_start} \u2192 {post_end}"},
        "metrics": results,
        "summary": {
            "metrics_tracked": len(results),
            "recovered": len(recovered_metrics),
            "not_yet_recovered": len(not_recovered),
            "avg_days_to_baseline": avg_recovery_days,
            "recovered_metrics": recovered_metrics,
            "still_recovering": not_recovered,
        },
        "coaching": {
            "huberman": f"Jet lag recovery: ~1 day per timezone crossed ({abs(tz_diff or 0)} zones). "
                        f"{'Eastbound travel is harder — your body prefers to delay, not advance.' if (tz_diff or 0) > 0 else 'Westbound is easier — staying up later is natural.'}",
            "attia": "Monitor HRV as the primary recovery signal. Training intensity should match recovery — keep it Zone 2 until HRV returns to baseline.",
            "walker": "Avoid sleeping pills; they suppress REM. Melatonin (0.5-1mg) at destination bedtime for the first few nights only.",
        },
    }


def tool_get_state_of_mind_trend(args):
    """State of Mind valence trend from How We Feel / Apple Health."""
    today = datetime.now().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)

    # ── Load daily aggregates from DynamoDB ──
    days_data = []
    current = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while current <= end_dt:
        ds = current.strftime("%Y-%m-%d")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + "apple_health", "sk": f"DATE#{ds}"})
            item = resp.get("Item", {})
            valence = item.get("som_avg_valence")
            if valence is not None:
                days_data.append({
                    "date": ds,
                    "avg_valence": float(valence),
                    "min_valence": float(item.get("som_min_valence", valence)),
                    "max_valence": float(item.get("som_max_valence", valence)),
                    "check_in_count": int(item.get("som_check_in_count", 0)),
                    "mood_count": int(item.get("som_mood_count", 0)),
                    "emotion_count": int(item.get("som_emotion_count", 0)),
                    "top_labels": item.get("som_top_labels", ""),
                    "top_associations": item.get("som_top_associations", ""),
                })
        except Exception:
            pass
        current += timedelta(days=1)

    if not days_data:
        return {
            "status": "no_data",
            "message": (
                "No State of Mind data found. To start collecting:\n"
                "1. Use How We Feel (or Apple Health State of Mind) to log moods\n"
                "2. In Health Auto Export app, create a NEW REST API automation:\n"
                "   - Data Type: 'State of Mind' (not Health Metrics)\n"
                "   - URL: same Lambda Function URL as your existing automation\n"
                "   - Headers: same Authorization Bearer token\n"
                "   - Export Format: JSON, Version 2\n"
                "   - Date Range: 'Since Last Sync'\n"
                "3. Check-ins will flow: How We Feel \u2192 HealthKit \u2192 HAE \u2192 Lambda \u2192 DynamoDB + S3"
            ),
            "period": {"start": start, "end": end},
        }

    # ── Load individual entries from S3 for label/association deep analysis ──
    all_labels = []
    all_associations = []
    all_entries = []
    for d in days_data:
        ds = d["date"]
        try:
            y, m, day = ds.split("-")
            key = f"raw/state_of_mind/{y}/{m}/{day}.json"
            resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            entries = json.loads(resp["Body"].read())
            for e in entries:
                all_entries.append(e)
                all_labels.extend(e.get("labels", []))
                all_associations.extend(e.get("associations", []))
        except Exception:
            pass

    # ── Valence statistics ──
    valences = [d["avg_valence"] for d in days_data]
    overall_avg = sum(valences) / len(valences)
    total_check_ins = sum(d["check_in_count"] for d in days_data)

    # 7-day rolling average for recent trend
    recent_7 = [d for d in days_data if d["date"] >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
    recent_avg = sum(d["avg_valence"] for d in recent_7) / len(recent_7) if recent_7 else None

    # Trend direction (first half vs second half)
    mid = len(valences) // 2
    if mid > 0:
        first_half = sum(valences[:mid]) / mid
        second_half = sum(valences[mid:]) / len(valences[mid:])
        delta = second_half - first_half
        if delta > 0.1:
            trend_direction = "improving"
        elif delta < -0.1:
            trend_direction = "declining"
        else:
            trend_direction = "stable"
    else:
        trend_direction = "insufficient_data"
        delta = 0

    # ── Label frequency analysis ──
    from collections import Counter
    label_freq = Counter(all_labels).most_common(10)
    assoc_freq = Counter(all_associations).most_common(10)

    # ── Valence by association (which life areas drive best/worst mood) ──
    assoc_valences = {}
    for e in all_entries:
        v = e.get("valence")
        if v is None:
            continue
        for a in e.get("associations", []):
            if a not in assoc_valences:
                assoc_valences[a] = []
            assoc_valences[a].append(float(v))

    assoc_avg = {}
    for a, vals in assoc_valences.items():
        if len(vals) >= 2:
            assoc_avg[a] = {"avg_valence": round(sum(vals) / len(vals), 3), "count": len(vals)}
    assoc_sorted = sorted(assoc_avg.items(), key=lambda x: -x[1]["avg_valence"])

    # ── Valence classification distribution ──
    class_counts = Counter()
    for e in all_entries:
        vc = e.get("valence_classification", "unknown")
        class_counts[vc] += 1
    class_dist = dict(class_counts.most_common())

    # ── Time-of-day analysis ──
    time_buckets = {"morning": [], "afternoon": [], "evening": [], "night": []}
    for e in all_entries:
        t = e.get("time", "")
        v = e.get("valence")
        if not t or v is None:
            continue
        try:
            parts = str(t).split(" ")
            hour = int(parts[1].split(":")[0]) if len(parts) > 1 else None
            if hour is not None:
                if 5 <= hour < 12:
                    time_buckets["morning"].append(float(v))
                elif 12 <= hour < 17:
                    time_buckets["afternoon"].append(float(v))
                elif 17 <= hour < 21:
                    time_buckets["evening"].append(float(v))
                else:
                    time_buckets["night"].append(float(v))
        except (IndexError, ValueError):
            pass

    time_of_day = {}
    for bucket, vals in time_buckets.items():
        if vals:
            time_of_day[bucket] = {"avg_valence": round(sum(vals) / len(vals), 3), "count": len(vals)}

    # ── Valence interpretation ──
    def interpret_valence(v):
        if v >= 0.67:
            return "very pleasant"
        elif v >= 0.33:
            return "pleasant"
        elif v >= 0.05:
            return "slightly pleasant"
        elif v >= -0.05:
            return "neutral"
        elif v >= -0.33:
            return "slightly unpleasant"
        elif v >= -0.67:
            return "unpleasant"
        else:
            return "very unpleasant"

    # ── Best / worst days ──
    sorted_days = sorted(days_data, key=lambda d: d["avg_valence"])
    worst_3 = sorted_days[:3] if len(sorted_days) >= 3 else sorted_days
    best_3 = sorted_days[-3:][::-1] if len(sorted_days) >= 3 else sorted_days[::-1]

    return {
        "period": {"start": start, "end": end},
        "summary": {
            "days_with_data": len(days_data),
            "total_check_ins": total_check_ins,
            "avg_check_ins_per_day": round(total_check_ins / len(days_data), 1),
            "overall_avg_valence": round(overall_avg, 3),
            "overall_interpretation": interpret_valence(overall_avg),
            "recent_7day_avg": round(recent_avg, 3) if recent_avg is not None else None,
            "recent_interpretation": interpret_valence(recent_avg) if recent_avg is not None else None,
            "trend_direction": trend_direction,
            "trend_delta": round(delta, 3),
        },
        "valence_distribution": class_dist,
        "top_emotion_labels": [{"label": l, "count": c} for l, c in label_freq],
        "top_life_associations": [{"association": a, "count": c} for a, c in assoc_freq],
        "valence_by_association": [
            {"association": a, **v} for a, v in assoc_sorted
        ],
        "time_of_day_pattern": time_of_day,
        "best_days": [{"date": d["date"], "valence": d["avg_valence"], "labels": d["top_labels"]} for d in best_3],
        "worst_days": [{"date": d["date"], "valence": d["avg_valence"], "labels": d["top_labels"]} for d in worst_3],
        "daily_detail": [
            {
                "date": d["date"],
                "avg_valence": d["avg_valence"],
                "check_ins": d["check_in_count"],
                "labels": d["top_labels"],
                "associations": d["top_associations"],
            }
            for d in days_data[-30:]  # Last 30 days detail
        ],
    }


def tool_get_blood_pressure_dashboard(args):
    """
    Blood pressure dashboard. Current status, AHA classification, trend,
    morning vs evening patterns, variability analysis.

    AHA categories:
      Normal:    <120 / <80
      Elevated:  120-129 / <80
      Stage 1:   130-139 / 80-89
      Stage 2:   >=140 / >=90
      Crisis:    >180 / >120
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": "No Apple Health data for range.", "start_date": start_date, "end_date": end_date}

    # Collect days with BP data
    bp_days = []
    for item in items:
        sys_val = item.get("blood_pressure_systolic")
        dia_val = item.get("blood_pressure_diastolic")
        if sys_val is None or dia_val is None:
            continue
        bp_days.append({
            "date": item.get("date", ""),
            "systolic": float(sys_val),
            "diastolic": float(dia_val),
            "pulse": float(item["blood_pressure_pulse"]) if item.get("blood_pressure_pulse") is not None else None,
            "readings_count": int(item.get("blood_pressure_readings_count", 1)),
        })

    if not bp_days:
        return {
            "status": "no_data",
            "message": "No blood pressure readings found in the date range. Ensure BP cuff syncs to Apple Health.",
            "start_date": start_date, "end_date": end_date,
        }

    bp_days.sort(key=lambda x: x["date"])

    # AHA classification
    def classify_bp(sys, dia):
        if sys > 180 or dia > 120:
            return "crisis"
        if sys >= 140 or dia >= 90:
            return "stage_2_hypertension"
        if 130 <= sys <= 139 or 80 <= dia <= 89:
            return "stage_1_hypertension"
        if 120 <= sys <= 129 and dia < 80:
            return "elevated"
        return "normal"

    # Current (latest reading)
    latest = bp_days[-1]
    latest_class = classify_bp(latest["systolic"], latest["diastolic"])

    # Averages
    sys_vals = [d["systolic"] for d in bp_days]
    dia_vals = [d["diastolic"] for d in bp_days]
    pulse_vals = [d["pulse"] for d in bp_days if d["pulse"] is not None]
    avg_sys = round(sum(sys_vals) / len(sys_vals), 1)
    avg_dia = round(sum(dia_vals) / len(dia_vals), 1)
    avg_class = classify_bp(avg_sys, avg_dia)

    # Variability (SD)
    import math as _math
    sys_sd = round(_math.sqrt(sum((v - avg_sys)**2 for v in sys_vals) / len(sys_vals)), 1) if len(sys_vals) > 1 else 0
    dia_sd = round(_math.sqrt(sum((v - avg_dia)**2 for v in dia_vals) / len(dia_vals)), 1) if len(dia_vals) > 1 else 0

    # Trend (first half vs second half)
    mid = len(bp_days) // 2
    if mid > 0:
        first_half_sys = sum(d["systolic"] for d in bp_days[:mid]) / mid
        second_half_sys = sum(d["systolic"] for d in bp_days[mid:]) / len(bp_days[mid:])
        trend_sys = round(second_half_sys - first_half_sys, 1)
        trend_dir = "rising" if trend_sys > 2 else ("falling" if trend_sys < -2 else "stable")
    else:
        trend_sys = 0
        trend_dir = "insufficient_data"

    # Morning vs Evening analysis (from S3 individual readings)
    morning_sys, morning_dia = [], []
    evening_sys, evening_dia = [], []
    total_readings = 0
    for day in bp_days:
        readings = _load_bp_readings(day["date"])
        for r in readings:
            total_readings += 1
            time_str = r.get("time", "")
            try:
                hour = int(time_str.split(" ")[1].split(":")[0])
            except (IndexError, ValueError):
                continue
            s, d = r.get("systolic"), r.get("diastolic")
            if s is None or d is None:
                continue
            if 5 <= hour < 12:
                morning_sys.append(float(s))
                morning_dia.append(float(d))
            elif hour >= 18:
                evening_sys.append(float(s))
                evening_dia.append(float(d))

    time_of_day = None
    if morning_sys and evening_sys:
        time_of_day = {
            "morning_avg": {"systolic": round(sum(morning_sys)/len(morning_sys), 1),
                           "diastolic": round(sum(morning_dia)/len(morning_dia), 1),
                           "readings": len(morning_sys)},
            "evening_avg": {"systolic": round(sum(evening_sys)/len(evening_sys), 1),
                           "diastolic": round(sum(evening_dia)/len(evening_dia), 1),
                           "readings": len(evening_sys)},
            "note": "Morning BP is typically higher (cortisol awakening response). " +
                    ("Your pattern matches." if sum(morning_sys)/len(morning_sys) > sum(evening_sys)/len(evening_sys)
                     else "Your evening is higher than morning — consider stress/sodium timing."),
        }

    # Classification distribution
    class_dist = {}
    for d in bp_days:
        c = classify_bp(d["systolic"], d["diastolic"])
        class_dist[c] = class_dist.get(c, 0) + 1

    # Coaching
    coaching = {}
    if avg_sys >= 130 or avg_dia >= 85:
        coaching["attia"] = "Sustained BP above 130/85 accelerates arterial aging. Sodium restriction (<2000mg), regular Zone 2, and sleep optimization are first-line interventions."
    if sys_sd > 12:
        coaching["huberman"] = f"High systolic variability (SD={sys_sd}). Consider consistent measurement timing, limiting caffeine before readings, and 5 min seated rest pre-measurement."
    if avg_class == "normal":
        coaching["summary"] = "Blood pressure is well-controlled. Continue current lifestyle factors."
    else:
        coaching["summary"] = f"Average classification: {avg_class.replace('_', ' ').title()}. Track trends and discuss with your physician if sustained."

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_bp": len(bp_days), "total_readings": total_readings},
        "current": {
            "date": latest["date"],
            "systolic": latest["systolic"], "diastolic": latest["diastolic"],
            "pulse": latest.get("pulse"),
            "classification": latest_class,
        },
        "averages": {
            "systolic": avg_sys, "diastolic": avg_dia,
            "pulse": round(sum(pulse_vals)/len(pulse_vals), 1) if pulse_vals else None,
            "classification": avg_class,
        },
        "variability": {"systolic_sd": sys_sd, "diastolic_sd": dia_sd,
                        "note": "SD >12 mmHg systolic suggests high visit-to-visit variability (independent CV risk factor)"},
        "trend": {"systolic_delta": trend_sys, "direction": trend_dir},
        "time_of_day": time_of_day,
        "classification_distribution": class_dist,
        "daily_readings": [{"date": d["date"], "systolic": d["systolic"], "diastolic": d["diastolic"],
                            "pulse": d.get("pulse"), "class": classify_bp(d["systolic"], d["diastolic"])}
                           for d in bp_days],
        "coaching": coaching,
        # R13-F09: Medical disclaimer on all health-assessment tool responses
        "_disclaimer": "For personal health tracking only. Not medical advice. Consult a qualified healthcare provider before making health decisions based on this data.",
    }


def tool_get_blood_pressure_correlation(args):
    """
    Correlate blood pressure with lifestyle factors: sodium, training load, stress,
    sleep quality, caffeine, weight. Pearson r + bucketed comparisons.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))

    ah_items = query_source("apple_health", start_date, end_date)
    mf_items = query_source("macrofactor",  start_date, end_date)
    wh_items = query_source("whoop",        start_date, end_date)
    wi_items = query_source("withings",     start_date, end_date)
    ga_items = query_source("garmin",       start_date, end_date)
    st_items = query_source("strava",       start_date, end_date)

    # Build date-indexed lookups
    def by_date(items):
        out = {}
        for i in items:
            d = i.get("date")
            if d:
                out[d] = i
        return out

    bp_by_date = {}
    for item in ah_items:
        s = item.get("blood_pressure_systolic")
        d = item.get("blood_pressure_diastolic")
        if s is not None and d is not None:
            bp_by_date[item.get("date", "")] = {"systolic": float(s), "diastolic": float(d)}

    if len(bp_by_date) < 5:
        return {"error": f"Need at least 5 days with BP data, found {len(bp_by_date)}.",
                "start_date": start_date, "end_date": end_date}

    mf_map = by_date(mf_items)
    wh_map = by_date(wh_items)
    wi_map = by_date(wi_items)
    ga_map = by_date(ga_items)
    st_map = by_date(st_items)

    # Correlate BP with various factors
    correlations = []
    ah_map = by_date(ah_items)

    factor_pairs = [
        ("Sodium (mg)",        mf_map, "total_sodium_mg"),
        ("Calories",           mf_map, "total_calories_kcal"),
        ("Caffeine (mg)",      ah_map, "caffeine_mg"),
        ("Sleep Efficiency %", wh_map, "sleep_efficiency_percentage"),
        ("Sleep Score",        wh_map, "sleep_quality_score"),
        ("Recovery Score",     wh_map, "recovery_score"),
        ("HRV",               wh_map, "hrv"),
        ("Garmin Stress",      ga_map, "avg_stress"),
        ("Weight (lbs)",       wi_map, "weight_lbs"),
        ("Steps",              ah_map, "steps"),
        ("Training Load",      st_map, "total_kilojoules"),
    ]

    for factor_name, source_map, field in factor_pairs:
        sys_xs, sys_ys, dia_xs, dia_ys = [], [], [], []
        for date, bp in bp_by_date.items():
            src = source_map.get(date, {})
            val = src.get(field)
            if val is not None:
                try:
                    v = float(val)
                    sys_xs.append(v)
                    sys_ys.append(bp["systolic"])
                    dia_xs.append(v)
                    dia_ys.append(bp["diastolic"])
                except (ValueError, TypeError):
                    pass

        if len(sys_xs) >= 5:
            r_sys = pearson_r(sys_xs, sys_ys)
            r_dia = pearson_r(dia_xs, dia_ys)
            correlations.append({
                "factor": factor_name,
                "n_days": len(sys_xs),
                "systolic_r": round(r_sys, 3) if r_sys is not None else None,
                "diastolic_r": round(r_dia, 3) if r_dia is not None else None,
                "strength": "strong" if r_sys is not None and abs(r_sys) >= 0.4 else
                           ("moderate" if r_sys is not None and abs(r_sys) >= 0.2 else "weak"),
            })

    # Sort by absolute systolic correlation strength
    correlations.sort(key=lambda c: abs(c.get("systolic_r") or 0), reverse=True)

    # Exercise day vs rest day comparison
    exercise_bp, rest_bp = [], []
    for date, bp in bp_by_date.items():
        st = st_map.get(date, {})
        if st.get("activity_count") and int(st["activity_count"]) > 0:
            exercise_bp.append(bp)
        else:
            rest_bp.append(bp)

    exercise_vs_rest = None
    if exercise_bp and rest_bp:
        exercise_vs_rest = {
            "exercise_days": {
                "n": len(exercise_bp),
                "avg_systolic": round(sum(b["systolic"] for b in exercise_bp) / len(exercise_bp), 1),
                "avg_diastolic": round(sum(b["diastolic"] for b in exercise_bp) / len(exercise_bp), 1),
            },
            "rest_days": {
                "n": len(rest_bp),
                "avg_systolic": round(sum(b["systolic"] for b in rest_bp) / len(rest_bp), 1),
                "avg_diastolic": round(sum(b["diastolic"] for b in rest_bp) / len(rest_bp), 1),
            },
        }

    # Sodium bucketing (if enough data)
    sodium_buckets = None
    sodium_bp = []
    for date, bp in bp_by_date.items():
        mf = mf_map.get(date, {})
        na = mf.get("total_sodium_mg")
        if na is not None:
            sodium_bp.append({"sodium": float(na), **bp})

    if len(sodium_bp) >= 10:
        sodium_bp.sort(key=lambda x: x["sodium"])
        low_cut = len(sodium_bp) // 3
        high_cut = 2 * len(sodium_bp) // 3
        low = sodium_bp[:low_cut]
        mid = sodium_bp[low_cut:high_cut]
        high = sodium_bp[high_cut:]
        sodium_buckets = {
            "low_sodium": {
                "range": f"<{int(low[-1]['sodium'])} mg" if low else "",
                "n": len(low),
                "avg_systolic": round(sum(x["systolic"] for x in low) / len(low), 1) if low else None,
                "avg_diastolic": round(sum(x["diastolic"] for x in low) / len(low), 1) if low else None,
            },
            "mid_sodium": {
                "range": f"{int(mid[0]['sodium'])}-{int(mid[-1]['sodium'])} mg" if mid else "",
                "n": len(mid),
                "avg_systolic": round(sum(x["systolic"] for x in mid) / len(mid), 1) if mid else None,
                "avg_diastolic": round(sum(x["diastolic"] for x in mid) / len(mid), 1) if mid else None,
            },
            "high_sodium": {
                "range": f">{int(high[0]['sodium'])} mg" if high else "",
                "n": len(high),
                "avg_systolic": round(sum(x["systolic"] for x in high) / len(high), 1) if high else None,
                "avg_diastolic": round(sum(x["diastolic"] for x in high) / len(high), 1) if high else None,
            },
        }

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_bp": len(bp_by_date)},
        "correlations": correlations,
        "exercise_vs_rest": exercise_vs_rest,
        "sodium_dose_response": sodium_buckets,
        "coaching": {
            "attia": "Sodium is the strongest modifiable BP lever. Track your personal dose-response — some people are salt-sensitive (RAAS genetics), others are not.",
            "huberman": "Consistent Zone 2 cardio (150 min/week) is the most evidence-backed BP intervention after sodium. Acute post-exercise hypotension lasts 12-24 hours.",
            "walker": "Poor sleep quality (especially <85% efficiency) reliably raises next-day BP by 5-10 mmHg via sympathetic overdrive.",
        },
        # R13-F09: Medical disclaimer on all health-assessment tool responses
        "_disclaimer": "For personal health tracking only. Not medical advice. Consult a qualified healthcare provider before making health decisions based on this data.",
    }


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
        "note": "TDEE from Apple Watch (active + basal) is more accurate than formula-based BMR. 500 kcal/day deficit \u2248 1 lb/week loss.",
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


def tool_create_experiment(args):
    """Create a new N=1 experiment.

    Tracks a specific protocol change (supplement, diet, sleep hygiene, training
    adjustment, etc.) with start date and metrics to monitor. The system will
    automatically compare the experiment period against the equivalent pre-period
    when you call get_experiment_results.

    Board of Directors rules:
      - One variable at a time (Huberman)
      - Minimum 14 days for meaningful signal (Attia)
      - Define success criteria upfront (Ferriss)
    """
    name       = (args.get("name") or "").strip()
    hypothesis = (args.get("hypothesis") or "").strip()
    start_date = (args.get("start_date") or "").strip()
    tags       = args.get("tags") or []
    notes      = (args.get("notes") or "").strip()

    if not name:
        raise ValueError("name is required (e.g. 'Creatine 5g daily', 'No caffeine after 10am')")
    if not hypothesis:
        raise ValueError("hypothesis is required (e.g. 'Will improve deep sleep % by >5%')")

    now = datetime.utcnow()
    if not start_date:
        start_date = now.strftime("%Y-%m-%d")

    # Generate a slug-style ID
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    exp_id = f"{slug}_{start_date}"
    sk = f"EXP#{exp_id}"

    # Check for duplicate
    existing = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if existing:
        raise ValueError(f"Experiment '{exp_id}' already exists. Choose a different name or start date.")

    item = {
        "pk":           EXPERIMENTS_PK,
        "sk":           sk,
        "experiment_id": exp_id,
        "name":         name,
        "hypothesis":   hypothesis,
        "start_date":   start_date,
        "end_date":     None,       # null = still active
        "status":       "active",   # active, completed, abandoned
        "tags":         tags,
        "notes":        notes,
        "outcome":      "",
        "created_at":   now.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Clean None values for DynamoDB
    clean_item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=clean_item)
    logger.info(f"create_experiment: created {exp_id}")

    return {
        "created":       True,
        "experiment_id": exp_id,
        "name":          name,
        "hypothesis":    hypothesis,
        "start_date":    start_date,
        "status":        "active",
        "tags":          tags,
        "board_of_directors": {
            "Huberman": "One variable at a time. Track for at least 2 weeks before drawing conclusions. Control for confounders: sleep timing, stress, travel.",
            "Attia":    "Define your primary endpoint now. What number would convince you this worked? Statistical noise requires \u226514 days of data.",
            "Ferriss":  "What does the minimum effective dose look like? Start with the smallest intervention that could produce a measurable change.",
        },
    }


def tool_list_experiments(args):
    """List all N=1 experiments with status and duration.

    Filter by status: active, completed, abandoned, or all.
    Shows days active, whether minimum duration (14d) has been met.
    """
    status_filter = args.get("status")  # None = all
    today = datetime.utcnow().strftime("%Y-%m-%d")

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"),
        ScanIndexForward=False,
    )
    items = resp.get("Items", [])

    results = []
    for item in items:
        status = item.get("status", "active")
        if status_filter and status != status_filter:
            continue

        start = item.get("start_date", "")
        end = item.get("end_date", today)
        try:
            days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
        except Exception:
            days = None

        results.append({
            "experiment_id": item.get("experiment_id", ""),
            "name":          item.get("name", ""),
            "hypothesis":    item.get("hypothesis", ""),
            "start_date":    start,
            "end_date":      item.get("end_date"),
            "status":        status,
            "days_active":   days,
            "min_duration_met": days is not None and days >= 14,
            "tags":          item.get("tags", []),
            "notes":         item.get("notes", ""),
            "outcome":       item.get("outcome", ""),
        })

    active = sum(1 for r in results if r["status"] == "active")
    completed = sum(1 for r in results if r["status"] == "completed")

    return {
        "total":     len(results),
        "active":    active,
        "completed": completed,
        "filter":    status_filter or "all",
        "experiments": results,
    }


# \u2500\u2500 Cohen's d effect size helper (IC-19 Deliverable 3C \u2014 Henning/Yael/Norton) \u2500\u2500
def _cohens_d(before_vals, during_vals):
    """Compute Cohen's d effect size using pooled SD.

    Formula (Board spec):
        pooled_sd = sqrt((sd_before\u00b2 + sd_during\u00b2) / 2)
        cohens_d  = (mean_during - mean_before) / pooled_sd

    Returns None if pooled_sd == 0 or either list has fewer than 2 values.
    Never binned into small/medium/large labels (Henning: N=1 binning is misleading).
    Yael: None propagates cleanly \u2014 verify JSON serialisation handles it (returns None).

    Pure function, _ prefix convention. (Elena)
    """
    if len(before_vals) < 2 or len(during_vals) < 2:
        return None
    mean_b = sum(before_vals) / len(before_vals)
    mean_d = sum(during_vals) / len(during_vals)
    var_b  = sum((x - mean_b) ** 2 for x in before_vals) / (len(before_vals) - 1)
    var_d  = sum((x - mean_d) ** 2 for x in during_vals) / (len(during_vals) - 1)
    pooled_sd = math.sqrt((var_b + var_d) / 2)
    if pooled_sd == 0:
        return None  # Yael: None propagates through JSON as null, not an error
    return (mean_d - mean_b) / pooled_sd


def tool_get_experiment_results(args):
    """Auto-compare before vs during metrics for an experiment.

    Computes the mean of key health metrics for:
      - BEFORE period: same number of days immediately before the experiment start
      - DURING period: experiment start to end (or today if still active)

    Reports: metric name, before mean, during mean, delta, % change, direction.

    Board of Directors evaluates the results with context from the hypothesis.
    """
    exp_id = (args.get("experiment_id") or "").strip()
    if not exp_id:
        raise ValueError("experiment_id is required")

    sk = f"EXP#{exp_id}"
    item = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if not item:
        raise ValueError(f"No experiment found with id={exp_id}")

    start_date = item.get("start_date", "")
    end_date = item.get("end_date") or datetime.utcnow().strftime("%Y-%m-%d")
    status = item.get("status", "active")
    hypothesis = item.get("hypothesis", "")

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid start_date or end_date on experiment")

    during_days = (end_dt - start_dt).days
    if during_days < 1:
        return {"error": "Experiment has less than 1 day of data. Check back later."}

    # Before period = same number of days before start
    before_start = (start_dt - timedelta(days=during_days)).strftime("%Y-%m-%d")
    before_end = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    during_start = start_date
    during_end = end_date

    # Gather unique sources needed
    sources_needed = list(set(m[0] for m in _EXPERIMENT_METRICS))

    # Query before + during in parallel
    before_data = {}
    during_data = {}
    for src in sources_needed:
        try:
            before_items = query_source(src, before_start, before_end)
            during_items = query_source(src, during_start, during_end)
            before_data[src] = before_items
            during_data[src] = during_items
        except Exception as e:
            logger.warning(f"get_experiment_results: failed to query {src}: {e}")

    # Normalize Whoop sleep fields so aliases (sleep_score, deep_pct, etc.) exist
    if "whoop" in before_data:
        before_data["whoop"] = [normalize_whoop_sleep(i) for i in before_data["whoop"]]
    if "whoop" in during_data:
        during_data["whoop"] = [normalize_whoop_sleep(i) for i in during_data["whoop"]]

    # Compute metric comparisons
    comparisons = []
    for source, field, display_name, higher_is_better in _EXPERIMENT_METRICS:
        before_vals = []
        during_vals = []

        for item_b in before_data.get(source, []):
            v = _extract_metric(item_b, field)
            if v is not None:
                before_vals.append(v)

        for item_d in during_data.get(source, []):
            v = _extract_metric(item_d, field)
            if v is not None:
                during_vals.append(v)

        # Need at least 3 data points in each period for meaningful comparison
        if len(before_vals) < 3 or len(during_vals) < 3:
            continue

        before_mean = sum(before_vals) / len(before_vals)
        during_mean = sum(during_vals) / len(during_vals)
        delta = during_mean - before_mean
        pct_change = (delta / before_mean * 100) if before_mean != 0 else None

        # Determine if change is favorable
        if higher_is_better is True:
            direction = "improved" if delta > 0 else ("worsened" if delta < 0 else "unchanged")
        elif higher_is_better is False:
            direction = "improved" if delta < 0 else ("worsened" if delta > 0 else "unchanged")
        else:
            direction = "increased" if delta > 0 else ("decreased" if delta < 0 else "unchanged")

        # Effect size: Cohen's d with honest uncertainty label (Henning/Norton \u2014 never binned)
        d_val = _cohens_d(before_vals, during_vals)
        if d_val is not None:
            effect_size = {
                "cohens_d": round(d_val, 3),
                "interpretation": (
                    f"d={d_val:.2f} \u2014 treat as directional only at N={len(during_vals)}; "
                    f"95% CI approximately \u00b1{round(1.96 / math.sqrt(len(during_vals) / 2), 2)}"
                ),
            }
        else:
            effect_size = None  # Yael: None \u2192 JSON null, not an error

        # Consistency score: % of during-period days above before-period mean (Henning: non-parametric)
        consistency_score = (
            round(sum(1 for v in during_vals if v > before_mean) / len(during_vals) * 100, 1)
            if during_vals else None
        )

        comparisons.append({
            "metric":             display_name,
            "source":             source,
            "before_mean":        round(before_mean, 2),
            "during_mean":        round(during_mean, 2),
            "delta":              round(delta, 2),
            "pct_change":         round(pct_change, 1) if pct_change is not None else None,
            "direction":          direction,
            "before_n":           len(before_vals),
            "during_n":           len(during_vals),
            "effect_size":        effect_size,
            "consistency_score":  consistency_score,
        })

    # Sort: improved first, then worsened, then unchanged
    order = {"improved": 0, "worsened": 1, "increased": 2, "decreased": 3, "unchanged": 4}
    comparisons.sort(key=lambda c: order.get(c["direction"], 5))

    improved = [c for c in comparisons if c["direction"] == "improved"]
    worsened = [c for c in comparisons if c["direction"] == "worsened"]

    # Minimum duration warning + domain-specific guidance (Norton: nutrition/supplement
    # experiments have ~5-7 days of adaptation noise before signal emerges in days 8-14+)
    category = (item.get("category") or "").lower()
    min_duration_met = during_days >= 14
    duration_warning = None
    if not min_duration_met:
        if "supplement" in category or "nutrition" in category or "macro" in category:
            duration_warning = (
                f"Only {during_days} days of data. For nutrition/supplement experiments, "
                f"the first 5-7 days are often adaptation noise \u2014 the signal typically "
                f"emerges in days 8-14+. Minimum 14 days recommended before drawing conclusions."
            )
        else:
            duration_warning = (
                f"Only {during_days} days of data. Board recommends minimum 14 days "
                f"for reliable signal. Results may be noise."
            )

    return {
        "experiment": {
            "id":         exp_id,
            "name":       item.get("name", ""),
            "hypothesis": hypothesis,
            "status":     status,
            "start_date": start_date,
            "end_date":   end_date if status != "active" else f"{end_date} (ongoing)",
        },
        "comparison_period": {
            "before": f"{before_start} \u2192 {before_end} ({during_days} days)",
            "during": f"{during_start} \u2192 {during_end} ({during_days} days)",
        },
        "duration_warning":  duration_warning,
        "metrics_compared":  len(comparisons),
        "improved_count":    len(improved),
        "worsened_count":    len(worsened),
        "comparisons":       comparisons,
        "board_of_directors": {
            "Attia": (
                f"{'✅ Minimum 14-day threshold met.' if min_duration_met else '⚠️ Under 14 days — treat as preliminary.'} "
                "Rate of change matters less than trajectory. Look at effect sizes (Cohen's d), not just direction. "
                "d < 0.2 is noise at these sample sizes; d > 0.5 with a consistency score >65% warrants attention."
            ),
            "Okafor": (
                "Trajectory matters more than any single datapoint. Check: is this experiment isolating one "
                "variable, or did other habits change during the same window? Confounders are the primary "
                "threat to N=1 validity. Cross-reference against travel, training load, and sleep quality."
            ),
            "Norton": (
                "Consistency score tells you how often each during-day beat your before average \u2014 "
                "it's the non-parametric signal that Cohen's d can miss at small N. A consistency score "
                "of 70%+ with a positive delta is more meaningful than a larger delta with 50% consistency. "
                + ("Note: for nutrition/supplement experiments, treat week 1 as adaptation noise. "
                   "The clean signal is in the second week and beyond. "
                   if ("supplement" in category or "nutrition" in category) else "")
                + "Build from what's working. Don't overhaul \u2014 optimize."
            ),
            "Chen": (
                "Cross-check HRV and recovery score trends against your training load (ATL/CTL/TSB) during "
                "the experiment window. If ATL was elevated, improvements in sleep or recovery metrics may "
                "be training-driven, not intervention-driven. Isolate the variable."
            ),
        },
    }


def tool_end_experiment(args):
    """End an active experiment and record the outcome.

    Marks the experiment as 'completed' or 'abandoned' with outcome notes.
    Run get_experiment_results first to see the data before closing.
    """
    exp_id  = (args.get("experiment_id") or "").strip()
    outcome = (args.get("outcome") or "").strip()
    status  = (args.get("status") or "completed").strip()
    end_date = (args.get("end_date") or "").strip()

    if not exp_id:
        raise ValueError("experiment_id is required")
    if status not in ("completed", "abandoned"):
        raise ValueError("status must be 'completed' or 'abandoned'")

    sk = f"EXP#{exp_id}"
    existing = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"No experiment found with id={exp_id}")
    if existing.get("status") != "active":
        raise ValueError(f"Experiment is already {existing.get('status')} — cannot end again")

    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")

    table.update_item(
        Key={"pk": EXPERIMENTS_PK, "sk": sk},
        UpdateExpression="SET #s = :s, outcome = :o, end_date = :e, ended_at = :ea",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s":  status,
            ":o":  outcome,
            ":e":  end_date,
            ":ea": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    logger.info(f"end_experiment: {exp_id} \u2192 {status}")

    start_date = existing.get("start_date", "")
    try:
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
    except Exception:
        days = None

    return {
        "ended":         True,
        "experiment_id": exp_id,
        "name":          existing.get("name", ""),
        "status":        status,
        "start_date":    start_date,
        "end_date":      end_date,
        "days_run":      days,
        "outcome":       outcome,
        "tip":           "Run get_experiment_results to see the full before/after comparison.",
    }


# \u2500\u2500 Ruck Logging (v2.49.0) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def tool_log_ruck(args):
    """
    Tag a Strava Walk activity as a ruck with weight.
    Finds the matching Walk on the given date (by time hint or single match),
    writes an overlay to ruck_log partition.
    """
    from decimal import Decimal
    import boto3

    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    weight_lbs = args.get("weight_lbs")
    if not weight_lbs or float(weight_lbs) <= 0:
        return {"error": "weight_lbs is required (e.g. 35 for a 35lb ruck)."}
    weight_lbs = float(weight_lbs)

    time_hint = args.get("time_hint", "")  # "morning", "afternoon", "evening", or HH:MM
    notes = args.get("notes", "")
    strava_id = args.get("strava_id")  # Optional direct match

    # \u2500\u2500 Find matching Walk activity from Strava \u2500\u2500
    strava_item = query_source("strava", date)
    if not strava_item:
        return {"error": f"No Strava data found for {date}. Was the activity recorded?"}

    activities = strava_item.get("activities", [])
    walks = [a for a in activities if a.get("type") in ("Walk", "Hike")]

    if not walks:
        all_types = [a.get("type", "?") for a in activities]
        return {"error": f"No Walk/Hike activities on {date}. Found: {', '.join(all_types)}"}

    matched = None

    if strava_id:
        # Direct match by strava_id
        matched = next((w for w in walks if str(w.get("strava_id")) == str(strava_id)), None)
        if not matched:
            return {"error": f"No walk with strava_id {strava_id} on {date}."}
    elif len(walks) == 1:
        matched = walks[0]
    elif time_hint:
        # Try to match by time of day
        def _hour(activity):
            local = activity.get("start_date_local", "")
            try:
                return int(local[11:13])
            except (ValueError, IndexError):
                return 12

        hint_lower = time_hint.lower().strip()
        if ":" in hint_lower:
            try:
                target_hour = int(hint_lower.split(":")[0])
            except ValueError:
                target_hour = 12
        elif hint_lower in ("morning", "am"):
            target_hour = 8
        elif hint_lower in ("afternoon", "midday"):
            target_hour = 14
        elif hint_lower in ("evening", "pm", "night"):
            target_hour = 18
        else:
            target_hour = 12

        matched = min(walks, key=lambda w: abs(_hour(w) - target_hour))
    else:
        # Multiple walks, no hint — list them
        options = []
        for w in walks:
            local = w.get("start_date_local", "")
            dist = w.get("distance_miles") or round(float(w.get("distance_meters", 0)) / 1609.34, 1)
            dur = round(float(w.get("moving_time_seconds", 0)) / 60)
            options.append(f"strava_id={w.get('strava_id')}: {local[11:16]} \u2014 {dist} mi, {dur} min")
        return {
            "error": f"Multiple walks on {date}. Specify time_hint or strava_id:",
            "walks": options,
        }

    # \u2500\u2500 Build ruck entry \u2500\u2500
    sid = str(matched.get("strava_id", ""))
    dist_mi = matched.get("distance_miles") or round(float(matched.get("distance_meters", 0)) / 1609.34, 2)
    dur_min = round(float(matched.get("moving_time_seconds", 0)) / 60, 1)
    avg_hr = matched.get("average_heartrate")
    elev_ft = matched.get("total_elevation_gain_feet") or 0
    name = matched.get("name", "Walk")
    start_local = matched.get("start_date_local", "")

    # Calorie estimate: Pandolf simplified — (bodyweight + load) / bodyweight * base walking kcal
    # Base: ~80 kcal/mile for 200 lb person walking at moderate pace
    # With load: multiply by (body_weight + ruck_weight) / body_weight
    # Also add ~10% per 1000 ft elevation gain
    try:
        profile = get_profile() or {}
        body_weight = float(profile.get("weight_lbs", 200))
    except Exception:
        body_weight = 200

    load_multiplier = (body_weight + weight_lbs) / body_weight
    base_kcal_per_mile = 0.4 * body_weight  # ~80 kcal/mi for 200lb
    elev_bonus = 1 + (float(elev_ft) / 1000) * 0.10 if elev_ft else 1.0
    estimated_kcal = round(float(dist_mi) * base_kcal_per_mile * load_multiplier * elev_bonus)

    entry = {
        "strava_id": sid,
        "weight_lbs": Decimal(str(weight_lbs)),
        "distance_miles": Decimal(str(round(float(dist_mi), 2))),
        "duration_min": Decimal(str(dur_min)),
        "elevation_gain_ft": Decimal(str(round(float(elev_ft), 1))),
        "avg_heartrate": Decimal(str(float(avg_hr))) if avg_hr else None,
        "estimated_kcal": estimated_kcal,
        "load_multiplier": Decimal(str(round(load_multiplier, 2))),
        "activity_name": name,
        "start_local": start_local,
        "notes": notes,
        "logged_at": datetime.utcnow().isoformat(),
    }
    entry = {k: v for k, v in entry.items() if v is not None and v != ""}

    # \u2500\u2500 Write to DynamoDB \u2500\u2500
    try:
        table.update_item(
            Key={"pk": RUCK_PK, "sk": f"DATE#{date}"},
            UpdateExpression=(
                "SET #r = list_append(if_not_exists(#r, :empty), :entry), "
                "#d = :date, #src = :src, #ua = :ua"
            ),
            ExpressionAttributeNames={"#r": "rucks", "#d": "date", "#src": "source", "#ua": "updated_at"},
            ExpressionAttributeValues={
                ":entry": [entry],
                ":empty": [],
                ":date": date,
                ":src": "ruck_log",
                ":ua": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        return {"error": f"Failed to log ruck: {e}"}

    return {
        "status": "logged",
        "date": date,
        "activity": f"{name} at {start_local[11:16] if len(start_local) > 11 else '?'}",
        "distance_miles": round(float(dist_mi), 2),
        "duration_min": dur_min,
        "ruck_weight_lbs": weight_lbs,
        "elevation_gain_ft": round(float(elev_ft), 1),
        "estimated_kcal": estimated_kcal,
        "load_multiplier": round(load_multiplier, 2),
        "avg_heartrate": float(avg_hr) if avg_hr else None,
        "message": (
            f"Tagged '{name}' as ruck: {round(float(dist_mi), 1)} mi with {weight_lbs} lbs "
            f"(~{estimated_kcal} kcal, {round(load_multiplier, 1)}x walking effort). "
            f"Strava ID: {sid}"
        ),
    }


def tool_get_ruck_log(args):
    """
    Retrieve ruck history: sessions, total miles, load trends, frequency.
    """
    end = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": RUCK_PK,
            ":s": f"DATE#{start}",
            ":e": f"DATE#{end}\xff",
        },
    )
    items = resp.get("Items", [])
    if not items:
        return {"message": f"No rucks logged between {start} and {end}.", "total_sessions": 0}

    all_rucks = []
    for item in items:
        date = item.get("date", "")
        for r in item.get("rucks", []):
            r["date"] = date
            all_rucks.append(decimal_to_float(r))

    all_rucks.sort(key=lambda r: r.get("date", ""))

    total_miles = sum(r.get("distance_miles", 0) for r in all_rucks)
    total_kcal = sum(r.get("estimated_kcal", 0) for r in all_rucks)
    avg_weight = sum(r.get("weight_lbs", 0) for r in all_rucks) / len(all_rucks) if all_rucks else 0
    total_min = sum(r.get("duration_min", 0) for r in all_rucks)
    max_weight = max((r.get("weight_lbs", 0) for r in all_rucks), default=0)
    total_elev = sum(r.get("elevation_gain_ft", 0) for r in all_rucks)

    # Weekly frequency
    weeks = max(1, (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 7)
    freq = round(len(all_rucks) / weeks, 1)

    # Per-session summary
    sessions = []
    for r in all_rucks:
        sessions.append({
            "date": r.get("date"),
            "weight_lbs": r.get("weight_lbs"),
            "distance_miles": r.get("distance_miles"),
            "duration_min": r.get("duration_min"),
            "elevation_ft": r.get("elevation_gain_ft"),
            "estimated_kcal": r.get("estimated_kcal"),
            "avg_hr": r.get("avg_heartrate"),
            "activity": r.get("activity_name", ""),
        })

    return {
        "period": f"{start} to {end}",
        "total_sessions": len(all_rucks),
        "weekly_frequency": freq,
        "total_miles": round(total_miles, 1),
        "total_duration_min": round(total_min),
        "total_elevation_ft": round(total_elev),
        "total_estimated_kcal": total_kcal,
        "avg_ruck_weight_lbs": round(avg_weight, 1),
        "max_ruck_weight_lbs": max_weight,
        "sessions": sessions,
    }
