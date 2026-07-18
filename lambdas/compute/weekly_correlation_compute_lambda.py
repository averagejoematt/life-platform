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

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import digest_utils  # shared query_range implementations (#970)
import experiment_gates  # #1371: the ONE registry of arming thresholds
import stats_core  # bundled shared module (#529): the one sanctioned stats implementation

# OBS-1: Structured logger
try:
    from platform_logger import get_logger

    logger = get_logger("weekly-correlation-compute")
except ImportError:
    logger = logging.getLogger("weekly-correlation-compute")
    logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)

# ── Lookback window ───────────────────────────────────────────────────────────
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "90"))


# ==============================================================================
# HELPERS
# ==============================================================================

# d2f / pagination / phase filter all live in digest_utils.query_range_list now (R13-F10, #970).


def _to_dec(val):
    if val is None:
        return None
    try:
        return Decimal(str(round(float(val), 6)))
    except Exception:
        return None


def fetch_range(source, start_date, end_date):
    """Paginated DDB query for source records in date range, as a list.

    Shared paginated, phase-scoped implementation (digest_utils, #970).
    Fail-soft ([] on error) preserved: a single source's failure degrades to
    no-data for that source rather than failing the whole compute run.
    """
    try:
        return digest_utils.query_range_list(table, source, start_date, end_date, user_id=USER_ID)
    except Exception as e:
        logger.warning("fetch_range(%s, %s→%s) failed: %s", source, start_date, end_date, e)
        return []


from digest_utils import safe_float  # shared bundled helpers (#970)

# ==============================================================================
# PEARSON CORRELATION (math lives in stats_core — #529/ADR-105; only the
# results-dict plumbing stays here)
# ==============================================================================


def pearson_r(xs, ys):
    """Pearson r for paired lists via stats_core; keeps this lambda's contract:
    (r rounded to 4, n) with min n from the experiment_gates registry (#1371)."""
    xs2, ys2 = stats_core.clean_pairs(xs, ys)
    n = len(xs2)
    r = stats_core.pearson_r(xs2, ys2, min_n=experiment_gates.CORRELATION_MIN_N)
    return (round(r, 4) if r is not None else None), n


def apply_benjamini_hochberg(results: dict, alpha: float = 0.05) -> dict:
    """Apply Benjamini-Hochberg FDR correction to a dict of correlation results.

    R13-F15: With 23 simultaneous hypothesis tests at nominal alpha=0.05, we
    expect ~1.15 false positives per run under the null. BH controls the
    expected proportion of false discoveries rather than the per-comparison
    error rate (Bonferroni), making it appropriate for exploratory health data
    where some true correlations exist.

    #529/ADR-105: each pair's p-value is computed on its autocorrelation-corrected
    effective n (`n_eff`, stamped by compute_correlations) rather than raw n_days —
    daily series are not i.i.d., and raw-n p-values were anticonservative.

    Modifies each result in-place, adding:
      p_value          : individual two-tailed p-value (on n_eff)
      p_value_fdr      : BH-adjusted p-value
      fdr_significant  : True if p_value_fdr <= alpha

    Pairs without a valid r (insufficient data) get p_value=None, fdr_significant=False.
    Returns modified results dict.
    """
    labels = list(results.keys())
    pvals = []
    for label in labels:
        data = results[label]
        r = data.get("pearson_r")
        n = data.get("n_eff") or data.get("n_days", 0)
        p = stats_core.pearson_p_value(r, n) if r is not None else None
        data["p_value"] = p
        pvals.append(p)

    adjusted = stats_core.bh_fdr(pvals)
    for label, p_adj in zip(labels, adjusted):
        if p_adj is None:
            results[label]["p_value_fdr"] = None
            results[label]["fdr_significant"] = False
        else:
            results[label]["p_value_fdr"] = round(p_adj, 4)
            results[label]["fdr_significant"] = p_adj <= alpha

    return results


