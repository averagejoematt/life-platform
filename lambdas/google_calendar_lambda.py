"""
google_calendar_lambda.py — Daily Google Calendar ingestion (v1.0.0)

Fetches calendar events and stores structured data to DynamoDB.
Runs daily at 6:30 AM PT (13:30 UTC) — before all compute and brief Lambdas.

DynamoDB records written:
  pk = USER#matthew#SOURCE#google_calendar
  sk = DATE#YYYY-MM-DD

  One record per day covering:
    - Confirmed events on that date
    - 14-day lookahead record (sk = DATE#lookahead) updated daily

Fields stored per day record:
  date, event_count, meeting_minutes, focus_block_count,
  earliest_event, latest_event, has_all_day_events,
  events[] — list of structured event objects
  ingested_at

Fields stored per event object:
  title (sanitised), calendar_name, start_time, end_time,
  duration_min, is_all_day, is_recurring, location,
  attendee_count, is_solo

Gap detection: 7-day lookback, backfills missing DATE records (partial-progress: one date at a time).
OAuth: refresh_token pattern, writes updated credentials back to Secrets Manager.
Auth: life-platform/google-calendar secret.

v1.0.1 — 2026-03-14 (R9 hardening: real focus_block_count algorithm, partial-progress gap fill)
v1.0.0 — 2026-03-14 (R8-ST1)
"""

import json
import os
import logging
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

try:
    from platform_logger import get_logger
    logger = get_logger("google_calendar")
except ImportError:
    logger = logging.getLogger("google_calendar")
    logger.setLevel(logging.INFO)

# ── Configuration ──────────────────────────────────────────────────────────────
SECRET_NAME    = "life-platform/google-calendar"
REGION         = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET      = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ["USER_ID"]
LOOKBACK_DAYS  = int(os.environ.get("LOOKBACK_DAYS", "7"))
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "14"))

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# ── AWS clients ────────────────────────────────────────────────────────────────
secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client      = boto3.client("s3",             region_name=REGION)
dynamodb       = boto3.resource("dynamodb",      region_name=REGION)
table          = dynamodb.Table(DYNAMODB_TABLE)


# ==============================================================================
# SERIALIZATION
# ==============================================================================

def _to_dec(obj):
    if isinstance(obj, float):  return Decimal(str(obj))
    if isinstance(obj, dict):   return {k: _to_dec(v) for k, v in obj.items()}
    if isinstance(obj, list):   return [_to_dec(v) for v in obj]
    return obj


# ==============================================================================
# OAUTH — refresh_token pattern (same as Strava/Whoop)
# ==============================================================================

def get_secret():
    resp = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])


def save_secret(secret_data):
    secrets_client.put_secret_value(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(secret_data),
    )


