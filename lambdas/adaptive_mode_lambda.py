"""
adaptive_mode_lambda.py — Feature #50: Adaptive Email Frequency
Computes daily engagement score + brief_mode, stores to DynamoDB.

Schedule: 9:36 AM PT (after character-sheet-compute, before Daily Brief)
EventBridge rule: adaptive-mode-compute

Modes:
  flourishing  (score ≥ 70) — 🌟 green banner, BoD celebrates
  standard     (score 40-69) — no banner, current behaviour
  struggling   (score < 40) — 💛 amber banner, BoD is warm/gentle

DynamoDB:
  PK: USER#matthew#SOURCE#adaptive_mode
  SK: DATE#YYYY-MM-DD
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("adaptive-mode-compute")
except ImportError:
    logger = logging.getLogger("adaptive-mode-compute")
    logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ["USER_ID"]
REGION = os.environ.get("AWS_REGION", "us-west-2")
ALGO_VERSION = "1.0"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


# ── DynamoDB helpers ──────────────────────────────────────────────────────────

def fetch_record(source, date_str):
    """Fetch a single DynamoDB record by source + date."""
    try:
        resp = table.get_item(
            Key={
                "pk": f"USER#{USER_ID}#SOURCE#{source}",
                "sk": f"DATE#{date_str}",
            }
        )
        return resp.get("Item", {})
    except Exception as e:
        logger.warning(f"fetch_record({source}, {date_str}) failed: {e}")
        return {}


def fetch_recent_dates(source, days=7, base_date=None):
    """Fetch records for the last N days."""
    if base_date is None:
        base_date = datetime.now(timezone.utc).date()
    records = {}
    for i in range(days):
        d = (base_date - timedelta(days=i)).isoformat()
        item = fetch_record(source, d)
        if item:
            records[d] = item
    return records


def store_adaptive_mode(date_str, result):
    """Write adaptive mode record to DynamoDB."""
    item = {
        "pk": f"USER#{USER_ID}#SOURCE#adaptive_mode",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "engagement_score": int(result["engagement_score"]),
        "brief_mode": result["brief_mode"],
        "mode_label": result["mode_label"],
        "factors": result["factors"],
        "component_scores": result["component_scores"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "algo_version": ALGO_VERSION,
    }
    table.put_item(Item=item)
    logger.info(f"Stored adaptive_mode for {date_str}: {result['brief_mode']} (score={result['engagement_score']})")


# ── Scoring components ────────────────────────────────────────────────────────

def score_journal(date_str):
    """
    Journal completion score (0-100, weight=25%).
    morning + evening entries = 100
    one template entry = 60
    no entry = 0
    """
    item = fetch_record("notion", date_str)  # journal lives under notion source
    if not item:
        return 0, "no journal entry"

    template_count = item.get("template_count", 0)
    entry_count = item.get("entry_count", 0)
    word_count = item.get("word_count", 0)

    # Two or more substantive entries
    if entry_count >= 2 and word_count > 100:
        return 100, f"{entry_count} entries, {word_count} words"
    # One entry with decent content
    elif entry_count >= 1 and word_count > 40:
        return 60, f"{entry_count} entry, {word_count} words"
    # Template only / very short
    elif template_count > 0 or word_count > 0:
        return 30, "minimal journal activity"
    else:
        return 0, "no journal content"


def score_t0_habits(date_str):
    """
    T0 (non-negotiable) habit adherence score (0-100, weight=30%).
    Reads from habit_scores partition.
    """
    item = fetch_record("habit_scores", date_str)
    if not item:
        return 50, "no habit data (neutral)"  # neutral — don't penalise for missing data

    t0_total = int(item.get("tier0_total", 0))
    t0_done = int(item.get("tier0_done", 0))

    if t0_total == 0:
        return 50, "no T0 habits tracked"

    pct = (t0_done / t0_total) * 100
    return int(pct), f"{t0_done}/{t0_total} T0 habits ({int(pct)}%)"


def score_t1_habits(date_str):
    """
    T1 (high-priority) habit adherence score (0-100, weight=20%).
    """
    item = fetch_record("habit_scores", date_str)
    if not item:
        return 50, "no habit data (neutral)"

    t1_total = int(item.get("tier1_total", 0))
    t1_done = int(item.get("tier1_done", 0))

    if t1_total == 0:
        return 50, "no T1 habits tracked"

    pct = (t1_done / t1_total) * 100
    return int(pct), f"{t1_done}/{t1_total} T1 habits ({int(pct)}%)"


def score_grade_trend(base_date_str):
    """
    7-day grade trend score (0-100, weight=25%).
    Compare recent 3 days vs prior 4 days average.
    Improving (+5 pts) = 100, Declining (-5 pts) = 0, Flat = 50.
    """
    base_date = datetime.strptime(base_date_str, "%Y-%m-%d").date()
    grades = {}

    for i in range(7):
        d = (base_date - timedelta(days=i)).isoformat()
        item = fetch_record("day_grade", d)
        if item:
            grade_val = item.get("score") or item.get("grade_numeric") or item.get("numeric_grade")
            if grade_val is not None:
                try:
                    grades[d] = float(grade_val)
                except (ValueError, TypeError):
                    pass

    if len(grades) < 3:
        return 50, "insufficient grade history (neutral)"

    dates_sorted = sorted(grades.keys(), reverse=True)
    recent = [grades[d] for d in dates_sorted[:3]]
    prior = [grades[d] for d in dates_sorted[3:7]]

    recent_avg = sum(recent) / len(recent)
    prior_avg = sum(prior) / len(prior) if prior else recent_avg

    delta = recent_avg - prior_avg  # positive = improving

    # Map delta (-5 to +5) → score (0 to 100)
    score = max(0, min(100, int(50 + (delta * 10))))

    trend_label = "improving" if delta > 0.5 else "declining" if delta < -0.5 else "stable"
    return score, f"grade trend {trend_label} (recent={recent_avg:.1f}, prior={prior_avg:.1f}, Δ={delta:+.1f})"


# ── Core computation ──────────────────────────────────────────────────────────

def compute_adaptive_mode(date_str):
    """
    Compute engagement score and brief_mode for a given date.
    Returns dict with all fields needed for DynamoDB storage.
    """
    logger.info(f"Computing adaptive mode for {date_str}")

    # Score each component
    journal_score, journal_reason = score_journal(date_str)
    t0_score, t0_reason = score_t0_habits(date_str)
    t1_score, t1_reason = score_t1_habits(date_str)
    trend_score, trend_reason = score_grade_trend(date_str)

    # Weighted composite (weights sum to 1.0)
    weights = {
        "journal": 0.25,
        "t0_habits": 0.30,
        "t1_habits": 0.20,
        "grade_trend": 0.25,
    }

    engagement_score = (
        journal_score * weights["journal"]
        + t0_score * weights["t0_habits"]
        + t1_score * weights["t1_habits"]
        + trend_score * weights["grade_trend"]
    )
    engagement_score = round(engagement_score, 1)

    # Determine mode
    if engagement_score >= 70:
        brief_mode = "flourishing"
        mode_label = "🌟 Flourishing"
    elif engagement_score < 40:
        brief_mode = "struggling"
        mode_label = "💛 Rough Patch"
    else:
        brief_mode = "standard"
        mode_label = "Standard"

    return {
        "date": date_str,
        "engagement_score": engagement_score,
        "brief_mode": brief_mode,
        "mode_label": mode_label,
        "component_scores": {
            "journal": journal_score,
            "t0_habits": t0_score,
            "t1_habits": t1_score,
            "grade_trend": trend_score,
        },
        "factors": {
            "journal": journal_reason,
            "t0_habits": t0_reason,
            "t1_habits": t1_reason,
            "grade_trend": trend_reason,
        },
    }


# ── Lambda handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Entry point. Accepts:
      - {} or {"date": "YYYY-MM-DD"}  → compute for given/today date
      - {"backfill_days": N}           → compute for last N days
    """
    logger.info(f"Event: {json.dumps(event)}")

    # Determine date(s) to process
    if "backfill_days" in event:
        days = int(event["backfill_days"])
        base = datetime.now(timezone.utc).date()
        dates = [(base - timedelta(days=i)).isoformat() for i in range(days)]
    elif "date" in event:
        dates = [event["date"]]
    else:
        # Default: yesterday (Daily Brief reads yesterday's data)
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        dates = [yesterday]

    results = []
    for date_str in dates:
        try:
            result = compute_adaptive_mode(date_str)
            store_adaptive_mode(date_str, result)
            results.append(result)
            logger.info(
                f"{date_str}: {result['mode_label']} "
                f"(score={result['engagement_score']}, "
                f"journal={result['component_scores']['journal']}, "
                f"t0={result['component_scores']['t0_habits']}, "
                f"t1={result['component_scores']['t1_habits']}, "
                f"trend={result['component_scores']['grade_trend']})"
            )
        except Exception as e:
            logger.error(f"Failed to compute adaptive mode for {date_str}: {e}", exc_info=True)
            results.append({"date": date_str, "error": str(e)})

    if len(results) == 1:
        return results[0]

    return {
        "processed": len(results),
        "results": results,
    }
