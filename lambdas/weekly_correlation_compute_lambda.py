"""
Weekly Correlation Compute Lambda — v1.0.0 (R8-LT9)
Scheduled Sunday at 11:30 AM PT (18:30 UTC via EventBridge).
Runs after ingestion week is complete but before hypothesis engine (12:00 PM PT).

Computes Pearson correlations between ~20 key metric pairs over a rolling 90-day
window and stores results to SOURCE#weekly_correlations. MCP tools can read this
partition for instant correlation lookups instead of computing from raw sources.

DynamoDB partition written:
  SOURCE#weekly_correlations   sk: WEEK#<iso_week>   (e.g. WEEK#2026-W11)

Correlation pairs computed:
  Recovery/Sleep    hrv vs recovery, sleep_duration vs recovery, hrv vs sleep_score
  Training          tsb vs recovery, strain vs hrv, zone2_min vs hrv
  Nutrition         protein_g vs recovery, calories vs hrv, carbs vs glucose_mean
  Habits            tier0_pct vs day_grade, tier01_pct vs recovery
  Lifestyle         steps vs recovery, steps vs hrv, mood_score vs hrv
  Weight            weight_lbs vs recovery, calories vs weight_change

Schedule: cron(30 18 ? * SUN *) — Sunday 11:30 AM PT (30 min before hypothesis engine)

v1.0.0 — 2026-03-14 (R8-LT9)
"""

import json
import math
import os
import time
import logging
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# OBS-1: Structured logger
try:
    from platform_logger import get_logger
    logger = get_logger("weekly-correlation-compute")
except ImportError:
    logger = logging.getLogger("weekly-correlation-compute")
    logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)

# ── Lookback window ───────────────────────────────────────────────────────────
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "90"))


# ==============================================================================
# HELPERS
# ==============================================================================

def d2f(obj):
    """Recursively convert DynamoDB Decimal to float."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def _to_dec(val):
    if val is None: return None
    try:
        return Decimal(str(round(float(val), 6)))
    except Exception:
        return None


def fetch_range(source, start_date, end_date):
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
            records.extend(d2f(item) for item in r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning("fetch_range(%s, %s→%s) failed: %s", source, start_date, end_date, e)
        return []


def safe_float(rec, field):
    """Extract float from record or return None."""
    if not rec or field not in rec:
        return None
    try:
        return float(rec[field])
    except (TypeError, ValueError):
        return None


# ==============================================================================
# PEARSON CORRELATION
# ==============================================================================

def pearson_r(xs, ys):
    """Compute Pearson r for paired lists. Returns None if insufficient variance."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 10:
        return None, n
    xs2, ys2 = zip(*pairs)
    mx = sum(xs2) / n
    my = sum(ys2) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dxs = math.sqrt(sum((x - mx) ** 2 for x in xs2))
    dys = math.sqrt(sum((y - my) ** 2 for y in ys2))
    if dxs == 0 or dys == 0:
        return None, n
    r = num / (dxs * dys)
    return round(max(-1.0, min(1.0, r)), 4), n


# Minimum sample sizes for each interpretation label (Henning, R9).
# Pearson r on small n is extremely noisy — a r=0.7 on n=12 must not be called 'strong'.
_INTERP_N_REQUIRED = {
    "strong":   50,  # |r| >= 0.6 AND n >= 50
    "moderate": 30,  # |r| >= 0.4 AND n >= 30
    "weak":     10,  # |r| >= 0.2 AND n >= 10
}


def interpret_r(r, n=None):
    """Classify correlation strength, gated on sample size.

    With small n, downgrade interpretation to avoid spurious 'strong' labels.
    Requires n >= 30 for 'moderate', n >= 50 for 'strong'.
    """
    if r is None:
        return "insufficient_data"
    abs_r = abs(r)
    # Determine raw label from r magnitude
    if abs_r >= 0.6:
        raw = "strong"
    elif abs_r >= 0.4:
        raw = "moderate"
    elif abs_r >= 0.2:
        raw = "weak"
    else:
        return "negligible"

    # Downgrade if n is too small for the label
    if n is not None:
        required = _INTERP_N_REQUIRED.get(raw, 0)
        if n < required:
            # Downgrade one level
            if raw == "strong":
                raw = "moderate" if n >= _INTERP_N_REQUIRED["moderate"] else "weak"
            elif raw == "moderate":
                raw = "weak" if n >= _INTERP_N_REQUIRED["weak"] else "insufficient_data"
            elif raw == "weak":
                raw = "insufficient_data"
    return raw


