"""lambdas/web/site_api_status.py — the platform-health panel (/api/status).

Split out of ``site_api_intelligence.py`` (#1654 — god-module breakup). One seam:
**is the machine healthy right now** — the active pipeline probe, per-source
freshness, the compute/email/AI component rollup, the cost block, and the single
traffic-light the site footer reads.

The routed handler entrypoints stay in the ``site_api_intelligence`` facade as
thin delegators; the logic lives here. Handlers receive the facade's ``globals()``
as ``_g`` and read the monkeypatched/injectable state (``table``,
``_budget_cost_block``) via ``_g["<name>"]``, so ``monkeypatch.setattr(intel,
"table", …)`` still reaches this code. This module does NOT import the facade —
no import cycle. Every other shared helper comes straight from
``site_api_common`` (identical binding semantics to the pre-split module).

The /api/status response cache lives HERE, not on the facade: ``status()`` writes
it under ``global`` and ``status_summary()`` reads it, so the two must share one
namespace. Nothing outside this module reads it.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from common import activity_publication as _activity_publication  # owner ruling 2026-11-03: private sources off the board
from common.macrofactor_fields import latest_day_condition, latest_sk_ceiling  # #5431: intake reads bounded at the Pacific today
from common.pacific_time import anchor_day_key  # #3913: a DATE# day key is aged in the calendar that NAMED it — never a hardcoded tz
from common.subscriber_cadence import cron_hour, cron_minute, required_weekday, sender, weekday_name  # #3619 (#3564 registry)
from ingestion.source_registry import (  # #3669 cadence, #3615 absence facets, #5930 the board's membership
    AVAILABILITY_PAUSED,
    DEFAULT_STALE_HOURS,
    SOURCE_REGISTRY,
    availability_facet,
    due_months,
)

from web.site_api_common import (
    DDB_REGION,
    PLATFORM_STATS,
    PT,
    STATUS_CACHE_TTL,
    USER_PREFIX,
    _ok,
    logger,
)

# ── #3669: due-date cadences for the "manual" (infrequent) data-source rows ───
# This dict used to be written inline inside the render loop as
# `DUE_MONTHS = {"labs": 6, "dexa": 12, …}` — a cadence living in the SERVING layer while
# `SOURCE_REGISTRY`, which every freshness, staleness and coach surface derives from, had
# no `labs` row at all. Two homes for one number, and nothing able to notice them
# disagreeing. `due_months()` is spliced in LAST so the registry always wins: a source
# that declares `cadence_months` owns its cadence outright, and the literals below are
# only the rows the registry does not hold yet — each a candidate for the same treatment
# (dexa's cadence was the named residual on #3669; it moved to the registry in #4639).
# `tests/test_source_registry_coverage_3669.py` asserts the two are the same number, in
# both directions: the panel's months AND the registry's derived `stale_hours`.
# "dexa" left this literal in #4639 — it is a registry source with `cadence_months` (3 since #5061) now, so due_months() carries it.
# "food_delivery" is 6 since #5006/#5108 (owner ruling 2026-10-23: a 6-monthly upload ritual). Its home is the charter's
# `nutrition.food_delivery.upload_every_months` (the reminder reads it there); tests/test_food_delivery_upload_ritual_5006.py
# holds this copy equal to it. Not a registry `cadence_months`: that would derive a 6-month stale_hours (see the registry row).
_DUE_MONTHS_UNREGISTERED = {"food_delivery": 6, "bp_readings": 3, "measurements": 2}
DUE_MONTHS = {**_DUE_MONTHS_UNREGISTERED, **due_months()}
DUE_MONTHS_DEFAULT = 6


# ── #3615 box 3 / #3516: ONE absence story, derived from the registry's facets ──
#
# Measured live on 2026-09-21, this panel rendered garmin as
#   "Pipeline may need attention — was flowing regularly but stopped 97d ago. Check auth/webhook."
# while /api/source_freshness rendered the SAME source as `status: paused` with the
# ADR-074 reason. Garmin is paused by decree and cannot report at all: there is no auth
# to check and no webhook to fix, and a reader who acts on that comment is chasing a
# fault that does not exist. #3516 already ruled on this for the coach inventory —
# `availability_facet()` is that ruling as a facet — and this is the same ruling applied
# to the health panel, so the DURATION (the panel's own relative last-sync) and the
# CAUSE (the registry's `method`/ADR text) are the same two things every narrating
# surface renders. Nothing is composed here beyond the sentence frame.
# SCOPE, stated because the narrower case was chosen deliberately: this rewrites the
# comment for a PAUSED source only. The registry also marks some sources LAGGING (a
# `stale_hours` override past the platform default), and this panel's activity-dependent
# heuristic will still say "Check auth/webhook" about a gap the registry expects — live
# on notion, 11d dark inside a 336h expectation. That case is a genuine disagreement
# between two honest rules (the panel's "an API poller writes daily" and the registry's
# per-source cadence) and resolving it is a product call, not a lane's: #3615's nightly
# gate reports it every night as a WARN naming the source, and it is the named residual.
# A pause is not that case: a paused source CANNOT report, at any duration, so there is
# no auth to check and no webhook to fix.
def _absence_comment(facet: dict, rel: str) -> str:
    """The comment a PAUSED source gets, built from ITS OWN registry facet."""
    low = str(rel or "").strip().lower()
    if low == LAST_SYNC_UNREADABLE:  # #5930: a failed read states neither a duration nor an absence
        duration = "Its records could not be read just now."
    elif low and low not in ("never", "not imported"):
        duration = f"Last record: {rel}."
    else:
        duration = "No record has ever arrived on this feed."
    return f"PAUSED in the source registry — {facet.get('reason') or 'intentionally off'}. {duration} A pause is a hole in the record, not a broken pipe."


def _status_row_is_public(row: tuple) -> bool:
    """A data-source row is published when its source is public AND the field it is tracked by (the
    tenth element, for a sub-stream of a shared partition) is public — common.activity_publication
    (owner rulings 2026-11-03/05; unclassified fails closed)."""
    if not _activity_publication.source_is_public(row[0]):
        return False
    field_check = row[9] if len(row) > 9 else None
    return field_check is None or _activity_publication.field_is_public(row[0], field_check)


# ── The data-source board: PRESENTATION copy over a registry-derived SET (#5930) ──
#
# (source_id, name, description, yellow_h, red_h, category, group, activity_dependent, source_app, field_check)
# name is the DATA type, the source app is separate. field_check: if set, _last_sync / the uptime bars
# count only records carrying that field (the sub-feeds of a shared partition like apple_health).
# category: "auto" (default), "manual" (blue — infrequent file imports), "onetime" (green — never
# changes), "archive" (blue — a FROZEN partition nothing writes any more; its age is not a fault).
#
# This table is the board's WORDING, not its membership. Which sources the board must show is
# `board_source_ids()` below, derived from the registry's facets: a registered source that is not
# paused, has a partition, is not a social channel and is public gets a row whether or not it is
# typed here — `_board_rows()` appends a registry-worded row for any it finds missing. Before #5930
# this list was the membership too, and it drifted: the live strength source `hevy` had no row while
# the frozen pre-Hevy `macrofactor_workouts` archive was typed as an "auto" feed and told readers to
# "Check auth/webhook" on a pipe that was retired on purpose. A row whose source is NOT a registry
# source must be a dispositioned `UNREGISTERED_PARTITIONS` entry rendered "onetime" or "archive"
# (tests/test_status_board_registry_5930.py holds both directions).
_DATA_SOURCES = [
    # ── API-Based (fully automated) ──
    (
        "whoop",
        "Recovery & Sleep Data",
        "HRV \u00b7 recovery score \u00b7 sleep staging",
        25,
        49,
        "auto",
        "API-Based",
        False,
        "Whoop",
        None,
    ),
    (
        "withings",
        "Weight Data",
        "Weight \u00b7 body composition \u00b7 blood pressure",
        25,
        49,
        "auto",
        "API-Based",
        True,
        "Withings",
        None,
    ),
    (
        "eightsleep",
        "Sleep Environment Data",
        "Sleep staging \u00b7 bed temperature \u00b7 HRV",
        25,
        49,
        "auto",
        "API-Based",
        False,
        "Eight Sleep",
        None,
    ),
    ("todoist", "To Do Task Data", "Tasks \u00b7 projects \u00b7 completion rate", 25, 49, "auto", "API-Based", True, "Todoist", None),
    (
        "weather",
        "Weather Data",
        "Daily temperature \u00b7 conditions \u00b7 humidity",
        25,
        49,
        "auto",
        "API-Based",
        False,
        "OpenWeather",
        None,
    ),
    (
        "garmin",
        "Activity Tracking (1 of 2)",
        "Walks \u00b7 runs \u00b7 GPS routes \u2014 delivered through Strava (direct feed retired, #4640)",
        25,
        49,
        "auto",
        "API-Based",
        True,
        "Garmin",
        None,
    ),
    (
        "strava",
        "Activity Tracking (2 of 2)",
        "Activities \u00b7 segments \u00b7 training load",
        25,
        49,
        "auto",
        "API-Based",
        True,
        "Strava",
        None,
    ),
    ("notion", "Journal Data", "Journal entries \u00b7 mood \u00b7 reflections", 25, 49, "auto", "API-Based", True, "Notion", None),
    # ── User-Driven (requires user to log/sync) ──
    ("habitify", "Habit Tracking Data", "Daily habits \u00b7 day grades", 25, 49, "auto", "User-Driven", True, "Habitify", None),
    (
        "macrofactor",
        "Nutrition Data",
        "Calories \u00b7 macros \u00b7 meal timing",
        25,
        49,
        "auto",
        "User-Driven",
        True,
        "MacroFactor via Dropbox",
        None,
    ),
    (
        "supplements",
        "Supplement Adherence",
        "Daily supplement tracking & compliance",
        25,
        49,
        "auto",
        "User-Driven",
        True,
        "Habitify",
        None,
    ),
    # #5930: the live strength source. Behavioral (a record exists only when he lifts), so a quiet
    # day is awaiting activity, not a fault — the same activity-dependent handling as the rows above.
    (
        "hevy",
        "Strength Training Data",
        "Strength sets · reps · load · rest times",
        25,
        49,
        "auto",
        "User-Driven",
        True,
        "Hevy",
        None,
    ),
    # State of Mind tracked via apple_health partition field check (som_avg_valence) in Periodic Uploads section
    # ── Periodic Uploads (file drops, webhooks, device sync) ──
    # #5930: a FROZEN archive (source_registry.UNREGISTERED_PARTITIONS — no writer since Hevy replaced it),
    # so "archive": it renders its age as history, never as a broken pipe to go and fix.
    (
        "macrofactor_workouts",
        "Exercise Log Archive",
        "Historical strength log (pre-Hevy) — live strength data is the Hevy row",
        48,
        168,
        "archive",
        "Periodic Uploads",
        True,
        "MacroFactor via Dropbox",
        None,
    ),
    (
        "apple_health",
        "CGM Glucose Data",
        "Continuous glucose monitor readings",
        25,
        49,
        "auto",
        "Periodic Uploads",
        True,
        "Dexcom Stelo via Health Exporter",
        "blood_glucose_avg",
    ),
    (
        "apple_health",
        "Water Intake Data",
        "Daily water consumption tracking",
        25,
        49,
        "auto",
        "Periodic Uploads",
        True,
        "Apple Health via Health Exporter",
        "water_intake_ml",
    ),
    (
        "apple_health",
        "Blood Pressure Data",
        "Systolic \u00b7 diastolic \u00b7 pulse",
        168,
        336,
        "manual",
        "Periodic Uploads",
        True,
        "Apple Health via Health Exporter",
        "blood_pressure_systolic",
    ),
    (
        "apple_health",
        "Breathwork Data",
        "Breathwork sessions logged as workouts",
        48,
        168,
        "auto",
        "Periodic Uploads",
        True,
        "Breathwrk via Apple Health",
        # #5930: was `mindful_minutes`, the Mindful Minutes row's field \u2014 two rows tracking one field.
        # `breathwork_minutes` is the HAE workouts aggregate (source_registry hae_datatypes "workouts").
        "breathwork_minutes",
    ),
    (
        "apple_health",
        "Stretching Data",
        "Flexibility sessions \u00b7 recovery",
        48,
        168,
        "auto",
        "Periodic Uploads",
        True,
        "Pliability via Health Exporter",
        "flexibility_minutes",
    ),
    (
        "apple_health",
        "Mindful Minutes Data",
        "Meditation & mindfulness sessions",
        48,
        168,
        "auto",
        "Periodic Uploads",
        True,
        "Apple Health via Health Exporter",
        "mindful_minutes",
    ),
    (
        "apple_health",
        "State of Mind Data (Health Export)",
        "How We Feel mood check-ins via Health Exporter",
        48,
        168,
        "auto",
        "Periodic Uploads",
        True,
        "Apple Health via Health Exporter",
        "som_avg_valence",
    ),
    (
        "apple_health",
        "Apple Health Import",
        "Steps \u00b7 activity \u00b7 walking metrics",
        25,
        49,
        "auto",
        "Periodic Uploads",
        True,
        "Health Auto Export",
        "steps",
    ),
    (
        "food_delivery",
        "Food Delivery Index",
        "6-monthly CSV upload \u00b7 delivery index 0-10",
        2160,
        2880,
        "manual",
        "Periodic Uploads",
        True,
        "CSV upload",
    ),
    (
        "measurements",
        "Body Tape Measurements",
        "Periodic body measurements \u00b7 waist-to-height ratio",
        1440,
        2880,
        "manual",
        "Periodic Uploads",
        True,
        "CSV upload (Partner)",
    ),
    # ── Lab & Clinical (infrequent) ──
    (
        "labs",
        "Blood Test Results",
        "Lab work \u00b7 biomarkers \u00b7 lipid panel",
        4320,
        8760,
        "manual",
        "Lab & Clinical",
        True,
        "Function Health",
    ),
    (
        "dexa",
        "Bone Density & Body Comp",
        "DEXA scan \u00b7 bone density \u00b7 lean mass",
        4320,
        8760,
        "manual",
        "Lab & Clinical",
        True,
        "Clinical (manual)",
    ),
    (
        "genome",
        "Genome Data",
        "Genetic variants \u00b7 risk scores \u00b7 SNPs",
        999999,
        999999,
        "onetime",
        "Lab & Clinical",
        False,
        "23andMe (one-time)",
    ),
]

#: The board group a registry-derived row lands in, from the registry's own `category` facet.
_GROUP_OF_REGISTRY_CATEGORY = {"Wearables": "API-Based", "Inputs": "API-Based", "Manual logs": "User-Driven", "Clinical": "Lab & Clinical"}


def board_source_ids(registry=None) -> set:
    """The registered sources the data-source board MUST show (#5930) — derived, never typed.

    A source qualifies when it is not `paused` (a paused source may keep a row — garmin and
    food_delivery do, narrated by `_absence_comment` — but is not owed one), has a DDB partition
    (`partition: False` is a transport pipe: there is nothing to age), is not a `social_channel`
    (inbound engagement channels have their own surfaces and no health-feed freshness), and is
    public under `common.activity_publication` (owner rulings 2026-11-03/05: an owner-only source's
    sync state is private activity, so it never newly appears here). `registry` is injectable so a
    test runs THIS rule over a planted row."""
    rows = SOURCE_REGISTRY if registry is None else registry
    return {
        k
        for k, v in rows.items()
        if not v.get("paused")
        and v.get("partition", True) is not False
        and not v.get("social_channel")
        and _activity_publication.source_is_public(k)
    }


def _registry_row(sid: str) -> tuple:
    """A board row worded from the registry alone, for a board source the presentation table lacks."""
    v = SOURCE_REGISTRY[sid]
    stale = v.get("stale_hours") or DEFAULT_STALE_HOURS
    category = "manual" if v.get("cadence_months") else "auto"
    group = _GROUP_OF_REGISTRY_CATEGORY.get(str(v.get("category")), "User-Driven")
    return (
        sid,
        str(v["label"]),
        str(v.get("desc") or ""),
        stale,
        2 * stale,
        category,
        group,
        bool(v.get("behavioral")),
        str(v["label"]),
        None,
    )


def _board_rows() -> list:
    """Every published board row: the presentation table, plus a registry-worded row for any
    `board_source_ids()` member it lacks, minus the private rows (`_status_row_is_public`)."""
    rows = list(_DATA_SOURCES)
    typed = {r[0] for r in rows}
    rows += [_registry_row(sid) for sid in sorted(board_source_ids() - typed)]
    return [r for r in rows if _status_row_is_public(r)]


def _component_id(sid: str, field_check) -> str:
    """#5527/#5930: ONE id per board row. A sub-feed of a shared partition is `<source>:<field>` — the
    seven apple_health rows used to all publish `apple_health`, so any consumer keyed on id kept one of
    them. The partition stays on the component as `source`, which is what a per-source reader keys on."""
    return f"{sid}:{field_check}" if field_check else sid


# ── #5930: the two freshness readers page to the END of what they asked for ───
#
# `_last_sync` made ONE query (Limit=200 plus a FilterExpression) and `_uptime_90d` one more. A
# DynamoDB page stops at Limit items OR 1 MB, whichever is first, and the FilterExpression runs
# after — so page 1 of a sub-feed read could be empty while the record sat on page 2. Measured
# read-only on 2026-11-14 against the apple_health partition: blood_glucose_avg's page 1 returned
# Count 0 / ScannedCount 26 (the 1 MB ceiling, recent rows are large) and its last record,
# DATE#2026-08-27, was on page 2; the board printed CGM, Breathwork and Mindful Minutes as "never".
# And every exception collapsed to None, which the board also rendered "never".
#
# Now: "never" is emitted only once the partition is EXHAUSTED (no LastEvaluatedKey); a read that
# raises, or that runs past the page cap, is LAST_SYNC_UNREADABLE and renders "unreadable".
# The cap: the largest partition the board reads (apple_health, 4,132 DATE# rows) exhausts in 13
# 1 MB pages / ~1.4 s / ~1,620 RCU, measured the same day for a field no row carries
# (breathwork_minutes); 40 pages is 3x that inside the site API's 30 s timeout.
LAST_SYNC_UNREADABLE = "unreadable"
_UNREADABLE_COMMENT = "Freshness unreadable \u2014 this feed's records could not be read just now (not a claim that nothing has arrived)"
_STATUS_MAX_PAGES = 40


def _is_day(last) -> bool:
    """True when `_last_sync` returned an actual day — not None ("never") and not LAST_SYNC_UNREADABLE."""
    return bool(last) and last != LAST_SYNC_UNREADABLE


# An exhaustive "never" read costs the whole partition (~1,620 RCU for apple_health), and /api/status
# rebuilds every STATUS_CACHE_TTL. So the verdict is remembered per (table, source, field) for
# _EXHAUSTED_MEMO_TTL_S, with a watermark day: inside the TTL only rows keyed on/after the watermark
# are re-read (a new record still shows on the next build); past it the full search runs again.
# The watermark sits _EXHAUSTED_WATERMARK_DAYS before the day of the search so a UTC-keyed partition's
# late-evening row and a same-week upsert are both still inside the re-read.
_EXHAUSTED_MEMO_TTL_S = 6 * 3600
_EXHAUSTED_WATERMARK_DAYS = 2
_exhausted_memo: dict = {}


class _PageCapExceeded(Exception):
    """A read ran past `_STATUS_MAX_PAGES` without exhausting what it asked for."""


def _paged_items(table, query: dict):
    """Yield each page's Items until LastEvaluatedKey is exhausted; raise past the page cap."""
    kw = dict(query)
    for _ in range(_STATUS_MAX_PAGES):
        resp = table.query(**kw)
        yield resp.get("Items", [])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return
        kw["ExclusiveStartKey"] = lek
    raise _PageCapExceeded(f"{_STATUS_MAX_PAGES} pages without reaching the end of the partition")


def _last_sync(table, source_id, field_check=None):
    """The newest `DATE#` day of a source — or of the rows carrying `field_check`, for the sub-feeds of a
    shared partition. Returns the day string, None ONLY when the partition was read to its end and holds
    no such record ("never"), or LAST_SYNC_UNREADABLE when the read failed or hit the page cap."""
    pk = f"{USER_PREFIX}{source_id}"
    query: dict = {
        "KeyConditionExpression": latest_day_condition(pk, source_id),
        "ScanIndexForward": False,
        "ProjectionExpression": "sk",
    }  # #5431
    if field_check:
        query["FilterExpression"] = Attr(field_check).exists()  # no Limit: 1 MB pages, paged below
    else:
        query["Limit"] = 1  # unfiltered: the first item IS the answer, an empty page IS the end
    memo_key = (source_id, field_check)
    memo = _exhausted_memo.get(memo_key)
    floor = memo[1] if memo and memo[0] is table and time.time() - memo[2] < _EXHAUSTED_MEMO_TTL_S else None
    if floor:
        ceiling = latest_sk_ceiling(source_id)
        query["KeyConditionExpression"] = Key("pk").eq(pk) & Key("sk").between(f"DATE#{floor}", f"{ceiling or 'DATE#'}~")
    try:
        for items in _paged_items(table, query):
            if items:
                _exhausted_memo.pop(memo_key, None)
                return items[0]["sk"].replace("DATE#", "")[:10]
    except Exception as e:  # noqa: BLE001 — an unreadable feed is reported as unreadable, never as "never"
        logger.warning(f"[status] last-sync read failed for {source_id}/{field_check}: {e}")
        return LAST_SYNC_UNREADABLE
    if not floor:
        watermark = (datetime.now(PT).date() - timedelta(days=_EXHAUSTED_WATERMARK_DAYS)).isoformat()
        _exhausted_memo[memo_key] = (table, watermark, time.time())
    return None


def _window_presence(table, source_id, fields, start: str, end: str) -> dict:
    """{day: set of `fields` present} for every DATE# row of `source_id` in [start, end], paged to the end.

    ONE paged read per partition per build serves every sub-feed's bars (#5930): the per-row filtered
    query this replaces read the same 90-day apple_health window once per sub-feed, and paging each of
    those to the end would have multiplied the read cost by the sub-feed count. Raises on a failed read
    or past the page cap — the caller degrades to a neutral bar."""
    query: dict = {
        "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").between(f"DATE#{start}", f"DATE#{end}~"),
        "ProjectionExpression": "sk",
    }
    if fields:
        names = {f"#f{i}": f for i, f in enumerate(fields)}
        query["ProjectionExpression"] = "sk, " + ", ".join(names)
        query["ExpressionAttributeNames"] = names
    out: dict = {}
    for items in _paged_items(table, query):
        for item in items:
            out.setdefault(item["sk"].replace("DATE#", "")[:10], set()).update(f for f in fields if f in item)
    return out


