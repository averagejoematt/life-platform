"""
Social, behavioral, and protocol tools:
  - Life event tagging (#40)
  - Contact frequency tracking (#42)
  - Temptation logging (#35)
  - Cold/heat exposure logging & correlation (#36)
"""
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from decimal import Decimal

from mcp.config import (
    table, USER_PREFIX, USER_ID, logger,
    LIFE_EVENTS_PK, INTERACTIONS_PK, TEMPTATIONS_PK, EXPOSURES_PK,
)
from mcp.core import (
    query_source, decimal_to_float, get_profile,
)
from mcp.helpers import pearson_r


# ═══════════════════════════════════════════════════════════════════════
# #40 — LIFE EVENT TAGGING (Sponsor: Elena Voss)
# ═══════════════════════════════════════════════════════════════════════

_LIFE_EVENT_TYPES = [
    "birthday", "anniversary", "work_milestone", "social", "conflict",
    "loss", "health_milestone", "travel", "relationship", "financial",
    "achievement", "setback", "other",
]


def tool_log_life_event(args):
    """Log a structured life event (birthday, loss, milestone, etc.)."""
    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    event_type = args.get("type", "other").lower()
    title = args.get("title", "").strip()
    if not title:
        return {"error": "title is required."}

    if event_type not in _LIFE_EVENT_TYPES:
        return {"error": f"Invalid type '{event_type}'. Valid: {_LIFE_EVENT_TYPES}"}

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    sk = f"EVENT#{date}#{ts}"

    item = {
        "pk": LIFE_EVENTS_PK,
        "sk": sk,
        "date": date,
        "type": event_type,
        "title": title,
        "source": "life_events",
        "logged_at": datetime.utcnow().isoformat(),
    }

    # Optional fields
    if args.get("description"):
        item["description"] = args["description"].strip()
    if args.get("people"):
        people = args["people"]
        if isinstance(people, str):
            people = [p.strip() for p in people.split(",") if p.strip()]
        item["people"] = people
    if args.get("emotional_weight"):
        weight = int(args["emotional_weight"])
        if 1 <= weight <= 5:
            item["emotional_weight"] = weight
    if args.get("recurring"):
        item["recurring"] = args["recurring"]  # "annual", "monthly", etc.

    try:
        table.put_item(Item=item)
    except Exception as e:
        return {"error": f"Failed to log life event: {e}"}

    return {
        "status": "logged",
        "date": date,
        "type": event_type,
        "title": title,
        "emotional_weight": item.get("emotional_weight"),
        "people": item.get("people"),
        "message": f"Life event logged: '{title}' ({event_type}) on {date}.",
    }


def tool_get_life_events(args):
    """Retrieve life events with optional filters."""
    end = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d"))
    filter_type = args.get("type")
    filter_person = args.get("person", "").lower()

    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": LIFE_EVENTS_PK,
            ":s": f"EVENT#{start}",
            ":e": f"EVENT#{end}\xff",
        },
    )
    items = [decimal_to_float(i) for i in resp.get("Items", [])]

    # Apply filters
    if filter_type:
        items = [i for i in items if i.get("type") == filter_type.lower()]
    if filter_person:
        items = [i for i in items if filter_person in [p.lower() for p in i.get("people", [])]]

    # Sort by date
    items.sort(key=lambda x: x.get("date", ""))

    # Type summary
    type_counts = defaultdict(int)
    for i in items:
        type_counts[i.get("type", "other")] += 1

    # People frequency
    people_freq = defaultdict(int)
    for i in items:
        for p in i.get("people", []):
            people_freq[p] += 1

    # Strip internal fields
    clean = []
    for i in items:
        clean.append({
            "date": i.get("date"),
            "type": i.get("type"),
            "title": i.get("title"),
            "description": i.get("description"),
            "people": i.get("people"),
            "emotional_weight": i.get("emotional_weight"),
            "recurring": i.get("recurring"),
        })

    return {
        "period": f"{start} to {end}",
        "total_events": len(clean),
        "type_breakdown": dict(type_counts),
        "people_mentioned": dict(sorted(people_freq.items(), key=lambda x: -x[1])[:10]),
        "events": clean,
    }


# ═══════════════════════════════════════════════════════════════════════
# #42 — CONTACT FREQUENCY TRACKING (Sponsor: Vivek Murthy)
# ═══════════════════════════════════════════════════════════════════════

