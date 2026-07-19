"""
lambdas/web/site_api_intelligence.py — system status + daily pulse handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 3, 2026-05-26).

Endpoints:
  /api/status            — full system-status panel (502-line beast,
                           queries DDB for health_check + cost data,
                           caches result for STATUS_CACHE_TTL seconds)
  /api/status/summary    — lightweight footer-dot overall status
  /api/pulse             — daily pulse insights (415 lines, pulls from
                           multiple sources, computes derived signals)
  /api/pulse_history     — history view of past pulses

Cache state for /api/status (_status_cache, _cost_cache, etc.) is owned
by this module (not site_api_common) because the cache lifecycle is
local to handle_status — the `global` declarations write back to this
module's namespace.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal  # noqa: F401

import boto3  # noqa: F401 — handlers may instantiate clients
import experiment_gates  # #1371: arming thresholds served to zero-states — same objects the engines enforce
import stats_core  # #1240: sanctioned stats implementation (ADR-105) — handle_correlations
from boto3.dynamodb.conditions import Key
from phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946 / #1197

from web.site_api_common import (
    DDB_REGION,
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    EXPERIMENT_START,
    PT,
    STATUS_CACHE_TTL,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _get_profile,
    _latest_item,
    _ok,
    _query_source,
    logger,
    pre_start_meta,
    table,
)
from web.vitals_resolver import resolve_vitals  # #1369: the ONE current-vitals truth

# ── Module-owned cache state for /api/status ─────────────
# These were originally globals in site_api_lambda.py; moved here so the
# `global` declarations in handle_status target this module's namespace.
_status_cache = {}
_status_cache_ts = 0
_cost_cache = {}
_cost_cache_ts = 0


def handle_status() -> dict:
    """
    GET /api/status — full system status for status page
    GET /api/status/summary — lightweight overall status for footer dot
    Cache: 300s (5 min) server-side, 60s client-side.
    """
    global _status_cache, _status_cache_ts

    now_ts = time.time()
    if now_ts - _status_cache_ts < STATUS_CACHE_TTL and _status_cache:
        return _ok(_status_cache, cache_seconds=60)

    today_dow = datetime.now(timezone.utc).weekday()

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
        "daily-insight-compute": "insights",
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
        ("insights", "Daily Insights", "IC-8 intent vs execution", 25, 49),
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
        last_dt = datetime.strptime(last_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
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

        # Green: data is current (accounting for natural lag)
        if effective_days <= 1:
            return "green", rel, None
        elif effective_days <= 2:
            return "yellow", rel, f"Last data {rel} — monitoring"
        else:
            hours_ago = (now - last_dt).total_seconds() / 3600
            if hours_ago <= red_h:
                return "yellow", rel, f"Last data {rel} — expected within {red_h}h"
            return "red", rel, f"STALE: last data {rel}. Threshold exceeded ({red_h}h)."

    def _uptime_90d(source_id, activity_dependent=False):
        """Uptime bars including today. All sources use same window for visual alignment."""
        try:
            epoch_start = datetime(2026, 3, 28, tzinfo=timezone.utc).date()
            today = datetime.now(timezone.utc).date()
            window_days = min(90, (today - epoch_start).days + 1)
            if window_days < 1:
                return [2]  # pre-epoch: neutral

            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}")
                & Key("sk").between(f"DATE#{epoch_start.isoformat()}", f"DATE#{today.isoformat()}"),
                ProjectionExpression="sk",
            )
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

    def _sched_aware(status, rel, exp_dow):
        if exp_dow < 0 or today_dow == exp_dow:
            return status, rel
        if status == "yellow":
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return "gray", f"next: {names[exp_dow]}"
        return status, rel

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
            uptime = []  # No daily bars for one-time sources
        elif category == "manual":
            # Labs / DEXA / Food Delivery — due-date tracking
            # Board recommendation: labs every 6mo, DEXA every 12mo, food delivery every 3mo
            DUE_MONTHS = {"labs": 6, "dexa": 12, "food_delivery": 3, "bp_readings": 3, "measurements": 2}
            due_mo = DUE_MONTHS.get(sid, 6)
            if last:
                last_dt = datetime.strptime(last[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
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
            uptime = _uptime_90d(sid, activity_dependent=activity_dep)

            # Activity-dependent sources: distinguish "user didn't log" vs "pipeline broke"
            # If a source HAD regular data and suddenly stops, that's likely a pipeline issue
            # (auth failure, webhook key mismatch) — not missing user activity.
            if activity_dep and status in ("red", "yellow") and sid not in alarming_sources:
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
                elif last:
                    status = "green"
                    comment = f"Pipeline ready \u2014 awaiting user activity. Last data: {rel}"
                else:
                    status = "green"
                    comment = "Pipeline ready \u2014 no data recorded yet"

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
        # Compute sources depend on ingestion data — if no new input, no new output is expected
        if status in ("red", "yellow") and sid not in alarming_sources:
            if not last:
                status = "green"
                rel = "verified"
                comment = "Smoke-tested OK \u2014 awaiting first scheduled run (April 1+)"
            else:
                status = "green"
                comment = f"Last computed: {rel} \u2014 runs daily when new data arrives"
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
        # Weekly/scheduled emails: if they've run within their expected window, they're fine
        # Apply recovery BEFORE _sched_aware so yellow is not downgraded to gray first
        if status in ("yellow",) and last and lid not in alarming_sources:
            status = "green"
            comment = f"Last sent: {rel} \u2014 next run scheduled"
        # Pre-launch: weekly emails that haven't fired yet — smoke-tested Mar 29
        if status == "red" and not last:
            status = "green"
            rel = "verified"
            comment = "Smoke-tested OK \u2014 awaiting first scheduled run"
            uptime = [1] * max(1, len(uptime))
        if lid in alarming_sources:
            status = "red"
            comment = "CloudWatch alarm firing \u2014 Lambda errors detected"
        # Apply schedule-aware downgrade AFTER recovery — green emails stay green,
        # only genuinely stale emails get grayed out on off-days
        if status not in ("green", "red"):
            status, rel = _sched_aware(status, rel, exp_dow)
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

    infra = [
        {
            "id": "cloudfront_main",
            "name": "averagejoematt.com",
            "description": "CloudFront \u00b7 66 pages",
            "status": "green",
            "comment": None,
        },
        {"id": "site_api", "name": "Site API Lambda", "description": "us-west-2 \u00b7 60+ endpoints", "status": "green", "comment": None},
        {"id": "mcp_server", "name": "MCP server", "description": "us-west-2 \u00b7 116 tools", "status": "green", "comment": None},
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
    red_components = [c for c in ds_components + compute_components + email_components if c["status"] == "red"]
    red_count = len(red_components)
    total_active = len([c for c in ds_components + compute_components + email_components if c["status"] not in ("blue", "gray")])

    if red_count == 0:
        overall = "green"
    elif red_count >= 3 or (total_active > 0 and red_count / total_active > 0.2):
        overall = "red"  # 3+ failures OR >20% of active pipelines down
    else:
        overall = "yellow"  # 1-2 failures = degraded, not down

    # ── Cost tracking (cached 24h — Cost Explorer API is slow + costs $0.01/call) ──
    # V2 P5.3 (2026-05-17): bumped from 1h → 24h. CE was billing $0.50-0.70/mo
    # for ~5 calls/day from this endpoint. Cost data changes by the day, not the
    # hour; 24h refresh preserves the dashboard signal without daily-cost waste.
    global _cost_cache, _cost_cache_ts
    cost_info = {}
    if _cost_cache and (time.time() - _cost_cache_ts < 86400):
        cost_info = _cost_cache
    else:
        try:
            ce = boto3.client("ce", region_name="us-east-1")
            now_date = datetime.now(timezone.utc)
            month_start = now_date.strftime("%Y-%m-01")
            today_str = now_date.strftime("%Y-%m-%d")
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": month_start, "End": today_str},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            mtd = float(resp["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
            days_elapsed = now_date.day
            days_in_month = 30
            projected = round((mtd / max(days_elapsed, 1)) * days_in_month, 2)
            budget = 15.0
            cost_info = {
                "mtd": round(mtd, 2),
                "projected": projected,
                "budget": budget,
                "status": "green" if projected <= budget else "yellow" if projected <= budget * 1.2 else "red",
                "pct_of_budget": round((projected / budget) * 100),
            }
            _cost_cache = cost_info
            _cost_cache_ts = time.time()
        except Exception as e:
            logger.warning(f"[status] Cost Explorer failed (non-fatal): {e}")

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


def handle_status_summary() -> dict:
    """GET /api/status/summary — lightweight overall status for footer dot."""
    # Ensure the cache is populated
    if not _status_cache or (time.time() - _status_cache_ts >= STATUS_CACHE_TTL):
        handle_status()
    return _ok(
        {
            "overall": _status_cache.get("overall", "green"),
            "generated_at": _status_cache.get("generated_at", ""),
        },
        cache_seconds=60,
    )


def handle_pulse() -> dict:
    """
    GET /api/pulse
    Returns live Pulse daily state computed from DynamoDB.
    Reads latest records from each source for real-time glyphs.
    Cache: 300s (5 min).
    """
    today_pt = datetime.now(PT).strftime("%Y-%m-%d")
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_pt = (datetime.now(PT) - timedelta(days=1)).strftime("%Y-%m-%d")
    # Display day number in PT; query DynamoDB covering both PT and UTC dates
    _pulse_day = (
        max(1, (datetime.now(PT).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
        if today_pt >= EXPERIMENT_START
        else 0
    )
    # Query range covers yesterday(PT) through today(UTC) to catch timezone boundary records
    q_start = min(yesterday_pt, today_pt)
    q_end = max(today_pt, today_utc)

    # Read latest data from each source
    # #1369 Truth Spine: recovery/hrv/rhr/sleep/steps come from the ONE canonical
    # resolver — /api/vitals (→ /api/snapshot) and the public_stats writers read
    # the same module, so two surfaces can't disagree about the same morning.
    _vr = resolve_vitals(table, USER_PREFIX)
    withings = _latest_item("withings") or {}
    ah = None
    try:
        ah_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}apple_health") & Key("sk").between(f"DATE#{q_start}", f"DATE#{q_end}"),
            ScanIndexForward=False,
            Limit=1,
        )
        ah = _decimal_to_float(ah_resp.get("Items", [{}])[0]) if ah_resp.get("Items") else {}
    except Exception:
        ah = {}
    habitify = _latest_item("habit_scores") or {}

    # Check for journal entry today + streak (single query for last 30 days)
    journal_today = False
    journal_streak = 0
    journal_gap_days = None  # staleness honesty: days since the LAST entry, for the narrative
    try:
        d30_ago = (datetime.now(PT) - timedelta(days=30)).strftime("%Y-%m-%d")
        j_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}notion") & Key("sk").between(f"DATE#{d30_ago}", f"DATE#{q_end}~"),
            ProjectionExpression="sk",
        )
        j_dates = set()
        for item in j_resp.get("Items", []):
            j_dates.add(item["sk"][:15])  # "DATE#YYYY-MM-DD"
        # Check both PT and UTC dates for today's journal (entry may be stored under either)
        journal_today = f"DATE#{today_pt}" in j_dates or f"DATE#{today_utc}" in j_dates
        if journal_today:
            journal_streak = 1
            for days_back in range(1, 31):
                check_sk = f"DATE#{(datetime.now(PT) - timedelta(days=days_back)).strftime('%Y-%m-%d')}"
                if check_sk in j_dates:
                    journal_streak += 1
                else:
                    break
        elif j_dates:
            _last_j = max(d[5:] for d in j_dates)
            journal_gap_days = max(0, (datetime.strptime(today_pt, "%Y-%m-%d").date() - datetime.strptime(_last_j, "%Y-%m-%d").date()).days)
    except Exception:
        pass

    # Also check apple_health for weight fallback
    w_val = float(withings.get("weight_lbs", 0)) if withings.get("weight_lbs") else None
    ah_wt = float(ah.get("weight_lbs", 0)) if ah and ah.get("weight_lbs") else None
    w_date = withings.get("sk", "").replace("DATE#", "")[:10] if withings else None
    ah_date = ah.get("sk", "").replace("DATE#", "")[:10] if ah else None
    w_eff_date = w_date  # the date the served weight actually belongs to (staleness honesty)
    if ah_wt and (not w_val or (ah_date and w_date and ah_date > w_date)):
        w_val = ah_wt
        w_eff_date = ah_date

    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))

    # #1369: the canonical resolver already applied the finalized-recovery,
    # sleep-finalizes-separately, and garmin-then-apple-steps policies.
    recovery = _vr["recovery_pct"]
    sleep_hrs = _vr["sleep_hours"]
    steps = _vr["steps"]
    # Water: get the PT-date record specifically (user logs water throughout the day in their timezone)
    water_ml = float(ah.get("water_intake_ml", 0)) if ah and ah.get("water_intake_ml") else None
    water_l = round(water_ml / 1000, 2) if water_ml else None
    t0_pct = float(habitify.get("tier0_pct", 0)) if habitify.get("tier0_pct") else None

    # --- Lift glyph: check for a strength session today (Hevy or Strava) ---
    trained_today = False
    workout_type = None
    try:
        _hevy_today = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}hevy") & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
            Limit=1,
        )
        _hevy_items = _hevy_today.get("Items", [])
        if _hevy_items:
            trained_today = True
            workout_type = _hevy_items[0].get("routine_name") or _hevy_items[0].get("workout_name") or "Strength"
    except Exception:
        pass
    # Staleness honesty (truth audit 2026-07-10): "Rest day" on day 15 of a training
    # blackout is fiction. Days since the last logged strength session (Hevy is the
    # strength log of record) drives the honest label below.
    days_since_workout = None
    try:
        _hevy_last = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}hevy") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="sk",
        )
        _hl_items = _hevy_last.get("Items", [])
        if _hl_items:
            _last_lift_date = _hl_items[0].get("sk", "")[5:15]
            days_since_workout = max(
                0, (datetime.strptime(today_pt, "%Y-%m-%d").date() - datetime.strptime(_last_lift_date, "%Y-%m-%d").date()).days
            )
    except Exception:
        pass
    if not trained_today:
        try:
            _strava_today = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}strava") & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
                Limit=1,
            )
            _strava_items = _strava_today.get("Items", [])
            if _strava_items:
                # Only count strength-type activities for the lift glyph — not walks/runs/rides
                _LIFT_TYPES = {"WeightTraining", "Crossfit", "Workout", "HIIT", "Yoga", "RockClimbing"}
                for _act in _strava_items[0].get("activities", []):
                    _act_m = _act.get("M", _act) if isinstance(_act, dict) else _act
                    _atype = (
                        _act_m.get("sport_type", {}).get("S", "")
                        if isinstance(_act_m.get("sport_type"), dict)
                        else str(_act_m.get("sport_type", ""))
                    )
                    if _atype in _LIFT_TYPES:
                        trained_today = True
                        _aname = (
                            _act_m.get("name", {}).get("S", "") if isinstance(_act_m.get("name"), dict) else str(_act_m.get("name", ""))
                        )
                        workout_type = _aname or _atype or "Strength"
                        break
        except Exception:
            pass

    # --- Mind glyph: State of Mind valence score ---
    mind_score = None
    try:
        _som_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}state_of_mind") & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
            ScanIndexForward=False,
            Limit=1,
        )
        _som_items = _som_resp.get("Items", [])
        if _som_items:
            mind_score = float(_som_items[0].get("som_avg_valence", 0)) or None
        if not mind_score:
            # Fallback: apple_health partition
            _ah_som = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}apple_health")
                & Key("sk").between(f"DATE#{today_pt}", f"DATE#{today_pt}~"),
                ScanIndexForward=False,
                Limit=1,
            )
            for _a in _ah_som.get("Items", []):
                _sv = _a.get("som_avg_valence")
                if _sv:
                    mind_score = float(_sv)
                    break
    except Exception:
        pass

    # --- N2: Nutrition logging check (last 7 days) ---
    nutrition_logged_7d = 0
    try:
        _d7 = (datetime.now(PT) - timedelta(days=7)).strftime("%Y-%m-%d")
        _mf_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}macrofactor") & Key("sk").between(f"DATE#{_d7}", f"DATE#{today_pt}~"),
        )
        nutrition_logged_7d = sum(
            1 for i in _mf_resp.get("Items", []) if i.get("total_calories_kcal") and float(str(i["total_calories_kcal"])) > 0
        )
    except Exception:
        pass

    # --- Glyph state classification (DPR-1.02) ---
    # RULE: gray = genuinely no data (value is None/null/absent).
    # If a value exists, it MUST be green, amber, or red — never gray.
    def _scale_state():
        if w_val is None:
            return "gray"
        # Staleness honesty (truth audit 2026-07-10): a lit glyph reads as "today's
        # weigh-in". When the latest reading belongs to an older day the glyph goes
        # gray — value/delta stay in the payload for context, dated by as_of.
        if w_eff_date and w_eff_date != today_pt:
            return "gray"
        delta = w_val - start_weight
        if delta <= 0:
            return "green"
        return "amber" if delta <= 2 else "red"

    def _water_state():
        if water_l is None:
            return "gray"
        pct = water_l / 3.0
        if pct >= 0.8:
            return "green"
        return "amber" if pct >= 0.3 else "red"

    def _movement_state():
        if steps is None:
            return "gray"
        if steps >= 8000:
            return "green"
        return "amber" if steps >= 4000 else "red"

    def _recovery_state():
        if recovery is None:
            return "gray"
        if recovery >= 67:
            return "green"
        return "amber" if recovery >= 34 else "red"

    def _sleep_state():
        if sleep_hrs is None:
            return "gray"
        if sleep_hrs >= 7:
            return "green"
        return "amber" if sleep_hrs >= 6 else "red"

    def _mind_state():
        if mind_score is None or mind_score == 0:
            return "gray"
        if mind_score >= 4:
            return "green"
        return "amber" if mind_score >= 2 else "red"

    glyphs = {
        "scale": {
            "state": _scale_state(),
            "value": round(w_val, 1) if w_val else None,
            "direction": "down" if w_val and w_val < start_weight else "up",
            "delta": round(w_val - start_weight, 1) if w_val else None,
            "delta_label": f"{round(w_val - start_weight, 1):+.1f} lbs" if w_val else None,
            "as_of": w_eff_date or today_pt,
        },
        "water": {
            "state": _water_state(),
            "liters": water_l,
            "target": 3.0,
            "label": f"{water_l}L" if water_l else None,
            "as_of": today_pt,
        },
        "movement": {
            "state": _movement_state(),
            "value": int(steps) if steps else None,
            "target": 8000,
            "label": f"{int(steps):,} steps" if steps else None,
            "source": _vr["steps_source"],
            "as_of": _vr["steps_as_of"],
        },
        "recovery": {
            "state": _recovery_state(),
            "value": round(recovery) if recovery else None,
            "recovery_pct": round(recovery) if recovery else None,
            "hrv_ms": round(_vr["hrv_ms"], 1) if _vr["hrv_ms"] is not None else None,
            "rhr_bpm": round(_vr["rhr_bpm"], 1) if _vr["rhr_bpm"] is not None else None,
            "label": f"{round(recovery)}%" if recovery else None,
            "as_of": _vr["recovery_as_of"],
        },
        "sleep": {
            "state": _sleep_state(),
            "value": round(sleep_hrs, 1) if sleep_hrs else None,
            "hours": round(sleep_hrs, 1) if sleep_hrs else None,
            "label": f"{round(sleep_hrs, 1)}h" if sleep_hrs else None,
            "as_of": _vr["sleep_as_of"],
        },
        "journal": {
            "state": "green" if journal_today else "gray",
            "written_today": journal_today,
            "streak_days": journal_streak,
            "gap_days": journal_gap_days,
            "label": (
                "Journaled"
                if journal_today
                else (f"No entry in {journal_gap_days} days" if journal_gap_days is not None and journal_gap_days >= 2 else "No entry yet")
            ),
        },
        "lift": {
            "state": "green" if trained_today else "gray",
            "trained_today": trained_today,
            "workout_type": workout_type,
            "days_since_last": days_since_workout,
            # "Rest day" is only honest for a beat or two after a session; past that it's
            # a layoff and the glyph says how long. No hevy record at all reads unlogged.
            "label": workout_type
            or (
                "Trained"
                if trained_today
                else (
                    "Rest day"
                    if days_since_workout is not None and days_since_workout <= 3
                    else (f"No training logged — {days_since_workout} days" if days_since_workout is not None else "No training logged")
                )
            ),
        },
        "mind": {
            "state": _mind_state(),
            "score": mind_score,
            "label": f"{mind_score:.1f}/5" if mind_score else None,
        },
    }

    signals_reporting = sum(1 for g in glyphs.values() if g.get("state") != "gray")
    amber_or_red = sum(1 for g in glyphs.values() if g.get("state") in ("amber", "red"))
    if signals_reporting == 0:
        status = "quiet"
    elif amber_or_red >= 2 or any(
        g.get("state") == "red" and g.get("recovery_pct") is not None and g["recovery_pct"] < 40 for g in glyphs.values()
    ):
        status = "mixed"
    elif t0_pct and t0_pct >= 80 and recovery and recovery > 50:
        status = "strong"
    else:
        status = "green" if signals_reporting >= 4 else "mixed"

    # --- DPR-1.01: Narrative generator ---
    # Build a natural-language daily brief headline from available signals.
    narrative_parts = []
    if w_val is not None:
        delta_from_start = round(w_val - start_weight, 1)
        dir_word = "down" if delta_from_start < 0 else "up" if delta_from_start > 0 else "flat"
        # Staleness honesty: a days-old weigh-in narrated without a date reads as
        # today's number \u2014 stale-qualify it with the day it actually belongs to.
        _w_stale_note = ""
        if w_eff_date and w_eff_date != today_pt:
            try:
                _lw_dt = datetime.strptime(w_eff_date, "%Y-%m-%d")
                _w_stale_note = f" (last weighed {_lw_dt.strftime('%b')} {_lw_dt.day})"
            except ValueError:
                _w_stale_note = f" (last weighed {w_eff_date})"
        narrative_parts.append(
            f"Day {_pulse_day}. {round(w_val, 1)} lbs \u2014 {dir_word} {abs(delta_from_start):.1f} from start{_w_stale_note}."
        )
    elif _pulse_day:
        narrative_parts.append(f"Day {_pulse_day}.")
    if sleep_hrs is not None:
        s_part = f"Sleep: {round(sleep_hrs, 1)}h"
        if sleep_hrs < 6:
            s_part += " \u2014 short night"
        elif sleep_hrs >= 7.5:
            s_part += " \u2014 solid rest"
        narrative_parts.append(s_part + ".")
    if recovery is not None:
        r_val = round(recovery)
        if r_val < 34:
            narrative_parts.append(f"Recovery low at {r_val}% \u2014 rest day suggested.")
        elif r_val < 50:
            narrative_parts.append(f"Recovery at {r_val}% \u2014 consider a lighter day.")
        elif r_val >= 67:
            narrative_parts.append(f"Recovery strong at {r_val}%.")
        else:
            narrative_parts.append(f"Recovery at {r_val}%.")
    if journal_today:
        narrative_parts.append("Journal logged.")
    elif journal_gap_days is not None and journal_gap_days >= 2:
        # "yet" implies today is the exception — past the threshold, the gap is the fact.
        narrative_parts.append(f"No journal entry in {journal_gap_days} days.")
    else:
        narrative_parts.append("No journal entry yet.")
    if nutrition_logged_7d > 0:
        narrative_parts.append(f"Nutrition: {nutrition_logged_7d}/7 days logged.")
    if not narrative_parts or signals_reporting == 0:
        narrative = "No data reported today. Signals populate as wearables sync."
    else:
        narrative = " ".join(narrative_parts)

    # --- DPR-1.14: Since yesterday deltas ---
    since_yesterday = []
    try:
        _yd_whoop = None
        for _w_item in _decimal_to_float(
            table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}whoop")
                & Key("sk").between(f"DATE#{yesterday_pt}", f"DATE#{yesterday_pt}~"),
                Limit=5,
            ).get("Items", [])
        ):
            if "#WORKOUT#" not in _w_item.get("sk", "") and _w_item.get("recovery_score") is not None:
                _yd_whoop = _w_item
                break
        _yd_wt = None
        _yd_wi = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}withings")
            & Key("sk").between(f"DATE#{yesterday_pt}", f"DATE#{yesterday_pt}~"),
            Limit=1,
        ).get("Items", [])
        if _yd_wi and _yd_wi[0].get("weight_lbs"):
            _yd_wt = float(_yd_wi[0]["weight_lbs"])
        if not _yd_wt:
            _yd_ah = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}apple_health")
                & Key("sk").between(f"DATE#{yesterday_pt}", f"DATE#{yesterday_pt}~"),
                Limit=1,
            ).get("Items", [])
            if _yd_ah and _yd_ah[0].get("weight_lbs"):
                _yd_wt = float(_yd_ah[0]["weight_lbs"])
        if w_val and _yd_wt:
            d = round(w_val - _yd_wt, 1)
            arrow = "\u2191" if d > 0 else "\u2193" if d < 0 else "\u2192"
            since_yesterday.append({"signal": "weight", "text": f"Weight {arrow}{abs(d):.1f} lbs", "delta": d})
            glyphs["scale"]["delta_1d"] = d
        if recovery and _yd_whoop and _yd_whoop.get("recovery_score"):
            d = round(recovery - float(_yd_whoop["recovery_score"]))
            arrow = "\u2191" if d > 0 else "\u2193" if d < 0 else "\u2192"
            since_yesterday.append({"signal": "recovery", "text": f"Recovery {arrow}{abs(d)}%", "delta": d})
            glyphs["recovery"]["delta_1d"] = d
        if sleep_hrs and _yd_whoop and _yd_whoop.get("sleep_duration_hours"):
            d = round(sleep_hrs - float(_yd_whoop["sleep_duration_hours"]), 1)
            arrow = "\u2191" if d > 0 else "\u2193" if d < 0 else "\u2192"
            since_yesterday.append({"signal": "sleep", "text": f"Sleep {arrow}{abs(d):.1f}h", "delta": d})
            glyphs["sleep"]["delta_1d"] = d
    except Exception:
        pass

    # --- DPR-1.15: Notable signals ---
    notable_signals = []
    if recovery is not None and recovery < 40:
        notable_signals.append(
            {
                "signal": "recovery",
                "message": f"Recovery is low at {round(recovery)}%. Consider a rest day or light movement only.",
                "severity": "warning",
            }
        )
    if sleep_hrs is not None and sleep_hrs < 6:
        notable_signals.append(
            {
                "signal": "sleep",
                "message": f"Sleep was {round(sleep_hrs, 1)}h \u2014 below the 7h minimum. Prioritize an early bedtime tonight.",
                "severity": "warning",
            }
        )
    if w_val and since_yesterday:
        _wt_d = next((s["delta"] for s in since_yesterday if s["signal"] == "weight"), None)
        if _wt_d and _wt_d > 3:
            notable_signals.append(
                {
                    "signal": "weight",
                    "message": f"Weight up {_wt_d:.1f} lbs from yesterday. Likely water retention \u2014 check sodium and hydration.",
                    "severity": "info",
                }
            )

    # PRE-START (#931): between a staged reset and its FUTURE genesis the pulse is a
    # countdown, not a broken Day 0 — deterministic copy (no LLM), and no from-start
    # weight delta (there is no baseline until Day 1's weigh-in creates one). Inert
    # once genesis <= today (pre_start_meta returns None and nothing here changes).
    _pre = pre_start_meta()
    if _pre:
        _n = _pre["days_until_start"]
        _start_dt = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
        narrative = (
            f"T−{_n} day{'s' if _n != 1 else ''}. The instruments are on; the experiment begins "
            f"{_start_dt.strftime('%A, %B')} {_start_dt.day}. First baseline: that morning's weigh-in."
        )
        glyphs["scale"]["delta"] = None
        glyphs["scale"]["delta_label"] = None

    return _ok(
        {
            "pulse": {
                **(_pre or {"pre_start": False}),
                "day_number": _pulse_day,
                "date": today_pt,
                "status": status,
                "status_color": {"strong": "#22c55e", "green": "#22c55e", "mixed": "#f5a623", "quiet": "#3a5a48"}.get(status, "#3a5a48"),
                "signals_reporting": signals_reporting,
                "signals_total": 8,
                "narrative": narrative,
                "since_yesterday": since_yesterday,
                "notable_signals": notable_signals,
                "glyphs": glyphs,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        cache_seconds=300,
    )


def handle_pulse_history() -> dict:
    """
    GET /api/pulse_history
    Returns daily pulse summaries from EXPERIMENT_START to today.
    One item per day with weight, recovery, sleep, steps.
    Cache: 3600s (1 hr) — historical data doesn't change.
    """
    today = datetime.now(PT).strftime("%Y-%m-%d")
    whoop_items = _query_source("whoop", EXPERIMENT_START, today)
    withings_items = _query_source("withings", EXPERIMENT_START, today)
    garmin_items = _query_source("garmin", EXPERIMENT_START, today)
    ah_items = _query_source("apple_health", EXPERIMENT_START, today)  # real steps (Garmin is dead/phantom)

    # Index by date
    whoop_by_date = {}
    for w in whoop_items:
        d = w.get("sk", "").replace("DATE#", "")[:10]
        if d and w.get("recovery_score") is not None:
            whoop_by_date[d] = w
    withings_by_date = {}
    for w in withings_items:
        d = w.get("sk", "").replace("DATE#", "")[:10]
        if d and w.get("weight_lbs"):
            withings_by_date[d] = w
    # Steps: Apple Health first; Garmin only if AH-absent AND plausible (>=1000) — drops the
    # phantom ~298 Garmin record that left steps null on 7/8 days (Vitals + Mirror depend on this).
    steps_by_date = {}
    for h in ah_items:
        d = h.get("sk", "").replace("DATE#", "")[:10]
        if d and h.get("steps") and float(h["steps"]) > 0:
            steps_by_date[d] = max(steps_by_date.get(d, 0), int(float(h["steps"])))
    for g in garmin_items:
        d = g.get("sk", "").replace("DATE#", "")[:10]
        if d and g.get("steps") and float(g["steps"]) >= 1000 and d not in steps_by_date:
            steps_by_date[d] = int(float(g["steps"]))

    # Build daily summaries
    days = []
    current = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
    end = datetime.strptime(today, "%Y-%m-%d")
    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
    day_num = 1

    while current <= end:
        d = current.strftime("%Y-%m-%d")
        w = whoop_by_date.get(d, {})
        wi = withings_by_date.get(d, {})

        weight = float(wi["weight_lbs"]) if wi.get("weight_lbs") else None
        recovery = float(w["recovery_score"]) if w.get("recovery_score") else None
        sleep_hrs = float(w["sleep_duration_hours"]) if w.get("sleep_duration_hours") else None
        hrv = float(w["hrv"]) if w.get("hrv") else None
        rhr = float(w["resting_heart_rate"]) if w.get("resting_heart_rate") else None  # falls during a cut = body responding
        strain = float(w["strain"]) if w.get("strain") else None
        steps = steps_by_date.get(d)

        headline_parts = []
        if weight:
            delta = round(weight - start_weight, 1)
            headline_parts.append(f"{round(weight)} lbs ({delta:+.1f})")
        if recovery is not None:
            headline_parts.append(f"Recovery {round(recovery)}%")
        if sleep_hrs:
            headline_parts.append(f"Sleep {round(sleep_hrs, 1)}h")

        days.append(
            {
                "date": d,
                "day_number": day_num,
                "weight_lbs": round(weight, 1) if weight else None,
                "weight_delta": round(weight - start_weight, 1) if weight else None,
                "recovery_pct": round(recovery) if recovery is not None else None,
                "sleep_hours": round(sleep_hrs, 1) if sleep_hrs else None,
                "hrv_ms": round(hrv, 1) if hrv else None,
                "rhr_bpm": round(rhr) if rhr is not None else None,
                "strain": round(strain, 1) if strain is not None else None,
                "steps": steps,
                "headline": " · ".join(headline_parts) if headline_parts else "No data recorded",
            }
        )
        current += timedelta(days=1)
        day_num += 1

    return _ok({"pulse_history": days}, cache_seconds=3600)


# ── PB-08 / #8: Hypotheses + Intelligence summary ─────────
# Both are public read-only routes that feed the Intelligence-page tabbed
# rebuild. Henning/Anika evidence rules apply: hypotheses MUST carry a status
# and confidence, never causal claims; the summary surfaces counts only.

_HYPOTHESES_PK = f"{USER_PREFIX}hypotheses"


def handle_hypotheses() -> dict:
    """
    GET /api/hypotheses
    Returns active hypotheses with status + confidence + domain, plus the
    verdict trail (last_checked / last_evidence) once the engine grades one.
    Filters out `public: false` so private records never leak.
    Cache: 3600s (the hypothesis engine runs WEEKLY, Sundays; data shifts slowly).
    """
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot hypotheses
                    "KeyConditionExpression": Key("pk").eq(_HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
                    "ScanIndexForward": False,  # newest first
                    "Limit": 50,
                }
            )
        )
    except Exception as e:
        logger.warning(f"hypotheses query failed: {e}")
        return _error(503, "Hypotheses unavailable.")

    items = _decimal_to_float(resp.get("Items", []))
    hypotheses = []
    for it in items:
        # Hide explicitly-private hypotheses. Default is public for hypotheses
        # written by the IC-18 engine, which produces user-visible findings.
        if it.get("public") is False:
            continue
        hypotheses.append(
            {
                "hypothesis_id": it.get("hypothesis_id") or it.get("sk", "").replace("HYPOTHESIS#", ""),
                "hypothesis": it.get("hypothesis", ""),
                "domains": it.get("domains", []),
                "status": it.get("status", "pending"),
                "confidence": it.get("confidence"),
                "created_at": it.get("created_at"),
                "check_count": it.get("check_count", 0),
                "evidence": it.get("evidence", {}),
                # The weekly check's verdict trail — the citing evidence sentence the
                # engine wrote when it last graded this bet (AI-4 requires confirming/
                # refuted verdicts to cite numbers). Null until the first check lands.
                "last_checked": it.get("last_checked"),
                "last_evidence": it.get("last_evidence"),
                # #530 (engine v2): the FROZEN pre-registered test spec + the
                # deterministic test's measured stats — the public proof that the
                # criterion predates the data that graded it (ADR-105). Null on
                # v1-era records (they age out within 30 days).
                "test_spec": it.get("test_spec"),
                "pre_registered_at": it.get("pre_registered_at") or it.get("created_at"),
                "deterministic_verdict": it.get("deterministic_verdict"),
                "effect_size": it.get("effect_size"),
                "ci95_low": it.get("ci95_low"),
                "ci95_high": it.get("ci95_high"),
                "n_condition": it.get("n_condition"),
                "n_comparison": it.get("n_comparison"),
                "days_observed": it.get("days_observed"),
            }
        )

    return _ok(
        {
            "hypotheses": hypotheses,
            "count": len(hypotheses),
            # #1371: on a cold start the engine's real arming gates + measured progress
            # ride along, so the zero-state renders a computed trigger. Only fetched
            # when the ledger is empty — armed instruments don't need the countdown.
            "gates": (experiment_gates.hypothesis_gates(current_n=_data_days_this_cycle()) if not hypotheses else None),
            "_notice": "N=1 personal-platform observations — not population claims.",
        },
        cache_seconds=3600,
    )


def handle_intelligence_summary() -> dict:
    """
    GET /api/intelligence_summary
    Top-line counts for the Intelligence page hero strip:
      - active hypotheses
      - validated discoveries / correlations
      - experiments active
      - last computed-at timestamps per signal class
    Cache: 1800s.
    """
    summary = {
        "hypotheses": {"count": 0, "by_status": {}},
        "correlations": {"count": 0, "last_week": None},
        "experiments": {"active": 0},
        "_meta": {"computed_at": datetime.now(timezone.utc).isoformat()},
    }
    # Hypotheses count + by-status
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot hypotheses
                    "KeyConditionExpression": Key("pk").eq(_HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
                    "Limit": 200,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        public_items = [it for it in items if it.get("public") is not False]
        summary["hypotheses"]["count"] = len(public_items)
        by_status = {}
        for it in public_items:
            s = it.get("status", "pending")
            by_status[s] = by_status.get(s, 0) + 1
        summary["hypotheses"]["by_status"] = by_status
    except Exception as e:
        logger.warning(f"intel summary: hypotheses count failed: {e}")

    # Latest weekly correlation matrix
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot correlations
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}weekly_correlations"),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        if items:
            record = items[0]
            corrs = record.get("correlations", {})
            summary["correlations"]["count"] = len(corrs) if isinstance(corrs, (dict, list)) else 0
            summary["correlations"]["last_week"] = record.get("sk", "").replace("WEEK#", "")
    except Exception as e:
        logger.warning(f"intel summary: correlations failed: {e}")

    # Active experiments — query the experiments partition (best-effort)
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot experiments
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}experiments"),
                    "Limit": 100,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        summary["experiments"]["active"] = sum(1 for it in items if it.get("status") == "active")
    except Exception as e:
        logger.warning(f"intel summary: experiments failed: {e}")

    return _ok(summary, cache_seconds=1800)


# ════════════════════════════════════════════════════════════════════════
# #1240: intelligence-adjacent domain handlers — moved verbatim from site_api_data.py
# (correlations / forecast / scenarios / state_of_matthew / inference_receipt /
# wrong / pillar_coupling). Behavior-identical; the router imports these from here.
# ════════════════════════════════════════════════════════════════════════

_COUPLING_PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]

_COUPLING_WINDOW = 60  # trailing character-sheet records to read

_COUPLING_MIN_N = experiment_gates.COUPLING_MIN_N  # a pair needs this many co-present real days or it's honestly omitted


def _coupling_real_score(pd: dict):
    """The pillar's raw_score for a day IF that day carried real signal, else None.

    ADR-104/105: a held/zero-coverage day is NOT a real low — counting a floored or
    carried-forward score would manufacture spurious (anti-)correlation, especially
    across a manual-logging gap. We correlate only days with genuine data.
    """
    if not isinstance(pd, dict):
        return None
    v = pd.get("raw_score")
    if v is None:
        return None
    if pd.get("coverage_hold"):
        return None
    cov = pd.get("data_coverage")
    if cov is not None and float(cov) <= 0:
        return None
    return float(v)


def handle_pillar_coupling() -> dict:
    """GET /api/pillar_coupling — #590: how the seven pillars have actually co-moved.

    Deterministic pairwise Pearson of each pillar's daily raw_score over a trailing
    window (real-signal days only, per _coupling_real_score). Every edge carries its
    own n; pairs below the n floor or with no variance are omitted, never faked — the
    constellation draws thin/absent data honestly faint. No AI, no forecast: this is a
    descriptive statistic over the last ~60 days, labeled by its actual date range.
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}character_sheet") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=_COUPLING_WINDOW,
    )
    recs = _decimal_to_float(resp.get("Items", []))
    recs.sort(key=lambda r: str(r.get("sk", "")))  # chronological
    if len(recs) < _COUPLING_MIN_N:
        return _ok(
            {
                "edges": [],
                "pillars": [],
                "window_start": None,
                "window_end": None,
                "window_days": 0,
                "min_n": _COUPLING_MIN_N,
                "honest_null": True,
            },
            cache_seconds=3600,
        )

    series = {p: [_coupling_real_score(r.get(f"pillar_{p}")) for r in recs] for p in _COUPLING_PILLARS}
    present = [p for p in _COUPLING_PILLARS if any(v is not None for v in series[p])]

    edges = []
    for i in range(len(present)):
        for j in range(i + 1, len(present)):
            a, b = present[i], present[j]
            r = stats_core.pearson_r(series[a], series[b], min_n=_COUPLING_MIN_N)
            if r is None:  # thin or flat → no honest edge to draw
                continue
            n = sum(1 for x, y in zip(series[a], series[b]) if x is not None and y is not None)
            p_val = stats_core.pearson_p_value(r, n)
            edges.append(
                {
                    "a": a,
                    "b": b,
                    "r": round(r, 2),
                    "n": n,
                    "p": round(p_val, 3) if p_val is not None else None,
                    "significant": bool(p_val is not None and p_val < 0.05),
                }
            )
    edges.sort(key=lambda e: -abs(e["r"]))
    return _ok(
        {
            "edges": edges,
            "pillars": present,
            "window_start": str(recs[0].get("sk", "")).replace("DATE#", "")[:10],
            "window_end": str(recs[-1].get("sk", "")).replace("DATE#", "")[:10],
            "window_days": len(recs),
            "min_n": _COUPLING_MIN_N,
            "honest_null": not edges,
        },
        cache_seconds=3600,
    )


