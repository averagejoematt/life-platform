"""
momentum_warning_compute_lambda.py — IC-5: Momentum & Early Warning System

Detects positive and negative momentum signals across all health pillars
and generates early warning flags before problems become entrenched.

DATA GATE: Requires 6-8 weeks of behavioral data. Scheduled ~2026-05-01.

WHAT IT DETECTS:

  MOMENTUM (positive compounding):
    - Streak streaks: consecutive days of high habit completion (tier0 + tier01)
    - Fitness upswing: CTL rising + TSB improving simultaneously
    - Sleep quality trend: 7-day score trending above 30-day baseline
    - Weight momentum: on-track trajectory vs goal curve

  EARLY WARNINGS (negative signals before alarm-level degradation):
    - HRV suppression: 3+ days below personal 30-day mean (pre-illness signal)
    - Habit attrition: completion rate declining over 14d vs prior 14d
    - Nutrition drift: 7-day average calories trending toward deficit/surplus extreme
    - Recovery floor creep: Whoop recovery scores in lower quartile 3+ consecutive days
    - Training load danger zone: ACWR approaching 1.3 (injury risk threshold)

  CONTEXT FLAGS (inform coaching without triggering alerts):
    - Travel impact: recovery delta pre/during/post travel
    - Seasonal pattern match: is current performance above/below historical same-month avg

DynamoDB writes:
  SOURCE#platform_memory   MEMORY#momentum_warning#YYYY-MM-DD

SCHEDULE: Daily at 9:50 AM PT (runs after daily-metrics-compute)
  EventBridge: cron(50 17 * * ? *)

v0.1.0 — 2026-03-15 (IC-5 skeleton — data-gated ~2026-05-01)
"""

import json
import os
import logging
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from platform_logger import get_logger
    logger = get_logger("momentum-warning-compute")
except ImportError:
    logger = logging.getLogger("momentum-warning-compute")
    logger.setLevel(logging.INFO)

_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# ── Data gate ────────────────────────────────────────────────────────────────
MIN_DAYS_REQUIRED = 42  # 6 weeks

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATE
# ══════════════════════════════════════════════════════════════════════════════

def _check_data_gate():
    """Return (ok: bool, days_available: int)."""
    try:
        today      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gate_start = (datetime.now(timezone.utc) - timedelta(days=MIN_DAYS_REQUIRED)).strftime("%Y-%m-%d")
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
            ExpressionAttributeValues={
                ":pk":    f"{USER_PREFIX}computed_metrics",
                ":start": f"DATE#{gate_start}",
                ":end":   f"DATE#{today}",
            },
            Select="COUNT",
        )
        days = resp.get("Count", 0)
        return days >= MIN_DAYS_REQUIRED, days
    except Exception as e:
        logger.warning(f"[IC-5] data gate check failed: {e}")
        return False, 0


# ══════════════════════════════════════════════════════════════════════════════
# MOMENTUM DETECTORS
# ══════════════════════════════════════════════════════════════════════════════

def _detect_habit_momentum(habit_records, today):
    """
    Detect habit completion streaks and trend direction.

    Returns:
      current_streak_days: consecutive days with tier0+tier01 completion >= threshold
      momentum_direction: 'building' | 'holding' | 'eroding'
      completion_7d_avg: float (0-100)
      completion_30d_avg: float (0-100)
    """
    # TODO: Implement when data gate met (~2026-05-01)
    # Method:
    #   1. Walk backward from today counting consecutive days >= completion threshold
    #   2. Compare 7d avg vs 30d avg to determine direction
    #   3. If 7d > 30d + 5pts: 'building'; if abs(diff) < 5: 'holding'; else 'eroding'
    return {}


