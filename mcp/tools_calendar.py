"""
tools_calendar.py — Google Calendar MCP tools.

Tools:
  tool_get_calendar_events  — events for a date or date range
  tool_get_schedule_load    — scheduling intelligence: meeting load, focus blocks, patterns

Data source: USER#matthew#SOURCE#google_calendar
  DATE#YYYY-MM-DD  — one record per day (past + today + tomorrow)
  DATE#lookahead   — 14-day forward summary (updated daily by ingestion Lambda)

v1.0.0 — 2026-03-14 (R8-ST1)
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mcp.config import USER_PREFIX, logger
from mcp.core import query_source, decimal_to_float

try:
    import boto3
    import os
    _REGION = os.environ.get("AWS_REGION", "us-west-2")
    _TABLE  = os.environ.get("TABLE_NAME", "life-platform")
    _ddb    = boto3.resource("dynamodb", region_name=_REGION)
    _table  = _ddb.Table(_TABLE)
except Exception:
    _table = None


def _fetch_day(date_str):
    """Fetch a single day's calendar record from DynamoDB."""
    try:
        resp = _table.get_item(
            Key={
                "pk": USER_PREFIX + "google_calendar",
                "sk": "DATE#" + date_str,
            }
        )
        item = resp.get("Item")
        return decimal_to_float(item) if item else None
    except Exception as e:
        logger.warning("_fetch_day(%s) failed: %s", date_str, e)
        return None


def _fetch_lookahead():
    """Fetch the 14-day lookahead summary record."""
    try:
        resp = _table.get_item(
            Key={
                "pk": USER_PREFIX + "google_calendar",
                "sk": "DATE#lookahead",
            }
        )
        item = resp.get("Item")
        return decimal_to_float(item) if item else None
    except Exception as e:
        logger.warning("_fetch_lookahead() failed: %s", e)
        return None


def _fetch_range(start_date, end_date):
    """Fetch calendar records for a date range."""
    return query_source("google_calendar", start_date, end_date)


# ==============================================================================
# tool_get_calendar_events
# ==============================================================================

