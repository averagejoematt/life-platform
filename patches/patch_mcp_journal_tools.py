#!/usr/bin/env python3
"""
Patch MCP server to add Notion Journal tools (Phase 3).

Adds:
  - 'notion' to SOURCES list
  - 'journal' to _DEFAULT_SOURCE_OF_TRUTH
  - 5 tool functions (before TOOLS dict)
  - 5 TOOLS dict entries
  - Version bump to v2.16.0

Usage: python3 patch_mcp_journal_tools.py
"""

import re

MCP_FILE = "mcp_server.py"

# ── Tool implementations ──────────────────────────────────────────────────────

TOOL_FUNCTIONS = '''

# ── Journal tools (v2.16.0) ──────────────────────────────────────────────────

def _query_journal(start_date, end_date, template=None):
    """Query journal entries from DynamoDB. Returns list of items."""
    pk = f"{USER_PREFIX}notion"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}#journal",
            f"DATE#{end_date}#journal#~"
        ),
        "ScanIndexForward": True,
    }
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
            "morning": "morning", "evening": "evening", "weekly": "weekly",
            "weekly_reflection": "weekly", "stressor": "stressor",
            "health_event": "health", "health": "health",
        }
        sk_suffix = alias_map.get(template_lower, template_lower)
        items = [i for i in items if f"#journal#{sk_suffix}" in i.get("sk", "")]

    return [decimal_to_float(i) for i in items]


def tool_get_journal_entries(args):
    """Retrieve journal entries for a date range with optional template filter."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    template = args.get("template")
    include_enriched = args.get("include_enriched", True)

    items = _query_journal(start, end, template)

    if not items:
        return {"entries": [], "count": 0, "date_range": f"{start} to {end}",
                "message": "No journal entries found. Start journaling in Notion!"}

    # Optionally strip enriched fields for cleaner output
    if not include_enriched:
        for item in items:
            keys_to_remove = [k for k in item if k.startswith("enriched_")]
            for k in keys_to_remove:
                del item[k]

    # Remove internal fields
    for item in items:
        item.pop("pk", None)
        item.pop("sk", None)
        item.pop("raw_text", None)  # Haiku sees this, user doesn't need it

    return {
        "entries": items,
        "count": len(items),
        "date_range": f"{start} to {end}",
        "templates_found": list(set(i.get("template", "") for i in items)),
    }


def tool_search_journal(args):
    """Full-text search across journal entries."""
    query = args.get("query", "").lower().strip()
    if not query:
        raise ValueError("query parameter is required")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", "2020-01-01")
    end = args.get("end_date", today)

    items = _query_journal(start, end)

    # Search across raw_text and enriched fields
    matches = []
    keywords = query.split()

    for item in items:
        searchable = " ".join([
            str(item.get("raw_text", "")),
            " ".join(item.get("enriched_themes", [])),
            " ".join(item.get("enriched_emotions", [])),
            " ".join(item.get("enriched_avoidance_flags", [])),
            " ".join(item.get("enriched_growth_signals", [])),
            " ".join(item.get("enriched_pain", [])),
            str(item.get("enriched_notable_quote", "")),
            str(item.get("enriched_sleep_context", "")),
            str(item.get("enriched_exercise_context", "")),
            " ".join(item.get("enriched_values_lived", [])),
            " ".join(item.get("enriched_cognitive_patterns", [])),
        ]).lower()

        if all(kw in searchable for kw in keywords):
            # Build a concise match summary
            match = {
                "date": item.get("date"),
                "template": item.get("template"),
                "enriched_mood": item.get("enriched_mood"),
                "enriched_stress": item.get("enriched_stress"),
                "enriched_themes": item.get("enriched_themes"),
                "enriched_emotions": item.get("enriched_emotions"),
                "enriched_notable_quote": item.get("enriched_notable_quote"),
            }
            # Add template-specific highlights
            for field in ["win_of_the_day", "what_drained_me", "notable_events",
                          "what_happened", "notes", "todays_intention", "gratitude",
                          "avoiding", "biggest_win", "biggest_challenge", "description"]:
                if field in item and item[field]:
                    match[field] = item[field]
            matches.append(match)

    return {
        "query": query,
        "matches": [decimal_to_float(m) for m in matches],
        "count": len(matches),
        "date_range": f"{start} to {end}",
    }


def tool_get_mood_trend(args):
    """Mood/energy/stress scores over time with enriched signals."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    metric = args.get("metric", "all")  # mood|energy|stress|all

    items = _query_journal(start, end)

    if not items:
        return {"trend": [], "message": "No journal entries found for this period."}

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


def tool_get_journal_insights(args):
    """Cross-entry pattern analysis — the 'so what?' tool."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)

    items = _query_journal(start, end)

    if not items:
        return {"message": "No journal entries found. Start journaling to unlock insights!"}

    # Aggregate enriched signals
    emotions_all = []
    themes_all = []
    patterns_all = []
    growth_all = []
    avoidance_all = []
    values_all = []
    gratitude_all = []
    pain_all = []

    mood_scores = []
    energy_scores = []
    stress_scores = []
    ownership_scores = []
    social_entries = []
    flow_count = 0
    alcohol_days = 0
    total_days = set()
    quotes = []

    for item in items:
        date = item.get("date", "")
        total_days.add(date)

        emotions_all.extend(item.get("enriched_emotions", []))
        themes_all.extend(item.get("enriched_themes", []))
        patterns_all.extend(item.get("enriched_cognitive_patterns", []))
        growth_all.extend(item.get("enriched_growth_signals", []))
        avoidance_all.extend(item.get("enriched_avoidance_flags", []))
        values_all.extend(item.get("enriched_values_lived", []))
        gratitude_all.extend(item.get("enriched_gratitude", []))
        pain_all.extend(item.get("enriched_pain", []))

        mood = item.get("enriched_mood")
        if mood: mood_scores.append(float(mood))
        energy = item.get("enriched_energy")
        if energy: energy_scores.append(float(energy))
        stress = item.get("enriched_stress")
        if stress: stress_scores.append(float(stress))
        ownership = item.get("enriched_ownership")
        if ownership: ownership_scores.append(float(ownership))

        social = item.get("enriched_social_quality")
        if social: social_entries.append(social)

        if item.get("enriched_flow"): flow_count += 1
        if item.get("enriched_alcohol"): alcohol_days += 1

        quote = item.get("enriched_notable_quote")
        if quote: quotes.append({"date": date, "quote": quote})

    def rank_items(items_list, top_n=8):
        counts = {}
        for i in items_list:
            counts[i] = counts.get(i, 0) + 1
        return [{"item": k, "count": v} for k, v in
                sorted(counts.items(), key=lambda x: -x[1])[:top_n]]

    def avg(vals):
        return round(sum(vals) / len(vals), 2) if vals else None

    # Cognitive pattern breakdown
    positive_patterns = ["reframing", "growth mindset", "self-compassion", "perspective-taking"]
    neg_patterns = [p for p in patterns_all if p not in positive_patterns]
    pos_patterns = [p for p in patterns_all if p in positive_patterns]

    # Social quality distribution
    social_dist = {}
    for s in social_entries:
        social_dist[s] = social_dist.get(s, 0) + 1

    result = {
        "date_range": f"{start} to {end}",
        "total_entries": len(items),
        "days_with_entries": len(total_days),

        "scores": {
            "mood_avg": avg(mood_scores),
            "energy_avg": avg(energy_scores),
            "stress_avg": avg(stress_scores),
            "ownership_avg": avg(ownership_scores),
        },

        "top_emotions": rank_items(emotions_all),
        "top_themes": rank_items(themes_all),
        "top_values_lived": rank_items(values_all),

        "cognitive_patterns": {
            "negative": rank_items(neg_patterns, 5),
            "positive": rank_items(pos_patterns, 5),
            "total_flags": len(patterns_all),
        },

        "growth_signals": rank_items(growth_all, 5),
        "avoidance_flags": rank_items(avoidance_all, 5),

        "social_connection": {
            "distribution": social_dist,
            "entries_with_social": len(social_entries),
        },

        "flow_states": {
            "count": flow_count,
            "pct_of_entries": round(flow_count / len(items) * 100, 1) if items else 0,
        },

        "gratitude": {
            "unique_items": len(set(gratitude_all)),
            "top_items": rank_items(gratitude_all, 5),
        },

        "pain_flags": rank_items(pain_all, 5),

        "alcohol_days": alcohol_days,

        "notable_quotes": quotes[-5:],  # Last 5 quotes
    }

    return result


def tool_get_journal_correlations(args):
    """Correlate journal signals with wearable data."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    signal = args.get("signal", "all")  # stress|mood|energy|sleep_quality|all

    # Get journal data
    journal_items = _query_journal(start, end)
    if not journal_items:
        return {"message": "No journal entries found for correlation analysis."}

    # Build daily journal scores
    journal_by_date = {}
    for item in journal_items:
        date = item.get("date")
        if not date:
            continue
        if date not in journal_by_date:
            journal_by_date[date] = {}
        jd = journal_by_date[date]

        # Take enriched scores where available, fall back to structured
        for field, enriched_key, structured_keys in [
            ("mood", "enriched_mood", ["morning_mood", "day_rating"]),
            ("energy", "enriched_energy", ["morning_energy", "energy_eod"]),
            ("stress", "enriched_stress", ["stress_level"]),
            ("sleep_quality", None, ["subjective_sleep_quality"]),
        ]:
            if field in jd:
                continue
            val = item.get(enriched_key) if enriched_key else None
            if not val:
                for sk in structured_keys:
                    val = item.get(sk)
                    if val:
                        break
            if val:
                jd[field] = float(val)

    # Get wearable data for same dates
    wearable_sources = {
        "whoop": ["recovery_score", "hrv", "resting_heart_rate", "strain"],
        "eightsleep": ["sleep_score", "sleep_efficiency", "total_sleep_seconds"],
        "garmin": ["avg_stress", "body_battery_end", "training_readiness"],
    }

    wearable_by_date = {}
    for source, fields in wearable_sources.items():
        source_items = query_source_range(source, start, end)
        for item in source_items:
            date = item.get("date")
            if not date:
                continue
            wearable_by_date.setdefault(date, {})
            for f in fields:
                val = item.get(f)
                if val is not None:
                    wearable_by_date[date][f"{source}_{f}"] = float(val)

    # Build paired observations for correlation
    correlations = {}
    journal_signals = ["mood", "energy", "stress", "sleep_quality"]
    if signal != "all":
        journal_signals = [signal]

    for js in journal_signals:
        for wearable_field in sorted(set(f for d in wearable_by_date.values() for f in d)):
            pairs = []
            for date in journal_by_date:
                j_val = journal_by_date[date].get(js)
                w_val = (wearable_by_date.get(date) or {}).get(wearable_field)
                if j_val is not None and w_val is not None:
                    pairs.append((j_val, w_val))

            if len(pairs) >= 5:
                # Compute Pearson r
                n = len(pairs)
                sum_x = sum(p[0] for p in pairs)
                sum_y = sum(p[1] for p in pairs)
                sum_xy = sum(p[0] * p[1] for p in pairs)
                sum_x2 = sum(p[0] ** 2 for p in pairs)
                sum_y2 = sum(p[1] ** 2 for p in pairs)

                denom = math.sqrt((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2))
                if denom > 0:
                    r = (n * sum_xy - sum_x * sum_y) / denom
                    strength = "strong" if abs(r) > 0.5 else "moderate" if abs(r) > 0.3 else "weak"
                    direction = "positive" if r > 0 else "negative"

                    correlations.setdefault(js, []).append({
                        "wearable_metric": wearable_field,
                        "pearson_r": round(r, 3),
                        "strength": strength,
                        "direction": direction,
                        "n": n,
                    })

    # Sort by absolute correlation strength
    for js in correlations:
        correlations[js].sort(key=lambda x: -abs(x["pearson_r"]))

    # Notable divergences (subjective vs objective)
    divergences = []
    for date in journal_by_date:
        j = journal_by_date[date]
        w = wearable_by_date.get(date, {})

        # Sleep quality divergence: low subjective + high objective (or vice versa)
        subj_sleep = j.get("sleep_quality")
        obj_sleep = w.get("eightsleep_sleep_score")
        if subj_sleep and obj_sleep:
            if subj_sleep <= 2 and obj_sleep >= 80:
                divergences.append({
                    "date": date, "type": "sleep_misperception_negative",
                    "subjective": subj_sleep, "objective": obj_sleep,
                    "note": "Felt terrible but objective sleep was good — possible sleep state misperception",
                })
            elif subj_sleep >= 4 and obj_sleep <= 60:
                divergences.append({
                    "date": date, "type": "sleep_misperception_positive",
                    "subjective": subj_sleep, "objective": obj_sleep,
                    "note": "Felt great but objective sleep was poor — may not be reading body signals accurately",
                })

        # Stress divergence: high journal stress + high Whoop recovery
        subj_stress = j.get("stress")
        obj_recovery = w.get("whoop_recovery_score")
        if subj_stress and obj_recovery:
            if subj_stress >= 4 and obj_recovery >= 80:
                divergences.append({
                    "date": date, "type": "psychological_not_physiological",
                    "subjective_stress": subj_stress, "whoop_recovery": obj_recovery,
                    "note": "High perceived stress but body recovering well — likely psychological, not physical",
                })

    return {
        "date_range": f"{start} to {end}",
        "journal_days": len(journal_by_date),
        "wearable_days": len(wearable_by_date),
        "paired_days": len(set(journal_by_date) & set(wearable_by_date)),
        "correlations": correlations,
        "notable_divergences": divergences[:10],
    }


def query_source_range(source, start_date, end_date):
    """Helper: query a source for a date range."""
    pk = f"{USER_PREFIX}{source}"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}"
        ),
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [decimal_to_float(i) for i in items]

'''