def _detect_hrv_suppression(whoop_records, today):
    """
    Flag if HRV has been suppressed below personal 30-day mean for 3+ consecutive days.

    This is a pre-illness signal (Huberman: parasympathetic depression precedes
    illness onset by 24-48h on average).

    Returns:
      suppressed: bool
      consecutive_days: int
      current_hrv: float
      baseline_30d: float
      pct_below_baseline: float
    """
    # TODO: Implement when data gate met (~2026-05-01)
    # Method:
    #   1. Compute 30d HRV mean as baseline
    #   2. Walk backward from today counting days below baseline
    #   3. Flag if 3+ consecutive days AND pct_below > 10%
    return {}


def _detect_nutrition_drift(macrofactor_records, profile):
    """
    Detect 7-day calorie average drifting toward extreme deficit or surplus.

    Thresholds (from profile calorie_target):
      Warning low:  < target * 0.75  (aggressive deficit, muscle loss risk)
      Warning high: > target * 1.25  (sustained surplus, body comp drift)

    Returns:
      drift_direction: 'surplus' | 'deficit' | 'on_track'
      severity: 'warning' | 'ok'
      avg_7d_calories: float
      target_calories: float
      pct_deviation: float
    """
    # TODO: Implement when data gate met (~2026-05-01)
    return {}


def _detect_training_load_warning(computed_records):
    """
    Flag ACWR approaching injury risk threshold (>= 1.3).

    Returns:
      warning: bool
      current_acwr: float | None
      risk_level: 'ok' | 'caution' | 'high'
      tsb: float | None
    """
    # TODO: Implement when data gate met (~2026-05-01)
    # Method: read latest computed_metrics TSB + ATL + CTL
    # ACWR = ATL / CTL
    # caution >= 1.3, high >= 1.5
    return {}


def _detect_recovery_floor_creep(whoop_records, today):
    """
    Flag if Whoop recovery has been in lower quartile (< 33) for 3+ consecutive days.

    Whoop recovery <33 = red. 3 consecutive reds = floor creep (not random variation).

    Returns:
      floor_creep: bool
      consecutive_low_days: int
      recovery_scores: list[float]  (last 7 days)
    """
    # TODO: Implement when data gate met (~2026-05-01)
    return {}


def _compute_positive_momentum_score(detections):
    """
    Aggregate positive signals into a 0-100 momentum score.

    Weights (subject to calibration after data gate):
      habit_streak (40%): normalized by 21-day max streak
      fitness_trend (30%): CTL direction + TSB sign
      sleep_trend (30%): 7d score vs 30d score delta

    Returns float 0-100.
    """
    # TODO: Implement when data gate met (~2026-05-01)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# WRITE MOMENTUM MEMORY
# ══════════════════════════════════════════════════════════════════════════════

