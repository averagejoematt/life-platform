"""
Lifestyle tools: insights, supplements, weather, social, meditation, travel, BP, experiments, gait, energy, movement, state_of_mind.
"""

import json
import math
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from mcp.config import EXPERIMENTS_PK, INSIGHTS_PK, S3_BUCKET, TRAVEL_PK, USER_ID, USER_PREFIX, logger, s3_client, table
from mcp.core import decimal_to_float, parallel_query_sources, query_source
from mcp.helpers import normalize_whoop_sleep

# ── Travel constants ──

_TZ_OFFSETS = {
    "America/Los_Angeles": -8,
    "America/Denver": -7,
    "America/Chicago": -6,
    "America/New_York": -5,
    "America/Anchorage": -9,
    "Pacific/Honolulu": -10,
    "Europe/London": 0,
    "Europe/Paris": 1,
    "Europe/Berlin": 1,
    "Europe/Rome": 1,
    "Europe/Madrid": 1,
    "Europe/Amsterdam": 1,
    "Europe/Zurich": 1,
    "Asia/Tokyo": 9,
    "Asia/Shanghai": 8,
    "Asia/Hong_Kong": 8,
    "Asia/Singapore": 8,
    "Asia/Seoul": 9,
    "Asia/Bangkok": 7,
    "Asia/Dubai": 4,
    "Asia/Kolkata": 5.5,
    "Australia/Sydney": 10,
    "Australia/Melbourne": 10,
    "Australia/Perth": 8,
    "Pacific/Auckland": 12,
    "America/Sao_Paulo": -3,
    "America/Mexico_City": -6,
    "America/Toronto": -5,
    "America/Vancouver": -8,
    "Africa/Cairo": 2,
    "America/Lima": -5,
    "America/Bogota": -5,
    "America/Buenos_Aires": -3,
}
HOME_TZ = "America/Los_Angeles"
HOME_OFFSET = _TZ_OFFSETS[HOME_TZ]


def _tz_offset(tz_name):
    """Get UTC offset for a timezone name. Returns None if unknown."""
    return _TZ_OFFSETS.get(tz_name)


def _is_traveling(date_str=None):
    """Check if a given date (or today) falls within an active trip. Returns trip dict or None."""
    check_date = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": TRAVEL_PK, ":prefix": "TRIP#"},
        )
        for item in resp.get("Items", []):
            item = decimal_to_float(item)
            start = item.get("start_date", "")
            end = item.get("end_date") or "9999-12-31"
            if start <= check_date <= end:
                return item
        return None
    except Exception:
        return None


# ── Citation gate (#758) ──
# Seligman/Holt-Lunstad-style research citations read as rigor-flavored garnish when the
# underlying personal sample is a handful of days (ADR-105: uncertainty + n on every claim).
# Gate the citation on real data volume; below threshold, omit it — the honest numbers
# (counts, streaks, correlations) still return either way. 14 = two full rolling weeks of
# enriched_social_quality logs, matching this tool's own rolling_7d/rolling_30d windows —
# enough to say "this is a pattern," not one journal entry dressed up as a finding.
_SOCIAL_CITATION_MIN_N = 14

# ── Experiment metrics ──

_EXPERIMENT_METRICS = [
    # Sleep
    ("whoop", "sleep_score", "Sleep Score", True),  # normalized from sleep_quality_score
    ("whoop", "sleep_efficiency_pct", "Sleep Efficiency %", True),  # normalized from sleep_efficiency_percentage
    ("whoop", "deep_pct", "Deep Sleep %", True),  # normalized from slow_wave_sleep_hours
    ("whoop", "rem_pct", "REM Sleep %", True),  # normalized from rem_sleep_hours
    ("eightsleep", "sleep_onset_latency_min", "Sleep Onset Latency", False),  # Eight Sleep only — Whoop doesn't track
    # Recovery
    ("whoop", "recovery_score", "Whoop Recovery", True),
    ("whoop", "hrv_rmssd", "HRV (rMSSD)", True),
    ("whoop", "resting_heart_rate", "Resting HR", False),
    # Stress & Energy
    ("garmin", "average_stress_level", "Garmin Stress", False),
    ("garmin", "body_battery_high", "Body Battery Peak", True),
    # Body
    ("withings", "weight_lbs", "Weight (lbs)", None),  # direction depends on goal
    # Nutrition
    ("macrofactor", "calories", "Calories", None),
    ("macrofactor", "protein_g", "Protein (g)", None),
    # Movement
    ("apple_health", "steps", "Steps", True),
    # Glucose (if available)
    ("apple_health", "cgm_mean_glucose", "Mean Glucose", False),
    ("apple_health", "cgm_time_in_range_pct", "CGM Time in Range %", True),
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
    LAT, LON = 47.6062, -122.3321  # Seattle, WA -- Matthew's home city for weather correlation

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
            # Use module-level table from mcp.config (was broken: referenced undefined _REGION/TABLE_NAME)

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
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")

    tags = args.get("tags") or []
    source = args.get("source") or "chat"

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S")
    insight_id = ts  # human-readable, doubles as sort key suffix
    sk = f"INSIGHT#{ts}"

    item = {
        "pk": INSIGHTS_PK,
        "sk": sk,
        "insight_id": insight_id,
        "text": text,
        "date_saved": now.strftime("%Y-%m-%d"),
        "source": source,
        "status": "open",
        "outcome_notes": "",
        "tags": tags,
    }
    table.put_item(Item=item)
    logger.info(f"save_insight: saved insight_id={insight_id}")
    return {
        "saved": True,
        "insight_id": insight_id,
        "date_saved": item["date_saved"],
        "text_preview": text[:120] + ("…" if len(text) > 120 else ""),
        "tags": tags,
        "source": source,
    }


def tool_get_insights(args):
    """List insights from the coaching log.
    Optionally filter by status (open/acted/resolved).
    Returns newest-first. Flags items open >14 days.
    """
    status_filter = args.get("status_filter")  # None = all
    limit = int(args.get("limit") or 50)
    today = datetime.now(timezone.utc).date()

    from mcp.core import _apply_phase_filter  # ADR-058

    resp = table.query(
        **_apply_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(INSIGHTS_PK) & Key("sk").begins_with("INSIGHT#"),
                "ScanIndexForward": False,  # newest first
                "Limit": 200,
            }
        )
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

        results.append(
            {
                "insight_id": item.get("insight_id", ""),
                "text": item.get("text", ""),
                "date_saved": date_saved,
                "days_open": days_open,
                "source": item.get("source", "chat"),
                "status": status,
                "outcome_notes": item.get("outcome_notes", ""),
                "tags": item.get("tags", []),
                "stale": (days_open is not None and days_open > 14 and status == "open"),
            }
        )
        if len(results) >= limit:
            break

    stale_count = sum(1 for r in results if r["stale"])
    return {
        "total": len(results),
        "stale_count": stale_count,
        "status_filter": status_filter or "all",
        "insights": results,
    }