# ── TOOLS dict entries ────────────────────────────────────────────────────────

TOOL_ENTRIES = '''
    # ── Journal tools (v2.16.0) ────────────────────────────────────────────────
    "get_journal_entries": {
        "fn": tool_get_journal_entries,
        "schema": {
            "name": "get_journal_entries",
            "description": (
                "Retrieve journal entries for a date range with optional template filter. "
                "Returns structured fields + Haiku-enriched signals (mood, energy, stress, "
                "themes, emotions, cognitive patterns, values, etc). "
                "Use for: 'show my journal from last week', 'what did I write this morning?', "
                "'evening entries from January', 'my weekly reflections'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 7 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "template":   {"type": "string", "description": "Filter by template: morning, evening, stressor, health_event, weekly. Optional."},
                    "include_enriched": {"type": "boolean", "description": "Include Haiku-enriched fields (default: true)."},
                },
                "required": [],
            },
        },
    },
    "search_journal": {
        "fn": tool_search_journal,
        "schema": {
            "name": "search_journal",
            "description": (
                "Full-text search across all journal entries — searches raw text, themes, "
                "emotions, avoidance flags, pain mentions, quotes, and all enriched fields. "
                "Use for: 'when did I mention back pain?', 'find entries about work stress', "
                "'search for entries where I felt lonely', 'find journal mentions of alcohol'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query":      {"type": "string", "description": "Search keywords (all must match)."},
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: all time)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                },
                "required": ["query"],
            },
        },
    },
    "get_mood_trend": {
        "fn": tool_get_mood_trend,
        "schema": {
            "name": "get_mood_trend",
            "description": (
                "Mood, energy, and stress scores over time with 7-day rolling averages, "
                "trend direction, and recurring themes at peaks/valleys. Combines structured "
                "Notion scores with Haiku-enriched signals for the most accurate longitudinal view. "
                "Use for: 'how has my mood been this month?', 'stress trend over 30 days', "
                "'am I getting better?', 'energy trend', 'mood and stress together'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "metric":     {"type": "string", "description": "mood, energy, stress, or all (default: all)."},
                },
                "required": [],
            },
        },
    },
    "get_journal_insights": {
        "fn": tool_get_journal_insights,
        "schema": {
            "name": "get_journal_insights",
            "description": (
                "Cross-entry pattern analysis — the 'so what?' tool. Surfaces recurring themes, "
                "dominant emotions, cognitive pattern frequency (CBT: catastrophizing, rumination, "
                "reframing, growth mindset), avoidance flags, ownership trend (locus of control), "
                "values alignment, social connection quality, flow state frequency, and gratitude patterns. "
                "Based on Seligman (PERMA), Beck (CBT), Ferriss (fear-setting), Jocko (ownership), "
                "Huberman (stress), Csikszentmihalyi (flow). "
                "Use for: 'what patterns do you see in my journal?', 'what am I consistently avoiding?', "
                "'how is my ownership trending?', 'cognitive pattern analysis', 'journal insights'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_journal_correlations": {
        "fn": tool_get_journal_correlations,
        "schema": {
            "name": "get_journal_correlations",
            "description": (
                "Correlate journal signals (mood, energy, stress, subjective sleep quality) "
                "with wearable data (Whoop recovery/HRV/strain, Eight Sleep score/efficiency, "
                "Garmin stress/Body Battery/readiness). Finds Pearson correlations and notable "
                "divergences where subjective experience doesn't match objective data "
                "(e.g. 'felt terrible but Eight Sleep scored 85' = possible sleep state misperception). "
                "Use for: 'does my mood correlate with HRV?', 'subjective vs objective sleep', "
                "'do high-stress days affect my recovery?', 'journal-wearable correlations'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 60 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "signal":     {"type": "string", "description": "stress, mood, energy, sleep_quality, or all (default: all)."},
                },
                "required": [],
            },
        },
    },
'''


