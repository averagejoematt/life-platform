# RETIRED v3.7.46 — ADR-030. Google Calendar integration abandoned.
# All integration paths were blocked by Smartsheet IT or macOS restrictions.
# Kept as reference only. Do not deploy or activate.
# See docs/DECISIONS.md ADR-030 for full decision log.

#!/usr/bin/env python3
"""
setup/calendar_sync.py — Mac-native calendar sync for Life Platform.

Reads events from Apple Calendar (which syncs your work Google Calendar)
using a single AppleScript call for the whole window, computes daily stats,
and writes directly to DynamoDB using the identical schema as
google_calendar_lambda.py.

No OAuth required. Runs every 4 hours via launchd — picks up whichever
windows the Mac lid is open during the day.

Idempotent: safe to run multiple times per day (overwrites same record).

Run manually:   python3 setup/calendar_sync.py
Run via launchd: see setup/com.matthewwalker.calendar-sync.plist

Writes to DynamoDB:
  pk = USER#matthew#SOURCE#google_calendar
  sk = DATE#YYYY-MM-DD  (one per day, lookback + lookahead)
  sk = DATE#lookahead   (rolling 14-day forward summary)

Schema identical to google_calendar_lambda.py so all existing MCP tools
(get_calendar_events, get_schedule_load) work with no changes.

v1.1.0 - 2026-03-15 (single AppleScript call for whole window, not per-date)
v1.0.0 - 2026-03-15
"""

import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("calendar_sync")

# Configuration
REGION         = os.environ.get("AWS_REGION",   "us-west-2")
DYNAMODB_TABLE = os.environ.get("TABLE_NAME",   "life-platform")
USER_ID        = os.environ.get("USER_ID",      "matthew")
LOOKBACK_DAYS  = int(os.environ.get("LOOKBACK_DAYS",  "7"))
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "14"))
USER_PREFIX    = f"USER#{USER_ID}#SOURCE#"

# Calendars to skip — noise/system calendars
SKIP_CALENDARS = {"Birthdays", "Siri Suggestions", "Holidays in United States"}

# AWS
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(DYNAMODB_TABLE)


# ==============================================================================
# APPLESCRIPT CALENDAR READER
# Single call for the entire date window — dramatically faster than per-date.
# Output format: one event per line, pipe-delimited:
#   TITLE ||| START_DT ||| END_DT ||| ALL_DAY ||| CALENDAR_NAME
# ==============================================================================

_APPLESCRIPT = r"""
set eventLines to {}
set startBound to date "START_BOUND"
set endBound to date "END_BOUND"

tell application "Calendar"
    repeat with aCal in calendars
        try
            set calName to name of aCal
            set calEvents to every event of aCal whose start date >= startBound and start date <= endBound
            repeat with anEvent in calEvents
                try
                    set evTitle to summary of anEvent
                    if evTitle is missing value then set evTitle to "(no title)"
                    set evStart to start date of anEvent
                    set evEnd to end date of anEvent
                    set evAllDay to allday event of anEvent
                    set evLine to (evTitle as string) & "|||" & (evStart as string) & "|||" & (evEnd as string) & "|||" & (evAllDay as string) & "|||" & (calName as string)
                    set end of eventLines to evLine
                end try
            end repeat
        end try
    end repeat
end tell

set AppleScript's text item delimiters to "\n"
return eventLines as string
"""


def _as_date(date_str: str, hour_offset: int = 0) -> str:
    """Format YYYY-MM-DD as AppleScript date literal.

    hour_offset=0 => start of day (12:00:00 AM)
    hour_offset=23 => end of day (11:59:59 PM)
    """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if hour_offset == 0:
        return d.strftime("%B %-d, %Y at 12:00:00 AM")
    return d.strftime("%B %-d, %Y at 11:59:59 PM")


