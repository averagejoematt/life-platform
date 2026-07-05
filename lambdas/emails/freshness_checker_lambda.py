"""
Freshness Checker Lambda — monitors data source staleness.
Fires via EventBridge schedule. Alerts via SNS when sources are stale.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("freshness-checker")
except ImportError:
    logger = logging.getLogger("freshness-checker")
    logger.setLevel(logging.INFO)

# ── Config (env vars with backwards-compatible defaults) ──
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SNS_ARN = os.environ.get("SNS_ARN", "arn:aws:sns:us-west-2:205930651321:life-platform-alerts")
STALE_HOURS = int(os.environ.get("STALE_HOURS", "48"))
# ADR-052: early-warning threshold. Sources between 24h and STALE_HOURS old
# emit a WarningSourceCount metric so degradation is visible on dashboards
# before it crosses the alarm threshold. No SNS alert from this tier.
WARNING_HOURS = int(os.environ.get("WARNING_HOURS", "24"))
# ADR-052: sick-day suppression looks back N days, not just yesterday.
# A multi-day illness or travel window shouldn't keep re-triggering staleness
# alerts day after day.
SICK_SUPPRESS_DAYS = int(os.environ.get("SICK_SUPPRESS_DAYS", "3"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
cw = boto3.client("cloudwatch", region_name=REGION)

# #392: source identity, per-source thresholds, and the behavioral-vs-infra
# classification all derive from the ONE canonical registry. The dicts below
# used to be hand-mirrored here + site_api_data + tools_labs and drifted —
# withings/strava read as infrastructure, so a quiet logging stretch paged.
# Per-source rationale (thresholds, pause reasons) lives in source_registry.py.
from source_registry import behavioral_source_keys, checker_sources, stale_hours_overrides

SOURCES = checker_sources()
SOURCE_STALE_HOURS = stale_hours_overrides(SOURCES)

# ── DI-1.6: Apple Health activity-integrity guard ──────────────────────────
# The HAE silent-413 blind spot: the per-sample steps payload exceeds the HTTP-API
# body limit and is rejected AT THE GATEWAY, before metering — so it appears in no
# CloudWatch metric (verified 2026-06-20: 4xx/5xx == 0 on days steps were dropped)
# and the HAE app reports "complete". Meanwhile the small automations (water/BP/CGM)
# keep landing in the SAME apple_health partition, so partition-level staleness never
# fires. The only detectable symptom is data-side: `steps` specifically is absent (or
# implausibly low) while the partition itself looks fresh. This guard watches exactly
# that. Thresholds are env-tunable.
AH_STEPS_LAG_ALERT_DAYS = int(os.environ.get("AH_STEPS_LAG_ALERT_DAYS", "2"))  # steps stale vs partition → alert
AH_LOW_STEP_FLOOR = int(os.environ.get("AH_LOW_STEP_FLOOR", "1000"))  # a complete day under this is "low"
AH_LOW_STEP_ALERT_COUNT = int(os.environ.get("AH_LOW_STEP_ALERT_COUNT", "4"))  # low days (of 7) → alert
AH_ACTIVITY_WINDOW_DAYS = int(os.environ.get("AH_ACTIVITY_WINDOW_DAYS", "7"))

# ── D-4 (#468): HAE per-datatype liveness ───────────────────────────────────
# Every HAE datatype (CGM, BP, State of Mind, workouts, water) lands in the SAME
# apple_health partition (SOURCE#apple_health / DATE# items) as merged daily fields —
# there is no per-datatype partition. So partition-level "fresh" hides a sensor that
# went dark weeks ago while steps/water keep the partition alive. This map lets the
# checker report last-seen PER datatype by which prefixed field last appeared on which
# DATE# record. `fields` = any-of presence signals; `stale_days` = behavioral threshold
# (a sensor-session lapse reports, it never pages). Lookback below covers the widest.
HAE_DATATYPES = [
    {"key": "cgm", "label": "CGM (glucose)", "fields": ["blood_glucose_avg", "blood_glucose_readings_count"], "stale_days": 3},
    {
        "key": "blood_pressure",
        "label": "Blood pressure",
        "fields": ["blood_pressure_systolic", "blood_pressure_diastolic"],
        "stale_days": 14,
    },
    {
        "key": "state_of_mind",
        "label": "State of Mind",
        "fields": ["som_avg_valence", "som_check_in_count", "som_mood_count"],
        "stale_days": 14,
    },
    {"key": "workouts", "label": "Workouts / recovery", "fields": ["recovery_workout_minutes", "breathwork_minutes"], "stale_days": 10},
    {"key": "water", "label": "Water", "fields": ["water_intake_ml", "water_intake_oz"], "stale_days": 3},
    {"key": "steps", "label": "Steps / activity", "fields": ["steps"], "stale_days": 2},
]
# Longest lookback needed to find a still-present-but-slow datatype (cap the scan).
HAE_LIVENESS_WINDOW_DAYS = int(os.environ.get("HAE_LIVENESS_WINDOW_DAYS", "45"))
_HAE_LIVENESS_SK = "DATATYPE_LIVENESS"  # sentinel SK on the apple_health partition (sorts before DATE#)
_AH_ALERT_STATE_SK = "ALERTSTATE#ah_activity_degraded"  # DI-1.6 episode sentinel


def check_apple_health_activity(table, now, sick_suppress):
    """Detect a silent Apple Health activity-stream failure (the HAE 413 blind spot).

    Reads the most recent apple_health DATE# records and looks at `steps` specifically
    (not partition freshness, which other HAE automations keep alive). Returns
    (alert_message_or_None, metrics_dict) where metrics_dict feeds CloudWatch.
    """
    pk = f"USER#{USER_ID}#SOURCE#apple_health"
    metrics = {"steps_lag_days": 0.0, "low_step_days": 0.0, "degraded": 0.0}
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": pk, ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=AH_ACTIVITY_WINDOW_DAYS + 3,  # a little headroom past the window
            ProjectionExpression="sk, steps, active_calories",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("apple_health activity check query failed (non-fatal): %s", e)
        return None, metrics

    items = resp.get("Items", [])
    if not items:
        return None, metrics

    today = now.date().isoformat()

    def _date(it):
        return it["sk"].replace("DATE#", "")[:10]

    def _steps(it):
        v = it.get("steps")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    partition_latest = _date(items[0])
    # Most recent date with a present, non-zero steps value.
    steps_present = [_date(it) for it in items if (_steps(it) or 0) > 0]
    steps_latest = max(steps_present) if steps_present else None

    # Steps lag vs the partition: the classic "partition fresh, steps stale" 413 signature.
    if steps_latest is None:
        steps_lag_days = AH_STEPS_LAG_ALERT_DAYS + 1  # no steps at all in window — treat as severe
    else:
        steps_lag_days = (datetime.strptime(partition_latest, "%Y-%m-%d") - datetime.strptime(steps_latest, "%Y-%m-%d")).days
    metrics["steps_lag_days"] = float(steps_lag_days)

    # Low-activity tally over the trailing complete days (exclude today — partial).
    complete = [it for it in items if _date(it) < today][:AH_ACTIVITY_WINDOW_DAYS]
    low_days = [_date(it) for it in complete if (_steps(it) or 0) < AH_LOW_STEP_FLOOR]
    metrics["low_step_days"] = float(len(low_days))

    reasons = []
    if steps_lag_days >= AH_STEPS_LAG_ALERT_DAYS:
        if steps_latest is None:
            reasons.append(
                f"no `steps` data in the last {AH_ACTIVITY_WINDOW_DAYS} days, " f"yet the partition is fresh (latest {partition_latest})."
            )
        else:
            reasons.append(
                f"`steps` last landed {steps_latest} ({steps_lag_days}d behind the partition's "
                f"latest record {partition_latest}) — the step stream stopped while other "
                f"Apple Health automations keep writing."
            )
    if len(low_days) >= AH_LOW_STEP_ALERT_COUNT:
        reasons.append(
            f"{len(low_days)} of the last {AH_ACTIVITY_WINDOW_DAYS} complete days have "
            f"steps < {AH_LOW_STEP_FLOOR} ({', '.join(sorted(low_days))})."
        )

    if not reasons:
        return None, metrics

    metrics["degraded"] = 1.0
    if sick_suppress:
        logger.info("Apple Health activity degraded but suppressed (sick day): %s", reasons)
        return None, metrics

    msg = (
        "⚠️ Life Platform: Apple Health activity-stream gap\n\n"
        "Apple Health is delivering data (the partition looks fresh), but its ACTIVITY "
        "stream specifically looks broken — the signature of a silently-dropped Health "
        "Auto Export payload (oversize 413, rejected at the gateway, invisible to "
        "CloudWatch; the HAE app still reports success):\n\n" + "\n".join(f"  • {r}" for r in reasons) + "\n\nWhat to do:\n"
        "  • Confirm the HAE 'Step counts' automation has Aggregate Data ON (daily totals,\n"
        "    small payload) — raw per-sample exports 413 silently.\n"
        "  • If it just broke, re-send via a one-time Apple Health file export\n"
        "    (backfill/onetime_apple_health_import_*.py).\n\n"
        f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    return msg, metrics


def _rec_date(it):
    """YYYY-MM-DD from an apple_health DATE# item's sk."""
    return str(it.get("sk", "")).replace("DATE#", "")[:10]


