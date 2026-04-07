"""
hypothesis_engine_lambda.py — IC-18: Cross-Domain Hypothesis Engine
v1.2.0 — AI-4 + IC-19 D3B: Conti intervention framing, experiment cross-reference, experiment suggestions

Scientific method applied to personal health data. Runs weekly (Sunday 11 AM PT)
after the Weekly Digest, surfacing non-obvious cross-domain correlations that the
existing 144 tools don't explicitly monitor.

Workflow:
  1. Pull 14 days of all-pillar data from DynamoDB
  2. Load existing pending hypotheses (to check for confirmation/refutation)
  3. Run Claude Sonnet: generate 3-5 new cross-domain hypotheses
  4. Check pending hypotheses against current data
  5. Write results to DDB SOURCE#hypotheses partition

Hypothesis lifecycle:
  pending → confirming → confirmed → archived
  pending → refuted    → archived

DDB pattern:
  pk = USER#matthew#SOURCE#hypotheses
  sk = HYPOTHESIS#<ISO-timestamp>

Downstream consumers:
  - daily-insight-compute Lambda can pull 'pending' hypotheses and monitor for evidence
  - Digest Lambdas inject confirming/refuting observations via IC-16 progressive context
  - MCP tools: get_hypotheses, update_hypothesis_outcome

Cost: ~$0.05/week (one Sonnet call + DDB reads/writes)
"""

import json
import os
import logging
import re
import time
import boto3
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("hypothesis-engine")
except ImportError:
    logger = logging.getLogger("hypothesis-engine")
    logger.setLevel(logging.INFO)

# AI-3: Output validator — validates AI text before storage/delivery
try:
    from ai_output_validator import validate_ai_output, AIOutputType
    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
S3_BUCKET  = os.environ["S3_BUCKET"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
secrets  = boto3.client("secretsmanager", region_name=REGION)

# AI model constants — read from env so model can be updated without redeployment
AI_MODEL       = os.environ.get("AI_MODEL",       "claude-sonnet-4-6")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

HYPOTHESES_PK = f"USER#{USER_ID}#SOURCE#hypotheses"
MAX_NEW_HYPOTHESES = 5
MAX_PENDING_HYPOTHESES = 20   # don't accumulate stale hypotheses

# AI-4: Validation thresholds
MIN_DATA_DAYS = 10            # require >= 10 days with sufficient metrics before generating
MIN_METRICS_PER_DAY = 5       # a day needs >= 5 non-null metrics to count as "complete"
HARD_EXPIRY_DAYS = 30         # archive any hypothesis older than 30 days regardless of status
MIN_SAMPLE_DAYS_FOR_CHECK = 7 # require >= 7 data days since creation before evaluating
REQUIRED_HYPOTHESIS_FIELDS = {
    "hypothesis_id", "hypothesis", "domains", "evidence",
    "confirmation_criteria", "monitoring_window_days", "confidence",
    "actionable_if_confirmed",
}
VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}
# Pattern: confirmation criteria should contain at least one number (threshold/percentage)
NUMERIC_PATTERN = re.compile(r'\d+\.?\d*\s*(%|days?|hours?|minutes?|ms|points?|g|kg|lbs?|cal|kcal|bpm|mg)')



# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_anthropic_key():
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
    try:
        val = secrets.get_secret_value(SecretId=secret_name)
        data = json.loads(val["SecretString"])
        return data.get("ANTHROPIC_API_KEY") or data.get("anthropic_api_key")
    except Exception as e:
        logger.error(f"Failed to get Anthropic key: {e}")
        raise


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
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{end_date}"
            )
        )
        return d2f(resp.get("Items", []))
    except Exception as e:
        logger.warning(f"query_range({source}) failed: {e}")
        return []


def fetch_profile():
    """Load user profile from DynamoDB."""
    try:
        resp = table.get_item(Key={"pk": f"USER#{USER_ID}#profile", "sk": "PROFILE"})
        return d2f(resp.get("Item", {}))
    except Exception:
        return {}


