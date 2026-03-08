#!/usr/bin/env python3
"""
Patch mcp_server.py to add Features #12 + #25 tool functions and TOOLS dict entries.
Run BEFORE deploying. Idempotent — safe to run multiple times.
"""
import sys
import os

MCP_PATH = os.path.expanduser("~/Documents/Claude/life-platform/mcp_server.py")

# ══════════════════════════════════════════════════════════════════════════════
# TOOL FUNCTIONS — inserted BEFORE TOOLS = { dict
# ══════════════════════════════════════════════════════════════════════════════

TOOL_FUNCTIONS = r'''

# ── Feature #12: Social Connection Scoring ─────────────────────────────────────

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
        ("eightsleep", "sleep_score", "Sleep Score"), ("garmin", "avg_stress", "Stress"),
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
    for src in ["whoop", "eightsleep", "garmin"]:
        try:
            health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
        except Exception:
            health_data[src] = {}

    for ep in episodes:
        ep_start = datetime.strptime(ep["start"], "%Y-%m-%d")
        pre_start = (ep_start - timedelta(days=7)).strftime("%Y-%m-%d")
        pre_end = (ep_start - timedelta(days=1)).strftime("%Y-%m-%d")
        impact = {"episode": ep, "health_deltas": {}}
        for src, field, label in [("whoop","recovery_score","Recovery"),("whoop","hrv","HRV"),("eightsleep","sleep_score","Sleep"),("garmin","avg_stress","Stress")]:
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


# ── Feature #25: Meditation & Breathwork Correlation ───────────────────────────

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
    for src in ["whoop", "eightsleep", "garmin"]:
        try:
            health_data[src] = {item.get("date"): item for item in query_source(src, start_date, end_date)}
        except Exception:
            health_data[src] = {}

    non_practice_dates = [d for d in all_dates if d not in daily_minutes]
    COMPARE_METRICS = [
        ("whoop","recovery_score","Recovery","higher_is_better"),("whoop","hrv","HRV","higher_is_better"),
        ("whoop","resting_heart_rate","Resting HR","lower_is_better"),("eightsleep","sleep_score","Sleep Score","higher_is_better"),
        ("eightsleep","sleep_efficiency","Sleep Efficiency","higher_is_better"),("garmin","avg_stress","Stress","lower_is_better"),
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

'''

# ══════════════════════════════════════════════════════════════════════════════
# TOOL DICT ENTRIES — inserted inside TOOLS = { ... }
# ══════════════════════════════════════════════════════════════════════════════

TOOL_ENTRIES = '''    "get_social_connection_trend": {
        "fn": tool_get_social_connection_trend,
        "schema": {
            "name": "get_social_connection_trend",
            "description": (
                "Social connection quality trend from journal entries. Tracks enriched_social_quality "
                "(alone/surface/meaningful/deep) over time with rolling averages, streaks, and PERMA "
                "wellbeing model context. Correlates social quality with recovery, HRV, sleep, stress. "
                "Seligman: Relationships are the #1 predictor of sustained wellbeing. "
                "Use for: 'social connection trend', 'meaningful connections', 'PERMA score'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_social_isolation_risk": {
        "fn": tool_get_social_isolation_risk,
        "schema": {
            "name": "get_social_isolation_risk",
            "description": (
                "Social isolation risk detector. Flags periods of 3+ consecutive days without meaningful "
                "social connection. Correlates isolation episodes with health metric declines. "
                "Use for: 'am I socially isolated?', 'isolation risk', 'loneliness health impact'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "consecutive_days": {"type": "integer", "description": "Consecutive days threshold (default: 3)."},
                },
                "required": [],
            },
        },
    },
    "get_meditation_correlation": {
        "fn": tool_get_meditation_correlation,
        "schema": {
            "name": "get_meditation_correlation",
            "description": (
                "Meditation and breathwork analysis. Tracks mindful_minutes from Apple Health, "
                "correlates with HRV, stress, sleep, recovery, Body Battery. Shows meditation vs "
                "non-meditation day comparisons, dose-response, next-day effects, streaks. "
                "Huberman: NSDR is highest-ROI. Attia: consistency > duration. "
                "Use for: 'meditation impact', 'does meditation help HRV?', 'breathwork effects'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
'''


def main():
    with open(MCP_PATH, "r") as f:
        content = f.read()

    # Check if already patched
    if "tool_get_social_connection_trend" in content:
        print("Already patched — tool functions present. Skipping.")
        return

    # Find TOOLS = { line
    tools_marker = "\nTOOLS = {"
    tools_idx = content.find(tools_marker)
    if tools_idx < 0:
        print("ERROR: Could not find 'TOOLS = {' in mcp_server.py")
        sys.exit(1)

    # Insert tool functions BEFORE TOOLS = {
    content = content[:tools_idx] + TOOL_FUNCTIONS + content[tools_idx:]

    # Now find the end of the TOOLS dict to insert entries
    # After our insertion, find TOOLS = { again
    tools_idx2 = content.find(tools_marker)
    # Find the closing } of get_training_recommendation entry, then the next standalone }
    last_tool = content.rfind('"get_training_recommendation"')
    if last_tool < 0:
        print("ERROR: Could not find last tool entry 'get_training_recommendation'")
        sys.exit(1)

    # Navigate to the closing } of TOOLS dict
    # Find matching braces: the TOOLS dict starts at tools_marker
    tools_dict_start = content.find("{", content.find("TOOLS = {"))
    depth = 0
    i = tools_dict_start
    while i < len(content):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                # This is the closing brace of TOOLS dict
                # Insert our entries just before it
                content = content[:i] + TOOL_ENTRIES + content[i:]
                break
        i += 1
    else:
        print("ERROR: Could not find closing brace of TOOLS dict")
        sys.exit(1)

    with open(MCP_PATH, "w") as f:
        f.write(content)

    print(f"✅ Patched {MCP_PATH}")
    print("   Added 3 tool functions before TOOLS dict")
    print("   Added 3 tool entries to TOOLS dict")


if __name__ == "__main__":
    main()
