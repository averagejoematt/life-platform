"""
Journal tools: entries, search, mood, insights, correlations.
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from mcp.config import USER_PREFIX, table
from mcp.core import decimal_to_float

# R22-SCI-02 (#820): fit-quality floor for the sentiment-trajectory regressions below.
# r² < 0.09 is |r| < 0.3 — the same "below moderate" floor already used as the weak/moderate
# correlation boundary in tools_habits.py (habit-lever interpretation) and tools_training.py
# (correlation interpretation). ADR-105 rule 1: every statistical claim carries its fit quality.
_TRAJECTORY_LOW_FIT_R2 = 0.09

# ── Journal query helper ──


def _query_journal(start_date, end_date, template=None):
    """Query journal entries from DynamoDB. Returns list of items."""
    from mcp.core import _apply_phase_filter  # ADR-058

    pk = f"{USER_PREFIX}notion"
    # ADR-058: longitudinal/clinical archive — cross-phase by design (owner decision 2026-06-06)
    kwargs = _apply_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}#journal", f"DATE#{end_date}#journal#~"),
            "ScanIndexForward": True,
        },
        include_pilot=True,
    )
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # Filter to journal items only
    items = [i for i in items if "#journal#" in i.get("sk", "")]

    # Optional template filter
    if template:
        template_lower = template.lower().replace(" ", "_").replace("-", "_")
        alias_map = {
            "morning": "morning",
            "evening": "evening",
            "weekly": "weekly",
            "weekly_reflection": "weekly",
            "stressor": "stressor",
            "health_event": "health",
            "health": "health",
        }
        sk_suffix = alias_map.get(template_lower, template_lower)
        items = [i for i in items if f"#journal#{sk_suffix}" in i.get("sk", "")]

    return [decimal_to_float(i) for i in items]


def _get_mood_trend(args):
    """Mood/energy/stress scores over time with enriched signals."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    metric = args.get("metric", "all")  # mood|energy|stress|all

    items = _query_journal(start, end)

    if not items:
        return {"trend": [], "error": "No journal entries found for this period."}

    # Build daily scores (prefer enriched, fall back to structured)
    daily = {}  # date -> {mood, energy, stress, themes, sentiment}
    for item in items:
        date = item.get("date")
        if not date:
            continue
        if date not in daily:
            daily[date] = {"date": date, "entries": 0}

        daily[date]["entries"] += 1
        template = item.get("template", "")

        # Mood: enriched > morning_mood > day_rating
        mood = item.get("enriched_mood") or item.get("morning_mood") or item.get("day_rating")
        if mood and ("mood" not in daily[date] or template == "Evening"):
            daily[date]["mood"] = float(mood) if mood else None

        # Energy: enriched > morning_energy > energy_eod
        energy = item.get("enriched_energy") or item.get("morning_energy") or item.get("energy_eod")
        if energy and ("energy" not in daily[date] or template == "Evening"):
            daily[date]["energy"] = float(energy) if energy else None

        # Stress: enriched > stress_level
        stress = item.get("enriched_stress") or item.get("stress_level")
        if stress and ("stress" not in daily[date] or template == "Evening"):
            daily[date]["stress"] = float(stress) if stress else None

        # Themes and sentiment from enrichment
        themes = item.get("enriched_themes", [])
        if themes:
            daily[date].setdefault("themes", []).extend(themes)

        sentiment = item.get("enriched_sentiment")
        if sentiment:
            daily[date]["sentiment"] = sentiment

        quote = item.get("enriched_notable_quote")
        if quote:
            daily[date]["notable_quote"] = quote

    trend = sorted(daily.values(), key=lambda x: x["date"])

    # Compute rolling 7-day averages
    for metric_name in ["mood", "energy", "stress"]:
        values = [(i, d.get(metric_name)) for i, d in enumerate(trend) if d.get(metric_name) is not None]
        for idx, val in values:
            window = [v for j, v in values if idx - 6 <= j <= idx]
            if window:
                trend[idx][f"{metric_name}_7d_avg"] = round(sum(window) / len(window), 2)

    # Summary stats
    summary = {}
    for metric_name in ["mood", "energy", "stress"]:
        vals = [d.get(metric_name) for d in trend if d.get(metric_name) is not None]
        if vals:
            summary[metric_name] = {
                "avg": round(sum(vals) / len(vals), 2),
                "min": min(vals),
                "max": max(vals),
                "latest": vals[-1],
                "days_tracked": len(vals),
            }
            # Trend direction (first half vs second half)
            if len(vals) >= 4:
                mid = len(vals) // 2
                first_avg = sum(vals[:mid]) / mid
                second_avg = sum(vals[mid:]) / (len(vals) - mid)
                delta = second_avg - first_avg
                if metric_name == "stress":
                    # For stress, down is good
                    direction = "improving" if delta < -0.3 else "worsening" if delta > 0.3 else "stable"
                else:
                    direction = "improving" if delta > 0.3 else "declining" if delta < -0.3 else "stable"
                summary[metric_name]["trend_direction"] = direction
                summary[metric_name]["half_delta"] = round(delta, 2)

    # Top recurring themes
    all_themes = []
    for d in trend:
        all_themes.extend(d.get("themes", []))
    theme_counts = {}
    for t in all_themes:
        theme_counts[t] = theme_counts.get(t, 0) + 1
    top_themes = sorted(theme_counts.items(), key=lambda x: -x[1])[:5]

    result = {
        "trend": trend,
        "summary": summary,
        "top_themes": [{"theme": t, "count": c} for t, c in top_themes],
        "days_with_entries": len(trend),
        "date_range": f"{start} to {end}",
    }

    # Filter to requested metric if not "all"
    if metric != "all" and metric in summary:
        result["summary"] = {metric: summary[metric]}

    return result


def tool_get_mood(args):
    """Unified mood/state-of-mind dispatcher.
    mood_trend = subjective journal-derived mood; state_of_mind = Apple Health HWF valence.
    """
    from mcp.tools_lifestyle import _get_state_of_mind_trend

    VALID_VIEWS = {
        "trend": _get_mood_trend,
        "state_of_mind": _get_state_of_mind_trend,
    }
    view = (args.get("view") or "trend").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'trend' for journal-derived mood/energy/stress scores, 'state_of_mind' for Apple Health How We Feel valence data.",
        }
    return VALID_VIEWS[view](args)


# ── BS-MP2: Journal Sentiment Trajectory ─────────────────────────────────
