"""
habitify_lambda.py — Habitify ingestion via SIMP-2 framework (P4.1, 2026-05-17).

Migrated from the standalone pattern to lambdas/ingestion_framework.py.
2nd of 13 ingestion Lambdas (Todoist was 1st).

Source-specific concerns:
  - Multiple API calls per day: areas (static config), journal (habits), moods
  - Aggregation into P40 groups + per-group + overall completion %
  - **Today refreshed on every hourly run** — habits checked throughout the day;
    framework's new refresh_today=True flag (P4.1, 2026-05-17) handles this.
  - **Supplement bridge** — checked supplement habits get extracted into a
    separate `USER#matthew#SOURCE#supplements` partition. Framework's
    post_store_fn callback is the right hook for this.

DDB shape (TD-11 Phase 1, 2026-05-29 — backward-compatible producer):
  pk: USER#matthew#SOURCE#habitify
  sk: DATE#YYYY-MM-DD
  habits: {name: 0/1}                — UNCHANGED, legacy readers still work
  habit_statuses: {name: {...}}      — NEW: per-habit structured status
  by_group, total_*, completion_pct, mood — unchanged

`habit_statuses[name]` carries:
  status           one of completed | pending | failed | skipped (TD-11 enum)
  current_value    Decimal — from Habitify progress.current_value
  target_value     Decimal — from Habitify progress.target_value
  periodicity      "daily" | "weekly" | "monthly" — for aggregate habits
  scheduled_today  bool — always True today (registry is all RRULE=DAILY per audit)
  completed_at     iso8601 string OR null

The "pending" state (today's in_progress, deadline not yet passed) is the
phantom-failed bug fix — scoring engine consumers can stop treating it as 0/miss.
Consumer-side read changes are TD-11 Phase 2 (planned, not yet shipped).
"""

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("habitify")
except ImportError:
    logger = logging.getLogger("habitify")
    logger.setLevel(logging.INFO)

from ingestion_framework import IngestionConfig, run_ingestion

SECRET_NAME = os.environ.get("HABITIFY_SECRET_NAME", "life-platform/habitify")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
BASE_URL = "https://api.habitify.me"
MOOD_LABELS = {1: "Terrible", 2: "Bad", 3: "Okay", 4: "Good", 5: "Excellent"}
P40_GROUPS = ["Data", "Discipline", "Growth", "Hygiene", "Nutrition", "Performance", "Recovery", "Supplements", "Wellbeing"]

# AWS clients used directly by the supplement bridge (post-store hook needs DDB
# access independent of the framework's table reference).
_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_table = _dynamodb.Table(os.environ.get("TABLE_NAME", "life-platform"))
_SUPPLEMENTS_PK = f"USER#{USER_ID}#SOURCE#supplements"


# ── Supplement bridge mapping (unchanged) ─────────────────────────────────────

