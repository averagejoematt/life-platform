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
    "sleep_coach", "nutrition_coach", "training_coach",
    "mind_coach", "physical_coach", "glucose_coach",
    "labs_coach", "explorer_coach",
]

# Metric → DynamoDB source mapping
METRIC_SOURCES = {
    "hrv": "whoop",
    "hrv_7day_avg": "whoop",
    "recovery_score": "whoop",
    "resting_heart_rate": "whoop",
    "sleep_duration_hours": "whoop",
    "sleep_score": "whoop",
    "deep_pct": "whoop",
    "rem_pct": "whoop",
    "weight_lbs": "withings",
    "total_calories_kcal": "macrofactor",
    "total_protein_g": "macrofactor",
    "steps": "apple_health",
    "blood_glucose_avg": "apple_health",
    "blood_glucose_std_dev": "apple_health",
    "body_fat_pct": "dexa",
}

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
    "sleep_quality": "sleep", "sleep_duration": "sleep",
    "sleep_efficiency": "sleep", "deep_sleep": "sleep", "rem_sleep": "sleep",
    # nutrition_coach
    "caloric_intake": "nutrition", "protein_intake": "nutrition",
    "macros": "nutrition", "meal_timing": "nutrition",
    # training_coach
    "training_load": "training", "training_frequency": "training",
    "strength": "training", "endurance": "training",
    "performance": "training", "cardio": "training",
    # mind_coach
    "mood": "mood", "stress": "mental", "focus": "mental",
    "mindfulness": "mental",
    # physical_coach
    "body_composition": "body_composition", "weight": "body_composition",
    "body_fat": "body_composition", "muscle_mass": "body_composition",
    "mobility": "training",
    # glucose_coach
    "glucose_control": "glucose", "glucose_variability": "glucose",
    "fasting_glucose": "glucose", "postprandial": "glucose",
    # labs_coach
    "cholesterol": "labs", "hormones": "labs", "inflammation": "labs",
    "vitamins": "labs", "metabolic": "labs",
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


# =============================================================================
# HELPERS
# =============================================================================

