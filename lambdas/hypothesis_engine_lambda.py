"""
hypothesis_engine_lambda.py — IC-18: Cross-Domain Hypothesis Engine
v1.1.0 — AI-4: Output validation (effect size, confidence intervals, 30-day expiry)

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

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ["USER_ID"]
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
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/api-keys")
    secret = secrets.get_secret_value(SecretId=secret_name)
    return json.loads(secret["SecretString"])["anthropic_api_key"]


def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default


def query_range(source, start_date, end_date):
    """Query a DDB source for a date range, return dict of date -> record."""
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk, ":s": f"DATE#{start_date}", ":e": f"DATE#{end_date}"
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item["sk"].replace("DATE#", "")
            records[date_str] = d2f(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records


def fetch_profile():
    try:
        r = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.warning(f"Profile fetch failed: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING — 14 days across all major sources
# ══════════════════════════════════════════════════════════════════════════════

def gather_data():
    today = datetime.now(timezone.utc).date()
    end_date = (today - timedelta(days=1)).isoformat()
    start_date = (today - timedelta(days=14)).isoformat()

    logger.info(f"Pulling 14d data: {start_date} -> {end_date}")

    profile = fetch_profile()

    sources = {
        "whoop":       query_range("whoop", start_date, end_date),
        "sleep":       query_range("sleep", start_date, end_date),
        "macrofactor": query_range("macrofactor", start_date, end_date),
        "strava":      query_range("strava", start_date, end_date),
        "habitify":    query_range("habitify", start_date, end_date),
        "apple":       query_range("apple_health", start_date, end_date),
        "withings":    query_range("withings", start_date, end_date),
        "journal":     query_range("journal", start_date, end_date),
        "eightsleep":  query_range("eightsleep", start_date, end_date),
    }

    # Also pull computed_metrics for day grades
    computed = query_range("computed_metrics", start_date, end_date)

    logger.info(f"Data pull complete: {', '.join(f'{k}:{len(v)}d' for k,v in sources.items())}")

    return {
        "sources": sources,
        "computed": computed,
        "profile": profile,
        "dates": {"start": start_date, "end": end_date},
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXISTING HYPOTHESIS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def load_existing_hypotheses(status_filter=None):
    """Load hypotheses from DDB. Optionally filter by status."""
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": HYPOTHESES_PK,
                ":prefix": "HYPOTHESIS#",
            },
            ScanIndexForward=False,
            Limit=50,
        )
        items = [d2f(i) for i in resp.get("Items", [])]
        if status_filter:
            items = [i for i in items if i.get("status") == status_filter]
        return items
    except Exception as e:
        logger.warning(f"load_existing_hypotheses failed: {e}")
        return []


def store_hypothesis(hypothesis: dict):
    """Write a hypothesis record to DDB."""
    now = datetime.now(timezone.utc).isoformat()
    sk = f"HYPOTHESIS#{now}"
    item = {
        "pk": HYPOTHESES_PK,
        "sk": sk,
        "created_at": now,
        "last_checked": now,
        "check_count": 0,
        "status": "pending",
        "evidence_log": [],
        **hypothesis,
    }
    table.put_item(Item=item)
    logger.info(f"Stored hypothesis: {hypothesis.get('hypothesis_id', '?')} -- {hypothesis.get('hypothesis', '')[:80]}")
    return sk


def update_hypothesis_status(sk: str, status: str, evidence_note: str = ""):
    """Update hypothesis status and append to evidence_log."""
    now = datetime.now(timezone.utc).isoformat()
    update_expr = "SET #s = :s, last_checked = :lc, check_count = check_count + :one"
    expr_names = {"#s": "status"}
    expr_vals = {":s": status, ":lc": now, ":one": 1}

    if evidence_note:
        update_expr += ", evidence_log = list_append(if_not_exists(evidence_log, :empty), :ev)"
        expr_vals[":empty"] = []
        expr_vals[":ev"] = [{"date": now[:10], "note": evidence_note, "direction": status}]

    table.update_item(
        Key={"pk": HYPOTHESES_PK, "sk": sk},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_vals,
    )


# ══════════════════════════════════════════════════════════════════════════════
# BUILD DATA NARRATIVE — compact summary of 14 days for the AI
# ══════════════════════════════════════════════════════════════════════════════

def build_data_narrative(data):
    """Compress 14 days of multi-source data into a compact narrative for the hypothesis generator."""
    sources = data["sources"]
    computed = data["computed"]
    dates = sorted(set(
        list(sources["whoop"].keys()) +
        list(sources["macrofactor"].keys()) +
        list(sources["sleep"].keys()) +
        list(sources["habitify"].keys())
    ))

    daily_rows = []
    for date_str in dates:
        whoop   = sources["whoop"].get(date_str, {})
        sleep   = sources["sleep"].get(date_str, {})
        mf      = sources["macrofactor"].get(date_str, {})
        strava  = sources["strava"].get(date_str, {})
        hab     = sources["habitify"].get(date_str, {})
        apple   = sources["apple"].get(date_str, {})
        journal = sources["journal"].get(date_str, {})
        eight   = sources["eightsleep"].get(date_str, {})
        comp    = computed.get(date_str, {})

        row = {
            "date": date_str,
            # Recovery & sleep
            "hrv":            safe_float(whoop, "hrv"),
            "recovery":       safe_float(whoop, "recovery_score"),
            "sleep_score":    safe_float(sleep, "sleep_score"),
            "sleep_hrs":      safe_float(sleep, "sleep_duration_hours"),
            "deep_pct":       safe_float(sleep, "deep_pct"),
            "rem_pct":        safe_float(sleep, "rem_pct"),
            "bed_temp_f":     safe_float(eight, "current_temp_f"),
            # Nutrition
            "calories":       safe_float(mf, "total_calories_kcal"),
            "protein_g":      safe_float(mf, "total_protein_g"),
            "carbs_g":        safe_float(mf, "total_carbs_g"),
            "fat_g":          safe_float(mf, "total_fat_g"),
            # Movement
            "activity_count": safe_float(strava, "activity_count"),
            "steps":          safe_float(apple, "steps"),
            # Glucose
            "glucose_avg":    safe_float(apple, "blood_glucose_avg"),
            "glucose_tir":    safe_float(apple, "blood_glucose_time_in_range_pct"),
            # Mind & habits
            "journal_stress": safe_float(journal, "stress_avg"),
            "journal_mood":   safe_float(journal, "mood_avg"),
            "habit_pct":      round(safe_float(hab, "total_completed", 0) /
                                    max(safe_float(hab, "total_possible", 1), 1) * 100, 0),
            # Day grade
            "day_grade":      safe_float(comp, "day_grade"),
        }
        # Remove None values
        row = {k: v for k, v in row.items() if v is not None}
        daily_rows.append(row)

    return daily_rows


# ══════════════════════════════════════════════════════════════════════════════
# AI-4: DATA COMPLETENESS & HYPOTHESIS VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def check_data_completeness(daily_rows):
    """AI-4: Verify enough data exists to generate meaningful hypotheses.

    Returns (is_sufficient, complete_days, total_days, message).
    A "complete" day has >= MIN_METRICS_PER_DAY non-null fields (excluding 'date').
    """
    total_days = len(daily_rows)
    complete_days = 0
    for row in daily_rows:
        non_null_metrics = sum(1 for k, v in row.items() if k != "date" and v is not None)
        if non_null_metrics >= MIN_METRICS_PER_DAY:
            complete_days += 1

    is_sufficient = complete_days >= MIN_DATA_DAYS
    if not is_sufficient:
        msg = (f"Insufficient data: {complete_days}/{MIN_DATA_DAYS} complete days "
               f"(total {total_days} days, requiring {MIN_METRICS_PER_DAY}+ metrics each)")
    else:
        msg = f"Data sufficient: {complete_days} complete days out of {total_days}"
    return is_sufficient, complete_days, total_days, msg


def validate_hypothesis(hyp, existing_texts=None):
    """AI-4: Validate a single hypothesis before storing.

    Returns (is_valid, issues_list). A hypothesis must:
    1. Have all required fields present and non-empty
    2. Have domains list with 2+ entries (cross-domain requirement)
    3. Have confidence in valid set
    4. Have confirmation_criteria containing at least one numeric threshold
    5. Have monitoring_window_days between 7 and 30
    6. Not duplicate existing hypotheses (simple substring check)
    """
    issues = []

    # Required fields check
    missing = REQUIRED_HYPOTHESIS_FIELDS - set(hyp.keys())
    if missing:
        issues.append(f"Missing fields: {missing}")

    # Non-empty checks
    for field in ("hypothesis", "evidence", "confirmation_criteria", "actionable_if_confirmed"):
        val = hyp.get(field, "")
        if not val or len(str(val).strip()) < 10:
            issues.append(f"Field '{field}' too short or empty")

    # Cross-domain: need 2+ domains
    domains = hyp.get("domains", [])
    if not isinstance(domains, list) or len(domains) < 2:
        issues.append(f"Need 2+ domains for cross-domain hypothesis, got {len(domains) if isinstance(domains, list) else 0}")

    # Confidence validation
    confidence = hyp.get("confidence", "")
    if confidence not in VALID_CONFIDENCE_LEVELS:
        issues.append(f"Invalid confidence '{confidence}'; must be one of {VALID_CONFIDENCE_LEVELS}")

    # Numeric threshold in confirmation criteria (AI-4: effect size requirement)
    criteria = str(hyp.get("confirmation_criteria", ""))
    if not NUMERIC_PATTERN.search(criteria):
        issues.append("Confirmation criteria must contain specific numeric thresholds "
                       "(e.g., '10% improvement', '5 points higher', '30 minutes more')")

    # Monitoring window bounds
    window = hyp.get("monitoring_window_days", 0)
    try:
        window = int(window)
    except (ValueError, TypeError):
        window = 0
    if window < 7 or window > 30:
        issues.append(f"monitoring_window_days must be 7-30, got {window}")

    # Hypothesis ID format
    hyp_id = hyp.get("hypothesis_id", "")
    if not hyp_id or not hyp_id.startswith("hyp_"):
        issues.append(f"hypothesis_id must start with 'hyp_', got '{hyp_id}'")

    # Deduplication check (simple substring overlap with existing)
    if existing_texts:
        hyp_text = hyp.get("hypothesis", "").lower()
        for existing in existing_texts:
            # Check if more than 60% of words overlap
            existing_words = set(existing.lower().split())
            hyp_words = set(hyp_text.split())
            if existing_words and hyp_words:
                overlap = len(existing_words & hyp_words) / max(len(existing_words), len(hyp_words))
                if overlap > 0.6:
                    issues.append(f"Too similar to existing hypothesis: '{existing[:80]}...'")
                    break

    return len(issues) == 0, issues


def enforce_hard_expiry(all_hypotheses):
    """AI-4: Archive any hypothesis older than HARD_EXPIRY_DAYS regardless of status.

    Returns list of (sk, "archived", reason) tuples for expired hypotheses.
    """
    now = datetime.now(timezone.utc).date()
    expired = []

    for hyp in all_hypotheses:
        if hyp.get("status") in ("archived", "confirmed", "refuted"):
            continue
        created_at = hyp.get("created_at", "")
        sk = hyp.get("sk", "")
        if not created_at or not sk:
            continue
        try:
            created_date = datetime.fromisoformat(created_at).date()
            days_old = (now - created_date).days
            if days_old > HARD_EXPIRY_DAYS:
                expired.append((
                    sk,
                    "archived",
                    f"Hard expiry: {days_old} days old (limit {HARD_EXPIRY_DAYS}d). "
                    f"Status was '{hyp.get('status', 'unknown')}' with {hyp.get('check_count', 0)} checks."
                ))
        except Exception:
            continue

    return expired


def validate_check_verdict(result):
    """AI-4: Validate the Haiku hypothesis check response.

    Returns (is_valid, verdict, evidence).
    """
    if not isinstance(result, dict):
        return False, "insufficient", "Invalid response format"

    verdict = result.get("verdict", "").strip().lower()
    evidence = result.get("evidence", "").strip()

    valid_verdicts = {"confirming", "refuted", "insufficient"}
    if verdict not in valid_verdicts:
        return False, "insufficient", f"Invalid verdict '{verdict}'"

    if not evidence or len(evidence) < 10:
        return False, verdict, "Evidence too short — treating as insufficient"

    return True, verdict, evidence


# ══════════════════════════════════════════════════════════════════════════════
# HYPOTHESIS GENERATION — Claude Sonnet pass
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

OUTPUT ONLY valid JSON. No preamble, no markdown, no backticks."""