def gather_data():
    """Fetch 14 days of multi-source data for hypothesis generation."""
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=13)).strftime("%Y-%m-%d")

    sources = ["whoop", "garmin", "macrofactor", "apple_health",
               "withings", "strava", "notion", "habitify", "eightsleep"]

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
            KeyConditionExpression=Key("pk").eq(HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
            ScanIndexForward=False,
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

    table.put_item(Item=to_decimal(item))
    logger.info(f"Stored hypothesis: {hypothesis.get('hypothesis_id', sk)}")


def update_hypothesis_status(sk: str, status: str, evidence_note: str = ""):
    """Update hypothesis status and increment check_count."""
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
            row["total_sleep_hrs"] = safe_float(whoop, "total_in_bed_time_hrs")

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
            row["weight_lbs"] = safe_float(mf, "tdee_kcal")  # TDEE as proxy

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
            row["bed_temp_f"] = safe_float(es, "avg_bed_temp_f")

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


# ── IC-19 D3B: Load active N=1 experiments for hypothesis cross-reference ──
def load_active_experiments():
    """Query active N=1 experiments from DynamoDB.

    Used to cross-reference hypothesis evidence: if an active experiment is testing
    something related to a pending hypothesis, that is additive confirmation evidence
    (Chen: check ATL/CTL context; Henning: small N, keep claims modest).

    Returns list of experiment dicts (id, name, hypothesis, start_date).
    """
    EXPERIMENTS_PK = f"USER#{USER_ID}#SOURCE#experiments"
    try:
        from boto3.dynamodb.conditions import Key
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"),
        )
        items = []
        for item in resp.get("Items", []):
            status = item.get("status", "")
            if status == "active":
                items.append({
                    "experiment_id": item.get("experiment_id", ""),
                    "name":          str(item.get("name", "")),
                    "hypothesis":    str(item.get("hypothesis", "")),
                    "start_date":    str(item.get("start_date", "")),
                })
        return items
    except Exception as e:
        logger.warning(f"load_active_experiments failed (non-fatal): {e}")
        return []

def validate_check_verdict(result):
    """AI-4: Validate the check verdict from Haiku.

    Returns (is_valid, verdict, evidence).
    """
    if not isinstance(result, dict):
        return False, "insufficient", "Invalid response structure"

    verdict = result.get("verdict", "").lower().strip()
    evidence = result.get("evidence", "")

    if verdict not in ("confirming", "refuted", "insufficient"):
        return False, "insufficient", f"Invalid verdict: {verdict}"

    if not evidence or len(evidence) < 10:
        return False, "insufficient", "Evidence too brief"

    # AI-4: Require evidence to cite at least one number for confirming/refuted verdicts
    if verdict in ("confirming", "refuted") and not re.search(r'\d', evidence):
        return False, "insufficient", "Evidence must cite specific values for confirming/refuted verdicts"

    return True, verdict, evidence


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

FRAMING RULE — NEGATIVE PSYCHOLOGICAL VARIABLES (Conti):
Hypotheses about stress, anxiety, low mood, emotional depletion, or other negative psychological
states MUST be framed as intervention opportunities, NOT as baseline characterisations.
BAD:  "High stress correlates with poor sleep efficiency"
GOOD: "Reducing perceived stress on high-workload days may improve sleep efficiency by ~X%"
The hypothesis sentence should describe what changing the variable could produce, not just that
two things move together. This applies to ANY variable where the desirable direction is reduction.

OUTPUT ONLY valid JSON. No preamble, no markdown, no backticks."""


def generate_hypotheses(daily_rows, existing_hypotheses, api_key, profile=None):
    """Run Claude to generate new cross-domain hypotheses from 14 days of data."""
    p = profile or {}
    start_w = p.get("journey_start_weight_lbs", 307)
    goal_w = p.get("goal_weight_lbs", 185)
    total_loss = round(start_w - goal_w)
    cal_target = p.get("calorie_target", 1800)
    pro_target = p.get("protein_target_g", 190)

    existing_texts = [h.get("hypothesis", "")[:100] for h in existing_hypotheses]
    existing_block = ""
    if existing_texts:
        existing_block = "\n\nEXISTING HYPOTHESES (do NOT duplicate these):\n" + "\n".join(f"- {t}" for t in existing_texts)

    user_message = f"""Here is {len(daily_rows)} days of Matthew's health data:

{json.dumps(daily_rows, indent=2)}

Context:
- 36-year-old male, {total_loss} lb weight loss transformation (started {start_w} lbs, goal {goal_w} lbs)
- Calorie target: {cal_target} cal/day, protein target: {pro_target}g/day
- 16:8 intermittent fasting (eating window ~11am-7pm)
- Primary training: walking + strength training, building Zone 2 base
- Data sources: Whoop (HRV/recovery), Eight Sleep (bed temp), Strava (activities), MacroFactor (nutrition), Habitify (habits), Apple Health (steps/glucose/gait), Notion journal (mood/stress/energy)
{existing_block}

Generate {MAX_NEW_HYPOTHESES} cross-domain hypotheses. Each should be:
- A non-obvious relationship between 2+ domains
- Grounded in a specific pattern you can see in this data
- Falsifiable with 2-4 weeks of continued observation

