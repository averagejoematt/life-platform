"""
Correlation tools: caffeine, exercise, zone2, alcohol vs sleep.
"""

from datetime import datetime, timedelta

from common.pacific_time import pacific_now, pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from training import zone2_minutes as z2m  # #4627: THE Zone 2 computation (shared with /api/zone2 + /api/training_overview)

from mcp.core import query_source
from mcp.helpers import pearson_r


def _calendar_weeks(start_date, end_date):
    """Monday of every calendar week touching [start, end], and the partial ones among them (#2661)."""
    win_start, win_end = datetime.strptime(start_date, "%Y-%m-%d"), datetime.strptime(end_date, "%Y-%m-%d")
    weeks, cur = [], win_start - timedelta(days=win_start.weekday())
    while cur <= win_end:
        weeks.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=7)
    partial = sorted(
        {
            wk
            for wk in (weeks[0], weeks[-1])
            if not (win_start <= datetime.strptime(wk, "%Y-%m-%d") and datetime.strptime(wk, "%Y-%m-%d") + timedelta(days=6) <= win_end)
        }
    )
    return weeks, partial


def _zone2_alerts(avg_z2_weekly, weekly_target_min, zones, sessions):
    alerts = []
    # #2661: a non-positive target makes "shortfall" meaningless too.
    if weekly_target_min > 0 and avg_z2_weekly < weekly_target_min * 0.5:
        alerts.append(
            f"Zone 2 deficit: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({round(weekly_target_min - avg_z2_weekly):.0f} min shortfall), measured as minutes in each device's own Zone 2. "
            "Zone 2 is the foundation of cardiovascular longevity -- consider adding 2-3 sessions of easy cardio per week."
        )
    elif weekly_target_min > 0 and avg_z2_weekly < weekly_target_min:
        alerts.append(
            f"Close to target: averaging {avg_z2_weekly} min/week vs {weekly_target_min} min target "
            f"({round(weekly_target_min - avg_z2_weekly):.0f} min shortfall). One additional Zone 2 session per week would close the gap."
        )
    z2, z3, z5 = zones["zone_2"], zones["zone_3"], zones["zone_5"]
    if z3 > z2 and z3 > 30:
        alerts.append(
            f"Training polarization issue: more time in Zone 3 ({round(z3)} min) than Zone 2 ({round(z2)} min). Per Seiler's "
            "polarized model, ~80% of endurance volume should be easy (Zone 1-2) with ~20% hard (Zone 4-5)."
        )
    if z5 > z2 and z5 > 20:
        alerts.append(
            f"High-intensity dominant: more Zone 5 ({round(z5)} min) than Zone 2 ({round(z2)} min). Prioritize Zone 2 base building."
        )
    unmeasured = sum(1 for s in sessions if not s["source"])
    if sessions and unmeasured > len(sessions) * 0.3:
        alerts.append(
            f"{unmeasured} of {len(sessions)} sessions ({round(100 * unmeasured / len(sessions))}%) carry no stored time-in-zone, "
            "so they add nothing to Zone 2 -- a gap, never a zero."
        )
    return alerts


