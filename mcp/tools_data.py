"""
Data access tools: sources, latest, daily summary, date range, search, compare.
"""

import bisect
import math
import operator
from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_now, pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from ingestion.strava_population import DISTANCE_POPULATION, DISTANCE_POPULATION_LABEL, ELEVATION_POPULATION_LABEL, activity_type
from privacy.field_tiers import strip_map

from mcp.config import RAW_DAY_LIMIT, SOURCES, USER_PREFIX, table
from mcp.core import date_diff_days, decimal_to_float, get_sot, query_source, resolve_field
from mcp.helpers import aggregate_items, flatten_strava_activity

# #2809: Tier-2 owner-only fields (PhenoAge posture) — never on a public surface, never
# quoted into an AI narrative context. MCP IS the sanctioned owner-only surface (a
# field-selective tool like get_labs's genome view may return Tier-2 data on purpose),
# but the GENERIC row dumpers below never picked fields — they hand back the whole DDB
# row, so a `get_date_range`/`get_daily_snapshot`/`find_days` call on withings put the
# Tier-2 trio into Claude conversation context by accident, which is exactly the
# distinction SCHEMA.md's "field-selective, never dump rows" line is about. Stripped
# once, here, rather than re-implemented per row-returning path.
#
# #2803: DERIVED from `lambdas/privacy/field_tiers.py`, not restated. Before this there
# was a literal trio here and a paragraph in SCHEMA.md and nothing compared them — the
# same one-copy rule the rest of the platform applies to counts and pins. Adding a
# Tier-2 field to the registry now strips it here with no edit to this file.
TIER2_STRIP_FIELDS = strip_map()


def _strip_tier2(source, item):
    """Remove `source`'s Tier-2 owner-only fields from one DDB row dict, in place.
    Returns the same dict for call-site chaining. A source with no Tier-2 facet (the
    common case) is a no-op — this only ever REMOVES keys already present, never
    invents, renames, or adds one. Keyed on the `source` the caller already queried
    (the row itself may not carry its own `source` attribute), never on the row."""
    if isinstance(item, dict):
        for f in TIER2_STRIP_FIELDS.get(source, ()):
            item.pop(f, None)
    return item


def _strip_tier2_many(source, items):
    """`_strip_tier2` applied over a list of rows for one known `source`."""
    for item in items:
        _strip_tier2(source, item)
    return items


def _date_of(items):
    """The day a partition-edge row belongs to — from the sk, which is authoritative.

    #2671: the `date` ATTRIBUTE is a duplicate of the key's own date segment and is not
    always written (labs' oldest row, `DATE#2019-05-01`, has no `date`). Reading only the
    attribute made a present record look absent. The sk is the thing the write built from,
    so it is what gets read.
    """
    if not items:
        return None
    row = items[0]
    if row.get("date"):
        return str(row["date"])[:10]
    sk = str(row.get("sk", ""))
    return sk.split("DATE#", 1)[1][:10] if sk.startswith("DATE#") else None


