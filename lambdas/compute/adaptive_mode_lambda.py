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
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("adaptive-mode-compute")
except ImportError:
    logger = logging.getLogger("adaptive-mode-compute")
    logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
REGION = os.environ.get("AWS_REGION", "us-west-2")
ALGO_VERSION = "1.0"
ENGAGEMENT_ALGO_VERSION = "1.0"

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
    # DATA-2: validate_item for adaptive_mode (Item 3, R12)
    try:
        from ingestion_validator import validate_item as _vi

        _vr = _vi("adaptive_mode", item, date_str)
        if _vr.should_skip_ddb:
            logger.error("[DATA-2] Skipping adaptive_mode write for %s: %s", date_str, _vr.errors)
            return
        if _vr.warnings:
            logger.warning("[DATA-2] adaptive_mode warnings for %s: %s", date_str, _vr.warnings)
    except ImportError:
        pass
    except Exception as ve:
        logger.warning("[DATA-2] adaptive_mode validate_item failed (proceeding): %s", ve)
    # Phase 3.3 (2026-05-16): tag with run_id + computed_at.
    try:
        from compute_metadata import tag_record

        item = tag_record(item, source_id="adaptive_mode")
    except ImportError:
        pass
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


# ── Presence / quiet-stretch (engagement_state) ───────────────────────────────
# A separate instrument from the engagement_score above: that one deliberately
# NEUTRALISES missing data (returns 50 so it never penalises a gap); this one
# MEASURES the gap so the coaches and the site can voice it. Same lambda, same
# schedule, its own record — engagement_score keeps its philosophy untouched.


def _engagement_reference_today():
    """The real 'now' Pacific day — engagement is measured from now, not from the
    yesterday that adaptive_mode scores. Falls back to UTC if pacific_time absent."""
    try:
        from pacific_time import pacific_today

        return pacific_today()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def _log_dates(source, today, window_days=35):
    """Trailing-window list of days `source` logged (high-water-mark widened).
    Deduped 'YYYY-MM-DD', newest first. BETWEEN spans suffixed SKs (hevy
    DATE#..#WORKOUT#, notion DATE#..#journal#)."""
    from datetime import timedelta as _td

    pk = f"USER#{USER_ID}#SOURCE#{source}"
    base = datetime.strptime(today, "%Y-%m-%d").date()
    lo = (base - _td(days=window_days)).isoformat()
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
            ExpressionAttributeValues={":pk": pk, ":lo": f"DATE#{lo}", ":hi": f"DATE#{today}~"},
            ProjectionExpression="sk",
        )
    except Exception as e:
        logger.warning("engagement _log_dates(%s) query failed: %s", source, e)
        return []
    out = set()
    for it in resp.get("Items", []):
        d = it.get("sk", "").replace("DATE#", "")[:10]
        try:
            datetime.strptime(d, "%Y-%m-%d")
            out.add(d)
        except ValueError:
            continue
    return sorted(out, reverse=True)


def _latest_date(source, today):
    """Newest DATE# day for a source (high-water-mark), or None."""
    dates = _log_dates(source, today, window_days=14)
    return dates[0] if dates else None


def _weight_series(today, window_days=60):
    """[(date, weight_lbs)] from Withings over the window, for the return delta."""
    from datetime import timedelta as _td

    pk = f"USER#{USER_ID}#SOURCE#withings"
    base = datetime.strptime(today, "%Y-%m-%d").date()
    lo = (base - _td(days=window_days)).isoformat()
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
            ExpressionAttributeValues={":pk": pk, ":lo": f"DATE#{lo}", ":hi": f"DATE#{today}~"},
            ProjectionExpression="sk, weight_lbs",
        )
    except Exception as e:
        logger.warning("engagement _weight_series query failed: %s", e)
        return []
    series = []
    for it in resp.get("Items", []):
        w = it.get("weight_lbs")
        d = it.get("sk", "").replace("DATE#", "")[:10]
        if w is not None:
            try:
                series.append((d, float(w)))
            except (ValueError, TypeError):
                continue
    return series


def store_engagement_state(today, signal):
    """Write the presence record: DATE#{today} (history) + STATE#current (cheap
    read for the orchestrator + site-api, like STANCE#latest)."""
    from compute_metadata import tag_record
    from numeric import floats_to_decimal

    base = {
        "pk": f"USER#{USER_ID}#SOURCE#engagement_state",
        "date": today,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "algo_version": ENGAGEMENT_ALGO_VERSION,
        **signal,
    }
    base = floats_to_decimal(base)
    for sk in (f"DATE#{today}", "STATE#current"):
        item = dict(base, sk=sk)
        try:
            item = tag_record(item, source_id="engagement_state")
        except ImportError:
            pass
        table.put_item(Item=item)
    logger.info(
        "Stored engagement_state for %s: %s (gap=%s, returned=%s)",
        today,
        signal.get("presence_class"),
        signal.get("gap_days"),
        signal.get("returned"),
    )


def compute_and_store_engagement():
    """Compute + persist the presence / quiet-stretch state. Fail-soft — never
    aborts the adaptive_mode run."""
    from engagement_core import MANUAL_CHANNELS, WEARABLES, compute_presence

    today = _engagement_reference_today()
    channel_dates = {src: _log_dates(src, today) for src in MANUAL_CHANNELS}
    wearable_latest = {src: _latest_date(src, today) for src in WEARABLES}
    weight_series = _weight_series(today)

    sick_days = set()
    try:
        from sick_day_checker import get_sick_days_range

        base = datetime.strptime(today, "%Y-%m-%d").date()
        recs = get_sick_days_range(table, USER_ID, (base - timedelta(days=35)).isoformat(), today) or []
        sick_days = {r.get("date") for r in recs if r.get("date")}
    except Exception as e:
        logger.info("engagement sick-day lookup skipped: %s", e)

    travel_days = _travel_days(today)

    signal = compute_presence(
        today,
        channel_dates,
        wearable_latest=wearable_latest,
        weight_series=weight_series,
        sick_days=sick_days,
        travel_days=travel_days,
    )
    store_engagement_state(today, signal)
    return signal


def _travel_days(today, window_days=35):
    """Set of 'YYYY-MM-DD' with a travel log in the window (best-effort)."""
    dates = set(_log_dates("travel", today, window_days=window_days))
    return dates


# ── Lambda handler ────────────────────────────────────────────────────────────


def lambda_handler(event, context):
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
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

        # Presence / quiet-stretch state — separate instrument, fail-soft so a
        # gap-compute error never aborts the adaptive_mode write above.
        try:
            compute_and_store_engagement()
        except Exception as e:
            logger.error("compute_and_store_engagement failed (non-fatal): %s", e, exc_info=True)

        if len(results) == 1:
            return results[0]

        return {
            "processed": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
