"""
coach_prediction_evaluator.py — Scheduled Daily Coach Prediction Evaluator
v1.0.0 — 2026-04-06 (Coach Intelligence Phase 1B)

Deterministic Lambda that evaluates pending coach predictions and updates
Bayesian confidence scores. No LLM calls — purely data-driven evaluation.

Runs daily at 10:00 AM PT (18:00 UTC via EventBridge), after the computation
engine (9:45 AM PT) so EWMA trends are fresh.

Evaluation types:
  1. machine      — metric crosses threshold within window
  2. directional  — metric moves in predicted direction (EWMA-based)
  3. conditional  — if X then Y (check precondition, then evaluate)
  4. qualitative  — skip (needs human/LLM, not this Lambda)

DynamoDB patterns:
  Predictions:   PK=COACH#{coach_id}  SK=PREDICTION#{pred_id}
  Confidence:    PK=COACH#{coach_id}  SK=CONFIDENCE#{subdomain}
  Learning log:  PK=COACH#{coach_id}  SK=LEARNING#{date}#{slug}
  Data sources:  PK=USER#matthew#SOURCE#{source}  SK=DATE#{YYYY-MM-DD}

Bayesian model: Beta(alpha, beta) distribution per coach per subdomain.
  - confirmed + beats_null: alpha += 1
  - refuted: beta += 1
  - matches_null or inconclusive: no update

Idempotent: safe to re-run. Already-evaluated predictions (status not in
pending/confirming) are skipped. Learning log uses put_item (upsert).
"""

import json
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from phase_filter import with_phase_filter  # ADR-058

# ── Structured logger ────────────────────────────────────────────────────────
try:
    from platform_logger import get_logger

    logger = get_logger("coach-prediction-evaluator")
except ImportError:
    logger = logging.getLogger("coach-prediction-evaluator")
    logger.setLevel(logging.INFO)

# ── Configuration ────────────────────────────────────────────────────────────
_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
ALGO_VERSION = "1.0"