_INTERACTION_TYPES = ["call", "text", "in_person", "video", "email", "social_media", "other"]
_DEPTH_LEVELS = ["surface", "meaningful", "deep"]


def tool_log_interaction(args):
    """Log a meaningful social interaction."""
    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    person = args.get("person", "").strip()
    if not person:
        return {"error": "person is required."}

    interaction_type = args.get("type", "other").lower()
    if interaction_type not in _INTERACTION_TYPES:
        return {"error": f"Invalid type '{interaction_type}'. Valid: {_INTERACTION_TYPES}"}

    depth = args.get("depth", "meaningful").lower()
    if depth not in _DEPTH_LEVELS:
        return {"error": f"Invalid depth '{depth}'. Valid: {_DEPTH_LEVELS}"}

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    sk = f"DATE#{date}#INT#{ts}"

    item = {
        "pk": INTERACTIONS_PK,
        "sk": sk,
        "date": date,
        "person": person,
        "type": interaction_type,
        "depth": depth,
        "source": "interactions",
        "logged_at": datetime.utcnow().isoformat(),
    }

    if args.get("duration_min"):
        item["duration_min"] = Decimal(str(int(args["duration_min"])))
    if args.get("notes"):
        item["notes"] = args["notes"].strip()
    if args.get("initiated_by"):
        item["initiated_by"] = args["initiated_by"].lower()  # "me" or "them"

    try:
        table.put_item(Item=item)
    except Exception as e:
        return {"error": f"Failed to log interaction: {e}"}

    return {
        "status": "logged",
        "date": date,
        "person": person,
        "type": interaction_type,
        "depth": depth,
        "duration_min": item.get("duration_min"),
        "message": f"Logged {depth} {interaction_type} with {person} on {date}.",
    }


def tool_get_social_dashboard(args):
    """Social connection dashboard: frequency, diversity, depth, trends."""
    end = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": INTERACTIONS_PK,
            ":s": f"DATE#{start}",
            ":e": f"DATE#{end}\xff",
        },
    )
    items = [decimal_to_float(i) for i in resp.get("Items", [])]
    items.sort(key=lambda x: x.get("date", ""))

    if not items:
        return {
            "period": f"{start} to {end}",
            "total_interactions": 0,
            "message": "No interactions logged yet. Use log_interaction to start tracking.",
        }

    total_days = max(1, (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days)
    total_weeks = max(1, total_days / 7)

    # Per-person stats
    person_stats = defaultdict(lambda: {"count": 0, "types": set(), "depths": [], "last_date": ""})
    for i in items:
        p = i.get("person", "Unknown")
        person_stats[p]["count"] += 1
        person_stats[p]["types"].add(i.get("type", "other"))
        person_stats[p]["depths"].append(i.get("depth", "surface"))
        if i.get("date", "") > person_stats[p]["last_date"]:
            person_stats[p]["last_date"] = i["date"]

    # Depth distribution
    depth_counts = {"surface": 0, "meaningful": 0, "deep": 0}
    for i in items:
        d = i.get("depth", "surface")
        if d in depth_counts:
            depth_counts[d] += 1

    # Type distribution
    type_counts = defaultdict(int)
    for i in items:
        type_counts[i.get("type", "other")] += 1

    # Weekly trend (last 8 weeks or full period)
    weekly_trend = []
    d = datetime.strptime(start, "%Y-%m-%d")
    d_end = datetime.strptime(end, "%Y-%m-%d")
    while d <= d_end:
        week_start = d.strftime("%Y-%m-%d")
        week_end = (d + timedelta(days=6)).strftime("%Y-%m-%d")
        week_items = [i for i in items if week_start <= i.get("date", "") <= week_end]
        unique_people = len(set(i.get("person") for i in week_items))
        weekly_trend.append({
            "week_of": week_start,
            "interactions": len(week_items),
            "unique_people": unique_people,
            "deep_count": sum(1 for i in week_items if i.get("depth") == "deep"),
        })
        d += timedelta(days=7)

    # Build person leaderboard
    leaderboard = []
    for person, stats in sorted(person_stats.items(), key=lambda x: -x[1]["count"]):
        depths = stats["depths"]
        depth_score = sum({"surface": 1, "meaningful": 2, "deep": 3}.get(d, 1) for d in depths) / len(depths)
        days_since = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(stats["last_date"], "%Y-%m-%d")).days
        leaderboard.append({
            "person": person,
            "interactions": stats["count"],
            "avg_depth_score": round(depth_score, 1),
            "channels": list(stats["types"]),
            "last_contact": stats["last_date"],
            "days_since_contact": days_since,
        })

    # Murthy thresholds
    unique_people = len(person_stats)
    weekly_avg = round(len(items) / total_weeks, 1)
    deep_pct = round(100 * depth_counts["deep"] / len(items), 1) if items else 0

    # Assessment
    connection_health = "healthy"
    flags = []
    if unique_people < 3:
        connection_health = "concerning"
        flags.append(f"Only {unique_people} unique connections — Murthy threshold is 3-5.")
    elif unique_people < 5:
        connection_health = "building"
        flags.append(f"{unique_people} unique connections — approaching Murthy's 3-5 threshold.")
    if weekly_avg < 2:
        flags.append(f"Only {weekly_avg} interactions/week — aim for 3+.")
    if deep_pct < 10 and len(items) >= 5:
        flags.append(f"Only {deep_pct}% deep conversations — consider more vulnerable exchanges.")

    # Stale contacts (>14 days since last interaction)
    stale = [p for p in leaderboard if p["days_since_contact"] > 14]

    return {
        "period": f"{start} to {end}",
        "total_interactions": len(items),
        "unique_people": unique_people,
        "weekly_average": weekly_avg,
        "connection_health": connection_health,
        "depth_distribution": depth_counts,
        "deep_conversation_pct": deep_pct,
        "type_distribution": dict(type_counts),
        "flags": flags,
        "stale_contacts": [{"person": p["person"], "days_since": p["days_since_contact"], "last": p["last_contact"]} for p in stale[:5]],
        "people": leaderboard[:15],
        "weekly_trend": weekly_trend[-8:],
    }