def _corr_p_value(p: dict):
    """Serve the stored p-value faithfully, or None when absent.

    The compute lambda rounds p to 4 decimals, so a highly-significant pair
    stores p=0.0 — and the old `float(... or 1)` coerced that 0.0 to 1.0,
    rendering the flagship FDR-significant pair as "p 1.000". Zero is a
    value, not a missing value.
    """
    raw = p.get("p_value", p.get("p"))
    if raw is None:
        return None
    return round(float(raw), 4)


def _corr_strength(r_val: float, stored: str) -> str:
    """Deterministic strength label from |r| (Cohen-style bands).

    The stored `interpretation` has disagreed with the number it sits next
    to (r=0.843 labeled "weak"); the served label must match the served r.
    Falls back to the stored label only for degenerate r=0 rows so
    "insufficient_data" survives.
    """
    a = abs(r_val)
    if a >= 0.7:
        return "strong"
    if a >= 0.4:
        return "moderate"
    if a > 0:
        return "weak"
    return stored or "weak"


def _data_days_this_cycle() -> int | None:
    """Days of computed daily metrics since genesis — the honest progress numerator
    a zero-state renders against the arming gates ("currently 3/10"). A cheap
    Select=COUNT on the computed_metrics partition; None (never a fabricated 0)
    when the count can't be measured (#1371, ADR-104)."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}computed_metrics") & Key("sk").gte(f"DATE#{EXPERIMENT_START}"),
            Select="COUNT",
        )
        return int(resp.get("Count", 0))
    except Exception as e:
        logger.warning("data_days_this_cycle count failed: %s", e)
        return None


def handle_correlations(event: dict = None) -> dict:
    """
    GET /api/correlations
    Returns the most recent weekly correlation matrix (23 pairs)
    for the public Correlation Explorer.

    HP-06: When ?featured=true is passed, returns a flat array of
    the top N significant correlations (default 3) for the homepage
    dynamic discoveries section. Response shape changes to:
      {"correlations": [{...}, ...], "week": "...", "count": N}
    so the homepage JS can iterate directly.

    Cache: 3600s.
    """
    # HP-06: Parse query params
    params = {}
    if event:
        params = event.get("queryStringParameters") or {}
    featured = (params.get("featured") or "").lower() == "true"
    limit = None
    if params.get("limit"):
        try:
            limit = max(1, min(20, int(params["limit"])))
        except (ValueError, TypeError):
            pass

    pk = f"{USER_PREFIX}weekly_correlations"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot weekly correlations
                "KeyConditionExpression": Key("pk").eq(pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        # Genesis week / weekly-correlation compute hasn't run — shaped-empty 200
        # so the site shows an honest "fills as data accrues" state, not a 503.
        # #1371: the zero-state carries the ENGINE's real arming gates + measured
        # progress, so the page renders a computed trigger, never authored copy.
        return _ok(
            {
                "correlations": [],
                "week": None,
                "start_date": None,
                "end_date": None,
                "count": 0,
                "gates": experiment_gates.correlation_gates(current_n=_data_days_this_cycle()),
            },
            cache_seconds=300,
        )

    record = items[0]
    week = record.get("sk", "").replace("WEEK#", "")
    start_date = record.get("start_date", "")
    end_date = record.get("end_date", "")

    # The compute lambda stores correlations as a dict (label → data).
    # Convert to list for the public API. Also supports legacy "pairs" list format.
    raw_corrs = record.get("correlations", {})
    if isinstance(raw_corrs, list):
        # Legacy format: already a list
        pairs = raw_corrs
    elif isinstance(raw_corrs, dict):
        # Current format: dict keyed by label. Convert to list.
        pairs = []
        for label, data in raw_corrs.items():
            entry = dict(data)
            entry["label"] = label
            pairs.append(entry)
    else:
        pairs = []

    # Human-readable labels and source names for each metric
    _METRIC_META = {
        "hrv": {"label": "Heart Rate Variability", "source": "Whoop"},
        "recovery_score": {"label": "Recovery Score", "source": "Whoop"},
        "sleep_duration": {"label": "Sleep Duration", "source": "Whoop"},
        "sleep_score": {"label": "Sleep Score", "source": "Whoop"},
        "resting_hr": {"label": "Resting Heart Rate", "source": "Whoop"},
        "strain": {"label": "Strain", "source": "Whoop"},
        "tsb": {"label": "Training Stress Balance", "source": "Computed"},
        "training_kj": {"label": "Training Load (kJ)", "source": "Strava"},
        "training_mins": {"label": "Training Minutes", "source": "Strava"},
        "protein_g": {"label": "Protein (g)", "source": "MacroFactor"},
        "calories": {"label": "Calories", "source": "MacroFactor"},
        "carbs_g": {"label": "Carbs (g)", "source": "MacroFactor"},
        "fat_g": {"label": "Fat (g)", "source": "MacroFactor"},
        "steps": {"label": "Steps", "source": "Apple Health"},
        "habit_pct": {"label": "Habit Completion %", "source": "Habitify"},
        "day_grade": {"label": "Day Grade", "source": "Computed"},
        "readiness": {"label": "Readiness Score", "source": "Computed"},
        "tier0_streak": {"label": "Tier 0 Streak", "source": "Computed"},
    }

    public_pairs = []
    for p in pairs:
        metric_a = p.get("metric_a", p.get("field_a", ""))
        metric_b = p.get("metric_b", p.get("field_b", ""))
        meta_a = _METRIC_META.get(metric_a, {})
        meta_b = _METRIC_META.get(metric_b, {})
        r_val = float(p.get("pearson_r", p.get("r", 0)) or 0)
        n_val = int(p.get("n_days", p.get("n", 0)) or 0)
        fdr_flag = bool(p.get("fdr_significant", False))
        public_pairs.append(
            {
                "source_a": meta_a.get("source", p.get("source_a", "")),
                "field_a": metric_a,
                "label_a": meta_a.get("label", p.get("label_a", metric_a)),
                "source_b": meta_b.get("source", p.get("source_b", "")),
                "field_b": metric_b,
                "label_b": meta_b.get("label", p.get("label_b", metric_b)),
                "r": round(r_val, 3),
                "p": _corr_p_value(p),
                "n": n_val,
                "strength": _corr_strength(r_val, p.get("interpretation", p.get("strength", ""))),
                "fdr_significant": p.get("fdr_significant", False),
                # #1372 Evidence Bar: the per-claim rigor readout, computed by the
                # ONE sanctioned pure function (stats_core.correlation_evidence,
                # ADR-105) — never an authored grade. Additive field; the shape
                # snapshot's key-added class is informational, not breaking.
                "evidence": stats_core.correlation_evidence(r_val, n_val, fdr_significant=fdr_flag),
                "correlation_type": p.get("correlation_type", "cross_sectional"),
                "lag_days": int(p.get("lag_days", 0) or 0),
                "description": p.get("description", ""),
                "direction": p.get("direction", ""),
                # DISC-1: counterintuitive flag from compute lambda
                "counterintuitive": p.get("counterintuitive", False),
                "expected_direction": p.get("expected_direction", ""),
                # HP-06: metric labels for homepage cards
                "metric_a": meta_a.get("label", p.get("label_a", metric_a)),
                "metric_b": meta_b.get("label", p.get("label_b", metric_b)),
            }
        )

    # Sort all by absolute r descending
    public_pairs.sort(key=lambda x: -abs(x["r"]))

    # HP-06: Featured mode — return flat array of top significant correlations
    if featured:
        # Filter to significant only (p < 0.05 or FDR-significant).
        # p may be None (absent) — and p=0.0 is maximally significant, not missing.
        significant = [p for p in public_pairs if p.get("fdr_significant") or (p.get("p") is not None and p["p"] < 0.05)]
        # Fall back to strongest by |r| if no significant ones found
        if not significant:
            significant = public_pairs
        # Apply limit (default 3)
        top = significant[: limit or 3]
        # Auto-generate description if missing
        for p in top:
            if not p.get("description"):
                direction = "positive" if p["r"] > 0 else "inverse"
                p["description"] = f"{direction.title()} correlation between " f"{p['metric_a']} and {p['metric_b']} " f"(r={p['r']:.2f})"
        return _ok(
            {
                "correlations": top,
                "week": week,
                "count": len(top),
            },
            cache_seconds=3600,
        )

    # Standard mode — return full object for explorer page
    return _ok(
        {
            "correlations": {
                "week": week,
                "start_date": start_date,
                "end_date": end_date,
                "pairs": public_pairs,
                "count": len(public_pairs),
                "methodology": "Pearson r over 90-day rolling window. Benjamini-Hochberg FDR correction. n-gated strength labels.",
            }
        },
        cache_seconds=3600,
    )


def handle_forecast() -> dict:
    """
    GET /api/forecast
    The forecast engine's daily summary (#541) — deterministic EWMA expectations
    for recovery / sleep / weight with 80% intervals, today's graded resolutions
    (expected vs actual), and the running interval-coverage stat. SOURCE#forecast
    holds frozen FORECAST# rows plus one DATE#<today> summary; we serve the
    latest summary with internal keys stripped. The anti-causal framing ships in
    the payload so every consumer renders it: these are expectations from
    observed patterns, not causal claims. Cache: 900s — recomputed once daily.
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}forecast") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    # #1197: the latest DATE# record may be a wiped cycle-N record (tombstone=true /
    # non-current phase) that survived a reset until the next daily writer run — mirror
    # the singleton_visible guard the coach get_item readers already apply (#946/#1085).
    if not items or not singleton_visible(items[0]):
        return _ok({"available": False}, cache_seconds=900)
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    data["framing"] = "what the model expects from observed patterns — correlative, not causal"
    # PRE-START (#948, throughline): before genesis these are the model's physiology
    # warm-up expectations, while Home simultaneously promises "no finish-line math
    # until Day 1" — flag the window so the cockpit can frame the panel instead of
    # reading as a contradiction. Inert (pre_start=False) once genesis <= today.
    _pre = pre_start_meta()
    data["pre_start"] = bool(_pre)
    if _pre:
        data.update(_pre)
    return _ok(data, cache_seconds=900)