def tool_get_zone2_breakdown(args):
    """
    Zone 2 training tracker over THE shared computation (`training.zone2_minutes`, #4627): minutes
    actually spent in each recording device's own Zone 2 band (Whoop workout zones, Strava activity
    zones), each session counted once across sources; Hevy bike/elliptical/treadmill blocks are
    reported as cardio minutes, never Zone 2. Aggregates weekly Zone 2 minutes over every calendar
    week in the window (#2661), compares to the 150 min/week target (Attia, Huberman, WHO) and
    shows the zone distribution. The same numbers `/api/zone2` and `/api/training_overview` serve.
    """
    end_date = args.get("end_date", pacific_today())
    start_date = args.get("start_date", (pacific_now() - timedelta(days=89)).strftime("%Y-%m-%d"))
    weekly_target_min = int(args.get("weekly_target_minutes", z2m.WEEKLY_TARGET_MIN))

    strava_items = query_source("strava", start_date, end_date)
    whoop_end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")  # Pacific evening -> next UTC key
    whoop_items = query_source("whoop", start_date, whoop_end)
    hevy_items = query_source("hevy", start_date, end_date)
    sessions = [s for s in z2m.counted_sessions(strava_items, whoop_items) if start_date <= s["date"] <= end_date]
    if not sessions:
        return {"error": "No recorded sessions for range.", "start_date": start_date, "end_date": end_date}
    window = z2m.zone2_window(None, None, hevy_items, start_date, end_date, sessions=sessions)

    calendar_weeks, partial_weeks = _calendar_weeks(start_date, end_date)
    by_week = {w["week_start"]: w for w in z2m.weekly(sessions, hevy_items, weekly_target_min)}
    target_is_meaningful = weekly_target_min > 0
    weekly_sorted = []
    for wk in calendar_weeks:
        w = by_week.get(wk) or {"zone_2_minutes": 0.0, "session_minutes": 0.0, "activity_count": 0, "hevy_cardio_minutes": 0.0}
        z2 = w["zone_2_minutes"]
        wk_sess = [s for s in sessions if s["source"] and z2m._monday(s["date"]) == wk]
        weekly_sorted.append(
            {
                "week_start": wk,
                "zone_2_minutes": z2,
                "target_pct": round(100 * z2 / weekly_target_min, 0) if target_is_meaningful else None,
                "target_met": (z2 >= weekly_target_min) if target_is_meaningful else None,
                **{f"{k}_min": round(sum(s["zones_minutes"][k] for s in wk_sess), 1) for k in ("zone_1", "zone_3", "zone_4", "zone_5")},
                "total_exercise_min": w["session_minutes"],
                "hevy_cardio_min": w["hevy_cardio_minutes"],
                "activity_count": w["activity_count"],
                "zone_2_activities": [
                    {"date": s["date"], "sport": s["sport"], "minutes": s["zone_2_minutes"], "source": s["source"]}
                    for s in wk_sess
                    if s["zone_2_minutes"]
                ],
            }
        )

    zones = window["zones_minutes"]
    dist = z2m.zone_distribution(sessions)
    zone_distribution = {
        z["zone"]: {"total_minutes": z["total_minutes"], "activity_count": z["activity_count"], "pct_of_training": z["pct_of_training"]}
        for z in dist
    }

    z2_weekly_vals = [w["zone_2_minutes"] for w in weekly_sorted]
    trend = None
    if len(z2_weekly_vals) >= 3:
        half = len(z2_weekly_vals) // 2
        first, second = sum(z2_weekly_vals[:half]) / max(half, 1), sum(z2_weekly_vals[half:]) / max(len(z2_weekly_vals) - half, 1)
        trend = {
            "direction": "INCREASING" if second > first + 5 else "DECREASING" if second < first - 5 else "STABLE",
            "first_half_avg_min": round(first, 1),
            "second_half_avg_min": round(second, 1),
            "correlation_r": pearson_r(list(range(len(z2_weekly_vals))), z2_weekly_vals),
        }

    n_weeks = len(weekly_sorted)  # #2661: calendar weeks in the window, not active weeks
    active_weeks = sum(1 for w in weekly_sorted if w["activity_count"] > 0)
    avg_z2_weekly = round(sum(z2_weekly_vals) / n_weeks, 1) if n_weeks > 0 else 0
    weeks_meeting_target = sum(1 for w in weekly_sorted if w["target_met"]) if target_is_meaningful else None
    summary = {
        "period": {"start_date": start_date, "end_date": end_date},
        "weeks_analyzed": n_weeks,
        # ADR-105: `weeks_analyzed` is the denominator every rate divides by; `active_weeks`
        # is how many had any session. When they differ, the gap IS the adherence story.
        "denominator": "calendar weeks in the requested window",
        "active_weeks": active_weeks,
        "zero_activity_weeks": n_weeks - active_weeks,
        "partial_weeks": partial_weeks,
        "total_activities": len(sessions),
        "zone_2_activities": sum(1 for s in sessions if s["source"] and s["zone_2_minutes"]),
        "unmeasured_sessions": window["unmeasured_sessions"],
        "avg_weekly_zone_2_min": avg_z2_weekly,
        "weekly_target_min": weekly_target_min,
        "weeks_meeting_target": weeks_meeting_target,
        "target_hit_rate_pct": (round(100 * weeks_meeting_target / n_weeks, 0) if (target_is_meaningful and n_weeks > 0) else None),
        "target_applicable": target_is_meaningful,
        "target_note": (
            None
            if target_is_meaningful
            else f"weekly_target_minutes={weekly_target_min} — a hit rate against a non-positive target is not defined, so none is reported."
        ),
        "total_zone_2_min": window["zone_2_minutes"],
        "zone_2_by_source": window["by_source"],
        "hevy_cardio_min": window["hevy_cardio_minutes"],
        "max_hr_used": None,  # #4627: no maximum is assumed — each device's own band
        "zone_2_hr_range": "each recording device's own Zone 2 band (Whoop, Strava)",
        "definition": z2m.DEFINITION,
    }
    return {
        "summary": summary,
        "zone_distribution": zone_distribution,
        "weekly_breakdown": weekly_sorted,
        "sport_type_zone2": z2m.sport_breakdown(sessions),
        "trend": trend,
        "alerts": _zone2_alerts(avg_z2_weekly, weekly_target_min, zones, sessions),
        "methodology": (
            "Minutes actually spent in each recording device's own Zone 2 band, from the stored time-in-zone rows "
            "(Whoop workout zones; Strava activity zones). Each session is counted once across sources — Whoop's own "
            "zones unless another recording measured materially more of the session. Sessions with no stored zones "
            "add nothing (a gap, not a zero). Hevy bike/elliptical/treadmill blocks are cardio minutes, not Zone 2."
        ),
    }