def compute_datatype_liveness(records, now, datatypes=None):
    """Per-HAE-datatype last-seen from apple_health DATE# records (D-4/#468). Pure.

    Each datatype writes prefixed fields into the day's merged apple_health item, so
    "last seen" for a datatype is the most recent DATE# on which ANY of its fields was
    present. records: dicts with 'sk' + the datatype fields. Returns a list of
    {key, label, last_seen (YYYY-MM-DD|None), age_days (int|None), dark (bool), stale_days}.
    A datatype with nothing in the window is dark with last_seen None.
    """
    datatypes = datatypes or HAE_DATATYPES
    today = now.date()
    out = []
    for dt in datatypes:
        last = None
        for it in records:
            if any(it.get(f) is not None for f in dt["fields"]):
                d = _rec_date(it)
                if len(d) == 10 and (last is None or d > last):
                    last = d
        if last:
            age = (today - datetime.strptime(last, "%Y-%m-%d").date()).days
            dark = age > dt["stale_days"]
        else:
            age, dark = None, True
        out.append(
            {"key": dt["key"], "label": dt["label"], "last_seen": last, "age_days": age, "dark": dark, "stale_days": dt["stale_days"]}
        )
    return out


def check_apple_health_datatypes(table, now):
    """Query the apple_health partition and compute per-datatype liveness (D-4/#468)."""
    pk = f"USER#{USER_ID}#SOURCE#apple_health"
    fields = sorted({f for dt in HAE_DATATYPES for f in dt["fields"]})
    # sk + every datatype field. None are DynamoDB reserved words, so no aliasing needed.
    projection = "sk, " + ", ".join(fields)
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": pk, ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=HAE_LIVENESS_WINDOW_DAYS + 3,
            ProjectionExpression=projection,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("apple_health datatype-liveness query failed (non-fatal): %s", e)
        return None
    return compute_datatype_liveness(resp.get("Items", []), now)