# Minimum sample sizes for each interpretation label (Henning, R9).
# Pearson r on small n is extremely noisy — a r=0.7 on n=12 must not be called 'strong'.
# #1371: defined in the experiment_gates registry (the site serves the same values
# in zero-states, so the rendered trigger can never drift from this enforcement).
_INTERP_N_REQUIRED = experiment_gates.CORRELATION_INTERP_N


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
        "whoop": fetch_range("whoop", start_date, end_date),
        "strava": fetch_range("strava", start_date, end_date),
        "macrofactor": fetch_range("macrofactor", start_date, end_date),
        "apple": fetch_range("apple_health", start_date, end_date),
        "habitify": fetch_range("habitify", start_date, end_date),
        "computed": fetch_range("computed_metrics", start_date, end_date),
        # R17-14 / ADR-025: composite_scores partition removed — all fields consolidated
        # into computed_metrics since v3.7.28. No new data written to composite_scores.
        "cgm": fetch_range("apple_health", start_date, end_date),  # CGM is in apple_health
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
        w = src_map.get("whoop")
        st = src_map.get("strava")
        mf = src_map.get("macrofactor")
        ap = src_map.get("apple")
        hab = src_map.get("habitify")
        cm = src_map.get("computed")

        metrics = {}

        # ── Recovery / Sleep ─────────────────────────────────────────────
        metrics["hrv"] = safe_float(w, "hrv")
        metrics["recovery_score"] = safe_float(w, "recovery_score")
        metrics["sleep_duration"] = safe_float(w, "sleep_duration_hours")
        metrics["sleep_score"] = safe_float(w, "sleep_quality_score") or safe_float(w, "sleep_score")
        metrics["resting_hr"] = safe_float(w, "resting_heart_rate")
        metrics["strain"] = safe_float(w, "strain")

        # ── Training ─────────────────────────────────────────────────────
        metrics["tsb"] = safe_float(cm, "tsb")
        if st:
            acts = st.get("activities", [])
            metrics["training_kj"] = sum(float(a.get("kilojoules") or 0) for a in acts)
            metrics["training_mins"] = sum(float(a.get("moving_time_seconds") or 0) / 60 for a in acts)
        else:
            metrics["training_kj"] = None
            metrics["training_mins"] = None

        # ── Nutrition ─────────────────────────────────────────────────────
        metrics["calories"] = safe_float(mf, "total_calories_kcal")
        metrics["protein_g"] = safe_float(mf, "total_protein_g")
        metrics["carbs_g"] = safe_float(mf, "total_carbs_g")
        metrics["fat_g"] = safe_float(mf, "total_fat_g")

        # ── Activity ─────────────────────────────────────────────────────
        metrics["steps"] = safe_float(ap, "steps")

        # ── Composite / Computed ──────────────────────────────────────────
        metrics["day_grade"] = safe_float(cm, "day_grade_score")
        metrics["readiness"] = safe_float(cm, "readiness_score")
        metrics["tier0_streak"] = safe_float(cm, "tier0_streak")

        # ── Habits ────────────────────────────────────────────────────────
        if hab:
            habits = hab.get("habits", {})
            done = sum(1 for v in habits.values() if v)
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
    ("hrv", "recovery_score", "hrv_vs_recovery", 0),
    ("sleep_duration", "recovery_score", "sleep_duration_vs_recovery", 0),
    ("sleep_score", "recovery_score", "sleep_score_vs_recovery", 0),
    ("hrv", "sleep_score", "hrv_vs_sleep_score", 0),
    ("resting_hr", "recovery_score", "rhr_vs_recovery", 0),
    # Training (cross-sectional; lagged versions are the higher-value analysis)
    ("tsb", "recovery_score", "tsb_vs_recovery", 0),
    ("strain", "hrv", "strain_vs_hrv", 0),
    ("training_kj", "hrv", "training_load_vs_hrv", 0),
    ("training_mins", "recovery_score", "training_mins_vs_recovery", 0),
    # Nutrition (cross-sectional)
    ("protein_g", "recovery_score", "protein_vs_recovery", 0),
    ("calories", "hrv", "calories_vs_hrv", 0),
    ("carbs_g", "hrv", "carbs_vs_hrv", 0),
    # Activity / Steps (cross-sectional)
    ("steps", "recovery_score", "steps_vs_recovery", 0),
    ("steps", "hrv", "steps_vs_hrv", 0),
    ("steps", "sleep_score", "steps_vs_sleep", 0),
    # Habits (cross-sectional)
    ("habit_pct", "day_grade", "habit_pct_vs_day_grade", 0),
    ("habit_pct", "recovery_score", "habit_pct_vs_recovery", 0),
    ("tier0_streak", "day_grade", "tier0_streak_vs_day_grade", 0),
    # Weight / Nutrition (cross-sectional)
    ("calories", "day_grade", "calories_vs_day_grade", 0),
    ("readiness", "day_grade", "readiness_vs_day_grade", 0),
    # Lagged predictive pairs (lag_days > 0)
    # Henning: lagged pairs test whether metric_a TODAY predicts metric_b TOMORROW.
    # Degrees of freedom reduced by lag_days; interpretation requires higher n thresholds.
    ("hrv", "training_kj", "hrv_predicts_next_day_load", 1),
    ("recovery_score", "training_kj", "recovery_predicts_next_day_load", 1),
    ("training_kj", "recovery_score", "load_predicts_next_day_recovery", 1),
]