def _parse_applescript_time(raw: str) -> datetime | None:
    """Parse AppleScript datetime string -> datetime.

    AppleScript returns: "Sunday, March 15, 2026 at 9:00:00 AM"
    """
    raw = raw.strip()
    for fmt in (
        "%A, %B %d, %Y at %I:%M:%S %p",
        "%A, %B  %d, %Y at %I:%M:%S %p",
        "%B %d, %Y at %I:%M:%S %p",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def get_all_events(start_date: str, end_date: str) -> dict:
    """Fetch ALL Apple Calendar events in a SINGLE AppleScript call.

    Returns dict of date_str -> [event_dicts].
    One call for the whole window avoids the 30s-per-date timeout problem.
    """
    script = _APPLESCRIPT.replace(
        "START_BOUND", _as_date(start_date, 0)
    ).replace(
        "END_BOUND", _as_date(end_date, 23)
    )

    logger.info("Fetching events %s to %s via AppleScript...", start_date, end_date)

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("AppleScript timed out for window %s to %s", start_date, end_date)
        return {}
    except FileNotFoundError:
        logger.error("osascript not found - not running on macOS?")
        return {}

    if result.returncode != 0:
        logger.debug("AppleScript exit %d: %s", result.returncode, result.stderr[:200])

    raw_output = result.stdout.strip()
    if not raw_output:
        logger.info("No events returned (empty calendar window or no access yet)")
        return {}

    events_by_date: dict = {}
    for line in raw_output.split("\n"):
        line = line.strip()
        if not line:
            continue

        parts = line.split("|||")
        if len(parts) != 5:
            logger.debug("Unexpected line format: %s", line[:80])
            continue

        title, start_raw, end_raw, all_day_str, cal_name = [p.strip() for p in parts]

        if cal_name in SKIP_CALENDARS:
            continue

        is_all_day = all_day_str.lower() == "true"
        start_time = None
        end_time = None
        duration_min = None

        start_dt = _parse_applescript_time(start_raw)
        end_dt   = _parse_applescript_time(end_raw)

        if not start_dt:
            continue

        event_date = start_dt.strftime("%Y-%m-%d")

        if not is_all_day and end_dt:
            start_time   = start_dt.strftime("%H:%M")
            end_time     = end_dt.strftime("%H:%M")
            duration_min = max(0, int((end_dt - start_dt).total_seconds() / 60))

        if not title or title == "missing value":
            title = "(no title)"

        events_by_date.setdefault(event_date, []).append({
            "title":          title[:120],
            "calendar":       cal_name,
            "start_time":     start_time,
            "end_time":       end_time,
            "start_date":     event_date,
            "duration_min":   duration_min,
            "is_all_day":     is_all_day,
            "is_recurring":   False,
            "location":       None,
            "attendee_count": 0,
            "is_solo":        True,
            "status":         "confirmed",
        })

    total = sum(len(v) for v in events_by_date.values())
    logger.info("Got %d events across %d dates", total, len(events_by_date))
    return events_by_date


# ==============================================================================
# STATS - identical logic to google_calendar_lambda.py:compute_day_stats()
# Keep in sync if Lambda logic changes.
# ==============================================================================

def compute_day_stats(events: list) -> dict:
    confirmed = [e for e in events if e.get("status") != "cancelled"]
    timed = [
        e for e in confirmed
        if e.get("duration_min") is not None and not e.get("is_all_day")
    ]

    meeting_minutes = sum(e["duration_min"] for e in timed)
    has_all_day     = any(e.get("is_all_day") for e in confirmed)
    times           = [e["start_time"] for e in timed if e.get("start_time")]
    end_times       = [e["end_time"] for e in timed if e.get("end_time")]
    earliest        = min(times) if times else None
    latest          = max(end_times) if end_times else None

    focus_block_count = None
    timed_with_bounds = [
        e for e in timed
        if e.get("start_time") and e.get("end_time")
        and len(e["start_time"]) == 5 and len(e["end_time"]) == 5
    ]
    if timed_with_bounds:
        try:
            def _to_min(t: str) -> int:
                h, m = t.split(":")
                return int(h) * 60 + int(m)

            sorted_ev = sorted(timed_with_bounds, key=lambda e: _to_min(e["start_time"]))
            gap_count = 0
            prev_end  = None
            for ev in sorted_ev:
                s     = _to_min(ev["start_time"])
                e_end = _to_min(ev["end_time"])
                if prev_end is not None and s - prev_end >= 90:
                    gap_count += 1
                prev_end = max(prev_end or 0, e_end)
            if _to_min(sorted_ev[0]["start_time"]) - 540 >= 90:
                gap_count += 1
            focus_block_count = gap_count
        except Exception:
            focus_block_count = None

    return {
        "event_count":        len(confirmed),
        "meeting_minutes":    meeting_minutes,
        "focus_block_count":  focus_block_count,
        "has_all_day_events": has_all_day,
        "earliest_event":     earliest,
        "latest_event":       latest,
    }


# ==============================================================================
# DYNAMODB - identical schema to google_calendar_lambda.py
# ==============================================================================

def _to_dec(obj):
    if isinstance(obj, float):  return Decimal(str(obj))
    if isinstance(obj, dict):   return {k: _to_dec(v) for k, v in obj.items()}
    if isinstance(obj, list):   return [_to_dec(v) for v in obj]
    return obj


def store_day(date_str: str, events: list, stats: dict, ingested_at: str):
    item = {
        "pk":          USER_PREFIX + "google_calendar",
        "sk":          "DATE#" + date_str,
        "date":        date_str,
        "ingested_at": ingested_at,
        "source":      "apple_calendar_sync",
        **_to_dec(stats),
    }
    if events:
        item["events"] = _to_dec(events)
    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=item)