def alert_episode_decision(state, degraded, now, reminder_hours=24):
    """Episode-based dedup so a recurring alert fires once + a daily reminder, not N/run (D-8/#468).

    Pure. Returns (should_send, new_state, kind). `state` is the prior sentinel dict (or None);
    `degraded` is whether the alerting condition is active now.
      - transition into degraded  -> send, kind="open"
      - still degraded, last send >= reminder_hours ago -> send, kind="reminder"
      - still degraded, within the reminder window -> no send, kind="hold"
      - recovery (was open, now clear) -> no send, close episode, kind="resolved"
    """
    state = dict(state or {})
    now_iso = now.isoformat()
    was_open = bool(state.get("episode_open"))
    if not degraded:
        if was_open:
            state["episode_open"] = False
            state["resolved_at"] = now_iso
        return (False, state, "resolved" if was_open else "quiet")
    if not was_open:
        return (
            True,
            {"episode_open": True, "first_fired_at": now_iso, "last_sent_at": now_iso, "send_count": 1, "resolved_at": None},
            "open",
        )
    last_sent = state.get("last_sent_at")
    send = True
    if last_sent:
        try:
            send = (now - datetime.fromisoformat(last_sent)).total_seconds() / 3600.0 >= reminder_hours
        except (ValueError, TypeError):
            send = True
    if send:
        state["last_sent_at"] = now_iso
        state["send_count"] = int(state.get("send_count", 0)) + 1
        return (True, state, "reminder")
    return (False, state, "hold")


# S-06/#392: Sources whose staleness means "no entry logged yet" rather than a
# broken pipeline. They still appear in the freshness report/email, but do NOT
# count toward StaleSourceCount — the metric the slo-source-freshness alarm
# watches — so only infra/OAuth/API breakage (actionable) pages. The set derives
# from the canonical registry; the original hand-rolled set missed withings,
# strava, and macrofactor, so a quiet stretch held the alarm red for days.
BEHAVIORAL_SOURCES = behavioral_source_keys()


def count_infra_stale(stale_sources) -> int:
    """How many stale sources should PAGE — infrastructure staleness only.

    stale_sources: list of (source_label, detail) as built by lambda_handler.
    Behavioral lapses (weigh-ins, workouts, food logs…) are excluded: they are
    reported honestly in the email/board but must never train the operator to
    ignore the alarm that exists to catch silent pipeline death (#392).
    """
    behavioral_labels = {SOURCES[k] for k in BEHAVIORAL_SOURCES if k in SOURCES}
    return sum(1 for name, _ in stale_sources if name not in behavioral_labels)


# DI-2b: interior-gap detection. The staleness check above only sees the latest
# date per source (the high-water mark), so a hole *behind* it is invisible — a
# daily source can go dead for a few days mid-window and then resume, and nothing
# flags the missing middle. We only judge sources expected to produce a record
# EVERY day; sparse sources (strava activities, withings weigh-ins, food_delivery)
# have legitimate empty days and would false-positive, so they are excluded.
DAILY_SOURCES = {"whoop", "apple_health", "eightsleep", "habitify"}
INTERIOR_GAP_WINDOW_DAYS = 14


