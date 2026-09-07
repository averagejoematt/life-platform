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

ATTRIBUTION (#3666, 2026-09-06) — THE LOG'S `created_date`, READ IN PACIFIC
---------------------------------------------------------------------------
`GET /journal?target_date=D` buckets by the **UTC date of the tick**, and this
Lambda files the answer under a **Pacific** `DATE#` key. Those are different
days for the 7-8 evening PT hours that are already tomorrow in UTC, so ONE
Pacific day was split across TWO `DATE#` rows at 17:00 PT and neither was ever
right. Measured 2026-09-06: `target_date=2026-09-06` returned 38 failed / 23
in_progress / **0 completed** while `target_date=2026-09-07` returned the
**15 completions the owner ticked at 19:11-19:13 PT on Sep 6**. The stored
record for `DATE#2026-09-06` therefore read 0 completed on a 15-habit day.

The `+00:00` offset in the request is IGNORED by the vendor — `...T00:00:00+00:00`
and `...T00:00:00-07:00` return byte-identical payloads. Only the date part is read.

The attribution key is `GET /logs/{habit_id}` -> `created_date`, converted to the
Pacific calendar day. It is correct in BOTH real cases, verified on the wire:

  same-day evening tick   "2026-09-07T02:11:22.363Z" -> Pacific 2026-09-06  (19:11:22 PT)
  back-dated two days     "2026-09-04T07:00:00.000Z" -> Pacific 2026-09-04  (00:00:00 PDT)

Habitify anchors a BACK-DATED completion at 00:00 *local* of the day it was
marked for (exact midnight, zero sub-second, against millisecond precision on a
real tap) — which also proves the account timezone is America/Los_Angeles and the
UTC bucketing is a quirk of `/journal` alone. So a next-day catch-up needs no
policy: `created_date` already carries the intent.

`progress.reference_date` IS NOT INTENT AND IS DELIBERATELY UNUSED. It merely
echoes whatever `target_date` was queried — the same monthly Sauna habit returns
`reference_date` 09-04, 09-05, 09-06 and 09-07 for the four respective queries.
Do not reach for it. `tests/test_habitify_pacific_attribution_3666.py` asserts it
stays unread.

The journal is still fetched, for the REGISTRY (habit names, areas, goal/periodicity,
archived flag) and for the two statuses that have no log channel — `skipped` and
`failed`. Its per-date `completed` is not per-day truth: a non-daily habit reports
`completed` on every date inside its period (Sauna, `periodicity: monthly`).

THREE STATES, NOT TWO (#3666's other half)
------------------------------------------
Habitify reports a MISS (`failed`) separately from an UNRESOLVED habit (`in_progress`).
The retired line collapsed them, and that loss was the worse of the two: a mis-dated
write can be re-derived from the vendor later, but a destroyed distinction cannot be
recovered from the stored row at all — and a reported lapse is exactly the behavioural
signal ADR-104 exists to protect. So `failed` passes through as `failed` (including on an
open day — it is a statement about the day, not a deadline artefact), `pending` is
reserved for `in_progress` and survives the whole Pacific day, and where this Lambda has
to resolve an unfinished habit at day close it labels that inference in `miss_source`
(`vendor` | `platform`) instead of hiding it inside the same word.

THE SECOND PARTITION THIS RECORD FEEDS
--------------------------------------
`supplement_bridge` (the post-store hook) writes `USER#matthew#SOURCE#supplements` from
THIS record's completions and nothing else. A day stored as 0 completed therefore
produces an empty supplement day with no error anywhere — on 2026-09-06 the owner took
and ticked Collagen, Creatine, Electrolytes and L Glutamine and the bridge wrote nothing.
Roughly twenty other modules read this partition (see the enumeration in
`tests/test_habitify_pacific_attribution_3666.py`); all of them read `habits` /
`habit_statuses` / `completion_pct`, so all of them are fixed by fixing the record, and
none of them had a check that would have noticed. `operational/habit_cross_source_qa.py`
is that missing check.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

import boto3

try:
    from common.platform_logger import get_logger

    logger = get_logger("habitify")
except ImportError:
    logger = logging.getLogger("habitify")
    logger.setLevel(logging.INFO)

from common.pacific_time import pacific_date_of, pacific_today

from ingestion.ingestion_framework import IngestionConfig, run_ingestion

# #422: bounded, verbatim clip of a habit note (shared conventions module, bundled #781).
try:
    from experiment.habit_causality import clip_note
except ImportError:  # pragma: no cover — the bundle always ships lambdas/ at root
    if not TYPE_CHECKING:  # mypy sees ONE signature (the import); runtime unchanged (#1656)

        def clip_note(text, _max=500):
            s = (text or "").strip()
            return s[:_max].rstrip() + "…" if len(s) > _max else s


SECRET_NAME = os.environ.get("HABITIFY_SECRET_NAME", "life-platform/habitify")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
BASE_URL = "https://api.habitify.me"

# #422 EVR-01/02 — Habitify is the PRIMARY habit-causality capture channel: notes attached
# to a habit at check-off / skip time in the app become driver context (on a done day) or
# the "why missed" reason (on a skipped/failed day). Fetching notes is one extra GET per
# tracked habit per ingested day; toggleable without a deploy if it ever pressures the API.
FETCH_NOTES = os.environ.get("HABITIFY_FETCH_NOTES", "1").strip().lower() not in ("0", "false", "no", "")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))
NOTES_MAX_PER_HABIT = 5
MOOD_LABELS = {1: "Terrible", 2: "Bad", 3: "Okay", 4: "Good", 5: "Excellent"}