def refresh_access_token(secret):
    """Exchange refresh_token for a new access_token via Google's token endpoint."""
    logger.info("Refreshing Google OAuth access token...")
    data = urllib.parse.urlencode({
        "client_id":     secret["client_id"],
        "client_secret": secret["client_secret"],
        "refresh_token": secret["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    secret["access_token"]  = result["access_token"]
    secret["expires_in"]    = result.get("expires_in", 3600)
    secret["token_fetched"] = datetime.now(timezone.utc).isoformat()
    if "refresh_token" in result:
        secret["refresh_token"] = result["refresh_token"]
    save_secret(secret)
    logger.info("Access token refreshed and stored")
    return secret


def get_valid_token(secret):
    """Return a valid access token, refreshing if needed."""
    fetched_at = secret.get("token_fetched")
    expires_in = int(secret.get("expires_in", 0))
    if fetched_at and expires_in:
        fetched_dt = datetime.fromisoformat(fetched_at)
        if (datetime.now(timezone.utc) - fetched_dt).total_seconds() < expires_in - 300:
            return secret  # still valid
    return refresh_access_token(secret)


# ==============================================================================
# GOOGLE CALENDAR API
# ==============================================================================

def calendar_get(path, params, secret):
    """Make authenticated GET to Google Calendar API."""
    url = f"{GOOGLE_CALENDAR_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {secret['access_token']}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        logger.error("Calendar API error %s: %s", e.code, body)
        raise


def list_calendars(secret):
    """Return list of all calendar entries for the authenticated user."""
    result = calendar_get("/users/me/calendarList", {"maxResults": 50}, secret)
    return result.get("items", [])


def fetch_events_for_range(calendar_id, time_min, time_max, secret):
    """Fetch all events from a calendar within a time window. Handles pagination."""
    all_events = []
    params = {
        "timeMin":      time_min,
        "timeMax":      time_max,
        "singleEvents": "true",
        "orderBy":      "startTime",
        "maxResults":   250,
    }
    base_path = f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events"

    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)
        result = calendar_get(base_path, params, secret)
        all_events.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return all_events


# ==============================================================================
# EVENT PARSING
# ==============================================================================

def parse_event(event, calendar_name):
    """Extract structured fields from a raw Google Calendar event object."""
    start = event.get("start", {})
    end   = event.get("end", {})

    is_all_day   = "date" in start and "dateTime" not in start
    start_str    = start.get("dateTime") or start.get("date", "")
    end_str      = end.get("dateTime")   or end.get("date", "")
    is_recurring = "recurrence" in event or bool(event.get("recurringEventId"))

    duration_min = None
    if not is_all_day and start_str and end_str:
        try:
            s = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            duration_min = max(0, int((e - s).total_seconds() / 60))
        except (ValueError, TypeError):
            pass

    start_time = None
    end_time   = None
    if not is_all_day and start_str:
        try:
            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00")).strftime("%H:%M")
            end_time   = datetime.fromisoformat(end_str.replace("Z", "+00:00")).strftime("%H:%M") if end_str else None
        except (ValueError, TypeError):
            pass

    attendees      = event.get("attendees", [])
    attendee_count = len(attendees)
    is_solo        = attendee_count == 0 or (attendee_count == 1 and attendees[0].get("self"))

    summary = (event.get("summary") or "").strip()
    if len(summary) > 120:
        summary = summary[:120] + "..."

    return {
        "title":          summary or "(no title)",
        "calendar":       calendar_name,
        "start_time":     start_time,
        "end_time":       end_time,
        "start_date":     (start.get("date") or start_str[:10]) if start_str else None,
        "duration_min":   duration_min,
        "is_all_day":     is_all_day,
        "is_recurring":   is_recurring,
        "location":       (event.get("location") or "")[:100] or None,
        "attendee_count": attendee_count,
        "is_solo":        is_solo,
        "status":         event.get("status", "confirmed"),
    }


def compute_day_stats(events):
    """
    Aggregate daily statistics from a list of parsed events.

    focus_block_count: number of gaps ≥90 minutes between consecutive timed events,
    computed from actual event start/end times. Returns None when insufficient
    time data is available (e.g. events missing start/end strings).
    Do NOT fabricate this value — null is correct when uncomputable.
    """
    confirmed = [e for e in events if e.get("status") != "cancelled"]
    timed     = [e for e in confirmed if e.get("duration_min") is not None and not e.get("is_all_day")]

    meeting_minutes = sum(e["duration_min"] for e in timed)
    has_all_day     = any(e.get("is_all_day") for e in confirmed)

    times     = [e["start_time"] for e in timed if e.get("start_time")]
    end_times = [e["end_time"] for e in timed if e.get("end_time")]
    earliest  = min(times) if times else None
    latest    = max(end_times) if end_times else None

    # Focus blocks: count actual gaps ≥90 min between consecutive events.
    # Requires HH:MM start and end times. Returns None if insufficient data.
    focus_block_count = None
    events_with_times = [
        e for e in timed
        if e.get("start_time") and e.get("end_time")
        and len(e["start_time"]) == 5 and len(e["end_time"]) == 5
    ]
    if events_with_times:
        try:
            def _to_min(t):
                h, m = t.split(":")
                return int(h) * 60 + int(m)

            sorted_ev = sorted(events_with_times, key=lambda e: _to_min(e["start_time"]))
            gap_count = 0
            prev_end  = None
            for ev in sorted_ev:
                start_min = _to_min(ev["start_time"])
                end_min   = _to_min(ev["end_time"])
                if prev_end is not None:
                    gap = start_min - prev_end
                    if gap >= 90:
                        gap_count += 1
                prev_end = max(prev_end or 0, end_min)
            # Count morning block before first event (from 09:00)
            first_start = _to_min(sorted_ev[0]["start_time"])
            if first_start - 540 >= 90:  # 540 = 9:00 AM
                gap_count += 1
            focus_block_count = gap_count
        except Exception:
            focus_block_count = None  # Parsing failed — return null, not a guess

    return {
        "event_count":        len(confirmed),
        "meeting_minutes":    meeting_minutes,
        "focus_block_count":  focus_block_count,  # None when not computable
        "has_all_day_events": has_all_day,
        "earliest_event":     earliest,
        "latest_event":       latest,
    }


# ==============================================================================
# DDB HELPERS
# ==============================================================================

def existing_dates(start_date, end_date):
    """Return set of DATE# sort keys already present in DDB for this source."""
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX + "google_calendar",
                ":s":  "DATE#" + start_date,
                ":e":  "DATE#" + end_date,
            },
            ProjectionExpression="sk",
        )
        return {item["sk"] for item in resp.get("Items", [])}
    except Exception as e:
        logger.warning("existing_dates query failed: %s", e)
        return set()


