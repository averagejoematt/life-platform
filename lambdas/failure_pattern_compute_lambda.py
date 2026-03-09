"""
Failure Pattern Compute Lambda — IC-4 v1.0.0
Scheduled weekly on Sundays at 9:50 AM PT (17:50 UTC via EventBridge).

Scans the past 7 days of computed_metrics. For each day where any
component scores below 50 (failing), fetches contextual conditions —
recovery, stress, task load, training load — and runs a Haiku synthesis
pass to identify recurring failure patterns.

Stores results to platform_memory as MEMORY#failure_pattern#<date> records.
These are consumed by daily_insight_compute_lambda.py → build_memory_context()
which injects them into every Daily Brief AI call.

Data flow:
  computed_metrics (7d)    ─┐
  whoop (recovery/HRV)     ─┤
  todoist (task count)     ─┼─→ Haiku synthesis → platform_memory (failure_pattern)
  notion (journal stress)  ─┤        ↓
  tsb (from computed)      ─┘  daily_insight_compute reads on next run

Schedule: Sunday 9:50 AM PT (after daily-metrics-compute + daily-insight-compute)

v1.0.0 — 2026-03-09
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import urllib.request

import boto3

try:
    from platform_logger import get_logger
    logger = get_logger("failure-pattern-compute")
except ImportError:
    logger = logging.getLogger("failure-pattern-compute")
    logger.setLevel(logging.INFO)

_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

ANTHROPIC_API  = "https://api.anthropic.com/v1/messages"
_api_key_cache = None

AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# Component threshold below which a day is considered "failing" for that component
FAILURE_THRESHOLD = 50

# Minimum occurrences of a pattern across 7 days before it's worth logging
MIN_PATTERN_OCCURRENCES = 2

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ==============================================================================
# HELPERS
# ==============================================================================

def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def safe_float(rec, field, default=None):
    if rec and field in rec:
        try:   return float(rec[field])
        except Exception: return default
    return default


def fetch_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        return d2f(r.get("Item"))
    except Exception as e:
        logger.warning("fetch_date(%s, %s): %s", source, date_str, e)
        return None


def fetch_range(source, start, end):
    try:
        records = []
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {":pk": USER_PREFIX + source,
                                          ":s": "DATE#" + start, ":e": "DATE#" + end},
        }
        while True:
            r = table.query(**kwargs)
            records.extend(d2f(i) for i in r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning("fetch_range(%s): %s", source, e)
        return []


def fetch_journal_entries_for_date(date_str):
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX + "notion",
                ":s": f"DATE#{date_str}#journal",
                ":e": f"DATE#{date_str}#journal#~",
            },
        )
        return [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning("fetch_journal(%s): %s", date_str, e)
        return []


def _get_api_key():
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    secrets_client = boto3.client("secretsmanager", region_name=_REGION)
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
    resp = secrets_client.get_secret_value(SecretId=secret_name)
    creds = json.loads(resp["SecretString"])
    _api_key_cache = creds.get("anthropic_api_key") or creds.get("ANTHROPIC_API_KEY")
    return _api_key_cache


# ==============================================================================
# CONTEXTUAL DATA FETCHER
# ==============================================================================

def fetch_context_for_date(date_str):
    """Fetch the contextual conditions for a given date.

    Returns a compact dict capturing the conditions under which failures occurred.
    Used to identify what was different on bad days vs good days.
    """
    ctx = {"date": date_str}

    # Day of week
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        ctx["day_of_week"] = DAY_NAMES[dt.weekday()]
    except Exception:
        pass

    # Recovery + HRV from Whoop
    whoop = fetch_date("whoop", date_str)
    if whoop:
        rec = safe_float(whoop, "recovery_score")
        hrv = safe_float(whoop, "hrv")
        sleep_hrs = safe_float(whoop, "sleep_duration_hours")
        if rec is not None:   ctx["recovery_score"] = round(rec)
        if hrv is not None:   ctx["hrv"] = round(hrv, 1)
        if sleep_hrs is not None: ctx["sleep_hours"] = round(sleep_hrs, 1)

    # Todoist — task load
    todoist = fetch_date("todoist", date_str)
    if todoist:
        completed = todoist.get("tasks_completed_today", 0)
        total     = todoist.get("tasks_total", 0)
        overdue   = todoist.get("tasks_overdue", 0)
        if completed is not None:
            ctx["tasks_completed"] = int(completed)
        if total is not None and total:
            ctx["tasks_total"] = int(total)
        if overdue is not None and overdue:
            ctx["tasks_overdue"] = int(overdue)

    # Journal stress
    journal_entries = fetch_journal_entries_for_date(date_str)
    if journal_entries:
        stress_vals = []
        for e in journal_entries:
            s = safe_float(e, "enriched_stress") or safe_float(e, "stress_level")
            if s is not None:
                stress_vals.append(s)
        if stress_vals:
            ctx["journal_stress_avg"] = round(sum(stress_vals) / len(stress_vals), 1)
        mood_vals = [safe_float(e, "enriched_mood") or safe_float(e, "morning_mood")
                     for e in journal_entries]
        mood_vals = [m for m in mood_vals if m is not None]
        if mood_vals:
            ctx["journal_mood_avg"] = round(sum(mood_vals) / len(mood_vals), 1)

    # MacroFactor — logged calories (signal for tracking gaps)
    mf = fetch_date("macrofactor", date_str)
    if mf:
        cal   = safe_float(mf, "total_calories_kcal")
        items = len(mf.get("food_log", []))
        if cal is not None:
            ctx["calories_logged"] = int(cal)
        ctx["food_items_logged"] = items

    return ctx


# ==============================================================================
# FAILURE DAY EXTRACTOR
# ==============================================================================

def extract_failure_days(computed_records_7d):
    """Return list of dicts for days where at least one component scored below FAILURE_THRESHOLD."""
    failure_days = []
    for rec in computed_records_7d:
        date_str = rec.get("date") or rec.get("sk", "").replace("DATE#", "")
        if not date_str:
            continue
        comp_scores = rec.get("component_scores", {})
        failing = []
        for comp, score in comp_scores.items():
            if score is not None and float(score) < FAILURE_THRESHOLD:
                failing.append((comp, round(float(score))))
        if failing:
            failure_days.append({
                "date":       date_str,
                "failing":    failing,
                "all_scores": {k: round(float(v)) for k, v in comp_scores.items() if v is not None},
                "day_grade":  round(float(rec["day_grade_score"])) if rec.get("day_grade_score") else None,
            })
    return failure_days


# ==============================================================================
# HAIKU SYNTHESIS
# ==============================================================================

def synthesize_patterns_haiku(failure_records, api_key):
    """Haiku synthesis: identify recurring failure patterns from 7 days of failure data.

    Returns list of pattern dicts:
      [{component, pattern, conditions, frequency, severity, suggestion}]
    Returns [] on any failure.
    """
    if not failure_records:
        return []

    lines = []
    for rec in failure_records:
        ctx   = rec.get("context", {})
        fails = rec.get("failing", [])
        fail_str = ", ".join(f"{comp} ({score})" for comp, score in fails)
        ctx_parts = []
        for key in ("day_of_week", "recovery_score", "hrv", "sleep_hours",
                    "journal_stress_avg", "journal_mood_avg",
                    "tasks_completed", "tasks_overdue", "calories_logged", "food_items_logged"):
            if key in ctx:
                ctx_parts.append(f"{key}={ctx[key]}")
        lines.append(f"[{rec['date']}] failed: {fail_str} | context: {', '.join(ctx_parts)}")

    data_block = "\n".join(lines)

    prompt = f"""Analyze this 7-day failure log from a personal health platform. Identify recurring patterns.