# ── Module-owned cache state for /api/status ─────────────────────────────────
# Originally globals in site_api_lambda.py, then on site_api_intelligence.py;
# they live here (#1654) so the `global` declarations in status() and the reads
# in status_summary() target ONE namespace — the module that owns the lifecycle.
_status_cache: dict[str, Any] = {}
_status_cache_ts = 0
# _cost_cache/_cost_cache_ts retired by #1909: the cost block no longer calls Cost
# Explorer, so there is nothing expensive left to cache. It reads the governor's
# already-computed breakdown from SSM (budget_guard caches that itself).


def _chronicle_send_label() -> str:
    """ "<Weekday> H:MM AM/PM · Elena Voss" for the `_EMAIL_LAMBDAS` wednesday_chronicle
    row — derived from #3564's `common.subscriber_cadence` sender registry (the
    live `ChronicleEmailSender` cron), never hand-typed (#3619, the fourth of the
    #3564 family of hand-typed cadence literals: /subscribe/, the confirmation
    email, and the welcome email were the first three). The cron is Pacific wall
    clock (config/schedules.json platform_timezone, #4284 / ADR-165), so its PT
    clock time is the same in both halves of the year — no "now" is needed."""
    chronicle = sender("chronicle-email-sender")
    weekday = weekday_name(required_weekday(chronicle.cron))
    clock = datetime(2000, 1, 1, cron_hour(chronicle.cron), cron_minute(chronicle.cron))
    time_str = clock.strftime("%I:%M %p").lstrip("0")
    return f"{weekday} {time_str} · Elena Voss"


