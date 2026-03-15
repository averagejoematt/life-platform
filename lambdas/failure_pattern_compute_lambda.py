"""
failure_pattern_compute_lambda.py — IC-4: Failure Pattern Recognition

Identifies recurring failure patterns from behavioral + outcome data.
Writes structured pattern records to SOURCE#platform_memory for use
by coaching AI in Daily Brief and Weekly Digest.

DATA GATE: Requires 6-8 weeks of behavioral data before meaningful patterns
emerge. Scheduled to activate ~2026-05-01.

WHAT IT DETECTS:
  - Habit completion → outcome correlations (which skips predict bad days)
  - Time-of-week failure clusters (e.g. Sundays, post-travel)
  - Cascade patterns (e.g. poor sleep → skip workout → overeat)
  - Rebound speed after bad days (how quickly Matthew recovers)
  - External trigger patterns (travel, social events, stress spikes)

DynamoDB writes:
  SOURCE#platform_memory   MEMORY#failure_patterns#YYYY-MM-DD

SCHEDULE: Sunday 11:45 AM PT (after weekly correlations, before hypothesis engine)
  EventBridge: cron(45 18 ? * SUN *)

v0.1.0 — 2026-03-15 (IC-4 skeleton — data-gated ~2026-05-01)
"""

import json
import os
import logging
import boto3
from datetime import datetime, timedelta

try:
    from platform_logger import get_logger
    logger = get_logger("failure-pattern-compute")
except ImportError:
    logger = logging.getLogger("failure-pattern-compute")
    logger.setLevel(logging.INFO)

_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# ── Data gate ────────────────────────────────────────────────────────────────
# Minimum days of behavioral data required before patterns are meaningful.
# Below this threshold, the Lambda exits early with a data_gate_not_met signal.
MIN_DAYS_REQUIRED = 42   # 6 weeks

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATE CHECK
# ══════════════════════════════════════════════════════════════════════════════

def _check_data_gate():
    """Return (ok: bool, days_available: int) for the habit_scores partition."""
    try:
        today      = datetime.utcnow().strftime("%Y-%m-%d")
        gate_start = (datetime.utcnow() - timedelta(days=MIN_DAYS_REQUIRED)).strftime("%Y-%m-%d")
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":pk":    f"{USER_PREFIX}habit_scores",
                ":start": f"DATE#{gate_start}",
                ":end":   f"DATE#{today}",
            },
            Select="COUNT",
        )
        days = resp.get("Count", 0)
        return days >= MIN_DAYS_REQUIRED, days
    except Exception as e:
        logger.warning(f"[IC-4] data gate check failed: {e}")
        return False, 0


# ══════════════════════════════════════════════════════════════════════════════
# PATTERN DETECTORS
# ══════════════════════════════════════════════════════════════════════════════

def _detect_habit_skip_predictors(habit_records, outcome_records):
    """
    Identify which habit skips most reliably predict bad outcome days.

    Method: For each habit, compute:
      - skip_bad_rate: P(bad day | habit skipped)
      - complete_good_rate: P(good day | habit completed)
      - lift: skip_bad_rate / baseline_bad_rate

    Returns top 3 highest-lift habits as failure predictors.

    IC-4: correlational framing only — AI-2 compliance.
    """
    # TODO: Implement when data gate met (~2026-05-01)
    # Pseudocode:
    #   for each habit in habit_records:
    #     skip_days = days where habit not completed
    #     bad_days_after_skip = outcome_records where date in skip_days and day_grade < 60
    #     skip_bad_rate = bad_days_after_skip / len(skip_days)
    #     lift = skip_bad_rate / baseline_bad_rate
    #   return sorted by lift, top 3
    return []


def _detect_cascade_patterns(habit_records, outcome_records, sleep_records):
    """
    Detect multi-day cascade patterns (e.g. poor sleep → skip workout → overeat).

    Method: Sliding 3-day windows across all metric dimensions.
    Flag windows where day-1 signal predicts day-2+3 degradation.

    Returns list of (trigger_metric, cascade_sequence, frequency, avg_severity).
    """
    # TODO: Implement when data gate met (~2026-05-01)
    return []


def _detect_day_of_week_clusters(habit_records):
    """
    Find days of week with elevated failure rates.

    Method: For each day of week, compute completion rate vs overall mean.
    Flag if completion rate < mean - 0.5*SD.

    Returns dict: {day_name: {completion_rate, delta_from_mean, risk_level}}.
    """
    # TODO: Implement when data gate met (~2026-05-01)
    return {}


