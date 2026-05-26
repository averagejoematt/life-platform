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
from datetime import datetime, timedelta, timezone

try:
    from platform_logger import get_logger
    logger = get_logger("failure-pattern-compute")
except ImportError:
    logger = logging.getLogger("failure-pattern-compute")
    logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# ── Data gate ────────────────────────────────────────────────────────────────
# Minimum days of behavioral data required before patterns are meaningful.
# Below this threshold, the Lambda exits early with a data_gate_not_met signal.
MIN_DAYS_REQUIRED = 42   # 6 weeks

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATE CHECK
# ══════════════════════════════════════════════════════════════════════════════

def _check_data_gate():
    """Return (ok: bool, days_available: int) for the habit_scores partition."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gate_start = (datetime.now(timezone.utc) - timedelta(days=MIN_DAYS_REQUIRED)).strftime("%Y-%m-%d")
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

_BAD_GRADE_THRESHOLD = 60   # day_grade.total_score below this → "bad day"
_GOOD_GRADE_THRESHOLD = 70  # day_grade.total_score at or above this → "rebounded"


def _grade_for_date(outcome_records):
    """Map date → total_score float. Skips records missing fields."""
    out = {}
    for r in outcome_records:
        d = r.get("date")
        s = r.get("total_score")
        if d is None or s is None:
            continue
        try:
            out[d] = float(s)
        except (TypeError, ValueError):
            continue
    return out


def _detect_habit_skip_predictors(habit_records, outcome_records):
    """
    Identify which habit skips most reliably predict bad outcome days.

    For each habit name appearing in any day's `missed_tier0` list, compute:
      - n_skipped: total days the habit was skipped
      - n_skipped_bad: of those, how many had day_grade < 60
      - skip_bad_rate: P(bad day | habit skipped)
      - lift = skip_bad_rate / baseline_bad_rate

    Returns top 3 highest-lift habits with n_skipped >= 3 (filter rare cases).

    IC-4: correlational framing only — AI-2 compliance.
    """
    grades = _grade_for_date(outcome_records)
    if not grades:
        return []

    n_total = len(grades)
    n_bad = sum(1 for v in grades.values() if v < _BAD_GRADE_THRESHOLD)
    if n_total == 0 or n_bad == 0:
        return []
    baseline_bad_rate = n_bad / n_total

    habit_skips = {}  # habit_name → list of dates skipped
    for r in habit_records:
        d = r.get("date")
        missed = r.get("missed_tier0") or []
        if not d or not isinstance(missed, list):
            continue
        for h in missed:
            if not isinstance(h, str):
                continue
            habit_skips.setdefault(h, []).append(d)

    predictors = []
    for habit, dates in habit_skips.items():
        n_skipped = len(dates)
        if n_skipped < 3:
            continue  # not enough data for this habit
        n_skipped_bad = sum(1 for d in dates if grades.get(d, 100) < _BAD_GRADE_THRESHOLD)
        skip_bad_rate = n_skipped_bad / n_skipped
        lift = skip_bad_rate / baseline_bad_rate if baseline_bad_rate > 0 else 0
        if lift <= 1.0:
            continue  # skipping this habit doesn't elevate bad-day risk
        predictors.append({
            "habit": habit,
            "n_skipped": n_skipped,
            "n_skipped_bad": n_skipped_bad,
            "skip_bad_rate": round(skip_bad_rate, 3),
            "baseline_bad_rate": round(baseline_bad_rate, 3),
            "lift": round(lift, 2),
        })

    predictors.sort(key=lambda x: x["lift"], reverse=True)
    return predictors[:3]


def _detect_cascade_patterns(habit_records, outcome_records, sleep_records):
    """
    Detect simple 2-day cascade: poor sleep (Whoop sleep_score < 60) → next-day bad outcome.

    Method: For each Whoop record with sleep_score < 60, check if the FOLLOWING
    day's day_grade < 60. Compute conditional probability vs baseline.

    Returns list of cascade pattern dicts (currently 1 pattern: poor_sleep → bad_day).
    """
    grades = _grade_for_date(outcome_records)
    if not grades or not sleep_records:
        return []

    # Build sleep_score map
    sleep_scores = {}
    for r in sleep_records:
        d = r.get("date")
        # Whoop records have sleep_score on the day
        score = r.get("sleep_score")
        if d is None or score is None:
            continue
        try:
            sleep_scores[d] = float(score)
        except (TypeError, ValueError):
            continue
    if not sleep_scores:
        return []

    # Baseline bad-day rate
    n_total = len(grades)
    n_bad = sum(1 for v in grades.values() if v < _BAD_GRADE_THRESHOLD)
    baseline = n_bad / n_total if n_total > 0 else 0
    if baseline == 0:
        return []

    # Cascade: poor sleep → next-day bad
    poor_sleep_days = sorted([d for d, s in sleep_scores.items() if s < 60])
    if len(poor_sleep_days) < 3:
        return []

    n_followed_by_bad = 0
    n_with_next_day_data = 0
    for d in poor_sleep_days:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            next_d = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            continue
        if next_d not in grades:
            continue
        n_with_next_day_data += 1
        if grades[next_d] < _BAD_GRADE_THRESHOLD:
            n_followed_by_bad += 1

    if n_with_next_day_data < 3:
        return []
    cascade_rate = n_followed_by_bad / n_with_next_day_data
    lift = cascade_rate / baseline if baseline > 0 else 0
    if lift <= 1.0:
        return []

    return [{
        "trigger": "poor_sleep_score",
        "trigger_threshold": "<60",
        "consequence": "next_day_bad_grade",
        "consequence_threshold": f"<{_BAD_GRADE_THRESHOLD}",
        "n_episodes": n_with_next_day_data,
        "n_followed_by_consequence": n_followed_by_bad,
        "cascade_rate": round(cascade_rate, 3),
        "baseline_rate": round(baseline, 3),
        "lift": round(lift, 2),
    }]


def _detect_day_of_week_clusters(habit_records):
    """
    Find days of week with elevated habit-skip rates.

    Method: For each day of week, compute mean composite_score. Flag DOWs
    where the mean is at least 5 points below the overall mean.

    Returns dict: {day_name: {mean_score, delta_from_overall, n_days, risk_level}}.
    """
    if not habit_records:
        return {}

    DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_dow = {d: [] for d in DOWS}
    for r in habit_records:
        d = r.get("date")
        score = r.get("composite_score")
        if not d or score is None:
            continue
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            score_f = float(score)
        except (ValueError, TypeError):
            continue
        by_dow[DOWS[dt.weekday()]].append(score_f)

    all_scores = [s for lst in by_dow.values() for s in lst]
    if not all_scores:
        return {}
    overall_mean = sum(all_scores) / len(all_scores)

    out = {}
    for dow, scores in by_dow.items():
        if len(scores) < 3:
            continue  # not enough samples
        dow_mean = sum(scores) / len(scores)
        delta = dow_mean - overall_mean
        if delta <= -5:
            risk = "elevated"
        elif delta <= -2:
            risk = "mild"
        else:
            continue  # only flag DOWs with notable downside
        out[dow] = {
            "mean_score": round(dow_mean, 1),
            "delta_from_overall": round(delta, 1),
            "n_days": len(scores),
            "risk_level": risk,
        }
    return out


def _detect_rebound_speed(outcome_records):
    """
    Measure how quickly Matthew recovers after bad days (grade < 60).

    Method: Walk dates in order. Each time a bad day is followed by ≥1 more
    bad-or-mediocre day, that's a "bad run." Episode ends when grade >= 70.
    Days to recover = (date of recovery) - (start of bad run).

    Returns {mean_days, median_days, p90_days, n_episodes}.
    """
    grades = _grade_for_date(outcome_records)
    if not grades:
        return {}

    sorted_dates = sorted(grades.keys())
    if len(sorted_dates) < 7:
        return {}

    rebound_days = []
    i = 0
    while i < len(sorted_dates):
        d = sorted_dates[i]
        if grades[d] < _BAD_GRADE_THRESHOLD:
            # found start of bad run; walk forward to find recovery
            j = i + 1
            while j < len(sorted_dates) and grades[sorted_dates[j]] < _GOOD_GRADE_THRESHOLD:
                j += 1
            if j < len(sorted_dates):
                # j is the recovery day
                try:
                    start = datetime.strptime(d, "%Y-%m-%d")
                    end = datetime.strptime(sorted_dates[j], "%Y-%m-%d")
                    rebound_days.append((end - start).days)
                except ValueError:
                    pass
            i = j + 1  # skip past the recovery day
        else:
            i += 1

    if not rebound_days:
        return {}

    rebound_days_sorted = sorted(rebound_days)
    n = len(rebound_days_sorted)
    mean = sum(rebound_days_sorted) / n
    median = rebound_days_sorted[n // 2]
    p90_idx = max(0, int(n * 0.9) - 1)
    p90 = rebound_days_sorted[p90_idx]

    return {
        "mean_days": round(mean, 1),
        "median_days": median,
        "p90_days": p90,
        "n_episodes": n,
    }


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
            "computed_at":    datetime.now(timezone.utc).isoformat(),
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
        # V2 P2.6 (2026-05-19): tag with run_id + computed_at
        try:
            from compute_metadata import tag_record
            item = tag_record(item, source_id="failure_patterns")
        except ImportError:
            pass
        table.put_item(Item=item)
        logger.info(f"[IC-4] Wrote failure_patterns memory for {today}")
    except Exception as e:
        logger.error(f"[IC-4] Failed to write pattern memory: {e}")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# LAMBDA HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    lookback_start = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

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