SUPPLEMENT_MAP = {
    # ── Morning batch (fasted) ──
    "Probiotics": {"dose": 1, "unit": "capsule", "timing": "morning", "category": "supplement"},
    "L Glutamine": {"dose": 5, "unit": "g", "timing": "morning", "category": "supplement"},
    "Collagen": {"dose": 10, "unit": "g", "timing": "morning", "category": "supplement"},
    "Electrolytes": {"dose": 1, "unit": "packet", "timing": "morning", "category": "supplement"},
    # ── Afternoon batch (with food) ──
    "Multivitamin": {"dose": 1, "unit": "capsule", "timing": "with_meal", "category": "vitamin"},
    "Vitamin D": {"dose": 5000, "unit": "IU", "timing": "with_meal", "category": "vitamin"},
    "Omega 3": {"dose": 2000, "unit": "mg", "timing": "with_meal", "category": "supplement"},
    "Zinc Picolinate": {"dose": 30, "unit": "mg", "timing": "with_meal", "category": "mineral"},
    "Basic B Complex": {"dose": 1, "unit": "capsule", "timing": "with_meal", "category": "vitamin"},
    "Creatine": {"dose": 5, "unit": "g", "timing": "with_meal", "category": "supplement"},
    "Lions Mane": {"dose": 1000, "unit": "mg", "timing": "with_meal", "category": "supplement"},
    "Green Tea Phytosome": {"dose": 500, "unit": "mg", "timing": "with_meal", "category": "supplement"},
    "NAC": {"dose": 600, "unit": "mg", "timing": "with_meal", "category": "supplement"},
    "Cordyceps": {"dose": 1000, "unit": "mg", "timing": "with_meal", "category": "supplement"},
    "Inositol": {"dose": 2000, "unit": "mg", "timing": "with_meal", "category": "supplement"},
    "Protein Supplement": {"dose": 25, "unit": "g", "timing": "with_meal", "category": "supplement"},
    # ── Evening batch (before bed — sleep stack) ──
    "Glycine": {"dose": 3, "unit": "g", "timing": "before_bed", "category": "supplement"},
    "L-Threonate": {"dose": 2000, "unit": "mg", "timing": "before_bed", "category": "supplement"},
    "Apigenin": {"dose": 50, "unit": "mg", "timing": "before_bed", "category": "supplement"},
    "Theanine": {"dose": 200, "unit": "mg", "timing": "before_bed", "category": "supplement"},
    "Reishi": {"dose": 1000, "unit": "mg", "timing": "before_bed", "category": "supplement"},
}


# ── Habitify API helpers ──────────────────────────────────────────────────────


