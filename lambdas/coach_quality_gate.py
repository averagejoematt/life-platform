"""
coach_quality_gate.py — Coach Intelligence: Post-Generation Quality Gate

Optional Haiku-based check that validates coach output quality after generation.
Advisory only — never blocks output, just flags issues for the caller.

Checks:
  1. Anti-pattern violations — output vs voice spec phrase_blacklist & structural_blacklist
  2. Decision class compliance — does the output exceed the evidence ceiling?
  3. Voice distinctiveness — does the output match the coach's structural signature?
  4. Cross-coach similarity — does this output sound too similar to other coaches?

Returns a quality report with pass/fail, score, and detailed findings.

DynamoDB patterns: reads only (no writes)
  PK=COACH#{coach_id}  SK=VOICE#state
  PK=COACH#{coach_id}  SK=OUTPUT#*  (recent outputs for cross-coach comparison)

S3: config/coaches/{coach_id}.json (voice spec)

v1.0.0 — 2026-04-06 (Coach Intelligence)
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from decimal import Decimal

import boto3

# Structured logger
try:
    from platform_logger import get_logger
    logger = get_logger("coach-quality-gate")
except ImportError:
    logger = logging.getLogger("coach-quality-gate")
    logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# Quality gate thresholds
PASS_SCORE_THRESHOLD = 60  # Score below this = failed
VOICE_DISTINCTIVENESS_MINIMUM = 40  # Below this = flagged as generic

# CloudWatch metrics
_cw = boto3.client("cloudwatch", region_name=REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "coach-quality-gate")
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

    secret_name = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")
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

def _call_haiku(system, user_message, max_tokens=800, temperature=0.1):
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
# DYNAMODB / S3 OPERATIONS
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


def _query_begins_with(pk, sk_prefix, scan_forward=True, limit=None):
    """Query DynamoDB for items with SK beginning with a prefix."""
    from boto3.dynamodb.conditions import Key
    try:
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            "ScanIndexForward": scan_forward,
        }
        if limit:
            kwargs["Limit"] = limit

        items = []
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if limit and len(items) >= limit:
                items = items[:limit]
                break
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        return _decimal_to_float(items)
    except Exception as e:
        logger.warning("query_begins_with(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


def _load_voice_spec(coach_id):
    """Load the coach's voice specification from S3.

    Falls back to an empty spec if the file doesn't exist.
    """
    try:
        obj = s3.get_object(
            Bucket=S3_BUCKET,
            Key=f"config/coaches/{coach_id}.json",
        )
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        logger.info("No voice spec found for %s in S3 — using empty default", coach_id)
        return {}
    except Exception as e:
        logger.warning("Failed to load voice spec for %s: %s — using empty default", coach_id, e)
        return {}


def _fetch_other_coaches_recent_outputs(coach_id, other_coach_ids=None):
    """Fetch the most recent output from other coaches for cross-coach comparison.

    Returns a dict of {coach_id: output_content_preview}.
    """
    all_coach_ids = [
        "sleep_coach", "nutrition_coach", "training_coach", "mind_coach",
        "physical_coach", "glucose_coach", "labs_coach", "explorer_coach",
    ]

    if other_coach_ids:
        compare_ids = other_coach_ids
    else:
        compare_ids = [c for c in all_coach_ids if c != coach_id]

    other_outputs = {}
    for other_id in compare_ids:
        outputs = _query_begins_with(
            f"COACH#{other_id}", "OUTPUT#",
            scan_forward=False,
            limit=1,
        )
        if outputs:
            content = outputs[0].get("content", "")
            # Truncate for comparison — 500 chars is enough for similarity detection
            other_outputs[other_id] = content[:500] if content else ""

    return other_outputs


# ══════════════════════════════════════════════════════════════════════════════
# QUALITY GATE PROMPT
# ══════════════════════════════════════════════════════════════════════════════

QUALITY_GATE_SYSTEM_PROMPT = (
    "You are a quality gate for an AI coaching system. Your job is to evaluate "
    "a coach's generated output for quality issues. You are strict but fair — "
    "flag real problems, not stylistic preferences.\n\n"
    "## Evaluation Criteria\n\n"
    "### 1. Anti-Pattern Violations (weight: 30%)\n"
    "Check the output against the provided phrase_blacklist and "
    "structural_blacklist. Each violation is a concrete finding.\n\n"
    "### 2. Decision Class Compliance (weight: 25%)\n"
    "Check whether the output exceeds the evidence ceiling from the "
    "generation brief. A coach should not make interventional recommendations "
    "if the brief only supports observational claims. Decision classes in "
    "ascending evidence order:\n"
    "  - observational: 'I notice...', 'watching...'\n"
    "  - directional: 'I suggest...', 'consider...'\n"
    "  - interventional: 'change...', 'stop...', 'start...'\n\n"
    "### 3. Voice Distinctiveness (weight: 25%)\n"
    "Does the output sound like THIS specific coach or is it generic? "
    "Check for:\n"
    "  - Domain-specific vocabulary and framing\n"
    "  - Structural patterns matching the coach's voice spec\n"
    "  - Opening approach variety (not repeating the same structure)\n"
    "  - Personality and perspective consistent with the coach persona\n\n"
    "### 4. Cross-Coach Similarity (weight: 20%)\n"
    "If other coaches' recent outputs are provided, check if this output "
    "sounds too similar. Coaches should have distinct voices and perspectives. "
    "Flag if:\n"
    "  - Phrasing patterns match another coach closely\n"
    "  - The opening structure mirrors another coach's recent opening\n"
    "  - Recommendations overlap without acknowledging the other coach\n\n"
    "## Output Format\n"
    "Return ONLY valid JSON:\n"
    "{\n"
    '  "passed": true/false,\n'
    '  "score": 0-100,\n'
    '  "anti_pattern_violations": [\n'
    '    {"phrase": "the forbidden phrase found", "context": "where it appears"}\n'
    "  ],\n"
    '  "decision_class_violations": [\n'
    '    {"expected_max": "observational", "found": "interventional", '
    '"excerpt": "the offending text"}\n'
    "  ],\n"
    '  "voice_distinctiveness_score": 0-100,\n'
    '  "cross_coach_similarity_flags": [\n'
    '    {"similar_to": "coach_id", "reason": "why they sound similar"}\n'
    "  ],\n"
    '  "suggestions": ["actionable suggestions for improvement"]\n'
    "}\n"
)


def _build_quality_gate_message(coach_id, output_text, voice_spec, generation_brief,
                                other_outputs=None):
    """Build the user message for the quality gate LLM call."""
    parts = [
        f"## Coach: {coach_id}",
        "",
        "## Output to Evaluate",
        "---",
        output_text,
        "---",
        "",
    ]

    # Voice spec anti-patterns
    anti_patterns = voice_spec.get("anti_pattern_detection", {})
    if anti_patterns:
        parts.append("## Anti-Pattern Checklist")
        phrase_bl = anti_patterns.get("phrase_blacklist", [])
        if phrase_bl:
            parts.append("### Forbidden Phrases")
            for phrase in phrase_bl:
                parts.append(f'  - "{phrase}"')
        structural_bl = anti_patterns.get("structural_blacklist", [])
        if structural_bl:
            parts.append("### Forbidden Structural Patterns")
            for pattern in structural_bl:
                parts.append(f'  - "{pattern}"')
        parts.append("")

    # Voice spec structural signature
    voice_sig = voice_spec.get("structural_signature", {})
    if voice_sig:
        parts.append("## Expected Voice Signature")
        parts.append(json.dumps(voice_sig, indent=2))
        parts.append("")

    # Voice spec personality / perspective
    persona = voice_spec.get("persona", {})
    if persona:
        parts.append("## Coach Persona")
        parts.append(json.dumps(persona, indent=2))
        parts.append("")

    # Generation brief — for decision class ceiling
    if generation_brief:
        parts.append("## Generation Brief (evidence ceiling)")
        if isinstance(generation_brief, dict):
            # Extract decision class ceiling if available
            ceiling = generation_brief.get("decision_class_ceiling")
            if ceiling:
                parts.append(f"  Decision class ceiling: {ceiling}")
            # Include data quality context
            data_quality = generation_brief.get("data_quality", {})
            if data_quality:
                parts.append(f"  Data quality: {json.dumps(data_quality)}")
            # Include guardrails
            guardrails = generation_brief.get("guardrails", {})
            if guardrails:
                parts.append(f"  Guardrails: {json.dumps(guardrails)}")
        else:
            parts.append(f"  {generation_brief}")
        parts.append("")

    # Other coaches' recent outputs for cross-coach comparison
    if other_outputs:
        parts.append("## Other Coaches' Recent Outputs (for similarity check)")
        for other_id, other_content in other_outputs.items():
            if other_content:
                parts.append(f"\n### {other_id}")
                parts.append(f"  {other_content}")
        parts.append("")

    parts.append(
        "Evaluate the output above against all four criteria. "
        "Return ONLY valid JSON with the quality report."
    )

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# QUALITY GATE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def _build_fallback_report(coach_id, error_msg):
    """Build a permissive fallback report when the LLM call fails.

    The quality gate is advisory — a failure to evaluate should not block output.
    Returns a passing report with a note about the evaluation failure.
    """
    return {
        "passed": True,
        "score": 50,
        "anti_pattern_violations": [],
        "decision_class_violations": [],
        "voice_distinctiveness_score": 50,
        "cross_coach_similarity_flags": [],
        "suggestions": [f"Quality gate evaluation failed ({error_msg}) — output passed by default"],
        "_fallback": True,
    }


def _run_quality_gate(coach_id, output_text, voice_spec, generation_brief,
                      other_outputs=None):
    """Run the quality gate check via Haiku.

    Returns the quality report dict.
    """
    user_message = _build_quality_gate_message(
        coach_id, output_text, voice_spec, generation_brief, other_outputs,
    )

    try:
        result = _call_haiku(
            system=QUALITY_GATE_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=800,
            temperature=0.1,
        )

        if not isinstance(result, dict):
            logger.warning(
                "Quality gate LLM returned non-dict for %s — using fallback", coach_id
            )
            return _build_fallback_report(coach_id, "LLM returned non-JSON")

        # Ensure required fields with defaults
        result.setdefault("passed", True)
        result.setdefault("score", 50)
        result.setdefault("anti_pattern_violations", [])
        result.setdefault("decision_class_violations", [])
        result.setdefault("voice_distinctiveness_score", 50)
        result.setdefault("cross_coach_similarity_flags", [])
        result.setdefault("suggestions", [])

        # Apply pass/fail logic based on score and violations
        # Even if LLM said "passed", override based on thresholds
        if isinstance(result["score"], (int, float)):
            if result["score"] < PASS_SCORE_THRESHOLD:
                result["passed"] = False
        if result.get("voice_distinctiveness_score", 100) < VOICE_DISTINCTIVENESS_MINIMUM:
            if "Voice distinctiveness below minimum threshold" not in result.get("suggestions", []):
                result["suggestions"].append("Voice distinctiveness below minimum threshold")

        logger.info(
            "Quality gate for %s: passed=%s, score=%s, violations=%d, "
            "voice_score=%s, similarity_flags=%d",
            coach_id,
            result["passed"],
            result["score"],
            len(result.get("anti_pattern_violations", []))
            + len(result.get("decision_class_violations", [])),
            result["voice_distinctiveness_score"],
            len(result.get("cross_coach_similarity_flags", [])),
        )

        return result

    except Exception as e:
        logger.error("Quality gate LLM call failed for %s: %s", coach_id, e)
        return _build_fallback_report(coach_id, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Post-generation quality gate for coach output.

    Required event fields:
      - coach_id: str — e.g. "sleep_coach"
      - output_text: str — the generated output text to evaluate

    Optional event fields:
      - voice_spec: dict — the coach's voice specification (if not provided,
        loaded from S3 at config/coaches/{coach_id}.json)
      - generation_brief: dict — the generation brief used to produce the output
        (used for decision class compliance checking)
      - other_coach_outputs: dict — {coach_id: output_text} for cross-coach
        similarity checking (if not provided, fetched from DynamoDB)
      - skip_cross_coach: bool — if true, skip cross-coach similarity check

    Returns the quality report dict. The quality gate is advisory — it never
    blocks output, just flags issues. If passed=false, the caller should
    consider regenerating or flagging for review.
    """
    try:
        coach_id = event.get("coach_id")
        output_text = event.get("output_text")

        if not coach_id:
            return {
                "statusCode": 400,
                "error": "Missing required field: coach_id",
                "passed": True,  # Don't block on missing input
            }
        if not output_text:
            return {
                "statusCode": 400,
                "error": "Missing required field: output_text",
                "passed": True,  # Don't block on missing input
            }

        logger.info(
            "coach-quality-gate START — coach=%s, text_length=%d",
            coach_id, len(output_text),
        )

        # Load voice spec — from event or S3
        voice_spec = event.get("voice_spec")
        if not voice_spec:
            voice_spec = _load_voice_spec(coach_id)

        # Generation brief — from event (optional)
        generation_brief = event.get("generation_brief")

        # Cross-coach comparison outputs
        skip_cross_coach = event.get("skip_cross_coach", False)
        other_outputs = None

        if not skip_cross_coach:
            other_outputs = event.get("other_coach_outputs")
            if not other_outputs:
                # Fetch recent outputs from other coaches
                other_outputs = _fetch_other_coaches_recent_outputs(coach_id)

        # Run the quality gate
        report = _run_quality_gate(
            coach_id, output_text, voice_spec, generation_brief, other_outputs,
        )

        logger.info(
            "coach-quality-gate COMPLETE — coach=%s, passed=%s, score=%s",
            coach_id, report.get("passed"), report.get("score"),
        )

        return {
            "statusCode": 200,
            "coach_id": coach_id,
            **report,
        }

    except Exception as e:
        logger.error("coach-quality-gate FAILED: %s", e, exc_info=True)
        # Quality gate failure should never block — return a permissive report
        return {
            "statusCode": 500,
            "error": str(e),
            "passed": True,
            "score": 0,
            "anti_pattern_violations": [],
            "decision_class_violations": [],
            "voice_distinctiveness_score": 0,
            "cross_coach_similarity_flags": [],
            "suggestions": [f"Quality gate crashed: {e}"],
        }
