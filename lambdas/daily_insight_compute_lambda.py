"""
Daily Insight Compute Lambda — IC-2 v1.0.0
Scheduled at 9:42 AM PT (17:42 UTC via EventBridge).

Transforms raw pre-computed metrics into curated coaching intelligence
for the Daily Brief's AI calls. Bridges the gap between data and insight:
the Brief's AI calls stop getting raw numbers and start getting context.

Reads from (already computed by 9:40 AM):
  - SOURCE#computed_metrics    — day grade, component scores, readiness (7-day history)
  - SOURCE#habit_scores        — tier-level completion rates (7-day history)
  - SOURCE#day_grade           — 14-day grade history for momentum trend
  - SOURCE#platform_memory     — coaching_calibration, what_worked, failure_pattern

Writes to:
  - SOURCE#computed_insights   — structured intelligence record

Output consumed by:
  - ai_calls.py: all 4 AI calls inject `ai_context_block` as platform intelligence

Schedule:
  9:40 AM PT  daily-metrics-compute  (writes computed_metrics + habit_scores)
  9:42 AM PT  daily-insight-compute  ← this Lambda
  10:00 AM PT daily-brief            (reads computed_insights via data["computed_insights"])

v1.0.0 — 2026-03-07
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME  = os.environ.get("TABLE_NAME", "life-platform")
USER_ID     = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)


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


def fetch_profile():
    try:
        r = table.get_item(Key={"pk": PROFILE_PK, "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.error("fetch_profile: %s", e)
        return {}


def fetch_memory_records(category, days=30):
    """Load platform_memory records for a given category."""
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    pk = USER_PREFIX + "platform_memory"
    start_sk = f"MEMORY#{category}#{start}"
    end_sk   = f"MEMORY#{category}#~"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": pk, ":s": start_sk, ":e": end_sk},
            ScanIndexForward=False,
            Limit=5,
        )
        return [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning("fetch_memory(%s): %s", category, e)
        return []


# ==============================================================================
# MOMENTUM COMPUTATION
# ==============================================================================

def compute_momentum(grade_records_14d, yesterday_str):
    """Compare this week vs last week average grade.

    Returns: (signal, this_week_avg, prev_week_avg, trend_pct)
    """
    week_boundary = (
        datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    this_week, prev_week = [], []
    for rec in grade_records_14d:
        date_str = rec.get("date", "") or rec.get("sk", "").replace("DATE#", "")
        # Handle computed_metrics records (day_grade_score) and day_grade records (total_score)
        score = safe_float(rec, "day_grade_score") or safe_float(rec, "total_score")
        if score is None:
            continue
        if date_str > week_boundary:
            this_week.append(score)
        else:
            prev_week.append(score)

    this_avg = round(sum(this_week) / len(this_week), 1) if this_week else None
    prev_avg = round(sum(prev_week) / len(prev_week), 1) if prev_week else None

    if this_avg is None:
        return "unknown", None, None, None
    if prev_avg is None:
        return "stable", this_avg, None, None

    trend_pct = round((this_avg - prev_avg) / max(prev_avg, 1) * 100, 1)
    if trend_pct > 5:
        signal = "improving"
    elif trend_pct < -5:
        signal = "declining"
    else:
        signal = "stable"

    return signal, this_avg, prev_avg, trend_pct


# ==============================================================================
# METRIC TREND DETECTION
# ==============================================================================

def detect_metric_trends(computed_records_7d):
    """Detect 3+ consecutive day runs in key metrics (leading indicators).

    Uses pre-computed records so this is cheap — no raw DDB reads needed.
    Returns: (declining_list, improving_list), each item:
      {metric, consecutive_days, current, baseline_7d_avg, delta_pct}
    """
    # Metrics to track at the top level
    TOP_METRICS = ["day_grade_score", "readiness_score"]
    # Component score keys inside component_scores dict
    COMP_METRICS = ["sleep_quality", "recovery", "nutrition", "movement", "habits_mvp"]

    # Build date-ordered time series per metric
    series = {m: [] for m in TOP_METRICS + COMP_METRICS}
    for rec in sorted(computed_records_7d, key=lambda x: x.get("date", "")):
        date_str = rec.get("date") or rec.get("sk", "").replace("DATE#", "")
        comp_scores = rec.get("component_scores", {})
        for m in TOP_METRICS:
            val = safe_float(rec, m)
            if val is not None:
                series[m].append((date_str, val))
        for m in COMP_METRICS:
            val = safe_float(comp_scores, m)
            if val is not None:
                series[m].append((date_str, val))

    declining, improving = [], []
    for metric, pts in series.items():
        if len(pts) < 3:
            continue
        recent = pts[-3:]
        baseline_7d = round(sum(v for _, v in pts) / len(pts), 1)

        if all(recent[i][1] < recent[i - 1][1] for i in range(1, len(recent))):
            delta_pct = round((recent[-1][1] - recent[0][1]) / max(recent[0][1], 1) * 100, 1)
            declining.append({
                "metric": metric,
                "consecutive_days": 3,
                "current": round(recent[-1][1]),
                "baseline_7d_avg": baseline_7d,
                "delta_pct": delta_pct,
            })

        elif all(recent[i][1] > recent[i - 1][1] for i in range(1, len(recent))):
            delta_pct = round((recent[-1][1] - recent[0][1]) / max(recent[0][1], 1) * 100, 1)
            improving.append({
                "metric": metric,
                "consecutive_days": 3,
                "current": round(recent[-1][1]),
                "baseline_7d_avg": baseline_7d,
                "delta_pct": delta_pct,
            })

    return declining, improving


# ==============================================================================
# HABIT PATTERN ANALYSIS
# ==============================================================================

def compute_habit_patterns(habit_score_records_7d, profile):
    """Compute 7-day habit miss rates from pre-computed habit_scores records.

    habit_scores records contain tier0/1 completion at the aggregate level, but
    also missed_tier0 lists and synergy_groups. We use those for pattern detection.

    Returns: (miss_rates, strongest_habits, weakest_habits, missed_tier0_frequency)
    """
    registry = profile.get("habit_registry", {})
    if not registry or not habit_score_records_7d:
        return {}, [], [], {}

    # Aggregate missed T0 habits across all 7 records
    t0_miss_counts = {}
    t0_total_days = 0
    for rec in habit_score_records_7d:
        missed = rec.get("missed_tier0") or []
        t0_total_days += 1
        for h in missed:
            t0_miss_counts[h] = t0_miss_counts.get(h, 0) + 1

    # Miss rate per T0 habit (how often missed in last 7 days)
    miss_rates = {}
    if t0_total_days > 0:
        for h, count in t0_miss_counts.items():
            miss_rates[h] = round(count / t0_total_days, 2)

    # Also track T1 habits from tier_status in component_details (if available)
    # For now we use tier0 miss rates as the primary signal

    # Identify synergy group health
    synergy_avg = {}
    for rec in habit_score_records_7d:
        sg = rec.get("synergy_groups") or {}
        for group, pct in sg.items():
            synergy_avg.setdefault(group, []).append(float(pct))
    synergy_health = {g: round(sum(v) / len(v), 2) for g, v in synergy_avg.items()}

    # Tier 0 completion rates from records
    t0_completion_rates = {}
    for name, meta in registry.items():
        if meta.get("status") != "active" or meta.get("tier", 2) != 0:
            continue
        days_missed = t0_miss_counts.get(name, 0)
        days_available = t0_total_days
        if days_available > 0:
            completion_rate = 1 - days_missed / days_available
            t0_completion_rates[name] = round(completion_rate, 2)

    strongest = [h for h, r in sorted(t0_completion_rates.items(), key=lambda x: -x[1])
                 if r >= 0.8][:5]
    weakest   = [h for h, r in sorted(t0_completion_rates.items(), key=lambda x: x[1])
                 if r <= 0.4][:5]

    return miss_rates, strongest, weakest, synergy_health


# ==============================================================================
# PLATFORM MEMORY CONTEXT BUILDER
# ==============================================================================

def build_memory_context():
    """Load relevant platform memory records and format as coaching context string.

    Prioritizes: coaching_calibration > what_worked > failure_pattern.
    Returns empty string if no records exist yet.
    """
    lines = []

    calibration = fetch_memory_records("coaching_calibration", days=90)
    if calibration:
        latest = calibration[0]
        note = latest.get("note") or latest.get("content") or ""
        if isinstance(note, dict):
            note = json.dumps(note)
        if note:
            lines.append(f"COACHING CALIBRATION: {str(note)[:200]}")

    what_worked = fetch_memory_records("what_worked", days=60)
    if what_worked:
        lines.append("WHAT HAS WORKED (recent episodes):")
        for rec in what_worked[:2]:
            conditions = rec.get("conditions", "")
            behaviors  = rec.get("behaviors", "")
            outcomes   = rec.get("outcomes", "")
            if conditions or behaviors:
                lines.append(f"  When {conditions}: {behaviors} → {outcomes}"[:150])

    failure_patterns = fetch_memory_records("failure_pattern", days=60)
    if failure_patterns:
        lines.append("KNOWN FAILURE PATTERNS:")
        for rec in failure_patterns[:2]:
            pattern = rec.get("pattern") or rec.get("note") or ""
            if isinstance(pattern, dict):
                pattern = json.dumps(pattern)
            if pattern:
                lines.append(f"  {str(pattern)[:120]}")

    return "\n".join(lines)


# ==============================================================================
# AI CONTEXT BLOCK ASSEMBLY
# ==============================================================================

def build_ai_context_block(momentum_signal, this_week_avg, prev_week_avg, trend_pct,
                            declining, improving, miss_rates, strongest, weakest,
                            synergy_health, memory_ctx):
    """Assemble the compact text block injected into all Daily Brief AI prompts."""
    lines = ["PLATFORM INTELLIGENCE (7-day context, pre-computed):"]

    # Momentum
    if this_week_avg is not None:
        if momentum_signal == "improving" and trend_pct is not None:
            lines.append(f"📈 Momentum: IMPROVING ({prev_week_avg}→{this_week_avg} avg grade, +{trend_pct}% week-over-week)")
        elif momentum_signal == "declining" and trend_pct is not None:
            lines.append(f"📉 Momentum: DECLINING ({prev_week_avg}→{this_week_avg} avg grade, {trend_pct}% week-over-week)")
        else:
            lines.append(f"➡️ Momentum: STABLE (avg grade: {this_week_avg})")

    # Leading indicators — declining first (more urgent)
    for d in declining[:2]:
        m = d["metric"].replace("_", " ")
        lines.append(f"⚠️ LEADING INDICATOR: {m} declining {d['consecutive_days']} days straight (now {d['current']} vs {d['baseline_7d_avg']} avg, {d['delta_pct']}%)")

    for imp in improving[:2]:
        m = imp["metric"].replace("_", " ")
        lines.append(f"✅ POSITIVE SIGNAL: {m} improving {imp['consecutive_days']} days straight (now {imp['current']} vs {imp['baseline_7d_avg']} avg, +{imp['delta_pct']}%)")

    # Habit patterns
    if weakest:
        habit_detail = []
        for h in weakest[:3]:
            miss_rate = miss_rates.get(h)
            days_missed = round(miss_rate * 7) if miss_rate else "?"
            habit_detail.append(f"{h} (missed {days_missed}/7 days)")
        lines.append(f"🔴 Weakest T0 habits: {', '.join(habit_detail)}")

    if strongest:
        lines.append(f"💪 Strongest habits: {', '.join(strongest[:3])}")

    # Synergy group issues
    broken_synergies = [g for g, h in synergy_health.items() if h < 0.5]
    if broken_synergies:
        lines.append(f"⚡ Broken synergy stacks: {', '.join(broken_synergies)}")

    # Platform memory (coaching calibration, what worked)
    if memory_ctx:
        lines.append("")
        lines.append(memory_ctx)

    lines.append("INSTRUCTION: Reference this intelligence in coaching. Name the specific patterns, "
                 "causal chains, and leading indicators above — don't just list them, connect them.")

    return "\n".join(lines)


# ==============================================================================
# STORE
# ==============================================================================

def _to_dec(val):
    if val is None: return None
    return Decimal(str(round(float(val), 4)))


def store_computed_insights(yesterday_str, payload):
    """Write computed_insights record to DynamoDB."""
    item = {
        "pk":          USER_PREFIX + "computed_insights",
        "sk":          "DATE#" + yesterday_str,
        "date":        yesterday_str,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Scalar fields
    for key in ("momentum_signal", "ai_context_block", "memory_context"):
        if payload.get(key) is not None:
            item[key] = payload[key]

    for key in ("week_grade_avg", "prev_week_grade_avg", "grade_trend_pct"):
        if payload.get(key) is not None:
            item[key] = _to_dec(payload[key])

    # Lists of dicts (serialize as JSON strings for DDB compatibility)
    for key in ("declining_metrics", "improving_metrics"):
        if payload.get(key):
            item[key] = json.dumps(payload[key])

    if payload.get("miss_rates"):
        item["habit_miss_rates_7d"] = json.dumps(payload["miss_rates"])
    if payload.get("strongest"):
        item["strongest_habits"] = payload["strongest"]
    if payload.get("weakest"):
        item["weakest_habits"] = payload["weakest"]
    if payload.get("synergy_health"):
        item["synergy_health"] = json.dumps(payload["synergy_health"])

    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=item)
    logger.info("Stored computed_insights for %s (momentum=%s, declining=%d, improving=%d)",
                yesterday_str, payload.get("momentum_signal"),
                len(payload.get("declining_metrics", [])),
                len(payload.get("improving_metrics", [])))


# ==============================================================================
# HANDLER
# ==============================================================================

def lambda_handler(event, context):
    logger.info("Daily Insight Compute v1.0.0 starting...")

    today = datetime.now(timezone.utc).date()
    yesterday_str = event.get("date") or (today - timedelta(days=1)).isoformat()

    # Idempotency check (skip unless force=True)
    if not event.get("force"):
        existing = fetch_date("computed_insights", yesterday_str)
        if existing:
            logger.info("Already computed insights for %s — skipping (use force=true to override)", yesterday_str)
            return {"statusCode": 200, "body": f"Already computed for {yesterday_str}", "skipped": True}

    profile = fetch_profile()

    # ── 1. Load pre-computed records ──
    computed_7d = fetch_range("computed_metrics",
                              (today - timedelta(days=7)).isoformat(),
                              yesterday_str)
    habit_7d    = fetch_range("habit_scores",
                              (today - timedelta(days=7)).isoformat(),
                              yesterday_str)
    grade_14d   = fetch_range("day_grade",
                              (today - timedelta(days=14)).isoformat(),
                              yesterday_str)

    logger.info("Loaded: %d computed_metrics, %d habit_scores, %d day_grade records",
                len(computed_7d), len(habit_7d), len(grade_14d))

    # ── 2. Momentum ──
    momentum_signal, this_week_avg, prev_week_avg, trend_pct = compute_momentum(
        grade_14d, yesterday_str)
    logger.info("Momentum: %s (this_week=%.1f, prev_week=%s, trend=%s%%)",
                momentum_signal, this_week_avg or 0,
                prev_week_avg, trend_pct)

    # ── 3. Metric trends ──
    declining, improving = detect_metric_trends(computed_7d)
    logger.info("Declining metrics: %s | Improving: %s",
                [d["metric"] for d in declining], [i["metric"] for i in improving])

    # ── 4. Habit patterns ──
    miss_rates, strongest, weakest, synergy_health = compute_habit_patterns(
        habit_7d, profile)
    logger.info("Weakest T0 habits: %s | Strongest: %s", weakest[:3], strongest[:3])

    # ── 5. Platform memory context ──
    memory_ctx = build_memory_context()

    # ── 6. Assemble AI context block ──
    ai_block = build_ai_context_block(
        momentum_signal, this_week_avg, prev_week_avg, trend_pct,
        declining, improving, miss_rates, strongest, weakest,
        synergy_health, memory_ctx)
    logger.info("AI context block: %d chars", len(ai_block))

    # ── 7. Store ──
    payload = {
        "momentum_signal":    momentum_signal,
        "week_grade_avg":     this_week_avg,
        "prev_week_grade_avg": prev_week_avg,
        "grade_trend_pct":    trend_pct,
        "declining_metrics":  declining,
        "improving_metrics":  improving,
        "miss_rates":         miss_rates,
        "strongest":          strongest,
        "weakest":            weakest,
        "synergy_health":     synergy_health,
        "memory_context":     memory_ctx,
        "ai_context_block":   ai_block,
    }
    store_computed_insights(yesterday_str, payload)

    return {
        "statusCode": 200,
        "body": f"Insights computed for {yesterday_str}",
        "momentum": momentum_signal,
        "declining_count": len(declining),
        "improving_count": len(improving),
        "weakest_habits": weakest[:3],
    }
