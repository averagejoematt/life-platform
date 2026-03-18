"""
Habit tracking & device tools.
"""
import json
import math
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from decimal import Decimal

from mcp.config import (
    table, s3_client, S3_BUCKET, USER_PREFIX, USER_ID, SOURCES,
    P40_GROUPS, FIELD_ALIASES, logger,
    INSIGHTS_PK, EXPERIMENTS_PK, TRAVEL_PK,
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

def tool_get_habit_adherence(args):
    """
    Per-habit and per-group completion rates over any date range.
    Returns habits ranked worst-to-best by adherence.
    """
    start_date = args.get("start_date", "2020-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    group_filter = (args.get("group") or "").strip()

    items = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if not series:
        return {"error": "No chronicling data found for the requested window."}

    n_days = len(series)
    habit_counts: dict[str, int]   = {}  # name -> days completed
    habit_days:   dict[str, int]   = {}  # name -> days tracked (possible)
    group_completed: dict[str, list] = {}
    group_possible:  dict[str, list] = {}

    for row in series:
        for habit, val in row["habits"].items():
            habit_counts[habit] = habit_counts.get(habit, 0) + int(val)
            habit_days[habit]   = habit_days.get(habit, 0) + 1
        for grp, gdata in row["by_group"].items():
            if group_filter and grp.lower() != group_filter.lower():
                continue
            group_completed.setdefault(grp, []).append(gdata.get("completed", 0))
            group_possible.setdefault(grp, []).append(gdata.get("possible", 0))

    # Per-habit table
    habit_rows = []
    for habit in sorted(habit_counts):
        days_tracked = habit_days[habit]
        days_done    = habit_counts[habit]
        pct = round(days_done / days_tracked, 4) if days_tracked else 0
        habit_rows.append({
            "habit":        habit,
            "days_done":    days_done,
            "days_tracked": days_tracked,
            "completion_pct": pct,
        })
    habit_rows.sort(key=lambda r: r["completion_pct"])

    # Per-group table
    group_rows = []
    for grp in P40_GROUPS:
        if grp not in group_completed:
            continue
        total_comp = sum(group_completed[grp])
        total_poss = sum(group_possible[grp])
        pct = round(total_comp / total_poss, 4) if total_poss else 0
        group_rows.append({
            "group":          grp,
            "total_completed": total_comp,
            "total_possible":  total_poss,
            "completion_pct":  pct,
        })
    group_rows.sort(key=lambda r: r["completion_pct"])

    # Overall
    all_comp = sum(row["total_completed"] for row in series)
    all_poss = sum(row["total_possible"]  for row in series)

    return {
        "start_date":     start_date,
        "end_date":       end_date,
        "days_analyzed":  n_days,
        "overall_completion_pct": round(all_comp / all_poss, 4) if all_poss else 0,
        "overall_completed": all_comp,
        "overall_possible":  all_poss,
        "by_group":       group_rows,
        "by_habit":       habit_rows,
        "note":           "Habits ranked worst-to-best. Pass group= to filter by P40 pillar.",
    }


def tool_get_habit_streaks(args):
    """
    Current streak, longest streak, and days since last completion for each habit.
    Returns sorted by current_streak descending.
    """
    start_date   = args.get("start_date", "2020-01-01")
    end_date     = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    habit_filter = (args.get("habit_name") or "").strip().lower()

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if not series:
        return {"error": "No chronicling data found."}

    # Collect all habit names
    all_habits = set()
    for row in series:
        all_habits |= set(row["habits"].keys())
    if habit_filter:
        all_habits = {h for h in all_habits if habit_filter in h.lower()}

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    def streak_stats(habit):
        done_dates = sorted(
            row["date"] for row in series if row["habits"].get(habit)
        )
        if not done_dates:
            return {"habit": habit, "current_streak": 0, "longest_streak": 0,
                    "days_since_last": None, "last_done_date": None, "total_completions": 0}

        # longest streak (consecutive days)
        longest = cur = 1
        for i in range(1, len(done_dates)):
            d1 = datetime.strptime(done_dates[i-1], "%Y-%m-%d")
            d2 = datetime.strptime(done_dates[i],   "%Y-%m-%d")
            if (d2 - d1).days == 1:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 1

        # current streak (working backwards from most recent done date)
        cur_streak = 1
        for i in range(len(done_dates)-1, 0, -1):
            d1 = datetime.strptime(done_dates[i-1], "%Y-%m-%d")
            d2 = datetime.strptime(done_dates[i],   "%Y-%m-%d")
            if (d2 - d1).days == 1:
                cur_streak += 1
            else:
                break
        # If last done wasn't yesterday or today, streak is 0
        last_dt = datetime.strptime(done_dates[-1], "%Y-%m-%d")
        gap_to_now = (end_dt - last_dt).days
        if gap_to_now > 1:
            cur_streak = 0

        return {
            "habit":             habit,
            "current_streak":    cur_streak,
            "longest_streak":    longest,
            "days_since_last":   gap_to_now,
            "last_done_date":    done_dates[-1],
            "total_completions": len(done_dates),
        }

    results = [streak_stats(h) for h in sorted(all_habits)]
    results.sort(key=lambda r: (-r["current_streak"], -r["longest_streak"]))

    active = [r for r in results if r["current_streak"] > 0]
    broken = [r for r in results if r["current_streak"] == 0]
    broken.sort(key=lambda r: (r["days_since_last"] or 9999))

    return {
        "start_date":      start_date,
        "end_date":        end_date,
        "active_streaks":  active,
        "broken_streaks":  broken,
        "note":            "current_streak=0 means not completed today or yesterday. days_since_last is days ago.",
    }


def tool_get_keystone_habits(args):
    """
    Identifies which individual habits have the highest Pearson correlation
    with overall daily completion_pct — the behavioral levers that lift everything.
    """
    start_date = args.get("start_date", "2020-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    top_n      = int(args.get("top_n", 15))

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if len(series) < 10:
        return {"error": f"Need at least 10 days of data (found {len(series)})."}

    overall_scores = [row["completion_pct"] for row in series]

    all_habits = set()
    for row in series:
        all_habits |= set(row["habits"].keys())

    correlations = []
    for habit in sorted(all_habits):
        habit_vals = [float(row["habits"].get(habit, 0)) for row in series]
        # Skip habits rarely tracked (less than 20% presence)
        done_count = sum(habit_vals)
        if done_count < max(3, len(series) * 0.05):
            continue
        r = pearson_r(habit_vals, overall_scores)
        if r is None:
            continue
        completion_rate = round(done_count / len(series), 3)
        correlations.append({
            "habit":           habit,
            "pearson_r":       r,
            "r_squared":       round(r**2, 3),
            "completion_rate": completion_rate,
            "interpretation":  (
                "strong lever" if r >= 0.5 else
                "moderate lever" if r >= 0.3 else
                "weak lever" if r >= 0.15 else
                "negligible"
            ),
            "n_days_done": int(done_count),
        })

    correlations.sort(key=lambda x: -x["pearson_r"])

    return {
        "start_date":   start_date,
        "end_date":     end_date,
        "days_analyzed": len(series),
        "top_n":        top_n,
        "keystone_habits": correlations[:top_n],
        "bottom_habits":   [h for h in reversed(correlations) if h["pearson_r"] < 0][:5],
        "coaching_note": (
            "Keystone habits are the behavioral levers: completing them on a given day predicts "
            "a higher overall P40 score. Focus willpower here first for cascade effects. "
            "r > 0.4 is practically meaningful."
        ),
    }


def tool_get_habit_health_correlations(args):
    """
    Correlate individual habit completion (0/1) or group score with a biometric outcome.
    Returns Pearson r, and mean biometric on days habit was done vs not done.
    Supports optional lag (e.g. does cold shower today predict HRV tomorrow?).
    """
    habit_name    = (args.get("habit_name") or "").strip()
    group_name    = (args.get("group_name") or "").strip()
    health_source = args.get("health_source")        # e.g. "whoop"
    health_field  = args.get("health_field")         # e.g. "hrv"
    start_date    = args.get("start_date", "2020-01-01")
    end_date      = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    lag_days      = int(args.get("lag_days", 0))

    if not (habit_name or group_name):
        return {"error": "Provide habit_name or group_name."}
    if not health_source or not health_field:
        return {"error": "health_source and health_field are required (e.g. health_source='whoop', health_field='hrv')."}

    # Build date range that covers lag
    lag_end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=abs(lag_days))
    lag_end    = lag_end_dt.strftime("%Y-%m-%d")

    habit_items  = query_chronicling(start_date, lag_end)
    health_items = query_source(health_source, start_date, lag_end)

    habit_series  = _habit_series(habit_items)
    health_by_date = {}
    resolved = resolve_field(health_source, health_field)
    for item in health_items:
        d = item.get("date")
        v = item.get(resolved)
        if d and v is not None:
            health_by_date[d] = float(v)

    pairs_done     = []
    pairs_not_done = []
    xs = []   # habit value (0/1 or group pct)
    ys = []   # health value (shifted by lag)

    for row in habit_series:
        date_str = row["date"]
        if date_str > end_date:
            continue
        if lag_days > 0:
            shifted = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
        else:
            shifted = date_str
        health_val = health_by_date.get(shifted)
        if health_val is None:
            continue

        if habit_name:
            habit_val = float(row["habits"].get(habit_name, 0))
        else:  # group
            grp_data = row["by_group"].get(group_name)
            habit_val = grp_data["pct"] if grp_data else 0.0

        xs.append(habit_val)
        ys.append(health_val)
        if habit_val >= 0.5:
            pairs_done.append(health_val)
        else:
            pairs_not_done.append(health_val)

    if len(xs) < 10:
        return {"error": f"Insufficient paired data points ({len(xs)}). Try wider date range."}

    r = pearson_r(xs, ys)
    mean_done     = round(sum(pairs_done)     / len(pairs_done),     2) if pairs_done     else None
    mean_not_done = round(sum(pairs_not_done) / len(pairs_not_done), 2) if pairs_not_done else None
    delta = round(mean_done - mean_not_done, 2) if (mean_done is not None and mean_not_done is not None) else None

    direction = "habit done → higher {f}" if delta and delta > 0 else "habit done → lower {f}"

    return {
        "habit_name":     habit_name or None,
        "group_name":     group_name or None,
        "health_source":  health_source,
        "health_field":   resolved,
        "lag_days":       lag_days,
        "lag_note":       f"Does {habit_name or group_name} today predict {resolved} in {lag_days} day(s)?" if lag_days else "Same-day relationship.",
        "start_date":     start_date,
        "end_date":       end_date,
        "n_paired_days":  len(xs),
        "pearson_r":      r,
        "r_squared":      round(r**2, 3) if r else None,
        "interpretation": (
            "strong correlation" if r and abs(r) >= 0.5 else
            "moderate correlation" if r and abs(r) >= 0.3 else
            "weak correlation" if r and abs(r) >= 0.15 else
            "negligible correlation"
        ) if r is not None else "insufficient variance",
        "mean_health_when_done":     mean_done,
        "mean_health_when_not_done": mean_not_done,
        "delta":          delta,
        "n_days_done":    len(pairs_done),
        "n_days_not_done":len(pairs_not_done),
        "coaching_note":  "r > 0.3 is meaningful. Check both r and the mean difference for practical significance.",
    }


def tool_get_group_trends(args):
    """
    Weekly P40 group scores over time.
    Returns week-by-week completion % per group, with trend direction across the window.
    """
    start_date    = args.get("start_date", "2020-01-01")
    end_date      = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    groups_filter = args.get("groups")  # optional list

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if not series:
        return {"error": "No chronicling data found."}

    # Bucket into ISO weeks
    weeks: dict[str, dict[str, list]] = {}  # week_key -> {group -> [pcts]}
    for row in series:
        date_str = row["date"]
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            iso = dt.isocalendar()
            wk  = f"{iso[0]}-W{iso[1]:02d}"
        except ValueError:
            continue
        weeks.setdefault(wk, {"overall": [], "dates": []})
        weeks[wk]["overall"].append(row["completion_pct"])
        weeks[wk]["dates"].append(date_str)
        for grp, gdata in row["by_group"].items():
            if groups_filter and grp not in groups_filter:
                continue
            weeks[wk].setdefault(grp, []).append(gdata.get("pct", 0))

    week_rows = []
    for wk in sorted(weeks.keys()):
        wdata = weeks[wk]
        row = {
            "week":       wk,
            "week_start": min(wdata["dates"]) if wdata["dates"] else "",
            "week_end":   max(wdata["dates"]) if wdata["dates"] else "",
            "days_data":  len(wdata["overall"]),
            "overall_pct": round(sum(wdata["overall"]) / len(wdata["overall"]), 4) if wdata["overall"] else None,
        }
        for grp in P40_GROUPS:
            if grp in wdata and wdata[grp]:
                row[f"{grp}_pct"] = round(sum(wdata[grp]) / len(wdata[grp]), 4)
        week_rows.append(row)

    # Trend direction per group (first half vs second half avg)
    trends = {}
    n = len(week_rows)
    if n >= 4:
        half = n // 2
        for grp in ["overall"] + P40_GROUPS:
            key = f"{grp}_pct" if grp != "overall" else "overall_pct"
            early_vals = [r[key] for r in week_rows[:half]  if r.get(key) is not None]
            late_vals  = [r[key] for r in week_rows[half:]  if r.get(key) is not None]
            if early_vals and late_vals:
                early_avg = sum(early_vals) / len(early_vals)
                late_avg  = sum(late_vals)  / len(late_vals)
                delta = round(late_avg - early_avg, 4)
                trends[grp] = {
                    "early_avg": round(early_avg, 4),
                    "late_avg":  round(late_avg, 4),
                    "delta":     delta,
                    "direction": "improving" if delta > 0.02 else ("declining" if delta < -0.02 else "stable"),
                }

    return {
        "start_date":   start_date,
        "end_date":     end_date,
        "weeks_analyzed": len(week_rows),
        "weekly_scores": week_rows,
        "trend_summary": trends,
        "note":          "Completion % shown as 0–1. Filter with groups= list to focus on specific pillars.",
    }


def tool_compare_habit_periods(args):
    """
    Side-by-side adherence comparison of two date ranges.
    Returns per-habit and per-group delta and direction.
    """
    pa_start = args.get("period_a_start")
    pa_end   = args.get("period_a_end")
    pb_start = args.get("period_b_start")
    pb_end   = args.get("period_b_end")
    pa_label = args.get("period_a_label", "Period A")
    pb_label = args.get("period_b_label", "Period B")

    if not all([pa_start, pa_end, pb_start, pb_end]):
        return {"error": "period_a_start, period_a_end, period_b_start, period_b_end are all required."}

    def period_stats(start, end):
        items  = query_chronicling(start, end)
        series = _habit_series(items)
        habit_rates: dict[str, float] = {}
        group_rates: dict[str, float] = {}
        n = len(series)
        if n == 0:
            return habit_rates, group_rates, n
        counts: dict[str, int] = {}
        for row in series:
            for habit, val in row["habits"].items():
                counts[habit] = counts.get(habit, 0) + int(val)
        for habit, done in counts.items():
            habit_rates[habit] = round(done / n, 4)
        grp_comp: dict[str, list] = {}
        grp_poss: dict[str, list] = {}
        for row in series:
            for grp, gdata in row["by_group"].items():
                grp_comp.setdefault(grp, []).append(gdata.get("completed", 0))
                grp_poss.setdefault(grp, []).append(gdata.get("possible", 0))
        for grp in P40_GROUPS:
            if grp in grp_comp and sum(grp_poss[grp]):
                group_rates[grp] = round(sum(grp_comp[grp]) / sum(grp_poss[grp]), 4)
        return habit_rates, group_rates, n

    habits_a, groups_a, days_a = period_stats(pa_start, pa_end)
    habits_b, groups_b, days_b = period_stats(pb_start, pb_end)

    all_habits = sorted(set(habits_a) | set(habits_b))
    habit_comparison = []
    for habit in all_habits:
        va = habits_a.get(habit)
        vb = habits_b.get(habit)
        delta = round(vb - va, 4) if (va is not None and vb is not None) else None
        habit_comparison.append({
            "habit":          habit,
            pa_label:         va,
            pb_label:         vb,
            "delta":          delta,
            "direction":      "improved" if delta and delta > 0.02 else ("declined" if delta and delta < -0.02 else "stable"),
        })
    habit_comparison.sort(key=lambda r: r.get("delta") or 0, reverse=True)

    group_comparison = []
    for grp in P40_GROUPS:
        va = groups_a.get(grp)
        vb = groups_b.get(grp)
        delta = round(vb - va, 4) if (va is not None and vb is not None) else None
        group_comparison.append({
            "group":     grp,
            pa_label:    va,
            pb_label:    vb,
            "delta":     delta,
            "direction": "improved" if delta and delta > 0.02 else ("declined" if delta and delta < -0.02 else "stable"),
        })
    group_comparison.sort(key=lambda r: r.get("delta") or 0, reverse=True)

    overall_a = sum(habits_a.values()) / len(habits_a) if habits_a else None
    overall_b = sum(habits_b.values()) / len(habits_b) if habits_b else None

    return {
        "period_a": {"label": pa_label, "start": pa_start, "end": pa_end, "days": days_a},
        "period_b": {"label": pb_label, "start": pb_start, "end": pb_end, "days": days_b},
        "overall": {
            pa_label: round(overall_a, 4) if overall_a else None,
            pb_label: round(overall_b, 4) if overall_b else None,
            "delta":  round(overall_b - overall_a, 4) if (overall_a and overall_b) else None,
        },
        "by_group": group_comparison,
        "by_habit": habit_comparison,
        "most_improved":  [h for h in habit_comparison if h.get("direction") == "improved"][:5],
        "most_declined":  [h for h in reversed(habit_comparison) if h.get("direction") == "declined"][:5],
    }


def tool_get_habit_stacks(args):
    """
    Co-occurrence analysis: which habits cluster together.
    Uses lift = P(A and B) / (P(A) * P(B)) to surface genuine co-occurrence
    beyond base rates. Returns top N habit pairs by lift.
    Also returns natural 'stacks' — groups of 3+ habits that co-occur on ≥60% of days.
    """
    start_date = args.get("start_date", "2020-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    top_n      = int(args.get("top_n", 20))
    min_pct    = float(args.get("min_pct", 0.1))  # minimum base rate for either habit

    items  = query_chronicling(start_date, end_date)
    series = _habit_series(items)
    if len(series) < 7:
        return {"error": "Need at least 7 days of data."}

    n = len(series)
    # Build presence rates
    habits = sorted({h for row in series for h in row["habits"]})
    p = {h: sum(row["habits"].get(h, 0) for row in series) / n for h in habits}
    # Filter out habits with very low base rates
    habits = [h for h in habits if p[h] >= min_pct]

    pair_counts: dict[tuple, int] = {}
    for row in series:
        done = [h for h in habits if row["habits"].get(h, 0)]
        for i in range(len(done)):
            for j in range(i+1, len(done)):
                key = (done[i], done[j])
                pair_counts[key] = pair_counts.get(key, 0) + 1

    pairs = []
    for (ha, hb), cnt in pair_counts.items():
        p_ab  = cnt / n
        lift  = p_ab / (p[ha] * p[hb]) if (p[ha] * p[hb]) > 0 else 0
        pairs.append({
            "habit_a":        ha,
            "habit_b":        hb,
            "co_occurrence_pct": round(p_ab, 4),
            "habit_a_base_rate": round(p[ha], 4),
            "habit_b_base_rate": round(p[hb], 4),
            "lift":           round(lift, 3),
            "n_days_together": cnt,
            "interpretation":  (
                "strongly cluster" if lift >= 2.0 else
                "tend to co-occur" if lift >= 1.5 else
                "slightly co-occur" if lift >= 1.2 else
                "independent"
            ),
        })
    pairs.sort(key=lambda r: -r["lift"])

    # Stack detection: find habits that all co-occur on >= threshold fraction of days
    threshold = 0.60
    stack_habits = [h for h in habits if p[h] >= 0.3]  # only habits done ≥30% of time
    stacks = []
    # Greedy: check all triples
    for i in range(len(stack_habits)):
        for j in range(i+1, len(stack_habits)):
            for k in range(j+1, len(stack_habits)):
                ha, hb, hc = stack_habits[i], stack_habits[j], stack_habits[k]
                co = sum(
                    1 for row in series
                    if row["habits"].get(ha) and row["habits"].get(hb) and row["habits"].get(hc)
                ) / n
                if co >= threshold:
                    stacks.append({
                        "stack": [ha, hb, hc],
                        "co_occurrence_pct": round(co, 4),
                        "type":  "routine stack",
                    })
    stacks.sort(key=lambda r: -r["co_occurrence_pct"])

    return {
        "start_date":    start_date,
        "end_date":      end_date,
        "days_analyzed": n,
        "top_pairs_by_lift": pairs[:top_n],
        "natural_stacks":    stacks[:20],
        "coaching_note": (
            "Lift > 1.5 means the habits genuinely cluster beyond chance. "
            "Natural stacks are habits you already do together 60%+ of the time — "
            "these are your existing routines."
        ),
    }


def tool_get_habit_dashboard(args):
    """
    Current-state P40 briefing. Returns:
    - Today's and yesterday's completion status (latest available)
    - 7-day rolling group scores vs 30-day baseline
    - Current streaks for top habits
    - Best and worst groups this week
    - Trend vs previous 7-day window
    """
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start   = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d14_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    d30_start  = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")

    items_30d = query_chronicling(d30_start, end_date)
    series_30 = _habit_series(items_30d)

    if not series_30:
        return {"error": "No chronicling data found."}

    # Latest day
    latest = series_30[-1]
    today_status = {
        "date":             latest["date"],
        "total_completed":  latest["total_completed"],
        "total_possible":   latest["total_possible"],
        "completion_pct":   latest["completion_pct"],
        "status":           "green" if latest["completion_pct"] >= 0.70 else ("yellow" if latest["completion_pct"] >= 0.50 else "red"),
        "by_group":         {grp: round(gdata.get("pct", 0), 4) for grp, gdata in latest["by_group"].items()},
    }

    # 7-day stats
    series_7 = [r for r in series_30 if r["date"] >= d7_start]
    series_prev_7 = [r for r in series_30 if d14_start <= r["date"] < d7_start]

    def group_avgs(s):
        grp_comp: dict[str, list] = {}
        grp_poss: dict[str, list] = {}
        for row in s:
            for grp, gdata in row["by_group"].items():
                grp_comp.setdefault(grp, []).append(gdata.get("completed", 0))
                grp_poss.setdefault(grp, []).append(gdata.get("possible", 0))
        return {
            grp: round(sum(grp_comp[grp]) / sum(grp_poss[grp]), 4)
            for grp in P40_GROUPS if grp in grp_comp and sum(grp_poss.get(grp, [0]))
        }

    avgs_7    = group_avgs(series_7)
    avgs_prev = group_avgs(series_prev_7)
    avgs_30   = group_avgs(series_30)

    overall_7 = round(sum(r["completion_pct"] for r in series_7) / len(series_7), 4) if series_7 else None
    overall_30 = round(sum(r["completion_pct"] for r in series_30) / len(series_30), 4) if series_30 else None

    group_trend = {}
    for grp in P40_GROUPS:
        if grp in avgs_7:
            delta = round(avgs_7[grp] - avgs_prev.get(grp, avgs_7[grp]), 4)
            group_trend[grp] = {
                "7d_avg":  avgs_7[grp],
                "30d_avg": avgs_30.get(grp),
                "delta_vs_prev_7d": delta,
                "direction": "improving" if delta > 0.02 else ("declining" if delta < -0.02 else "stable"),
            }

    sorted_groups = sorted(group_trend.items(), key=lambda x: x[1]["7d_avg"], reverse=True)
    best_groups  = [grp for grp, _ in sorted_groups[:3]]
    worst_groups = [grp for grp, _ in sorted_groups[-3:]]

    # Streak highlights: top 5 habits by current streak
    streak_result = tool_get_habit_streaks({"start_date": d30_start, "end_date": end_date})
    top_streaks = streak_result.get("active_streaks", [])[:5]

    alerts = []
    if latest["completion_pct"] < 0.40:
        alerts.append(f"⚠️ Latest day only {round(latest['completion_pct']*100)}% — below 40% threshold.")
    for grp, data in group_trend.items():
        if data["direction"] == "declining" and data["7d_avg"] < 0.40:
            alerts.append(f"⚠️ {grp} group declining — 7d avg {round(data['7d_avg']*100)}%.")

    return {
        "as_of":         end_date,
        "today":         today_status,
        "rolling_7d": {
            "overall_pct":  overall_7,
            "baseline_30d": overall_30,
            "delta_vs_30d": round(overall_7 - overall_30, 4) if (overall_7 and overall_30) else None,
            "days_data":    len(series_7),
        },
        "group_trends":  group_trend,
        "best_groups":   best_groups,
        "worst_groups":  worst_groups,
        "top_streaks":   top_streaks,
        "alerts":        alerts if alerts else ["✅ P40 system nominal."],
        "alert_count":   len(alerts),
    }


def tool_get_habits(args):
    """
    Unified habit intelligence dispatcher. Routes to the appropriate underlying
    function based on the 'view' parameter. All underlying functions are preserved
    for direct use (e.g. warmer.py).
    """
    VALID_VIEWS = {
        "dashboard":  tool_get_habit_dashboard,
        "adherence":  tool_get_habit_adherence,
        "streaks":    tool_get_habit_streaks,
        "tiers":      tool_get_habit_tier_report,
        "stacks":     tool_get_habit_stacks,
        "keystones":  tool_get_keystone_habits,
    }
    view = (args.get("view") or "dashboard").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Default view is 'dashboard'. Use 'adherence', 'streaks', 'tiers', 'stacks', or 'keystones' for other analyses.",
        }
    return VALID_VIEWS[view](args)


def tool_get_garmin_summary(args):
    """
    Garmin daily biometrics over a date range.
    Returns Body Battery, physiological stress, overnight HRV, RHR, and respiration
    from the Garmin Epix. These are Garmin-native metrics not available from other sources.

    Key metrics:
      body_battery_end  — Energy reserve at end of day (0-100). Garmin's flagship metric.
                          <25 = depleted; 25-50 = low; 50-75 = moderate; >75 = well-recovered.
      body_battery_high — Peak energy reserve for the day (how recovered you started).
      avg_stress        — Physiological stress (HRV-derived, 0-100). Objective, not subjective.
                          <25 = restful; 25-50 = low stress; 50-75 = medium; >75 = high stress.
      hrv_last_night    — Overnight average HRV from Garmin (ms). Cross-check with Whoop HRV.
      hrv_status        — Garmin's qualitative HRV status: POOR / FAIR / GOOD / EXCELLENT.
      resting_heart_rate— Daily RHR from Garmin optical sensor (cross-check with Whoop).
      avg_respiration   — Waking average respiration rate (breaths/min).
      sleep_respiration — Sleep average respiration (cross-check with Eight Sleep).
    """
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"))
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    items = query_source("garmin", start_date, end_date)
    if not items:
        return {"error": f"No Garmin data found for {start_date} to {end_date}. "
                         "Check that garmin-data-ingestion Lambda is running and has ingested data."}

    items_sorted = sorted(items, key=lambda x: x.get("date", ""))

    # Build per-day rows
    rows = []
    for item in items_sorted:
        row = {"date": item.get("date")}
        for field in ["body_battery_end", "body_battery_high", "body_battery_low",
                      "avg_stress", "max_stress", "stress_qualifier",
                      "hrv_last_night", "hrv_status", "hrv_5min_high",
                      "resting_heart_rate", "avg_respiration", "sleep_respiration", "steps"]:
            val = item.get(field)
            if val is not None:
                row[field] = float(val) if isinstance(val, Decimal) else val
        rows.append(row)

    # Compute period averages for numeric fields
    numeric_fields = ["body_battery_end", "body_battery_high", "avg_stress",
                      "hrv_last_night", "resting_heart_rate", "avg_respiration", "sleep_respiration"]
    averages = {}
    for field in numeric_fields:
        vals = [float(r[field]) for r in rows if field in r]
        if vals:
            averages[field] = round(sum(vals) / len(vals), 1)

    # HRV status breakdown
    hrv_statuses = [r["hrv_status"] for r in rows if "hrv_status" in r]
    status_counts = {}
    for s in hrv_statuses:
        status_counts[s] = status_counts.get(s, 0) + 1

    # Body Battery interpretation
    avg_bb = averages.get("body_battery_end")
    bb_interpretation = None
    if avg_bb is not None:
        if avg_bb >= 75:
            bb_interpretation = "Well-recovered — high energy reserve at end of day"
        elif avg_bb >= 50:
            bb_interpretation = "Moderate — adequate recovery but room to improve"
        elif avg_bb >= 25:
            bb_interpretation = "Low — energy reserve depleted, prioritise recovery"
        else:
            bb_interpretation = "Depleted — significant recovery deficit, consider rest day"

    return {
        "period":             {"start": start_date, "end": end_date, "days": len(rows)},
        "daily":              rows,
        "averages":           averages,
        "hrv_status_breakdown": status_counts if status_counts else None,
        "body_battery_interpretation": bb_interpretation,
        "note": (
            "Body Battery is Garmin's proprietary energy-reserve metric (0-100), computed from "
            "overnight HRV, stress load, sleep quality, and activity. Avg stress is physiological "
            "(HRV-derived), not self-reported — it measures your body's stress response, not your "
            "perceived stress level."
        ),
    }


def tool_get_device_agreement(args):
    """
    Cross-device validation: Whoop vs Garmin agreement on HRV and RHR.
    Surfaces nights where the two devices significantly disagree, which is itself
    a signal — large disagreement often indicates a poor device fit, measurement
    artifact, or genuine physiological noise worth flagging.

    Agreement thresholds:
      HRV: |Whoop - Garmin| <= 10ms → agree; 10-20ms → minor variance; >20ms → flag
      RHR: |Whoop - Garmin| <= 3bpm → agree; 3-6bpm → minor variance; >6bpm → flag

    Returns:
      - Day-by-day comparison table
      - Overall agreement rate for each metric
      - Flagged disagreement days with context
      - Composite device confidence rating
    """
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    whoop_items  = {item["date"]: item for item in query_source("whoop", start_date, end_date)
                    if item.get("date")}
    garmin_items = {item["date"]: item for item in query_source("garmin", start_date, end_date)
                    if item.get("date")}

    all_dates = sorted(set(whoop_items.keys()) & set(garmin_items.keys()))

    if not all_dates:
        return {"error": f"No overlapping Whoop + Garmin data for {start_date} to {end_date}. "
                         "Ensure Garmin ingestion has run for this period."}

    hrv_agree = hrv_minor = hrv_flag = 0
    rhr_agree = rhr_minor = rhr_flag = 0
    comparison_rows = []
    flagged_days = []

    for date in all_dates:
        w = whoop_items[date]
        g = garmin_items[date]

        row = {"date": date}
        flags = []

        # ── HRV comparison ────────────────────────────────────────────────────
        whoop_hrv  = w.get("hrv")
        garmin_hrv = g.get("hrv_last_night")
        if whoop_hrv is not None and garmin_hrv is not None:
            wh = float(whoop_hrv)
            gh = float(garmin_hrv)
            diff = abs(wh - gh)
            row.update({
                "whoop_hrv_ms":   round(wh, 1),
                "garmin_hrv_ms":  round(gh, 1),
                "hrv_delta_ms":   round(wh - gh, 1),
                "hrv_abs_diff_ms": round(diff, 1),
            })
            if diff <= 10:
                row["hrv_agreement"] = "agree"
                hrv_agree += 1
            elif diff <= 20:
                row["hrv_agreement"] = "minor_variance"
                hrv_minor += 1
            else:
                row["hrv_agreement"] = "flag"
                hrv_flag += 1
                flags.append(f"HRV: Whoop {wh:.0f}ms vs Garmin {gh:.0f}ms (diff {diff:.0f}ms)")

        # ── RHR comparison ────────────────────────────────────────────────────
        whoop_rhr  = w.get("resting_heart_rate")
        garmin_rhr = g.get("resting_heart_rate")
        if whoop_rhr is not None and garmin_rhr is not None:
            wr = float(whoop_rhr)
            gr = float(garmin_rhr)
            diff = abs(wr - gr)
            row.update({
                "whoop_rhr_bpm":   round(wr, 1),
                "garmin_rhr_bpm":  round(gr, 1),
                "rhr_delta_bpm":   round(wr - gr, 1),
                "rhr_abs_diff_bpm": round(diff, 1),
            })
            if diff <= 3:
                row["rhr_agreement"] = "agree"
                rhr_agree += 1
            elif diff <= 6:
                row["rhr_agreement"] = "minor_variance"
                rhr_minor += 1
            else:
                row["rhr_agreement"] = "flag"
                rhr_flag += 1
                flags.append(f"RHR: Whoop {wr:.0f}bpm vs Garmin {gr:.0f}bpm (diff {diff:.0f}bpm)")

        comparison_rows.append(row)
        if flags:
            flagged_days.append({"date": date, "flags": flags})

    n = len(all_dates)
    hrv_days = hrv_agree + hrv_minor + hrv_flag
    rhr_days = rhr_agree + rhr_minor + rhr_flag

    hrv_agreement_rate = round(hrv_agree / hrv_days * 100, 1) if hrv_days else None
    rhr_agreement_rate = round(rhr_agree / rhr_days * 100, 1) if rhr_days else None

    # Composite device confidence
    combined_rate = None
    if hrv_agreement_rate is not None and rhr_agreement_rate is not None:
        combined_rate = round((hrv_agreement_rate + rhr_agreement_rate) / 2, 1)
    elif hrv_agreement_rate is not None:
        combined_rate = hrv_agreement_rate
    elif rhr_agreement_rate is not None:
        combined_rate = rhr_agreement_rate

    if combined_rate is not None:
        if combined_rate >= 80:
            confidence = "HIGH — devices closely agree; composite readiness score is reliable"
        elif combined_rate >= 60:
            confidence = "MODERATE — minor inter-device variance; composite score is broadly reliable"
        else:
            confidence = "LOW — significant disagreement; investigate fit, positioning, or artifacts"
    else:
        confidence = "UNKNOWN — insufficient overlapping data"

    return {
        "period":            {"start": start_date, "end": end_date, "overlapping_days": n},
        "hrv_agreement": {
            "agree_days":    hrv_agree,
            "minor_days":    hrv_minor,
            "flagged_days":  hrv_flag,
            "agreement_rate_pct": hrv_agreement_rate,
            "threshold_note": "Agree: ≤10ms delta; minor: 10-20ms; flag: >20ms",
        } if hrv_days else None,
        "rhr_agreement": {
            "agree_days":    rhr_agree,
            "minor_days":    rhr_minor,
            "flagged_days":  rhr_flag,
            "agreement_rate_pct": rhr_agreement_rate,
            "threshold_note": "Agree: ≤3bpm delta; minor: 3-6bpm; flag: >6bpm",
        } if rhr_days else None,
        "device_confidence":  confidence,
        "combined_agreement_rate_pct": combined_rate,
        "flagged_disagreement_days": flagged_days if flagged_days else None,
        "daily":             comparison_rows,
        "interpretation": (
            "HRV delta is expected between devices (Whoop uses 1-min intervals overnight; "
            "Garmin uses 5-min intervals) — 10-15ms variance is normal. Flags >20ms often "
            "indicate one device had a poor-fit night. RHR should agree within 3-5bpm; "
            "larger gaps suggest optical sensor placement or motion artifacts."
        ),
    }


# ==============================================================================
# HABIT REGISTRY TOOLS (v2.47.0)
# ==============================================================================

def tool_get_habit_registry(args):
    """
    Inspect the habit registry — all 65 habits with tier, category, science,
    why_matthew, synergy_group, and scoring metadata.
    """
    tier_filter = args.get("tier")
    category_filter = (args.get("category") or "").strip().lower()
    vice_only = args.get("vice_only", False)
    synergy_filter = (args.get("synergy_group") or "").strip().lower()

    profile = get_profile()
    registry = profile.get("habit_registry", {})
    if not registry:
        return {"error": "No habit_registry found in PROFILE#v1. Deploy the registry first."}

    results = []
    tier_counts = {0: 0, 1: 0, 2: 0}
    category_counts = {}
    vice_count = 0
    synergy_groups_found = set()

    for name, meta in sorted(registry.items()):
        tier = meta.get("tier", 2)
        category = meta.get("category", "")
        is_vice = meta.get("vice", False)
        sg = meta.get("synergy_group", "")

        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        if is_vice:
            vice_count += 1
        if sg:
            synergy_groups_found.add(sg)

        if tier_filter is not None and tier != int(tier_filter):
            continue
        if category_filter and category.lower() != category_filter:
            continue
        if vice_only and not is_vice:
            continue
        if synergy_filter and sg.lower() != synergy_filter:
            continue

        results.append({
            "name": name, "tier": tier, "category": category,
            "vice": is_vice, "status": meta.get("status", "active"),
            "applicable_days": meta.get("applicable_days", "daily"),
            "target_frequency": meta.get("target_frequency", 7),
            "scoring_weight": meta.get("scoring_weight", 1.0),
            "p40_group": meta.get("p40_group", ""),
            "synergy_group": sg or None,
            "board_member": meta.get("board_member", ""),
            "science": meta.get("science", ""),
            "why_matthew": meta.get("why_matthew", ""),
            "expected_impact": meta.get("expected_impact", ""),
            "evidence_strength": meta.get("evidence_strength", ""),
            "friction_level": meta.get("friction_level", ""),
            "graduation_criteria": meta.get("graduation_criteria", ""),
        })

    return {
        "total_habits": len(registry), "filtered_count": len(results),
        "tier_counts": tier_counts, "category_counts": category_counts,
        "vice_count": vice_count, "synergy_groups": sorted(synergy_groups_found),
        "habits": results,
        "note": "Filter with tier=, category=, vice_only=true, or synergy_group= to narrow results.",
    }


def tool_get_habit_tier_report(args):
    """
    Tier-level adherence trends from the habit_scores partition.
    The key question: 'Are my non-negotiables actually non-negotiable?'
    """
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    items = query_source_range("habit_scores", start_date, end_date)
    if not items:
        return {"error": "No habit_scores data found. This data is generated by the daily brief starting v2.47.0."}

    items_sorted = sorted(items, key=lambda x: x.get("date", ""))
    daily = []
    t0_pcts, t1_pcts, vice_pcts, composites = [], [], [], []

    for item in items_sorted:
        t0_pct = float(item.get("tier0_pct", 0)) if item.get("tier0_pct") is not None else None
        t1_pct = float(item.get("tier1_pct", 0)) if item.get("tier1_pct") is not None else None
        v_held = int(item.get("vices_held", 0))
        v_total = int(item.get("vices_total", 0))
        v_pct = round(v_held / v_total, 3) if v_total > 0 else None
        comp = float(item.get("composite_score", 0)) if item.get("composite_score") is not None else None

        row = {
            "date": item.get("date"),
            "tier0_done": int(item.get("tier0_done", 0)), "tier0_total": int(item.get("tier0_total", 0)),
            "tier0_pct": t0_pct,
            "tier1_done": int(item.get("tier1_done", 0)), "tier1_total": int(item.get("tier1_total", 0)),
            "tier1_pct": t1_pct,
            "vices_held": v_held, "vices_total": v_total, "vices_pct": v_pct,
            "composite_score": comp,
            "missed_tier0": item.get("missed_tier0"),
        }
        daily.append(row)
        if t0_pct is not None: t0_pcts.append(t0_pct)
        if t1_pct is not None: t1_pcts.append(t1_pct)
        if v_pct is not None: vice_pcts.append(v_pct)
        if comp is not None: composites.append(comp)

    n = len(daily)
    def safe_avg(vals): return round(sum(vals) / len(vals), 3) if vals else None

    perfect_t0_days = sum(1 for d in daily if d["tier0_pct"] == 1.0)
    t0_perfect_rate = round(perfect_t0_days / n, 3) if n > 0 else None

    missed_t0_counts = {}
    for d in daily:
        for h in (d.get("missed_tier0") or []):
            missed_t0_counts[h] = missed_t0_counts.get(h, 0) + 1
    most_missed_t0 = sorted(missed_t0_counts.items(), key=lambda x: -x[1])[:5]

    def trend_direction(vals):
        if len(vals) < 6: return "insufficient_data"
        half = len(vals) // 2
        early = sum(vals[:half]) / half
        late = sum(vals[half:]) / (len(vals) - half)
        delta = late - early
        return "improving" if delta > 0.03 else ("declining" if delta < -0.03 else "stable")

    sg_data = {}
    for item in items_sorted:
        sgs = item.get("synergy_groups")
        if sgs and isinstance(sgs, dict):
            for sg, pct in sgs.items():
                sg_data.setdefault(sg, []).append(float(pct))
    sg_summary = {sg: {"avg_completion": safe_avg(pcts), "days_tracked": len(pcts), "trend": trend_direction(pcts)} for sg, pcts in sg_data.items()}

    return {
        "period": {"start": start_date, "end": end_date, "days": n},
        "summary": {
            "tier0_avg": safe_avg(t0_pcts), "tier0_perfect_days": perfect_t0_days,
            "tier0_perfect_rate": t0_perfect_rate, "tier0_trend": trend_direction(t0_pcts),
            "tier1_avg": safe_avg(t1_pcts), "tier1_trend": trend_direction(t1_pcts),
            "vice_avg": safe_avg(vice_pcts), "vice_trend": trend_direction(vice_pcts),
            "composite_avg": safe_avg(composites), "composite_trend": trend_direction(composites),
        },
        "most_missed_tier0": [{"habit": h, "days_missed": c} for h, c in most_missed_t0],
        "synergy_groups": sg_summary if sg_summary else None,
        "daily": daily,
        "coaching_note": "Tier 0 perfect rate is the single most important habit metric. If T0 adherence drops below 85%, the entire system needs attention.",
    }


def tool_get_vice_streak_history(args):
    """
    Vice streak trends over time from daily habit_scores snapshots.
    """
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    vice_filter = (args.get("vice_name") or "").strip().lower()

    items = query_source_range("habit_scores", start_date, end_date)
    if not items:
        return {"error": "No habit_scores data found. Generated by daily brief v2.47.0+."}

    items_sorted = sorted(items, key=lambda x: x.get("date", ""))
    vice_series = {}
    for item in items_sorted:
        vs = item.get("vice_streaks")
        if not vs or not isinstance(vs, dict):
            continue
        date = item.get("date")
        for vice_name, streak_days in vs.items():
            if vice_filter and vice_filter not in vice_name.lower():
                continue
            vice_series.setdefault(vice_name, []).append({"date": date, "streak_days": int(streak_days)})

    if not vice_series:
        return {"error": "No vice streak data found in the requested window."}

    vice_reports = []
    for vice_name, series in sorted(vice_series.items()):
        streaks = [s["streak_days"] for s in series]
        max_streak = max(streaks) if streaks else 0
        current_streak = streaks[-1] if streaks else 0
        max_date = next((s["date"] for s in series if s["streak_days"] == max_streak), None)

        relapses = []
        for i in range(1, len(series)):
            if series[i]["streak_days"] == 0 and series[i - 1]["streak_days"] > 0:
                relapses.append({"date": series[i]["date"], "streak_lost": series[i - 1]["streak_days"]})

        if len(streaks) >= 6:
            half = len(streaks) // 2
            early_avg = sum(streaks[:half]) / half
            late_avg = sum(streaks[half:]) / (len(streaks) - half)
            trend = "improving" if late_avg > early_avg + 2 else ("declining" if late_avg < early_avg - 2 else "stable")
        else:
            trend = "insufficient_data"

        vice_reports.append({
            "vice": vice_name, "current_streak": current_streak,
            "max_streak": max_streak, "max_streak_date": max_date,
            "relapse_count": len(relapses), "relapses": relapses[-5:],
            "trend": trend, "days_tracked": len(series), "series": series,
        })

    vice_reports.sort(key=lambda r: -r["current_streak"])

    return {
        "period": {"start": start_date, "end": end_date},
        "vices": vice_reports,
        "coaching_note": "Vice streaks are built on identity, not willpower. A relapse isn't failure — it's data. Look for patterns in timing and context.",
    }


# ==============================================================================
# BS-BH1: VICE STREAK AMPLIFIER
# ==============================================================================

def tool_get_vice_streaks(args):
    """BS-BH1: Vice Streak Amplifier.

    Dedicated view of vice streaks with compounding value calculation,
    streak risk rating, and identity reinforcement framing.
    Compounding formula: value = streak^1.5 / 10 (day 30 is ~3x day 3).
    Champions: Goggins (identity), Clear (habit identity).
    """
    days_back  = int(args.get("days_back", 90))
    end_date   = args.get("end_date", (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"))
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days_back - 1)).strftime("%Y-%m-%d")
    vice_filter = (args.get("vice_name") or "").strip().lower()

    items = query_source_range("habit_scores", start_date, end_date)
    if not items:
        return {"error": "No habit_scores data found. Generated by daily brief v2.47.0+."}

    items_sorted = sorted(items, key=lambda x: x.get("date", ""))

    # Extract vice series from habit_scores vice_streaks field
    vice_series = {}  # vice_name → [(date, streak_days)]
    for item in items_sorted:
        vs = item.get("vice_streaks")
        if not vs or not isinstance(vs, dict):
            continue
        date = item.get("date")
        for vice_name, streak_days in vs.items():
            if vice_filter and vice_filter not in vice_name.lower():
                continue
            vice_series.setdefault(vice_name, []).append(
                {"date": date, "streak_days": int(streak_days)}
            )

    if not vice_series:
        return {"error": "No vice streak data found in the requested window."}

    def compounding_value(streak_days):
        """Compounding value formula: streak^1.5 / 10. Day 30 ≈ 16.4, Day 3 ≈ 0.5 (3x ratio)."""
        return round((streak_days ** 1.5) / 10, 2)

    def streak_risk(streak_days, miss_rate_14d):
        """Rate relapse risk based on streak length and recent miss rate."""
        if streak_days <= 3:    return "establishing"
        if streak_days <= 14:
            return "moderate_risk" if miss_rate_14d > 0 else "building"
        if streak_days <= 30:  return "consolidating"
        return "identity_level"

    vice_reports = []
    total_value  = 0.0

    for vice_name, series in sorted(vice_series.items()):
        streaks  = [s["streak_days"] for s in series]
        dates    = [s["date"]        for s in series]
        current  = streaks[-1] if streaks else 0
        max_streak = max(streaks) if streaks else 0
        max_date   = dates[streaks.index(max_streak)] if streaks else None

        # Relapse detection
        relapses = []
        for i in range(1, len(series)):
            if series[i]["streak_days"] == 0 and series[i - 1]["streak_days"] > 0:
                relapses.append({
                    "date":         series[i]["date"],
                    "streak_lost":  series[i - 1]["streak_days"],
                })

        # 14-day miss rate (relapse count in last 14 days)
        recent_14 = [s for s in series if s["date"] >= (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")]
        relapses_14d = sum(1 for i in range(1, len(recent_14))
                           if recent_14[i]["streak_days"] == 0 and recent_14[i - 1]["streak_days"] > 0)
        miss_rate_14d = relapses_14d / max(len(recent_14), 1)

        # Compounding value
        current_value = compounding_value(current)
        max_value     = compounding_value(max_streak)
        total_value  += current_value

        # Value at milestone days
        milestones = {}
        for day in [7, 14, 30, 60, 90]:
            if day > current:
                milestones[f"day_{day}"] = compounding_value(day)
        next_milestone = min((d for d in [7, 14, 30, 60, 90] if d > current), default=None)
        days_to_next   = (next_milestone - current) if next_milestone else None

        risk = streak_risk(current, miss_rate_14d)

        # Trend over window
        if len(streaks) >= 14:
            half = len(streaks) // 2
            early_avg = sum(streaks[:half]) / half
            late_avg  = sum(streaks[half:]) / (len(streaks) - half)
            trend = "improving" if late_avg > early_avg + 2 else ("declining" if late_avg < early_avg - 2 else "stable")
        else:
            trend = "insufficient_data"

        report = {
            "vice":              vice_name,
            "current_streak":    current,
            "max_streak":        max_streak,
            "max_streak_date":   max_date,
            "current_value":     current_value,
            "max_value_ever":    max_value,
            "streak_risk":       risk,
            "relapse_count":     len(relapses),
            "last_relapse":      relapses[-1] if relapses else None,
            "next_milestone_day":  next_milestone,
            "days_to_milestone":   days_to_next,
            "value_at_milestone":  compounding_value(next_milestone) if next_milestone else None,
            "trend":             trend,
        }
        if next_milestone and days_to_next is not None:
            report["milestone_coaching"] = (
                f"Day {next_milestone} in {days_to_next} days: value jumps to "
                f"{compounding_value(next_milestone):.1f} (from {current_value:.1f} now)."
            )
        vice_reports.append(report)

    # Sort by current streak descending
    vice_reports.sort(key=lambda r: -r["current_streak"])

    # Summary
    identity_vices  = [r for r in vice_reports if r["streak_risk"] == "identity_level"]
    at_risk_vices   = [r for r in vice_reports if r["current_streak"] > 0 and r["relapse_count"] > 0 and r["streak_risk"] == "building"]
    broken_vices    = [r for r in vice_reports if r["current_streak"] == 0]

    coaching = []
    if identity_vices:
        names = ", ".join(r["vice"] for r in identity_vices)
        coaching.append(f"Identity-level (30+ days): {names}. You're no longer fighting this — it's part of who you are.")
    best = vice_reports[0] if vice_reports else None
    if best and best["days_to_milestone"] is not None:
        coaching.append(best["milestone_coaching"])
    if broken_vices:
        worst = broken_vices[0]
        coaching.append(f"Not yet building: {worst['vice']}. Last streak: {worst['max_streak']} days. Every streak starts from 1.")

    return {
        "as_of":           end_date,
        "window_days":     days_back,
        "vices":           vice_reports,
        "total_portfolio_value": round(total_value, 2),
        "identity_vices":  [r["vice"] for r in identity_vices],
        "at_risk_count":   len(at_risk_vices),
        "broken_count":    len(broken_vices),
        "coaching":        coaching,
        "formula_note":    "Compounding value = streak^1.5 / 10. Day 30 ≈ 16.4 points (3x Day 3's 5.2). Portfolio value = sum of all active vice streak values.",
        "goggins_note":    "Vice restraint isn't willpower — it's identity. The streak is proof you are the person who doesn't do this anymore.",
    }


def tool_get_essential_seven(args):
    """
    BS-01: Essential Seven Protocol.
    Returns Tier 0 habits only — the non-negotiable core. Streak, today's status,
    last failure date, and cascade risk (from computed_metrics habit_scores partition).
    Sarah Chen directive: define the surface (Daily Brief HTML + MCP) before building.
    Clear + Attia: 65 habits is too many; Essential Seven is the fix.
    """
    target_date = args.get("date", (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"))
    days_back   = int(args.get("days_back", 30))
    start_date  = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=days_back - 1)).strftime("%Y-%m-%d")

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (TypeError, ValueError): return None

    # ── Profile: get Tier 0 registry ───────────────────────────────────────────
    profile  = get_profile()
    registry = profile.get("habit_registry", {})

    tier0 = [
        name for name, meta in registry.items()
        if meta.get("tier") == 0 and meta.get("status") == "active"
    ]

    if not tier0:
        # Fallback: mvp_habits list
        tier0 = profile.get("mvp_habits", [])

    if not tier0:
        return {"error": "No Tier 0 habits found in profile. Check habit_registry or mvp_habits."}

    # ── Habitify records ──────────────────────────────────────────────────
    habit_records = query_source("habitify", start_date, target_date)
    by_date = {r["date"]: r for r in sorted(habit_records, key=lambda r: r.get("date", ""))}

    # ── Per-habit streak + last-fail analysis ─────────────────────────────────
    today_rec = by_date.get(target_date, {})
    today_habits = today_rec.get("habits", {}) if today_rec else {}

    habit_rows = []
    for habit in tier0:
        meta     = registry.get(habit, {})
        # Today's status
        today_val = _sf(today_habits.get(habit))
        today_done = bool(today_val and today_val >= 1)

        # Streak: walk back from target_date
        streak       = 0
        last_fail_date = None
        for i in range(days_back):
            d   = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
            rec = by_date.get(d, {})
            habits_map = rec.get("habits", {}) if rec else {}
            val = _sf(habits_map.get(habit))
            done = bool(val and val >= 1)
            if done:
                streak += 1
            else:
                last_fail_date = d
                break

        # Completion rate over window
        dates_with_data = [d for d in by_date if start_date <= d <= target_date]
        done_count = sum(
            1 for d in dates_with_data
            if _sf((by_date[d].get("habits") or {}).get(habit)) and
               _sf((by_date[d].get("habits") or {}).get(habit)) >= 1
        )
        completion_pct = round(done_count / len(dates_with_data) * 100) if dates_with_data else None

        habit_rows.append({
            "habit":           habit,
            "tier":            0,
            "today":           today_done,
            "streak_days":     streak,
            "last_fail":       last_fail_date,
            "completion_pct":  completion_pct,
            "applicable_days": meta.get("applicable_days", "all"),
            "synergy_group":   meta.get("synergy_group"),
        })

    # ── Aggregate streak (all T0 complete) ─────────────────────────────────────
    aggregate_streak = 0
    for i in range(days_back):
        d   = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = by_date.get(d, {})
        habits_map = rec.get("habits", {}) if rec else {}
        if not habits_map:
            break
        all_done = all(
            _sf(habits_map.get(h)) and _sf(habits_map.get(h)) >= 1
            for h in tier0
            if registry.get(h, {}).get("applicable_days") != "weekdays"
               or datetime.strptime(d, "%Y-%m-%d").weekday() < 5
        )
        if all_done:
            aggregate_streak += 1
        else:
            break

    # ── Today's score ───────────────────────────────────────────────────────
    today_done_count  = sum(1 for h in habit_rows if h["today"])
    today_total       = len(habit_rows)

    # ── Weakest link (most failures in window) ──────────────────────────────
    weakest = min(
        (h for h in habit_rows if h["completion_pct"] is not None),
        key=lambda h: h["completion_pct"],
        default=None,
    )

    # ── Board coaching ───────────────────────────────────────────────────────
    coaching = []
    if aggregate_streak >= 7:
        coaching.append(f"Clear: {aggregate_streak}-day Essential Seven streak. This is identity-level consistency — you're becoming someone who does these things.")
    elif aggregate_streak >= 3:
        coaching.append(f"Clear: {aggregate_streak} consecutive days with all 7. Enough to feel momentum; not enough to take for granted.")
    if weakest and weakest["completion_pct"] < 60:
        coaching.append(f"Attia: '{weakest['habit']}' is your weakest link at {weakest['completion_pct']}% completion. The chain is only as strong as this one.")
    if today_done_count < today_total:
        missing = [h["habit"] for h in habit_rows if not h["today"]]
        coaching.append(f"Today: {today_done_count}/{today_total} Essential habits done. Still open: {', '.join(missing)}.")

    return {
        "date":              target_date,
        "habits":            habit_rows,
        "aggregate_streak":  aggregate_streak,
        "today_done":        today_done_count,
        "today_total":       today_total,
        "today_pct":         round(today_done_count / today_total * 100) if today_total else 0,
        "weakest_habit":     weakest["habit"] if weakest else None,
        "window_days":       days_back,
        "coaching":          coaching,
        "tier":              "Tier 0 — non-negotiable core (Essential Seven Protocol, BS-01)",
    }
