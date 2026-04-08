"""
Data access tools: sources, latest, daily summary, date range, search, compare.
"""
import json
import math
import re
import bisect
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from boto3.dynamodb.conditions import Key

from mcp.config import (
    table, s3_client, S3_BUCKET, USER_PREFIX, USER_ID, SOURCES,
    P40_GROUPS, FIELD_ALIASES, logger,
    INSIGHTS_PK, EXPERIMENTS_PK, TRAVEL_PK, RAW_DAY_LIMIT,
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
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    if period not in ("month", "year"):
        raise ValueError("'period' must be 'month' or 'year'")

    if source and source in SOURCES:
        default_start = "2010-01-01"
    else:
        if period == "year":
            default_start = (datetime.now(timezone.utc) - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
        else:
            default_start = (datetime.now(timezone.utc) - timedelta(days=365 * 2)).strftime("%Y-%m-%d")

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
    end_date      = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    name_contains = args.get("name_contains", "").lower()
    sport_type    = args.get("sport_type", "").lower()
    min_distance  = args.get("min_distance_miles")
    min_elevation = args.get("min_elevation_gain_feet")
    sort_by       = args.get("sort_by", "distance_miles")
    limit         = int(args.get("limit", 100))

    day_records = query_source(get_sot("cardio"), start_date, end_date)

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
        if name_contains:
            name_match     = name_contains in (act.get("name")          or "").lower()
            enriched_match = name_contains in (act.get("enriched_name") or "").lower()
            if not (name_match or enriched_match):
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
    end_date   = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

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
    end_date   = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    sort_by    = args.get("sort_by", "total_distance_miles")
    limit      = int(args.get("limit", 52))
    sort_asc   = args.get("sort_ascending", False)

    day_records = query_source(get_sot("cardio"), start_date, end_date)

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


def tool_get_daily_snapshot(args):
    """
    Unified daily data dispatcher. Routes to get_daily_summary (specific date)
    or get_latest (most recent records across sources) based on view parameter.
    """
    VALID_VIEWS = {
        "summary": tool_get_daily_summary,
        "latest":  tool_get_latest,
    }
    view = (args.get("view") or "summary").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Use 'summary' for all data on a specific date, 'latest' for the most recent record per source.",
        }
    return VALID_VIEWS[view](args)


def tool_get_longitudinal_summary(args):
    """
    Unified longitudinal data dispatcher. Routes to aggregated_summary,
    seasonal_patterns, or personal_records based on view parameter.
    """
    VALID_VIEWS = {
        "aggregate":  tool_get_aggregated_summary,
        "seasonal":   tool_get_seasonal_patterns,  # noqa: F821
        "records":    tool_get_personal_records,  # noqa: F821
    }
    view = (args.get("view") or "aggregate").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Use 'aggregate' for monthly/yearly averages, 'seasonal' for month-by-month patterns across all years, 'records' for all-time PRs.",
        }
    return VALID_VIEWS[view](args)


def tool_get_intelligence_quality(args):
    """Query intelligence quality validation results.

    Shows recent validation flags from the post-generation intelligence validator.
    Filters by severity (error/warning), coach, or date range.
    """
    from mcp.core import USER_PREFIX, table, _decimal_to_float
    from boto3.dynamodb.conditions import Key

    days = int(args.get("days", 7))
    severity_filter = args.get("severity")  # error, warning, or None for all
    coach_filter = args.get("coach")

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    # Query all intelligence_quality records in date range
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#matthew") & Key("sk").between(
                f"SOURCE#intelligence_quality#{start_date}",
                f"SOURCE#intelligence_quality#{end_date}~",
            ),
        )
        items = [_decimal_to_float(i) for i in resp.get("Items", [])]
    except Exception as e:
        return {"error": str(e)}

    # Filter
    if coach_filter:
        items = [i for i in items if i.get("coach_id") == coach_filter]

    # Flatten flags
    all_flags = []
    for item in items:
        for flag in item.get("flags", []):
            if severity_filter and flag.get("severity") != severity_filter:
                continue
            all_flags.append({
                "date": item.get("date"),
                "coach": item.get("coach_id"),
                "domain": item.get("domain"),
                **flag,
            })

    # Summary
    total_errors = sum(1 for f in all_flags if f.get("severity") == "error")
    total_warnings = sum(1 for f in all_flags if f.get("severity") == "warning")

    return {
        "period": {"start": start_date, "end": end_date},
        "total_checks": len(items) * 5,  # 5 checks per coach
        "total_flags": len(all_flags),
        "errors": total_errors,
        "warnings": total_warnings,
        "flags": all_flags[:20],  # Cap at 20 for readability
        "coaches_checked": list(set(i.get("coach_id") for i in items)),
    }