def _decimal_to_float(obj):
    """Recursively convert DynamoDB Decimal values to Python float."""
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


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
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower().strip())
    return slug[:60].strip('-')


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
                ":s":  "DATE#" + start_date,
                ":e":  "DATE#" + end_date,
            },
        }
        while True:
            r = table.query(**kwargs)
            records.extend(_decimal_to_float(i) for i in r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning("fetch_range(%s, %s -> %s) failed: %s",
                       source, start_date, end_date, e)
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
                    ":pk":     f"COACH#{coach_id}",
                    ":prefix": "PREDICTION#",
                },
            }
            while True:
                resp = table.query(**kwargs)
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
            base_metric = metric_key[:-len(suffix)]
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
    weights = [(1 - decay) * (decay ** i) for i in range(n - 1, -1, -1)]
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
                source = METRIC_SOURCES.get(metric_key[:-len(suffix)])
                break
    if not source:
        return None, None

    records = _get_source_data(source, data_cache, end_date, lookback_days=30)
    base_metric = metric_key
    for suffix in ["_7day_avg", "_14day_avg", "_30day_avg"]:
        if base_metric.endswith(suffix):
            base_metric = base_metric[:-len(suffix)]
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
        "gt":  actual > threshold,
        "gte": actual >= threshold,
        "lt":  actual < threshold,
        "lte": actual <= threshold,
        "eq":  abs(actual - threshold) < 0.01,
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
        "reason": (
            f"{metric_key}={actual_value:.4f} "
            f"{'meets' if result else 'fails'} "
            f"{condition} {threshold}"
        ),
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

    direction_matches = (actual_direction == pred_dir)
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
        "reason": (
            f"{metric_key} trend={actual_direction} (slope={slope:.4f}), "
            f"predicted={pred_dir}"
        ),
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
            "reason": (
                f"Precondition not met: {cond_metric}={x_value:.4f} "
                f"does not satisfy {cond_condition} {cond_threshold}"
            ),
            "actual_value": None,
            "beats_null": False,
        }

    # Precondition met — evaluate Y
    y_result = _evaluate_machine(pred, eval_spec, data_cache, today_str)
    if y_result:
        y_result["reason"] = (
            f"Precondition met ({cond_metric}={x_value:.4f} "
            f"{cond_condition} {cond_threshold}). "
            + y_result.get("reason", "")
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

        outcome_notes = json.dumps({
            "actual_value": evaluation.get("actual_value"),
            "reason": evaluation.get("reason", ""),
            "beats_null": evaluation.get("beats_null", False),
            "bayesian_update": evaluation.get("bayesian_update"),
            "algo_version": ALGO_VERSION,
        })

        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression=(
                "SET #status = :status, outcome = :outcome, "
                "outcome_date = :odate, outcome_notes = :notes"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": evaluation["status"],
                ":outcome": evaluation["status"],
                ":odate":  evaluation["evaluated_date"],
                ":notes":  outcome_notes,
            },
        )
        logger.info(
            "Updated prediction %s -> %s",
            evaluation.get("prediction_id", "?"), evaluation["status"]
        )
    except Exception as e:
        logger.error(
            "Failed to update prediction %s: %s",
            evaluation.get("prediction_id", "?"), e
        )


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

        table.put_item(Item={
            "pk": pk,
            "sk": sk,
            "alpha": _to_decimal(alpha),
            "beta_param": _to_decimal(beta_val),
            "mean_confidence": _to_decimal(mean_confidence),
            "sample_size": Decimal(str(max(0, sample_size))),
            "subdomain": subdomain,
            "coach_id": coach_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "Updated confidence for %s/%s: Beta(%.0f,%.0f) = %.3f (n=%d)",
            coach_id, subdomain, alpha, beta_val, mean_confidence, sample_size
        )
    except Exception as e:
        logger.error(
            "Failed to update Bayesian confidence for %s/%s: %s",
            coach_id, subdomain, e
        )


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
        logger.error("Failed to write LEARNING record for %s: %s",
                     prediction_id, e)


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
        "confirmed": 0, "refuted": 0, "inconclusive": 0,
        "expired": 0, "skipped_window": 0, "skipped_error": 0,
        "pending": 0,
    }

    for pred in predictions:
        eval_spec = pred.get("evaluation", {})
        eval_type = eval_spec.get("type", "machine")
        coach_id = pred.get("coach_id", "")
        subdomain = pred.get("subdomain", "")
        prediction_id = (
            pred.get("prediction_id")
            or pred.get("sk", "").replace("PREDICTION#", "")
        )

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
            logger.error(
                "Evaluation error for %s (%s): %s",
                prediction_id, eval_type, e
            )
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
                f"(window={effective_window}, max={effective_window * EXPIRY_MULTIPLIER}). "
                + result.get("reason", "")
            )

        # If conditional evaluation returns 'pending', don't write yet
        if status == "pending":
            stats["pending"] += 1
            continue

        # Determine Bayesian update direction
        bayesian_update = None
        if status == "confirmed" and result.get("beats_null"):
            bayesian_update = "success"   # alpha += 1
        elif status == "refuted":
            bayesian_update = "failure"   # beta += 1
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
        "Evaluation stats: confirmed=%d refuted=%d inconclusive=%d "
        "expired=%d pending=%d skipped_window=%d skipped_error=%d",
        stats["confirmed"], stats["refuted"], stats["inconclusive"],
        stats["expired"], stats["pending"],
        stats["skipped_window"], stats["skipped_error"],
    )
    return evaluations, stats


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

def lambda_handler(event, context):
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

        if not predictions:
            logger.info("No evaluable predictions found. Exiting.")
            return {
                "statusCode": 200,
                "date": today_str,
                "predictions_found": 0,
                "evaluations": [],
                "stats": {},
            }

        # Run evaluations
        evaluations, stats = _evaluate_all(predictions, today_str)

        logger.info(
            "coach-prediction-evaluator COMPLETE: %d predictions evaluated out of %d found",
            len(evaluations), len(predictions)
        )

        return {
            "statusCode": 200,
            "date": today_str,
            "algo_version": ALGO_VERSION,
            "predictions_found": len(predictions),
            "predictions_evaluated": len(evaluations),
            "stats": stats,
            "evaluations": evaluations,
        }
    except Exception as e:
        logger.error("coach-prediction-evaluator FAILED: %s", e, exc_info=True)
        return {"statusCode": 500, "error": str(e)}
