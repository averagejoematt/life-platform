"""
coach_narrative_orchestrator.py — Coach Intelligence Phase 2: Narrative Orchestrator

The "showrunner" — an LLM planning step (Haiku) that runs before a coach generates
content. Reads all coach state, ensemble context, computation results, and narrative
arc, then produces a structured generation brief for the target coach.

Phase 2 target: sleep_coach (Dr. Lisa Park) — highest cross-domain influence.

Inputs (all DynamoDB + S3):
  - Target coach compressed state (COACH#sleep_coach / COMPRESSED#latest)
  - All other coaches' compressed states
  - Ensemble digest (ENSEMBLE#digest / most recent CYCLE#)
  - Influence graph (ENSEMBLE#influence_graph / CONFIG#v1)
  - Computation results (COACH#computation / most recent RESULTS#)
  - Narrative arc state (NARRATIVE#arc / STATE#current)
  - Target coach voice state (COACH#sleep_coach / VOICE#state)
  - Target coach open threads (COACH#sleep_coach / THREAD# where status=open)
  - Target coach active predictions (COACH#sleep_coach / PREDICTION# where status in pending/confirming)

Output:
  - Generation brief JSON (returned + cached to COACH#sleep_coach / BRIEF#{date})

Schedule: Invoked by email generation pipeline, pre-generation step.

v1.0.0 — 2026-04-06 (Coach Intelligence Phase 2)
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3

# Structured logger
try:
    from platform_logger import get_logger
    logger = get_logger("coach-narrative-orchestrator")
except ImportError:
    logger = logging.getLogger("coach-narrative-orchestrator")
    logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# Phase 2 target coach — will be parameterized in Phase 3
TARGET_COACH = os.environ.get("TARGET_COACH", "sleep_coach")

# All coach IDs in the system
ALL_COACH_IDS = [
    "sleep_coach", "training_coach", "nutrition_coach", "mind_coach",
    "physical_coach", "glucose_coach", "labs_coach", "explorer_coach",
]

# CloudWatch metrics
_cw = boto3.client("cloudwatch", region_name=REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "coach-narrative-orchestrator")
_CW_NAMESPACE = "LifePlatform/AI"

# Backoff delays between retry attempts (seconds)
_BACKOFF_DELAYS = [5, 15, 45]
_MAX_ATTEMPTS = len(_BACKOFF_DELAYS) + 1
_RETRYABLE_CODES = frozenset([429, 500, 502, 503, 504, 529])

# AWS clients
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# ══════════════════════════════════════════════════════════════════════════════
# SECRET CACHING
# ══════════════════════════════════════════════════════════════════════════════

_api_key_cache = {"key": None, "ts": 0}
_API_KEY_TTL = 900  # 15 minutes


def _get_api_key():
    """Read Anthropic API key from Secrets Manager with in-memory caching."""
    now = time.time()
    if _api_key_cache["key"] and (now - _api_key_cache["ts"]) < _API_KEY_TTL:
        return _api_key_cache["key"]

    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
    try:
        val = secrets.get_secret_value(SecretId=secret_name)
        data = json.loads(val["SecretString"])
        key = data.get("ANTHROPIC_API_KEY") or data.get("anthropic_api_key")
        if not key:
            raise ValueError("No anthropic_api_key found in secret")
        _api_key_cache["key"] = key
        _api_key_cache["ts"] = now
        logger.debug("API key fetched from Secrets Manager (cache miss)")
        return key
    except Exception as e:
        logger.error("Failed to get Anthropic API key: %s", e)
        raise


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _decimal_to_float(obj):
    """Recursively convert DynamoDB Decimals to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(v) for v in obj]
    return obj


def _float_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB writes."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(v) for v in obj]
    return obj


