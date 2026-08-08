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
from boto3.dynamodb.conditions import Key

from web.site_api_common import (
    DDB_REGION,
    PLATFORM_STATS,
    STATUS_CACHE_TTL,
    USER_PREFIX,
    _ok,
    logger,
)

# ── Module-owned cache state for /api/status ─────────────────────────────────
# Originally globals in site_api_lambda.py, then on site_api_intelligence.py;
# they live here (#1654) so the `global` declarations in status() and the reads
# in status_summary() target ONE namespace — the module that owns the lifecycle.
_status_cache: dict[str, Any] = {}
_status_cache_ts = 0
# _cost_cache/_cost_cache_ts retired by #1909: the cost block no longer calls Cost
# Explorer, so there is nothing expensive left to cache. It reads the governor's
# already-computed breakdown from SSM (budget_guard caches that itself).


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

    # (#2221: `today_dow` lived here to feed the deleted _sched_aware idle state. The
    # cadence check that replaced it measures days of silence, not the weekday.)

    # ── Pipeline health check results (active probe) ──
    health_check_failures = set()
    health_check_info = {}
    try:
        hc_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}health_check"),
            ScanIndexForward=False,
            Limit=1,
        )
        hc_items = hc_resp.get("Items", [])
        if hc_items:
            hc = hc_items[0]
            health_check_info = {
                "checked_at": hc.get("checked_at", ""),
                "passed": int(hc.get("passed", 0)),
                "failed": int(hc.get("failed", 0)),
            }
            failures = json.loads(hc.get("failures", "[]"))
            for f in failures:
                health_check_failures.add(f.get("source_id", ""))
    except Exception as e:
        logger.warning(f"[status] Health check read failed (non-fatal): {e}")

    # ── CloudWatch alarm check — detect pipeline errors ──
    cw_alarm_states = {}
    try:
        cw = boto3.client("cloudwatch", region_name=DDB_REGION)
        alarms_resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=50)
        for alarm in alarms_resp.get("MetricAlarms", []):
            # Map alarm name back to source ID (convention: ingestion-error-{source} or {source}-errors)
            aname = alarm.get("AlarmName", "")
            for dim in alarm.get("Dimensions", []):
                if dim.get("Name") == "FunctionName":
                    cw_alarm_states[dim["Value"]] = aname
    except Exception as e:
        logger.warning(f"[status] CloudWatch alarm check failed (non-fatal): {e}")

    # Map Lambda function names to source IDs for alarm lookup
    _LAMBDA_TO_SOURCE = {
        "whoop-data-ingestion": "whoop",
        "withings-data-ingestion": "withings",
        "garmin-data-ingestion": "garmin",
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

    # (source_id, display_name, description, yellow_h, red_h, category)
    # category: "auto" (default), "manual" (blue — infrequent file imports), "onetime" (green — never changes)
    # Restructured: name is the DATA type, source app is separate
    # (source_id, name, description, yellow_h, red_h, category, group, activity_dependent, source_app, field_check)
    # field_check: if set, _last_sync filters by this field existing (for shared partitions like apple_health)
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
            "Steps \u00b7 GPS routes \u00b7 stress \u00b7 body battery",
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
        # State of Mind tracked via apple_health partition field check (som_avg_valence) in Periodic Uploads section
        # ── Periodic Uploads (file drops, webhooks, device sync) ──
        (
            "macrofactor_workouts",
            "Exercise Log Data",
            "Workout CSV via file drop",
            48,
            168,
            "auto",
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
            "Breathwork mindful minutes \u00b7 sessions",
            48,
            168,
            "auto",
            "Periodic Uploads",
            True,
            "Breathwrk via Apple Health",
            "mindful_minutes",
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
            "Quarterly CSV import \u00b7 delivery index 0-10",
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
        ("wednesday_chronicle", "Wednesday chronicle", "Wednesday 8:00 AM · Elena Voss", 2, 200, 400),
        ("weekly_plate", "Weekly plate", "Friday 7:00 PM · nutrition", 4, 200, 400),
        ("nutrition_review", "Nutrition review", "Saturday 10:00 AM", 5, 200, 400),
        ("anomaly_detector", "Anomaly detector", "9:05 AM daily · 15 metrics", -1, 25, 49),
    ]

    def _last_sync(source_id, field_check=None):
        """Get the latest date for a source. If field_check is set, only count records
        that have that specific field (for shared partitions like apple_health)."""
        try:
            if field_check:
                # Must scan with filter — more expensive but necessary for sub-source tracking
                from boto3.dynamodb.conditions import Attr

                resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").begins_with("DATE#"),
                    FilterExpression=Attr(field_check).exists(),
                    ScanIndexForward=False,
                    ProjectionExpression="sk",
                    Limit=200,  # scan recent records to find one with the field
                )
                items = resp.get("Items", [])
                return items[0]["sk"].replace("DATE#", "")[:10] if items else None
            else:
                resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").begins_with("DATE#"),
                    ScanIndexForward=False,
                    Limit=1,
                    ProjectionExpression="sk",
                )
                items = resp.get("Items", [])
                return items[0]["sk"].replace("DATE#", "")[:10] if items else None
        except Exception:
            return None

    # Sources where data is inherently 1 day behind (keyed by wake date / previous day)
    _LAGGED_SOURCES = {"eightsleep", "whoop"}

    def _comp_status(last_date_str, yellow_h, red_h, source_id=None):
        if not last_date_str:
            return "green" if source_id == "genome" else "red", "never", "No records found in DynamoDB" if source_id != "genome" else None
        # #2221 / ADR-104: a freshness check that could not EVALUATE must read as
        # unreadable, never as a pass — and never as a 500. This strptime was the one
        # unguarded call of the four in this module, so a single malformed `DATE#` sort
        # key anywhere in the table raised ValueError out of the handler and took down
        # the whole status page AND the footer dot (status_summary delegates to status).
        try:
            last_dt = datetime.strptime(last_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return "yellow", "unknown", "Freshness unreadable — the newest record's date could not be parsed"
        now = datetime.now(timezone.utc)
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
        other sub-sources' rows. The filter runs server-side, before the projection, so
        `ProjectionExpression="sk"` still returns only what the bars need.
        """
        try:
            epoch_start = datetime(2026, 3, 28, tzinfo=timezone.utc).date()
            today = datetime.now(timezone.utc).date()
            window_days = min(90, (today - epoch_start).days + 1)
            if window_days < 1:
                return [2]  # pre-epoch: neutral

            _q = {
                "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}{source_id}")
                & Key("sk").between(f"DATE#{epoch_start.isoformat()}", f"DATE#{today.isoformat()}"),
                "ProjectionExpression": "sk",
            }
            if field_check:
                from boto3.dynamodb.conditions import Attr

                _q["FilterExpression"] = Attr(field_check).exists()
            resp = table.query(**_q)
            present = {item["sk"].replace("DATE#", "")[:10] for item in resp.get("Items", [])}
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
        days_silent = (datetime.now(timezone.utc).date() - last_dt).days
        return days_silent > _WEEKLY_CYCLE_DAYS, _DOW_NAMES[exp_dow]

    # Build data source components
    now = datetime.now(timezone.utc)
    ds_components = []
    for row in _DATA_SOURCES:
        sid, name, desc, yh, rh = row[0], row[1], row[2], row[3], row[4]
        category = row[5] if len(row) > 5 else "auto"
        group = row[6] if len(row) > 6 else "API-Based"
        activity_dep = row[7] if len(row) > 7 else False
        source_app = row[8] if len(row) > 8 else ""
        field_check = row[9] if len(row) > 9 else None
        last = _last_sync(sid, field_check=field_check)

        if category == "onetime":
            # Genome — one-time import, no recurring tracking
            try:
                _gene_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{sid}"),
                    Limit=1,
                    ProjectionExpression="sk",
                )
                has_data = len(_gene_resp.get("Items", [])) > 0
            except Exception:
                has_data = False
            status = "green" if has_data else "blue"
            rel = "imported" if has_data else "not imported"
            comment = "One-time import \u2014 data on file" if has_data else "Awaiting initial import"
            uptime: list[Any] = []  # No daily bars for one-time sources
        elif category == "manual":
            # Labs / DEXA / Food Delivery — due-date tracking
            # Board recommendation: labs every 6mo, DEXA every 12mo, food delivery every 3mo
            DUE_MONTHS = {"labs": 6, "dexa": 12, "food_delivery": 3, "bp_readings": 3, "measurements": 2}
            due_mo = DUE_MONTHS.get(sid, 6)
            # #2221: this was the SECOND unguarded strptime (the finding named only the
            # one in _comp_status). A malformed DATE# key on a manual source would raise
            # straight out of the handler exactly the same way.
            try:
                last_dt = datetime.strptime(last[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) if last else None
            except (ValueError, TypeError):
                last_dt = None
            if last_dt is not None:
                days_ago = (datetime.now(timezone.utc).date() - last_dt.date()).days
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
            if activity_dep and last and status in ("red", "yellow") and sid not in alarming_sources:
                # Check if this source had a consistent history that suddenly stopped
                _was_regular = False
                if last:
                    try:
                        _hist_resp = table.query(
                            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{sid}") & Key("sk").begins_with("DATE#"),
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
            elif activity_dep and not last:
                comment = "No record has ever arrived on this feed"

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
                "id": sid,
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
        last = _last_sync(sid)
        status, rel, comment = _comp_status(last, yh, rh, source_id=sid)
        uptime = _uptime_90d(sid, activity_dependent=True)  # compute depends on ingestion — missing days aren't system failures
        # Compute sources depend on ingestion data — if no new input, no new output is
        # expected, so a SHORT gap is still excused to green. #2220 bounds the excuse by
        # the row's own threshold: it applies to yellow only. Past red_h the component
        # really has stopped producing and now says so, and a component with NO output
        # ever is no longer rewritten green — the old branch published rel="verified"
        # and "Smoke-tested OK", which asserts a pre-launch smoke run rather than
        # reporting an observation of this component (ADR-104).
        if status == "yellow" and last and sid not in alarming_sources:
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
        last = _last_sync(f"email_log#{lid}")
        status, rel, comment = _comp_status(last, yh, rh, source_id=lid)
        uptime = _uptime_90d(f"email_log#{lid}", activity_dependent=True)  # scheduled emails — gaps aren't system failures
        # Weekly/scheduled emails: if they've run within their expected window, they're
        # fine. #2221 bounds "within its window" by the sender's OWN cadence instead of
        # by red_h: the recovery branch used to fire on any `last`, so the whole stretch
        # between "sent this week" and the ~17-day red threshold of a 400h red_h read
        # "next run scheduled" for a sender that had already skipped a week.
        _missed, _next_day = _missed_scheduled_run(last, exp_dow)
        if status in ("yellow",) and last and lid not in alarming_sources and not _missed:
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
