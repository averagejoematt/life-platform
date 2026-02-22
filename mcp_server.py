"""
life-platform MCP Server v1.8.0
Tools:
  - get_sources                  : list available sources and their date ranges
  - get_latest                   : most recent record(s) per source
  - get_daily_summary            : all sources for a single date
  - get_date_range               : time series (auto-aggregates for large windows)
  - find_days                    : filter days matching numeric field criteria (day-level only)
  - get_aggregated_summary       : monthly or yearly averages over any date range
  - get_field_stats              : min/max/avg/count + top-5 highs/lows + trend direction
  - search_activities            : search Strava activities by name, type, distance, elevation + percentile rank
  - compare_periods              : side-by-side comparison of two date ranges across any source
  - get_weekly_summary           : weekly training load totals for Strava
  - get_training_load            : CTL/ATL/TSB/ACWR — Banister fitness-fatigue model + injury risk
  - get_personal_records         : all-time PRs across every measurable dimension
  - get_cross_source_correlation : Pearson r between any two metrics with optional day lag
  - get_seasonal_patterns        : month-by-month averages across all years revealing annual cycles
  - get_health_dashboard         : current-state briefing — readiness, load, biomarker alerts
  - get_weight_loss_progress     : weekly rate of loss, BMI series, clinical milestones, plateau detection
  - get_body_composition_trend   : fat mass vs lean mass over time — is the loss fat or muscle?
  - get_energy_expenditure       : daily BMR + exercise calories = TDEE estimate and implied deficit
  - get_non_scale_victories      : fitness biomarker improvements since journey start
"""

import json
import math
import bisect
import time
import hashlib
import concurrent.futures
import boto3
import logging
from collections import defaultdict
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")
secrets  = boto3.client("secretsmanager", region_name="us-west-2")

USER_PREFIX     = "USER#matthew#SOURCE#"
PROFILE_PK      = "USER#matthew"
PROFILE_SK      = "PROFILE#v1"
API_SECRET_NAME = "life-platform/mcp-api-key"
RAW_DAY_LIMIT   = 90

SOURCES = ["whoop", "withings", "strava", "todoist", "apple_health"]

FIELD_ALIASES = {
    "strava": {
        "distance_miles":        "total_distance_miles",
        "elevation_gain_feet":   "total_elevation_gain_feet",
        "elevation_gain":        "total_elevation_gain_feet",
        "distance":              "total_distance_miles",
    }
}

# ── Profile cache (loaded once per Lambda warm instance) ─────────────────────
_PROFILE_CACHE = None

def get_profile():
    global _PROFILE_CACHE
    if _PROFILE_CACHE is not None:
        return _PROFILE_CACHE
    try:
        resp = table.get_item(Key={"pk": PROFILE_PK, "sk": PROFILE_SK})
        _PROFILE_CACHE = decimal_to_float(resp.get("Item", {}))
    except Exception as e:
        logger.warning(f"Could not load profile: {e}")
        _PROFILE_CACHE = {}
    return _PROFILE_CACHE


# ── In-memory cache (survives across invocations on a warm Lambda instance) ───
_MEM_CACHE: dict = {}
MEM_CACHE_TTL = 600  # 10 minutes

def mem_cache_get(key: str):
    entry = _MEM_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < MEM_CACHE_TTL:
        logger.info(f"[cache:mem] hit — {key}")
        return entry["data"]
    return None

def mem_cache_set(key: str, data):
    _MEM_CACHE[key] = {"data": data, "ts": time.time()}
    logger.info(f"[cache:mem] stored — {key}")


# ── DynamoDB pre-computed cache (survives cold starts, written nightly) ───────
CACHE_PK       = "CACHE#matthew"
CACHE_TTL_SECS = 26 * 3600  # 26 hours

def ddb_cache_get(cache_key: str):
    """Read a pre-computed result from DynamoDB. Returns None on miss/expiry."""
    try:
        resp = table.get_item(Key={"pk": CACHE_PK, "sk": f"TOOL#{cache_key}"})
        item = resp.get("Item")
        if not item:
            return None
        ttl = item.get("ttl_epoch")
        if ttl and float(ttl) < time.time():
            logger.info(f"[cache:ddb] stale — {cache_key}")
            return None
        payload = item.get("payload")
        if payload:
            logger.info(f"[cache:ddb] hit — {cache_key}")
            return json.loads(payload)
    except Exception as e:
        logger.warning(f"[cache:ddb] read error for {cache_key}: {e}")
    return None

def ddb_cache_set(cache_key: str, data):
    """Write a pre-computed result to DynamoDB cache with a TTL."""
    try:
        ttl_epoch = int(time.time()) + CACHE_TTL_SECS
        table.put_item(Item={
            "pk":           CACHE_PK,
            "sk":           f"TOOL#{cache_key}",
            "payload":      json.dumps(data, default=str),
            "ttl_epoch":    Decimal(str(ttl_epoch)),
            "computed_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        logger.info(f"[cache:ddb] stored — {cache_key}")
    except Exception as e:
        logger.warning(f"[cache:ddb] write error for {cache_key}: {e}")


# ── Serialisation helpers ─────────────────────────────────────────────────────
def decimal_to_float(obj):
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    if isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def get_api_key():
    try:
        return secrets.get_secret_value(SecretId=API_SECRET_NAME)["SecretString"]
    except Exception as e:
        logger.warning(f"Could not retrieve API key: {e}")
        return None


# ── DynamoDB query with full pagination ───────────────────────────────────────
# Fields that are never numeric and are expensive to transfer (large arrays).
# Stripped post-fetch for any path that only needs numeric aggregation.
_LEAN_STRIP = {"activities", "sport_types", "pk", "sk", "ingested_at", "source"}


def query_source(source, start_date, end_date, lean=False):
    """Query DynamoDB by source + date range with full pagination.
    lean=True: strip large non-numeric fields post-fetch (saves ~30-50% RAM
    for Strava which embeds full activity objects in each day record).
    """
    pk = f"{USER_PREFIX}{source}"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}~"
        )
    }
    items = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
        logger.info(f"query_source paginating {source}: {len(items)} items so far")
    raw = decimal_to_float(items)
    if lean:
        return [{k: v for k, v in item.items() if k not in _LEAN_STRIP} for item in raw]
    return raw


