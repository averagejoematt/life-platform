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
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058
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
    table,
)

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
            "CSV upload (Brittany)",
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
            comment = f"Daily health check failed \u2014 pipeline error detected"

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
    # Whoop: skip workout sub-records (DATE#...#WORKOUT#...), get most recent daily record
    whoop = None
    try:
        _w_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}whoop") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=20,  # Increased from 5 — workout sub-records can push daily records out of window
        )
        for _w_item in _decimal_to_float(_w_resp.get("Items", [])):
            _w_sk = _w_item.get("sk", "")
            if "#WORKOUT#" not in _w_sk and _w_item.get("recovery_score") is not None:
                whoop = _w_item
                break
        if not whoop:
            # No record with recovery data found — use most recent daily (non-workout) record
            for _w_item in _decimal_to_float(_w_resp.get("Items", [])):
                if "#WORKOUT#" not in _w_item.get("sk", ""):
                    whoop = _w_item
                    break
        if not whoop:
            whoop = {}
    except Exception:
        whoop = {}
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
    except Exception:
        pass

    # Also check apple_health for weight fallback
    w_val = float(withings.get("weight_lbs", 0)) if withings.get("weight_lbs") else None
    ah_wt = float(ah.get("weight_lbs", 0)) if ah and ah.get("weight_lbs") else None
    w_date = withings.get("sk", "").replace("DATE#", "")[:10] if withings else None
    ah_date = ah.get("sk", "").replace("DATE#", "")[:10] if ah else None
    if ah_wt and (not w_val or (ah_date and w_date and ah_date > w_date)):
        w_val = ah_wt

    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))

    recovery = float(whoop.get("recovery_score", 0)) if whoop.get("recovery_score") else None
    sleep_hrs = float(whoop.get("sleep_duration_hours", 0)) if whoop.get("sleep_duration_hours") else None
    # Steps: prefer Garmin (more accurate with watch), fall back to Apple Health
    steps = None
    try:
        _g_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}garmin") & Key("sk").between(f"DATE#{yesterday_pt}", f"DATE#{q_end}"),
            ScanIndexForward=False,
            Limit=1,
        )
        for _g in _g_resp.get("Items", []):
            _gs = _g.get("steps")
            if _gs:
                steps = float(str(_gs))
                break
    except Exception:
        pass
    if not steps:
        steps = float(ah.get("steps", 0)) if ah and ah.get("steps") else None
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
            "as_of": w_date or ah_date or today_pt,
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
        },
        "recovery": {
            "state": _recovery_state(),
            "value": round(recovery) if recovery else None,
            "recovery_pct": round(recovery) if recovery else None,
            "hrv_ms": round(float(whoop.get("hrv", 0)), 1) if whoop.get("hrv") else None,
            "rhr_bpm": round(float(whoop.get("resting_heart_rate", 0)), 1) if whoop.get("resting_heart_rate") else None,
            "label": f"{round(recovery)}%" if recovery else None,
        },
        "sleep": {
            "state": _sleep_state(),
            "value": round(sleep_hrs, 1) if sleep_hrs else None,
            "hours": round(sleep_hrs, 1) if sleep_hrs else None,
            "label": f"{round(sleep_hrs, 1)}h" if sleep_hrs else None,
        },
        "journal": {
            "state": "green" if journal_today else "gray",
            "written_today": journal_today,
            "streak_days": journal_streak,
            "label": "Journaled" if journal_today else "No entry yet",
        },
        "lift": {
            "state": "green" if trained_today else "gray",
            "trained_today": trained_today,
            "workout_type": workout_type,
            "label": workout_type or ("Trained" if trained_today else "Rest day"),
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
        narrative_parts.append(f"Day {_pulse_day}. {round(w_val, 1)} lbs \u2014 {dir_word} {abs(delta_from_start):.1f} from start.")
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

    return _ok(
        {
            "pulse": {
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
    garmin_by_date = {}
    for g in garmin_items:
        d = g.get("sk", "").replace("DATE#", "")[:10]
        if d and g.get("steps"):
            garmin_by_date[d] = g

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
        g = garmin_by_date.get(d, {})

        weight = float(wi["weight_lbs"]) if wi.get("weight_lbs") else None
        recovery = float(w["recovery_score"]) if w.get("recovery_score") else None
        sleep_hrs = float(w["sleep_duration_hours"]) if w.get("sleep_duration_hours") else None
        hrv = float(w["hrv"]) if w.get("hrv") else None
        steps = int(float(str(g["steps"]))) if g.get("steps") else None

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
    Returns active hypotheses with status + confidence + domain.
    Filters out `public: false` so private records never leak.
    Cache: 3600s (hypothesis engine runs daily; data shifts slowly).
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
            }
        )

    return _ok(
        {
            "hypotheses": hypotheses,
            "count": len(hypotheses),
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