# #3666: the group registry is DERIVED from the live `/areas` response, not hand-stated.
# P40_GROUPS is the 2026-05 area list and is now a FALLBACK only, used when `/areas`
# comes back empty or unusable. It had silently drifted: the owner reorganised Habitify
# into `Core` / `Optimize` / `Vice`, none of which is in this list, so `by_group` was
# empty and `total_possible` was **0 for every stored day** — which pins `completion_pct`
# at 0 no matter how the completions are attributed, and makes `ai_context._habit_block`
# (gated on `total_possible > 0`) hand every narrative surface an empty habit context.
# A registry that a rename can silently empty is exactly the shape the charter's
# derivation guard exists to kill.
P40_GROUPS = ["Data", "Discipline", "Growth", "Hygiene", "Nutrition", "Performance", "Recovery", "Supplements", "Wellbeing"]

# GET /logs/{habit_id} is one request per habit per INVOCATION (memoised across the dates
# a single run ingests — see `_LOGS_CACHE`). The window is padded either side of the
# ingest lookback so a back-dated tick inside the window is always visible.
LOGS_WINDOW_PAD_DAYS = 2

# Statuses that record a decision the owner actually made. Once one is stored for a
# Pacific day, a later run of the same day may never replace it with a non-terminal
# status (#3666's upgrade-only guard — the Lambda re-writes every day 24x/day).
TERMINAL_STATUSES = ("completed", "skipped")

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
        from common.http_retry import urlopen_with_retry

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
    """The habit REGISTRY for a date (names, areas, goal/periodicity, archived flag).

    #3666: this endpoint's per-date `status` is NOT the attribution key. It buckets by
    the UTC date of the tick while our `DATE#` keys are Pacific days, and it reports a
    non-daily habit `completed` on every date inside its period. Completions come from
    `fetch_logs` + `created_date`; the journal supplies the registry and `skipped`.

    The `+00:00` suffix is decoration — the vendor reads only the date part and returns
    a byte-identical payload for `-07:00`. Kept for wire compatibility, not meaning.
    """
    date_str = f"{target_date}T00:00:00+00:00"
    return api_get("/journal", api_key, {"target_date": date_str})