# Coach IDs — exhaustive list of all coaches that can issue predictions
COACH_IDS = [
    "sleep_coach",
    "nutrition_coach",
    "training_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]

# Metric → DynamoDB source mapping. CONSOLIDATED 2026-06-28 (Coherence Program
# Phase 2): this was a hand-synced duplicate of coach_state_updater's allowlist —
# drift silently broke prediction grading. Single source now; MEASURABLE_METRICS is
# DERIVED from this map, so the extractor's allowlist and the evaluator's source-map
# cannot diverge. See lambdas/measurable_metrics.py.
from measurable_metrics import METRIC_SOURCES  # noqa: E402

# Domain-appropriate minimum evaluation windows (days).
# Predictions with shorter windows are clamped to these minimums.
DOMAIN_MIN_WINDOWS = {
    "sleep": 7,
    "hrv": 14,
    "recovery": 14,
    "training": 21,
    "body_composition": 28,
    "biomarkers": 60,
    "mood": 7,
    "mental": 7,
    "nutrition": 14,
    "glucose": 14,
    "labs": 60,
}

# Map subdomains to their domain category for window enforcement
SUBDOMAIN_TO_DOMAIN = {
    # sleep_coach
    "sleep_quality": "sleep",
    "sleep_duration": "sleep",
    "sleep_efficiency": "sleep",
    "deep_sleep": "sleep",
    "rem_sleep": "sleep",
    # nutrition_coach
    "caloric_intake": "nutrition",
    "protein_intake": "nutrition",
    "macros": "nutrition",
    "meal_timing": "nutrition",
    # training_coach
    "training_load": "training",
    "training_frequency": "training",
    "strength": "training",
    "endurance": "training",
    "performance": "training",
    "cardio": "training",
    # mind_coach
    "mood": "mood",
    "stress": "mental",
    "focus": "mental",
    "mindfulness": "mental",
    # physical_coach
    "body_composition": "body_composition",
    "weight": "body_composition",
    "body_fat": "body_composition",
    "muscle_mass": "body_composition",
    "mobility": "training",
    # glucose_coach
    "glucose_control": "glucose",
    "glucose_variability": "glucose",
    "fasting_glucose": "glucose",
    "postprandial": "glucose",
    # labs_coach
    "cholesterol": "labs",
    "hormones": "labs",
    "inflammation": "labs",
    "vitamins": "labs",
    "metabolic": "labs",
    # explorer_coach
    "cross_domain": "training",  # default conservative window
}

# Statuses that are eligible for evaluation
EVALUABLE_STATUSES = {"pending", "confirming"}

# EWMA decay factor for directional trend evaluation
EWMA_DECAY = 0.87

# Directional evaluation: minimum slope magnitude to count as a real signal
# (avoids calling noise a confirmed direction)
DIRECTIONAL_NOISE_THRESHOLD = 0.02

# Expiry multiplier — if window elapsed by more than 2x and still not evaluable
EXPIRY_MULTIPLIER = 2

# ── AWS clients ──────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)
_lambda_client = boto3.client("lambda", region_name=_REGION)  # #534: fires coach-history-summarizer's event refresh
_cw = boto3.client("cloudwatch", region_name=_REGION)  # #727: grading-liveness metrics

# ── #727: grading-liveness (scientific-liveness heartbeat) ───────────────────
# The evaluator ran daily for weeks producing zero graded outcomes and nothing
# noticed — the ingestion/coherence heartbeats watch the *pipeline*, not the
# *science*. This emits, every run, the two counts that make a stall visible
# (LifePlatform/Predictions) plus a DaysSinceLastDecided gauge the monitoring
# stack alarms on at >= 14 days (monitoring_stack.GradingStalled). A rolling-sum
# "zero decided in N days" alarm can't express 14 days — CloudWatch caps a
# daily-period alarm's window at 7 days (EvaluationPeriods x Period <= 604800;
# see monitoring_stack._heartbeat_alarm) — so a single deterministic gauge
# alarmed at a threshold is both the correct 14-day semantic AND fires on the
# CURRENT state the day it deploys (no marker yet + 0 decided => sentinel => ALARM).
LIVENESS_NAMESPACE = "LifePlatform/Predictions"
_LAST_DECIDED_PK = "EVALUATOR#coach_prediction"
_LAST_DECIDED_SK = "STATE#last_decided"
# Emitted when the marker has never been written (grading has produced nothing in
# this experiment cycle). Any value >= the 14-day alarm threshold works; 999 reads
# unambiguously as "never" in a dashboard without pretending to be a real day count.
_NEVER_DECIDED_DAYS = 999


# =============================================================================
# HELPERS
# =============================================================================


from numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401


def _to_decimal(val):
    """Convert a numeric value to Decimal for DynamoDB writes."""
    if val is None:
        return None
    try:
        return Decimal(str(round(float(val), 6)))
    except Exception:
        return None


def _safe_float(item, field, default=None):
    """Safely extract a numeric value from a DynamoDB item."""
    if item and field in item:
        try:
            return float(item[field])
        except (TypeError, ValueError):
            return default
    return default


def _decimalize_dict(d):
    """Recursively convert all floats/ints in a dict to Decimal for DynamoDB."""
    if isinstance(d, dict):
        return {k: _decimalize_dict(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_decimalize_dict(i) for i in d]
    if isinstance(d, float):
        if math.isnan(d) or math.isinf(d):
            return None
        return Decimal(str(round(d, 6)))
    if isinstance(d, int) and not isinstance(d, bool):
        return Decimal(str(d))
    return d


def _slugify(text):
    """Create a URL-safe slug from text for LEARNING# sort keys."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return slug[:60].strip("-")


# =============================================================================
# DATA FETCHING
# =============================================================================


def _fetch_range(source, start_date, end_date):
    """Paginated DynamoDB query for source records in a date range."""
    try:
        records = []
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": USER_PREFIX + source,
                ":s": "DATE#" + start_date,
                ":e": "DATE#" + end_date,
            },
        }
        while True:
            r = table.query(**with_phase_filter(kwargs))
            records.extend(_decimal_to_float(i) for i in r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning("fetch_range(%s, %s -> %s) failed: %s", source, start_date, end_date, e)
        return []


def _fetch_predictions():
    """
    Fetch all evaluable predictions across all coaches.

    Queries each coach's PREDICTION# prefix and filters to statuses
    in EVALUABLE_STATUSES. Skips qualitative evaluation types.
    """
    predictions = []
    for coach_id in COACH_IDS:
        try:
            kwargs = {
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                "ExpressionAttributeValues": {
                    ":pk": f"COACH#{coach_id}",
                    ":prefix": "PREDICTION#",
                },
            }
            while True:
                resp = table.query(**with_phase_filter(kwargs))
                items = [_decimal_to_float(i) for i in resp.get("Items", [])]
                for item in items:
                    status = item.get("status", "")
                    eval_type = item.get("evaluation", {}).get("type", "")
                    if status in EVALUABLE_STATUSES and eval_type != "qualitative":
                        predictions.append(item)
                if "LastEvaluatedKey" not in resp:
                    break
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        except Exception as e:
            logger.warning("Failed to fetch predictions for %s: %s", coach_id, e)
    logger.info("Total evaluable predictions fetched: %d", len(predictions))
    return predictions


def _fetch_commitments():
    """Fetch pending COMMITMENT# records across all coaches (#532).

    Commitments are the concrete actions a coach pushed the subject to take. The
    metric-backed ones (action_check set) are graded kept/broken here; the rest
    are left for the coach to ask about, but expire to 'unresolved' past 2x window.
    """
    commitments = []
    for coach_id in COACH_IDS:
        try:
            kwargs = {
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                "ExpressionAttributeValues": {
                    ":pk": f"COACH#{coach_id}",
                    ":prefix": "COMMITMENT#",
                },
            }
            while True:
                resp = table.query(**with_phase_filter(kwargs))
                for item in (_decimal_to_float(i) for i in resp.get("Items", [])):
                    if item.get("status", "") == "pending":
                        commitments.append(item)
                if "LastEvaluatedKey" not in resp:
                    break
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        except Exception as e:
            logger.warning("Failed to fetch commitments for %s: %s", coach_id, e)
    logger.info("Total pending commitments fetched: %d", len(commitments))
    return commitments


def _update_commitment_status(commitment, status, reason, today_str):
    """Write a commitment's follow-through outcome (kept/broken/unresolved)."""
    try:
        pk = commitment.get("pk") or f"COACH#{commitment.get('coach_id', '')}"
        sk = commitment.get("sk") or f"COMMITMENT#{commitment.get('commitment_id', '')}"
        notes = json.dumps({"reason": reason, "algo_version": ALGO_VERSION})
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #status = :status, outcome = :outcome, outcome_date = :odate, outcome_notes = :notes",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": status, ":outcome": status, ":odate": today_str, ":notes": notes},
        )
        logger.info("Commitment %s -> %s", commitment.get("commitment_id", "?"), status)
    except Exception as e:
        logger.error("Failed to update commitment %s: %s", commitment.get("commitment_id", "?"), e)


def _evaluate_commitments(commitments, today_str, data_cache):
    """Grade due commitments' follow-through against the data (#532).

    Metric-backed commitments reuse the directional evaluator: the action_check
    metric moving in the committed direction is evidence the subject followed
    through (kept); moving the opposite way is broken; flat/no-data is unresolved
    once past expiry, else left pending. Metric-less commitments can't be auto-graded
    — they expire to 'unresolved' past 2x window so the coach stops carrying them.
    """
    today = datetime.strptime(today_str, "%Y-%m-%d")
    stats = {"kept": 0, "broken": 0, "unresolved": 0, "pending": 0}
    for c in commitments:
        created_date = c.get("created_date")
        window_days = int(c.get("window_days") or 7)
        try:
            created_dt = datetime.strptime(created_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        due = created_dt + timedelta(days=window_days)
        if today < due:
            stats["pending"] += 1
            continue  # not due yet

        expired = (today - created_dt).days > window_days * EXPIRY_MULTIPLIER
        action_check = c.get("action_check")
        if action_check and action_check.get("metric") and action_check.get("direction"):
            eval_spec = {"type": "directional", "metric": action_check["metric"], "condition": action_check["direction"]}
            result = _evaluate_directional({}, eval_spec, data_cache, today_str) or {}
            r_status = result.get("status", "inconclusive")
            if r_status == "confirmed":
                status = "kept"
            elif r_status == "refuted":
                status = "broken"
            elif expired:
                status = "unresolved"
            else:
                stats["pending"] += 1
                continue
            _update_commitment_status(c, status, result.get("reason", ""), today_str)
            stats[status] += 1
        else:
            # No machine check — the coach owns following up. Expire stale ones so
            # they don't accumulate as forever-open.
            if expired:
                _update_commitment_status(
                    c, "unresolved", "No machine-checkable action; window elapsed without coach follow-up.", today_str
                )
                stats["unresolved"] += 1
            else:
                stats["pending"] += 1
    logger.info(
        "Commitment stats: kept=%d broken=%d unresolved=%d pending=%d",
        stats["kept"],
        stats["broken"],
        stats["unresolved"],
        stats["pending"],
    )
    return stats


# =============================================================================
# METRIC RESOLUTION
# =============================================================================


def _extract_metric_series(records, metric):
    """
    Extract a chronological list of (date_str, value) tuples for a metric
    from a list of DynamoDB records, sorted by date.
    """
    series = []
    for rec in records:
        val = _safe_float(rec, metric)
        if val is not None:
            date_str = rec.get("date") or (rec.get("sk", "").replace("DATE#", ""))
            if date_str:
                series.append((date_str, val))
    series.sort(key=lambda x: x[0])
    return series


def _resolve_metric_value(metric_key, data_cache, end_date):
    """
    Resolve a metric key to a current numeric value.

    Supports:
      - Raw metric names (returns most recent value in last 7 days)
      - Computed aggregates: hrv_7day_avg, hrv_14day_avg, hrv_30day_avg
    """
    # Handle computed aggregate metrics
    for suffix, days in [("_30day_avg", 30), ("_14day_avg", 14), ("_7day_avg", 7)]:
        if metric_key.endswith(suffix):
            base_metric = metric_key[: -len(suffix)]
            return _compute_metric_average(base_metric, data_cache, end_date, days)

    # Raw metric — get most recent value from last 7 days
    source = METRIC_SOURCES.get(metric_key)
    if not source:
        logger.warning("No source mapping for metric: %s", metric_key)
        return None

    records = _get_source_data(source, data_cache, end_date, lookback_days=7)
    series = _extract_metric_series(records, metric_key)
    if series:
        return series[-1][1]  # Most recent value
    return None


def _compute_metric_average(base_metric, data_cache, end_date, days):
    """Compute the average of the last N days for a base metric."""
    source = METRIC_SOURCES.get(base_metric)
    if not source:
        return None

    records = _get_source_data(source, data_cache, end_date, lookback_days=days)
    series = _extract_metric_series(records, base_metric)
    if not series:
        return None

    recent = [v for _, v in series[-days:]]
    if not recent:
        return None
    return sum(recent) / len(recent)


def _get_source_data(source, data_cache, end_date, lookback_days=30):
    """
    Fetch source data with caching. Avoids re-querying the same source
    if data for a sufficient range is already loaded.
    """
    cache_key = f"{source}:{lookback_days}"
    if cache_key in data_cache:
        return data_cache[cache_key]

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=lookback_days)
    start_str = start_dt.strftime("%Y-%m-%d")

    records = _fetch_range(source, start_str, end_date)
    data_cache[cache_key] = records
    return records


def _compute_ewma(values, decay):
    """
    Exponentially weighted moving average.
    Values are ordered chronologically — most recent value last.
    """
    if not values:
        return None
    n = len(values)
    weights = [(1 - decay) * (decay**i) for i in range(n - 1, -1, -1)]
    weight_sum = sum(weights)
    if weight_sum == 0:
        return None
    return sum(w * v for w, v in zip(weights, values)) / weight_sum


def _get_ewma_trend(metric_key, data_cache, end_date):
    """
    Compute EWMA trend direction and slope for a metric.

    Returns (direction, slope) where direction is 'up', 'down', or 'flat',
    and slope is the fractional change between current EWMA and 7-day-ago EWMA.
    """
    source = METRIC_SOURCES.get(metric_key)
    if not source:
        # Try stripping common suffixes
        for suffix in ["_7day_avg", "_14day_avg", "_30day_avg"]:
            if metric_key.endswith(suffix):
                source = METRIC_SOURCES.get(metric_key[: -len(suffix)])
                break
    if not source:
        return None, None

    records = _get_source_data(source, data_cache, end_date, lookback_days=30)
    base_metric = metric_key
    for suffix in ["_7day_avg", "_14day_avg", "_30day_avg"]:
        if base_metric.endswith(suffix):
            base_metric = base_metric[: -len(suffix)]
            break

    series = _extract_metric_series(records, base_metric)
    values = [v for _, v in series]

    if len(values) < 5:
        return None, None

    current_ewma = _compute_ewma(values, EWMA_DECAY)
    cutoff = max(1, len(values) - 7)
    prior_values = values[:cutoff]
    prior_ewma = _compute_ewma(prior_values, EWMA_DECAY) if len(prior_values) >= 2 else None

    if current_ewma is None or prior_ewma is None or prior_ewma == 0:
        return None, None

    slope = (current_ewma - prior_ewma) / abs(prior_ewma)
    if slope > DIRECTIONAL_NOISE_THRESHOLD:
        direction = "up"
    elif slope < -DIRECTIONAL_NOISE_THRESHOLD:
        direction = "down"
    else:
        direction = "flat"

    return direction, slope


# =============================================================================
# EVALUATION LOGIC
# =============================================================================


def _evaluate_condition(actual, condition, threshold):
    """Evaluate a prediction condition against a threshold."""
    if actual is None or threshold is None:
        return None  # Inconclusive — missing data
    cond_map = {
        "gt": actual > threshold,
        "gte": actual >= threshold,
        "lt": actual < threshold,
        "lte": actual <= threshold,
        "eq": abs(actual - threshold) < 0.01,
    }
    return cond_map.get(condition)


def _get_effective_window(eval_spec, subdomain):
    """
    Enforce domain-appropriate minimum evaluation windows.

    The prediction's stated window is used if it meets the domain minimum;
    otherwise the domain minimum is enforced.
    """
    stated_window = int(eval_spec.get("evaluation_window_days", 14))
    domain = SUBDOMAIN_TO_DOMAIN.get(subdomain, "training")
    min_window = DOMAIN_MIN_WINDOWS.get(domain, 14)
    return max(stated_window, min_window)


def _evaluate_machine(pred, eval_spec, data_cache, today_str):
    """
    Machine evaluation: metric crosses threshold within window.

    Steps:
      1. Fetch current metric value
      2. Apply condition against threshold
      3. Compare against null hypothesis
      4. Return status: confirmed / refuted / inconclusive
    """
    metric_key = eval_spec.get("metric")
    if not metric_key:
        return None

    actual_value = _resolve_metric_value(metric_key, data_cache, today_str)
    threshold = eval_spec.get("threshold")
    condition = eval_spec.get("condition")

    if actual_value is None:
        return {
            "status": "inconclusive",
            "reason": f"No data available for metric '{metric_key}'",
            "actual_value": None,
            "beats_null": False,
        }

    result = _evaluate_condition(actual_value, condition, threshold)

    if result is None:
        return {
            "status": "inconclusive",
            "reason": f"Could not evaluate condition '{condition}'",
            "actual_value": round(actual_value, 4),
            "beats_null": False,
        }

    # Determine status considering null hypothesis
    null_text = eval_spec.get("null_hypothesis", "")
    beats_null_if = eval_spec.get("beats_null_if", "")

    if result:
        if null_text:
            # Has a null hypothesis — check beats_null_if
            if beats_null_if == "exceeds_threshold":
                beats_null = True
            elif beats_null_if == "meets_threshold":
                beats_null = True
            else:
                beats_null = True  # Default: confirmed with null = beats null
            status = "confirmed"
        else:
            status = "confirmed"
            beats_null = False  # No null hypothesis to beat
    else:
        status = "refuted"
        beats_null = False

    return {
        "status": status,
        "reason": (f"{metric_key}={actual_value:.4f} " f"{'meets' if result else 'fails'} " f"{condition} {threshold}"),
        "actual_value": round(actual_value, 4),
        "beats_null": beats_null,
    }


def _evaluate_directional(pred, eval_spec, data_cache, today_str):
    """
    Directional evaluation: metric moves in predicted direction.

    Uses EWMA trend detection to determine actual direction, then compares
    against the predicted direction. Confirmed only if the direction matches
    AND the magnitude exceeds the noise threshold.
    """
    metric_key = eval_spec.get("metric")
    predicted_direction = eval_spec.get("condition")  # "up" or "down"
    if not metric_key or not predicted_direction:
        return None

    actual_direction, slope = _get_ewma_trend(metric_key, data_cache, today_str)

    if actual_direction is None:
        return {
            "status": "inconclusive",
            "reason": f"Insufficient data to determine trend for '{metric_key}'",
            "actual_value": None,
            "beats_null": False,
        }

    # Normalize predicted direction
    pred_dir = predicted_direction.lower().strip()
    if pred_dir not in ("up", "down"):
        return {
            "status": "inconclusive",
            "reason": f"Invalid predicted direction: '{predicted_direction}'",
            "actual_value": None,
            "beats_null": False,
        }

    direction_matches = actual_direction == pred_dir
    magnitude_sufficient = abs(slope) > DIRECTIONAL_NOISE_THRESHOLD if slope else False

    if direction_matches and magnitude_sufficient:
        status = "confirmed"
        beats_null = True
    elif actual_direction == "flat":
        status = "inconclusive"
        beats_null = False
    else:
        status = "refuted"
        beats_null = False

    return {
        "status": status,
        "reason": (f"{metric_key} trend={actual_direction} (slope={slope:.4f}), " f"predicted={pred_dir}"),
        "actual_value": slope,
        "beats_null": beats_null,
    }


def _evaluate_conditional(pred, eval_spec, data_cache, today_str):
    """
    Conditional evaluation: if X then Y.

    Structure in eval_spec:
      - condition_metric: the precondition metric (X)
      - condition_threshold: threshold for X
      - condition_condition: comparison operator for X
      - metric: the outcome metric (Y)
      - threshold: threshold for Y
      - condition: comparison operator for Y (overloaded, but Y's operator)

    If the precondition is not met, status remains 'pending' (re-evaluate later).
    If precondition met, evaluate Y normally.
    """
    # Check precondition X
    cond_metric = eval_spec.get("condition_metric")
    cond_threshold = eval_spec.get("condition_threshold")
    cond_condition = eval_spec.get("condition_condition")

    if not cond_metric or cond_threshold is None or not cond_condition:
        return None  # Malformed conditional — skip

    x_value = _resolve_metric_value(cond_metric, data_cache, today_str)
    if x_value is None:
        return {
            "status": "pending",
            "reason": f"Precondition metric '{cond_metric}' has no data",
            "actual_value": None,
            "beats_null": False,
        }

    x_met = _evaluate_condition(x_value, cond_condition, cond_threshold)
    if not x_met:
        return {
            "status": "pending",
            "reason": (f"Precondition not met: {cond_metric}={x_value:.4f} " f"does not satisfy {cond_condition} {cond_threshold}"),
            "actual_value": None,
            "beats_null": False,
        }

    # Precondition met — evaluate Y
    y_result = _evaluate_machine(pred, eval_spec, data_cache, today_str)
    if y_result:
        y_result["reason"] = f"Precondition met ({cond_metric}={x_value:.4f} " f"{cond_condition} {cond_threshold}). " + y_result.get(
            "reason", ""
        )
    return y_result


def _check_expiry(pred, effective_window, today):
    """
    Check if a prediction should expire.

    A prediction expires if its window has elapsed by more than 2x
    the original window AND it's still not evaluable (no data).
    Returns True if expired.
    """
    created_date = pred.get("created_date")
    if not created_date:
        return False

    try:
        created_dt = datetime.strptime(created_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False

    days_since_creation = (today - created_dt).days
    max_allowed = effective_window * EXPIRY_MULTIPLIER

    return days_since_creation > max_allowed


# =============================================================================
# DYNAMO WRITES
# =============================================================================


def _update_prediction_status(prediction, evaluation):
    """Update a prediction record with its evaluation outcome."""
    try:
        pk = prediction.get("pk") or f"COACH#{prediction.get('coach_id', '')}"
        sk = prediction.get("sk") or f"PREDICTION#{prediction.get('prediction_id', '')}"

        outcome_notes = json.dumps(
            {
                "actual_value": evaluation.get("actual_value"),
                "reason": evaluation.get("reason", ""),
                "beats_null": evaluation.get("beats_null", False),
                "bayesian_update": evaluation.get("bayesian_update"),
                "algo_version": ALGO_VERSION,
            }
        )

        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression=("SET #status = :status, outcome = :outcome, " "outcome_date = :odate, outcome_notes = :notes"),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": evaluation["status"],
                ":outcome": evaluation["status"],
                ":odate": evaluation["evaluated_date"],
                ":notes": outcome_notes,
            },
        )
        logger.info("Updated prediction %s -> %s", evaluation.get("prediction_id", "?"), evaluation["status"])
    except Exception as e:
        logger.error("Failed to update prediction %s: %s", evaluation.get("prediction_id", "?"), e)


