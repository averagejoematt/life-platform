"""
hypothesis_engine_lambda.py — IC-18: Cross-Domain Hypothesis Engine
v2.0.0 — #530/ADR-105: the math arrives — deterministic test specs, effect sizes,
pre-registration, calibration. (v1.2.0 was AI-4 + IC-19 D3B.)

Scientific method applied to personal health data — now with the method. Runs
weekly (Sunday 11 AM PT) after the Weekly Digest, surfacing non-obvious
cross-domain relationships the existing tools don't explicitly monitor.

The v2 contract (ADR-105 rule 3 — deterministic before narrative):
  - At CREATION the LLM must emit a machine-checkable `test_spec` (condition
    metric/op/threshold, outcome metric, direction, min effect, lag) alongside
    the prose. The spec is validated deterministically and FROZEN — that is the
    pre-registration. Hypotheses without a parseable spec are rejected.
  - At CHECK time the verdict is pure Python: split days into condition vs
    comparison arms per the frozen spec, compute the effect size + a
    moving-block-bootstrap 95% CI (stats_core), and decide supported /
    contradicted / inconclusive from the CI. No LLM sees the data.
  - Haiku only NARRATES resolutions (fail-soft to the deterministic evidence
    string) — the weekly per-hypothesis Haiku verdict calls are gone, so v2 is
    a net AI-cost reduction.
  - Every resolution (confirmed / refuted / expired-undecided) writes a row to
    the CALIBRATION ledger so "do 'high confidence' hypotheses confirm more
    often?" is answerable (consumed by the calibration scoreboard story).

Workflow:
  1. Pull 30 days of all-pillar data from DynamoDB (checks need the full window;
     generation sees the last 14 days)
  2. Load existing pending hypotheses; evaluate each frozen test_spec
     deterministically; resolve/advance statuses; write calibration rows
  3. Generate 3-5 new hypotheses (each with a frozen test_spec) if room exists
  4. Write results to DDB SOURCE#hypotheses partition

Hypothesis lifecycle:
  pending → confirming → confirmed          (supported + full window observed)
  pending/confirming → refuted              (CI excludes 0 in the WRONG direction)
  pending/confirming → archived (undecided) (window expired without a verdict)

DDB pattern:
  pk = USER#matthew#SOURCE#hypotheses    sk = HYPOTHESIS#<ISO-timestamp>
  pk = USER#matthew#SOURCE#calibration   sk = CALIB#<date>#<hypothesis_id>

Downstream consumers:
  - Digest Lambdas inject confirming/refuting observations via IC-16 progressive context
  - MCP tools: get_hypotheses, update_hypothesis_outcome
  - /api/hypotheses (evidence page "What the machine suspects" — shows the
    pre-registered spec + measured effect)

Cost: ~$0.05/week (one generation call + DDB reads/writes; check path is free
except a small narration call when something resolves)
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import stats_core  # shared layer (#529): effect sizes + block-bootstrap CIs for the deterministic verdict
from constants import EXPERIMENT_BASELINE_WEIGHT_LBS  # ADR-058
from phase_filter import with_phase_filter  # ADR-058: default-deny pilot data

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("hypothesis-engine")
except ImportError:
    logger = logging.getLogger("hypothesis-engine")
    logger.setLevel(logging.INFO)

# AI-3: Output validator — validates AI text before storage/delivery
try:
    from ai_output_validator import AIOutputType, validate_ai_output

    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
S3_BUCKET = os.environ["S3_BUCKET"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# AI model constants — read from env so model can be updated without redeployment
AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

HYPOTHESES_PK = f"USER#{USER_ID}#SOURCE#hypotheses"
CALIBRATION_PK = f"USER#{USER_ID}#SOURCE#calibration"  # #530: resolution ledger (cross_phase)
MAX_NEW_HYPOTHESES = 5
MAX_PENDING_HYPOTHESES = 20  # don't accumulate stale hypotheses

# AI-4: Validation thresholds
MIN_DATA_DAYS = 10  # require >= 10 days with sufficient metrics before generating
MIN_METRICS_PER_DAY = 5  # a day needs >= 5 non-null metrics to count as "complete"
HARD_EXPIRY_DAYS = 30  # archive any hypothesis older than 30 days regardless of status
MIN_SAMPLE_DAYS_FOR_CHECK = 7  # require >= 7 data days since creation before evaluating
LOOKBACK_DAYS = 30  # #530: checks evaluate the full monitoring window (generation sees the last GENERATION_DAYS)
GENERATION_DAYS = 14
REQUIRED_HYPOTHESIS_FIELDS = {
    "hypothesis_id",
    "hypothesis",
    "domains",
    "evidence",
    "confirmation_criteria",
    "monitoring_window_days",
    "confidence",
    "actionable_if_confirmed",
    "test_spec",  # #530: no pre-registered spec, no hypothesis
}
VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}
# Pattern: confirmation criteria should contain at least one number (threshold/percentage)
NUMERIC_PATTERN = re.compile(r"\d+\.?\d*\s*(%|days?|hours?|minutes?|ms|points?|g|kg|lbs?|cal|kcal|bpm|mg)")

# ── #530: the deterministic test-spec contract ────────────────────────────────
# The metric vocabulary is exactly what build_data_narrative() emits — a spec can
# only reference values the check path can actually compute. Keep the two in sync.
SPEC_METRICS = frozenset(
    {
        "recovery",
        "hrv",
        "rhr",
        "sleep_score",
        "sleep_efficiency",
        "deep_sleep_hrs",
        "rem_hrs",
        "total_sleep_hrs",
        "stress",
        "body_battery",
        "steps_garmin",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
        "weight_lbs",
        "steps",
        "active_cal",
        "mindful_min",
        "glucose_avg",
        "walking_speed",
        "workout",
        "training_load",
        "zone2_min",
        "mood",
        "energy",
        "journal_stress",
        "sleep_onset_min",
        "bed_temp_f",
    }
)
VALID_SPEC_OPS = frozenset({">=", "<=", "median_split"})
VALID_SPEC_DIRECTIONS = frozenset({"higher", "lower"})
MIN_DAYS_PER_ARM = 5  # each arm needs 5+ days (also stats_core's bootstrap floor)
MAX_LAG_DAYS = 3


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def d2f(obj):
    """Convert DynamoDB Decimals to float/int."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [d2f(v) for v in obj]
    return obj