# ═══════════════════════════════════════════════════════════════════════
# #35 — TEMPTATION LOGGING (Sponsor: Coach Maya Rodriguez)
# ═══════════════════════════════════════════════════════════════════════

_TEMPTATION_CATEGORIES = [
    "food", "alcohol", "sleep_sabotage", "skip_workout",
    "screen_time", "social_avoidance", "impulse_purchase", "other",
]


def tool_log_temptation(args):
    """Log a temptation moment — resisted or succumbed."""
    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    category = args.get("category", "other").lower()
    resisted = args.get("resisted")

    if resisted is None:
        return {"error": "resisted (true/false) is required."}
    if category not in _TEMPTATION_CATEGORIES:
        return {"error": f"Invalid category '{category}'. Valid: {_TEMPTATION_CATEGORIES}"}

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    sk = f"DATE#{date}#T#{ts}"

    item = {
        "pk": TEMPTATIONS_PK,
        "sk": sk,
        "date": date,
        "category": category,
        "resisted": bool(resisted),
        "source": "temptations",
        "logged_at": datetime.utcnow().isoformat(),
    }

    if args.get("trigger"):
        item["trigger"] = args["trigger"].strip()
    if args.get("notes"):
        item["notes"] = args["notes"].strip()
    if args.get("intensity"):
        intensity = int(args["intensity"])
        if 1 <= intensity <= 5:
            item["intensity"] = intensity
    if args.get("time_of_day"):
        item["time_of_day"] = args["time_of_day"].strip()

    try:
        table.put_item(Item=item)
    except Exception as e:
        return {"error": f"Failed to log temptation: {e}"}

    outcome = "resisted" if resisted else "succumbed"
    return {
        "status": "logged",
        "date": date,
        "category": category,
        "resisted": bool(resisted),
        "intensity": item.get("intensity"),
        "trigger": item.get("trigger"),
        "message": f"Temptation logged: {category} — {outcome} on {date}.",
    }