# DISC-1: Domain knowledge — expected direction for each pair.
# When observed direction differs from expected AND |r| >= 0.2, the finding
# is flagged as counterintuitive for the public Discoveries page.
EXPECTED_DIRECTIONS = {
    "hrv_vs_recovery": "positive",  # higher HRV → better recovery
    "sleep_duration_vs_recovery": "positive",  # more sleep → better recovery
    "sleep_score_vs_recovery": "positive",  # better sleep → better recovery
    "hrv_vs_sleep_score": "positive",  # higher HRV → better sleep
    "rhr_vs_recovery": "negative",  # lower RHR → better recovery
    "tsb_vs_recovery": "positive",  # positive TSB → better recovery
    "strain_vs_hrv": "negative",  # more strain → lower HRV (same day)
    "training_load_vs_hrv": "negative",  # more training → lower HRV
    "training_mins_vs_recovery": "negative",  # more training → lower recovery (same day)
    "protein_vs_recovery": "positive",  # more protein → better recovery
    "calories_vs_hrv": "positive",  # adequate calories → higher HRV
    "carbs_vs_hrv": "positive",  # adequate carbs → higher HRV
    "steps_vs_recovery": "positive",  # more steps → better recovery
    "steps_vs_hrv": "positive",  # more steps → higher HRV
    "steps_vs_sleep": "positive",  # more steps → better sleep
    "habit_pct_vs_day_grade": "positive",  # better habits → better day
    "habit_pct_vs_recovery": "positive",  # better habits → better recovery
    "tier0_streak_vs_day_grade": "positive",  # longer streak → better day
    "calories_vs_day_grade": "positive",  # adequate calories → better day
    "readiness_vs_day_grade": "positive",  # higher readiness → better day
    "hrv_predicts_next_day_load": "positive",  # higher HRV → more training next day
    "recovery_predicts_next_day_load": "positive",  # better recovery → more training next day
    "load_predicts_next_day_recovery": "negative",  # more load → lower recovery next day
}


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
        # #529/ADR-105: effective n (AR(1)/Bartlett) feeds the p-value; the
        # moving-block bootstrap CI preserves day-to-day memory. Flat ci95_* keys —
        # store_correlations' Decimal conversion only handles top-level values.
        n_eff = ci95 = None
        if r is not None:
            xs2, ys2 = stats_core.clean_pairs(xs, ys)
            n_eff = round(stats_core.effective_sample_size(xs2, ys2), 1)
            ci95 = stats_core.moving_block_bootstrap_ci(xs2, ys2)
        results[label] = {
            "metric_a": metric_a,
            "metric_b": metric_b,
            "pearson_r": r,
            "r_squared": round(r**2, 4) if r is not None else None,
            "n_days": n,
            "n_eff": n_eff,
            "ci95_low": round(ci95[0], 3) if ci95 else None,
            "ci95_high": round(ci95[1], 3) if ci95 else None,
            "interpretation": interpret_r(r, n),  # n-gated: moderate≥30, strong≥50
            "direction": ("positive" if r > 0 else "negative") if r is not None else None,
            "correlation_type": correlation_type,  # Henning R12: cross_sectional vs lagged
            "lag_days": lag_days if lag_days > 0 else None,
        }
        # DISC-1: Flag counterintuitive findings where observed direction
        # differs from domain-knowledge expected direction.
        expected = EXPECTED_DIRECTIONS.get(label)
        observed = results[label].get("direction")
        results[label]["expected_direction"] = expected
        results[label]["counterintuitive"] = (
            expected is not None
            and observed is not None
            and expected != observed
            and abs(r or 0) >= 0.2  # only flag if signal is meaningful
        )

        if r is not None:
            ci_flag = " ** COUNTERINTUITIVE" if results[label]["counterintuitive"] else ""
            logger.info("  %-45s r=%.3f (n=%d, %s, %s)%s", label, r, n, interpret_r(r, n), correlation_type, ci_flag)

    # R13-F15: Apply Benjamini-Hochberg FDR correction across all m=23 pairs.
    # With 23 simultaneous tests at alpha=0.05, naive thresholding yields ~1.15
    # expected false positives. BH controls the false discovery rate instead.
    # Adds p_value, p_value_fdr, and fdr_significant fields to each result.
    results = apply_benjamini_hochberg(results, alpha=0.05)
    fdr_sig = sum(1 for v in results.values() if v.get("fdr_significant"))
    logger.info("[R13-F15] BH FDR correction applied: %d/%d pairs FDR-significant (alpha=0.05)", fdr_sig, len(results))

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
                if isinstance(v, bool):
                    result[label][k] = v  # bool before int (bool is subclass of int)
                elif isinstance(v, float):
                    result[label][k] = _to_dec(v) or Decimal("0")
                elif isinstance(v, int):
                    result[label][k] = Decimal(str(v))
                elif v is not None:
                    result[label][k] = v
        return result

    item = {
        "pk": USER_PREFIX + "weekly_correlations",
        "sk": "WEEK#" + week_key,
        "week": week_key,
        "start_date": start_date,
        "end_date": end_date,
        "lookback_days": Decimal(str(LOOKBACK_DAYS)),
        "n_pairs": Decimal(str(len(correlations))),
        "correlations": _dec_correlations(correlations),
        "computed_at": computed_at,
    }
    # V2 P2.6 (2026-05-19): tag with run_id + computed_at
    try:
        from compute_metadata import tag_record

        item = tag_record(item, source_id="weekly_correlations")
    except ImportError:
        pass
    table.put_item(Item=item)
    logger.info("Stored weekly_correlations for week %s (%d pairs)", week_key, len(correlations))


