"""mcp/tools_social_connection.py — the PERMA / connection-quality trend tool.

Lifted out of ``mcp/tools_lifestyle.py`` by #2221 so the honest-numbers repairs in
this tool (date-bounded rolling windows, ADR-105 correlations) could land without
raising that module's size-guard baseline — the shape #1654 established.

The registered entry point is ``get_social_connection_trend``; ``mcp/registry.py``
imports ``tool_get_social_connection_trend`` from here.
"""

from datetime import datetime, timedelta

from common.pacific_time import pacific_now, pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

from mcp.core import query_source
from mcp.helpers import correlation_report, normalize_whoop_sleep

# ── Citation gate (#758) ──
# Seligman/Holt-Lunstad-style research citations read as rigor-flavored garnish when the
# underlying personal sample is a handful of days (ADR-105: uncertainty + n on every claim).
# Gate the citation on real data volume; below threshold, omit it — the honest numbers
# (counts, streaks, correlations) still return either way. 14 = two full rolling weeks of
# enriched_social_quality logs, matching this tool's own rolling_7d/rolling_30d windows —
# enough to say "this is a pattern," not one journal entry dressed up as a finding.
_SOCIAL_CITATION_MIN_N = 14

# ADR-105: below ten paired days the correlation is omitted entirely rather than
# published at n=2. correlation_report enforces the same floor for every spec.
_CORRELATION_MIN_N = 10

QUALITY_MAP = {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4}

# (source, DynamoDB field, display label, higher_is_better) — the direction feeds
# correlation_report's impact verdict, which is confidence-gated (ADR-105).
HEALTH_SOURCES = [
    ("whoop", "recovery_score", "Recovery", True),
    ("whoop", "hrv", "HRV", True),
    ("whoop", "sleep_score", "Sleep Score", True),
    ("garmin", "avg_stress", "Stress", False),
    ("garmin", "body_battery_high", "Body Battery", True),
]


def _sf(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 2) if v else None


def _rolling_by_date(daily_social, sorted_dates, span_days):
    """#2221/#1917 WINDOW HONESTY: a field named for an N-day window spans N real
    CALENDAR DAYS, not the last N logged entries.

    Journaling is voluntary and gappy, so ``scores[i-6:i+1]`` described months on a
    sparse stretch while calling itself a week, and rolling_7d/rolling_30d silently
    collapsed to the same number. Each point now carries ``days_logged`` — how many
    of the ``span_days`` dates actually have an entry — so the reader can see the
    density the mean was computed over (ADR-105: n on every statistical claim).
    """
    out = []
    parsed = [(d, datetime.strptime(d, "%Y-%m-%d")) for d in sorted_dates]
    for d, dt in parsed:
        floor = dt - timedelta(days=span_days - 1)
        vals = [daily_social[od]["score"] for od, odt in parsed if floor <= odt <= dt]
        out.append(
            {
                "date": d,
                "avg": round(sum(vals) / len(vals), 2),
                "days_logged": len(vals),
                "window_days": span_days,
                "window_start": floor.strftime("%Y-%m-%d"),
            }
        )
    return out


def _connection_correlations(daily_social, sorted_dates, health_data, journal_series):
    """One batched, ADR-105-compliant correlation pass (#2221).

    The module used to hand-roll a population Pearson r inline TWICE, gate it at a
    bare n>=10, and attach a 'strong'/'moderate'/'weak' verdict with no p-value, no
    CI, no autocorrelation-corrected effective n and no multiplicity control across
    the eight correlations it runs in a single call. mcp/helpers.py::correlation_report
    supplies all four and applies Benjamini-Hochberg across the WHOLE batch — so
    health and journal correlations are computed in one call, not two, or the FDR
    would be applied to two half-families and understate the multiplicity.
    """
    specs = []
    for src, field, label, hib in HEALTH_SOURCES:
        xs, ys = [], []
        for d in sorted_dates:
            hv = _sf(health_data.get(src, {}).get(d, {}).get(field))
            if hv is not None:
                xs.append(daily_social[d]["score"])
                ys.append(hv)
        specs.append(
            {"key": f"health:{label}", "xs": xs, "ys": ys, "label": label, "direction": "higher_is_better" if hib else "lower_is_better"}
        )
    for field_data, label, hib in journal_series:
        xs, ys = [], []
        for d in sorted_dates:
            if d in field_data:
                xs.append(daily_social[d]["score"])
                ys.append(field_data[d])
        specs.append(
            {"key": f"journal:{label}", "xs": xs, "ys": ys, "label": label, "direction": "higher_is_better" if hib else "lower_is_better"}
        )

    report = correlation_report(specs, min_n=_CORRELATION_MIN_N)
    health, journal = [], []
    for key, rec in report.items():
        row = {
            "metric": rec["label"],
            "r": round(rec["pearson_r"], 3),
            "n": rec["n"],
            "n_eff": rec["n_eff"],
            "ci_low": rec["ci_low"],
            "ci_high": rec["ci_high"],
            "p_value": rec["p_value"],
            "q_value": rec["q_value"],
            "confidence": rec["confidence"],
            "impact": rec["impact"],
        }
        (health if key.startswith("health:") else journal).append(row)
    return health, journal