def tool_get_temptation_trend(args):
    """Temptation trend: resist rate, category breakdown, triggers, patterns."""
    end = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": TEMPTATIONS_PK,
            ":s": f"DATE#{start}",
            ":e": f"DATE#{end}\xff",
        },
    )
    items = [decimal_to_float(i) for i in resp.get("Items", [])]
    items.sort(key=lambda x: x.get("date", ""))

    if not items:
        return {
            "period": f"{start} to {end}",
            "total": 0,
            "message": "No temptations logged yet. Use log_temptation to start tracking.",
        }

    total = len(items)
    resisted = sum(1 for i in items if i.get("resisted"))
    succumbed = total - resisted
    resist_rate = round(100 * resisted / total, 1)

    # Category breakdown
    cat_stats = defaultdict(lambda: {"total": 0, "resisted": 0})
    for i in items:
        cat = i.get("category", "other")
        cat_stats[cat]["total"] += 1
        if i.get("resisted"):
            cat_stats[cat]["resisted"] += 1

    categories = {}
    for cat, stats in cat_stats.items():
        categories[cat] = {
            "total": stats["total"],
            "resisted": stats["resisted"],
            "succumbed": stats["total"] - stats["resisted"],
            "resist_rate_pct": round(100 * stats["resisted"] / stats["total"], 1) if stats["total"] > 0 else 0,
        }

    # Common triggers
    trigger_counts = defaultdict(int)
    for i in items:
        t = i.get("trigger")
        if t:
            trigger_counts[t.lower()] += 1
    top_triggers = sorted(trigger_counts.items(), key=lambda x: -x[1])[:5]

    # Weekly trend
    weekly = []
    d = datetime.strptime(start, "%Y-%m-%d")
    d_end = datetime.strptime(end, "%Y-%m-%d")
    while d <= d_end:
        ws = d.strftime("%Y-%m-%d")
        we = (d + timedelta(days=6)).strftime("%Y-%m-%d")
        week_items = [i for i in items if ws <= i.get("date", "") <= we]
        if week_items:
            wr = sum(1 for i in week_items if i.get("resisted"))
            weekly.append({
                "week_of": ws,
                "total": len(week_items),
                "resisted": wr,
                "resist_rate_pct": round(100 * wr / len(week_items), 1),
            })
        d += timedelta(days=7)

    # Time-of-day pattern
    tod_counts = defaultdict(lambda: {"total": 0, "resisted": 0})
    for i in items:
        tod = i.get("time_of_day", "unknown")
        tod_counts[tod]["total"] += 1
        if i.get("resisted"):
            tod_counts[tod]["resisted"] += 1

    # Intensity analysis
    intensities = [i.get("intensity") for i in items if i.get("intensity")]
    avg_intensity = round(sum(intensities) / len(intensities), 1) if intensities else None
    resisted_intensities = [i.get("intensity") for i in items if i.get("intensity") and i.get("resisted")]
    succumbed_intensities = [i.get("intensity") for i in items if i.get("intensity") and not i.get("resisted")]
    avg_resisted_intensity = round(sum(resisted_intensities) / len(resisted_intensities), 1) if resisted_intensities else None
    avg_succumbed_intensity = round(sum(succumbed_intensities) / len(succumbed_intensities), 1) if succumbed_intensities else None

    # Assessment
    assessment = "strong" if resist_rate >= 75 else "building" if resist_rate >= 50 else "struggling"
    flags = []
    if resist_rate < 50:
        flags.append(f"Resist rate at {resist_rate}% — below 50%. Focus on the weakest category.")
    worst_cat = min(categories.items(), key=lambda x: x[1]["resist_rate_pct"]) if categories else None
    if worst_cat and worst_cat[1]["resist_rate_pct"] < 40 and worst_cat[1]["total"] >= 3:
        flags.append(f"Weakest category: {worst_cat[0]} ({worst_cat[1]['resist_rate_pct']}% resist rate).")

    return {
        "period": f"{start} to {end}",
        "total": total,
        "resisted": resisted,
        "succumbed": succumbed,
        "resist_rate_pct": resist_rate,
        "assessment": assessment,
        "categories": categories,
        "top_triggers": [{"trigger": t, "count": c} for t, c in top_triggers],
        "intensity": {
            "overall_avg": avg_intensity,
            "avg_when_resisted": avg_resisted_intensity,
            "avg_when_succumbed": avg_succumbed_intensity,
        },
        "flags": flags,
        "weekly_trend": weekly[-8:],
    }


# ═══════════════════════════════════════════════════════════════════════
# #36 — COLD/HEAT EXPOSURE LOGGING & CORRELATION (Sponsor: Huberman)
# ═══════════════════════════════════════════════════════════════════════

_EXPOSURE_TYPES = ["cold_shower", "cold_plunge", "ice_bath", "sauna", "hot_bath", "contrast", "other"]