def find_interior_gaps(present_dates, window_start: str, window_end: str) -> list:
    """Missing dates strictly inside the [first, last] present span in the window.

    Only the span between the earliest and latest present date is judged — a
    trailing or leading absence is recency (handled by the staleness check), not
    an interior hole. Returns a sorted list of 'YYYY-MM-DD'. Needs >=2 present
    dates to define an interior at all.
    """
    present = sorted(d for d in present_dates if window_start <= d <= window_end)
    if len(present) < 2:
        return []
    pset = set(present)
    cur = datetime.strptime(present[0], "%Y-%m-%d").date()
    hi = datetime.strptime(present[-1], "%Y-%m-%d").date()
    gaps = []
    while cur <= hi:
        s = cur.isoformat()
        if s not in pset:  # lo/hi are present, so anything missing here is interior
            gaps.append(s)
        cur += timedelta(days=1)
    return gaps


# Field-level completeness checks — key fields that should be non-null in a healthy record.
# A source can be "fresh" (recent date) but have partial data (missing key metrics).
# Missing fields here emit a PartialCompletenessCount metric and include source in alert.
# Added v3.7.27 (item 11 — Omar / Jin board recommendation).
FIELD_COMPLETENESS_CHECKS: dict[str, list[str]] = {
    "whoop": ["hrv", "recovery_score", "sleep_duration_hours"],
    "garmin": ["steps", "resting_heart_rate", "body_battery_highest"],
    "apple_health": ["steps", "active_calories"],
    # "macrofactor":   [...],  # dead since 2026-04-11 (Tier 1 torn down)
    "strava": ["activity_count"],  # RE-ENABLED 2026-06-20
    "eightsleep": ["sleep_efficiency_pct", "sleep_duration_hours"],
    "withings": ["weight_lbs"],
    "habitify": ["total_completed"],
    "measurements": ["waist_navel_in", "waist_narrowest_in", "thigh_left_in"],
    "todoist": ["tasks_completed"],
    # google_calendar removed — ADR-030
}