def store_lookahead(events_by_date: dict, ingested_at: str):
    summary = []
    for date_str in sorted(events_by_date.keys()):
        day_events = events_by_date[date_str]
        stats = compute_day_stats(day_events)
        summary.append({
            "date":            date_str,
            "event_count":     stats["event_count"],
            "meeting_minutes": stats["meeting_minutes"],
            "events":          day_events[:20],
        })

    item = {
        "pk":             USER_PREFIX + "google_calendar",
        "sk":             "DATE#lookahead",
        "lookahead_days": Decimal(str(LOOKAHEAD_DAYS)),
        "generated_at":   ingested_at,
        "source":         "apple_calendar_sync",
        "days":           _to_dec(summary),
    }
    table.put_item(Item=item)
    logger.info("Stored lookahead: %d days", len(summary))


# ==============================================================================
# MAIN
# ==============================================================================

def main() -> int:
    today        = date.today()
    today_str    = today.isoformat()
    ingested_at  = datetime.now(timezone.utc).isoformat()
    window_start = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    window_end   = (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat()

    logger.info("Calendar sync starting - %s (lookback=%d, lookahead=%d)",
                today_str, LOOKBACK_DAYS, LOOKAHEAD_DAYS)

    # Single AppleScript call for the entire window
    all_events = get_all_events(window_start, window_end)

    # Store every date in the window
    stored = 0
    all_dates = (
        [(today - timedelta(days=i)).isoformat() for i in range(LOOKBACK_DAYS, -1, -1)]
        + [(today + timedelta(days=i)).isoformat() for i in range(1, LOOKAHEAD_DAYS + 1)]
    )

    for date_str in all_dates:
        events = all_events.get(date_str, [])
        stats  = compute_day_stats(events)
        try:
            store_day(date_str, events, stats, ingested_at)
            stored += 1
        except Exception as e:
            logger.warning("Failed to store %s: %s", date_str, e)

    # Log today prominently
    today_stats = compute_day_stats(all_events.get(today_str, []))
    logger.info("Today %s: %d events, %d meeting mins, %s focus blocks",
                today_str, today_stats["event_count"], today_stats["meeting_minutes"],
                today_stats["focus_block_count"])

    # Store lookahead summary record
    lookahead_by_date = {
        (today + timedelta(days=i)).isoformat(): all_events.get(
            (today + timedelta(days=i)).isoformat(), []
        )
        for i in range(LOOKAHEAD_DAYS + 1)
    }
    store_lookahead(lookahead_by_date, ingested_at)

    total_events = sum(len(v) for v in all_events.values())
    logger.info("Done - %d dates stored, %d total events", stored, total_events)
    return stored


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