def main():
    with open(MCP_FILE, "r") as f:
        content = f.read()

    changes = 0

    # 1. Add 'notion' to SOURCES if not present
    if '"notion"' not in content.split("SOURCES")[1].split("]")[0]:
        content = content.replace(
            '"habitify", "labs"',
            '"habitify", "notion", "labs"'
        )
        changes += 1
        print("  ✓ Added 'notion' to SOURCES")

    # 2. Add 'journal' to _DEFAULT_SOURCE_OF_TRUTH if not present
    if '"journal"' not in content:
        content = content.replace(
            '    "sleep":       "eightsleep",',
            '    "sleep":       "eightsleep",\n    "journal":     "notion",         # Subjective journal — Notion (morning, evening, ad-hoc)',
        )
        changes += 1
        print("  ✓ Added 'journal' to _DEFAULT_SOURCE_OF_TRUTH")

    # 3. Insert tool functions before the TOOLS dict
    tools_marker = "\nTOOLS = {"
    if "tool_get_journal_entries" not in content:
        content = content.replace(tools_marker, TOOL_FUNCTIONS + tools_marker)
        changes += 1
        print("  ✓ Added 5 journal tool functions")

    # 4. Insert TOOLS dict entries before the closing brace
    # Find the last entry in TOOLS and add after it
    if '"get_journal_entries"' not in content:
        # Insert before the closing }
        # Find the last tool entry (get_glucose_exercise_correlation closing)
        content = content.replace(
            "\n}\n\n\n# ── MCP protocol handlers",
            TOOL_ENTRIES + "\n}\n\n\n# ── MCP protocol handlers"
        )
        changes += 1
        print("  ✓ Added 5 journal TOOLS entries")

    # 5. Version bump
    content = content.replace(
        'life-platform MCP Server v2.15.0',
        'life-platform MCP Server v2.16.0'
    )
    content = content.replace(
        '"version": "2.15.0"',
        '"version": "2.16.0"'
    )
    changes += 1
    print("  ✓ Version bumped to v2.16.0")

    with open(MCP_FILE, "w") as f:
        f.write(content)

    print(f"\n  ✅ {changes} changes applied to {MCP_FILE}")
    print(f"  New tools: get_journal_entries, search_journal, get_mood_trend,")
    print(f"             get_journal_insights, get_journal_correlations")
    print(f"  Total tools: 52 + 5 = 57")


if __name__ == "__main__":
    main()