def lambda_handler(event, context):
    table = dynamodb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc)
    now - timedelta(hours=STALE_HOURS)

    # ── Sick day check: suppress stale alerts if any of the last N days was sick ──
    # ADR-052: extended from yesterday-only to a N-day lookback so multi-day
    # illness or travel doesn't keep re-triggering staleness alerts.
    # Stale data on a sick day is expected — user is not tracking anything.
    window_end = now.date() - timedelta(days=1)
    window_start = now.date() - timedelta(days=SICK_SUPPRESS_DAYS)
    _sick_suppress = False
    try:
        from sick_day_checker import get_sick_days_range

        sick_records = get_sick_days_range(
            table,
            USER_ID,
            window_start.isoformat(),
            window_end.isoformat(),
        )
        if sick_records:
            _sick_suppress = True
            _sick_dates = ", ".join(sorted(r.get("sk", "").replace("DATE#", "")[:10] for r in sick_records))
            logger.info(
                "Sick day(s) flagged in last %d days (%s) — freshness alerts suppressed",
                SICK_SUPPRESS_DAYS,
                _sick_dates,
            )
    except ImportError:
        pass

    stale_sources = []
    partial_sources = []  # fresh but missing expected fields
    warning_sources = []  # ADR-052: age > WARNING_HOURS but < stale threshold
    source_status = []

    for source_key, source_name in SOURCES.items():
        pk = f"USER#{USER_ID}#SOURCE#{source_key}"

        try:
            # Filter SK to DATE# prefix so non-date sentinel records (e.g.
            # REFRESH_RATELIMIT for garmin, YEAR#2026 for food_delivery) —
            # which sort lexicographically after DATE#YYYY-MM-DD — are never
            # returned as the "latest" record, causing a false-stale alarm.
            response = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
                ExpressionAttributeValues={":pk": pk, ":pfx": "DATE#"},
                ScanIndexForward=False,
                Limit=1,
                ProjectionExpression="sk",
            )
        except Exception as e:
            logger.error("DynamoDB query failed for %s: %s", source_key, e)
            stale_sources.append((source_name, f"Query error: {e}"))
            source_status.append(f"  ❌ {source_name}: QUERY ERROR")
            continue

        items = response.get("Items", [])
        if not items:
            stale_sources.append((source_name, "No data found"))
            source_status.append(f"  ❌ {source_name}: NO DATA")
            continue

        sk = items[0]["sk"]
        date_str = sk.replace("DATE#", "")[:10]  # Take only YYYY-MM-DD, ignore sub-record suffixes

        try:
            last_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            age_hours = (now - last_date).total_seconds() / 3600

            source_stale_hrs = SOURCE_STALE_HOURS.get(source_key, STALE_HOURS)
            source_stale_threshold = now - timedelta(hours=source_stale_hrs)
            if last_date < source_stale_threshold:
                stale_sources.append((source_name, f"Last update: {date_str} ({age_hours:.0f}h ago)"))
                source_status.append(f"  ⚠️  {source_name}: {date_str} ({age_hours:.0f}h ago)")
            elif age_hours >= WARNING_HOURS:
                # ADR-052: early-warning tier — track but don't alert.
                # Visible on dashboards; helps spot degradation before it crosses
                # the alarm threshold.
                warning_sources.append((source_name, age_hours))
                source_status.append(f"  🟡 {source_name}: {date_str} ({age_hours:.0f}h ago) [warning]")
            else:
                # Source is fresh — now spot-check field completeness
                completeness_flag = ""
                expected_fields = FIELD_COMPLETENESS_CHECKS.get(source_key, [])
                if expected_fields:
                    try:
                        item_resp = table.get_item(
                            Key={"pk": pk, "sk": sk},
                            ProjectionExpression=", ".join(expected_fields),
                        )
                        item = item_resp.get("Item", {})
                        missing = [f for f in expected_fields if item.get(f) is None]
                        if missing:
                            partial_sources.append((source_name, missing))
                            completeness_flag = f" ⚠️ PARTIAL: {missing}"
                    except Exception as _ce:
                        logger.warning("Field completeness check failed for %s: %s", source_key, _ce)

                source_status.append(f"  ✅ {source_name}: {date_str} ({age_hours:.0f}h ago){completeness_flag}")
        except ValueError:
            stale_sources.append((source_name, f"Invalid date format: {date_str}"))
            source_status.append(f"  ❌ {source_name}: Invalid date {date_str}")

    if stale_sources:
        stale_list = "\n".join([f"  - {name}: {detail}" for name, detail in stale_sources])
        status_list = "\n".join(source_status)

        if _sick_suppress:
            # Sick day — expected data gap, no alert needed
            yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            logger.info(
                "Stale sources detected (%d) but suppressed — sick day (%s)",
                len(stale_sources),
                yesterday_str,
            )
        else:
            # Actionable remediation hint, keyed off which stale sources are present.
            # #392: behavioral sources get the "no entry logged" hint (a stale
            # withings is a skipped weigh-in, not an expired token); OAuth hints
            # only for infra sources that actually auth via OAuth.
            _stale_keys = {n for n, _ in stale_sources}
            _behavioral_hint_labels = {SOURCES[k] for k in BEHAVIORAL_SOURCES if k in SOURCES}
            _oauth_stale = {
                lbl
                for lbl in _stale_keys
                if lbl in (SOURCES.get("whoop"), SOURCES.get("eightsleep")) and lbl not in _behavioral_hint_labels
            }
            _input_stale = {lbl for lbl in _stale_keys if lbl in _behavioral_hint_labels}
            hints = []
            if _oauth_stale:
                hints.append(
                    f"• OAuth source(s) stale ({', '.join(sorted(_oauth_stale))}) → the token likely "
                    f"expired; re-auth (Garmin: `python3 setup_garmin_browser_auth.py`)."
                )
            if _input_stale:
                hints.append(
                    f"• Input source(s) stale ({', '.join(sorted(_input_stale))}) → no new entry logged; "
                    f"expected if you've paused that tracking."
                )
            remediation = ("\n\nWhat to do:\n" + "\n".join(hints)) if hints else ""
            message = (
                f"⚠️ Life Platform: Stale Data Detected\n\n"
                f"The following sources have not updated in over {STALE_HOURS} hours:\n\n"
                f"{stale_list}{remediation}\n\n"
                f"Full source status:\n{status_list}\n\n"
                f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
            )
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject=f"⚠️ Life Platform: {len(stale_sources)} stale source(s)",
                    Message=message,
                )
                logger.info("Alert sent for %d stale source(s)", len(stale_sources))
            except Exception as e:
                logger.error("SNS publish failed: %s", e)
    else:
        status_list = "\n".join(source_status)
        logger.info("All sources fresh.\n%s", status_list)

    # Partial completeness alert (separate from staleness alert)
    if partial_sources and not _sick_suppress:
        partial_list = "\n".join([f"  - {name}: missing {', '.join(fields)}" for name, fields in partial_sources])
        try:
            sns.publish(
                TopicArn=SNS_ARN,
                Subject=f"⚠️ Life Platform: {len(partial_sources)} partial record(s)",
                Message=(
                    f"⚠️ Life Platform: Partial Data Detected\n\n"
                    f"The following sources have fresh records but are missing expected fields:\n\n"
                    f"{partial_list}\n\n"
                    f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
                ),
            )
            logger.info("Partial completeness alert sent for %d source(s)", len(partial_sources))
        except Exception as e:
            logger.error("Partial completeness SNS publish failed: %s", e)

    # ── MacroFactor format-drift guard (meal-grouping, 2026-06-19) ──
    # The diary export carries per-food timestamps (entries_count > 0). MacroFactor's
    # default export is a daily-summary (one row/day, empty food_log, entries_count == 0)
    # — when it silently reverts, the date stays "fresh" but the meal grouper is starved.
    # Alert when the last N records all have entries_count == 0, and emit a metric.
    macro_drift = False
    try:
        drift_resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": f"USER#{USER_ID}#SOURCE#macrofactor", ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=5,
            ProjectionExpression="entries_count",
        )
        drift_recs = drift_resp.get("Items", [])
        empties = [r for r in drift_recs if int(r.get("entries_count", 0) or 0) == 0]
        macro_drift = bool(drift_recs) and len(empties) == len(drift_recs)
        if macro_drift and not _sick_suppress:
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject="⚠️ Life Platform: MacroFactor format drift",
                    Message=(
                        "⚠️ MacroFactor diary export appears to have reverted to daily-summary format.\n\n"
                        f"The last {len(drift_recs)} MacroFactor records all have an empty food_log "
                        f"(entries_count == 0). The derived meal layer (macrofactor_meals) is starved — "
                        f"new days won't group.\n\nFix: re-export the *diary* format from MacroFactor.\n\n"
                        f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                )
                logger.info("MacroFactor format-drift alert sent (%d/%d empty)", len(empties), len(drift_recs))
            except Exception as _de:
                logger.error("Format-drift SNS publish failed: %s", _de)
    except Exception as e:
        logger.warning("MacroFactor format-drift check failed (non-fatal): %s", e)

    # ── DI-2b: interior-gap scan (daily sources only) ──
    # For each daily source, pull the window's DATE# records and flag any missing
    # date INSIDE the present span — a hole that means the source went dead mid-
    # window then resumed, which the high-water-mark staleness check above cannot
    # see. Sparse sources are excluded (see DAILY_SOURCES) so rest days don't fire.
    interior_gaps = {}  # source_key -> [missing interior dates]
    _gap_window_start = (now - timedelta(days=INTERIOR_GAP_WINDOW_DAYS)).strftime("%Y-%m-%d")
    _gap_window_end = now.strftime("%Y-%m-%d")
    for source_key in DAILY_SOURCES:
        if source_key not in SOURCES:
            continue
        try:
            gap_resp = table.query(
                KeyConditionExpression="pk = :pk AND sk BETWEEN :a AND :b",
                ExpressionAttributeValues={
                    ":pk": f"USER#{USER_ID}#SOURCE#{source_key}",
                    ":a": f"DATE#{_gap_window_start}",
                    ":b": f"DATE#{_gap_window_end}~",  # '~' > '#': include same-day sub-record SKs
                },
                ProjectionExpression="sk",
            )
            present = {it["sk"].replace("DATE#", "")[:10] for it in gap_resp.get("Items", [])}
            gaps = find_interior_gaps(present, _gap_window_start, _gap_window_end)
            if gaps:
                interior_gaps[source_key] = gaps
        except Exception as _ge:
            logger.warning("Interior-gap scan failed for %s (non-fatal): %s", source_key, _ge)
    interior_gap_count = sum(len(v) for v in interior_gaps.values())
    if interior_gap_count and not _sick_suppress:
        logger.warning(
            "Interior gaps detected behind high-water mark: %s",
            {SOURCES.get(k, k): v for k, v in interior_gaps.items()},
        )

    # OBS-3: Emit SLO metrics to CloudWatch
    try:
        fresh_count = len(SOURCES) - len(stale_sources)
        # S-06/#392: StaleSourceCount counts only infra/pipeline staleness (actionable —
        # OAuth/API/webhook breakage), not behavioral input lapses. Behavioral
        # sources remain in stale_sources for the email report but don't trip the SLO.
        infra_stale_count = count_infra_stale(stale_sources)
        cw.put_metric_data(
            Namespace="LifePlatform/Freshness",
            MetricData=[
                {
                    "MetricName": "StaleSourceCount",
                    "Value": infra_stale_count,
                    "Unit": "Count",
                },
                {
                    "MetricName": "FreshSourceCount",
                    "Value": fresh_count,
                    "Unit": "Count",
                },
                {
                    "MetricName": "PartialCompletenessCount",
                    "Value": float(len(partial_sources)),
                    "Unit": "Count",
                },
                # ADR-052: early-warning metric (no alarm). Dashboards and
                # operators see degradation before it crosses the alarm threshold.
                {
                    "MetricName": "WarningSourceCount",
                    "Value": float(len(warning_sources)),
                    "Unit": "Count",
                },
                # meal-grouping guard: 1 when MacroFactor diary export has reverted to
                # daily-summary (empty food_log) across the last N records.
                {
                    "MetricName": "MacroFactorFormatDrift",
                    "Value": 1.0 if macro_drift else 0.0,
                    "Unit": "Count",
                },
                # DI-2b: count of missing dates behind the high-water mark across
                # daily sources. Suppressed on sick days (expected gaps).
                {
                    "MetricName": "InteriorGapCount",
                    "Value": 0.0 if _sick_suppress else float(interior_gap_count),
                    "Unit": "Count",
                },
            ],
        )
        logger.info(
            "SLO metrics emitted: %d stale, %d fresh, %d partial, %d warning",
            len(stale_sources),
            fresh_count,
            len(partial_sources),
            len(warning_sources),
        )
    except Exception as e:
        logger.error("CloudWatch SLO metric emit failed (non-fatal): %s", e)

    # R8-ST4: OAuth token health check — alert if any OAuth refresh token not updated >60 days.
    # Prevents silent cascade failure if tokens expire during extended absence.
    # Phase 2.6 (2026-05-16): also monitor manually-rotated secrets (Anthropic + 3rd-party
    # API tokens) at a longer 120-day threshold. These don't auto-refresh and need human
    # rotation; surfacing staleness lets the operator schedule rotation proactively.
    OAUTH_SECRETS = [
        "life-platform/whoop",
        "life-platform/withings",
        "life-platform/strava",  # RE-ENABLED 2026-06-20
        # "life-platform/garmin",  # PAUSED 2026-06-03 — see SOURCES note (server-side refresh 429-blocked)
    ]
    MANUAL_ROTATION_SECRETS = [
        "life-platform/ai-keys",  # Anthropic — no rotation API; manual every 90d
        "life-platform/site-api-ai-key",  # Anthropic — separate key for site API
        "life-platform/eightsleep-client",
        "life-platform/notion",
        # "life-platform/dropbox",  # removed 2026-05-28 — secret soft-deleted
        "life-platform/todoist",
        "life-platform/ingestion-keys",  # COST-B bundle: Notion + Habitify + Todoist + Dropbox + HAE
    ]
    OAUTH_STALE_DAYS = int(os.environ.get("OAUTH_STALE_DAYS", "60"))
    MANUAL_ROTATION_STALE_DAYS = int(os.environ.get("MANUAL_ROTATION_STALE_DAYS", "120"))
    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        oauth_stale = []
        manual_stale = []
        for secret_name in OAUTH_SECRETS:
            try:
                meta = sm.describe_secret(SecretId=secret_name)
                last_changed = meta.get("LastChangedDate")
                if last_changed:
                    age_days = (now - last_changed.replace(tzinfo=timezone.utc)).days
                    if age_days > OAUTH_STALE_DAYS:
                        oauth_stale.append((secret_name, age_days))
                        logger.warning(
                            "OAuth token stale: %s last updated %d days ago",
                            secret_name,
                            age_days,
                        )
            except Exception as _se:
                logger.warning("Could not check OAuth secret %s: %s", secret_name, _se)
        # Phase 2.6 — manually-rotated secrets (Anthropic + 3rd-party API tokens)
        for secret_name in MANUAL_ROTATION_SECRETS:
            try:
                meta = sm.describe_secret(SecretId=secret_name)
                last_changed = meta.get("LastChangedDate")
                if last_changed:
                    age_days = (now - last_changed.replace(tzinfo=timezone.utc)).days
                    if age_days > MANUAL_ROTATION_STALE_DAYS:
                        manual_stale.append((secret_name, age_days))
                        logger.warning(
                            "Manual-rotation secret stale: %s last rotated %d days ago",
                            secret_name,
                            age_days,
                        )
            except Exception as _se:
                logger.warning("Could not check manual secret %s: %s", secret_name, _se)

        if oauth_stale:
            stale_list = "\n".join([f"  - {name}: {days} days since last update" for name, days in oauth_stale])
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject=f"⚠️ Life Platform: {len(oauth_stale)} OAuth token(s) may be expiring",
                    Message=(
                        f"⚠️ Life Platform: OAuth Token Health Warning\n\n"
                        f"The following OAuth secrets have not been updated in over {OAUTH_STALE_DAYS} days.\n"
                        f"Tokens may be at risk of expiring during extended absence:\n\n"
                        f"{stale_list}\n\n"
                        f"Action: trigger a manual data pull for each source to force a token refresh,\n"
                        f"or verify tokens are still valid in AWS Secrets Manager.\n\n"
                        f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                )
                logger.info("OAuth token health alert sent for %d secret(s)", len(oauth_stale))
            except Exception as _sns_e:
                logger.error("OAuth alert SNS publish failed: %s", _sns_e)

        # Phase 2.6: manual-rotation staleness alert (separate from OAuth)
        if manual_stale:
            stale_list = "\n".join([f"  - {name}: {days} days since last rotation" for name, days in manual_stale])
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject=f"⚠️ Life Platform: {len(manual_stale)} secret(s) due for manual rotation",
                    Message=(
                        f"⚠️ Life Platform: Manual Rotation Reminder\n\n"
                        f"The following secrets have not been rotated in over {MANUAL_ROTATION_STALE_DAYS} days.\n"
                        f"These are manually-rotated (no auto-rotation API available):\n\n"
                        f"{stale_list}\n\n"
                        f"Action: rotate via the source provider's portal, then update via\n"
                        f"`aws secretsmanager put-secret-value --secret-id <name> --secret-string ...`\n\n"
                        f"See docs/SECRETS_ROTATION.md for per-secret procedures.\n\n"
                        f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                )
                logger.info("Manual rotation alert sent for %d secret(s)", len(manual_stale))
            except Exception as _sns_e:
                logger.error("Manual rotation alert SNS publish failed: %s", _sns_e)

        # Emit CloudWatch metric for OAuth + manual-rotation token staleness
        cw.put_metric_data(
            Namespace="LifePlatform/Freshness",
            MetricData=[
                {"MetricName": "OAuthTokenStaleCount", "Value": float(len(oauth_stale)), "Unit": "Count"},
                {"MetricName": "ManualRotationStaleCount", "Value": float(len(manual_stale)), "Unit": "Count"},
            ],
        )

    except Exception as _oauth_e:
        logger.error("OAuth/manual token health check failed (non-fatal): %s", _oauth_e)

    # ── D-4 (#468): per-datatype HAE liveness — compute + store so a months-dark
    # sensor (CGM/BP/SoM/workouts/water) is visible instead of hidden behind a single
    # "apple_health: fresh". /api/source_freshness reads the stored map.
    _ah_pk = f"USER#{USER_ID}#SOURCE#apple_health"
    try:
        _dt_liveness = check_apple_health_datatypes(table, now)
        if _dt_liveness is not None:
            table.put_item(
                Item={
                    "pk": _ah_pk,
                    "sk": _HAE_LIVENESS_SK,
                    "datatypes": _dt_liveness,
                    "computed_at": now.isoformat(),
                    "dark_count": sum(1 for d in _dt_liveness if d["dark"]),
                }
            )
            logger.info("HAE datatype liveness stored: %d dark of %d", sum(1 for d in _dt_liveness if d["dark"]), len(_dt_liveness))
    except Exception as _dl_e:
        logger.error("HAE datatype liveness compute/store failed (non-fatal): %s", _dl_e)

    # ── DI-1.6: Apple Health activity-integrity guard (the silent-413 blind spot) ──
    ah_degraded = False
    try:
        ah_alert, ah_metrics = check_apple_health_activity(table, now, _sick_suppress)
        ah_degraded = bool(ah_metrics.get("degraded"))
        # D-8 (#468): episode-based dedup. The alert used to publish on EVERY run that
        # found degradation (36 sends in 72h). Now: send once when the episode opens,
        # then at most one daily reminder, and go quiet on recovery — regardless of how
        # often the checker is invoked (async retries / SNS fanout can't amplify it).
        _prior = {}
        try:
            # ConsistentRead: the dedup verdict depends on the just-written state, so a
            # stale replica read could re-fire the alert. (Belt-and-suspenders — the cron
            # is 24h apart in prod, but correctness shouldn't rest on that.)
            _prior = (table.get_item(Key={"pk": _ah_pk, "sk": _AH_ALERT_STATE_SK}, ConsistentRead=True).get("Item")) or {}
        except Exception as _se:
            logger.warning("alert-state read failed (fail-open to send): %s", _se)
        _should_send, _new_state, _kind = alert_episode_decision(_prior, ah_degraded, now)
        try:
            table.put_item(Item={"pk": _ah_pk, "sk": _AH_ALERT_STATE_SK, **_new_state})
        except Exception as _we:
            logger.error("alert-state write failed (non-fatal): %s", _we)
        if ah_alert and _should_send:
            try:
                _subj = "⚠️ Life Platform: Apple Health activity-stream gap"
                if _kind == "reminder":
                    _subj += " (ongoing)"
                sns.publish(TopicArn=SNS_ARN, Subject=_subj, Message=ah_alert)
                logger.info("Apple Health activity-integrity alert sent (episode=%s)", _kind)
            except Exception as _ae:
                logger.error("Apple Health activity alert SNS publish failed: %s", _ae)
        elif ah_alert:
            logger.info("Apple Health activity degraded but alert held (episode=%s, no re-fire)", _kind)
        try:
            cw.put_metric_data(
                Namespace="LifePlatform/Freshness",
                MetricData=[
                    {"MetricName": "AppleHealthStepsLagDays", "Value": ah_metrics["steps_lag_days"], "Unit": "Count"},
                    {"MetricName": "AppleHealthLowStepDays7d", "Value": ah_metrics["low_step_days"], "Unit": "Count"},
                    {"MetricName": "AppleHealthActivityDegraded", "Value": ah_metrics["degraded"], "Unit": "Count"},
                ],
            )
        except Exception as _me:
            logger.error("Apple Health activity metric emit failed (non-fatal): %s", _me)
    except Exception as _ah_e:
        logger.error("Apple Health activity-integrity check failed (non-fatal): %s", _ah_e)

    return {
        "statusCode": 200,
        "apple_health_activity_degraded": ah_degraded,
        "stale_count": len(stale_sources),
        "stale_sources": [s[0] for s in stale_sources],
        "partial_count": len(partial_sources),
        "partial_sources": [s[0] for s in partial_sources],
        "warning_count": len(warning_sources),
        "warning_sources": [s[0] for s in warning_sources],
        "checked_at": now.isoformat(),
    }