def tool_get_sources(_args):
    """Which sources have data, and over what span — the orientation call a session makes first.

    #2671: this disagreed with the tools that actually query the data, and it is the tool
    every subsequent question is steered by, so a false negative here closes a line of
    inquiry before it starts. Measured live on 2026-08-15, four sources were wrong:

        apple_health   available false — while its own latest_date said 2026-08-15
        dexa           available false — with 10 months of scans on file (2025-05→2026-03)
        labs           available false — 2019-05-01 through 2026-04-03 on file
        food_delivery  latest_date null — real newest DATE# is 2026-03-28

    Two causes, both from asking the partition a different question than the domain tools
    ask it. First, the edge queries were unconstrained, so the "oldest" and "newest" rows
    were whatever sorted first and last in the WHOLE partition — apple_health's oldest is
    `ALERTSTATE#ah_activity_degraded` (an operational marker), food_delivery's newest is
    `YEAR#2026` (an aggregate), labs' newest is `PROVIDER#function_health#2025-spring`.
    Availability for apple_health was therefore decided by an alert-state row. Every
    domain tool ranges on `begins_with("DATE#")`; now this does too, which is the single
    truth source the issue asks for. Second, `available` keyed off the `date` attribute
    rather than the record's existence — see `_date_of`.

    The issue named apple_health / labs / food_delivery / strava. The wire says the fourth
    is **dexa**: strava's edges are both clean DATE# rows and always agreed. dexa is the
    worst of the four — body composition reported as absent while a year of scans sit in
    the partition.

    `state` is `resolve_source_state`, the same call `get_freshness_status` makes, so the
    two tools cannot drift on what live/paused/stale/rate_limited mean. #2671 originally
    layered the registry's `paused` facet on top of it here, because the resolver read only
    `DECLARED_PAUSED_SOURCES` — empty by design — and so answered `stale` for a source that
    is off by design. #2715 fixed that at the root: the resolver now reads the facet, and
    the layer is gone. Freshness still wins, so a paused source that starts producing again
    reads `live` with no code change.
    """
    from ingestion.source_state import has_rate_limit_marker, resolve_source_state

    today = pacific_now().date().isoformat()
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        edge_kwargs = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
            "Limit": 1,
            "ProjectionExpression": "sk, #dt",
            "ExpressionAttributeNames": {"#dt": "date"},
        }
        oldest = table.query(**edge_kwargs, ScanIndexForward=True)
        newest = table.query(**edge_kwargs, ScanIndexForward=False)
        last = _date_of(newest["Items"])
        state = resolve_source_state(source, last, today, rate_limited=has_rate_limit_marker(table, "matthew", source))
        result[source] = {
            "available": bool(newest["Items"]),
            "first_date": _date_of(oldest["Items"]),
            "latest_date": last,
            "state": state,
        }
    return result


def _snapshot_include_pilot(args):
    """The caller's explicit `include_pilot`, or None to DERIVE it per source (#4061).

    Before #4061 an absent argument meant the ADR-058 filter on every source, so the snapshot
    of any pre-genesis day (Strava 2024-10-01: 6 activities, `phase=pilot`) came back empty.
    """
    raw = args.get("include_pilot")
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip().lower() not in ("false", "0", "no", "")
    return bool(raw)


def _get_latest(args):
    from mcp.core import _apply_phase_filter, _resolve_include_pilot  # ADR-058 / #4061

    sources = args.get("sources", SOURCES)
    requested = _snapshot_include_pilot(args)
    result = {}
    for source in sources:
        pk = f"{USER_PREFIX}{source}"
        kwargs = _apply_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(pk), "Limit": 1, "ScanIndexForward": False},
            include_pilot=_resolve_include_pilot(source, requested)[0],
        )
        response = table.query(**kwargs)
        items = decimal_to_float(response.get("Items", []))
        result[source] = _strip_tier2(source, items[0]) if items else None
    return result


def _get_daily_summary(args):
    from mcp.core import _apply_phase_filter, _resolve_include_pilot  # ADR-058 / #4061

    date = args.get("date")
    if not date:
        raise ValueError("'date' is required (YYYY-MM-DD)")
    requested = _snapshot_include_pilot(args)
    result = {}
    for source in SOURCES:
        pk = f"{USER_PREFIX}{source}"
        include_pilot, derived = _resolve_include_pilot(source, requested)
        kwargs = _apply_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(f"DATE#{date}")},
            include_pilot=include_pilot,
        )
        response = table.query(**kwargs)
        items = response.get("Items", [])
        if derived:
            items = [i for i in items if not i.get("tombstone")]  # superseded rows stay out, as in query_source
        items = decimal_to_float(items)
        if items:
            result[source] = _strip_tier2_many(source, items)
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
    items = _strip_tier2_many(source, query_source(source, start_date, end_date))

    if days > RAW_DAY_LIMIT:
        period = "year" if days > 365 * 2 else "month"
        return {
            "note": f"Window of {days} days — returning {period}ly aggregates.",
            "period": period,
            "source": source,
            "aggregated": aggregate_items(items, period),
        }

    return {"note": "Raw daily data.", "source": source, "items": items}