def fetch_logs(api_key, habit_id, window_from, window_to):
    """#3666: raw completion logs for one habit over a UTC instant window.

    Wire shape (measured 2026-09-06, `GET /logs/{habit_id}?from=&to=`)::

        {"id": "-P0tcawv9ZLsXVAg6fXE", "value": 1,
         "created_date": "2026-09-07T02:11:22.363Z",
         "unit_type": "rep", "habit_id": "61252250-..."}

    `created_date` is the attribution key: a real tap carries the tap instant to the
    millisecond; a back-dated completion carries 00:00:00.000 **local** of the day it was
    marked for. `pacific_date_of` recovers the intended Pacific day in both cases.

    Non-fatal by contract, and the fail-soft is VISIBLE rather than silent: a habit whose
    logs could not be fetched is absent from the returned map, `transform` falls back to
    the journal status for that habit alone, and the stored record's `attribution` field
    says so. Losing one habit's precision beats losing the day's ingest.
    """
    params = {"from": window_from, "to": window_to}
    return api_get(f"/logs/{habit_id}", api_key, params)


def logs_window(target_date, today_pt, lookback_days):
    """UTC ISO bounds wide enough to contain every tick the run could attribute.

    Two dates, not one, and the second is what makes a backfill work. A normal run's
    targets all sit inside `[today - lookback, today]`, so the window is identical for
    every date and the per-habit GET is memoised across the whole invocation
    (`_LOGS_CACHE`) instead of repeating per date. A `{"date_override": "2026-08-25"}`
    backfill invoke targets a date OUTSIDE that span — and a window anchored on today
    alone would return no logs for it, so every habit would read `failed` and the
    backfill would confidently rewrite the day as a total miss. The window therefore
    stretches to cover the target as well; it is still constant within one invocation.

    LOGS_WINDOW_PAD_DAYS on each end covers the frame skew (a Pacific day's ticks can
    carry the next UTC date) plus a back-dated completion just outside the span.
    """
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    today = datetime.strptime(today_pt, "%Y-%m-%d").date()
    start = min(target, today - timedelta(days=lookback_days)) - timedelta(days=LOGS_WINDOW_PAD_DAYS)
    end = max(target, today) + timedelta(days=LOGS_WINDOW_PAD_DAYS)
    return f"{start.isoformat()}T00:00:00+00:00", f"{end.isoformat()}T00:00:00+00:00"


# Per-invocation memo for fetch_logs, keyed (habit_id, window). Cleared by
# lambda_handler before every run — a module-level dict survives a warm container and a
# stale hit would freeze a day's completions at whatever the previous run saw.
_LOGS_CACHE: dict[tuple, list] = {}


def reset_logs_cache() -> None:
    _LOGS_CACHE.clear()


def fetch_moods(api_key, target_date):
    """Mood entries for a date. Non-fatal on error."""
    date_str = f"{target_date}T00:00:00+00:00"
    try:
        return api_get("/moods", api_key, {"target_date": date_str})
    except Exception as e:
        logger.warning("Moods fetch failed (non-fatal): %s", e)
        return []