def _write_momentum_memory(signals, today):
    """Write momentum and early warning signals to platform_memory partition."""
    try:
        item = {
            "pk":          f"{USER_PREFIX}platform_memory",
            "sk":          f"MEMORY#momentum_warning#{today}",
            "date":        today,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "memory_type": "momentum_warning",
            "algo_version": "0.1.0",
            "momentum_score":       signals.get("momentum_score"),
            "habit_momentum":       json.dumps(signals.get("habit_momentum", {})),
            "hrv_suppression":      json.dumps(signals.get("hrv_suppression", {})),
            "nutrition_drift":      json.dumps(signals.get("nutrition_drift", {})),
            "training_load_warning": json.dumps(signals.get("training_load_warning", {})),
            "recovery_floor_creep": json.dumps(signals.get("recovery_floor_creep", {})),
            "active_warnings":      json.dumps(signals.get("active_warnings", [])),
            "coaching_context":     json.dumps(signals.get("coaching_context", {})),
            "note": (
                "IC-5 momentum + early warning memory. Correlational only — AI-2. "
                "Warnings are probabilistic signals, not predictions."
            ),
        }
        table.put_item(Item=item)
        logger.info(f"[IC-5] Wrote momentum_warning memory for {today}")
    except Exception as e:
        logger.error(f"[IC-5] Failed to write momentum memory: {e}")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# LAMBDA HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info(f"[IC-5] momentum-warning-compute START date={today}")

    # ── Data gate ──────────────────────────────────────────────────────────
    gate_ok, days_available = _check_data_gate()
    if not gate_ok:
        msg = (
            f"IC-5 data gate not met: {days_available}/{MIN_DAYS_REQUIRED} days available. "
            f"Activate when ≥{MIN_DAYS_REQUIRED} days of computed_metrics data exists (~2026-05-01)."
        )
        logger.info(f"[IC-5] {msg}")
        return {"status": "data_gate_not_met", "days_available": days_available,
                "days_required": MIN_DAYS_REQUIRED, "message": msg}

    # ── Data collection ────────────────────────────────────────────────────
    lookback_start = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        def _query(source):
            resp = table.query(
                KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
                ExpressionAttributeValues={
                    ":pk":    f"{USER_PREFIX}{source}",
                    ":start": f"DATE#{lookback_start}",
                    ":end":   f"DATE#{today}",
                },
            )
            return resp.get("Items", [])

        whoop_records       = _query("whoop")
        habit_records       = _query("habit_scores")
        computed_records    = _query("computed_metrics")
        macrofactor_records = _query("macrofactor")

        # Load profile for calorie targets
        profile_resp = table.get_item(
            Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"}
        )
        profile = profile_resp.get("Item", {})

    except Exception as e:
        logger.error(f"[IC-5] Data collection failed: {e}")
        return {"status": "error", "error": str(e)}

    # ── Run detectors ──────────────────────────────────────────────────────
    habit_momentum        = _detect_habit_momentum(habit_records, today)
    hrv_suppression       = _detect_hrv_suppression(whoop_records, today)
    nutrition_drift       = _detect_nutrition_drift(macrofactor_records, profile)
    training_load_warning = _detect_training_load_warning(computed_records)
    recovery_floor_creep  = _detect_recovery_floor_creep(whoop_records, today)

    # ── Aggregate active warnings ──────────────────────────────────────────
    active_warnings = []
    if hrv_suppression.get("suppressed"):
        active_warnings.append({
            "type": "hrv_suppression",
            "severity": "medium",
            "message": f"HRV suppressed {hrv_suppression.get('consecutive_days', 0)} consecutive days — possible illness onset signal (Huberman).",
        })
    if nutrition_drift.get("severity") == "warning":
        active_warnings.append({
            "type": "nutrition_drift",
            "severity": "low",
            "message": f"Calories trending {nutrition_drift.get('drift_direction', 'off-target')} — {nutrition_drift.get('pct_deviation', 0):.0f}% from target.",
        })
    if training_load_warning.get("warning"):
        active_warnings.append({
            "type": "training_load",
            "severity": training_load_warning.get("risk_level", "caution"),
            "message": f"ACWR {training_load_warning.get('current_acwr', '?')} — approaching injury risk threshold (Galpin).",
        })
    if recovery_floor_creep.get("floor_creep"):
        active_warnings.append({
            "type": "recovery_floor",
            "severity": "medium",
            "message": f"Recovery in red zone {recovery_floor_creep.get('consecutive_low_days', 0)} consecutive days.",
        })

    signals = {
        "momentum_score":        _compute_positive_momentum_score({
            "habit_momentum": habit_momentum,
            "training_load":  training_load_warning,
        }),
        "habit_momentum":        habit_momentum,
        "hrv_suppression":       hrv_suppression,
        "nutrition_drift":       nutrition_drift,
        "training_load_warning": training_load_warning,
        "recovery_floor_creep":  recovery_floor_creep,
        "active_warnings":       active_warnings,
        "coaching_context": {
            "days_of_data":  days_available,
            "warning_count": len(active_warnings),
        },
    }

    _write_momentum_memory(signals, today)

    result = {
        "status":          "ok",
        "date":            today,
        "momentum_score":  signals["momentum_score"],
        "active_warnings": len(active_warnings),
        "warning_types":   [w["type"] for w in active_warnings],
        "note":            "IC-5: All signals are correlational, not predictive (AI-2).",
    }
    logger.info(f"[IC-5] COMPLETE: {result}")
    return result