# The single source of truth for find_days comparison operators: validation and
# evaluation both read this table, so the supported set cannot drift (#2306).
FIND_DAYS_OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
}


# ── find_days mode='similar' knobs (#2351) ────────────────────────────────────
# All three are part of the tool's stated, stable contract (ADR-105): the method
# string in the response derives from them, and the tests pin the arithmetic.
SIMILAR_DEFAULT_K = 5
SIMILAR_MAX_K = 20
# A feature must be carried by at least this many candidate days to contribute —
# below this the z-normalization is too noisy to call two days "alike" on it.
SIMILAR_MIN_FEATURE_N = 10
# The honesty floor: a candidate further than this RMS z-distance is not a
# "comparable day"; with nothing under the floor the answer is no matches,
# never the least-bad five (issue #2351 acceptance).
SIMILAR_MAX_RMS_Z = 1.0
# Default feature vector per source. Only sources listed here have a default;
# any other source requires an explicit `features` list from the caller.
SIMILAR_DEFAULT_FEATURES = {
    "whoop": ["recovery_score", "hrv", "resting_heart_rate", "strain", "sleep_duration_hours"],
}


def _numeric(item, field):
    """The numeric value of `field` on a day record, or None. Absence (or a
    non-numeric value) is None — never imputed to a mean or zero (ADR-104)."""
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _next_date(date_str):
    return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def _find_similar_days(args):
    """mode='similar': nearest-neighbour retrieval over day vectors (#2351).

    Deterministic arithmetic only — no AI call, no budget band (ADR-105):
    each feature is z-scored against the candidate window (population mean/std
    over the candidate days that carry it, target excluded), distance is the
    RMS z-difference over the used features, ties break by date ascending.
    A day missing a used feature is excluded from comparability rather than
    imputed (ADR-104). "What happened next" is a described distribution of the
    next calendar day after each match, with its n — never a prediction.
    """
    source = args.get("source")
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    target_date = args.get("target_date")
    if not all([source, start_date, end_date, target_date]):
        raise ValueError("mode='similar' requires 'source', 'start_date', 'end_date', and 'target_date'")
    features = args.get("features") or SIMILAR_DEFAULT_FEATURES.get(source)
    if not features:
        raise ValueError(
            f"'features' is required for source '{source}' (no default feature vector). "
            f"Defaults exist for: {sorted(SIMILAR_DEFAULT_FEATURES)}"
        )
    k = max(1, min(int(args.get("k", SIMILAR_DEFAULT_K)), SIMILAR_MAX_K))

    resolved = []
    for f in features:
        rf = resolve_field(source, f)
        if rf not in resolved:
            resolved.append(rf)

    items = query_source(source, start_date, end_date)
    # One record per date, deterministically (first by sort key on collision).
    by_date = {}
    for item in sorted(items, key=lambda i: str(i.get("sk", ""))):
        d = item.get("date")
        if d and d not in by_date:
            by_date[d] = item

    if start_date <= target_date <= end_date:
        target = by_date.get(target_date)
    else:
        target_items = query_source(source, target_date, target_date)
        target = target_items[0] if target_items else None
    if target is None:
        return {
            "mode": "similar",
            "source": source,
            "target_date": target_date,
            "matches": [],
            "note": f"No data for target_date {target_date} in source '{source}' — nothing to compare against.",
        }

    candidate_dates = sorted(d for d in by_date if d != target_date)

    used, dropped, stats = [], {}, {}
    for f in resolved:
        target_value = _numeric(target, f)
        if target_value is None:
            dropped[f] = "missing on the target day — absence is not imputed (ADR-104)"
            continue
        present = [v for v in (_numeric(by_date[d], f) for d in candidate_dates) if v is not None]
        if len(present) < SIMILAR_MIN_FEATURE_N:
            dropped[f] = f"only {len(present)} candidate day(s) carry it (floor: {SIMILAR_MIN_FEATURE_N})"
            continue
        mean = sum(present) / len(present)
        std = math.sqrt(sum((v - mean) ** 2 for v in present) / len(present))
        if std == 0:
            dropped[f] = "zero variance across candidate days — cannot discriminate on it"
            continue
        stats[f] = (mean, std)
        used.append(f)

    method = (
        f"Deterministic feature-vector retrieval: per-feature z-score against the candidate window "
        f"(population mean/std over candidate days carrying the feature, target excluded); "
        f"distance = RMS z-difference over the used features; similarity floor = {SIMILAR_MAX_RMS_Z} RMS z; "
        f"ties break by date. No AI involved."
    )
    result = {
        "mode": "similar",
        "source": source,
        "target_date": target_date,
        "features_used": used,
        "features_dropped": dropped,
        "method": method,
        "n_candidate_days": len(candidate_dates),
        "similarity_floor_rms_z": SIMILAR_MAX_RMS_Z,
    }
    if not used:
        result["matches"] = []
        result["note"] = "No usable features — see features_dropped for why each was excluded."
        return result

    target_z = {f: (_numeric(target, f) - stats[f][0]) / stats[f][1] for f in used}
    result["target_values"] = {f: _numeric(target, f) for f in used}

    scored, excluded_missing = [], 0
    for d in candidate_dates:
        z = {}
        for f in used:
            v = _numeric(by_date[d], f)
            if v is None:
                z = None
                break
            z[f] = (v - stats[f][0]) / stats[f][1]
        if z is None:
            excluded_missing += 1
            continue
        distance = math.sqrt(sum((z[f] - target_z[f]) ** 2 for f in used) / len(used))
        scored.append((distance, d))
    scored.sort(key=lambda t: (t[0], t[1]))

    result["n_comparable"] = len(scored)
    result["n_excluded_missing_features"] = excluded_missing
    within = [t for t in scored if t[0] <= SIMILAR_MAX_RMS_Z]
    matches = []
    for distance, d in within[:k]:
        match = {
            "date": d,
            "rms_z_distance": round(distance, 3),
            "values": {f: _numeric(by_date[d], f) for f in used},
        }
        next_day = by_date.get(_next_date(d))
        if next_day is not None:
            next_values = {f: v for f in used if (v := _numeric(next_day, f)) is not None}
            if next_values:
                match["next_day"] = {"date": _next_date(d), "values": next_values}
        matches.append(match)
    result["n_matches"] = len(matches)
    result["matches"] = matches

    if not matches:
        nearest = (
            f"nearest candidate was {round(scored[0][0], 3)} RMS z on {scored[0][1]}"
            if scored
            else "no candidate carried all used features"
        )
        result["note"] = f"No comparable days: nothing within {SIMILAR_MAX_RMS_Z} RMS z-distance of the target ({nearest})."
        return result

    next_distribution = {}
    for f in used:
        values = sorted(m["next_day"]["values"][f] for m in matches if "next_day" in m and f in m["next_day"]["values"])
        if values:
            mid = len(values) // 2
            next_distribution[f] = {
                "n": len(values),
                "mean": round(sum(values) / len(values), 2),
                "median": values[mid] if len(values) % 2 else round((values[mid - 1] + values[mid]) / 2, 2),
                "min": values[0],
                "max": values[-1],
            }
    result["what_happened_next"] = {
        "note": (
            f"Described distribution of the next calendar day after each of the {len(matches)} matched day(s) — "
            "a matched sample, not a prediction (ADR-105). Per-feature n reflects days actually carrying the feature."
        ),
        "features": next_distribution,
    }
    return result