def _detect_rebound_speed(outcome_records):
    """
    Measure how quickly Matthew recovers after bad days (grade < 60).

    Method: Find all bad-day runs. Measure days to return to grade >= 70.
    Compute mean, median, p90 rebound time.

    Returns {mean_days: float, median_days: float, p90_days: float, n_episodes: int}.
    """
    # TODO: Implement when data gate met (~2026-05-01)
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# WRITE PATTERN MEMORY
# ══════════════════════════════════════════════════════════════════════════════

def _write_pattern_memory(patterns, today):
    """Write failure pattern analysis to platform_memory partition."""
    try:
        from decimal import Decimal
        item = {
            "pk":             f"{USER_PREFIX}platform_memory",
            "sk":             f"MEMORY#failure_patterns#{today}",
            "date":           today,
            "computed_at":    datetime.utcnow().isoformat(),
            "memory_type":    "failure_patterns",
            "algo_version":   "0.1.0",
            "habit_skip_predictors": json.dumps(patterns.get("habit_skip_predictors", [])),
            "cascade_patterns":      json.dumps(patterns.get("cascade_patterns", [])),
            "dow_clusters":          json.dumps(patterns.get("dow_clusters", {})),
            "rebound_speed":         json.dumps(patterns.get("rebound_speed", {})),
            "data_window_days":      patterns.get("data_window_days", 0),
            "note": (
                "IC-4 failure pattern memory. Correlational only — AI-2. "
                "Use to inform coaching about recurring struggle patterns, not to predict failures."
            ),
        }
        table.put_item(Item=item)
        logger.info(f"[IC-4] Wrote failure_patterns memory for {today}")
    except Exception as e:
        logger.error(f"[IC-4] Failed to write pattern memory: {e}")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# LAMBDA HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    logger.info(f"[IC-4] failure-pattern-compute START date={today}")

    # ── Data gate check ────────────────────────────────────────────────────
    gate_ok, days_available = _check_data_gate()
    if not gate_ok:
        msg = (
            f"IC-4 data gate not met: {days_available}/{MIN_DAYS_REQUIRED} days available. "
            f"Activate when ≥{MIN_DAYS_REQUIRED} days of habit_scores data exists (~2026-05-01)."
        )
        logger.info(f"[IC-4] {msg}")
        return {"status": "data_gate_not_met", "days_available": days_available,
                "days_required": MIN_DAYS_REQUIRED, "message": msg}

    # ── Data collection ────────────────────────────────────────────────────
    lookback_start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        habit_resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":pk":    f"{USER_PREFIX}habit_scores",
                ":start": f"DATE#{lookback_start}",
                ":end":   f"DATE#{today}",
            },
        )
        habit_records = habit_resp.get("Items", [])

        outcome_resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":pk":    f"{USER_PREFIX}day_grade",
                ":start": f"DATE#{lookback_start}",
                ":end":   f"DATE#{today}",
            },
        )
        outcome_records = outcome_resp.get("Items", [])

        sleep_resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":pk":    f"{USER_PREFIX}whoop",
                ":start": f"DATE#{lookback_start}",
                ":end":   f"DATE#{today}",
            },
        )
        sleep_records = sleep_resp.get("Items", [])

    except Exception as e:
        logger.error(f"[IC-4] Data collection failed: {e}")
        return {"status": "error", "error": str(e)}

    logger.info(
        f"[IC-4] Loaded {len(habit_records)} habit, "
        f"{len(outcome_records)} outcome, {len(sleep_records)} sleep records"
    )

    # ── Run pattern detectors ──────────────────────────────────────────────
    patterns = {
        "habit_skip_predictors": _detect_habit_skip_predictors(habit_records, outcome_records),
        "cascade_patterns":      _detect_cascade_patterns(habit_records, outcome_records, sleep_records),
        "dow_clusters":          _detect_day_of_week_clusters(habit_records),
        "rebound_speed":         _detect_rebound_speed(outcome_records),
        "data_window_days":      days_available,
    }

    # ── Write to memory ────────────────────────────────────────────────────
    _write_pattern_memory(patterns, today)

    result = {
        "status":           "ok",
        "date":             today,
        "data_window_days": days_available,
        "patterns_found": {
            "habit_predictors": len(patterns["habit_skip_predictors"]),
            "cascades":         len(patterns["cascade_patterns"]),
            "dow_clusters":     len(patterns["dow_clusters"]),
            "rebound_episodes": patterns["rebound_speed"].get("n_episodes", 0),
        },
        "note": "IC-4: All patterns are correlational, not causal (AI-2).",
    }
    logger.info(f"[IC-4] COMPLETE: {result}")
    return result
