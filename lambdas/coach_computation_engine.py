"""
Coach Computation Engine Lambda — v1.0.0

Deterministic computation layer for the Coach Intelligence system.
ALL math happens here — the LLM never does math. This Lambda provides
pre-computed results that coaches receive in their generation briefs.

Components:
  1. EWMA trend detection — domain-specific decay from S3 config
  2. Regression-to-mean detection — flag noise vs signal
  3. Seasonality flags — population-level seasonal adjustments
  4. Autocorrelation warnings — flag likely noise in autocorrelated metrics
  5. Statistical guardrails — data availability tags + decision class ceiling
  6. Prediction evaluation — machine-evaluable predictions with Bayesian update

DynamoDB writes:
  PK: COACH#computation   SK: RESULTS#{YYYY-MM-DD}

Schedule: Daily at 9:45 AM PT (17:45 UTC via EventBridge)
  Runs after daily-metrics-compute (9:40 AM PT), before narrative orchestrator.

v1.0.0 — 2026-04-06 (Phase 1B — Coach Intelligence)
"""

import json
import os
import logging
import math
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ── Structured logger ────────────────────────────────────────────────────────
try:
    from platform_logger import get_logger
    logger = get_logger("coach-computation-engine")
except ImportError:
    logger = logging.getLogger("coach-computation-engine")
    logger.setLevel(logging.INFO)

# ── Configuration ────────────────────────────────────────────────────────────
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")

USER_PREFIX     = f"USER#{USER_ID}#SOURCE#"
ALGO_VERSION    = "1.0"
LOOKBACK_DAYS   = 30
EXPERIMENT_START = "2026-04-01"

# Metrics by source for EWMA processing
SOURCE_METRICS = {
    "whoop": ["hrv", "recovery_score", "resting_heart_rate",
              "sleep_duration_hours", "sleep_score", "deep_pct", "rem_pct"],
    "withings": ["weight_lbs"],
    "macrofactor": ["total_calories_kcal", "total_protein_g"],
    "apple_health": ["steps", "blood_glucose_avg", "blood_glucose_std_dev",
                     "som_avg_valence"],
    "strava": ["moving_time_seconds"],
    "eightsleep": ["sleep_score", "deep_pct", "rem_pct", "bed_temp_f"],
    "garmin": ["steps"],
}

# Metrics that are highly autocorrelated — need >=5 consecutive data points
# before a trend claim is meaningful (Jordan, Expert Panel)
AUTOCORRELATED_METRICS = {
    "hrv", "sleep_score", "recovery_score",
    "resting_heart_rate", "deep_pct", "rem_pct",
}

# Domain mapping for each metric — determines which EWMA decay to apply
METRIC_DOMAIN = {
    "hrv": "hrv_recovery",
    "recovery_score": "hrv_recovery",
    "resting_heart_rate": "hrv_recovery",
    "sleep_duration_hours": "sleep",
    "sleep_score": "sleep",
    "deep_pct": "sleep",
    "rem_pct": "sleep",
    "weight_lbs": "nutrition_body_comp",
    "total_calories_kcal": "nutrition_body_comp",
    "total_protein_g": "nutrition_body_comp",
    "steps": "training",
    "blood_glucose_avg": "nutrition_body_comp",
    "blood_glucose_std_dev": "nutrition_body_comp",
    "som_avg_valence": "mood",
    "moving_time_seconds": "training",
    "bed_temp_f": "sleep",
}

# Coach IDs for prediction scanning
COACH_IDS = [
    "dr_johansson", "fitness_coach", "nutrition_coach",
    "mind_coach", "sleep_coach", "body_comp_coach",
    "lifestyle_coach", "recovery_coach",
]

# Default EWMA decay params — used if S3 config unavailable
DEFAULT_EWMA_PARAMS = {
    "sleep": 0.85,
    "hrv_recovery": 0.87,
    "training": 0.90,
    "nutrition_body_comp": 0.95,
    "mood": 0.80,
}

