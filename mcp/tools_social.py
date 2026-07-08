"""
Social, behavioral, and protocol tools:
  - Life event tagging (#40)
  - Contact frequency tracking (#42)
  - Temptation logging (#35)
  - Cold/heat exposure logging & correlation (#36)
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from mcp.config import INTERACTIONS_PK, table
from mcp.core import decimal_to_float

# ═══════════════════════════════════════════════════════════════════════
# #40 — LIFE EVENT TAGGING (Sponsor: Elena Voss)
# ═══════════════════════════════════════════════════════════════════════

_LIFE_EVENT_TYPES = [
    "birthday",
    "anniversary",
    "work_milestone",
    "social",
    "conflict",
    "loss",
    "health_milestone",
    "travel",
    "relationship",
    "financial",
    "achievement",
    "setback",
    "other",
]


# ═══════════════════════════════════════════════════════════════════════
# #42 — CONTACT FREQUENCY TRACKING (Sponsor: Vivek Murthy)
# ═══════════════════════════════════════════════════════════════════════

_INTERACTION_TYPES = ["call", "text", "in_person", "video", "email", "social_media", "other"]
_DEPTH_LEVELS = ["surface", "meaningful", "deep"]


def tool_get_social_dashboard(args):
    """Social connection dashboard: frequency, diversity, depth, trends."""
    end = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d"))

    from mcp.core import _apply_phase_filter  # ADR-058

    resp = table.query(
        **_apply_phase_filter(
            {
                "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                "ExpressionAttributeValues": {
                    ":pk": INTERACTIONS_PK,
                    ":s": f"DATE#{start}",
                    ":e": f"DATE#{end}\xff",
                },
            }
        )
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
        weekly_trend.append(
            {
                "week_of": week_start,
                "interactions": len(week_items),
                "unique_people": unique_people,
                "deep_count": sum(1 for i in week_items if i.get("depth") == "deep"),
            }
        )
        d += timedelta(days=7)

    # Build person leaderboard
    leaderboard = []
    for person, stats in sorted(person_stats.items(), key=lambda x: -x[1]["count"]):
        depths = stats["depths"]
        depth_score = sum({"surface": 1, "meaningful": 2, "deep": 3}.get(d, 1) for d in depths) / len(depths)
        days_since = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(stats["last_date"], "%Y-%m-%d")).days
        leaderboard.append(
            {
                "person": person,
                "interactions": stats["count"],
                "avg_depth_score": round(depth_score, 1),
                "channels": list(stats["types"]),
                "last_contact": stats["last_date"],
                "days_since_contact": days_since,
            }
        )

    # Murthy thresholds
    unique_people = len(person_stats)
    weekly_avg = round(len(items) / total_weeks, 1)
    deep_pct = round(100 * depth_counts["deep"] / len(items), 1) if items else 0

    # Assessment
    connection_health = "healthy"
    flags = []
    if unique_people < 3:
        connection_health = "concerning"
        # Murthy "Together" (2020): 3-5 close relationships minimum for wellbeing
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
    "food",
    "alcohol",
    "sleep_sabotage",
    "skip_workout",
    "screen_time",
    "social_avoidance",
    "impulse_purchase",
    "other",
]


# ═══════════════════════════════════════════════════════════════════════
# #36 — COLD/HEAT EXPOSURE LOGGING & CORRELATION (Sponsor: Huberman)
# ═══════════════════════════════════════════════════════════════════════

_EXPOSURE_TYPES = ["cold_shower", "cold_plunge", "ice_bath", "sauna", "hot_bath", "contrast", "other"]


# ═══════════════════════════════════════════════════════════════════════
# DISC-7 — DISCOVERY ANNOTATIONS (behavioral response to findings)
# ═══════════════════════════════════════════════════════════════════════

import hashlib as _hashlib


def _make_event_key(date: str, event_type: str, title: str) -> str:
    """Compute deterministic key for a timeline event."""
    raw = f"{date}|{event_type}|{title}"
    return _hashlib.sha256(raw.encode()).hexdigest()[:16]