# ==============================================================================
# BS-TR1: CENTENARIAN DECATHLON PROGRESS TRACKER
# ==============================================================================

# Attia centenarian targets: bodyweight-relative 1RM targets at current age,
# computed to ensure functional independence at 80-85 given ~8-12% decline/decade.
CENTENARIAN_TARGETS = {
    "deadlift": 2.0,  # x bodyweight
    "squat": 1.75,
    "bench_press": 1.5,
    "overhead_press": 1.0,
}


def _compute_centenarian_progress(series, end_date):
    """Compute centenarian decathlon benchmark progress.

    Reads latest bodyweight from series (withings), then queries hevy partition
    for 1RM estimates per lift. Writes snapshot dict.
    """
    try:
        # Latest bodyweight from Withings (use dates near end_date)
        d30_start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
        wt_recs = fetch_range("withings", d30_start, end_date)
        wt_vals = [safe_float(r, "weight_lbs") for r in wt_recs if safe_float(r, "weight_lbs")]
        if not wt_vals:
            logger.warning("BS-TR1: No bodyweight data — skipping centenarian progress")
            return None
        bodyweight_lbs = wt_vals[-1]  # most recent

        # 1RM estimates from Hevy computed_metrics or hevy partition
        # Read from hevy source — look for computed 1rm fields written by hevy ingestion
        d180_start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
        hevy_recs = fetch_range("hevy", d180_start, end_date)

        # Collect max estimated_1rm per exercise name across all records
        lift_1rm = {}  # normalized_name → max 1RM (lbs)
        LIFT_ALIASES = {
            "deadlift": ["deadlift", "romanian deadlift", "rdl"],
            "squat": ["squat", "back squat", "front squat", "goblet squat"],
            "bench_press": ["bench press", "incline bench", "flat bench"],
            "overhead_press": ["overhead press", "ohp", "shoulder press", "military press"],
        }
        ALIAS_TO_LIFT = {}
        for lift, aliases in LIFT_ALIASES.items():
            for alias in aliases:
                ALIAS_TO_LIFT[alias] = lift

        for rec in hevy_recs:
            exercises = rec.get("exercises") or []
            for ex in exercises:
                ex_name = (ex.get("title") or ex.get("exercise_name") or "").lower().strip()
                e1rm = safe_float(ex, "estimated_1rm_lbs") or safe_float(ex, "e1rm_lbs")
                if not e1rm:
                    continue
                for alias, lift in ALIAS_TO_LIFT.items():
                    if alias in ex_name:
                        lift_1rm[lift] = max(lift_1rm.get(lift, 0.0), e1rm)
                        break

        # Score each lift
        lift_scores = {}
        overall_ready = 0
        lifts_scored = 0
        for lift, target_ratio in CENTENARIAN_TARGETS.items():
            target_lbs = target_ratio * bodyweight_lbs
            current_lbs = lift_1rm.get(lift)
            if current_lbs is None:
                lift_scores[lift] = {"status": "no_data", "target_lbs": round(target_lbs, 1)}
                continue
            pct_of_target = current_lbs / target_lbs
            gap_lbs = max(0.0, target_lbs - current_lbs)
            if pct_of_target >= 1.0:
                status = "exceeds_target"
            elif pct_of_target >= 0.9:
                status = "at_target"
            elif pct_of_target >= 0.75:
                status = "approaching"
            elif pct_of_target >= 0.5:
                status = "progressing"
            else:
                status = "below_minimum"
            lift_scores[lift] = {
                "current_lbs": round(current_lbs, 1),
                "target_lbs": round(target_lbs, 1),
                "target_ratio": target_ratio,
                "pct_of_target": round(pct_of_target * 100, 1),
                "gap_lbs": round(gap_lbs, 1),
                "status": status,
            }
            overall_ready += pct_of_target
            lifts_scored += 1

        overall_readiness = round(overall_ready / lifts_scored * 100, 1) if lifts_scored else None
        priority_lift = min(
            (l for l in CENTENARIAN_TARGETS if l in lift_1rm),
            key=lambda l: lift_1rm.get(l, 0) / (CENTENARIAN_TARGETS[l] * bodyweight_lbs),
            default=None,
        )

        return {
            "bodyweight_lbs": round(bodyweight_lbs, 1),
            "lifts": lift_scores,
            "overall_readiness": overall_readiness,
            "priority_lift": priority_lift,
            "lifts_scored": lifts_scored,
        }
    except Exception as e:
        logger.warning("BS-TR1 centenarian progress failed (non-fatal): %s", e)
        return None