def _read_health_check(table) -> tuple:
    """(the reader's probe summary, the set of source ids whose daily probe failed) from the newest
    health_check row. Owner ruling 2026-11-03: the tally is recounted over PUBLIC sources — a private
    source's probe (the journal pull and its enrichment) moves neither `passed` nor `failed`, and a
    record without per-probe results cannot be recounted and serves no tally (fail closed)."""
    info: dict = {}
    failed_sources: set = set()
    try:
        hc_items = table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}health_check"), ScanIndexForward=False, Limit=1).get(
            "Items", []
        )
        if not hc_items:
            return info, failed_sources
        hc = hc_items[0]
        results = hc.get("results")
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except ValueError:
                results = None
        info = {"checked_at": hc.get("checked_at", "")}
        if isinstance(results, list):
            public = [
                r for r in results if isinstance(r, dict) and not _activity_publication.is_private_activity_source(r.get("source_id"))
            ]
            info["passed"] = sum(1 for r in public if r.get("healthy") and not r.get("paused"))
            info["failed"] = sum(1 for r in public if not r.get("healthy") and not r.get("paused"))
        for f in json.loads(hc.get("failures", "[]")):
            if _activity_publication.is_private_activity_source((f or {}).get("source_id")):
                continue
            # #4761: an enrichment probe failure is not its parent source's ingestion failing.
            # New records carry "<parent>:enrichment"; the function_name test also covers a
            # record written before that id existed. Stays in `health_check` counts only.
            if str(f.get("function_name", "")).endswith("-enrichment") or ":" in str(f.get("source_id", "")):
                continue
            failed_sources.add(f.get("source_id", ""))
    except Exception as e:
        logger.warning(f"[status] Health check read failed (non-fatal): {e}")
    return info, failed_sources


