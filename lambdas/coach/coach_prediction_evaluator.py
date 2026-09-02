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
  - inconclusive / expired / confirmed-but-matches-null: no update

  Both deterministic verdict paths report beats_null=True on a confirm (#2219):
  the threshold (machine) or the above-noise directional move (directional) IS
  the falsifiable bar, so credit and debit are symmetric. The `beats_null`
  conjunction is kept in `_evaluate_all` as the explicit contract — a future
  evaluator that CAN measure a null may return confirmed-but-matches-null, and
  that outcome must still move neither side.

Idempotent: safe to re-run. Already-evaluated predictions (status not in
pending/confirming) are skipped. Learning log uses put_item (upsert).
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from experiment.phase_filter import with_phase_filter  # ADR-058
from experiment.phase_taxonomy import experiment_stamp  # #2811: hoisted — it was imported locally in two functions

# ── Structured logger ────────────────────────────────────────────────────────
try:
    from common.platform_logger import get_logger

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

# #1841 — the on-tape claims ledger. Claims the SUBJECT made on camera are written in the
# canonical PREDICTION# record shape (diary_claims.build_claim_record) into their own
# partition, so grading them costs ONE extra partition on this scan rather than a second
# grader that would drift from this one. They carry `coach_id: ""`, which the existing
# `if bayesian_update and coach_id` guard below already honours — a claim of Matthew's
# must never move a coach's Bayesian confidence or write to a coach's LEARNING# trail.
DIARY_CLAIMS_PK = f"{USER_PREFIX}diary_claims"

# Coach IDs — exhaustive list of all coaches that can issue predictions, derived
# from the canonical persona registry, never re-typed (#2334; guard:
# tests/test_coach_roster_set_guard_2334.py).
from coach.persona_registry import OPERATIONAL_COACH_IDS

COACH_IDS = list(OPERATIONAL_COACH_IDS)

# Metric → DynamoDB source mapping. CONSOLIDATED 2026-06-28 (Coherence Program
# Phase 2): this was a hand-synced duplicate of coach_state_updater's allowlist —
# drift silently broke prediction grading. Single source now; MEASURABLE_METRICS is
# DERIVED from this map, so the extractor's allowlist and the evaluator's source-map
# cannot diverge. See lambdas/measurable_metrics.py.
from experiment.measurable_metrics import METRIC_SOURCES, infer_direction  # noqa: E402

# Window policy (domain minimums + subdomain map) moved to
# coach.prediction_windows (#3046) so the public scorecard surface computes due
# dates from the SAME clamp this evaluator grades with. Re-exported here because
# the suite + siblings (dispute_docket, diary_claims, coach_nudge) read them off
# this module.
from coach.prediction_windows import (  # noqa: E402,F401  (F401: DOMAIN_MIN_WINDOWS/SUBDOMAIN_TO_DOMAIN are re-exports)
    DOMAIN_MIN_WINDOWS,
    SUBDOMAIN_TO_DOMAIN,
    effective_window_days as _effective_window_days,
    is_gradeable as _is_gradeable,
)

# Statuses that are eligible for evaluation
EVALUABLE_STATUSES = {"pending", "confirming"}

# EWMA decay factor for directional trend evaluation
EWMA_DECAY = 0.87

# Directional evaluation: minimum slope to count as real signal — a DOCUMENTED ADR-105
# EXCEPTION (2026-09-02, #3448): fixed editorial band, the de-facto null for the #813
# rescue path. Stamp, reach + re-derive trigger: registry entry `directional_trend_verdict`
# + the PROPORTIONALITY row; failure regimes executable in test_directional_noise_band_3448.
DIRECTIONAL_NOISE_THRESHOLD = 0.02

# #2221 — the EWMA observation floor + the provisional-grade rules, reasoned out there.
from coach.prediction_grading import (  # noqa: E402
    EWMA_MIN_OBSERVATIONS,
    EWMA_MIN_PRIOR_POINTS,
    EWMA_PRIOR_LAG,
    EXPIRY_MULTIPLIER,
    build_outcome_notes,
    check_expiry as _check_expiry,
    grading_window_still_open,
)

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


from common.numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401


def _scalar_to_decimal(val):
    """Coerce a SCALAR numeric value to a 6-dp Decimal for DynamoDB writes.

    Distinct contract from numeric.floats_to_decimal (#1207): this coerces a
    single value via float() (accepting ints/str), rounds to 6 dp, and returns
    None on None/unparseable input — it is NOT a recursive structure walker, so
    it is deliberately not consolidated into the canonical helper.
    """
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


def _was_terminalized_by_duplicate_grader(item):
    """#813: True for status='inconclusive' records graded by coach_computation_engine's
    now-removed duplicate grader — those were killed at the raw stated window (before
    this evaluator's domain-clamped window elapsed) and with threshold=None could only
    ever be inconclusive, so they never got a real grading pass.

    Deterministic discriminator: THIS evaluator always stamps algo_version into
    outcome_notes; the duplicate grader never did. One-way — once re-graded here (any
    outcome), algo_version is present and the record is terminal again.
    """
    if item.get("status") != "inconclusive":
        return False
    try:
        notes = json.loads(item.get("outcome_notes") or "{}")
    except (ValueError, TypeError):
        return False
    return isinstance(notes, dict) and "algo_version" not in notes


def _fetch_predictions():
    """
    Fetch all evaluable predictions across all coaches.

    Queries each coach's PREDICTION# prefix and filters to statuses
    in EVALUABLE_STATUSES — plus the #813 reclaim: 'inconclusive' records
    terminalized by the removed duplicate grader get one real grading pass.

    Qualitative evaluation types have no deterministic grading path; they are
    returned SEPARATELY (#3046) rather than silently dropped — the handler
    retires the past-window ones (_retire_ungradeable) and the count feeds the
    GradableShare metric, so a structurally-skipped majority is visible instead
    of pending forever (the DIL-007 finding: 28/50 pending were qualitative).

    #1841: the subject's own on-tape diary claims live in DIARY_CLAIMS_PK under the same
    PREDICTION# sk prefix and the same record shape, so they ride this identical scan and
    are graded by identical code — one grader for every forecast on the platform.

    Returns (evaluable, ungradeable_pending).
    """
    predictions = []
    ungradeable = []
    reclaimed = 0
    second_look = 0
    partitions = [f"COACH#{coach_id}" for coach_id in COACH_IDS] + [DIARY_CLAIMS_PK]
    for partition_pk in partitions:
        try:
            kwargs = {
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                "ExpressionAttributeValues": {
                    ":pk": partition_pk,
                    ":prefix": "PREDICTION#",
                },
            }
            while True:
                resp = table.query(**with_phase_filter(kwargs))
                items = [_decimal_to_float(i) for i in resp.get("Items", [])]
                for item in items:
                    status = item.get("status", "")
                    if not _is_gradeable(item.get("evaluation", {})):
                        # Legacy pending-qualitative debt (new qualitative claims are
                        # emitted status="observation" and never enter this set).
                        if status in EVALUABLE_STATUSES:
                            ungradeable.append(item)
                        continue
                    if status in EVALUABLE_STATUSES:
                        predictions.append(item)
                    elif _was_terminalized_by_duplicate_grader(item):
                        reclaimed += 1
                        predictions.append(item)
                    elif grading_window_still_open(item):  # #2221: provisional, re-grade
                        second_look += 1
                        predictions.append(item)
                if "LastEvaluatedKey" not in resp:
                    break
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        except Exception as e:
            logger.warning("Failed to fetch predictions for %s: %s", partition_pk, e)
    logger.info(
        "Evaluable predictions: %d (%d reclaimed #813, %d provisional second-look #2221, %d ungradeable-pending #3046)",
        len(predictions),
        reclaimed,
        second_look,
        len(ungradeable),
    )
    return predictions, ungradeable


def _retire_ungradeable(ungradeable, today_str):
    """#3046: retire legacy pending-qualitative predictions at window end.

    A qualitative record has no deterministic grading path — left alone it pends
    forever (28/50 of the pending corpus at the DIL-007 audit, violating closed
    #715's "zero ungradeable-by-construction"). Once its domain-clamped window
    elapses it expires: 'expired' moves no Bayesian confidence — a call the world
    never tested is not a hit and not a miss — and no learning record is written
    (the learning log is for graded outcomes). No 2x grace period: grace exists
    for late-arriving data, and no data can ever grade these. Returns the count
    retired; fail-soft per record.
    """
    today = datetime.strptime(today_str, "%Y-%m-%d")
    retired = 0
    for pred in ungradeable:
        try:
            created_dt = datetime.strptime(str(pred.get("created_date")), "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        window = _get_effective_window(pred.get("evaluation", {}), pred.get("subdomain", ""))
        if today < created_dt + timedelta(days=window):
            continue  # window still open — stays visible as an open observational claim
        evaluation = {
            "prediction_id": pred.get("prediction_id") or pred.get("sk", "").replace("PREDICTION#", ""),
            "status": "expired",
            "evaluated_date": today_str,
            "reason": (
                f"Retired unevaluated at window end ({window}d): eval_type=qualitative has no "
                "deterministic grading path (ungradeable-by-construction, #3046)"
            ),
        }
        _update_prediction_status(pred, evaluation)
        retired += 1
    if ungradeable:
        logger.info("[#3046] ungradeable-pending: %d found, %d retired at window end", len(ungradeable), retired)
    return retired


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
    through (kept); moving the opposite way OR staying flat is broken (#801 —
    "nothing happened" is evidence against the commitment, not a non-result);
    genuinely missing data is unresolved once past expiry, else left pending.
    Metric-less commitments can't be auto-graded — they expire to 'unresolved'
    past 2x window so the coach stops carrying them.
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

    Returns (direction, slope) where direction is 'up', 'down', or 'flat', and slope is
    the fractional change between the current EWMA and the EWMA as of EWMA_PRIOR_LAG
    observations ago. Fewer than EWMA_MIN_OBSERVATIONS readings is an honest (None, None):
    no trend, not a flat one — see prediction_grading for why that floor is what it is.
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

    if len(values) < EWMA_MIN_OBSERVATIONS:
        logger.info("No EWMA trend for %s: %d observation(s), floor is %d", metric_key, len(values), EWMA_MIN_OBSERVATIONS)
        return None, None

    current_ewma = _compute_ewma(values, EWMA_DECAY)
    prior_values = values[: max(0, len(values) - EWMA_PRIOR_LAG)]
    prior_ewma = _compute_ewma(prior_values, EWMA_DECAY) if len(prior_values) >= EWMA_MIN_PRIOR_POINTS else None

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
    """Domain-clamped evaluation window — delegates to the shared policy module
    (coach.prediction_windows, #3046); semantics unchanged."""
    return _effective_window_days(eval_spec, subdomain)


def _evaluate_machine(pred, eval_spec, data_cache, today_str):
    """
    Machine evaluation: metric crosses threshold within window.

    Steps:
      1. Fetch current metric value
      2. Apply condition against threshold
      3. Return status: confirmed / refuted / inconclusive

    A met condition is `confirmed` with beats_null=True (#2219) — the threshold
    is the bar the call had to clear, so a hit credits alpha the same way a miss
    debits beta. The spec's free-text `null_hypothesis` / `beats_null_if` keys
    are not read: neither is machine-checkable, and no writer emits them.
    """
    metric_key = eval_spec.get("metric")
    if not metric_key:
        return None

    threshold = eval_spec.get("threshold")
    condition = eval_spec.get("condition")

    # ── #813: legacy null-threshold rescue ────────────────────────────────────
    # Every machine-type spec written before the C-3 emission fix (2026-06-28)
    # carries threshold=None + condition='gt' regardless of the claim ('gt' was a
    # constant, not a signal). A threshold-less comparison can only ever grade
    # inconclusive, which is how the corpus starved the scorecard. When the claim
    # text yields a deterministic direction, re-route to the directional (EWMA)
    # evaluator — the same grading path C-3 gives new predictions. No inferable
    # direction → inconclusive with an explicit reason (expiry will retire it).
    if threshold is None:
        direction = infer_direction(None, pred.get("claim_natural") or "")
        if direction:
            rescued_spec = dict(eval_spec)
            rescued_spec["condition"] = direction
            result = _evaluate_directional(pred, rescued_spec, data_cache, today_str)
            if result:
                result["reason"] = "[null-threshold machine spec re-routed to directional] " + result.get("reason", "")
            return result
        return {
            "status": "inconclusive",
            "reason": ("Machine spec has threshold=None (pre-C-3 emission bug) and the claim " "has no inferable direction"),
            "actual_value": None,
            "beats_null": False,
        }

    actual_value = _resolve_metric_value(metric_key, data_cache, today_str)

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

    # ── #2219: a confirmed threshold call credits alpha, symmetrically ────────
    # This branch used to set beats_null=True only when the spec carried a truthy
    # `null_hypothesis`, and fall through to beats_null=False when it did not.
    # No writer in this repo has ever emitted that key (coach_state_updater's
    # _build_prediction_eval_spec hard-codes it to None; diary_claims omits it),
    # and the live corpus agrees — 0 of the 2,458 PREDICTION# rows standing on
    # 2026-08-08 carried one. So `_evaluate_all` could never reach its
    # `confirmed and beats_null` -> alpha branch from here, while every refuted
    # call took the unconditional beta branch: the posterior could only fall.
    #
    # The threshold IS the null on this path. The spec names a number and a
    # comparison the evaluator grades deterministically, so crossing it is the
    # falsifiable event — there is nothing further to beat, exactly as
    # `_evaluate_directional` has always treated a matched, above-noise move
    # (beats_null=True with no null-hypothesis gate). A free-text
    # `null_hypothesis` is not machine-checkable and therefore cannot change a
    # deterministic verdict; giving one real gating power would need its own
    # numeric spec field and an ADR-105 threshold derived from personal variance,
    # not a prose string. The `beats_null_if` three-way branch is gone with it:
    # all three of its arms assigned True, so it distinguished nothing.
    if result:
        status = "confirmed"
        beats_null = True
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
    AND the magnitude exceeds the noise threshold. Refuted if the metric moved
    the opposite way, OR (#801) if it stayed flat — a directional call is a bet
    that something moves, and "nothing happened" is evidence against that bet,
    not a non-result. Only missing data or a malformed prediction is inconclusive.
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
        reason = f"{metric_key} trend={actual_direction} (slope={slope:.4f}), " f"predicted={pred_dir}"
    elif actual_direction == "flat":
        # #801: a directional call is refuted whether the metric moved the OPPOSITE
        # way or didn't move at all. "Flat" isn't "no evidence either way" — the coach
        # predicted movement (up/down) and the metric stayed inside the noise band
        # (±DIRECTIONAL_NOISE_THRESHOLD), so the predicted move simply didn't happen.
        # Only a genuinely undecidable case (missing data, invalid prediction) stays
        # inconclusive — see the earlier early-returns in this function.
        status = "refuted"
        beats_null = False
        reason = (
            f"predicted {pred_dir}, metric flat (slope={slope:.4f}, "
            f"within ±{DIRECTIONAL_NOISE_THRESHOLD} noise band) — no movement to confirm the call"
        )
    else:
        status = "refuted"
        beats_null = False
        reason = f"{metric_key} trend={actual_direction} (slope={slope:.4f}), " f"predicted={pred_dir}"

    return {
        "status": status,
        "reason": reason,
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


# =============================================================================
# DYNAMO WRITES
# =============================================================================


def _update_prediction_status(prediction, evaluation):
    """Update a prediction record with its evaluation outcome."""
    try:
        pk = prediction.get("pk") or f"COACH#{prediction.get('coach_id', '')}"
        sk = prediction.get("sk") or f"PREDICTION#{prediction.get('prediction_id', '')}"

        outcome_notes = build_outcome_notes(evaluation, ALGO_VERSION)

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
        if item and item.get("tombstone"):
            # ADR-077: a tombstoned CONFIDENCE# row is a prior cycle's archive —
            # inheriting its Beta counts would contaminate the new cycle, and the
            # full-item put below would resurrect it. Start fresh instead.
            item = None

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
        # #1787: n = GRADED predictions only. This path increments by exactly 1 per
        # graded outcome, but the SAME Beta also carries #1481's fractional
        # conversational pseudo-observations — so the honest count subtracts them
        # (ONE shared definition, `coach_calibration.graded_sample_size`, used by both
        # writers; the conversational contribution stays disclosed in its own
        # accumulators, carried forward below).
        from coach.coach_calibration import graded_sample_size

        sample_size = graded_sample_size(
            alpha, beta_val, item.get("conversation_alpha") if item else 0, item.get("conversation_beta") if item else 0
        )

        new_item = {
            **experiment_stamp(),
            "pk": pk,
            "sk": sk,
            "alpha": _scalar_to_decimal(alpha),
            "beta_param": _scalar_to_decimal(beta_val),
            "mean_confidence": _scalar_to_decimal(mean_confidence),
            "sample_size": Decimal(str(max(0, sample_size))),
            "subdomain": subdomain,
            "coach_id": coach_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            # #1481 (ADR-141): provenance of the LAST update — the conversation
            # path (lambdas/coach_calibration.py) stamps "conversation" here.
            "source": "data",
        }
        # #1481: carry the conversational contribution accumulators forward —
        # this full-item put must not erase the audit split ADR-141 requires.
        if item:
            for carry in ("conversation_alpha", "conversation_beta"):
                if item.get(carry) is not None:
                    new_item[carry] = item[carry]
        table.put_item(Item=new_item)
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

    #1841: coach_id is empty for the subject's own on-tape diary claims. Writing one
    would land a LEARNING# row on a `COACH#` partition with no coach — a phantom that
    every track-record and hit-rate surface reading `COACH#` would then count. The claim's
    own record already carries its graded outcome, so there is nothing to lose by
    skipping, and a coach's calibration to corrupt by not.

    #2119: COACH#* is a tagger-blind partition — stamp write-time provenance
    (experiment_stamp(), #1233) so this LEARNING# row self-describes its reset
    generation, matching this module's own _update_bayesian_confidence.
    """
    if not coach_id:
        return

    prediction_id = evaluation.get("prediction_id", "unknown")
    slug = _slugify(f"{prediction_id}-{evaluation.get('status', 'eval')}")
    pk = f"COACH#{coach_id}"
    sk = f"LEARNING#{today_str}#{slug}"

    try:
        item = {
            **experiment_stamp(),
            "pk": pk,
            "sk": sk,
            "coach_id": coach_id,
            "date": today_str,
            "prediction_id": prediction_id,
            "channel": "data",  # #1481 (ADR-141): provenance — vs channel="conversation" from coach_calibration
            "evaluation_type": evaluation.get("evaluation_type", "machine"),
            "status": evaluation.get("status", ""),
            "metric": evaluation.get("metric", ""),
            "actual_value": _scalar_to_decimal(evaluation.get("actual_value")),
            "threshold": _scalar_to_decimal(evaluation.get("threshold")),
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
        past_grace = _check_expiry(pred, effective_window, today)

        # Retire any undecided call past the 2x window. #2221: this covered 'inconclusive'
        # only, so a conditional whose precondition never materialised stayed 'pending'
        # forever — re-graded daily, never decided, never retired, inflating GradableCount
        # while ADR-105's "every forecast is graded" went unmet. 'expired' moves no
        # confidence: a call the world never tested is not a hit and not a miss.
        if status in ("inconclusive", "pending") and past_grace:
            status = "expired"
            result["status"] = "expired"
            result["reason"] = (
                f"Expired: {(today - created_dt).days} days elapsed "
                f"(window={effective_window}, max={effective_window * EXPIRY_MULTIPLIER}). " + result.get("reason", "")
            )

        # Still inside the grace period — the precondition may yet arrive; don't write.
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
            # #2221: undecidable inside the grace period -> provisional, re-graded tomorrow.
            "grading_open": status == "inconclusive" and not past_grace,
        }
        evaluations.append(evaluation)

        # Write status update to prediction record
        _update_prediction_status(pred, evaluation)

        # Update Bayesian confidence if applicable
        if bayesian_update and coach_id and subdomain:
            _update_bayesian_confidence(coach_id, subdomain, bayesian_update)

        # Write learning log record. #2221: a provisional grade writes none — one row per
        # day per undecided call would crowd real outcomes out of the 60-row window the
        # public coach profile reads. The terminal outcome writes exactly one.
        if not evaluation["grading_open"]:
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

from ai.ai_context import _WEIGHT_MILESTONES  # noqa: E402 — the one canonical list (see ai_context._build_milestone_context)
from ai.budget_guard import allow as _budget_allow  # noqa: E402
from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days
from health.sick_day_checker import check_sick_day  # noqa: E402

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
    # #1969 (#946 class): habit_scores is EXPERIMENT_SCOPED — around a reset the
    # exact-key read can hit a tombstoned row, and a relapse "event" fired off
    # wiped vice_streaks would trigger stance refreshes from a cycle that no
    # longer exists. Tombstoned/wrong-phase rows read as absent.
    try:
        from experiment.phase_filter import singleton_visible

        resp = table.get_item(Key={"pk": f"{USER_PREFIX}habit_scores", "sk": f"DATE#{date_str}"})
        item = _decimal_to_float(resp.get("Item"))
        if not singleton_visible(item):
            return {}
        return item
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


def emit_grading_liveness(stats, gradable_count, today_str, ungradeable_count=0):
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
    - UngradeablePendingCount / GradableShare (#3046) — pending-corpus composition.
      GradingStalled resets on ANY decided outcome, so a structurally-skipped
      qualitative MAJORITY was invisible to it (DIL-007: 28/50 pending). The share
      = gradable / (gradable + ungradeable-pending); monitoring alarms at < 0.5
      sustained (prediction-gradable-share-low). Emitted only when the pending
      corpus is non-empty — an empty board has no composition to judge, and the
      alarm treats missing data as not-breaching (a dead evaluator is
      GradingStalled's job, via its BREACHING gauge).
    """
    decided_count = int(stats.get("confirmed", 0)) + int(stats.get("refuted", 0))

    if decided_count > 0:
        _write_last_decided_date(today_str)
        days_since = 0
    else:
        days_since = _days_since(today_str, _read_last_decided_date())

    pending_total = int(gradable_count) + int(ungradeable_count)
    gradable_share = (float(gradable_count) / pending_total) if pending_total > 0 else None

    payload = {
        "decided_count": decided_count,
        "gradable_count": int(gradable_count),
        "days_since_last_decided": days_since,
        "ungradeable_pending_count": int(ungradeable_count),
        "gradable_share": gradable_share,
    }
    try:
        metric_data = [
            {"MetricName": "DecidedCount", "Value": float(decided_count), "Unit": "Count"},
            {"MetricName": "GradableCount", "Value": float(gradable_count), "Unit": "Count"},
            {"MetricName": "DaysSinceLastDecided", "Value": float(days_since), "Unit": "Count"},
            {"MetricName": "UngradeablePendingCount", "Value": float(ungradeable_count), "Unit": "Count"},
        ]
        if gradable_share is not None:
            metric_data.append({"MetricName": "GradableShare", "Value": gradable_share, "Unit": "None"})
        _cw.put_metric_data(Namespace=LIVENESS_NAMESPACE, MetricData=metric_data)
        logger.info(
            "[liveness] decided=%d gradable=%d days_since_last_decided=%d ungradeable_pending=%d share=%s",
            decided_count,
            gradable_count,
            days_since,
            ungradeable_count,
            "n/a" if gradable_share is None else f"{gradable_share:.2f}",
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
        today_str = pacific_today()

        logger.info("coach-prediction-evaluator START date=%s", today_str)

        # Fetch all evaluable predictions (+ the legacy ungradeable-pending set, #3046)
        predictions, ungradeable = _fetch_predictions()

        # Run prediction evaluations (commitments are graded below regardless — a coach
        # can have follow-through to check even on a day with no open predictions).
        if predictions:
            evaluations, stats = _evaluate_all(predictions, today_str)
            logger.info("coach-prediction-evaluator COMPLETE: %d predictions evaluated out of %d found", len(evaluations), len(predictions))
        else:
            logger.info("No evaluable predictions found.")
            evaluations, stats = [], {}

        # #3046: retire legacy pending-qualitative records at window end — they have
        # no grading path and would otherwise pend forever. Fail-soft.
        retired_ungradeable = 0
        try:
            retired_ungradeable = _retire_ungradeable(ungradeable, today_str)
        except Exception as e:
            logger.error("Ungradeable retirement failed (non-fatal): %s", e)

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

        # #1386: resolve due Dispute Docket entries in the same deterministic
        # lane (ADR-105 — verdicts are code; the docket resolver reuses THIS
        # module's metric resolution + Bayesian update). Fail-soft — a docket
        # error must never sink prediction evaluation.
        docket_stats = {}
        try:
            from coach import dispute_docket

            docket_stats = dispute_docket.resolve_due(today_str)
        except Exception as e:
            logger.error("Dispute-docket resolution failed (non-fatal): %s", e)

        # #727: scientific-liveness — emit decided/gradable counts + the
        # days-since-last-decided gauge EVERY run (the stall alarm needs a daily
        # datapoint). gradable_count is the evaluable predictions found this run.
        liveness = {}
        try:
            liveness = emit_grading_liveness(stats, len(predictions), today_str, ungradeable_count=len(ungradeable))
        except Exception as e:
            logger.error("Grading-liveness emit failed (non-fatal): %s", e)

        return {
            "statusCode": 200,
            "date": today_str,
            "algo_version": ALGO_VERSION,
            "predictions_found": len(predictions),
            "predictions_evaluated": len(evaluations),
            "ungradeable_pending": len(ungradeable),
            "ungradeable_retired": retired_ungradeable,
            "stats": stats,
            "commitment_stats": commitment_stats,
            "stance_refresh_stats": stance_refresh_stats,
            "docket_stats": docket_stats,
            "liveness": liveness,
            "evaluations": evaluations,
        }
    except Exception as e:
        logger.error("coach-prediction-evaluator FAILED: %s", e, exc_info=True)
        return {"statusCode": 500, "error": str(e)}