def _find_days_filter(args):
    source = args.get("source")
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    filters = args.get("filters", [])
    if not all([source, start_date, end_date]):
        raise ValueError("'source', 'start_date', and 'end_date' are required")
    for f in filters:
        if f.get("op") not in FIND_DAYS_OPERATORS:
            raise ValueError(f"Unknown operator '{f.get('op')}'. Supported: {sorted(FIND_DAYS_OPERATORS)}")

    items = query_source(source, start_date, end_date)

    def passes(item):
        for f in filters:
            field = resolve_field(source, f["field"])
            actual = item.get(field)
            if actual is None:
                return False
            if not FIND_DAYS_OPERATORS[f["op"]](float(actual), float(f["value"])):
                return False
        return True

    matched = [item for item in items if passes(item)]
    for item in matched:
        _annotate_unmeasured_distance(item)

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
            "activity_count",
            "activities_without_distance",
        }
        matched = [{k: v for k, v in m.items() if k in key_fields} for m in matched]

    return _strip_tier2_many(source, matched)


def _annotate_unmeasured_distance(day):
    """Stamp a day-aggregate with how many of its activities carry no measured distance (#4061).

    A Strava day's `total_distance_miles` sums MEASURED distance only (`strava_lambda.transform`),
    and a WHOOP-synced trainer walk stores `distance_miles` absent (`strava_population`) — so a
    day whose walks were all WHOOP-recorded reads 0.0 miles and a distance filter drops it
    without a word. The count rides on the row itself, only when non-zero, so the row says
    what its total leaves out. Rows without an `activities` list are untouched.
    """
    acts = day.get("activities")
    if not isinstance(acts, list):
        return
    n = sum(1 for a in acts if isinstance(a, dict) and a.get("distance_miles") is None and activity_type(a) in DISTANCE_POPULATION)
    if n:
        day["activities_without_distance"] = n