def store_centenarian_progress(week_key, progress, end_date, computed_at):
    """Write centenarian progress snapshot to SOURCE#centenarian_progress."""
    if not progress:
        return
    item = {
        "pk": USER_PREFIX + "centenarian_progress",
        "sk": "WEEK#" + week_key,
        "week": week_key,
        "date": end_date,
        "computed_at": computed_at,
    }

    # Decimal-safe fields
    def _safe_dec(v):
        if v is None:
            return None
        try:
            return Decimal(str(round(float(v), 4)))
        except Exception:
            return None

    item["bodyweight_lbs"] = _safe_dec(progress["bodyweight_lbs"])
    item["overall_readiness"] = _safe_dec(progress["overall_readiness"])
    if progress["priority_lift"]:
        item["priority_lift"] = progress["priority_lift"]
    item["lifts_scored"] = Decimal(str(progress["lifts_scored"]))
    # Encode lift_scores as a map
    lifts_enc = {}
    for lift, data in progress["lifts"].items():
        lifts_enc[lift] = {k: (_safe_dec(v) if isinstance(v, float) else v) for k, v in data.items() if v is not None}
    item["lifts"] = lifts_enc
    table.put_item(Item=item)
    logger.info("BS-TR1: Stored centenarian_progress for week %s (readiness=%.1f%%)", week_key, progress["overall_readiness"] or 0)


# ==============================================================================
# BS-TR2: ZONE 2 CARDIAC EFFICIENCY TREND
# ==============================================================================

# Zone 2 HR range (as % of max HR) — matches get_zone2_breakdown defaults
ZONE2_HR_LOW = int(os.environ.get("ZONE2_HR_LOW", "110"))
ZONE2_HR_HIGH = int(os.environ.get("ZONE2_HR_HIGH", "139"))
ZONE2_MIN_DURATION_MINUTES = int(os.environ.get("ZONE2_MIN_DURATION_MINUTES", "20"))