# ==============================================================================
# DATA ASSEMBLY
# ==============================================================================

def assemble_daily_series(start_date, end_date):
    """
    Fetch all source records for the lookback window and build a
    date-keyed dict of extracted metric values.

    Returns: dict[date_str → dict[metric_name → float]]
    """
    # Fetch all required sources in parallel-ish sequential calls
    sources = {
        "whoop":       fetch_range("whoop",       start_date, end_date),
        "strava":      fetch_range("strava",       start_date, end_date),
        "macrofactor": fetch_range("macrofactor",  start_date, end_date),
        "apple":       fetch_range("apple_health", start_date, end_date),
        "habitify":    fetch_range("habitify",     start_date, end_date),
        "computed":    fetch_range("computed_metrics", start_date, end_date),
        "composite":   fetch_range("composite_scores",  start_date, end_date),
        "cgm":         fetch_range("apple_health", start_date, end_date),  # CGM is in apple_health
    }

    # Build date-indexed lookup per source
    by_date = {}

    def index_by_date(records, source_key):
        for r in records:
            d = r.get("date") or r.get("sk", "").replace("DATE#", "")[:10]
            if d:
                by_date.setdefault(d, {})[source_key] = r

    for src_key, records in sources.items():
        index_by_date(records, src_key)

    # Build metric series per date
    series = {}
    for d, src_map in sorted(by_date.items()):
        w   = src_map.get("whoop")
        st  = src_map.get("strava")
        mf  = src_map.get("macrofactor")
        ap  = src_map.get("apple")
        hab = src_map.get("habitify")
        cm  = src_map.get("computed")
        co  = src_map.get("composite")

        metrics = {}

        # ── Recovery / Sleep ─────────────────────────────────────────────
        metrics["hrv"]              = safe_float(w, "hrv")
        metrics["recovery_score"]   = safe_float(w, "recovery_score")
        metrics["sleep_duration"]   = safe_float(w, "sleep_duration_hours")
        metrics["sleep_score"]      = safe_float(w, "sleep_quality_score") or safe_float(w, "sleep_score")
        metrics["resting_hr"]       = safe_float(w, "resting_heart_rate")
        metrics["strain"]           = safe_float(w, "strain")

        # ── Training ─────────────────────────────────────────────────────
        metrics["tsb"]              = safe_float(cm, "tsb") or safe_float(co, "tsb")
        if st:
            acts = st.get("activities", [])
            metrics["training_kj"]  = sum(float(a.get("kilojoules") or 0) for a in acts)
            metrics["training_mins"] = sum(float(a.get("moving_time_seconds") or 0) / 60 for a in acts)
        else:
            metrics["training_kj"]  = None
            metrics["training_mins"] = None

        # ── Nutrition ─────────────────────────────────────────────────────
        metrics["calories"]         = safe_float(mf, "total_calories_kcal")
        metrics["protein_g"]        = safe_float(mf, "total_protein_g")
        metrics["carbs_g"]          = safe_float(mf, "total_carbs_g")
        metrics["fat_g"]            = safe_float(mf, "total_fat_g")

        # ── Activity ─────────────────────────────────────────────────────
        metrics["steps"]            = safe_float(ap, "steps")

        # ── Composite / Computed ──────────────────────────────────────────
        metrics["day_grade"]        = safe_float(cm, "day_grade_score") or safe_float(co, "day_grade_score")
        metrics["readiness"]        = safe_float(cm, "readiness_score") or safe_float(co, "readiness_score")
        metrics["tier0_streak"]     = safe_float(cm, "tier0_streak") or safe_float(co, "tier0_streak")

        # ── Habits ────────────────────────────────────────────────────────
        if hab:
            habits = hab.get("habits", {})
            done  = sum(1 for v in habits.values() if v)
            total = len(habits)
            metrics["habit_pct"] = (done / total) if total > 0 else None
        else:
            metrics["habit_pct"] = None

        series[d] = metrics

    return series


# ==============================================================================
# CORRELATION COMPUTATION
# ==============================================================================