def tool_find_days(args):
    """Two modes over day-level aggregates: 'filter' (threshold conditions, the
    original behavior and the default) and 'similar' (#2351 — nearest-neighbour
    retrieval: 'the days most like this one', deterministic vector math)."""
    mode = (args.get("mode") or "filter").lower().strip()
    modes = {"filter": _find_days_filter, "similar": _find_similar_days}
    if mode not in modes:
        raise ValueError(f"Unknown mode '{mode}'. Valid: {sorted(modes)}")
    return modes[mode](args)


def _population_label(sort_by):
    """Name the population an all-time percentile over `sort_by` is computed against (#2331)."""
    if sort_by == "distance_miles":
        return DISTANCE_POPULATION_LABEL
    if sort_by == "total_elevation_gain_feet":
        return ELEVATION_POPULATION_LABEL
    return f"Strava activities reporting {sort_by}"


def tool_search_activities(args):
    start_date = args.get("start_date", "2010-01-01")
    end_date = args.get("end_date", pacific_today())
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

    # #4061 box 4: an activity with no measured `distance_miles` / elevation (a WHOOP-synced
    # trainer walk or ride, a manual entry — `ingestion/strava_population.py` stores those
    # ABSENT, never 0) used to leave this tool without a word: a `min_*` filter dropped it,
    # and the default distance sort ranked it as 0 so a `limit` cut it first. It is still
    # excluded by a `min_*` filter and still ranked after every measured value — both are
    # correct, it has no value to compare — but the output now COUNTS both, so an answer
    # like "no walks that month" can be told apart from "the walks carry no distance".
    excluded_unmeasured = {"distance_miles": 0, "total_elevation_gain_feet": 0}
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
            if dist is None:
                excluded_unmeasured["distance_miles"] += 1
                continue
            if float(dist) < float(min_distance):
                continue
        if min_elevation is not None:
            elev = act.get("total_elevation_gain_feet")
            if elev is None:
                excluded_unmeasured["total_elevation_gain_feet"] += 1
                continue
            if float(elev) < float(min_elevation):
                continue
        matched.append(act)

    # Measured values first, descending; an activity with no measured `sort_by` after them all.
    matched.sort(key=lambda x: (x.get(sort_by) is not None, float(x.get(sort_by, 0) or 0)), reverse=True)
    unmeasured_sort = sum(1 for a in matched if a.get(sort_by) is None)
    unmeasured_shown = sum(1 for a in matched[:limit] if a.get(sort_by) is None)

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
        # #2331 — a "top N% all-time" claim is meaningless without saying what the
        # N% is OF. `all_time_total_acts` counts activities carrying a non-null
        # `sort_by`, and for distance/elevation that is the measured population
        # defined in ingestion/strava_population.py (gym sessions and indoor-trainer
        # or manually-entered records are excluded — those metrics were never
        # measured for them, so they are absent rather than zero).
        "population": _population_label(sort_by),
        "activities": results,
        **_unmeasured_block(sort_by, unmeasured_sort, unmeasured_shown, excluded_unmeasured),
    }