Return ONLY this JSON structure:
{{
  "hypotheses": [
    {{
      "hypothesis_id": "hyp_<short_slug>",
      "hypothesis": "One clear sentence stating the relationship",
      "domains": ["domain1", "domain2"],
      "evidence": "What you saw in this data that suggested it (2-3 sentences, CITE SPECIFIC DATES AND VALUES)",
      "confirmation_criteria": "What would confirm this over 2-4 weeks — MUST include specific numeric thresholds (e.g., 'deep sleep % increases by 5+ points on days following protein >150g')",
      "effect_size_observed": "The magnitude of the pattern you observed (e.g., '12% higher deep sleep on high-protein days')",
      "monitoring_window_days": 21,
      "confidence": "low|medium|high",
      "confidence_reason": "Why this confidence level — how many data points support it",
      "actionable_if_confirmed": "What Matthew could change if this is confirmed (1 sentence)"
    }}
  ]
}}"""

    payload = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 2000,
        "system": HYPOTHESIS_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}, method="POST",
    )

    for attempt in range(1, 3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                resp = json.loads(r.read())
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
        except urllib.error.HTTPError as e:
            logger.warning(f"Anthropic HTTP {e.code} attempt {attempt}")
            if attempt < 2 and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(5)
            else:
                raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Hypothesis parse error: {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# HYPOTHESIS CHECKING — evaluate pending hypotheses against new data
# ══════════════════════════════════════════════════════════════════════════════

def check_pending_hypotheses(pending_hypotheses, daily_rows, api_key):
    """For each pending hypothesis, check if recent data is confirming or refuting it.

    AI-4 changes:
    - Uses MIN_SAMPLE_DAYS_FOR_CHECK (7 days) instead of hardcoded 3
    - Validates Haiku check response structure
    - Hard expiry enforced separately (in handler)

    IC-19 D3B changes:
    - Loads active N=1 experiments and cross-references against each hypothesis
    - Injects matching experiment context into the check prompt (additive evidence)

    Returns list of (sk, new_status, evidence_note) tuples.
    """
    if not pending_hypotheses or not daily_rows:
        return []

    updates = []
    now = datetime.now(timezone.utc).date()

    # IC-19 D3B: Load active experiments once for the whole batch
    active_experiments = load_active_experiments()

    for hyp in pending_hypotheses:
        sk = hyp.get("sk", "")
        hypothesis_text = hyp.get("hypothesis", "")
        confirmation_criteria = hyp.get("confirmation_criteria", "")
        created_at = hyp.get("created_at", "")
        check_count = hyp.get("check_count", 0)
        monitoring_window = hyp.get("monitoring_window_days", 21)

        if not sk or not hypothesis_text:
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

        # Archive if monitoring window expired and checked enough times
        if days_old > monitoring_window and check_count >= 3:
            updates.append((sk, "archived", f"Monitoring window of {monitoring_window} days expired after {check_count} checks"))
            continue

        relevant_data = [r for r in daily_rows if r.get("date", "") >= created_at[:10]]
        if len(relevant_data) < MIN_SAMPLE_DAYS_FOR_CHECK:
            logger.info(f"[AI-4] Insufficient data for check: {len(relevant_data)} days (need {MIN_SAMPLE_DAYS_FOR_CHECK})")
            continue

        # IC-19 D3B: If an active experiment's hypothesis overlaps with this one,
        # include it as additional context (Raj: early exit if no experiments to check)
        exp_context = ""
        if active_experiments:
            hyp_lower = hypothesis_text.lower()
            related = [
                e for e in active_experiments
                if any(kw in hyp_lower for kw in e["name"].lower().split()[:4]
                       if len(kw) > 4)
                or any(kw in hyp_lower for kw in e["hypothesis"].lower().split()[:6]
                       if len(kw) > 4)
            ]
            if related:
                exp_lines = [
                    f"  [{e['experiment_id']}] {e['name']}: {e['hypothesis']!r} (since {e['start_date']})"
                    for e in related
                ]
                exp_context = (
                    "\n\nACTIVE EXPERIMENTS (cross-reference as additional evidence — "
                    "Henning: small N, keep claims correlative not causal):\n"
                    + "\n".join(exp_lines)
                    + "\n"
                )

        check_prompt = f"""Hypothesis: {hypothesis_text}

Confirmation criteria: {confirmation_criteria}

Recent data ({len(relevant_data)} days since hypothesis was created):{exp_context}
{json.dumps(relevant_data[-7:], indent=2)}

Based on this data, evaluate the hypothesis STRICTLY:
- CONFIRMING: data shows a clear pattern consistent with the hypothesis, with observable effect sizes matching the criteria
- REFUTED: data clearly contradicts the hypothesis or shows no pattern after sufficient observation
- INSUFFICIENT: not enough relevant data points, or pattern is ambiguous

Be conservative: default to INSUFFICIENT unless the evidence is clear. Cite specific values.