def parallel_query_sources(sources, start_date, end_date, lean=False):
    """Query multiple DynamoDB sources concurrently. Returns {source: [items]}.
    lean=True: strip non-numeric/large fields post-fetch (see query_source)."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sources), 5)) as pool:
        future_to_src = {
            pool.submit(query_source, src, start_date, end_date, lean): src
            for src in sources
        }
        for future in concurrent.futures.as_completed(future_to_src):
            src = future_to_src[future]
            try:
                results[src] = future.result()
            except Exception as e:
                logger.warning(f"parallel_query_sources failed for {src}: {e}")
                results[src] = []
    return results


def date_diff_days(start, end):
    try:
        return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    except Exception:
        return 0


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


def resolve_field(source, field):
    aliases = FIELD_ALIASES.get(source, {})
    return aliases.get(field, field)


def flatten_strava_activity(day_record):
    """Flatten a Strava day record + nested activities into one dict per activity."""
    activities = day_record.get("activities", [])
    result = []
    for act in activities:
        sport_type = act.get("sport_type") or act.get("type") or ""
        flat = {
            "date":                      day_record.get("date"),
            "name":                      act.get("name"),
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


# ── Tool implementations ──────────────────────────────────────────────────────

def tool_get_sources(_args):
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        oldest = table.query(
            KeyConditionExpression=Key("pk").eq(pk), Limit=1, ScanIndexForward=True,
            ProjectionExpression="#dt", ExpressionAttributeNames={"#dt": "date"},
        )
        newest = table.query(
            KeyConditionExpression=Key("pk").eq(pk), Limit=1, ScanIndexForward=False,
            ProjectionExpression="#dt", ExpressionAttributeNames={"#dt": "date"},
        )
        first = oldest["Items"][0]["date"] if oldest["Items"] else None
        last  = newest["Items"][0]["date"] if newest["Items"] else None
        result[source] = {"available": first is not None, "first_date": first, "latest_date": last}
    return result


def tool_get_latest(args):
    sources = args.get("sources", SOURCES)
    result  = {}
    for source in sources:
        pk = f"{USER_PREFIX}{source}"
        response = table.query(KeyConditionExpression=Key("pk").eq(pk), Limit=1, ScanIndexForward=False)
        items = decimal_to_float(response.get("Items", []))
        result[source] = items[0] if items else None
    return result


def tool_get_daily_summary(args):
    date = args.get("date")
    if not date:
        raise ValueError("'date' is required (YYYY-MM-DD)")
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        response = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(f"DATE#{date}")
        )
        items = decimal_to_float(response.get("Items", []))
        if items:
            result[source] = items
    return result


def tool_get_date_range(args):
    source     = args.get("source")
    start_date = args.get("start_date")
    end_date   = args.get("end_date")
    if not all([source, start_date, end_date]):
        raise ValueError("'source', 'start_date', and 'end_date' are required")
    if source not in SOURCES:
        raise ValueError(f"Unknown source '{source}'. Valid: {SOURCES}")

    days  = date_diff_days(start_date, end_date)
    items = query_source(source, start_date, end_date)

    if days > RAW_DAY_LIMIT:
        period = "year" if days > 365 * 2 else "month"
        return {
            "note":       f"Window of {days} days — returning {period}ly aggregates.",
            "period":     period,
            "source":     source,
            "aggregated": aggregate_items(items, period),
        }

    return {"note": "Raw daily data.", "source": source, "items": items}


def tool_find_days(args):
    source     = args.get("source")
    start_date = args.get("start_date")
    end_date   = args.get("end_date")
    filters    = args.get("filters", [])
    if not all([source, start_date, end_date]):
        raise ValueError("'source', 'start_date', and 'end_date' are required")

    items = query_source(source, start_date, end_date)

    def passes(item):
        for f in filters:
            field  = resolve_field(source, f["field"])
            actual = item.get(field)
            if actual is None:
                return False
            actual = float(actual)
            value  = float(f["value"])
            op     = f["op"]
            if op == ">"  and not actual >  value: return False
            if op == ">=" and not actual >= value: return False
            if op == "<"  and not actual <  value: return False
            if op == "<=" and not actual <= value: return False
            if op == "="  and not actual == value: return False
        return True

    matched = [item for item in items if passes(item)]

    if len(matched) > 200:
        key_fields = {"date", "recovery_score", "hrv", "strain", "weight_lbs",
                      "sleep_duration_hours", "resting_heart_rate",
                      "total_distance_miles", "total_elevation_gain_feet", "sport_types"}
        matched = [{k: v for k, v in m.items() if k in key_fields} for m in matched]

    return matched


def tool_get_aggregated_summary(args):
    source   = args.get("source")
    period   = args.get("period", "year")
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    if period not in ("month", "year"):
        raise ValueError("'period' must be 'month' or 'year'")

    if source and source in SOURCES:
        default_start = "2010-01-01"
    else:
        if period == "year":
            default_start = (datetime.utcnow() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
        else:
            default_start = (datetime.utcnow() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")

    start_date = args.get("start_date", default_start)
    sources_to_query = [source] if source and source in SOURCES else SOURCES

    cache_key = f"aggregated_summary_{period}_{start_date}_{end_date}_{','.join(sources_to_query)}"
    cached = ddb_cache_get(cache_key) or mem_cache_get(cache_key)
    if cached:
        return cached

    if len(sources_to_query) > 1:
        source_data = parallel_query_sources(sources_to_query, start_date, end_date, lean=True)
    else:
        source_data = {sources_to_query[0]: query_source(sources_to_query[0], start_date, end_date, lean=True)}

    result = {}
    for src, items in source_data.items():
        if items:
            result[src] = aggregate_items(items, period)

    payload = {
        "period":     period,
        "start_date": start_date,
        "end_date":   end_date,
        "note":       "Pass an explicit start_date to override the default window." if not args.get("start_date") else None,
        "sources":    result,
    }
    mem_cache_set(cache_key, payload)
    return payload


def tool_search_activities(args):
    start_date    = args.get("start_date", "2010-01-01")
    end_date      = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    name_contains = args.get("name_contains", "").lower()
    sport_type    = args.get("sport_type", "").lower()
    min_distance  = args.get("min_distance_miles")
    min_elevation = args.get("min_elevation_gain_feet")
    sort_by       = args.get("sort_by", "distance_miles")
    limit         = int(args.get("limit", 100))

    day_records = query_source("strava", start_date, end_date)

    all_activities = []
    for day in day_records:
        all_activities.extend(flatten_strava_activity(day))

    all_sort_vals = sorted(
        [float(a.get(sort_by, 0) or 0) for a in all_activities if a.get(sort_by) is not None]
    )
    total_for_rank = len(all_sort_vals)

    def percentile_rank(val):
        if total_for_rank == 0:
            return None
        pos = bisect.bisect_left(all_sort_vals, float(val))
        return round(100.0 * pos / total_for_rank, 1)

    matched = []
    for act in all_activities:
        if name_contains and name_contains not in (act.get("name") or "").lower():
            continue
        if sport_type and sport_type not in (act.get("sport_type") or "").lower():
            continue
        if min_distance is not None:
            dist = act.get("distance_miles")
            if dist is None or float(dist) < float(min_distance):
                continue
        if min_elevation is not None:
            elev = act.get("total_elevation_gain_feet")
            if elev is None or float(elev) < float(min_elevation):
                continue
        matched.append(act)

    matched.sort(key=lambda x: float(x.get(sort_by, 0) or 0), reverse=True)

    results = []
    for act in matched[:limit]:
        enriched = dict(act)
        sort_val = act.get(sort_by)
        if sort_val is not None:
            pct = percentile_rank(sort_val)
            enriched[f"{sort_by}_all_time_percentile"] = pct
            if pct is not None:
                if pct >= 99:
                    enriched["context"] = f"ALL-TIME top 1% for {sort_by}"
                elif pct >= 95:
                    enriched["context"] = f"Top 5% all-time for {sort_by}"
                elif pct >= 90:
                    enriched["context"] = f"Top 10% all-time for {sort_by}"
        results.append(enriched)

    return {
        "total_matched":       len(matched),
        "showing":             len(results),
        "sorted_by":           sort_by,
        "all_time_total_acts": total_for_rank,
        "activities":          results,
    }


def tool_get_field_stats(args):
    source     = args.get("source")
    field      = args.get("field")
    start_date = args.get("start_date", "2010-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    if not source or not field:
        raise ValueError("'source' and 'field' are required")
    if source not in SOURCES:
        raise ValueError(f"Unknown source '{source}'. Valid: {SOURCES}")

    items = query_source(source, start_date, end_date)
    resolved_field = resolve_field(source, field)

    values = []
    for item in sorted(items, key=lambda x: x.get("date", "")):
        if "#WORKOUT#" in item.get("sk", ""):
            continue
        val = item.get(resolved_field)
        if val is not None:
            values.append((round(float(val), 2), item.get("date", "unknown")))

    if not values:
        return {"source": source, "field": resolved_field,
                "message": "No data found for this field in the specified range."}

    nums    = [v for v, _ in values]
    max_val = max(nums)
    min_val = min(nums)
    avg_val = round(sum(nums) / len(nums), 2)

    sorted_desc = sorted(values, key=lambda x: x[0], reverse=True)
    sorted_asc  = sorted(values, key=lambda x: x[0])
    top5_high   = [{"value": v, "date": d} for v, d in sorted_desc[:5]]
    top5_low    = [{"value": v, "date": d} for v, d in sorted_asc[:5]]

    third = max(1, len(values) // 3)
    early_avg = round(sum(v for v, _ in values[:third]) / third, 2)
    late_avg  = round(sum(v for v, _ in values[-third:]) / third, 2)
    delta     = round(late_avg - early_avg, 2)
    if abs(delta) < 0.5:
        trend = "stable"
    elif delta > 0:
        trend = f"increasing (+{delta} from early to recent average)"
    else:
        trend = f"decreasing ({delta} from early to recent average)"

    return {
        "source":           source,
        "field":            resolved_field,
        "start_date":       start_date,
        "end_date":         end_date,
        "count":            len(nums),
        "max":              max_val,
        "max_dates":        [d for v, d in values if v == max_val],
        "min":              min_val,
        "min_dates":        [d for v, d in values if v == min_val],
        "avg":              avg_val,
        "top5_highest":     top5_high,
        "top5_lowest":      top5_low,
        "trend":            trend,
        "early_period_avg": early_avg,
        "recent_period_avg":late_avg,
        "storytelling_tip": "Pair with get_aggregated_summary (period=year) for the full arc.",
    }


def tool_compare_periods(args):
    pa_start = args.get("period_a_start")
    pa_end   = args.get("period_a_end")
    pb_start = args.get("period_b_start")
    pb_end   = args.get("period_b_end")
    pa_label = args.get("period_a_label", "Period A")
    pb_label = args.get("period_b_label", "Period B")
    source   = args.get("source")

    if not all([pa_start, pa_end, pb_start, pb_end]):
        raise ValueError("period_a_start, period_a_end, period_b_start, period_b_end are all required")

    sources_to_query = [source] if source and source in SOURCES else SOURCES
    skip_fields = {"pk", "sk", "source", "ingested_at", "date", "activities", "sport_types"}

    result = {
        "period_a": {"label": pa_label, "start": pa_start, "end": pa_end},
        "period_b": {"label": pb_label, "start": pb_start, "end": pb_end},
        "sources":  {}
    }

    for src in sources_to_query:
        items_a = query_source(src, pa_start, pa_end)
        items_b = query_source(src, pb_start, pb_end)
        if not items_a and not items_b:
            continue

        def field_avgs(items):
            buckets = defaultdict(list)
            for item in items:
                if "#WORKOUT#" in item.get("sk", ""):
                    continue
                for k, v in item.items():
                    if k not in skip_fields and isinstance(v, (int, float)):
                        buckets[k].append(float(v))
            return {k: round(sum(v) / len(v), 2) for k, v in buckets.items() if v}

        avgs_a = field_avgs(items_a)
        avgs_b = field_avgs(items_b)
        all_fields = sorted(set(avgs_a) | set(avgs_b))

        comparisons = {}
        for field in all_fields:
            val_a = avgs_a.get(field)
            val_b = avgs_b.get(field)
            row = {pa_label: val_a, pb_label: val_b}
            if val_a is not None and val_b is not None:
                delta = round(val_b - val_a, 2)
                pct   = round(100.0 * delta / val_a, 1) if val_a != 0 else None
                row["delta"]     = delta
                row["pct_change"]= pct
                row["direction"] = "improved" if delta > 0 else ("declined" if delta < 0 else "unchanged")
            comparisons[field] = row

        result["sources"][src] = {
            "days_in_period_a": len(items_a),
            "days_in_period_b": len(items_b),
            "fields": comparisons,
        }

    return result


def tool_get_weekly_summary(args):
    start_date = args.get("start_date", "2000-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    sort_by    = args.get("sort_by", "total_distance_miles")
    limit      = int(args.get("limit", 52))
    sort_asc   = args.get("sort_ascending", False)

    day_records = query_source("strava", start_date, end_date)

    weeks = defaultdict(lambda: {
        "total_distance_miles": 0.0,
        "total_elevation_gain_feet": 0.0,
        "total_moving_time_seconds": 0,
        "activity_count": 0,
        "days_active": 0,
        "sport_types": defaultdict(int),
        "dates": [],
    })

    for day in day_records:
        date_str = day.get("date", "")
        if not date_str:
            continue
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        except ValueError:
            continue

        w = weeks[key]
        w["total_distance_miles"]      += float(day.get("total_distance_miles") or 0)
        w["total_elevation_gain_feet"] += float(day.get("total_elevation_gain_feet") or 0)
        w["total_moving_time_seconds"] += int(day.get("total_moving_time_seconds") or 0)
        w["activity_count"]            += int(day.get("activity_count") or 0)
        w["days_active"]               += 1
        w["dates"].append(date_str)
        for st in (day.get("sport_types") or []):
            if st:
                w["sport_types"][st] += 1

    rows = []
    for week_key, w in weeks.items():
        rows.append({
            "week":                      week_key,
            "week_start":                min(w["dates"]) if w["dates"] else "",
            "week_end":                  max(w["dates"]) if w["dates"] else "",
            "total_distance_miles":      round(w["total_distance_miles"], 2),
            "total_elevation_gain_feet": round(w["total_elevation_gain_feet"], 1),
            "total_moving_time_seconds": w["total_moving_time_seconds"],
            "activity_count":            w["activity_count"],
            "days_active":               w["days_active"],
            "sport_types":               dict(w["sport_types"]),
        })

    rows.sort(key=lambda x: x.get(sort_by, 0), reverse=not sort_asc)

    return {
        "total_weeks_with_data": len(rows),
        "sorted_by":             sort_by,
        "weeks":                 rows[:limit],
    }


def tool_get_training_load(args):
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_dt   = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=180)
    start_date = args.get("start_date", start_dt.strftime("%Y-%m-%d"))
    warmup_dt  = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=84)
    warmup_start = warmup_dt.strftime("%Y-%m-%d")

    day_records = query_source("strava", warmup_start, end_date)

    load_by_date = {}
    for day in day_records:
        d = day.get("date")
        if d:
            load_by_date[d] = compute_daily_load_score(day)

    cur = warmup_dt
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    chrono = []
    while cur <= end_dt:
        ds = cur.strftime("%Y-%m-%d")
        chrono.append((ds, load_by_date.get(ds, 0.0)))
        cur += timedelta(days=1)

    ctl_series = compute_ewa(chrono, 42)
    atl_series = compute_ewa(chrono, 7)

    start_dt_req = datetime.strptime(start_date, "%Y-%m-%d")
    result_rows = []
    for (date_str, ctl), (_, atl) in zip(ctl_series, atl_series):
        if datetime.strptime(date_str, "%Y-%m-%d") < start_dt_req:
            continue
        tsb  = round(ctl - atl, 2)
        acwr = round(atl / ctl, 2) if ctl > 0 else None

        risk = "low"
        if acwr is not None:
            if acwr > 1.5:
                risk = "HIGH — injury risk elevated, consider reducing load"
            elif acwr > 1.3:
                risk = "moderate — monitor carefully"

        form = "neutral"
        if tsb > 5:
            form = "fresh — good for key sessions or race"
        elif tsb < -10:
            form = "fatigued — accumulated training stress is high"
        elif tsb < -25:
            form = "very fatigued — recovery priority"

        result_rows.append({
            "date":           date_str,
            "daily_load":     round(load_by_date.get(date_str, 0.0), 1),
            "ctl_fitness":    ctl,
            "atl_fatigue":    atl,
            "tsb_form":       tsb,
            "acwr":           acwr,
            "injury_risk":    risk,
            "form_status":    form,
        })

    if not result_rows:
        return {"message": "No training data found for the requested window."}

    latest = result_rows[-1]
    peak_ctl = max(result_rows, key=lambda r: r["ctl_fitness"])
    return {
        "model":          "Banister Impulse-Response (CTL=42d EWA, ATL=7d EWA)",
        "load_proxy":     "kJ (cycling) > TRIMP (HR×time) > distance+elevation estimate",
        "current_state":  latest,
        "peak_fitness":   {"ctl": peak_ctl["ctl_fitness"], "date": peak_ctl["date"]},
        "series":         result_rows,
        "interpretation": {
            "CTL": "Fitness base (42-day). Higher = more aerobic capacity built.",
            "ATL": "Fatigue (7-day). Spikes after big training blocks.",
            "TSB": "Form = CTL - ATL. Positive = fresh, negative = tired.",
            "ACWR": "Acute:Chronic ratio. >1.3 caution, >1.5 injury risk.",
        },
    }


def tool_get_personal_records(args):
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    profile  = get_profile()
    dob_str  = profile.get("date_of_birth")

    def age_at(date_str):
        if not dob_str or not date_str:
            return None
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d")
            d   = datetime.strptime(date_str, "%Y-%m-%d")
            return round((d - dob).days / 365.25, 1)
        except Exception:
            return None

    records = {}

    pr_cache_key = f"personal_records_{end_date}"
    cached = ddb_cache_get(pr_cache_key) or mem_cache_get(pr_cache_key)
    if cached:
        return cached

    pr_sources = parallel_query_sources(["strava", "whoop", "withings"], "2000-01-01", end_date)

    strava_days = pr_sources.get("strava", [])
    all_acts    = []
    for day in strava_days:
        all_acts.extend(flatten_strava_activity(day))

    act_fields = {
        "longest_activity_miles":         ("distance_miles",            "max"),
        "most_elevation_gain_feet":        ("total_elevation_gain_feet", "max"),
        "longest_moving_time_seconds":     ("moving_time_seconds",       "max"),
        "highest_avg_heartrate_bpm":       ("average_heartrate",         "max"),
        "highest_max_heartrate_bpm":       ("max_heartrate",             "max"),
        "highest_avg_watts":               ("average_watts",             "max"),
        "most_kilojoules":                 ("kilojoules",                "max"),
        "most_prs_in_one_activity":        ("pr_count",                  "max"),
    }

    for label, (field, mode) in act_fields.items():
        candidates = [(float(a[field]), a) for a in all_acts if a.get(field) is not None]
        if not candidates:
            continue
        best_val, best_act = max(candidates, key=lambda x: x[0])
        records[label] = {
            "value":      round(best_val, 2),
            "date":       best_act.get("date"),
            "activity":   best_act.get("name"),
            "sport_type": best_act.get("sport_type"),
            "age_at_record": age_at(best_act.get("date")),
        }

    day_fields = {
        "biggest_day_miles":     ("total_distance_miles",      "max"),
        "biggest_day_elevation": ("total_elevation_gain_feet", "max"),
        "most_activities_in_day":("activity_count",            "max"),
    }
    for label, (field, mode) in day_fields.items():
        candidates = [(float(d[field]), d) for d in strava_days if d.get(field)]
        if not candidates:
            continue
        best_val, best_day = max(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    weeks = defaultdict(lambda: {"miles": 0.0, "elev": 0.0, "dates": []})
    for day in strava_days:
        date_str = day.get("date", "")
        if not date_str:
            continue
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        except ValueError:
            continue
        weeks[key]["miles"] += float(day.get("total_distance_miles") or 0)
        weeks[key]["elev"]  += float(day.get("total_elevation_gain_feet") or 0)
        weeks[key]["dates"].append(date_str)

    if weeks:
        best_week_miles = max(weeks.items(), key=lambda x: x[1]["miles"])
        best_week_elev  = max(weeks.items(), key=lambda x: x[1]["elev"])
        records["biggest_week_miles"] = {
            "value": round(best_week_miles[1]["miles"], 2),
            "week":  best_week_miles[0],
            "week_start": min(best_week_miles[1]["dates"]),
            "age_at_record": age_at(min(best_week_miles[1]["dates"])),
        }
        records["biggest_week_elevation_feet"] = {
            "value": round(best_week_elev[1]["elev"], 1),
            "week":  best_week_elev[0],
            "week_start": min(best_week_elev[1]["dates"]),
            "age_at_record": age_at(min(best_week_elev[1]["dates"])),
        }

    whoop_days = pr_sources.get("whoop", [])
    whoop_fields = {
        "best_hrv_ms":              ("hrv",                 "max"),
        "lowest_resting_hr_bpm":    ("resting_heart_rate",  "min"),
        "best_recovery_score":      ("recovery_score",      "max"),
        "highest_strain":           ("strain",              "max"),
        "longest_sleep_hours":      ("sleep_duration_hours","max"),
        "worst_recovery_score":     ("recovery_score",      "min"),
    }
    for label, (field, mode) in whoop_fields.items():
        candidates = [(float(d[field]), d) for d in whoop_days if d.get(field) is not None]
        if not candidates:
            continue
        best_val, best_day = (max if mode == "max" else min)(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    withings_days = pr_sources.get("withings", [])
    withings_fields = {
        "heaviest_weight_lbs":   ("weight_lbs", "max"),
        "lightest_weight_lbs":   ("weight_lbs", "min"),
        "lowest_body_fat_pct":   ("body_fat_percentage", "min"),
        "highest_muscle_mass_lbs": ("muscle_mass_lbs", "max"),
    }
    for label, (field, mode) in withings_fields.items():
        candidates = [(float(d[field]), d) for d in withings_days if d.get(field) is not None]
        if not candidates:
            continue
        best_val, best_day = (max if mode == "max" else min)(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    payload = {
        "profile_dob":    dob_str,
        "records_through": end_date,
        "total_records":  len(records),
        "records":        records,
        "coaching_note":  "Age at record enables tracking whether peak performances are trending younger or older over time.",
    }
    ddb_cache_set(pr_cache_key, payload)
    mem_cache_set(pr_cache_key, payload)
    return payload


def tool_get_cross_source_correlation(args):
    source_a   = args.get("source_a")
    field_a    = args.get("field_a")
    source_b   = args.get("source_b")
    field_b    = args.get("field_b")
    start_date = args.get("start_date", "2019-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    lag_days   = int(args.get("lag_days", 0))

    if not all([source_a, field_a, source_b, field_b]):
        raise ValueError("source_a, field_a, source_b, field_b are all required")

    lag_end_dt  = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=abs(lag_days))
    lag_end     = lag_end_dt.strftime("%Y-%m-%d")

    items_a = query_source(source_a, start_date, lag_end)
    items_b = query_source(source_b, start_date, lag_end)

    fa = resolve_field(source_a, field_a)
    fb = resolve_field(source_b, field_b)

    dict_a = {}
    for item in items_a:
        d = item.get("date")
        v = item.get(fa)
        if d and v is not None:
            dict_a[d] = float(v)

    dict_b = {}
    for item in items_b:
        d = item.get("date")
        v = item.get(fb)
        if d and v is not None:
            dict_b[d] = float(v)

    pairs = []
    for date_str, val_a in sorted(dict_a.items()):
        if date_str > end_date:
            continue
        try:
            shifted = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
        except Exception:
            continue
        val_b = dict_b.get(shifted)
        if val_b is not None:
            pairs.append((date_str, val_a, val_b))

    if len(pairs) < 10:
        return {
            "error": f"Insufficient overlapping data points ({len(pairs)}). Try a wider date range or different sources."
        }

    xs = [p[1] for p in pairs]
    ys = [p[2] for p in pairs]
    r  = pearson_r(xs, ys)

    if r is None:
        interpretation = "Cannot compute (zero variance in one series)"
    else:
        abs_r = abs(r)
        direction = "positive" if r > 0 else "negative"
        if abs_r >= 0.7:
            strength = "strong"
        elif abs_r >= 0.4:
            strength = "moderate"
        elif abs_r >= 0.2:
            strength = "weak"
        else:
            strength = "negligible"
        interpretation = f"{strength} {direction} correlation"

    return {
        "source_a":       source_a,
        "field_a":        fa,
        "source_b":       source_b,
        "field_b":        fb,
        "lag_days":       lag_days,
        "lag_note":       f"Positive lag: does {fa} today predict {fb} in {lag_days} days?" if lag_days > 0 else "No lag — same-day relationship",
        "start_date":     start_date,
        "end_date":       end_date,
        "n_paired_days":  len(pairs),
        "pearson_r":      r,
        "r_squared":      round(r**2, 3) if r is not None else None,
        "interpretation": interpretation,
        "mean_a":         round(sum(xs)/len(xs), 2),
        "mean_b":         round(sum(ys)/len(ys), 2),
        "coaching_note":  "r > 0.4 is practically meaningful for coaching. r² tells you what % of variance is explained.",
    }


def tool_get_seasonal_patterns(args):
    source     = args.get("source")
    start_date = args.get("start_date", "2010-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    sources_to_query = [source] if source and source in SOURCES else SOURCES
    skip_fields = {"pk", "sk", "source", "ingested_at", "date", "activities", "sport_types"}

    month_names = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                   7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

    cache_key = f"seasonal_patterns_{start_date}_{end_date}_{','.join(sources_to_query)}"
    cached = ddb_cache_get(cache_key) or mem_cache_get(cache_key)
    if cached:
        return cached

    if len(sources_to_query) > 1:
        source_data = parallel_query_sources(sources_to_query, start_date, end_date, lean=True)
    else:
        source_data = {sources_to_query[0]: query_source(sources_to_query[0], start_date, end_date, lean=True)}

    result = {}
    for src in sources_to_query:
        items = source_data.get(src, [])
        if not items:
            continue

        month_buckets = defaultdict(lambda: defaultdict(list))
        year_counts   = defaultdict(set)

        for item in items:
            if "#WORKOUT#" in item.get("sk", ""):
                continue
            date_str = item.get("date", "")
            if not date_str or len(date_str) < 7:
                continue
            try:
                month = int(date_str[5:7])
                year  = date_str[:4]
            except ValueError:
                continue
            year_counts[month].add(year)
            for field, value in item.items():
                if field in skip_fields:
                    continue
                if isinstance(value, (int, float)):
                    month_buckets[month][field].append(float(value))

        months_result = []
        for m in range(1, 13):
            if m not in month_buckets:
                continue
            row = {
                "month":         m,
                "month_name":    month_names[m],
                "years_of_data": len(year_counts[m]),
            }
            for field, values in month_buckets[m].items():
                row[f"{field}_avg"] = round(sum(values) / len(values), 2)
                row[f"{field}_min"] = round(min(values), 2)
                row[f"{field}_max"] = round(max(values), 2)
            months_result.append(row)

        result[src] = months_result

    seasonal_payload = {
        "start_date": start_date,
        "end_date":   end_date,
        "note":       "Months averaged across all available years. 'years_of_data' shows how many years contribute to each month.",
        "sources":    result,
    }
    mem_cache_set(cache_key, seasonal_payload)
    ddb_cache_set(cache_key, seasonal_payload)
    return seasonal_payload


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

    return {
        "summary":          summary,
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


# ── Tool registry ─────────────────────────────────────────────────────────────
TOOLS = {
    "get_sources": {
        "fn": tool_get_sources,
        "schema": {
            "name": "get_sources",
            "description": "List all available data sources and their date ranges in the life platform.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_latest": {
        "fn": tool_get_latest,
        "schema": {
            "name": "get_latest",
            "description": "Get the most recent record(s) for one or more sources. Useful for current status checks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sources": {"type": "array", "items": {"type": "string"},
                                "description": f"List of sources to fetch. Defaults to all. Valid: {SOURCES}"}
                },
                "required": [],
            },
        },
    },
    "get_daily_summary": {
        "fn": tool_get_daily_summary,
        "schema": {
            "name": "get_daily_summary",
            "description": "Get all available data across every source for a single date. Best starting point for 'how was my day/yesterday?' questions.",
            "inputSchema": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "Date in YYYY-MM-DD format."}},
                "required": ["date"],
            },
        },
    },
    "get_date_range": {
        "fn": tool_get_date_range,
        "schema": {
            "name": "get_date_range",
            "description": f"Get time-series records for a single source. Returns raw daily data for windows up to {RAW_DAY_LIMIT} days, monthly aggregates beyond that. Use get_aggregated_summary for multi-year trends.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (inclusive)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (inclusive)."},
                },
                "required": ["source", "start_date", "end_date"],
            },
        },
    },
    "find_days": {
        "fn": tool_find_days,
        "schema": {
            "name": "find_days",
            "description": "Find days within a date range where numeric fields meet filter conditions. For Strava, use field names: 'total_distance_miles', 'total_elevation_gain_feet'. For Whoop: 'hrv', 'recovery_score', 'strain'. Great for correlations. IMPORTANT: This tool operates on day-level aggregates only — it cannot search inside individual activity names or sport types. For any query involving specific activity names, first/longest/highest achievements, named events, or sport-type filtering, you MUST use search_activities instead.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "filters": {
                        "type": "array",
                        "description": "List of field filter conditions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op":    {"type": "string", "enum": [">", ">=", "<", "<=", "="]},
                                "value": {"type": "number"},
                            },
                            "required": ["field", "op", "value"],
                        },
                    },
                },
                "required": ["source", "start_date", "end_date"],
            },
        },
    },
    "get_aggregated_summary": {
        "fn": tool_get_aggregated_summary,
        "schema": {
            "name": "get_aggregated_summary",
            "description": "Get monthly or yearly averages across any date range. Use this for long-horizon questions like 'summarize my health history' or 'how has my weight trended over the years'. Returns avg/min/max per period per source.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Optional. If omitted all sources included. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "period":     {"type": "string", "enum": ["month", "year"],
                                   "description": "Use 'year' for multi-year history, 'month' for 1-3 year windows."},
                },
                "required": [],
            },
        },
    },
    "get_field_stats": {
        "fn": tool_get_field_stats,
        "schema": {
            "name": "get_field_stats",
            "description": "Get rich stats for a numeric field: min/max/avg/count, dates of the all-time peak and trough, top-5 highest and top-5 lowest readings with dates, and a trend direction. Use this to find actual historical peaks rather than guessing AND to build a narrative arc. Examples: 'what was my heaviest weight ever?' (source=withings, field=weight_lbs), 'best HRV day' (source=whoop, field=hrv), 'lowest resting heart rate' (source=whoop, field=resting_heart_rate). Always prefer this over get_aggregated_summary when the user asks about a specific extreme value or record. For full narrative context, follow up with get_aggregated_summary (period=year) to show the trend between the peaks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "field":      {"type": "string", "description": "The numeric field name to analyze. E.g. 'weight_lbs', 'hrv', 'recovery_score', 'resting_heart_rate', 'total_distance_miles'."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01 (all-time)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["source", "field"],
            },
        },
    },
    "search_activities": {
        "fn": tool_search_activities,
        "schema": {
            "name": "search_activities",
            "description": "Search Strava activities by name keyword, sport type, minimum distance, or minimum elevation gain. ALWAYS use this tool (not find_days) for: named activities ('first century', 'mailbox peak', 'machu picchu'), achievement queries (longest run, biggest hike, first 100-mile ride), or sorting by distance/elevation to find top efforts. CRITICAL: Do NOT filter by sport_type when looking for longest/biggest/most impressive efforts — long walks and hikes count equally to runs and should be included. Only pass sport_type if the user explicitly asks for a specific type (e.g. 'my longest run' vs 'my longest activity'). Results include an all-time percentile rank and a context flag for exceptional values so you can narrate how remarkable the effort was.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":              {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date":                {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "name_contains":           {"type": "string", "description": "Keyword to search in activity name (case-insensitive). E.g. 'machu', 'half marathon', 'trail'."},
                    "sport_type":              {"type": "string", "description": "Filter by sport type (case-insensitive). Common values: 'Run', 'Walk', 'Hike', 'Ride', 'VirtualRide', 'WeightTraining'."},
                    "min_distance_miles":      {"type": "number", "description": "Only return activities with distance >= this value in miles."},
                    "min_elevation_gain_feet": {"type": "number", "description": "Only return activities with elevation gain >= this value in feet."},
                    "sort_by":                 {"type": "string", "description": "Field to sort results by descending. Options: 'distance_miles', 'total_elevation_gain_feet', 'moving_time_seconds', 'kilojoules'. Default: 'distance_miles'."},
                    "limit":                   {"type": "number", "description": "Max results to return. Default 100."},
                },
                "required": [],
            },
        },
    },
    "compare_periods": {
        "fn": tool_compare_periods,
        "schema": {
            "name": "compare_periods",
            "description": "Side-by-side comparison of two date ranges across one or all sources. Returns per-field averages for both periods plus delta and % change. Use for benchmarking questions: 'how does my fitness now compare to my 2022 peak?', 'was I more active this year vs last year?', 'did my HRV improve after I started running more?'. Label your periods meaningfully (e.g. 'Peak 2022', 'Current').",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period_a_start": {"type": "string", "description": "Start date of period A (YYYY-MM-DD)."},
                    "period_a_end":   {"type": "string", "description": "End date of period A (YYYY-MM-DD)."},
                    "period_b_start": {"type": "string", "description": "Start date of period B (YYYY-MM-DD)."},
                    "period_b_end":   {"type": "string", "description": "End date of period B (YYYY-MM-DD)."},
                    "period_a_label": {"type": "string", "description": "Human-readable label for period A. E.g. 'Peak 2022', 'Pre-injury', 'Last year'."},
                    "period_b_label": {"type": "string", "description": "Human-readable label for period B. E.g. 'Current', 'Post-injury', 'This year'."},
                    "source":         {"type": "string", "description": f"Optional. Limit to one source. Valid: {SOURCES}. Omit to compare all sources."},
                },
                "required": ["period_a_start", "period_a_end", "period_b_start", "period_b_end"],
            },
        },
    },
    "get_weekly_summary": {
        "fn": tool_get_weekly_summary,
        "schema": {
            "name": "get_weekly_summary",
            "description": "Group Strava activities into ISO calendar weeks and return per-week totals (distance, elevation, time, activity count, sport type breakdown). Use for training load questions: 'what was my biggest training week ever?', 'show my weekly mileage this year', 'what were my top 10 highest mileage weeks?'. Sort by distance (default), elevation, or time. Chronological order available via sort_ascending=true for trend analysis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":     {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2000-01-01 (all-time)."},
                    "end_date":       {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "sort_by":        {"type": "string", "description": "Field to sort weeks by. Options: 'total_distance_miles' (default), 'total_elevation_gain_feet', 'total_moving_time_seconds', 'activity_count'."},
                    "limit":          {"type": "number", "description": "Max weeks to return. Default 52."},
                    "sort_ascending": {"type": "boolean", "description": "Set true for chronological order (trend view). Default false (best weeks first)."},
                },
                "required": [],
            },
        },
    },
    "get_training_load": {
        "fn": tool_get_training_load,
        "schema": {
            "name": "get_training_load",
            "description": "Compute the Banister fitness-fatigue model: CTL (42-day fitness), ATL (7-day fatigue), TSB (form = CTL-ATL), and ACWR (injury risk ratio). Use for: 'how fit am I right now?', 'am I overtraining?', 'am I ready for a race?', 'when was my peak fitness?', 'what is my injury risk?'. ACWR > 1.3 = caution, > 1.5 = danger. TSB positive = fresh, negative = fatigued. Returns a full time series plus current state summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 6 months ago."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_personal_records": {
        "fn": tool_get_personal_records,
        "schema": {
            "name": "get_personal_records",
            "description": "All-time personal records (PRs) across every measurable dimension — the athlete's trophy case. Includes: longest activity, most elevation, biggest week, best HRV, lowest resting HR, best recovery score, heaviest/lightest weight, lowest body fat, and more. Each record includes the date it was set and age at the time (requires profile DOB). Use for: 'what are my all-time best performances?', 'when was I fittest?', 'what are my PRs?', 'have I ever run further than X miles?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date": {"type": "string", "description": "Only consider records up to this date. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_cross_source_correlation": {
        "fn": tool_get_cross_source_correlation,
        "schema": {
            "name": "get_cross_source_correlation",
            "description": "Pearson correlation between any two numeric metrics, with optional day lag. The coaching superpower — reveals hidden relationships in your data. Examples: 'does HRV predict next-day training output?' (source_a=whoop, field_a=hrv, source_b=strava, field_b=total_distance_miles, lag_days=1), 'does work stress suppress recovery?' (source_a=todoist, field_a=tasks_completed, source_b=whoop, field_b=recovery_score), 'does weight track with training volume?' (source_a=withings, field_a=weight_lbs, source_b=strava, field_b=total_distance_miles). r > 0.4 is practically meaningful.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_a":   {"type": "string", "description": f"First data source. Valid: {SOURCES}"},
                    "field_a":    {"type": "string", "description": "Field from source_a (e.g. 'hrv', 'recovery_score', 'weight_lbs')"},
                    "source_b":   {"type": "string", "description": f"Second data source. Valid: {SOURCES}"},
                    "field_b":    {"type": "string", "description": "Field from source_b (e.g. 'total_distance_miles', 'recovery_score')"},
                    "lag_days":   {"type": "number", "description": "Shift source_b forward N days. Use lag=1 to ask 'does A today predict B tomorrow?'. Default 0."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2019-01-01."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["source_a", "field_a", "source_b", "field_b"],
            },
        },
    },
    "get_seasonal_patterns": {
        "fn": tool_get_seasonal_patterns,
        "schema": {
            "name": "get_seasonal_patterns",
            "description": "Month-by-month averages aggregated across ALL years, revealing annual cycles. Use for: 'do I always gain weight in winter?', 'what month do I train most?', 'when is my HRV historically highest?', 'what are my seasonal training patterns?', 'when should I plan my peak event?'. Essential for periodisation and setting realistic seasonal targets. Each month shows how many years of data contribute.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Optional. Limit to one source. Valid: {SOURCES}. Omit for all sources."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_health_dashboard": {
        "fn": tool_get_health_dashboard,
        "schema": {
            "name": "get_health_dashboard",
            "description": "Current-state morning briefing in a single call. Returns: today's readiness (recovery score, HRV, RHR, sleep), training load status (CTL/ATL/TSB/ACWR), 7-day and 30-day training summaries, 30-day biomarker trends (HRV, RHR, weight), and automated alerts for anything outside healthy ranges. Use for: 'how am I doing?', 'morning check-in', 'give me a health briefing', 'am I overtrained?', 'should I train hard today?'",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_weight_loss_progress": {
        "fn": tool_get_weight_loss_progress,
        "schema": {
            "name": "get_weight_loss_progress",
            "description": "The core weight-loss coaching report. Returns: weekly rate of loss with fast/slow flags, full BMI series with clinical milestone flags (Obese III→II→I→Overweight→Normal), projected goal date at current pace, plateau detection (14+ days of minimal movement), and % complete toward goal. Use for: 'how is my weight loss going?', 'when will I reach my goal?', 'am I losing too fast?', 'am I in a plateau?', 'what BMI am I at?'. Requires journey_start_date, goal_weight_lbs in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Override start date YYYY-MM-DD. Defaults to journey_start_date from profile."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_body_composition_trend": {
        "fn": tool_get_body_composition_trend,
        "schema": {
            "name": "get_body_composition_trend",
            "description": "Tracks fat mass vs lean/muscle mass over time from Withings data — the question the scale alone cannot answer: are you losing fat or muscle? Returns fat mass, lean mass, body fat %, FFMI series, and flags significant lean mass loss events. Use for: 'am I losing fat or muscle?', 'how is my body composition changing?', 'am I protecting my lean mass?', 'what is my body fat percentage trend?'. Requires Withings body composition sync.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to journey_start_date from profile."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_energy_expenditure": {
        "fn": tool_get_energy_expenditure,
        "schema": {
            "name": "get_energy_expenditure",
            "description": "Estimates Total Daily Energy Expenditure (TDEE) = BMR + exercise calories. BMR computed via Mifflin-St Jeor (most validated for people with obesity). Exercise calories from Strava kilojoules or TRIMP estimate. Returns implied daily calorie target at a given deficit, and shows how BMR has changed since start weight (metabolic adaptation). Use for: 'how many calories should I eat?', 'what is my TDEE?', 'how much am I burning?', 'how has my metabolism changed as I lose weight?'. Requires height_inches, date_of_birth, biological_sex in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_deficit_kcal": {"type": "number", "description": "Daily calorie deficit target. Default 500 (≈1 lb/week). Use 750 for 1.5 lbs/week, 1000 for 2 lbs/week."},
                    "end_date":            {"type": "string",  "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_non_scale_victories": {
        "fn": tool_get_non_scale_victories,
        "schema": {
            "name": "get_non_scale_victories",
            "description": "Surfaces fitness and health improvements since journey start that are independent of the scale — critical for motivation during plateaus. Compares: resting HR, HRV, recovery score, sleep, activity count, monthly mileage, and moving speed between the first 30 days of the journey and the most recent 30 days. Use for: 'what non-scale victories have I had?', 'how has my fitness improved?', 'I am in a plateau — am I still making progress?', 'has my heart rate improved since I started?'. Requires journey_start_date in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
}


# ── MCP protocol handlers ─────────────────────────────────────────────────────
def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities":    {"tools": {}},
        "serverInfo":      {"name": "life-platform", "version": "1.8.0"},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}


def handle_tools_call(params):
    name      = params.get("name")
    arguments = params.get("arguments", {})
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")
    logger.info(f"Calling tool '{name}' with args: {arguments}")
    result = TOOLS[name]["fn"](arguments)
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


METHOD_HANDLERS = {
    "initialize":                handle_initialize,
    "tools/list":                handle_tools_list,
    "tools/call":                handle_tools_call,
    "notifications/initialized": lambda _: None,
}


# ── Nightly cache warmer ──────────────────────────────────────────────────────
# Triggered by EventBridge at 03:00 UTC daily. Pre-computes the slowest tools
# and writes results to the DynamoDB CACHE# partition so that Claude's first
# morning query is instant rather than waiting 8-15 seconds.

# Sources excluded from warmer heavy queries — apple_health has 3000+ items
# and takes ~20s to paginate; it's rarely the focus of aggregation queries.
WARMER_CORE_SOURCES = [s for s in SOURCES if s != "apple_health"]


def nightly_cache_warmer():
    """Pre-compute expensive tool results and store in DynamoDB cache.
    Excludes apple_health from aggregate queries (3000+ items, ~20s paginate).
    Lambda timeout is 300s; typical warmer runtime ~60-90s.
    Per-step timing is logged so slowdowns are easy to diagnose.
    """
    warmer_start = time.time()
    today    = datetime.utcnow().strftime("%Y-%m-%d")
    five_yrs = (datetime.utcnow() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    two_yrs  = (datetime.utcnow() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    results  = {}
    logger.info(f"[warmer] START date={today} sources={WARMER_CORE_SOURCES}")

    # 1. get_aggregated_summary — year view (5 years, core sources only)
    _t = time.time()
    try:
        logger.info("[warmer] computing aggregated_summary year (core sources)")
        source_data = parallel_query_sources(WARMER_CORE_SOURCES, five_yrs, today, lean=True)
        agg_result = {}
        for src, items in source_data.items():
            if items:
                agg_result[src] = aggregate_items(items, "year")
        data = {"period": "year", "start_date": five_yrs, "end_date": today,
                "sources": agg_result, "note": "warmer: apple_health excluded"}
        cache_key = f"aggregated_summary_year_{five_yrs}_{today}_{','.join(WARMER_CORE_SOURCES)}"
        ddb_cache_set(cache_key, data)
        mem_cache_set(cache_key, data)
        results["aggregated_summary_year"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] aggregated_summary year failed: {e}")
        results["aggregated_summary_year"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 2. get_aggregated_summary — month view (2 years, core sources only)
    _t = time.time()
    try:
        logger.info("[warmer] computing aggregated_summary month (core sources)")
        source_data = parallel_query_sources(WARMER_CORE_SOURCES, two_yrs, today, lean=True)
        agg_result = {}
        for src, items in source_data.items():
            if items:
                agg_result[src] = aggregate_items(items, "month")
        data = {"period": "month", "start_date": two_yrs, "end_date": today,
                "sources": agg_result, "note": "warmer: apple_health excluded"}
        cache_key = f"aggregated_summary_month_{two_yrs}_{today}_{','.join(WARMER_CORE_SOURCES)}"
        ddb_cache_set(cache_key, data)
        mem_cache_set(cache_key, data)
        results["aggregated_summary_month"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] aggregated_summary month failed: {e}")
        results["aggregated_summary_month"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 3. get_personal_records
    _t = time.time()
    try:
        logger.info("[warmer] computing personal_records")
        data = tool_get_personal_records({"end_date": today})
        ddb_cache_set("personal_records_all", data)
        mem_cache_set("personal_records_all", data)
        results["personal_records"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] personal_records failed: {e}")
        results["personal_records"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 4. get_seasonal_patterns (core sources only — apple_health volume)
    _t = time.time()
    try:
        logger.info("[warmer] computing seasonal_patterns (core sources)")
        data = tool_get_seasonal_patterns({"start_date": "2010-01-01", "end_date": today,
                                           "source": None})
        ddb_cache_set("seasonal_patterns_all", data)
        mem_cache_set("seasonal_patterns_all", data)
        results["seasonal_patterns"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] seasonal_patterns failed: {e}")
        results["seasonal_patterns"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 5. get_health_dashboard
    _t = time.time()
    try:
        logger.info("[warmer] computing health_dashboard")
        data = tool_get_health_dashboard({})
        ddb_cache_set("health_dashboard_today", data)
        mem_cache_set("health_dashboard_today", data)
        results["health_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] health_dashboard failed: {e}")
        results["health_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    total_ms = int((time.time() - warmer_start) * 1000)
    errors   = [k for k, v in results.items() if not v.get("status", "").startswith("ok")]
    status   = "COMPLETE" if not errors else f"PARTIAL — {len(errors)} step(s) failed: {errors}"
    logger.info(f"[warmer] {status} total_ms={total_ms} steps={json.dumps(results)}")
    if errors:
        logger.error(f"[warmer] FAILED steps: {errors}")

    return {"warmer": status, "date": today, "total_ms": total_ms, "results": results}


# ── Lambda handler ────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    # EventBridge scheduled rule — run nightly cache warmer, no auth needed
    if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
        logger.info("[lambda_handler] EventBridge trigger — running nightly cache warmer")
        result = nightly_cache_warmer()
        return {"statusCode": 200, "body": json.dumps(result),
                "headers": {"Content-Type": "application/json"}}

    expected_key = get_api_key()
    if expected_key:
        provided_key = (event.get("headers") or {}).get("x-api-key", "")
        if provided_key != expected_key:
            return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"}),
                    "headers": {"Content-Type": "application/json"}}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"}),
                "headers": {"Content-Type": "application/json"}}

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})
    logger.info(f"MCP request: method={method} id={rpc_id}")

    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return {
            "statusCode": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32601, "message": f"Method not found: {method}"}}),
            "headers": {"Content-Type": "application/json"},
        }

    try:
        result = handler(params)
        if result is None:
            return {"statusCode": 204, "body": ""}
        response_body = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except ValueError as e:
        response_body = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": str(e)}}
    except Exception as e:
        logger.error(f"Tool error: {e}", exc_info=True)
        response_body = {"jsonrpc": "2.0", "id": rpc_id,
                         "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}

    return {
        "statusCode": 200,
        "body":       json.dumps(response_body, default=str),
        "headers":    {"Content-Type": "application/json"},
    }