def tool_get_social_connection_trend(args):
    """
    Aggregates enriched_social_quality from journal entries over time.
    Tracks social connection quality, streaks, rolling averages, and
    correlates with health outcomes. The `perma_context` field (a Seligman
    PERMA / Holt-Lunstad citation) is gated on n — see `_SOCIAL_CITATION_MIN_N` (#758).
    """
    end_date = args.get("end_date", pacific_today())
    start_date = args.get("start_date", (pacific_now() - timedelta(days=90)).strftime("%Y-%m-%d"))

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

    rolling_7d = _rolling_by_date(daily_social, sorted_dates, 7)
    rolling_30d = _rolling_by_date(daily_social, sorted_dates, 30)

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
    today = pacific_today()
    for d in reversed(sorted_dates):
        if daily_social[d]["score"] >= 3:
            days_since_meaningful = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days
            break

    health_data = {}
    for src, _f, _l, _h in HEALTH_SOURCES:
        if src not in health_data:
            try:
                # #2221: whoop's sleep_score/deep_pct are aliases the writer never stores, so
                # without normalising on the way in the "Sleep Score" row was permanently absent.
                rows = query_source(src, start_date, end_date)
                health_data[src] = {i.get("date"): (normalize_whoop_sleep(i) if src == "whoop" else i) for i in rows}
            except Exception:
                health_data[src] = {}

    health_correlations, journal_correlations = _connection_correlations(
        daily_social,
        sorted_dates,
        health_data,
        [(daily_mood, "Mood", True), (daily_energy, "Energy", True), (daily_stress, "Stress", False)],
    )

    meaningful_days = [d for d in sorted_dates if daily_social[d]["score"] >= 3]
    low_days = [d for d in sorted_dates if daily_social[d]["score"] <= 2]
    comparison = {}
    for src, field, label, _hib in HEALTH_SOURCES:
        m_vals = [_sf(health_data.get(src, {}).get(d, {}).get(field)) for d in meaningful_days]
        l_vals = [_sf(health_data.get(src, {}).get(d, {}).get(field)) for d in low_days]
        m_avg, l_avg = _avg(m_vals), _avg(l_vals)
        if m_avg is not None and l_avg is not None:
            comparison[label] = {"meaningful_avg": m_avg, "low_social_avg": l_avg, "diff": round(m_avg - l_avg, 2)}

    result = {
        "start_date": start_date,
        "end_date": end_date,
        "total_days_with_data": len(daily_social),
        "distribution": distribution,
        "overall_avg_score": _avg(scores),
        "score_legend": dict(QUALITY_MAP),
        "rolling_7d_latest": rolling_7d[-1] if rolling_7d else None,
        "rolling_30d_latest": rolling_30d[-1] if rolling_30d else None,
        "streaks": {
            "current_meaningful_streak": current_streak,
            "longest_meaningful_streak": longest_streak,
            "days_since_meaningful": days_since_meaningful,
        },
        "health_correlations": health_correlations,
        "journal_correlations": journal_correlations,
        "meaningful_vs_low_comparison": comparison,
    }

    # #758: cite external wellbeing research only once there's enough real data to
    # ground it in — below the floor it's garnish, not a finding about this person.
    if len(daily_social) >= _SOCIAL_CITATION_MIN_N:
        result["perma_context"] = (
            "Seligman PERMA: Relationships are #1 wellbeing predictor. Holt-Lunstad: isolation "
            "increases mortality 26%. Target: meaningful+ connection 5+ days/week."
        )

    return result