# Pairs to compute: (metric_a, metric_b, label, lag_days)
# lag_days: 0 = same-day cross-sectional; N = metric_a on day D predicts metric_b on day D+N
# Henning (R12): distinguish cross_sectional vs lagged correlations in output —
# lagged correlations have fewer effective degrees of freedom and must not be
# interpreted using the same significance thresholds as cross-sectional.
CORRELATION_PAIRS = [
    # Recovery / HRV (cross-sectional)
    ("hrv",           "recovery_score",  "hrv_vs_recovery",               0),
    ("sleep_duration","recovery_score",  "sleep_duration_vs_recovery",    0),
    ("sleep_score",   "recovery_score",  "sleep_score_vs_recovery",       0),
    ("hrv",           "sleep_score",     "hrv_vs_sleep_score",            0),
    ("resting_hr",    "recovery_score",  "rhr_vs_recovery",               0),

    # Training (cross-sectional; lagged versions are the higher-value analysis)
    ("tsb",           "recovery_score",  "tsb_vs_recovery",               0),
    ("strain",        "hrv",             "strain_vs_hrv",                 0),
    ("training_kj",   "hrv",             "training_load_vs_hrv",          0),
    ("training_mins", "recovery_score",  "training_mins_vs_recovery",     0),

    # Nutrition (cross-sectional)
    ("protein_g",     "recovery_score",  "protein_vs_recovery",           0),
    ("calories",      "hrv",             "calories_vs_hrv",               0),
    ("carbs_g",       "hrv",             "carbs_vs_hrv",                  0),

    # Activity / Steps (cross-sectional)
    ("steps",         "recovery_score",  "steps_vs_recovery",             0),
    ("steps",         "hrv",             "steps_vs_hrv",                  0),
    ("steps",         "sleep_score",     "steps_vs_sleep",                0),

    # Habits (cross-sectional)
    ("habit_pct",     "day_grade",       "habit_pct_vs_day_grade",        0),
    ("habit_pct",     "recovery_score",  "habit_pct_vs_recovery",         0),
    ("tier0_streak",  "day_grade",       "tier0_streak_vs_day_grade",     0),

    # Weight / Nutrition (cross-sectional)
    ("calories",      "day_grade",       "calories_vs_day_grade",         0),
    ("readiness",     "day_grade",       "readiness_vs_day_grade",        0),

    # Lagged predictive pairs (lag_days > 0)
    # Henning: lagged pairs test whether metric_a TODAY predicts metric_b TOMORROW.
    # Degrees of freedom reduced by lag_days; interpretation requires higher n thresholds.
    ("hrv",           "training_kj",     "hrv_predicts_next_day_load",    1),
    ("recovery_score","training_kj",     "recovery_predicts_next_day_load", 1),
    ("training_kj",   "recovery_score",  "load_predicts_next_day_recovery", 1),
]


def compute_correlations(series):
    """Compute all pairs from the daily series dict.

    Handles both cross-sectional (lag=0) and lagged (lag>0) pairs.
    Lagged pairs: xs from day D, ys from day D+lag_days.

    Henning (R12): correlation_type distinguishes cross_sectional from lagged.
    Lagged correlations have reduced effective degrees of freedom; n-gating
    thresholds still apply but interpretation must note the predictive framing.
    """
    dates = sorted(series.keys())
    results = {}

    for pair in CORRELATION_PAIRS:
        # Support old 3-tuple format (no lag) and new 4-tuple format (with lag)
        if len(pair) == 4:
            metric_a, metric_b, label, lag_days = pair
        else:
            metric_a, metric_b, label = pair
            lag_days = 0

        if lag_days == 0:
            # Cross-sectional: same day for both metrics
            xs = [series[d].get(metric_a) for d in dates]
            ys = [series[d].get(metric_b) for d in dates]
            correlation_type = "cross_sectional"
        else:
            # Lagged: xs from day D, ys from day D+lag_days
            # For each date, find the lagged date and pair them
            xs, ys = [], []
            for i, d in enumerate(dates):
                # Find target date = d + lag_days
                try:
                    target_date = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
                except Exception:
                    continue
                if target_date in series:
                    x_val = series[d].get(metric_a)
                    y_val = series[target_date].get(metric_b)
                    xs.append(x_val)
                    ys.append(y_val)
            correlation_type = f"lagged_{lag_days}d"

        r, n = pearson_r(xs, ys)
        results[label] = {
            "metric_a":        metric_a,
            "metric_b":        metric_b,
            "pearson_r":       r,
            "r_squared":       round(r ** 2, 4) if r is not None else None,
            "n_days":          n,
            "interpretation":  interpret_r(r, n),  # n-gated: moderate≥30, strong≥50
            "direction":       ("positive" if r > 0 else "negative") if r is not None else None,
            "correlation_type": correlation_type,   # Henning R12: cross_sectional vs lagged
            "lag_days":        lag_days if lag_days > 0 else None,
        }
        if r is not None:
            logger.info("  %-45s r=%.3f (n=%d, %s, %s)", label, r, n, interpret_r(r, n), correlation_type)

    return results