def _emit_token_metrics(input_tokens, output_tokens):
    """Emit per-Lambda token usage to CloudWatch (non-fatal)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AnthropicInputTokens",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": input_tokens, "Unit": "Count",
                },
                {
                    "MetricName": "AnthropicOutputTokens",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": output_tokens, "Unit": "Count",
                },
            ],
        )
    except Exception as e:
        logger.warning("CloudWatch token metric emit failed (non-fatal): %s", e)


def _emit_failure_metric():
    """Emit API failure metric to CloudWatch (non-fatal)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[{
                "MetricName": "AnthropicAPIFailure",
                "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                "Value": 1, "Unit": "Count",
            }],
        )
    except Exception as e:
        logger.warning("CloudWatch failure metric emit failed (non-fatal): %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# ANTHROPIC API CALL
# ══════════════════════════════════════════════════════════════════════════════

def _call_haiku(system, user_message, max_tokens=2000, temperature=0.3):
    """Call Anthropic Haiku with exponential backoff + CloudWatch metrics.

    Returns parsed JSON dict if the response is valid JSON, otherwise raw text.
    Raises on final failure after all retry attempts.
    """
    api_key = _get_api_key()

    body = {
        "model": AI_MODEL_HAIKU,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        body["system"] = system

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        ANTHROPIC_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
                usage = resp.get("usage", {})
                if usage:
                    _emit_token_metrics(
                        usage.get("input_tokens", 0),
                        usage.get("output_tokens", 0),
                    )
                text = resp["content"][0]["text"].strip()
                # Try to parse as JSON
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    # Try extracting JSON from markdown code block
                    if "```json" in text:
                        start = text.index("```json") + 7
                        end = text.index("```", start)
                        return json.loads(text[start:end].strip())
                    elif "```" in text:
                        start = text.index("```") + 3
                        end = text.index("```", start)
                        return json.loads(text[start:end].strip())
                    return text

        except urllib.error.HTTPError as e:
            logger.warning("Anthropic HTTP %d attempt %d/%d", e.code, attempt, _MAX_ATTEMPTS)
            if e.code in _RETRYABLE_CODES and attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                logger.info("Retrying in %ds...", delay)
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise

        except urllib.error.URLError as e:
            logger.warning("Anthropic network error attempt %d/%d: %s", attempt, _MAX_ATTEMPTS, e)
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                logger.info("Retrying in %ds...", delay)
                time.sleep(delay)
            else:
                _emit_failure_metric()
                raise


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMODB READS
# ══════════════════════════════════════════════════════════════════════════════

def _get_item(pk, sk):
    """Get a single DynamoDB item. Returns None if not found or on error."""
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _decimal_to_float(item) if item else None
    except Exception as e:
        logger.warning("get_item(%s, %s) failed: %s", pk, sk, e)
        return None


def _query_begins_with(pk, sk_prefix, scan_forward=True):
    """Query DynamoDB for items with SK beginning with a prefix."""
    from boto3.dynamodb.conditions import Key
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            ScanIndexForward=scan_forward,
        )
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.warning("query_begins_with(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


def _query_latest(pk, sk_prefix):
    """Query for the most recent item matching a SK prefix (descending, limit 1)."""
    from boto3.dynamodb.conditions import Key
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return _decimal_to_float(items[0]) if items else None
    except Exception as e:
        logger.warning("query_latest(%s, %s) failed: %s", pk, sk_prefix, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# STATE GATHERING
# ══════════════════════════════════════════════════════════════════════════════

def _gather_all_state(coach_id):
    """Gather all state needed for the orchestrator's generation brief.

    Returns a dict of context components, with sensible defaults for missing state.
    Designed to be resilient — early in the experiment, most state will be empty.
    """
    logger.info("Gathering state for coach: %s", coach_id)
    coach_pk = f"COACH#{coach_id}"

    # 1. Target coach compressed state
    target_compressed = _get_item(coach_pk, "COMPRESSED#latest")
    if not target_compressed:
        logger.info("No compressed state for %s — using empty default", coach_id)
        target_compressed = {
            "coach_id": coach_id,
            "summary": "No prior outputs yet. This is the coach's first generation cycle.",
            "key_themes": [],
            "open_threads": [],
            "active_predictions": [],
            "confidence_state": {},
        }

    # 2. All other coaches' compressed states (for cross-coach context)
    other_compressed = {}
    for cid in ALL_COACH_IDS:
        if cid == coach_id:
            continue
        state = _get_item(f"COACH#{cid}", "COMPRESSED#latest")
        if state:
            other_compressed[cid] = state

    # 3. Ensemble digest (most recent CYCLE#)
    ensemble_digest = _query_latest("ENSEMBLE#digest", "CYCLE#")
    if not ensemble_digest:
        logger.info("No ensemble digest found — using empty default")
        ensemble_digest = {
            "coach_summaries": [],
            "active_disagreements": [],
            "note": "No ensemble digest yet — first generation cycle.",
        }

    # 4. Influence graph
    influence_graph = _get_item("ENSEMBLE#influence_graph", "CONFIG#v1")
    if not influence_graph:
        logger.info("No influence graph in DynamoDB — attempting S3 fallback")
        try:
            obj = s3.get_object(
                Bucket=S3_BUCKET,
                Key="config/coaches/influence_graph.json",
            )
            influence_graph = json.loads(obj["Body"].read())
        except Exception as e:
            logger.warning("Influence graph S3 fallback failed: %s", e)
            influence_graph = {"weights": {}, "notes": "Influence graph not yet loaded."}

    # 5. Computation results (most recent RESULTS#)
    computation_results = _query_latest("COACH#computation", "RESULTS#")
    if not computation_results:
        logger.info("No computation results found — using empty default")
        computation_results = {
            "trends": {},
            "regression_to_mean_warnings": [],
            "seasonal_flags": [],
            "statistical_notes": [],
            "note": "No computation results yet — deterministic engine has not run.",
        }

    # 6. Narrative arc state
    narrative_arc = _get_item("NARRATIVE#arc", "STATE#current")
    if not narrative_arc:
        logger.info("No narrative arc state — defaulting to early_baseline")
        narrative_arc = {
            "current_phase": "early_baseline",
            "phase_started": "2026-04-01",
            "journey_day": 6,
            "arc_history": [],
            "note": "Day 6 of experiment — deep in early baseline.",
        }

    # 7. Target coach voice state
    voice_state = _get_item(coach_pk, "VOICE#state")
    if not voice_state:
        logger.info("No voice state for %s — using empty default", coach_id)
        voice_state = {
            "recent_openings": [],
            "overused_patterns": [],
            "signature_patterns_to_reinforce": [],
            "anti_patterns": [],
            "note": "No voice history yet — first generation.",
        }

    # 8. Open threads (filter status=open)
    all_threads = _query_begins_with(coach_pk, "THREAD#")
    open_threads = [t for t in all_threads if t.get("status") == "open"]
    if not open_threads:
        logger.info("No open threads for %s", coach_id)

    # 9. Active predictions (filter status in pending/confirming)
    all_predictions = _query_begins_with(coach_pk, "PREDICTION#")
    active_predictions = [
        p for p in all_predictions
        if p.get("status") in ("pending", "confirming")
    ]
    if not active_predictions:
        logger.info("No active predictions for %s", coach_id)

    return {
        "target_compressed": target_compressed,
        "other_compressed": other_compressed,
        "ensemble_digest": ensemble_digest,
        "influence_graph": influence_graph,
        "computation_results": computation_results,
        "narrative_arc": narrative_arc,
        "voice_state": voice_state,
        "open_threads": open_threads,
        "active_predictions": active_predictions,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = (
    "You are the Narrative Orchestrator — the 'showrunner' for a team of "
    "AI health coaches. Your job is to produce a structured generation brief "
    "that will guide one specific coach's next output.\n\n"
    "You are NOT the coach. You do not write the coaching content. You plan "
    "what the coach should write about, which threads to reference, what "
    "cross-coach context to incorporate, and what voice/structural guidance "
    "to follow.\n\n"
    "## Your Responsibilities\n\n"
    "1. **Thread management**: Identify which open threads the coach should "
    "address, which to leave dormant, and whether new threads should be "
    "opened based on computation results.\n\n"
    "2. **Cross-coach context**: Determine which other coaches' concerns, "
    "recommendations, or disagreements are relevant to this coach's domain. "
    "Weight by influence graph.\n\n"
    "3. **Prediction accountability**: Flag predictions that need addressing "
    "— confirmed, refuted, or approaching their evaluation window.\n\n"
    "4. **Narrative beat**: Set the narrative tone for this output based on "
    "the journey phase, recent arc history, and current data state.\n\n"
    "5. **Voice guidance**: Based on the coach's voice state, recommend "
    "opening types (avoiding overused patterns), structural approaches, and "
    "any anti-patterns to watch for.\n\n"
    "6. **Decision class ceiling**: Based on available evidence and data "
    "maturity, set the maximum decision class "
    "(observational/directional/interventional) the coach should use.\n\n"
    "7. **Computation context**: Package relevant trend data, statistical "
    "flags, and regression-to-mean warnings for the coach.\n\n"
    "## Statistical Guardrails (ENFORCE THESE)\n\n"
    '- <7 days of data: "Observational only — no directional claims"\n'
    '- <14 days of data: "Use preliminary framing"\n'
    '- Regression-to-mean warnings: "Do not claim intervention effect"\n'
    '- Autocorrelation flags: "Likely autocorrelation, not independent signal"\n'
    '- N=1 constraint: Always. "Unusual for you" only, never "unusual."\n\n'
    "## Output Format\n\n"
    "Return ONLY valid JSON matching the generation_brief schema. "
    "No markdown, no explanation, no preamble."
)


def _build_user_message(state, coach_id, today):
    """Build the user message with all gathered context for the orchestrator."""
    parts = [
        f"## Target Coach: {coach_id}",
        f"## Date: {today}",
        "",
        "## Target Coach Compressed State",
        json.dumps(state["target_compressed"], indent=2, default=str),
        "",
    ]

    # Other coaches' states
    if state["other_compressed"]:
        parts.append("## Other Coaches' Compressed States")
        for cid, cstate in state["other_compressed"].items():
            parts.append(f"### {cid}")
            parts.append(json.dumps(cstate, indent=2, default=str))
        parts.append("")
    else:
        parts.append("## Other Coaches: No compressed states available yet (first cycle).")
        parts.append("")

    # Ensemble digest
    parts.append("## Ensemble Digest (Most Recent Cycle)")
    parts.append(json.dumps(state["ensemble_digest"], indent=2, default=str))
    parts.append("")

    # Influence graph
    parts.append("## Cross-Coach Influence Graph")
    parts.append(json.dumps(state["influence_graph"], indent=2, default=str))
    parts.append("")

    # Computation results
    parts.append("## Computation Results Package")
    parts.append(json.dumps(state["computation_results"], indent=2, default=str))
    parts.append("")

    # Narrative arc
    parts.append("## Narrative Arc State")
    parts.append(json.dumps(state["narrative_arc"], indent=2, default=str))
    parts.append("")

    # Voice state
    parts.append("## Coach Voice State")
    parts.append(json.dumps(state["voice_state"], indent=2, default=str))
    parts.append("")

    # Open threads
    parts.append("## Open Threads")
    if state["open_threads"]:
        parts.append(json.dumps(state["open_threads"], indent=2, default=str))
    else:
        parts.append("No open threads — this is the coach's first cycle or all threads are resolved.")
    parts.append("")

    # Active predictions
    parts.append("## Active Predictions")
    if state["active_predictions"]:
        parts.append(json.dumps(state["active_predictions"], indent=2, default=str))
    else:
        parts.append("No active predictions — coach has not yet made formal predictions.")
    parts.append("")

    parts.append("## Instructions")
    parts.append(
        f"Produce a generation brief for {coach_id}. Return ONLY the JSON object "
        "with the schema: {coach_id, generation_brief: {open_threads, cross_coach_context, "
        "predictions_to_address, narrative_beat, journey_phase, periodization_note, "
        "voice_guidance: {avoid_openings, suggested_opening, structural_note}, "
        "decision_class_ceiling, evidence_note, seasonal_flags, computation_outputs}}."
    )

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# BRIEF CACHING
# ══════════════════════════════════════════════════════════════════════════════

def _cache_brief(coach_id, brief, today):
    """Cache the generation brief to DynamoDB for fallback use."""
    try:
        item = _float_to_decimal({
            "pk": f"COACH#{coach_id}",
            "sk": f"BRIEF#{today}",
            "brief": brief,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        table.put_item(Item=item)
        logger.info("Cached generation brief for %s at BRIEF#%s", coach_id, today)
    except Exception as e:
        logger.error("Failed to cache brief for %s: %s", coach_id, e)


def _load_fallback_brief(coach_id):
    """Load the most recent cached brief if the LLM call fails."""
    brief = _query_latest(f"COACH#{coach_id}", "BRIEF#")
    if brief:
        logger.info("Loaded fallback brief for %s from %s", coach_id, brief.get("sk", "unknown"))
        return brief.get("brief")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT BRIEF
# ══════════════════════════════════════════════════════════════════════════════

def _build_default_brief(coach_id, today):
    """Build a safe default brief when LLM and fallback both fail.

    Conservative — observational only, no bold claims.
    """
    return {
        "coach_id": coach_id,
        "generation_brief": {
            "open_threads": [],
            "cross_coach_context": [],
            "predictions_to_address": [],
            "narrative_beat": "early_baseline",
            "journey_phase": "early_baseline",
            "periodization_note": (
                "Month 1 — building baseline. Conservative observation appropriate. "
                "Insufficient data history for trend analysis or directional claims."
            ),
            "voice_guidance": {
                "avoid_openings": [],
                "suggested_opening": "lead_with_data",
                "structural_note": (
                    "First generation — establish voice and begin observing. "
                    "No prior outputs to callback to."
                ),
            },
            "decision_class_ceiling": "observational",
            "evidence_note": (
                "Very early in data collection (<14 days). "
                "All observations are preliminary. No directional claims warranted."
            ),
            "seasonal_flags": [],
            "computation_outputs": {
                "trends": {},
                "regression_to_mean_warnings": [],
            },
            "_fallback": True,
            "_generated_at": today,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Produce a generation brief for the target coach.

    Event fields (all optional — defaults to TARGET_COACH env var):
      - coach_id: Override target coach ID
      - date: Override date (YYYY-MM-DD format, for testing/backfill)

    Returns the generation brief JSON.
    """
    coach_id = event.get("coach_id", TARGET_COACH)
    today = event.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    logger.info("Starting narrative orchestrator for %s on %s", coach_id, today)

    # Gather all state
    state = _gather_all_state(coach_id)

    # Build the orchestrator prompt
    user_message = _build_user_message(state, coach_id, today)

    # Call Haiku to produce the generation brief
    try:
        result = _call_haiku(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=2000,
            temperature=0.3,
        )

        # Validate that we got a dict with the expected structure
        if isinstance(result, dict):
            # Ensure coach_id is set
            if "coach_id" not in result:
                result["coach_id"] = coach_id
            # Ensure generation_brief wrapper exists
            if "generation_brief" not in result:
                # The LLM might have returned the brief contents directly
                result = {"coach_id": coach_id, "generation_brief": result}

            brief = result
            logger.info(
                "Generation brief produced for %s — narrative_beat: %s, ceiling: %s",
                coach_id,
                brief.get("generation_brief", {}).get("narrative_beat", "unknown"),
                brief.get("generation_brief", {}).get("decision_class_ceiling", "unknown"),
            )
        else:
            logger.warning(
                "LLM returned non-dict response for %s — attempting fallback", coach_id
            )
            brief = _load_fallback_brief(coach_id)
            if not brief:
                brief = _build_default_brief(coach_id, today)

    except Exception as e:
        logger.error("LLM call failed for %s: %s — attempting fallback", coach_id, e)
        brief = _load_fallback_brief(coach_id)
        if not brief:
            logger.warning("No fallback brief available — using default for %s", coach_id)
            brief = _build_default_brief(coach_id, today)

    # Cache the brief for fallback use
    _cache_brief(coach_id, brief, today)

    logger.info("Narrative orchestrator complete for %s", coach_id)
    return brief