def status(*, _g) -> dict:
    """
    GET /api/status — full system status for status page
    GET /api/status/summary — lightweight overall status for footer dot
    Cache: 300s (5 min) server-side, 60s client-side.
    """
    global _status_cache, _status_cache_ts

    table = _g["table"]
    _budget_cost_block = _g["_budget_cost_block"]

    now_ts = time.time()
    if now_ts - _status_cache_ts < STATUS_CACHE_TTL and _status_cache:
        return _ok(_status_cache, cache_seconds=60)

    # (#2221: `today_dow` lived here to feed the deleted schedule-aware idle state. The
    # cadence check that replaced it measures days of silence, not the weekday.)

    # ── Pipeline health check results (active probe) ──
    health_check_info, health_check_failures = _read_health_check(table)

    # ── CloudWatch alarm check — detect pipeline errors ──
    cw_alarm_states = {}
    composite_alarms = []  # #3503: red composites, which carry no Dimensions to map by
    try:
        cw = boto3.client("cloudwatch", region_name=DDB_REGION)
        # #3503: `describe_alarms` returns METRIC ALARMS ONLY unless AlarmTypes is passed.
        # The composites are named explicitly rather than left to the default, so a red
        # composite (whose constituents may all be OK-by-design) reaches this page instead
        # of being invisible to it — `ai-tokens-platform-daily-total-urgent` was red for
        # ~24h on 2026-08-30 and no sweep but the alert digest could see it.
        alarms_resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=50, AlarmTypes=["CompositeAlarm", "MetricAlarm"])
        for alarm in alarms_resp.get("MetricAlarms", []):
            # Map alarm name back to source ID (convention: ingestion-error-{source} or {source}-errors)
            aname = alarm.get("AlarmName", "")
            for dim in alarm.get("Dimensions", []):
                if dim.get("Name") == "FunctionName":
                    cw_alarm_states[dim["Value"]] = aname
        # A composite carries no Dimensions, so it can never map to a source row. Surface
        # the names directly — an unmappable red must be visible, not dropped on the floor.
        composite_alarms = sorted(a.get("AlarmName", "") for a in alarms_resp.get("CompositeAlarms", []))
    except Exception as e:
        logger.warning(f"[status] CloudWatch alarm check failed (non-fatal): {e}")

    # Map Lambda function names to source IDs for alarm lookup
    _LAMBDA_TO_SOURCE = {
        "whoop-data-ingestion": "whoop",
        "withings-data-ingestion": "withings",
        "strava-data-ingestion": "strava",
        "habitify-data-ingestion": "habitify",
        "eightsleep-data-ingestion": "eightsleep",
        "macrofactor-data-ingestion": "macrofactor",
        "notion-journal-ingestion": "notion",
        "todoist-data-ingestion": "todoist",
        "weather-data-ingestion": "weather",
        "health-auto-export-webhook": "apple_health",
        "food-delivery-ingestion": "food_delivery",
        "character-sheet-compute": "character_sheet",
        "daily-metrics-compute": "computed_metrics",
        "daily-insight-compute": "computed_insights",
        "adaptive-mode-compute": "adaptive_mode",
        "daily-brief": "daily_brief",
        "weekly-digest": "weekly_digest",
        "monday-compass": "monday_compass",
        "wednesday-chronicle": "wednesday_chronicle",
        "weekly-plate": "weekly_plate",
        "nutrition-review": "nutrition_review",
        "anomaly-detector": "anomaly_detector",
    }
    alarming_sources = set()
    for fn_name, alarm_name in cw_alarm_states.items():
        src = _LAMBDA_TO_SOURCE.get(fn_name)
        if src:
            alarming_sources.add(src)

    _COMPUTE_SOURCES = [
        ("character_sheet", "Character Sheet", "Pillar scores \u00b7 level \u00b7 XP", 25, 49),
        ("computed_metrics", "Daily Metrics", "Cross-domain computed signals", 25, 49),
        ("habit_scores", "Habit Score Aggregation", "Tier scores \u00b7 streaks \u00b7 grades", 25, 49),
        # `computed_insights`, not `insights` (#2220): daily-insight-compute writes its
        # daily record to SOURCE#computed_insights. SOURCE#insights exists but is keyed
        # INSIGHT#<timestamp>, so the DATE# freshness probe could never match it — this
        # row read "never ran" forever, which the old green rewrite hid completely.
        ("computed_insights", "Daily Insights", "IC-8 intent vs execution", 25, 49),
        ("adaptive_mode", "Adaptive Mode", "Engagement scoring \u00b7 brief mode", 25, 49),
    ]
    _EMAIL_LAMBDAS = [
        ("daily_brief", "Daily brief", "11:00 AM daily · 18 sections", -1, 25, 49),
        ("weekly_digest", "Weekly digest", "Sunday 9:00 AM", 6, 200, 400),
        ("monday_compass", "Monday compass", "Monday 8:00 AM · forward planning", 0, 200, 400),
        # #3619: the description string below is a LITERAL fallback only — the test
        # harness's `_module_literal` AST-reads this table as a pure constant (it
        # cannot see a function call), so the real cadence-derived label
        # (`_chronicle_send_label()`) is substituted onto this ONE row at render
        # time, in the loop below. `exp_dow=2` still matches
        # `subscriber_cadence.chronicle_weekday()` (Wednesday) — a real drift
        # between this literal and the registry is caught by
        # tests/test_subscriber_cadence_promise_3564.py's own cron-mirror guard.
        ("wednesday_chronicle", "Wednesday chronicle", "Wednesday · Elena Voss", 2, 200, 400),
        ("weekly_plate", "Weekly plate", "Friday 7:00 PM · nutrition", 4, 200, 400),
        ("nutrition_review", "Nutrition review", "Saturday 10:00 AM", 5, 200, 400),
        ("anomaly_detector", "Anomaly detector", "9:05 AM daily · 15 metrics", -1, 25, 49),
    ]

    # Sources where data is inherently 1 day behind (keyed by wake date / previous day)
    _LAGGED_SOURCES = {"eightsleep", "whoop"}

    def _comp_status(last_date_str, yellow_h, red_h, source_id=None):
        # #5930: a failed read is not an absence, so it never says "never" — but it is not a pass
        # either: red, so a DynamoDB outage turns the traffic light instead of reading as calm.
        if last_date_str == LAST_SYNC_UNREADABLE:
            return "red", LAST_SYNC_UNREADABLE, _UNREADABLE_COMMENT
        if not last_date_str:
            return "green" if source_id == "genome" else "red", "never", "No records found in DynamoDB" if source_id != "genome" else None
        # #2221 / ADR-104: a freshness check that could not EVALUATE must read as
        # unreadable, never as a pass — and never as a 500. This strptime was the one
        # unguarded call of the four in this module, so a single malformed `DATE#` sort
        # key anywhere in the table raised ValueError out of the handler and took down
        # the whole status page AND the footer dot (status_summary delegates to status).
        # #3913: the THIRD consumer that ages a source `DATE#` key, found by re-deriving the
        # sweep rather than by re-reading #3257's list. It hand-anchored EVERY source at UTC
        # midnight — the exact defect #3257 fixed in site_api_freshness and #2817 in
        # freshness_checker — so `_hours_ago` ran 7h (PDT) / 8h (PST) HIGH for the eleven
        # Pacific-framed sources and was right about whoop/apple_health only by coincidence.
        # It now goes through the ONE anchor, so the frame comes from the registry facet.
        try:
            last_dt = anchor_day_key(last_date_str, source_id or "")
        except (ValueError, TypeError):
            return "yellow", "unknown", "Freshness unreadable — the newest record's date could not be parsed"
        now = datetime.now(PT)
        days_ago = (now.date() - last_dt.date()).days

        # Sleep/recovery sources are keyed by wake date — yesterday is current
        effective_days = days_ago
        if source_id in _LAGGED_SOURCES:
            effective_days = max(0, days_ago - 1)

        if days_ago == 0:
            rel = "today"
        elif days_ago == 1:
            rel = "yesterday"
        else:
            rel = f"{days_ago}d ago"

        # For lagged sources, show "current" instead of "2d ago" when data is actually fresh
        if source_id in _LAGGED_SOURCES and effective_days <= 1 and days_ago >= 1:
            rel = "current"

        # NB (#2221): `yellow_h` is still not read here — see the standing finding on
        # test_a_source_past_its_own_yellow_threshold_is_not_reported_green. Enforcing it
        # as configured would contradict test_data_from_yesterday_is_still_green on the
        # SAME source, and the picked 25h disagrees with the cadence-derived window in
        # lambdas/ingestion/source_registry.py. Resolving that is a threshold decision,
        # not a code fix, so the column stays inert rather than half-enforced.
        _hours_ago = (now - last_dt).total_seconds() / 3600

        # Green: data is current (accounting for natural lag)
        if effective_days <= 1:
            return "green", rel, None
        elif effective_days <= 2:
            return "yellow", rel, f"Last data {rel} — monitoring"
        elif _hours_ago <= red_h:
            return "yellow", rel, f"Last data {rel} — expected within {red_h}h"
        return "red", rel, f"STALE: last data {rel}. Threshold exceeded ({red_h}h)."

    def _uptime_90d(source_id, activity_dependent=False, field_check=None):
        """Uptime bars including today. All sources use same window for visual alignment.

        #2221: `field_check` mirrors _last_sync's sub-source filter. Several rows share
        one partition (apple_health is written by cgm, water, steps, mindful minutes and
        more), and without the filter every sub-source drew the SAME bars — a CGM feed
        with no glucose reading in 90 days showed a fully green uptime chart built from
        other sub-sources' rows.

        #5930: the window is read ONCE per partition per build (`_window_presence`, paged to
        the end — one page stopped at 1 MB, ~26 days of apple_health) and each sub-feed's
        bars are the days whose row carries its field. A failed read is cached as None so
        every sub-feed of that partition degrades to the neutral bar without re-querying.
        """
        try:
            epoch_start = datetime(2026, 3, 28, tzinfo=timezone.utc).date()
            today = datetime.now(PT).date()
            window_days = min(90, (today - epoch_start).days + 1)
            if window_days < 1:
                return [2]  # pre-epoch: neutral

            if source_id not in _windows:
                try:
                    fields = sorted(_fields_by_source.get(source_id, ()))
                    _windows[source_id] = _window_presence(table, source_id, fields, epoch_start.isoformat(), today.isoformat())
                except Exception as e:  # noqa: BLE001 — bars degrade to neutral, never to invented red
                    logger.warning(f"[status] uptime window read failed for {source_id}: {e}")
                    _windows[source_id] = None
            window = _windows[source_id]
            if window is None:
                return [2]
            present = {d for d, fields_on_day in window.items() if field_check is None or field_check in fields_on_day}
            bars = []
            for i in range(window_days - 1, -1, -1):
                d = (today - timedelta(days=i)).isoformat()
                if d in present:
                    bars.append(1)  # green — data exists
                elif i <= 1:
                    bars.append(2)  # neutral — today or yesterday, data may come later
                elif activity_dependent:
                    bars.append(2)  # neutral — no user activity, not a system failure
                else:
                    bars.append(0)  # red — older day with no data (system issue)
            return bars
        except Exception:
            return [2]

    _DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    # A day-scheduled sender (exp_dow >= 0) runs once a week; one cycle is 7 days.
    _WEEKLY_CYCLE_DAYS = 7

    def _missed_scheduled_run(last_date_str, exp_dow):
        """#2221: has a day-scheduled sender gone longer than one whole cycle without
        sending? Returns (missed, scheduled_day_name).

        The window is the sender's OWN cadence — `exp_dow >= 0` means it runs once a
        week, so one cycle is 7 days — not the row's red_h. That is the defect: with
        red_h=400 the recovery branch rewrote everything up to ~17 days of silence to
        "next run scheduled", so a sender that had already skipped a week published
        green.

        Cycle length, not "did it land exactly on its weekday", is deliberate. Today's
        slot is never counted against a sender (the page is read at all hours, and a
        Sunday sender at 06:00 on a Sunday has missed nothing yet), and a send that ran
        a day early or late is still one send per week — the thing worth a colour is a
        whole cycle with no delivery at all.

        exp_dow < 0 means "daily"; those rows are governed by their own yellow_h/red_h.
        """
        if exp_dow < 0 or not last_date_str:
            return False, None
        try:
            last_dt = datetime.strptime(last_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return False, None
        days_silent = (datetime.now(PT).date() - last_dt).days
        return days_silent > _WEEKLY_CYCLE_DAYS, _DOW_NAMES[exp_dow]

    # Build data source components
    now = datetime.now(PT)
    ds_components = []
    board_rows = _board_rows()
    # #5930: per-build state for the shared uptime-window read — the fields each partition's rows
    # are tracked by, and {source: {day: fields present} | None} once read.
    _fields_by_source: dict = {}
    for _r in board_rows:
        if len(_r) > 9 and _r[9]:
            _fields_by_source.setdefault(_r[0], set()).add(_r[9])
    _windows: dict = {}
    # Owner ruling 2026-11-03: a PRIVATE source's sync state (the journal's last sync, its uptime
    # bars, its status colour, its alarm) is private activity — the row is omitted, not marked, and
    # so is its share of the rollup below (common.activity_publication; unclassified fails closed).
    # Owner ruling 2026-11-05: a row tracked by a PRIVATE FIELD of a public source (the State-of-Mind
    # row's `som_avg_valence` inside apple_health) is that private sub-stream's sync state — omitted too.
    # #5930: the rows come from `_board_rows()` — the presentation table plus any registry board
    # source it lacks — already filtered to the public ones.
    for row in board_rows:
        sid, name, desc, yh, rh = row[0], row[1], row[2], row[3], row[4]
        category = row[5] if len(row) > 5 else "auto"
        group = row[6] if len(row) > 6 else "API-Based"
        activity_dep = row[7] if len(row) > 7 else False
        source_app = row[8] if len(row) > 8 else ""
        field_check = row[9] if len(row) > 9 else None
        last = _last_sync(table, sid, field_check=field_check)

        if category == "onetime":
            # Genome — one-time import, no recurring tracking
            try:
                _gene_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{sid}"),
                    Limit=1,
                    ProjectionExpression="sk",
                )
                has_data: bool | None = len(_gene_resp.get("Items", [])) > 0
            except Exception:
                has_data = None  # #5930: unreadable — never "Awaiting initial import" on a failed read
            uptime: list[Any] = []  # No daily bars for one-time sources
            if has_data is None:
                status, rel, comment = "yellow", LAST_SYNC_UNREADABLE, _UNREADABLE_COMMENT
            else:
                status = "green" if has_data else "blue"
                rel = "imported" if has_data else "not imported"
                comment = "One-time import \u2014 data on file" if has_data else "Awaiting initial import"
        elif category == "archive":
            # #5930: a FROZEN partition (source_registry.UNREGISTERED_PARTITIONS) that nothing writes any
            # more. Its age is history, not a fault: blue (out of the rollup), no bars, no auth to check.
            _, rel, _ = _comp_status(last, yh, rh, source_id=sid)
            status = "blue" if rel != LAST_SYNC_UNREADABLE else "yellow"
            comment = (
                _UNREADABLE_COMMENT
                if rel == LAST_SYNC_UNREADABLE
                else f"Frozen archive \u2014 nothing writes this feed any more, so its silence is not a fault. Last record: {rel}."
            )
            uptime = []
        elif category == "manual":
            # Labs / DEXA / Food Delivery — due-date tracking.
            # Cadences come from the module-level DUE_MONTHS above, whose registered rows
            # are DERIVED from SOURCE_REGISTRY's `cadence_months` facet (#3669) — labs is
            # 6 months because the registry says so, not because this line repeats it.
            due_mo = DUE_MONTHS.get(sid, DUE_MONTHS_DEFAULT)
            # #2221: this was the SECOND unguarded strptime (the finding named only the
            # one in _comp_status). A malformed DATE# key on a manual source would raise
            # straight out of the handler exactly the same way.
            try:
                last_dt = datetime.strptime(last[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) if last else None
            except (ValueError, TypeError):
                last_dt = None
            if last == LAST_SYNC_UNREADABLE:
                status, rel, comment = "yellow", LAST_SYNC_UNREADABLE, _UNREADABLE_COMMENT
            elif last_dt is not None:
                days_ago = (datetime.now(PT).date() - last_dt.date()).days
                months_ago = days_ago / 30.0
                due_date = last_dt + timedelta(days=due_mo * 30)
                due_str = due_date.strftime("%b %Y")
                # Human-readable relative time
                if days_ago == 0:
                    rel = "today"
                elif days_ago == 1:
                    rel = "yesterday"
                elif days_ago < 30:
                    rel = f"{days_ago}d ago"
                else:
                    rel = f"{int(months_ago)}mo ago"
                if months_ago < due_mo:
                    status = "green"
                    comment = f"Last: {rel}. Next due: {due_str}"
                elif months_ago < due_mo * 1.5:
                    status = "yellow"
                    comment = f"Due for refresh ({due_str}). Last: {rel}"
                else:
                    status = "yellow"
                    comment = f"Overdue \u2014 was due {due_str}. Last: {rel}"
            else:
                status = "blue"
                rel = "never"
                comment = "No data yet \u2014 schedule first appointment"
            uptime = []  # No daily bars for infrequent sources
        else:
            status, rel, comment = _comp_status(last, yh, rh, source_id=sid)
            uptime = _uptime_90d(sid, activity_dependent=activity_dep, field_check=field_check)

            # Activity-dependent sources: distinguish "user didn't log" vs "pipeline broke"
            # If a source HAD regular data and suddenly stops, that's likely a pipeline issue
            # (auth failure, webhook key mismatch) — not missing user activity.
            #
            # The excuse needs a record to excuse (`and last`, #2220). A feed that has
            # never produced a single record is not "ready, awaiting activity" — nothing
            # has ever been observed from it, so _comp_status's red stands rather than
            # being rewritten green on the basis of nothing (ADR-104).
            if activity_dep and _is_day(last) and status in ("red", "yellow") and sid not in alarming_sources:
                # Check if this source had a consistent history that suddenly stopped
                _was_regular = False
                if last:
                    try:
                        _hist_resp = table.query(
                            KeyConditionExpression=latest_day_condition(f"{USER_PREFIX}{sid}", sid),  # #5431
                            ScanIndexForward=False,
                            Limit=14,
                            ProjectionExpression="sk",
                        )
                        _hist_dates = [i["sk"].replace("DATE#", "")[:10] for i in _hist_resp.get("Items", [])]
                        if len(_hist_dates) >= 7:
                            # Had 7+ records in recent history — this source was flowing regularly
                            # Check gap: if last record is 3+ days old but source had daily data, pipeline likely broke
                            _last_dt = datetime.strptime(last[:10], "%Y-%m-%d")
                            _gap_days = (now.date() - _last_dt.date()).days
                            if _gap_days >= 3 and len(_hist_dates) >= 5:
                                _was_regular = True
                    except Exception:
                        pass

                # Also check: for API-based sources, if the Lambda ran today but wrote nothing,
                # that's a pipeline issue (auth failure, not missing activity)
                if not _was_regular and group == "API-Based" and last:
                    try:
                        _last_dt = datetime.strptime(last[:10], "%Y-%m-%d")
                        _gap_days = (now.date() - _last_dt.date()).days
                        # API sources should write daily — a 2+ day gap means the Lambda
                        # ran but couldn't fetch data (auth expired, API down, etc.)
                        if _gap_days >= 2:
                            _was_regular = True
                    except Exception:
                        pass

                if _was_regular:
                    status = "yellow"
                    comment = f"Pipeline may need attention \u2014 was flowing regularly but stopped {rel}. Check auth/webhook."
                else:
                    status = "green"
                    comment = f"Pipeline ready \u2014 awaiting user activity. Last data: {rel}"
            elif activity_dep and last is None:  # #5930: None now means the partition was read to its end
                comment = "No record has ever arrived on this feed"

        # #3615/#3516: before any alarm override, a source the REGISTRY calls paused or
        # lagging tells its absence story from the registry's own facets. Applied when the
        # panel is already narrating an absence (non-green), and always for a paused
        # source — a pause is a standing fact about the pipe, not a transient state.
        if availability_facet(sid)["status"] == AVAILABILITY_PAUSED:
            comment = _absence_comment(availability_facet(sid), rel)

        # CloudWatch alarm override — if Lambda is actively erroring, escalate status
        if sid in alarming_sources and status != "blue":
            if status == "green":
                # Data is fresh despite alarm — likely a stale 24h-window alarm that's recovering
                status = "yellow"
                comment = "CloudWatch alarm recovering \u2014 data still flowing"
            else:
                status = "red"
                comment = "CloudWatch alarm firing \u2014 Lambda errors detected"
        # Health check override — if daily probe failed, show red
        elif sid in health_check_failures and status not in ("blue", "red"):
            status = "red"
            comment = "Daily health check failed \u2014 pipeline error detected"

        ds_components.append(
            {
                # #5527/#5930: unique per row; `source` keeps the partition id a per-source reader keys on.
                "id": _component_id(sid, field_check),
                "source": sid,
                "field_check": field_check,
                "name": name,
                "description": desc,
                "status": status,
                "last_sync_relative": rel,
                "uptime_90d": uptime,
                "comment": comment,
                "group": group,
                "source_app": source_app,
            }
        )

    # Compute components
    compute_components = []
    for sid, name, desc, yh, rh in _COMPUTE_SOURCES:
        last = _last_sync(table, sid)
        status, rel, comment = _comp_status(last, yh, rh, source_id=sid)
        uptime = _uptime_90d(sid, activity_dependent=True)  # compute depends on ingestion — missing days aren't system failures
        # Compute sources depend on ingestion data — if no new input, no new output is
        # expected, so a SHORT gap is still excused to green. #2220 bounds the excuse by
        # the row's own threshold: it applies to yellow only. Past red_h the component
        # really has stopped producing and now says so, and a component with NO output
        # ever is no longer rewritten green — the old branch published rel="verified"
        # and "Smoke-tested OK", which asserts a pre-launch smoke run rather than
        # reporting an observation of this component (ADR-104).
        if status == "yellow" and _is_day(last) and sid not in alarming_sources:
            status = "green"
            comment = f"Last computed: {rel} \u2014 runs daily when new data arrives"
        elif not last:
            comment = "No output on record \u2014 this component has never published a result"
        if sid in alarming_sources:
            status = "red"
            comment = "CloudWatch alarm firing \u2014 Lambda errors detected"
        compute_components.append(
            {
                "id": sid,
                "name": name,
                "description": desc,
                "status": status,
                "last_sync_relative": rel,
                "uptime_90d": uptime,
                "comment": comment,
            }
        )

    # Email components
    email_components = []
    for lid, name, desc, exp_dow, yh, rh in _EMAIL_LAMBDAS:
        if lid == "wednesday_chronicle":
            # #3619: the table literal above is a fallback the AST-reading test
            # harness can see; the real, cadence-derived label is substituted here.
            desc = _chronicle_send_label()
        last = _last_sync(table, f"email_log#{lid}")
        status, rel, comment = _comp_status(last, yh, rh, source_id=lid)
        uptime = _uptime_90d(f"email_log#{lid}", activity_dependent=True)  # scheduled emails — gaps aren't system failures
        # Weekly/scheduled emails: if they've run within their expected window, they're
        # fine. #2221 bounds "within its window" by the sender's OWN cadence instead of
        # by red_h: the recovery branch used to fire on any `last`, so the whole stretch
        # between "sent this week" and the ~17-day red threshold of a 400h red_h read
        # "next run scheduled" for a sender that had already skipped a week.
        _missed, _next_day = _missed_scheduled_run(last, exp_dow)
        if status in ("yellow",) and _is_day(last) and lid not in alarming_sources and not _missed:
            status = "green"
            comment = f"Last sent: {rel} \u2014 next run scheduled"
        elif _missed and lid not in alarming_sources and status != "red":
            status = "yellow"
            comment = f"More than a week since the last {_next_day} send \u2014 last delivery {rel}"
        # A sender with no send log has not sent. #2220 retired the pre-launch
        # "smoke-tested Mar 29" carve-out, which turned that red green, replaced the
        # measured age with rel="verified" and — worse — overwrote the whole uptime
        # array with `[1] * 90`: ninety green delivery bars invented from zero send
        # records. The bars now stay as measured (neutral, because nothing was sent).
        if status == "red" and not last:
            comment = "No send on record \u2014 this sender has never delivered"
        if lid in alarming_sources:
            status = "red"
            comment = "CloudWatch alarm firing \u2014 Lambda errors detected"
        # #2221: the schedule-aware "gray / next: <Day>" downgrade used to sit here. It
        # was unreachable dead code — every earlier branch had already forced green or
        # red, so `status not in ("green", "red")` was never true — and it is NOT
        # restored, deliberately. Now that a missed slot survives as yellow (above), the
        # only thing this branch could ever do is repaint that miss as "idle, next: Sun"
        # on the six days a week that are not the send day: an honest signal turned into
        # a shrug, which is the exact ADR-104 failure /api/status exists to avoid. A
        # scheduled sender is fully described by green (sent within its cadence, and the
        # comment already names the next run), yellow (skipped a slot) and red (past its
        # threshold); there is no fourth state worth a colour.
        email_components.append(
            {
                "id": lid,
                "name": name,
                "description": desc,
                "status": status,
                "last_sync_relative": rel,
                "uptime_90d": uptime,
                "comment": comment,
            }
        )

    # Infrastructure
    # DLQ depth check
    dlq_depth = 0
    dlq_status = "green"
    dlq_comment = None
    try:
        sqs = boto3.client("sqs", region_name=DDB_REGION)
        dlq_attrs = sqs.get_queue_attributes(
            QueueUrl=f"https://sqs.{DDB_REGION}.amazonaws.com/205930651321/life-platform-ingestion-dlq",
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        dlq_depth = int(dlq_attrs["Attributes"]["ApproximateNumberOfMessages"])
        if dlq_depth > 0:
            dlq_status = "yellow" if dlq_depth < 10 else "red"
            dlq_comment = f"{dlq_depth} messages in dead-letter queue"
    except Exception:
        pass

    # The page/tool counts come from PLATFORM_STATS (#2220) \u2014 the one dict
    # `deploy/sync_doc_metadata.py --apply` rewrites and `tests/test_platform_stats_truth.py`
    # pins against an AST parse of mcp/registry.py. They were hand-typed literals here and
    # had drifted to "116 tools" (registry holds 76) and "66 pages" (77).
    # NB: read the count from PLATFORM_STATS, never `import mcp.registry` \u2014 build_bundle's
    # stage_tree() copies only lambdas/, so mcp/ is absent from the site-api bundle and a
    # runtime import of it would pass every local test and ModuleNotFoundError in prod.
    infra = [
        {
            "id": "cloudfront_main",
            "name": "averagejoematt.com",
            "description": f"CloudFront \u00b7 {PLATFORM_STATS['site_pages']} pages",
            "status": "green",
            "comment": None,
        },
        {"id": "site_api", "name": "Site API Lambda", "description": "us-west-2 \u00b7 60+ endpoints", "status": "green", "comment": None},
        {
            "id": "mcp_server",
            "name": "MCP server",
            "description": f"us-west-2 \u00b7 {PLATFORM_STATS['mcp_tools']} tools",
            "status": "green",
            "comment": None,
        },
        {"id": "dynamodb", "name": "DynamoDB", "description": "on-demand \u00b7 PITR enabled", "status": "green", "comment": None},
        {
            "id": "ses",
            "name": "SES email delivery",
            "description": "Production mode \u00b7 receipt rule",
            "status": "green",
            "comment": None,
        },
        {"id": "dlq", "name": "Dead-letter queue", "description": f"{dlq_depth} messages", "status": dlq_status, "comment": dlq_comment},
    ]

    # Overall status: proportional to severity.
    # Exclude: blue (manual/infrequent), gray (idle), yellow (overdue labs etc.)
    #
    # The infrastructure panel used to be excluded WHOLESALE (#2220), so a red
    # dead-letter queue — ingestion actively dropping messages — left the traffic light
    # green. Only the MEASURED infrastructure rows join the rollup: the rest of that
    # panel is hand-typed `"status": "green"` literals, and padding the denominator with
    # unobserved greens would make the light harder to turn, not more honest.
    _MEASURED_INFRA_IDS = {"dlq"}
    rollup_components = ds_components + compute_components + email_components + [c for c in infra if c["id"] in _MEASURED_INFRA_IDS]
    red_components = [c for c in rollup_components if c["status"] == "red"]
    red_count = len(red_components)
    total_active = len([c for c in rollup_components if c["status"] not in ("blue", "gray")])

    if red_count == 0:
        overall = "green"
    elif red_count >= 3 or (total_active > 0 and red_count / total_active > 0.2):
        overall = "red"  # 3+ failures OR >20% of active pipelines down
    else:
        overall = "yellow"  # 1-2 failures = degraded, not down

    cost_info = _budget_cost_block()

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "cost": cost_info,
        # #3503: composite alarms currently red. They have no FunctionName dimension, so
        # they can never join a source row; without this key a composite red — the ONLY
        # routing of ai-tokens-platform-daily-total — is absent from the status surface.
        "composite_alarms": composite_alarms,
        "health_check": health_check_info,
        "groups": [
            {
                "id": "data_sources",
                "label": "Data sources",
                "subtitle": f"{len(ds_components)} feeds \u2014 wearables \u00b7 nutrition \u00b7 labs \u00b7 genome",
                "components": ds_components,
            },
            {
                "id": "compute",
                "label": "Compute layer",
                "subtitle": "character sheet \u00b7 metrics \u00b7 insights \u00b7 adaptive mode",
                "components": compute_components,
            },
            {"id": "email", "label": "Email & digests", "subtitle": "7 scheduled senders", "components": email_components},
            {
                "id": "infrastructure",
                "label": "Infrastructure",
                "subtitle": "CloudFront \u00b7 DynamoDB \u00b7 SES \u00b7 DLQ",
                "components": infra,
            },
        ],
    }

    _status_cache = result
    _status_cache_ts = now_ts
    return _ok(result, cache_seconds=60)


def status_summary(*, _g) -> dict:
    """GET /api/status/summary — lightweight overall status for footer dot."""
    # Ensure the cache is populated
    if not _status_cache or (time.time() - _status_cache_ts >= STATUS_CACHE_TTL):
        status(_g=_g)
    return _ok(
        {
            "overall": _status_cache.get("overall", "green"),
            "generated_at": _status_cache.get("generated_at", ""),
        },
        cache_seconds=60,
    )
