#!/usr/bin/env python3
"""
Habitify → DynamoDB ingestion Lambda.

Replaces Chronicling as the P40 habit tracking source. Pulls daily habit
completion, group scores, and mood from the Habitify API.

DynamoDB schema (matches chronicling format for MCP compatibility):
  pk: USER#matthew#SOURCE#habitify
  sk: DATE#YYYY-MM-DD
  Fields:
    habits          — {habit_name: 1/0}  (matches chronicling count format)
    by_group        — {GroupName: {completed, possible, pct, habits_done}}
    total_completed — int
    total_possible  — int
    completion_pct  — Decimal (0.0–1.0)
    mood            — int (1-5, from Habitify moods)
    mood_label      — string (Terrible/Bad/Okay/Good/Excellent)
    skipped_count   — int

EventBridge trigger: daily at 6:15 AM PT (captures previous day; runs before
daily brief at 8:15 AM PT).

Can also be invoked manually:
  {"date": "YYYY-MM-DD"}           — single date
  {"start": "...", "end": "..."}   — backfill range

Environment variables:
  HABITIFY_SECRET_NAME — Secrets Manager key (default: life-platform/habitify)
  TABLE_NAME           — DynamoDB table (default: life-platform)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
SECRET_NAME = os.environ.get("HABITIFY_SECRET_NAME", "life-platform/habitify")
BASE_URL = "https://api.habitify.me"
# ── Config (env vars with backwards-compatible defaults) ──
REGION     = os.environ.get("AWS_REGION", "us-west-2")
USER_ID    = os.environ.get("USER_ID", "matthew")

PK = f"USER#{USER_ID}#SOURCE#habitify"

MOOD_LABELS = {1: "Terrible", 2: "Bad", 3: "Okay", 4: "Good", 5: "Excellent"}

# P40 group order (for consistent output)
P40_GROUPS = ["Data", "Discipline", "Growth", "Hygiene",
              "Nutrition", "Performance", "Recovery", "Supplements", "Wellbeing"]

# ── AWS clients ───────────────────────────────────────────────────────────────
secrets = boto3.client("secretsmanager", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def get_api_key():
    """Fetch Habitify API key from Secrets Manager."""
    resp = secrets.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    return secret["api_key"]


def api_get(endpoint, api_key, params=None):
    """GET request to Habitify API. Returns parsed JSON data field."""
    url = f"{BASE_URL}{endpoint}"
    if params:
        qs = urlencode(params)
        url = f"{url}?{qs}"
    req = Request(url, headers={"Authorization": api_key, "User-Agent": "LifePlatform/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            if not body.get("status"):
                raise Exception(f"API error: {body.get('message', 'Unknown')}")
            return body.get("data", [])
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error(f"Habitify API {e.code} on {endpoint}: {error_body}")
        raise


def fetch_areas(api_key):
    """Fetch all areas → {area_id: area_name} mapping."""
    areas = api_get("/areas", api_key)
    return {a["id"]: a["name"] for a in areas}


def fetch_journal(api_key, target_date):
    """Fetch all habits with status for a given date."""
    date_str = f"{target_date}T00:00:00+00:00"
    return api_get("/journal", api_key, {"target_date": date_str})


def fetch_moods(api_key, target_date):
    """Fetch mood entries for a given date."""
    date_str = f"{target_date}T00:00:00+00:00"
    try:
        return api_get("/moods", api_key, {"target_date": date_str})
    except Exception as e:
        logger.warning(f"Moods fetch failed (non-fatal): {e}")
        return []


def process_day(api_key, area_map, target_date):
    """
    Process a single day: fetch journal + moods, compute scores.

    Output matches chronicling DynamoDB format for MCP compatibility:
      habits:          {name: 1/0}
      by_group:        {GroupName: {completed, possible, pct, habits_done}}
      total_completed: int
      total_possible:  int
      completion_pct:  Decimal (0.0–1.0)

    Returns None if no habit data exists for the day.
    """
    journal = fetch_journal(api_key, target_date)

    if not journal:
        logger.info(f"No journal data for {target_date}")
        return None

    # ── Build habits map and group tallies ────────────────────────────────────
    habits = {}                   # {habit_name: 1 or 0}
    group_habits_done = {}        # {group: [list of completed habit names]}
    group_habits_possible = {}    # {group: [list of all habit names]}
    skipped_count = 0

    for entry in journal:
        name = entry.get("name", "Unknown")
        is_archived = entry.get("is_archived", False)
        if is_archived:
            continue

        # Determine completion status
        status = entry.get("status", "none")
        if isinstance(status, dict):
            status = status.get("status", "none")

        is_completed = (status == "completed")
        is_skipped = (status == "skipped")

        # Store as 1/0 to match chronicling format (int(val) in MCP _habit_series)
        habits[name] = Decimal("1") if is_completed else Decimal("0")

        if is_skipped:
            skipped_count += 1

        # Determine group from area
        area = entry.get("area")
        group = None
        if area and area.get("id"):
            group = area_map.get(area["id"])

        # Only count habits in recognized P40 groups
        if group and group in P40_GROUPS:
            group_habits_possible.setdefault(group, []).append(name)
            if is_completed:
                group_habits_done.setdefault(group, []).append(name)

    # ── Compute by_group (matches chronicling format) ─────────────────────────
    by_group = {}
    for group in P40_GROUPS:
        possible_list = group_habits_possible.get(group, [])
        done_list = group_habits_done.get(group, [])
        possible = len(possible_list)
        completed = len(done_list)
        if possible > 0:
            by_group[group] = {
                "completed": completed,
                "possible": possible,
                "pct": Decimal(str(round(completed / possible, 4))),
                "habits_done": done_list,
            }

    # ── Total score ───────────────────────────────────────────────────────────
    total_possible = sum(len(v) for v in group_habits_possible.values())
    total_completed = sum(len(v) for v in group_habits_done.values())
    completion_pct = Decimal(str(round(total_completed / total_possible, 4))) \
        if total_possible > 0 else Decimal("0")

    # ── Mood ──────────────────────────────────────────────────────────────────
    moods = fetch_moods(api_key, target_date)
    mood_value = None
    mood_label = None
    if moods:
        latest = moods[-1]
        mood_value = latest.get("value")
        mood_label = MOOD_LABELS.get(mood_value, "Unknown")

    # ── Build DynamoDB item ───────────────────────────────────────────────────
    item = {
        "pk": PK,
        "sk": f"DATE#{target_date}",
        "date": target_date,
        "source": "habitify",
        # ── Chronicling-compatible fields (MCP tools read these) ──────────────
        "habits": habits,                    # {name: 1/0}
        "by_group": by_group,                # {Group: {completed, possible, pct, habits_done}}
        "total_completed": total_completed,
        "total_possible": total_possible,
        "completion_pct": completion_pct,     # 0.0–1.0
        # ── New fields (Habitify-specific) ────────────────────────────────────
        "skipped_count": skipped_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if mood_value is not None:
        item["mood"] = mood_value
        item["mood_label"] = mood_label

    return item


def write_to_dynamo(item):
    """Write item to DynamoDB."""
    table.put_item(Item=item)
    logger.info(f"Wrote {item['sk']} — pct={item['completion_pct']}, "
                f"completed={item['total_completed']}/{item['total_possible']}"
                f"{', mood=' + str(item.get('mood', '')) if item.get('mood') else ''}")


def lambda_handler(event, context):
    """
    Lambda entry point.

    Event formats:
      {}                                → fetch yesterday (default for 6:15am schedule)
      {"date": "YYYY-MM-DD"}            → fetch specific date
      {"start": "...", "end": "..."}    → backfill date range
    """
    api_key = get_api_key()
    area_map = fetch_areas(api_key)
    logger.info(f"Fetched {len(area_map)} areas: {list(area_map.values())}")

    # Determine date(s) to process
    if "start" in event and "end" in event:
        # Backfill mode
        start = datetime.strptime(event["start"], "%Y-%m-%d")
        end = datetime.strptime(event["end"], "%Y-%m-%d")
        days_written = 0
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            item = process_day(api_key, area_map, date_str)
            if item:
                write_to_dynamo(item)
                days_written += 1
            current += timedelta(days=1)
        return {"statusCode": 200, "body": f"Backfilled {days_written} days"}

    elif "date" in event:
        target_date = event["date"]
    else:
        # Default: yesterday (scheduled at 6:15am PT, captures full previous day)
        pacific = timezone(timedelta(hours=-8))
        now_pacific = datetime.now(pacific)
        target_date = (now_pacific - timedelta(days=1)).strftime("%Y-%m-%d")

    item = process_day(api_key, area_map, target_date)

    if item:
        write_to_dynamo(item)
        return {
            "statusCode": 200,
            "body": json.dumps({
                "date": target_date,
                "completion_pct": float(item["completion_pct"]),
                "total_completed": item["total_completed"],
                "total_possible": item["total_possible"],
                "groups": {k: float(v["pct"]) for k, v in item["by_group"].items()},
                "mood": item.get("mood"),
            }),
        }
    else:
        return {
            "statusCode": 200,
            "body": json.dumps({"date": target_date, "message": "No data"}),
        }