def _compute_zone2_efficiency(series, end_date):
    """Compute weekly Zone 2 cardiac efficiency (pace-at-HR).

    For each Strava activity with avg_heartrate in Zone 2 range and duration
    >= ZONE2_MIN_DURATION_MINUTES, compute: efficiency = speed_mph / avg_heartrate.
    Higher = better (faster pace at same HR, or same pace at lower HR).
    Aggregates weekly efficiency, computes linear regression trend.
    """
    try:
        d90_start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        strava_recs = fetch_range("strava", d90_start, end_date)

        # Per-week: collect efficiency samples
        week_samples = {}  # week_key → [efficiency values]
        for rec in strava_recs:
            date_str = rec.get("date") or rec.get("sk", "").replace("DATE#", "")[:10]
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                iso = dt.isocalendar()
                week_key = f"{iso[0]}-W{iso[1]:02d}"
            except Exception:
                continue
            activities = rec.get("activities", [])
            for act in activities:
                avg_hr = safe_float(act, "average_heartrate")
                duration_s = safe_float(act, "moving_time_seconds") or 0
                distance_m = safe_float(act, "distance") or 0  # metres from Strava
                sport_type = (act.get("sport_type") or "").lower()

                if avg_hr is None or avg_hr < ZONE2_HR_LOW or avg_hr > ZONE2_HR_HIGH:
                    continue
                if duration_s < ZONE2_MIN_DURATION_MINUTES * 60:
                    continue
                if sport_type in ("weightraining", "weighttraining", "strength"):
                    continue
                # Compute efficiency: (distance_miles / duration_hours) / avg_hr
                # = speed_mph / avg_hr → dimensionless efficiency metric
                duration_h = duration_s / 3600
                distance_mi = distance_m * 0.000621371
                if duration_h <= 0 or distance_mi <= 0:
                    continue
                speed_mph = distance_mi / duration_h
                efficiency = speed_mph / avg_hr  # higher = better
                week_samples.setdefault(week_key, []).append(round(efficiency, 6))

        if not week_samples:
            logger.info("BS-TR2: No Zone 2 sessions found in 90-day window")
            return None

        # Weekly averages (chronological)
        weeks_sorted = sorted(week_samples.keys())
        weekly = []
        for wk in weeks_sorted:
            samples = week_samples[wk]
            weekly.append(
                {
                    "week": wk,
                    "avg_efficiency": round(sum(samples) / len(samples), 6),
                    "n_sessions": len(samples),
                }
            )

        # Linear regression trend
        if len(weekly) >= 4:
            y_vals = [w["avg_efficiency"] for w in weekly]
            n = len(y_vals)
            xs = list(range(n))
            x_mean = sum(xs) / n
            y_mean = sum(y_vals) / n
            num = sum((xs[i] - x_mean) * (y_vals[i] - y_mean) for i in range(n))
            den = sum((xs[i] - x_mean) ** 2 for i in range(n))
            slope_per_week = (num / den) if den else 0.0
            pct_change = round(slope_per_week / max(y_mean, 1e-9) * 100, 2)
            if slope_per_week > 0.0001:
                trend = "improving"
            elif slope_per_week < -0.0001:
                trend = "declining"
            else:
                trend = "stable"
        else:
            slope_per_week = None
            pct_change = None
            trend = "insufficient_data"

        latest_eff = weekly[-1]["avg_efficiency"] if weekly else None
        baseline_eff = weekly[0]["avg_efficiency"] if weekly else None

        return {
            "weeks_analyzed": len(weekly),
            "weekly": weekly,
            "trend": trend,
            "slope_per_week": round(slope_per_week, 8) if slope_per_week is not None else None,
            "pct_change_per_week": pct_change,
            "latest_efficiency": latest_eff,
            "baseline_efficiency": baseline_eff,
            "zone2_hr_range": f"{ZONE2_HR_LOW}–{ZONE2_HR_HIGH} bpm",
            "interpretation": (
                "Efficiency = speed_mph ÷ avg_HR. Higher = better fitness at same HR. " "Improving trend = aerobic base is growing."
            ),
        }
    except Exception as e:
        logger.warning("BS-TR2 zone2 efficiency failed (non-fatal): %s", e)
        return None


def store_zone2_efficiency(week_key, efficiency, end_date, computed_at):
    """Write zone2 efficiency snapshot to SOURCE#zone2_efficiency."""
    if not efficiency:
        return

    def _safe_dec(v):
        if v is None:
            return None
        try:
            return Decimal(str(round(float(v), 8)))
        except Exception:
            return None

    # Build weekly list (Decimal-safe)
    weekly_enc = []
    for w in efficiency.get("weekly", []):
        weekly_enc.append(
            {
                "week": w["week"],
                "avg_efficiency": _safe_dec(w["avg_efficiency"]),
                "n_sessions": Decimal(str(w["n_sessions"])),
            }
        )

    item = {
        "pk": USER_PREFIX + "zone2_efficiency",
        "sk": "WEEK#" + week_key,
        "week": week_key,
        "date": end_date,
        "computed_at": computed_at,
        "weeks_analyzed": Decimal(str(efficiency["weeks_analyzed"])),
        "trend": efficiency["trend"],
        "latest_efficiency": _safe_dec(efficiency["latest_efficiency"]),
        "baseline_efficiency": _safe_dec(efficiency["baseline_efficiency"]),
        "zone2_hr_range": efficiency["zone2_hr_range"],
        "weekly": weekly_enc,
    }
    if efficiency.get("slope_per_week") is not None:
        item["slope_per_week"] = _safe_dec(efficiency["slope_per_week"])
    if efficiency.get("pct_change_per_week") is not None:
        item["pct_change_per_week"] = _safe_dec(efficiency["pct_change_per_week"])

    table.put_item(Item=item)
    logger.info(
        "BS-TR2: Stored zone2_efficiency for week %s (trend=%s, weeks=%d)", week_key, efficiency["trend"], efficiency["weeks_analyzed"]
    )