def fetch_notes(api_key, habit_id, target_date):
    """#422: per-habit notes for one date (GET /notes/{habit_id}?from=...&to=...).

    #950: the notes endpoint requires a from/to RANGE — it 412s on target_date
    ("Unable to find to, from. Expect to, from in query"), which silently killed
    this channel since ship (non-fatal contract swallowed every call). We send the
    target day's UTC bounds using the same ISO-8601 `+00:00` convention the
    journal/moods endpoints use.

    Non-fatal by contract — notes are the causality layer, never worth failing the whole
    habit ingest over. Returns ``[{"content": str, "created_at": str}]`` (verbatim, clipped),
    filtered to notes actually created on ``target_date`` so a note is never smeared across
    every day if the API returns a wider range than requested.
    """
    params = {
        "from": f"{target_date}T00:00:00+00:00",
        "to": f"{target_date}T23:59:59+00:00",
    }
    try:
        raw_notes = api_get(f"/notes/{habit_id}", api_key, params)
    except Exception as e:
        logger.warning("Notes fetch failed for habit %s on %s (non-fatal): %s", habit_id, target_date, e)
        return []
    out = []
    for n in raw_notes or []:
        if not isinstance(n, dict):
            continue
        content = clip_note(n.get("content") or n.get("note") or "")
        if not content:
            continue
        created = str(n.get("created_date") or n.get("created_at") or "")
        if created and created[:10] != target_date:
            continue
        out.append({"content": content, "created_at": created})
        if len(out) >= NOTES_MAX_PER_HABIT:
            break
    return out


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

    # #422: per-habit notes → causality layer. One GET per tracked habit for this date;
    # each is non-fatal, so a notes hiccup never blocks the completion record.
    notes_by_name = {}
    if FETCH_NOTES:
        for entry in journal:
            if entry.get("is_archived"):
                continue
            habit_id = entry.get("id")
            if not habit_id:
                continue
            notes = fetch_notes(api_key, habit_id, date_str)
            if notes:
                notes_by_name[entry.get("name", "Unknown")] = notes

    # #3666: the completion logs — THE attribution channel. One GET per habit per
    # invocation (memoised on the window, which is anchored on Pacific today, so the
    # second and subsequent dates of a run are free). A habit missing from this map had
    # its logs GET fail; `transform` degrades that habit alone to the journal status.
    window = logs_window(date_str, pacific_today(), LOOKBACK_DAYS)
    logs_by_name = {}
    for entry in journal:
        if entry.get("is_archived"):
            continue
        habit_id = entry.get("id")
        if not habit_id:
            continue
        cache_key = (habit_id,) + window
        if cache_key not in _LOGS_CACHE:
            try:
                _LOGS_CACHE[cache_key] = fetch_logs(api_key, habit_id, *window) or []
            except Exception as e:
                logger.warning("Logs fetch failed for habit %s (non-fatal, journal fallback): %s", habit_id, e)
                continue
        logs_by_name[entry.get("name", "Unknown")] = _LOGS_CACHE[cache_key]

    return {
        "date": date_str,
        "area_map": area_map,
        "journal": journal,
        "moods": moods,
        "notes": notes_by_name,
        "logs": logs_by_name,
    }


def _decimal(value, default="0"):
    """Best-effort Decimal — a malformed vendor number falls back, never raises."""
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return Decimal(default)


def _goal_facets(entry: dict, progress: dict) -> tuple[str, Decimal]:
    """(periodicity, target_value) preferring the habit's stable `goal` over `progress`.

    `goal` is the habit definition and does not move with the queried date; `progress`
    is the vendor's per-query aggregate. Falling back to `progress` keeps every
    pre-#3666 fixture (which carries only `progress`) reading exactly as before.
    """
    goal = entry.get("goal") or {}
    periodicity = goal.get("periodicity") or progress.get("periodicity") or "daily"
    raw_target = goal.get("value")
    if raw_target is None:
        raw_target = progress.get("target_value", 1)
    target = _decimal(raw_target, "1")
    return periodicity, (target if target > 0 else Decimal("1"))


def logs_on_pacific_day(logs, date_str: str) -> list[dict]:
    """#3666: the log entries whose `created_date` lands on Pacific day `date_str`.

    THE attribution rule, in one place. `pacific_date_of` is the platform's one ISO
    parser + the one Pacific frame (#1964) — never a private `fromisoformat` fork.
    """
    out = []
    for log in logs or []:
        if not isinstance(log, dict):
            continue
        if pacific_date_of(log.get("created_date")) == date_str:
            out.append(log)
    return out


