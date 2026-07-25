"""lambdas/web/site_api_mind.py — mind/journal endpoints (journal_analysis, mind_overview).

Split out of site_api_observatory.py (#1654 slice 3 — god-module breakup). The
routed handler entrypoints stay in the site_api_observatory facade as thin
delegators; this module holds the logic. Handlers receive the facade's globals()
as `_g` and read the monkeypatched/injectable state (table / _query_source /
_experiment_date / EXPERIMENT_START) via `_g["<name>"]`. This module does NOT
import the facade — no import cycle. All other shared helpers come straight from
site_api_common (identical binding semantics to the pre-split facade).
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    USER_PREFIX,
    _decimal_to_float,
    _is_blocked_vice,
    _ok,
)


def journal_analysis(*, _g) -> dict:
    """
    GET /api/journal_analysis
    Returns 90-day journal theme analysis from cache partition.
    Cache: 3600s.
    """
    table = _g["table"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)

    ja_pk = f"{USER_PREFIX}journal_analysis"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot journal analysis
                "KeyConditionExpression": Key("pk").eq(ja_pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    # Build theme frequency counts
    theme_counts = {}
    for item in items:
        for theme in item.get("themes", []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    total = len(items)
    top_themes = sorted(
        [{"theme": k, "count": v, "pct": round(v / max(total, 1) * 100)} for k, v in theme_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    # Sentiment trend — rolling 7-day average
    sentiment_trend = []
    daily_scores = [(item.get("date", ""), float(item.get("sentiment_score", 0))) for item in items]
    for i, (date, _) in enumerate(daily_scores):
        window = [s for _, s in daily_scores[max(0, i - 6) : i + 1]]
        sentiment_trend.append(
            {
                "date": date,
                "avg_sentiment": round(sum(window) / len(window), 3) if window else 0,
            }
        )

    daily_themes = []
    for item in items:
        # J-8 (#504): one_line_summary is a per-day journal digest — never
        # public. Aggregates (themes, sentiment) are the public surface.
        daily_themes.append(
            {
                "date": item.get("date", item.get("sk", "").replace("DATE#", "")),
                "dominant_theme": item.get("dominant_theme", "other"),
                "themes": item.get("themes", []),
                "sentiment_score": float(item.get("sentiment_score", 0)),
                "sentiment_label": item.get("sentiment_label", "neutral"),
                "word_count": item.get("word_count", 0),
            }
        )

    return _ok(
        {
            "daily_themes": daily_themes,
            "top_themes": top_themes,
            "total_analyzed": total,
            "date_range": {"start": d90, "end": today},
            "sentiment_trend": sentiment_trend,
        },
        cache_seconds=3600,
    )


def mind_overview(*, _g) -> dict:
    """
    GET /api/mind_overview
    Returns: mood/energy/stress trends, vice streaks, social connection quality,
    mind pillar score, cognitive patterns (when journal data is available).
    Cache: 3600s.
    """
    table = _g["table"]
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    d90 = _experiment_date(90)

    # ── 1. Mind pillar from character_sheet ──
    mind_pillar = None
    cs_pk = f"{USER_PREFIX}character_sheet"
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            mp = record.get("pillar_mind", {})
            mind_pillar = {
                "level": float(mp.get("level", 1)),
                "raw_score": float(mp.get("raw_score", 0)),
                "tier": mp.get("tier", "Foundation"),
            }
            break

    # ── 2. State of mind / mood data (Apple Health How We Feel) ──
    som_items = _query_source("state_of_mind", d30, today)
    mood_entries = []
    for s in som_items:
        valence = s.get("valence")
        if valence is not None:
            mood_entries.append(
                {
                    "date": s.get("date") or s.get("sk", "").replace("DATE#", ""),
                    "valence": float(valence),
                    "label": s.get("label", ""),
                }
            )
    # Fallback: check apple_health partition for som_avg_valence (HAE writes here)
    if not mood_entries:
        ah_som = _query_source("apple_health", d30, today)
        for s in ah_som:
            valence = s.get("som_avg_valence")
            if valence is not None:
                mood_entries.append(
                    {
                        "date": s.get("date") or s.get("sk", "").replace("DATE#", ""),
                        "valence": float(valence),
                        "label": "",
                    }
                )
    mood_entries.sort(key=lambda x: x["date"])
    avg_valence = None
    if mood_entries:
        vals = [m["valence"] for m in mood_entries]
        avg_valence = round(sum(vals) / len(vals), 2)

    # ── 3. Vice streaks from habit_scores ──
    # Stage0 Fix 1 (2026-05-30): use _is_blocked_vice (matches both
    # blocked_vices full names AND blocked_vice_keywords substrings) so the
    # client doesn't have to ship a keyword list to filter what we missed.
    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(hs_pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    vice_data = []
    if hs_items:
        latest_hs = hs_items[0]
        raw_vs = latest_hs.get("vice_streaks") or {}
        if isinstance(raw_vs, dict):
            for name, streak_val in raw_vs.items():
                if _is_blocked_vice(name):
                    continue
                vice_data.append(
                    {
                        "name": name,
                        "current_streak": int(streak_val or 0),
                        "holding": int(streak_val or 0) > 0,
                    }
                )
        vice_data.sort(key=lambda v: -v["current_streak"])

    # ── 4. Social connection quality (interactions) ──
    int_pk = f"{USER_PREFIX}interactions"
    try:
        int_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot interactions
                    "KeyConditionExpression": Key("pk").eq(int_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}~"),
                    "ScanIndexForward": True,
                }
            )
        )
        interactions = _decimal_to_float(int_resp.get("Items", []))
    except Exception:
        interactions = []

    total_interactions = len(interactions)
    depth_counts = {"surface": 0, "meaningful": 0, "deep": 0}
    for i in interactions:
        d = (i.get("depth") or "surface").lower()
        if d in depth_counts:
            depth_counts[d] += 1
    meaningful_pct = round((depth_counts["meaningful"] + depth_counts["deep"]) / total_interactions * 100) if total_interactions else 0

    # ── 5. Temptation resist rate (90d) ──
    temp_pk = f"{USER_PREFIX}temptations"
    try:
        temp_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot temptations
                    "KeyConditionExpression": Key("pk").eq(temp_pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}~"),
                }
            )
        )
        temptations = _decimal_to_float(temp_resp.get("Items", []))
    except Exception:
        temptations = []

    total_temptations = len(temptations)
    resisted = sum(1 for t in temptations if t.get("resisted"))
    resist_rate = round(resisted / total_temptations * 100) if total_temptations else None

    # ── 6. Journal entry count (as journaling progress signal) ──
    journal_pk = f"{USER_PREFIX}notion"
    try:
        j_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot journal records
                    "KeyConditionExpression": Key("pk").eq(journal_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
                    "Select": "COUNT",
                }
            )
        )
        journal_count = j_resp.get("Count", 0)
    except Exception:
        journal_count = 0

    # ── 7. Meditation / breathwork (Apple Health) ──
    ah_mind = _query_source("apple_health", d30, today)
    meditation_sessions = []
    med_total_min = 0
    med_session_count = 0
    for h in ah_mind:
        _md = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        _bw_sess = int(float(h.get("breathwork_sessions") or 0))
        # Also check mindful_minutes (Breathwrk app writes here via HAE)
        _mm_min = float(h.get("mindful_minutes") or 0)
        if _mm_min > 0 and _bw_min == 0:
            _bw_min = _mm_min
            _bw_sess = max(_bw_sess, 1)  # At least 1 session if we have minutes
        if _bw_min > 0 or _bw_sess > 0:
            meditation_sessions.append(
                {
                    "date": _md,
                    "minutes": round(_bw_min, 1),
                    "sessions": _bw_sess,
                }
            )
            med_total_min += _bw_min
            med_session_count += _bw_sess
    meditation_sessions.sort(key=lambda x: x["date"])
    meditation_data = {
        "sessions_30d": med_session_count,
        "total_minutes_30d": round(med_total_min, 1),
        "avg_session_min": round(med_total_min / med_session_count, 1) if med_session_count else None,
        "daily": meditation_sessions,
    }

    # ── 8. Vice streak timeline (30-day daily history) ──
    hs_30d_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(hs_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    hs_30d_items = _decimal_to_float(hs_30d_resp.get("Items", []))
    vice_timeline = []
    for hs_day in hs_30d_items:
        day_date = hs_day.get("date") or hs_day.get("sk", "").replace("DATE#", "")
        raw_vs = hs_day.get("vice_streaks") or {}
        day_entry = {"date": day_date, "held": int(hs_day.get("vices_held", 0)), "total": int(hs_day.get("vices_total", 0))}
        # Include per-vice streaks (filtered)
        if isinstance(raw_vs, dict):
            streaks = {}
            for name, val in raw_vs.items():
                if _is_blocked_vice(name):
                    continue
                streaks[name] = int(val or 0)
            day_entry["streaks"] = streaks
        vice_timeline.append(day_entry)

    # ── 9. Energy level from journal analysis (latest entry) ──
    energy_level = None
    try:
        ja_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot journal analysis
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}journal_analysis")
                    & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
                    "ScanIndexForward": False,
                    "Limit": 5,
                }
            )
        )
        ja_items = _decimal_to_float(ja_resp.get("Items", []))
        energy_vals = [i.get("energy_level") for i in ja_items if i.get("energy_level")]
        if energy_vals:
            energy_level = energy_vals[0]  # Most recent
    except Exception:
        pass

    return _ok(
        {
            "mind": {
                "mind_pillar": mind_pillar,
                "avg_valence": avg_valence,
                "mood_entries_count": len(mood_entries),
                "journal_entries_30d": journal_count,
                "resist_rate_pct": resist_rate,
                "total_temptations_90d": total_temptations,
                "resisted_90d": resisted,
                "total_interactions_30d": total_interactions,
                "meaningful_pct": meaningful_pct,
                "depth_counts": depth_counts,
                "energy_level": energy_level,
            },
            "vice_streaks": vice_data,
            "vice_timeline": vice_timeline,
            "mood_trend": mood_entries[-30:],
            "meditation": meditation_data,
        },
        cache_seconds=3600,
    )