def store_day(date_str, events, stats, ingested_at):
    """Write one day's calendar data to DynamoDB."""
    item = {
        "pk":          USER_PREFIX + "google_calendar",
        "sk":          "DATE#" + date_str,
        "date":        date_str,
        "ingested_at": ingested_at,
        **_to_dec(stats),
    }
    if events:
        item["events"] = _to_dec(events)
    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=item)


def store_lookahead(events_by_date, ingested_at):
    """
    Write 14-day lookahead summary. sk = DATE#lookahead (overwritten daily).
    NOTE: DATE#lookahead is intentionally non-standard — it sorts after all
    DATE#YYYY-MM-DD keys so date-range queries never accidentally return it.
    """
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
        "days":           _to_dec(summary),
    }
    table.put_item(Item=item)
    logger.info("Stored lookahead record: %d days", len(summary))


# ==============================================================================
# MAIN INGESTION LOGIC
# ==============================================================================

def ingest_date_range(calendars, start_date, end_date, secret):
    """Fetch and aggregate events for all calendars. Returns date_str → [events]."""
    time_min = f"{start_date}T00:00:00Z"
    time_max = f"{end_date}T23:59:59Z"

    cal_map = {
        c["id"]: c.get("summary", c["id"])
        for c in calendars
        if c.get("accessRole") in ("owner", "writer", "reader", "freeBusyReader")
        and not c.get("deleted")
    }

    events_by_date = {}
    for cal_id, cal_name in cal_map.items():
        try:
            raw_events = fetch_events_for_range(cal_id, time_min, time_max, secret)
            logger.info("Calendar '%s': %d events", cal_name, len(raw_events))
        except Exception as e:
            logger.warning("Failed to fetch calendar '%s': %s", cal_name, e)
            continue

        for raw in raw_events:
            if raw.get("status") == "cancelled":
                continue
            parsed = parse_event(raw, cal_name)
            event_date = parsed.get("start_date")
            if not event_date:
                continue
            events_by_date.setdefault(event_date, []).append(parsed)

    return events_by_date


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================