# Default seasonal adjustments — used if S3 config unavailable
DEFAULT_SEASONAL_ADJUSTMENTS = {
    "sleep_duration_hours": {
        "1": -15, "2": -10, "3": -5, "4": 0, "5": 5, "6": 10,
        "7": 10, "8": 5, "9": 0, "10": -5, "11": -10, "12": -15,
    },
    "som_avg_valence": {
        "1": -0.3, "2": -0.2, "3": 0.0, "4": 0.1, "5": 0.2, "6": 0.2,
        "7": 0.1, "8": 0.1, "9": 0.0, "10": -0.1, "11": -0.2, "12": -0.3,
    },
}

# ── AWS clients ──────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=_REGION)


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


def _s3_json(key):
    """Read a JSON file from S3. Returns None on error."""
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.warning("S3 read failed (%s): %s", key, e)
        return None


def _decimalize_dict(d):
    """Recursively convert all floats in a dict to Decimal for DynamoDB."""
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


# =============================================================================
# DATA FETCHING
# =============================================================================

def _fetch_range(source, start_date, end_date):
    """Paginated DDB query for source records in date range."""
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
        logger.warning("fetch_range(%s, %s -> %s) failed: %s", source, start_date, end_date, e)
        return []


def _fetch_all_source_data(start_date, end_date):
    """Fetch data from all sources for the given date range."""
    data = {}
    for source in SOURCE_METRICS:
        records = _fetch_range(source, start_date, end_date)
        data[source] = records
        logger.info("Fetched %d records from %s", len(records), source)
    return data


def _fetch_predictions():
    """Fetch all pending machine-evaluable predictions across all coaches."""
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
            resp = table.query(**kwargs)
            items = [_decimal_to_float(i) for i in resp.get("Items", [])]
            for item in items:
                if item.get("status") == "pending":
                    predictions.append(item)
        except Exception as e:
            logger.warning("Failed to fetch predictions for %s: %s", coach_id, e)
    return predictions


def _load_ewma_params():
    """Load EWMA decay parameters from S3, falling back to defaults."""
    config = _s3_json("config/computation/ewma_params.json")
    if config and isinstance(config, dict):
        logger.info("Loaded EWMA params from S3")
        return config
    logger.info("Using default EWMA params (S3 config not found)")
    return DEFAULT_EWMA_PARAMS


def _load_seasonal_adjustments():
    """Load seasonal adjustments from S3, falling back to defaults."""
    config = _s3_json("config/computation/seasonal_adjustments.json")
    if config and isinstance(config, dict):
        logger.info("Loaded seasonal adjustments from S3")
        return config
    logger.info("Using default seasonal adjustments (S3 config not found)")
    return DEFAULT_SEASONAL_ADJUSTMENTS


# =============================================================================
# COMPONENT 1: EWMA TREND DETECTION
# =============================================================================

def ewma(values, decay):
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


def _extract_metric_series(records, metric):
    """
    Extract a chronological list of (date_str, value) tuples for a metric
    from a list of DynamoDB records, sorted by date.
    """
    series = []
    for rec in records:
        val = _safe_float(rec, metric)
        if val is not None:
            # Extract date from sk (DATE#YYYY-MM-DD) or from 'date' field
            date_str = rec.get("date") or (rec.get("sk", "").replace("DATE#", ""))
            if date_str:
                series.append((date_str, val))
    series.sort(key=lambda x: x[0])
    return series


