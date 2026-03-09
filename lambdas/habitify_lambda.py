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

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("habitify")
except ImportError:
    logger = logging.getLogger("habitify")
    logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
SECRET_NAME = os.environ.get("HABITIFY_SECRET_NAME", "life-platform/api-keys")
BASE_URL = "https://api.habitify.me"
# ── Config (env vars with backwards-compatible defaults) ──
REGION     = os.environ.get("AWS_REGION", "us-west-2")
USER_ID    = os.environ.get("USER_ID", "matthew")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))

PK = f"USER#{USER_ID}#SOURCE#habitify"

MOOD_LABELS = {1: "Terrible", 2: "Bad", 3: "Okay", 4: "Good", 5: "Excellent"}

# P40 group order (for consistent output)
P40_GROUPS = ["Data", "Discipline", "Growth", "Hygiene",
              "Nutrition", "Performance", "Recovery", "Supplements", "Wellbeing"]

# ── Supplement Bridge (v2.55.1) ───────────────────────────────────────────────
# Maps Habitify supplement habit names → structured supplement metadata.
# Automatically writes to USER#matthew#SOURCE#supplements after each Habitify
# ingestion so get_supplement_log / get_supplement_correlation have data.
# Dosages are defaults — update here when actual doses are confirmed.

SUPPLEMENTS_PK = f"USER#{USER_ID}#SOURCE#supplements"

SUPPLEMENT_MAP = {
    # ── Morning batch (fasted) ──
    "Probiotics":    {"dose": 1,    "unit": "capsule", "timing": "morning",    "category": "supplement"},
    "L Glutamine":   {"dose": 5,    "unit": "g",       "timing": "morning",    "category": "supplement"},
    "Collagen":      {"dose": 10,   "unit": "g",       "timing": "morning",    "category": "supplement"},
    "Electrolytes":  {"dose": 1,    "unit": "packet",  "timing": "morning",    "category": "supplement"},
    # ── Afternoon batch (with food) ──
    "Multivitamin":          {"dose": 1,    "unit": "capsule", "timing": "with_meal", "category": "vitamin"},
    "Vitamin D":             {"dose": 5000, "unit": "IU",      "timing": "with_meal", "category": "vitamin"},
    "Omega 3":               {"dose": 2000, "unit": "mg",      "timing": "with_meal", "category": "supplement"},
    "Zinc Picolinate":       {"dose": 30,   "unit": "mg",      "timing": "with_meal", "category": "mineral"},
    "Basic B Complex":       {"dose": 1,    "unit": "capsule", "timing": "with_meal", "category": "vitamin"},
    "Creatine":              {"dose": 5,    "unit": "g",       "timing": "with_meal", "category": "supplement"},
    "Lions Mane":            {"dose": 1000, "unit": "mg",      "timing": "with_meal", "category": "supplement"},
    "Green Tea Phytosome":   {"dose": 500,  "unit": "mg",      "timing": "with_meal", "category": "supplement"},
    "NAC":                   {"dose": 600,  "unit": "mg",      "timing": "with_meal", "category": "supplement"},
    "Cordyceps":             {"dose": 1000, "unit": "mg",      "timing": "with_meal", "category": "supplement"},
    "Inositol":              {"dose": 2000, "unit": "mg",      "timing": "with_meal", "category": "supplement"},
    "Protein Supplement":    {"dose": 25,   "unit": "g",       "timing": "with_meal", "category": "supplement"},
    # ── Evening batch (before bed — sleep stack) ──
    "Glycine":       {"dose": 3,    "unit": "g",  "timing": "before_bed", "category": "supplement"},
    "L-Threonate":   {"dose": 2000, "unit": "mg", "timing": "before_bed", "category": "supplement"},
    "Apigenin":      {"dose": 50,   "unit": "mg", "timing": "before_bed", "category": "supplement"},
    "Theanine":      {"dose": 200,  "unit": "mg", "timing": "before_bed", "category": "supplement"},
    "Reishi":        {"dose": 1000, "unit": "mg", "timing": "before_bed", "category": "supplement"},
}