def tool_log_exposure(args):
    """Log a cold or heat exposure session."""
    date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    exposure_type = args.get("type", "").lower()
    if not exposure_type:
        return {"error": "type is required."}
    if exposure_type not in _EXPOSURE_TYPES:
        return {"error": f"Invalid type '{exposure_type}'. Valid: {_EXPOSURE_TYPES}"}

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    sk = f"DATE#{date}#E#{ts}"

    item = {
        "pk": EXPOSURES_PK,
        "sk": sk,
        "date": date,
        "type": exposure_type,
        "source": "exposures",
        "logged_at": datetime.utcnow().isoformat(),
    }

    is_cold = exposure_type in ("cold_shower", "cold_plunge", "ice_bath")
    is_heat = exposure_type in ("sauna", "hot_bath")

    if args.get("duration_min"):
        item["duration_min"] = Decimal(str(float(args["duration_min"])))
    if args.get("temperature_f"):
        item["temperature_f"] = Decimal(str(float(args["temperature_f"])))
    if args.get("notes"):
        item["notes"] = args["notes"].strip()
    if args.get("time_of_day"):
        item["time_of_day"] = args["time_of_day"].strip()

    # Classify
    item["modality"] = "cold" if is_cold else "heat" if is_heat else "contrast" if exposure_type == "contrast" else "other"

    try:
        table.put_item(Item=item)
    except Exception as e:
        return {"error": f"Failed to log exposure: {e}"}

    return {
        "status": "logged",
        "date": date,
        "type": exposure_type,
        "modality": item["modality"],
        "duration_min": float(item["duration_min"]) if item.get("duration_min") else None,
        "temperature_f": float(item["temperature_f"]) if item.get("temperature_f") else None,
        "message": f"Logged {exposure_type} on {date}.",
    }