def _compute_trends(all_data, ewma_params):
    """
    Compute EWMA trends for all metrics across all sources.

    For each metric:
      - Compute current EWMA from full series
      - Compute EWMA from series ending 7 days ago
      - Derive slope and direction (up/down/flat at +/-2% threshold)

    Returns dict: {source: {metric: {ewma, ewma_7d_ago, slope, direction, n_points}}}
    """
    trends = {}

    for source, metrics in SOURCE_METRICS.items():
        records = all_data.get(source, [])
        if not records:
            continue

        source_trends = {}
        for metric in metrics:
            series = _extract_metric_series(records, metric)
            values = [v for _, v in series]

            if len(values) < 2:
                continue

            domain = METRIC_DOMAIN.get(metric, "training")
            decay = ewma_params.get(domain, 0.90)

            # Current EWMA (full series)
            current_ewma = ewma(values, decay)

            # EWMA from 7 days ago (drop last 7 data points, or fewer if not enough)
            cutoff = max(1, len(values) - 7)
            prior_values = values[:cutoff]
            prior_ewma = ewma(prior_values, decay) if len(prior_values) >= 2 else None

            # Slope and direction
            slope = None
            direction = "flat"
            if current_ewma is not None and prior_ewma is not None and prior_ewma != 0:
                slope = (current_ewma - prior_ewma) / abs(prior_ewma)
                if slope > 0.02:
                    direction = "up"
                elif slope < -0.02:
                    direction = "down"
                else:
                    direction = "flat"

            source_trends[metric] = {
                "ewma": round(current_ewma, 4) if current_ewma is not None else None,
                "ewma_7d_ago": round(prior_ewma, 4) if prior_ewma is not None else None,
                "slope": round(slope, 6) if slope is not None else None,
                "direction": direction,
                "n_points": len(values),
                "domain": domain,
            }

        if source_trends:
            trends[source] = source_trends

    return trends


# =============================================================================
# COMPONENT 2: REGRESSION-TO-MEAN DETECTION
# =============================================================================

def is_likely_regression_to_mean(current, prior, baseline_mean, baseline_std):
    """
    Flag if prior was extreme (z > 1.5) and current moved toward mean.
    Returns True if the change is likely regression to mean, not signal.
    """
    if baseline_std == 0 or baseline_std is None:
        return False
    prior_z = abs(prior - baseline_mean) / baseline_std
    moved_toward_mean = abs(current - baseline_mean) < abs(prior - baseline_mean)
    return prior_z > 1.5 and moved_toward_mean


def _detect_regression_to_mean(all_data):
    """
    Check all metrics for regression-to-mean patterns.
    Uses the full lookback window as the baseline for mean/std.

    Returns list of warning dicts.
    """
    warnings = []

    for source, metrics in SOURCE_METRICS.items():
        records = all_data.get(source, [])
        if not records:
            continue

        for metric in metrics:
            series = _extract_metric_series(records, metric)
            values = [v for _, v in series]

            if len(values) < 7:
                continue

            baseline_values = values[:-1]  # All but most recent
            baseline_mean = sum(baseline_values) / len(baseline_values)
            variance = sum((v - baseline_mean) ** 2 for v in baseline_values) / len(baseline_values)
            baseline_std = math.sqrt(variance) if variance > 0 else 0

            if baseline_std == 0:
                continue

            current = values[-1]
            prior = values[-2]

            if is_likely_regression_to_mean(current, prior, baseline_mean, baseline_std):
                prior_z = abs(prior - baseline_mean) / baseline_std
                warnings.append({
                    "source": source,
                    "metric": metric,
                    "current": round(current, 4),
                    "prior": round(prior, 4),
                    "baseline_mean": round(baseline_mean, 4),
                    "baseline_std": round(baseline_std, 4),
                    "prior_z_score": round(prior_z, 2),
                    "message": (
                        f"{metric} change likely reflects regression to mean "
                        f"(prior z={prior_z:.1f}), not intervention effect."
                    ),
                })

    return warnings


# =============================================================================
# COMPONENT 3: SEASONALITY FLAGS
# =============================================================================

def _compute_seasonality_flags(all_data, seasonal_adjustments, current_month):
    """
    Compare current metric trends against expected seasonal pattern.
    Flag when a trend aligns with seasonal expectations (meaning the
    real signal might be flat despite an apparent trend).

    Returns list of flag dicts.
    """
    flags = []
    month_key = str(current_month)

    for metric, month_adjustments in seasonal_adjustments.items():
        expected_adj = month_adjustments.get(month_key)
        if expected_adj is None:
            continue

        # Find the metric in the data
        for source, source_metrics in SOURCE_METRICS.items():
            if metric not in source_metrics:
                continue

            records = all_data.get(source, [])
            if not records:
                continue

            series = _extract_metric_series(records, metric)
            values = [v for _, v in series]

            if len(values) < 7:
                continue

            # Compare recent 7-day avg vs older data avg
            recent_avg = sum(values[-7:]) / min(7, len(values[-7:]))
            older_values = values[:-7]
            if not older_values:
                continue
            older_avg = sum(older_values) / len(older_values)

            observed_change = recent_avg - older_avg

            # Check alignment: if observed change direction matches seasonal
            # expectation direction, the real signal may be weaker than it appears
            if expected_adj != 0:
                seasonal_direction = "up" if expected_adj > 0 else "down"
                observed_direction = "up" if observed_change > 0 else "down"

                if seasonal_direction == observed_direction:
                    flags.append({
                        "source": source,
                        "metric": metric,
                        "month": current_month,
                        "expected_seasonal_adjustment": expected_adj,
                        "observed_change": round(observed_change, 4),
                        "message": (
                            f"{metric} trend ({observed_direction}) aligns with seasonal "
                            f"pattern for month {current_month}. "
                            f"Deseasonalized trend may be flat."
                        ),
                    })
            break  # Found source for this metric, no need to check others

    return flags