def safe_float(rec, field, default=None):
    v = rec.get(field)
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def query_range(source, start_date, end_date):
    """Query DynamoDB for a source's data in a date range."""
    from boto3.dynamodb.conditions import Key

    pk = f"USER#{USER_ID}#SOURCE#{source}"
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}"),
                }
            )
        )
        return d2f(resp.get("Items", []))
    except Exception as e:
        logger.warning(f"query_range({source}) failed: {e}")
        return []


def fetch_profile():
    from intelligence_common import fetch_profile as _shared_fetch_profile

    return _shared_fetch_profile(table, USER_ID)


def gather_data(days=LOOKBACK_DAYS):
    """Fetch multi-source data. #530: 30 days — deterministic checks evaluate the
    hypothesis's full monitoring window; generation only sees the last GENERATION_DAYS."""
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    sources = ["whoop", "garmin", "macrofactor", "apple_health", "withings", "strava", "notion", "habitify", "eightsleep"]

    data = {}
    for source in sources:
        try:
            items = query_range(source, start_date, end_date)
            if items:
                data[source] = items
                logger.info(f"Loaded {len(items)} {source} records")
        except Exception as e:
            logger.warning(f"Failed to load {source}: {e}")

    return data if data else None


def load_existing_hypotheses(status_filter=None):
    """Load existing hypotheses from DynamoDB."""
    from boto3.dynamodb.conditions import Key

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
                    "ScanIndexForward": False,
                }
            )
        )
        items = d2f(resp.get("Items", []))
        if status_filter:
            items = [h for h in items if h.get("status") == status_filter]
        return items
    except Exception as e:
        logger.error(f"Failed to load hypotheses: {e}")
        return []