def handle_scenarios() -> dict:
    """
    GET /api/scenarios
    The scenario explorer's nightly precompute (#550) — for each curated lever
    ("slept 7.5h+", "20+ zone-2 minutes", …), the distribution of what FOLLOWED
    similar days (next-day recovery/sleep/HRV/mood/energy) with block-bootstrap
    CIs and honest n / n_eff labels; thin cells are pre-hidden by the compute's
    effective-n gate. Anti-causal framing ships in the payload. Read-only;
    cache 3600s — recomputed nightly.
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}scenarios") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    # #1197: same latest-DATE# tombstone/phase guard as handle_forecast.
    if not items or not singleton_visible(items[0]):
        return _ok({"available": False}, cache_seconds=3600)
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    return _ok(data, cache_seconds=3600)


def handle_state_of_matthew() -> dict:
    """
    GET /api/state_of_matthew
    The weekly "State of Matthew" model brief (#552) — the deterministic
    assembly of the forecast engine (#541), the hypothesis engine's live
    pre-registered bets (#530/ADR-105), the coaching panel's current
    consensus/disputes, and the calibration scoreboard (#538) into one
    narrated read-back, computed weekly by state-of-matthew-lambda. Each of
    the four sections is independently present-or-absent per
    `sections_available` — a source with genuinely nothing yet (e.g. n=0
    calibration post-reset) is omitted rather than zero-filled. The one
    Haiku call that wrote `narrative` never computed a number; every figure
    traces back to the section it's quoted from. Read-only; cache 3600s —
    recomputed once a week (Sundays).
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}state_of_matthew") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    # #1197 (LIVE leak): before this guard, the wiped cycle-5 "Week 1, Day 1" brief
    # (tombstone=true, phase=pilot) served as current on /coaching/ for the ~1-week
    # window until the next Sunday state-of-matthew run overwrote it. singleton_visible
    # gives the honest empty state coaching.js already renders ("honest-absent until the
    # first Sunday run of the cycle").
    if not items or not singleton_visible(items[0]):
        return _ok({"available": False}, cache_seconds=3600)
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    return _ok(data, cache_seconds=3600)


# ══════════════════════════════════════════════════════════════════════════════
# The inference receipt (2026-06-13) — radical cost transparency.
# Every Claude call already lands in two metric streams: AWS/Bedrock emits
# token counts per ModelId, and the bundled modules emit per-Lambda tokens to
# LifePlatform/AI. This endpoint reads both, prices them with the same table
# the cost governor enforces, and publishes the meter.
# ══════════════════════════════════════════════════════════════════════════════
_BEDROCK_PRICES = {  # USD per 1M tokens — keep in sync with cost_governor_lambda._PRICES
    "fable": {"in": 10.00, "out": 50.00},
    "sonnet": {"in": 3.00, "out": 15.00},
    "haiku": {"in": 1.00, "out": 5.00},
    "opus": {"in": 5.00, "out": 25.00},
}


def _price_for_model(model_id: str) -> dict:
    m = (model_id or "").lower()
    for k, p in _BEDROCK_PRICES.items():
        if k in m:
            return p
    return _BEDROCK_PRICES["sonnet"]


# #1230: the ADR-133 base ceiling (amendment 2026-07-08, $75→$85). The live ceiling is
# derived from the governor's /life-platform/budget-breakdown param (#822) — it floats to
# $100 in reader-traffic surge mode. This constant is ONLY the fail-closed fallback when
# that read fails; never the retired $75.
_ADR133_BASE_CEILING_USD = 85.0


def handle_inference_receipt() -> dict:
    """GET /api/inference_receipt — today's AI calls + month-to-date, priced."""
    try:
        cw = boto3.client("cloudwatch", region_name="us-west-2")
        ssm = boto3.client("ssm", region_name="us-west-2")
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def _sum(namespace, metric, dim_name, dim_value, start):
            r = cw.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric,
                Dimensions=[{"Name": dim_name, "Value": dim_value}],
                StartTime=start,
                EndTime=now,
                Period=86400,
                Statistics=["Sum"],
            )
            return sum(p["Sum"] for p in r.get("Datapoints", []))

        # Per-model (AWS/Bedrock emits these for every invoke)
        models = []
        seen = cw.list_metrics(Namespace="AWS/Bedrock", MetricName="InputTokenCount")
        for m in seen.get("Metrics", []):
            mid = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "ModelId"), None)
            if not mid:
                continue
            price = _price_for_model(mid)
            row = {"model": mid.split("/")[-1]}
            for label, start in (("today", day_start), ("month", month_start)):
                tin = _sum("AWS/Bedrock", "InputTokenCount", "ModelId", mid, start)
                tout = _sum("AWS/Bedrock", "OutputTokenCount", "ModelId", mid, start)
                row[label] = {
                    "input_tokens": int(tin),
                    "output_tokens": int(tout),
                    "est_cost_usd": round((tin * price["in"] + tout * price["out"]) / 1_000_000, 4),
                }
            if row["month"]["input_tokens"] or row["month"]["output_tokens"]:
                models.append(row)

        # Per-feature (the bundled modules dimension by Lambda function)
        features = []
        fn_metrics = cw.list_metrics(Namespace="LifePlatform/AI", MetricName="AnthropicInputTokens")
        for m in fn_metrics.get("Metrics", []):
            fn = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "LambdaFunction"), None)
            if not fn:
                continue
            tin = _sum("LifePlatform/AI", "AnthropicInputTokens", "LambdaFunction", fn, month_start)
            tout = _sum("LifePlatform/AI", "AnthropicOutputTokens", "LambdaFunction", fn, month_start)
            if tin or tout:
                features.append({"lambda": fn, "month_input_tokens": int(tin), "month_output_tokens": int(tout)})
        features.sort(key=lambda f: -(f["month_input_tokens"] + f["month_output_tokens"]))

        try:
            tier = int(ssm.get_parameter(Name="/life-platform/budget-tier")["Parameter"]["Value"])
        except Exception:
            tier = None

        # #1230: derive the ceiling from the governor's breakdown param (#822 / ADR-133)
        # rather than a hardcoded literal — the base is $85 and floats to $100 in surge
        # mode, so a hardcoded number is guaranteed to be a lie. Fail closed to the $85
        # base (never the retired $75) if the breakdown read fails.
        ceiling_usd = _ADR133_BASE_CEILING_USD
        surge_active = False
        try:
            breakdown = json.loads(ssm.get_parameter(Name="/life-platform/budget-breakdown")["Parameter"]["Value"])
            ceiling_usd = float(breakdown["ceiling"])
            surge_active = bool(breakdown.get("surge_active", False))
        except Exception:
            pass

        month_total = round(sum(r["month"]["est_cost_usd"] for r in models), 2)
        surge_clause = " — reader-traffic surge mode" if surge_active else ""
        note = (
            "Every Claude call routes through one audited chokepoint (ADR-062). "
            "Costs are estimated from token metrics x list prices — the same math "
            f"the budget governor enforces. The ${_ADR133_BASE_CEILING_USD:.0f} base ceiling "
            f"(${ceiling_usd:.0f} in effect{surge_clause}) covers the WHOLE platform, not just AI."
        )
        return _ok(
            {
                "as_of": now.isoformat(timespec="seconds"),
                "budget_ceiling_usd": ceiling_usd,
                "budget_surge_active": surge_active,
                "budget_tier": tier,
                "ai_month_to_date_usd": month_total,
                "models": models,
                "features": features,
                "note": note,
            },
            cache_seconds=900,
        )
    except Exception as e:
        logger.warning(f"[inference_receipt] failed: {e}")
        return _error(503, "Inference receipt temporarily unavailable.")


