"""
Data access tools: sources, latest, daily summary, date range, search, compare.
"""

import bisect
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from mcp.config import RAW_DAY_LIMIT, SOURCES, USER_PREFIX, table
from mcp.core import date_diff_days, decimal_to_float, get_sot, query_source, resolve_field
from mcp.helpers import aggregate_items, flatten_strava_activity


def tool_get_sources(_args):
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        oldest = table.query(
            KeyConditionExpression=Key("pk").eq(pk),
            Limit=1,
            ScanIndexForward=True,
            ProjectionExpression="#dt",
            ExpressionAttributeNames={"#dt": "date"},
        )
        newest = table.query(
            KeyConditionExpression=Key("pk").eq(pk),
            Limit=1,
            ScanIndexForward=False,
            ProjectionExpression="#dt",
            ExpressionAttributeNames={"#dt": "date"},
        )
        # 2026-05-03: use .get() — at least one source partition has a record
        # without a `date` field; was raising KeyError and tanking the whole tool.
        first = oldest["Items"][0].get("date") if oldest["Items"] else None
        last = newest["Items"][0].get("date") if newest["Items"] else None
        result[source] = {"available": first is not None, "first_date": first, "latest_date": last}
    return result


def _get_latest(args):
    from mcp.core import _apply_phase_filter  # ADR-058

    sources = args.get("sources", SOURCES)
    include_pilot = bool(args.get("include_pilot"))
    result = {}
    for source in sources:
        pk = f"{USER_PREFIX}{source}"
        kwargs = _apply_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(pk), "Limit": 1, "ScanIndexForward": False},
            include_pilot=include_pilot,
        )
        response = table.query(**kwargs)
        items = decimal_to_float(response.get("Items", []))
        result[source] = items[0] if items else None
    return result


def _get_daily_summary(args):
    from mcp.core import _apply_phase_filter  # ADR-058

    date = args.get("date")
    if not date:
        raise ValueError("'date' is required (YYYY-MM-DD)")
    include_pilot = bool(args.get("include_pilot"))
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        kwargs = _apply_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(f"DATE#{date}")},
            include_pilot=include_pilot,
        )
        response = table.query(**kwargs)
        items = decimal_to_float(response.get("Items", []))
        if items:
            result[source] = items
    return result


def tool_get_date_range(args):
    source = args.get("source")
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    if not all([source, start_date, end_date]):
        raise ValueError("'source', 'start_date', and 'end_date' are required")
    if source not in SOURCES:
        raise ValueError(f"Unknown source '{source}'. Valid: {SOURCES}")

    days = date_diff_days(start_date, end_date)
    items = query_source(source, start_date, end_date)

    if days > RAW_DAY_LIMIT:
        period = "year" if days > 365 * 2 else "month"
        return {
            "note": f"Window of {days} days — returning {period}ly aggregates.",
            "period": period,
            "source": source,
            "aggregated": aggregate_items(items, period),
        }

    return {"note": "Raw daily data.", "source": source, "items": items}


def tool_find_days(args):
    source = args.get("source")
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    filters = args.get("filters", [])
    if not all([source, start_date, end_date]):
        raise ValueError("'source', 'start_date', and 'end_date' are required")

    items = query_source(source, start_date, end_date)

    def passes(item):
        for f in filters:
            field = resolve_field(source, f["field"])
            actual = item.get(field)
            if actual is None:
                return False
            actual = float(actual)
            value = float(f["value"])
            op = f["op"]
            if op == ">" and not actual > value:
                return False
            if op == ">=" and not actual >= value:
                return False
            if op == "<" and not actual < value:
                return False
            if op == "<=" and not actual <= value:
                return False
            if op == "=" and not actual == value:
                return False
        return True

    matched = [item for item in items if passes(item)]

    if len(matched) > 200:
        key_fields = {
            "date",
            "recovery_score",
            "hrv",
            "strain",
            "weight_lbs",
            "sleep_duration_hours",
            "resting_heart_rate",
            "total_distance_miles",
            "total_elevation_gain_feet",
            "sport_types",
        }
        matched = [{k: v for k, v in m.items() if k in key_fields} for m in matched]

    return matched


def tool_search_activities(args):
    start_date = args.get("start_date", "2010-01-01")
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    name_contains = args.get("name_contains", "").lower()
    sport_type = args.get("sport_type", "").lower()
    min_distance = args.get("min_distance_miles")
    min_elevation = args.get("min_elevation_gain_feet")
    sort_by = args.get("sort_by", "distance_miles")
    limit = int(args.get("limit", 100))

    day_records = query_source(get_sot("cardio"), start_date, end_date)

    all_activities = []
    for day in day_records:
        all_activities.extend(flatten_strava_activity(day))

    all_sort_vals = sorted([float(a.get(sort_by, 0) or 0) for a in all_activities if a.get(sort_by) is not None])
    total_for_rank = len(all_sort_vals)

    def percentile_rank(val):
        if total_for_rank == 0:
            return None
        pos = bisect.bisect_left(all_sort_vals, float(val))
        return round(100.0 * pos / total_for_rank, 1)

    matched = []
    for act in all_activities:
        if name_contains:
            name_match = name_contains in (act.get("name") or "").lower()
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
        "total_matched": len(matched),
        "showing": len(results),
        "sorted_by": sort_by,
        "all_time_total_acts": total_for_rank,
        "activities": results,
    }


def tool_get_daily_snapshot(args):
    """
    Unified daily data dispatcher. Routes to get_daily_summary (specific date)
    or get_latest (most recent records across sources) based on view parameter.
    """
    VALID_VIEWS = {
        "summary": _get_daily_summary,
        "latest": _get_latest,
    }
    view = (args.get("view") or "summary").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Use 'summary' for all data on a specific date, 'latest' for the most recent record per source.",
        }
    return VALID_VIEWS[view](args)


def tool_get_intelligence_quality(args):
    """Query intelligence quality validation results.

    Shows recent validation flags from the post-generation intelligence validator.
    Filters by severity (error/warning), coach, or date range.
    """
    from boto3.dynamodb.conditions import Key

    from mcp.core import decimal_to_float, table

    days = int(args.get("days", 7))
    severity_filter = args.get("severity")  # error, warning, or None for all
    coach_filter = args.get("coach")

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    # Query all intelligence_quality records in date range
    try:
        # ADR-058: phase=pilot hidden by default.
        from mcp.core import _apply_phase_filter

        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq("USER#matthew")
                    & Key("sk").between(
                        f"SOURCE#intelligence_quality#{start_date}",
                        f"SOURCE#intelligence_quality#{end_date}~",
                    ),
                }
            )
        )
        items = [decimal_to_float(i) for i in resp.get("Items", [])]
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
            all_flags.append(
                {
                    "date": item.get("date"),
                    "coach": item.get("coach_id"),
                    "domain": item.get("domain"),
                    **flag,
                }
            )

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