# ==============================================================================
# SS-08: MONTHLY "WHAT CHANGED" — cumulative deltas + newly-unlocked correlations
# ==============================================================================
#
# So a flat DAY still shows MOTION over the MONTH. Two real, low-fabrication halves:
#   • deltas       — real trailing-30d vs prior-30d averages (n>=10 real days each
#                    half, never zero-filled/interpolated) for the headline metrics.
#   • newly_unlocked — correlations that FIRST crossed FDR significance within the
#                    trailing 30 days, via a first-seen ledger so a pair is announced
#                    ONCE and a flickering pair is never re-announced.
# honest_null when both are empty → the front-end shows a calm "steady month", not
# fake motion. Both halves piggyback the series + correlations already computed here.

# (series key, display label, unit, higher_is_better) — the metrics worth surfacing.
_MONTH_DELTA_METRICS = [
    ("recovery_score", "Recovery", "%", True),
    ("hrv", "HRV", "ms", True),
    ("sleep_duration", "Sleep", "h", True),
    ("resting_hr", "Resting HR", "bpm", False),
    ("steps", "Steps", "/day", True),
    ("protein_g", "Protein", "g", True),
    ("day_grade", "Day grade", "", True),
    ("readiness", "Readiness", "", True),
]


def _deep_dec(obj):
    """Recursively cast floats→Decimal through lists/dicts for a DynamoDB write."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return _to_dec(obj) or Decimal("0")
    if isinstance(obj, int):
        return Decimal(str(obj))
    if isinstance(obj, list):
        return [_deep_dec(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _deep_dec(v) for k, v in obj.items()}
    return obj


def compute_month_deltas(series, end_date, *, metrics=None, min_days=10):
    """Real trailing-30d vs prior-30d averages for the headline metrics. A metric is
    emitted ONLY when BOTH halves have >= min_days real (non-None) values — never
    zero-filled or interpolated — and the averages genuinely differ. Returns a list
    of delta dicts (empty on a flat/sparse window)."""
    metrics = metrics or _MONTH_DELTA_METRICS
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    cur_lo, prior_hi, prior_lo = (end - timedelta(days=29)), (end - timedelta(days=30)), (end - timedelta(days=59))

    def _half(lo, hi, key):
        vals = []
        for d, m in series.items():
            try:
                dd = datetime.strptime(d, "%Y-%m-%d").date()
            except Exception:
                continue
            if lo <= dd <= hi and m.get(key) is not None:
                vals.append(float(m[key]))
        return vals

    out = []
    for key, label, unit, higher_better in metrics:
        cur, prior = _half(cur_lo, end, key), _half(prior_lo, prior_hi, key)
        if len(cur) < min_days or len(prior) < min_days:
            continue
        a, b = sum(cur) / len(cur), sum(prior) / len(prior)
        delta = round(a - b, 2)
        if delta == 0:
            continue  # genuinely flat metric — no motion to surface
        out.append(
            {
                "metric": key,
                "label": label,
                "unit": unit,
                "this_month_avg": round(a, 2),
                "prior_month_avg": round(b, 2),
                "delta": delta,
                "pct": round((a - b) / b * 100, 1) if b else None,
                "direction": "improved" if ((delta > 0) == higher_better) else "declined",
                "n_this": len(cur),
                "n_prior": len(prior),
            }
        )
    return out


def diff_newly_unlocked(correlations, first_sig, end_date, *, window_days=30):
    """Update the first-seen ledger and return the correlations that FIRST crossed FDR
    significance within the trailing window. A pair is stamped on its first significant
    run and NEVER re-stamped — so a pair that drops out then re-crosses keeps its
    original date and is not re-announced. Returns (newly_unlocked_list, updated_first_sig)."""
    first_sig = dict(first_sig or {})
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    cutoff = end - timedelta(days=window_days)
    fresh = []
    for label, data in (correlations or {}).items():
        if not data.get("fdr_significant"):
            continue
        if label not in first_sig:
            first_sig[label] = end_date  # first time significant → stamp now
        try:
            seen = datetime.strptime(str(first_sig[label]), "%Y-%m-%d").date()
        except Exception:
            seen = end
        if seen >= cutoff:
            fresh.append(
                {
                    "label": label,
                    "metric_a": data.get("metric_a"),
                    "metric_b": data.get("metric_b"),
                    "r": data.get("pearson_r"),
                    "n": data.get("n_days"),
                    "direction": data.get("direction"),
                    "interpretation": data.get("interpretation"),
                    "first_seen": first_sig[label],
                }
            )
    return fresh, first_sig


def store_what_changed(week_key, deltas, newly_unlocked, first_sig, end_date, computed_at):
    """Write the SS-08 SNAPSHOT#current (the served record) + STATE#first_seen (the
    ledger) under SOURCE#what_changed. honest_null when nothing moved."""
    window_start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
    snap = {
        "pk": USER_PREFIX + "what_changed",
        "sk": "SNAPSHOT#current",
        "week": week_key,
        "window_start": window_start,
        "window_end": end_date,
        "deltas": _deep_dec(deltas),
        "newly_unlocked": _deep_dec(newly_unlocked),
        "honest_null": (not deltas and not newly_unlocked),
        "computed_at": computed_at,
    }
    try:
        from compute_metadata import tag_record

        snap = tag_record(snap, source_id="what_changed")
    except ImportError:
        pass
    table.put_item(Item=snap)
    # The first-seen ledger is a plain {label: date} string map — no Decimal needed.
    table.put_item(
        Item={
            "pk": USER_PREFIX + "what_changed",
            "sk": "STATE#first_seen",
            "first_sig": first_sig,
            "updated_at": computed_at,
        }
    )
    logger.info(
        "SS-08: stored what_changed for week %s (%d deltas, %d newly-unlocked, honest_null=%s)",
        week_key,
        len(deltas),
        len(newly_unlocked),
        snap["honest_null"],
    )


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

    logger.info("Computing correlations for week %s | window: %s → %s (%d days)", week_key, start_date, end_date, LOOKBACK_DAYS)

    # Idempotency — skip if already computed this week unless forced
    if not event.get("force"):
        try:
            existing = table.get_item(
                Key={
                    "pk": USER_PREFIX + "weekly_correlations",
                    "sk": "WEEK#" + week_key,
                }
            ).get("Item")
            if existing:
                stored_at = existing.get("computed_at", "")
                logger.info("Already computed for week %s at %s — skipping (pass force=true to recompute)", week_key, stored_at)
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

    if len(series) < experiment_gates.CORRELATION_MIN_N:
        logger.warning(
            "Insufficient data (%d days) — need at least %d for meaningful correlations",
            len(series),
            experiment_gates.CORRELATION_MIN_N,
        )
        return {
            "statusCode": 200,
            "body": f"Insufficient data: {len(series)} days (need ≥{experiment_gates.CORRELATION_MIN_N})",
            "week": week_key,
            "days_available": len(series),
        }

    # Compute correlations
    logger.info("Computing %d correlation pairs...", len(CORRELATION_PAIRS))
    correlations = compute_correlations(series)

    # Store correlations
    store_correlations(week_key, correlations, start_date, end_date, computed_at)

    # BS-TR1: Centenarian Decathlon Progress (non-fatal)
    try:
        logger.info("BS-TR1: Computing centenarian decathlon progress...")
        centenarian = _compute_centenarian_progress(series, end_date)
        store_centenarian_progress(week_key, centenarian, end_date, computed_at)
    except Exception as e:
        logger.warning("BS-TR1 failed (non-fatal): %s", e)

    # BS-TR2: Zone 2 Cardiac Efficiency Trend (non-fatal)
    try:
        logger.info("BS-TR2: Computing Zone 2 cardiac efficiency trend...")
        zone2_eff = _compute_zone2_efficiency(series, end_date)
        store_zone2_efficiency(week_key, zone2_eff, end_date, computed_at)
    except Exception as e:
        logger.warning("BS-TR2 failed (non-fatal): %s", e)

    # SS-08: Monthly "what changed" — cumulative deltas + newly-unlocked correlations (non-fatal).
    # Piggybacks the series + correlations already in hand; reads/writes the first-seen ledger.
    try:
        logger.info("SS-08: Computing monthly 'what changed'...")
        _wc = table.get_item(Key={"pk": USER_PREFIX + "what_changed", "sk": "STATE#first_seen"}).get("Item") or {}
        _first_sig = dict(_wc.get("first_sig") or {})
        _deltas = compute_month_deltas(series, end_date)
        _unlocked, _first_sig = diff_newly_unlocked(correlations, _first_sig, end_date)
        store_what_changed(week_key, _deltas, _unlocked, _first_sig, end_date, computed_at)
    except Exception as e:
        logger.warning("SS-08 failed (non-fatal): %s", e)

    elapsed = time.time() - t0
    significant = {k: v for k, v in correlations.items() if v.get("pearson_r") is not None and abs(v["pearson_r"]) >= 0.3}
    logger.info("Done in %.1fs — %d pairs computed, %d significant (|r|≥0.3)", elapsed, len(correlations), len(significant))

    return {
        "statusCode": 200,
        "body": f"Weekly correlations computed for {week_key}",
        "week": week_key,
        "start_date": start_date,
        "end_date": end_date,
        "days_analyzed": len(series),
        "pairs_computed": len(correlations),
        "significant": len(significant),
        "elapsed_seconds": round(elapsed, 1),
    }