def _unmeasured_block(sort_by, unmeasured_sort, unmeasured_shown, excluded_unmeasured):
    """Say what the search could not rank or filter, instead of dropping it silently (#4061).

    Empty when nothing was unmeasured, so a fully-measured answer is unchanged.
    """
    excluded = {k: v for k, v in excluded_unmeasured.items() if v}
    if not unmeasured_sort and not excluded:
        return {}
    notes = []
    if unmeasured_sort:
        cut = unmeasured_sort - unmeasured_shown
        notes.append(
            f"{unmeasured_sort} matched activit{'y' if unmeasured_sort == 1 else 'ies'} carry no measured {sort_by} "
            "(WHOOP-synced trainer sessions and manual entries store it absent, never 0) — ranked after every measured one"
            + (f"; {cut} of them fell past the limit and are not listed" if cut else "")
            + ". Pass sort_by='moving_time_seconds' or a sport_type to see them."
        )
    for field, n in excluded.items():
        notes.append(
            f"{n} activit{'y' if n == 1 else 'ies'} excluded by the min_{'distance_miles' if field == 'distance_miles' else 'elevation_gain_feet'} "
            f"filter because {field} was never measured for them (not because it was below the threshold)."
        )
    return {
        "unmeasured": {
            f"matched_without_{sort_by}": unmeasured_sort,
            "excluded_by_min_filter_unmeasured": excluded,
            "note": " ".join(notes),
        }
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

    end_date = pacific_today()
    start_date = (pacific_now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Query all intelligence_quality records in date range
    try:
        # #4088: `intelligence_quality` is SYSTEM_STATE (the validator's ops ledger) — the
        # phase machinery ignores it, so the decision is derived from the key's class
        # rather than the unconditional ADR-058 filter.
        from mcp.core import _apply_phase_filter, _resolve_include_pilot_key

        _iq_pilot, _ = _resolve_include_pilot_key("USER#matthew", "SOURCE#intelligence_quality#")
        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq("USER#matthew")
                    & Key("sk").between(
                        f"SOURCE#intelligence_quality#{start_date}",
                        f"SOURCE#intelligence_quality#{end_date}~",
                    ),
                },
                include_pilot=_iq_pilot,
            )
        )
        items = [decimal_to_float(i) for i in resp.get("Items", [])]
    except Exception as e:  # noqa: BLE001
        # #3920: an unreadable validator ledger is not a week with zero flags.
        from mcp.layer_status import DERIVED_LAYERS, layer_fields, read_status

        status, reason = read_status(error=e)
        return {"error": str(e), **layer_fields(status, reason, producer=DERIVED_LAYERS["intelligence_quality"]["producer"])}

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

    # #2305: the denominator is the sum of what the validator actually ran —
    # each row stores its own `checks_run` (derived from _VALIDATOR_CHECKS on
    # the write side, #1658). Never a hand-typed check count here: a row
    # missing `checks_run` is excluded rather than contributing a fabricated
    # number. Guarded by tests/test_mcp_tools_data_behavior.py.
    total_checks = sum(int(i["checks_run"]) for i in items if i.get("checks_run") is not None)

    # #3920: the layer verdict — nightly validator; two silent nights is degraded, and says so.
    from mcp.layer_status import DERIVED_LAYERS, counted, layer_fields, read_status

    newest = max((str(i.get("date") or "") for i in items), default="") or None
    status, reason = read_status(newest_date=newest, cadence_days=DERIVED_LAYERS["intelligence_quality"]["cadence_days"])
    return {
        "period": {"start": start_date, "end": end_date},
        **layer_fields(status, reason, producer=DERIVED_LAYERS["intelligence_quality"]["producer"], newest_date=newest),
        "total_checks": counted(status, total_checks),
        "total_flags": counted(status, len(all_flags)),
        "errors": total_errors,
        "warnings": total_warnings,
        "flags": all_flags[:20],  # Cap at 20 for readability
        "coaches_checked": list(set(i.get("coach_id") for i in items)),
    }