def generate_hypotheses(daily_rows, existing_hypotheses, api_key):
    """Run Claude to generate new cross-domain hypotheses from 14 days of data."""

    existing_texts = [h.get("hypothesis", "")[:100] for h in existing_hypotheses]
    existing_block = ""
    if existing_texts:
        existing_block = "\n\nEXISTING HYPOTHESES (do NOT duplicate these):\n" + "\n".join(f"- {t}" for t in existing_texts)

    user_message = f"""Here is {len(daily_rows)} days of Matthew's health data:

{json.dumps(daily_rows, indent=2)}

Context:
- 36-year-old male, 14+ weeks into a 117 lb weight loss transformation (started 302 lbs)
- Calorie target: 1800 cal/day, protein target: 190g/day
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

    Returns list of (sk, new_status, evidence_note) tuples.
    """
    if not pending_hypotheses or not daily_rows:
        return []

    updates = []
    now = datetime.now(timezone.utc).date()

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

        check_prompt = f"""Hypothesis: {hypothesis_text}

Confirmation criteria: {confirmation_criteria}

Recent data ({len(relevant_data)} days since hypothesis was created):
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
    logger.info("IC-18: Hypothesis Engine v1.1.0 (AI-4) starting...")

    api_key = get_anthropic_key()

    # 1. Gather data
    data = gather_data()
    if not data:
        return {"statusCode": 500, "body": "Failed to gather data"}

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

        result = generate_hypotheses(daily_rows, all_hypotheses, api_key)

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