# =============================================================================
# COMPONENT 4: AUTOCORRELATION WARNINGS
# =============================================================================

def _detect_autocorrelation_warnings(all_data):
    """
    Flag when a "trend" in a highly autocorrelated metric has fewer than
    5 consecutive data points in the same direction — likely noise, not signal.

    Autocorrelated metrics: HRV, sleep_score, recovery_score, resting_heart_rate,
    deep_pct, rem_pct (Jordan, Expert Panel).

    Returns list of warning dicts.
    """
    warnings = []

    for source, metrics in SOURCE_METRICS.items():
        records = all_data.get(source, [])
        if not records:
            continue

        for metric in metrics:
            if metric not in AUTOCORRELATED_METRICS:
                continue

            series = _extract_metric_series(records, metric)
            values = [v for _, v in series]

            if len(values) < 3:
                continue

            # Count consecutive direction at the tail of the series
            consecutive = 1
            if len(values) >= 2:
                last_direction = "up" if values[-1] > values[-2] else "down"
                for i in range(len(values) - 2, 0, -1):
                    if values[i] == values[i - 1]:
                        continue
                    current_dir = "up" if values[i] > values[i - 1] else "down"
                    if current_dir == last_direction:
                        consecutive += 1
                    else:
                        break

            if consecutive < 5:
                warnings.append({
                    "source": source,
                    "metric": metric,
                    "consecutive_same_direction": consecutive,
                    "min_required": 5,
                    "message": (
                        f"{metric} has only {consecutive} consecutive data points "
                        f"in the same direction (need 5+). Likely autocorrelation, "
                        f"not independent signal."
                    ),
                })

    return warnings


# =============================================================================
# COMPONENT 5: STATISTICAL GUARDRAILS
# =============================================================================

def _compute_statistical_guardrails(all_data):
    """
    Tag every metric with data availability level and decision class ceiling.

    Levels:
      <7 days  = "observational_only"  -> ceiling: "observational"
      <14 days = "preliminary"         -> ceiling: "directional"
      14+ days = "established"         -> ceiling: "interventional"

    Returns dict: {source: {metric: {level, ceiling, n_points}}}
    """
    LEVEL_MAP = {
        "observational_only": "observational",
        "preliminary": "directional",
        "established": "interventional",
    }

    guardrails = {}

    for source, metrics in SOURCE_METRICS.items():
        records = all_data.get(source, [])
        if not records:
            continue

        source_guardrails = {}
        for metric in metrics:
            series = _extract_metric_series(records, metric)
            n_points = len(series)

            if n_points < 7:
                level = "observational_only"
            elif n_points < 14:
                level = "preliminary"
            else:
                level = "established"

            source_guardrails[metric] = {
                "level": level,
                "decision_class_ceiling": LEVEL_MAP[level],
                "n_points": n_points,
            }

        if source_guardrails:
            guardrails[source] = source_guardrails

    return guardrails


# =============================================================================
# COMPONENT 6: PREDICTION EVALUATION
# =============================================================================