def api_get(endpoint, api_key, params=None):
    """GET request to Habitify API. Returns parsed JSON `data` field.
    Retries via http_retry (P3.5) on 429/5xx."""
    url = f"{BASE_URL}{endpoint}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": api_key, "User-Agent": "LifePlatform/1.0"})
    try:
        from http_retry import urlopen_with_retry

        with urlopen_with_retry(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            if not body.get("status"):
                raise Exception(f"API error: {body.get('message', 'Unknown')}")
            return body.get("data", [])
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error("Habitify API %s on %s: %s", e.code, endpoint, error_body)
        raise


def fetch_areas(api_key):
    """{area_id: area_name} map. Used to bucket habits into P40 groups."""
    areas = api_get("/areas", api_key)
    return {a["id"]: a["name"] for a in areas}


def fetch_journal(api_key, target_date):
    """Habits + status for a date."""
    date_str = f"{target_date}T00:00:00+00:00"
    return api_get("/journal", api_key, {"target_date": date_str})


def fetch_moods(api_key, target_date):
    """Mood entries for a date. Non-fatal on error."""
    date_str = f"{target_date}T00:00:00+00:00"
    try:
        return api_get("/moods", api_key, {"target_date": date_str})
    except Exception as e:
        logger.warning("Moods fetch failed (non-fatal): %s", e)
        return []


# ── SIMP-2 framework callbacks ────────────────────────────────────────────────


def authenticate(secret_data: dict) -> dict:
    """Habitify uses a long-lived API key. No OAuth refresh."""
    key = secret_data.get("habitify_api_key") or secret_data.get("api_key")
    if not key:
        raise RuntimeError("Habitify secret missing 'habitify_api_key'/'api_key' field")
    return {"api_key": key}


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Fetch journal + moods for one day. Areas fetched per-invocation (rare
    that they change between days within a single run; could cache further)."""
    api_key = credentials["api_key"]
    area_map = fetch_areas(api_key)
    journal = fetch_journal(api_key, date_str)
    if not journal:
        logger.info("No journal data for %s", date_str)
        return None
    moods = fetch_moods(api_key, date_str)
    return {
        "date": date_str,
        "area_map": area_map,
        "journal": journal,
        "moods": moods,
    }


def transform(raw: dict, date_str: str) -> list[dict]:
    """Build the chronicling-compatible habit record (single per day)."""
    if not raw:
        return []
    area_map = raw["area_map"]
    journal = raw["journal"]
    moods = raw["moods"]

    habits = {}
    habit_statuses = {}  # TD-11 Phase 1: structured per-habit state alongside binary
    group_habits_done = {}
    group_habits_possible = {}
    skipped_count = 0

    # `date_str` is the date we're ingesting for (UTC-anchored). We compare it
    # to today (UTC) to disambiguate Habitify's `in_progress` between "pending"
    # (today's deadline hasn't passed) and "failed" (past day, never resolved).
    # End-of-UTC-day is Habitify's source-of-truth flip point per the TD-11 audit.
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for entry in journal:
        if entry.get("is_archived"):
            continue
        name = entry.get("name", "Unknown")
        status = entry.get("status", "none")
        if isinstance(status, dict):
            status = status.get("status", "none")
        is_completed = status == "completed"
        is_skipped = status == "skipped"
        habits[name] = Decimal("1") if is_completed else Decimal("0")
        if is_skipped:
            skipped_count += 1

        # TD-11 Phase 1: resolve API status → TD-11 enum.
        if status == "completed":
            resolved = "completed"
        elif status == "skipped":
            resolved = "skipped"
        elif status == "failed":
            resolved = "failed"
        elif status == "in_progress":
            # in_progress on today = pending (correct). On a past day = failed
            # (Habitify normally flips this at end-of-UTC-day; carryover is rare
            # but the audit found 1–2 per day, so handle it).
            resolved = "pending" if date_str >= today_utc else "failed"
        else:
            resolved = status or "unknown"

        progress = entry.get("progress") or {}
        habit_statuses[name] = {
            "status": resolved,
            "current_value": Decimal(str(progress.get("current_value", 0))),
            "target_value": Decimal(str(progress.get("target_value", 1))),
            "periodicity": progress.get("periodicity", "daily"),
            "scheduled_today": True,  # All current habits are RRULE=DAILY per audit
        }
        if is_completed:
            # Habitify doesn't expose a per-completion timestamp on the journal
            # endpoint observed in the audit; record the ingestion observation time.
            habit_statuses[name]["completed_at"] = datetime.now(timezone.utc).isoformat()

        area = entry.get("area")
        group = area_map.get(area["id"]) if area and area.get("id") else None
        # Persist the resolved group per-habit so read-only surfaces (the public
        # habits page) can render the registry grouped without re-deriving it.
        habit_statuses[name]["group"] = group or "Other"
        if group and group in P40_GROUPS:
            group_habits_possible.setdefault(group, []).append(name)
            if is_completed:
                group_habits_done.setdefault(group, []).append(name)

    by_group = {}
    for group in P40_GROUPS:
        possible_list = group_habits_possible.get(group, [])
        done_list = group_habits_done.get(group, [])
        if possible_list:
            by_group[group] = {
                "completed": len(done_list),
                "possible": len(possible_list),
                "pct": Decimal(str(round(len(done_list) / len(possible_list), 4))),
                "habits_done": done_list,
            }

    total_possible = sum(len(v) for v in group_habits_possible.values())
    total_completed = sum(len(v) for v in group_habits_done.values())

    # TD-11 Phase 2: count habits still pending (today, deadline not yet passed).
    # Excluding these from the denominator is the phantom-fail fix — mid-day
    # `completion_pct` was reading near-zero because Habitify's in_progress was
    # being treated as failure. For past days `pending_count` is always 0, so
    # the math is identical for historical records.
    pending_count = sum(1 for hs in habit_statuses.values() if hs["status"] == "pending")
    resolved_possible = max(total_possible - pending_count, 0)
    completion_pct = Decimal(str(round(total_completed / resolved_possible, 4))) if resolved_possible > 0 else Decimal("0")
    # Legacy completion_pct kept under a clearly-named slot in case any reader
    # wants the strict "pending counts as miss" interpretation for comparison.
    completion_pct_strict = Decimal(str(round(total_completed / total_possible, 4))) if total_possible > 0 else Decimal("0")

    record = {
        "source": "habitify",
        "date": date_str,
        "habits": habits,
        "habit_statuses": habit_statuses,  # TD-11 Phase 1 — structured status alongside binary
        "by_group": by_group,
        "total_completed": total_completed,
        "total_possible": total_possible,
        "pending_count": pending_count,  # TD-11 Phase 2
        "completion_pct": completion_pct,  # pending-aware (the bug fix)
        "completion_pct_strict": completion_pct_strict,  # legacy interpretation, for comparison
        "skipped_count": skipped_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if moods:
        latest = moods[-1]
        mood_value = latest.get("value")
        if mood_value is not None:
            record["mood"] = mood_value
            record["mood_label"] = MOOD_LABELS.get(mood_value, "Unknown")

    return [record]


def supplement_bridge(items: list[dict], date_str: str) -> None:
    """Post-store hook: extract supplement habit completions → supplements partition.

    Framework calls this AFTER successful DDB write of the main habit record.
    Failures here are logged but never raised — the bridge is auxiliary; if it
    breaks, the primary habitify record still got written.
    """
    if not items:
        return
    item = items[0]
    habits = item.get("habits", {})
    entries = []
    for habit_name, completed in habits.items():
        if int(completed) != 1:
            continue
        if habit_name not in SUPPLEMENT_MAP:
            continue
        meta = SUPPLEMENT_MAP[habit_name]
        entries.append(
            {
                "name": habit_name,
                "dose": Decimal(str(meta["dose"])),
                "unit": meta["unit"],
                "timing": meta["timing"],
                "category": meta["category"],
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "source": "habitify_bridge",
            }
        )

    if not entries:
        logger.info("Supplement bridge: no supplements checked for %s", date_str)
        return

    try:
        # #480/E-5: MERGE, don't clobber. MCP log_supplement appends manual
        # entries to the same key; the old full put_item destroyed any same-day
        # manual log on the next hourly bridge run. The bridge owns only its own
        # entries (source == habitify_bridge) — everything else is preserved.
        manual_entries = []
        try:
            existing = _table.get_item(Key={"pk": _SUPPLEMENTS_PK, "sk": f"DATE#{date_str}"}).get("Item") or {}
            manual_entries = [e for e in existing.get("supplements", []) if isinstance(e, dict) and e.get("source") != "habitify_bridge"]
        except Exception as ge:
            logger.warning("Supplement bridge: read-before-merge failed (%s) — writing bridge entries only", ge)
        _table.put_item(
            Item={
                "pk": _SUPPLEMENTS_PK,
                "sk": f"DATE#{date_str}",
                "date": date_str,
                "source": "supplements",
                "schema_version": 1,
                "supplements": manual_entries + entries,
                "bridge_source": "habitify",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info(
            "Supplement bridge: wrote %d bridge + %d preserved manual supplements for %s", len(entries), len(manual_entries), date_str
        )
    except Exception as e:
        logger.error("Supplement bridge write failed for %s: %s", date_str, e)


# ── Framework config ──────────────────────────────────────────────────────────

_config = IngestionConfig(
    source_name="habitify",
    secret_id=SECRET_NAME,
    s3_archive_prefix="raw/matthew/habitify",
    schema_version=2,  # TD-11 Phase 1: added habit_statuses alongside habits
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
    enable_item_size_guard=True,
    refresh_today=True,  # Habits update throughout day → re-write today every run
    # #477/E-2: the last write of UTC-day D is the 23:05 UTC run, while checks can
    # still be 'pending' — without a post-midnight rewrite a 48% day froze as 100%
    # forever (pending is excluded from the pct denominator) and late-evening
    # checks never landed. One trailing-day refresh finalizes yesterday every run.
    refresh_trailing_days=1,
)


def lambda_handler(event: dict, context) -> dict:
    """SIMP-2 entry point. Same event shapes as Todoist:
    {}                                 — gap-aware backfill (default, includes today)
    {"date_override": "today"}         — force today's data only
    {"date_override": "2026-05-15"}    — single explicit date
    {"healthcheck": true}              — boot check, returns 200/"ok"
    """
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context, post_store_fn=supplement_bridge)
    except Exception as e:
        logger.error("habitify ingestion failed: %s", e, exc_info=True)
        raise