def tool_list_actions(args):
    """List coach-issued actions with status tracking.

    Shows open, completed, expired, and superseded actions across all coaches.
    Supports filtering by domain, status, and time window.
    """
    domain_filter = args.get("domain")
    status_filter = args.get("status")
    days = int(args.get("days", 30))

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        resp = table.query(
            KeyConditionExpression=(
                Key("pk").eq("USER#matthew")
                & Key("sk").begins_with("SOURCE#coach_actions#")
            ),
        )
        items = [decimal_to_float(i) for i in resp.get("Items", [])]
    except Exception as e:
        return {"error": str(e)}

    # Filter by date window
    items = [i for i in items if (i.get("issued_date") or "") >= cutoff_date]

    # Filter by domain
    if domain_filter:
        items = [i for i in items if i.get("domain") == domain_filter]

    # Check for expired open actions
    rules_config = {}
    try:
        resp_s3 = s3_client.get_object(Bucket=S3_BUCKET, Key="config/action_detection_rules.json")
        rules_config = json.loads(resp_s3["Body"].read())
    except Exception:
        pass
    expiry_days = rules_config.get("expiry_days", 14)

    for item in items:
        if item.get("status") == "open" and item.get("issued_date"):
            try:
                issued_dt = datetime.strptime(item["issued_date"], "%Y-%m-%d")
                age = (datetime.strptime(today, "%Y-%m-%d") - issued_dt).days
                if age > expiry_days:
                    item["status"] = "expired"
                    item["age_days"] = age
                else:
                    item["age_days"] = age
            except ValueError:
                pass

    # Filter by status
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]

    # Sort by issued_date descending
    items.sort(key=lambda x: x.get("issued_date", ""), reverse=True)

    # Strip pk/sk for cleaner output
    clean_items = []
    for item in items:
        clean = {k: v for k, v in item.items() if k not in ("pk", "sk")}
        clean_items.append(clean)

    # Summary stats
    status_counts = defaultdict(int)
    for item in clean_items:
        status_counts[item.get("status", "unknown")] += 1

    return {
        "period": {"start": cutoff_date, "end": today},
        "total": len(clean_items),
        "status_summary": dict(status_counts),
        "actions": clean_items[:30],  # Cap at 30 for readability
    }


def tool_complete_action(args):
    """Manually mark a coach action as completed.

    Use when Matthew has done something a coach recommended.
    """
    action_id = args.get("action_id")
    if not action_id:
        raise ValueError("'action_id' is required")

    note = args.get("note")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    update_expr = "SET #st = :completed, completion_date = :cd, completion_method = :cm"
    attr_names = {"#st": "status"}
    attr_values = {
        ":completed": "completed",
        ":cd": today,
        ":cm": "manual",
    }

    if note:
        update_expr += ", follow_up_note = :fn"
        attr_values[":fn"] = note

    try:
        resp = table.update_item(
            Key={
                "pk": "USER#matthew",
                "sk": f"SOURCE#coach_actions#{action_id}",
            },
            UpdateExpression=update_expr,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
            ReturnValues="ALL_NEW",
        )
        updated = decimal_to_float(resp.get("Attributes", {}))
        clean = {k: v for k, v in updated.items() if k not in ("pk", "sk")}
        return {
            "status": "success",
            "message": f"Action '{action_id}' marked as completed.",
            "action": clean,
        }
    except Exception as e:
        return {"error": f"Failed to complete action: {str(e)}"}