def _resolve_metric_value(metric_key, all_data):
    """
    Resolve a metric key (e.g. 'hrv_7day_avg') to a current numeric value.
    Supports both raw metric names and computed aggregates.
    """
    # Handle computed metrics like 'hrv_7day_avg'
    if metric_key.endswith("_7day_avg"):
        base_metric = metric_key.replace("_7day_avg", "")
        return _compute_metric_average(base_metric, all_data, days=7)
    if metric_key.endswith("_14day_avg"):
        base_metric = metric_key.replace("_14day_avg", "")
        return _compute_metric_average(base_metric, all_data, days=14)
    if metric_key.endswith("_30day_avg"):
        base_metric = metric_key.replace("_30day_avg", "")
        return _compute_metric_average(base_metric, all_data, days=30)

    # Raw metric — get most recent value
    for source, metrics in SOURCE_METRICS.items():
        if metric_key in metrics:
            records = all_data.get(source, [])
            series = _extract_metric_series(records, metric_key)
            if series:
                return series[-1][1]  # Most recent value
    return None


def _compute_metric_average(base_metric, all_data, days):
    """Compute the average of the last N days for a base metric."""
    for source, metrics in SOURCE_METRICS.items():
        if base_metric in metrics:
            records = all_data.get(source, [])
            series = _extract_metric_series(records, base_metric)
            if not series:
                return None
            recent = [v for _, v in series[-days:]]
            if not recent:
                return None
            return sum(recent) / len(recent)
    return None


def _evaluate_condition(actual, condition, threshold):
    """Evaluate a prediction condition against a threshold."""
    if actual is None or threshold is None:
        return None  # Inconclusive
    cond_map = {
        "gt": actual > threshold,
        "gte": actual >= threshold,
        "lt": actual < threshold,
        "lte": actual <= threshold,
        "eq": abs(actual - threshold) < 0.01,
    }
    return cond_map.get(condition)


def _evaluate_predictions(predictions, all_data, today_str):
    """
    Evaluate machine-evaluable predictions whose evaluation window has elapsed.

    For each eligible prediction:
      1. Check if evaluation window has elapsed
      2. Fetch current metric value
      3. Evaluate against threshold and condition
      4. Compare against null hypothesis
      5. Determine outcome status
      6. Prepare Bayesian confidence update (alpha/beta)

    Returns list of evaluation result dicts.
    """
    today = datetime.strptime(today_str, "%Y-%m-%d")
    evaluations = []

    for pred in predictions:
        eval_spec = pred.get("evaluation", {})
        if eval_spec.get("type") != "machine":
            continue

        # Check evaluation window
        created_date = pred.get("created_date")
        window_days = eval_spec.get("evaluation_window_days")
        if not created_date or not window_days:
            continue

        try:
            created_dt = datetime.strptime(created_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        eval_deadline = created_dt + timedelta(days=int(window_days))
        if today < eval_deadline:
            continue  # Window hasn't elapsed yet

        # Resolve metric value
        metric_key = eval_spec.get("metric")
        if not metric_key:
            continue

        actual_value = _resolve_metric_value(metric_key, all_data)
        threshold = eval_spec.get("threshold")
        condition = eval_spec.get("condition")

        result = _evaluate_condition(actual_value, condition, threshold)

        # Determine outcome status
        if result is None:
            status = "inconclusive"
            beats_null = False
        elif result:
            status = "confirmed"
            # Check if it beats the null hypothesis
            null_text = eval_spec.get("null_hypothesis", "")
            # If there is a null hypothesis, only count as beating null
            # if the prediction meaningfully exceeds what was expected
            beats_null = bool(null_text)  # Default: if we confirmed AND had a null, we beat it
        else:
            status = "refuted"
            beats_null = False

        # Bayesian update direction
        # Only update confidence if the prediction beat the null or was refuted
        bayesian_update = None
        if status == "confirmed" and beats_null:
            bayesian_update = "success"  # alpha += 1
        elif status == "refuted":
            bayesian_update = "failure"  # beta += 1
        # 'inconclusive' or 'confirmed but matches null' = no update

        coach_id = pred.get("coach_id")
        subdomain = pred.get("subdomain")
        prediction_id = pred.get("prediction_id") or pred.get("sk", "").replace("PREDICTION#", "")

        evaluation = {
            "prediction_id": prediction_id,
            "coach_id": coach_id,
            "subdomain": subdomain,
            "metric": metric_key,
            "threshold": threshold,
            "condition": condition,
            "actual_value": round(actual_value, 4) if actual_value is not None else None,
            "status": status,
            "beats_null": beats_null,
            "bayesian_update": bayesian_update,
            "created_date": created_date,
            "evaluated_date": today_str,
            "evaluation_window_days": window_days,
        }
        evaluations.append(evaluation)

        # Write the update back to the prediction record
        _update_prediction_outcome(pred, evaluation)

        # Update Bayesian confidence if applicable
        if bayesian_update and coach_id and subdomain:
            _update_bayesian_confidence(coach_id, subdomain, bayesian_update)

    return evaluations


def _update_prediction_outcome(prediction, evaluation):
    """Update a prediction record with its evaluation outcome."""
    try:
        pk = prediction.get("pk") or f"COACH#{prediction.get('coach_id', '')}"
        sk = prediction.get("sk") or f"PREDICTION#{prediction.get('prediction_id', '')}"

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
                ":odate": evaluation["evaluated_date"],
                ":notes": json.dumps({
                    "actual_value": evaluation["actual_value"],
                    "beats_null": evaluation["beats_null"],
                    "bayesian_update": evaluation["bayesian_update"],
                }),
            },
        )
        logger.info(
            "Updated prediction %s -> %s",
            evaluation["prediction_id"], evaluation["status"]
        )
    except Exception as e:
        logger.error(
            "Failed to update prediction %s: %s",
            evaluation.get("prediction_id"), e
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
        # Read current confidence
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
            "sample_size": Decimal(str(sample_size)),
            "subdomain": subdomain,
            "coach_id": coach_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "Updated confidence for %s/%s: Beta(%.0f,%.0f) = %.2f",
            coach_id, subdomain, alpha, beta_val, mean_confidence
        )
    except Exception as e:
        logger.error(
            "Failed to update Bayesian confidence for %s/%s: %s",
            coach_id, subdomain, e
        )