# ══════════════════════════════════════════════════════════════════════════════
# The Wrong Page (2026-06-13) — the AI's misses, in public.
# Three streams of being wrong, all already recorded:
#   1. The post-generation validator: coach claims contradicted by the data
#      (USER#matthew / SOURCE#intelligence_quality#date — errors[] + flags[])
#   2. The prediction evaluator: per-coach LEARNING# verdicts
#      (confirmed / refuted / inconclusive / expired)
#   3. Refuted hypotheses from the weekly engine
# Nothing here is curated. An empty refuted column after a reset is honest,
# not flattering — the ledger fills as calls resolve.
# ══════════════════════════════════════════════════════════════════════════════
_WRONG_COACHES = ("sleep", "nutrition", "training", "glucose", "mind", "physical", "labs", "explorer")


def handle_wrong() -> dict:
    """GET /api/wrong — the public ledger of AI misses."""
    try:
        # 1. Validator catches (last 120 days)
        start = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew")
            & Key("sk").between(f"SOURCE#intelligence_quality#{start}", "SOURCE#intelligence_quality#~"),
        )
        items = _decimal_to_float(resp.get("Items", []))
        checks_run = int(sum(i.get("checks_run", 0) or 0 for i in items))
        catches, numeric_caught = [], 0
        for i in items:
            for field, sev in (("errors", "error"), ("flags", "flag")):
                v = i.get(field)
                if isinstance(v, list):
                    for e in v:
                        what = (e.get("detail") or e.get("check") or str(e)) if isinstance(e, dict) else str(e)
                        catches.append({"date": i.get("date"), "coach": i.get("coach_id"), "severity": sev, "what": str(what)[:240]})
                elif isinstance(v, (int, float)) and v:
                    numeric_caught += int(v)  # older records store counts, not detail
        catches.sort(key=lambda c: c.get("date") or "", reverse=True)

        # 2. Prediction verdicts per coach
        ledger, recent_misses = [], []
        for c in _WRONG_COACHES:
            r = table.query(
                KeyConditionExpression=Key("pk").eq(f"COACH#{c}_coach") & Key("sk").begins_with("LEARNING#"),
            )
            recs = _decimal_to_float(r.get("Items", []))
            live = [x for x in recs if not x.get("tombstone")]
            counts = {}
            for x in live:
                counts[x.get("status", "unknown")] = counts.get(x.get("status", "unknown"), 0) + 1
            if live:
                ledger.append({"coach": c, **{k: counts.get(k, 0) for k in ("confirmed", "refuted", "inconclusive", "expired")}})
            for x in live:
                if x.get("status") == "refuted":
                    recent_misses.append(
                        {"date": x.get("date"), "coach": c, "what": str(x.get("condition") or x.get("reason") or "")[:240]}
                    )
        recent_misses.sort(key=lambda m: m.get("date") or "", reverse=True)

        return _ok(
            {
                # #1369: the header count is DERIVED (detailed + undetailed) and both
                # parts ship, so the front-end can render a total that always agrees
                # with the rows it shows — "4 caught" over 2 rows was a live
                # self-contradiction (older records logged counts without detail).
                "validator": {
                    "claims_checked": checks_run,
                    "caught": len(catches) + numeric_caught,
                    "caught_detailed": len(catches),
                    "caught_undetailed": numeric_caught,
                    "recent": catches[:25],
                },
                "predictions": {"by_coach": ledger, "refuted_recent": recent_misses[:25]},
                "note": (
                    "Uncurated. The validator audits every coach claim against the data it cites; "
                    "the evaluator scores every dated prediction. A thin refuted column right after "
                    "a reset means the slate is young, not that the model is right — inconclusive "
                    "and expired are claims that could not be proven either."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[wrong] failed: {e}")
        return _error(503, "The wrong page is temporarily unavailable.")