def _aggregate(habit_statuses: dict, groups: set) -> dict:
    """Derive every roll-up field from `habit_statuses`, so the two can never disagree.

    Factored out of `transform` for #3666 because `upgrade_only_merge` also has to
    rebuild them after it restores a status the vendor forgot — an aggregate computed
    once at transform time and then left alone is how a merged record ends up reporting
    `total_completed: 0` next to a `habit_statuses` map full of completions.
    """
    habits: dict = {}
    group_done: dict[str, list[str]] = {}
    group_possible: dict[str, list[str]] = {}
    skipped_count = 0
    for name, hs in habit_statuses.items():
        status = hs.get("status")
        is_completed = status == "completed"
        habits[name] = Decimal("1") if is_completed else Decimal("0")
        if status == "skipped":
            skipped_count += 1
        group = hs.get("group") or "Other"
        if group in groups:
            group_possible.setdefault(group, []).append(name)
            if is_completed:
                group_done.setdefault(group, []).append(name)

    by_group = {}
    for group in sorted(group_possible):
        possible_list = group_possible[group]
        done_list = group_done.get(group, [])
        by_group[group] = {
            "completed": len(done_list),
            "possible": len(possible_list),
            "pct": Decimal(str(round(len(done_list) / len(possible_list), 4))),
            "habits_done": done_list,
        }

    total_possible = sum(len(v) for v in group_possible.values())
    total_completed = sum(len(v) for v in group_done.values())

    # TD-11 Phase 2: habits still open on a Pacific day that has not closed are excluded
    # from the denominator — counting them as misses is the phantom-fail bug. For a past
    # day `pending_count` is 0, so historical math is unchanged.
    pending_count = sum(1 for hs in habit_statuses.values() if hs.get("status") == "pending")
    # #3666: the owner-authored/platform-assumed split, surfaced at the top level so a
    # consumer never has to walk habit_statuses to tell a reported lapse from an artefact.
    failed_vendor_count = sum(1 for hs in habit_statuses.values() if hs.get("status") == "failed" and hs.get("miss_source") == "vendor")
    failed_platform_count = sum(1 for hs in habit_statuses.values() if hs.get("status") == "failed" and hs.get("miss_source") == "platform")
    resolved_possible = max(total_possible - pending_count, 0)
    completion_pct = Decimal(str(round(total_completed / resolved_possible, 4))) if resolved_possible > 0 else Decimal("0")
    # The strict "pending counts as a miss" reading, kept for comparison.
    completion_pct_strict = Decimal(str(round(total_completed / total_possible, 4))) if total_possible > 0 else Decimal("0")

    return {
        "habits": habits,
        "by_group": by_group,
        "total_completed": total_completed,
        "total_possible": total_possible,
        "pending_count": pending_count,
        "failed_vendor_count": failed_vendor_count,
        "failed_platform_count": failed_platform_count,
        "completion_pct": completion_pct,
        "completion_pct_strict": completion_pct_strict,
        "skipped_count": skipped_count,
    }