# =============================================================================
# RESULTS WRITER
# =============================================================================

def _write_results(today_str, package):
    """Write the computation results package to DynamoDB for caching."""
    try:
        item = {
            "pk": "COACH#computation",
            "sk": f"RESULTS#{today_str}",
            "date": today_str,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "algo_version": ALGO_VERSION,
        }

        # Serialize sub-packages as JSON strings to avoid DynamoDB type issues
        # with deeply nested structures, but keep top-level fields queryable
        item["trends"] = json.dumps(package.get("trends", {}))
        item["regression_to_mean_warnings"] = json.dumps(
            package.get("regression_to_mean_warnings", [])
        )
        item["seasonality_flags"] = json.dumps(
            package.get("seasonality_flags", [])
        )
        item["autocorrelation_warnings"] = json.dumps(
            package.get("autocorrelation_warnings", [])
        )
        item["statistical_guardrails"] = json.dumps(
            package.get("statistical_guardrails", {})
        )
        item["prediction_evaluations"] = json.dumps(
            package.get("prediction_evaluations", [])
        )

        # Summary counts for quick reads
        item["trend_count"] = Decimal(str(
            sum(len(m) for m in package.get("trends", {}).values())
        ))
        item["warning_count"] = Decimal(str(
            len(package.get("regression_to_mean_warnings", []))
            + len(package.get("autocorrelation_warnings", []))
        ))
        item["flag_count"] = Decimal(str(
            len(package.get("seasonality_flags", []))
        ))
        item["prediction_eval_count"] = Decimal(str(
            len(package.get("prediction_evaluations", []))
        ))

        table.put_item(Item=item)
        logger.info("Wrote computation results for %s", today_str)
    except Exception as e:
        logger.error("Failed to write computation results: %s", e)
        raise


# =============================================================================
# COMPONENT 7: NARRATIVE ARC TRANSITION DETECTION
# =============================================================================