def tool_get_calendar_events(args):
    """
    Get calendar events for a specific date or date range.

    Single date (default today):
      Returns full event list with titles, times, durations, calendars.

    Date range:
      Returns day-by-day summary with event counts and meeting minutes.

    Lookahead (default view):
      Returns the 14-day forward summary (pre-computed nightly).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    view        = (args.get("view") or "day").lower().strip()
    date_str    = args.get("date", today)
    start_date  = args.get("start_date")
    end_date    = args.get("end_date", today)

    if view == "lookahead":
        lookahead = _fetch_lookahead()
        if not lookahead:
            return {
                "error": "No lookahead data found. Google Calendar integration may not be set up.",
                "hint": "Run setup/setup_google_calendar_auth.py to authorize, then wait for the next daily ingestion run.",
            }
        days = lookahead.get("days", [])
        return {
            "view":           "lookahead",
            "generated_at":   lookahead.get("generated_at"),
            "lookahead_days": lookahead.get("lookahead_days", 14),
            "days":           days,
            "total_events":   sum(d.get("event_count", 0) for d in days),
            "total_meeting_minutes": sum(d.get("meeting_minutes", 0) for d in days),
        }

    if view == "range" and start_date:
        records = _fetch_range(start_date, end_date)
        if not records:
            return {
                "error": f"No calendar data for {start_date} → {end_date}.",
                "hint": "Google Calendar data only available from ingestion start date forward.",
            }
        summary = []
        for r in sorted(records, key=lambda x: x.get("date", "")):
            summary.append({
                "date":              r.get("date"),
                "event_count":       r.get("event_count", 0),
                "meeting_minutes":   r.get("meeting_minutes", 0),
                "focus_block_count": r.get("focus_block_count", 0),
                "earliest_event":    r.get("earliest_event"),
                "latest_event":      r.get("latest_event"),
            })
        total_meeting = sum(d["meeting_minutes"] for d in summary)
        avg_daily     = round(total_meeting / len(summary)) if summary else 0
        return {
            "view":                  "range",
            "start_date":            start_date,
            "end_date":              end_date,
            "days_with_data":        len(summary),
            "total_meeting_minutes": total_meeting,
            "avg_daily_meeting_min": avg_daily,
            "days":                  summary,
        }

    # Default: single day
    rec = _fetch_day(date_str)
    if not rec:
        # Try lookahead for future dates
        lookahead = _fetch_lookahead()
        if lookahead:
            for day in lookahead.get("days", []):
                if day.get("date") == date_str:
                    return {
                        "view":            "day",
                        "date":            date_str,
                        "source":          "lookahead",
                        "event_count":     day.get("event_count", 0),
                        "meeting_minutes": day.get("meeting_minutes", 0),
                        "events":          day.get("events", []),
                    }
        return {
            "error": f"No calendar data for {date_str}.",
            "hint": "Use view=lookahead for future dates, or check that Google Calendar is authorized.",
        }

    events = rec.get("events", [])
    return {
        "view":              "day",
        "date":              date_str,
        "event_count":       rec.get("event_count", 0),
        "meeting_minutes":   rec.get("meeting_minutes", 0),
        "focus_block_count": rec.get("focus_block_count", 0),
        "earliest_event":    rec.get("earliest_event"),
        "latest_event":      rec.get("latest_event"),
        "has_all_day_events": rec.get("has_all_day_events", False),
        "events":            events,
        "ingested_at":       rec.get("ingested_at"),
    }


# ==============================================================================
# tool_get_schedule_load
# ==============================================================================

def tool_get_schedule_load(args):
    """
    Scheduling intelligence: meeting load analysis, focus block availability,
    and planning patterns. Correlates schedule density with health/habit outcomes.

    Helps answer: 'Do I have a heavy week?', 'When are my best focus blocks?',
    'How does my meeting load affect my recovery?', 'Is tomorrow manageable?'
    """
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    days     = int(args.get("days", 14))
    end_date = args.get("end_date") or (
        datetime.now(timezone.utc) + timedelta(days=days)
    ).strftime("%Y-%m-%d")
    start_date = args.get("start_date") or today

    # Fetch historical data for pattern analysis
    hist_days  = int(args.get("history_days", 30))
    hist_start = (datetime.now(timezone.utc) - timedelta(days=hist_days)).strftime("%Y-%m-%d")
    yesterday  = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    historical = _fetch_range(hist_start, yesterday) if hist_days > 0 else []
    upcoming   = _fetch_lookahead()

    # ── Historical patterns ────────────────────────────────────────────────────
    patterns = {}
    if historical:
        meeting_mins_per_day = [r.get("meeting_minutes", 0) for r in historical]
        event_counts         = [r.get("event_count", 0) for r in historical]
        avg_meeting_min = round(sum(meeting_mins_per_day) / len(meeting_mins_per_day)) if meeting_mins_per_day else 0
        avg_events      = round(sum(event_counts) / len(event_counts), 1) if event_counts else 0
        heavy_days      = sum(1 for m in meeting_mins_per_day if m >= 240)  # ≥4h meetings
        focus_days      = sum(1 for m in meeting_mins_per_day if m <= 60)   # light schedule

        # Day-of-week breakdown
        dow_load = {str(i): [] for i in range(7)}  # 0=Mon...6=Sun
        for r in historical:
            d = r.get("date", "")
            try:
                dow = datetime.strptime(d, "%Y-%m-%d").weekday()
                dow_load[str(dow)].append(r.get("meeting_minutes", 0))
            except (ValueError, TypeError):
                pass
        dow_avg = {}
        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, name in enumerate(dow_names):
            vals = dow_load.get(str(i), [])
            dow_avg[name] = round(sum(vals) / len(vals)) if vals else 0

        busiest_dow   = max(dow_avg, key=dow_avg.get)
        lightest_dow  = min((k for k, v in dow_avg.items() if v is not None), key=dow_avg.get)

        patterns = {
            "history_days":       len(historical),
            "avg_meeting_min_per_day": avg_meeting_min,
            "avg_events_per_day": avg_events,
            "heavy_days_pct":     round(heavy_days / len(historical) * 100) if historical else 0,
            "focus_days_pct":     round(focus_days / len(historical) * 100) if historical else 0,
            "by_day_of_week":     dow_avg,
            "busiest_day":        busiest_dow,
            "lightest_day":       lightest_dow,
        }

    # ── Upcoming week summary ─────────────────────────────────────────────────
    upcoming_summary = []
    if upcoming:
        for day in upcoming.get("days", [])[:days]:
            d_str   = day.get("date", "")
            m_mins  = day.get("meeting_minutes", 0)
            e_count = day.get("event_count", 0)

            # Load classification
            if m_mins >= 300:   load = "very_heavy"
            elif m_mins >= 180: load = "heavy"
            elif m_mins >= 60:  load = "moderate"
            elif m_mins > 0:    load = "light"
            else:               load = "clear"

            upcoming_summary.append({
                "date":            d_str,
                "event_count":     e_count,
                "meeting_minutes": m_mins,
                "load":            load,
                "focus_available": load in ("clear", "light"),
            })

    # ── This week at a glance ──────────────────────────────────────────────────
    week_total_min  = sum(d["meeting_minutes"] for d in upcoming_summary[:7])
    week_heavy_days = sum(1 for d in upcoming_summary[:7] if d["load"] in ("heavy", "very_heavy"))
    week_clear_days = sum(1 for d in upcoming_summary[:7] if d["load"] == "clear")

    return {
        "generated_at":       today,
        "upcoming_days":      upcoming_summary,
        "week_ahead": {
            "total_meeting_minutes": week_total_min,
            "heavy_days":        week_heavy_days,
            "clear_days":        week_clear_days,
            "assessment": (
                "very_heavy_week" if week_total_min > 1500
                else "heavy_week" if week_total_min > 900
                else "moderate_week" if week_total_min > 400
                else "light_week"
            ),
        },
        "historical_patterns": patterns,
        "coaching_note": (
            f"Your average meeting load is {patterns.get('avg_meeting_min_per_day', 0)} min/day. "
            f"{patterns.get('lightest_day', 'Wednesday')} is typically your lightest day — "
            "consider protecting it for deep work."
            if patterns else
            "No historical data yet — patterns will emerge after a few weeks of data."
        ),
    }