def tool_update_insight_outcome(args):
    """Update the outcome notes and/or status of an existing insight.
    insight_id is the timestamp string returned by save_insight (e.g. 2026-02-22T09:15:00).
    status must be one of: open, acted, resolved.
    """
    insight_id = (args.get("insight_id") or "").strip()
    outcome_notes = (args.get("outcome_notes") or "").strip()
    new_status = (args.get("status") or "acted").strip()

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
            ":d": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
    )
    logger.info(f"update_insight_outcome: insight_id={insight_id} status={new_status}")
    return {
        "updated": True,
        "insight_id": insight_id,
        "status": new_status,
        "outcome_notes": outcome_notes,
        "text_preview": existing.get("text", "")[:120],
    }


def tool_get_social_connection_trend(args):
    """
    Aggregates enriched_social_quality from journal entries over time.
    Tracks social connection quality, streaks, rolling averages, and
    correlates with health outcomes. The `perma_context` field (a Seligman
    PERMA / Holt-Lunstad citation) is gated on n — see `_SOCIAL_CITATION_MIN_N` (#758).
    """
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

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
        w7 = scores[max(0, i - 6) : i + 1]
        w30 = scores[max(0, i - 29) : i + 1]
        rolling_7d.append({"date": d, "avg": round(sum(w7) / len(w7), 2)})
        rolling_30d.append({"date": d, "avg": round(sum(w30) / len(w30), 2)})

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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for d in reversed(sorted_dates):
        if daily_social[d]["score"] >= 3:
            days_since_meaningful = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days
            break

    health_correlations = []
    HEALTH_SOURCES = [
        ("whoop", "recovery_score", "Recovery"),
        ("whoop", "hrv", "HRV"),
        ("whoop", "sleep_score", "Sleep Score"),
        ("garmin", "avg_stress", "Stress"),
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
            mx, my = sum(xs) / n, sum(ys) / n
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
            sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
            sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
            r = round(cov / (sx * sy), 3) if sx > 0 and sy > 0 else 0
            health_correlations.append(
                {"metric": label, "r": r, "n": n, "interpretation": "strong" if abs(r) > 0.5 else "moderate" if abs(r) > 0.3 else "weak"}
            )

    journal_correlations = []
    for field_data, label in [(daily_mood, "Mood"), (daily_energy, "Energy"), (daily_stress, "Stress")]:
        xs, ys = [], []
        for d in sorted_dates:
            if d in field_data:
                xs.append(daily_social[d]["score"])
                ys.append(field_data[d])
        if len(xs) >= 10:
            n = len(xs)
            mx, my = sum(xs) / n, sum(ys) / n
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
            sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
            sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
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

    result = {
        "start_date": start_date,
        "end_date": end_date,
        "total_days_with_data": len(daily_social),
        "distribution": distribution,
        "overall_avg_score": _avg(scores),
        "score_legend": {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4},
        "rolling_7d_latest": rolling_7d[-1] if rolling_7d else None,
        "rolling_30d_latest": rolling_30d[-1] if rolling_30d else None,
        "streaks": {
            "current_meaningful_streak": current_streak,
            "longest_meaningful_streak": longest_streak,
            "days_since_meaningful": days_since_meaningful,
        },
        "health_correlations": health_correlations,
        "journal_correlations": journal_correlations,
        "meaningful_vs_low_comparison": comparison,
    }

    # #758: cite external wellbeing research only once there's enough real data to
    # ground it in — below the floor it's garnish, not a finding about this person.
    if len(daily_social) >= _SOCIAL_CITATION_MIN_N:
        result["perma_context"] = (
            "Seligman PERMA: Relationships are #1 wellbeing predictor. Holt-Lunstad: isolation "
            "increases mortality 26%. Target: meaningful+ connection 5+ days/week."
        )

    return result


def _get_state_of_mind_trend(args):
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
                days_data.append(
                    {
                        "date": ds,
                        "avg_valence": float(valence),
                        "min_valence": float(item.get("som_min_valence", valence)),
                        "max_valence": float(item.get("som_max_valence", valence)),
                        "check_in_count": int(item.get("som_check_in_count", 0)),
                        "mood_count": int(item.get("som_mood_count", 0)),
                        "emotion_count": int(item.get("som_emotion_count", 0)),
                        "top_labels": item.get("som_top_labels", ""),
                        "top_associations": item.get("som_top_associations", ""),
                    }
                )
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
            # HAE writes SoM raw check-ins under the user-segmented prefix
            # (raw/matthew/state_of_mind/…). The old un-segmented path silently
            # 404'd, dropping the label/association/time-of-day deep analysis.
            key = f"raw/{USER_ID}/state_of_mind/{y}/{m}/{day}.json"
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
        "valence_by_association": [{"association": a, **v} for a, v in assoc_sorted],
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


def _load_library_entry(library_id):
    """#1117: fetch one experiment_library.json entry by id (fail-soft → None).

    The library is the promotion ledger — promoted entries carry rationale,
    promoted_date, votes and the for/against evidence citations that become the
    experiment's why_now + evidence_links when no explicit values are given."""
    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key="config/experiment_library.json")
        lib = json.loads(obj["Body"].read())
        for entry in lib.get("experiments", []):
            if entry.get("id") == library_id:
                return entry
    except Exception as e:  # noqa: BLE001 — fail-soft: no trigger means honest-empty, never a blocked creation
        logger.warning(f"create_experiment: experiment library lookup failed for '{library_id}': {e}")
    return None