FAILURE DATA (days where health components scored below 50/100):
{data_block}

TASK: Identify 1-4 specific, actionable failure patterns. A pattern requires:
- Same or related component(s) failing
- Shared contextual conditions (day of week, low recovery, high task load, poor sleep, etc.)
- Minimum 2 occurrences

For each pattern, produce a JSON object:
{{
  "component": "nutrition|sleep_quality|recovery|movement|habits_mvp|hydration|journal",
  "pattern": "One sentence: what fails and when/why",
  "conditions": ["list", "of", "triggering", "conditions"],
  "frequency": "X/7 days",
  "severity": "critical|moderate|mild",
  "suggestion": "One specific behavior change to address this pattern"
}}

Rules:
- Be specific to the actual data — don't generate generic health advice
- Only patterns supported by 2+ days of data
- If no clear patterns, return empty array
- Keep pattern text under 25 words, suggestion under 20 words

Return ONLY a JSON array, no preamble or markdown."""

    payload = json.dumps({
        "model": AI_MODEL_HAIKU,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        ANTHROPIC_API, data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read())["content"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            return json.loads(raw.strip())
    except Exception as e:
        logger.warning("Haiku synthesis failed: %s", e)
        return []


# ==============================================================================
# PATTERN STORE
# ==============================================================================

def store_failure_patterns(run_date_str, patterns, failure_days_count, week_start_str):
    """Write failure pattern records to platform_memory.

    One record per pattern, keyed by run date + pattern index.
    Idempotent on rerun (same SK overwrites).
    """
    stored = 0
    for i, p in enumerate(patterns):
        component    = p.get("component", "unknown")
        pattern_text = p.get("pattern", "")
        if not pattern_text:
            continue

        sk = f"MEMORY#failure_pattern#{run_date_str}#{i}"
        item = {
            "pk":                   USER_PREFIX + "platform_memory",
            "sk":                   sk,
            "category":             "failure_pattern",
            "date":                 run_date_str,
            "week_start":           week_start_str,
            "component":            component,
            "pattern":              pattern_text,
            "conditions":           json.dumps(p.get("conditions", [])),
            "frequency":            p.get("frequency", ""),
            "severity":             p.get("severity", "moderate"),
            "suggestion":           p.get("suggestion", ""),
            "failure_days_scanned": failure_days_count,
            "stored_at":            datetime.now(timezone.utc).isoformat(),
        }
        item = {k: v for k, v in item.items() if v is not None and v != ""}
        table.put_item(Item=item)
        stored += 1
        logger.info("Stored failure_pattern[%d]: %s — %s", i, component, pattern_text[:60])

    return stored


# ==============================================================================
# HANDLER
# ==============================================================================

def lambda_handler(event, context):
    logger.info("Failure Pattern Compute v1.0.0 starting...")

    today = datetime.now(timezone.utc).date()

    if event.get("week_end"):
        week_end = datetime.strptime(event["week_end"], "%Y-%m-%d").date()
    else:
        week_end = today - timedelta(days=1)

    week_start = week_end - timedelta(days=6)
    run_date_str   = today.isoformat()
    week_start_str = week_start.isoformat()

    logger.info("Analyzing failure patterns for %s -> %s", week_start_str, week_end.isoformat())

    # Idempotency: skip if already ran today (unless force=True)
    if not event.get("force"):
        try:
            existing = table.query(
                KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
                ExpressionAttributeValues={
                    ":pk": USER_PREFIX + "platform_memory",
                    ":s": f"MEMORY#failure_pattern#{run_date_str}",
                    ":e": f"MEMORY#failure_pattern#{run_date_str}#~",
                },
                Limit=1,
            )
            if existing.get("Items"):
                logger.info("Already ran failure_pattern for %s — skipping (use force=true)", run_date_str)
                return {"statusCode": 200, "body": "Already ran today", "skipped": True}
        except Exception as e:
            logger.warning("Idempotency check failed (non-fatal): %s", e)

    # 1. Load computed_metrics for the week
    computed_7d = fetch_range("computed_metrics", week_start_str, week_end.isoformat())
    logger.info("Loaded %d computed_metrics records", len(computed_7d))

    if not computed_7d:
        logger.info("No computed_metrics data for %s->%s — exiting", week_start_str, week_end.isoformat())
        return {"statusCode": 200, "body": "No data", "failure_days": 0, "patterns_stored": 0}

    # 2. Extract failure days
    failure_days = extract_failure_days(computed_7d)
    logger.info("Failure days (any component < %d): %d / %d",
                FAILURE_THRESHOLD, len(failure_days), len(computed_7d))

    if len(failure_days) < MIN_PATTERN_OCCURRENCES:
        logger.info("Fewer than %d failure days — no patterns to identify", MIN_PATTERN_OCCURRENCES)
        return {
            "statusCode": 200,
            "body": f"Only {len(failure_days)} failure day(s) — no patterns",
            "failure_days": len(failure_days),
            "patterns_stored": 0,
        }

    # 3. Enrich failure days with contextual data
    enriched = []
    for fd in failure_days:
        date_str = fd["date"]
        ctx = fetch_context_for_date(date_str)
        enriched.append({**fd, "context": ctx})
        logger.info("Context for %s: %s", date_str,
                    {k: v for k, v in ctx.items() if k != "date"})

    # 4. Haiku synthesis
    try:
        api_key = _get_api_key()
    except Exception as e:
        logger.error("Could not load API key: %s", e)
        return {"statusCode": 500, "body": f"API key error: {e}"}

    patterns = synthesize_patterns_haiku(enriched, api_key)
    logger.info("Haiku identified %d pattern(s)", len(patterns))
    for p in patterns:
        logger.info("  [%s] %s | %s | %s",
                    p.get("severity", "?"), p.get("component", "?"),
                    p.get("pattern", "")[:60], p.get("frequency", ""))

    # 5. Store to platform_memory
    stored = 0
    if patterns:
        stored = store_failure_patterns(run_date_str, patterns, len(failure_days), week_start_str)

    logger.info("Done: %d failure days -> %d patterns stored", len(failure_days), stored)

    return {
        "statusCode":      200,
        "body":            f"Failure patterns computed for week of {week_start_str}",
        "week_start":      week_start_str,
        "week_end":        week_end.isoformat(),
        "failure_days":    len(failure_days),
        "patterns_found":  len(patterns),
        "patterns_stored": stored,
        "failure_summary": [
            {"date": fd["date"], "components": [c for c, _ in fd["failing"]]}
            for fd in failure_days
        ],
    }