# ==============================================================================
# STORE
# ==============================================================================

def store_correlations(week_key, correlations, start_date, end_date, computed_at):
    """Write correlation results to SOURCE#weekly_correlations partition."""
    # Convert float values to Decimal for DynamoDB
    def _dec_correlations(corr_dict):
        result = {}
        for label, data in corr_dict.items():
            result[label] = {}
            for k, v in data.items():
                if isinstance(v, float):
                    result[label][k] = _to_dec(v) or Decimal("0")
                elif isinstance(v, int):
                    result[label][k] = Decimal(str(v))
                elif v is not None:
                    result[label][k] = v
        return result

    item = {
        "pk":          USER_PREFIX + "weekly_correlations",
        "sk":          "WEEK#" + week_key,
        "week":        week_key,
        "start_date":  start_date,
        "end_date":    end_date,
        "lookback_days": Decimal(str(LOOKBACK_DAYS)),
        "n_pairs":     Decimal(str(len(correlations))),
        "correlations": _dec_correlations(correlations),
        "computed_at": computed_at,
    }
    table.put_item(Item=item)
    logger.info("Stored weekly_correlations for week %s (%d pairs)", week_key, len(correlations))


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================

def lambda_handler(event, context):
    t0 = time.time()
    now = datetime.now(timezone.utc)
    logger.info("Weekly Correlation Compute v1.0.0 starting...")

    # Determine target week
    if event.get("week"):
        # Manual override: "2026-W10"
        week_key = event["week"]
        # Derive end_date from week key
        year, week_num = week_key.split("-W")
        # ISO week: Monday of that week
        target_monday = datetime.strptime(f"{year}-W{week_num}-1", "%Y-W%W-%w")
        end_date = (target_monday + timedelta(days=6)).strftime("%Y-%m-%d")
    else:
        # Default: compute for the week ending today (Sunday run)
        iso_year, iso_week, _ = now.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        end_date = now.strftime("%Y-%m-%d")

    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=LOOKBACK_DAYS - 1)).strftime("%Y-%m-%d")
    computed_at = now.isoformat()

    logger.info("Computing correlations for week %s | window: %s → %s (%d days)",
                week_key, start_date, end_date, LOOKBACK_DAYS)

    # Idempotency — skip if already computed this week unless forced
    if not event.get("force"):
        try:
            existing = table.get_item(Key={
                "pk": USER_PREFIX + "weekly_correlations",
                "sk": "WEEK#" + week_key,
            }).get("Item")
            if existing:
                stored_at = existing.get("computed_at", "")
                logger.info("Already computed for week %s at %s — skipping (pass force=true to recompute)",
                            week_key, stored_at)
                return {
                    "statusCode": 200,
                    "body": f"Already computed for {week_key}",
                    "skipped": True,
                    "week": week_key,
                }
        except Exception as e:
            logger.warning("Idempotency check failed (proceeding): %s", e)

    # Assemble daily metric series
    logger.info("Fetching source data...")
    series = assemble_daily_series(start_date, end_date)
    logger.info("Assembled %d days of data", len(series))

    if len(series) < 10:
        logger.warning("Insufficient data (%d days) — need at least 10 for meaningful correlations",
                       len(series))
        return {
            "statusCode": 200,
            "body": f"Insufficient data: {len(series)} days (need ≥10)",
            "week": week_key,
            "days_available": len(series),
        }

    # Compute correlations
    logger.info("Computing %d correlation pairs...", len(CORRELATION_PAIRS))
    correlations = compute_correlations(series)

    # Store
    store_correlations(week_key, correlations, start_date, end_date, computed_at)

    elapsed = time.time() - t0
    significant = {k: v for k, v in correlations.items()
                   if v.get("pearson_r") is not None and abs(v["pearson_r"]) >= 0.3}
    logger.info("Done in %.1fs — %d pairs computed, %d significant (|r|≥0.3)",
                elapsed, len(correlations), len(significant))

    return {
        "statusCode":     200,
        "body":           f"Weekly correlations computed for {week_key}",
        "week":           week_key,
        "start_date":     start_date,
        "end_date":       end_date,
        "days_analyzed":  len(series),
        "pairs_computed": len(correlations),
        "significant":    len(significant),
        "elapsed_seconds": round(elapsed, 1),
    }