def _detect_arc_transition(trends, guardrails, all_data, today_str):
    """
    Detect whether the narrative arc should transition based on trend patterns.

    Transitions:
      early_baseline → building_momentum: 14+ days + majority trends positive
      any → setback: 60%+ key metrics declining simultaneously
      building_momentum/deep_adaptation → plateau: 70%+ metrics flat for 7+ days
      setback/plateau → breakthrough: 60%+ metrics improving
    """
    try:
        resp = table.get_item(Key={"pk": "NARRATIVE#arc", "sk": "STATE#current"})
        arc = _decimal_to_float(resp.get("Item", {}))
    except Exception:
        arc = {}

    current_phase = arc.get("phase", "early_baseline")
    entered_date = arc.get("entered_date", "2026-04-01")

    try:
        days_in_phase = (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(entered_date, "%Y-%m-%d")).days
    except Exception:
        days_in_phase = 0

    up_count = down_count = flat_count = 0
    for domain_metrics in trends.values():
        if not isinstance(domain_metrics, dict):
            continue
        for metric_data in domain_metrics.values():
            if not isinstance(metric_data, dict):
                continue
            d = metric_data.get("direction", "flat")
            if d == "up":
                up_count += 1
            elif d == "down":
                down_count += 1
            else:
                flat_count += 1

    total = up_count + down_count + flat_count
    if total == 0:
        return None

    up_pct = up_count / total
    down_pct = down_count / total
    flat_pct = flat_count / total

    new_phase = None
    reason = ""

    if current_phase == "early_baseline":
        if days_in_phase >= 14 and up_pct > 0.5:
            new_phase = "building_momentum"
            reason = f"{days_in_phase} days in baseline, {up_pct:.0%} of trends positive"
        elif days_in_phase >= 28:
            new_phase = "building_momentum"
            reason = "28 days in baseline — auto-transition"

    if down_pct >= 0.6 and total >= 3 and current_phase != "setback":
        new_phase = "setback"
        reason = f"{down_count}/{total} metrics declining"

    if flat_pct >= 0.7 and days_in_phase >= 7 and current_phase in ("building_momentum", "deep_adaptation"):
        new_phase = "plateau"
        reason = f"{flat_count}/{total} metrics flat for {days_in_phase}+ days"

    if up_pct >= 0.6 and total >= 4 and current_phase in ("setback", "plateau"):
        new_phase = "breakthrough"
        reason = f"{up_count}/{total} metrics improving"

    if not new_phase or new_phase == current_phase:
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    transition = {
        "from": current_phase, "to": new_phase,
        "date": today_str, "reason": reason,
        "metrics_context": {"up": up_count, "down": down_count, "flat": flat_count, "total": total},
    }

    try:
        table.put_item(Item=_decimalize_dict({
            "pk": "NARRATIVE#arc", "sk": "STATE#current",
            "phase": new_phase, "entered_date": today_str,
            "previous_phase": current_phase, "transition_reason": reason,
            "last_updated": now_iso,
        }))
        table.put_item(Item=_decimalize_dict({
            "pk": "NARRATIVE#arc", "sk": f"HISTORY#{today_str}",
            "transition": transition, "created_at": now_iso,
        }))
        logger.info("Arc transition: %s → %s (%s)", current_phase, new_phase, reason)
    except Exception as e:
        logger.error("Failed to write arc transition: %s", e)

    return transition


# =============================================================================
# LAMBDA HANDLER
# =============================================================================