# ── AWS clients ───────────────────────────────────────────────────────────────
secrets = boto3.client("secretsmanager", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def get_api_key():
    """Fetch Habitify API key from Secrets Manager."""
    resp = secrets.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    return secret.get("habitify_api_key") or secret.get("api_key")


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
        "schema_version": 1,
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


def bridge_supplements(item):
    """Extract checked supplement habits from a Habitify item and write to supplements partition."""
    habits = item.get("habits", {})
    date_str = item["date"]

    entries = []
    for habit_name, completed in habits.items():
        if int(completed) != 1:
            continue
        if habit_name not in SUPPLEMENT_MAP:
            continue
        meta = SUPPLEMENT_MAP[habit_name]
        entries.append({
            "name": habit_name,
            "dose": Decimal(str(meta["dose"])),
            "unit": meta["unit"],
            "timing": meta["timing"],
            "category": meta["category"],
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "source": "habitify_bridge",
        })

    if not entries:
        logger.info(f"Supplement bridge: no supplements checked for {date_str}")
        return 0

    table.put_item(Item={
        "pk": SUPPLEMENTS_PK,
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "supplements",
        "schema_version": 1,
        "supplements": entries,
        "bridge_source": "habitify",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"Supplement bridge: wrote {len(entries)} supplements for {date_str}")
    return len(entries)


def write_to_dynamo(item):
    """Write item to DynamoDB, then bridge supplements."""
    date_str = item.get("sk", "").replace("DATE#", "")
    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item
        _vr = _validate_item("habitify", item, date_str)
        if _vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping habitify DDB write for {date_str}: {_vr.errors}")
            return  # no s3_client in habitify — log only
        else:
            if _vr.warnings:
                logger.warning(f"[DATA-2] Validation warnings for habitify/{date_str}: {_vr.warnings}")
            table.put_item(Item=item)
    except ImportError:
        table.put_item(Item=item)
    logger.info(f"Wrote {item['sk']} — pct={item['completion_pct']}, "
                f"completed={item['total_completed']}/{item['total_possible']}"
                f"{', mood=' + str(item.get('mood', '')) if item.get('mood') else ''}")
    # Bridge supplements automatically
    try:
        bridge_supplements(item)
    except Exception as e:
        logger.error(f"Supplement bridge failed for {item.get('date')}: {e}")


# ── Gap detection (v2.0) ──────────────────────────────────────────────────────
def find_missing_dates(lookback_days=LOOKBACK_DAYS):
    """Check DynamoDB for missing Habitify records in the lookback window."""
    from boto3.dynamodb.conditions import Key
    today = datetime.now(timezone.utc).date()
    check_dates = set()
    for i in range(1, lookback_days + 1):
        check_dates.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))

    oldest = min(check_dates)
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(PK)
            & Key("sk").between(f"DATE#{oldest}", f"DATE#{today.strftime('%Y-%m-%d')}"),
        ProjectionExpression="sk",
    )
    existing = {item["sk"][5:] for item in resp.get("Items", [])}
    missing = sorted(check_dates - existing)
    if missing:
        print(f"[GAP-FILL] Found {len(missing)} missing dates in last {lookback_days} days: {missing}")
    else:
        print(f"[GAP-FILL] No gaps in last {lookback_days} days")
    return missing


def lambda_handler(event, context):
    """
    Lambda entry point.

    Event formats:
      {}                                → gap-aware lookback (default for 6:15am schedule)
      {"date": "YYYY-MM-DD"}            → fetch specific date
      {"start": "...", "end": "..."}    → backfill date range
    """
    import time as _time
    logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1

    api_key = get_api_key()
    area_map = fetch_areas(api_key)
    logger.info(f"Fetched {len(area_map)} areas: {list(area_map.values())}")

    # ── Mode 1: Explicit date range backfill ──
    if "start" in event and "end" in event:
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

    # ── Mode 2: Explicit single date ──
    if "date" in event:
        target_date = event["date"]
        print(f"Habitify ingestion — explicit date={target_date}")
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
                }),
            }
        return {"statusCode": 200, "body": json.dumps({"date": target_date, "message": "No data"})}

    # ── Mode 3: Scheduled run — gap-aware lookback ──
    print(f"[GAP-FILL] Habitify gap-aware lookback ({LOOKBACK_DAYS} days)")
    missing_dates = find_missing_dates()

    if not missing_dates:
        return {"statusCode": 200, "body": json.dumps({"message": "No gaps to fill", "lookback_days": LOOKBACK_DAYS})}

    results = {}
    for i, date_str in enumerate(missing_dates):
        print(f"[GAP-FILL] Ingesting {date_str} ({i+1}/{len(missing_dates)})")
        try:
            item = process_day(api_key, area_map, date_str)
            if item:
                write_to_dynamo(item)
                results[date_str] = float(item["completion_pct"])
            else:
                results[date_str] = "no data"
        except Exception as e:
            print(f"[GAP-FILL] ERROR on {date_str}: {e}")
            results[date_str] = f"error: {e}"
        if i < len(missing_dates) - 1:
            _time.sleep(0.5)  # Gentle pacing

    filled = sum(1 for v in results.values() if isinstance(v, float))
    print(f"[GAP-FILL] Complete: {filled}/{len(missing_dates)} days filled")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "mode": "gap_fill",
            "lookback_days": LOOKBACK_DAYS,
            "gaps_found": len(missing_dates),
            "gaps_filled": filled,
            "details": results,
        }, default=str),
    }