def _update_bayesian_confidence(coach_id, subdomain, update_type):
    """
    Update the Bayesian confidence (Beta distribution) for a coach's subdomain.

    Beta(alpha, beta): alpha += 1 for success, beta += 1 for failure.
    Uninformed prior: Beta(1, 1).
    """
    pk = f"COACH#{coach_id}"
    sk = f"CONFIDENCE#{subdomain}"

    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")

        if item:
            alpha = float(item.get("alpha", 1))
            beta_val = float(item.get("beta_param", 1))
        else:
            alpha = 1.0
            beta_val = 1.0

        if update_type == "success":
            alpha += 1
        elif update_type == "failure":
            beta_val += 1

        mean_confidence = alpha / (alpha + beta_val)
        sample_size = int(alpha + beta_val - 2)

        table.put_item(
            Item={
                "pk": pk,
                "sk": sk,
                "alpha": _to_decimal(alpha),
                "beta_param": _to_decimal(beta_val),
                "mean_confidence": _to_decimal(mean_confidence),
                "sample_size": Decimal(str(max(0, sample_size))),
                "subdomain": subdomain,
                "coach_id": coach_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info(
            "Updated confidence for %s/%s: Beta(%.0f,%.0f) = %.3f (n=%d)",
            coach_id,
            subdomain,
            alpha,
            beta_val,
            mean_confidence,
            sample_size,
        )
    except Exception as e:
        logger.error("Failed to update Bayesian confidence for %s/%s: %s", coach_id, subdomain, e)


def _write_learning_record(coach_id, today_str, evaluation):
    """
    Write a LEARNING# record documenting the evaluation outcome.

    These records build an audit trail of what the coach got right and wrong,
    enabling downstream analysis of prediction calibration.
    """
    prediction_id = evaluation.get("prediction_id", "unknown")
    slug = _slugify(f"{prediction_id}-{evaluation.get('status', 'eval')}")
    pk = f"COACH#{coach_id}"
    sk = f"LEARNING#{today_str}#{slug}"

    try:
        item = {
            "pk": pk,
            "sk": sk,
            "coach_id": coach_id,
            "date": today_str,
            "prediction_id": prediction_id,
            "evaluation_type": evaluation.get("evaluation_type", "machine"),
            "status": evaluation.get("status", ""),
            "metric": evaluation.get("metric", ""),
            "actual_value": _to_decimal(evaluation.get("actual_value")),
            "threshold": _to_decimal(evaluation.get("threshold")),
            "condition": evaluation.get("condition", ""),
            "subdomain": evaluation.get("subdomain", ""),
            "beats_null": evaluation.get("beats_null", False),
            "bayesian_update": evaluation.get("bayesian_update"),
            "reason": evaluation.get("reason", ""),
            "algo_version": ALGO_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Remove None values to keep items clean
        item = {k: v for k, v in item.items() if v is not None}
        table.put_item(Item=item)
        logger.info("Wrote LEARNING record: %s / %s", pk, sk)
    except Exception as e:
        logger.error("Failed to write LEARNING record for %s: %s", prediction_id, e)


# =============================================================================
# MAIN EVALUATION LOOP
# =============================================================================


def _evaluate_all(predictions, today_str):
    """
    Evaluate all pending predictions.

    For each prediction:
      1. Determine effective evaluation window (with domain minimum)
      2. Check if window has elapsed
      3. Route to appropriate evaluator (machine / directional / conditional)
      4. Handle expiry for unevaluable predictions
      5. Update prediction status in DynamoDB
      6. Update Bayesian confidence if confirmed or refuted
      7. Write LEARNING# record

    Returns a list of evaluation result dicts.
    """
    today = datetime.strptime(today_str, "%Y-%m-%d")
    data_cache = {}  # Shared cache across all evaluations
    evaluations = []
    stats = {
        "confirmed": 0,
        "refuted": 0,
        "inconclusive": 0,
        "expired": 0,
        "skipped_window": 0,
        "skipped_error": 0,
        "pending": 0,
    }

    for pred in predictions:
        eval_spec = pred.get("evaluation", {})
        eval_type = eval_spec.get("type", "machine")
        coach_id = pred.get("coach_id", "")
        subdomain = pred.get("subdomain", "")
        prediction_id = pred.get("prediction_id") or pred.get("sk", "").replace("PREDICTION#", "")

        # Determine effective window with domain minimum enforcement
        effective_window = _get_effective_window(eval_spec, subdomain)

        # Check if evaluation window has elapsed
        created_date = pred.get("created_date")
        if not created_date:
            stats["skipped_error"] += 1
            continue

        try:
            created_dt = datetime.strptime(created_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            stats["skipped_error"] += 1
            continue

        eval_deadline = created_dt + timedelta(days=effective_window)
        if today < eval_deadline:
            stats["skipped_window"] += 1
            continue  # Window hasn't elapsed yet

        # Route to appropriate evaluator
        result = None
        try:
            if eval_type == "machine":
                result = _evaluate_machine(pred, eval_spec, data_cache, today_str)
            elif eval_type == "directional":
                result = _evaluate_directional(pred, eval_spec, data_cache, today_str)
            elif eval_type == "conditional":
                result = _evaluate_conditional(pred, eval_spec, data_cache, today_str)
            else:
                logger.info("Skipping unsupported evaluation type: %s", eval_type)
                stats["skipped_error"] += 1
                continue
        except Exception as e:
            logger.error("Evaluation error for %s (%s): %s", prediction_id, eval_type, e)
            stats["skipped_error"] += 1
            continue

        if result is None:
            stats["skipped_error"] += 1
            continue

        status = result.get("status", "inconclusive")

        # Handle expiry: if inconclusive and past expiry window, mark expired
        if status == "inconclusive" and _check_expiry(pred, effective_window, today):
            status = "expired"
            result["status"] = "expired"
            result["reason"] = (
                f"Expired: {(today - created_dt).days} days elapsed "
                f"(window={effective_window}, max={effective_window * EXPIRY_MULTIPLIER}). " + result.get("reason", "")
            )

        # If conditional evaluation returns 'pending', don't write yet
        if status == "pending":
            stats["pending"] += 1
            continue

        # Determine Bayesian update direction
        bayesian_update = None
        if status == "confirmed" and result.get("beats_null"):
            bayesian_update = "success"  # alpha += 1
        elif status == "refuted":
            bayesian_update = "failure"  # beta += 1
        # inconclusive, expired, or confirmed-but-matches-null: no update

        evaluation = {
            "prediction_id": prediction_id,
            "coach_id": coach_id,
            "subdomain": subdomain,
            "evaluation_type": eval_type,
            "metric": eval_spec.get("metric", ""),
            "threshold": eval_spec.get("threshold"),
            "condition": eval_spec.get("condition", ""),
            "actual_value": result.get("actual_value"),
            "status": status,
            "beats_null": result.get("beats_null", False),
            "bayesian_update": bayesian_update,
            "reason": result.get("reason", ""),
            "created_date": created_date,
            "evaluated_date": today_str,
            "evaluation_window_days": effective_window,
        }
        evaluations.append(evaluation)

        # Write status update to prediction record
        _update_prediction_status(pred, evaluation)

        # Update Bayesian confidence if applicable
        if bayesian_update and coach_id and subdomain:
            _update_bayesian_confidence(coach_id, subdomain, bayesian_update)

        # Write learning log record
        _write_learning_record(coach_id, today_str, evaluation)

        stats[status] = stats.get(status, 0) + 1

    logger.info(
        "Evaluation stats: confirmed=%d refuted=%d inconclusive=%d " "expired=%d pending=%d skipped_window=%d skipped_error=%d",
        stats["confirmed"],
        stats["refuted"],
        stats["inconclusive"],
        stats["expired"],
        stats["pending"],
        stats["skipped_window"],
        stats["skipped_error"],
    )
    return evaluations, stats


# =============================================================================
# #534: EVENT-DRIVEN STANCE REFRESH — deterministic significant-event detector
# =============================================================================
#
# Epic #526's "weekly-frozen personality" gap: STANCE# (the coach-opinion) only
# refreshes on the Sunday batch (coach_history_summarizer.py), so a big Tuesday
# event changes nothing until the weekend. This runs at the end of the
# (already daily, already deterministic, already no-LLM) evaluation pass and
# fires an ASYNC, single-coach STANCE# refresh for the coach whose domain the
# event actually happened in — never a platform-wide refresh.
#
# Four event classes, each deterministic and read from data this run already
# has in memory or can cheaply read (no LLM, no guessing at "significance" —
# every trigger below is a hard, already-computed fact):
#   - prediction_refuted  — one of a coach's own predictions was just graded
#                            refuted by _evaluate_all above (free — already in
#                            memory). Coach: the prediction's own coach_id.
#   - sick_day_onset      — a sick day was logged for today and NOT yesterday
#                            (onset only, so a multi-day sick spell fires once,
#                            not once per day of the spell). Coach: physical_coach
#                            (longevity_medicine / "the long arc" — the closest
#                            of the 8 to a body-recovery owner; no dedicated
#                            recovery coach exists to route to instead).
#   - vice_relapse        — a habit_scores.vice_streaks entry dropped from >0
#                            to 0 between yesterday and today. Coach: mind_coach
#                            (behavioral_psychology — "the stories behind the
#                            streaks" is its own bio line in config/personas.json).
#   - weight_milestone    — today's resolved weight crossed one of the canonical
#                            _WEIGHT_MILESTONES thresholds (ai_context.py) that
#                            yesterday's resolved weight had not yet crossed —
#                            a strict crossing, not a fuzzy proximity window, so
#                            it fires exactly once, the day it's actually true.
#                            Coach: physical_coach (longevity_medicine — the
#                            milestones are framed as biological/longevity
#                            events: sleep-apnea risk, cardiovascular age, FFMI).
#
# Deliberately NOT covered here: "a PR" (a new personal record), even though
# the epic names it. The only existing PR computation
# (mcp/tools_training.py::tool_get_personal_records) is an MCP-package,
# on-demand, full-history scan (2000-01-01 → today) built on MCP-only helpers
# (get_profile / parallel_query_sources / get_sot) that aren't available to this
# bundle without a new cross-package coupling the deploy convention warns
# against (docs/CONVENTIONS.md — the single-file/bundle sibling-import trap).
# Rather than invent a cheaper, unvetted approximation, this is left as a named,
# documented fast-follow (see the PR description) instead of guessing broadly.
#
# Budget (matches epic #526's Budget line verbatim): capped Haiku calls, ≤2/day
# PLATFORM-WIDE (not per-coach) — a mid-week refresh is a nice-to-have, not the
# product; the $75/mo ceiling and the Sunday batch stay the priority. Same
# tier-1 cutoff as every other coach narrative (budget_guard "coach_narrative").

STANCE_EVENT_REFRESH_DAILY_CAP = 2  # epic #526 Budget: "Capped Haiku calls (≤2/day platform-wide)"

from ai_context import _WEIGHT_MILESTONES  # noqa: E402 — the one canonical list (see ai_context._build_milestone_context)
from budget_guard import allow as _budget_allow  # noqa: E402
from sick_day_checker import check_sick_day  # noqa: E402

# physical_coach owns both sick-day onset and weight-milestone crossings (see
# the docstring above); mind_coach owns vice-streak relapses.
_SICK_DAY_COACH = "physical_coach"
_RELAPSE_COACH = "mind_coach"
_MILESTONE_COACH = "physical_coach"


def _detect_prediction_miss_events(evaluations):
    """A coach's own prediction was refuted THIS run — the coach's most
    confident public claims just took a deterministic, real hit. One event per
    coach even if multiple predictions refuted the same day (the cap is
    precious; the refresh reasons over the whole track record, not one miss)."""
    events = {}
    for e in evaluations or []:
        if e.get("status") != "refuted":
            continue
        coach_id = e.get("coach_id")
        if not coach_id or coach_id in events:
            continue
        claim = e.get("metric") or "a prediction"
        events[coach_id] = {
            "type": "prediction_refuted",
            "detail": f"a prediction about {claim} was just graded refuted ({e.get('reason', '')})".strip(),
        }
    return events


def _detect_sick_day_event(today_str, yesterday_str):
    """Sick day ONSET only (today flagged, yesterday not) — a multi-day sick
    spell must not re-fire the refresh once per day of the spell."""
    try:
        today_sick = check_sick_day(table, USER_ID, today_str)
        if not today_sick:
            return None
        yesterday_sick = check_sick_day(table, USER_ID, yesterday_str)
        if yesterday_sick:
            return None  # continuation, not onset
        reason = (today_sick or {}).get("reason") or "logged"
        return {"type": "sick_day_onset", "detail": f"a sick day was logged today ({reason})"}
    except Exception as e:
        logger.warning("[stance-event] sick day check failed (non-fatal): %s", e)
        return None


def _habit_scores_for(date_str):
    try:
        resp = table.get_item(Key={"pk": f"{USER_PREFIX}habit_scores", "sk": f"DATE#{date_str}"})
        return _decimal_to_float(resp.get("Item")) or {}
    except Exception as e:
        logger.warning("[stance-event] habit_scores read failed for %s (non-fatal): %s", date_str, e)
        return {}


def _detect_relapse_event(today_str, yesterday_str):
    """Any vice whose streak dropped from >0 to 0 between yesterday and today."""
    today_vs = (_habit_scores_for(today_str) or {}).get("vice_streaks") or {}
    if not isinstance(today_vs, dict) or not today_vs:
        return None
    yesterday_vs = (_habit_scores_for(yesterday_str) or {}).get("vice_streaks") or {}
    if not isinstance(yesterday_vs, dict):
        return None
    relapsed = sorted(v for v, streak in today_vs.items() if streak == 0 and (yesterday_vs.get(v) or 0) > 0)
    if not relapsed:
        return None
    return {"type": "vice_relapse", "detail": f"the streak on {', '.join(relapsed)} just reset to 0"}


def _crossed_milestones(prior_weight, current_weight):
    """Milestones whose threshold sits strictly between prior and current
    weight — a downward crossing only (this is a weight-LOSS journey; a regain
    isn't the positive 'milestone' _WEIGHT_MILESTONES models)."""
    if prior_weight is None or current_weight is None or current_weight >= prior_weight:
        return []
    return [m for m in _WEIGHT_MILESTONES if current_weight <= m["weight_lbs"] < prior_weight]


def _detect_milestone_event(today_str, yesterday_str):
    """A canonical weight milestone (ai_context._WEIGHT_MILESTONES) crossed
    strictly between yesterday's and today's resolved weight.

    Each call gets its OWN fresh data_cache — _get_source_data's cache key is
    `{source}:{lookback_days}` (no end_date component, #534 audit), so sharing
    one cache dict across the today/yesterday calls would silently serve
    today's fetch back for the "yesterday" lookup too and the crossing check
    would never fire. Two isolated one-shot caches sidestep that trap cleanly
    rather than touching the shared caching helper other evaluators rely on.
    """
    try:
        current = _resolve_metric_value("weight_lbs", {}, today_str)
        prior = _resolve_metric_value("weight_lbs", {}, yesterday_str)
        crossed = _crossed_milestones(prior, current)
        if not crossed:
            return None
        deepest = min(crossed, key=lambda m: m["weight_lbs"])  # multiple crossed in one day -> report the furthest
        return {"type": "weight_milestone", "detail": f"'{deepest['name']}' just crossed — {deepest['significance']}"}
    except Exception as e:
        logger.warning("[stance-event] milestone check failed (non-fatal): %s", e)
        return None


def _detect_stance_events(evaluations, today_str, yesterday_str):
    """Union of all 4 deterministic event classes, deduped to ONE event per
    coach (first class wins if a coach somehow qualifies for two the same day).
    Returns {coach_id: {"type": ..., "detail": ...}}."""
    events = _detect_prediction_miss_events(evaluations)

    sick = _detect_sick_day_event(today_str, yesterday_str)
    if sick and _SICK_DAY_COACH not in events:
        events[_SICK_DAY_COACH] = sick

    relapse = _detect_relapse_event(today_str, yesterday_str)
    if relapse and _RELAPSE_COACH not in events:
        events[_RELAPSE_COACH] = relapse

    milestone = _detect_milestone_event(today_str, yesterday_str)
    if milestone and _MILESTONE_COACH not in events:
        events[_MILESTONE_COACH] = milestone

    return events


def _event_refresh_count_today(today_str):
    """How many event-driven STANCE# refreshes have already landed today,
    across all 8 coach partitions (cheap — 8 GetItems, no GSI/scan needed).
    Counts only trigger="event:*" writes, never the weekly Sunday batch, so
    the two caps stay independent of each other."""
    count = 0
    for coach_id in COACH_IDS:
        try:
            resp = table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": f"STANCE#{today_str}"})
            item = resp.get("Item")
            if item and str(item.get("trigger", "")).startswith("event:"):
                count += 1
        except Exception as e:
            logger.warning("[stance-event] cap check read failed for %s (non-fatal): %s", coach_id, e)
    return count


def _fire_event_stance_refreshes(events, today_str):
    """Budget-gate, cap-enforce, and async-invoke coach-history-summarizer's
    mid-week single-coach refresh path (#534) for each detected event, up to
    STANCE_EVENT_REFRESH_DAILY_CAP total across the whole platform per day.

    Fail-soft throughout — a detection or invoke error here must never fail
    the prediction-evaluation run this is bolted onto.
    """
    if not events:
        return {"detected": 0, "fired": 0, "skipped": "no_events"}

    if not _budget_allow("coach_narrative"):
        logger.info("[stance-event] budget tier paused coach narratives — skipping all %d event(s)", len(events))
        return {"detected": len(events), "fired": 0, "skipped": "budget_tier"}

    already_today = _event_refresh_count_today(today_str)
    remaining = max(0, STANCE_EVENT_REFRESH_DAILY_CAP - already_today)
    if remaining <= 0:
        logger.info(
            "[stance-event] daily cap (%d) already reached (%d done) — skipping %d event(s)",
            STANCE_EVENT_REFRESH_DAILY_CAP,
            already_today,
            len(events),
        )
        return {"detected": len(events), "fired": 0, "skipped": "daily_cap_reached", "already_today": already_today}

    fired = []
    for coach_id, event_context in events.items():
        if len(fired) >= remaining:
            break
        try:
            _lambda_client.invoke(
                FunctionName="coach-history-summarizer",
                InvocationType="Event",  # async, fire-and-forget — never block the evaluator
                Payload=json.dumps(
                    {
                        "mode": "event_stance_refresh",
                        "coach_id": coach_id,
                        "trigger_event": event_context,
                    }
                ).encode(),
            )
            fired.append(coach_id)
            logger.info("[stance-event] fired mid-week refresh for %s (%s)", coach_id, event_context.get("type"))
        except Exception as e:
            logger.warning("[stance-event] invoke failed for %s (non-fatal): %s", coach_id, e)

    return {"detected": len(events), "fired": len(fired), "coaches": fired, "already_today": already_today}


# =============================================================================
# #727: SCIENTIFIC-LIVENESS HEARTBEAT
# =============================================================================


def _read_last_decided_date():
    """The date grading last produced a decided (confirmed/refuted) outcome, or
    None if the marker has never been written. Exact-key GetItem — not phase
    filtered (this is operational system-state, not experiment-scoped data)."""
    try:
        item = table.get_item(Key={"pk": _LAST_DECIDED_PK, "sk": _LAST_DECIDED_SK}).get("Item")
        return (item or {}).get("date")
    except Exception as e:
        logger.warning("[liveness] read last-decided marker failed (non-fatal): %s", e)
        return None


def _write_last_decided_date(today_str):
    """Stamp the last-decided marker to today. Called only when this run actually
    decided something, so the DaysSinceLastDecided gauge resets to 0."""
    try:
        table.put_item(
            Item={
                "pk": _LAST_DECIDED_PK,
                "sk": _LAST_DECIDED_SK,
                "date": today_str,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        logger.warning("[liveness] write last-decided marker failed (non-fatal): %s", e)


def _days_since(today_str, prior_str):
    """Whole days between two YYYY-MM-DD strings (>= 0), or the never sentinel if
    prior is missing/unparseable."""
    if not prior_str:
        return _NEVER_DECIDED_DAYS
    try:
        d = (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(prior_str, "%Y-%m-%d")).days
        return max(0, d)
    except (ValueError, TypeError):
        return _NEVER_DECIDED_DAYS


def emit_grading_liveness(stats, gradable_count, today_str):
    """#727: emit the scientific-liveness metrics EVERY run (even a zero run — the
    whole point is that a metric must be present daily for the stall alarm to have
    data). Returns the dict it emitted so the handler can surface + tests can pin it.

    - DecidedCount    — confirmed + refuted THIS run (the outcomes that fill the
      public track record). The number that has been silently 0 for weeks.
    - GradableCount   — evaluable predictions found this run (pending/confirming,
      non-qualitative). A gradability floor: >0 gradable but 0 decided over a long
      window is the exact stall this closes.
    - DaysSinceLastDecided — the gauge monitoring_stack.GradingStalled alarms on at
      >= 14. Reads the marker; if this run decided anything, resets to 0 and
      re-stamps the marker. Fail-soft — a metrics error must never sink evaluation.
    """
    decided_count = int(stats.get("confirmed", 0)) + int(stats.get("refuted", 0))

    if decided_count > 0:
        _write_last_decided_date(today_str)
        days_since = 0
    else:
        days_since = _days_since(today_str, _read_last_decided_date())

    payload = {
        "decided_count": decided_count,
        "gradable_count": int(gradable_count),
        "days_since_last_decided": days_since,
    }
    try:
        _cw.put_metric_data(
            Namespace=LIVENESS_NAMESPACE,
            MetricData=[
                {"MetricName": "DecidedCount", "Value": float(decided_count), "Unit": "Count"},
                {"MetricName": "GradableCount", "Value": float(gradable_count), "Unit": "Count"},
                {"MetricName": "DaysSinceLastDecided", "Value": float(days_since), "Unit": "Count"},
            ],
        )
        logger.info(
            "[liveness] decided=%d gradable=%d days_since_last_decided=%d",
            decided_count,
            gradable_count,
            days_since,
        )
    except Exception as e:
        logger.warning("[liveness] metric emit failed (non-fatal): %s", e)
    return payload


# =============================================================================
# LAMBDA HANDLER
# =============================================================================


def lambda_handler(event: dict, context) -> dict:
    """
    Coach Prediction Evaluator entry point.

    Invoked daily by EventBridge. Fetches all pending/confirming predictions
    across all coaches, evaluates those whose window has elapsed, updates
    statuses, Bayesian confidence scores, and writes learning records.

    Returns a summary of all evaluations performed.
    """
    try:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger.info("coach-prediction-evaluator START date=%s", today_str)

        # Fetch all evaluable predictions
        predictions = _fetch_predictions()

        # Run prediction evaluations (commitments are graded below regardless — a coach
        # can have follow-through to check even on a day with no open predictions).
        if predictions:
            evaluations, stats = _evaluate_all(predictions, today_str)
            logger.info("coach-prediction-evaluator COMPLETE: %d predictions evaluated out of %d found", len(evaluations), len(predictions))
        else:
            logger.info("No evaluable predictions found.")
            evaluations, stats = [], {}

        # #532: grade coach commitments' follow-through in the same lane (shares the
        # metric cache; deterministic, zero AI). Fail-soft — a commitment error must
        # never sink the prediction evaluation.
        commitment_stats = {}
        try:
            commitments = _fetch_commitments()
            if commitments:
                commitment_stats = _evaluate_commitments(commitments, today_str, {})
        except Exception as e:
            logger.error("Commitment evaluation failed (non-fatal): %s", e)

        # #534: deterministic significant-event detection -> mid-week STANCE#
        # refresh for the affected coach only. Fail-soft — a detection/invoke
        # error here must never sink prediction evaluation.
        stance_refresh_stats = {}
        try:
            yesterday_str = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            stance_events = _detect_stance_events(evaluations, today_str, yesterday_str)
            stance_refresh_stats = _fire_event_stance_refreshes(stance_events, today_str)
        except Exception as e:
            logger.error("Stance-event detection failed (non-fatal): %s", e)

        # #727: scientific-liveness — emit decided/gradable counts + the
        # days-since-last-decided gauge EVERY run (the stall alarm needs a daily
        # datapoint). gradable_count is the evaluable predictions found this run.
        liveness = {}
        try:
            liveness = emit_grading_liveness(stats, len(predictions), today_str)
        except Exception as e:
            logger.error("Grading-liveness emit failed (non-fatal): %s", e)

        return {
            "statusCode": 200,
            "date": today_str,
            "algo_version": ALGO_VERSION,
            "predictions_found": len(predictions),
            "predictions_evaluated": len(evaluations),
            "stats": stats,
            "commitment_stats": commitment_stats,
            "stance_refresh_stats": stance_refresh_stats,
            "liveness": liveness,
            "evaluations": evaluations,
        }
    except Exception as e:
        logger.error("coach-prediction-evaluator FAILED: %s", e, exc_info=True)
        return {"statusCode": 500, "error": str(e)}