def _find_hypothesis(hyp_id):
    """#1117: fetch a hypothesis-engine record by hypothesis_id or sk suffix
    (fail-soft → None). A CONFIRMED record is the hypothesis→experiment promotion
    trigger; derive_why_now turns it into the experiment's why_now."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}hypotheses") & Key("sk").begins_with("HYPOTHESIS#"),
            ScanIndexForward=False,
        )
        for it in resp.get("Items", []):
            if it.get("hypothesis_id") == hyp_id or it.get("sk", "").replace("HYPOTHESIS#", "") == hyp_id:
                return decimal_to_float(it)
    except Exception as e:  # noqa: BLE001 — fail-soft, same posture as the library lookup
        logger.warning(f"create_experiment: hypothesis lookup failed for '{hyp_id}': {e}")
    return None


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
    name = (args.get("name") or "").strip()
    hypothesis = (args.get("hypothesis") or "").strip()
    start_date = (args.get("start_date") or "").strip()
    tags = args.get("tags") or []
    notes = (args.get("notes") or "").strip()
    library_id = (args.get("library_id") or "").strip()
    duration_tier = (args.get("duration_tier") or "").strip()
    experiment_type = (args.get("experiment_type") or "").strip()
    planned_duration_days = args.get("planned_duration_days")
    design = args.get("design")
    # #1117: the justification contract — why this experiment, why now, what outcome
    # is hoped for, how it is measured, and the evidence behind it.
    why_now = (args.get("why_now") or "").strip()
    priority = (args.get("priority") or "").strip().lower()
    hoped_outcome = (args.get("hoped_outcome") or "").strip()
    measurement = (args.get("measurement") or "").strip()
    evidence_links = args.get("evidence_links") or []
    source_hypothesis_id = (args.get("source_hypothesis_id") or "").strip()

    if not name:
        raise ValueError("name is required (e.g. 'Creatine 5g daily', 'No caffeine after 10am')")
    if not hypothesis:
        raise ValueError("hypothesis is required (e.g. 'Will improve deep sleep % by >5%')")

    import experiment_design

    # #539: pre-registration — the design is validated NOW and frozen on the record.
    # An invalid design rejects the creation outright (a sloppy design silently
    # accepted would be worse than none), and nothing may mutate it afterward.
    if design is not None:
        ok, issues = experiment_design.validate_design(design)
        if not ok:
            raise ValueError("invalid design (pre-registration rejected): " + "; ".join(issues))

    # #1117: same posture for the justification fields — invalid values reject the
    # creation; absent values stay absent (ADR-104 honest-empty, never placeholder).
    ok, issues = experiment_design.validate_justification(
        {
            "why_now": why_now or None,
            "priority": priority or None,
            "hoped_outcome": hoped_outcome or None,
            "measurement": measurement or None,
            "evidence_links": evidence_links or None,
        }
    )
    if not ok:
        raise ValueError("invalid justification (rejected): " + "; ".join(issues))

    # #1117: wire why_now to the promotion trigger — provenance is automatic where it
    # exists. Explicit wins; else a confirmed hypothesis (source_hypothesis_id) or the
    # promoted library entry supplies it. Lookups fail soft: a missing trigger simply
    # leaves the field empty, never blocks the creation.
    lib_entry = _load_library_entry(library_id) if library_id else None
    hyp_record = _find_hypothesis(source_hypothesis_id) if source_hypothesis_id else None
    if source_hypothesis_id and hyp_record is None:
        logger.warning(f"create_experiment: source_hypothesis_id '{source_hypothesis_id}' not found — why_now not derived from it")
    why_now, why_now_source = experiment_design.derive_why_now(why_now or None, hypothesis=hyp_record, library_entry=lib_entry)
    evidence_links = experiment_design.derive_evidence_links(evidence_links or None, library_entry=lib_entry)

    now = datetime.now(timezone.utc)
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

    # EL-F5: Auto-detect iteration count from past experiments with same library_id or slug
    iteration = 1
    try:
        past_resp = table.query(
            KeyConditionExpression=Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"),
            ScanIndexForward=False,
        )
        for past in past_resp.get("Items", []):
            past_lib = past.get("library_id", "")
            past_slug = re.sub(r"[^a-z0-9]+", "-", past.get("name", "").lower()).strip("-")[:40]
            if (library_id and past_lib == library_id) or past_slug == slug:
                iteration += 1
    except Exception:
        pass

    item = {
        "pk": EXPERIMENTS_PK,
        "sk": sk,
        "experiment_id": exp_id,
        "name": name,
        "hypothesis": hypothesis,
        "start_date": start_date,
        "end_date": None,  # null = still active
        "status": "active",  # active, completed, abandoned
        "tags": tags,
        "notes": notes,
        "outcome": "",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        # EL-F5: New fields
        "library_id": library_id or None,
        "duration_tier": duration_tier or None,
        "experiment_type": experiment_type or None,
        "planned_duration_days": int(planned_duration_days) if planned_duration_days else None,
        "iteration": iteration,
        # #539: the frozen n-of-1 design + its public pre-registration stamp.
        # Floats → Decimal for DDB (min_effect is commonly fractional).
        "design": json.loads(json.dumps(design), parse_float=Decimal) if design else None,
        "pre_registered_at": now.strftime("%Y-%m-%dT%H:%M:%S") if design else None,
        # #1117: the justification contract. why_now carries its provenance stamp
        # (explicit | hypothesis | library); absent fields are simply absent —
        # ADR-104 honest-empty, the surfaces render nothing for them.
        "why_now": why_now,
        "why_now_source": why_now_source,
        "source_hypothesis_id": source_hypothesis_id or None,
        "priority": priority or None,
        "hoped_outcome": hoped_outcome or None,
        "measurement": measurement or None,
        "evidence_links": evidence_links or None,
    }

    # #728: freeze the pre-registration as a PUBLIC, timestamped S3 artifact —
    # written at creation, before any results exist, and never mutated afterward.
    # The S3 Last-Modified + this body's registered_at are the before-the-results
    # proof the experiment page links. Fail-soft: an S3 hiccup must not block the
    # experiment itself, but the response says so honestly instead of pretending.
    prereg_url = None
    prereg_warning = None
    if design is not None:
        prereg_key = f"generated/experiments/prereg/{exp_id}.json"
        artifact = {
            "schema_version": 1,
            "experiment_id": exp_id,
            "name": name,
            "hypothesis": hypothesis,
            "start_date": start_date,
            "planned_duration_days": item["planned_duration_days"],
            "duration_tier": duration_tier or None,
            "experiment_type": experiment_type or None,
            "iteration": iteration,
            "design": design,  # raw JSON floats — this is the public copy, not the DDB one
            # #1117: the justification is part of the pre-registered thinking — frozen
            # with the design (present fields only; honest-empty stays empty).
            **{
                k: v
                for k, v in (
                    ("why_now", why_now),
                    ("why_now_source", why_now_source),
                    ("priority", priority or None),
                    ("hoped_outcome", hoped_outcome or None),
                    ("measurement", measurement or None),
                    ("evidence_links", evidence_links or None),
                )
                if v is not None
            },
            "registered_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "contract": (
                "Frozen at creation, before any results existed. The design above is what "
                "was promised; the closing analysis is graded against it, not against hindsight."
            ),
        }
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=prereg_key,
                Body=json.dumps(artifact, indent=2),
                ContentType="application/json",
                CacheControl="public, max-age=300",
            )
            prereg_url = f"https://averagejoematt.com/experiments/prereg/{exp_id}.json"
            item["prereg_key"] = prereg_key
            item["prereg_url"] = prereg_url
        except Exception as e:  # noqa: BLE001 — fail-soft by design, surfaced in the response
            logger.warning(f"create_experiment: pre-registration artifact write failed for {exp_id}: {e}")
            prereg_warning = (
                "pre-registration artifact could NOT be written to S3 — the experiment exists "
                "but has no public timestamped proof; re-create it or write the artifact manually"
            )

    # Clean None values for DynamoDB
    clean_item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=clean_item)
    logger.info(f"create_experiment: created {exp_id} (iteration {iteration})")

    return {
        "created": True,
        "experiment_id": exp_id,
        "name": name,
        "hypothesis": hypothesis,
        "start_date": start_date,
        "status": "active",
        "tags": tags,
        "library_id": library_id or None,
        "duration_tier": duration_tier or None,
        "experiment_type": experiment_type or None,
        "iteration": iteration,
        "design": design,
        "pre_registered_at": item.get("pre_registered_at"),
        "pre_registration_url": prereg_url,
        # #1117: the justification contract, echoed with why_now provenance.
        "why_now": why_now,
        "why_now_source": why_now_source,
        "priority": priority or None,
        "hoped_outcome": hoped_outcome or None,
        "measurement": measurement or None,
        "evidence_links": evidence_links or None,
        **({"pre_registration_warning": prereg_warning} if prereg_warning else {}),
        "board_of_directors": {
            "Huberman": "One variable at a time. Track for at least 2 weeks before drawing conclusions. Control for confounders: sleep timing, stress, travel.",
            "Attia": "Define your primary endpoint now. What number would convince you this worked? Statistical noise requires \u226514 days of data.",
            "Ferriss": "What does the minimum effective dose look like? Start with the smallest intervention that could produce a measurable change.",
        },
    }


def tool_list_experiments(args):
    """List all N=1 experiments with status and duration.

    Filter by status: active, completed, abandoned, or all.
    Shows days active, whether minimum duration (14d) has been met.
    """
    status_filter = args.get("status")  # None = all
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from mcp.core import _apply_phase_filter  # ADR-058

    resp = table.query(
        **_apply_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"),
                "ScanIndexForward": False,
            }
        )
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

        results.append(
            {
                "experiment_id": item.get("experiment_id", ""),
                "name": item.get("name", ""),
                "hypothesis": item.get("hypothesis", ""),
                "start_date": start,
                "end_date": item.get("end_date"),
                "status": status,
                "days_active": days,
                "min_duration_met": days is not None and days >= 14,
                "tags": item.get("tags", []),
                "notes": item.get("notes", ""),
                "outcome": item.get("outcome", ""),
                # EL-22/23: Evolution fields
                "library_id": item.get("library_id"),
                "grade": item.get("grade"),
                "compliance_pct": item.get("compliance_pct"),
                "duration_tier": item.get("duration_tier"),
                "experiment_type": item.get("experiment_type"),
                "iteration": item.get("iteration", 1),
                "reflection": item.get("reflection"),
                # #1117: the justification contract (nulls on legacy records — honest-empty).
                "why_now": item.get("why_now"),
                "why_now_source": item.get("why_now_source"),
                "priority": item.get("priority"),
                "hoped_outcome": item.get("hoped_outcome"),
                "measurement": item.get("measurement"),
                "evidence_links": decimal_to_float(item.get("evidence_links") or []),
            }
        )

    active = sum(1 for r in results if r["status"] == "active")
    completed = sum(1 for r in results if r["status"] == "completed")

    return {
        "total": len(results),
        "active": active,
        "completed": completed,
        "filter": status_filter or "all",
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
    var_b = sum((x - mean_b) ** 2 for x in before_vals) / (len(before_vals) - 1)
    var_d = sum((x - mean_d) ** 2 for x in during_vals) / (len(during_vals) - 1)
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
    end_date = item.get("end_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        consistency_score = round(sum(1 for v in during_vals if v > before_mean) / len(during_vals) * 100, 1) if during_vals else None

        comparisons.append(
            {
                "metric": display_name,
                "source": source,
                "before_mean": round(before_mean, 2),
                "during_mean": round(during_mean, 2),
                "delta": round(delta, 2),
                "pct_change": round(pct_change, 1) if pct_change is not None else None,
                "direction": direction,
                "before_n": len(before_vals),
                "during_n": len(during_vals),
                "effect_size": effect_size,
                "consistency_score": consistency_score,
            }
        )

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
                f"Only {during_days} days of data. Board recommends minimum 14 days " f"for reliable signal. Results may be noise."
            )

    return {
        "experiment": {
            "id": exp_id,
            "name": item.get("name", ""),
            "hypothesis": hypothesis,
            "status": status,
            "start_date": start_date,
            "end_date": end_date if status != "active" else f"{end_date} (ongoing)",
        },
        "comparison_period": {
            "before": f"{before_start} \u2192 {before_end} ({during_days} days)",
            "during": f"{during_start} \u2192 {during_end} ({during_days} days)",
        },
        "duration_warning": duration_warning,
        "metrics_compared": len(comparisons),
        "improved_count": len(improved),
        "worsened_count": len(worsened),
        "comparisons": comparisons,
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
                + (
                    "Note: for nutrition/supplement experiments, treat week 1 as adaptation noise. "
                    "The clean signal is in the second week and beyond. "
                    if ("supplement" in category or "nutrition" in category)
                    else ""
                )
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

    EL-F5 additions: grade (completed/partial/failed), compliance_pct (0-100),
    reflection ("what I'd do differently").
    """
    exp_id = (args.get("experiment_id") or "").strip()
    outcome = (args.get("outcome") or "").strip()
    status = (args.get("status") or "completed").strip()
    end_date = (args.get("end_date") or "").strip()
    grade = (args.get("grade") or "").strip()
    compliance_pct = args.get("compliance_pct")
    reflection = (args.get("reflection") or "").strip()

    if not exp_id:
        raise ValueError("experiment_id is required")
    if status not in ("completed", "abandoned"):
        raise ValueError("status must be 'completed' or 'abandoned'")
    if grade and grade not in ("completed", "partial", "failed"):
        raise ValueError("grade must be 'completed', 'partial', or 'failed'")

    sk = f"EXP#{exp_id}"
    existing = table.get_item(Key={"pk": EXPERIMENTS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"No experiment found with id={exp_id}")
    if existing.get("status") != "active":
        raise ValueError(f"Experiment is already {existing.get('status')} — cannot end again")

    if not end_date:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Auto-infer grade if not provided
    if not grade:
        grade = "failed" if status == "abandoned" else "completed"

    update_expr = "SET #s = :s, outcome = :o, end_date = :e, ended_at = :ea, grade = :g"
    expr_values = {
        ":s": status,
        ":o": outcome,
        ":e": end_date,
        ":ea": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        ":g": grade,
    }
    if compliance_pct is not None:
        update_expr += ", compliance_pct = :cp"
        expr_values[":cp"] = int(compliance_pct)
    if reflection:
        update_expr += ", reflection = :ref"
        expr_values[":ref"] = reflection

    # #539: designed experiments close with the pre-registered paired analysis \u2014
    # baseline vs washout-trimmed intervention window, block-bootstrap 95% CI,
    # deterministic verdict against the FROZEN criterion. Fail-soft: an analysis
    # error never blocks closing (the honest state is analysis=None, not a guess).
    analysis = None
    design = existing.get("design")
    if design and status == "completed":
        try:
            analysis = _run_design_analysis(existing, design, end_date)
        except Exception as e:
            logger.warning(f"end_experiment: design analysis failed for {exp_id}: {e}")
    if analysis is not None:
        update_expr += ", analysis = :an"
        expr_values[":an"] = json.loads(json.dumps(analysis), parse_float=Decimal)

    table.update_item(
        Key={"pk": EXPERIMENTS_PK, "sk": sk},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=expr_values,
    )
    logger.info(f"end_experiment: {exp_id} \u2192 {status} (grade={grade})")

    start_date = existing.get("start_date", "")
    try:
        days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
    except Exception:
        days = None

    return {
        "ended": True,
        "experiment_id": exp_id,
        "name": existing.get("name", ""),
        "status": status,
        "grade": grade,
        "start_date": start_date,
        "end_date": end_date,
        "days_run": days,
        "outcome": outcome,
        "compliance_pct": int(compliance_pct) if compliance_pct is not None else None,
        "reflection": reflection or None,
        "iteration": existing.get("iteration", 1),
        "analysis": analysis,
        "tip": "Run get_experiment_results to see the full before/after comparison.",
    }


def _run_design_analysis(existing, design, end_date):
    """#539: the deterministic close-path analysis for a pre-registered design.

    Fetches the criterion metric's daily series for the baseline window and the
    washout-trimmed intervention window, then evaluates against the frozen
    criterion via experiment_design (stats_core underneath). Returns the analysis
    dict (windows + stats + verdict + summary sentence), or None when the washout
    consumed the whole experiment."""
    import experiment_design

    design_f = json.loads(json.dumps(design, default=float))  # Decimals → floats for math
    windows = experiment_design.design_windows(existing.get("start_date", ""), end_date, design_f)
    if windows is None:
        return {
            "verdict": "inconclusive",
            "summary": "Washout consumed the whole experiment window — no analysis possible.",
            "windows": None,
        }
    metric = (design_f.get("criterion") or {}).get("metric", "")
    source, field, _label = experiment_design.DESIGN_METRICS[metric]

    def _values(start, end):
        items = query_source(source, start, end)
        if source == "whoop":
            items = [normalize_whoop_sleep(i) for i in items]
        vals = []
        for it in items:
            v = _extract_metric(it, field)
            if v is not None:
                vals.append(v)
        return vals

    baseline_vals = _values(windows["baseline_start"], windows["baseline_end"])
    window_vals = _values(windows["analysis_start"], windows["analysis_end"])
    stats = experiment_design.evaluate_design(design_f, baseline_vals, window_vals)
    return {
        "windows": windows,
        "metric": metric,
        **stats,
        "summary": experiment_design.analysis_summary(design_f, stats),
        "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "engine": "n1-design-v1",
    }


# \u2500\u2500 Ruck Logging (v2.49.0) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


# ==============================================================================
# BL-04: FIELD NOTES — Weekly AI-vs-Matthew Lab Notebook
# ==============================================================================

FIELD_NOTES_PK = f"USER#{USER_ID}#SOURCE#field_notes"


def _field_note_week_monday(week: str) -> str:
    """ISO week (YYYY-WNN) -> its Monday date (YYYY-MM-DD), for a date-sortable SK."""
    year, week_num = int(week[:4]), int(week[6:])
    return datetime.fromisocalendar(year, week_num, 1).strftime("%Y-%m-%d")


def _write_field_note_interactions(week: str, week_label: str, agreement, notes: str, disputed, added: str) -> None:
    """#533: broadcast Matthew's field-note pushback into every coach's memory.

    A field note is the platform's single cross-domain voice (field_notes_lambda),
    not attributable to one of the 8 coaches — it has no per-domain breakdown
    (`ai_domains` is aspirational, never populated). Rather than guess a mapping,
    Matthew's agreement/disagreement is written as one episodic INTERACTION#
    record per operational coach (persona_registry.OPERATIONAL_COACH_IDS), so
    every coach's weekly compression (coach_history_summarizer) can see it —
    mirroring the #531 board-Q&A write-back, just broadcast instead of per-coach.
    Content-addressed on the week (not today's date) so re-logging a response
    for the same week overwrites rather than piling up. Fail-soft per coach: a
    write failure never affects the saved field-note response."""
    try:
        import persona_registry

        coach_ids = persona_registry.OPERATIONAL_COACH_IDS
    except Exception as e:
        logger.warning(f"[field_notes] persona_registry unavailable for interaction write-back (non-fatal): {e}")
        return

    monday = _field_note_week_monday(week)
    now = datetime.now(timezone.utc).isoformat()
    item_base = {
        "sk": f"INTERACTION#{monday}#fieldnote-{week}",
        "interaction_type": "field_note_pushback",
        "channel": "field_notes",
        "week": week,
        "week_label": week_label,
        "agreement": agreement,
        "notes": notes[:500],
        "disputed": list(disputed)[:6] if disputed else [],
        "added": (added or "")[:300],
        "created_at": now,
    }
    for coach_id in coach_ids:
        try:
            table.put_item(Item={"pk": f"COACH#{coach_id}", **item_base})
        except Exception as e:
            logger.warning(f"[field_notes] interaction write-back failed for {coach_id} (non-fatal): {e}")


# ==============================================================================
# BL-03: THE LEDGER — Achievement-Linked Charitable Giving
# ==============================================================================

LEDGER_PK = f"USER#{USER_ID}#SOURCE#ledger"


def _get_movement_score(args):
    """Daily movement & NEAT analysis."""
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"))
    step_target = args.get("step_target", 8000)

    # DI-1.2: Hevy is the primary "did he train" signal. A step count must never, on
    # its own, drive a sedentary conclusion — has_workout is true if a normalized workout
    # exists from ANY source (Hevy first, then Strava). Hevy stores one record per workout
    # under DATE#{date}#WORKOUT#{id}, so a date "has a Hevy workout" if any such record exists.
    sources = parallel_query_sources(["apple_health", "strava", "hevy"], start_date, end_date)
    ah_items = sources.get("apple_health", [])
    strava_items = sources.get("strava", [])
    hevy_items = sources.get("hevy", [])
    if not ah_items and not hevy_items:
        return {"error": "No Apple Health or Hevy data in range."}

    ah_by_date = {i.get("date"): i for i in ah_items if i.get("date")}
    strava_by_date = {i.get("date"): i for i in strava_items if i.get("date")}
    hevy_dates = {i.get("date") for i in hevy_items if i.get("date")}

    daily = []
    neat_vals = []
    step_vals = []
    sedentary_days = []
    step_incomplete_dates = []  # DI-1.4: AH record present but step field missing (false-clean envelope)

    # Union of Apple-Health and Hevy dates: a Hevy-only training day (no Apple sync)
    # must still report has_workout and is never sedentary.
    for date in sorted(set(ah_by_date.keys()) | hevy_dates):
        ah = ah_by_date.get(date, {})
        strava = strava_by_date.get(date, {})
        steps = ah.get("steps")
        flights = ah.get("flights_climbed")
        distance = ah.get("distance_walk_run_miles")
        active_cal = ah.get("active_calories")
        exercise_kj = strava.get("total_kilojoules")
        exercise_kcal = float(exercise_kj) if exercise_kj else 0
        hevy_workout = date in hevy_dates
        strava_workout = int(float(strava.get("activity_count", 0))) > 0
        has_workout = hevy_workout or strava_workout

        row = {"date": date, "has_workout": has_workout}
        if has_workout:
            row["workout_sources"] = (["hevy"] if hevy_workout else []) + (["strava"] if strava_workout else [])
        if steps is not None:
            row["steps"] = int(float(steps))
            step_vals.append(float(steps))
        # DI-1.4: step-field completeness. The apple_health envelope can read "fresh"
        # while the step field itself is missing for the day — surface that gap rather
        # than silently treating a missing field as zero movement.
        if date in ah_by_date:
            row["step_data_complete"] = steps is not None
            if steps is None:
                step_incomplete_dates.append(date)
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
    # DI-1.4: step-field completeness across the Apple-Health envelope days.
    _ah_days = len(ah_by_date)
    if _ah_days:
        summary["step_coverage_pct"] = round((_ah_days - len(step_incomplete_dates)) / _ah_days * 100, 1)
        if step_incomplete_dates:
            summary["step_incomplete_dates"] = sorted(step_incomplete_dates)
            summary["step_incomplete_days"] = len(step_incomplete_dates)
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
        "note": (
            "NEAT is energy burned outside exercise. Sedentary = <5000 steps + no workout from ANY "
            "source (Hevy or Strava) + <200 active cal. has_workout reads Hevy first, then Strava — a "
            "Hevy lifting day is never sedentary regardless of step count."
        ),
    }