def transform(raw: dict, date_str: str) -> list[dict]:
    """Build the chronicling-compatible habit record (single per day).

    `date_str` is a PACIFIC calendar day — it becomes the `DATE#` key verbatim.
    """
    if not raw:
        return []
    area_map = raw["area_map"]
    journal = raw["journal"]
    moods = raw["moods"]
    notes_by_name = raw.get("notes") or {}  # #422: {habit_name: [{content, created_at}]}
    logs_by_name = raw.get("logs")  # #3666: {habit_name: [log, …]}; absent name = fetch failed
    if not isinstance(logs_by_name, dict):
        logs_by_name = {}

    # #3666: the group registry, DERIVED from the live /areas response. The hand-stated
    # P40_GROUPS list is the fallback for an empty/unusable /areas payload only.
    groups = {g for g in area_map.values() if isinstance(g, str) and g} or set(P40_GROUPS)

    habits_seen = []
    habit_statuses = {}  # TD-11 Phase 1: structured per-habit state alongside binary
    log_attributed = 0
    journal_fallback = 0

    # #3666: the comparison is PACIFIC-to-PACIFIC, and #2811's exemption on this site is
    # RETIRED rather than reworded. That exemption's reasoning was true about
    # the vendor and wrong about us: Habitify's `/journal` really does flip at end of the
    # UTC day, but `date_str` — the other side of the comparison — is a PACIFIC day, the
    # literal `DATE#` key this record is filed under. Comparing a Pacific day key against
    # a UTC "today" marked every still-open habit `failed` from 17:00 PT onward, which is
    # precisely when the owner ticks his evening habits. Both sides are now the Pacific
    # calendar day, which is the frame the key, the site, and the owner all use.
    today_pt = pacific_today()
    day_open = date_str >= today_pt

    for entry in journal:
        if entry.get("is_archived"):
            continue
        name = entry.get("name", "Unknown")
        status = entry.get("status", "none")
        if isinstance(status, dict):
            status = status.get("status", "none")

        progress = entry.get("progress") or {}
        periodicity, target_value = _goal_facets(entry, progress)

        # #3666: `progress.reference_date` is deliberately NOT read. It echoes whatever
        # `target_date` was queried (the monthly Sauna habit returns 09-04, 09-05, 09-06
        # and 09-07 for the four respective queries), so it carries no intent whatsoever.
        attributed = logs_on_pacific_day(logs_by_name[name], date_str) if name in logs_by_name else None
        logged_value = sum((_decimal(log.get("value")) for log in attributed), Decimal("0")) if attributed is not None else None

        # ── status resolution ────────────────────────────────────────────────────
        # THREE distinct states, and keeping them distinct is half of #3666.
        # Habitify reports a MISS (`failed` — the owner marked it missed in the app, or
        # Habitify resolved it at the end of its own day) separately from an UNRESOLVED
        # habit (`in_progress`). The retired line `"pending" if date_str >= today_utc else
        # "failed"` collapsed them: after it ran, a reported lapse and a timezone artefact
        # were byte-identical in the stored row. A mis-dated write can be re-derived from
        # the vendor later; a destroyed distinction cannot be recovered from the record at
        # all, and a reported lapse is exactly the behavioural signal ADR-104 exists to
        # protect. So: the vendor's `failed` passes through as `failed` — including while
        # the Pacific day is still open, because it is a statement about the day, not a
        # deadline artefact — `pending` is reserved for `in_progress` and survives the
        # whole Pacific day, and a platform-side resolution at day close says so in
        # `miss_source` rather than hiding inside the same label.
        miss_source = None
        if status == "skipped":
            # A skip is an owner decision with no log channel — the journal is its only source.
            resolved = "skipped"
        elif attributed is not None and periodicity == "daily":
            log_attributed += 1
            if logged_value >= target_value:
                resolved = "completed"
            elif status == "failed":
                resolved, miss_source = "failed", "vendor"
            elif day_open:
                resolved = "pending"
            else:
                resolved, miss_source = "failed", "platform"
        else:
            # Fallback: the vendor's own journal status. Taken when the logs GET failed
            # for this habit, or when the habit is a weekly/monthly aggregate whose
            # `completed` is a PERIOD judgement the vendor owns and we do not re-derive.
            # The pending/failed boundary is Pacific either way.
            if attributed is None:
                journal_fallback += 1
            if status == "completed":
                resolved = "completed"
            elif status == "failed":
                resolved, miss_source = "failed", "vendor"
            elif status == "in_progress":
                if day_open:
                    resolved = "pending"
                else:
                    resolved, miss_source = "failed", "platform"
            else:
                resolved = status or "unknown"

        current_value = (
            logged_value if (logged_value is not None and periodicity == "daily") else _decimal(progress.get("current_value", 0))
        )
        habit_statuses[name] = {
            "status": resolved,
            "current_value": current_value,
            "target_value": target_value,
            "periodicity": periodicity,
            "scheduled_today": True,  # All current habits are RRULE=DAILY per audit
        }
        if miss_source:
            # WHO said this was a miss.
            #   "vendor"   — Habitify's own `failed`. That covers BOTH the owner marking it
            #                missed in the app AND Habitify auto-resolving it at the end of
            #                its own UTC day; the API does not separate the two and this
            #                field does not pretend it can (ADR-104 — the honest label is
            #                the one the data supports).
            #   "platform" — nobody said anything: the habit was still `in_progress` when
            #                its PACIFIC day closed and THIS Lambda resolved it. That is an
            #                inference, and it is now labelled as one instead of being
            #                stamped `failed` indistinguishably from a reported lapse.
            habit_statuses[name]["miss_source"] = miss_source
        # The real tap instant, not the ingestion observation time: the latest log
        # attributed to THIS Pacific day. A back-dated completion therefore stamps
        # 00:00 local of the day it was marked for, which is the vendor's own anchor.
        if attributed:
            habit_statuses[name]["completed_at"] = max(str(log.get("created_date") or "") for log in attributed)
        elif attributed is None and resolved == "completed":
            # Journal-fallback path only (this habit's logs GET failed). With logs in hand
            # and none attributed to this day, there IS no completion instant for this day
            # and stamping the ingest time would invent one — that is how a non-daily
            # habit's period-level `completed` used to smear a fake timestamp across every
            # date in its period.
            habit_statuses[name]["completed_at"] = datetime.now(timezone.utc).isoformat()

        area = entry.get("area")
        group = area_map.get(area["id"]) if area and area.get("id") else None
        # Persist the resolved group per-habit so read-only surfaces (the public
        # habits page) can render the registry grouped without re-deriving it.
        habit_statuses[name]["group"] = group or "Other"

        # #422 EVR-01/02: attach the in-app note(s) verbatim. On a completed day these are
        # driver context (trigger/reward); on a skipped/failed day the "why missed" reason.
        # Stored raw — interpretation (the trigger:/reward: convention) is deterministic and
        # lives in habit_causality.parse_note on the read side (ADR-104, no inference here).
        note_entries = notes_by_name.get(name) or []
        if note_entries:
            habit_statuses[name]["notes"] = [ne["content"] for ne in note_entries]
            habit_statuses[name]["notes_at"] = [ne.get("created_at", "") for ne in note_entries]
            habit_statuses[name]["note_channel"] = "habitify_note"
        habits_seen.append(name)

    record = {
        "source": "habitify",
        "date": date_str,
        "habit_statuses": habit_statuses,  # TD-11 Phase 1 — structured status alongside binary
        # #3666: which channel decided this day's completions, stored so a degraded run is
        # visible in the record itself rather than only in a log line nobody reads.
        "attribution": ("logs" if journal_fallback == 0 and log_attributed else "journal_fallback" if not log_attributed else "mixed"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    record.update(_aggregate(habit_statuses, groups))

    if moods:
        latest = moods[-1]
        mood_value = latest.get("value")
        if mood_value is not None:
            record["mood"] = mood_value
            record["mood_label"] = MOOD_LABELS.get(mood_value, "Unknown")

    return [record]


def upgrade_only_merge(existing: dict, new: dict) -> dict:
    """#3666: re-ingest may only UPGRADE a Pacific day, never downgrade it.

    This Lambda rewrites today and yesterday on every one of its 24 daily runs, and each
    write is a full `put_item` REPLACE rebuilt from the API response alone. Two ways that
    loses real data, both live hazards rather than theory:

      1. **A stored completion disappears.** `completed`/`skipped` are decisions the owner
         made. A later run that cannot see them (a logs GET that failed, a habit renamed
         or archived upstream, a vendor blip) must not overwrite them with `failed`.
         Restored here, with the original `completed_at` instant.
      2. **`pending` is finalised early.** A 17:05 PT run writes `pending` for the evening
         habits; nothing may turn that into `failed` while the Pacific day is still open.
         Once the day HAS closed, `pending -> failed` is the correct, allowed resolution —
         that is the day ending, not data loss.

    Notes and mood are carried forward too: both fetches are non-fatal by contract, so an
    empty one on run N+1 means "not fetched", never "retracted".

    Every roll-up is recomputed from the merged statuses (`_aggregate`) — a restored
    completion that did not move `total_completed` would be a record disagreeing with
    itself. Never raises: the framework calls this inside a try/except that stores the
    un-merged item, but a merge that silently dropped the day would be worse than a red.
    """
    if not isinstance(existing, dict) or not isinstance(new, dict):
        return new
    prev_statuses = existing.get("habit_statuses") or {}
    next_statuses = new.get("habit_statuses") or {}
    if not isinstance(prev_statuses, dict) or not isinstance(next_statuses, dict):
        return new

    date_str = str(new.get("date") or existing.get("date") or "")
    day_open = bool(date_str) and date_str >= pacific_today()
    upgrades = []

    for name, prev in prev_statuses.items():
        if not isinstance(prev, dict):
            continue
        prev_status = prev.get("status")
        cur = next_statuses.get(name)
        if cur is None:
            # The habit vanished from the journal (archived/renamed upstream). Keep the
            # stored row when it recorded a decision; drop it otherwise.
            if prev_status in TERMINAL_STATUSES:
                next_statuses[name] = prev
                upgrades.append(f"{name}:restored-{prev_status}")
            continue
        if not isinstance(cur, dict):
            continue
        cur_status = cur.get("status")
        if prev_status in TERMINAL_STATUSES and cur_status not in TERMINAL_STATUSES:
            cur["status"] = prev_status
            if prev.get("completed_at"):
                cur["completed_at"] = prev["completed_at"]
            if _decimal(prev.get("current_value")) > _decimal(cur.get("current_value")):
                cur["current_value"] = _decimal(prev.get("current_value"))
            cur.pop("miss_source", None)  # it is no longer a miss
            upgrades.append(f"{name}:{cur_status}->{prev_status}")
        elif prev_status == "pending" and cur_status == "failed" and day_open and cur.get("miss_source") != "vendor":
            # An UNRESOLVED failure on an open day is a premature finalisation; an
            # owner-authored one is the owner telling us he missed it, and clamping that
            # back to `pending` would destroy the very distinction #3666 restored.
            cur["status"] = "pending"
            upgrades.append(f"{name}:failed->pending(day-open)")
        if prev.get("notes") and not cur.get("notes"):
            cur["notes"] = prev["notes"]
            cur["notes_at"] = prev.get("notes_at", [])
            cur["note_channel"] = prev.get("note_channel", "habitify_note")

    if "mood" in existing and "mood" not in new:
        new["mood"] = existing["mood"]
        if "mood_label" in existing:
            new["mood_label"] = existing["mood_label"]

    if not upgrades:
        return new

    new["habit_statuses"] = next_statuses
    groups = {hs.get("group") for hs in next_statuses.values() if isinstance(hs, dict)}
    groups = {g for g in groups if g and g != "Other"} or set(P40_GROUPS)
    new.update(_aggregate(next_statuses, groups))
    new["upgrade_only_merges"] = upgrades[:50]
    logger.info("[UPGRADE-ONLY] %s: kept %d stored status(es): %s", date_str, len(upgrades), ", ".join(upgrades[:10]))
    return new


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
    schema_version=3,  # #3666: completions attributed by log created_date → Pacific day
    enable_gap_detection=True,
    lookback_days=LOOKBACK_DAYS,
    enable_item_size_guard=True,
    refresh_today=True,  # Habits update throughout day → re-write today every run
    # #477/E-2: the last write of UTC-day D is the 23:05 UTC run, while checks can
    # still be 'pending' — without a post-midnight rewrite a 48% day froze as 100%
    # forever (pending is excluded from the pct denominator) and late-evening
    # checks never landed. One trailing-day refresh finalizes yesterday every run.
    refresh_trailing_days=1,
    # #3504 (PR #2877's own body called this fast-follow "not done here", and it was
    # never ticketed until the 2026-09-05 review found it): Habitify is in
    # freshness_checker_lambda.DAILY_SOURCES with behavioral=False, so a day with no
    # record is never a normal lapse — it is either a pipeline miss or a measured
    # vendor absence, and the interior-gap alarm (Maximum(InteriorGapCount) >= 1 over a
    # 14-day lookback) holds red until the day ages out of the window with no way to
    # self-clear. #2643's marker is what closes it honestly: on the LAST run that will
    # ever look at a date (the oldest day in the gap-fill window), a still-empty fetch
    # writes an explicit `absent: True` record instead of letting the hole vanish.
    # Eight Sleep has carried this since #2643; whoop and habitify are the two other
    # framework-based DAILY_SOURCES members and now do too —
    # tests/test_source_enumeration_drift.py asserts the SET, so a fourth one cannot
    # enter without it.
    record_gap_exhausted_absence=True,
    # #3666: every run is a full REPLACE of today AND yesterday. Without this, a stored
    # completion or an open `pending` could be downgraded by the next run an hour later.
    carry_forward_fn=upgrade_only_merge,
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
        # #3666: the logs memo is module-level and a warm container outlives the run —
        # a stale hit would freeze a day's completions at whatever the last run saw.
        reset_logs_cache()
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context, post_store_fn=supplement_bridge)
    except Exception as e:
        logger.error("habitify ingestion failed: %s", e, exc_info=True)
        raise