Respond ONLY with JSON: {{"verdict": "confirming|refuted|insufficient", "evidence": "2-3 sentences citing specific data points and effect sizes"}}"""

        payload = json.dumps({
            "model": AI_MODEL_HAIKU,
            "max_tokens": 200,
            "messages": [{"role": "user", "content": check_prompt}],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=payload,
            headers={"Content-Type": "application/json", "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"}, method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = json.loads(r.read())
                raw = resp["content"][0]["text"].strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                result = json.loads(raw.strip())

                # AI-4: Validate check verdict
                is_valid, verdict, evidence = validate_check_verdict(result)
                if not is_valid:
                    logger.warning(f"[AI-4] Invalid check verdict for {sk[:40]}: {result}")
                    verdict = "insufficient"

                # AI-3: Validate evidence text before storing
                if _HAS_AI_VALIDATOR and evidence:
                    ev_result = validate_ai_output(evidence, AIOutputType.GENERIC)
                    if ev_result.blocked:
                        logger.warning("[AI-3] check evidence blocked for %s: %s", sk[:40], ev_result.block_reason)
                        evidence = ev_result.safe_fallback or "Evidence unavailable — output blocked by validator."
                    elif ev_result.warnings:
                        logger.warning("[AI-3] check evidence warnings for %s: %s", sk[:40], ev_result.warnings)

                if verdict == "refuted":
                    new_status = "refuted"
                elif verdict == "confirming":
                    # AI-4: Require 3 confirming checks (was 2) for promotion to confirmed
                    new_status = "confirmed" if check_count >= 3 else "confirming"
                else:
                    new_status = hyp.get("status", "pending")

                updates.append((sk, new_status, evidence))
                logger.info(f"[AI-4] Hypothesis check: {verdict} -> {new_status} (checks: {check_count + 1})")
                time.sleep(0.5)

        except Exception as e:
            logger.warning(f"Hypothesis check failed for {sk[:40]}: {e}")

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
                lines.append(f"  [CONFIRMED] {h['hypothesis']}")
                # IC-19 D3B: Suggest formalising confirmed hypotheses as N=1 experiments
                # (Conti: if the confirmed hypothesis involves a negative psychological variable,
                # frame the experiment suggestion as an intervention opportunity, not a label)
                actionable = h.get("actionable_if_confirmed", "")
                if actionable:
                    lines.append(
                        f"  [EXPERIMENT SUGGESTED] {actionable} "
                        f"— Consider running a formal N=1 experiment to quantify this effect."
                    )

        if pending:
            lines.append("ACTIVE HYPOTHESES (watch for confirming/refuting evidence in current data):")
            for h in pending[:5]:
                domains = " + ".join(h.get("domains", []))
                lines.append(f"  [WATCHING: {domains}] {h['hypothesis']}")
                criteria = h.get("confirmation_criteria", "")
                if criteria:
                    lines.append(f"     Criteria: {criteria[:120]}")

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
        table.put_item(Item=item)
        logger.info(f"Hypothesis context written: {len(pending)} pending, {len(confirmed)} confirmed")
    except Exception as e:
        logger.warning(f"write_hypothesis_context_to_memory failed (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    try:
        logger.info("IC-18: Hypothesis Engine v1.2.0 (AI-4 + IC-19 D3B) starting...")

        api_key = get_anthropic_key()

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

        # 3. Check pending hypotheses against new data
        updates_made = 0
        if pending_hypotheses:
            updates = check_pending_hypotheses(pending_hypotheses, daily_rows, api_key)
            for sk, new_status, evidence_note in updates:
                update_hypothesis_status(sk, new_status, evidence_note)
                updates_made += 1
            logger.info(f"Hypothesis checks: {updates_made} updated")

        # 4. Generate new hypotheses if room exists AND data is sufficient
        new_hypotheses_stored = 0
        validation_rejected = 0
        if not is_sufficient:
            logger.info(f"[AI-4] Skipping generation — {completeness_msg}")
        elif pending_count < MAX_PENDING_HYPOTHESES:
            slots_available = MAX_PENDING_HYPOTHESES - pending_count
            n_to_generate = min(MAX_NEW_HYPOTHESES, slots_available)
            logger.info(f"Generating {n_to_generate} new hypotheses ({slots_available} slots)")

            result = generate_hypotheses(daily_rows, all_hypotheses, api_key, profile=profile)

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
        active = [h for h in all_hypotheses_updated
                  if h.get("status") in ("pending", "confirming", "confirmed")]
        write_hypothesis_context_to_memory(active)

        summary = {
            "new_hypotheses": new_hypotheses_stored,
            "validation_rejected": validation_rejected,
            "expired_by_hard_limit": expired_count,
            "hypotheses_checked": len(pending_hypotheses),
            "hypotheses_updated": updates_made,
            "total_active": len(active),
            "data_complete_days": complete_days,
            "data_sufficient": is_sufficient,
        }
        logger.info(f"Complete: {summary}")
        return {"statusCode": 200, "body": json.dumps(summary)}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