def tool_get_field_notes(args):
    """Retrieve Field Notes for a specific ISO week (or current week).

    Returns AI Lab Notes (present/lookback/focus paragraphs) and any
    existing Matthew response. Used before log_field_note_response so
    Matthew can read the AI notes and write back.
    """
    week = args.get("week")
    if not week:
        now = datetime.now(timezone.utc)
        year, wk, _ = now.isocalendar()
        week = f"{year}-W{wk:02d}"

    resp = table.get_item(Key={"pk": FIELD_NOTES_PK, "sk": f"WEEK#{week}"})
    item = resp.get("Item")
    if not item:
        return {
            "status": "not_yet_generated",
            "week": week,
            "message": f"No field notes found for {week}. The AI notes may not have been generated yet.",
        }

    item = decimal_to_float(item)
    result = {
        "week": item.get("week", week),
        "week_label": item.get("week_label", ""),
        "ai_present": item.get("ai_present", ""),
        "ai_lookback": item.get("ai_lookback", ""),
        "ai_focus": item.get("ai_focus", ""),
        "ai_generated_at": item.get("ai_generated_at"),
        "ai_tone": item.get("ai_tone"),
        "ai_domains": item.get("ai_domains", []),
        "ai_key_metrics": item.get("ai_key_metrics", {}),
    }
    # Include Matthew's response if present
    if item.get("matthew_notes"):
        result["matthew_notes"] = item["matthew_notes"]
        result["matthew_notes_at"] = item.get("matthew_notes_at")
        result["matthew_agreement"] = item.get("matthew_agreement")
        result["matthew_disputed"] = item.get("matthew_disputed", [])
        result["matthew_added"] = item.get("matthew_added")
        result["has_matthew_response"] = True
    else:
        result["has_matthew_response"] = False
        result["message"] = "AI notes are ready. Matthew hasn't responded yet."

    return result