def tool_get_exposure_log(args):
    """Retrieve exposure history and summary stats."""
    end = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": EXPOSURES_PK,
            ":s": f"DATE#{start}",
            ":e": f"DATE#{end}\xff",
        },
    )
    items = [decimal_to_float(i) for i in resp.get("Items", [])]
    items.sort(key=lambda x: x.get("date", ""))

    if not items:
        return {
            "period": f"{start} to {end}",
            "total_sessions": 0,
            "message": "No exposure sessions logged yet. Use log_exposure to start tracking.",
        }

    total_days = max(1, (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days)
    total_weeks = max(1, total_days / 7)

    # Type breakdown
    type_counts = defaultdict(int)
    for i in items:
        type_counts[i.get("type", "other")] += 1

    # Modality breakdown
    cold_sessions = [i for i in items if i.get("modality") == "cold"]
    heat_sessions = [i for i in items if i.get("modality") == "heat"]

    # Duration stats
    durations = [i.get("duration_min", 0) for i in items if i.get("duration_min")]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None
    total_min = round(sum(durations), 1)

    # Build sessions list
    sessions = []
    for i in items:
        sessions.append({
            "date": i.get("date"),
            "type": i.get("type"),
            "modality": i.get("modality"),
            "duration_min": i.get("duration_min"),
            "temperature_f": i.get("temperature_f"),
            "time_of_day": i.get("time_of_day"),
            "notes": i.get("notes"),
        })

    return {
        "period": f"{start} to {end}",
        "total_sessions": len(items),
        "weekly_frequency": round(len(items) / total_weeks, 1),
        "cold_sessions": len(cold_sessions),
        "heat_sessions": len(heat_sessions),
        "type_breakdown": dict(type_counts),
        "avg_duration_min": avg_duration,
        "total_duration_min": total_min,
        "sessions": sessions,
    }


def tool_get_exposure_correlation(args):
    """Correlate cold/heat exposure with HRV, sleep, mood, recovery."""
    end = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    # Get exposures
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": EXPOSURES_PK,
            ":s": f"DATE#{start}",
            ":e": f"DATE#{end}\xff",
        },
    )
    exposures = [decimal_to_float(i) for i in resp.get("Items", [])]

    if len(exposures) < 3:
        return {"error": f"Need at least 3 exposure sessions for correlation. Currently: {len(exposures)}."}

    # Build per-date exposure map
    exposure_dates = defaultdict(lambda: {"cold": False, "heat": False, "any": False, "total_min": 0})
    for e in exposures:
        d = e.get("date", "")
        if not d:
            continue
        modality = e.get("modality", "other")
        exposure_dates[d]["any"] = True
        if modality == "cold":
            exposure_dates[d]["cold"] = True
        elif modality == "heat":
            exposure_dates[d]["heat"] = True
        exposure_dates[d]["total_min"] += e.get("duration_min", 0)

    # Get health metrics for the full range
    whoop = query_source("whoop", start, end)
    som = query_source("state_of_mind", start, end)

    whoop_by_date = {i.get("date"): decimal_to_float(i) for i in whoop if i.get("date")}
    som_by_date = {i.get("date"): decimal_to_float(i) for i in som if i.get("date")}

    # Build aligned series
    all_dates = sorted(set(
        list(whoop_by_date.keys())
    ))

    exposure_days = {"hrv": [], "rhr": [], "recovery": [], "sleep_score": [], "som_valence": []}
    rest_days = {"hrv": [], "rhr": [], "recovery": [], "sleep_score": [], "som_valence": []}

    for d in all_dates:
        w = whoop_by_date.get(d, {})
        s = som_by_date.get(d, {})
        is_exposure = d in exposure_dates

        hrv = w.get("hrv_rmssd") or w.get("hrv")
        rhr = w.get("resting_heart_rate")
        recovery = w.get("recovery_score")
        sleep_score = w.get("sleep_score") or w.get("sleep_quality_score")
        valence = s.get("som_avg_valence")

        target = exposure_days if is_exposure else rest_days
        if hrv is not None:
            target["hrv"].append(float(hrv))
        if rhr is not None:
            target["rhr"].append(float(rhr))
        if recovery is not None:
            target["recovery"].append(float(recovery))
        if sleep_score is not None:
            target["sleep_score"].append(float(sleep_score))
        if valence is not None:
            target["som_valence"].append(float(valence))

    # Compute averages
    def _avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else None

    comparison = {}
    for metric in ["hrv", "rhr", "recovery", "sleep_score", "som_valence"]:
        exp_avg = _avg(exposure_days[metric])
        rest_avg = _avg(rest_days[metric])
        delta = round(exp_avg - rest_avg, 2) if exp_avg is not None and rest_avg is not None else None
        comparison[metric] = {
            "exposure_day_avg": exp_avg,
            "rest_day_avg": rest_avg,
            "delta": delta,
            "exposure_day_n": len(exposure_days[metric]),
            "rest_day_n": len(rest_days[metric]),
        }

    # Next-day analysis (exposure today → metrics tomorrow)
    next_day = {"hrv": [], "recovery": [], "sleep_score": []}
    next_day_rest = {"hrv": [], "recovery": [], "sleep_score": []}
    for d in all_dates:
        tomorrow = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        w_next = whoop_by_date.get(tomorrow, {})
        if not w_next:
            continue

        target = next_day if d in exposure_dates else next_day_rest
        hrv = w_next.get("hrv_rmssd") or w_next.get("hrv")
        recovery = w_next.get("recovery_score")
        sleep_score = w_next.get("sleep_score") or w_next.get("sleep_quality_score")
        if hrv is not None:
            target["hrv"].append(float(hrv))
        if recovery is not None:
            target["recovery"].append(float(recovery))
        if sleep_score is not None:
            target["sleep_score"].append(float(sleep_score))

    next_day_comparison = {}
    for metric in ["hrv", "recovery", "sleep_score"]:
        exp_avg = _avg(next_day[metric])
        rest_avg = _avg(next_day_rest[metric])
        delta = round(exp_avg - rest_avg, 2) if exp_avg is not None and rest_avg is not None else None
        next_day_comparison[metric] = {
            "after_exposure_avg": exp_avg,
            "after_rest_avg": rest_avg,
            "delta": delta,
        }

    return {
        "period": f"{start} to {end}",
        "total_exposure_sessions": len(exposures),
        "exposure_days": len(exposure_dates),
        "rest_days": len(all_dates) - len(exposure_dates),
        "same_day_comparison": comparison,
        "next_day_comparison": next_day_comparison,
        "interpretation": {
            "note": (
                "Same-day comparison shows metrics on exposure vs non-exposure days. "
                "Next-day comparison shows whether exposure today predicts better metrics tomorrow. "
                "Huberman protocol: deliberate cold exposure (1-3 min) increases dopamine 2.5x for hours. "
                "Heat exposure (sauna 20+ min) increases growth hormone and improves cardiovascular markers."
            ),
        },
    }