def lambda_handler(event, context):
    import time
    t0 = time.time()
    logger.info("Google Calendar ingestion v1.0.1 starting...")

    today       = datetime.now(timezone.utc).date()
    ingested_at = datetime.now(timezone.utc).isoformat()

    # ── Auth ──────────────────────────────────────────────────────────────────
    try:
        secret = get_secret()
    except Exception as e:
        logger.error("Failed to load secret %s: %s", SECRET_NAME, e)
        return {"statusCode": 500, "body": f"Secret load failed: {e}"}

    try:
        secret = get_valid_token(secret)
    except Exception as e:
        logger.error("Token refresh failed: %s", e)
        return {"statusCode": 500, "body": f"Token refresh failed: {e}"}

    # ── List calendars ────────────────────────────────────────────────────────
    try:
        calendars = list_calendars(secret)
        logger.info("Found %d calendars", len(calendars))
    except Exception as e:
        logger.error("Failed to list calendars: %s", e)
        return {"statusCode": 500, "body": f"Calendar list failed: {e}"}

    # ── Gap detection (backfill lookback window) ───────────────────────────────
    lookback_start = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    today_str      = today.isoformat()

    present = existing_dates(lookback_start, today_str)
    missing_dates = [
        (today - timedelta(days=i)).isoformat()
        for i in range(LOOKBACK_DAYS + 1)
        if f"DATE#{(today - timedelta(days=i)).isoformat()}" not in present
    ]

    if missing_dates:
        logger.info("Backfilling %d missing date(s): %s", len(missing_dates), missing_dates[:5])

    # ── Fetch past dates (gap fill — partial-progress: store each date as fetched) ──
    stored_count = 0
    if missing_dates:
        # Fetch + store one date at a time so partial runs still persist progress.
        # If the Lambda times out or an API call fails mid-backfill, already-fetched
        # dates are safely stored and won't be re-fetched on the next run.
        for date_str in sorted(missing_dates):
            try:
                day_events_batch = ingest_date_range(calendars, date_str, date_str, secret)
                day_evts = day_events_batch.get(date_str, [])
                stats    = compute_day_stats(day_evts)
                store_day(date_str, day_evts, stats, ingested_at)
                stored_count += 1
                logger.info("Stored %s: %d events, %d meeting mins",
                            date_str, stats["event_count"], stats["meeting_minutes"])
            except Exception as e:
                logger.warning("Failed to ingest date %s: %s — skipping (will retry tomorrow)",
                               date_str, e)

    # ── Fetch lookahead (always refresh) ─────────────────────────────────────
    lookahead_end    = (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat()
    lookahead_events = ingest_date_range(calendars, today_str, lookahead_end, secret)
    store_lookahead(lookahead_events, ingested_at)

    # Also store today + tomorrow as DATE records for Daily Brief access
    for d_str in [today_str, (today + timedelta(days=1)).isoformat()]:
        day_evts = lookahead_events.get(d_str, [])
        stats    = compute_day_stats(day_evts)
        store_day(d_str, day_evts, stats, ingested_at)
        stored_count += 1

    # ── S3 backup (today's raw) ───────────────────────────────────────────────
    try:
        s3_key = f"raw/google_calendar/{today_str}.json"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps({
                "date": today_str,
                "lookahead_days": LOOKAHEAD_DAYS,
                "events_by_date": lookahead_events,
                "ingested_at": ingested_at,
            }, default=str),
            ContentType="application/json",
        )
        logger.info("S3 backup: s3://%s/%s", S3_BUCKET, s3_key)
    except Exception as e:
        logger.warning("S3 backup failed (non-fatal): %s", e)

    elapsed      = round(time.time() - t0, 1)
    total_events = sum(len(v) for v in lookahead_events.values())
    logger.info("Done in %ss — %d dates stored, %d lookahead events", elapsed, stored_count, total_events)

    return {
        "statusCode":       200,
        "dates_stored":     stored_count,
        "lookahead_events": total_events,
        "elapsed_seconds":  elapsed,
    }