def tool_log_field_note_response(args):
    """Write Matthew's response to the right page of a Field Notes entry.

    Uses update_item so Matthew's fields never overwrite the AI-generated fields.
    The WEEK# record must already exist with ai_generated_at set.
    """
    week = args.get("week", "").strip()
    notes = args.get("notes", "").strip()
    agreement = args.get("agreement")
    disputed = args.get("disputed", [])
    added = args.get("added", "")

    if not week:
        return {"error": "week is required (e.g. '2026-W14')"}
    if not re.match(r"^\d{4}-W\d{2}$", week):
        return {"error": f"Invalid week format '{week}'. Use YYYY-WNN (e.g. '2026-W14')"}
    if not notes:
        return {"error": "notes is required — write your response to the AI lab notes"}

    sk = f"WEEK#{week}"
    # Verify the record exists and has AI notes
    existing = table.get_item(Key={"pk": FIELD_NOTES_PK, "sk": sk}).get("Item")
    if not existing:
        return {"error": f"No field notes record for {week}. AI notes must be generated first."}
    if not existing.get("ai_generated_at"):
        return {"error": f"AI notes for {week} haven't been generated yet. Can't respond to empty notes."}

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    update_parts = [
        "matthew_notes = :mn",
        "matthew_notes_at = :mnat",
    ]
    expr_values = {
        ":mn": notes,
        ":mnat": ts,
    }

    if agreement:
        update_parts.append("matthew_agreement = :ma")
        expr_values[":ma"] = agreement

    if disputed:
        update_parts.append("matthew_disputed = :md")
        expr_values[":md"] = disputed

    if added:
        update_parts.append("matthew_added = :madd")
        expr_values[":madd"] = added

    table.update_item(
        Key={"pk": FIELD_NOTES_PK, "sk": sk},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeValues=expr_values,
    )

    week_label = existing.get("week_label", week)

    # #533: fold this pushback into every coach's episodic memory. The helper
    # already fails soft per-coach; this outer guard makes the promise absolute —
    # the saved field-note response (the actual product feature) must never fail
    # because of a bug in the write-back path.
    try:
        _write_field_note_interactions(week, week_label, agreement, notes, disputed, added)
    except Exception as e:
        logger.warning(f"[field_notes] interaction write-back skipped for {week} (non-fatal): {e}")

    word_count = len(notes.split())
    ai_preview = (existing.get("ai_present") or "")[:80]

    return {
        "status": "saved",
        "week": week,
        "week_label": week_label,
        "agreement": agreement,
        "word_count": word_count,
        "message": (
            f"Field Notes response saved — {week_label}\n"
            f"   Agreement: {agreement or 'not specified'}\n"
            f"   The right page is now filled.\n\n"
            f'   AI said: "{ai_preview}..."\n'
            f"   You responded in {word_count} words."
        ),
    }