def store_hypothesis(hypothesis: dict):
    """Write a new hypothesis to DynamoDB."""
    now = datetime.now(timezone.utc)
    sk = f"HYPOTHESIS#{now.isoformat()}"

    item = {
        "pk": HYPOTHESES_PK,
        "sk": sk,
        "status": "pending",
        "created_at": now.isoformat(),
        # #530: the spec is FROZEN as of this write — checks read it, never revise it
        "pre_registered_at": now.isoformat(),
        "engine_version": 2,
        "check_count": 0,
        **{k: v for k, v in hypothesis.items() if v is not None},
    }

    # Convert floats to Decimal for DynamoDB
    def to_decimal(obj):
        if isinstance(obj, float):
            return Decimal(str(obj))
        if isinstance(obj, dict):
            return {k: to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [to_decimal(v) for v in obj]
        return obj

    # V2 P2.6 (2026-05-19): tag with run_id + computed_at for double-write detection
    try:
        from compute_metadata import tag_record

        item = tag_record(item, source_id="hypotheses")
    except ImportError:
        pass
    table.put_item(Item=to_decimal(item))
    logger.info(f"Stored hypothesis: {hypothesis.get('hypothesis_id', sk)}")


# #530: the deterministic-check stat fields persisted onto the HYPOTHESIS# record
# each check (read by MCP get_hypotheses, /api/hypotheses, and the digests).
_CHECK_STAT_FIELDS = (
    "effect_size",
    "ci95_low",
    "ci95_high",
    "cohens_d",
    "n_condition",
    "n_comparison",
    "days_observed",
    "mean_condition",
    "mean_comparison",
)


def update_hypothesis_status(sk: str, status: str, evidence_note: str = "", stats: dict = None):
    """Update hypothesis status, increment check_count, and (#530) persist the
    deterministic test's effect size / CI / arm counts + verdict."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        update_expr = "SET #s = :s, last_checked = :now, check_count = if_not_exists(check_count, :zero) + :one"
        expr_names = {"#s": "status"}
        expr_vals = {
            ":s": status,
            ":now": now,
            ":zero": Decimal("0"),
            ":one": Decimal("1"),
        }

        if evidence_note:
            update_expr += ", last_evidence = :ev"
            expr_vals[":ev"] = evidence_note

        if stats:
            update_expr += ", deterministic_verdict = :dv"
            expr_vals[":dv"] = stats.get("verdict", "inconclusive")
            for field in _CHECK_STAT_FIELDS:
                val = stats.get(field)
                if val is None:
                    continue
                update_expr += f", {field} = :{field}"
                expr_vals[f":{field}"] = Decimal(str(val)) if isinstance(val, (int, float)) else val

        table.update_item(
            Key={"pk": HYPOTHESES_PK, "sk": sk},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_vals,
        )
        logger.info(f"Updated hypothesis {sk[:40]}: {status}")
    except Exception as e:
        logger.error(f"Failed to update hypothesis {sk}: {e}")


def build_data_narrative(data):
    """Build day-by-day narrative rows for hypothesis evaluation."""
    if not data:
        return []

    # Find date range
    all_dates = set()
    for source, items in data.items():
        for item in items:
            d = item.get("date") or item.get("sk", "")[-10:]
            if d and len(d) == 10:
                all_dates.add(d)

    rows = []
    for date in sorted(all_dates):
        row = {"date": date}

        # Whoop
        whoop = next((i for i in data.get("whoop", []) if i.get("date") == date), {})
        if whoop:
            row["recovery"] = safe_float(whoop, "recovery_score")
            row["hrv"] = safe_float(whoop, "hrv")
            row["rhr"] = safe_float(whoop, "resting_heart_rate")
            row["sleep_score"] = safe_float(whoop, "sleep_quality_score")
            row["sleep_efficiency"] = safe_float(whoop, "sleep_efficiency_percentage")
            row["deep_sleep_hrs"] = safe_float(whoop, "slow_wave_sleep_hours")
            row["rem_hrs"] = safe_float(whoop, "rem_sleep_hours")
            row["total_sleep_hrs"] = safe_float(whoop, "sleep_duration_hours")

        # Garmin
        garmin = next((i for i in data.get("garmin", []) if i.get("date") == date), {})
        if garmin:
            row["stress"] = safe_float(garmin, "average_stress_level")
            row["body_battery"] = safe_float(garmin, "body_battery_high")
            row["steps_garmin"] = safe_float(garmin, "total_steps")

        # MacroFactor
        mf = next((i for i in data.get("macrofactor", []) if i.get("date") == date), {})
        if mf:
            row["calories"] = safe_float(mf, "total_calories_kcal")
            row["protein_g"] = safe_float(mf, "total_protein_g")
            row["carbs_g"] = safe_float(mf, "total_carbs_g")
            row["fat_g"] = safe_float(mf, "total_fat_g")
            # (#484) removed: `weight_lbs = tdee_kcal` — a never-populated field written
            # into the weight column; Withings weight is set authoritatively just below.

        # Withings (weight)
        wi = next((i for i in data.get("withings", []) if i.get("date") == date), {})
        if wi:
            row["weight_lbs"] = safe_float(wi, "weight_lbs")

        # Apple Health
        ah = next((i for i in data.get("apple_health", []) if i.get("date") == date), {})
        if ah:
            row["steps"] = safe_float(ah, "steps")
            row["active_cal"] = safe_float(ah, "active_calories")
            row["mindful_min"] = safe_float(ah, "mindful_minutes")
            row["glucose_avg"] = safe_float(ah, "blood_glucose_avg")
            row["walking_speed"] = safe_float(ah, "walking_speed_mph")

        # Strava
        st = next((i for i in data.get("strava", []) if i.get("date") == date), {})
        if st:
            row["workout"] = bool(safe_float(st, "activity_count", 0))
            row["training_load"] = safe_float(st, "total_kilojoules")
            row["zone2_min"] = safe_float(st, "zone2_minutes")

        # Notion journal
        nj = next((i for i in data.get("notion", []) if i.get("date") == date), {})
        if nj:
            row["mood"] = safe_float(nj, "enriched_mood")
            row["energy"] = safe_float(nj, "enriched_energy")
            row["journal_stress"] = safe_float(nj, "enriched_stress")
            row["social"] = nj.get("enriched_social_quality")

        # Eight Sleep
        es = next((i for i in data.get("eightsleep", []) if i.get("date") == date), {})
        if es:
            row["sleep_onset_min"] = safe_float(es, "time_to_sleep_min")
            row["bed_temp_f"] = safe_float(es, "bed_temp_f")

        # Filter None values
        row = {k: v for k, v in row.items() if v is not None}
        if len(row) > 1:  # more than just date
            rows.append(row)

    return rows


def check_data_completeness(daily_rows):
    """AI-4: Check if we have enough complete data to generate reliable hypotheses.

    Returns (is_sufficient, complete_days, total_days, message).
    """
    total = len(daily_rows)
    complete = sum(1 for r in daily_rows if len(r) >= MIN_METRICS_PER_DAY + 1)  # +1 for date key
    msg = f"{complete}/{total} complete days (need {MIN_DATA_DAYS} with {MIN_METRICS_PER_DAY}+ metrics)"
    return complete >= MIN_DATA_DAYS, complete, total, msg


def validate_hypothesis(hyp, existing_texts=None):
    """AI-4: Validate a generated hypothesis against quality requirements.

    Returns (is_valid, list_of_issues).
    """
    issues = []

    # Required fields
    missing = REQUIRED_HYPOTHESIS_FIELDS - set(hyp.keys())
    if missing:
        issues.append(f"Missing fields: {missing}")

    # Confidence level
    if hyp.get("confidence") not in VALID_CONFIDENCE_LEVELS:
        issues.append(f"Invalid confidence: {hyp.get('confidence')}")

    # Cross-domain requirement
    domains = hyp.get("domains", [])
    if not isinstance(domains, list) or len(domains) < 2:
        issues.append("Must have 2+ domains")

    # Numeric threshold in confirmation criteria
    criteria = hyp.get("confirmation_criteria", "")
    if not NUMERIC_PATTERN.search(criteria):
        issues.append("confirmation_criteria must contain numeric threshold with units")

    # #530: the machine-checkable test spec IS the pre-registration — no spec, no hypothesis
    spec_ok, spec_issues = validate_test_spec(hyp.get("test_spec"))
    if not spec_ok:
        issues.append(f"test_spec invalid: {'; '.join(spec_issues)}")

    # Monitoring window
    window = hyp.get("monitoring_window_days", 0)
    try:
        window = int(window)
        if not (7 <= window <= 30):
            issues.append(f"monitoring_window_days must be 7-30, got {window}")
    except (ValueError, TypeError):
        issues.append(f"monitoring_window_days must be numeric, got {window}")

    # Duplicate check
    if existing_texts:
        hypothesis_text = hyp.get("hypothesis", "")[:100].lower()
        for existing in existing_texts:
            if existing and len(hypothesis_text) > 20:
                # Simple overlap check: if >50% of words match, likely duplicate
                h_words = set(hypothesis_text.split())
                e_words = set(existing.lower().split())
                if h_words and len(h_words & e_words) / len(h_words) > 0.5:
                    issues.append(f"Too similar to existing hypothesis: {existing[:60]}")
                    break

    return len(issues) == 0, issues


def enforce_hard_expiry(all_hypotheses):
    """AI-4: Archive any hypothesis older than HARD_EXPIRY_DAYS regardless of status.

    Returns list of (sk, new_status, reason) tuples for hypotheses to archive.
    """
    updates = []
    now = datetime.now(timezone.utc).date()

    for hyp in all_hypotheses:
        if hyp.get("status") in ("archived", "confirmed", "refuted"):
            continue

        created_at = hyp.get("created_at", "")
        try:
            created_date = datetime.fromisoformat(created_at).date()
            days_old = (now - created_date).days
        except Exception:
            continue

        if days_old > HARD_EXPIRY_DAYS:
            sk = hyp.get("sk", "")
            if sk:
                updates.append((sk, "archived", f"Hard expiry: {days_old} days old (limit {HARD_EXPIRY_DAYS})"))

    return updates


# (IC-19 D3B's load_active_experiments was deleted in v2 — it existed only to
# feed extra context into the Haiku check prompt, and the check is now
# deterministic. The experiment cross-reference lives on in tools_challenges'
# hypothesis_graduate flow.)


def validate_test_spec(spec):
    """#530: Validate a machine-checkable test spec. Returns (is_valid, issues).

    A valid spec is the pre-registration contract: condition metric/op/threshold,
    outcome metric, expected direction, optional minimum effect (outcome units),
    optional lag. Both metrics must come from the build_data_narrative vocabulary
    or the check path could never evaluate it.
    """
    issues = []
    if not isinstance(spec, dict):
        return False, ["test_spec must be an object"]

    cond_m = spec.get("condition_metric")
    out_m = spec.get("outcome_metric")
    if cond_m not in SPEC_METRICS:
        issues.append(f"condition_metric '{cond_m}' not in the measurable vocabulary")
    if out_m not in SPEC_METRICS:
        issues.append(f"outcome_metric '{out_m}' not in the measurable vocabulary")
    if cond_m and cond_m == out_m:
        issues.append("condition_metric and outcome_metric must differ")

    op = spec.get("condition_op")
    if op not in VALID_SPEC_OPS:
        issues.append(f"condition_op must be one of {sorted(VALID_SPEC_OPS)}, got '{op}'")
    if op in (">=", "<="):
        try:
            float(spec.get("condition_threshold"))
        except (TypeError, ValueError):
            issues.append(f"condition_threshold must be numeric for op '{op}'")

    if spec.get("direction") not in VALID_SPEC_DIRECTIONS:
        issues.append(f"direction must be one of {sorted(VALID_SPEC_DIRECTIONS)}")

    min_effect = spec.get("min_effect", 0)
    try:
        if float(min_effect) < 0:
            issues.append("min_effect must be >= 0")
    except (TypeError, ValueError):
        issues.append(f"min_effect must be numeric, got {min_effect!r}")

    lag = spec.get("lag_days", 0)
    try:
        if not (0 <= int(lag) <= MAX_LAG_DAYS):
            issues.append(f"lag_days must be 0-{MAX_LAG_DAYS}, got {lag}")
    except (TypeError, ValueError):
        issues.append(f"lag_days must be an integer, got {lag!r}")

    return len(issues) == 0, issues


def evaluate_test_spec(spec, daily_rows, since_date):
    """#530: THE deterministic hypothesis test (ADR-105 rule 3) — pure Python, no LLM.

    Splits condition-days from comparison-days per the frozen spec (threshold or
    median split), pairs each condition day's outcome at the spec's lag, then
    computes the effect size (mean difference, outcome units) with a moving-block
    bootstrap 95% CI and Cohen's d via stats_core.

    Verdict:
      supported     — CI excludes 0 in the predicted direction AND |effect| >= min_effect
      contradicted  — CI excludes 0 in the OPPOSITE direction
      inconclusive  — arms too thin or CI straddles 0

    Returns a stats dict (always includes verdict + arm counts; effect/CI fields
    are None when uncomputable).
    """
    lag = int(spec.get("lag_days", 0) or 0)
    op = spec.get("condition_op", "median_split")
    direction = spec.get("direction", "higher")
    min_effect = float(spec.get("min_effect", 0) or 0)

    by_date = {r["date"]: r for r in daily_rows if r.get("date")}
    pairs = []  # (condition_value, outcome_value) per qualifying day
    for d in sorted(by_date):
        if d < since_date:
            continue
        cv = by_date[d].get(spec.get("condition_metric"))
        if cv is None:
            continue
        if lag:
            try:
                od = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag)).strftime("%Y-%m-%d")
            except ValueError:
                continue
        else:
            od = d
        ov = by_date.get(od, {}).get(spec.get("outcome_metric"))
        if ov is None:
            continue
        try:
            pairs.append((float(cv), float(ov)))
        except (TypeError, ValueError):
            continue

    result = {
        "verdict": "inconclusive",
        "days_observed": len(pairs),
        "n_condition": 0,
        "n_comparison": 0,
        "mean_condition": None,
        "mean_comparison": None,
        "effect_size": None,
        "ci95_low": None,
        "ci95_high": None,
        "cohens_d": None,
    }
    if len(pairs) < 2 * MIN_DAYS_PER_ARM:
        return result

    cond_values = [cv for cv, _ in pairs]
    if op == "median_split":
        threshold = sorted(cond_values)[len(cond_values) // 2]
        in_condition = [cv > threshold for cv, _ in pairs]
    elif op == ">=":
        threshold = float(spec.get("condition_threshold"))
        in_condition = [cv >= threshold for cv, _ in pairs]
    else:  # "<="
        threshold = float(spec.get("condition_threshold"))
        in_condition = [cv <= threshold for cv, _ in pairs]

    condition_arm = [ov for (_, ov), hit in zip(pairs, in_condition) if hit]
    comparison_arm = [ov for (_, ov), hit in zip(pairs, in_condition) if not hit]
    result["n_condition"] = len(condition_arm)
    result["n_comparison"] = len(comparison_arm)
    if len(condition_arm) < MIN_DAYS_PER_ARM or len(comparison_arm) < MIN_DAYS_PER_ARM:
        return result

    mean_c = sum(condition_arm) / len(condition_arm)
    mean_o = sum(comparison_arm) / len(comparison_arm)
    effect = mean_c - mean_o
    ci = stats_core.bootstrap_mean_diff_ci(comparison_arm, condition_arm)
    d_val = stats_core.cohens_d(comparison_arm, condition_arm)
    result.update(
        {
            "mean_condition": round(mean_c, 3),
            "mean_comparison": round(mean_o, 3),
            "effect_size": round(effect, 3),
            "cohens_d": round(d_val, 3) if d_val is not None else None,
        }
    )
    if ci is None:
        return result
    lo, hi = ci
    result["ci95_low"] = round(lo, 3)
    result["ci95_high"] = round(hi, 3)

    predicted_positive = direction == "higher"
    excludes_zero_predicted = (lo > 0) if predicted_positive else (hi < 0)
    excludes_zero_opposite = (hi < 0) if predicted_positive else (lo > 0)
    if excludes_zero_predicted and abs(effect) >= min_effect:
        result["verdict"] = "supported"
    elif excludes_zero_opposite:
        result["verdict"] = "contradicted"
    return result


def deterministic_evidence(spec, stats):
    """Human-readable evidence sentence built ONLY from the computed stats —
    this is what gets stored (and what Haiku may narrate, never replace)."""
    cond_m = spec.get("condition_metric", "?")
    out_m = spec.get("outcome_metric", "?")
    op = spec.get("condition_op", "median_split")
    cond_desc = f"{cond_m} {op} {spec.get('condition_threshold')}" if op in (">=", "<=") else f"high-{cond_m} (above median)"
    lag = int(spec.get("lag_days", 0) or 0)
    lag_note = f" {lag}d later" if lag else ""
    if stats.get("effect_size") is None:
        return (
            f"Deterministic test inconclusive: {stats.get('n_condition', 0)} {cond_desc} days vs "
            f"{stats.get('n_comparison', 0)} comparison days over {stats.get('days_observed', 0)} observed "
            f"(need {MIN_DAYS_PER_ARM}+ per arm)."
        )
    line = (
        f"Deterministic test: {out_m}{lag_note} averaged {stats['mean_condition']} on {stats['n_condition']} "
        f"{cond_desc} days vs {stats['mean_comparison']} on {stats['n_comparison']} comparison days — "
        f"effect {stats['effect_size']:+g}"
    )
    if stats.get("ci95_low") is not None:
        line += f" (95% CI [{stats['ci95_low']:g}, {stats['ci95_high']:g}]"
        if stats.get("cohens_d") is not None:
            line += f", d={stats['cohens_d']:g}"
        line += ")"
    return line + f" → {stats['verdict']}."


def build_calibration_item(hyp, stats, outcome, resolved_at):
    """#530: One calibration-ledger row per resolution — the raw material for
    'do high-confidence hypotheses confirm more often?'. Pure builder (tested);
    the writer is a thin put_item. CROSS_PHASE: the engine's long-run scoreboard
    survives experiment resets (see phase_taxonomy)."""
    hyp_id = hyp.get("hypothesis_id") or hyp.get("sk", "").replace("HYPOTHESIS#", "")
    return {
        "pk": CALIBRATION_PK,
        "sk": f"CALIB#{resolved_at[:10]}#{hyp_id}",
        "record_type": "hypothesis_resolution",
        "hypothesis_id": hyp_id,
        "hypothesis": hyp.get("hypothesis", ""),
        "stated_confidence": hyp.get("confidence", "low"),
        "outcome": outcome,  # confirmed | refuted | expired_undecided
        "predicted_direction": (hyp.get("test_spec") or {}).get("direction"),
        "effect_size": stats.get("effect_size"),
        "ci95_low": stats.get("ci95_low"),
        "ci95_high": stats.get("ci95_high"),
        "cohens_d": stats.get("cohens_d"),
        "n_condition": stats.get("n_condition"),
        "n_comparison": stats.get("n_comparison"),
        "days_observed": stats.get("days_observed"),
        "test_spec": hyp.get("test_spec"),
        "pre_registered_at": hyp.get("created_at", ""),
        "resolved_at": resolved_at,
    }


def write_calibration_row(hyp, stats, outcome):
    """Persist one resolution to the calibration ledger (fail-soft)."""
    try:
        item = build_calibration_item(hyp, stats, outcome, datetime.now(timezone.utc).isoformat())
        item = {k: v for k, v in item.items() if v is not None}

        def to_decimal(obj):
            if isinstance(obj, float):
                return Decimal(str(obj))
            if isinstance(obj, dict):
                return {k: to_decimal(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [to_decimal(v) for v in obj]
            return obj

        try:
            from compute_metadata import tag_record

            item = tag_record(item, source_id="calibration")
        except ImportError:
            pass
        table.put_item(Item=to_decimal(item))
        logger.info(f"[#530] Calibration row written: {item['sk']} outcome={outcome}")
    except Exception as e:
        logger.warning(f"write_calibration_row failed (non-fatal): {e}")


def narrate_resolution(hyp, det_evidence, new_status):
    """#530: Haiku narrates a resolution the deterministic test already decided
    (ADR-104 pattern). Fail-soft: any error returns '' and the stored evidence
    stays the deterministic sentence. Only called on resolutions, so v2's check
    path costs ~nothing in normal weeks."""
    prompt = (
        f"A pre-registered health hypothesis just resolved as {new_status.upper()}.\n"
        f"Hypothesis: {hyp.get('hypothesis', '')}\n"
        f"Deterministic result (already computed — the decision is made): {det_evidence}\n\n"
        "Write ONE plain-language sentence explaining what happened for a general reader. "
        "Use ONLY numbers that appear in the result above; do not invent, extrapolate, or add any. "
        "Respond with the sentence only."
    )
    payload = json.dumps({"model": AI_MODEL_HAIKU, "max_tokens": 150, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01"},
        method="POST",
    )
    try:
        from retry_utils import call_anthropic_raw

        resp = call_anthropic_raw(req)
        text = resp["content"][0]["text"].strip()
        if _HAS_AI_VALIDATOR and text:
            val = validate_ai_output(text, AIOutputType.GENERIC)
            if val.blocked:
                logger.warning("[#530] narration blocked: %s", val.block_reason)
                return ""
        return text
    except Exception as e:
        logger.info(f"[#530] narration skipped (non-fatal): {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# HYPOTHESIS SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

HYPOTHESIS_SYSTEM_PROMPT = """You are a data scientist analyzing Matthew's personal health data to generate cross-domain hypotheses.

Your role: identify NON-OBVIOUS correlations between health domains that the existing monitoring tools don't explicitly track.

EXISTING TOOLS ALREADY MONITOR:
- HRV vs sleep quality (direct)
- Calories vs weight trend (direct)
- Exercise load vs recovery (direct)
- Habit completion rate (direct)

WHAT YOU'RE LOOKING FOR — the interesting intersections:
- Lag effects (nutrition today -> sleep 2 nights later)
- Compound interactions (two mediocre pillars -> third pillar collapses)
- Asymmetric patterns (high X improves Y, but low X doesn't hurt Y)
- Cyclical patterns (something that happens on specific day-of-week)
- Threshold effects (below X, Y seems fine; above X, Y degrades sharply)
- Surprising non-correlations (two things that SHOULD correlate but don't)

CRITERIA FOR GOOD HYPOTHESES:
1. Cross-domain (involves at least 2 different pillars/sources)
2. Specific and falsifiable (has clear confirmation criteria WITH NUMERIC THRESHOLDS)
3. Actionable if confirmed (Matthew could change something)
4. Non-obvious (not something the Board would already coach)
5. Grounded in the data (point to specific patterns you observed, cite values)

STRICT REQUIREMENTS (hypotheses that fail these are rejected):
- confirmation_criteria MUST contain at least one specific number with units (e.g., "10% improvement in deep sleep", "HRV increases by 5+ points", "30 minutes more sleep")
- domains MUST have 2+ entries (cross-domain is mandatory)
- confidence must be "low", "medium", or "high" based on how many data points support it
- monitoring_window_days must be 7-30 (not shorter, not longer)
- evidence must cite specific dates or values from the data provided
- test_spec is MANDATORY and is the PRE-REGISTERED deterministic test: the platform will
  split days into condition vs comparison arms per this exact spec, compute the effect size
  with a bootstrap confidence interval, and confirm/refute WITHOUT any further AI judgment.
  The spec is FROZEN at creation — it cannot be revised later. Both metrics MUST come from
  the metric vocabulary in the user message (the exact keys of the data rows). Pick the
  test you would stake the hypothesis on.

FRAMING RULE — NEGATIVE PSYCHOLOGICAL VARIABLES (Conti):
Hypotheses about stress, anxiety, low mood, emotional depletion, or other negative psychological
states MUST be framed as intervention opportunities, NOT as baseline characterisations.
BAD:  "High stress correlates with poor sleep efficiency"
GOOD: "Reducing perceived stress on high-workload days may improve sleep efficiency by ~X%"
The hypothesis sentence should describe what changing the variable could produce, not just that
two things move together. This applies to ANY variable where the desirable direction is reduction.

OUTPUT ONLY valid JSON. No preamble, no markdown, no backticks."""


def fetch_journal_candidates(limit=5):
    """#506: testable journal-derived candidates (HYPO_CANDIDATE# rows written by
    the journal analyzer) — cause/effect already mapped into SPEC_METRICS, verbatim
    quotes as provenance. Fail-soft: no candidates, no block."""
    try:
        from boto3.dynamodb.conditions import Key

        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#journal_analysis") & Key("sk").begins_with("HYPO_CANDIDATE#"),
        )
        rows = [d2f(i) for i in resp.get("Items", [])]
        testable = [r for r in rows if r.get("status") == "testable"]
        testable.sort(key=lambda r: (-(r.get("mentions") or 0), r.get("slug", "")))
        return testable[:limit]
    except Exception as e:
        logger.warning(f"[#506] journal candidates unavailable (non-blocking): {e}")
        return []


def format_journal_candidates(candidates):
    """The prompt block for journal-derived seeds. Empty string when none."""
    if not candidates:
        return ""
    lines = []
    for c in candidates:
        quote = ""
        quotes = c.get("quotes") or []
        if quotes:
            quote = f" — journal quote ({quotes[0].get('date', '?')}): \"{quotes[0].get('quote', '')[:160]}\""
        lines.append(
            f"- \"{c.get('cause', '?')}\" -> \"{c.get('effect', '?')}\" "
            f"(metric mapping: {c.get('cause_metric')} -> {c.get('effect_metric')}; "
            f"mentioned {int(c.get('mentions') or 1)}x{quote})"
        )
    return (
        "\n\nJOURNAL-DERIVED CANDIDATES (#506 — Matthew's own stated cause->effect hints, quotes are verbatim provenance).\n"
        "Prefer formalizing one of these into a hypothesis when the data supports it, using the given metric mapping in test_spec:\n"
        + "\n".join(lines)
    )


def generate_hypotheses(daily_rows, existing_hypotheses, profile=None, journal_candidates=None):
    """Run Claude to generate new cross-domain hypotheses from 14 days of data."""
    p = profile or {}
    start_w = p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS)
    goal_w = p.get("goal_weight_lbs", 185)
    total_loss = round(start_w - goal_w)
    cal_target = p.get("calorie_target", 1800)
    pro_target = p.get("protein_target_g", 190)

    existing_texts = [h.get("hypothesis", "")[:100] for h in existing_hypotheses]
    existing_block = ""
    if existing_texts:
        existing_block = "\n\nEXISTING HYPOTHESES (do NOT duplicate these):\n" + "\n".join(f"- {t}" for t in existing_texts)
    candidates_block = format_journal_candidates(journal_candidates or [])

    user_message = f"""Here is {len(daily_rows)} days of Matthew's health data:

{json.dumps(daily_rows, indent=2)}

Context:
- 36-year-old male, {total_loss} lb weight loss transformation (started {start_w} lbs, goal {goal_w} lbs)
- Calorie target: {cal_target} cal/day, protein target: {pro_target}g/day
- 16:8 intermittent fasting (eating window ~11am-7pm)
- Primary training: walking + strength training, building Zone 2 base
- Data sources: Whoop (HRV/recovery), Eight Sleep (bed temp), Strava (activities), MacroFactor (nutrition), Habitify (habits), Apple Health (steps/glucose/gait), Notion journal (mood/stress/energy)
{existing_block}{candidates_block}

Generate {MAX_NEW_HYPOTHESES} cross-domain hypotheses. Each should be:
- A non-obvious relationship between 2+ domains
- Grounded in a specific pattern you can see in this data
- Falsifiable with 2-4 weeks of continued observation

METRIC VOCABULARY for test_spec (the ONLY valid condition_metric / outcome_metric values):
{", ".join(sorted(SPEC_METRICS))}

Return ONLY this JSON structure:
{{
  "hypotheses": [
    {{
      "hypothesis_id": "hyp_<short_slug>",
      "hypothesis": "One clear sentence stating the relationship",
      "domains": ["domain1", "domain2"],
      "evidence": "What you saw in this data that suggested it (2-3 sentences, CITE SPECIFIC DATES AND VALUES)",
      "confirmation_criteria": "What would confirm this over 2-4 weeks — MUST include specific numeric thresholds (e.g., 'deep sleep % increases by 5+ points on days following protein >150g')",
      "test_spec": {{
        "condition_metric": "<metric from the vocabulary — the day-splitter>",
        "condition_op": ">=|<=|median_split",
        "condition_threshold": 150,
        "outcome_metric": "<different metric from the vocabulary — what should move>",
        "direction": "higher|lower",
        "min_effect": 0.5,
        "lag_days": 0
      }},
      "effect_size_observed": "The magnitude of the pattern you observed (e.g., '12% higher deep sleep on high-protein days')",
      "monitoring_window_days": 21,
      "confidence": "low|medium|high",
      "confidence_reason": "Why this confidence level — how many data points support it",
      "actionable_if_confirmed": "What Matthew could change if this is confirmed (1 sentence)"
    }}
  ]
}}

test_spec field notes:
- condition_op "median_split" needs no condition_threshold (days above the observed median form the condition arm)
- direction is the expected move of outcome_metric ON condition days vs comparison days
- min_effect is in outcome_metric's own units (use 0 if any direction-consistent effect counts)
- lag_days 0-3: outcome measured this many days AFTER the condition day"""

    payload = json.dumps(
        {
            "model": AI_MODEL,
            # 2026-05-03: bumped 2000 → 4000 — hypothesis JSON with multiple
            # patterns + confidence reasons was hitting truncation, then 400 on
            # retry. Sonnet 4.x supports 8192 in standard mode; 4000 is safe.
            "max_tokens": 4000,
            "system": [{"type": "text", "text": HYPOTHESIS_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_message}],
        }
    ).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        },
        method="POST",
    )

    # ADR-062 (2026-05-27): route through retry_utils.call_anthropic_raw (Bedrock).
    try:
        from retry_utils import call_anthropic_raw

        resp = call_anthropic_raw(req)
        raw = resp["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        # AI-3: Validate raw JSON text before parsing
        if _HAS_AI_VALIDATOR:
            val_result = validate_ai_output(raw, AIOutputType.GENERIC)
            if val_result.blocked:
                logger.error("[AI-3] generate_hypotheses blocked: %s", val_result.block_reason)
                return None
            if val_result.warnings:
                logger.warning("[AI-3] generate_hypotheses warnings: %s", val_result.warnings)
        return json.loads(raw.strip())
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Hypothesis parse error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# HYPOTHESIS CHECKING — evaluate pending hypotheses against new data
# ══════════════════════════════════════════════════════════════════════════════


def check_pending_hypotheses(pending_hypotheses, daily_rows):
    """#530: Evaluate each pending hypothesis DETERMINISTICALLY against its frozen
    test_spec (ADR-105 rule 3). The LLM never sees the data and never decides.

    Status transitions (all from the deterministic verdict):
      contradicted                          → refuted (resolution)
      supported + full window observed      → confirmed (resolution)
      supported (window still open)         → confirming
      inconclusive + window expired         → archived / expired_undecided (resolution)
      inconclusive (window still open)      → status unchanged, stats recorded

    v1 legacy hypotheses (no test_spec) are never LLM-checked anymore; they age
    out via the 30-day hard expiry (self-draining — the engine runs weekly).

    Returns list of (hyp, new_status, evidence_note, stats, resolution_outcome)
    tuples; resolution_outcome is None unless this check resolves the hypothesis.
    """
    if not pending_hypotheses or not daily_rows:
        return []

    updates = []
    now = datetime.now(timezone.utc).date()

    for hyp in pending_hypotheses:
        sk = hyp.get("sk", "")
        created_at = hyp.get("created_at", "")
        monitoring_window = hyp.get("monitoring_window_days", 21)

        if not sk or not hyp.get("hypothesis"):
            continue

        spec = hyp.get("test_spec")
        if not spec:
            logger.info(f"[#530] {sk[:40]} is a v1 hypothesis (no test_spec) — left to hard expiry, never LLM-checked")
            continue

        # AI-4: Skip if hypothesis is less than MIN_SAMPLE_DAYS_FOR_CHECK old
        try:
            created_date = datetime.fromisoformat(created_at).date()
            days_old = (now - created_date).days
        except Exception:
            days_old = 0

        if days_old < MIN_SAMPLE_DAYS_FOR_CHECK:
            logger.info(f"[AI-4] Skipping check for {sk[:40]} — only {days_old}d old (need {MIN_SAMPLE_DAYS_FOR_CHECK})")
            continue

        stats = evaluate_test_spec(spec, daily_rows, created_at[:10])
        verdict = stats["verdict"]
        window_done = days_old >= monitoring_window

        resolution = None
        if verdict == "contradicted":
            new_status, resolution = "refuted", "refuted"
        elif verdict == "supported" and window_done:
            new_status, resolution = "confirmed", "confirmed"
        elif verdict == "supported":
            new_status = "confirming"
        elif days_old > monitoring_window:
            new_status, resolution = "archived", "expired_undecided"
        else:
            new_status = hyp.get("status", "pending")

        evidence = deterministic_evidence(spec, stats)
        if resolution:
            narration = narrate_resolution(hyp, evidence, new_status)
            if narration:
                evidence = f"{evidence} {narration}"
            time.sleep(0.5)

        updates.append((hyp, new_status, evidence, stats, resolution))
        logger.info(
            f"[#530] Deterministic check: {verdict} -> {new_status} (observed {stats['days_observed']}d, window {monitoring_window}d)"
        )

    return updates


# ══════════════════════════════════════════════════════════════════════════════
# DOWNSTREAM CONTEXT — write hypothesis context for digest Lambdas
# ══════════════════════════════════════════════════════════════════════════════


def write_hypothesis_context_to_memory(active_hypotheses):
    """Write compact hypothesis monitoring block to platform_memory for IC-16 consumption."""
    if not active_hypotheses:
        return

    try:
        pending = [h for h in active_hypotheses if h.get("status") in ("pending", "confirming")]
        confirmed = [h for h in active_hypotheses if h.get("status") == "confirmed"]

        lines = []
        if confirmed:
            lines.append("CONFIRMED HYPOTHESES (incorporate into coaching as established patterns):")
            for h in confirmed[:3]:
                # #530: carry the deterministic effect + CI so coaching narrates
                # measured numbers, never a vibe (ADR-104/105)
                stat_note = ""
                if h.get("effect_size") is not None and h.get("ci95_low") is not None:
                    stat_note = (
                        f" (measured effect {h['effect_size']:+g}, 95% CI [{h['ci95_low']:g}, {h['ci95_high']:g}], "
                        f"n={int(h.get('n_condition', 0))}/{int(h.get('n_comparison', 0))} days)"
                    )
                lines.append(f"  [CONFIRMED] {h['hypothesis']}{stat_note}")
                # IC-19 D3B: Suggest formalising confirmed hypotheses as N=1 experiments
                # (Conti: if the confirmed hypothesis involves a negative psychological variable,
                # frame the experiment suggestion as an intervention opportunity, not a label)
                actionable = h.get("actionable_if_confirmed", "")
                if actionable:
                    lines.append(
                        f"  [EXPERIMENT SUGGESTED] {actionable} " f"— Consider running a formal N=1 experiment to quantify this effect."
                    )

        if pending:
            lines.append("ACTIVE HYPOTHESES (watch for confirming/refuting evidence in current data):")
            for h in pending[:5]:
                domains = " + ".join(h.get("domains", []))
                lines.append(f"  [WATCHING: {domains}] {h['hypothesis']}")
                criteria = h.get("confirmation_criteria", "")
                if criteria:
                    pre_reg = (h.get("pre_registered_at") or h.get("created_at") or "")[:10]
                    tag = f" (pre-registered {pre_reg})" if pre_reg else ""
                    lines.append(f"     Criteria{tag}: {criteria[:120]}")

        if not lines:
            return

        now = datetime.now(timezone.utc)
        item = {
            "pk": f"USER#{USER_ID}#SOURCE#platform_memory",
            "sk": f"MEMORY#hypothesis_monitoring#{now.date().isoformat()}",
            "category": "hypothesis_monitoring",
            "stored_at": now.isoformat(),
            "context_block": "\n".join(lines),
            "pending_count": len(pending),
            "confirmed_count": len(confirmed),
        }
        # V2 P2.6 (2026-05-19): tag with run_id + computed_at
        try:
            from compute_metadata import tag_record

            item = tag_record(item, source_id="hypothesis_context")
        except ImportError:
            pass
        table.put_item(Item=item)
        logger.info(f"Hypothesis context written: {len(pending)} pending, {len(confirmed)} confirmed")
    except Exception as e:
        logger.warning(f"write_hypothesis_context_to_memory failed (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def lambda_handler(event, context):
    try:
        logger.info("IC-18: Hypothesis Engine v2.0.0 (#530: deterministic specs + calibration) starting...")

        # 1. Gather data + profile
        data = gather_data()
        if not data:
            return {"statusCode": 500, "body": "Failed to gather data"}
        profile = fetch_profile()

        daily_rows = build_data_narrative(data)
        logger.info(f"Built data narrative: {len(daily_rows)} days")

        # AI-4: Check data completeness before any hypothesis work
        is_sufficient, complete_days, total_days, completeness_msg = check_data_completeness(daily_rows)
        logger.info(f"[AI-4] Data completeness: {completeness_msg}")

        # 2. Load existing hypotheses
        all_hypotheses = load_existing_hypotheses()
        pending_hypotheses = [h for h in all_hypotheses if h.get("status") in ("pending", "confirming")]
        pending_count = len(pending_hypotheses)
        logger.info(f"Existing: {len(all_hypotheses)} total, {pending_count} pending/confirming")

        # AI-4: Enforce hard expiry on all non-terminal hypotheses
        expired_updates = enforce_hard_expiry(all_hypotheses)
        expired_count = 0
        for sk, status, reason in expired_updates:
            update_hypothesis_status(sk, status, reason)
            expired_count += 1
        if expired_count:
            logger.info(f"[AI-4] Hard expiry: archived {expired_count} hypotheses older than {HARD_EXPIRY_DAYS} days")
            # Reload after expiry to get accurate pending count
            all_hypotheses = load_existing_hypotheses()
            pending_hypotheses = [h for h in all_hypotheses if h.get("status") in ("pending", "confirming")]
            pending_count = len(pending_hypotheses)

        # 3. Check pending hypotheses against new data — deterministic (#530).
        # Resolutions also write a calibration-ledger row (ADR-105 rule 2).
        updates_made = 0
        resolutions = 0
        if pending_hypotheses:
            updates = check_pending_hypotheses(pending_hypotheses, daily_rows)
            for hyp, new_status, evidence_note, stats, resolution in updates:
                update_hypothesis_status(hyp.get("sk", ""), new_status, evidence_note, stats=stats)
                updates_made += 1
                if resolution:
                    write_calibration_row(hyp, stats, resolution)
                    resolutions += 1
            logger.info(f"Hypothesis checks: {updates_made} updated, {resolutions} resolved -> calibration ledger")

        # 4. Generate new hypotheses if room exists AND data is sufficient
        new_hypotheses_stored = 0
        validation_rejected = 0
        if not is_sufficient:
            logger.info(f"[AI-4] Skipping generation — {completeness_msg}")
        elif pending_count < MAX_PENDING_HYPOTHESES:
            slots_available = MAX_PENDING_HYPOTHESES - pending_count
            n_to_generate = min(MAX_NEW_HYPOTHESES, slots_available)
            logger.info(f"Generating {n_to_generate} new hypotheses ({slots_available} slots)")

            # #530: generation sees only the recent window; checks used the full 30d
            # #506: journal-derived candidates (testable cause->effect hints with
            # verbatim quotes) seed the generation prompt.
            journal_candidates = fetch_journal_candidates()
            if journal_candidates:
                logger.info(f"[#506] Seeding generation with {len(journal_candidates)} journal candidates")
            result = generate_hypotheses(
                daily_rows[-GENERATION_DAYS:], all_hypotheses, profile=profile, journal_candidates=journal_candidates
            )

            if result and "hypotheses" in result:
                existing_texts = [h.get("hypothesis", "")[:100] for h in all_hypotheses]

                for hyp in result["hypotheses"][:n_to_generate]:
                    # AI-4: Full validation before storing
                    is_valid, issues = validate_hypothesis(hyp, existing_texts)
                    if not is_valid:
                        logger.warning(f"[AI-4] Rejected hypothesis '{hyp.get('hypothesis_id', '?')}': {issues}")
                        validation_rejected += 1
                        continue

                    # Clamp monitoring_window_days to valid range
                    window = hyp.get("monitoring_window_days", 21)
                    try:
                        window = max(7, min(30, int(window)))
                    except (ValueError, TypeError):
                        window = 21
                    hyp["monitoring_window_days"] = window

                    store_hypothesis(hyp)
                    new_hypotheses_stored += 1

                logger.info(f"Stored {new_hypotheses_stored} new hypotheses, rejected {validation_rejected}")
            else:
                logger.warning("Hypothesis generation returned no results")
        else:
            logger.info(f"Hypothesis cap reached ({pending_count} pending) — skipping generation")

        # 5. Write monitoring context to platform_memory for IC-16 consumption
        all_hypotheses_updated = load_existing_hypotheses()
        active = [h for h in all_hypotheses_updated if h.get("status") in ("pending", "confirming", "confirmed")]
        write_hypothesis_context_to_memory(active)

        summary = {
            "new_hypotheses": new_hypotheses_stored,
            "validation_rejected": validation_rejected,
            "expired_by_hard_limit": expired_count,
            "hypotheses_checked": len(pending_hypotheses),
            "hypotheses_updated": updates_made,
            "resolutions_to_calibration": resolutions,
            "total_active": len(active),
            "data_complete_days": complete_days,
            "data_sufficient": is_sufficient,
        }
        logger.info(f"Complete: {summary}")
        return {"statusCode": 200, "body": json.dumps(summary)}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