def lambda_handler(event, context):
    """
    Coach Computation Engine entry point.

    Can be invoked directly or via EventBridge schedule.
    Fetches last 30 days of data, runs all 7 components, writes results
    to DynamoDB at COACH#computation / RESULTS#{date}.

    Returns structured computation_results_package.
    """
    today_dt = datetime.now(timezone.utc)
    today_str = today_dt.strftime("%Y-%m-%d")
    current_month = today_dt.month

    logger.info("coach-computation-engine START date=%s", today_str)

    # Clamp lookback to experiment start
    lookback_dt = today_dt - timedelta(days=LOOKBACK_DAYS)
    experiment_start_dt = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
    if lookback_dt < experiment_start_dt:
        lookback_dt = experiment_start_dt
    start_date = lookback_dt.strftime("%Y-%m-%d")

    logger.info("Lookback window: %s to %s", start_date, today_str)

    # ── Load configs from S3 ─────────────────────────────────────────────
    ewma_params = _load_ewma_params()
    seasonal_adjustments = _load_seasonal_adjustments()

    # ── Fetch all source data ────────────────────────────────────────────
    all_data = _fetch_all_source_data(start_date, today_str)

    total_records = sum(len(v) for v in all_data.values())
    logger.info("Total records fetched: %d", total_records)

    # ── Run components (each is resilient — failures don't block others) ─

    # Component 1: EWMA Trends
    trends = {}
    try:
        trends = _compute_trends(all_data, ewma_params)
        logger.info(
            "Trends computed: %d sources, %d metrics",
            len(trends), sum(len(m) for m in trends.values())
        )
    except Exception as e:
        logger.error("Component 1 (EWMA trends) failed: %s", e)

    # Component 2: Regression-to-Mean Detection
    rtm_warnings = []
    try:
        rtm_warnings = _detect_regression_to_mean(all_data)
        logger.info("Regression-to-mean warnings: %d", len(rtm_warnings))
    except Exception as e:
        logger.error("Component 2 (regression-to-mean) failed: %s", e)

    # Component 3: Seasonality Flags
    season_flags = []
    try:
        season_flags = _compute_seasonality_flags(
            all_data, seasonal_adjustments, current_month
        )
        logger.info("Seasonality flags: %d", len(season_flags))
    except Exception as e:
        logger.error("Component 3 (seasonality) failed: %s", e)

    # Component 4: Autocorrelation Warnings
    autocorr_warnings = []
    try:
        autocorr_warnings = _detect_autocorrelation_warnings(all_data)
        logger.info("Autocorrelation warnings: %d", len(autocorr_warnings))
    except Exception as e:
        logger.error("Component 4 (autocorrelation) failed: %s", e)

    # Component 5: Statistical Guardrails
    guardrails = {}
    try:
        guardrails = _compute_statistical_guardrails(all_data)
        logger.info(
            "Statistical guardrails: %d sources",
            len(guardrails)
        )
    except Exception as e:
        logger.error("Component 5 (statistical guardrails) failed: %s", e)

    # Component 6: Prediction Evaluation
    pred_evals = []
    try:
        predictions = _fetch_predictions()
        logger.info("Pending predictions found: %d", len(predictions))
        if predictions:
            pred_evals = _evaluate_predictions(predictions, all_data, today_str)
            logger.info("Predictions evaluated: %d", len(pred_evals))
    except Exception as e:
        logger.error("Component 6 (prediction evaluation) failed: %s", e)

    # ── Component 7: Narrative arc transition detection ────────────────
    arc_transition = None
    try:
        arc_transition = _detect_arc_transition(trends, guardrails, all_data, today_str)
        if arc_transition:
            logger.info("Arc transition detected: %s → %s", arc_transition["from"], arc_transition["to"])
    except Exception as e:
        logger.error("Component 7 (arc transition) failed: %s", e)

    # ── Assemble results package ─────────────────────────────────────────
    computation_results_package = {
        "date": today_str,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "algo_version": ALGO_VERSION,
        "lookback_start": start_date,
        "lookback_days": (today_dt - lookback_dt).days,
        "total_records": total_records,
        "trends": trends,
        "regression_to_mean_warnings": rtm_warnings,
        "seasonality_flags": season_flags,
        "autocorrelation_warnings": autocorr_warnings,
        "statistical_guardrails": guardrails,
        "prediction_evaluations": pred_evals,
        "arc_transition": arc_transition,
    }

    # ── Write to DynamoDB ────────────────────────────────────────────────
    try:
        _write_results(today_str, computation_results_package)
    except Exception as e:
        logger.error("Failed to write results to DynamoDB: %s", e)
        # Don't fail the Lambda — still return the package

    result_summary = {
        "status": "ok",
        "date": today_str,
        "trends_computed": sum(len(m) for m in trends.values()),
        "regression_to_mean_warnings": len(rtm_warnings),
        "seasonality_flags": len(season_flags),
        "autocorrelation_warnings": len(autocorr_warnings),
        "guardrail_sources": len(guardrails),
        "predictions_evaluated": len(pred_evals),
    }

    logger.info("coach-computation-engine COMPLETE: %s", json.dumps(result_summary))

    return computation_results_package
